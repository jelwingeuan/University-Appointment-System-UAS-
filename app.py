import calendar
import hmac
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import bcrypt
import click
from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename

from booking_service import BookingConflict, BookingError, InvalidTransition
from booking_service import create_booking as create_booking_record
from booking_service import slot_is_available, transition_appointment
from database import connect_database, init_schema


load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "jfif"}
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif"}


class User(UserMixin):
    def __init__(self, row):
        self.id = str(row["id"])
        self.username = row["username"]
        self.email = row["email"]
        self.role = row["role"]
        self.faculty = row["faculty"]
        self.phone_number = row["phone_number"]


def _environment_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def generate_recurrence(start, recurrence_end, repeat_type):
    if recurrence_end < start:
        raise ValueError("End date must not be before start date")
    if repeat_type not in {"", "weekly", "monthly"}:
        raise ValueError("Invalid recurrence type")
    if not repeat_type:
        return [start]

    values = []
    current = start
    anchor_day = start.day
    while current <= recurrence_end:
        values.append(current)
        if len(values) > 370:
            raise ValueError("Recurrence creates too many availability windows")
        if repeat_type == "weekly":
            current += timedelta(weeks=1)
        else:
            month = current.month + 1
            year = current.year
            if month == 13:
                month = 1
                year += 1
            day = min(anchor_day, calendar.monthrange(year, month)[1])
            current = current.replace(year=year, month=month, day=day)
    return values


def _safe_next_url(target):
    if not target:
        return None
    host = urlparse(request.host_url)
    resolved = urlparse(urljoin(request.host_url, target))
    return target if (resolved.scheme, resolved.netloc) == (host.scheme, host.netloc) else None


def _content_path(app):
    return Path(app.root_path) / "content.json"


def _load_content(app):
    with _content_path(app).open(encoding="utf-8") as handle:
        return json.load(handle)


def _save_content(app, content):
    with _content_path(app).open("w", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2)


def _database_path(app):
    return app.config["DATABASE_PATH"]


def _local_zone(app):
    return ZoneInfo(app.config["UNIVERSITY_TIMEZONE"])


def _local_to_utc(app, local_datetime):
    return local_datetime.replace(tzinfo=_local_zone(app)).astimezone(timezone.utc)


def _utc_to_local(app, value):
    return datetime.fromisoformat(value).astimezone(_local_zone(app))


def _appointment_view(app, row):
    start = _utc_to_local(app, row["starts_at"])
    end = _utc_to_local(app, row["ends_at"])
    result = dict(row)
    result["appointment_date"] = start.strftime("%Y-%m-%d")
    result["appointment_time"] = f"{start:%H:%M} - {end:%H:%M}"
    return result


def _valid_image(file):
    if not file or not file.filename or "." not in file.filename:
        return False
    extension = file.filename.rsplit(".", 1)[1].lower()
    return extension in ALLOWED_IMAGE_EXTENSIONS and file.mimetype in ALLOWED_IMAGE_TYPES


def create_app(test_config=None):
    application = Flask(__name__, static_folder="static")
    app_environment = os.getenv("APP_ENV", "production").strip().lower()
    application.config.from_mapping(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY"),
        DATABASE_PATH=os.getenv("DATABASE_PATH", str(Path(application.root_path) / "database.db")),
        UNIVERSITY_TIMEZONE=os.getenv("UNIVERSITY_TIMEZONE", "Asia/Kuala_Lumpur"),
        LECTURER_REGISTRATION_SECRET=os.getenv("LECTURER_REGISTRATION_SECRET"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_environment_flag(
            "SESSION_COOKIE_SECURE", app_environment == "production"
        ),
        DEBUG=app_environment != "production" and _environment_flag("FLASK_DEBUG"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        WTF_CSRF_TIME_LIMIT=3600,
        RATELIMIT_STORAGE_URI="memory://",
    )
    if test_config:
        application.config.update(test_config)
    secret_key = application.config.get("SECRET_KEY") or ""
    if not secret_key:
        raise RuntimeError("FLASK_SECRET_KEY is required")
    if not application.config.get("TESTING") and len(secret_key) < 32:
        raise RuntimeError("FLASK_SECRET_KEY must contain at least 32 characters")
    try:
        ZoneInfo(application.config["UNIVERSITY_TIMEZONE"])
    except Exception as exc:
        raise RuntimeError("UNIVERSITY_TIMEZONE is invalid") from exc

    upload_folder = Path(application.static_folder) / "faculty_pp"
    upload_folder.mkdir(parents=True, exist_ok=True)
    application.config["UPLOAD_FOLDER"] = str(upload_folder)

    login_manager.init_app(application)
    login_manager.login_view = "login"
    csrf.init_app(application)
    limiter.init_app(application)

    @application.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if application.config["SESSION_COOKIE_SECURE"] and not application.config.get("TESTING"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    @login_manager.user_loader
    def load_user(user_id):
        with connect_database(_database_path(application)) as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return User(row) if row else None

    @application.cli.command("init-db")
    def init_db_command():
        with connect_database(_database_path(application)) as connection:
            init_schema(connection)
        click.echo("Database schema initialized.")

    @application.cli.command("bootstrap-admin")
    def bootstrap_admin_command():
        email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        password = os.getenv("ADMIN_PASSWORD", "")
        if not email or len(password) < 12:
            raise click.ClickException("ADMIN_EMAIL and ADMIN_PASSWORD (12+ characters) are required")
        with connect_database(_database_path(application)) as connection:
            init_schema(connection)
            existing = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            password_hash = hash_password(password)
            if existing:
                connection.execute(
                    "UPDATE users SET role = 'admin', password = ? WHERE id = ?",
                    (password_hash, existing["id"]),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO users (role, faculty, username, email, phone_number, password)
                    VALUES ('admin', 'Administration', ?, ?, ?, ?)
                    """,
                    (
                        f"Administrator-{os.urandom(4).hex()}",
                        email,
                        f"admin-{os.urandom(6).hex()}",
                        password_hash,
                    ),
                )
        click.echo("Administrator account is ready.")

    @application.route("/")
    def home():
        return render_template("home.html", **_load_content(application))

    @application.route("/about")
    def about():
        return render_template("about.html")

    @application.route("/signup", methods=["GET", "POST"])
    @limiter.limit("10 per minute")
    def signup():
        if request.method == "POST":
            role = request.form.get("role", "")
            faculty = request.form.get("faculty", "").strip()
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            phone = request.form.get("phone_number", "").strip()
            password = request.form.get("password", "")
            confirmation = request.form.get("confirm_password", "")
            if role not in {"student", "teacher"}:
                flash("Please select a valid role", "error")
            elif not all((faculty, username, email, phone)):
                flash("All fields are required", "error")
            elif password != confirmation or len(password) < 8:
                flash("Passwords must match and contain at least 8 characters", "error")
            elif role == "student" and not email.endswith("@student.mmu.edu.my"):
                flash("Students must use an @student.mmu.edu.my email", "error")
            elif role == "teacher" and not email.endswith("@mmu.edu.my"):
                flash("Lecturers must use an @mmu.edu.my email", "error")
            elif role == "teacher" and (
                not application.config.get("LECTURER_REGISTRATION_SECRET")
                or not hmac.compare_digest(
                    request.form.get("pin", ""), application.config["LECTURER_REGISTRATION_SECRET"]
                )
            ):
                flash("Lecturer registration could not be verified", "error")
            else:
                try:
                    with connect_database(_database_path(application)) as connection:
                        connection.execute(
                            """
                            INSERT INTO users (role, faculty, username, email, phone_number, password)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (role, faculty, username, email, phone, hash_password(password)),
                        )
                    return redirect(url_for("login"))
                except sqlite3.IntegrityError:
                    flash("An account with those details already exists", "error")
            return redirect(url_for("signup"))

        with connect_database(_database_path(application)) as connection:
            faculties = connection.execute("SELECT faculty_name FROM facultyhub ORDER BY faculty_name").fetchall()
        return render_template("signup.html", faculties=faculties)

    @application.route("/login", methods=["GET", "POST"])
    @limiter.limit("5 per minute")
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            with connect_database(_database_path(application)) as connection:
                row = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            valid = bool(row and bcrypt.checkpw(password.encode("utf-8"), row["password"].encode("utf-8")))
            if not valid:
                flash("Invalid email or password", "error")
                return redirect(url_for("login"))
            user = User(row)
            login_user(user)
            destination = _safe_next_url(request.args.get("next"))
            if destination:
                return redirect(destination)
            return redirect(url_for("admin_dashboard") if user.role == "admin" else url_for("home"))
        return render_template("login.html")

    @application.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        session.clear()
        return redirect(url_for("home"))

    @application.route("/profile")
    @login_required
    def profile():
        return render_template(
            "profile.html",
            username=current_user.username,
            email=current_user.email,
            faculty=current_user.faculty,
            phone_number=current_user.phone_number,
            role=current_user.role,
        )

    @application.route("/update_user_info", methods=["POST"])
    @login_required
    def update_user():
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone_number", "").strip()
        valid_domain = (
            current_user.role == "student" and email.endswith("@student.mmu.edu.my")
        ) or (current_user.role == "teacher" and email.endswith("@mmu.edu.my"))
        if current_user.role == "admin":
            valid_domain = "@" in email and not any(character.isspace() for character in email)
        if not all((username, email, phone)) or not valid_domain:
            flash("Enter valid account details", "error")
            return redirect(url_for("profile"))
        try:
            with connect_database(_database_path(application)) as connection:
                connection.execute(
                    "UPDATE users SET username = ?, email = ?, phone_number = ? WHERE id = ?",
                    (username, email, phone, int(current_user.id)),
                )
            flash("User information updated successfully", "success")
        except sqlite3.IntegrityError:
            flash("Those account details are already in use", "error")
        return redirect(url_for("profile"))

    @application.route("/change_password", methods=["GET", "POST"])
    @login_required
    def change_password():
        if request.method == "GET":
            return render_template("changepassword.html")
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirmation = request.form.get("confirm_password", "")
        with connect_database(_database_path(application)) as connection:
            row = connection.execute("SELECT password FROM users WHERE id = ?", (current_user.id,)).fetchone()
            if (
                not row
                or not bcrypt.checkpw(current_password.encode(), row["password"].encode())
                or new_password != confirmation
                or len(new_password) < 8
            ):
                flash("Password change could not be completed", "error")
                return redirect(url_for("change_password"))
            connection.execute(
                "UPDATE users SET password = ? WHERE id = ?", (hash_password(new_password), current_user.id)
            )
        flash("Password updated", "success")
        return redirect(url_for("profile"))

    @application.route("/changepassword")
    @login_required
    def changepassword():
        return redirect(url_for("change_password"))

    @application.route("/appointment")
    @role_required("student")
    def appointment():
        return render_template("appointment.html")

    @application.route("/appointment2")
    @role_required("student")
    def appointment2():
        with connect_database(_database_path(application)) as connection:
            lecturers = connection.execute(
                "SELECT id, username FROM users WHERE role = 'teacher' ORDER BY username"
            ).fetchall()
        return render_template("appointment2.html", lecturers=lecturers)

    @application.route("/get_calendar_details", methods=["GET"])
    @role_required("student")
    def get_calendar_details():
        try:
            lecturer_id = int(request.args.get("lecturer", ""))
            selected_date = datetime.strptime(request.args.get("appointment_date", ""), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid lecturer or date"}), 400
        day_start = datetime.combine(selected_date, datetime.min.time(), _local_zone(application)).astimezone(timezone.utc)
        day_end = day_start + timedelta(days=1)
        with connect_database(_database_path(application)) as connection:
            windows = connection.execute(
                """
                SELECT * FROM availability
                WHERE lecturer_id = ? AND starts_at < ? AND ends_at > ?
                ORDER BY starts_at
                """,
                (lecturer_id, day_end.isoformat(), day_start.isoformat()),
            ).fetchall()
        slots = []
        for window in windows:
            current = datetime.fromisoformat(window["starts_at"])
            window_end = datetime.fromisoformat(window["ends_at"])
            duration = timedelta(minutes=window["slot_minutes"])
            while current + duration <= window_end:
                local_start = current.astimezone(_local_zone(application))
                local_end = (current + duration).astimezone(_local_zone(application))
                slots.append(
                    {
                        "availability_id": window["id"],
                        "starts_at": current.isoformat(),
                        "label": f"{local_start:%H:%M} - {local_end:%H:%M}",
                        "available": slot_is_available(_database_path(application), window["id"], current.isoformat()),
                    }
                )
                current += duration
        return jsonify({"slots": slots})

    @application.route("/check_availability", methods=["GET"])
    @role_required("student")
    def check_availability():
        try:
            availability_id = int(request.args.get("availability_id", ""))
            available = slot_is_available(
                _database_path(application), availability_id, request.args.get("starts_at")
            )
        except (TypeError, ValueError, BookingError):
            available = False
        return jsonify({"available": available})

    @application.route("/create_booking", methods=["POST"])
    @role_required("student")
    def create_booking():
        try:
            _, reference = create_booking_record(
                _database_path(application),
                int(current_user.id),
                int(request.form.get("availability_id", "")),
                request.form.get("slot_start"),
                request.form.get("purpose"),
            )
        except BookingConflict as exc:
            flash(str(exc), "error")
            return redirect(url_for("appointment2"))
        except (BookingError, TypeError, ValueError):
            flash("The selected appointment is invalid", "error")
            return redirect(url_for("appointment2"))
        session["last_booking_reference"] = reference
        flash("Booking created successfully", "success")
        return redirect(url_for("render_template_invoice", reference=reference))

    @application.route("/invoice")
    @role_required("student")
    def render_template_invoice():
        reference = request.args.get("reference") or session.get("last_booking_reference")
        with connect_database(_database_path(application)) as connection:
            row = connection.execute(
                """
                SELECT a.*, lecturer.username AS lecturer
                FROM appointments a
                JOIN users lecturer ON lecturer.id = a.lecturer_id
                WHERE a.public_reference = ? AND a.student_id = ?
                """,
                (reference, current_user.id),
            ).fetchone()
        if not row:
            abort(404)
        appointment_data = _appointment_view(application, row)
        invoice_row = [
            row["id"], current_user.username, row["student_id"], row["lecturer"],
            appointment_data["appointment_date"], appointment_data["appointment_time"], row["purpose"],
        ]
        return render_template(
            "invoice.html", username=current_user.username, email=current_user.email,
            faculty=current_user.faculty, role=current_user.role, appointment=invoice_row,
            booking_id=row["public_reference"],
        )

    @application.route("/bookinghistory")
    @role_required("student", "teacher")
    def user_booking_history():
        owner_column = "student_id" if current_user.role == "student" else "lecturer_id"
        other_join = "lecturer" if current_user.role == "student" else "student"
        query = f"""
            SELECT a.*, student.username AS student, lecturer.username AS lecturer
            FROM appointments a
            JOIN users student ON student.id = a.student_id
            JOIN users lecturer ON lecturer.id = a.lecturer_id
            WHERE a.{owner_column} = ? ORDER BY a.starts_at DESC
        """
        with connect_database(_database_path(application)) as connection:
            rows = connection.execute(query, (current_user.id,)).fetchall()
        appointments = [_appointment_view(application, row) for row in rows]
        return render_template(
            "booking_history.html", appointments=appointments, display_role=other_join, role=current_user.role
        )

    def status_change(target):
        try:
            transition_appointment(
                _database_path(application), int(request.form.get("id", "")),
                int(current_user.id), current_user.role, target,
            )
        except PermissionError:
            abort(403)
        except (BookingError, InvalidTransition, TypeError, ValueError):
            flash("That appointment status cannot be changed", "error")
        return redirect(url_for("user_booking_history"))

    @application.route("/cancel_booking", methods=["POST"])
    @role_required("student")
    def cancel_booking():
        return status_change("Cancelled")

    @application.route("/reject_booking", methods=["POST"])
    @role_required("teacher")
    def reject_booking():
        return status_change("Rejected")

    @application.route("/accept_booking", methods=["POST"])
    @role_required("teacher")
    def accept_booking():
        return status_change("Accepted")

    @application.route("/calendar_record", methods=["GET", "POST"])
    @role_required("teacher")
    def create_calendar():
        if request.method == "GET":
            return redirect(url_for("event"))
        try:
            start_date = datetime.strptime(request.form.get("event_date", ""), "%Y-%m-%d")
            end_date_value = datetime.strptime(request.form.get("end_date", ""), "%Y-%m-%d")
            start_time = datetime.strptime(request.form.get("start_time", ""), "%H:%M").time()
            end_time = datetime.strptime(request.form.get("end_time", ""), "%H:%M").time()
            slot_minutes = int(request.form.get("slot_size", ""))
            repeat_type = request.form.get("repeat_type", "")
            first_start = datetime.combine(start_date.date(), start_time)
            first_end = datetime.combine(start_date.date(), end_time)
            recurrence_end = datetime.combine(end_date_value.date(), start_time)
            if first_end <= first_start or slot_minutes <= 0 or first_end - first_start < timedelta(minutes=slot_minutes):
                raise ValueError
            occurrences = generate_recurrence(first_start, recurrence_end, repeat_type)
            with connect_database(_database_path(application)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                for occurrence in occurrences:
                    occurrence_end = occurrence + (first_end - first_start)
                    connection.execute(
                        """
                        INSERT INTO availability (lecturer_id, starts_at, ends_at, slot_minutes)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            current_user.id, _local_to_utc(application, occurrence).isoformat(),
                            _local_to_utc(application, occurrence_end).isoformat(), slot_minutes,
                        ),
                    )
                connection.commit()
        except (TypeError, ValueError, sqlite3.IntegrityError):
            flash("Availability details are invalid or duplicate an existing window", "error")
            return redirect(url_for("event"))
        return redirect(url_for("event"))

    @application.route("/calendar")
    @role_required("teacher")
    def event():
        return render_template("calendar.html")

    @application.route("/events")
    @role_required("teacher")
    def get_events():
        with connect_database(_database_path(application)) as connection:
            windows = connection.execute(
                "SELECT * FROM availability WHERE lecturer_id = ? ORDER BY starts_at", (current_user.id,)
            ).fetchall()
            appointments = connection.execute(
                """
                SELECT a.*, student.username AS student
                FROM appointments a JOIN users student ON student.id = a.student_id
                WHERE a.lecturer_id = ? AND a.status = 'Accepted' ORDER BY a.starts_at
                """,
                (current_user.id,),
            ).fetchall()
        events = [
            {
                "id": f"availability-{row['id']}", "title": "Consultation Hour",
                "start": row["starts_at"], "end": row["ends_at"],
                "extendedProps": {"availability_id": row["id"], "kind": "availability"},
            }
            for row in windows
        ]
        events.extend(
            {
                "id": f"appointment-{row['id']}", "title": f"Appointment with {row['student']}",
                "start": row["starts_at"], "end": row["ends_at"],
                "extendedProps": {"kind": "appointment"},
            }
            for row in appointments
        )
        return jsonify(events)

    @application.route("/delete_event", methods=["POST"])
    @role_required("teacher")
    def delete_event():
        try:
            availability_id = int(request.form.get("availability_id", ""))
            with connect_database(_database_path(application)) as connection:
                cursor = connection.execute(
                    "DELETE FROM availability WHERE id = ? AND lecturer_id = ?",
                    (availability_id, current_user.id),
                )
                if cursor.rowcount == 0:
                    abort(404)
            return jsonify({"status": "success"})
        except sqlite3.IntegrityError:
            return jsonify({"status": "error", "message": "Availability with bookings cannot be deleted"}), 409
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "Invalid availability"}), 400

    @application.route("/admin")
    @role_required("admin")
    def admin_dashboard():
        search = request.args.get("search", "").strip()
        parameters = [f"%{search}%"] * 5
        where = ""
        if search:
            where = "WHERE lecturer.username LIKE ? OR student.username LIKE ? OR a.starts_at LIKE ? OR a.purpose LIKE ? OR a.status LIKE ?"
        with connect_database(_database_path(application)) as connection:
            counts = {
                role: connection.execute("SELECT COUNT(*) FROM users WHERE role = ?", (role,)).fetchone()[0]
                for role in ("teacher", "student")
            }
            num_appointments = connection.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
            num_users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT a.*, student.username AS student, lecturer.username AS lecturer
                FROM appointments a JOIN users student ON student.id = a.student_id
                JOIN users lecturer ON lecturer.id = a.lecturer_id
                {where} ORDER BY a.starts_at DESC
                """,
                parameters if search else (),
            ).fetchall()
        appointments = []
        for row in rows:
            view = _appointment_view(application, row)
            appointments.append([
                row["lecturer"], row["student"], view["appointment_date"], row["purpose"],
                row["status"], view["appointment_time"], row["public_reference"],
            ])
        return render_template(
            "admin.html", appointments=appointments, num_teachers=counts["teacher"],
            num_students=counts["student"], num_appointments=num_appointments, num_users=num_users,
        )

    @application.route("/appointmentcontrol")
    @role_required("admin")
    def appointmentcontrol():
        search = request.args.get("search", "").strip()
        where = ""
        parameters = ()
        if search:
            where = "WHERE lecturer.username LIKE ? OR student.username LIKE ? OR a.starts_at LIKE ? OR a.purpose LIKE ? OR a.status LIKE ?"
            parameters = (f"%{search}%",) * 5
        with connect_database(_database_path(application)) as connection:
            rows = connection.execute(
                f"""
                SELECT a.*, lecturer.username AS lecturer
                FROM appointments a JOIN users lecturer ON lecturer.id = a.lecturer_id
                JOIN users student ON student.id = a.student_id
                {where} ORDER BY a.starts_at DESC
                """,
                parameters,
            ).fetchall()
        appointments = []
        for row in rows:
            view = _appointment_view(application, row)
            appointments.append([
                row["id"], row["lecturer"], row["student_id"], view["appointment_date"],
                row["purpose"], row["status"], view["appointment_time"],
            ])
        return render_template("appointment_control.html", appointments=appointments)

    @application.route("/delete_booking", methods=["POST"])
    @role_required("admin")
    def delete_booking():
        try:
            appointment_id = int(request.form.get("id", ""))
        except ValueError:
            abort(400)
        with connect_database(_database_path(application)) as connection:
            connection.execute("DELETE FROM appointments WHERE id = ?", (appointment_id,))
        return redirect(url_for("appointmentcontrol"))

    @application.route("/usercontrol")
    @role_required("admin")
    def usercontrol():
        search = request.args.get("search", "").strip()
        with connect_database(_database_path(application)) as connection:
            if search:
                users = connection.execute(
                    """
                    SELECT id, role, faculty, username, phone_number FROM users
                    WHERE username LIKE ? OR role LIKE ? OR faculty LIKE ? OR phone_number LIKE ?
                    ORDER BY username
                    """,
                    (f"%{search}%",) * 4,
                ).fetchall()
            else:
                users = connection.execute(
                    "SELECT id, role, faculty, username, phone_number FROM users ORDER BY username"
                ).fetchall()
        return render_template("usercontrol.html", users=users)

    @application.route("/delete_user", methods=["POST"])
    @role_required("admin")
    def delete_user_route():
        try:
            user_id = int(request.form.get("id", ""))
            if user_id == int(current_user.id):
                raise sqlite3.IntegrityError
            with connect_database(_database_path(application)) as connection:
                connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        except (ValueError, sqlite3.IntegrityError):
            flash("Users with related records, including the active administrator, cannot be deleted", "error")
        return redirect(url_for("usercontrol"))

    @application.route("/adminpageeditor", methods=["GET", "POST"])
    @role_required("admin")
    def admin_page_editor():
        content = _load_content(application)
        if request.method == "POST":
            uploaded = request.files.get("school_logo")
            filename = content.get("school_logo", "")
            if uploaded and uploaded.filename:
                if not _valid_image(uploaded):
                    flash("Upload a JPG, PNG, or GIF image", "error")
                    return redirect(url_for("admin_page_editor"))
                filename = secure_filename(uploaded.filename)
                uploaded.save(Path(application.config["UPLOAD_FOLDER"]) / filename)
            content.update(
                {
                    "home_content": request.form.get("home_content", "").strip(),
                    "school_name": request.form.get("school_name", "").strip(),
                    "school_tel": request.form.get("school_tel", "").strip(),
                    "school_email": request.form.get("school_email", "").strip(),
                    "school_logo": filename,
                }
            )
            _save_content(application, content)
            return redirect(url_for("admin_page_editor"))
        return render_template("adminpageeditor.html", **content)

    @application.route("/faculty")
    @role_required("admin")
    def faculty():
        with connect_database(_database_path(application)) as connection:
            faculties = connection.execute(
                "SELECT faculty_name, faculty_image FROM facultyhub ORDER BY faculty_name"
            ).fetchall()
            faculty_data = []
            for item in faculties:
                members = connection.execute(
                    "SELECT username, email, role FROM users WHERE faculty = ? ORDER BY username",
                    (item["faculty_name"],),
                ).fetchall()
                faculty_data.append(
                    {
                        "faculty_name": item["faculty_name"], "faculty_image": item["faculty_image"],
                        "lecturers": [row for row in members if row["role"] == "teacher"],
                        "students": [row for row in members if row["role"] == "student"],
                    }
                )
        return render_template("Faculty.html", faculty_info=faculty_data)

    @application.route("/createfacultyhub", methods=["GET", "POST"])
    @role_required("admin")
    def create_faculty_hub():
        if request.method == "POST":
            name = request.form.get("faculty_name", "").strip()
            uploaded = request.files.get("faculty_image")
            if not name or not _valid_image(uploaded):
                flash("A faculty name and valid image are required", "error")
                return redirect(url_for("create_faculty_hub"))
            filename = secure_filename(uploaded.filename)
            uploaded.save(Path(application.config["UPLOAD_FOLDER"]) / filename)
            try:
                with connect_database(_database_path(application)) as connection:
                    connection.execute(
                        "INSERT INTO facultyhub (faculty_name, faculty_image) VALUES (?, ?)",
                        (name, filename),
                    )
            except sqlite3.IntegrityError:
                flash("That faculty already exists", "error")
            return redirect(url_for("faculty"))
        with connect_database(_database_path(application)) as connection:
            faculty_hubs = connection.execute("SELECT * FROM facultyhub ORDER BY faculty_name").fetchall()
        return render_template("createfacultyhub.html", faculty_hubs=faculty_hubs)

    return application


app = create_app()


if __name__ == "__main__":
    app.run(debug=app.debug, port=6969)

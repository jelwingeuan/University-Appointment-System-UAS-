import hmac

import bcrypt
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import select

from .common import transaction
from .extensions import db, limiter
from .models import Faculty, User

bp = Blueprint("public", __name__)


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


@bp.get("/")
def home():
    import json

    with open(current_app.config["CONTENT_PATH"], encoding="utf-8") as handle:
        content = json.load(handle)
    return render_template("home.html", **content)


@bp.get("/about")
def about():
    return render_template("about.html")


@bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def signup():
    if request.method == "POST":
        role = request.form.get("role", "")
        faculty_name = request.form.get("faculty", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone_number", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")
        error = None
        if role not in {"student", "teacher"}:
            error = "Please select a valid role"
        elif not all((faculty_name, username, email, phone)):
            error = "All fields are required"
        elif password != confirmation or len(password) < 8:
            error = "Passwords must match and contain at least 8 characters"
        elif role == "student" and not email.endswith("@student.mmu.edu.my"):
            error = "Students must use an @student.mmu.edu.my email"
        elif role == "teacher" and not email.endswith("@mmu.edu.my"):
            error = "Lecturers must use an @mmu.edu.my email"
        elif role == "teacher":
            expected = current_app.config.get("LECTURER_REGISTRATION_SECRET", "")
            provided = request.form.get("pin", "")
            if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
                error = "Lecturer registration could not be verified"
        faculty = db.session.scalar(select(Faculty).where(Faculty.faculty_name == faculty_name))
        if not error and not faculty:
            error = "Select a valid faculty"
        if error:
            flash(error, "error")
            return redirect(url_for("public.signup"))
        try:
            with transaction() as session:
                session.add(
                    User(
                        role=role,
                        faculty_id=faculty.id,
                        username=username,
                        email=email,
                        phone_number=phone,
                        password=hash_password(password),
                    )
                )
            return redirect(url_for("auth.login"))
        except Exception as exc:
            from sqlalchemy.exc import IntegrityError

            if isinstance(exc, IntegrityError):
                flash("An account with those details already exists", "error")
                return redirect(url_for("public.signup"))
            raise
    faculties = db.session.scalars(select(Faculty.faculty_name).order_by(Faculty.faculty_name)).all()
    return render_template("signup.html", faculties=faculties)

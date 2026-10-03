from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from .common import appointment_view, require_actor, role_required, transaction
from .content_service import load_content, save_content, save_image
from .extensions import db
from .models import Appointment, Faculty, User

bp = Blueprint("admin", __name__)


@bp.get("/admin")
@role_required("admin")
def admin_dashboard():
    search = request.args.get("search", "").strip()
    counts = {
        role: db.session.scalar(select(func.count()).select_from(User).where(User.role == role))
        for role in ("teacher", "student")
    }
    statement = select(Appointment).order_by(Appointment.starts_at.desc())
    if search:
        term = f"%{search}%"
        student, lecturer = aliased(User), aliased(User)
        statement = (
            select(Appointment)
            .join(student, Appointment.student_id == student.id)
            .join(lecturer, Appointment.lecturer_id == lecturer.id)
            .where(
                or_(
                    student.username.ilike(term),
                    lecturer.username.ilike(term),
                    Appointment.purpose.ilike(term),
                    Appointment.status.ilike(term),
                    cast(Appointment.starts_at, String).ilike(term),
                )
            )
            .order_by(Appointment.starts_at.desc())
        )
    rows = db.session.scalars(statement).all()
    appointments = [
        [
            row.lecturer.username,
            row.student.username,
            appointment_view(row)["appointment_date"],
            row.purpose,
            row.status,
            appointment_view(row)["appointment_time"],
            row.public_reference,
        ]
        for row in rows
    ]
    return render_template(
        "admin.html",
        appointments=appointments,
        num_teachers=counts["teacher"],
        num_students=counts["student"],
        num_appointments=db.session.scalar(select(func.count()).select_from(Appointment)),
        num_users=db.session.scalar(select(func.count()).select_from(User)),
    )


@bp.get("/appointmentcontrol")
@role_required("admin")
def appointmentcontrol():
    search = request.args.get("search", "").strip()
    statement = select(Appointment).order_by(Appointment.starts_at.desc())
    if search:
        term = f"%{search}%"
        student, lecturer = aliased(User), aliased(User)
        statement = (
            select(Appointment)
            .join(student, Appointment.student_id == student.id)
            .join(lecturer, Appointment.lecturer_id == lecturer.id)
            .where(
                or_(
                    student.username.ilike(term),
                    lecturer.username.ilike(term),
                    Appointment.purpose.ilike(term),
                    Appointment.status.ilike(term),
                    cast(Appointment.starts_at, String).ilike(term),
                )
            )
            .order_by(Appointment.starts_at.desc())
        )
    rows = db.session.scalars(statement).all()
    appointments = [
        [
            row.id,
            row.lecturer.username,
            row.student_id,
            appointment_view(row)["appointment_date"],
            row.purpose,
            row.status,
            appointment_view(row)["appointment_time"],
        ]
        for row in rows
    ]
    return render_template("appointment_control.html", appointments=appointments)


@bp.post("/delete_booking")
@role_required("admin")
def delete_booking():
    try:
        appointment_id = int(request.form.get("id", ""))
        with transaction() as session:
            require_actor(session, current_user.id, "admin")
            appointment = session.get(Appointment, appointment_id)
            if not appointment:
                abort(404)
            from .common import lock_lecturer

            lock_lecturer(session, appointment.lecturer_id)
            appointment = session.get(Appointment, appointment_id)
            if not appointment:
                abort(404)
            session.delete(appointment)
    except (TypeError, ValueError):
        abort(400)
    return redirect(url_for("admin.appointmentcontrol"))


@bp.get("/usercontrol")
@role_required("admin")
def usercontrol():
    search = request.args.get("search", "").strip()
    statement = select(User).order_by(User.username)
    if search:
        term = f"%{search}%"
        statement = statement.where(
            or_(
                User.username.ilike(term),
                User.role.ilike(term),
                User.phone_number.ilike(term),
                User.faculty_record.has(Faculty.faculty_name.ilike(term)),
            )
        )
    users = [
        {
            "id": user.id,
            "role": user.role,
            "faculty": user.faculty,
            "username": user.username,
            "phone_number": user.phone_number,
        }
        for user in db.session.scalars(statement)
    ]
    return render_template("usercontrol.html", users=users)


@bp.post("/delete_user")
@role_required("admin")
def delete_user_route():
    try:
        user_id = int(request.form.get("id", ""))
    except (TypeError, ValueError):
        abort(400)
    if user_id == int(current_user.id):
        flash("Users with related records, including the active administrator, cannot be deleted", "error")
        return redirect(url_for("admin.usercontrol"))
    try:
        with transaction() as session:
            user = session.get(User, user_id)
            if user:
                session.delete(user)
    except IntegrityError:
        flash("Users with related records cannot be deleted", "error")
    return redirect(url_for("admin.usercontrol"))


@bp.route("/adminpageeditor", methods=["GET", "POST"])
@role_required("admin")
def admin_page_editor():
    content = load_content()
    if request.method == "POST":
        uploaded = request.files.get("school_logo")
        filename = content.get("school_logo", "")
        if uploaded and uploaded.filename:
            try:
                filename = save_image(uploaded)
            except ValueError:
                flash("Upload a valid JPG, PNG, or GIF image", "error")
                return redirect(url_for("admin.admin_page_editor"))
        content.update(
            {
                key: request.form.get(key, "").strip()
                for key in ("home_content", "school_name", "school_tel", "school_email")
            }
        )
        content["school_logo"] = filename
        save_content(content)
        return redirect(url_for("admin.admin_page_editor"))
    return render_template("adminpageeditor.html", **content)

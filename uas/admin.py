from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import aliased, selectinload

from .account_service import issue_lecturer_invitation
from .booking_service import BookingError, InvalidTransition, transition_appointment
from .common import (
    appointment_view,
    page_number,
    pagination,
    record_audit,
    require_actor,
    role_required,
    transaction,
    utc_now,
)
from .content_service import load_content, save_content, save_image
from .extensions import db
from .models import Appointment, Faculty, User
from .validation import InputValidationError, clean_text, validate_email, validate_search

bp = Blueprint("admin", __name__)


@bp.get("/admin")
@role_required("admin")
def admin_dashboard():
    try:
        search = validate_search(request.args.get("search", ""))
    except InputValidationError:
        abort(400)
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
    total = db.session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    pages = pagination(page_number(request.args.get("page")), total)
    rows = db.session.scalars(
        statement.options(selectinload(Appointment.lecturer), selectinload(Appointment.student))
        .limit(pages["per_page"]).offset((pages["page"] - 1) * pages["per_page"])
    ).all()
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
        pagination=pages,
        search=search,
        num_teachers=counts["teacher"],
        num_students=counts["student"],
        num_appointments=db.session.scalar(select(func.count()).select_from(Appointment)),
        num_users=db.session.scalar(select(func.count()).select_from(User)),
    )


@bp.get("/appointmentcontrol")
@role_required("admin")
def appointmentcontrol():
    try:
        search = validate_search(request.args.get("search", ""))
    except InputValidationError:
        abort(400)
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
    total = db.session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    pages = pagination(page_number(request.args.get("page")), total)
    rows = db.session.scalars(
        statement.options(selectinload(Appointment.lecturer), selectinload(Appointment.student))
        .limit(pages["per_page"]).offset((pages["page"] - 1) * pages["per_page"])
    ).all()
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
    return render_template("appointment_control.html", appointments=appointments, pagination=pages, search=search)


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
            record_audit(session, current_user.id, "appointment.deleted", "Appointment", appointment.id)
            session.delete(appointment)
    except (TypeError, ValueError):
        abort(400)
    return redirect(url_for("admin.appointmentcontrol"))


@bp.get("/usercontrol")
@role_required("admin")
def usercontrol():
    try:
        search = validate_search(request.args.get("search", ""))
    except InputValidationError:
        abort(400)
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
    total = db.session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    pages = pagination(page_number(request.args.get("page")), total)
    users = [
        {
            "id": user.id,
            "role": user.role,
            "faculty": user.faculty,
            "username": user.username,
            "phone_number": user.phone_number,
            "active": user.active,
        }
        for user in db.session.scalars(
            statement.options(selectinload(User.faculty_record))
            .limit(pages["per_page"]).offset((pages["page"] - 1) * pages["per_page"])
        )
    ]
    from .models import LecturerInvitation

    invitations = db.session.scalars(
        select(LecturerInvitation)
        .where(LecturerInvitation.used_at.is_(None), LecturerInvitation.revoked_at.is_(None))
        .order_by(LecturerInvitation.created_at.desc())
        .limit(25)
    ).all()
    return render_template("usercontrol.html", users=users, pagination=pages, search=search, invitations=invitations)


@bp.post("/delete_user")
@role_required("admin")
def delete_user_route():
    try:
        user_id = int(request.form.get("id", ""))
    except (TypeError, ValueError):
        abort(400)
    try:
        with transaction() as session:
            require_actor(session, current_user.id, "admin")
            user = session.scalar(select(User).where(User.id == user_id).with_for_update())
            if not user:
                abort(404)
            if user.id == int(current_user.id):
                raise ValueError("You cannot deactivate your own administrator account")
            if user.role == "admin" and user.active:
                active_admins = session.scalars(
                    select(User).where(User.role == "admin", User.active.is_(True)).order_by(User.id).with_for_update()
                ).all()
                if len(active_admins) <= 1:
                    raise ValueError("The last active administrator cannot be deactivated")
            if user.active:
                user.active = False
                user.session_version += 1
                if user.role == "teacher":
                    from .models import Availability

                    session.query(Availability).filter_by(lecturer_id=user.id).update(
                        {Availability.active: False, Availability.updated_at: utc_now()}
                    )
                record_audit(session, current_user.id, "user.deactivated", "User", user.id, role=user.role)
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.usercontrol"))


@bp.post("/activate_user")
@role_required("admin")
def activate_user_route():
    try:
        user_id = int(request.form.get("id", ""))
    except (TypeError, ValueError):
        abort(400)
    with transaction() as session:
        require_actor(session, current_user.id, "admin")
        user = session.get(User, user_id)
        if not user:
            abort(404)
        if not user.active:
            user.active = True
            user.session_version += 1
            record_audit(session, current_user.id, "user.reactivated", "User", user.id, role=user.role)
    return redirect(url_for("admin.usercontrol"))


@bp.route("/adminpageeditor", methods=["GET", "POST"])
@role_required("admin")
def admin_page_editor():
    content = load_content()
    if request.method == "POST":
        uploaded = request.files.get("school_logo")
        filename = content.get("school_logo", "")
        form_values = {
            key: request.form.get(key, "").strip()
            for key in ("home_content", "school_name", "school_tel", "school_email")
        }
        form_errors = {}
        bounds = {"home_content": 5000, "school_name": 200, "school_tel": 35}
        for key, maximum in bounds.items():
            try:
                form_values[key] = clean_text(form_values[key], key, minimum=0, maximum=maximum)
            except InputValidationError as exc:
                form_errors.update(exc.errors)
        try:
            form_values["school_email"] = validate_email(form_values["school_email"], "admin")
        except InputValidationError as exc:
            form_errors["school_email"] = exc.errors["email"]
        if uploaded and uploaded.filename and not form_errors:
            try:
                filename = save_image(uploaded)
            except ValueError:
                form_errors["school_logo"] = "Upload a valid JPEG, PNG, or WebP image under the size limit."
        if form_errors:
            return render_template(
                "adminpageeditor.html", **content, form_values=form_values, form_errors=form_errors
            ), 400
        content.update(form_values)
        content["school_logo"] = filename
        save_content(content, current_user.id)
        return redirect(url_for("admin.admin_page_editor"))
    return render_template("adminpageeditor.html", **content, form_values={}, form_errors={})


@bp.post("/admin/lecturer-invitations")
@role_required("admin")
def create_lecturer_invitation():
    raw_email = request.form.get("email", "").strip()
    try:
        email = validate_email(raw_email, "teacher") if raw_email else None
    except InputValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.usercontrol"))
    try:
        token = issue_lecturer_invitation(current_user.id, email)
    except PermissionError:
        abort(403)
    response = render_template("invitation_created.html", token=token)
    from flask import make_response

    result = make_response(response)
    result.headers["Cache-Control"] = "no-store"
    return result


@bp.post("/admin/lecturer-invitations/<int:invitation_id>/revoke")
@role_required("admin")
def revoke_lecturer_invitation_route(invitation_id):
    from .account_service import revoke_lecturer_invitation

    try:
        revoke_lecturer_invitation(current_user.id, invitation_id)
    except PermissionError:
        abort(403)
    except ValueError:
        abort(404)
    return redirect(url_for("admin.usercontrol"))


@bp.post("/admin/appointment-status")
@role_required("admin")
def admin_appointment_status():
    try:
        target = request.form.get("status", "")
        if target not in {"Completed", "No Show"}:
            abort(400)
        transition_appointment(int(request.form.get("id", "")), current_user.id, "admin", target)
    except PermissionError:
        abort(403)
    except (BookingError, InvalidTransition, TypeError, ValueError):
        flash("That appointment status cannot be changed", "error")
    return redirect(url_for("admin.appointmentcontrol"))

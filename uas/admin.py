from datetime import UTC, date, datetime, time, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased, joinedload

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
    university_zone,
    utc_now,
)
from .content_service import load_content, save_content, save_image
from .extensions import db
from .models import (
    Appointment,
    AppointmentStatusHistory,
    AuditLog,
    Faculty,
    LecturerInvitation,
    Status,
    User,
)
from .validation import InputValidationError, clean_text, validate_email, validate_search

bp = Blueprint("admin", __name__)

APPOINTMENT_STATUSES = tuple(status.value for status in Status)
INVITATION_STATUSES = ("active", "used", "expired", "revoked")
AUDIT_ACTION_LABELS = {
    "account.password_changed": "Password changed",
    "account.password_reset": "Password reset",
    "account.profile_updated": "Profile updated",
    "appointment.deleted": "Appointment deleted",
    "faculty.created": "Faculty created",
    "faculty.updated": "Faculty updated",
    "lecturer_invitation.created": "Lecturer invitation created",
    "lecturer_invitation.revoked": "Lecturer invitation revoked",
    "site_settings.updated": "Site settings updated",
    "user.deactivated": "User deactivated",
    "user.reactivated": "User reactivated",
}


def _optional_id(name):
    value = request.args.get(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        abort(400)


def _local_date_range():
    values = {}
    for name in ("date_from", "date_to"):
        raw = request.args.get(name, "").strip()
        if not raw:
            values[name] = None
            continue
        try:
            values[name] = date.fromisoformat(raw)
        except ValueError:
            abort(400)
    first, last = values["date_from"], values["date_to"]
    if first and last and first > last:
        abort(400)
    zone = university_zone()
    start = datetime.combine(first, time.min, tzinfo=zone).astimezone(UTC) if first else None
    try:
        end_day = last + timedelta(days=1) if last else None
    except OverflowError:
        abort(400)
    end = datetime.combine(end_day, time.min, tzinfo=zone).astimezone(UTC) if end_day else None
    return values["date_from"], values["date_to"], start, end


def _audit_summary(rows):
    """Build safe labels without exposing arbitrary audit metadata or foreign keys."""
    target_ids = {}
    for row in rows:
        try:
            target_ids.setdefault(row.target_type, set()).add(int(row.target_id))
        except (TypeError, ValueError):
            continue
    labels = {}
    if target_ids.get("User"):
        labels.update(
            (f"User:{user.id}", user.username)
            for user in db.session.scalars(select(User).where(User.id.in_(target_ids["User"])))
        )
    if target_ids.get("Faculty"):
        labels.update(
            (f"Faculty:{faculty.id}", faculty.faculty_name)
            for faculty in db.session.scalars(select(Faculty).where(Faculty.id.in_(target_ids["Faculty"])))
        )
    if target_ids.get("Appointment"):
        student, lecturer = aliased(User), aliased(User)
        labels.update(
            (f"Appointment:{appointment.id}", f"{appointment.public_reference} - {appointment.student_name} / {appointment.lecturer_name}")
            for appointment in db.session.execute(
                select(
                    Appointment.id,
                    Appointment.public_reference,
                    student.username.label("student_name"),
                    lecturer.username.label("lecturer_name"),
                )
                .join(student, Appointment.student_id == student.id)
                .join(lecturer, Appointment.lecturer_id == lecturer.id)
                .where(Appointment.id.in_(target_ids["Appointment"]))
            )
        )
    if target_ids.get("LecturerInvitation"):
        labels.update(
            (f"LecturerInvitation:{invitation.id}", invitation.email or "Lecturer invitation")
            for invitation in db.session.scalars(
                select(LecturerInvitation).where(LecturerInvitation.id.in_(target_ids["LecturerInvitation"]))
            )
        )
    summaries = []
    for row in rows:
        key = f"{row.target_type}:{row.target_id}"
        target = labels.get(key, {
            "SiteSettings": "Institution settings",
            "Appointment": "Appointment record no longer available",
            "User": "User account no longer available",
            "Faculty": "Faculty no longer available",
            "LecturerInvitation": "Lecturer invitation no longer available",
        }.get(row.target_type, "Administrative record"))
        role = row.metadata_json.get("role") if isinstance(row.metadata_json, dict) else None
        role = {"student": "Student", "teacher": "Lecturer", "admin": "Administrator"}.get(role)
        summaries.append({
            "row": row,
            "action_label": AUDIT_ACTION_LABELS.get(row.action, "Administrative change"),
            "target_label": target,
            "detail": f"Role: {role}" if role else "",
        })
    return summaries


@bp.get("/admin")
@role_required("admin")
def admin_dashboard():
    people = {
        (role, active): count
        for role, active, count in db.session.execute(
            select(User.role, User.active, func.count(User.id)).group_by(User.role, User.active)
        )
    }
    roles = dict(db.session.execute(select(User.role, func.count(User.id)).group_by(User.role)).all())
    statuses = dict(db.session.execute(select(Appointment.status, func.count(Appointment.id)).group_by(Appointment.status)).all())
    recent_rows = db.session.scalars(
        select(AuditLog).options(joinedload(AuditLog.actor)).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(5)
    ).all()
    zone = university_zone()
    recent_activity = _audit_summary(recent_rows)
    for item in recent_activity:
        item["created_at"] = item["row"].created_at.astimezone(zone)
    return render_template(
        "admin.html",
        metrics={
            "users": sum(people.values()),
            "active_users": sum(count for (role, active), count in people.items() if active),
            "students": roles.get("student", 0),
            "lecturers": roles.get("teacher", 0),
            "appointment_statuses": {status.value: statuses.get(status.value, 0) for status in Status},
        },
        recent_activity=recent_activity,
    )


@bp.get("/appointmentcontrol")
@role_required("admin")
def appointmentcontrol():
    try:
        search = validate_search(request.args.get("search", ""))
    except InputValidationError:
        abort(400)
    status = request.args.get("status", "").strip()
    if status and status not in APPOINTMENT_STATUSES:
        abort(400)
    faculty_id = _optional_id("faculty_id")
    faculties = db.session.scalars(select(Faculty).order_by(Faculty.faculty_name)).all()
    if faculty_id and faculty_id not in {faculty.id for faculty in faculties}:
        abort(400)
    date_from, date_to, start_bound, end_bound = _local_date_range()
    statement = select(Appointment).order_by(Appointment.starts_at.desc(), Appointment.id.desc())
    if search:
        term = f"%{search}%"
        student, lecturer = aliased(User), aliased(User)
        statement = (
            select(Appointment)
            .join(student, Appointment.student_id == student.id)
            .join(lecturer, Appointment.lecturer_id == lecturer.id)
            .where(
                or_(
                    Appointment.public_reference.ilike(term),
                    student.username.ilike(term),
                    student.email.ilike(term),
                    lecturer.username.ilike(term),
                    lecturer.email.ilike(term),
                    Appointment.purpose.ilike(term),
                )
            )
            .order_by(Appointment.starts_at.desc(), Appointment.id.desc())
        )
    if status:
        statement = statement.where(Appointment.status == status)
    if faculty_id:
        statement = statement.where(Appointment.lecturer.has(User.faculty_id == faculty_id))
    if start_bound:
        statement = statement.where(Appointment.starts_at >= start_bound)
    if end_bound:
        statement = statement.where(Appointment.starts_at < end_bound)
    total = db.session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    pages = pagination(page_number(request.args.get("page")), total)
    rows = db.session.scalars(
        statement.options(
            joinedload(Appointment.lecturer).joinedload(User.faculty_record),
            joinedload(Appointment.student).joinedload(User.faculty_record),
        )
        .limit(pages["per_page"]).offset((pages["page"] - 1) * pages["per_page"])
    ).all()
    appointments = []
    for row in rows:
        view = appointment_view(row)
        appointments.append({"row": row, "date": view["appointment_date"], "time": view["appointment_time"]})
    return render_template(
        "appointment_control.html",
        appointments=appointments,
        pagination=pages,
        search=search,
        status_filter=status,
        faculty_id=faculty_id,
        faculties=faculties,
        date_from=date_from.isoformat() if date_from else "",
        date_to=date_to.isoformat() if date_to else "",
    )


@bp.get("/admin/appointments/<public_reference>")
@role_required("admin")
def appointment_detail(public_reference):
    appointment = db.session.scalar(
        select(Appointment)
        .where(Appointment.public_reference == public_reference)
        .options(
            joinedload(Appointment.student).joinedload(User.faculty_record),
            joinedload(Appointment.lecturer).joinedload(User.faculty_record),
        )
    )
    if not appointment:
        abort(404)
    history = db.session.scalars(
        select(AppointmentStatusHistory)
        .where(AppointmentStatusHistory.appointment_id == appointment.id)
        .options(joinedload(AppointmentStatusHistory.actor))
        .order_by(AppointmentStatusHistory.created_at, AppointmentStatusHistory.id)
    ).all()
    view = appointment_view(appointment)
    zone = university_zone()
    return render_template(
        "admin_appointment_detail.html",
        appointment=appointment,
        appointment_date=view["appointment_date"],
        appointment_time=view["appointment_time"],
        created_at=appointment.created_at.astimezone(zone),
        history=[{"row": item, "created_at": item.created_at.astimezone(zone)} for item in history],
        can_delete=not history,
    )


@bp.get("/admin/audit-log")
@role_required("admin")
def audit_log():
    try:
        actor = validate_search(request.args.get("actor", ""))
    except InputValidationError:
        abort(400)
    action = request.args.get("action", "").strip()
    target_type = request.args.get("target_type", "").strip()
    target_types = ("User", "Appointment", "Faculty", "SiteSettings", "LecturerInvitation")
    if target_type and target_type not in target_types:
        abort(400)
    known_actions = set(
        db.session.scalars(
            select(AuditLog.action).where(AuditLog.action.in_(AUDIT_ACTION_LABELS)).distinct()
        ).all()
    )
    if action and (len(action) > 80 or action not in known_actions):
        abort(400)
    date_from, date_to, start_bound, end_bound = _local_date_range()
    statement = select(AuditLog).options(joinedload(AuditLog.actor)).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if actor:
        user = aliased(User)
        statement = statement.join(user, AuditLog.actor_user_id == user.id).where(
            or_(user.username.ilike(f"%{actor}%"), user.email.ilike(f"%{actor}%"))
        )
    if action:
        statement = statement.where(AuditLog.action == action)
    if target_type:
        statement = statement.where(AuditLog.target_type == target_type)
    if start_bound:
        statement = statement.where(AuditLog.created_at >= start_bound)
    if end_bound:
        statement = statement.where(AuditLog.created_at < end_bound)
    total = db.session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    pages = pagination(page_number(request.args.get("page")), total)
    rows = db.session.scalars(
        statement.limit(pages["per_page"]).offset((pages["page"] - 1) * pages["per_page"])
    ).all()
    zone = university_zone()
    activity = _audit_summary(rows)
    for entry in activity:
        entry["created_at"] = entry["row"].created_at.astimezone(zone)
    return render_template(
        "audit_log.html",
        activity=activity,
        pagination=pages,
        filters={
            "actor": actor,
            "action": action,
            "target_type": target_type,
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
        },
        actions=sorted(known_actions),
        action_labels=AUDIT_ACTION_LABELS,
        target_types=target_types,
    )


@bp.post("/delete_booking")
@role_required("admin")
def delete_booking():
    try:
        appointment_id = int(request.form.get("id", ""))
    except (TypeError, ValueError):
        abort(400)
    try:
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
            if session.scalar(
                select(AppointmentStatusHistory.id)
                .where(AppointmentStatusHistory.appointment_id == appointment.id)
                .limit(1)
            ):
                raise ValueError("Appointments with status history cannot be deleted.")
            record_audit(session, current_user.id, "appointment.deleted", "Appointment", appointment.id)
            session.delete(appointment)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Appointment deleted.", "success")
    return redirect(url_for("admin.appointmentcontrol"))


@bp.get("/usercontrol")
@role_required("admin")
def usercontrol():
    try:
        search = validate_search(request.args.get("search", ""))
    except InputValidationError:
        abort(400)
    role = request.args.get("role", "").strip()
    active = request.args.get("active", "").strip()
    verification = request.args.get("verification", "").strip()
    faculty_id = _optional_id("faculty_id")
    if role and role not in {"student", "teacher", "admin"}:
        abort(400)
    if active and active not in {"active", "inactive"}:
        abort(400)
    if verification and verification not in {"verified", "unverified"}:
        abort(400)
    faculties = db.session.scalars(select(Faculty).order_by(Faculty.faculty_name)).all()
    if faculty_id and faculty_id not in {faculty.id for faculty in faculties}:
        abort(400)
    statement = select(User).order_by(User.username)
    if search:
        term = f"%{search}%"
        statement = statement.where(
            or_(
                User.username.ilike(term),
                User.email.ilike(term),
                User.phone_number.ilike(term),
                User.faculty_record.has(Faculty.faculty_name.ilike(term)),
            )
        )
    if role:
        statement = statement.where(User.role == role)
    if active:
        statement = statement.where(User.active.is_(active == "active"))
    if verification:
        statement = statement.where(User.email_verified_at.is_not(None) if verification == "verified" else User.email_verified_at.is_(None))
    if faculty_id:
        statement = statement.where(User.faculty_id == faculty_id)
    total = db.session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    pages = pagination(page_number(request.args.get("page")), total)
    users = db.session.scalars(
        statement.options(joinedload(User.faculty_record))
        .limit(pages["per_page"]).offset((pages["page"] - 1) * pages["per_page"])
    ).all()
    active_admins = db.session.scalar(
        select(func.count(User.id)).where(User.role == "admin", User.active.is_(True))
    ) or 0
    for user in users:
        user.can_deactivate = user.id != current_user.id and not (
            user.role == "admin" and user.active and active_admins <= 1
        )

    invitation_status = request.args.get("invitation_status", "").strip()
    if invitation_status and invitation_status not in INVITATION_STATUSES:
        abort(400)
    now = utc_now()
    invitation_statement = select(LecturerInvitation).options(
        joinedload(LecturerInvitation.creator)
    ).order_by(LecturerInvitation.created_at.desc(), LecturerInvitation.id.desc())
    invitation_conditions = {
        "active": (LecturerInvitation.used_at.is_(None), LecturerInvitation.revoked_at.is_(None), LecturerInvitation.expires_at > now),
        "used": (LecturerInvitation.used_at.is_not(None),),
        "expired": (LecturerInvitation.used_at.is_(None), LecturerInvitation.revoked_at.is_(None), LecturerInvitation.expires_at <= now),
        "revoked": (LecturerInvitation.revoked_at.is_not(None),),
    }
    if invitation_status:
        invitation_statement = invitation_statement.where(*invitation_conditions[invitation_status])
    invitation_total = db.session.scalar(
        select(func.count()).select_from(invitation_statement.order_by(None).subquery())
    ) or 0
    invitation_pages = pagination(page_number(request.args.get("invitation_page")), invitation_total)
    invitation_rows = db.session.scalars(
        invitation_statement.limit(invitation_pages["per_page"])
        .offset((invitation_pages["page"] - 1) * invitation_pages["per_page"])
    ).all()
    invitations = []
    zone = university_zone()
    for invitation in invitation_rows:
        status = (
            "Revoked" if invitation.revoked_at else
            "Used" if invitation.used_at else
            "Expired" if invitation.expires_at <= now else
            "Active"
        )
        invitations.append({
            "row": invitation,
            "status": status,
            "created_at": invitation.created_at.astimezone(zone),
            "expires_at": invitation.expires_at.astimezone(zone),
        })
    filter_params = {
        key: value for key, value in {
            "search": search,
            "role": role,
            "active": active,
            "faculty_id": faculty_id,
            "verification": verification,
        }.items() if value not in (None, "")
    }
    invitation_filter_params = {"invitation_status": invitation_status} if invitation_status else {}
    return render_template(
        "usercontrol.html",
        users=users,
        pagination=pages,
        search=search,
        role_filter=role,
        active_filter=active,
        verification_filter=verification,
        faculty_filter=faculty_id,
        faculties=faculties,
        invitations=invitations,
        invitation_pagination=invitation_pages,
        invitation_status_filter=invitation_status,
        filter_params=filter_params,
        invitation_filter_params=invitation_filter_params,
        display_zone=university_zone(),
    )


@bp.get("/admin/users/<int:user_id>")
@role_required("admin")
def user_detail(user_id):
    user = db.session.scalar(
        select(User).where(User.id == user_id).options(joinedload(User.faculty_record))
    )
    if not user:
        abort(404)
    active_admins = db.session.scalar(
        select(func.count(User.id)).where(User.role == "admin", User.active.is_(True))
    ) or 0
    user.can_deactivate = user.id != current_user.id and not (
        user.role == "admin" and user.active and active_admins <= 1
    )
    zone = university_zone()
    return render_template(
        "admin_user_detail.html",
        user=user,
        created_at=user.created_at.astimezone(zone),
        last_login_at=user.last_login_at.astimezone(zone) if user.last_login_at else None,
    )


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
                changed = True
            else:
                changed = False
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        if changed:
            flash("Account deactivated. Existing sessions are invalidated.", "success")
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
            changed = True
        else:
            changed = False
    if changed:
        flash("Account reactivated. Lecturer availability remains disabled until re-enabled separately.", "success")
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
        flash("Site settings saved.", "success")
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
    flash("Invitation revoked.", "success")
    return redirect(url_for("admin.usercontrol"))


@bp.post("/admin/appointment-status")
@role_required("admin")
def admin_appointment_status():
    try:
        target = request.form.get("status", "")
        if target not in {"Completed", "No Show"}:
            abort(400)
        transition_appointment(int(request.form.get("id", "")), current_user.id, "admin", target)
        flash(f"Appointment marked as {target.lower()}.", "success")
    except PermissionError:
        abort(403)
    except (BookingError, InvalidTransition, TypeError, ValueError):
        flash("That appointment status cannot be changed", "error")
    return redirect(url_for("admin.appointmentcontrol"))

from datetime import UTC, datetime, time, timedelta
from math import ceil

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import joinedload

from .booking_service import (
    BookingConflict,
    BookingError,
    InvalidTransition,
    create_booking,
    slot_is_available,
    transition_appointment,
)
from .common import (
    appointment_view,
    page_number,
    pagination,
    role_required,
    safe_next_url,
    university_zone,
    utc_now,
)
from .content_service import load_content
from .extensions import db
from .models import Appointment, AppointmentStatusHistory, Availability, Faculty, Status, User
from .validation import InputValidationError, validate_search

bp = Blueprint("appointments", __name__)

_STUDENT_STATUS_COPY = {
    "Pending": "Waiting for lecturer confirmation.",
    "Accepted": "Your appointment is confirmed.",
    "Rejected": "The lecturer declined this request.",
    "Cancelled": "This appointment was cancelled.",
    "Completed": "This appointment is finished.",
    "No Show": "This appointment was marked as unattended.",
}
_LECTURER_STATUSES = tuple(status.value for status in Status)


def _student_appointment_view(row):
    view = appointment_view(row)
    start = row.starts_at.astimezone(university_zone())
    end = row.ends_at.astimezone(university_zone())
    view.update(
        date_display=start.strftime("%a, %d %b %Y"),
        time_display=f"{start.strftime('%I:%M %p').lstrip('0')} - {end.strftime('%I:%M %p').lstrip('0')}",
        lecturer_faculty=row.lecturer.faculty_record.faculty_name,
        status_description=_STUDENT_STATUS_COPY.get(row.status, "Appointment status updated."),
        can_cancel=row.status in {"Pending", "Accepted"},
    )
    return view


def _format_local_datetime(value):
    local = value.astimezone(university_zone())
    return f"{local.strftime('%a, %d %b %Y')} at {local.strftime('%I:%M %p').lstrip('0')}"


def _student_appointment_query():
    return select(Appointment).options(
        joinedload(Appointment.lecturer).joinedload(User.faculty_record),
        joinedload(Appointment.student),
    )


def _lecturer_appointment_query():
    return select(Appointment).options(
        joinedload(Appointment.student).joinedload(User.faculty_record)
    )


def _lecturer_appointment_view(row):
    local_start = row.starts_at.astimezone(university_zone())
    local_end = row.ends_at.astimezone(university_zone())
    purpose = row.purpose
    summary = purpose if len(purpose) <= 120 else f"{purpose[:117].rstrip()}…"
    return {
        "id": row.id,
        "public_reference": row.public_reference,
        "student": row.student.username,
        "student_faculty": row.student.faculty_record.faculty_name,
        "date_display": local_start.strftime("%a, %d %b %Y"),
        "time_display": f"{local_start.strftime('%I:%M %p').lstrip('0')} – {local_end.strftime('%I:%M %p').lstrip('0')}",
        "starts_at": row.starts_at,
        "duration_minutes": int((row.ends_at - row.starts_at).total_seconds() // 60),
        "purpose": purpose,
        "purpose_summary": summary,
        "status": row.status,
        "created_at": row.created_at,
    }


def _lecturer_status_history(row):
    records = db.session.scalars(
        select(AppointmentStatusHistory)
        .options(joinedload(AppointmentStatusHistory.actor))
        .where(AppointmentStatusHistory.appointment_id == row.id)
        .order_by(AppointmentStatusHistory.created_at, AppointmentStatusHistory.id)
    ).all()
    labels = {
        "Accepted": "Appointment accepted",
        "Rejected": "Appointment rejected",
        "Cancelled": "Appointment cancelled",
        "Completed": "Appointment completed",
        "No Show": "Marked as no show",
    }
    events = [
        {
            "label": "Request received",
            "description": "The student sent this appointment request.",
            "actor": row.student.username,
            "timestamp": _format_local_datetime(row.created_at),
        }
    ]
    events.extend(
        {
            "label": labels.get(record.to_status, "Appointment updated"),
            "description": f"Status changed from {record.from_status} to {record.to_status}.",
            "actor": record.actor.username,
            "timestamp": _format_local_datetime(record.created_at),
        }
        for record in records
    )
    return events


def _lecturer_return_location():
    return safe_next_url(request.referrer) or url_for("appointments.booking_history")


@bp.get("/lecturer")
@role_required("teacher")
def lecturer_dashboard():
    owner = int(current_user.id)
    now = utc_now()
    zone = university_zone()
    local_today = now.astimezone(zone).date()
    today_start = datetime.combine(local_today, time.min, zone).astimezone(UTC)
    tomorrow_start = datetime.combine(local_today + timedelta(days=1), time.min, zone).astimezone(UTC)
    week_end = tomorrow_start + timedelta(days=7)

    pending_count = db.session.scalar(
        select(func.count()).select_from(Appointment).where(
            Appointment.lecturer_id == owner,
            Appointment.status == "Pending",
        )
    ) or 0
    pending_rows = db.session.scalars(
        _lecturer_appointment_query()
        .where(Appointment.lecturer_id == owner, Appointment.status == "Pending")
        .order_by(Appointment.created_at, Appointment.starts_at, Appointment.id)
        .limit(5)
    ).all()
    today_rows = db.session.scalars(
        _lecturer_appointment_query()
        .where(
            Appointment.lecturer_id == owner,
            Appointment.status == "Accepted",
            Appointment.starts_at >= today_start,
            Appointment.starts_at < tomorrow_start,
        )
        .order_by(Appointment.starts_at, Appointment.id)
        .limit(10)
    ).all()
    next_row = db.session.scalar(
        _lecturer_appointment_query()
        .where(
            Appointment.lecturer_id == owner,
            Appointment.status == "Accepted",
            Appointment.starts_at >= tomorrow_start,
        )
        .order_by(Appointment.starts_at, Appointment.id)
        .limit(1)
    )
    week_rows = db.session.scalars(
        _lecturer_appointment_query()
        .where(
            Appointment.lecturer_id == owner,
            Appointment.status == "Accepted",
            Appointment.starts_at >= tomorrow_start,
            Appointment.starts_at < week_end,
        )
        .order_by(Appointment.starts_at, Appointment.id)
        .limit(8)
    ).all()
    availability_count = db.session.scalar(
        select(func.count()).select_from(Availability).where(
            Availability.lecturer_id == owner,
            Availability.active.is_(True),
            Availability.ends_at > now,
        )
    ) or 0
    return render_template(
        "lecturer_dashboard.html",
        pending_count=pending_count,
        pending_appointments=[_lecturer_appointment_view(row) for row in pending_rows],
        today_appointments=[_lecturer_appointment_view(row) for row in today_rows],
        today_total=len(today_rows),
        next_appointment=_lecturer_appointment_view(next_row) if next_row else None,
        upcoming_appointments=[
            _lecturer_appointment_view(row) for row in week_rows if not next_row or row.id != next_row.id
        ],
        availability_count=availability_count,
    )


@bp.get("/lecturer/requests")
@role_required("teacher")
def lecturer_requests():
    owner = int(current_user.id)
    total = db.session.scalar(
        select(func.count()).select_from(Appointment).where(
            Appointment.lecturer_id == owner,
            Appointment.status == "Pending",
        )
    ) or 0
    pages = pagination(page_number(request.args.get("page")), total)
    rows = db.session.scalars(
        _lecturer_appointment_query()
        .where(Appointment.lecturer_id == owner, Appointment.status == "Pending")
        .order_by(Appointment.created_at, Appointment.starts_at, Appointment.id)
        .limit(pages["per_page"])
        .offset((pages["page"] - 1) * pages["per_page"])
    ).all()
    return render_template(
        "lecturer_requests.html",
        appointments=[_lecturer_appointment_view(row) for row in rows],
        pagination=pages,
    )


@bp.get("/lecturer/appointments/<string:public_reference>")
@role_required("teacher")
def lecturer_detail(public_reference):
    row = db.session.scalar(
        _lecturer_appointment_query().where(
            Appointment.public_reference == public_reference,
            Appointment.lecturer_id == int(current_user.id),
        )
    )
    if row is None:
        abort(404)
    return render_template(
        "lecturer_detail.html",
        appointment=_lecturer_appointment_view(row),
        status_history=_lecturer_status_history(row),
    )


def _booking_retry_url():
    params = {}
    for form_name, query_name in (("faculty_id", "faculty_id"), ("lecturer", "lecturer")):
        try:
            value = int(request.form.get(form_name, ""))
        except (TypeError, ValueError):
            continue
        if value > 0:
            params[query_name] = value
    raw_date = request.form.get("appointment_date", "")
    try:
        params["appointment_date"] = datetime.strptime(raw_date, "%Y-%m-%d").date().isoformat()  # noqa: DTZ007
    except (TypeError, ValueError):
        pass
    return redirect(url_for("appointments.appointment2", **params))


@bp.get("/appointment")
@role_required("student")
def appointment():
    now = utc_now()
    next_appointment = db.session.scalar(
        _student_appointment_query()
        .where(
            Appointment.student_id == int(current_user.id),
            Appointment.status == "Accepted",
            Appointment.starts_at >= now,
        )
        .order_by(Appointment.starts_at)
        .limit(1)
    )
    pending = db.session.scalars(
        _student_appointment_query()
        .where(Appointment.student_id == int(current_user.id), Appointment.status == "Pending")
        .order_by(Appointment.created_at.desc())
        .limit(3)
    ).all()
    upcoming = db.session.scalars(
        _student_appointment_query()
        .where(
            Appointment.student_id == int(current_user.id),
            Appointment.status.in_(("Pending", "Accepted")),
            Appointment.starts_at >= now,
        )
        .order_by(Appointment.starts_at)
        .limit(8)
    ).all()
    excluded = {row.id for row in pending}
    if next_appointment:
        excluded.add(next_appointment.id)
    upcoming = [row for row in upcoming if row.id not in excluded][:4]
    recent = db.session.scalars(
        _student_appointment_query()
        .where(
            Appointment.student_id == int(current_user.id),
            Appointment.status.notin_(("Pending", "Accepted")),
        )
        .order_by(Appointment.updated_at.desc())
        .limit(4)
    ).all()
    return render_template(
        "appointment.html",
        next_appointment=_student_appointment_view(next_appointment) if next_appointment else None,
        pending_appointments=[_student_appointment_view(row) for row in pending],
        upcoming_appointments=[_student_appointment_view(row) for row in upcoming],
        recent_appointments=[_student_appointment_view(row) for row in recent],
        has_appointments=bool(next_appointment or pending or upcoming or recent),
    )


@bp.get("/appointment2")
@role_required("student")
def appointment2():
    faculties = db.session.scalars(select(Faculty).order_by(Faculty.faculty_name)).all()
    faculty_id = request.args.get("faculty_id", type=int)
    faculty_ids = {faculty.id for faculty in faculties}
    if faculty_id not in faculty_ids:
        faculty_id = None
    lecturers = [
        {"id": user.id, "username": user.username, "faculty_id": user.faculty_id, "faculty": user.faculty_record.faculty_name}
        for user in db.session.scalars(
            select(User)
            .options(joinedload(User.faculty_record))
            .where(User.role == "teacher", User.active.is_(True))
            .order_by(User.username)
        )
    ]
    lecturer_id = request.args.get("lecturer", type=int)
    if lecturer_id and not any(lecturer["id"] == lecturer_id for lecturer in lecturers):
        lecturer_id = None
    if lecturer_id:
        selected_lecturer = next(lecturer for lecturer in lecturers if lecturer["id"] == lecturer_id)
        faculty_id = selected_lecturer["faculty_id"]
    appointment_date = request.args.get("appointment_date", "")
    try:
        appointment_date = datetime.strptime(appointment_date, "%Y-%m-%d").date().isoformat()  # noqa: DTZ007
    except (TypeError, ValueError):
        appointment_date = ""
    today = utc_now().astimezone(university_zone()).date().isoformat()
    if appointment_date and appointment_date < today:
        appointment_date = ""
    return render_template(
        "appointment2.html",
        faculties=faculties,
        faculty_id=faculty_id,
        lecturer_id=lecturer_id,
        lecturers=lecturers,
        appointment_date=appointment_date,
        min_booking_date=today,
        slots_endpoint=url_for("appointments.get_calendar_details"),
    )


@bp.get("/get_calendar_details")
@role_required("student")
def get_calendar_details():
    try:
        lecturer_id = int(request.args.get("lecturer", ""))
        day = datetime.strptime(request.args.get("appointment_date", ""), "%Y-%m-%d").date()  # noqa: DTZ007
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid lecturer or date"}), 400
    if not db.session.scalar(
        select(User.id).where(User.id == lecturer_id, User.role == "teacher", User.active.is_(True))
    ):
        return jsonify({"slots": []})
    start = datetime.combine(day, time.min, university_zone()).astimezone(UTC)
    end = start + timedelta(days=1)
    windows = db.session.scalars(
        select(Availability)
        .where(
            Availability.lecturer_id == lecturer_id,
            Availability.active.is_(True),
            Availability.starts_at < end,
            Availability.ends_at > start,
        )
        .order_by(Availability.starts_at)
    ).all()
    slots = []
    active = db.session.scalars(
        select(Appointment.starts_at, Appointment.ends_at).where(
            Appointment.lecturer_id == lecturer_id,
            Appointment.status.in_(("Pending", "Accepted")),
            Appointment.starts_at < end,
            Appointment.ends_at > start,
        )
    ).all()
    for window in windows:
        duration = timedelta(minutes=window.slot_minutes)
        slot_seconds = duration.total_seconds()
        offset = max(0.0, (start - window.starts_at).total_seconds())
        current = window.starts_at + duration * ceil(offset / slot_seconds)
        while current + duration <= window.ends_at and current < end and current + duration > start:
            finish = current + duration
            local_start, local_end = current.astimezone(university_zone()), finish.astimezone(university_zone())
            conflict = any(a < finish and b > current for a, b in active)
            slots.append(
                {
                    "availability_id": window.id,
                    "starts_at": current.isoformat(),
                    "label": f"{local_start.strftime('%I:%M %p').lstrip('0')} - {local_end.strftime('%I:%M %p').lstrip('0')}",
                    "available": not conflict,
                }
            )
            current += duration
    return jsonify({"slots": slots})


@bp.get("/check_availability")
@role_required("student")
def check_availability():
    try:
        available = slot_is_available(int(request.args.get("availability_id", "")), request.args.get("starts_at"))
    except (TypeError, ValueError):
        available = False
    return jsonify({"available": available})


@bp.post("/create_booking")
@role_required("student")
def create_booking_route():
    try:
        _, reference = create_booking(
            int(current_user.id),
            int(request.form.get("availability_id", "")),
            request.form.get("slot_start"),
            request.form.get("purpose"),
        )
    except BookingConflict:
        flash("That time was just booked by someone else. Choose another available time.", "error")
        return _booking_retry_url()
    except (BookingError, TypeError, ValueError):
        flash("That appointment time is no longer valid. Choose another available time.", "error")
        return _booking_retry_url()
    session["last_booking_reference"] = reference
    flash("Appointment request sent", "success")
    return redirect(url_for("appointments.invoice", reference=reference))


@bp.get("/invoice")
@role_required("student")
def invoice():
    reference = request.args.get("reference") or session.get("last_booking_reference")
    row = db.session.scalar(
        _student_appointment_query().where(
            Appointment.public_reference == reference, Appointment.student_id == int(current_user.id)
        )
    )
    if not row:
        abort(404)
    student_view = _student_appointment_view(row)
    status_events = [
        {
            "label": "Request sent",
            "description": "Your appointment request was submitted.",
            "timestamp": _format_local_datetime(row.created_at),
        }
    ]
    history = db.session.scalars(
        select(AppointmentStatusHistory)
        .where(AppointmentStatusHistory.appointment_id == row.id)
        .order_by(AppointmentStatusHistory.created_at, AppointmentStatusHistory.id)
    ).all()
    event_labels = {
        "Accepted": "Accepted by lecturer",
        "Rejected": "Request declined",
        "Cancelled": "Appointment cancelled",
        "Completed": "Appointment completed",
        "No Show": "Marked as no show",
    }
    for event in history:
        status_events.append(
            {
                "label": event_labels.get(event.to_status, event.to_status),
                "description": _STUDENT_STATUS_COPY.get(event.to_status, "Appointment status updated."),
                "timestamp": _format_local_datetime(event.created_at),
            }
        )
    content = load_content()
    data = [
        row.id,
        current_user.username,
        row.student_id,
        row.lecturer.username,
        student_view["appointment_date"],
        student_view["appointment_time"],
        row.purpose,
    ]
    return render_template(
        "invoice.html",
        username=current_user.username,
        email=current_user.email,
        faculty=current_user.faculty,
        role=current_user.role,
        appointment=data,
        booking_id=row.public_reference,
        university=content.get("school_name", "Multimedia University"),
        student_appointment=student_view,
        status_events=status_events,
    )


@bp.get("/bookinghistory")
@role_required("student", "teacher")
def booking_history():
    owner = Appointment.student_id if current_user.role == "student" else Appointment.lecturer_id
    if current_user.role == "student":
        now = utc_now()
        total = db.session.scalar(select(func.count()).select_from(Appointment).where(owner == int(current_user.id))) or 0
        pages = pagination(page_number(request.args.get("page")), total)
        rows = db.session.scalars(
            _student_appointment_query()
            .where(owner == int(current_user.id))
            .order_by(
                case((Appointment.starts_at >= now, 0), else_=1),
                case((Appointment.starts_at >= now, Appointment.starts_at), else_=None).asc(),
                case((Appointment.starts_at < now, Appointment.starts_at), else_=None).desc(),
            )
            .limit(pages["per_page"])
            .offset((pages["page"] - 1) * pages["per_page"])
        ).all()
        upcoming = [row for row in rows if row.starts_at >= now]
        past = [row for row in rows if row.starts_at < now]
        return render_template(
            "booking_history.html",
            role="student",
            upcoming_appointments=[_student_appointment_view(row) for row in upcoming],
            past_appointments=[_student_appointment_view(row) for row in past],
            pagination=pages,
        )
    try:
        search = validate_search(request.args.get("q", ""))
    except InputValidationError:
        abort(400)
    status_filter = request.args.get("status", "").strip()
    if status_filter and status_filter not in _LECTURER_STATUSES:
        abort(400)

    conditions = [owner == int(current_user.id)]
    if status_filter:
        conditions.append(Appointment.status == status_filter)
    if search:
        pattern = f"%{search}%"
        conditions.append(
            or_(
                Appointment.student.has(User.username.ilike(pattern)),
                Appointment.public_reference.ilike(pattern),
                Appointment.purpose.ilike(pattern),
            )
        )
    total = db.session.scalar(
        select(func.count()).select_from(Appointment).where(*conditions)
    ) or 0
    pages = pagination(page_number(request.args.get("page")), total)
    query = _lecturer_appointment_query().where(*conditions)
    now = utc_now()
    if status_filter == "Pending":
        ordering = (Appointment.created_at.asc(), Appointment.id.asc())
    elif status_filter == "Accepted":
        upcoming = and_(Appointment.starts_at >= now)
        ordering = (
            case((upcoming, 0), else_=1),
            case((upcoming, Appointment.starts_at), else_=None).asc(),
            case((~upcoming, Appointment.starts_at), else_=None).desc(),
            Appointment.id.desc(),
        )
    elif status_filter:
        ordering = (Appointment.starts_at.desc(), Appointment.id.desc())
    else:
        pending = Appointment.status == "Pending"
        upcoming_accepted = and_(Appointment.status == "Accepted", Appointment.starts_at >= now)
        ordering = (
            case((pending, 0), (upcoming_accepted, 1), else_=2),
            case((pending, Appointment.created_at), else_=None).asc(),
            case((upcoming_accepted, Appointment.starts_at), else_=None).asc(),
            case((~pending & ~upcoming_accepted, Appointment.starts_at), else_=None).desc(),
            Appointment.id.desc(),
        )
    rows = db.session.scalars(
        query.order_by(*ordering)
        .limit(pages["per_page"])
        .offset((pages["page"] - 1) * pages["per_page"])
    ).all()
    return render_template(
        "booking_history.html",
        appointments=[_lecturer_appointment_view(row) for row in rows],
        pagination=pages,
        search=search,
        status_filter=status_filter,
        statuses=_LECTURER_STATUSES,
        display_role="student",
        role=current_user.role,
    )


def status_change(target):
    try:
        transition_appointment(
            int(request.form.get("id", "")),
            int(current_user.id),
            current_user.role,
            target,
            request.form.get("reason"),
        )
    except PermissionError:
        abort(403)
    except (BookingError, InvalidTransition, TypeError, ValueError):
        flash("That appointment status cannot be changed", "error")
        return redirect(_lecturer_return_location() if current_user.role == "teacher" else url_for("appointments.booking_history"))
    if current_user.role == "teacher":
        messages = {
            "Accepted": "Appointment accepted",
            "Rejected": "Appointment rejected",
            "Completed": "Appointment marked as completed",
            "No Show": "Appointment marked as no show",
        }
        flash(messages.get(target, "Appointment updated"), "success")
        return redirect(_lecturer_return_location())
    return redirect(url_for("appointments.booking_history"))


@bp.post("/cancel_booking")
@role_required("student")
def cancel_booking():
    return status_change("Cancelled")


@bp.post("/reject_booking")
@role_required("teacher")
def reject_booking():
    return status_change("Rejected")


@bp.post("/accept_booking")
@role_required("teacher")
def accept_booking():
    return status_change("Accepted")


@bp.post("/complete_booking")
@role_required("teacher")
def complete_booking():
    return status_change("Completed")


@bp.post("/no_show_booking")
@role_required("teacher")
def no_show_booking():
    return status_change("No Show")

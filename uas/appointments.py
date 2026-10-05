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
from sqlalchemy import select

from .booking_service import (
    BookingConflict,
    BookingError,
    InvalidTransition,
    create_booking,
    slot_is_available,
    transition_appointment,
)
from .common import appointment_view, role_required, university_zone
from .content_service import load_content
from .extensions import db
from .models import Appointment, Availability, User

bp = Blueprint("appointments", __name__)


@bp.get("/appointment")
@role_required("student")
def appointment():
    return render_template("appointment.html")


@bp.get("/appointment2")
@role_required("student")
def appointment2():
    lecturers = [
        {"id": u.id, "username": u.username}
        for u in db.session.scalars(
            select(User).where(User.role == "teacher", User.active.is_(True)).order_by(User.username)
        )
    ]
    return render_template("appointment2.html", lecturers=lecturers)


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
                    "label": f"{local_start:%H:%M} - {local_end:%H:%M}",
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
    except BookingConflict as exc:
        flash(str(exc), "error")
        return redirect(url_for("appointments.appointment2"))
    except (BookingError, TypeError, ValueError):
        flash("The selected appointment is invalid", "error")
        return redirect(url_for("appointments.appointment2"))
    session["last_booking_reference"] = reference
    flash("Booking created successfully", "success")
    return redirect(url_for("appointments.invoice", reference=reference))


@bp.get("/invoice")
@role_required("student")
def invoice():
    reference = request.args.get("reference") or session.get("last_booking_reference")
    row = db.session.scalar(
        select(Appointment).where(
            Appointment.public_reference == reference, Appointment.student_id == int(current_user.id)
        )
    )
    if not row:
        abort(404)
    view = appointment_view(row)
    content = load_content()
    data = [
        row.id,
        current_user.username,
        row.student_id,
        row.lecturer.username,
        view["appointment_date"],
        view["appointment_time"],
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
    )


@bp.get("/bookinghistory")
@role_required("student", "teacher")
def booking_history():
    owner = Appointment.student_id if current_user.role == "student" else Appointment.lecturer_id
    rows = db.session.scalars(
        select(Appointment).where(owner == int(current_user.id)).order_by(Appointment.starts_at.desc())
    ).all()
    return render_template(
        "booking_history.html",
        appointments=[appointment_view(row) for row in rows],
        display_role="lecturer" if current_user.role == "student" else "student",
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

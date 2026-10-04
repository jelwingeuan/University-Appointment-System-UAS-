import calendar as month_calendar
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .common import (
    local_to_utc,
    lock_lecturer,
    role_required,
    transaction,
)
from .extensions import db
from .models import Appointment, Availability
from .validation import parse_positive_int

bp = Blueprint("calendar", __name__)


def generate_recurrence(start, recurrence_end, repeat_type):
    if recurrence_end < start or repeat_type not in {"", "weekly", "monthly"}:
        raise ValueError("Invalid recurrence range")
    if not repeat_type:
        return [start]
    result, current, anchor = [], start, start.day
    while current <= recurrence_end:
        result.append(current)
        if len(result) > 370:
            raise ValueError("Too many availability windows")
        if repeat_type == "weekly":
            current += timedelta(weeks=1)
        else:
            month = current.month + 1
            year = current.year
            if month == 13:
                month, year = 1, year + 1
            current = current.replace(
                year=year, month=month, day=min(anchor, month_calendar.monthrange(year, month)[1])
            )
    return result


@bp.route("/calendar_record", methods=["GET", "POST"])
@role_required("teacher")
def calendar_record():
    if request.method == "GET":
        return redirect(url_for("calendar.events_page"))
    try:
        start_date = datetime.strptime(request.form.get("event_date", ""), "%Y-%m-%d").date()  # noqa: DTZ007
        end_date = datetime.strptime(request.form.get("end_date", ""), "%Y-%m-%d").date()  # noqa: DTZ007
        start_time = datetime.strptime(request.form.get("start_time", ""), "%H:%M").time()  # noqa: DTZ007
        end_time = datetime.strptime(request.form.get("end_time", ""), "%H:%M").time()  # noqa: DTZ007
        slot_minutes = parse_positive_int(request.form.get("slot_size"), "slot_size", minimum=5, maximum=240)
        repeat_type = request.form.get("repeat_type", "")
        start = datetime.combine(start_date, start_time)
        end = datetime.combine(start_date, end_time)
        duration_minutes = int((end - start).total_seconds() // 60)
        if (
            end <= start
            or duration_minutes > 1440
            or duration_minutes % slot_minutes
        ):
            raise ValueError("Invalid slot duration")
        occurrences = generate_recurrence(start, datetime.combine(end_date, start_time), repeat_type)
        with transaction() as db_session:
            lock_lecturer(db_session, int(current_user.id))
            for occurrence in occurrences:
                occurrence_end = occurrence + (end - start)
                db_session.add(
                    Availability(
                        lecturer_id=int(current_user.id),
                        starts_at=local_to_utc(occurrence),
                        ends_at=local_to_utc(occurrence_end),
                        slot_minutes=slot_minutes,
                    )
                )
            db_session.flush()
    except (TypeError, ValueError, IntegrityError):
        flash("Availability details are invalid or duplicate an existing window", "error")
        return redirect(url_for("calendar.events_page"))
    return redirect(url_for("calendar.events_page"))


@bp.get("/calendar")
@role_required("teacher")
def events_page():
    return render_template("calendar.html")


@bp.get("/events")
@role_required("teacher")
def events():
    owner = int(current_user.id)
    windows = db.session.scalars(
        select(Availability).where(Availability.lecturer_id == owner).order_by(Availability.starts_at)
    ).all()
    rows = db.session.scalars(
        select(Appointment)
        .where(Appointment.lecturer_id == owner, Appointment.status == "Accepted")
        .order_by(Appointment.starts_at)
    ).all()
    result = [
        {
            "id": f"availability-{row.id}",
            "title": "Consultation Hour",
            "start": row.starts_at.isoformat(),
            "end": row.ends_at.isoformat(),
            "extendedProps": {"availability_id": row.id, "kind": "availability"},
        }
        for row in windows
    ]
    result.extend(
        {
            "id": f"appointment-{row.id}",
            "title": f"Appointment with {row.student.username}",
            "start": row.starts_at.isoformat(),
            "end": row.ends_at.isoformat(),
            "extendedProps": {"kind": "appointment"},
        }
        for row in rows
    )
    return jsonify(result)


@bp.post("/delete_event")
@role_required("teacher")
def delete_event():
    try:
        availability_id = int(request.form.get("availability_id", ""))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid availability"}), 400
    try:
        with transaction() as db_session:
            window = db_session.get(Availability, availability_id)
            if not window or window.lecturer_id != int(current_user.id):
                abort(404)
            db_session.delete(window)
    except IntegrityError:
        return jsonify({"status": "error", "message": "Availability with bookings cannot be deleted"}), 409
    return jsonify({"status": "success"})

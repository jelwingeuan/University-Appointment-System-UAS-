import calendar as month_calendar
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    abort,
    current_app,
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
from sqlalchemy.orm import joinedload

from .common import (
    aware_datetime,
    local_to_utc,
    lock_lecturer,
    role_required,
    transaction,
    university_zone,
    utc_now,
)
from .extensions import db
from .models import Appointment, Availability
from .validation import parse_positive_int

bp = Blueprint("calendar", __name__)


class AvailabilityOverlap(ValueError):
    pass


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
    repeat_type = request.form.get("repeat_type", "")
    try:
        raw_start_date = request.form.get("event_date", "")
        start_date = datetime.strptime(raw_start_date, "%Y-%m-%d").date()  # noqa: DTZ007
        raw_end_date = request.form.get("end_date", "")
        if raw_end_date:
            end_date = datetime.strptime(raw_end_date, "%Y-%m-%d").date()  # noqa: DTZ007
        elif repeat_type:
            raise ValueError("A recurring availability needs an end date")
        else:
            end_date = start_date
        start_time = datetime.strptime(request.form.get("start_time", ""), "%H:%M").time()  # noqa: DTZ007
        end_time = datetime.strptime(request.form.get("end_time", ""), "%H:%M").time()  # noqa: DTZ007
        slot_minutes = parse_positive_int(request.form.get("slot_size"), "slot_size", minimum=5, maximum=240)
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
                starts_at = local_to_utc(occurrence)
                ends_at = local_to_utc(occurrence_end)
                conflict = db_session.scalar(
                    select(Availability.id).where(
                        Availability.lecturer_id == int(current_user.id),
                        Availability.active.is_(True),
                        Availability.starts_at < ends_at,
                        Availability.ends_at > starts_at,
                    ).limit(1)
                )
                if conflict:
                    raise AvailabilityOverlap("Availability windows cannot overlap")
                db_session.add(
                    Availability(
                        lecturer_id=int(current_user.id),
                        starts_at=starts_at,
                        ends_at=ends_at,
                        slot_minutes=slot_minutes,
                    )
                )
            db_session.flush()
    except AvailabilityOverlap:
        if repeat_type:
            flash("This recurring schedule conflicts with an existing availability window, so no dates were added.", "error")
        else:
            flash("This availability overlaps an existing availability window.", "error")
        return redirect(url_for("calendar.events_page"))
    except IntegrityError:
        if repeat_type:
            flash("This recurring schedule conflicts with an existing availability window, so no dates were added.", "error")
        else:
            flash("This availability overlaps an existing availability window.", "error")
        return redirect(url_for("calendar.events_page"))
    except (TypeError, ValueError):
        flash("Enter a valid date, time, slot size, and recurrence range.", "error")
        return redirect(url_for("calendar.events_page"))
    flash("Availability added.", "success")
    return redirect(url_for("calendar.events_page"))


@bp.get("/calendar")
@role_required("teacher")
def events_page():
    calendar_today = utc_now().astimezone(university_zone()).date().isoformat()
    return render_template(
        "calendar.html",
        university_timezone=current_app.config["UNIVERSITY_TIMEZONE"],
        calendar_today=calendar_today,
    )


@bp.get("/events")
@role_required("teacher")
def events():
    owner = int(current_user.id)
    start_value, end_value = request.args.get("start"), request.args.get("end")
    if bool(start_value) != bool(end_value):
        return jsonify({"error": "Both calendar range boundaries are required."}), 400
    starts_at = ends_at = None
    if start_value and end_value:
        try:
            start_local = datetime.fromisoformat(start_value)
            end_local = datetime.fromisoformat(end_value)
            starts_at = aware_datetime(start_local) if start_local.tzinfo else local_to_utc(start_local)
            ends_at = aware_datetime(end_local) if end_local.tzinfo else local_to_utc(end_local)
        except (TypeError, ValueError):
            return jsonify({"error": "Calendar range must use timezone-aware timestamps."}), 400
        if ends_at <= starts_at or ends_at - starts_at > timedelta(days=62):
            return jsonify({"error": "Calendar range is invalid."}), 400

    availability_filters = [Availability.lecturer_id == owner, Availability.active.is_(True)]
    appointment_filters = [Appointment.lecturer_id == owner, Appointment.status == "Accepted"]
    if starts_at is not None:
        availability_filters.extend((Availability.starts_at < ends_at, Availability.ends_at > starts_at))
        appointment_filters.extend((Appointment.starts_at < ends_at, Appointment.ends_at > starts_at))
    windows = db.session.scalars(
        select(Availability).where(*availability_filters).order_by(Availability.starts_at)
    ).all()
    window_ids = [row.id for row in windows]
    referenced_ids = set()
    if window_ids:
        referenced_ids = set(
            db.session.scalars(
                select(Appointment.availability_id)
                .where(Appointment.availability_id.in_(window_ids))
                .distinct()
            ).all()
        )
    rows = db.session.scalars(
        select(Appointment)
        .options(joinedload(Appointment.student))
        .where(*appointment_filters)
        .order_by(Appointment.starts_at)
    ).all()
    result = [
        {
            "id": f"availability-{row.id}",
            "title": "Availability",
            "start": row.starts_at.astimezone(university_zone()).isoformat(),
            "end": row.ends_at.astimezone(university_zone()).isoformat(),
            "classNames": ["uas-event-availability"],
            "extendedProps": {
                "availability_id": row.id,
                "kind": "availability",
                "has_appointments": row.id in referenced_ids,
            },
        }
        for row in windows
    ]
    result.extend(
        {
            "id": f"appointment-{row.public_reference}",
            "title": row.student.username,
            "start": row.starts_at.astimezone(university_zone()).isoformat(),
            "end": row.ends_at.astimezone(university_zone()).isoformat(),
            "classNames": ["uas-event-appointment"],
            "extendedProps": {
                "kind": "appointment",
                "public_reference": row.public_reference,
                "detail_url": url_for("appointments.lecturer_detail", public_reference=row.public_reference),
            },
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
        return jsonify({"status": "error", "message": "This availability contains appointments and cannot be removed."}), 409
    return jsonify({"status": "success"})

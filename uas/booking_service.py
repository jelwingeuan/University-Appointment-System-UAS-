from datetime import timedelta

from sqlalchemy import select

from .common import lock_lecturer, transaction, utc_now
from .models import Appointment, Availability, Status, User


class BookingError(ValueError):
    pass


class BookingConflict(BookingError):
    pass


class InvalidTransition(BookingError):
    pass


def parse_requested_time(value):
    from .common import aware_datetime

    try:
        return aware_datetime(value)
    except (TypeError, ValueError) as exc:
        raise BookingError("Invalid appointment time") from exc


def _validate_slot(session, availability_id, requested, now=None):
    window = session.get(Availability, availability_id)
    if not window or window.lecturer.role != "teacher" or not window.lecturer.active:
        raise BookingError("Invalid availability")
    duration = timedelta(minutes=window.slot_minutes)
    end = requested + duration
    offset = (requested - window.starts_at).total_seconds()
    if (
        requested < window.starts_at
        or end > window.ends_at
        or offset < 0
        or offset % duration.total_seconds() != 0
        or requested <= (now or utc_now())
    ):
        raise BookingError("Selected time is outside the availability window")
    return window, end


def slot_is_available(availability_id, requested_start):
    try:
        requested = parse_requested_time(requested_start)
        with transaction() as session:
            window, end = _validate_slot(session, availability_id, requested)
            conflict = session.scalar(
                select(Appointment.id)
                .where(
                    Appointment.lecturer_id == window.lecturer_id,
                    Appointment.status.in_((Status.PENDING.value, Status.ACCEPTED.value)),
                    Appointment.starts_at < end,
                    Appointment.ends_at > requested,
                )
                .limit(1)
            )
            return conflict is None
    except BookingError:
        return False


def create_booking(student_id, availability_id, requested_start, purpose):
    purpose = (purpose or "").strip()
    if not purpose or len(purpose) > 500:
        raise BookingError("Purpose is required and must be 500 characters or fewer")
    try:
        requested = parse_requested_time(requested_start)
        with transaction() as session:
            student = session.get(User, student_id)
            if not student or not student.active or student.role != "student":
                raise BookingError("Invalid student")
            window = session.get(Availability, availability_id)
            if not window:
                raise BookingError("Invalid availability")
            lock_lecturer(session, window.lecturer_id)
            window, end = _validate_slot(session, availability_id, requested)
            conflict = session.scalar(
                select(Appointment.id)
                .where(
                    Appointment.lecturer_id == window.lecturer_id,
                    Appointment.status.in_((Status.PENDING.value, Status.ACCEPTED.value)),
                    Appointment.starts_at < end,
                    Appointment.ends_at > requested,
                )
                .limit(1)
            )
            if conflict:
                raise BookingConflict("That appointment slot is no longer available")
            row = Appointment(
                student_id=student_id,
                lecturer_id=window.lecturer_id,
                availability_id=window.id,
                starts_at=requested,
                ends_at=end,
                purpose=purpose,
            )
            session.add(row)
            session.flush()
            return row.id, row.public_reference
    except BookingError:  # noqa: TRY203
        raise


def transition_appointment(appointment_id, actor_id, actor_role, target_status):
    allowed = {
        "teacher": {(Status.PENDING.value, Status.ACCEPTED.value), (Status.PENDING.value, Status.REJECTED.value)},
        "student": {(Status.PENDING.value, Status.CANCELLED.value), (Status.ACCEPTED.value, Status.CANCELLED.value)},
    }
    if actor_role not in allowed or target_status not in {
        Status.ACCEPTED.value,
        Status.REJECTED.value,
        Status.CANCELLED.value,
    }:
        raise InvalidTransition("Invalid appointment status")
    with transaction() as session:
        row = session.get(Appointment, appointment_id)
        if not row:
            raise BookingError("Appointment not found")
        lock_lecturer(session, row.lecturer_id)
        row = session.get(Appointment, appointment_id)
        owner_id = row.lecturer_id if actor_role == "teacher" else row.student_id
        if owner_id != int(actor_id):
            raise PermissionError("You cannot update this appointment")
        if (row.status, target_status) not in allowed[actor_role]:
            raise InvalidTransition("Invalid appointment status transition")
        row.status = target_status

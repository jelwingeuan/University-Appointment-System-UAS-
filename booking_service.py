import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from database import connect_database


BLOCKING_STATUSES = ("Pending", "Accepted")


class BookingError(ValueError):
    pass


class BookingConflict(BookingError):
    pass


class InvalidTransition(BookingError):
    pass


def _aware_datetime(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise BookingError("Invalid appointment time") from exc
    if parsed.tzinfo is None:
        raise BookingError("Appointment time must include a timezone")
    return parsed.astimezone(timezone.utc)


def create_booking(database_path, student_id, availability_id, requested_start, purpose):
    purpose = (purpose or "").strip()
    if not 1 <= len(purpose) <= 500:
        raise BookingError("Purpose is required and must be 500 characters or fewer")

    requested = _aware_datetime(requested_start)
    connection = connect_database(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        student = connection.execute(
            "SELECT id FROM users WHERE id = ? AND role = 'student'", (student_id,)
        ).fetchone()
        availability = connection.execute(
            """
            SELECT a.*, u.role AS lecturer_role
            FROM availability a
            JOIN users u ON u.id = a.lecturer_id
            WHERE a.id = ?
            """,
            (availability_id,),
        ).fetchone()
        if not student or not availability or availability["lecturer_role"] != "teacher":
            raise BookingError("Invalid student or availability")

        window_start = _aware_datetime(availability["starts_at"])
        window_end = _aware_datetime(availability["ends_at"])
        slot = timedelta(minutes=availability["slot_minutes"])
        requested_end = requested + slot
        offset_seconds = (requested - window_start).total_seconds()
        if (
            requested < window_start
            or requested_end > window_end
            or offset_seconds < 0
            or offset_seconds % slot.total_seconds() != 0
        ):
            raise BookingError("Selected time is outside the availability window")

        conflict = connection.execute(
            """
            SELECT 1 FROM appointments
            WHERE lecturer_id = ?
              AND status IN ('Pending', 'Accepted')
              AND starts_at < ?
              AND ends_at > ?
            LIMIT 1
            """,
            (availability["lecturer_id"], requested_end.isoformat(), requested.isoformat()),
        ).fetchone()
        if conflict:
            raise BookingConflict("That appointment slot is no longer available")

        reference = str(uuid.uuid4())
        cursor = connection.execute(
            """
            INSERT INTO appointments
                (public_reference, student_id, lecturer_id, availability_id,
                 starts_at, ends_at, purpose, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending')
            """,
            (
                reference,
                student_id,
                availability["lecturer_id"],
                availability_id,
                requested.isoformat(),
                requested_end.isoformat(),
                purpose,
            ),
        )
        connection.commit()
        return cursor.lastrowid, reference
    except (BookingError, sqlite3.Error):
        connection.rollback()
        raise
    finally:
        connection.close()


def slot_is_available(database_path, availability_id, requested_start):
    connection = connect_database(database_path)
    try:
        availability = connection.execute(
            "SELECT * FROM availability WHERE id = ?", (availability_id,)
        ).fetchone()
        if not availability:
            return False
        requested = _aware_datetime(requested_start)
        window_start = _aware_datetime(availability["starts_at"])
        window_end = _aware_datetime(availability["ends_at"])
        slot = timedelta(minutes=availability["slot_minutes"])
        requested_end = requested + slot
        if (
            requested < window_start
            or requested_end > window_end
            or (requested - window_start).total_seconds() % slot.total_seconds() != 0
        ):
            return False
        return connection.execute(
            """
            SELECT 1 FROM appointments
            WHERE lecturer_id = ?
              AND status IN ('Pending', 'Accepted')
              AND starts_at < ?
              AND ends_at > ?
            LIMIT 1
            """,
            (availability["lecturer_id"], requested_end.isoformat(), requested.isoformat()),
        ).fetchone() is None
    finally:
        connection.close()


def transition_appointment(database_path, appointment_id, actor_id, actor_role, target_status):
    allowed = {
        "teacher": {("Pending", "Accepted"), ("Pending", "Rejected")},
        "student": {("Pending", "Cancelled"), ("Accepted", "Cancelled")},
    }
    if target_status not in {"Accepted", "Rejected", "Cancelled"}:
        raise InvalidTransition("Invalid appointment status")

    connection = connect_database(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        appointment = connection.execute(
            "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
        ).fetchone()
        if not appointment:
            raise BookingError("Appointment not found")
        owner_field = "lecturer_id" if actor_role == "teacher" else "student_id"
        if actor_role not in allowed or appointment[owner_field] != actor_id:
            raise PermissionError("You cannot update this appointment")
        if (appointment["status"], target_status) not in allowed[actor_role]:
            raise InvalidTransition("Invalid appointment status transition")
        connection.execute(
            "UPDATE appointments SET status = ? WHERE id = ?", (target_status, appointment_id)
        )
        connection.commit()
    except (BookingError, PermissionError, sqlite3.Error):
        connection.rollback()
        raise
    finally:
        connection.close()

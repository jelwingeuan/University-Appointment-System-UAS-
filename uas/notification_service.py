from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from .common import transaction, university_zone, utc_now
from .models import (
    Appointment,
    Notification,
    NotificationPreference,
    NotificationType,
    Status,
)


@dataclass(frozen=True)
class PreferenceValues:
    email_updates: bool = True
    reminder_24h: bool = True
    reminder_1h: bool = True


_EVENT_COPY = {
    NotificationType.APPOINTMENT_REQUESTED.value: (
        "New appointment request",
        "A student requested an appointment for",
    ),
    NotificationType.APPOINTMENT_ACCEPTED.value: (
        "Appointment accepted",
        "Your appointment on",
    ),
    NotificationType.APPOINTMENT_REJECTED.value: (
        "Appointment request declined",
        "The lecturer declined your request for",
    ),
    NotificationType.APPOINTMENT_CANCELLED.value: (
        "Appointment cancelled",
        "A student cancelled the appointment on",
    ),
}


def preferences_for(session, user_id):
    row = session.get(NotificationPreference, int(user_id))
    if row is None:
        return PreferenceValues()
    return PreferenceValues(row.email_updates, row.reminder_24h, row.reminder_1h)


def update_preferences(session, user_id, *, email_updates, reminder_24h, reminder_1h):
    row = session.get(NotificationPreference, int(user_id))
    if row is None:
        row = NotificationPreference(user_id=int(user_id))
        session.add(row)
    row.email_updates = bool(email_updates)
    row.reminder_24h = bool(reminder_24h)
    row.reminder_1h = bool(reminder_1h)
    return row


def _appointment_time(appointment):
    start = appointment.starts_at.astimezone(university_zone())
    end = appointment.ends_at.astimezone(university_zone())
    date = start.strftime("%a, %d %b %Y")
    time = f"{start.strftime('%I:%M %p').lstrip('0')} - {end.strftime('%I:%M %p').lstrip('0')}"
    return date, time


def _reminder_enabled(preferences, offset_minutes):
    return preferences.reminder_24h if offset_minutes == 1440 else preferences.reminder_1h


def create_notification(
    session,
    *,
    user_id,
    appointment,
    notification_type,
    deduplication_key,
    title,
    message,
    reminder_offset_minutes=None,
):
    notification = Notification(
        user_id=int(user_id),
        appointment_id=appointment.id,
        deduplication_key=deduplication_key,
        type=str(notification_type),
        title=title,
        message=message,
        reminder_offset_minutes=reminder_offset_minutes,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(notification)
    session.flush()

    from flask import current_app

    if not current_app.config.get("APPOINTMENT_MAIL_DELIVERY_FACTORY"):
        return notification, None
    preferences = preferences_for(session, user_id)
    if not preferences.email_updates:
        return notification, None
    if reminder_offset_minutes and not _reminder_enabled(preferences, reminder_offset_minutes):
        return notification, None

    from .models import NotificationDelivery

    delivery = NotificationDelivery(
        notification_id=notification.id,
        next_attempt_at=utc_now(),
    )
    session.add(delivery)
    session.flush()
    return notification, delivery.id


def notify_appointment_event(session, appointment, event_type):
    """Persist in-app notification and optional email intent in the caller's transaction."""
    event_type = str(event_type)
    if event_type not in _EVENT_COPY:
        return []
    date, time = _appointment_time(appointment)
    title, prefix = _EVENT_COPY[event_type]
    message = f"{prefix} {date} at {time}."
    if event_type == NotificationType.APPOINTMENT_CANCELLED.value:
        recipient_id = (
            appointment.lecturer_id
            if appointment.cancelled_by_user_id == appointment.student_id
            else appointment.student_id
        )
    else:
        recipient_id = (
            appointment.lecturer_id
            if event_type == NotificationType.APPOINTMENT_REQUESTED.value
            else appointment.student_id
        )
    _, delivery_id = create_notification(
        session,
        user_id=recipient_id,
        appointment=appointment,
        notification_type=event_type,
        deduplication_key=f"appointment:{appointment.id}:{event_type}:{recipient_id}",
        title=title,
        message=message,
    )
    return [delivery_id] if delivery_id else []


def reminder_notification(session, appointment, recipient_id, offset_minutes):
    if offset_minutes not in {60, 1440}:
        return None
    preferences = preferences_for(session, recipient_id)
    if not _reminder_enabled(preferences, offset_minutes):
        return False, None
    date, time = _appointment_time(appointment)
    title = "Appointment tomorrow" if offset_minutes == 1440 else "Appointment in 1 hour"
    message = f"You have an appointment on {date} at {time}."
    key = f"appointment:{appointment.id}:reminder:{offset_minutes}:{recipient_id}"
    _, delivery_id = create_notification(
        session,
        user_id=recipient_id,
        appointment=appointment,
        notification_type=NotificationType.APPOINTMENT_REMINDER.value,
        deduplication_key=key,
        title=title,
        message=message,
        reminder_offset_minutes=offset_minutes,
    )
    return True, delivery_id


def process_due_reminders(*, now=None, limit=500):
    now = now or utc_now()
    upper = now + timedelta(days=1)
    delivery_ids = []
    created = 0
    with transaction() as session:
        appointments = session.scalars(
            select(Appointment)
            .options(
                joinedload(Appointment.student),
                joinedload(Appointment.lecturer),
            )
            .where(
                Appointment.status == Status.ACCEPTED.value,
                Appointment.starts_at > now,
                Appointment.starts_at <= upper,
                or_(
                    Appointment.starts_at <= now + timedelta(days=1),
                    Appointment.starts_at <= now + timedelta(hours=1),
                ),
            )
            .order_by(Appointment.starts_at, Appointment.id)
            .limit(limit)
            .with_for_update(of=Appointment, skip_locked=True)
        ).all()
        if not appointments:
            return 0, []

        appointment_ids = [row.id for row in appointments]
        existing = set(
            session.scalars(
                select(Notification.deduplication_key).where(
                    Notification.appointment_id.in_(appointment_ids),
                    Notification.type == NotificationType.APPOINTMENT_REMINDER.value,
                )
            ).all()
        )
        for appointment in appointments:
            for offset in (1440, 60):
                if appointment.starts_at - timedelta(minutes=offset) > now:
                    continue
                if offset == 1440 and appointment.starts_at - now <= timedelta(hours=1):
                    continue
                for recipient_id in (appointment.student_id, appointment.lecturer_id):
                    key = f"appointment:{appointment.id}:reminder:{offset}:{recipient_id}"
                    if key in existing:
                        continue
                    was_created, delivery_id = reminder_notification(session, appointment, recipient_id, offset)
                    if not was_created:
                        continue
                    if delivery_id:
                        delivery_ids.append(delivery_id)
                    created += 1
                    existing.add(key)
    return created, delivery_ids


def notification_for_display(row, role):
    from flask import url_for

    appointment = row.appointment
    open_url = None
    if appointment is not None:
        if role == "student" and appointment.student_id == row.user_id:
            open_url = url_for("appointments.invoice", reference=appointment.public_reference)
        elif role == "teacher" and appointment.lecturer_id == row.user_id:
            open_url = url_for(
                "appointments.lecturer_detail", public_reference=appointment.public_reference
            )
    icon = {
        NotificationType.APPOINTMENT_REQUESTED.value: "fa-calendar-plus",
        NotificationType.APPOINTMENT_ACCEPTED.value: "fa-circle-check",
        NotificationType.APPOINTMENT_REJECTED.value: "fa-circle-xmark",
        NotificationType.APPOINTMENT_CANCELLED.value: "fa-calendar-xmark",
        NotificationType.APPOINTMENT_REMINDER.value: "fa-clock",
    }.get(row.type, "fa-bell")
    created = row.created_at.astimezone(university_zone())
    delta = max(0, int((utc_now() - row.created_at).total_seconds()))
    if delta < 60:
        relative = "Just now"
    elif delta < 3600:
        relative = f"{delta // 60} min ago"
    elif delta < 86400:
        relative = f"{delta // 3600} hr ago"
    elif delta < 172800:
        relative = "Yesterday"
    else:
        relative = created.strftime("%d %b %Y")
    return {
        "id": row.id,
        "title": row.title,
        "message": row.message,
        "read": row.read_at is not None,
        "icon": icon,
        "created_at": created,
        "relative_time": relative,
        "open_url": open_url,
    }

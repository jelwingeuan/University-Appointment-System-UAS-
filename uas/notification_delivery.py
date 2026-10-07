from dataclasses import dataclass
from datetime import timedelta
from importlib import import_module
from urllib.parse import quote, urlencode
from uuid import uuid4

from flask import current_app
from sqlalchemy import or_, select, update
from sqlalchemy.orm import joinedload

from .common import transaction, utc_now
from .extensions import db
from .models import (
    DeliveryStatus,
    Notification,
    NotificationDelivery,
    NotificationType,
    SiteSettings,
    Status,
)
from .notification_service import _reminder_enabled, preferences_for

_MAX_ATTEMPTS = 5
_RETRY_DELAYS = (60, 300, 1800, 7200)
_CLAIM_LEASE = timedelta(minutes=5)
_QUEUE_VISIBILITY = timedelta(minutes=5)


@dataclass(frozen=True)
class AppointmentEmail:
    to_address: str
    subject: str
    text_body: str
    html_body: str
    idempotency_key: str


class EmailDeliveryError(Exception):
    def __init__(self, safe_code="provider_error", *, retryable=True):
        super().__init__(safe_code)
        self.safe_code = safe_code if safe_code in {"timeout", "rate_limited", "rejected", "provider_error"} else "provider_error"
        self.retryable = bool(retryable)


def _redis_queue():
    from redis import Redis
    from rq import Queue

    uri = current_app.config.get("NOTIFICATION_QUEUE_REDIS_URL")
    if not uri:
        raise RuntimeError("NOTIFICATION_QUEUE_REDIS_URL must be configured for appointment email")
    connection = Redis.from_url(uri, socket_connect_timeout=2, socket_timeout=2)
    return Queue("uas-notifications", connection=connection), connection


def _mark_enqueued(delivery_id):
    now = utc_now()
    with transaction() as session:
        session.execute(
            update(NotificationDelivery)
            .where(
                NotificationDelivery.id == int(delivery_id),
                NotificationDelivery.status == DeliveryStatus.PENDING.value,
            )
            .values(enqueued_at=now)
        )


def enqueue_delivery_ids(delivery_ids):
    if not delivery_ids or not current_app.config.get("APPOINTMENT_MAIL_DELIVERY_FACTORY"):
        return 0
    try:
        queue, _ = _redis_queue()
    except Exception as exc:  # noqa: BLE001 - queueing is deliberately best-effort after commit.
        current_app.logger.warning(
            "notification queue unavailable",
            extra={"event": "notification.enqueue", "status": "unavailable", "error_type": type(exc).__name__},
        )
        return 0

    queued = 0
    for delivery_id in dict.fromkeys(int(value) for value in delivery_ids):
        try:
            queue.enqueue(
                "uas.notification_delivery.deliver_notification_email_job",
                delivery_id,
                job_id=f"uas-notification-{delivery_id}-{uuid4().hex}",
                job_timeout=120,
                result_ttl=0,
                failure_ttl=3600,
            )
            _mark_enqueued(delivery_id)
            queued += 1
        except Exception as exc:  # noqa: BLE001 - preserve outbox intent if a Redis/DB enqueue step fails.
            current_app.logger.warning(
                "notification delivery enqueue failed",
                extra={
                    "event": "notification.enqueue",
                    "delivery_id": delivery_id,
                    "channel": "email",
                    "status": "pending",
                    "error_type": type(exc).__name__,
                },
            )
    return queued


def _retry_delay(attempts):
    return _RETRY_DELAYS[min(max(attempts - 1, 0), len(_RETRY_DELAYS) - 1)]


def _recover_expired_claims(now, limit):
    with transaction() as session:
        expired = session.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status == DeliveryStatus.PROCESSING.value,
                NotificationDelivery.claim_expires_at <= now,
            )
            .order_by(NotificationDelivery.claim_expires_at, NotificationDelivery.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for delivery in expired:
            delivery.claim_token = None
            delivery.claim_expires_at = None
            delivery.enqueued_at = None
            delivery.last_error_code = "worker_timeout"
            if delivery.attempts >= _MAX_ATTEMPTS:
                delivery.status = DeliveryStatus.FAILED.value
            else:
                delivery.status = DeliveryStatus.PENDING.value
                delivery.next_attempt_at = now + timedelta(seconds=_retry_delay(delivery.attempts))
        return len(expired)


def dispatch_pending_deliveries(*, now=None, limit=200):
    if not current_app.config.get("APPOINTMENT_MAIL_DELIVERY_FACTORY"):
        return 0
    now = now or utc_now()
    _recover_expired_claims(now, limit)
    with db.engine.connect() as connection:
        ids = connection.execute(
            select(NotificationDelivery.id)
            .where(
                NotificationDelivery.status == DeliveryStatus.PENDING.value,
                NotificationDelivery.next_attempt_at <= now,
                or_(
                    NotificationDelivery.enqueued_at.is_(None),
                    NotificationDelivery.enqueued_at <= now - _QUEUE_VISIBILITY,
                ),
            )
            .order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
            .limit(limit)
        ).scalars().all()
    return enqueue_delivery_ids(ids)


def _safe_action_url(notification, user):
    if not notification.appointment:
        return None
    appointment = notification.appointment
    origin = str(current_app.config.get("PUBLIC_APP_ORIGIN") or "").rstrip("/")
    if not origin:
        return None
    reference = str(appointment.public_reference)
    if user.role == "student" and appointment.student_id == user.id:
        path = f"/invoice?{urlencode({'reference': reference})}"
    elif user.role == "teacher" and appointment.lecturer_id == user.id:
        path = f"/lecturer/appointments/{quote(reference, safe='')}"
    else:
        return None
    return f"{origin}{path}"


def _appointment_status_matches(notification, appointment):
    expected = {
        NotificationType.APPOINTMENT_REQUESTED.value: Status.PENDING.value,
        NotificationType.APPOINTMENT_ACCEPTED.value: Status.ACCEPTED.value,
        NotificationType.APPOINTMENT_REJECTED.value: Status.REJECTED.value,
        NotificationType.APPOINTMENT_CANCELLED.value: Status.CANCELLED.value,
        NotificationType.APPOINTMENT_REMINDER.value: Status.ACCEPTED.value,
    }.get(notification.type)
    return expected is not None and appointment.status == expected


def _subject_for(notification_type):
    return {
        NotificationType.APPOINTMENT_REQUESTED.value: "New university appointment request",
        NotificationType.APPOINTMENT_ACCEPTED.value: "Your university appointment was accepted",
        NotificationType.APPOINTMENT_REJECTED.value: "An update about your university appointment",
        NotificationType.APPOINTMENT_CANCELLED.value: "Your university appointment was cancelled",
        NotificationType.APPOINTMENT_REMINDER.value: "Reminder about your university appointment",
    }.get(notification_type, "University appointment update")


def _build_email(session, notification, user, delivery_id):
    settings = session.get(SiteSettings, 1)
    school_name = settings.school_name if settings else "Multimedia University"
    action_url = _safe_action_url(notification, user)
    context = {
        "school_name": school_name,
        "title": notification.title,
        "message": notification.message,
        "action_url": action_url,
    }
    return AppointmentEmail(
        to_address=user.email,
        subject=_subject_for(notification.type),
        text_body=current_app.jinja_env.get_template("emails/appointment_notification.txt").render(**context),
        html_body=current_app.jinja_env.get_template("emails/appointment_notification.html").render(**context),
        idempotency_key=f"uas-appointment-delivery-{delivery_id}",
    )


def _claim_delivery(delivery_id, now):
    claim_token = str(uuid4())
    snapshot = None
    with transaction() as session:
        delivery = session.scalar(
            select(NotificationDelivery)
            .where(NotificationDelivery.id == int(delivery_id))
            .with_for_update(skip_locked=True)
        )
        if not delivery or delivery.status in {
            DeliveryStatus.SENT.value,
            DeliveryStatus.FAILED.value,
            DeliveryStatus.SKIPPED.value,
        }:
            return None
        if delivery.status == DeliveryStatus.PROCESSING.value and delivery.claim_expires_at and delivery.claim_expires_at > now:
            return None
        if delivery.next_attempt_at > now:
            return None
        if delivery.attempts >= _MAX_ATTEMPTS:
            delivery.status = DeliveryStatus.FAILED.value
            delivery.last_error_code = delivery.last_error_code or "retry_limit"
            return None

        notification = session.scalar(
            select(Notification)
            .options(
                joinedload(Notification.user),
                joinedload(Notification.appointment),
            )
            .where(Notification.id == delivery.notification_id)
        )
        if not notification:
            delivery.status = DeliveryStatus.SKIPPED.value
            delivery.last_error_code = "notification_missing"
            return None
        user = notification.user
        appointment = notification.appointment
        invalid_code = None
        if not user.active:
            invalid_code = "inactive_recipient"
        elif current_app.config.get("REQUIRE_EMAIL_VERIFICATION") and not user.email_verified_at:
            invalid_code = "unverified_recipient"
        elif user.role not in {"student", "teacher"}:
            invalid_code = "unsupported_recipient"
        elif not appointment:
            invalid_code = "appointment_missing"
        elif not _appointment_status_matches(notification, appointment):
            invalid_code = "appointment_status_changed"
        else:
            preferences = preferences_for(session, user.id)
            if not preferences.email_updates:
                invalid_code = "email_preference_disabled"
            elif notification.type == NotificationType.APPOINTMENT_REMINDER.value and (
                appointment.status != Status.ACCEPTED.value
                or appointment.starts_at <= now
                or not _reminder_enabled(preferences, notification.reminder_offset_minutes)
            ):
                invalid_code = "reminder_not_eligible"

        if invalid_code:
            delivery.status = DeliveryStatus.SKIPPED.value
            delivery.last_error_code = invalid_code
            delivery.claim_token = None
            delivery.claim_expires_at = None
            return None

        delivery.status = DeliveryStatus.PROCESSING.value
        delivery.attempts += 1
        delivery.claim_token = claim_token
        delivery.claim_expires_at = now + _CLAIM_LEASE
        snapshot = (
            claim_token,
            _build_email(session, notification, user, delivery.id),
            delivery.id,
            notification.id,
            delivery.attempts,
        )
    return snapshot


def _finish_delivery(delivery_id, claim_token, now, *, error=None):
    with transaction() as session:
        delivery = session.scalar(
            select(NotificationDelivery)
            .where(NotificationDelivery.id == int(delivery_id))
            .with_for_update(skip_locked=True)
        )
        if not delivery or delivery.claim_token != claim_token:
            return None
        delivery.claim_token = None
        delivery.claim_expires_at = None
        delivery.enqueued_at = None
        if error is None:
            delivery.status = DeliveryStatus.SENT.value
            delivery.sent_at = now
            delivery.last_error_code = None
        elif not error.retryable or delivery.attempts >= _MAX_ATTEMPTS:
            delivery.status = DeliveryStatus.FAILED.value
            delivery.last_error_code = error.safe_code
        else:
            delivery.status = DeliveryStatus.PENDING.value
            delivery.next_attempt_at = now + timedelta(seconds=_retry_delay(delivery.attempts))
            delivery.last_error_code = error.safe_code
        return delivery.status


def _mail_sender():
    factory_path = current_app.config.get("APPOINTMENT_MAIL_DELIVERY_FACTORY")
    if not factory_path:
        raise RuntimeError("APPOINTMENT_MAIL_DELIVERY_FACTORY is not configured")
    sender = current_app.extensions.get("appointment_mail_sender")
    if sender is None:
        module_name, separator, factory_name = factory_path.partition(":")
        if not separator:
            raise RuntimeError("APPOINTMENT_MAIL_DELIVERY_FACTORY must use module:factory syntax")
        factory = getattr(import_module(module_name), factory_name)
        sender = factory(current_app)
        if not callable(sender):
            raise RuntimeError("Appointment email factory must return a callable")
        current_app.extensions["appointment_mail_sender"] = sender
    return sender


def deliver_notification_email(delivery_id):
    """RQ job entry point. The worker runs this function inside the Flask app context."""
    now = utc_now()
    claimed = _claim_delivery(delivery_id, now)
    if not claimed:
        return "not claimed"
    claim_token, email, claimed_id, notification_id, attempt = claimed
    try:
        _mail_sender()(email)
    except EmailDeliveryError as exc:
        failure = exc
    except Exception:  # noqa: BLE001 - provider failures are intentionally reduced to a safe error code.
        failure = EmailDeliveryError("provider_error", retryable=True)
    else:
        failure = None
    status = _finish_delivery(claimed_id, claim_token, utc_now(), error=failure)
    current_app.logger.info(
        "notification email delivery completed",
        extra={
            "event": "notification.delivery",
            "delivery_id": claimed_id,
            "notification_id": notification_id,
            "channel": "email",
            "attempt": attempt,
            "status": status or "stale_claim",
            "error_code": failure.safe_code if failure else None,
        },
    )
    return status or "stale claim"


def deliver_notification_email_job(delivery_id):
    """RQ entry point; each forked work horse gets its own Flask app context."""
    from app import app

    with app.app_context():
        return deliver_notification_email(delivery_id)


def notification_worker():
    queue, connection = _redis_queue()
    from rq import Worker

    Worker([queue], connection=connection).work(with_scheduler=False)

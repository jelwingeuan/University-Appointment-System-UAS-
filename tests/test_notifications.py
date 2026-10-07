from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock
from time import sleep

import pytest
from sqlalchemy import event, select

from tests.conftest import FIXED_NOW, login
from uas import booking_service
from uas.extensions import db
from uas.models import (
    Appointment,
    Availability,
    DeliveryStatus,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationType,
    Status,
    User,
)
from uas.notification_delivery import (
    EmailDeliveryError,
    _recover_expired_claims,
    deliver_notification_email,
    dispatch_pending_deliveries,
    enqueue_delivery_ids,
)
from uas.notification_service import (
    create_notification,
    process_due_reminders,
    update_preferences,
)


def _notification(appointment, user_id, *, key="test-event", kind=NotificationType.APPOINTMENT_REQUESTED.value):
    row, delivery_id = create_notification(
        db.session,
        user_id=user_id,
        appointment=appointment,
        notification_type=kind,
        deduplication_key=key,
        title="An appointment update",
        message="An appointment update is available.",
    )
    db.session.commit()
    return row, delivery_id


def _future_appointment(*, status=Status.ACCEPTED.value, hours=30):
    start = FIXED_NOW + timedelta(hours=hours)
    availability = Availability(
        lecturer_id=3,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        slot_minutes=30,
    )
    db.session.add(availability)
    db.session.flush()
    appointment = Appointment(
        student_id=1,
        lecturer_id=3,
        availability_id=availability.id,
        starts_at=start,
        ends_at=start + timedelta(minutes=30),
        purpose="Private purpose that must not be emailed",
        status=status,
    )
    db.session.add(appointment)
    db.session.commit()
    return appointment


def test_booking_and_transition_notifications_have_only_intended_recipients(client, app):
    from uas.booking_service import create_booking, transition_appointment

    appointment_id, _ = create_booking(1, 1, app.config["TEST_SLOT_START"], "Private purpose")
    assert db.session.scalar(select(Notification.user_id).where(Notification.type == "appointment_requested")) == 3
    assert db.session.scalar(select(Notification.id).where(Notification.user_id == 1)) is None
    assert db.session.scalar(select(Notification.id).where(Notification.user_id == 5)) is None

    transition_appointment(appointment_id, 3, "teacher", Status.ACCEPTED.value)
    assert db.session.scalar(
        select(Notification.id).where(
            Notification.user_id == 1,
            Notification.type == NotificationType.APPOINTMENT_ACCEPTED.value,
        )
    )
    assert db.session.scalar(
        select(Notification.id).where(
            Notification.user_id == 3,
            Notification.type == NotificationType.APPOINTMENT_ACCEPTED.value,
        )
    ) is None

    transition_appointment(appointment_id, 1, "student", Status.CANCELLED.value)
    assert db.session.scalar(
        select(Notification.id).where(
            Notification.user_id == 3,
            Notification.type == NotificationType.APPOINTMENT_CANCELLED.value,
        )
    )
    assert db.session.scalar(
        select(Notification.id).where(
            Notification.user_id == 1,
            Notification.type == NotificationType.APPOINTMENT_CANCELLED.value,
        )
    ) is None
    assert db.session.query(Notification).filter(Notification.message.contains("Private purpose")).count() == 0


def test_notification_insert_rolls_back_with_booking_transaction(app, monkeypatch):
    original = booking_service.notify_appointment_event

    def notify_then_fail(session, appointment, event_type):
        original(session, appointment, event_type)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(booking_service, "notify_appointment_event", notify_then_fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        booking_service.create_booking(1, 1, app.config["TEST_SLOT_START"], "Advice")
    assert db.session.query(Appointment).count() == 0
    assert db.session.query(Notification).count() == 0


def test_rejection_notifies_student_but_completion_and_no_show_do_not(app):
    first_start = app.config["TEST_SLOT_START"]
    rejected_id, _ = booking_service.create_booking(1, 1, first_start, "Review")
    booking_service.transition_appointment(rejected_id, 3, "teacher", Status.REJECTED.value)
    assert db.session.scalar(
        select(Notification.id).where(
            Notification.user_id == 1,
            Notification.type == NotificationType.APPOINTMENT_REJECTED.value,
        )
    )

    second_start = (FIXED_NOW + timedelta(days=7, hours=2, minutes=30)).isoformat()
    completed_id, _ = booking_service.create_booking(2, 1, second_start, "Completion")
    booking_service.transition_appointment(completed_id, 3, "teacher", Status.ACCEPTED.value)
    booking_service.transition_appointment(completed_id, 3, "teacher", Status.COMPLETED.value)
    assert db.session.scalar(
        select(Notification.id).where(Notification.type == "appointment_completed")
    ) is None

    third_start = (FIXED_NOW + timedelta(days=7, hours=3)).isoformat()
    no_show_id, _ = booking_service.create_booking(1, 1, third_start, "No show")
    booking_service.transition_appointment(no_show_id, 3, "teacher", Status.ACCEPTED.value)
    booking_service.transition_appointment(no_show_id, 3, "teacher", Status.NO_SHOW.value)
    assert db.session.scalar(
        select(Notification.id).where(Notification.type == "appointment_no_show")
    ) is None


def test_profile_preferences_default_enabled_and_can_be_saved(client, app):
    login(client, "student1@student.mmu.edu.my")
    markup = client.get("/profile").get_data(as_text=True)
    assert 'name="email_updates" value="1" checked' in markup
    assert 'name="reminder_24h" value="1" checked' in markup
    assert "not configured" in markup
    response = client.post("/profile/notification-preferences", data={})
    assert response.status_code == 302
    preferences = db.session.get(NotificationPreference, 1)
    assert preferences.email_updates is False
    assert preferences.reminder_24h is False
    assert preferences.reminder_1h is False
    client.post("/logout")
    login(client, "lecturer1@mmu.edu.my")
    assert client.get("/profile").status_code == 200
    client.post("/logout")
    login(client, "admin@mmu.edu.my")
    assert client.get("/profile").status_code == 200


def test_new_accounts_receive_a_persisted_default_preference_record(app, user_factory):
    student = user_factory(role="student")
    preferences = db.session.get(NotificationPreference, student.id)
    assert preferences is not None
    assert (preferences.email_updates, preferences.reminder_24h, preferences.reminder_1h) == (True, True, True)


def test_inbox_filters_paginates_marks_read_and_scopes_ids(client, app):
    appointment = _future_appointment()
    rows = []
    for index in range(27):
        row, _ = _notification(
            appointment,
            1,
            key=f"student-notice-{index}",
            kind=NotificationType.APPOINTMENT_REMINDER.value,
        )
        rows.append(row.id)
    other, _ = _notification(appointment, 2, key="other-user-notice")

    login(client, "student1@student.mmu.edu.my")
    all_page = client.get("/notifications")
    assert all_page.status_code == 200
    assert b"Page 1 of 2" in all_page.data
    assert b"All" in all_page.data and b"Unread" in all_page.data
    assert client.get("/notifications?view=unread&page=2").status_code == 200
    assert client.get("/notifications?view=unread&page=3").status_code == 200
    assert client.post(f"/notifications/{other.id}/read").status_code == 404
    assert client.post(f"/notifications/{other.id}/open").status_code == 404

    assert client.post(f"/notifications/{rows[0]}/read").status_code == 302
    assert db.session.get(Notification, rows[0]).read_at is not None
    assert client.post("/notifications/read-all").status_code == 302
    assert db.session.scalar(
        select(Notification.id).where(Notification.user_id == 1, Notification.read_at.is_(None))
    ) is None
    assert client.get("/notifications?view=invalid").status_code == 400

    client.post("/logout")
    login(client, "admin@mmu.edu.my")
    assert client.get("/notifications").status_code == 403


def test_open_notification_derives_role_safe_destination(client, app):
    appointment = _future_appointment()
    student_notice, _ = _notification(appointment, 1, key="student-open")
    lecturer_notice, _ = _notification(appointment, 3, key="lecturer-open")
    login(client, "student1@student.mmu.edu.my")
    response = client.post(f"/notifications/{student_notice.id}/open")
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/invoice?reference={appointment.public_reference}")
    db.session.expire_all()
    assert db.session.get(Notification, student_notice.id).read_at is not None
    client.post("/logout")
    login(client, "lecturer1@mmu.edu.my")
    response = client.post(f"/notifications/{lecturer_notice.id}/open")
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/lecturer/appointments/{appointment.public_reference}")


def test_notification_actions_require_csrf_when_enabled(client, app):
    appointment = _future_appointment()
    row, _ = _notification(appointment, 1)
    login(client, "student1@student.mmu.edu.my")
    app.config["WTF_CSRF_ENABLED"] = True
    assert client.post(f"/notifications/{row.id}/read").status_code == 400


def test_shell_preview_is_bounded_and_bell_hidden_when_empty(client, app):
    login(client, "student1@student.mmu.edu.my")
    assert b"app-notification-menu" not in client.get("/profile").data
    appointment = _future_appointment()
    for index in range(8):
        _notification(appointment, 1, key=f"preview-{index}")
    markup = client.get("/profile").get_data(as_text=True)
    assert 'class="app-notification-menu"' in markup
    assert markup.count("An appointment update is available.") == 5
    assert 'aria-label="Notifications. 8 unread"' in markup


def test_public_home_does_not_query_app_notification_preview(client, app):
    login(client, "student1@student.mmu.edu.my")
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "notifications" in statement.lower():
            statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", capture)
    try:
        assert client.get("/").status_code == 200
    finally:
        event.remove(db.engine, "before_cursor_execute", capture)
    assert statements == []


def test_reminders_are_accepted_only_preference_aware_and_deduplicated(app):
    pending = _future_appointment(status=Status.PENDING.value, hours=23)
    accepted = _future_appointment(status=Status.ACCEPTED.value, hours=22)
    one_hour = _future_appointment(status=Status.ACCEPTED.value, hours=0.5)
    update_preferences(db.session, 1, email_updates=True, reminder_24h=False, reminder_1h=True)
    update_preferences(db.session, 3, email_updates=True, reminder_24h=True, reminder_1h=True)
    db.session.commit()

    created, _ = process_due_reminders(now=FIXED_NOW)
    assert created == 3  # The 24-hour reminder is suppressed once the 1-hour window is reached.
    assert process_due_reminders(now=FIXED_NOW)[0] == 0
    created_rows = db.session.scalars(select(Notification).where(
        Notification.type == NotificationType.APPOINTMENT_REMINDER.value
    )).all()
    assert len(created_rows) == 3
    assert all(row.appointment_id in {accepted.id, one_hour.id} for row in created_rows)
    assert {row.user_id for row in created_rows if row.appointment_id == accepted.id} == {3}
    assert {row.user_id for row in created_rows if row.appointment_id == one_hour.id} == {1, 3}
    assert pending.id != accepted.id


def test_email_outbox_delivery_is_owned_generic_and_idempotent(app):
    app.config.update(
        APPOINTMENT_MAIL_DELIVERY_FACTORY="tests.test_notifications:unused_factory",
        PUBLIC_APP_ORIGIN="https://portal.example.edu",
    )
    appointment = _future_appointment()
    notice, delivery_id = _notification(
        appointment,
        1,
        key="accepted-email",
        kind=NotificationType.APPOINTMENT_ACCEPTED.value,
    )
    assert delivery_id
    sent = []
    app.extensions["appointment_mail_sender"] = sent.append
    assert deliver_notification_email(delivery_id) == DeliveryStatus.SENT.value
    assert len(sent) == 1
    email = sent[0]
    assert email.to_address == "student1@student.mmu.edu.my"
    assert "appointment" in email.subject.lower()
    assert appointment.public_reference in email.text_body
    assert "Private purpose" not in email.text_body + email.html_body
    assert email.idempotency_key == f"uas-appointment-delivery-{delivery_id}"
    assert deliver_notification_email(delivery_id) == "not claimed"
    delivery = db.session.get(NotificationDelivery, delivery_id)
    assert delivery.status == DeliveryStatus.SENT.value
    assert delivery.attempts == 1
    assert db.session.get(Notification, notice.id).appointment_id == appointment.id


def test_email_preferences_and_changed_status_suppress_delivery(app):
    app.config["APPOINTMENT_MAIL_DELIVERY_FACTORY"] = "tests.test_notifications:unused_factory"
    update_preferences(db.session, 1, email_updates=False, reminder_24h=True, reminder_1h=True)
    appointment = _future_appointment()
    _, disabled_delivery = _notification(
        appointment, 1, key="disabled-email", kind=NotificationType.APPOINTMENT_ACCEPTED.value
    )
    assert disabled_delivery is None

    update_preferences(db.session, 1, email_updates=True, reminder_24h=True, reminder_1h=True)
    db.session.commit()
    notice, delivery_id = _notification(
        appointment, 1, key="stale-accepted-email", kind=NotificationType.APPOINTMENT_ACCEPTED.value
    )
    appointment.status = Status.CANCELLED.value
    db.session.commit()
    app.extensions["appointment_mail_sender"] = lambda email: pytest.fail("stale email must not be sent")
    assert deliver_notification_email(delivery_id) == "not claimed"
    delivery = db.session.get(NotificationDelivery, delivery_id)
    assert delivery.status == DeliveryStatus.SKIPPED.value
    assert delivery.last_error_code == "appointment_status_changed"
    assert db.session.get(Notification, notice.id).id == notice.id


def test_redis_enqueue_failure_preserves_pending_outbox_row(app, monkeypatch):
    app.config["APPOINTMENT_MAIL_DELIVERY_FACTORY"] = "tests.test_notifications:unused_factory"
    appointment = _future_appointment()
    _, delivery_id = _notification(
        appointment, 1, key="redis-unavailable", kind=NotificationType.APPOINTMENT_ACCEPTED.value
    )

    def unavailable():
        raise ConnectionError("no redis")

    monkeypatch.setattr("uas.notification_delivery._redis_queue", unavailable)
    assert enqueue_delivery_ids([delivery_id]) == 0
    db.session.expire_all()
    delivery = db.session.get(NotificationDelivery, delivery_id)
    assert delivery.status == DeliveryStatus.PENDING.value
    assert delivery.enqueued_at is None


@pytest.mark.parametrize("failure", ["inactive", "unverified"])
def test_email_delivery_rechecks_account_eligibility(app, failure):
    app.config["APPOINTMENT_MAIL_DELIVERY_FACTORY"] = "tests.test_notifications:unused_factory"
    app.config["REQUIRE_EMAIL_VERIFICATION"] = True
    appointment = _future_appointment()
    _, delivery_id = _notification(
        appointment,
        1,
        key=f"eligibility-{failure}",
        kind=NotificationType.APPOINTMENT_ACCEPTED.value,
    )
    user = db.session.get(User, 1)
    if failure == "inactive":
        user.active = False
        user.email_verified_at = FIXED_NOW
    else:
        user.email_verified_at = None
    db.session.commit()
    app.extensions["appointment_mail_sender"] = lambda email: pytest.fail("ineligible email must not be sent")
    assert deliver_notification_email(delivery_id) == "not claimed"
    assert db.session.get(NotificationDelivery, delivery_id).status == DeliveryStatus.SKIPPED.value


def test_delivery_retries_with_bounded_backoff_and_stops_after_five_attempts(app):
    app.config["APPOINTMENT_MAIL_DELIVERY_FACTORY"] = "tests.test_notifications:unused_factory"
    clock = [FIXED_NOW]
    app.config["CLOCK"] = lambda: clock[0]
    appointment = _future_appointment()
    _, delivery_id = _notification(
        appointment, 1, key="retry-email", kind=NotificationType.APPOINTMENT_ACCEPTED.value
    )

    def fail(_email):
        raise EmailDeliveryError("timeout")

    app.extensions["appointment_mail_sender"] = fail
    expected = [60, 300, 1800, 7200]
    previous_due = FIXED_NOW
    for attempt in range(1, 6):
        result = deliver_notification_email(delivery_id)
        db.session.expire_all()
        delivery = db.session.get(NotificationDelivery, delivery_id)
        assert delivery.attempts == attempt
        if attempt < 5:
            assert result == DeliveryStatus.PENDING.value
            assert delivery.last_error_code == "timeout"
            clock[0] = delivery.next_attempt_at
            assert int((clock[0] - previous_due).total_seconds()) == expected[attempt - 1]
            previous_due = clock[0]
        else:
            assert result == DeliveryStatus.FAILED.value
            assert delivery.status == DeliveryStatus.FAILED.value
    assert db.session.get(NotificationDelivery, delivery_id).attempts == 5


def test_expired_worker_lease_is_recovered_and_pending_delivery_redispatched(app, monkeypatch):
    app.config["APPOINTMENT_MAIL_DELIVERY_FACTORY"] = "tests.test_notifications:unused_factory"
    appointment = _future_appointment()
    _, delivery_id = _notification(
        appointment, 1, key="expired-lease", kind=NotificationType.APPOINTMENT_ACCEPTED.value
    )
    delivery = db.session.get(NotificationDelivery, delivery_id)
    delivery.status = DeliveryStatus.PROCESSING.value
    delivery.attempts = 1
    delivery.claim_token = "expired-token"
    delivery.claim_expires_at = FIXED_NOW - timedelta(minutes=1)
    db.session.commit()
    assert _recover_expired_claims(FIXED_NOW, 10) == 1
    db.session.expire_all()
    assert db.session.get(NotificationDelivery, delivery_id).status == DeliveryStatus.PENDING.value
    assert db.session.get(NotificationDelivery, delivery_id).next_attempt_at == FIXED_NOW + timedelta(minutes=1)

    queued = []
    monkeypatch.setattr("uas.notification_delivery.enqueue_delivery_ids", lambda ids: queued.extend(ids) or len(ids))
    assert dispatch_pending_deliveries(now=FIXED_NOW + timedelta(minutes=2)) == 1
    assert queued == [delivery_id]


def test_two_workers_cannot_claim_one_delivery_concurrently(app):
    app.config["APPOINTMENT_MAIL_DELIVERY_FACTORY"] = "tests.test_notifications:unused_factory"
    appointment = _future_appointment()
    _, delivery_id = _notification(
        appointment, 1, key="concurrent-delivery", kind=NotificationType.APPOINTMENT_ACCEPTED.value
    )
    sent = []
    sent_lock = Lock()

    def provider(email):
        sleep(0.1)
        with sent_lock:
            sent.append(email.idempotency_key)

    app.extensions["appointment_mail_sender"] = provider

    def run_delivery():
        with app.app_context():
            return deliver_notification_email(delivery_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: run_delivery(), range(2)))
    assert sent == [f"uas-appointment-delivery-{delivery_id}"]
    assert outcomes.count(DeliveryStatus.SENT.value) == 1
    assert outcomes.count("not claimed") == 1

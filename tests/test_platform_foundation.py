from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import bcrypt
import pytest
from flask import g
from sqlalchemy import inspect, select, text

from app import create_app
from tests.conftest import login
from uas import booking_service as service
from uas.account_service import (
    bootstrap_admin,
    consume_account_token,
    deliver_account_token,
    issue_account_token,
    issue_lecturer_invitation,
    use_lecturer_invitation,
)
from uas.booking_service import BookingConflict, InvalidTransition, create_booking, transition_appointment
from uas.common import transaction
from uas.extensions import db
from uas.models import (
    AccountToken,
    Appointment,
    AppointmentStatusHistory,
    AuditLog,
    Availability,
    LecturerInvitation,
    SiteSettings,
    User,
)


class TestImageStorage:
    def save(self, key, content, content_type):
        pass

    def delete(self, key):
        pass

    def open(self, key):
        return None

    def url(self, key):
        return None


def storage_factory(_app):
    return TestImageStorage()


def mail_factory(app):
    def send(email, purpose, token):
        app.extensions.setdefault("test_outbox", []).append((email, purpose, token))

    return send


def test_health_and_readiness_do_not_expose_configuration(client):
    health = client.get("/health")
    ready = client.get("/ready")
    assert health.status_code == 200 and health.json == {"status": "ok"}
    assert ready.status_code == 200 and ready.json == {"ready": True}
    assert "DATABASE_URL" not in health.get_data(as_text=True)


def test_password_reset_request_does_not_reveal_account_presence(client):
    existing = client.post("/password-reset", data={"email": "student1@student.mmu.edu.my"})
    known_message = client.get(existing.headers["Location"]).get_data(as_text=True)
    client.post("/password-reset", data={"email": "nobody@student.mmu.edu.my"})
    unknown_message = client.get("/login").get_data(as_text=True)
    generic = "If that account can receive mail, password reset instructions have been sent."
    assert generic in known_message and generic in unknown_message


def test_account_mail_adapter_delivers_tokens_and_routes_complete_flows(client, app):
    app.config["MAIL_DELIVERY_FACTORY"] = "tests.test_platform_foundation:mail_factory"
    client.post("/password-reset", data={"email": "student1@student.mmu.edu.my"})
    reset_email, reset_purpose, reset_token = app.extensions["test_outbox"].pop()
    assert (reset_email, reset_purpose) == ("student1@student.mmu.edu.my", "password_reset")
    response = client.post(
        "/password-reset/complete",
        data={"token": reset_token, "password": "new account passphrase", "confirm_password": "new account passphrase"},
    )
    assert response.status_code == 302
    assert bcrypt.checkpw(
        b"new account passphrase", db.session.get(User, 1).password_hash.encode()
    )

    token = issue_account_token(1, "email_verification")
    assert deliver_account_token("student1@student.mmu.edu.my", "email_verification", token)
    assert app.extensions["test_outbox"].pop() == (
        "student1@student.mmu.edu.my",
        "email_verification",
        token,
    )
    response = client.post("/email-verification/complete", data={"token": token})
    assert response.status_code == 302
    db.session.expire_all()
    assert db.session.get(User, 1).email_verified_at is not None


def test_production_requires_postgres_shared_limits_and_durable_image_store(monkeypatch):
    from uas import config

    monkeypatch.setattr(config, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FLASK_SECRET_KEY", "a-production-test-secret-that-is-long-enough")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL must be explicitly configured"):
        create_app({"APP_ENV": "production"})

    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/should-not-be-used.db")
    with pytest.raises(RuntimeError, match="requires DATABASE_URL for PostgreSQL"):
        create_app({"APP_ENV": "production"})

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://uas:secret@localhost/uas")
    with pytest.raises(RuntimeError, match="shared Redis"):
        create_app({"APP_ENV": "production"})
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "redis://localhost:6379/1")
    with pytest.raises(RuntimeError, match="IMAGE_STORAGE_FACTORY"):
        create_app({"APP_ENV": "production"})

    monkeypatch.setenv("IMAGE_STORAGE_FACTORY", "tests.test_platform_foundation:storage_factory")
    monkeypatch.setenv("DEMO_ACCOUNT_PASSWORD", "must-not-load-in-production")
    app = create_app({"APP_ENV": "production", "DEBUG": True, "SESSION_COOKIE_SECURE": False})
    assert not app.debug
    assert app.config["SESSION_COOKIE_SECURE"]
    assert app.config["SESSION_PROTECTION"] == "strong"
    assert app.config["DEMO_ACCOUNT_PASSWORD"] is None

    monkeypatch.setenv("APPOINTMENT_MAIL_DELIVERY_FACTORY", "uas.dev_mail:create_sender")
    monkeypatch.setenv("PUBLIC_APP_ORIGIN", "https://uas.example.edu")
    monkeypatch.setenv("NOTIFICATION_QUEUE_REDIS_URL", "rediss://redis.example.edu:6379/2")
    with pytest.raises(RuntimeError, match="local development mailbox cannot be enabled in production"):
        create_app({"APP_ENV": "production"})


def test_database_migrations_upgrade_clean_db_and_current_head(tmp_path):
    app = create_app({"TESTING": True, "DATABASE_PATH": str(tmp_path / "migration.db")})
    runner = app.test_cli_runner()
    assert runner.invoke(args=["db", "upgrade"]).exit_code == 0
    with app.app_context():
        tables = set(inspect(db.engine).get_table_names())
        assert {"users", "appointments", "site_settings", "account_tokens", "audit_logs"} <= tables
    assert runner.invoke(args=["db", "upgrade"]).exit_code == 0
    with app.app_context():
        db.engine.dispose()


def test_upgrade_from_existing_0001_preserves_user_and_appointment_data(tmp_path):
    app = create_app({"TESTING": True, "DATABASE_PATH": str(tmp_path / "upgrade-existing.db")})
    runner = app.test_cli_runner()
    assert runner.invoke(args=["db", "upgrade", "0001_orm_schema"]).exit_code == 0
    with app.app_context():
        db.session.execute(text("INSERT INTO faculties (id, faculty_name) VALUES (1, 'FCI')"))
        db.session.execute(
            text(
                "INSERT INTO users (id, role, faculty_id, username, email, phone_number, password, active) "
                "VALUES (7, 'student', 1, 'Legacy Student', 'legacy@student.mmu.edu.my', '0100000007', 'hash', 1)"
            )
        )
        db.session.commit()
    assert runner.invoke(args=["db", "upgrade"]).exit_code == 0
    with app.app_context():
        user = db.session.get(User, 7)
        assert user.username == "Legacy Student"
        assert user.password_hash == "hash"
        assert user.active is True and user.created_at is not None
        assert user.session_version == 0
        db.engine.dispose()


def test_database_content_and_audit_are_atomic_and_json_stays_unchanged(client, app):
    original = Path(app.config["CONTENT_PATH"]).read_text(encoding="utf-8")
    login(client, "admin@mmu.edu.my")
    response = client.post(
        "/adminpageeditor",
        data={"home_content": "Updated text", "school_name": "MMU", "school_tel": "03-123", "school_email": "info@mmu.edu.my"},
    )
    assert response.status_code == 302
    db.session.expire_all()
    settings = db.session.get(SiteSettings, 1)
    assert settings.home_content == "Updated text"
    audit = db.session.scalar(select(AuditLog).where(AuditLog.action == "site_settings.updated"))
    assert audit and audit.actor_user_id == 5 and audit.metadata_json == {}
    assert Path(app.config["CONTENT_PATH"]).read_text(encoding="utf-8") == original


def test_account_tokens_are_hashed_expiring_single_use_and_invalidate_sessions(client, app):
    login(client, "student1@student.mmu.edu.my")
    token = issue_account_token(1, "password_reset")
    record = db.session.scalar(select(AccountToken).where(AccountToken.user_id == 1))
    assert record.token_hash != token
    assert consume_account_token(token, "password_reset", new_password="a much longer passphrase")
    db.session.expire_all()
    assert db.session.get(User, 1).session_version == 1
    assert not consume_account_token(token, "password_reset", new_password="another longer passphrase")
    db.session.expire_all()
    with client.session_transaction() as flask_session:
        assert flask_session.get("_user_id") == "1:0"
    g.pop("_login_user", None)
    assert client.get("/profile").status_code == 302
    expired = issue_account_token(1, "email_verification", expires_in=timedelta(seconds=-1))
    assert not consume_account_token(expired, "email_verification")


def test_admin_bootstrap_verifies_operator_controlled_email(app):
    app.config["REQUIRE_EMAIL_VERIFICATION"] = True
    with transaction() as session:
        bootstrap_admin(session, "admin@mmu.edu.my", "a bootstrapped admin password")
    db.session.expire_all()
    user = db.session.get(User, 5)
    assert user.email_verified_at is not None
    assert user.session_version == 1


def test_lecturer_invitation_is_hashed_targeted_and_single_use(app):
    token = issue_lecturer_invitation(5, "newlecturer@mmu.edu.my")
    stored = db.session.scalar(select(LecturerInvitation))
    assert stored.token_hash != token
    with transaction() as session, pytest.raises(ValueError, match="invalid"):
        use_lecturer_invitation(session, token, "other@mmu.edu.my")
    with transaction() as session:
        use_lecturer_invitation(session, token, "newlecturer@mmu.edu.my")


def test_admin_invitation_route_displays_once_and_can_revoke(client, app):
    login(client, "admin@mmu.edu.my")
    response = client.post("/admin/lecturer-invitations", data={"email": "newlecturer@mmu.edu.my"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    token = response.get_data(as_text=True).split("<code>", 1)[1].split("</code>", 1)[0]
    invitation = db.session.scalar(select(LecturerInvitation))
    assert invitation.email == "newlecturer@mmu.edu.my"
    assert token != invitation.token_hash
    response = client.post(f"/admin/lecturer-invitations/{invitation.id}/revoke")
    assert response.status_code == 302
    db.session.expire_all()
    assert db.session.get(LecturerInvitation, invitation.id).revoked_at is not None
    with transaction() as session, pytest.raises(ValueError, match="invalid"):
        use_lecturer_invitation(session, token, "newlecturer@mmu.edu.my")


def test_deactivation_preserves_history_invalidates_session_and_closes_availability(client, app):
    booking_id, _ = create_booking(1, 1, app.config["TEST_SLOT_START"], "Consultation")
    login(client, "admin@mmu.edu.my")
    response = client.post("/delete_user", data={"id": 3})
    assert response.status_code == 302
    db.session.expire_all()
    lecturer = db.session.get(User, 3)
    assert lecturer.active is False
    assert lecturer.session_version == 1
    assert db.session.get(Appointment, booking_id) is not None
    assert db.session.get(Availability, 1).active is False
    assert client.get("/ready").json == {"ready": True}
    client.post("/activate_user", data={"id": 3})
    db.session.expire_all()
    assert db.session.get(User, 3).active is True
    assert db.session.get(Availability, 1).active is False


def test_cannot_deactivate_last_active_administrator(client):
    login(client, "admin@mmu.edu.my")
    assert client.post("/delete_user", data={"id": 5}).status_code == 302
    db.session.expire_all()
    assert db.session.get(User, 5).active is True


def test_completed_no_show_transitions_write_status_history_and_are_terminal(app):
    appointment_id, _ = create_booking(1, 1, app.config["TEST_SLOT_START"], "Consultation")
    transition_appointment(appointment_id, 3, "teacher", "Accepted")
    transition_appointment(appointment_id, 3, "teacher", "Completed")
    row = db.session.get(Appointment, appointment_id)
    assert row.status == "Completed" and row.completed_at is not None
    history = db.session.scalars(
        select(AppointmentStatusHistory).where(AppointmentStatusHistory.appointment_id == appointment_id)
    ).all()
    assert [(item.from_status, item.to_status) for item in history] == [
        ("Pending", "Accepted"),
        ("Accepted", "Completed"),
    ]
    with pytest.raises(InvalidTransition):
        transition_appointment(appointment_id, 3, "teacher", "Accepted")
    with pytest.raises(InvalidTransition):
        transition_appointment(appointment_id, 1, "student", "No Show")


def test_status_transition_and_history_rollback_together(app, monkeypatch):
    appointment_id, _ = create_booking(1, 1, app.config["TEST_SLOT_START"], "Consultation")

    def fail_history(*_args, **_kwargs):
        raise RuntimeError("forced history failure")

    monkeypatch.setattr(service, "AppointmentStatusHistory", fail_history)
    with pytest.raises(RuntimeError, match="forced history failure"):
        transition_appointment(appointment_id, 3, "teacher", "Accepted")
    db.session.expire_all()
    assert db.session.get(Appointment, appointment_id).status == "Pending"
    assert db.session.scalar(
        select(AppointmentStatusHistory.id).where(AppointmentStatusHistory.appointment_id == appointment_id)
    ) is None


def test_recurring_availability_conflict_rolls_back_all_occurrences(client, app):
    login(client, "lecturer1@mmu.edu.my")
    existing = Availability(
        lecturer_id=3,
        starts_at=datetime(2026, 10, 27, 2, tzinfo=UTC),
        ends_at=datetime(2026, 10, 27, 3, tzinfo=UTC),
        slot_minutes=30,
    )
    db.session.add(existing)
    db.session.commit()
    response = client.post(
        "/calendar_record",
        data={"event_date": "2026-10-20", "end_date": "2026-11-03", "start_time": "10:00", "end_time": "11:00", "slot_size": "30", "repeat_type": "weekly"},
    )
    assert response.status_code == 302
    db.session.expire_all()
    rows = db.session.scalars(select(Availability).where(Availability.lecturer_id == 3)).all()
    assert len(rows) == 2


def test_overlapping_availability_is_rejected_at_the_service_boundary(client, app):
    login(client, "lecturer1@mmu.edu.my")
    before = len(db.session.scalars(select(Availability).where(Availability.lecturer_id == 3)).all())
    response = client.post(
        "/calendar_record",
        data={"event_date": "2026-10-08", "end_date": "2026-10-08", "start_time": "10:30", "end_time": "11:00", "slot_size": "30", "repeat_type": ""},
    )
    assert response.status_code == 302
    db.session.expire_all()
    windows = db.session.scalars(select(Availability).where(Availability.lecturer_id == 3)).all()
    assert len(windows) == before


def test_concurrent_same_lecturer_booking_on_postgresql(app):
    if db.engine.dialect.name != "postgresql":
        pytest.skip("row-lock race is meaningful only on PostgreSQL")
    barrier = Barrier(3)

    def attempt(student_id):
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                return create_booking(student_id, 1, app.config["TEST_SLOT_START"], "Concurrent")
            except BookingConflict:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, student_id) for student_id in (1, 2)]
        barrier.wait(timeout=10)
        results = [future.result(timeout=20) for future in futures]
    assert sum(result is not None for result in results) == 1
    assert db.session.scalar(
        select(Appointment.id).where(Appointment.lecturer_id == 3, Appointment.status.in_(("Pending", "Accepted")))
    ) is not None


def test_concurrent_different_lecturers_succeed_without_shared_lock(app):
    if db.engine.dialect.name != "postgresql":
        pytest.skip("row-lock independence is meaningful only on PostgreSQL")
    second = Availability(
        lecturer_id=4,
        starts_at=datetime.fromisoformat(app.config["TEST_SLOT_START"]),
        ends_at=datetime.fromisoformat(app.config["TEST_SLOT_START"]) + timedelta(hours=1),
        slot_minutes=30,
    )
    db.session.add(second)
    db.session.commit()
    barrier = Barrier(3)

    def attempt(student_id, availability_id):
        with app.app_context():
            barrier.wait(timeout=10)
            return create_booking(student_id, availability_id, app.config["TEST_SLOT_START"], "Concurrent")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, 1, 1), pool.submit(attempt, 2, second.id)]
        barrier.wait(timeout=10)
        results = [future.result(timeout=20) for future in futures]
    assert len(results) == 2
    assert db.session.scalar(select(Appointment.id).where(Appointment.lecturer_id == 3))
    assert db.session.scalar(select(Appointment.id).where(Appointment.lecturer_id == 4))

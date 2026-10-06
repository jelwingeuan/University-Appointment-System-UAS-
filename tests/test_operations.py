import json
import logging
from uuid import UUID

from sqlalchemy import select

from tests.conftest import login
from uas.extensions import db
from uas.models import Appointment, Availability, Faculty, User
from uas.observability import ApplicationFormatter


def test_request_id_is_generated_and_request_logs_are_safe(client, app, caplog):
    caplog.set_level(logging.INFO, logger=app.logger.name)
    response = client.post(
        "/login?access_token=QUERY-SECRET",
        headers={"X-Request-ID": "SPOOFED-REQUEST-ID", "Authorization": "Bearer HEADER-SECRET"},
        data={"email": "missing@example.edu", "password": "BODY-SECRET", "csrf_token": "CSRF-SECRET"},
    )

    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4
    assert request_id != "SPOOFED-REQUEST-ID"
    record = next(row for row in caplog.records if getattr(row, "event", None) == "http.request")
    assert record.request_id == request_id
    assert (record.method, record.route, record.status_code) == ("POST", "/login", 302)
    assert record.duration_ms >= 0
    assert all(secret not in caplog.text for secret in ("QUERY-SECRET", "HEADER-SECRET", "BODY-SECRET", "CSRF-SECRET"))


def test_request_logs_include_authenticated_id_and_safe_error_type(client, app, caplog):
    def fail_safely():
        raise RuntimeError("BODY-SECRET-DO-NOT-LOG")

    app.add_url_rule("/test-logging-error", endpoint="test_logging_error", view_func=fail_safely)
    caplog.set_level(logging.INFO, logger=app.logger.name)
    login(client, "student1@student.mmu.edu.my")
    caplog.clear()
    response = client.get("/profile?reset_token=QUERY-SECRET")
    assert response.headers.get("X-Request-ID")
    record = next(row for row in caplog.records if getattr(row, "event", None) == "http.request")
    assert record.user_id == 1
    assert record.route == "/profile"
    assert "QUERY-SECRET" not in caplog.text

    app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
    caplog.clear()
    error_response = client.get("/test-logging-error")
    assert error_response.status_code == 500
    error_record = next(row for row in caplog.records if getattr(row, "event", None) == "application.error")
    assert error_record.error_type == "RuntimeError"
    assert error_record.request_id == error_response.headers["X-Request-ID"]
    assert "BODY-SECRET-DO-NOT-LOG" not in caplog.text


def test_log_formatter_is_human_readable_locally_and_json_in_production():
    formatter = ApplicationFormatter()
    record = logging.LogRecord("uas", logging.INFO, __file__, 1, "request completed", (), None)
    record.app_env = "development"
    record.request_id = "local-id"
    record.method = "GET"
    record.route = "/health"
    record.user_id = None
    record.status_code = 200
    record.duration_ms = 1.25
    record.event = "http.request"
    assert "GET" in formatter.format(record) and "request_id=local-id" in formatter.format(record)

    record.app_env = "production"
    structured = json.loads(formatter.format(record))
    assert structured["event"] == "http.request"
    assert structured["request_id"] == "local-id"
    assert structured["route"] == "/health"
    assert structured["status"] == 200
    assert structured["environment"] == "production"


def test_seed_demo_refuses_production_without_writing_rows(app):
    app.config.update(APP_ENV="production", DEMO_ACCOUNT_PASSWORD="DemoPassword#2026")
    models = (Faculty, User, Availability, Appointment)
    before = tuple(db.session.query(model).count() for model in models)
    result = app.test_cli_runner().invoke(args=["seed-demo"])
    assert result.exit_code != 0
    assert "cannot be seeded in production" in result.output
    assert tuple(db.session.query(model).count() for model in models) == before


def test_seed_demo_collision_rolls_back_everything(app):
    original = db.session.get(User, 1)
    db.session.add(
        User(
            role="student",
            faculty_id=1,
            username="Unrelated Existing Account",
            email="demo.student.empty@student.mmu.edu.my",
            phone_number="+601199999999",
            password_hash=original.password_hash,
        )
    )
    db.session.commit()
    app.config["DEMO_ACCOUNT_PASSWORD"] = "DemoPassword#2026"

    result = app.test_cli_runner().invoke(args=["seed-demo"])

    assert result.exit_code != 0
    assert "conflicts with existing data" in result.output
    assert db.session.query(Faculty).filter(Faculty.faculty_name.like("UAS Demo:%")).count() == 0
    assert db.session.query(User).filter_by(username="Unrelated Existing Account").count() == 1
    assert db.session.query(Availability).count() == 1
    assert db.session.query(Appointment).count() == 0


def test_seed_demo_is_idempotent_and_creates_valid_synthetic_data(app, client):
    app.config["DEMO_ACCOUNT_PASSWORD"] = "DemoPassword#2026"
    runner = app.test_cli_runner()
    first = runner.invoke(args=["seed-demo"])
    assert first.exit_code == 0, first.output
    counts = tuple(db.session.query(model).count() for model in (Faculty, User, Availability, Appointment))
    second = runner.invoke(args=["seed-demo"])
    assert second.exit_code == 0, second.output
    assert tuple(db.session.query(model).count() for model in (Faculty, User, Availability, Appointment)) == counts

    seeded = db.session.scalars(
        select(Appointment).where(Appointment.purpose.like("Demo appointment:%"))
    ).all()
    assert len(seeded) == 14
    assert {row.status for row in seeded} == {"Pending", "Accepted", "Rejected", "Cancelled", "Completed", "No Show"}
    assert len({row.starts_at.date() for row in seeded}) > 1
    assert all(row.student.role == "student" and row.lecturer.role == "teacher" for row in seeded)
    assert all(row.availability.lecturer_id == row.lecturer_id for row in seeded)

    lecturers = {user.email: user for user in db.session.scalars(select(User).where(User.email.like("demo.lecturer.%")))}
    empty_lecturer = lecturers["demo.lecturer.empty@mmu.edu.my"]
    busy_lecturer = lecturers["demo.lecturer.busy@mmu.edu.my"]
    assert db.session.scalar(select(Availability.id).where(Availability.lecturer_id == empty_lecturer.id)) is None
    assert db.session.query(Appointment).filter_by(lecturer_id=busy_lecturer.id).count() >= 10
    assert db.session.scalar(select(Appointment.id).where(Appointment.student_id == db.session.scalar(
        select(User.id).where(User.email == "demo.student.empty@student.mmu.edu.my")
    ))) is None
    assert len(busy_lecturer.username) > 60
    assert {row.slot_minutes for row in db.session.scalars(select(Availability).where(
        Availability.lecturer_id.in_([user.id for user in lecturers.values()])
    ))} == {30, 45, 60}
    assert db.session.get(User, 1).username == "Student One"
    assert db.session.get(Availability, 1).lecturer_id == 3

    assert login(client, "demo.student.one@student.mmu.edu.my", "DemoPassword#2026").status_code == 302
    assert client.get("/bookinghistory").status_code == 200


def test_seed_demo_requires_a_valid_local_password_without_partial_writes(app):
    app.config["DEMO_ACCOUNT_PASSWORD"] = ""
    result = app.test_cli_runner().invoke(args=["seed-demo"])
    assert result.exit_code != 0
    assert "at least 12 characters" in result.output
    assert db.session.query(User).count() == 5

import io
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import bcrypt

from app import create_app
from database import connect_database, init_schema
from tests.conftest import login


def test_public_pages_and_login_form(client):
    assert client.get("/").status_code == 200
    assert client.get("/about").status_code == 200
    assert 'name="csrf_token"' in client.get("/login").get_data(as_text=True)
    assert client.get("/signup").status_code == 200


def test_student_workflow_routes(client, app, db):
    login(client, "student1@student.mmu.edu.my")
    assert client.get("/profile").status_code == 200
    assert client.get("/appointment").status_code == 200
    assert client.get("/appointment2").status_code == 200
    assert client.get("/bookinghistory").status_code == 200
    assert client.get("/invoice").status_code == 404

    local_date = datetime.fromisoformat(app.config["TEST_SLOT_START"]).astimezone(
        ZoneInfo("Asia/Kuala_Lumpur")
    ).date().isoformat()
    details = client.get(f"/get_calendar_details?lecturer=3&appointment_date={local_date}")
    assert details.status_code == 200
    slot = details.get_json()["slots"][0]
    assert slot["availability_id"] == 1
    assert slot["available"] is True
    availability = client.get(
        "/check_availability",
        query_string={"availability_id": 1, "starts_at": slot["starts_at"]},
    ).get_json()
    assert availability == {"available": True}

    created = client.post(
        "/create_booking",
        data={"availability_id": 1, "slot_start": slot["starts_at"], "purpose": "Academic advice"},
    )
    assert created.status_code == 302
    invoice = client.get(created.headers["Location"])
    assert invoice.status_code == 200
    assert "Academic advice" in invoice.get_data(as_text=True)
    assert db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1


def test_student_profile_and_password_updates(client, db):
    login(client, "student1@student.mmu.edu.my")
    response = client.post(
        "/update_user_info",
        data={
            "username": "Student Updated",
            "email": "student1@student.mmu.edu.my",
            "phone_number": "0100000011",
        },
    )
    assert response.status_code == 302
    assert db.execute("SELECT username FROM users WHERE id = 1").fetchone()[0] == "Student Updated"
    assert client.post(
        "/change_password",
        data={
            "current_password": "CorrectHorse1",
            "new_password": "NewCorrectHorse2",
            "confirm_password": "NewCorrectHorse2",
        },
    ).status_code == 302
    password = db.execute("SELECT password FROM users WHERE id = 1").fetchone()[0]
    assert bcrypt.checkpw(b"NewCorrectHorse2", password.encode())


def test_signup_validates_lecturer_secret(client, db):
    base = {
        "role": "teacher",
        "faculty": "FCI",
        "username": "New Lecturer",
        "email": "newlecturer@mmu.edu.my",
        "phone_number": "0100000010",
        "password": "CorrectHorse1",
        "confirm_password": "CorrectHorse1",
    }
    assert client.post("/signup", data={**base, "pin": "wrong"}).status_code == 302
    assert db.execute("SELECT COUNT(*) FROM users WHERE email = ?", (base["email"],)).fetchone()[0] == 0
    assert client.post("/signup", data={**base, "pin": "lecturer-test-secret"}).status_code == 302
    assert db.execute("SELECT role FROM users WHERE email = ?", (base["email"],)).fetchone()[0] == "teacher"


def test_teacher_availability_calendar_and_owned_delete(client, app, db):
    login(client, "lecturer1@mmu.edu.my")
    assert client.get("/calendar").status_code == 200
    assert client.get("/events").status_code == 200
    local_start = datetime.now(ZoneInfo("Asia/Kuala_Lumpur")) + timedelta(days=14)
    response = client.post(
        "/calendar_record",
        data={
            "event_date": local_start.date().isoformat(),
            "end_date": local_start.date().isoformat(),
            "start_time": "14:00",
            "end_time": "15:00",
            "slot_size": "30",
            "repeat_type": "",
        },
    )
    assert response.status_code == 302
    created = db.execute(
        "SELECT id FROM availability WHERE lecturer_id = 3 ORDER BY id DESC"
    ).fetchone()[0]
    deleted = client.post("/delete_event", data={"availability_id": created})
    assert deleted.status_code == 200
    assert db.execute("SELECT COUNT(*) FROM availability WHERE id = ?", (created,)).fetchone()[0] == 0


def test_admin_routes_and_bootstrap_command(client, app, db, monkeypatch):
    login(client, "admin@mmu.edu.my")
    for path in ["/admin", "/admin?search=Pending", "/usercontrol", "/appointmentcontrol", "/faculty", "/createfacultyhub", "/adminpageeditor"]:
        assert client.get(path).status_code == 200
    assert client.post("/delete_user", data={"id": 5}).status_code == 302
    assert db.execute("SELECT COUNT(*) FROM users WHERE id = 5").fetchone()[0] == 1

    monkeypatch.setenv("ADMIN_EMAIL", "newadmin@mmu.edu.my")
    monkeypatch.setenv("ADMIN_PASSWORD", "StrongAdminPassword1")
    result = app.test_cli_runner().invoke(args=["bootstrap-admin"])
    assert result.exit_code == 0
    row = db.execute("SELECT role, password FROM users WHERE email = 'newadmin@mmu.edu.my'").fetchone()
    assert row["role"] == "admin"
    assert bcrypt.checkpw(b"StrongAdminPassword1", row["password"].encode())


def test_invalid_upload_is_rejected(client):
    login(client, "admin@mmu.edu.my")
    response = client.post(
        "/adminpageeditor",
        data={
            "home_content": "Home",
            "school_name": "School",
            "school_tel": "123",
            "school_email": "school@example.com",
            "school_logo": (io.BytesIO(b"not an image"), "payload.txt"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302


def test_login_rate_limit(tmp_path, monkeypatch):
    database_path = tmp_path / "rate.db"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "rate-test-secret",
            "DATABASE_PATH": str(database_path),
            "LECTURER_REGISTRATION_SECRET": "lecturer-test-secret",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": True,
        }
    )
    with connect_database(database_path) as connection:
        init_schema(connection)
    client = app.test_client()
    statuses = [
        client.post("/login", data={"email": "missing@example.com", "password": "wrong"}).status_code
        for _ in range(6)
    ]
    assert statuses[-1] == 429

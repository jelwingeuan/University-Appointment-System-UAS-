import io
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from tests.conftest import login
from uas.booking_service import BookingError, InvalidTransition, create_booking, transition_appointment
from uas.calendar import generate_recurrence
from uas.extensions import db as orm
from uas.models import Appointment, Availability, Faculty, User


def test_inactive_account_cannot_login_or_keep_a_session(client, app):
    user = orm.session.get(User, 1)
    user.active = False
    orm.session.commit()
    assert login(client, user.email).status_code == 302
    user.active = True
    orm.session.commit()
    login(client, user.email)
    user.active = False
    orm.session.commit()
    assert client.get("/profile").status_code == 302


def test_login_only_accepts_same_origin_next(client):
    response = client.post(
        "/login?next=https://attacker.invalid/",
        data={"email": "student1@student.mmu.edu.my", "password": "CorrectHorse1"},
    )
    assert response.headers["Location"].endswith("/")
    client.post("/logout")
    response = client.post(
        "/login?next=/profile", data={"email": "student1@student.mmu.edu.my", "password": "CorrectHorse1"}
    )
    assert response.headers["Location"].endswith("/profile")


def test_booking_rejects_invalid_alignment_past_and_purpose(app):
    start = datetime.fromisoformat(app.config["TEST_SLOT_START"])
    for when, purpose in [
        (start + timedelta(minutes=5), "bad alignment"),
        (start - timedelta(days=10), "past"),
        (start, " "),
    ]:
        with pytest.raises(BookingError):
            create_booking(1, 1, when.isoformat(), purpose)


def test_conflict_checks_overlap_across_availability_windows(app):
    window = orm.session.get(Availability, 1)
    second = Availability(
        lecturer_id=3,
        starts_at=window.starts_at + timedelta(minutes=15),
        ends_at=window.ends_at + timedelta(minutes=15),
        slot_minutes=30,
    )
    orm.session.add(second)
    orm.session.commit()
    create_booking(1, 1, app.config["TEST_SLOT_START"], "first")
    with pytest.raises(BookingError):
        create_booking(2, second.id, (window.starts_at + timedelta(minutes=15)).isoformat(), "partial overlap")


def test_back_to_back_and_different_lecturer_bookings_are_allowed(app):
    first_start = datetime.fromisoformat(app.config["TEST_SLOT_START"])
    second_teacher_window = Availability(
        lecturer_id=4,
        starts_at=first_start,
        ends_at=first_start + timedelta(hours=2),
        slot_minutes=30,
    )
    orm.session.add(second_teacher_window)
    orm.session.commit()
    create_booking(1, 1, first_start.isoformat(), "first")
    create_booking(2, 1, (first_start + timedelta(minutes=30)).isoformat(), "back to back")
    create_booking(2, second_teacher_window.id, first_start.isoformat(), "other lecturer")
    assert orm.session.query(Appointment).count() == 3


def test_status_transitions_enforce_roles_and_allow_student_cancel(app):
    appointment_id, _ = create_booking(1, 1, app.config["TEST_SLOT_START"], "test")
    with pytest.raises(PermissionError):
        transition_appointment(appointment_id, 4, "teacher", "Accepted")
    transition_appointment(appointment_id, 3, "teacher", "Accepted")
    transition_appointment(appointment_id, 1, "student", "Cancelled")
    with pytest.raises(InvalidTransition):
        transition_appointment(appointment_id, 3, "teacher", "Rejected")


def test_weekly_recurrence_is_inclusive_and_invalid_ranges_rejected():
    start = datetime(2026, 10, 5, 10, tzinfo=UTC)
    assert len(generate_recurrence(start, start + timedelta(days=14), "weekly")) == 3
    with pytest.raises(ValueError):
        generate_recurrence(start, start - timedelta(days=1), "weekly")
    with pytest.raises(ValueError):
        generate_recurrence(start, start, "yearly")


def test_calendar_recurrence_writes_inclusive_occurrences_and_delete_is_owned(client, app):
    login(client, "lecturer1@mmu.edu.my")
    day = (app.config["CLOCK"]() + timedelta(days=28)).astimezone(ZoneInfo("Asia/Kuala_Lumpur")).date()
    response = client.post(
        "/calendar_record",
        data={
            "event_date": day.isoformat(),
            "end_date": (day + timedelta(days=14)).isoformat(),
            "start_time": "10:00",
            "end_time": "11:00",
            "slot_size": "30",
            "repeat_type": "weekly",
        },
    )
    assert response.status_code == 302
    ids = [row.id for row in orm.session.query(Availability).filter_by(lecturer_id=3).all()]
    assert len(ids) == 4  # includes the fixture window plus three occurrences
    login(client, "lecturer2@mmu.edu.my")
    response = client.post("/delete_event", data={"availability_id": ids[-1]})
    assert response.status_code == 404


def test_admin_can_delete_booking_but_not_appointments_through_user_delete(client, app):
    appointment_id, _ = create_booking(1, 1, app.config["TEST_SLOT_START"], "test")
    login(client, "admin@mmu.edu.my")
    assert client.get("/appointmentcontrol?search=test").status_code == 200
    assert client.post("/delete_user", data={"id": 1}).status_code == 302
    assert orm.session.get(User, 1) is not None
    assert client.post("/delete_booking", data={"id": appointment_id}).status_code == 302
    orm.session.expire_all()
    assert orm.session.get(Appointment, appointment_id) is None


def test_admin_deactivates_unreferenced_user_and_updates_database_content(client, app):
    login(client, "admin@mmu.edu.my")
    assert client.get("/usercontrol?search=Student").status_code == 200
    assert client.post("/delete_user", data={"id": 2}).status_code == 302
    orm.session.expire_all()
    assert orm.session.get(User, 2).active is False
    response = client.post(
        "/adminpageeditor",
        data={"home_content": "Updated", "school_name": "MMU", "school_tel": "123", "school_email": "info@mmu.edu.my"},
    )
    assert response.status_code == 302
    from uas.content_service import load_content

    assert load_content()["home_content"] == "Updated"


def test_image_validation_and_faculty_creation(client, app):
    login(client, "admin@mmu.edu.my")
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(image, format="PNG")
    image.seek(0)
    response = client.post(
        "/createfacultyhub",
        data={
            "faculty_name": "New Faculty",
            "faculty_image": (image, "test.png", "image/png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert orm.session.query(Faculty).filter_by(faculty_name="New Faculty").count() == 1


def test_profile_rejects_invalid_details_and_bad_current_password(client):
    login(client, "student1@student.mmu.edu.my")
    assert (
        client.post("/update_user_info", data={"username": "", "email": "bad@invalid", "phone_number": ""}).status_code
        == 400
    )
    assert (
        client.post(
            "/change_password",
            data={"current_password": "wrong", "new_password": "ValidPassword1", "confirm_password": "ValidPassword1"},
        ).status_code
        == 302
    )


def test_calendar_rejects_nonpositive_or_duplicate_window(client, app):
    login(client, "lecturer1@mmu.edu.my")
    day = (app.config["CLOCK"]() + timedelta(days=30)).astimezone(ZoneInfo("Asia/Kuala_Lumpur")).date().isoformat()
    form = {
        "event_date": day,
        "end_date": day,
        "start_time": "10:00",
        "end_time": "11:00",
        "slot_size": "0",
        "repeat_type": "",
    }
    assert client.post("/calendar_record", data=form).status_code == 302
    form["slot_size"] = "30"
    client.post("/calendar_record", data=form)
    assert client.post("/calendar_record", data=form).status_code == 302


def test_ajax_calendar_deletion_requires_csrf_token(client, app):
    login(client, "lecturer1@mmu.edu.my")
    app.config["WTF_CSRF_ENABLED"] = True
    assert client.post("/delete_event", data={"availability_id": 1}).status_code == 400
    page = client.get("/calendar").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    response = client.post("/delete_event", data={"availability_id": 1, "csrf_token": token})
    assert response.status_code == 200


def test_bootstrap_command_rotates_existing_administrator_password(client, app, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "admin@mmu.edu.my")
    monkeypatch.setenv("ADMIN_PASSWORD", "UpdatedStrongAdminPassword1")
    result = app.test_cli_runner().invoke(args=["bootstrap-admin"])
    assert result.exit_code == 0
    orm.session.expire_all()
    assert orm.session.get(User, 5).role == "admin"
    import bcrypt

    assert bcrypt.checkpw(b"UpdatedStrongAdminPassword1", orm.session.get(User, 5).password_hash.encode())

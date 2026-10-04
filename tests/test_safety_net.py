import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import FIXED_NOW, login
from uas.booking_service import BookingConflict, BookingError, InvalidTransition, create_booking, transition_appointment
from uas.calendar import generate_recurrence
from uas.extensions import db
from uas.models import Appointment, User


def test_student_cannot_change_another_students_booking(client, app):
    booking_id, reference = create_booking(1, 1, app.config["TEST_SLOT_START"], "Advice")
    login(client, "student2@student.mmu.edu.my")
    assert client.get(f"/invoice?reference={reference}").status_code == 404
    assert client.post("/cancel_booking", data={"id": booking_id}).status_code == 403
    db.session.expire_all()
    assert db.session.get(Appointment, booking_id).status == "Pending"


def test_tampered_booking_actor_fields_are_ignored(client, app):
    login(client, "student2@student.mmu.edu.my")
    response = client.post(
        "/create_booking",
        data={
            "availability_id": 1,
            "slot_start": app.config["TEST_SLOT_START"],
            "purpose": "Advice",
            "student_id": 1,
            "lecturer_id": 4,
            "status": "Accepted",
        },
    )
    assert response.status_code == 302
    row = db.session.query(Appointment).one()
    assert (row.student_id, row.lecturer_id, row.status) == (2, 3, "Pending")


def test_signup_cannot_submit_admin_role(client):
    response = client.post(
        "/signup",
        data={
            "role": "admin",
            "faculty": "FCI",
            "username": "Intruder",
            "email": "intruder@mmu.edu.my",
            "phone_number": "+60123456789",
            "password": "CorrectHorse1",
            "confirm_password": "CorrectHorse1",
        },
    )
    assert response.status_code == 400
    assert db.session.query(User).filter_by(username="Intruder").count() == 0


@pytest.mark.parametrize("offset", [-15, 0, 15])
def test_overlap_from_both_sides_and_exact_match_is_atomic(app, availability_factory, offset):
    start = datetime.fromisoformat(app.config["TEST_SLOT_START"])
    create_booking(1, 1, start.isoformat(), "First")
    competing = availability_factory(start=start + timedelta(minutes=offset), minutes=60)
    with pytest.raises(BookingConflict):
        create_booking(2, competing.id, competing.starts_at.isoformat(), "Conflict")
    assert db.session.query(Appointment).count() == 1


def test_cancelled_booking_releases_slot_and_invalid_transition_rolls_back(app):
    first_id, _ = create_booking(1, 1, app.config["TEST_SLOT_START"], "First")
    transition_appointment(first_id, 1, "student", "Cancelled")
    second_id, _ = create_booking(2, 1, app.config["TEST_SLOT_START"], "Second")
    with pytest.raises(InvalidTransition):
        transition_appointment(first_id, 3, "teacher", "Accepted")
    assert db.session.get(Appointment, first_id).status == "Cancelled"
    assert db.session.get(Appointment, second_id).status == "Pending"


def test_invalid_booking_does_not_create_a_row(app):
    with pytest.raises(BookingError):
        create_booking(1, 1, app.config["TEST_SLOT_START"], "x" * 501)
    with pytest.raises(BookingError):
        create_booking(1, 1, (FIXED_NOW - timedelta(days=1)).isoformat(), "Past")
    assert db.session.query(Appointment).count() == 0


def test_recurrence_month_end_leap_year_and_year_boundary():
    start = datetime(2024, 1, 31, 10, tzinfo=UTC)
    end = datetime(2025, 1, 31, 10, tzinfo=UTC)
    dates = [value.date().isoformat() for value in generate_recurrence(start, end, "monthly")]
    assert dates[:3] == ["2024-01-31", "2024-02-29", "2024-03-31"]
    assert dates[-2:] == ["2024-12-31", "2025-01-31"]
    weekly = generate_recurrence(datetime(2026, 12, 28, tzinfo=UTC), datetime(2027, 1, 11, tzinfo=UTC), "weekly")
    assert [day.date().isoformat() for day in weekly] == ["2026-12-28", "2027-01-04", "2027-01-11"]


def test_appointment_rejects_mismatched_availability_and_user_deletion(app):
    start = datetime.fromisoformat(app.config["TEST_SLOT_START"])
    db.session.add(
        Appointment(student_id=1, lecturer_id=4, availability_id=1, starts_at=start,
                    ends_at=start + timedelta(minutes=30), purpose="Advice")
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    with pytest.raises(IntegrityError):
        db.session.delete(db.session.get(User, 3))
        db.session.commit()
    db.session.rollback()


def test_csrf_rejects_form_post_but_accepts_valid_token(client, app):
    app.config["WTF_CSRF_ENABLED"] = True
    assert client.post("/login", data={"email": "student1@student.mmu.edu.my", "password": "CorrectHorse1"}).status_code == 400
    page = client.get("/login").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    response = client.post(
        "/login",
        data={"email": "student1@student.mmu.edu.my", "password": "CorrectHorse1", "csrf_token": token},
    )
    assert response.status_code == 302


def test_admin_lists_paginate_and_bound_search(client, user_factory):
    for _ in range(28):
        user_factory()
    login(client, "admin@mmu.edu.my")
    response = client.get("/usercontrol?page=2&search=Fixture")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Page 2 of 2" in page
    assert "?page=1&amp;search=Fixture" in page
    assert client.get("/usercontrol?search=" + "x" * 101).status_code == 400


def test_new_york_local_conversion_rejects_dst_gaps_and_folds(app):
    from uas.common import local_to_utc

    app.config["UNIVERSITY_TIMEZONE"] = "America/New_York"
    with pytest.raises(ValueError, match="does not exist"):
        local_to_utc(datetime(2026, 3, 8, 2, 30))  # noqa: DTZ001
    with pytest.raises(ValueError, match="ambiguous"):
        local_to_utc(datetime(2026, 11, 1, 1, 30))  # noqa: DTZ001
    assert local_to_utc(datetime(2026, 1, 15, 12, 0)).utcoffset() == timedelta(0)  # noqa: DTZ001


def test_student_lecturer_admin_workflow(client, app):
    login(client, "student1@student.mmu.edu.my")
    response = client.post(
        "/create_booking",
        data={"availability_id": 1, "slot_start": app.config["TEST_SLOT_START"], "purpose": "Degree plan"},
    )
    assert client.get(response.headers["Location"]).status_code == 200
    booking = db.session.query(Appointment).one()
    client.post("/logout")
    login(client, "lecturer1@mmu.edu.my")
    assert client.get("/bookinghistory").status_code == 200
    assert client.post("/accept_booking", data={"id": booking.id}).status_code == 302
    assert client.post("/calendar_record", data={
        "event_date": "2026-10-20", "end_date": "2026-10-20", "start_time": "10:00",
        "end_time": "11:00", "slot_size": "30", "repeat_type": "",
    }).status_code == 302
    client.post("/logout")
    login(client, "admin@mmu.edu.my")
    assert client.get("/admin").status_code == 200
    assert client.get("/usercontrol").status_code == 200
    assert client.get("/appointmentcontrol").status_code == 200
    assert client.get("/faculty").status_code == 200
    db.session.expire_all()
    assert db.session.get(Appointment, booking.id).status == "Accepted"

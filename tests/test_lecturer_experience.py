from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy import event

from tests.conftest import FIXED_NOW, login
from uas.extensions import db
from uas.models import Appointment, Availability


def lecturer_login(client):
    login(client, "lecturer1@mmu.edu.my")


def test_lecturer_pages_are_teacher_only_and_owner_scoped(client, appointment_factory):
    appointment = appointment_factory()
    paths = (
        "/lecturer",
        "/lecturer/requests",
        f"/lecturer/appointments/{appointment.public_reference}",
    )

    for path in paths:
        assert client.get(path).status_code == 302

    login(client, "student1@student.mmu.edu.my")
    for path in paths:
        assert client.get(path).status_code == 403

    client.post("/logout")
    login(client, "admin@mmu.edu.my")
    for path in paths:
        assert client.get(path).status_code == 403

    client.post("/logout")
    lecturer_login(client)
    response = client.get(f"/lecturer/appointments/{appointment.public_reference}")
    assert response.status_code == 200
    assert appointment.public_reference in response.get_data(as_text=True)


def test_lecturer_dashboard_prioritizes_requests_and_shows_today_and_next(
    client, app, availability_factory, appointment_factory
):
    today_window = availability_factory(
        start=FIXED_NOW + timedelta(hours=2), minutes=90, slot_minutes=30
    )
    pending = appointment_factory(
        availability_id=today_window.id,
        starts_at=today_window.starts_at,
        status="Pending",
        purpose="A detailed request about my study plan",
    )
    today = appointment_factory(
        availability_id=today_window.id,
        starts_at=today_window.starts_at + timedelta(minutes=30),
        status="Accepted",
        purpose="Review project scope",
    )
    next_window = availability_factory(
        start=FIXED_NOW + timedelta(days=2), minutes=60, slot_minutes=30
    )
    next_appointment = appointment_factory(
        availability_id=next_window.id,
        starts_at=next_window.starts_at,
        status="Accepted",
        purpose="Discuss next semester options",
    )

    lecturer_login(client)
    markup = client.get("/lecturer").get_data(as_text=True)
    assert "Lecturer Dashboard" in markup
    assert pending.public_reference in markup
    assert "A detailed request about my study plan" in markup
    assert today.public_reference in markup
    assert "Review project scope" in markup
    assert next_appointment.public_reference in markup
    assert "Discuss next semester options" in markup
    assert markup.index("Appointment requests") < markup.index("Today")
    assert "0100000001" not in markup
    assert "student1@student.mmu.edu.my" not in markup


def test_lecturer_request_inbox_has_actions_and_paginates(client, app, availability_factory, appointment_factory):
    window = availability_factory(
        start=FIXED_NOW + timedelta(days=1), minutes=13 * 60, slot_minutes=30
    )
    rows = [
        appointment_factory(
            availability_id=window.id,
            starts_at=window.starts_at + timedelta(minutes=30 * slot),
            status="Pending",
            purpose=f"Request {slot:02d}",
        )
        for slot in range(26)
    ]
    lecturer_login(client)

    first = client.get("/lecturer/requests")
    assert first.status_code == 200
    markup = first.get_data(as_text=True)
    assert markup.count('name="id"') == 26
    assert "Request 00" in markup
    assert "Request 25" not in markup
    assert f"/lecturer/appointments/{rows[0].public_reference}" in markup
    assert 'action="/accept_booking"' in markup
    assert 'data-confirm-url="/reject_booking"' in markup
    assert "data-lecturer-confirm" in markup
    assert 'id="lecturer-confirm-dialog"' in markup
    assert "student1@student.mmu.edu.my" not in markup
    assert "0100000001" not in markup

    second = client.get("/lecturer/requests?page=2")
    assert second.status_code == 200
    second_markup = second.get_data(as_text=True)
    assert "Request 25" in second_markup
    assert second_markup.count('name="id"') == 2


@pytest.mark.parametrize("status", ["Pending", "Accepted", "Rejected", "Cancelled", "Completed", "No Show"])
def test_lecturer_detail_shows_only_actions_allowed_for_current_state(
    client, appointment_factory, status
):
    appointment = appointment_factory(status=status)
    lecturer_login(client)
    response = client.get(f"/lecturer/appointments/{appointment.public_reference}")
    assert response.status_code == 200
    markup = response.get_data(as_text=True)
    assert appointment.public_reference in markup
    assert status in markup
    assert "Appointment history" in markup

    expected = {
        "Pending": ("/accept_booking", "/reject_booking"),
        "Accepted": ("/complete_booking", "/no_show_booking"),
        "Rejected": (),
        "Cancelled": (),
        "Completed": (),
        "No Show": (),
    }[status]
    assert ('action="/accept_booking"' in markup) is ("/accept_booking" in expected)
    for action in ("/reject_booking", "/complete_booking", "/no_show_booking"):
        assert (f'data-confirm-url="{action}"' in markup) is (action in expected)


def test_lecturer_detail_uses_public_reference_and_hides_other_lecturers(
    client, availability_factory, appointment_factory
):
    appointment = appointment_factory()
    other_window = availability_factory(lecturer_id=4)
    other_appointment = appointment_factory(
        lecturer_id=4, availability_id=other_window.id, starts_at=other_window.starts_at
    )
    lecturer_login(client)

    own = client.get(f"/lecturer/appointments/{appointment.public_reference}")
    assert own.status_code == 200
    assert appointment.public_reference in own.get_data(as_text=True)
    assert client.get(f"/lecturer/appointments/{other_appointment.public_reference}").status_code == 404
    assert client.get("/lecturer/appointments/not-a-reference").status_code == 404


def test_lecturer_appointments_search_status_and_page_validation(
    client, availability_factory, appointment_factory
):
    window = availability_factory(start=FIXED_NOW + timedelta(days=1), minutes=60, slot_minutes=30)
    first = appointment_factory(availability_id=window.id, starts_at=window.starts_at, purpose="Thesis review")
    appointment_factory(
        availability_id=window.id,
        starts_at=window.starts_at + timedelta(minutes=30),
        status="Accepted",
        purpose="Lab consultation",
    )
    lecturer_login(client)

    searched = client.get("/bookinghistory?q=Thesis&status=Pending")
    assert searched.status_code == 200
    assert first.public_reference in searched.get_data(as_text=True)
    assert "Lab consultation" not in searched.get_data(as_text=True)
    assert client.get("/bookinghistory?status=In+Progress").status_code == 400
    assert client.get("/bookinghistory?q=" + "x" * 101).status_code == 400


def test_lecturer_history_pagination_preserves_search_and_status(
    client, availability_factory, appointment_factory
):
    window = availability_factory(start=FIXED_NOW + timedelta(days=1), minutes=13 * 60, slot_minutes=30)
    for slot in range(26):
        appointment_factory(
            availability_id=window.id,
            starts_at=window.starts_at + timedelta(minutes=30 * slot),
            purpose=f"Searchable appointment {slot}",
        )
    lecturer_login(client)

    response = client.get("/bookinghistory?q=Searchable&status=Pending")
    assert response.status_code == 200
    markup = response.get_data(as_text=True)
    next_link = next(line for line in markup.splitlines() if "Next" in line and "bookinghistory" in line)
    assert "q=Searchable" in next_link
    assert "status=Pending" in next_link


def test_lecturer_status_actions_return_to_origin_and_show_server_confirmed_feedback(
    client, appointment_factory
):
    appointment = appointment_factory(status="Pending")
    lecturer_login(client)

    response = client.post(
        "/accept_booking",
        data={"id": appointment.id},
        headers={"Referer": "http://localhost/lecturer/requests"},
    )
    assert urlsplit(response.location).path == "/lecturer/requests"
    inbox = client.get(response.location)
    assert "Appointment accepted" in inbox.get_data(as_text=True)
    detail = client.get(f"/lecturer/appointments/{appointment.public_reference}")
    detail_markup = detail.get_data(as_text=True)
    assert "Appointment accepted" in detail_markup
    assert "Status changed from Pending to Accepted." in detail_markup
    assert "Lecturer One" in detail_markup
    with client.application.app_context():
        assert db.session.get(Appointment, appointment.id).status == "Accepted"


def test_recurring_availability_overlap_explains_atomic_rollback(client, app):
    lecturer_login(client)
    before = db.session.query(Availability).filter_by(lecturer_id=3).count()
    response = client.post(
        "/calendar_record",
        data={
            "event_date": "2026-10-01",
            "end_date": "2026-10-15",
            "start_time": "10:00",
            "end_time": "11:00",
            "slot_size": "30",
            "repeat_type": "weekly",
        },
    )
    assert response.status_code == 302
    markup = client.get(response.location).get_data(as_text=True)
    assert "This recurring schedule conflicts with an existing availability window, so no dates were added." in markup
    with app.app_context():
        assert db.session.query(Availability).filter_by(lecturer_id=3).count() == before


def test_calendar_range_is_validated_and_returns_only_overlapping_events(
    client, app, availability_factory, appointment_factory
):
    visible = availability_factory(start=FIXED_NOW + timedelta(days=1), minutes=60, slot_minutes=30)
    hidden = availability_factory(start=FIXED_NOW + timedelta(days=10), minutes=60, slot_minutes=30)
    appointment = appointment_factory(
        availability_id=visible.id,
        starts_at=visible.starts_at,
        status="Accepted",
    )
    lecturer_login(client)
    start = visible.starts_at.isoformat()
    end = (visible.ends_at + timedelta(seconds=1)).isoformat()

    response = client.get("/events", query_string={"start": start, "end": end})
    assert response.status_code == 200
    events = response.get_json()
    assert len(events) == 2
    appointment_event = next(event for event in events if event["extendedProps"]["kind"] == "appointment")
    assert appointment_event["extendedProps"]["public_reference"] == appointment.public_reference
    assert appointment.public_reference in appointment_event["id"]
    assert appointment_event["id"] == f"appointment-{appointment.public_reference}"
    assert all(event.get("extendedProps", {}).get("availability_id") != hidden.id for event in events)
    assert client.get("/events?start=not-a-date&end=also-invalid").status_code == 400


def test_calendar_keeps_legacy_no_range_api_and_marks_referenced_availability(
    client, availability_factory, appointment_factory
):
    window = availability_factory(start=FIXED_NOW + timedelta(days=1), minutes=60, slot_minutes=30)
    appointment_factory(availability_id=window.id, starts_at=window.starts_at, status="Accepted")
    lecturer_login(client)

    events = client.get("/events").get_json()
    availability = next(event for event in events if event["extendedProps"]["kind"] == "availability")
    assert availability["extendedProps"]["has_appointments"] is True


def test_lecturer_cannot_delete_availability_referenced_by_appointment(
    client, availability_factory, appointment_factory
):
    window = availability_factory(start=FIXED_NOW + timedelta(days=1), minutes=60, slot_minutes=30)
    appointment_factory(availability_id=window.id, starts_at=window.starts_at)
    lecturer_login(client)

    response = client.post("/delete_event", data={"availability_id": window.id})
    assert response.status_code == 409
    assert "contains appointments" in response.get_json()["message"]
    assert db.session.get(Availability, window.id) is not None


def test_lecturer_calendar_and_shell_preserve_accessible_contracts(client):
    lecturer_login(client)
    markup = client.get("/calendar").get_data(as_text=True)
    assert 'aria-label="Appointment and availability calendar"' in markup
    assert "Availability" in markup
    assert "Accepted appointment" in markup
    assert 'id="lecturer-event-list"' in markup
    assert 'id="eventForm"' in markup
    assert markup.count('name="csrf_token"') >= 2
    for name in ("event_date", "end_date", "start_time", "end_time", "slot_size", "repeat_type"):
        assert f'name="{name}"' in markup
    assert "jquery" not in markup.lower()
    assert "bootstrap" not in markup.lower()

    home = client.get("/lecturer").get_data(as_text=True)
    for href in ("/lecturer", "/lecturer/requests", "/calendar", "/bookinghistory", "/profile"):
        assert f'href="{href}"' in home
    assert 'href="/admin"' not in home


def test_lecturer_template_queries_do_not_scale_with_rendered_appointments(
    client, app, availability_factory, appointment_factory
):
    window = availability_factory(start=FIXED_NOW + timedelta(days=1), minutes=13 * 60, slot_minutes=30)
    for slot in range(25):
        appointment_factory(
            availability_id=window.id,
            starts_at=window.starts_at + timedelta(minutes=30 * slot),
        )
    statements = []

    def record_query(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    with app.app_context():
        event.listen(db.engine, "before_cursor_execute", record_query)
        try:
            lecturer_login(client)
            response = client.get("/lecturer/requests")
            assert response.status_code == 200
        finally:
            event.remove(db.engine, "before_cursor_execute", record_query)

    assert len(statements) <= 12

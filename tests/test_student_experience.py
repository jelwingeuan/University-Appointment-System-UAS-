from datetime import timedelta

from sqlalchemy import event

from tests.conftest import login
from uas.extensions import db as orm
from uas.models import Appointment, AppointmentStatusHistory, Availability


def test_student_home_shows_next_accepted_pending_and_recent(client, app, appointment_factory, availability_factory):
    login(client, "student1@student.mmu.edu.my")
    accepted = appointment_factory(status="Accepted", purpose="Review my study plan")
    pending_window = availability_factory(start=app.config["CLOCK"]() + timedelta(days=9, hours=2))
    appointment_factory(availability_id=pending_window.id, status="Pending", purpose="Discuss course choices")
    past_start = app.config["CLOCK"]() - timedelta(days=3)
    past_window = Availability(
        lecturer_id=3,
        starts_at=past_start,
        ends_at=past_start + timedelta(hours=1),
        slot_minutes=30,
    )
    orm.session.add(past_window)
    orm.session.flush()
    appointment_factory(availability_id=past_window.id, status="Completed", purpose="Earlier advising")

    statements = []

    def count_queries(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(orm.engine, "before_cursor_execute", count_queries)
    try:
        response = client.get("/appointment")
    finally:
        event.remove(orm.engine, "before_cursor_execute", count_queries)

    markup = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Next appointment" in markup
    assert "Lecturer One" in markup
    assert "Review my study plan" in markup
    assert "Waiting for lecturer confirmation." in markup
    assert "Discuss course choices" in markup
    assert "Earlier advising" in markup
    assert f'href="/invoice?reference={accepted.public_reference}"' in markup
    assert len(statements) <= 7


def test_student_home_empty_state_links_to_booking(client):
    login(client, "student1@student.mmu.edu.my")
    markup = client.get("/appointment").get_data(as_text=True)
    assert "No confirmed appointments coming up" in markup
    assert 'href="/appointment2"' in markup


def test_student_explore_supports_faculty_and_name_filters_with_role_checks(client, faculty_factory, user_factory):
    new_faculty = faculty_factory("Faculty of Computing")
    user_factory(role="teacher", faculty_id=new_faculty.id)
    login(client, "student1@student.mmu.edu.my")

    all_results = client.get("/explore")
    assert all_results.status_code == 200
    assert "Faculty of Computing" in all_results.get_data(as_text=True)

    filtered = client.get(f"/explore?faculty_id={new_faculty.id}&q=Fixture%20User")
    filtered_markup = filtered.get_data(as_text=True)
    assert filtered.status_code == 200
    assert "Fixture User" in filtered_markup
    assert "Lecturer One" not in filtered_markup
    assert client.get("/explore?q=" + "x" * 101).status_code == 400

    client.post("/logout")
    login(client, "lecturer1@mmu.edu.my")
    assert client.get("/explore").status_code == 403
    client.post("/logout")
    login(client, "admin@mmu.edu.my")
    assert client.get("/explore").status_code == 403


def test_student_booking_is_a_progressive_accessible_form(client):
    login(client, "student1@student.mmu.edu.my")
    response = client.get("/appointment2")
    markup = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<form id="student-booking-form"' in markup
    assert 'name="availability_id"' in markup
    assert 'name="slot_start"' in markup
    assert 'name="purpose"' in markup
    assert "Review appointment request" in markup
    assert "jquery" not in markup.lower()
    assert "Find available times" in markup


def test_student_history_uses_status_cards_and_only_offers_allowed_cancellations(
    client, app, availability_factory, appointment_factory
):
    login(client, "student1@student.mmu.edu.my")
    statuses = ("Pending", "Accepted", "Rejected", "Cancelled", "Completed", "No Show")
    for index, status in enumerate(statuses):
        window = availability_factory(
            start=app.config["CLOCK"]() + timedelta(days=10 + index, hours=2),
        )
        appointment_factory(availability_id=window.id, status=status, purpose=f"Purpose {status}")

    markup = client.get("/bookinghistory").get_data(as_text=True)
    for status in statuses:
        assert f"status-{status.lower().replace(' ', '-')}" in markup
        assert status in markup
    assert markup.count("data-cancel-appointment=") == 2
    assert 'method="post"' in markup
    assert 'name="csrf_token"' in markup
    assert 'aria-labelledby="upcoming-appointments-heading"' in markup


def test_student_history_paginates_large_lists(client, app, appointment_factory):
    login(client, "student1@student.mmu.edu.my")
    original = orm.session.get(Availability, 1)
    appointments = []
    base = app.config["CLOCK"]() + timedelta(days=30)
    for index in range(26):
        start = base + timedelta(hours=index)
        window = Availability(
            lecturer_id=3,
            starts_at=start,
            ends_at=start + timedelta(minutes=30),
            slot_minutes=30,
        )
        orm.session.add(window)
        orm.session.flush()
        appointments.append(
            Appointment(
                student_id=1,
                lecturer_id=3,
                availability_id=window.id,
                starts_at=start,
                ends_at=start + timedelta(minutes=30),
                status="Pending",
                purpose=f"Paged purpose {index}",
            )
        )
    orm.session.add_all(appointments)
    orm.session.commit()

    first = client.get("/bookinghistory")
    second = client.get("/bookinghistory?page=2")
    assert first.status_code == second.status_code == 200
    assert "Page 1 of 2" in first.get_data(as_text=True)
    assert "Page 2 of 2" in second.get_data(as_text=True)
    assert original is not None


def test_student_appointment_detail_shows_status_timeline_and_is_private(client, appointment_factory):
    login(client, "student1@student.mmu.edu.my")
    appointment = appointment_factory(status="Accepted", purpose="Review my study plan")
    orm.session.add(
        AppointmentStatusHistory(
            appointment_id=appointment.id,
            from_status="Pending",
            to_status="Accepted",
            actor_user_id=3,
            created_at=appointment.created_at,
        )
    )
    orm.session.commit()
    response = client.get(f"/invoice?reference={appointment.public_reference}")
    markup = response.get_data(as_text=True)
    assert response.status_code == 200
    assert appointment.public_reference in markup
    assert "Your appointment is confirmed." in markup
    assert "Request sent" in markup
    assert "Accepted by lecturer" in markup
    assert "Review my study plan" in markup
    assert "data-cancel-appointment=" in markup
    assert f">{appointment.id}<" not in markup

    client.post("/logout")
    login(client, "student2@student.mmu.edu.my")
    assert client.get(f"/invoice?reference={appointment.public_reference}").status_code == 404


def test_student_profile_and_password_pages_keep_existing_forms_and_roles(client):
    login(client, "student1@student.mmu.edu.my")
    profile = client.get("/profile").get_data(as_text=True)
    assert "Account details" in profile
    assert 'name="username"' in profile
    assert 'name="email"' in profile
    assert 'name="phone_number"' in profile
    assert 'name="role"' not in profile
    assert "FCI" in profile
    assert 'href="/change_password"' in profile

    password = client.get("/change_password").get_data(as_text=True)
    assert "Change password" in password
    assert 'name="current_password"' in password
    assert 'name="new_password"' in password
    assert 'name="confirm_password"' in password
    assert "12 characters" in password


def test_student_booking_conflict_returns_to_selected_lecturer_and_date(client, app):
    window = orm.session.get(Availability, 1)
    orm.session.add(
        Appointment(
            student_id=2,
            lecturer_id=3,
            availability_id=window.id,
            starts_at=window.starts_at,
            ends_at=window.starts_at + timedelta(minutes=window.slot_minutes),
            status="Pending",
            purpose="Existing appointment",
        )
    )
    orm.session.commit()
    login(client, "student1@student.mmu.edu.my")
    local_date = app.config["TEST_SLOT_START"][:10]
    response = client.post(
        "/create_booking",
        data={
            "availability_id": "1",
            "slot_start": app.config["TEST_SLOT_START"],
            "purpose": "Appointment request",
            "faculty_id": "1",
            "lecturer": "3",
            "appointment_date": local_date,
        },
    )
    assert response.status_code == 302
    assert "appointment2" in response.headers["Location"]
    assert "faculty_id=1" in response.headers["Location"]

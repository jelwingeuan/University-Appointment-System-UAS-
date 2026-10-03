from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import login
from uas.booking_service import BookingConflict, create_booking
from uas.calendar import generate_recurrence
from uas.extensions import db as orm
from uas.models import Appointment


def test_monthly_recurrence_keeps_anchor_day_and_clamps_short_months():
    dates = generate_recurrence(datetime(2024, 1, 31, 10, tzinfo=UTC), datetime(2024, 3, 31, 10, tzinfo=UTC), "monthly")
    assert [v.date().isoformat() for v in dates] == ["2024-01-31", "2024-02-29", "2024-03-31"]


def test_booking_uses_ids_and_preserves_slot_duration(app):
    appointment_id, reference = create_booking(1, 1, app.config["TEST_SLOT_START"], "Project consultation")
    with app.app_context():
        row = orm.session.get(Appointment, appointment_id)
        assert (row.student_id, row.lecturer_id, row.availability_id) == (1, 3, 1)
        assert row.public_reference == reference
        assert row.ends_at - row.starts_at == timedelta(minutes=30)


def test_booking_normalizes_equivalent_offset_to_utc(app):
    requested = datetime.fromisoformat(app.config["TEST_SLOT_START"])
    malaysia_value = requested.astimezone(requested.tzinfo.__class__(timedelta(hours=8))).isoformat()
    appointment_id, _ = create_booking(1, 1, malaysia_value, "Timezone validation")
    with app.app_context():
        assert orm.session.get(Appointment, appointment_id).starts_at == requested


def test_overlapping_booking_is_rejected_and_rolled_back(app):
    create_booking(1, 1, app.config["TEST_SLOT_START"], "First")
    with pytest.raises(BookingConflict):
        create_booking(2, 1, app.config["TEST_SLOT_START"], "Second")
    with app.app_context():
        assert orm.session.query(Appointment).count() == 1


def test_concurrent_booking_allows_exactly_one(app):
    def attempt(student_id):
        try:
            with app.app_context():
                create_booking(student_id, 1, app.config["TEST_SLOT_START"], f"Student {student_id}")
            return "created"
        except BookingConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    assert sorted(results) == ["conflict", "created"]
    with app.app_context():
        assert orm.session.query(Appointment).count() == 1


def test_lecturer_cannot_update_another_lecturers_appointment(client, app):
    appointment_id, _ = create_booking(1, 1, app.config["TEST_SLOT_START"], "Consultation")
    login(client, "lecturer2@mmu.edu.my")
    assert client.post("/accept_booking", data={"id": appointment_id}).status_code == 403
    with app.app_context():
        assert orm.session.get(Appointment, appointment_id).status == "Pending"


def test_status_transitions_and_released_slot(client, app):
    appointment_id, _ = create_booking(1, 1, app.config["TEST_SLOT_START"], "Consultation")
    login(client, "lecturer1@mmu.edu.my")
    assert client.post("/reject_booking", data={"id": appointment_id}).status_code == 302
    client.post("/logout")
    create_booking(2, 1, app.config["TEST_SLOT_START"], "Replacement")
    with app.app_context():
        assert orm.session.query(Appointment).count() == 2

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from app import generate_recurrence
from booking_service import BookingConflict, create_booking
from database import connect_database
from tests.conftest import login


def test_monthly_recurrence_keeps_anchor_day_and_clamps_short_months():
    dates = generate_recurrence(
        datetime(2024, 1, 31, 10, 0),
        datetime(2024, 3, 31, 10, 0),
        "monthly",
    )
    assert [value.date().isoformat() for value in dates] == ["2024-01-31", "2024-02-29", "2024-03-31"]


def test_booking_uses_ids_and_preserves_slot_duration(app, db):
    appointment_id, reference = create_booking(
        app.config["DATABASE_PATH"],
        student_id=1,
        availability_id=1,
        requested_start=app.config["TEST_SLOT_START"],
        purpose="Project consultation",
    )
    appointment = db.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    assert appointment["student_id"] == 1
    assert appointment["lecturer_id"] == 3
    assert appointment["availability_id"] == 1
    assert appointment["public_reference"] == reference
    assert datetime.fromisoformat(appointment["ends_at"]) - datetime.fromisoformat(appointment["starts_at"]) == pytest.approx(
        __import__("datetime").timedelta(minutes=30)
    )


def test_booking_normalizes_equivalent_offset_to_utc(app, db):
    requested = datetime.fromisoformat(app.config["TEST_SLOT_START"])
    malaysia_value = requested.astimezone(timezone(timedelta(hours=8))).isoformat()
    appointment_id, _ = create_booking(
        app.config["DATABASE_PATH"], 1, 1, malaysia_value, "Timezone validation"
    )
    stored = db.execute(
        "SELECT starts_at FROM appointments WHERE id = ?", (appointment_id,)
    ).fetchone()[0]
    assert stored == requested.astimezone(timezone.utc).isoformat()


def test_overlapping_booking_is_rejected_and_rolled_back(app, db):
    create_booking(app.config["DATABASE_PATH"], 1, 1, app.config["TEST_SLOT_START"], "First")
    with pytest.raises(BookingConflict):
        create_booking(app.config["DATABASE_PATH"], 2, 1, app.config["TEST_SLOT_START"], "Second")
    assert db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1


def test_concurrent_booking_allows_exactly_one(app):
    def attempt(student_id):
        try:
            create_booking(
                app.config["DATABASE_PATH"],
                student_id,
                1,
                app.config["TEST_SLOT_START"],
                f"Student {student_id}",
            )
            return "created"
        except BookingConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, [1, 2]))
    assert sorted(results) == ["conflict", "created"]
    with connect_database(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1


def test_lecturer_cannot_update_another_lecturers_appointment(client, app, db):
    appointment_id, _ = create_booking(
        app.config["DATABASE_PATH"], 1, 1, app.config["TEST_SLOT_START"], "Consultation"
    )
    login(client, "lecturer2@mmu.edu.my")
    assert client.post("/accept_booking", data={"id": appointment_id}).status_code == 403
    assert db.execute("SELECT status FROM appointments WHERE id = ?", (appointment_id,)).fetchone()[0] == "Pending"


def test_status_transitions_and_released_slot(client, app, db):
    appointment_id, _ = create_booking(
        app.config["DATABASE_PATH"], 1, 1, app.config["TEST_SLOT_START"], "Consultation"
    )
    login(client, "lecturer1@mmu.edu.my")
    assert client.post("/reject_booking", data={"id": appointment_id}).status_code == 302
    client.post("/logout")
    create_booking(app.config["DATABASE_PATH"], 2, 1, app.config["TEST_SLOT_START"], "Replacement")
    assert db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 2

import sqlite3

import pytest

from database import connect_database


def test_foreign_keys_and_unique_reference_are_enforced(app):
    with connect_database(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO appointments
                    (public_reference, student_id, lecturer_id, availability_id, starts_at, ends_at, purpose, status)
                VALUES ('missing-user', 999, 3, 1, ?, ?, 'x', 'Pending')
                """,
                (app.config["TEST_SLOT_START"], app.config["TEST_SLOT_START"]),
            )


def test_user_deletion_is_restricted_when_records_exist(app):
    with connect_database(app.config["DATABASE_PATH"]) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM users WHERE id = 3")

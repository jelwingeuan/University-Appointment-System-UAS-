import sqlite3

import bcrypt

from migrate_database import migrate_database


def test_legacy_database_is_backed_up_and_migrated(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, role TEXT, faculty TEXT, username TEXT,
            email TEXT, phone_number TEXT, password TEXT
        );
        CREATE TABLE facultyhub (id INTEGER PRIMARY KEY, faculty_name TEXT, faculty_image TEXT);
        CREATE TABLE calendar (
            id INTEGER PRIMARY KEY, lecturer TEXT, event_title TEXT, event_date TEXT,
            end_date TEXT, start_time TEXT, end_time TEXT, status TEXT,
            repeat_type TEXT, event_type TEXT, slot_size INTEGER
        );
        CREATE TABLE appointments (
            id INTEGER PRIMARY KEY, booking_id INTEGER, student TEXT, lecturer TEXT,
            appointment_date TEXT, appointment_time TEXT, purpose TEXT, status TEXT
        );
        """
    )
    password = bcrypt.hashpw(b"CorrectHorse1", bcrypt.gensalt()).decode()
    connection.executemany(
        "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (7, "student", "FCI", "Student", "student@student.mmu.edu.my", "0101", password),
            (9, "teacher", "FCI", "Lecturer", "lecturer@mmu.edu.my", "0102", password),
        ],
    )
    connection.execute(
        "INSERT INTO calendar VALUES (3, 'Lecturer', 'Consultation Hour', '2026-11-02', '2026-11-02', '10:00', '11:00', 'Pending', '', 'Work', 30)"
    )
    connection.execute(
        "INSERT INTO appointments VALUES (4, 123456, 'Student', 'Lecturer', '2026-11-02', '10:00 - 10:30', 'Advice', 'Pending')"
    )
    connection.commit()
    connection.close()

    result = migrate_database(path)

    assert result["backup"]
    assert not result["issues"]
    migrated = sqlite3.connect(path)
    migrated.row_factory = sqlite3.Row
    assert migrated.execute("SELECT id FROM users WHERE username = 'Student'").fetchone()[0] == 7
    appointment = migrated.execute("SELECT * FROM appointments").fetchone()
    assert appointment["student_id"] == 7
    assert appointment["lecturer_id"] == 9
    assert appointment["availability_id"]
    assert appointment["public_reference"] != "123456"
    migrated.close()

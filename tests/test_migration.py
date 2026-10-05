import json
import sqlite3
from contextlib import closing

import bcrypt
import pytest

from app import create_app
from uas.extensions import db as orm
from uas.legacy_import import import_sqlite
from uas.models import Appointment, Availability, Faculty, User


def legacy_source(path):
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, role TEXT, faculty TEXT, username TEXT,
                email TEXT, phone_number TEXT, password TEXT);
            CREATE TABLE facultyhub (id INTEGER PRIMARY KEY, faculty_name TEXT, faculty_image TEXT);
            CREATE TABLE calendar (id INTEGER PRIMARY KEY, lecturer TEXT, event_title TEXT, event_date TEXT,
                end_date TEXT, start_time TEXT, end_time TEXT, status TEXT, repeat_type TEXT,
                event_type TEXT, slot_size INTEGER);
            CREATE TABLE appointments (id INTEGER PRIMARY KEY, booking_id INTEGER, student TEXT,
                lecturer TEXT, appointment_date TEXT, appointment_time TEXT, purpose TEXT, status TEXT);
        """)
        password = bcrypt.hashpw(b"CorrectHorse1", bcrypt.gensalt()).decode()
        connection.executemany(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (7, "student", "FCI", "Student", "student@student.mmu.edu.my", "0101", password),
                (9, "teacher", "FCI", "Lecturer", "lecturer@mmu.edu.my", "0102", password),
            ],
        )
        connection.execute(
            "INSERT INTO calendar VALUES (3, 'Lecturer', 'Consultation', '2026-11-02', '2026-11-02', '10:00', '11:00', 'Pending', '', 'Work', 30)"
        )
        connection.execute(
            "INSERT INTO appointments VALUES (4, 123456, 'Student', 'Lecturer', '2026-11-02', '10:00 - 10:30', 'Advice', 'Pending')"
        )
        connection.commit()


def test_legacy_import_preserves_ids_and_backup(tmp_path):
    source = tmp_path / "legacy.db"
    legacy_source(source)
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "migration-test",
            "DATABASE_PATH": str(tmp_path / "dest.db"),
            "WTF_CSRF_ENABLED": False,
        }
    )
    with app.app_context():
        result = app.test_cli_runner().invoke(args=["db", "upgrade"])
        assert result.exit_code == 0, result.output
        imported = import_sqlite(source, orm.session)
        assert imported["counts"]["users"] == {"source": 2, "imported": 2}
        assert imported["counts"]["appointments"]["imported"] == 1
        assert not imported["issues"]
        assert orm.session.get(User, 7).username == "Student"
        appointment = orm.session.get(Appointment, 4)
        assert (appointment.student_id, appointment.lecturer_id) == (7, 9)
        assert appointment.public_reference != "123456"
    assert (tmp_path / "legacy.db").exists()
    assert imported["backup"] and __import__("pathlib").Path(imported["backup"]).exists()
    report = json.loads(__import__("pathlib").Path(imported["report"]).read_text())
    assert report["counts"]["availability"]["imported"] == 1


def test_import_refuses_nonempty_destination(tmp_path):
    source = tmp_path / "legacy.db"
    legacy_source(source)
    app = create_app({"TESTING": True, "SECRET_KEY": "migration-test", "DATABASE_PATH": str(tmp_path / "dest.db")})
    with app.app_context():
        app.test_cli_runner().invoke(args=["db", "upgrade"])
        orm.session.add(Faculty(id=1, faculty_name="Existing"))
        orm.session.flush()
        orm.session.add(User(role="student", faculty_id=1, username="x", email="x@y", phone_number="x", password_hash="x"))
        orm.session.commit()
        with pytest.raises(ValueError, match="must be empty"):
            import_sqlite(source, orm.session)


def test_import_refuses_source_destination_collision(tmp_path):
    source = tmp_path / "same.db"
    legacy_source(source)
    app = create_app({"TESTING": True, "SECRET_KEY": "migration-test", "DATABASE_PATH": str(source)})
    with app.app_context():
        app.test_cli_runner().invoke(args=["db", "upgrade"])
        with pytest.raises(ValueError, match="different databases"):
            import_sqlite(source, orm.session)
    assert not list(tmp_path.glob("same.db.backup-*"))


def test_intermediate_normalized_import_preserves_uuid_reference(tmp_path):
    source = tmp_path / "intermediate.db"
    with closing(sqlite3.connect(source)) as connection:
        connection.executescript("""
            CREATE TABLE faculties (id INTEGER PRIMARY KEY, faculty_name TEXT, faculty_image TEXT);
            CREATE TABLE users (id INTEGER PRIMARY KEY, role TEXT, faculty_id INTEGER, username TEXT,
            email TEXT, phone_number TEXT, password_hash TEXT, active INTEGER);
            CREATE TABLE availability (id INTEGER PRIMARY KEY, lecturer_id INTEGER, starts_at TEXT,
                ends_at TEXT, slot_minutes INTEGER);
            CREATE TABLE appointments (id INTEGER PRIMARY KEY, public_reference TEXT, student_id INTEGER,
                lecturer_id INTEGER, availability_id INTEGER, starts_at TEXT, ends_at TEXT,
                purpose TEXT, status TEXT);
        """)
        hashed = bcrypt.hashpw(b"CorrectHorse1", bcrypt.gensalt()).decode()
        connection.execute("INSERT INTO faculties VALUES (6, 'FCI', 'fci.png')")
        connection.executemany(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (12, "student", 6, "Student", "s@student.mmu.edu.my", "s1", hashed, 1),
                (18, "teacher", 6, "Lecturer", "l@mmu.edu.my", "l1", hashed, 1),
            ],
        )
        connection.execute(
            "INSERT INTO availability VALUES (22, 18, '2026-11-02T02:00:00+00:00', '2026-11-02T03:00:00+00:00', 30)"
        )
        connection.execute(
            "INSERT INTO appointments VALUES (33, '12345678-1234-4234-8234-123456789abc', 12, 18, 22, '2026-11-02T02:00:00+00:00', '2026-11-02T02:30:00+00:00', 'Advice', 'Accepted')"
        )
        connection.commit()
    app = create_app(
        {"TESTING": True, "SECRET_KEY": "migration-test", "DATABASE_PATH": str(tmp_path / "normalized-dest.db")}
    )
    with app.app_context():
        app.test_cli_runner().invoke(args=["db", "upgrade"])
        result = import_sqlite(source, orm.session)
        assert result["counts"]["appointments"]["imported"] == 1
        appointment = orm.session.get(Appointment, 33)
        assert appointment.public_reference == "12345678-1234-4234-8234-123456789abc"
        assert (appointment.student_id, appointment.lecturer_id, appointment.availability_id) == (12, 18, 22)
        assert orm.session.get(User, 12).faculty == "FCI"


def test_legacy_weekly_availability_expands_through_end_date(tmp_path):
    source = tmp_path / "recurrence.db"
    legacy_source(source)
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("UPDATE calendar SET end_date='2026-11-16', repeat_type='weekly'")
        connection.commit()
    app = create_app(
        {"TESTING": True, "SECRET_KEY": "migration-test", "DATABASE_PATH": str(tmp_path / "recurrence-dest.db")}
    )
    with app.app_context():
        app.test_cli_runner().invoke(args=["db", "upgrade"])
        result = import_sqlite(source, orm.session)
        assert result["counts"]["availability"] == {"source": 1, "imported": 1, "windows_created": 3}
        assert orm.session.query(Availability).count() == 3


def test_import_reports_invalid_roles_and_statuses_without_defaulting(tmp_path):
    source = tmp_path / "invalid.db"
    legacy_source(source)
    with closing(sqlite3.connect(source)) as connection:
        connection.execute(
            "INSERT INTO users VALUES (10, 'faculty', 'FCI', 'Invalid', 'invalid@mmu.edu.my', '0103', 'hash')"
        )
        connection.execute("UPDATE appointments SET status='Done'")
        connection.commit()
    app = create_app(
        {"TESTING": True, "SECRET_KEY": "migration-test", "DATABASE_PATH": str(tmp_path / "invalid-dest.db")}
    )
    with app.app_context():
        app.test_cli_runner().invoke(args=["db", "upgrade"])
        result = import_sqlite(source, orm.session)
        reasons = [issue["reason"] for issue in result["issues"]]
        assert any("invalid role" in reason for reason in reasons)
        assert any("invalid status" in reason for reason in reasons)


def test_import_commit_failure_rolls_back_destination_but_keeps_backup(tmp_path, monkeypatch):
    source = tmp_path / "failure.db"
    legacy_source(source)
    app = create_app(
        {"TESTING": True, "SECRET_KEY": "migration-test", "DATABASE_PATH": str(tmp_path / "failure-dest.db")}
    )
    with app.app_context():
        app.test_cli_runner().invoke(args=["db", "upgrade"])

        real_commit = orm.session.commit
        commit_calls = 0

        def fail_final_commit():
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls == 1:
                return real_commit()
            raise RuntimeError("injected commit failure")

        monkeypatch.setattr(orm.session, "commit", fail_final_commit)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            import_sqlite(source, orm.session)
        monkeypatch.undo()
        orm.session.rollback()
        assert orm.session.query(User).count() == 0
        backups = list(tmp_path.glob("failure.db.backup-*"))
        assert len(backups) == 1

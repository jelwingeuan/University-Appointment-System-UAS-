import os
import sqlite3
from datetime import datetime, timedelta, timezone

os.environ.setdefault("FLASK_SECRET_KEY", "test-import-secret-with-32-characters")
os.environ.setdefault("LECTURER_REGISTRATION_SECRET", "test-import-lecturer-secret")
os.environ.setdefault("APP_ENV", "development")

import bcrypt
import pytest

from app import create_app
from database import connect_database, init_schema


@pytest.fixture()
def app(tmp_path):
    database_path = tmp_path / "test.db"
    test_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_PATH": str(database_path),
            "LECTURER_REGISTRATION_SECRET": "lecturer-test-secret",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "UNIVERSITY_TIMEZONE": "Asia/Kuala_Lumpur",
        }
    )
    with connect_database(database_path) as connection:
        init_schema(connection)
        users = [
            (1, "student", "FCI", "Student One", "student1@student.mmu.edu.my", "0100000001"),
            (2, "student", "FCI", "Student Two", "student2@student.mmu.edu.my", "0100000002"),
            (3, "teacher", "FCI", "Lecturer One", "lecturer1@mmu.edu.my", "0100000003"),
            (4, "teacher", "FCI", "Lecturer Two", "lecturer2@mmu.edu.my", "0100000004"),
            (5, "admin", "Administration", "Administrator", "admin@mmu.edu.my", "0100000005"),
        ]
        password_hash = bcrypt.hashpw(b"CorrectHorse1", bcrypt.gensalt()).decode()
        connection.executemany(
            """
            INSERT INTO users (id, role, faculty, username, email, phone_number, password)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [(*user, password_hash) for user in users],
        )
        start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=7)
        start = start.replace(hour=2, minute=0, second=0)
        end = start + timedelta(hours=2)
        connection.execute(
            """
            INSERT INTO availability (id, lecturer_id, starts_at, ends_at, slot_minutes)
            VALUES (1, 3, ?, ?, 30)
            """,
            (start.isoformat(), end.isoformat()),
        )
        connection.commit()
    test_app.config["TEST_SLOT_START"] = start.isoformat()
    yield test_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    connection = sqlite3.connect(app.config["DATABASE_PATH"])
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    yield connection
    connection.close()


def login(client, email, password="CorrectHorse1"):
    return client.post("/login", data={"email": email, "password": password})

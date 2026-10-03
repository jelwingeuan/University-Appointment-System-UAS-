import os
import shutil
from datetime import UTC, datetime, timedelta

os.environ.setdefault("FLASK_SECRET_KEY", "test-import-secret-with-32-characters")
os.environ.setdefault("LECTURER_REGISTRATION_SECRET", "test-import-lecturer-secret")
os.environ.setdefault("APP_ENV", "development")

import bcrypt
import pytest

from app import create_app
from uas.extensions import db as orm
from uas.models import Availability, Faculty, User


@pytest.fixture()
def app(tmp_path):
    database_path = tmp_path / "test.db"
    config = {
        "TESTING": True,
        "SECRET_KEY": "test-only-secret",
        "LECTURER_REGISTRATION_SECRET": "lecturer-test-secret",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
        "UNIVERSITY_TIMEZONE": "Asia/Kuala_Lumpur",
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "CONTENT_PATH": str(tmp_path / "content.json"),
        "CLOCK": lambda: datetime.now(UTC),
    }
    if os.getenv("TEST_DATABASE_URL"):
        config["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    else:
        config["DATABASE_PATH"] = str(database_path)
    test_app = create_app(config)
    shutil.copyfile("content.json", test_app.config["CONTENT_PATH"])
    with test_app.app_context():
        orm.create_all()
        faculty = Faculty(id=1, faculty_name="FCI")
        admin_faculty = Faculty(id=2, faculty_name="Administration")
        orm.session.add_all([faculty, admin_faculty])
        orm.session.flush()
        password_hash = bcrypt.hashpw(b"CorrectHorse1", bcrypt.gensalt()).decode()
        users = [
            User(
                id=1,
                role="student",
                faculty_id=1,
                username="Student One",
                email="student1@student.mmu.edu.my",
                phone_number="0100000001",
                password=password_hash,
            ),
            User(
                id=2,
                role="student",
                faculty_id=1,
                username="Student Two",
                email="student2@student.mmu.edu.my",
                phone_number="0100000002",
                password=password_hash,
            ),
            User(
                id=3,
                role="teacher",
                faculty_id=1,
                username="Lecturer One",
                email="lecturer1@mmu.edu.my",
                phone_number="0100000003",
                password=password_hash,
            ),
            User(
                id=4,
                role="teacher",
                faculty_id=1,
                username="Lecturer Two",
                email="lecturer2@mmu.edu.my",
                phone_number="0100000004",
                password=password_hash,
            ),
            User(
                id=5,
                role="admin",
                faculty_id=2,
                username="Administrator",
                email="admin@mmu.edu.my",
                phone_number="0100000005",
                password=password_hash,
            ),
        ]
        orm.session.add_all(users)
        start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=7)
        start = start.replace(hour=2, minute=0, second=0)
        orm.session.add(
            Availability(id=1, lecturer_id=3, starts_at=start, ends_at=start + timedelta(hours=2), slot_minutes=30)
        )
        orm.session.commit()
        if orm.engine.dialect.name == "postgresql":
            from sqlalchemy import text

            for table in ("users", "faculties", "availability", "appointments"):
                orm.session.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table}), 1), true)"
                    )
                )
            orm.session.commit()
        test_app.config["TEST_SLOT_START"] = start.isoformat()
    context = test_app.app_context()
    context.push()
    yield test_app
    context.pop()
    with test_app.app_context():
        orm.session.remove()
        orm.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, email, password="CorrectHorse1"):
    return client.post("/login", data={"email": email, "password": password})

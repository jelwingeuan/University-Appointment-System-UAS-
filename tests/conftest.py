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
from uas.models import Appointment, Availability, Faculty, User

FIXED_NOW = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def close_standalone_test_apps(request, monkeypatch):
    creator = getattr(request.module, "create_app", None)
    created = []
    if creator is not None:
        def tracked_create_app(*args, **kwargs):
            test_app = creator(*args, **kwargs)
            created.append(test_app)
            return test_app

        monkeypatch.setattr(request.module, "create_app", tracked_create_app)
    yield
    for test_app in created:
        with test_app.app_context():
            orm.session.remove()
            test_app.extensions["sqlalchemy"].engine.dispose()


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
        "CLOCK": lambda: FIXED_NOW,
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
        start = FIXED_NOW + timedelta(days=7)
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
        orm.engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, email, password="CorrectHorse1"):
    return client.post("/login", data={"email": email, "password": password})


@pytest.fixture()
def user_factory():
    def create(*, role="student", faculty_id=1, active=True):
        number = orm.session.query(User).count() + 20
        user = User(
            role=role,
            faculty_id=faculty_id,
            username=f"Fixture User {number}",
            email=f"fixture{number}@example.edu",
            phone_number=f"+6012000{number:04d}",
            password=bcrypt.hashpw(b"CorrectHorse1", bcrypt.gensalt()).decode(),
            active=active,
        )
        orm.session.add(user)
        orm.session.commit()
        return user

    return create


@pytest.fixture()
def availability_factory():
    def create(*, lecturer_id=3, start=None, minutes=60, slot_minutes=30):
        start = start or FIXED_NOW + timedelta(days=8, hours=2)
        row = Availability(
            lecturer_id=lecturer_id,
            starts_at=start,
            ends_at=start + timedelta(minutes=minutes),
            slot_minutes=slot_minutes,
        )
        orm.session.add(row)
        orm.session.commit()
        return row

    return create


@pytest.fixture()
def faculty_factory():
    def create(name=None):
        number = orm.session.query(Faculty).count() + 1
        row = Faculty(faculty_name=name or f"Test Faculty {number}")
        orm.session.add(row)
        orm.session.commit()
        return row

    return create


@pytest.fixture()
def appointment_factory():
    def create(*, student_id=1, lecturer_id=3, availability_id=1, starts_at=None, status="Pending", purpose="Advice"):
        window = orm.session.get(Availability, availability_id)
        starts_at = starts_at or window.starts_at
        row = Appointment(
            student_id=student_id,
            lecturer_id=lecturer_id,
            availability_id=availability_id,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=window.slot_minutes),
            status=status,
            purpose=purpose,
        )
        orm.session.add(row)
        orm.session.commit()
        return row

    return create

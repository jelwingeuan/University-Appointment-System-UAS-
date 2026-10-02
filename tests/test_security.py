import re

import pytest

from app import create_app
from tests.conftest import login


def test_valid_logins_and_logout(client):
    for email, destination in [
        ("student1@student.mmu.edu.my", "/"),
        ("lecturer1@mmu.edu.my", "/"),
        ("admin@mmu.edu.my", "/admin"),
    ]:
        response = login(client, email)
        assert response.status_code == 302
        assert response.headers["Location"].endswith(destination)
        assert client.post("/logout").status_code == 302


def test_invalid_login_is_generic(client):
    response = login(client, "missing@example.com", "wrong-password")
    assert response.status_code == 302
    page = client.get("/login").get_data(as_text=True)
    assert "Invalid email or password" in page
    assert "missing@example.com" not in page


def test_protected_and_role_routes(client):
    assert client.get("/profile").status_code == 302
    login(client, "student1@student.mmu.edu.my")
    assert client.get("/admin").status_code == 403
    assert client.get("/calendar").status_code == 403
    client.post("/logout")
    login(client, "lecturer1@mmu.edu.my")
    assert client.get("/admin").status_code == 403
    assert client.get("/appointment2").status_code == 403


def test_getpin_is_gone(client):
    assert client.get("/getpin").status_code == 404


def test_csrf_rejects_missing_token(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "csrf-test-secret",
            "DATABASE_PATH": str(tmp_path / "csrf.db"),
            "LECTURER_REGISTRATION_SECRET": "lecturer-test-secret",
            "WTF_CSRF_ENABLED": True,
            "RATELIMIT_ENABLED": False,
        }
    )
    client = app.test_client()
    response = client.post("/login", data={"email": "x@example.com", "password": "x"})
    assert response.status_code == 400


def test_production_requires_strong_secret_and_disables_debug(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FLASK_DEBUG", "1")
    monkeypatch.setenv("FLASK_SECRET_KEY", "too-short")
    with pytest.raises(RuntimeError, match="at least 32"):
        create_app()

    monkeypatch.setenv("FLASK_SECRET_KEY", "a-production-secret-with-32-characters")
    production_app = create_app(
        {
            "DATABASE_PATH": str(tmp_path / "production.db"),
            "RATELIMIT_ENABLED": False,
        }
    )
    assert production_app.debug is False
    assert production_app.config["SESSION_COOKIE_SECURE"] is True


def test_security_headers_are_set(client):
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["Referrer-Policy"] == "same-origin"


def test_no_hardcoded_or_plaintext_secrets():
    source = open("app.py", encoding="utf-8").read()
    assert 'secret_key = "jelwin"' not in source.lower()
    assert "admin.json" not in source
    assert "pin.json" not in source
    assert not re.search(r"random\.randint\(", source)


def test_student_cannot_change_another_students_profile(client, db):
    login(client, "student1@student.mmu.edu.my")
    response = client.post(
        "/update_user_info",
        data={"id": 2, "username": "Changed", "email": "changed@example.com", "phone_number": "019"},
    )
    assert response.status_code == 302
    other = db.execute("SELECT username FROM users WHERE id = 2").fetchone()
    assert other["username"] == "Student Two"

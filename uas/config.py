import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def flag(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def database_url(value):
    if value.startswith(("postgres://", "postgresql://")):
        return "postgresql+psycopg://" + value.split("://", 1)[1]
    return value


class Config:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    WTF_CSRF_TIME_LIMIT = 3600
    CONTENT_PATH = str(ROOT / "content.json")
    UPLOAD_FOLDER = str(ROOT / "static" / "faculty_pp")


class DevelopmentConfig(Config):
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True
    DEBUG = False


class TestingConfig(Config):
    TESTING = True
    SESSION_COOKIE_SECURE = False
    SECRET_KEY = "isolated-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


def configure(app, overrides):
    load_dotenv(ROOT / ".env")
    testing = bool(overrides.get("TESTING")) or os.getenv("APP_ENV", "").lower() == "testing"
    environment = "testing" if testing else os.getenv("APP_ENV", "production").lower()
    classes = {"testing": TestingConfig, "development": DevelopmentConfig, "production": ProductionConfig}
    if environment not in classes:
        raise RuntimeError("APP_ENV must be development, testing, or production")
    app.config.from_object(classes[environment])
    test_root = Path(tempfile.mkdtemp(prefix="uas-test-")) if testing else None
    if test_root:
        app.config.update(CONTENT_PATH=str(test_root / "content.json"), UPLOAD_FOLDER=str(test_root / "uploads"))
    if not testing:
        app.config.update(
            SECRET_KEY=os.getenv("FLASK_SECRET_KEY"),
            SQLALCHEMY_DATABASE_URI=database_url(
                os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'instance' / 'uas.db'}")
            ),
            LECTURER_REGISTRATION_SECRET=os.getenv("LECTURER_REGISTRATION_SECRET"),
            SESSION_COOKIE_SECURE=flag("SESSION_COOKIE_SECURE", environment == "production"),
            DEBUG=flag("FLASK_DEBUG"),
        )
    app.config.update(
        UNIVERSITY_TIMEZONE="Asia/Kuala_Lumpur" if testing else os.getenv("UNIVERSITY_TIMEZONE", "Asia/Kuala_Lumpur"),
        RATELIMIT_STORAGE_URI="memory://" if testing else os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
    )
    app.config.update(overrides)
    if testing and overrides.get("DATABASE_PATH"):
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{Path(overrides['DATABASE_PATH']).resolve()}"
    if testing and overrides.get("DATABASE_URL"):
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url(overrides["DATABASE_URL"])
    if (
        testing
        and os.getenv("TEST_DATABASE_URL")
        and not overrides.get("DATABASE_PATH")
        and not overrides.get("DATABASE_URL")
    ):
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url(os.environ["TEST_DATABASE_URL"])
    app.config["APP_ENV"] = environment
    if environment == "production":
        app.config.update(DEBUG=False, SESSION_COOKIE_SECURE=True)
    secret = app.config.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("FLASK_SECRET_KEY is required")
    if not testing and len(secret) < 32:
        raise RuntimeError("FLASK_SECRET_KEY must contain at least 32 characters")

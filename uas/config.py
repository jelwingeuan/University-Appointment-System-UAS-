import os
import tempfile
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

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
    UPLOAD_FOLDER = str(ROOT / "instance" / "uploads")
    MAX_IMAGE_PIXELS = 20_000_000
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_REFRESH_EACH_REQUEST = False
    LOGIN_DISABLED = False


class DevelopmentConfig(Config):
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True
    DEBUG = False
    SESSION_PROTECTION = "strong"


class TestingConfig(Config):
    TESTING = True
    SESSION_COOKIE_SECURE = False
    SECRET_KEY = "isolated-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


def configure(app, overrides):
    environment_hint = str(overrides.get("APP_ENV", os.getenv("APP_ENV", ""))).lower()
    testing = bool(overrides.get("TESTING")) or environment_hint == "testing"
    if not testing:
        load_dotenv(ROOT / ".env")
    requested_environment = str(overrides.get("APP_ENV", os.getenv("APP_ENV", "production"))).lower()
    environment = "testing" if testing else requested_environment
    classes = {"testing": TestingConfig, "development": DevelopmentConfig, "production": ProductionConfig}
    if environment not in classes:
        raise RuntimeError("APP_ENV must be development, testing, or production")
    app.config.from_object(classes[environment])
    test_root = Path(tempfile.mkdtemp(prefix="uas-test-")) if testing else None
    if test_root:
        app.config.update(CONTENT_PATH=str(test_root / "content.json"), UPLOAD_FOLDER=str(test_root / "uploads"))
    if not testing:
        database = os.getenv("DATABASE_URL")
        if environment == "production" and not database and "SQLALCHEMY_DATABASE_URI" not in overrides:
            raise RuntimeError("DATABASE_URL must be explicitly configured in production")
        app.config.update(
            SECRET_KEY=os.getenv("FLASK_SECRET_KEY"),
            SQLALCHEMY_DATABASE_URI=database_url(database or f"sqlite:///{ROOT / 'instance' / 'uas.db'}"),
            LECTURER_REGISTRATION_SECRET=os.getenv("LECTURER_REGISTRATION_SECRET"),
            SESSION_COOKIE_SECURE=flag("SESSION_COOKIE_SECURE", environment == "production"),
            DEBUG=flag("FLASK_DEBUG"),
        )
    app.config.update(
        UNIVERSITY_TIMEZONE="Asia/Kuala_Lumpur" if testing else os.getenv("UNIVERSITY_TIMEZONE", "Asia/Kuala_Lumpur"),
        RATELIMIT_STORAGE_URI=(
            "memory://" if testing else os.getenv("RATELIMIT_STORAGE_URI", "memory://")
        ),
        IMAGE_STORAGE_FACTORY=None if testing else os.getenv("IMAGE_STORAGE_FACTORY"),
        MAIL_DELIVERY_FACTORY=None if testing else os.getenv("MAIL_DELIVERY_FACTORY"),
        REQUIRE_EMAIL_VERIFICATION=False if testing else flag("REQUIRE_EMAIL_VERIFICATION"),
        TRUSTED_HOSTS=None if testing else _csv(os.getenv("TRUSTED_HOSTS")),
    )
    app.config.update(overrides)
    if overrides.get("DATABASE_URL"):
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url(overrides["DATABASE_URL"])
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
    secret = app.config.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("FLASK_SECRET_KEY is required")
    if not testing and len(secret) < 32:
        raise RuntimeError("FLASK_SECRET_KEY must contain at least 32 characters")
    if environment == "production":
        app.config.update(
            DEBUG=False,
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            SESSION_PROTECTION="strong",
            WTF_CSRF_ENABLED=True,
            RATELIMIT_ENABLED=True,
        )
        uri = app.config.get("SQLALCHEMY_DATABASE_URI")
        if not (overrides.get("DATABASE_URL") or os.getenv("DATABASE_URL")):
            raise RuntimeError("DATABASE_URL must be explicitly configured in production")
        try:
            backend = make_url(uri).get_backend_name() if uri else ""
        except (ArgumentError, ValueError, TypeError):
            backend = ""
        if backend != "postgresql" and not (backend == "sqlite" and flag("ALLOW_PRODUCTION_SQLITE")):
            raise RuntimeError("Production requires DATABASE_URL for PostgreSQL; set ALLOW_PRODUCTION_SQLITE=1 only for an intentional override")
        limiter_uri = app.config.get("RATELIMIT_STORAGE_URI", "")
        if not limiter_uri.startswith(("redis://", "rediss://", "redis+unix://")):
            raise RuntimeError("RATELIMIT_STORAGE_URI must configure shared Redis storage in production")
        if not app.config.get("IMAGE_STORAGE_FACTORY"):
            raise RuntimeError("IMAGE_STORAGE_FACTORY must configure durable image storage in production")
        if app.config.get("REQUIRE_EMAIL_VERIFICATION") and not app.config.get("MAIL_DELIVERY_FACTORY"):
            raise RuntimeError("MAIL_DELIVERY_FACTORY is required when email verification is enabled")
        app.config["PROXY_FIX_COUNTS"] = {
            name: _nonnegative_int(os.getenv(f"PROXY_FIX_{name.upper()}", "0"))
            for name in ("x_for", "x_proto", "x_host", "x_port", "x_prefix")
        }


def _csv(value):
    return [item.strip() for item in value.split(",") if item.strip()] if value else None


def _nonnegative_int(value):
    try:
        result = int(value)
    except ValueError as exc:
        raise RuntimeError("Proxy hop counts must be nonnegative integers") from exc
    if result < 0:
        raise RuntimeError("Proxy hop counts must be nonnegative integers")
    return result

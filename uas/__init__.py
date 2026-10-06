import os
import re
import time
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from flask import Flask, g, url_for
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import HTTPException

from .config import ROOT, configure
from .extensions import csrf, db, limiter, login_manager, migrate
from .models import User
from .observability import configure_logging


def create_app(test_config=None):
    overrides = test_config or {}
    app = Flask(__name__, static_folder=str(ROOT / "static"), template_folder=str(ROOT / "templates"))
    configure(app, overrides)
    configure_logging(app)
    ZoneInfo(app.config["UNIVERSITY_TIMEZONE"])
    from .storage import create_image_storage

    app.extensions["image_storage"] = create_image_storage(app)
    database_url = app.config["SQLALCHEMY_DATABASE_URI"]
    if database_url.startswith("sqlite:///"):
        Path(database_url.removeprefix("sqlite:///")).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    if database_url.startswith("sqlite:///"):
        sqlite_path = Path(database_url.removeprefix("sqlite:///"))
        if not sqlite_path.is_absolute():
            sqlite_path = Path(app.instance_path) / sqlite_path
        sqlite_path.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.session_protection = app.config.get("SESSION_PROTECTION", "strong")
    migrate.init_app(app, db, directory=str(ROOT / "migrations"))

    with app.app_context():
        if db.engine.dialect.name == "sqlite":

            def enable_sqlite_foreign_keys(connection, _record):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

            event.listen(db.engine, "connect", enable_sqlite_foreign_keys)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            identity, separator, version = user_id.partition(":")
            if not separator:
                return None
            user = db.session.get(User, int(identity))
            if not user or not user.active or user.session_version != int(version):
                return None
            if app.config.get("REQUIRE_EMAIL_VERIFICATION") and not user.email_verified_at:
                return None
            return user
        except (TypeError, ValueError):
            return None

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        request_id = getattr(g, "request_id", None) or str(uuid4())
        response.headers["X-Request-ID"] = request_id
        app.logger.info(
            "request completed",
            extra={
                "event": "http.request",
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - getattr(g, "request_started", time.perf_counter())) * 1000, 2),
            },
        )
        return response

    @app.before_request
    def begin_request():
        g.request_id = str(uuid4())
        g.request_started = time.perf_counter()

    @app.context_processor
    def image_helpers():
        def image_url(filename):
            if not filename:
                return ""
            if re.fullmatch(r"[a-f0-9]{32}\.(?:jpg|png|webp)", filename):
                from .content_service import stored_image_url

                return stored_image_url(filename) or url_for("public.uploaded_image_route", filename=filename)
            if Path(filename).name == filename:
                return url_for("static", filename=f"faculty_pp/{filename}")
            return ""

        return {"image_url": image_url}

    @app.errorhandler(HTTPException)
    def http_error(error):
        if app.config["TESTING"]:
            return error
        if error.code == 404:
            return "Page not found", 404
        if error.code == 403:
            return "You are not authorized to access this page", 403
        return "The request could not be completed", error.code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        if isinstance(error, IntegrityError):
            db.session.rollback()
            return "The requested change conflicts with existing data", 409
        if app.config["TESTING"]:
            raise error
        app.logger.error(
            "unhandled application error",
            extra={"event": "application.error", "error_type": type(error).__name__},
        )
        return "An unexpected error occurred", 500

    from . import admin, appointments, auth, calendar, faculty, profile, public

    for module in (public, auth, profile, appointments, calendar, admin, faculty):
        app.register_blueprint(module.bp)

    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    @app.get("/ready")
    def ready():
        try:
            db.session.execute(text("SELECT 1"))
            return {"ready": True}, 200
        except SQLAlchemyError:
            db.session.rollback()
            return {"ready": False}, 503

    @app.cli.command("bootstrap-admin")
    def bootstrap_admin_command():
        from .account_service import bootstrap_admin

        email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        password = os.getenv("ADMIN_PASSWORD", "")
        if not email or len(password) < 12:
            import click

            raise click.ClickException("ADMIN_EMAIL and ADMIN_PASSWORD (12+ characters) are required")
        try:
            db.session.remove()
            with db.session.begin():
                bootstrap_admin(db.session, email, password)
        except IntegrityError:
            db.session.rollback()
            import click

            raise click.ClickException("Admin email is already used by another account")
        import click

        click.echo("Administrator account is ready.")

    @app.cli.command("check-db")
    def check_database_command():
        from flask_migrate import current

        current()

    import click

    @app.cli.command("import-legacy-sqlite")
    @click.argument("source")
    def import_legacy_sqlite_command(source):
        from .legacy_import import import_sqlite

        result = import_sqlite(source, db.session, app.config["UNIVERSITY_TIMEZONE"])
        click.echo(
            f"Imported {result['counts']}; backup: {result['backup']}; report: {result['report']}; issues: {len(result['issues'])}"
        )

    @app.cli.command("seed-demo")
    def seed_demo_command():
        if app.config.get("APP_ENV") == "production":
            raise click.ClickException("Demo data cannot be seeded in production")
        from .demo_seed import seed_demo

        password = app.config.get("DEMO_ACCOUNT_PASSWORD", "")
        try:
            db.session.remove()
            with db.session.begin():
                counts = seed_demo(db.session, password)
        except ValueError as exc:
            db.session.rollback()
            raise click.ClickException(str(exc)) from exc
        except IntegrityError as exc:
            db.session.rollback()
            raise click.ClickException("Demo records conflict with existing data; no changes were saved") from exc
        except Exception:
            db.session.rollback()
            raise
        click.echo(f"Demo data ready: {counts}")

    if app.config.get("APP_ENV") == "production":
        from werkzeug.middleware.proxy_fix import ProxyFix

        counts = app.config["PROXY_FIX_COUNTS"]
        if any(counts.values()):
            app.wsgi_app = ProxyFix(
                app.wsgi_app,
                x_for=counts["x_for"],
                x_proto=counts["x_proto"],
                x_host=counts["x_host"],
                x_port=counts["x_port"],
                x_prefix=counts["x_prefix"],
            )
    return app

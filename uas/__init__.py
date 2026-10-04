import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, url_for
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

from .config import ROOT, configure
from .extensions import csrf, db, limiter, login_manager, migrate
from .models import User


def create_app(test_config=None):
    overrides = test_config or {}
    app = Flask(__name__, static_folder=str(ROOT / "static"), template_folder=str(ROOT / "templates"))
    configure(app, overrides)
    ZoneInfo(app.config["UNIVERSITY_TIMEZONE"])
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["CONTENT_PATH"]).parent.mkdir(parents=True, exist_ok=True)
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
            user = db.session.get(User, int(user_id))
            return user if user and user.active else None
        except (TypeError, ValueError):
            return None

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    @app.context_processor
    def image_helpers():
        def image_url(filename):
            if not filename:
                return ""
            if re.fullmatch(r"[a-f0-9]{32}\.(?:jpg|png|webp)", filename):
                return url_for("public.uploaded_image_route", filename=filename)
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
        app.logger.exception("Unhandled application error")
        return "An unexpected error occurred", 500

    from . import admin, appointments, auth, calendar, faculty, profile, public

    for module in (public, auth, profile, appointments, calendar, admin, faculty):
        app.register_blueprint(module.bp)

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

    return app

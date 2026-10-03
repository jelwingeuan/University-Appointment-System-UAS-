"""WSGI entrypoint. Run with ``gunicorn app:app`` or ``flask --app app``."""

from uas import create_app

app = create_app()

__all__ = ["app", "create_app"]

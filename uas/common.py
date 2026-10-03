from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from flask import abort, current_app, request
from flask_login import current_user, login_required
from sqlalchemy import select
from sqlalchemy.orm import Session

from .extensions import db
from .models import User


def role_required(*roles):
    def decorate(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorate


def require_actor(session, actor_id, role):
    actor = session.get(User, int(actor_id))
    if not actor or not actor.active or actor.role != role:
        raise PermissionError("Not authorized")
    return actor


@contextmanager
def transaction():
    # ponytail: SQLite serializes writers; PostgreSQL uses per-lecturer row locks.
    with Session(db.engine) as session, session.begin():
        if db.engine.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield session


def lock_lecturer(session, lecturer_id):
    session.execute(select(User).where(User.id == lecturer_id).with_for_update()).scalar_one_or_none()


def utc_now():
    return current_app.config.get("CLOCK", lambda: datetime.now(UTC))()


def university_zone():
    return ZoneInfo(current_app.config["UNIVERSITY_TIMEZONE"])


def local_to_utc(value):
    return value.replace(tzinfo=university_zone()).astimezone(UTC)


def aware_datetime(value):
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Time must include a timezone")
    return parsed.astimezone(UTC)


def safe_next_url(target):
    host = urlparse(request.host_url)
    resolved = urlparse(urljoin(request.host_url, target or ""))
    return target if target and (resolved.scheme, resolved.netloc) == (host.scheme, host.netloc) else None


def appointment_view(row):
    start, end = row.starts_at.astimezone(university_zone()), row.ends_at.astimezone(university_zone())
    return {
        "id": row.id,
        "student_id": row.student_id,
        "lecturer_id": row.lecturer_id,
        "student": row.student.username,
        "lecturer": row.lecturer.username,
        "appointment_date": start.strftime("%Y-%m-%d"),
        "appointment_time": f"{start:%H:%M} - {end:%H:%M}",
        "purpose": row.purpose,
        "status": row.status,
        "public_reference": row.public_reference,
    }

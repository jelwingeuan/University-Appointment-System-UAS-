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
from .models import AuditLog, User


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


def record_audit(session, actor_id, action, target_type, target_id, **metadata):
    # Only callers pass allowlisted, non-secret values; this also strips common credential keys.
    forbidden = {"password", "password_hash", "token", "token_hash", "secret", "csrf", "cookie"}
    safe = {key: value for key, value in metadata.items() if key.lower() not in forbidden}
    session.add(
        AuditLog(
            actor_user_id=int(actor_id),
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            metadata_json=safe,
        )
    )


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
    zone = university_zone()
    naive = value.replace(tzinfo=None)
    candidates = [naive.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
    round_trips = [candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) for candidate in candidates]
    if any(result != naive for result in round_trips):
        raise ValueError("Local time does not exist in the configured timezone")
    if candidates[0].utcoffset() != candidates[1].utcoffset():
        raise ValueError("Local time is ambiguous in the configured timezone")
    return candidates[0].astimezone(UTC)


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
        "created_at": row.created_at.astimezone(university_zone()).isoformat() if row.created_at else "",
    }


def page_number(value):
    try:
        page = int(value or 1)
    except (TypeError, ValueError):
        return 1
    return min(max(page, 1), 100000)


def pagination(page, total, per_page=25):
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    return {"page": page, "pages": pages, "total": total, "per_page": per_page}

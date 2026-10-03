"""Read-only SQLite compatibility importer. This is the sole production SQLite importer."""

import calendar
import json
import sqlite3
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from .models import Appointment, Availability, Faculty, User

VALID_ROLES = {"student", "teacher", "admin"}
VALID_STATUSES = {"Pending", "Accepted", "Rejected", "Cancelled"}


def _tables(connection):
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _as_utc(value, zone):
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(UTC)


def _legacy_range(row, zone):
    start = row.get("starts_at")
    end = row.get("ends_at")
    if start and end:
        return _as_utc(start, UTC), _as_utc(end, UTC)
    date = row.get("appointment_date") or row.get("event_date")
    time_range = row.get("appointment_time")
    if time_range and "-" in time_range:
        start_time, end_time = (part.strip() for part in time_range.split("-", 1))
    else:
        start_time, end_time = row.get("start_time"), row.get("end_time")
    if not date or not start_time or not end_time:
        raise ValueError("missing date or time")
    return (_as_utc(f"{date}T{start_time}", zone), _as_utc(f"{date}T{end_time}", zone))


def _legacy_availability_ranges(row, zone):
    repeat = str(row.get("repeat_type") or "").lower()
    if not repeat:
        return [_legacy_range(row, zone)]
    if repeat not in {"weekly", "monthly"}:
        raise ValueError(f"invalid recurrence type: {repeat!r}")
    try:
        start_date = datetime.strptime(row["event_date"], "%Y-%m-%d").date()  # noqa: DTZ007
        end_date = datetime.strptime(row["end_date"], "%Y-%m-%d").date()  # noqa: DTZ007
        start_time = datetime.strptime(row["start_time"], "%H:%M").time()  # noqa: DTZ007
        end_time = datetime.strptime(row["end_time"], "%H:%M").time()  # noqa: DTZ007
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid recurrence dates or times") from exc
    local_start = datetime.combine(start_date, start_time)
    local_end = datetime.combine(start_date, end_time)
    if end_date < start_date or local_end <= local_start:
        raise ValueError("invalid recurrence range")
    duration = local_end - local_start
    result, current, anchor = [], start_date, start_date.day
    while current <= end_date:
        occurrence = datetime.combine(current, start_time)
        result.append((_as_utc(occurrence.isoformat(), zone), _as_utc((occurrence + duration).isoformat(), zone)))
        if len(result) > 370:
            raise ValueError("recurrence creates too many availability windows")
        if repeat == "weekly":
            current += timedelta(weeks=1)
        else:
            month, year = current.month + 1, current.year
            if month == 13:
                month, year = 1, year + 1
            current = current.replace(year=year, month=month, day=min(anchor, calendar.monthrange(year, month)[1]))
    return result


def import_sqlite(source_path, destination_session, timezone_name="Asia/Kuala_Lumpur", backup_dir=None):
    source_path = Path(source_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    zone = ZoneInfo(timezone_name)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = Path(backup_dir or source_path.parent) / f"{source_path.name}.backup-{stamp}"
    report = source_path.with_name(f"{source_path.stem}.import-report-{stamp}.json")
    if backup.exists() or report.exists():
        raise FileExistsError("Timestamped import backup/report already exists")
    destination = destination_session.get_bind().url.database
    if destination and destination_session.get_bind().dialect.name == "sqlite":
        location = destination_session.execute(text("PRAGMA database_list")).first()[2]
        if location and source_path == Path(location).resolve():
            raise ValueError("Source and destination must be different databases")
    inspector = inspect(destination_session.get_bind())
    tables_present = set(inspector.get_table_names())
    required = {"alembic_version", "faculties", "users", "availability", "appointments"}
    if not required.issubset(tables_present) or tables_present - required:
        raise ValueError("Destination must be upgraded to Alembic head before import")
    version = destination_session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if version != "0001_orm_schema":
        raise ValueError("Destination must be upgraded to Alembic head before import")
    if any(
        table in tables_present and destination_session.execute(text(f"SELECT 1 FROM {table} LIMIT 1")).first()
        for table in ("users", "faculties", "availability", "appointments")
    ):
        raise ValueError("Destination must be empty before import")
    # End inspection reads, then force a real outer SQLite transaction before nested row savepoints.
    destination_session.commit()
    if destination_session.get_bind().dialect.name == "sqlite":
        destination_session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    else:
        destination_session.connection()
    with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as reader:
        with sqlite3.connect(backup) as writer:
            reader.backup(writer)
        reader.row_factory = sqlite3.Row
        tables = _tables(reader)
        if "users" not in tables:
            raise ValueError("Source has no users table")
        report_data = {"source": str(source_path), "backup": str(backup), "counts": {}, "issues": []}
        imported_users, user_by_name = {}, {}
        try:
            rows = [dict(row) for row in reader.execute("SELECT * FROM users ORDER BY id")]
            username_counts = Counter(str(row.get("username") or "").strip() for row in rows)
            faculties = {}
            if "facultyhub" in tables:
                for row in reader.execute("SELECT * FROM facultyhub ORDER BY id"):
                    faculty_row = dict(row)
                    name = faculty_row["faculty_name"]
                    faculties.setdefault(name, faculty_row.get("faculty_image"))
            elif "faculties" in tables:
                for faculty_row in reader.execute("SELECT * FROM faculties ORDER BY id"):
                    name = faculty_row["faculty_name"]
                    faculties.setdefault(name, faculty_row["faculty_image"])
            for row in rows:
                if "faculty" in row:
                    faculty_name = row.get("faculty") or ("Administration" if row.get("role") == "admin" else "")
                elif "faculty_id" in row and "faculties" in tables:
                    faculty_row = reader.execute(
                        "SELECT faculty_name FROM faculties WHERE id=?", (row["faculty_id"],)
                    ).fetchone()
                    faculty_name = faculty_row[0] if faculty_row else ""
                else:
                    faculty_name = "Administration" if row.get("role") == "admin" else ""
                role = row.get("role")
                if role not in VALID_ROLES:
                    report_data["issues"].append(
                        {"table": "users", "legacy_id": row.get("id"), "reason": f"invalid role: {role!r}"}
                    )
                    continue
                if not faculty_name:
                    report_data["issues"].append(
                        {"table": "users", "legacy_id": row.get("id"), "reason": "missing faculty"}
                    )
                    continue
                faculties.setdefault(faculty_name, None)
                phone = row.get("phone_number") or ""
                normalized = {
                    "id": int(row["id"]),
                    "role": role,
                    "username": str(row.get("username") or "").strip(),
                    "email": str(row.get("email") or "").strip().lower(),
                    "phone_number": str(phone),
                    "password": row.get("password") or "",
                    "active": bool(row.get("active", 1)),
                    "faculty": faculty_name,
                }
                if not all((normalized["username"], normalized["email"], normalized["password"])):
                    report_data["issues"].append(
                        {"table": "users", "legacy_id": row.get("id"), "reason": "missing required user field"}
                    )
                    continue
                try:
                    with destination_session.begin_nested():
                        faculty = destination_session.scalar(
                            select(Faculty).where(Faculty.faculty_name == faculty_name)
                        )
                        if not faculty:
                            faculty = Faculty(faculty_name=faculty_name, faculty_image=faculties[faculty_name])
                            destination_session.add(faculty)
                            destination_session.flush()
                        user = User(
                            id=normalized["id"],
                            role=role,
                            faculty_id=faculty.id,
                            username=normalized["username"],
                            email=normalized["email"],
                            phone_number=normalized["phone_number"],
                            password=normalized["password"],
                            active=normalized["active"],
                        )
                        destination_session.add(user)
                        destination_session.flush()
                    imported_users[user.id] = user
                    if username_counts[user.username] == 1:
                        user_by_name[user.username] = user
                except (SQLAlchemyError, ValueError, TypeError, KeyError, OverflowError) as exc:
                    report_data["issues"].append(
                        {
                            "table": "users",
                            "legacy_id": row.get("id"),
                            "reason": f"duplicate or invalid user: {type(exc).__name__}",
                        }
                    )
            report_data["counts"]["users"] = {"source": len(rows), "imported": len(imported_users)}

            windows_by_id = {}
            if "availability" in tables:
                avail_rows = [dict(row) for row in reader.execute("SELECT * FROM availability ORDER BY id")]
            elif "calendar" in tables:
                calendar_rows = [dict(value) for value in reader.execute("SELECT * FROM calendar ORDER BY id")]
                avail_rows = []
                for row in calendar_rows:
                    if str(row.get("event_type", "")).lower() == "appointment":
                        report_data["issues"].append(
                            {
                                "table": "availability",
                                "legacy_id": row.get("id"),
                                "reason": "calendar appointment marker is not an availability window",
                            }
                        )
                    else:
                        avail_rows.append(row)
            else:
                avail_rows = []
            legacy_ids = []
            for row in avail_rows:
                try:
                    candidate_id = int(row["id"])
                    if candidate_id > 0:
                        legacy_ids.append(candidate_id)
                except (KeyError, TypeError, ValueError):
                    pass
            max_legacy_id = max(legacy_ids, default=0)
            next_window_id = max_legacy_id + 1
            imported_availability_rows, imported_windows = 0, 0
            for row in avail_rows:
                legacy_id = row.get("id")
                lecturer = imported_users.get(row.get("lecturer_id")) or user_by_name.get(row.get("lecturer"))
                try:
                    if not lecturer or lecturer.role != "teacher":
                        raise ValueError("lecturer is missing or not a teacher")
                    slot = int(row.get("slot_minutes") or row.get("slot_size") or 0)
                    ranges = _legacy_availability_ranges(row, zone)
                    if slot <= 0 or any(end <= start for start, end in ranges):
                        raise ValueError("invalid time range or slot duration")
                    if legacy_id is not None and int(legacy_id) <= 0:
                        raise ValueError("invalid availability ID")
                    windows = []
                    with destination_session.begin_nested():
                        for index, (start, end) in enumerate(ranges):
                            if index == 0 and legacy_id is not None:
                                window_id = int(legacy_id)
                            else:
                                window_id = next_window_id
                                next_window_id += 1
                            window = Availability(
                                id=window_id, lecturer_id=lecturer.id, starts_at=start, ends_at=end, slot_minutes=slot
                            )
                            destination_session.add(window)
                            windows.append(window)
                        destination_session.flush()
                    if legacy_id is not None:
                        windows_by_id[legacy_id] = windows[0]
                    for window in windows:
                        windows_by_id[window.id] = window
                    imported_availability_rows += 1
                    imported_windows += len(windows)
                except (SQLAlchemyError, ValueError, TypeError, KeyError, OverflowError) as exc:
                    report_data["issues"].append({"table": "availability", "legacy_id": legacy_id, "reason": str(exc)})
            report_data["counts"]["availability"] = {
                "source": len(avail_rows)
                + sum(
                    issue["table"] == "availability"
                    and issue["reason"] == "calendar appointment marker is not an availability window"
                    for issue in report_data["issues"]
                ),
                "imported": imported_availability_rows,
                "windows_created": imported_windows,
            }

            appointment_rows = (
                [dict(row) for row in reader.execute("SELECT * FROM appointments ORDER BY id")]
                if "appointments" in tables
                else []
            )
            imported_appointments = 0
            for row in appointment_rows:
                legacy_id = row.get("id")
                try:
                    student = imported_users.get(row.get("student_id")) or user_by_name.get(row.get("student"))
                    lecturer = imported_users.get(row.get("lecturer_id")) or user_by_name.get(row.get("lecturer"))
                    if not student or student.role != "student" or not lecturer or lecturer.role != "teacher":
                        raise ValueError("student or lecturer identity is missing/invalid")
                    start, end = _legacy_range(row, zone)
                    if end <= start:
                        raise ValueError("invalid appointment range")
                    matching = [
                        w
                        for w in windows_by_id.values()
                        if w.lecturer_id == lecturer.id
                        and w.starts_at <= start
                        and w.ends_at >= end
                        and (start - w.starts_at).total_seconds() % (w.slot_minutes * 60) == 0
                        and (end - start).total_seconds() == w.slot_minutes * 60
                    ]
                    if row.get("availability_id") in windows_by_id:
                        matching = [w for w in matching if w.id == row["availability_id"]]
                    if len(matching) != 1:
                        raise ValueError("appointment availability mapping is ambiguous or missing")
                    status = row.get("status")
                    status = next((item for item in VALID_STATUSES if item.lower() == str(status).lower()), None)
                    if status is None:
                        raise ValueError(f"invalid status: {row.get('status')!r}")
                    if status in {"Pending", "Accepted"} and destination_session.scalar(
                        select(Appointment.id)
                        .where(
                            Appointment.lecturer_id == lecturer.id,
                            Appointment.status.in_(("Pending", "Accepted")),
                            Appointment.starts_at < end,
                            Appointment.ends_at > start,
                        )
                        .limit(1)
                    ):
                        raise ValueError("conflicting pending/accepted appointment")
                    purpose = str(row.get("purpose") or "").strip()
                    if not purpose or len(purpose) > 500:
                        raise ValueError("invalid purpose")
                    ref = row.get("public_reference")
                    if ref is not None:
                        if not str(ref).strip():
                            raise ValueError("invalid public reference")
                        try:
                            ref = str(uuid.UUID(str(ref)))
                        except ValueError as exc:
                            raise ValueError("invalid public reference") from exc
                    else:
                        ref = str(uuid.uuid4())
                    with destination_session.begin_nested():
                        destination_session.add(
                            Appointment(
                                id=int(legacy_id) if legacy_id is not None else None,
                                public_reference=ref,
                                student_id=student.id,
                                lecturer_id=lecturer.id,
                                availability_id=matching[0].id,
                                starts_at=start,
                                ends_at=end,
                                purpose=purpose,
                                status=status,
                            )
                        )
                        destination_session.flush()
                    imported_appointments += 1
                except (SQLAlchemyError, ValueError, TypeError, KeyError, OverflowError) as exc:
                    report_data["issues"].append({"table": "appointments", "legacy_id": legacy_id, "reason": str(exc)})
            report_data["counts"]["appointments"] = {"source": len(appointment_rows), "imported": imported_appointments}
            destination_session.flush()
            for table in ("users", "availability", "appointments"):
                accounted = report_data["counts"][table]["imported"] + sum(
                    issue["table"] == table for issue in report_data["issues"]
                )
                if accounted != report_data["counts"][table]["source"]:
                    raise RuntimeError(f"Import row accounting failed for {table}")
            if destination_session.get_bind().dialect.name == "sqlite":
                violations = destination_session.execute(text("PRAGMA foreign_key_check")).all()
                if violations:
                    raise RuntimeError(f"Foreign key validation failed: {len(violations)} violation(s)")
            if destination_session.get_bind().dialect.name == "postgresql":
                for table in ("users", "faculties", "availability", "appointments"):
                    destination_session.execute(
                        text(
                            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1), true)"
                        )
                    )
            destination_session.commit()
        except Exception:
            destination_session.rollback()
            raise
    report.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    report_data["backup"] = str(backup)
    report_data["report"] = str(report)
    return report_data

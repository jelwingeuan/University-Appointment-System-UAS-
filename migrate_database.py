import argparse
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from database import connect_database, init_schema


STATUS_MAP = {
    "pending": "Pending",
    "accepted": "Accepted",
    "rejected": "Rejected",
    "cancelled": "Cancelled",
    "canceled": "Cancelled",
}


def _legacy_tables(connection):
    return {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }


def _to_utc(zone, date_value, time_value):
    local = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M").replace(tzinfo=zone)
    return local.astimezone(timezone.utc)


def migrate_database(database_path, timezone_name="Asia/Kuala_Lumpur"):
    source_path = Path(database_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    zone = ZoneInfo(timezone_name)
    with sqlite3.connect(source_path) as probe:
        if "availability" in _legacy_tables(probe):
            return {"already_current": True, "backup": None, "issues": []}

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = source_path.with_name(f"{source_path.name}.bak-{timestamp}")
    temp_path = source_path.with_name(f".{source_path.name}.migrating")
    report_path = source_path.with_name(f"{source_path.stem}.migration-issues.json")
    shutil.copy2(source_path, backup_path)
    if temp_path.exists():
        temp_path.unlink()

    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    target = connect_database(temp_path)
    issues = []
    try:
        init_schema(target)
        tables = _legacy_tables(source)
        target.execute("BEGIN IMMEDIATE")
        for row in source.execute("SELECT * FROM users ORDER BY id"):
            role = row["role"] if row["role"] in {"student", "teacher", "admin"} else "student"
            target.execute(
                """
                INSERT INTO users (id, role, faculty, username, email, phone_number, password)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (row["id"], role, row["faculty"], row["username"], row["email"], row["phone_number"], row["password"]),
            )
        if "facultyhub" in tables:
            for row in source.execute("SELECT * FROM facultyhub ORDER BY id"):
                target.execute(
                    "INSERT OR IGNORE INTO facultyhub (id, faculty_name, faculty_image) VALUES (?, ?, ?)",
                    (row["id"], row["faculty_name"], row["faculty_image"]),
                )

        if "calendar" in tables:
            for row in source.execute("SELECT * FROM calendar ORDER BY id"):
                if str(row["event_type"] or "").lower() == "appointment":
                    continue
                lecturer = target.execute(
                    "SELECT id FROM users WHERE username = ? AND role = 'teacher'", (row["lecturer"],)
                ).fetchone()
                try:
                    starts_at = _to_utc(zone, row["event_date"], row["start_time"])
                    ends_at = _to_utc(zone, row["event_date"], row["end_time"])
                    slot_minutes = int(row["slot_size"])
                    if not lecturer or ends_at <= starts_at or slot_minutes <= 0:
                        raise ValueError
                    target.execute(
                        """
                        INSERT OR IGNORE INTO availability
                            (lecturer_id, starts_at, ends_at, slot_minutes)
                        VALUES (?, ?, ?, ?)
                        """,
                        (lecturer["id"], starts_at.isoformat(), ends_at.isoformat(), slot_minutes),
                    )
                except (TypeError, ValueError):
                    issues.append({"table": "calendar", "legacy_id": row["id"], "reason": "invalid availability"})

        if "appointments" in tables:
            for row in source.execute("SELECT * FROM appointments ORDER BY id"):
                try:
                    student = target.execute("SELECT id FROM users WHERE username = ?", (row["student"],)).fetchone()
                    lecturer = target.execute("SELECT id FROM users WHERE username = ?", (row["lecturer"],)).fetchone()
                    start_text, end_text = [value.strip() for value in row["appointment_time"].split("-", 1)]
                    starts_at = _to_utc(zone, row["appointment_date"], start_text)
                    ends_at = _to_utc(zone, row["appointment_date"], end_text)
                    if not student or not lecturer or ends_at <= starts_at:
                        raise ValueError
                    availability = target.execute(
                        """
                        SELECT id FROM availability
                        WHERE lecturer_id = ? AND starts_at <= ? AND ends_at >= ?
                        ORDER BY starts_at LIMIT 1
                        """,
                        (lecturer["id"], starts_at.isoformat(), ends_at.isoformat()),
                    ).fetchone()
                    if not availability:
                        raise LookupError
                    target.execute(
                        """
                        INSERT INTO appointments
                            (public_reference, student_id, lecturer_id, availability_id,
                             starts_at, ends_at, purpose, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()), student["id"], lecturer["id"], availability["id"],
                            starts_at.isoformat(), ends_at.isoformat(), row["purpose"],
                            STATUS_MAP.get(str(row["status"]).lower(), "Pending"),
                        ),
                    )
                except LookupError:
                    issues.append({"table": "appointments", "legacy_id": row["id"], "reason": "no matching availability"})
                except (AttributeError, TypeError, ValueError, sqlite3.IntegrityError):
                    issues.append({"table": "appointments", "legacy_id": row["id"], "reason": "invalid appointment"})
        target.commit()
    except Exception:
        target.rollback()
        target.close()
        source.close()
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        if source:
            source.close()
        if target:
            target.close()

    os.replace(temp_path, source_path)
    report_path.write_text(json.dumps({"issues": issues}, indent=2), encoding="utf-8")
    return {"already_current": False, "backup": str(backup_path), "report": str(report_path), "issues": issues}


def main():
    parser = argparse.ArgumentParser(description="Migrate a legacy UAS SQLite database safely")
    parser.add_argument("database", help="Path to the legacy SQLite database")
    parser.add_argument("--timezone", default="Asia/Kuala_Lumpur")
    args = parser.parse_args()
    result = migrate_database(args.database, args.timezone)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

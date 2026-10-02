import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL CHECK (role IN ('student', 'teacher', 'admin')),
    faculty TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phone_number TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facultyhub (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    faculty_name TEXT NOT NULL UNIQUE,
    faculty_image TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lecturer_id INTEGER NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    slot_minutes INTEGER NOT NULL CHECK (slot_minutes > 0),
    CHECK (ends_at > starts_at),
    UNIQUE (lecturer_id, starts_at, ends_at),
    FOREIGN KEY (lecturer_id) REFERENCES users(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_reference TEXT NOT NULL UNIQUE,
    student_id INTEGER NOT NULL,
    lecturer_id INTEGER NOT NULL,
    availability_id INTEGER NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (length(trim(purpose)) BETWEEN 1 AND 500),
    status TEXT NOT NULL DEFAULT 'Pending'
        CHECK (status IN ('Pending', 'Accepted', 'Rejected', 'Cancelled')),
    CHECK (ends_at > starts_at),
    FOREIGN KEY (student_id) REFERENCES users(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (lecturer_id) REFERENCES users(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (availability_id) REFERENCES availability(id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_appointments_lecturer_start
    ON appointments (lecturer_id, starts_at);
CREATE INDEX IF NOT EXISTS idx_appointments_student_start
    ON appointments (student_id, starts_at);
CREATE INDEX IF NOT EXISTS idx_appointments_status
    ON appointments (status);
CREATE INDEX IF NOT EXISTS idx_availability_lecturer_start
    ON availability (lecturer_id, starts_at);
"""


def connect_database(path):
    connection = sqlite3.connect(Path(path), timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def init_schema(connection):
    connection.executescript(SCHEMA)

University Appointment System (UAS)

The University Appointment System (UAS) is a web application built with Flask, designed to manage appointments within a university setting. It allows students, faculty, and staff to schedule and manage appointments efficiently.

## Features

- **User Authentication**: Users can sign up for accounts and log in securely using bcrypt for password hashing.
- **Appointment Booking**: Students can book appointments with faculty or staff members for various purposes such as academic advising, office hours, or consultations.
- **Faculty Hub Creation**: Faculty members can create hubs for managing their appointments, specifying their availability and location.
- **Admin Panel**: Administrators have access to an admin panel where they can manage user accounts, faculty hubs, and other system settings.
- **Database Integration**: UAS integrates with SQLite for data storage, ensuring reliable and efficient data management.

https://university-appointment-system-47589565d85d.herokuapp.com (under maintainance)

## Secure local setup

1. Create a virtual environment and install `requirements.txt`.
2. Copy `.env.example` to `.env` and set new, private values. Never reuse the credentials that were previously committed.
3. For a new database, run `flask --app app init-db`.
4. Set `ADMIN_EMAIL` and a 12+ character `ADMIN_PASSWORD`, then run `flask --app app bootstrap-admin` once. Remove `ADMIN_PASSWORD` from the runtime environment afterward.
5. Start development with `APP_ENV=development flask --app app run`. Production must use HTTPS, `APP_ENV=production`, and a strong `FLASK_SECRET_KEY`.

Required runtime values:

- `FLASK_SECRET_KEY`: a long random value used to sign sessions and CSRF tokens.
- `DATABASE_PATH`: SQLite database path, normally `database.db`.
- `LECTURER_REGISTRATION_SECRET`: a rotated secret issued privately to lecturers.
- `UNIVERSITY_TIMEZONE`: defaults to `Asia/Kuala_Lumpur`; canonical database timestamps are stored in UTC.
- `SESSION_COOKIE_SECURE`: use `1` behind HTTPS and `0` only for local HTTP development. It defaults to secure in production.
- `FLASK_DEBUG`: honored only when `APP_ENV` is not `production`; production debug mode is always disabled.

`ADMIN_EMAIL` and `ADMIN_PASSWORD` are needed only while running the administrator bootstrap command.

## Migrating the legacy database

Run the migration before starting the updated application:

```sh
python migrate_database.py database.db
```

The migration creates a timestamped `database.db.bak-*` backup before replacing the schema. It preserves users, faculties, valid availability windows, and appointments that can be linked safely. Rows that cannot be converted are listed by legacy ID and reason in `database.migration-issues.json`; the original values remain available in the backup. Database files, backups, migration reports, and environment files are intentionally ignored by Git.

## Tests

```sh
pytest -q --cov=app --cov=booking_service --cov=database --cov=migrate_database --cov-fail-under=80
```

# University Appointment System

The University Appointment System is a Flask/Jinja application for student and lecturer appointments, availability calendars, and administrative account/faculty management. The existing interface and routes are retained; appointment storage is now relational and SQLAlchemy-backed.

## Local setup

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Set `FLASK_SECRET_KEY` to a random value of at least 32 characters and rotate `LECTURER_REGISTRATION_SECRET` before sharing lecturer registration access. `.env` is loaded by the application factory. `DATABASE_URL` defaults to local SQLite; PostgreSQL URLs such as `postgresql+psycopg://user:password@host/database` are also supported. The default display timezone is `Asia/Kuala_Lumpur`; timestamps are stored in UTC.

Initialize a new database through Alembic (the app never creates production tables on startup):

```sh
flask --app app db upgrade
```

Bootstrap the first administrator once, then remove the password from the process environment:

```sh
export ADMIN_EMAIL=admin@example.edu
export ADMIN_PASSWORD='a-long-unique-password'
flask --app app bootstrap-admin
unset ADMIN_PASSWORD
```

Start the development server with `flask --app app run`. For production set `APP_ENV=production`, configure HTTPS and a production database, and run `gunicorn app:app`. Production always uses secure session cookies and disables debug mode, regardless of local flags.

## Importing a legacy SQLite database

The importer supports both the original username-linked schema and the intermediate normalized SQLite schema. It does not rewrite the source. First configure `DATABASE_URL` to point at a **separate, empty destination**; migrate that destination to Alembic head, then import:

```sh
flask --app app db upgrade
flask --app app import-legacy-sqlite /path/to/legacy-database.db
```

The importer uses SQLite's online backup API and writes a timestamped `.backup-*` beside the source, plus a `.import-report-*` JSON file with counts and every invalid, duplicate, or ambiguous row. It preserves usable IDs/references and does not silently substitute invalid roles/statuses. Check the report before switching the application to the imported destination. Keep the source and backup until the imported records have been reviewed.

For rollback, stop the app, restore the previous `DATABASE_URL` (or point it to the preserved backup copy), and restart. The importer never replaces or deletes the original source database.

## Tests and lint

```sh
pytest --cov=uas --cov-fail-under=80
ruff check .
```

Tests use disposable SQLite databases. CI runs the suite on SQLite and PostgreSQL; PostgreSQL connection failures are test failures, not skips.

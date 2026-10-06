# University Appointment System

Flask/Jinja application for student and lecturer appointments, availability calendars, and university administration. The existing routes and interface remain in place; persistence uses SQLAlchemy and Alembic.

## Local development

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Development uses SQLite, local image files, memory-backed rate limits, and the configured `Asia/Kuala_Lumpur` display timezone. Set `FLASK_SECRET_KEY` to at least 32 random characters. Apply schema changes before running the server:

```sh
flask --app app db upgrade
flask --app app run
```

Bootstrap the first administrator once, then clear the password from the shell environment:

```sh
export ADMIN_EMAIL=admin@example.edu
export ADMIN_PASSWORD='a-long-unique-passphrase'
flask --app app bootstrap-admin
unset ADMIN_PASSWORD
```

Passwords require at least 12 characters and must fit bcrypt's 72-byte limit. The CLI hashes the password; the application never stores or displays it in plaintext.

Lecturer registration in development can still use `LECTURER_REGISTRATION_SECRET`. In production, lecturers register with a single-use invitation: an administrator creates one under User Control, copies the token from its one-time response, and sends it to the lecturer. Invitations expire after seven days, can be tied to an institutional email, and store only a token hash.

### Synthetic demo data

For local UI work, set a local-only `DEMO_ACCOUNT_PASSWORD` (at least 12 characters) and run:

```sh
export DEMO_ACCOUNT_PASSWORD='a-local-only-demo-password'
flask --app app seed-demo
unset DEMO_ACCOUNT_PASSWORD
```

The command refuses `APP_ENV=production`, creates synthetic users that share this password, and is safe to repeat. It does not reset or overwrite unrelated records and never runs during application startup. Do not reuse an institutional or production password. The [UI contract](docs/ui-contract.md) documents the behaviors the redesigned UI should rely on.

## Production configuration

Install the production Redis client extra as well as the core application:

```sh
pip install -r requirements.txt -r requirements-production.txt
```

Set `APP_ENV=production`, a strong `FLASK_SECRET_KEY`, and an explicit PostgreSQL `DATABASE_URL` such as `postgresql+psycopg://...`. Production startup fails if the database is missing or is not PostgreSQL. `ALLOW_PRODUCTION_SQLITE=1` is an explicit exception for an intentional single-instance deployment, not a fallback. Production also requires a shared Redis-compatible `RATELIMIT_STORAGE_URI` (`redis://`, `rediss://`, or `redis+unix://`) and an `IMAGE_STORAGE_FACTORY` implementation. Debug is disabled, secure/HttpOnly/SameSite=Lax cookies are enforced, CSRF and rate limiting cannot be disabled by local overrides, and Flask-Login sessions expire after eight hours.

### Image storage adapter

Images are decoded, pixel-limited, re-encoded as JPEG/PNG/WebP, stripped of metadata, named randomly by the server, and limited by the 5 MB request cap. Development stores them under `instance/uploads`. Production provides a Python factory using `IMAGE_STORAGE_FACTORY=package.module:factory`; the factory receives the Flask app and returns an object implementing:

- `save(key, content_bytes, content_type)`
- `delete(key)`
- `open(key)` returning a path or binary file, or `None`
- `url(key)` returning a trusted public/signed URL or `None`

This interface is provider-neutral. Configure any S3-compatible/object-storage provider in the deployment rather than coupling application code to a vendor. Existing image files are not copied or removed automatically: transfer them to the selected storage with their current filenames before cutover so existing image references continue to resolve. The repository includes the interface and local implementation; no cloud object store has been configured or tested here.

### Email delivery adapter

Email ownership verification can be enabled with `REQUIRE_EMAIL_VERIFICATION=1`; production then also requires `MAIL_DELIVERY_FACTORY=package.module:factory`. The factory receives the Flask app and returns a callable `(email, purpose, token)`. It must deliver the token without logging it. Build links using the configured public origin and put the token in a URL fragment, for example `/password-reset/complete#token=...` or `/email-verification/complete#token=...`; the page submits it in a CSRF-protected POST body so it is not sent in request URLs or referrers.

Password reset requests always return the same public response regardless of whether the account exists. Reset and verification tokens are cryptographically random, stored as hashes, expire, and can be used once. Password reset increments the account session version so existing sessions stop working. No email provider is bundled or configured; password reset and required verification delivery need an operator-supplied adapter.

### Reverse proxy and probes

`TRUSTED_HOSTS` is an optional comma-separated list of deployment hostnames. Forwarded headers are ignored unless a `PROXY_FIX_X_FOR`, `PROXY_FIX_X_PROTO`, `PROXY_FIX_X_HOST`, `PROXY_FIX_X_PORT`, or `PROXY_FIX_X_PREFIX` hop count is explicitly set. Configure each count to the number of trusted proxies that actually set that header; do not trust client-controlled forwarding headers. `/health` reports process liveness. `/ready` returns only whether a database query succeeded.

Example production environment keys are commented in `.env.example`. Do not commit production credentials or put them in source control. Start production with `gunicorn app:app` after applying migrations.

## Database and rollback

Schema is created only by Alembic, never by application startup. Before upgrading an existing database, take a restorable database backup. For PostgreSQL, for example:

```sh
pg_dump --format=custom --file=uas-before-upgrade.dump --dbname="service=uas-production"
flask --app app db upgrade
```

The `uas-production` service should be defined in a protected libpq service file and use a separate restricted password file or managed identity; do not put credentials in the command or source tree. The application emits request logs to stderr using route templates rather than raw URLs. Configure proxy or Gunicorn access logs to omit query strings, headers, and request bodies.

See the [PostgreSQL backup and recovery runbook](docs/backup-recovery.md) for scheduled backup, encryption, retention, isolated restore, and restore-drill guidance.

Migration `0002_production_foundation` preserves user IDs, renames `password` to `password_hash`, adds account and lifecycle timestamps, adds settings/tokens/history/audit tables, and expands appointment statuses. It seeds the single `site_settings` row from tracked `content.json` at migration time. Normal production reads and edits use the database; the JSON file remains a read-only local fallback/bootstrap source. To roll back after a failed upgrade, restore the pre-upgrade database backup. Do not downgrade after `Completed` or `No Show` appointments exist; the migration refuses that downgrade. A downgrade also removes settings, tokens, audit entries, and status history, so backup restore is the supported rollback.

Deactivate accounts instead of deleting them. Historical appointments remain intact. Deactivating a lecturer disables all their availability windows; reactivation does not reopen those windows automatically.

Appointment transitions are recorded with the appointment update in one transaction: lecturer `Pending -> Accepted|Rejected`, student `Pending|Accepted -> Cancelled`, and lecturer/admin `Accepted -> Completed|No Show`. Status history uses restrictive foreign keys to preserve the record trail.

Availability windows for one lecturer may not overlap. The service locks that lecturer while validating and inserting all recurrence occurrences; recurring creation is all-or-nothing. PostgreSQL booking transactions lock only the relevant lecturer row. SQLite uses `BEGIN IMMEDIATE`, which serializes SQLite writers globally.

### Legacy SQLite import

The importer supports the original username-linked schema and the prior normalized schema, including `password_hash`. It leaves the source untouched and creates an SQLite backup beside it. Configure `DATABASE_URL` to a separate empty destination, upgrade it first, then import:

```sh
flask --app app db upgrade
flask --app app import-legacy-sqlite /path/to/legacy-database.db
```

Review the generated `.import-report-*.json` for invalid or ambiguous rows before switching over. Keep the original file and backup until that review is complete. The importer preserves supported IDs, account activity, UUID references and usable records; it does not import transient reset/invitation tokens or prior audit records. Recreate pending invitations after import. For rollback, point `DATABASE_URL` back to the unchanged source or restore the destination backup.

## Tests and checks

```sh
pytest --cov=uas --cov-fail-under=80
ruff check .
pip-audit -r requirements.txt -r requirements-production.txt -r requirements-dev.txt
```

Tests use isolated databases and files. CI runs the suite on SQLite and PostgreSQL and includes Ruff and dependency auditing. PostgreSQL-only concurrency tests are skipped locally on SQLite and run in the PostgreSQL job.

# Notifications and appointment reminders

## In-app behavior

Students and lecturers receive private, in-app notifications for appointment requests and the Accepted, Rejected, and Cancelled transitions. A new request goes to its lecturer; an acceptance/rejection goes to the student; a student cancellation goes to the lecturer. The acting user and administrators are not recipients. Completed and No Show transitions do not create notifications. Messages include the appointment date and time, but never its purpose.

Notifications are stored with the booking or status change in the same database transaction. A failed appointment transaction therefore cannot leave a notification behind. A database uniqueness key prevents duplicate event notifications and reminder notifications. A notification references its appointment when available; if old appointment data is later removed, the inbox still keeps its message and shows no appointment action.

Only a signed-in student or lecturer can use `/notifications`. All list, unread count, preview, mark-read, mark-all-read, and open queries are scoped to the current user. The open action marks the notification read and derives its destination from the current role and appointment ownership. No URL is saved in, or accepted from, notification data. The shell loads five recent notifications and a separate unread count; it does not poll. The bell is omitted until at least one notification exists.

## Preferences

In-app appointment notifications are always enabled. `notification_preferences` stores `email_updates`, `reminder_24h`, and `reminder_1h`; all default to enabled, including rows backfilled during migration. Students and lecturers can change them under Profile. `email_updates` controls appointment event email; the two reminder preferences independently control the corresponding reminder email and reminder notification. Password-reset and email-verification messages use the existing security-mail adapter and are not controlled by these preferences.

If appointment email is not configured, the profile explains that in-app notifications remain available. Preference choices are still saved, so they can be applied if the adapter is enabled later.

## Email outbox and workers

Email delivery is optional. When an appointment email adapter is configured, eligible notification creation also writes a `notification_deliveries` outbox row in the same transaction. Queueing happens after commit and is best-effort. The scheduled `process-reminders` command also re-dispatches pending rows, so a temporary Redis outage does not discard delivery intent. A 24-hour reminder is not emitted once the appointment is within its 1-hour reminder window, avoiding a stale “tomorrow” message alongside the imminent reminder.

Production uses the deployment's existing Redis service. Install `requirements-production.txt` and configure `APPOINTMENT_MAIL_DELIVERY_FACTORY`, `PUBLIC_APP_ORIGIN`, and `NOTIFICATION_QUEUE_REDIS_URL`. The queue URL defaults to `RATELIMIT_STORAGE_URI` if no separate URL is set. `PUBLIC_APP_ORIGIN` must be the exact HTTPS origin (scheme and host only). When the appointment-email adapter is unset, in-app notifications continue to work and worker/queue configuration is not required.

The factory is `package.module:factory`; it receives the Flask app and returns a callable that accepts one `AppointmentEmail` value with `to_address`, generic `subject`, `text_body`, `html_body`, and a stable `idempotency_key`. Use that key with the provider's idempotency feature when available. Rendered emails contain only the short notification text and a role-checked internal appointment link; purpose text is not included. The provider adapter must not log message bodies, addresses, tokens, or credentials.

The web process does not run a scheduler thread. Run the worker process from the Procfile and schedule this command periodically (every five minutes is a reasonable starting point):

```sh
flask --app app process-reminders
```

The command creates due reminders only for Accepted appointments and dispatches eligible outbox rows. Before each delivery the worker rechecks appointment status, recipient activity and (when email verification is required) verification, as well as email/reminder preferences. A worker claims each row under a short database lease before calling the provider outside the transaction. Expired claims are recovered by the next dispatcher run. Failures retry at most five times with bounded delays (1, 5, 30, and 120 minutes); permanent provider rejections and exhausted attempts become `Failed`. Logs contain delivery IDs, safe error codes, and exception type only.

The outbox and database claim prevent concurrent duplicate sends inside UAS. If an external provider cannot honor the idempotency key, an ambiguous provider timeout can still result in an at-least-once email; it cannot be guaranteed exactly once across the database/provider boundary.

### Local mailbox

For development only, the included sink writes appointment-email previews to `instance/dev-mailbox.jsonl` with restrictive local file permissions. Do not enable it in production. To exercise the worker locally, install production requirements, run Redis, set the three local settings shown in `.env.example`, then run `flask --app app notification-worker` in one terminal and `flask --app app process-reminders` in another. No messages are sent merely by starting the web app.

## Retention and operations

Notification and delivery records are currently retained; the app does not silently purge them. Adopt a reviewed retention schedule (12 months is a sensible initial target for this service), with notification and delivery rows removed together only after the institution approves the policy and backup/audit requirements. Do not delete delivery rows independently while referenced. Keep database backups and their retention separate from notification retention.

Operational checks should include: confirm the worker is running; confirm the scheduled command completes; inspect counts of Pending/Processing/Failed deliveries and the age of the oldest due row; verify Redis connectivity; and periodically send a test appointment through a non-production provider. Restore drills should include the outbox tables. If Redis is interrupted, run `process-reminders` after recovery to re-enqueue pending rows.

## Data model

- `notification_preferences`: one per user, with in-app availability independent from email preferences.
- `notifications`: recipient, optional appointment, type, short copy, deduplication key, read timestamp, and optional reminder interval.
- `notification_deliveries`: durable email delivery state, retry schedule, attempt count, and expiring claim token.

Alembic revision `0004_notifications` adds these tables, checks, uniqueness constraints, unread-history index, and due-delivery index. Run `flask --app app db upgrade` before starting application/worker processes.

# UAS UI Contract

The server is authoritative for identity, ownership, appointment state, availability, and conflicts. The UI may use availability endpoints to improve feedback, but it must submit the booking and handle the server result as final.

## Roles and ownership

- **Student:** browse active lecturers and their available slots; create and view their own bookings/invoices; cancel their own Pending or Accepted booking.
- **Teacher (lecturer):** create availability and delete their own unbooked windows; view their own calendar and bookings; accept or reject their own Pending bookings; mark their own Accepted bookings Completed or No Show.
- **Admin:** inspect users and appointments; deactivate/reactivate accounts; create faculties and lecturer invitations; edit site settings; delete appointments; mark Accepted appointments Completed or No Show. Admin actions do not grant ownership of student invoices or lecturer calendars.

Student navigation opens `/appointment` for a personal summary, `/appointment2` for booking, `/bookinghistory` for the student's own appointments, `/explore` for read-only faculty/active lecturer discovery, and `/profile` for account settings. Lecturer and administrator workflows remain unchanged.

## Appointment states and transitions

The supported states are `Pending`, `Accepted`, `Rejected`, `Cancelled`, `Completed`, and `No Show`.

| Actor | Allowed transition |
| --- | --- |
| Lecturer who owns the booking | `Pending -> Accepted` or `Pending -> Rejected` |
| Student who owns the booking | `Pending -> Cancelled` or `Accepted -> Cancelled` |
| Lecturer who owns the booking | `Accepted -> Completed` or `Accepted -> No Show` |
| Admin | `Accepted -> Completed` or `Accepted -> No Show` |

Only Pending and Accepted appointments block a slot. Rejected, Cancelled, Completed, and No Show do not. Invalid transitions are rejected. Successful transitions and their actor are stored in appointment status history.

## Booking and calendar

- `GET /get_calendar_details?lecturer=<id>&appointment_date=YYYY-MM-DD` returns slot hints with `availability_id`, ISO `starts_at`, display `label`, and `available`.
- `GET /check_availability?availability_id=<id>&starts_at=<ISO timestamp>` returns `{"available": boolean}` as a UX hint only.
- `POST /create_booking` accepts `availability_id`, `slot_start` (timezone-aware ISO timestamp), and `purpose` (1-500 characters). The server derives the student from the signed-in account, lecturer from the availability record, and end time from that record's slot duration. It rejects invalid, past, misaligned, out-of-window, or conflicting slots. A conflict flashes an error and redirects to `/appointment2`; other invalid input does likewise. Do not trust submitted student, lecturer, status, or end-time fields.
- Conflicts are checked across all availability windows for the lecturer. Adjacent back-to-back slots are allowed. The booking transaction is authoritative even when a prior availability check said the slot was free.
- `POST /calendar_record` accepts `event_date`, `end_date`, `start_time`, `end_time`, `slot_size`, and `repeat_type` (``, `weekly`, or `monthly`). Local times are converted by the server. `GET /events` returns only the signed-in lecturer's active availability and Accepted appointments. `POST /delete_event` accepts `availability_id` and only deletes the owning lecturer's unbooked window.
- Student booking history and invoice lookup are scoped to the signed-in student. Lecturer history is scoped to the signed-in lecturer.
- `/explore` is student-only, read-only, and searches active lecturers by name or faculty. Results are paginated at 12 lecturers per page; booking still uses the normal server-validated `/appointment2` flow.

## Authentication and invitations

- `POST /login` accepts `email` and `password`; failures are generic. A `next` destination is followed only when it is same-origin. `POST /logout` ends the session.
- Password reset begins at `POST /password-reset` with `email`. The response does not reveal whether an account exists. Completion posts `token`, `password`, and `confirm_password` to `/password-reset/complete`; tokens are one-use, stored as hashes, and expire. Email verification is optional by deployment configuration and also uses a one-use token posted to `/email-verification/complete`.
- Lecturer signup is invitation-only in production. An admin-created invitation is single-use, expires after seven days, and may be bound to an email; the raw token is shown once while only its hash is stored. Development may use `LECTURER_REGISTRATION_SECRET` instead.
- Inactive or unverified accounts where verification is required cannot establish a session. Deactivation invalidates existing sessions.

## Administration, audit, and uploads

- Admin user deactivation invalidates sessions and disables a lecturer's availability; reactivation does not re-enable availability. Admins cannot deactivate themselves or the final active administrator. Faculty membership remains linked to stable user/faculty IDs.
- Audit entries cover account profile/password changes, settings edits, faculty creation, user deactivation/reactivation, invitation creation/revocation, and appointment deletion. Appointment state transitions have their own history table. Do not infer that read-only views are audited.
- New images accept JPEG, PNG, or WebP, with a 5 MB request-body cap and a 20-million-pixel decoded-image limit. The server decodes and re-encodes uploads, removes metadata, and assigns a random filename. Existing image references remain displayable.

## Search, pagination, and dates

- Admin user and appointment lists and faculty member lists use 25 records per page. `page` defaults to 1 and is clamped to the available range. Admin list search accepts up to 100 characters; longer input returns HTTP 400. Pagination links preserve the current search.
- The database stores timezone-aware UTC timestamps (SQLite values are normalized through the ORM adapter). Display and local availability forms use `UNIVERSITY_TIMEZONE`, defaulting to `Asia/Kuala_Lumpur`. Nonexistent or ambiguous local times are rejected rather than guessed.

## Security headers

Existing security headers remain in force. A restrictive Content Security Policy is intentionally deferred until the UI redesign establishes its script, style, font, image, and third-party resource requirements.

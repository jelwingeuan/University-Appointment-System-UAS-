# UAS UI Contract

The server is authoritative for identity, ownership, appointment state, availability, and conflicts. The UI may use availability endpoints to improve feedback, but it must submit the booking and handle the server result as final.

## Roles and ownership

- **Student:** browse active lecturers and their available slots; create and view their own bookings/invoices; cancel their own Pending or Accepted booking.
- **Teacher (lecturer):** view a lecturer dashboard and request inbox; view only their own appointment details, calendar, availability, and history; accept or reject their own Pending bookings; mark their own Accepted bookings Completed or No Show.
- **Admin:** inspect users and appointments; deactivate/reactivate accounts; create faculties and lecturer invitations; edit site settings; delete appointments; mark Accepted appointments Completed or No Show. Admin actions do not grant ownership of student invoices or lecturer calendars.

Student navigation opens `/appointment` for a personal summary, `/appointment2` for booking, `/bookinghistory` for the student's own appointments, `/explore` for read-only faculty/active lecturer discovery, and `/profile` for account settings. Lecturer navigation opens `/lecturer` (Home), `/lecturer/requests`, `/calendar`, `/bookinghistory`, and `/profile`. Successful lecturer login continues to redirect to the public home page; the Home link opens the protected lecturer dashboard.

Lecturer page contracts:

- `GET /lecturer` shows bounded, owner-scoped pending requests, today's Accepted appointments, the next Accepted appointment, a short upcoming-week list, and future availability count.
- `GET /lecturer/requests` lists only the signed-in lecturer's Pending appointments, oldest request first, paginated at 25 per page.
- `GET /lecturer/appointments/<public_reference>` displays details only when the signed-in lecturer owns the appointment; missing and non-owned references return 404. The public reference is the visible identifier.
- Lecturer `GET /bookinghistory` accepts optional `q` (up to 100 characters), `status` (one of the six defined states), and `page`. Search matches student name, public reference, or purpose. Results use 25 rows per page; invalid search length or status returns HTTP 400. Pending requests sort oldest first, Accepted upcoming appointments soonest first, and terminal/past rows most recent first.
- Lecturer status forms continue to post the existing appointment ID to the existing CSRF-protected action routes. The transition service remains authoritative; UI visibility does not grant permission.

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
- `POST /calendar_record` accepts `event_date`, `end_date`, `start_time`, `end_time`, `slot_size`, and `repeat_type` (``, `weekly`, or `monthly`). Local times are converted by the server. A recurring form requires `end_date`; one-time availability may omit it. Recurrence remains inclusive and all-or-nothing.
- `GET /events` returns only the signed-in lecturer's active availability and Accepted appointments. Optional `start` and `end` query parameters bound results to the visible calendar range; both must be valid timestamps and the range may not exceed 62 days. Offset-aware values are interpreted as instants; timezone-less calendar range values use `UNIVERSITY_TIMEZONE`. Omitting both retains the existing response behavior. Appointment event IDs use public references. `POST /delete_event` still accepts `availability_id` and only deletes the owning lecturer's window when no appointment references it.
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

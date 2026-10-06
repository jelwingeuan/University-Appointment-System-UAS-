from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select

from .account_service import hash_password
from .common import local_to_utc, university_zone, utc_now
from .models import Appointment, AppointmentStatusHistory, Availability, Faculty, User

FACULTIES = ("UAS Demo: Computing", "UAS Demo: Business", "UAS Demo: Creative Media")
USERS = (
    ("demo.student.empty@student.mmu.edu.my", "Demo Student With No Appointments", "student", FACULTIES[0], "+601111000001"),
    ("demo.student.one@student.mmu.edu.my", "Demo Student Amina Rahman", "student", FACULTIES[0], "+601111000002"),
    ("demo.student.two@student.mmu.edu.my", "Demo Student Hafiz Lim", "student", FACULTIES[1], "+601111000003"),
    ("demo.student.three@student.mmu.edu.my", "Demo Student Mei Tan", "student", FACULTIES[2], "+601111000004"),
    ("demo.lecturer.empty@mmu.edu.my", "Demo Lecturer Without Availability", "teacher", FACULTIES[1], "+601111000005"),
    ("demo.lecturer.busy@mmu.edu.my", "Demo Lecturer: Accessible Computing, Interaction Design, and Student Support", "teacher", FACULTIES[0], "+601111000006"),
    ("demo.lecturer.media@mmu.edu.my", "Demo Lecturer Noor Iskandar", "teacher", FACULTIES[2], "+601111000007"),
)
WINDOWS = (
    ("busy-past", "demo.lecturer.busy@mmu.edu.my", -14, time(9), time(11), 30),
    ("busy-half-hour", "demo.lecturer.busy@mmu.edu.my", 1, time(9), time(13), 30),
    ("busy-hour", "demo.lecturer.busy@mmu.edu.my", 3, time(9), time(13), 60),
    ("media-45-minute", "demo.lecturer.media@mmu.edu.my", 2, time(9), time(12), 45),
)
APPOINTMENTS = (
    ("busy-past", 0, "demo.student.one@student.mmu.edu.my", "Rejected"),
    ("busy-past", 1, "demo.student.two@student.mmu.edu.my", "Cancelled"),
    ("busy-past", 2, "demo.student.one@student.mmu.edu.my", "Completed"),
    ("busy-past", 3, "demo.student.two@student.mmu.edu.my", "No Show"),
    ("busy-half-hour", 0, "demo.student.one@student.mmu.edu.my", "Pending"),
    ("busy-half-hour", 1, "demo.student.two@student.mmu.edu.my", "Accepted"),
    ("busy-half-hour", 2, "demo.student.three@student.mmu.edu.my", "Pending"),
    ("busy-half-hour", 3, "demo.student.one@student.mmu.edu.my", "Accepted"),
    ("busy-half-hour", 4, "demo.student.two@student.mmu.edu.my", "Pending"),
    ("busy-hour", 0, "demo.student.one@student.mmu.edu.my", "Accepted"),
    ("busy-hour", 1, "demo.student.three@student.mmu.edu.my", "Pending"),
    ("busy-hour", 2, "demo.student.two@student.mmu.edu.my", "Accepted"),
    ("media-45-minute", 0, "demo.student.three@student.mmu.edu.my", "Accepted"),
    ("media-45-minute", 1, "demo.student.one@student.mmu.edu.my", "Pending"),
)


def seed_demo(session, password):
    """Insert or reuse reserved synthetic rows without changing unrelated data."""
    password_hash = hash_password(password or "")
    emails = [row[0] for row in USERS]
    existing = {row.email: row for row in session.scalars(select(User).where(User.email.in_(emails)))}
    anchors = [row.created_at for row in existing.values() if row.created_at]
    anchor = min(anchors) if anchors else utc_now()
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    anchor = anchor.astimezone(UTC)

    faculties = {}
    for name in FACULTIES:
        faculty = session.scalar(select(Faculty).where(Faculty.faculty_name == name))
        if faculty is None:
            faculty = Faculty(faculty_name=name)
            session.add(faculty)
            session.flush()
        faculties[name] = faculty

    users = {}
    for email, username, role, faculty_name, phone in USERS:
        user = existing.get(email)
        if user is not None:
            if (user.username, user.role, user.faculty_id, user.phone_number) != (
                username,
                role,
                faculties[faculty_name].id,
                phone,
            ):
                raise ValueError(f"Reserved demo account conflicts with existing data: {email}")
        else:
            user = User(
                username=username,
                email=email,
                role=role,
                faculty_id=faculties[faculty_name].id,
                phone_number=phone,
                password_hash=password_hash,
                active=True,
                email_verified_at=anchor,
                created_at=anchor,
                updated_at=anchor,
            )
            session.add(user)
            session.flush()
        users[email] = user

    base_date = anchor.astimezone(university_zone()).date()
    windows = {}
    for key, lecturer_email, day_offset, start_time, end_time, slot_minutes in WINDOWS:
        local_start = datetime.combine(base_date + timedelta(days=day_offset), start_time)
        local_end = datetime.combine(base_date + timedelta(days=day_offset), end_time)
        starts_at, ends_at = local_to_utc(local_start), local_to_utc(local_end)
        lecturer = users[lecturer_email]
        window = session.scalar(
            select(Availability).where(
                Availability.lecturer_id == lecturer.id,
                Availability.starts_at == starts_at,
                Availability.ends_at == ends_at,
            )
        )
        if window is None:
            window = Availability(
                lecturer_id=lecturer.id,
                starts_at=starts_at,
                ends_at=ends_at,
                slot_minutes=slot_minutes,
            )
            session.add(window)
            session.flush()
        elif window.slot_minutes != slot_minutes:
            raise ValueError(f"Reserved demo availability conflicts with existing data: {key}")
        windows[key] = window

    count = 0
    for key, slot_index, student_email, status in APPOINTMENTS:
        window = windows[key]
        starts_at = window.starts_at + timedelta(minutes=window.slot_minutes * slot_index)
        ends_at = starts_at + timedelta(minutes=window.slot_minutes)
        purpose = f"Demo appointment: {key} slot {slot_index + 1}"
        existing_row = session.scalar(
            select(Appointment).where(
                Appointment.lecturer_id == window.lecturer_id,
                Appointment.starts_at == starts_at,
            )
        )
        student = users[student_email]
        if existing_row is not None:
            if (
                existing_row.student_id,
                existing_row.availability_id,
                existing_row.ends_at,
                existing_row.status,
                existing_row.purpose,
            ) != (student.id, window.id, ends_at, status, purpose):
                raise ValueError(f"Reserved demo appointment conflicts with existing data: {purpose}")
            continue

        is_past = starts_at < anchor
        created_at = starts_at - timedelta(days=3) if is_past else anchor - timedelta(minutes=30)
        accepted_at = (
            starts_at - timedelta(days=2) if is_past else anchor
        ) if status in {"Accepted", "Completed", "No Show"} else None
        rejected_at = starts_at - timedelta(days=1) if status == "Rejected" else None
        cancelled_at = starts_at - timedelta(days=1) if status == "Cancelled" else None
        completed_at = ends_at if status == "Completed" else None
        no_show_at = ends_at if status == "No Show" else None
        updated_at = completed_at or no_show_at or cancelled_at or rejected_at or accepted_at or created_at
        appointment = Appointment(
            student_id=student.id,
            lecturer_id=window.lecturer_id,
            availability_id=window.id,
            starts_at=starts_at,
            ends_at=ends_at,
            purpose=purpose,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            accepted_at=accepted_at,
            cancelled_at=cancelled_at,
            cancelled_by_user_id=student.id if cancelled_at else None,
            cancel_reason="Demo cancellation" if cancelled_at else None,
            completed_at=completed_at,
            no_show_at=no_show_at,
        )
        session.add(appointment)
        session.flush()
        teacher_id = window.lecturer_id
        history = []
        if status in {"Accepted", "Completed", "No Show"}:
            history.append(("Pending", "Accepted", teacher_id, accepted_at))
        if status == "Rejected":
            history.append(("Pending", "Rejected", teacher_id, rejected_at))
        elif status == "Cancelled":
            history.append(("Pending", "Cancelled", student.id, cancelled_at))
        elif status in {"Completed", "No Show"}:
            history.append(("Accepted", status, teacher_id, completed_at or no_show_at))
        session.add_all(
            AppointmentStatusHistory(
                appointment_id=appointment.id,
                from_status=before,
                to_status=after,
                actor_user_id=actor_id,
                created_at=at,
            )
            for before, after, actor_id, at in history
        )
        count += 1

    session.flush()
    return {"faculties": len(faculties), "users": len(users), "availability": len(windows), "appointments_added": count}

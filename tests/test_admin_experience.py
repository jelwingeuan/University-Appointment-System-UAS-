import re
from datetime import timedelta
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import inspect, select

from tests.conftest import FIXED_NOW, login
from uas.extensions import db
from uas.models import (
    Appointment,
    AppointmentStatusHistory,
    AuditLog,
    Faculty,
    LecturerInvitation,
    SiteSettings,
)


def test_admin_navigation_includes_audit_log_and_marks_it_active(client):
    login(client, "admin@mmu.edu.my")

    response = client.get("/admin/audit-log")

    assert response.status_code == 200
    markup = response.get_data(as_text=True)
    assert 'href="/admin/audit-log"' in markup
    assert 'href="/admin/audit-log" aria-current="page"' in markup


@pytest.mark.parametrize("role_email", [None, "student1@student.mmu.edu.my", "lecturer1@mmu.edu.my"])
def test_admin_detail_and_audit_pages_require_admin(client, role_email):
    if role_email:
        login(client, role_email)

    for path in ("/admin/audit-log", "/admin/users/1", "/admin/appointments/missing-reference", "/faculty/1/edit"):
        assert client.get(path).status_code in ({302} if role_email is None else {403})


def test_admin_dashboard_uses_operational_counts_and_recent_activity(client, app, appointment_factory):
    login(client, "admin@mmu.edu.my")
    appointment_factory(status="Completed", purpose="Dashboard completed sample")
    db.session.add(AuditLog(actor_user_id=5, action="user.deactivated", target_type="User", target_id="1"))
    db.session.commit()

    response = client.get("/admin")

    markup = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Active users" in markup
    assert "Pending" in markup
    assert "Completed" in markup
    assert "Recent administrative activity" in markup
    assert "Dashboard completed sample" not in markup
    assert "chart.js" not in markup.lower()


def test_admin_user_search_filters_and_detail_hide_sensitive_fields(client, app, user_factory):
    target = user_factory(role="teacher", active=False)
    target.email_verified_at = None
    target.last_login_at = FIXED_NOW - timedelta(days=2)
    db.session.commit()
    login(client, "admin@mmu.edu.my")

    filtered = client.get("/usercontrol?search=fixture&role=teacher&active=inactive&verification=unverified")
    detail = client.get(f"/admin/users/{target.id}")

    assert filtered.status_code == 200
    assert target.username in filtered.get_data(as_text=True)
    assert detail.status_code == 200
    detail_markup = detail.get_data(as_text=True)
    assert target.email in detail_markup
    assert target.phone_number in detail_markup
    assert "Inactive" in detail_markup and "Unverified" in detail_markup
    assert target.password_hash not in detail_markup
    assert "session_version" not in detail_markup
    assert client.get("/admin/users/999999").status_code == 404


def test_admin_user_filters_reject_invalid_values_and_preserve_query(client):
    login(client, "admin@mmu.edu.my")

    assert client.get("/usercontrol?role=owner").status_code == 400
    assert client.get("/usercontrol?active=maybe").status_code == 400
    markup = client.get("/usercontrol?role=student&active=active&faculty_id=1").get_data(as_text=True)
    assert 'name="role"' in markup
    assert 'name="active"' in markup
    assert 'name="faculty_id"' in markup


def test_invitation_list_paginates_safe_statuses_without_hashes(client, app):
    login(client, "admin@mmu.edu.my")
    invites = [
        LecturerInvitation(
            token_hash=f"{index:064x}",
            email=f"invite{index}@mmu.edu.my",
            created_by_id=5,
            created_at=FIXED_NOW - timedelta(days=index),
            expires_at=FIXED_NOW + timedelta(days=7 - index),
            used_at=FIXED_NOW if index == 2 else None,
            revoked_at=FIXED_NOW if index == 3 else None,
        )
        for index in range(1, 4)
    ]
    invites.append(
        LecturerInvitation(
            token_hash=f"{4:064x}", email="expired@mmu.edu.my", created_by_id=5,
            created_at=FIXED_NOW - timedelta(days=10), expires_at=FIXED_NOW - timedelta(days=1),
        )
    )
    db.session.add_all(invites)
    db.session.commit()

    response = client.get("/usercontrol?invitation_page=1")

    assert response.status_code == 200
    markup = response.get_data(as_text=True)
    assert "Expired" in markup
    assert "Used" in markup
    assert "Revoked" in markup
    assert "Active" in markup
    assert all(invitation.token_hash not in markup for invitation in invites)
    filtered = client.get("/usercontrol?invitation_status=expired&invitation_page=1")
    assert "expired@mmu.edu.my" in filtered.get_data(as_text=True)
    assert "invite1@mmu.edu.my" not in filtered.get_data(as_text=True)


def test_appointment_filters_and_admin_detail_show_history_not_internal_ids(client, appointment_factory):
    appointment = appointment_factory(status="Accepted", purpose="History review target")
    db.session.add(
        AppointmentStatusHistory(
            appointment_id=appointment.id,
            from_status="Pending",
            to_status="Accepted",
            actor_user_id=3,
            created_at=FIXED_NOW,
        )
    )
    db.session.commit()
    login(client, "admin@mmu.edu.my")

    filtered = client.get("/appointmentcontrol?search=History+review&status=Accepted&date_from=2026-10-01")
    detail = client.get(f"/admin/appointments/{appointment.public_reference}")

    assert filtered.status_code == 200
    assert appointment.public_reference in filtered.get_data(as_text=True)
    assert detail.status_code == 200
    markup = detail.get_data(as_text=True)
    assert appointment.public_reference in markup
    assert "Student One" in markup and "Lecturer One" in markup
    assert "Pending" in markup and "Accepted" in markup
    assert f">{appointment.id}<" not in markup
    assert client.get("/admin/appointments/not-a-reference").status_code == 404


def test_admin_appointment_filter_validation(client):
    login(client, "admin@mmu.edu.my")

    assert client.get("/appointmentcontrol?status=In+Progress").status_code == 400
    assert client.get("/appointmentcontrol?date_from=not-a-date").status_code == 400
    assert client.get("/appointmentcontrol?date_from=2026-10-10&date_to=2026-10-01").status_code == 400


def test_faculty_management_search_counts_members_and_edit_audits(client, app, faculty_factory, user_factory):
    faculty = faculty_factory("Faculty for Admin Edit")
    member = user_factory(role="teacher", faculty_id=faculty.id)
    login(client, "admin@mmu.edu.my")

    list_response = client.get("/faculty?q=Faculty+for+Admin+Edit&faculty_id=" + str(faculty.id))
    edit_response = client.get(f"/faculty/{faculty.id}/edit")
    save_response = client.post(
        f"/faculty/{faculty.id}/edit",
        data={"faculty_name": "Faculty Edited Safely"},
    )

    assert list_response.status_code == 200
    list_markup = list_response.get_data(as_text=True)
    assert faculty.faculty_name in list_markup and member.username in list_markup
    assert "1 member" in list_markup
    assert edit_response.status_code == 200
    assert save_response.status_code == 302
    db.session.expire_all()
    assert db.session.get(Faculty, faculty.id).faculty_name == "Faculty Edited Safely"
    assert db.session.scalar(select(AuditLog).where(AuditLog.action == "faculty.updated")) is not None


def test_faculty_edit_rejects_duplicate_names_and_missing_faculty(client, faculty_factory):
    faculty = faculty_factory("Existing Faculty")
    login(client, "admin@mmu.edu.my")

    duplicate = client.post(f"/faculty/{faculty.id}/edit", data={"faculty_name": "FCI"})

    assert duplicate.status_code == 409
    assert client.get("/faculty/999999/edit").status_code == 404


def test_audit_log_filters_and_summarizes_known_actions_without_metadata_dump(client, app):
    login(client, "admin@mmu.edu.my")
    db.session.add_all(
        [
            AuditLog(actor_user_id=5, action="user.deactivated", target_type="User", target_id="1", metadata_json={"role": "student", "token_hash": "never-render"}),
            AuditLog(actor_user_id=5, action="site_settings.updated", target_type="SiteSettings", target_id="1", metadata_json={"password_hash": "never-render"}),
            AuditLog(actor_user_id=5, action="secret-token-raw", target_type="UnknownType", target_id="private-record-id", metadata_json={"credential": "never-render"}),
        ]
    )
    db.session.commit()

    response = client.get("/admin/audit-log?actor=Administrator&action=user.deactivated&target_type=User")

    assert response.status_code == 200
    markup = response.get_data(as_text=True)
    assert "User deactivated" in markup
    assert "Student" in markup
    assert "never-render" not in markup
    assert "token_hash" not in markup
    assert "password_hash" not in markup
    assert "private-record-id" not in markup
    assert "secret-token-raw" not in markup
    assert "Administrator" in markup
    assert "name=\"actor\"" in markup


def test_new_admin_mutations_still_require_csrf(client, app, faculty_factory):
    login(client, "admin@mmu.edu.my")
    app.config["WTF_CSRF_ENABLED"] = True
    faculty = faculty_factory("CSRF Edit Faculty")

    response = client.post(f"/faculty/{faculty.id}/edit", data={"faculty_name": "No CSRF"})

    assert response.status_code == 400
    db.session.expire_all()
    assert db.session.get(Faculty, faculty.id).faculty_name == "CSRF Edit Faculty"


def test_admin_new_read_routes_keep_role_separation(client):
    for email in ("student1@student.mmu.edu.my", "lecturer1@mmu.edu.my"):
        login(client, email)
        assert client.get("/admin/audit-log").status_code == 403
        client.post("/logout")


def test_invitation_creation_displays_raw_token_once_and_stores_only_its_hash(client, app):
    login(client, "admin@mmu.edu.my")

    response = client.post("/admin/lecturer-invitations", data={"email": "newlecturer@mmu.edu.my"})

    markup = response.get_data(as_text=True)
    match = re.search(r'<code><span id="invitation-token">([^<]+)</span></code>', markup)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert match
    token = match.group(1)
    assert 'data-copy-invitation="invitation-token"' in markup
    assert token not in response.request.path
    invitation = db.session.scalar(
        select(LecturerInvitation).where(LecturerInvitation.email == "newlecturer@mmu.edu.my")
    )
    assert invitation.token_hash == LecturerInvitation.hash_token(token)
    assert token not in client.get("/usercontrol").get_data(as_text=True)


def test_deactivation_invalidates_sessions_and_reactivation_keeps_availability_off(
    client, app, user_factory, availability_factory
):
    lecturer = user_factory(role="teacher")
    availability = availability_factory(lecturer_id=lecturer.id)
    login(client, "admin@mmu.edu.my")
    starting_version = lecturer.session_version

    deactivated = client.post("/delete_user", data={"id": lecturer.id})

    assert deactivated.status_code == 302
    db.session.expire_all()
    assert not db.session.get(type(lecturer), lecturer.id).active
    assert db.session.get(type(lecturer), lecturer.id).session_version == starting_version + 1
    assert not db.session.get(type(availability), availability.id).active
    reactivated = client.post("/activate_user", data={"id": lecturer.id})
    assert reactivated.status_code == 302
    db.session.expire_all()
    assert db.session.get(type(lecturer), lecturer.id).active
    assert not db.session.get(type(availability), availability.id).active
    assert db.session.scalar(select(AuditLog).where(AuditLog.action == "user.deactivated"))
    assert db.session.scalar(select(AuditLog).where(AuditLog.action == "user.reactivated"))


def test_admin_can_complete_accepted_appointment_and_cannot_delete_history(
    client, appointment_factory
):
    appointment = appointment_factory(status="Accepted")
    login(client, "admin@mmu.edu.my")

    response = client.post(
        "/admin/appointment-status",
        data={"id": appointment.id, "status": "Completed"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Appointment marked as completed" in response.data
    db.session.expire_all()
    assert db.session.get(Appointment, appointment.id).status == "Completed"
    assert db.session.scalar(
        select(AppointmentStatusHistory).where(AppointmentStatusHistory.appointment_id == appointment.id)
    )
    detail = client.get(f"/admin/appointments/{appointment.public_reference}")
    assert b"cannot be deleted" in detail.data
    deleted = client.post("/delete_booking", data={"id": appointment.id}, follow_redirects=True)
    assert b"cannot be deleted" in deleted.data
    assert db.session.get(Appointment, appointment.id) is not None


def test_admin_can_delete_unmodified_appointment_only_after_detail_confirmation(client, appointment_factory):
    appointment = appointment_factory(status="Pending")
    appointment_id = appointment.id
    login(client, "admin@mmu.edu.my")

    detail = client.get(f"/admin/appointments/{appointment.public_reference}")
    markup = detail.get_data(as_text=True)
    assert 'data-dialog-open="delete-appointment"' in markup
    assert f">{appointment.id}<" not in markup
    response = client.post("/delete_booking", data={"id": appointment_id}, follow_redirects=True)

    assert response.status_code == 200
    assert b"Appointment deleted" in response.data
    db.session.expire_all()
    assert db.session.get(Appointment, appointment_id) is None


def test_faculty_edit_accepts_decoded_image_and_preserves_replaced_asset(client, app, faculty_factory):
    faculty = faculty_factory("Faculty Image Edit")
    login(client, "admin@mmu.edu.my")

    def upload_image(fmt, filename):
        buffer = BytesIO()
        Image.new("RGB", (3, 3), (30, 90, 130)).save(buffer, format=fmt)
        buffer.seek(0)
        return buffer, filename

    first = client.post(
        f"/faculty/{faculty.id}/edit",
        data={"faculty_name": faculty.faculty_name, "faculty_image": upload_image("PNG", "first.png")},
    )
    assert first.status_code == 302
    db.session.expire_all()
    old_image = db.session.get(Faculty, faculty.id).faculty_image
    second = client.post(
        f"/faculty/{faculty.id}/edit",
        data={"faculty_name": "Faculty Image Updated", "faculty_image": upload_image("JPEG", "second.jpg")},
    )
    assert second.status_code == 302
    db.session.expire_all()
    new_image = db.session.get(Faculty, faculty.id).faculty_image
    assert new_image != old_image
    assert re.fullmatch(r"[a-f0-9]{32}\.jpg", new_image)
    assert (Path(app.config["UPLOAD_FOLDER"]) / old_image).is_file()
    assert (Path(app.config["UPLOAD_FOLDER"]) / new_image).is_file()


def test_faculty_edit_rejects_deceptive_image_and_preserves_name(client, faculty_factory):
    faculty = faculty_factory("Faculty Image Validation")
    login(client, "admin@mmu.edu.my")

    response = client.post(
        f"/faculty/{faculty.id}/edit",
        data={"faculty_name": "Changed Name", "faculty_image": (BytesIO(b"not an image"), "image.png")},
    )

    assert response.status_code == 400
    assert b"faculty_image-error" in response.data or b"valid image" in response.data
    db.session.expire_all()
    assert db.session.get(Faculty, faculty.id).faculty_name == "Faculty Image Validation"


def test_site_settings_validation_preserves_fields_and_logs_success(client, app):
    login(client, "admin@mmu.edu.my")
    initial = client.get("/adminpageeditor")
    assert initial.status_code == 200
    assert all(name.encode() in initial.data for name in ("school_name", "school_tel", "school_email", "school_logo", "home_content"))

    invalid = client.post(
        "/adminpageeditor",
        data={"school_name": "Changed School", "school_tel": "010-1234567", "school_email": "not-an-email", "home_content": "Plain content"},
    )
    assert invalid.status_code == 400
    assert b"school_email" in invalid.data
    assert db.session.get(SiteSettings, 1) is None

    saved = client.post(
        "/adminpageeditor",
        data={"school_name": "Updated University", "school_tel": "+60312345678", "school_email": "contact@example.edu", "home_content": "Plain content only"},
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert b"Site settings saved" in saved.data
    settings = db.session.get(SiteSettings, 1)
    assert settings.school_name == "Updated University"
    assert "Plain content only" == settings.home_content
    assert db.session.scalar(select(AuditLog).where(AuditLog.action == "site_settings.updated"))


def test_audit_ordering_index_is_in_schema(client):
    indexes = {index["name"] for index in inspect(db.engine).get_indexes("audit_logs")}
    assert "ix_audit_logs_created_id" in indexes


def test_all_admin_post_actions_reject_missing_csrf(client, app, faculty_factory, user_factory, appointment_factory):
    login(client, "admin@mmu.edu.my")
    faculty = faculty_factory("CSRF protected faculty")
    inactive_user = user_factory(active=False)
    active_user = user_factory(role="teacher")
    pending = appointment_factory(status="Pending")
    accepted = appointment_factory(
        status="Accepted",
        starts_at=appointment_factory().starts_at + timedelta(minutes=30),
    )
    invitation = LecturerInvitation(
        token_hash="a" * 64,
        email="csrf@mmu.edu.my",
        expires_at=FIXED_NOW + timedelta(days=7),
        created_by_id=5,
    )
    db.session.add(invitation)
    db.session.commit()
    app.config["WTF_CSRF_ENABLED"] = True

    responses = [
        client.post(f"/faculty/{faculty.id}/edit", data={"faculty_name": "No CSRF"}),
        client.post("/delete_user", data={"id": active_user.id}),
        client.post("/activate_user", data={"id": inactive_user.id}),
        client.post("/delete_booking", data={"id": pending.id}),
        client.post("/admin/appointment-status", data={"id": accepted.id, "status": "Completed"}),
        client.post(f"/admin/lecturer-invitations/{invitation.id}/revoke"),
        client.post("/adminpageeditor", data={"school_name": "No CSRF"}),
    ]

    assert [response.status_code for response in responses] == [400] * len(responses)
    db.session.expire_all()
    assert db.session.get(Faculty, faculty.id).faculty_name == "CSRF protected faculty"
    assert db.session.get(type(active_user), active_user.id).active
    assert not db.session.get(type(inactive_user), inactive_user.id).active
    assert db.session.get(Appointment, accepted.id).status == "Accepted"
    assert db.session.get(LecturerInvitation, invitation.id).revoked_at is None

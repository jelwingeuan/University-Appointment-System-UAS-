from flask import url_for

_ROLE_LABELS = {"student": "Student", "teacher": "Lecturer", "admin": "Administrator"}
_ROLE_LINKS = {
    "student": (
        ("Home", "appointments.appointment", "fa-house", ("appointments.appointment",)),
        ("Book", "appointments.appointment2", "fa-calendar-plus", ("appointments.appointment2",)),
        ("Appointments", "appointments.booking_history", "fa-calendar-check", ("appointments.booking_history", "appointments.invoice")),
        ("Explore", "faculty.student_explore", "fa-building-columns", ("faculty.student_explore",)),
        ("Profile", "profile.profile", "fa-user", ("profile.profile", "profile.change_password", "profile.changepassword")),
    ),
    "teacher": (
        ("Appointments", "appointments.booking_history", "fa-calendar-check", ("appointments.booking_history",)),
        ("Calendar", "calendar.events_page", "fa-calendar-days", ("calendar.events_page", "calendar.calendar_record")),
        ("Profile", "profile.profile", "fa-user", ("profile.profile", "profile.change_password", "profile.changepassword")),
    ),
    "admin": (
        ("Dashboard", "admin.admin_dashboard", "fa-chart-line", ("admin.admin_dashboard",)),
        ("Users", "admin.usercontrol", "fa-users", ("admin.usercontrol", "admin.create_lecturer_invitation", "admin.revoke_lecturer_invitation_route")),
        ("Appointments", "admin.appointmentcontrol", "fa-calendar-check", ("admin.appointmentcontrol", "admin.delete_booking", "admin.admin_appointment_status")),
        ("Faculties", "faculty.faculty", "fa-building-columns", ("faculty.faculty", "faculty.create_faculty_hub")),
        ("Site Settings", "admin.admin_page_editor", "fa-sliders", ("admin.admin_page_editor",)),
        ("Profile", "profile.profile", "fa-user", ("profile.profile", "profile.change_password", "profile.changepassword")),
    ),
}


def account_initials(value):
    parts = (value or "U").strip().split()
    if len(parts) > 1:
        return f"{parts[0][0]}{parts[1][0]}".upper()
    return parts[0][:2].upper()


def navigation_for_user(role, endpoint):
    links = []
    for label, view, icon, active_endpoints in _ROLE_LINKS.get(role, ()):
        links.append(
            {
                "label": label,
                "url": url_for(view),
                "icon": icon,
                "active": endpoint in active_endpoints,
            }
        )
    return links


def role_label(role):
    return _ROLE_LABELS.get(role, "Account")

import re
from urllib.parse import urlsplit

from flask import abort

from tests.conftest import login

APP_LINKS = re.compile(r'<a class="app-nav-link[^\"]*" href="([^\"]+)"([^>]*)>(.*?)</a>', re.DOTALL)


def links_for(markup):
    return [(urlsplit(href).path, attrs, re.sub(r"<[^>]+>", "", label).strip()) for href, attrs, label in APP_LINKS.findall(markup)]


def assert_app_shell(markup):
    assert 'class="app-shell"' in markup
    assert '<main id="main-content"' in markup
    assert 'href="#main-content"' in markup
    assert 'id="uas-theme"' in markup
    assert markup.count('id="uas-theme"') == 1
    assert 'id="app-navigation"' in markup
    assert 'aria-labelledby="app-navigation-title"' in markup
    assert '/static/ui.js' in markup


def test_student_shell_uses_only_student_navigation_and_resolvable_links(client, app, appointment_factory):
    login(client, "student1@student.mmu.edu.my")
    markup = client.get("/appointment2").get_data(as_text=True)
    assert_app_shell(markup)
    links = links_for(markup)
    paths = {path for path, _, _ in links}
    assert {"/appointment", "/appointment2", "/bookinghistory", "/explore", "/profile"} <= paths
    assert not paths & {"/admin", "/calendar", "/faculty", "/usercontrol"}
    assert {"Home", "Book", "Appointments", "Explore", "Profile"} <= {label for _, _, label in links}
    assert markup.count('class="app-nav-link is-active"') == 2
    assert 'aria-current="step"' in markup
    assert all(app.url_map.bind("localhost").match(path)[0] for path in paths)
    assert "Student One" in markup
    assert "Student" in markup
    assert "FCI" in markup
    assert 'action="/logout" method="post"' in markup
    assert re.search(r'<form[^>]+action="/logout"[^>]+method="post"[^>]*>.*?name="csrf_token"', markup, re.DOTALL)
    assert 'data-dialog-close' in markup
    invoice = appointment_factory()
    invoice_markup = client.get(f"/invoice?reference={invoice.public_reference}").get_data(as_text=True)
    assert_app_shell(invoice_markup)
    assert 'aria-label="Breadcrumb"' in invoice_markup


def test_lecturer_and_admin_shells_expose_only_their_role_destinations(client, app):
    login(client, "lecturer1@mmu.edu.my")
    lecturer = client.get("/calendar").get_data(as_text=True)
    assert_app_shell(lecturer)
    lecturer_paths = {path for path, _, _ in links_for(lecturer)}
    assert {"/bookinghistory", "/calendar", "/profile"} <= lecturer_paths
    assert not lecturer_paths & {"/admin", "/faculty", "/appointment2", "/usercontrol"}
    assert "Lecturer" in lecturer
    assert 'aria-current="page"' in lecturer

    client.post("/logout")
    login(client, "admin@mmu.edu.my")
    admin = client.get("/admin").get_data(as_text=True)
    assert_app_shell(admin)
    admin_paths = {path for path, _, _ in links_for(admin)}
    assert {"/admin", "/usercontrol", "/appointmentcontrol", "/faculty", "/adminpageeditor", "/profile"} <= admin_paths
    assert not admin_paths & {"/appointment2", "/bookinghistory", "/calendar"}
    assert {"Dashboard", "Users", "Appointments", "Faculties", "Site Settings", "Profile"} <= {
        label for _, _, label in links_for(admin)
    }
    assert 'aria-current="page"' in admin
    assert "Administrator" in admin
    assert_app_shell(client.get("/usercontrol").get_data(as_text=True))
    assert_app_shell(client.get("/appointmentcontrol").get_data(as_text=True))
    assert_app_shell(client.get("/faculty").get_data(as_text=True))
    assert_app_shell(client.get("/adminpageeditor").get_data(as_text=True))

    invitation = client.post("/admin/lecturer-invitations", data={"email": "newlecturer@mmu.edu.my"})
    assert invitation.status_code == 200
    assert_app_shell(invitation.get_data(as_text=True))


def test_public_pages_stay_on_public_layout_with_role_valid_application_menu(client):
    login(client, "student1@student.mmu.edu.my")
    markup = client.get("/").get_data(as_text=True)
    assert 'class="app-shell"' not in markup
    assert 'class="public-nav"' in markup
    assert 'id="uas-theme"' in markup
    assert 'href="/appointment"' in markup
    assert 'href="/appointment2"' in markup
    assert 'href="/explore"' in markup
    assert 'href="/bookinghistory"' in markup
    assert 'href="/calendar"' not in markup
    assert 'href="/admin"' not in markup


def test_app_page_header_and_deeper_page_breadcrumbs_render_semantically(client):
    login(client, "admin@mmu.edu.my")
    markup = client.get("/createfacultyhub").get_data(as_text=True)
    assert '<h1>Add Faculty</h1>' in markup
    assert 'aria-label="Breadcrumb"' in markup
    assert 'aria-current="page">Add Faculty</span>' in markup
    assert 'href="/faculty"' in markup
    assert 'href="/admin"' in markup


def test_shell_errors_render_html_only_when_html_is_requested(client, app):
    def missing():
        abort(404)

    def conflict():
        abort(409)

    def failed():
        abort(500)

    app.add_url_rule("/test-html-missing", endpoint="test_html_missing", view_func=missing)
    app.add_url_rule("/test-html-conflict", endpoint="test_html_conflict", view_func=conflict)
    app.add_url_rule("/test-html-failed", endpoint="test_html_failed", view_func=failed)

    for path, status, title in (
        ("/test-html-missing", 404, "Page not found"),
        ("/test-html-conflict", 409, "Conflict"),
        ("/test-html-failed", 500, "Something went wrong"),
    ):
        response = client.get(path, headers={"Accept": "text/html"})
        assert response.status_code == status
        assert response.mimetype == "text/html"
        assert title in response.get_data(as_text=True)

    json_response = client.get("/test-html-missing", headers={"Accept": "application/json"})
    assert json_response.status_code == 404
    assert "<html" not in json_response.get_data(as_text=True)
    assert json_response.get_data(as_text=True) == "Page not found"


def test_forbidden_browser_error_uses_public_base_and_preserves_status(client):
    login(client, "student1@student.mmu.edu.my")
    response = client.get("/admin", headers={"Accept": "text/html"})
    assert response.status_code == 403
    assert 'class="app-shell"' not in response.get_data(as_text=True)
    assert "Access denied" in response.get_data(as_text=True)

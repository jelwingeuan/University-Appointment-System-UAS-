from tests.conftest import login


def assert_shared_shell(markup):
    assert 'href="#main-content"' in markup
    assert '<main id="main-content"' in markup
    assert 'id="uas-theme"' in markup
    assert 'name="theme"' in markup
    assert "/static/ui.js" in markup
    assert "/static/css/design-system.css" in markup


def test_public_templates_use_shared_shell(client):
    for path in (
        "/", "/login", "/signup", "/password-reset",
        "/password-reset/complete", "/email-verification/complete",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert_shared_shell(response.get_data(as_text=True))
        assert 'class="app-shell"' not in response.get_data(as_text=True)
    login(client, "student1@student.mmu.edu.my")
    appointment = client.get("/appointment")
    assert appointment.status_code == 200
    assert_shared_shell(appointment.get_data(as_text=True))
    assert 'class="app-shell"' in appointment.get_data(as_text=True)


def test_authenticated_role_templates_use_shared_shell(client):
    for path in ("/appointment2", "/profile", "/change_password", "/bookinghistory"):
        login(client, "student1@student.mmu.edu.my")
        response = client.get(path)
        assert response.status_code == 200, path
        assert_shared_shell(response.get_data(as_text=True))
        assert 'class="app-shell"' in response.get_data(as_text=True)
        client.post("/logout")

    login(client, "lecturer1@mmu.edu.my")
    calendar = client.get("/calendar")
    assert calendar.status_code == 200
    assert_shared_shell(calendar.get_data(as_text=True))
    assert 'class="app-shell"' in calendar.get_data(as_text=True)
    client.post("/logout")

    login(client, "admin@mmu.edu.my")
    for path in ("/admin", "/usercontrol", "/appointmentcontrol", "/faculty"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert_shared_shell(response.get_data(as_text=True))
        assert 'class="app-shell"' in response.get_data(as_text=True)


def test_persistent_flashes_render_accessible_categories_and_dismiss_controls(client):
    with client.session_transaction() as session:
        session["_flashes"] = [("error", "Check the submitted details."), ("success", "Changes saved.")]

    markup = client.get("/login").get_data(as_text=True)
    assert 'class="flash-message alert alert-danger" role="alert"' in markup
    assert 'class="flash-message alert alert-success" role="status"' in markup
    assert 'aria-live="polite"' in markup
    assert markup.count('data-alert-dismiss') == 2
    assert "Check the submitted details." in markup
    assert "Changes saved." in markup


def test_design_system_showcase_has_all_statuses_and_interaction_helpers(client):
    response = client.get("/design-system")
    markup = response.get_data(as_text=True)
    assert response.status_code == 200
    assert_shared_shell(markup)
    for state in ("pending", "accepted", "rejected", "cancelled", "completed", "no-show"):
        assert f"status-{state}" in markup
    assert 'data-dialog-open="design-dialog"' in markup
    assert 'data-toast-kind="success"' in markup


def test_design_system_showcase_is_not_available_in_production(client, app):
    app.config["APP_ENV"] = "production"
    assert client.get("/design-system").status_code == 404

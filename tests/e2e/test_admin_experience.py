from datetime import timedelta
from threading import Thread

import pytest
from werkzeug.serving import make_server

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright

from tests.conftest import FIXED_NOW
from uas.extensions import db
from uas.models import User


@pytest.fixture
def admin_live_server(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=3)


def login_admin(page, base_url):
    page.goto(f"{base_url}/login")
    login_form = page.locator("form").filter(has=page.locator('input[name="password"]'))
    login_form.locator('input[name="email"]').fill("admin@mmu.edu.my")
    login_form.locator('input[name="password"]').fill("CorrectHorse1")
    login_form.locator('input[name="password"]').press("Enter")
    page.wait_for_url(f"{base_url}/admin")


def test_admin_user_invitation_appointment_faculty_settings_and_audit_flows(
    app, admin_live_server, user_factory, faculty_factory, appointment_factory
):
    user = user_factory(role="teacher")
    with app.app_context():
        stored_user = db.session.get(User, user.id)
        stored_user.username = "Lecturer " + "LongDisplayName " * 6
        db.session.commit()
        user_id = stored_user.id
        long_username = stored_user.username

    faculty_factory("Faculty for admin browser")
    accepted = appointment_factory(status="Accepted", purpose="Admin browser appointment")
    pending = appointment_factory(
        starts_at=FIXED_NOW + timedelta(days=9, hours=2),
        purpose="Appointment for confirmed deletion",
    )

    with sync_playwright() as playwright_session:
        try:
            browser = playwright_session.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        try:
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            context.grant_permissions(["clipboard-read", "clipboard-write"], origin=admin_live_server)
            page = context.new_page()
            console_errors = []
            local_asset_errors = []
            page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: console_errors.append(str(error)))
            page.on("response", lambda response: local_asset_errors.append(response.url) if response.url.startswith(admin_live_server) and response.status >= 400 else None)
            login_admin(page, admin_live_server)

            page.goto(f"{admin_live_server}/admin/users/{user_id}")
            expect(page.get_by_role("heading", name="User details")).to_be_visible()
            expect(page.locator("main")).to_contain_text(long_username)
            deactivate = page.get_by_role("button", name="Deactivate account")
            deactivate.click()
            deactivate_dialog = page.get_by_role("dialog", name=f"Deactivate {long_username}?")
            expect(deactivate_dialog).to_be_visible()
            deactivate_dialog.get_by_role("button", name="Deactivate account").click()
            expect(page.get_by_role("status").filter(has_text="Account deactivated")).to_be_visible()

            page.goto(f"{admin_live_server}/admin/users/{user_id}")
            reactivate = page.get_by_role("button", name="Reactivate account")
            reactivate.click()
            page.get_by_role("dialog", name=f"Reactivate {long_username}?").get_by_role(
                "button", name="Reactivate account"
            ).click()
            expect(page.get_by_role("status").filter(has_text="Account reactivated")).to_be_visible()

            page.goto(f"{admin_live_server}/usercontrol#invite-lecturer")
            page.get_by_label("Institutional email, optional").fill("browser-invite@mmu.edu.my")
            page.get_by_role("button", name="Create invitation").click()
            page.wait_for_url("**/admin/lecturer-invitations")
            expect(page.get_by_role("heading", name="Lecturer invitation created")).to_be_visible()
            page.get_by_role("button", name="Copy token").click()
            expect(page.get_by_role("status").filter(has_text="Invitation token copied")).to_be_visible(timeout=3000)

            page.goto(f"{admin_live_server}/appointmentcontrol?search=Admin+browser+appointment&status=Accepted")
            page.get_by_role("link", name=accepted.public_reference).click()
            expect(page.locator("main")).to_contain_text("Status history")
            page.get_by_role("button", name="Mark Completed").click()
            completed_dialog = page.get_by_role("dialog", name="Mark as completed?")
            expect(completed_dialog).to_be_visible()
            completed_dialog.get_by_role("button", name="Confirm Completed").click()
            expect(page.get_by_role("status").filter(has_text="Appointment marked as completed")).to_be_visible()

            page.goto(f"{admin_live_server}/admin/appointments/{pending.public_reference}")
            page.get_by_role("button", name="Delete appointment").first.click()
            delete_dialog = page.get_by_role("dialog", name="Delete this appointment?")
            expect(delete_dialog).to_be_visible()
            delete_dialog.get_by_role("button", name="Delete appointment").click()
            expect(page.get_by_role("status").filter(has_text="Appointment deleted")).to_be_visible()

            page.goto(f"{admin_live_server}/faculty?q=Faculty+for+admin+browser")
            page.get_by_role("link", name="Edit", exact=True).click()
            page.get_by_label("Faculty name").fill("Faculty edited in browser")
            page.get_by_role("button", name="Save faculty").click()
            expect(page.get_by_role("status").filter(has_text="Faculty updated")).to_be_visible()

            long_school_name = "Multimedia University " + "Administrative Portal " * 5
            page.goto(f"{admin_live_server}/adminpageeditor")
            page.get_by_label("School name").fill(long_school_name[:200])
            page.get_by_label("School contact").fill("+60312345678")
            page.get_by_label("School email").fill("contact@example.edu")
            page.get_by_label("Homepage text").fill("Updated through the admin console")
            page.get_by_role("button", name="Save settings").click()
            expect(page.get_by_role("status").filter(has_text="Site settings saved")).to_be_visible()

            page.get_by_role("link", name="Audit Log", exact=True).click()
            expect(page.locator("main")).to_contain_text("Site settings updated")
            expect(page.locator("main")).to_contain_text("Faculty updated")
            expect(page.locator("main")).to_contain_text("User deactivated")

            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="Open application navigation").click()
            drawer = page.locator("#app-navigation")
            expect(drawer).to_be_visible()
            page.keyboard.press("Escape")
            expect(drawer).not_to_be_visible()
            expect(page.get_by_role("button", name="Open application navigation")).to_be_focused()

            for theme in ("light", "dark", "system"):
                page.locator("#uas-theme").select_option(theme)
                assert page.locator("html").get_attribute("data-theme") == theme

            for width in (320, 360, 390, 430, 768, 820, 1024, 1280, 1440, 1920):
                page.set_viewport_size({"width": width, "height": 844})
                dimensions = page.evaluate("({scroll: document.documentElement.scrollWidth, viewport: window.innerWidth})")
                assert dimensions["scroll"] <= dimensions["viewport"], f"overflow at {width}px: {dimensions}"
            page.set_viewport_size({"width": 844, "height": 390})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "admin overflows in landscape"
            assert console_errors == []
            assert local_asset_errors == []
        finally:
            browser.close()


def test_admin_account_menu_keyboard_and_mobile_filters(app, admin_live_server, user_factory):
    with app.app_context():
        admin = db.session.get(User, 5)
        admin.username = "Administrator With A Long Name For Narrow Screens"
        db.session.commit()
    user_factory(role="teacher")

    with sync_playwright() as playwright_session:
        try:
            browser = playwright_session.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            login_admin(page, admin_live_server)
            page.goto(f"{admin_live_server}/usercontrol?role=teacher&active=active")
            expect(page.get_by_label("Role")).to_have_value("teacher")
            expect(page.get_by_label("Account status")).to_have_value("active")

            account_summary = page.locator(".app-account-menu summary")
            account_summary.focus()
            page.keyboard.press("Enter")
            expect(page.locator(".app-account-menu")).to_have_attribute("open", "")
            page.keyboard.press("Escape")
            expect(page.locator(".app-account-menu")).not_to_have_attribute("open", "")
            expect(account_summary).to_be_focused()

            for width in (320, 360, 390, 430, 768, 820, 1024, 1280, 1440, 1920):
                page.set_viewport_size({"width": width, "height": 844})
                dimensions = page.evaluate("({scroll: document.documentElement.scrollWidth, viewport: window.innerWidth})")
                assert dimensions["scroll"] <= dimensions["viewport"], f"overflow at {width}px: {dimensions}"
        finally:
            browser.close()

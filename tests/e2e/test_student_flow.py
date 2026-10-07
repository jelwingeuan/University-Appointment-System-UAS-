from datetime import datetime
from threading import Thread
from zoneinfo import ZoneInfo

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from uas.extensions import db
from uas.models import Appointment, NotificationType, User
from uas.notification_service import create_notification


@pytest.fixture
def live_server(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=3)


def test_student_can_book_review_cancel_and_is_blocked_from_other_roles(app, live_server):
    with app.app_context():
        student = db.session.get(User, 1)
        student.username = "Student With A Particularly Long Display Name For Small Screens"
        db.session.commit()

    with sync_playwright() as playwright_session:
        try:
            browser = playwright_session.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")

        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(f"{live_server}/login")
            login_form = page.locator("form").filter(has=page.locator('input[name="password"]'))
            email = login_form.locator('input[name="email"]')
            password = login_form.locator('input[name="password"]')
            email.fill("student1@student.mmu.edu.my")
            password.fill("CorrectHorse1")
            password.press("Enter")
            page.wait_for_url("**/appointment")

            for width in (320, 360, 390, 430, 768, 820, 1024, 1280, 1440, 1920):
                page.set_viewport_size({"width": width, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="Open application navigation").click()
            page.get_by_role("link", name="Book", exact=True).click()
            page.locator("#faculty-select").select_option("1")
            page.locator("#lecturer-select").select_option("3")
            slot_start = datetime.fromisoformat(app.config["TEST_SLOT_START"])
            local_date = slot_start.astimezone(ZoneInfo("Asia/Kuala_Lumpur")).date().isoformat()
            page.locator("#appointment-date").fill(local_date)
            page.locator('input[name="slot-selection"]').first.wait_for()
            page.locator('input[name="slot-selection"]').first.check()
            page.locator('textarea[name="purpose"]').fill("Review my study plan")
            page.get_by_role("button", name="Review request").click()

            review = page.get_by_role("dialog", name="Review appointment request")
            review.wait_for(state="visible")
            assert "Lecturer One" in review.inner_text()
            assert "Review my study plan" in review.inner_text()
            page.get_by_role("button", name="Send request").click()
            page.wait_for_url("**/invoice?reference=*")
            assert "Appointment request sent" in page.locator("main").inner_text()
            assert "Pending" in page.locator("main").inner_text()

            page.get_by_role("button", name="Cancel appointment").click()
            confirmation = page.get_by_role("dialog", name="Cancel appointment")
            confirmation.wait_for(state="visible")
            page.get_by_role("button", name="Confirm cancellation").click()
            page.wait_for_url("**/bookinghistory")
            assert "Cancelled" in page.locator("main").inner_text()

            for path in ("/bookinghistory", "/profile"):
                page.goto(f"{live_server}{path}")
                for width in (320, 360, 390, 430, 768, 820, 1024, 1280, 1440, 1920):
                    page.set_viewport_size({"width": width, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                        f"{path} overflows at {width}px"
                    )
                page.set_viewport_size({"width": 844, "height": 390})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                    f"{path} overflows in landscape"
                )

            page.goto(f"{live_server}/calendar")
            assert "Access denied" in page.locator("main").inner_text()
            page.goto(f"{live_server}/admin")
            assert "Access denied" in page.locator("main").inner_text()
        finally:
            browser.close()


def test_student_notification_flow_preferences_and_mobile_keyboard(app, live_server, appointment_factory):
    appointment = appointment_factory(status="Accepted")
    with app.app_context():
        row = db.session.get(Appointment, appointment.id)
        create_notification(
            db.session,
            user_id=row.student_id,
            appointment=row,
            notification_type=NotificationType.APPOINTMENT_ACCEPTED.value,
            deduplication_key=f"e2e-student-accepted:{row.id}",
            title="Appointment accepted",
            message="Your appointment has been accepted.",
        )
        db.session.commit()

    with sync_playwright() as playwright_session:
        try:
            browser = playwright_session.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(f"{live_server}/login")
            login_form = page.locator("form").filter(has=page.locator('input[name="password"]'))
            login_form.locator('input[name="email"]').fill("student1@student.mmu.edu.my")
            login_form.locator('input[name="password"]').fill("CorrectHorse1")
            login_form.locator('input[name="password"]').press("Enter")
            page.wait_for_url("**/appointment")

            bell = page.locator(".app-notification-menu > summary")
            bell.click()
            page.keyboard.press("Escape")
            assert page.locator(".app-notification-menu").evaluate("el => !el.open")
            assert bell.evaluate("el => el === document.activeElement")
            bell.click()
            page.get_by_role("link", name="View all notifications").click()
            assert "Appointment accepted" in page.locator("main").inner_text()
            page.get_by_role("button", name="View appointment").click()
            page.wait_for_url(f"**/invoice?reference={appointment.public_reference}")

            page.goto(f"{live_server}/profile")
            email_updates = page.locator('input[name="email_updates"]')
            reminder_24h = page.locator('input[name="reminder_24h"]')
            reminder_1h = page.locator('input[name="reminder_1h"]')
            assert email_updates.is_checked() and reminder_24h.is_checked() and reminder_1h.is_checked()
            reminder_24h.uncheck()
            page.get_by_role("button", name="Save email preferences").click()
            assert not page.locator('input[name="reminder_24h"]').is_checked()

            theme = page.locator("#uas-theme")
            for selected in ("light", "dark", "system"):
                theme.select_option(selected)
                assert page.locator("html").get_attribute("data-theme") == selected
                assert page.evaluate("localStorage.getItem('uas-theme')") == selected
            for width in (360, 390, 768, 1024, 1280, 1440):
                page.set_viewport_size({"width": width, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        finally:
            browser.close()


def test_public_auth_pages_csp_labels_and_portrait_landscape_layout(app, live_server):
    with sync_playwright() as playwright_session:
        try:
            browser = playwright_session.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            js_errors = []
            console_errors = []
            local_asset_errors = []
            failed_asset_responses = []
            font_css_responses = []
            page.add_init_script("""
                window.__uasCspViolations = [];
                document.addEventListener('securitypolicyviolation', (event) => {
                    window.__uasCspViolations.push({directive: event.violatedDirective, blocked: event.blockedURI});
                });
            """)
            page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: js_errors.append(str(error)))
            page.on("response", lambda response: local_asset_errors.append(response.url) if response.url.startswith(live_server) and response.status >= 400 else None)
            page.on("response", lambda response: failed_asset_responses.append((response.url, response.status, response.request.resource_type)) if response.status >= 400 else None)
            page.on("response", lambda response: font_css_responses.append((response.status, response.headers.get("content-type", ""))) if "cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" in response.url else None)

            response = page.goto(f"{live_server}/")
            assert response and "default-src 'self'" in response.headers.get("content-security-policy", "")
            assert page.get_by_role("heading", name="University Appointment System", level=1).is_visible()

            for path in ("/", "/login", "/signup", "/password-reset"):
                page.goto(f"{live_server}{path}")
                assert page.locator("h1").count() == 1, f"expected one page heading on {path}"
                for width in (320, 360, 390, 430, 768, 820, 1024, 1280, 1440, 1920):
                    page.set_viewport_size({"width": width, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"{path} overflows at {width}px"
                page.set_viewport_size({"width": 844, "height": 390})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"{path} overflows in landscape"

            page.goto(f"{live_server}/login")
            assert page.locator("#login-email").evaluate("element => element.labels.length > 0")
            assert page.locator("#passwordField").evaluate("element => element.labels.length > 0")
            page.goto(f"{live_server}/signup")
            page.get_by_label("Student", exact=True).check()
            assert page.get_by_label("Full name").is_visible()
            assert page.locator('input[name="username"]').evaluate("element => element.labels.length > 0")
            page.locator("#uas-theme").select_option("dark")
            page.goto(f"{live_server}/login")
            assert page.locator("html").get_attribute("data-theme") == "dark"
            page.locator("#uas-theme").select_option("system")
            page.emulate_media(color_scheme="dark")
            assert page.evaluate("getComputedStyle(document.documentElement).colorScheme === 'dark'")
            assert page.evaluate("window.__uasCspViolations") == []
            assert js_errors == []
            assert console_errors == [], {"console": console_errors, "failed_assets": failed_asset_responses, "font_css": font_css_responses}
            assert failed_asset_responses == []
            assert local_asset_errors == []
            assert font_css_responses and all(
                status in {200, 304} and "text/css" in content_type
                for status, content_type in font_css_responses
            ), font_css_responses
        finally:
            browser.close()

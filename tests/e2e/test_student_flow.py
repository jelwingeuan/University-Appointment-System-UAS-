from datetime import datetime
from threading import Thread
from zoneinfo import ZoneInfo

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from uas.extensions import db
from uas.models import User


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

            for width in (360, 390, 768, 1024, 1280, 1440):
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

            page.goto(f"{live_server}/calendar")
            assert "Access denied" in page.locator("main").inner_text()
            page.goto(f"{live_server}/admin")
            assert "Access denied" in page.locator("main").inner_text()
        finally:
            browser.close()

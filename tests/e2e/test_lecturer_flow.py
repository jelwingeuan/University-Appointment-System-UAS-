from datetime import datetime, timedelta
from threading import Thread

import pytest
from werkzeug.serving import make_server

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright

from uas.extensions import db
from uas.models import Appointment, NotificationType
from uas.notification_service import create_notification


@pytest.fixture
def lecturer_live_server(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=3)


def login_lecturer(page, base_url):
    page.goto(f"{base_url}/login")
    login_form = page.locator("form").filter(has=page.locator('input[name="password"]'))
    email = login_form.locator('input[name="email"]')
    password = login_form.locator('input[name="password"]')
    email.fill("lecturer1@mmu.edu.my")
    password.fill("CorrectHorse1")
    password.press("Enter")
    expect(page).to_have_url(f"{base_url}/")


def open_lecturer_home_from_public_navigation(page, base_url):
    page.locator(".public-role-menu summary").click()
    page.locator(".public-role-menu").get_by_role("link", name="Home", exact=True).click()
    expect(page).to_have_url(f"{base_url}/lecturer")


def test_lecturer_can_review_accept_and_reject_requests(
    app, lecturer_live_server, appointment_factory
):
    accepted_request = appointment_factory(purpose="Discuss course selection")
    rejected_request = appointment_factory(
        starts_at=datetime.fromisoformat(app.config["TEST_SLOT_START"]) + timedelta(minutes=30),
        purpose="Review a research proposal",
    )

    with sync_playwright() as playwright_session:
        try:
            browser = playwright_session.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            login_lecturer(page, lecturer_live_server)
            open_lecturer_home_from_public_navigation(page, lecturer_live_server)
            page.get_by_role("link", name="Requests", exact=True).click()
            accepted_card = page.locator(".lecturer-request-card").filter(has_text="Discuss course selection")
            accepted_card.get_by_role("button", name="Accept").click()
            expect(page.get_by_role("status").filter(has_text="Appointment accepted")).to_be_visible()
            expect(page.locator(".lecturer-request-card").filter(has_text="Discuss course selection")).to_have_count(0)

            rejected_card = page.locator(".lecturer-request-card").filter(has_text="Review a research proposal")
            reject_button = rejected_card.get_by_role("button", name="Reject")
            reject_button.click()
            dialog = page.get_by_role("dialog", name="Reject this request?")
            expect(dialog).to_be_visible()
            expect(dialog).to_contain_text("Student One")
            page.keyboard.press("Escape")
            expect(dialog).not_to_be_visible()
            expect(reject_button).to_be_focused()
            reject_button.click()
            expect(dialog).to_be_visible()
            dialog.get_by_role("button", name="Reject request").click()
            expect(page.get_by_role("status").filter(has_text="Appointment rejected")).to_be_visible()
            expect(page.locator(".lecturer-request-card").filter(has_text="Review a research proposal")).to_have_count(0)
        finally:
            browser.close()

    with app.app_context():
        assert db.session.get(Appointment, accepted_request.id).status == "Accepted"
        assert db.session.get(Appointment, rejected_request.id).status == "Rejected"


def test_lecturer_can_open_private_request_notification(app, lecturer_live_server, appointment_factory):
    appointment = appointment_factory(purpose="A private request purpose")
    with app.app_context():
        row = db.session.get(Appointment, appointment.id)
        create_notification(
            db.session,
            user_id=row.lecturer_id,
            appointment=row,
            notification_type=NotificationType.APPOINTMENT_REQUESTED.value,
            deduplication_key=f"e2e-lecturer-request:{row.id}",
            title="New appointment request",
            message="A student requested an appointment.",
        )
        db.session.commit()

    with sync_playwright() as playwright_session:
        try:
            browser = playwright_session.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            login_lecturer(page, lecturer_live_server)
            open_lecturer_home_from_public_navigation(page, lecturer_live_server)
            bell = page.locator(".app-notification-menu > summary")
            bell.click()
            page.get_by_role("link", name="View all notifications").click()
            assert "New appointment request" in page.locator("main").inner_text()
            page.get_by_role("button", name="View appointment").click()
            expect(page).to_have_url(
                f"{lecturer_live_server}/lecturer/appointments/{appointment.public_reference}"
            )
            assert "A private request purpose" in page.locator("main").inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        finally:
            browser.close()


def test_lecturer_detail_confirms_completion_and_no_show(
    app, lecturer_live_server, appointment_factory
):
    completed = appointment_factory(status="Accepted", purpose="Completion flow appointment")
    no_show = appointment_factory(
        starts_at=datetime.fromisoformat(app.config["TEST_SLOT_START"]) + timedelta(minutes=30),
        status="Accepted",
        purpose="No-show flow appointment",
    )

    with sync_playwright() as playwright_session:
        try:
            browser = playwright_session.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            login_lecturer(page, lecturer_live_server)
            page.goto(f"{lecturer_live_server}/lecturer/appointments/{completed.public_reference}")
            page.get_by_role("button", name="Mark as completed").click()
            completion_dialog = page.get_by_role("dialog", name="Mark as completed?")
            expect(completion_dialog).to_be_visible()
            completion_dialog.get_by_role("button", name="Mark as completed", exact=True).click()
            expect(page.get_by_text("Completed", exact=True)).to_be_visible()
            expect(page.get_by_role("status").filter(has_text="Appointment marked as completed")).to_be_visible()

            page.goto(f"{lecturer_live_server}/lecturer/appointments/{no_show.public_reference}")
            page.get_by_role("button", name="Mark as no show").click()
            no_show_dialog = page.get_by_role("dialog", name="Mark as no show?")
            expect(no_show_dialog).to_contain_text("cannot be reopened")
            no_show_dialog.get_by_role("button", name="Mark as no show", exact=True).click()
            expect(page.get_by_text("No Show", exact=True)).to_be_visible()
            expect(page.get_by_role("status").filter(has_text="Appointment marked as no show")).to_be_visible()
        finally:
            browser.close()

    with app.app_context():
        assert db.session.get(Appointment, completed.id).status == "Completed"
        assert db.session.get(Appointment, no_show.id).status == "No Show"


def test_lecturer_can_add_reject_overlap_and_remove_availability(
    app, lecturer_live_server
):
    with sync_playwright() as playwright_session:
        try:
            browser = playwright_session.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            login_lecturer(page, lecturer_live_server)
            page.goto(f"{lecturer_live_server}/calendar")
            expect(page.locator(".fc")).to_be_visible()
            page.get_by_role("button", name="Add availability").click()
            dialog = page.get_by_role("dialog", name="Add availability")
            dialog.locator("#eventDate").fill("2026-10-02")
            dialog.locator("#startTime").fill("09:00")
            dialog.locator("#endTime").fill("10:00")
            dialog.locator("#slot_size").fill("30")
            dialog.get_by_role("button", name="Save availability").click()
            expect(page.get_by_role("status").filter(has_text="Availability added")).to_be_visible()
            expect(page.get_by_text("Availability", exact=False).first).to_be_visible()

            page.get_by_role("button", name="Add availability").click()
            conflict = page.get_by_role("dialog", name="Add availability")
            conflict.locator("#eventDate").fill("2026-10-02")
            conflict.locator("#startTime").fill("09:30")
            conflict.locator("#endTime").fill("10:30")
            conflict.locator("#slot_size").fill("30")
            conflict.get_by_role("button", name="Save availability").click()
            expect(page.get_by_role("alert").filter(has_text="overlaps an existing availability window")).to_be_visible()

            page.get_by_role("button", name="Remove availability").click()
            delete_dialog = page.get_by_role("dialog", name="Remove this availability?")
            expect(delete_dialog).to_be_visible()
            delete_dialog.get_by_role("button", name="Remove availability", exact=True).click()
            expect(page.get_by_role("status").filter(has_text="Availability removed")).to_be_visible()
        finally:
            browser.close()


def test_mobile_lecturer_can_open_request_and_accept_from_detail(
    app, lecturer_live_server, appointment_factory
):
    appointment = appointment_factory(purpose="Mobile request workflow")

    with sync_playwright() as playwright_session:
        try:
            browser = playwright_session.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.add_init_script("""
                window.__uasCspViolations = [];
                document.addEventListener('securitypolicyviolation', (event) => {
                    window.__uasCspViolations.push({directive: event.violatedDirective, blocked: event.blockedURI});
                });
            """)
            login_lecturer(page, lecturer_live_server)
            open_lecturer_home_from_public_navigation(page, lecturer_live_server)
            drawer_button = page.get_by_role("button", name="Open application navigation")
            drawer_button.click()
            drawer = page.get_by_role("dialog", name="Navigation")
            expect(drawer).to_be_visible()
            page.keyboard.press("Escape")
            expect(drawer).not_to_be_visible()
            expect(drawer_button).to_be_focused()
            drawer_button.click()
            drawer.get_by_role("link", name="Requests").click()
            request = page.locator(".lecturer-request-card").filter(has_text="Mobile request workflow")
            request.get_by_role("link", name="View details").click()
            expect(page).to_have_url(f"{lecturer_live_server}/lecturer/appointments/{appointment.public_reference}")
            page.get_by_role("button", name="Accept").click()
            expect(page.get_by_role("status").filter(has_text="Appointment accepted")).to_be_visible()
            expect(page.get_by_text("Accepted", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        finally:
            browser.close()


def test_lecturer_pages_fit_supported_widths_and_theme_choices(
    lecturer_live_server,
):
    with sync_playwright() as playwright_session:
        try:
            browser = playwright_session.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            console_errors = []
            page_errors = []
            page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.add_init_script("""
                window.__uasCspViolations = [];
                document.addEventListener('securitypolicyviolation', (event) => {
                    window.__uasCspViolations.push({directive: event.violatedDirective, blocked: event.blockedURI});
                });
            """)
            login_lecturer(page, lecturer_live_server)
            open_lecturer_home_from_public_navigation(page, lecturer_live_server)
            theme = page.get_by_label("Appearance")
            for choice in ("light", "dark", "system"):
                theme.select_option(choice)
                expect(page.locator("html")).to_have_attribute("data-theme", choice)
            page.emulate_media(reduced_motion="reduce")
            assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")

            for width in (320, 360, 390, 430, 768, 820, 1024, 1280, 1440, 1920):
                page.set_viewport_size({"width": width, "height": 900})
                page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"dashboard overflows at {width}px"

            page.goto(f"{lecturer_live_server}/calendar")
            if not page.locator(".fc").count():
                debug = page.evaluate("""() => ({
                    fullCalendar: typeof window.FullCalendar,
                    csp: window.__uasCspViolations,
                    scripts: [...document.scripts].map(script => ({src: script.src, readyState: script.readyState})),
                    body: document.body.innerText.slice(0, 400),
                })""")
                raise AssertionError(f"FullCalendar did not initialize: {debug}; console={console_errors}; page_errors={page_errors}")
            expect(page.locator(".fc")).to_be_visible()
            for width in (320, 360, 390, 430, 768, 820, 1024, 1280, 1440, 1920):
                page.set_viewport_size({"width": width, "height": 900})
                page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                dimensions = page.evaluate("""() => ({
                    viewport: window.innerWidth,
                    scroll: document.documentElement.scrollWidth,
                    accountOpen: document.querySelector('.app-account-menu')?.open,
                    topbar: document.querySelector('.app-topbar')?.getBoundingClientRect().toJSON(),
                    topbarTools: document.querySelector('.app-topbar-tools')?.getBoundingClientRect().toJSON(),
                    topbarChildren: [...document.querySelector('.app-topbar-tools').children].map((element) => ({className: String(element.className), rect: element.getBoundingClientRect().toJSON()})),
                    accountRect: document.querySelector('.app-account-menu')?.getBoundingClientRect().toJSON(),
                    offenders: [...document.querySelectorAll('body *')].map((element) => {
                        const rect = element.getBoundingClientRect();
                        return {tag: element.tagName, className: String(element.className), left: rect.left, right: rect.right, width: rect.width};
                    }).filter((element) => element.right > window.innerWidth + 1 || element.left < -1).slice(0, 12),
                })""")
                assert dimensions["scroll"] <= width, f"calendar overflows at {width}px: {dimensions}"
            page.set_viewport_size({"width": 844, "height": 390})
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "calendar overflows in landscape"
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(f"{lecturer_live_server}/profile")
            profile_trigger = page.get_by_role("button", name="Edit profile")
            profile_trigger.click()
            profile_dialog = page.get_by_role("dialog", name="Edit profile")
            expect(profile_dialog).to_be_visible()
            page.keyboard.press("Escape")
            expect(profile_dialog).not_to_be_visible()
            expect(profile_trigger).to_be_focused()
            profile_trigger.click()
            page.get_by_role("button", name="Close profile editor").click()
            expect(profile_dialog).not_to_be_visible()
            expect(profile_trigger).to_be_focused()
            assert page.evaluate("window.__uasCspViolations") == []
            assert console_errors == []
            assert page_errors == []
            assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
        finally:
            browser.close()

from statistics import median
from time import perf_counter

from flask import g
from sqlalchemy import event

from tests.conftest import login
from uas.extensions import db


def test_representative_page_query_counts_stay_bounded(client, app):
    with app.app_context():
        engine = db.engine
        measurements = []

        def measure(path, *, json_response=False):
            db.session.remove()
            # The app fixture keeps one app context pushed for the test. Clear
            # Flask-Login's per-app-context cache along with the ORM session so
            # each request measures a fresh database-backed user load.
            g.pop("_login_user", None)
            statements = 0

            def count_statement(_connection, _cursor, _statement, _parameters, _context, _executemany):
                nonlocal statements
                statements += 1

            event.listen(engine, "before_cursor_execute", count_statement)
            started = perf_counter()
            try:
                headers = {"Accept": "application/json"} if json_response else None
                response = client.get(path, headers=headers)
            finally:
                elapsed_ms = (perf_counter() - started) * 1000
                event.remove(engine, "before_cursor_execute", count_statement)
            assert response.status_code == 200, f"{path} returned {response.status_code}"
            measurements.append((path, statements, elapsed_ms))

        measure("/")
        measure("/login")

        login(client, "student1@student.mmu.edu.my")
        measure("/appointment2")
        measure("/bookinghistory")
        client.post("/logout")

        login(client, "lecturer1@mmu.edu.my")
        measure("/lecturer")
        measure("/lecturer/requests")
        measure("/bookinghistory")
        measure("/calendar")
        measure("/events", json_response=True)
        client.post("/logout")

        login(client, "admin@mmu.edu.my")
        for path in (
            "/admin",
            "/usercontrol",
            "/appointmentcontrol",
            "/faculty",
            "/adminpageeditor",
            "/admin/audit-log",
        ):
            measure(path)

        assert max(count for _, count, _ in measurements) < 50
        summary = "\n".join(
            f"{path}: {count} SQL statements, {elapsed:.1f} ms"
            for path, count, elapsed in measurements
        )
        print(f"Representative page query/time baseline (median {median(t for _, _, t in measurements):.1f} ms):\n{summary}")

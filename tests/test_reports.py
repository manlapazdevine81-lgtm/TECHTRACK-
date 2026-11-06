"""Phase 9 — Reports (CSV exports): content, headers, filters, empty results,
authorization, and error cases. Runs against `techis_test` via the shared
fixtures in tests/conftest.py.
"""
import csv
import io
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.activity import Activity, ActivityRegistration, AttendanceRecord
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, ROLE_PARTICIPANT
from app.services import report_service

from .conftest import login

PW = "Passw0rd!"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ACCOUNTS = (
    ("admin", ROLE_ADMIN, "admin@rp.demo", "Admin User"),
    ("officer", ROLE_OFFICER, "off@rp.demo", "Officer User"),
    ("adviser", ROLE_ADVISER, "adv@rp.demo", "Adviser User"),
    ("p1", ROLE_PARTICIPANT, "p1@rp.demo", "Juan Dela Cruz"),
    ("p2", ROLE_PARTICIPANT, "p2@rp.demo", "Maria Santos"),
)


def _users(app, make_user) -> dict:
    from app.models.user import User

    for _key, role, email, name in _ACCOUNTS:
        make_user(role, email=email, password=PW, full_name=name)
    with app.app_context():
        return {u.email: u.id for u in User.query.all()}


def _user(app, make_user, role, email, name, student_id=None) -> int:
    make_user(role, email=email, password=PW, full_name=name, student_id=student_id)
    from app.models.user import User

    with app.app_context():
        return User.query.filter_by(email=email).first().id


def _activity(app, created_by, *, title="Event", status="published", start=None,
              activity_type=None) -> int:
    start = start or datetime.now(timezone.utc) + timedelta(days=1)
    with app.app_context():
        a = Activity(
            title=title,
            activity_type=activity_type,
            start_datetime=start,
            end_datetime=start + timedelta(hours=2),
            status=status,
            created_by=created_by,
        )
        db.session.add(a)
        db.session.commit()
        return a.id


def _register(app, activity_id, user_id, status="registered") -> int:
    with app.app_context():
        r = ActivityRegistration(
            activity_id=activity_id,
            user_id=user_id,
            status=status,
            registration_date=datetime(2026, 8, 1, 8, 30, tzinfo=timezone.utc),
        )
        db.session.add(r)
        db.session.commit()
        return r.id


def _attend(app, activity_id, user_id, status, recorded_by, registration_id=None,
            time_in=None, remarks=None) -> None:
    with app.app_context():
        db.session.add(AttendanceRecord(
            activity_id=activity_id,
            user_id=user_id,
            registration_id=registration_id,
            attendance_status=status,
            time_in=time_in,
            remarks=remarks,
            recorded_by=recorded_by,
            recorded_at=datetime(2026, 8, 1, 9, 5, tzinfo=timezone.utc),
        ))
        db.session.commit()


def _csv_rows(resp) -> list[list[str]]:
    """Decode a CSV download (stripping the BOM) into rows of cells."""
    text = resp.get_data(as_text=True)
    assert text.startswith("\ufeff")
    return list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))


def _seed(app, make_user) -> dict:
    """Two activities in different school years with mixed data."""
    users = _users(app, make_user)
    admin = users["admin@rp.demo"]
    old = _activity(app, admin, title="Old Event",
                    start=datetime(2024, 7, 15, 9, 0, tzinfo=timezone.utc))
    new = _activity(app, admin, title="New Event",
                    activity_type="Workshop",
                    start=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc))
    r1 = _register(app, new, users["p1@rp.demo"])
    r2 = _register(app, new, users["p2@rp.demo"])
    _register(app, new, users["off@rp.demo"])
    _register(app, new, users["adv@rp.demo"], status="cancelled")
    _register(app, old, users["p1@rp.demo"])
    _attend(app, new, users["p1@rp.demo"], "present", admin, registration_id=r1,
            time_in=datetime(2026, 8, 10, 9, 2, tzinfo=timezone.utc))
    _attend(app, new, users["p2@rp.demo"], "late", admin, registration_id=r2,
            time_in=datetime(2026, 8, 10, 9, 20, tzinfo=timezone.utc))
    # Walk-in: attendance without a registration row.
    walk = _user(app, make_user, ROLE_PARTICIPANT, "walk@rp.demo", "Walk In")
    _attend(app, new, walk, "present", admin)
    return {"users": users, "old": old, "new": new, "walk": walk}


@pytest.fixture()
def seeded(app, client, make_user):
    return _seed(app, make_user)


# ---------------------------------------------------------------------------
# Report catalogue page
# ---------------------------------------------------------------------------


def test_report_page_lists_all_confirmed_reports(app, client, seeded):
    login(client, "admin@rp.demo", PW)
    resp = client.get("/reports")
    assert resp.status_code == 200
    for label in (b"Attendance", b"Participation", b"Activity summary", b"Registrations"):
        assert label in resp.data
    assert b"T13" in resp.data            # PDF status is stated, not implied
    assert b"/reports/attendance.csv" in resp.data


def test_report_page_applies_filters_to_links(app, client, seeded):
    login(client, "admin@rp.demo", PW)
    resp = client.get(f"/reports?activity_id={seeded['new']}&academic_year=2026-2027")
    assert resp.status_code == 200
    assert (
        f"/reports/participation.csv?activity_id={seeded['new']}&academic_year=2026-2027"
    ).encode() in resp.data


def test_report_page_empty_database(app, client, make_user):
    _users(app, make_user)
    login(client, "admin@rp.demo", PW)
    resp = client.get("/reports")
    assert resp.status_code == 200
    assert b"No activities exist yet" in resp.data


# ---------------------------------------------------------------------------
# Attendance report
# ---------------------------------------------------------------------------


def test_attendance_report_headers_and_content(app, client, seeded):
    login(client, "admin@rp.demo", PW)
    resp = client.get("/reports/attendance.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert resp.headers["Content-Disposition"].startswith(
        'attachment; filename="attendance_report_'
    )
    assert resp.headers["Content-Disposition"].endswith('.csv"')
    assert resp.headers["X-Content-Type-Options"] == "nosniff"

    rows = _csv_rows(resp)
    header, body = rows[0], rows[1:]
    assert header == [
        "Activity", "Activity Status", "Activity Date", "Participant",
        "Email", "Student ID", "Role", "Attendance Status",
        "Time In (UTC)", "Time Out (UTC)", "Registration Linked", "Remarks",
        "Recorded At (UTC)",
    ]
    assert len(body) == 3
    juan = next(r for r in body if r[3] == "Juan Dela Cruz")
    assert juan[0] == "New Event"
    assert juan[1] == "published"
    assert juan[2] == "2026-08-10 09:00:00"        # ISO-8601 UTC text
    assert juan[4] == "p1@rp.demo"
    assert juan[7] == "present"
    assert juan[8] == "2026-08-10 09:02:00"
    assert juan[9] == ""                            # missing time out -> blank
    assert juan[10] == "Yes"
    assert juan[12] == "2026-08-01 09:05:00"
    walkin = next(r for r in body if r[3] == "Walk In")
    assert walkin[10] == "No"                       # no registration link


def test_attendance_report_omits_contact_for_adviser(app, client, seeded):
    login(client, "adv@rp.demo", PW)
    rows = _csv_rows(client.get("/reports/attendance.csv"))
    assert "Email" not in rows[0]
    assert "Student ID" not in rows[0]
    assert rows[0][3] == "Participant"
    assert all("p1@rp.demo" not in row for row in rows)


def test_attendance_report_includes_contact_for_officer(app, client, seeded):
    login(client, "off@rp.demo", PW)
    rows = _csv_rows(client.get("/reports/attendance.csv"))
    assert "Email" in rows[0]
    assert any("p1@rp.demo" in row for row in rows)


# ---------------------------------------------------------------------------
# Participation report (must match Phase 8 numbers)
# ---------------------------------------------------------------------------


def test_participation_report_matches_phase8_dashboard(app, client, seeded):
    from app.services import general_analytics_service as ga

    login(client, "admin@rp.demo", PW)
    rows = _csv_rows(client.get("/reports/participation.csv"))
    header = rows[0]
    by_title = {row[1]: dict(zip(header, row)) for row in rows[1:]}

    with app.app_context():
        data = ga.build_general_dashboard()
    detail = {row["title"]: row for row in data["detail"]}

    assert by_title["New Event"]["Active Registrations"] == str(detail["New Event"]["registered"])
    assert by_title["New Event"]["Attendance Rows"] == str(detail["New Event"]["attendance_rows"])
    assert by_title["New Event"]["Walk-ins"] == "1"
    # 3 attendance rows / 3 active registrations = 100.0
    assert by_title["New Event"]["Conversion (%)"] == "100.0"
    assert by_title["New Event"]["School Year"] == "2026-2027"
    # "Old Event" has 1 registration and 0 attendance: a real denominator, so
    # 0.0 is correct here (blank is only for a zero denominator).
    assert by_title["Old Event"]["Active Registrations"] == "1"
    assert by_title["Old Event"]["Conversion (%)"] == "0.0"
    assert by_title["Old Event"]["Attendance Rate (%)"] == ""   # 0 of 0 rows


def test_participation_report_has_no_nan(app, client, seeded):
    login(client, "admin@rp.demo", PW)
    text = client.get("/reports/participation.csv").get_data(as_text=True).lower()
    assert "nan" not in text


def test_participation_untyped_activity_writes_empty_cell(app, client, make_user):
    """An untyped activity exports a blank Type cell (never nan, never "None").

    Pandas stores None in long-text cells as NaN, so the service normalizes it
    before writing; this asserts the exported cell and the literal text.
    """
    users = _users(app, make_user)
    _activity(app, users["admin@rp.demo"], title="No Type Set")  # activity_type=None
    login(client, "admin@rp.demo", PW)

    resp = client.get("/reports/participation.csv")
    rows = _csv_rows(resp)
    header = rows[0]
    row = rows[1]
    assert row[1] == "No Type Set"
    assert row[header.index("Type")] == ""
    text = resp.get_data(as_text=True).lower()
    assert "nan" not in text
    assert "none" not in text


# ---------------------------------------------------------------------------
# Activities report
# ---------------------------------------------------------------------------


def test_activities_report_rows_and_total(app, client, seeded):
    login(client, "admin@rp.demo", PW)
    rows = _csv_rows(client.get("/reports/activities.csv"))
    header, body = rows[0], rows[1:]
    assert header[0] == "Activity ID"
    assert "Conversion (%)" in header
    activities = [r for r in body if r[1] != "TOTAL"]
    total = body[-1]
    assert [r[1] for r in activities] == ["Old Event", "New Event"]
    assert total[1] == "TOTAL"
    # 4 active registrations across both activities (1 old + 3 new).
    assert total[header.index("Active Registrations")] == "4"
    assert total[header.index("Cancelled Registrations")] == "1"
    # 3 attendance rows / 4 registrations = 75.0
    assert total[header.index("Conversion (%)")] == "75.0"


# ---------------------------------------------------------------------------
# Registrations report
# ---------------------------------------------------------------------------


def test_registrations_report_status_and_attendance_join(app, client, seeded):
    login(client, "admin@rp.demo", PW)
    rows = _csv_rows(client.get("/reports/registrations.csv"))
    header, body = rows[0], rows[1:]
    assert "Registration Status" in header
    assert "Attendance Status" in header
    assert len(body) == 5                       # every registration row

    cancelled = [r for r in body if r[header.index("Registration Status")] == "cancelled"]
    assert len(cancelled) == 1
    juan_new = next(
        r for r in body
        if r[1] == "New Event" and r[4] == "Juan Dela Cruz"
    )
    assert juan_new[header.index("Attendance Status")] == "present"
    assert juan_new[header.index("Registered At (UTC)")] == "2026-08-01 08:30:00"


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_activity_filter_limits_exports(app, client, seeded):
    login(client, "admin@rp.demo", PW)
    rows = _csv_rows(client.get(f"/reports/registrations.csv?activity_id={seeded['old']}"))
    body = rows[1:]
    assert body
    assert {r[1] for r in body} == {"Old Event"}


def test_academic_year_filter_limits_exports(app, client, seeded):
    login(client, "admin@rp.demo", PW)
    # 2024-07-15 -> AY 2024-2025 (Old Event, no attendance rows).
    in_year = _csv_rows(client.get("/reports/participation.csv?academic_year=2024-2025"))
    assert {r[1] for r in in_year[1:]} == {"Old Event"}
    other = _csv_rows(client.get("/reports/participation.csv?academic_year=2026-2027"))
    assert {r[1] for r in other[1:]} == {"New Event"}
    # Attendance exists only for 2026-2027.
    att = _csv_rows(client.get("/reports/attendance.csv?academic_year=2024-2025"))
    assert len(att) == 1, "header only: no attendance rows in that school year"


def test_filename_records_applied_filters(app, client, seeded):
    login(client, "admin@rp.demo", PW)
    resp = client.get(f"/reports/participation.csv?activity_id={seeded['new']}&academic_year=2026-2027")
    disposition = resp.headers["Content-Disposition"]
    assert f"activity{seeded['new']}" in disposition
    assert "ay2026-2027" in disposition


@pytest.mark.parametrize("query", [
    "activity_id=abc",
    "activity_id=999999",
    "academic_year=not-a-year",
    "academic_year=1999-2000",
    "academic_year=2025-2027",
])
def test_invalid_filters_fall_back_and_report(app, client, seeded, query):
    login(client, "admin@rp.demo", PW)
    resp = client.get(f"/reports/attendance.csv?{query}")
    assert resp.status_code == 200
    rows = _csv_rows(resp)
    assert len(rows) - 1 == 3           # all rows exported, not an empty file
    # The ignored-filter notice is flashed (rendered on the next HTML page).
    page = client.get("/reports")
    assert b"ignored" in page.data.lower()


# ---------------------------------------------------------------------------
# Empty results
# ---------------------------------------------------------------------------


def test_empty_database_exports_header_only(app, client, make_user):
    _users(app, make_user)
    login(client, "admin@rp.demo", PW)
    for key in ("attendance", "participation", "activities", "registrations"):
        resp = client.get(f"/reports/{key}.csv")
        assert resp.status_code == 200
        rows = _csv_rows(resp)
        assert len(rows) == 1, f"{key} should be header-only"
        assert rows[0]


def test_activity_with_no_participation_is_blank_not_zero(app, client, make_user):
    """An activity with 0 registrations exports blanks, never 0.0 or nan."""
    users = _users(app, make_user)
    _activity(app, users["admin@rp.demo"], title="Nothing Yet")
    login(client, "admin@rp.demo", PW)

    rows = _csv_rows(client.get("/reports/participation.csv"))
    header, body = rows[0], rows[1:]
    assert len(body) == 1
    assert body[0][header.index("Active Registrations")] == "0"
    assert body[0][header.index("Conversion (%)")] == ""
    assert body[0][header.index("Attendance Rate (%)")] == ""

    acts = _csv_rows(client.get("/reports/activities.csv"))
    a_header = acts[0]
    total = acts[-1]
    assert total[a_header.index("Conversion (%)")] == ""   # 0 of 0 -> blank
    assert "nan" not in "".join(sum(acts, [])).lower()


# ---------------------------------------------------------------------------
# Authorization and error cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("email", ["admin@rp.demo", "off@rp.demo", "adv@rp.demo"])
def test_staff_can_open_reports_and_export(app, client, seeded, email):
    login(client, email, PW)
    assert client.get("/reports").status_code == 200
    assert client.get("/reports/attendance.csv").status_code == 200


def test_participant_cannot_view_or_export(app, client, seeded):
    login(client, "p1@rp.demo", PW)
    assert client.get("/reports").status_code == 403
    for key in ("attendance", "participation", "activities", "registrations"):
        assert client.get(f"/reports/{key}.csv").status_code == 403


def test_participant_sidebar_hides_reports(app, client, seeded):
    login(client, "p1@rp.demo", PW)
    assert b"/reports" not in client.get("/dashboard").data


def test_anonymous_cannot_export(app, client, seeded):
    resp = client.get("/reports/attendance.csv")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_unknown_report_is_404(app, client, seeded):
    login(client, "admin@rp.demo", PW)
    assert client.get("/reports/nope.csv").status_code == 404


def test_report_path_traversal_rejected(app, client, seeded):
    login(client, "admin@rp.demo", PW)
    # The key is a path segment matched against the registry — never a file path.
    assert client.get("/reports/..%2f..%2fetc%2fpasswd.csv").status_code == 404


# ---------------------------------------------------------------------------
# Injection / formatting safety in real exports
# ---------------------------------------------------------------------------


def test_formula_injection_is_neutralized_in_export(app, client, make_user):
    users = _users(app, make_user)
    admin = users["admin@rp.demo"]
    act = _activity(app, admin, title="=HYPERLINK(\"http://evil\",\"x\")")
    _register(app, act, users["p1@rp.demo"])
    _attend(app, act, users["p1@rp.demo"], "present", admin,
            remarks="@SUM(A1:A9)")

    login(client, "admin@rp.demo", PW)
    rows = _csv_rows(client.get("/reports/attendance.csv"))
    header = rows[0]
    row = rows[1]
    assert row[0].startswith("'=")                 # title neutralized
    assert row[header.index("Remarks")].startswith("'@")


def test_commas_and_quotes_round_trip(app, client, make_user):
    users = _users(app, make_user)
    admin = users["admin@rp.demo"]
    act = _activity(app, admin, title='Planning, "Q3" meeting')
    _register(app, act, users["p1@rp.demo"])
    login(client, "admin@rp.demo", PW)
    rows = _csv_rows(client.get("/reports/participation.csv"))
    assert rows[1][1] == 'Planning, "Q3" meeting'   # parsed back intact


# ---------------------------------------------------------------------------
# Service-level unit checks (no HTTP)
# ---------------------------------------------------------------------------


def test_resolve_filters_drops_unknown_activity(app, client, seeded):
    with app.app_context():
        filters = report_service.resolve_filters({"activity_id": "999999"})
    assert filters["activity_id"] is None
    assert filters["errors"]


def test_can_see_participant_contact_by_role():
    assert report_service.can_see_participant_contact(ROLE_ADMIN)
    assert report_service.can_see_participant_contact(ROLE_OFFICER)
    # Adviser is read-only and does not get participant contact details.
    assert not report_service.can_see_participant_contact(ROLE_ADVISER)
    assert not report_service.can_see_participant_contact(ROLE_PARTICIPANT)


def test_every_registered_report_builds(app, client, seeded):
    """The registry and the route stay in sync."""
    login(client, "admin@rp.demo", PW)
    for key in report_service.REPORTS:
        assert client.get(f"/reports/{key}.csv").status_code == 200

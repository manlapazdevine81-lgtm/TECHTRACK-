"""Phase 8 — General Analytics (Pandas): calculations, denominators, filters,
permissions, and empty data. Runs against the PostgreSQL `techis_test` DB via
the shared fixtures in tests/conftest.py.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.extensions import db
from app.models.activity import Activity, ActivityRegistration, AttendanceRecord
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, ROLE_PARTICIPANT
from app.services import general_analytics_service as svc

from .conftest import login

PW = "Passw0rd!"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dt(days: int = 1) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _user(app, make_user, role, email, name):
    make_user(role, email=email, password=PW, full_name=name)
    from app.models.user import User
    with app.app_context():
        return User.query.filter_by(email=email).first().id


def _activity(app, created_by: int, *, title="Event", status="published",
              start=None, activity_type=None) -> int:
    start = start or _dt()
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


def _register(app, activity_id: int, user_id: int, status="registered") -> int:
    with app.app_context():
        r = ActivityRegistration(
            activity_id=activity_id,
            user_id=user_id,
            status=status,
            registration_date=_dt(),
        )
        db.session.add(r)
        db.session.commit()
        return r.id


def _attend(app, activity_id: int, user_id: int, status: str, recorded_by: int,
            registration_id=None) -> None:
    with app.app_context():
        db.session.add(AttendanceRecord(
            activity_id=activity_id,
            user_id=user_id,
            registration_id=registration_id,
            attendance_status=status,
            recorded_by=recorded_by,
            recorded_at=_dt(),
        ))
        db.session.commit()


_ACCOUNTS = (
    ("admin", ROLE_ADMIN, "admin@ga.demo", "Admin User"),
    ("officer", ROLE_OFFICER, "off@ga.demo", "Officer User"),
    ("adviser", ROLE_ADVISER, "adv@ga.demo", "Adviser User"),
    ("p1", ROLE_PARTICIPANT, "p1@ga.demo", "P One"),
    ("p2", ROLE_PARTICIPANT, "p2@ga.demo", "P Two"),
    ("p3", ROLE_PARTICIPANT, "p3@ga.demo", "P Three"),
)


def _users(app, make_user):
    """Create the standard accounts and return key -> user id."""
    from app.models.user import User

    for _key, role, email, name in _ACCOUNTS:
        make_user(role, email=email, password=PW, full_name=name)
    with app.app_context():
        return {u.email: u.id for u in User.query.all()}





# ---------------------------------------------------------------------------
# Pure Pandas calculations (no database)
# ---------------------------------------------------------------------------


def _frames(activities, registrations=None, attendance=None):
    """Build the same frames the service loads, from plain dicts."""
    acts = pd.DataFrame(activities)
    if not acts.empty:
        acts["start"] = pd.to_datetime(acts["start"], utc=True)
        acts["academic_year"] = acts["start"].map(svc.academic_year_for)
    regs = pd.DataFrame(
        registrations or [],
        columns=["registration_id", "activity_id", "user_id", "reg_status"],
    )
    atts = pd.DataFrame(
        attendance or [],
        columns=["attendance_id", "activity_id", "user_id", "registration_id",
                 "attendance_status"],
    )
    return acts, regs, atts


def _act(activity_id, title="A", start="2026-07-01"):
    return {"activity_id": activity_id, "title": title, "activity_type": "Event",
            "status": "published", "start": start}


def test_conversion_uses_active_registrations_as_denominator():
    acts, regs, atts = _frames(
        [_act(1)],
        registrations=[
            (1, 1, 10, "registered"),
            (2, 1, 11, "registered"),
            (3, 1, 12, "registered"),
            (4, 1, 13, "registered"),
            (5, 1, 14, "cancelled"),   # must NOT count
        ],
        attendance=[
            (1, 1, 10, 1, "present"),
            (2, 1, 11, 2, "late"),
            (3, 1, 12, 3, "absent"),
        ],
    )
    frame = svc.build_activity_frame(acts, regs, atts)
    row = frame.iloc[0]
    assert row["registered"] == 4          # cancelled excluded
    assert row["cancelled"] == 1
    assert row["attendance_rows"] == 3
    assert row["conversion"] == 75.0       # 3 / 4
    assert row["attendance_rate"] == 66.7  # (1 present + 1 late) / 3


def test_zero_denominators_are_none_not_zero():
    acts, regs, atts = _frames([_act(1)])
    frame = svc.build_activity_frame(acts, regs, atts)
    assert frame.iloc[0]["conversion"] is None
    assert frame.iloc[0]["attendance_rate"] is None


def test_walk_ins_can_exceed_100_percent_and_are_reported():
    acts, regs, atts = _frames(
        [_act(1)],
        registrations=[(1, 1, 10, "registered")],
        attendance=[
            (1, 1, 10, 1, "present"),
            (2, 1, 99, None, "present"),   # walk-in: no registration
        ],
    )
    frame = svc.build_activity_frame(acts, regs, atts)
    row = frame.iloc[0]
    assert row["registered"] == 1
    assert row["walk_ins"] == 1
    assert row["conversion"] == 200.0      # deliberately not clamped
    assert row["attendance_rate"] == 100.0


def test_activity_without_any_rows_still_appears():
    acts, regs, atts = _frames([_act(1), _act(2, title="B")],
                               registrations=[(1, 1, 10, "registered")])
    frame = svc.build_activity_frame(acts, regs, atts)
    assert len(frame) == 2
    empty_row = frame[frame["activity_id"] == 2].iloc[0]
    assert empty_row["registered"] == 0
    assert empty_row["conversion"] is None
    assert empty_row["attendance_rate"] is None


def test_empty_frames_produce_typed_empty_frame():
    acts, regs, atts = _frames([])
    frame = svc.build_activity_frame(acts, regs, atts)
    assert frame.empty
    assert set(svc._ACTIVITY_COLUMNS).issubset(frame.columns)
    totals = svc._totals(frame)
    for key in ("conversion_rate", "turnout_rate", "attendance_rate",
                "session_coverage_rate"):
        assert totals[key] is None
    assert totals["registered"] == 0


def test_zero_rows_but_declared_registration_columns():
    """Registrations frame with columns but no rows must not break the merge."""
    acts, _, atts = _frames([_act(1)])
    empty_regs = pd.DataFrame(columns=["registration_id", "activity_id",
                                       "user_id", "reg_status"])
    frame = svc.build_activity_frame(acts, empty_regs, atts)
    assert frame.iloc[0]["registered"] == 0
    assert frame.iloc[0]["conversion"] is None


@pytest.mark.parametrize(
    "moment, expected",
    [
        (datetime(2026, 7, 1, tzinfo=timezone.utc), "2026-2027"),
        (datetime(2026, 1, 15, tzinfo=timezone.utc), "2025-2026"),
        (datetime(2026, 5, 31, tzinfo=timezone.utc), "2025-2026"),
        (datetime(2026, 6, 1, tzinfo=timezone.utc), "2026-2027"),
    ],
)
def test_academic_year_derivation(moment, expected):
    assert svc.academic_year_for(moment) == expected


def test_academic_year_of_none_is_none():
    assert svc.academic_year_for(None) is None


def test_trend_groups_by_month_and_fills_gaps():
    acts, regs, atts = _frames(
        [
            _act(1, start="2026-06-10"),
            _act(2, title="B", start="2026-08-05"),
        ],
        registrations=[
            (1, 1, 10, "registered"),
            (2, 2, 11, "registered"),
        ],
        attendance=[(1, 1, 10, 1, "present")],
    )
    frame = svc.build_activity_frame(acts, regs, atts)
    trend = svc._monthly_trend(frame)
    assert trend["labels"] == ["2026-06", "2026-07", "2026-08"]
    assert trend["registered"] == [1, 0, 1]
    assert trend["attendance"] == [1, 0, 0]


# ---------------------------------------------------------------------------
# Filter parsing (never raises)
# ---------------------------------------------------------------------------


class _Args(dict):
    """Minimal stand-in for request.args."""


@pytest.mark.parametrize(
    "args, expected_activity, expected_year, errors",
    [
        ({}, None, None, 0),
        ({"activity_id": "", "academic_year": ""}, None, None, 0),
        ({"activity_id": "7"}, 7, None, 0),
        ({"activity_id": "abc"}, None, None, 1),
        ({"activity_id": "-3"}, None, None, 1),
        ({"activity_id": "0"}, None, None, 1),
        ({"academic_year": "2025-2026"}, None, "2025-2026", 0),
        ({"academic_year": "2025-2027"}, None, None, 1),
        ({"academic_year": "25-26"}, None, None, 1),
        ({"academic_year": "<script>"}, None, None, 1),
    ],
)
def test_parse_filters(args, expected_activity, expected_year, errors):
    parsed = svc.parse_filters(_Args(args))
    assert parsed["activity_id"] == expected_activity
    assert parsed["academic_year"] == expected_year
    assert len(parsed["errors"]) == errors


# ---------------------------------------------------------------------------
# Empty data through the service and the route
# ---------------------------------------------------------------------------


def test_empty_database_has_no_rates(app, client, make_user):
    _users(app, make_user)
    with app.app_context():
        data = svc.build_general_dashboard()
    assert data["has_any_activities"] is False
    assert data["has_data"] is False
    assert data["detail"] == []
    assert data["by_type"] == []
    assert data["trend"]["labels"] == []
    assert data["totals"]["conversion_rate"] is None
    assert data["totals"]["attendance_rate"] is None


def test_empty_page_renders_without_error(app, client, make_user):
    _users(app, make_user)
    login(client, "admin@ga.demo", PW)
    resp = client.get("/analytics/general")
    assert resp.status_code == 200
    assert b"General Analytics" in resp.data
    assert b"no participation to analyse" in resp.data


# ---------------------------------------------------------------------------
# End-to-end calculations from the database
# ---------------------------------------------------------------------------


def test_dashboard_totals_and_conversion_from_db(app, client, make_user):
    users = _users(app, make_user)
    admin = users["admin@ga.demo"]
    act = _activity(app, admin, title="Orientation")
    for user in (users["p1@ga.demo"], users["p2@ga.demo"], users["p3@ga.demo"]):
        reg = _register(app, act, user)
        _attend(app, act, user, "present", admin, registration_id=reg)
    p4 = _user(app, make_user, ROLE_PARTICIPANT, "p4@ga.demo", "P Four")
    _register(app, act, p4, status="cancelled")

    with app.app_context():
        data = svc.build_general_dashboard()
    totals = data["totals"]
    assert totals["activities"] == 1
    assert totals["registered"] == 3
    assert totals["cancelled_registrations"] == 1
    assert totals["attendance_rows"] == 3
    assert totals["conversion_rate"] == 100.0
    assert totals["attendance_rate"] == 100.0
    assert totals["session_coverage_rate"] == 100.0


def test_walk_in_reported_from_db(app, client, make_user):
    users = _users(app, make_user)
    admin = users["admin@ga.demo"]
    act = _activity(app, admin, title="Seminar")
    reg = _register(app, act, users["p1@ga.demo"])
    _attend(app, act, users["p1@ga.demo"], "present", admin, registration_id=reg)
    outsider = _user(app, make_user, ROLE_PARTICIPANT, "walk@ga.demo", "Walk In")
    _attend(app, act, outsider, "late", admin)   # no registration row

    with app.app_context():
        data = svc.build_general_dashboard()
    assert data["totals"]["walk_ins"] == 1
    assert data["totals"]["conversion_rate"] == 200.0
    assert data["totals"]["attendance_rate"] == 100.0
    assert data["detail"][0]["walk_ins"] == 1


def test_activity_filter_narrows_results(app, client, make_user):
    users = _users(app, make_user)
    admin = users["admin@ga.demo"]
    a1 = _activity(app, admin, title="First")
    a2 = _activity(app, admin, title="Second")
    _register(app, a1, users["p1@ga.demo"])
    _register(app, a1, users["p2@ga.demo"])
    _register(app, a2, users["p3@ga.demo"])

    with app.app_context():
        data = svc.build_general_dashboard(
            {"activity_id": a1, "academic_year": None, "errors": []}
        )
    assert data["has_data"] is True
    assert data["totals"]["registered"] == 2
    assert [row["title"] for row in data["detail"]] == ["First"]
    assert data["filter_errors"] == []


def test_academic_year_filter(app, client, make_user):
    users = _users(app, make_user)
    admin = users["admin@ga.demo"]
    old = _activity(app, admin, title="Old", start=datetime(2024, 7, 1, tzinfo=timezone.utc))
    new = _activity(app, admin, title="New", start=datetime(2026, 8, 1, tzinfo=timezone.utc))
    _register(app, old, users["p1@ga.demo"])
    _register(app, new, users["p2@ga.demo"])
    _register(app, new, users["p3@ga.demo"])

    with app.app_context():
        data = svc.build_general_dashboard(
            {"activity_id": None, "academic_year": "2026-2027", "errors": []}
        )
        years = svc.academic_years()
    assert data["totals"]["registered"] == 2
    assert [row["title"] for row in data["detail"]] == ["New"]
    assert years == ["2026-2027", "2024-2025"]


def test_unknown_activity_id_is_ignored_and_reported(app, client, make_user):
    users = _users(app, make_user)
    admin = users["admin@ga.demo"]
    act = _activity(app, admin, title="Only")
    _register(app, act, users["p1@ga.demo"])

    with app.app_context():
        data = svc.build_general_dashboard(
            {"activity_id": 999999, "academic_year": None, "errors": []}
        )
    assert data["filter_errors"], "a bogus activity id must be reported"
    assert data["has_data"] is True            # falls back to all data
    assert data["totals"]["registered"] == 1


def test_academic_year_with_no_data_is_ignored_and_reported(app, client, make_user):
    users = _users(app, make_user)
    admin = users["admin@ga.demo"]
    act = _activity(app, admin, title="Only", start=datetime(2026, 8, 1, tzinfo=timezone.utc))
    _register(app, act, users["p1@ga.demo"])

    with app.app_context():
        data = svc.build_general_dashboard(
            {"activity_id": None, "academic_year": "1999-2000", "errors": []}
        )
    assert any("1999-2000" in message for message in data["filter_errors"])
    assert data["totals"]["registered"] == 1


def test_by_type_groups_and_labels_untyped(app, client, make_user):
    users = _users(app, make_user)
    admin = users["admin@ga.demo"]
    typed = _activity(app, admin, title="Typed", activity_type="Workshop")
    untyped = _activity(app, admin, title="Untyped")
    _register(app, typed, users["p1@ga.demo"])
    _register(app, typed, users["p2@ga.demo"])
    _register(app, untyped, users["p3@ga.demo"])

    with app.app_context():
        data = svc.build_general_dashboard()
    rows = {row["activity_type"]: row for row in data["by_type"]}
    assert rows["Workshop"]["activities"] == 1
    assert rows["Workshop"]["registered"] == 2
    assert rows["(untyped)"]["registered"] == 1


def test_phase5_metrics_are_not_reported_here(app, client, make_user):
    """Phase 8 must not duplicate officer responsibility metrics."""
    _users(app, make_user)
    with app.app_context():
        data = svc.build_general_dashboard()
    assert "officers" not in data
    assert "assigned" not in data["totals"]
    assert "completion_rate" not in data["totals"]


# ---------------------------------------------------------------------------
# Route behavior: permissions, filters via query string, rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("email, expected", [
    ("admin@ga.demo", 200),
    ("adv@ga.demo", 200),
])
def test_general_analytics_allowed_for_admin_and_adviser(app, client, make_user, email, expected):
    _users(app, make_user)
    login(client, email, PW)
    assert client.get("/analytics/general").status_code == expected


@pytest.mark.parametrize("email", ["off@ga.demo", "p1@ga.demo"])
def test_general_analytics_forbidden_for_officer_and_participant(app, client, make_user, email):
    _users(app, make_user)
    login(client, email, PW)
    assert client.get("/analytics/general").status_code == 403


def test_general_analytics_anonymous_redirected(app, client):
    resp = client.get("/analytics/general")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_activity_with_no_participation_renders_dash_not_nan(app, client, make_user):
    """Zero denominators must reach the page as None ("—"), never as nan."""
    users = _users(app, make_user)
    admin = users["admin@ga.demo"]
    _activity(app, admin, title="Empty Activity")            # no registration
    _activity(app, admin, title="Nobody Registered")         # 0 registrations
    _register(app, _activity(app, admin, title="Registered Only"), users["p1@ga.demo"])
    login(client, "admin@ga.demo", PW)

    with app.app_context():
        data = svc.build_general_dashboard()
    by_title = {row["title"]: row for row in data["detail"]}
    # No registrations and no attendance -> both denominators are 0 -> None.
    assert by_title["Nobody Registered"]["registered"] == 0
    assert by_title["Nobody Registered"]["conversion_rate"] is None
    assert by_title["Nobody Registered"]["attendance_rate"] is None
    # One registration but no attendance rows -> attendance denominator is 0,
    # while conversion has a real denominator (1) and is therefore 0.0%.
    assert by_title["Registered Only"]["conversion_rate"] == 0.0
    assert by_title["Registered Only"]["attendance_rate"] is None

    resp = client.get("/analytics/general")
    assert resp.status_code == 200
    assert b"nan" not in resp.data.lower()
    for title in ("Empty Activity", "Nobody Registered", "Registered Only"):
        assert title.encode() in resp.data


def test_route_handles_invalid_filter_values(app, client, make_user):
    users = _users(app, make_user)
    admin = users["admin@ga.demo"]
    act = _activity(app, admin, title="Only")
    _register(app, act, users["p1@ga.demo"])
    login(client, "admin@ga.demo", PW)

    resp = client.get("/analytics/general?activity_id=abc&academic_year=not-a-year")
    assert resp.status_code == 200
    body = resp.data
    assert b"Filter notice" in body
    assert b"Only" in body                     # fell back to all data


def test_route_renders_filters_and_rates(app, client, make_user):
    users = _users(app, make_user)
    admin = users["admin@ga.demo"]
    act = _activity(app, admin, title="Rendered Activity",
                    start=datetime(2026, 9, 1, tzinfo=timezone.utc))
    reg = _register(app, act, users["p1@ga.demo"])
    _attend(app, act, users["p1@ga.demo"], "present", admin, registration_id=reg)
    login(client, "admin@ga.demo", PW)

    resp = client.get("/analytics/general?academic_year=2026-2027")
    assert resp.status_code == 200
    body = resp.data
    assert b"Rendered Activity" in body
    assert b"AY 2026-2027" in body
    assert b"100.0%" in body
    assert b"trendChart" in body
    assert b"/activities/general" in body or b"analytics/general" in body


def test_phase5_dashboard_links_to_general(app, client, make_user):
    _users(app, make_user)
    login(client, "admin@ga.demo", PW)
    resp = client.get("/analytics")
    assert resp.status_code == 200
    assert b"General Analytics" in resp.data

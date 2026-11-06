"""Phase 5 — Officer Performance Analytics: metrics, permissions, empty data.

Uses the shared fixtures from tests/conftest.py (runs against techis_test).
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.activity import Activity, ActivityRegistration, AttendanceRecord
from app.models.assignment import ActivityAssignment
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, ROLE_PARTICIPANT
from app.services import analytics_service

from .conftest import login, logout

PW = "Passw0rd!"


def _dt(days: int = 1):
    return datetime.now(timezone.utc) + timedelta(days=days)


def _activity(app, created_by: int, status: str = "published", days: int = 1) -> int:
    start = _dt(days)
    with app.app_context():
        a = Activity(
            title="Event " + str(days),
            start_datetime=start,
            end_datetime=start + timedelta(hours=2),
            status=status,
            created_by=created_by,
        )
        db.session.add(a)
        db.session.commit()
        return a.id


def _assignment(app, activity_id: int, officer_id: int, assigned_by: int,
                status: str = "assigned", due=None, responsibility="Duty") -> int:
    with app.app_context():
        a = ActivityAssignment(
            activity_id=activity_id,
            officer_user_id=officer_id,
            assigned_by=assigned_by,
            responsibility=responsibility,
            status=status,
            due_date=due,
            completed_at=_dt() if status == "completed" else None,
        )
        db.session.add(a)
        db.session.commit()
        return a.id


def _register(app, activity_id: int, user_id: int) -> None:
    with app.app_context():
        db.session.add(ActivityRegistration(
            activity_id=activity_id, user_id=user_id,
            status="registered", registration_date=_dt(),
        ))
        db.session.commit()


def _attend(app, activity_id: int, user_id: int, status: str, recorded_by: int) -> None:
    with app.app_context():
        db.session.add(AttendanceRecord(
            activity_id=activity_id, user_id=user_id, attendance_status=status,
            recorded_by=recorded_by, recorded_at=_dt(),
        ))
        db.session.commit()


def _ids(app):
    from app.models.user import User
    with app.app_context():
        return {u.email: u.id for u in User.query.all()}


def _setup_users(make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW, full_name="Admin User")
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW, full_name="B Officer")
    make_user(ROLE_OFFICER, email="off2@t.demo", password=PW, full_name="A Officer")
    make_user(ROLE_ADVISER, email="adv@t.demo", password=PW, full_name="Adviser User")
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Part User")


# ---------------------------------------------------------------------------
# Empty-data behavior (no exceptions, no division by zero)
# ---------------------------------------------------------------------------


def test_empty_dashboard_has_no_rates(app, client, make_user):
    _setup_users(make_user)
    with app.app_context():
        data = analytics_service.build_dashboard()
    assert data["has_data"] is False
    assert data["totals"]["assigned"] == 0
    assert data["totals"]["completed"] == 0
    assert data["totals"]["completion_rate"] is None      # not 0, not a crash
    assert data["totals"]["attendance_rate"] is None
    assert len(data["timeline"]["labels"]) == 12


def test_empty_dashboard_renders(app, client, make_user):
    _setup_users(make_user)
    login(client, "admin@t.demo", PW)
    resp = client.get("/analytics")
    assert resp.status_code == 200
    assert b"Officer Performance Analytics" in resp.data
    assert b"nothing to measure" in resp.data


def test_rates_are_none_when_denominator_zero(app, client, make_user):
    _setup_users(make_user)
    ids = _ids(app)
    admin_id = ids["admin@t.demo"]
    officer_id = ids["off@t.demo"]
    act = _activity(app, admin_id)
    # assignment exists -> completion denominator 1; but no attendance rows
    _assignment(app, act, officer_id, admin_id, status="assigned")

    with app.app_context():
        data = analytics_service.build_dashboard()
    row = next(r for r in data["officers"] if r["officer"].id == officer_id)
    assert row["assigned"] == 1
    assert row["completion_rate"] == 0.0
    assert row["attendance_rate"] is None


# ---------------------------------------------------------------------------
# Metric calculations
# ---------------------------------------------------------------------------


def test_assigned_completed_overdue_counts(app, client, make_user):
    _setup_users(make_user)
    ids = _ids(app)
    admin_id = ids["admin@t.demo"]
    officer_id = ids["off@t.demo"]
    act = _activity(app, admin_id)

    _assignment(app, act, officer_id, admin_id, "completed", responsibility="Done")
    _assignment(app, act, officer_id, admin_id, "assigned", responsibility="Open one")
    _assignment(
        app, act, officer_id, admin_id, "in_progress",
        due=date.today() - timedelta(days=5), responsibility="Late one",
    )

    with app.app_context():
        data = analytics_service.build_dashboard()
    row = next(r for r in data["officers"] if r["officer"].id == officer_id)
    assert row["assigned"] == 3
    assert row["completed"] == 1
    assert row["overdue"] == 1
    assert row["completion_rate"] == pytest.approx(33.3, abs=0.1)


def test_attendance_rate_counts_present_and_late(app, client, make_user):
    _setup_users(make_user)
    ids = _ids(app)
    admin_id = ids["admin@t.demo"]
    officer_id = ids["off@t.demo"]
    act = _activity(app, admin_id)

    _attend(app, act, officer_id, "present", admin_id)
    # One attendance row per (activity, user) is enforced, so each status
    # needs its own activity.
    act2 = _activity(app, admin_id, days=2)
    _attend(app, act2, officer_id, "late", admin_id)
    act3 = _activity(app, admin_id, days=3)
    _attend(app, act3, officer_id, "absent", admin_id)
    act4 = _activity(app, admin_id, days=4)
    _attend(app, act4, officer_id, "excused", admin_id)

    with app.app_context():
        data = analytics_service.build_dashboard()
    row = next(r for r in data["officers"] if r["officer"].id == officer_id)
    assert row["attendance_total"] == 4
    assert row["attendance"]["present"] == 1
    assert row["attendance"]["late"] == 1
    # (present + late) / total = 2/4
    assert row["attendance_rate"] == 50.0


def test_participation_counts_registrations(app, client, make_user):
    _setup_users(make_user)
    ids = _ids(app)
    admin_id = ids["admin@t.demo"]
    officer_id = ids["off@t.demo"]
    act1 = _activity(app, admin_id)
    act2 = _activity(app, admin_id, days=2)
    _register(app, act1, officer_id)
    _register(app, act2, officer_id)

    with app.app_context():
        data = analytics_service.build_dashboard()
    row = next(r for r in data["officers"] if r["officer"].id == officer_id)
    assert row["registrations"] == 2


def test_officers_ordered_alphabetically_not_by_metric(app, client, make_user):
    _setup_users(make_user)
    ids = _ids(app)
    admin_id = ids["admin@t.demo"]
    a_off = ids["off2@t.demo"]   # "A Officer"
    b_off = ids["off@t.demo"]    # "B Officer"
    act = _activity(app, admin_id)
    # Give A Officer ZERO assignments and B Officer some, to prove ordering
    # is alphabetical rather than by volume.
    _assignment(app, act, b_off, admin_id, "completed", responsibility="x")

    with app.app_context():
        names = [r["officer"].full_name for r in analytics_service.build_dashboard()["officers"]]
    assert names.index("A Officer") < names.index("B Officer")


def test_timeline_buckets_are_fixed_twelve_months(app, client, make_user):
    _setup_users(make_user)
    ids = _ids(app)
    admin_id = ids["admin@t.demo"]
    act = _activity(app, admin_id)
    _assignment(app, act, ids["off@t.demo"], admin_id)

    with app.app_context():
        tl = analytics_service.responsibility_timeline()
    assert len(tl["labels"]) == 12
    assert len(tl["counts"]) == 12
    assert sum(tl["counts"]) == 1
    assert all(isinstance(v, int) for v in tl["counts"])


def test_no_scoring_or_ranking_fields_exposed(app, client, make_user):
    """Guard the design rule: no score/rank/grade keys leak into the payload."""
    _setup_users(make_user)
    with app.app_context():
        data = analytics_service.build_dashboard()
    forbidden = {"score", "rank", "grade", "rating", "leaderboard"}
    for row in data["officers"]:
        assert not (forbidden & set(row.keys()))


def test_t12_activities_created_metric_absent(app, client, make_user):
    _setup_users(make_user)
    ids = _ids(app)
    _activity(app, ids["off@t.demo"])
    with app.app_context():
        data = analytics_service.build_dashboard()
    assert "activities_created" not in data["totals"]
    for row in data["officers"]:
        assert "activities_created" not in row


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("email,expected", [
    ("admin@t.demo", 200),
    ("adv@t.demo", 200),
])
def test_analytics_allowed_for_admin_and_adviser(app, client, make_user, email, expected):
    _setup_users(make_user)
    login(client, email, PW)
    assert client.get("/analytics").status_code == expected


@pytest.mark.parametrize("email", ["off@t.demo", "part@t.demo"])
def test_analytics_forbidden_for_officer_and_participant(app, client, make_user, email):
    _setup_users(make_user)
    login(client, email, PW)
    assert client.get("/analytics").status_code == 403


def test_analytics_anonymous_redirected(app, client):
    resp = client.get("/analytics")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_module_link_is_live_and_hidden_from_officers(app, client, make_user):
    _setup_users(make_user)
    login(client, "admin@t.demo", PW)
    assert client.get("/modules/analytics", follow_redirects=True).status_code == 200
    logout(client)

    login(client, "off@t.demo", PW)
    assert client.get("/modules/analytics").status_code == 403
    assert b"/analytics" not in client.get("/dashboard").data

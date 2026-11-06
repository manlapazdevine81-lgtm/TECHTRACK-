"""Organizational position assignment (officer_terms) — Parts 1-3.

Covers:
  * creating/assigning a position term;
  * several officers holding the same position;
  * active vs ended terms and assignment history;
  * officers with no position (role_display fallback);
  * Responsible Officer dropdown labels (activities form + detail);
  * authorization unchanged: only admins assign, terms grant no permissions.

Runs against techis_test via the shared fixtures (schema from db.create_all()).
"""
from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models.activity import Activity
from app.models.officer_term import OfficerTerm
from app.models.organization import Organization
from app.models.position import Position
from app.models.user import (
    ROLE_ADMIN,
    ROLE_ADVISER,
    ROLE_OFFICER,
    ROLE_PARTICIPANT,
    User,
)
from app.services import position_service

from .conftest import login, logout, post_csrf

PW = "Passw0rd!"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def org(app, client):
    """`client` first: it resets the schema for every test."""
    with app.app_context():
        organization = Organization(name="Tech Innovators Society", academic_year="2026-2027")
        db.session.add(organization)
        db.session.commit()
        return organization.id


@pytest.fixture()
def positions(app, org):
    """A small, real subset of the catalogue."""
    with app.app_context():
        rows = {}
        for order, (title, dept) in enumerate(
            [
                ("Chief Operating Officer", None),
                ("Technical Project Manager", "Technology"),
                ("Marketing Manager", "Communications & Creatives"),
            ]
        ):
            p = Position(
                organization_id=org, title=title, department=dept,
                duties=f"{title} duties", sort_order=order,
            )
            db.session.add(p)
            rows[title] = None
        db.session.commit()
        return {p.title: p.id for p in Position.query.all()}


@pytest.fixture()
def people(app, client, make_user):
    return {
        "admin": make_user(ROLE_ADMIN, email="admin@t.demo", password=PW, full_name="Ada Admin"),
        "officer": make_user(ROLE_OFFICER, email="off@t.demo", password=PW, full_name="Demo TechIS Officer"),
        "officer2": make_user(ROLE_OFFICER, email="off2@t.demo", password=PW, full_name="Other Officer"),
        "adviser": make_user(ROLE_ADVISER, email="adv@t.demo", password=PW, full_name="Ana Adviser"),
        "participant": make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Pat Participant"),
    }


def _user(app, user_id) -> User:
    with app.app_context():
        return db.session.get(User, user_id)


def _assign_via_service(app, user_id, position_id, start=None):
    with app.app_context():
        user = db.session.get(User, user_id)
        position = db.session.get(Position, position_id)
        return position_service.assign_position(user, position, start).id


# ---------------------------------------------------------------------------
# 1. Model / assignment basics
# ---------------------------------------------------------------------------


def test_term_model_columns_and_constraints():
    columns = {c.name for c in OfficerTerm.__table__.columns}
    assert {"user_id", "position_id", "start_date", "end_date", "status"} <= columns
    assert OfficerTerm.STATUSES == ("active", "ended")
    uniques = {
        c.name
        for c in OfficerTerm.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert "uq_term_user_position_start" in uniques


def test_assign_position_creates_active_term(app, org, positions, people):
    term_id = _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    with app.app_context():
        term = db.session.get(OfficerTerm, term_id)
        assert term.user_id == people["officer"]
        assert term.position.title == "Chief Operating Officer"
        assert term.status == "active"
        assert term.end_date is None
        assert term.is_active is True


def test_assigning_a_new_position_ends_the_previous_one(app, org, positions, people):
    first = _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    second = _assign_via_service(
        app, people["officer"], positions["Technical Project Manager"]
    )
    with app.app_context():
        old = db.session.get(OfficerTerm, first)
        new = db.session.get(OfficerTerm, second)
        assert old.status == "ended"
        assert old.end_date is not None          # history preserved, not deleted
        assert new.status == "active"
        assert position_service.active_position_label(people["officer"]) == (
            "Technical Project Manager"
        )


def test_ending_a_term_preserves_history(app, org, positions, people):
    _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    with app.app_context():
        user = db.session.get(User, people["officer"])
        closed = position_service.end_active_term(user)
        assert closed is not None
        assert closed.status == "ended"
        assert position_service.active_position_label(user.id) is None
        assert OfficerTerm.query.count() == 1     # still present as history


def test_multiple_officers_can_hold_the_same_position(app, org, positions, people):
    _assign_via_service(app, people["officer"], positions["Technical Project Manager"])
    _assign_via_service(app, people["officer2"], positions["Technical Project Manager"])
    with app.app_context():
        holders = OfficerTerm.query.filter_by(
            position_id=positions["Technical Project Manager"], status="active"
        ).all()
        assert len(holders) == 2
        assert {h.user_id for h in holders} == {people["officer"], people["officer2"]}


def test_one_officer_holds_at_most_one_active_position(app, org, positions, people):
    _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    _assign_via_service(app, people["officer"], positions["Marketing Manager"])
    with app.app_context():
        active = OfficerTerm.query.filter_by(
            user_id=people["officer"], status="active"
        ).all()
        assert len(active) == 1
        assert active[0].position.title == "Marketing Manager"


def test_reactivating_the_same_position_is_a_no_op(app, org, positions, people):
    first = _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    again = _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    assert first == again
    with app.app_context():
        assert OfficerTerm.query.filter_by(user_id=people["officer"]).count() == 1


def test_active_vs_ended_filtering(app, org, positions, people):
    today = date.today()
    with app.app_context():
        user = db.session.get(User, people["officer"])
        ended = OfficerTerm(
            user_id=user.id, position_id=positions["Marketing Manager"],
            start_date=today - timedelta(days=400), end_date=today - timedelta(days=200),
            status="ended",
        )
        active = OfficerTerm(
            user_id=user.id, position_id=positions["Chief Operating Officer"],
            start_date=today - timedelta(days=10), status="active",
        )
        db.session.add_all([ended, active])
        db.session.commit()

        labels = position_service.active_labels_by_user([user.id])
        assert labels[user.id] == "Chief Operating Officer"   # not the ended one
        assert len(position_service.term_history(user.id)) == 2


def test_officer_without_position_has_no_label(app, people):
    with app.app_context():
        assert position_service.active_position_label(people["officer"]) is None
        assert position_service.active_labels_by_user([people["officer"]]) == {}


# ---------------------------------------------------------------------------
# 2. Admin assignment route
# ---------------------------------------------------------------------------


def test_admin_can_assign_position_through_the_ui(app, client, org, positions, people):
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/admin/users/{people['officer']}/position",
        form_path=f"/admin/users/{people['officer']}/position",
        position_id=str(positions["Chief Operating Officer"]),
    )
    assert resp.status_code == 302
    with app.app_context():
        assert position_service.active_position_label(people["officer"]) == (
            "Chief Operating Officer"
        )


def test_non_admin_cannot_assign_position(app, client, org, positions, people):
    login(client, "off@t.demo", PW)
    resp = post_csrf(
        client, f"/admin/users/{people['officer']}/position",
        form_path="/dashboard",
        position_id=str(positions["Marketing Manager"]),
    )
    assert resp.status_code == 403
    with app.app_context():
        assert OfficerTerm.query.count() == 0


def test_anonymous_cannot_reach_assignment(app, client, people):
    resp = client.get(f"/admin/users/{people['officer']}/position")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_ineligible_role_is_refused(app, client, org, positions, people):
    """Participants/advisers hold no organizational position."""
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/admin/users/{people['participant']}/position",
        form_path=f"/admin/users/{people['participant']}/position",
        position_id=str(positions["Marketing Manager"]),
        follow=True,
    )
    assert b"can only be assigned to" in resp.data
    with app.app_context():
        assert OfficerTerm.query.count() == 0


def test_assigning_invalid_position_is_rejected(app, client, org, positions, people):
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/admin/users/{people['officer']}/position",
        form_path=f"/admin/users/{people['officer']}/position",
        position_id="999999", follow=True,
    )
    assert b"could not be found" in resp.data
    with app.app_context():
        assert OfficerTerm.query.count() == 0


def test_end_term_route_closes_the_term(app, client, org, positions, people):
    _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/admin/users/{people['officer']}/position/end",
        form_path=f"/admin/users/{people['officer']}/position", follow=True,
    )
    assert b"has ended" in resp.data
    with app.app_context():
        assert position_service.active_position_label(people["officer"]) is None
        assert OfficerTerm.query.count() == 1


# ---------------------------------------------------------------------------
# 3. Activities dropdown labels
# ---------------------------------------------------------------------------


def _make_activity(app, created_by, title="Label Event"):
    from datetime import datetime, timezone

    with app.app_context():
        a = Activity(
            title=title,
            start_datetime=datetime.now(timezone.utc),
            end_datetime=datetime.now(timezone.utc),
            status="published",
            created_by=created_by,
        )
        db.session.add(a)
        db.session.commit()
        return a.id


def test_dropdown_shows_position_when_assigned(app, client, org, positions, people):
    _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    login(client, "admin@t.demo", PW)
    html = client.get("/activities/new").data.decode()
    assert "Demo TechIS Officer (Chief Operating Officer)" in html
    assert "Demo TechIS Officer (TechIS Officer)" not in html


def test_dropdown_falls_back_to_role_without_a_position(app, client, org, positions, people):
    login(client, "admin@t.demo", PW)
    html = client.get("/activities/new").data.decode()
    assert "Demo TechIS Officer (TechIS Officer)" in html


def test_dropdown_shows_the_active_position_not_an_ended_one(app, client, org, positions, people):
    _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    _assign_via_service(app, people["officer"], positions["Marketing Manager"])
    login(client, "admin@t.demo", PW)
    html = client.get("/activities/new").data.decode()
    assert "Demo TechIS Officer (Marketing Manager)" in html
    assert "(Chief Operating Officer)" not in html


def test_dropdown_still_lists_only_eligible_staff(app, client, org, positions, people):
    _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    login(client, "admin@t.demo", PW)
    html = client.get("/activities/new").data.decode()
    # Participants/advisers remain ineligible regardless of any position data.
    assert "Pat Participant" not in html
    assert "Ana Adviser" not in html


def test_activity_detail_shows_position_label(app, client, org, positions, people):
    _assign_via_service(app, people["officer"], positions["Technical Project Manager"])
    activity_id = _make_activity(app, people["admin"])
    with app.app_context():
        db.session.get(Activity, activity_id).responsible_officer_id = people["officer"]
        db.session.commit()

    login(client, "admin@t.demo", PW)
    html = client.get(f"/activities/{activity_id}").data.decode()
    assert "Technical Project Manager" in html


def test_activity_detail_falls_back_to_role(app, client, org, positions, people):
    activity_id = _make_activity(app, people["admin"])
    with app.app_context():
        db.session.get(Activity, activity_id).responsible_officer_id = people["officer"]
        db.session.commit()

    login(client, "admin@t.demo", PW)
    html = client.get(f"/activities/{activity_id}").data.decode()
    assert "Demo TechIS Officer" in html
    assert "TechIS Officer" in html


# ---------------------------------------------------------------------------
# 4. Authorization must be unaffected by positions
# ---------------------------------------------------------------------------


def test_position_does_not_change_system_permissions(app, client, org, positions, people):
    """An officer with the highest-sounding position still gets officer access."""
    _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    login(client, "off@t.demo", PW)

    # Officer-level access is unchanged...
    assert client.get("/activities").status_code == 200
    assert client.get("/reports").status_code == 200
    # ...and admin-only areas remain forbidden.
    assert client.get("/admin/users").status_code == 403
    assert client.get("/analytics").status_code == 403
    assert client.get(f"/admin/users/{people['officer']}/position").status_code == 403


def test_position_does_not_affect_the_participant(app, client, org, positions, people):
    login(client, "part@t.demo", PW)
    assert client.get("/organization").status_code == 403
    assert client.get("/activities").status_code == 403


def test_assigning_does_not_touch_the_system_role(app, org, positions, people):
    with app.app_context():
        before = db.session.get(User, people["officer"]).role_name
    _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    with app.app_context():
        after = db.session.get(User, people["officer"]).role_name
    assert before == after == ROLE_OFFICER


def test_assigning_does_not_grant_any_permission_column(app, org, positions, people):
    """T19 stays frozen: `permission_level` is not part of the schema at all."""
    assert "permission_level" not in {c.name for c in Position.__table__.columns}
    _assign_via_service(app, people["officer"], positions["Chief Operating Officer"])
    with app.app_context():
        # The assignment lives only in officer_terms.
        assert OfficerTerm.query.count() == 1
        # `roles` was not modified in any way by the assignment.
        assert db.session.get(User, people["officer"]).role_name == ROLE_OFFICER

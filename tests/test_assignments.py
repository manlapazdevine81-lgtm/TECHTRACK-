"""Phase 3 — ActivityAssignment model, validation, permissions, and editing.

Runs against the `techis_test` database via tests/conftest.py fixtures only.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.activity import Activity
from app.models.assignment import ActivityAssignment, is_eligible_officer
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, ROLE_PARTICIPANT

from .conftest import login, logout, post_csrf


def _activity(app, created_by: int, status: str = "draft", title: str = "Tech Talk") -> int:
    start = datetime.now(timezone.utc) + timedelta(days=1)
    with app.app_context():
        activity = Activity(
            title=title,
            venue="Lipa Campus",
            start_datetime=start,
            end_datetime=start + timedelta(hours=2),
            status=status,
            created_by=created_by,
        )
        db.session.add(activity)
        db.session.commit()
        return activity.id


def _add_assignment(
    app,
    activity_id: int,
    officer_id: int,
    assigned_by: int,
    responsibility: str = "Coordinate venue",
    status: str = "assigned",
) -> int:
    with app.app_context():
        assignment = ActivityAssignment(
            activity_id=activity_id,
            officer_user_id=officer_id,
            assigned_by=assigned_by,
            responsibility=responsibility,
            status=status,
        )
        db.session.add(assignment)
        db.session.commit()
        return assignment.id


def _user_ids(app) -> dict[str, int]:
    from app.models.user import User

    with app.app_context():
        return {u.email: u.id for u in User.query.all()}


def _assignments(app, activity_id: int) -> list:
    with app.app_context():
        return (
            db.session.execute(
                db.select(ActivityAssignment)
                .where(ActivityAssignment.activity_id == activity_id)
                .order_by(ActivityAssignment.id)
            )
            .scalars()
            .all()
        )


# ---------------------------------------------------------------------------
# Model constraints
# ---------------------------------------------------------------------------


def test_multiple_officers_can_hold_separate_responsibilities(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    officer_id = make_user(ROLE_OFFICER, email="off@t.demo")
    activity_id = _activity(app, admin_id)

    _add_assignment(app, activity_id, officer_id, admin_id, "Coordinate venue")
    _add_assignment(app, activity_id, officer_id, admin_id, "Manage registration")

    assert len(_assignments(app, activity_id)) == 2


def test_multiple_officers_on_one_activity(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    a_id = make_user(ROLE_OFFICER, email="a@t.demo")
    b_id = make_user(ROLE_OFFICER, email="b@t.demo")
    activity_id = _activity(app, admin_id)

    _add_assignment(app, activity_id, a_id, admin_id)
    _add_assignment(app, activity_id, b_id, admin_id)

    officers = {a.officer_user_id for a in _assignments(app, activity_id)}
    assert officers == {a_id, b_id}


def test_duplicate_duty_for_same_officer_is_rejected_by_db(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    officer_id = make_user(ROLE_OFFICER, email="off@t.demo")
    activity_id = _activity(app, admin_id)
    _add_assignment(app, activity_id, officer_id, admin_id, "Coordinate venue")

    with app.app_context():
        db.session.add(
            ActivityAssignment(
                activity_id=activity_id,
                officer_user_id=officer_id,
                assigned_by=admin_id,
                responsibility="Coordinate venue",
                status="assigned",
            )
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_responsibility_is_required_column(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    activity_id = _activity(app, admin_id)

    with app.app_context():
        db.session.add(
            ActivityAssignment(
                activity_id=activity_id,
                officer_user_id=admin_id,
                assigned_by=admin_id,
                responsibility=None,
                status="assigned",
            )
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_assignment_status_transitions_via_model(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    activity_id = _activity(app, admin_id)
    assignment_id = _add_assignment(app, activity_id, admin_id, admin_id)

    with app.app_context():
        assignment = db.session.get(ActivityAssignment, assignment_id)
        assert assignment.set_status("in_progress") is True
        assert assignment.set_status("draft") is False          # unknown status
        assert assignment.set_status("completed") is True
        assert assignment.completed_at is not None
        assert assignment.set_status("assigned") is False       # illegal from completed
        db.session.rollback()


def test_overdue_is_derived_not_stored(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    activity_id = _activity(app, admin_id)

    with app.app_context():
        assignment = ActivityAssignment(
            activity_id=activity_id,
            officer_user_id=admin_id,
            assigned_by=admin_id,
            responsibility="Late duty",
            status="assigned",
            due_date=date.today() - timedelta(days=3),
        )
        db.session.add(assignment)
        db.session.commit()
        assert assignment.is_overdue is True
        assert assignment.status == "assigned"   # derived, never auto-written
        db.session.rollback()


def test_eligible_officer_helper_uses_confirmed_roles_only(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    officer_id = make_user(ROLE_OFFICER, email="off@t.demo")
    adviser_id = make_user(ROLE_ADVISER, email="adv@t.demo")
    participant_id = make_user(ROLE_PARTICIPANT, email="part@t.demo")

    from app.models.user import User

    with app.app_context():
        assert is_eligible_officer(db.session.get(User, admin_id)) is True
        assert is_eligible_officer(db.session.get(User, officer_id)) is True
        assert is_eligible_officer(db.session.get(User, adviser_id)) is False
        assert is_eligible_officer(db.session.get(User, participant_id)) is False
        assert is_eligible_officer(None) is False


# ---------------------------------------------------------------------------
# Route: creating assignments (validation + permissions)
# ---------------------------------------------------------------------------


def _form(**overrides):
    data = {"responsibility": "Coordinate venue", "due_date": ""}
    data.update(overrides)
    return data


def test_manager_can_assign_officer(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    officer_id = make_user(ROLE_OFFICER, email="off@t.demo")
    activity_id = _activity(app, admin_id)

    login(client, "admin@t.demo", "Passw0rd!")
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/assignments",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(officer_id),
        **_form(),
        follow=True,
    )
    assert b"Responsibility assigned" in resp.data
    rows = _assignments(app, activity_id)
    assert len(rows) == 1
    assert rows[0].officer_user_id == officer_id
    assert rows[0].status == "assigned"
    assert rows[0].assigned_by == admin_id


def test_officer_can_assign_on_own_activity(app, client, make_user):
    owner_id = make_user(ROLE_OFFICER, email="owner@t.demo", password="Passw0rd!")
    other_id = make_user(ROLE_OFFICER, email="other@t.demo")
    activity_id = _activity(app, owner_id)

    login(client, "owner@t.demo", "Passw0rd!")
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/assignments",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(other_id),
        **_form(),
        follow=True,
    )
    assert b"Responsibility assigned" in resp.data


def test_officer_cannot_assign_on_anothers_activity(app, client, make_user):
    owner_id = make_user(ROLE_OFFICER, email="owner@t.demo")
    other_id = make_user(ROLE_OFFICER, email="other@t.demo", password="Passw0rd!")
    activity_id = _activity(app, owner_id)

    login(client, "other@t.demo", "Passw0rd!")
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/assignments",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(owner_id),
        **_form(),
    )
    assert resp.status_code == 403
    assert _assignments(app, activity_id) == []


def test_adviser_and_participant_cannot_assign(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    make_user(ROLE_ADVISER, email="adv@t.demo", password="Passw0rd!")
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password="Passw0rd!")
    activity_id = _activity(app, admin_id, status="published")

    for email in ("adv@t.demo", "part@t.demo"):
        login(client, email, "Passw0rd!")
        resp = post_csrf(
            client,
            f"/activities/{activity_id}/assignments",
            form_path="/dashboard",
            officer_user_id=str(admin_id),
            **_form(),
        )
        assert resp.status_code == 403, email
        logout(client)
    assert _assignments(app, activity_id) == []


def test_assignment_requires_responsibility(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    activity_id = _activity(app, admin_id)

    login(client, "admin@t.demo", "Passw0rd!")
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/assignments",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(admin_id),
        responsibility="   ",
        follow=True,
    )
    assert b"Responsibility is required" in resp.data
    assert _assignments(app, activity_id) == []


@pytest.mark.parametrize("email,role", [
    ("adv@t.demo", ROLE_ADVISER),
    ("part@t.demo", ROLE_PARTICIPANT),
])
def test_ineligible_roles_cannot_be_assigned(app, client, make_user, email, role):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    target_id = make_user(role, email=email)
    activity_id = _activity(app, admin_id)

    login(client, "admin@t.demo", "Passw0rd!")
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/assignments",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(target_id),
        **_form(),
        follow=True,
    )
    assert b"Only active System Administrators and TechIS Officers" in resp.data
    assert _assignments(app, activity_id) == []


def test_inactive_officer_cannot_be_assigned(app, client, make_user):
    from app.models.user import User

    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    officer_id = make_user(ROLE_OFFICER, email="off@t.demo")
    activity_id = _activity(app, admin_id)

    with app.app_context():
        db.session.get(User, officer_id).is_active = False
        db.session.commit()

    login(client, "admin@t.demo", "Passw0rd!")
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/assignments",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(officer_id),
        **_form(),
        follow=True,
    )
    assert b"Only active System Administrators" in resp.data
    assert _assignments(app, activity_id) == []


def test_duplicate_duty_rejected_with_message(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    activity_id = _activity(app, admin_id)
    _add_assignment(app, activity_id, admin_id, admin_id, "Coordinate venue")

    login(client, "admin@t.demo", "Passw0rd!")
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/assignments",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(admin_id),
        **_form(),
        follow=True,
    )
    assert b"already has this responsibility" in resp.data
    assert len(_assignments(app, activity_id)) == 1


def test_assignment_rejected_on_terminal_activity(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    login(client, "admin@t.demo", "Passw0rd!")
    for status in ("completed", "cancelled"):
        activity_id = _activity(app, admin_id, status=status)
        resp = post_csrf(
            client,
            f"/activities/{activity_id}/assignments",
            form_path=f"/activities/{activity_id}",
            officer_user_id=str(admin_id),
            **_form(),
            follow=True,
        )
        assert b"cannot be added" in resp.data, status
        assert _assignments(app, activity_id) == []


# ---------------------------------------------------------------------------
# Route: editing assignments
# ---------------------------------------------------------------------------


def test_edit_assignment_details(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    activity_id = _activity(app, admin_id, status="published")
    assignment_id = _add_assignment(app, activity_id, admin_id, admin_id)

    login(client, "admin@t.demo", "Passw0rd!")
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/assignments/{assignment_id}/edit",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(admin_id),
        responsibility="Updated duty",
        due_date="2026-12-31",
        status="in_progress",
        follow=True,
    )
    assert b"Assignment updated" in resp.data
    row = _assignments(app, activity_id)[0]
    assert row.responsibility == "Updated duty"
    assert row.status == "in_progress"
    assert row.due_date == date(2026, 12, 31)


def test_edit_assignment_status_completed_sets_timestamp(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    activity_id = _activity(app, admin_id, status="published")
    assignment_id = _add_assignment(app, activity_id, admin_id, admin_id)

    login(client, "admin@t.demo", "Passw0rd!")
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/assignments/{assignment_id}/edit",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(admin_id),
        responsibility="Coordinate venue",
        due_date="",
        status="completed",
        follow=True,
    )
    assert b"Assignment updated" in resp.data
    rows = _assignments(app, activity_id)
    assert rows[0].status == "completed"
    assert rows[0].completed_at is not None


def test_edit_assignment_illegal_transition_rejected(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    activity_id = _activity(app, admin_id)
    assignment_id = _add_assignment(
        app, activity_id, admin_id, admin_id, status="completed"
    )

    login(client, "admin@t.demo", "Passw0rd!")
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/assignments/{assignment_id}/edit",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(admin_id),
        responsibility="Coordinate venue",
        status="assigned",
        follow=True,
    )
    assert b"Cannot change a completed assignment" in resp.data
    assert _assignments(app, activity_id)[0].status == "completed"


def test_edit_assignment_from_another_activity_is_404(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    activity_a = _activity(app, admin_id, title="A")
    activity_b = _activity(app, admin_id, title="B")
    foreign_id = _add_assignment(app, activity_a, admin_id, admin_id)

    login(client, "admin@t.demo", "Passw0rd!")
    assert (
        post_csrf(
            client,
            f"/activities/{activity_b}/assignments/{foreign_id}/edit",
            form_path=f"/activities/{activity_b}",
            officer_user_id=str(admin_id),
            responsibility="X",
        ).status_code
        == 404
    )


def test_assignment_edit_rejected_on_terminal_activity(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    activity_id = _activity(app, admin_id, status="published")
    assignment_id = _add_assignment(app, activity_id, admin_id, admin_id)

    login(client, "admin@t.demo", "Passw0rd!")
    post_csrf(
        client,
        f"/activities/{activity_id}/status",
        form_path=f"/activities/{activity_id}",
        status="completed",
    )
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/assignments/{assignment_id}/edit",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(admin_id),
        responsibility="Changed after completion",
        follow=True,
    )
    assert b"cannot be changed" in resp.data
    assert _assignments(app, activity_id)[0].responsibility == "Coordinate venue"


def test_assignment_routes_require_csrf(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    activity_id = _activity(app, admin_id)
    login(client, "admin@t.demo", "Passw0rd!")

    assert (
        client.post(
            f"/activities/{activity_id}/assignments",
            data={"officer_user_id": str(admin_id), "responsibility": "No token"},
        ).status_code
        == 400
    )
    assert _assignments(app, activity_id) == []


# ---------------------------------------------------------------------------
# Detail view rendering
# ---------------------------------------------------------------------------


def test_detail_page_lists_assignments_and_form_for_manager(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password="Passw0rd!")
    activity_id = _activity(app, admin_id, status="published")
    _add_assignment(app, activity_id, admin_id, admin_id, "Coordinate venue")

    login(client, "admin@t.demo", "Passw0rd!")
    html = client.get(f"/activities/{activity_id}").data
    assert b"Officer responsibilities" in html
    assert b"Coordinate venue" in html
    assert f"/activities/{activity_id}/assignments".encode() in html


def test_adviser_sees_assignments_read_only(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    make_user(ROLE_ADVISER, email="adv@t.demo", password="Passw0rd!")
    activity_id = _activity(app, admin_id, status="published")
    _add_assignment(app, activity_id, admin_id, admin_id, "Coordinate venue")

    login(client, "adv@t.demo", "Passw0rd!")
    html = client.get(f"/activities/{activity_id}").data
    assert b"Coordinate venue" in html
    assert b"Assign responsibility" not in html

"""Phase 4B — Event Participants views + attendance edge cases and permissions.

Read-only module tests plus attendance integrity tests. No schema changes are made
here: rows are inserted through the existing models. Runs against `techis_test`
via tests/conftest.py fixtures only.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.activity import Activity, ActivityRegistration, AttendanceRecord
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, ROLE_PARTICIPANT

from .conftest import login, logout, post_csrf

PW = "Passw0rd!"


# ---------------------------------------------------------------------------
# Helpers (existing models only)
# ---------------------------------------------------------------------------


def _activity(app, created_by: int, status: str = "published", title: str = "Tech Talk") -> int:
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


def _register(app, activity_id: int, user_id: int, status: str = "registered") -> int:
    with app.app_context():
        registration = ActivityRegistration(
            activity_id=activity_id,
            user_id=user_id,
            status=status,
            registration_date=datetime.now(timezone.utc),
        )
        db.session.add(registration)
        db.session.commit()
        return registration.id


def _attendance_rows(app, activity_id: int) -> list:
    with app.app_context():
        return (
            db.session.execute(
                db.select(AttendanceRecord).where(
                    AttendanceRecord.activity_id == activity_id
                )
            )
            .scalars()
            .all()
        )


def _attendance(app, activity_id: int, user_id: int):
    with app.app_context():
        return db.session.execute(
            db.select(AttendanceRecord).where(
                AttendanceRecord.activity_id == activity_id,
                AttendanceRecord.user_id == user_id,
            )
        ).scalar_one_or_none()


def _user_ids(app) -> dict[str, int]:
    from app.models.user import User

    with app.app_context():
        return {u.email: u.id for u in User.query.all()}


def _post_attendance(client, activity_id: int, **data):
    return post_csrf(
        client,
        f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        follow=True,
        **data,
    )


# ---------------------------------------------------------------------------
# Attendance status persistence (all four statuses)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["present", "late", "absent", "excused"])
def test_attendance_status_persists(app, client, make_user, status):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Part Person")
    activity_id = _activity(app, admin_id)
    part_id = _user_ids(app)["part@t.demo"]
    _register(app, activity_id, part_id)

    login(client, "admin@t.demo", PW)
    resp = _post_attendance(
        client, activity_id, user_id=str(part_id), attendance_status=status
    )
    assert b"Attendance recorded" in resp.data
    record = _attendance(app, activity_id, part_id)
    assert record is not None
    assert record.attendance_status == status


def test_attendance_records_time_in_and_time_out(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Part Person")
    activity_id = _activity(app, admin_id)
    part_id = _user_ids(app)["part@t.demo"]
    _register(app, activity_id, part_id)

    login(client, "admin@t.demo", PW)
    resp = _post_attendance(
        client,
        activity_id,
        user_id=str(part_id),
        attendance_status="present",
        time_in="2026-11-01T09:00",
        time_out="2026-11-01T12:00",
    )
    assert b"Attendance recorded" in resp.data
    record = _attendance(app, activity_id, part_id)
    assert record.time_in is not None and record.time_out is not None
    assert record.time_out > record.time_in


def test_recorded_by_is_the_signed_in_staff_member(app, client, make_user):
    owner_id = make_user(ROLE_OFFICER, email="owner@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Part Person")
    activity_id = _activity(app, owner_id)
    part_id = _user_ids(app)["part@t.demo"]
    _register(app, activity_id, part_id)

    login(client, "owner@t.demo", PW)
    _post_attendance(client, activity_id, user_id=str(part_id), attendance_status="present")
    record = _attendance(app, activity_id, part_id)
    assert record.recorded_by == owner_id


# ---------------------------------------------------------------------------
# Attendance validation rejections
# ---------------------------------------------------------------------------


def test_invalid_attendance_status_is_rejected(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Part Person")
    activity_id = _activity(app, admin_id)
    part_id = _user_ids(app)["part@t.demo"]
    _register(app, activity_id, part_id)

    login(client, "admin@t.demo", PW)
    resp = _post_attendance(
        client, activity_id, user_id=str(part_id), attendance_status="visiting"
    )
    assert b"Select a valid attendance status" in resp.data
    assert _attendance(app, activity_id, part_id) is None


def test_time_out_before_time_in_is_rejected(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Part Person")
    activity_id = _activity(app, admin_id)
    part_id = _user_ids(app)["part@t.demo"]
    _register(app, activity_id, part_id)

    login(client, "admin@t.demo", PW)
    resp = _post_attendance(
        client,
        activity_id,
        user_id=str(part_id),
        attendance_status="present",
        time_in="2026-11-01T12:00",
        time_out="2026-11-01T09:00",
    )
    assert b"Time out cannot be earlier than time in" in resp.data
    assert _attendance(app, activity_id, part_id) is None


def test_malformed_time_in_is_rejected(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Part Person")
    activity_id = _activity(app, admin_id)
    part_id = _user_ids(app)["part@t.demo"]
    _register(app, activity_id, part_id)

    login(client, "admin@t.demo", PW)
    resp = _post_attendance(
        client,
        activity_id,
        user_id=str(part_id),
        attendance_status="present",
        time_in="not-a-datetime",
    )
    assert b"Time in is not a valid date/time" in resp.data
    assert _attendance(app, activity_id, part_id) is None


def test_missing_user_selection_is_rejected(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    activity_id = _activity(app, admin_id)

    login(client, "admin@t.demo", PW)
    resp = _post_attendance(
        client, activity_id, user_id="", attendance_status="present"
    )
    assert b"Select a participant" in resp.data
    assert _attendance_rows(app, activity_id) == []


# ---------------------------------------------------------------------------
# Walk-in attendance (registration_id NULL) and composite FK integrity
# ---------------------------------------------------------------------------


def test_walk_in_attendance_without_registration_persists(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="walkin@t.demo", password=PW, full_name="Walk In")
    activity_id = _activity(app, admin_id)
    walkin_id = _user_ids(app)["walkin@t.demo"]

    login(client, "admin@t.demo", PW)
    resp = _post_attendance(
        client, activity_id, user_id=str(walkin_id), attendance_status="present"
    )
    assert b"Attendance recorded" in resp.data
    record = _attendance(app, activity_id, walkin_id)
    assert record is not None
    assert record.registration_id is None          # no registration existed
    assert record.attendance_status == "present"


def test_attendance_links_to_matching_registration(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Part Person")
    activity_id = _activity(app, admin_id)
    part_id = _user_ids(app)["part@t.demo"]
    registration_id = _register(app, activity_id, part_id)

    login(client, "admin@t.demo", PW)
    _post_attendance(client, activity_id, user_id=str(part_id), attendance_status="present")
    record = _attendance(app, activity_id, part_id)
    assert record.registration_id == registration_id


def test_composite_fk_rejects_mismatched_registration(app, client, make_user):
    """A row can never point at a registration from another activity/user."""
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    a_id = make_user(ROLE_PARTICIPANT, email="a@t.demo")
    b_id = make_user(ROLE_PARTICIPANT, email="b@t.demo")
    activity_one = _activity(app, admin_id, title="One")
    activity_two = _activity(app, admin_id, title="Two")
    reg_of_a_on_one = _register(app, activity_one, a_id)

    with app.app_context():
        # registration belongs to activity_one + user A, but the row claims
        # activity_two + user B -> composite FK must reject it.
        db.session.add(
            AttendanceRecord(
                activity_id=activity_two,
                user_id=b_id,
                registration_id=reg_of_a_on_one,
                attendance_status="present",
                recorded_by=admin_id,
                recorded_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_duplicate_attendance_row_rejected_by_db(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    activity_id = _activity(app, admin_id)

    with app.app_context():
        for _ in range(2):
            db.session.add(
                AttendanceRecord(
                    activity_id=activity_id,
                    user_id=admin_id,
                    attendance_status="present",
                    recorded_by=admin_id,
                    recorded_at=datetime.now(timezone.utc),
                )
            )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


# ---------------------------------------------------------------------------
# Attendance permission restrictions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("email,role", [
    ("adv@t.demo", ROLE_ADVISER),
    ("part@t.demo", ROLE_PARTICIPANT),
])
def test_non_manager_roles_cannot_record_attendance(app, client, make_user, email, role):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    target_id = make_user(role, email=email, password=PW)
    activity_id = _activity(app, admin_id)
    _register(app, activity_id, target_id)

    login(client, email, PW)
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/attendance",
        form_path="/dashboard",
        user_id=str(target_id),
        attendance_status="present",
    )
    assert resp.status_code == 403
    assert _attendance_rows(app, activity_id) == []


def test_officer_cannot_record_attendance_for_foreign_activity(app, client, make_user):
    owner_id = make_user(ROLE_OFFICER, email="owner@t.demo")
    make_user(ROLE_OFFICER, email="other@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Part Person")
    activity_id = _activity(app, owner_id)
    part_id = _user_ids(app)["part@t.demo"]
    _register(app, activity_id, part_id)

    login(client, "other@t.demo", PW)
    resp = post_csrf(
        client,
        f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        user_id=str(part_id),
        attendance_status="present",
    )
    assert resp.status_code == 403
    assert _attendance(app, activity_id, part_id) is None


def test_anonymous_user_redirected_from_attendance(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    activity_id = _activity(app, admin_id)
    for url in ("/attendance", "/participants"):
        resp = client.get(url)
        assert resp.status_code == 302, url
        assert "/login" in resp.headers["Location"], url


# ---------------------------------------------------------------------------
# Event Participants (read-only module)
# ---------------------------------------------------------------------------


def test_roster_lists_only_accounts_with_registrations(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="joined@t.demo", full_name="Joined Person")
    make_user(ROLE_PARTICIPANT, email="silent@t.demo", full_name="Silent Person")
    activity_id = _activity(app, admin_id)
    joined_id = _user_ids(app)["joined@t.demo"]
    _register(app, activity_id, joined_id)

    login(client, "admin@t.demo", PW)
    html = client.get("/participants").data
    assert b"Joined Person" in html
    assert b"Silent Person" not in html


def test_roster_search_and_activity_filter(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    a_id = make_user(ROLE_PARTICIPANT, email="alpha@t.demo", full_name="Alpha Person")
    b_id = make_user(ROLE_PARTICIPANT, email="beta@t.demo", full_name="Beta Person")
    activity_one = _activity(app, admin_id, title="Only One")
    activity_two = _activity(app, admin_id, title="Only Two")
    _register(app, activity_one, a_id)
    _register(app, activity_two, b_id)

    login(client, "admin@t.demo", PW)
    search = client.get("/participants", query_string={"q": "alpha"}).data
    assert b"Alpha Person" in search and b"Beta Person" not in search

    filtered = client.get(
        "/participants", query_string={"activity_id": str(activity_one)}
    ).data
    assert b"Alpha Person" in filtered and b"Beta Person" not in filtered


def test_participant_detail_shows_registrations_and_attendance(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Part Person")
    activity_id = _activity(app, admin_id, title="Attendance Demo")
    part_id = _user_ids(app)["part@t.demo"]
    _register(app, activity_id, part_id)

    login(client, "admin@t.demo", PW)
    _post_attendance(client, activity_id, user_id=str(part_id), attendance_status="late")

    html = client.get(f"/participants/{part_id}").data
    assert b"Part Person" in html
    assert b"Attendance Demo" in html
    assert b"Late" in html
    # Read-only page: no <form> at all (base.html's logout form lives in the
    # sidebar and is rendered by a different template block).
    body = html.split(b"<main")[1]
    assert b"<form" not in body
    assert b"<input" not in body


def test_adviser_can_view_roster_but_not_edit(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    make_user(ROLE_PARTICIPANT, email="part@t.demo", full_name="Part Person")
    make_user(ROLE_ADVISER, email="adv@t.demo", password=PW)
    activity_id = _activity(app, admin_id)
    _register(app, activity_id, _user_ids(app)["part@t.demo"])

    login(client, "adv@t.demo", PW)
    assert client.get("/participants").status_code == 200
    assert b"Part Person" in client.get("/participants").data


def test_participant_cannot_open_roster_or_other_records(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo")
    me_id = make_user(ROLE_PARTICIPANT, email="me@t.demo", password=PW, full_name="Me Person")
    other_id = make_user(ROLE_PARTICIPANT, email="other@t.demo", full_name="Other Person")

    login(client, "me@t.demo", PW)
    assert client.get("/participants").status_code == 403
    assert client.get(f"/participants/{other_id}").status_code == 403
    assert client.get(f"/participants/{me_id}").status_code == 200
    logout(client)


def test_participant_detail_unknown_user_is_404(app, client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    assert client.get("/participants/99999").status_code == 404


def test_participants_module_link_is_live(app, client, make_user):
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    dash = client.get("/dashboard").data
    assert b"not implemented yet" not in client.get("/modules/participants").data
    assert b"Working" in dash
    assert client.get("/modules/participants", follow_redirects=True).status_code == 200


def test_participant_does_not_see_participants_module_link(app, client, make_user):
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW)
    login(client, "part@t.demo", PW)
    html = client.get("/dashboard").data
    assert b"/participants" not in html
    # Direct URL is still blocked server-side. The errors/403.html page is
    # returned without the sidebar, so the path cannot appear via navigation.
    assert client.get("/participants").status_code == 403

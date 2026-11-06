"""Attendance audit fields — `last_edited_by` / `last_edited_at`.

Approved behaviour under test
  * A newly created attendance row has BOTH `last_edited_*` fields NULL.
  * The first correction stamps `recorded_by`, `recorded_at`, `last_edited_by`,
    and `last_edited_at`.
  * A subsequent correction re-stamps all four to reflect the LATEST edit.
  * Preserving the original creation values is not required.
  * Existing role permissions and attendance validation are unchanged.

Runs against techis_test via the shared fixtures (the `positions`/attendance
schema comes from db.create_all() in the client fixture — no migration is run).
"""
from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models.activity import Activity, ActivityRegistration, AttendanceRecord
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, ROLE_PARTICIPANT

from .conftest import login, logout, post_csrf

PW = "Passw0rd!"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def setup(app, make_user):
    """An admin, a second manager (officer), a participant, and a published activity."""
    ids = {
        "admin": make_user(ROLE_ADMIN, email="admin@t.demo", password=PW, full_name="Ada Admin"),
        "officer": make_user(ROLE_OFFICER, email="off@t.demo", password=PW, full_name="Oscar Officer"),
        "adviser": make_user(ROLE_ADVISER, email="adv@t.demo", password=PW, full_name="Ana Adviser"),
        "participant": make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Pat Participant"),
    }
    with app.app_context():
        # NOTE: `_may_manage` lets an officer manage ONLY activities they
        # created, so the officer must own this activity for the correction
        # tests to exercise the route rather than a 403.
        activity = Activity(
            title="Audit Field Event",
            start_datetime=datetime.now(timezone.utc),
            end_datetime=datetime.now(timezone.utc).replace(hour=23),
            status="published",
            created_by=ids["officer"],
        )
        db.session.add(activity)
        db.session.flush()
        db.session.add(
            ActivityRegistration(activity_id=activity.id, user_id=ids["participant"])
        )
        db.session.commit()
        ids["activity"] = activity.id
    return ids


def _row(app, activity_id: int, user_id: int) -> AttendanceRecord:
    with app.app_context():
        return db.session.execute(
            db.select(AttendanceRecord).where(
                AttendanceRecord.activity_id == activity_id,
                AttendanceRecord.user_id == user_id,
            )
        ).scalar_one()


def _record(client, ids, status="present", **extra):
    data = {"user_id": str(ids["participant"]), "attendance_status": status}
    data.update(extra)
    # `None` means "omit the field" so the base status survives the override.
    if data.get("attendance_status") is None:
        data.pop("attendance_status")
    return post_csrf(
        client,
        f"/activities/{ids['activity']}/attendance",
        form_path=f"/activities/{ids['activity']}",
        **data,
    )


# ---------------------------------------------------------------------------
# 1. Creation leaves both fields NULL
# ---------------------------------------------------------------------------


def test_new_record_has_null_edit_fields(app, client, setup):
    login(client, "admin@t.demo", PW)
    resp = _record(client, setup)
    assert resp.status_code == 302

    row = _row(app, setup["activity"], setup["participant"])
    assert row.recorded_by == setup["admin"]
    assert row.recorded_at is not None
    assert row.last_edited_by is None
    assert row.last_edited_at is None


def test_walk_in_record_also_has_null_edit_fields(app, client, setup):
    """A row with no registration (walk-in) behaves identically.

    The walk-in is an active account that was NOT registered for the activity.
    """
    walk_in = setup["adviser"]  # staff account, but no registration row
    login(client, "admin@t.demo", PW)
    post_csrf(
        client,
        f"/activities/{setup['activity']}/attendance",
        form_path=f"/activities/{setup['activity']}",
        user_id=str(walk_in),
        attendance_status="late",
    )

    row = _row(app, setup["activity"], walk_in)
    assert row.registration_id is None
    assert row.last_edited_by is None
    assert row.last_edited_at is None


# ---------------------------------------------------------------------------
# 2. First correction stamps all four fields
# ---------------------------------------------------------------------------


def test_first_correction_stamps_all_four_fields(app, client, setup):
    login(client, "admin@t.demo", PW)
    _record(client, setup)
    created = _row(app, setup["activity"], setup["participant"])
    created_at = created.recorded_at

    # A different manager performs the correction, so recorded_by/last_edited_by
    # are observably distinct from the creator.
    logout(client)
    login(client, "off@t.demo", PW)
    _record(client, setup, status="late")

    row = _row(app, setup["activity"], setup["participant"])
    assert row.attendance_status == "late"
    assert row.recorded_by == setup["officer"]          # refreshed to the latest writer
    assert row.last_edited_by == setup["officer"]
    assert row.last_edited_at is not None
    assert row.recorded_at >= created_at                 # refreshed
    # Original creation values are not required to be preserved.
    assert row.recorded_by != setup["admin"]


# ---------------------------------------------------------------------------
# 3. A later correction re-stamps all four to the LATEST edit
# ---------------------------------------------------------------------------


def test_second_correction_restamps_to_the_latest_edit(app, client, setup):
    login(client, "admin@t.demo", PW)
    _record(client, setup)

    logout(client)
    login(client, "off@t.demo", PW)
    _record(client, setup, status="late")
    first_edit = _row(app, setup["activity"], setup["participant"])
    first_edited_at = first_edit.last_edited_at
    assert first_edit.last_edited_by == setup["officer"]

    logout(client)
    login(client, "admin@t.demo", PW)
    _record(client, setup, status="excused", remarks="Corrected again")

    row = _row(app, setup["activity"], setup["participant"])
    assert row.attendance_status == "excused"
    assert row.recorded_by == setup["admin"]             # latest writer
    assert row.last_edited_by == setup["admin"]          # latest editor, not the first
    # The timestamp follows the most recent correction. (>= rather than >
    # because two edits can land in the same clock tick.)
    assert row.last_edited_at >= first_edited_at
    assert row.last_edited_by != first_edit.last_edited_by


def test_same_user_repeated_edits_keep_updating_timestamp(app, client, setup):
    """Even with one editor, the timestamp follows the most recent correction."""
    login(client, "admin@t.demo", PW)
    _record(client, setup)

    _record(client, setup, status="late")
    first = _row(app, setup["activity"], setup["participant"]).last_edited_at

    _record(client, setup, status="absent")
    row = _row(app, setup["activity"], setup["participant"])
    assert row.attendance_status == "absent"
    assert row.last_edited_by == setup["admin"]
    assert row.last_edited_at >= first


def test_editing_again_does_not_create_a_second_row(app, client, setup):
    login(client, "admin@t.demo", PW)
    _record(client, setup)
    _record(client, setup, status="late")
    _record(client, setup, status="excused")

    with app.app_context():
        count = db.session.execute(
            db.select(db.func.count(AttendanceRecord.id)).where(
                AttendanceRecord.activity_id == setup["activity"]
            )
        ).scalar()
    assert count == 1


# ---------------------------------------------------------------------------
# 4. Role permissions unchanged
# ---------------------------------------------------------------------------


def test_adviser_still_cannot_record_attendance(app, client, setup):
    login(client, "adv@t.demo", PW)
    resp = _record(client, setup)
    assert resp.status_code == 403
    with app.app_context():
        assert db.session.execute(
            db.select(db.func.count(AttendanceRecord.id))
        ).scalar() == 0


def test_participant_still_cannot_record_attendance(app, client, setup):
    login(client, "part@t.demo", PW)
    resp = _record(client, setup)
    assert resp.status_code == 403


def test_officer_cannot_record_on_another_officers_activity(app, client, make_user, setup):
    """Ownership still restricts officers to activities they created."""
    outsider = make_user(ROLE_OFFICER, email="other@t.demo", password=PW)
    with app.app_context():
        activity = db.session.get(Activity, setup["activity"])
        assert activity.created_by == setup["officer"]
        assert activity.created_by != outsider
    login(client, "other@t.demo", PW)
    resp = _record(client, setup)
    assert resp.status_code == 403


def test_admin_can_correct_an_officers_record(app, client, setup):
    login(client, "off@t.demo", PW)
    _record(client, setup)
    logout(client)
    login(client, "admin@t.demo", PW)
    assert _record(client, setup, status="late").status_code == 302

    row = _row(app, setup["activity"], setup["participant"])
    assert row.attendance_status == "late"
    assert row.recorded_by == setup["admin"]
    assert row.last_edited_by == setup["admin"]
    assert row.last_edited_at is not None


# ---------------------------------------------------------------------------
# 5. Validation unchanged (no audit fields written on rejected input)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload,message",
    [
        ({"attendance_status": "maybe"}, b"Select a valid attendance status"),
        (
            {"attendance_status": "present", "time_in": "not-a-date"},
            b"Time in is not a valid date/time",
        ),
        (
            {
                "attendance_status": "present",
                "time_in": "2026-03-01T10:00",
                "time_out": "2026-03-01T09:00",
            },
            b"Time out cannot be earlier than time in",
        ),
    ],
)
def test_invalid_correction_leaves_audit_fields_untouched(
    app, client, setup, payload, message
):
    login(client, "admin@t.demo", PW)
    _record(client, setup, status="late")
    before = _row(app, setup["activity"], setup["participant"])

    resp = post_csrf(
        client,
        f"/activities/{setup['activity']}/attendance",
        form_path=f"/activities/{setup['activity']}",
        user_id=str(setup["participant"]),
        follow=True,
        **payload,
    )
    assert message in resp.data
    assert b"Attendance recorded" not in resp.data

    after = _row(app, setup["activity"], setup["participant"])
    assert after.attendance_status == "late"
    assert (after.last_edited_by, after.last_edited_at) == (None, None)
    assert (after.recorded_by, after.recorded_at) == (before.recorded_by, before.recorded_at)


def test_attendance_rejected_for_draft_activity(app, client, setup):
    with app.app_context():
        activity = db.session.get(Activity, setup["activity"])
        activity.status = "draft"
        db.session.commit()

    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client,
        f"/activities/{setup['activity']}/attendance",
        form_path=f"/activities/{setup['activity']}",
        user_id=str(setup["participant"]),
        attendance_status="present",
        follow=True,
    )
    assert b"Attendance cannot be recorded" in resp.data
    with app.app_context():
        assert db.session.execute(
            db.select(db.func.count(AttendanceRecord.id))
        ).scalar() == 0


# ---------------------------------------------------------------------------
# 6. Schema shape
# ---------------------------------------------------------------------------


def test_model_exposes_the_new_columns():
    columns = {c.name: c for c in AttendanceRecord.__table__.columns}
    assert "last_edited_by" in columns
    assert "last_edited_at" in columns
    assert columns["last_edited_by"].nullable is True
    assert columns["last_edited_at"].nullable is True
    # No server default: untouched rows stay NULL.
    assert columns["last_edited_by"].default is None
    assert columns["last_edited_at"].default is None
    # Existing audit fields are unchanged in shape.
    assert columns["recorded_by"].nullable is False
    assert columns["recorded_at"].nullable is False


def test_statuses_and_uniqueness_unchanged():
    assert AttendanceRecord.STATUSES == ("present", "late", "absent", "excused")
    names = {
        c.name
        for c in AttendanceRecord.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert "uq_att_activity_user" in names

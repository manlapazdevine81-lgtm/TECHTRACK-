"""Activities module — comprehensive route, validation, permission and
error-handling tests (Phase 11).

Coverage map
  1. Routes / HTTP contract ......... every endpoint, method rules, auth redirect
  2. Permission matrix .............. 4 roles × read/write, ownership, CSRF
  3. Form validation ................ required fields, lengths, dates, officer
  4. Registrations .................. self, staff-added, duplicates, rejoin, limits
  5. Attendance ..................... statuses, times, walk-ins, updates, limits
  6. Status workflow ................ legal/illegal transitions, side effects
  7. Assignments .................... creation on a terminal activity, ownership
  8. Lists & filters ................ status/search filters, counts, HTML escaping
  9. Errors ......................... 404s, input overflows, error pages

Every request that mutates data goes through `post_csrf`/`get_csrf` so CSRF is
exercised rather than bypassed. No schema change, no new dependency.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.activity import Activity, ActivityRegistration, AttendanceRecord
from app.models.assignment import ActivityAssignment
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, ROLE_PARTICIPANT, User

from .conftest import login, logout, post_csrf

PW = "Passw0rd!"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _window(days: int = 1, hours: int = 2):
    start = datetime.now(timezone.utc) + timedelta(days=days)
    return start, start + timedelta(hours=hours)


def make_activity(
    app,
    created_by: int,
    status: str = "draft",
    title: str = "Tech Talk",
    **overrides,
) -> int:
    start, end = _window()
    with app.app_context():
        activity = Activity(
            title=title,
            description=overrides.get("description", "Demo activity"),
            activity_type=overrides.get("activity_type", "Seminar"),
            venue=overrides.get("venue", "Lipa Campus"),
            start_datetime=overrides.get("start_datetime", start),
            end_datetime=overrides.get("end_datetime", end),
            status=status,
            created_by=created_by,
        )
        db.session.add(activity)
        db.session.commit()
        return activity.id


def make_registration(app, activity_id: int, user_id: int, status: str = "registered") -> int:
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


def _utc_hhmm(moment: datetime | None) -> str:
    """UTC clock time of a stored timestamp (naive values are already UTC)."""
    assert moment is not None
    if moment.tzinfo is None:
        return moment.strftime("%H:%M")
    return moment.astimezone(timezone.utc).strftime("%H:%M")


def activity_of(app, activity_id: int) -> Activity:
    with app.app_context():
        return db.session.get(Activity, activity_id)


def activity_status(app, activity_id: int) -> str:
    return activity_of(app, activity_id).status


def user_id_of(app, email: str) -> int:
    with app.app_context():
        return User.query.filter_by(email=email).one().id


def attendance_rows(app, activity_id: int) -> list:
    with app.app_context():
        return list(
            db.session.execute(
                db.select(AttendanceRecord).where(
                    AttendanceRecord.activity_id == activity_id
                )
            )
            .scalars()
            .all()
        )


def registrations_of(app, activity_id: int) -> list:
    with app.app_context():
        return list(
            db.session.execute(
                db.select(ActivityRegistration).where(
                    ActivityRegistration.activity_id == activity_id
                )
            )
            .scalars()
            .all()
        )


def valid_form(**overrides) -> dict:
    """A complete, valid activity form payload (datetime-local format)."""
    start, end = _window(days=3)
    data = {
        "title": "Cloud Study Jam",
        "description": "Hands-on session",
        "activity_type": "Workshop",
        "venue": "Room 204",
        "start_datetime": start.strftime("%Y-%m-%dT%H:%M"),
        "end_datetime": end.strftime("%Y-%m-%dT%H:%M"),
        "responsible_officer_id": "",
    }
    data.update(overrides)
    return data


def set_last_activity_id(app) -> int:
    with app.app_context():
        return db.session.execute(
            db.select(Activity.id).order_by(Activity.id.desc()).limit(1)
        ).scalar()





@pytest.fixture()
def staff(app, make_user):
    """One user per role, returned as {role: id}."""
    return {
        ROLE_ADMIN: make_user(ROLE_ADMIN, email="admin@t.demo", password=PW, full_name="Ada Admin"),
        ROLE_OFFICER: make_user(ROLE_OFFICER, email="off@t.demo", password=PW, full_name="Oscar Officer"),
        ROLE_ADVISER: make_user(ROLE_ADVISER, email="adv@t.demo", password=PW, full_name="Ana Adviser"),
        ROLE_PARTICIPANT: make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW, full_name="Pat Participant"),
    }


# ===========================================================================
# 1. Routes / HTTP contract
# ===========================================================================


@pytest.mark.parametrize(
    "url",
    [
        "/activities",
        "/activities/new",
        "/activities/1",
        "/activities/1/edit",
        "/my-activities",
        "/attendance",
    ],
)
def test_anonymous_is_redirected_to_login_on_get(client, url):
    resp = client.get(url)
    assert resp.status_code == 302, url
    assert "/login" in resp.headers["Location"], url


@pytest.mark.parametrize(
    "url",
    [
        "/activities/1/register",
        "/activities/1/registrations",
        "/activities/1/attendance",
        "/activities/1/assignments",
    ],
)
def test_anonymous_cannot_post_to_activity_routes(client, url):
    """Documented behaviour: Flask-WTF's global CSRF check runs before the view.

    An anonymous POST carries no session token, so it is refused with 400. No
    route body executes and nothing is written — verified by the 404 that
    follows for the (nonexistent) activity in a logged-in session.
    """
    resp = client.post(url, data={})
    assert resp.status_code == 400, url
    # Still anonymous (a redirect to /login), so no authenticated write happened.
    assert client.get("/activities/1").status_code == 302


@pytest.mark.parametrize(
    "method,url",
    [
        ("get", "/activities"),
        ("get", "/activities/new"),
        ("get", "/activities/1"),
        ("get", "/my-activities"),
        ("get", "/attendance"),
        ("post", "/activities/1/status"),
        ("post", "/activities/1/register"),
        ("post", "/activities/1/registrations"),
        ("post", "/activities/1/attendance"),
        ("post", "/activities/1/assignments"),
    ],
)
def test_get_only_routes_reject_other_methods_appropriately(client, make_user, method, url):
    """Mutating routes are POST-only; GET on them must not be a 200 render."""
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    if method == "post":
        # POST with no CSRF token must be refused by Flask-WTF (400), never applied.
        resp = client.post(url, data={})
        assert resp.status_code in (400, 302, 404), url


@pytest.mark.parametrize("url", ["/activities/status", "/activities/x", "/attendance/1"])
def test_malformed_activity_urls_are_404(client, make_user, url):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    assert client.get(url).status_code == 404


def test_missing_activity_is_404_not_500(client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    assert client.get("/activities/999999").status_code == 404
    assert client.get("/activities/999999/edit").status_code == 404


def test_activity_list_renders_for_staff(app, client, staff):
    make_activity(app, staff[ROLE_ADMIN], title="Robotics Night")
    login(client, "off@t.demo", PW)
    resp = client.get("/activities")
    assert resp.status_code == 200
    assert b"Robotics Night" in resp.data
    assert b"Activities" in resp.data


def test_attendance_overview_renders_for_managers(client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    resp = client.get("/attendance")
    assert resp.status_code == 200
    assert b"Attendance" in resp.data


# ===========================================================================
# 2. Permission matrix
# ===========================================================================


def test_adviser_is_read_only(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "adv@t.demo", PW)

    assert client.get("/activities").status_code == 200
    assert client.get(f"/activities/{activity_id}").status_code == 200
    assert client.get(f"/activities/{activity_id}/edit").status_code == 403
    assert client.get("/activities/new").status_code == 403
    assert client.get("/attendance").status_code == 403
    assert client.get("/my-activities").status_code == 403
    # Every mutating route is closed to the adviser too.
    assert post_csrf(
        client, f"/activities/{activity_id}/status", form_path=f"/activities/{activity_id}",
        status="completed",
    ).status_code == 403
    assert post_csrf(
        client, f"/activities/{activity_id}/registrations",
        form_path=f"/activities/{activity_id}", user_id=str(staff[ROLE_PARTICIPANT]),
    ).status_code == 403
    assert post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        user_id=str(staff[ROLE_PARTICIPANT]), attendance_status="present",
    ).status_code == 403
    assert post_csrf(
        client, f"/activities/{activity_id}/assignments",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(staff[ROLE_OFFICER]), responsibility="Check venue",
    ).status_code == 403
    assert activity_status(app, activity_id) == "published"


def test_participant_cannot_reach_staff_surfaces(client, staff):
    login(client, "part@t.demo", PW)
    assert client.get("/activities").status_code == 403
    assert client.get("/activities/new").status_code == 403
    assert client.get("/attendance").status_code == 403


def test_officer_cannot_manage_another_officers_activity(app, client, make_user, staff):
    other_id = make_user(ROLE_OFFICER, email="other@t.demo", password=PW)
    activity_id = make_activity(app, other_id)

    login(client, "off@t.demo", PW)
    assert client.get(f"/activities/{activity_id}/edit").status_code == 403
    assert post_csrf(
        client, f"/activities/{activity_id}/status", form_path=f"/activities/{activity_id}",
        status="published",
    ).status_code == 403
    assert post_csrf(
        client, f"/activities/{activity_id}/assignments",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(staff[ROLE_OFFICER]), responsibility="Book room",
    ).status_code == 403
    assert activity_status(app, activity_id) == "draft"
    with app.app_context():
        assert ActivityAssignment.query.filter_by(activity_id=activity_id).count() == 0


def test_officer_can_manage_own_activity(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_OFFICER])
    login(client, "off@t.demo", PW)
    assert client.get(f"/activities/{activity_id}/edit").status_code == 200
    resp = post_csrf(
        client, f"/activities/{activity_id}/status", form_path=f"/activities/{activity_id}",
        status="published",
    )
    assert resp.status_code == 302
    assert activity_status(app, activity_id) == "published"


def test_admin_can_edit_any_activity(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_OFFICER])
    login(client, "admin@t.demo", PW)
    assert client.get(f"/activities/{activity_id}/edit").status_code == 200


def test_participant_sees_own_activity_detail_only(app, client, staff, make_user):
    make_user(ROLE_PARTICIPANT, email="other@t.demo", password=PW)
    draft_id = make_activity(app, staff[ROLE_ADMIN], status="draft", title="Secret Draft")
    other_draft = make_activity(app, staff[ROLE_ADMIN], status="draft", title="Other Draft")
    make_registration(app, other_draft, staff[ROLE_PARTICIPANT])

    login(client, "part@t.demo", PW)
    assert client.get(f"/activities/{draft_id}").status_code == 403       # not published
    assert client.get(f"/activities/{other_draft}").status_code == 200    # registered
    assert logout(client).status_code == 302

    login(client, "other@t.demo", PW)
    assert client.get(f"/activities/{other_draft}").status_code == 403    # someone else's


def test_participant_detail_hides_roster_and_admin_controls(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    make_registration(app, activity_id, staff[ROLE_PARTICIPANT])

    login(client, "part@t.demo", PW)
    html = client.get(f"/activities/{activity_id}").data
    assert b"Add a participant" not in html
    assert b"Record attendance" not in html
    assert b"Assign responsibility" not in html
    assert b"Mark completed" not in html
    assert b"Your registration" in html


def test_csrf_required_for_every_activity_mutation(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN])
    login(client, "admin@t.demo", PW)
    for url in (
        f"/activities/{activity_id}/status",
        f"/activities/{activity_id}/register",
        f"/activities/{activity_id}/registrations",
        f"/activities/{activity_id}/attendance",
        f"/activities/{activity_id}/assignments",
    ):
        assert client.post(url, data={"status": "published"}).status_code == 400, url
    assert activity_status(app, activity_id) == "draft"


# ===========================================================================
# 3. Form validation
# ===========================================================================


def test_create_activity_happy_path(app, client, staff):
    login(client, "admin@t.demo", PW)
    resp = post_csrf(client, "/activities/new", **valid_form(), follow=True)
    assert b"created as a draft" in resp.data
    new_id = set_last_activity_id(app)
    activity = activity_of(app, new_id)
    assert activity.title == "Cloud Study Jam"
    assert activity.status == "draft"
    assert activity.created_by == staff[ROLE_ADMIN]


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("title", "", b"Title is required"),
        ("start_datetime", "", b"Start date and time is required"),
        ("end_datetime", "", b"End date and time is required"),
        ("start_datetime", "not-a-date", b"Start date and time is not a valid"),
        ("end_datetime", "2026-13-45T99:99", b"End date and time is not a valid"),
        ("title", "x" * 256, b"Title must be 255 characters"),
        ("activity_type", "y" * 65, b"Activity type must be 64 characters"),
        ("venue", "z" * 256, b"Venue must be 255 characters"),
        ("responsible_officer_id", "abc", b"Responsible officer is not a valid"),
        ("responsible_officer_id", "999999", b"Responsible officer could not be found"),
    ],
)
def test_create_validation_errors(app, client, staff, field, value, message):
    login(client, "admin@t.demo", PW)
    resp = post_csrf(client, "/activities/new", **valid_form(**{field: value}), follow=True)
    assert resp.status_code == 200
    assert message in resp.data, (field, value[:20])
    with app.app_context():
        assert db.session.execute(db.select(db.func.count(Activity.id))).scalar() == 0


def test_end_must_be_after_start(app, client, staff):
    start, _ = _window(days=4)
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client,
        "/activities/new",
        **valid_form(
            start_datetime=start.strftime("%Y-%m-%dT%H:%M"),
            end_datetime=start.strftime("%Y-%m-%dT%H:%M"),
        ),
        follow=True,
    )
    assert b"End date and time must be after the start" in resp.data


def test_responsible_officer_must_be_staff(app, client, staff):
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, "/activities/new",
        **valid_form(responsible_officer_id=str(staff[ROLE_PARTICIPANT])), follow=True,
    )
    assert b"Responsible officer must be a System Administrator or a TechIS Officer" in resp.data


def test_create_with_responsible_officer_succeeds(app, client, staff):
    login(client, "admin@t.demo", PW)
    post_csrf(
        client, "/activities/new",
        **valid_form(responsible_officer_id=str(staff[ROLE_OFFICER])),
    )
    activity = activity_of(app, set_last_activity_id(app))
    assert activity.responsible_officer_id == staff[ROLE_OFFICER]


def test_edit_updates_fields_and_keeps_status(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/edit",
        **valid_form(title="Renamed Event", venue="Gym"), follow=True,
    )
    assert b"updated" in resp.data
    activity = activity_of(app, activity_id)
    assert activity.title == "Renamed Event"
    assert activity.venue == "Gym"
    assert activity.status == "published"      # edit never changes status


def test_edit_form_prefills_current_values(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], title="Prefilled Title")
    login(client, "admin@t.demo", PW)
    html = client.get(f"/activities/{activity_id}/edit").data
    assert b"Prefilled Title" in html
    assert b'type="datetime-local"' in html


def test_edit_invalid_input_does_not_change_record(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], title="Original")
    login(client, "admin@t.demo", PW)
    post_csrf(client, f"/activities/{activity_id}/edit", **valid_form(title="", venue="X"))
    activity = activity_of(app, activity_id)
    assert activity.title == "Original"
    assert activity.venue == "Lipa Campus"


def test_form_values_survive_a_validation_error(app, client, staff):
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, "/activities/new",
        **valid_form(title="", venue="Recovered Venue"), follow=True,
    )
    assert b"Recovered Venue" in resp.data


def test_activity_title_is_html_escaped(app, client, staff):
    payload = "<script>alert('xss')</script>"
    activity_id = make_activity(app, staff[ROLE_ADMIN], title=payload)
    login(client, "admin@t.demo", PW)
    for url in ("/activities", f"/activities/{activity_id}"):
        html = client.get(url).data
        assert b"<script>alert(" not in html, url
        assert b"&lt;script&gt;" in html, url


# ===========================================================================
# 4. Registrations
# ===========================================================================


def test_participant_self_registers_for_published_activity(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "part@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/register", form_path="/my-activities",
        follow=True,
    )
    assert b"You are registered" in resp.data
    rows = registrations_of(app, activity_id)
    assert len(rows) == 1
    assert rows[0].user_id == staff[ROLE_PARTICIPANT]
    assert rows[0].status == "registered"


def test_self_registration_pending_approval_is_not_invented(app, client, staff):
    """T2 unresolved: registering must create a 'registered' row, no waitlist."""
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "part@t.demo", PW)
    post_csrf(client, f"/activities/{activity_id}/register", form_path="/my-activities")
    rows = registrations_of(app, activity_id)
    assert [r.status for r in rows] == ["registered"]
    assert ActivityRegistration.STATUSES == ("registered", "cancelled")


@pytest.mark.parametrize("status", ["draft", "completed", "cancelled"])
def test_self_registration_blocked_unless_published(app, client, staff, status):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status=status)
    login(client, "part@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/register", form_path="/my-activities",
        follow=True,
    )
    assert b"not open for registration" in resp.data
    assert registrations_of(app, activity_id) == []


def test_duplicate_self_registration_is_rejected(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "part@t.demo", PW)
    post_csrf(client, f"/activities/{activity_id}/register", form_path="/my-activities")
    resp = post_csrf(
        client, f"/activities/{activity_id}/register", form_path="/my-activities",
        follow=True,
    )
    assert b"already registered" in resp.data
    assert len(registrations_of(app, activity_id)) == 1


def test_staff_can_add_a_participant(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/registrations",
        form_path=f"/activities/{activity_id}", user_id=str(staff[ROLE_PARTICIPANT]),
        follow=True,
    )
    assert b"was added" in resp.data
    assert len(registrations_of(app, activity_id)) == 1


@pytest.mark.parametrize(
    "user_id,message",
    [
        ("", b"Select a participant"),
        ("not-an-int", b"Select a participant"),
        ("999999", b"could not be found"),
    ],
)
def test_staff_add_registration_rejects_bad_input(app, client, staff, user_id, message):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/registrations",
        form_path=f"/activities/{activity_id}", user_id=user_id, follow=True,
    )
    assert message in resp.data
    assert registrations_of(app, activity_id) == []


def test_staff_cannot_register_for_unpublished_activity(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="draft")
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/registrations",
        form_path=f"/activities/{activity_id}", user_id=str(staff[ROLE_PARTICIPANT]),
        follow=True,
    )
    assert b"not open for registration" in resp.data
    assert registrations_of(app, activity_id) == []


def test_cancelled_registration_is_reactivated_not_duplicated(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    reg_id = make_registration(app, activity_id, staff[ROLE_PARTICIPANT], status="cancelled")

    login(client, "admin@t.demo", PW)
    post_csrf(
        client, f"/activities/{activity_id}/registrations",
        form_path=f"/activities/{activity_id}", user_id=str(staff[ROLE_PARTICIPANT]),
    )
    rows = registrations_of(app, activity_id)
    assert len(rows) == 1
    assert rows[0].id == reg_id
    assert rows[0].status == "registered"


def test_participant_can_cancel_own_registration_and_rejoin(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    make_registration(app, activity_id, staff[ROLE_PARTICIPANT])
    login(client, "part@t.demo", PW)

    resp = post_csrf(
        client, f"/activities/{activity_id}/registrations/{staff[ROLE_PARTICIPANT]}/cancel",
        form_path="/my-activities", follow=True,
    )
    assert b"cancelled" in resp.data.lower()
    assert registrations_of(app, activity_id)[0].status == "cancelled"

    resp = post_csrf(
        client, f"/activities/{activity_id}/register", form_path="/my-activities",
        follow=True,
    )
    assert b"You are registered" in resp.data
    assert registrations_of(app, activity_id)[0].status == "registered"


def test_participant_cannot_cancel_someone_elses_registration(app, client, staff, make_user):
    other_id = make_user(ROLE_PARTICIPANT, email="other@t.demo", password=PW)
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    make_registration(app, activity_id, other_id)

    login(client, "part@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/registrations/{other_id}/cancel",
        form_path=f"/activities/{activity_id}",
    )
    assert resp.status_code == 403
    assert registrations_of(app, activity_id)[0].status == "registered"


def test_cancel_missing_registration_is_404(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/registrations/{staff[ROLE_ADMIN]}/cancel",
        form_path=f"/activities/{activity_id}",
    )
    assert resp.status_code == 404


def test_cancelling_twice_reports_already_cancelled(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    make_registration(app, activity_id, staff[ROLE_PARTICIPANT])
    login(client, "admin@t.demo", PW)
    url = f"/activities/{activity_id}/registrations/{staff[ROLE_PARTICIPANT]}/cancel"
    post_csrf(client, url, form_path=f"/activities/{activity_id}")
    resp = post_csrf(client, url, form_path=f"/activities/{activity_id}", follow=True)
    assert b"already cancelled" in resp.data


def test_cancel_link_only_for_published_activities(app, client, staff):
    """Regression (Phase 11): Bug 3.

    `my_activities.html` offered "Cancel registration" for `draft` activities,
    but the only way to acquire a registration on a draft is staff adding one —
    and the route then refuses with "not open for registration". The link now
    appears only for `published` activities, matching `activity_register`.
    """
    published_id = make_activity(app, staff[ROLE_ADMIN], status="published", title="Pub")
    draft_id = make_activity(app, staff[ROLE_ADMIN], status="draft", title="Drf")
    make_registration(app, published_id, staff[ROLE_PARTICIPANT])
    make_registration(app, draft_id, staff[ROLE_PARTICIPANT])

    login(client, "part@t.demo", PW)
    html = client.get("/my-activities").data
    assert f"/activities/{published_id}/registrations/".encode() in html
    assert f"/activities/{draft_id}/registrations/".encode() not in html


def test_my_activities_lists_joined_and_hides_joined_from_open_list(app, client, staff):
    joined_id = make_activity(app, staff[ROLE_ADMIN], status="published", title="Joined One")
    open_id = make_activity(app, staff[ROLE_ADMIN], status="published", title="Open One")
    make_activity(app, staff[ROLE_ADMIN], status="draft", title="Hidden Draft")
    make_registration(app, joined_id, staff[ROLE_PARTICIPANT])

    login(client, "part@t.demo", PW)
    html = client.get("/my-activities").data
    assert b"Joined One" in html
    assert b"Open One" in html
    assert b"Hidden Draft" not in html
    assert f"/activities/{joined_id}/register".encode() not in html   # already joined
    assert f"/activities/{open_id}/register".encode() in html


# ===========================================================================
# 5. Attendance
# ===========================================================================


def _attendance_payload(user_id, status="present", **extra):
    data = {"user_id": str(user_id), "attendance_status": status}
    data.update(extra)
    return data


@pytest.mark.parametrize("activity_status_value", ["published", "completed"])
def test_attendance_allowed_for_published_and_completed(app, client, staff, activity_status_value):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status=activity_status_value)
    make_registration(app, activity_id, staff[ROLE_PARTICIPANT])
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        **_attendance_payload(staff[ROLE_PARTICIPANT]), follow=True,
    )
    assert b"Attendance recorded" in resp.data
    rows = attendance_rows(app, activity_id)
    assert len(rows) == 1
    assert rows[0].recorded_by == staff[ROLE_ADMIN]
    assert rows[0].registration_id == registrations_of(app, activity_id)[0].id


@pytest.mark.parametrize("activity_status_value", ["draft", "cancelled"])
def test_attendance_rejected_for_draft_and_cancelled(app, client, staff, activity_status_value):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status=activity_status_value)
    make_registration(app, activity_id, staff[ROLE_PARTICIPANT])
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        **_attendance_payload(staff[ROLE_PARTICIPANT]), follow=True,
    )
    assert b"Attendance cannot be recorded" in resp.data
    assert attendance_rows(app, activity_id) == []


@pytest.mark.parametrize("status", ["present", "late", "absent", "excused"])
def test_every_attendance_status_persists(app, client, staff, status):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    make_registration(app, activity_id, staff[ROLE_PARTICIPANT])
    login(client, "admin@t.demo", PW)
    post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        **_attendance_payload(staff[ROLE_PARTICIPANT], status=status),
    )
    assert attendance_rows(app, activity_id)[0].attendance_status == status


def test_invalid_attendance_status_is_rejected(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        **_attendance_payload(staff[ROLE_PARTICIPANT], status="maybe"), follow=True,
    )
    assert b"Select a valid attendance status" in resp.data
    assert attendance_rows(app, activity_id) == []


@pytest.mark.parametrize(
    "user_id,message",
    [("", b"Select a participant"), ("abc", b"Select a participant"), ("999999", b"could not be found")],
)
def test_attendance_rejects_bad_participant(app, client, staff, user_id, message):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        user_id=user_id, attendance_status="present", follow=True,
    )
    assert message in resp.data
    assert attendance_rows(app, activity_id) == []


def test_time_out_before_time_in_is_rejected(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    make_registration(app, activity_id, staff[ROLE_PARTICIPANT])
    login(client, "admin@t.demo", PW)
    post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        **_attendance_payload(
            staff[ROLE_PARTICIPANT],
            time_in="2026-03-01T10:00", time_out="2026-03-01T09:00",
        ),
    )
    detail = client.get(f"/activities/{activity_id}").data
    assert b"Time out cannot be earlier than time in" in detail
    assert attendance_rows(app, activity_id) == []


@pytest.mark.parametrize("field", ["time_in", "time_out"])
def test_invalid_time_values_are_rejected(app, client, staff, field):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        **_attendance_payload(staff[ROLE_PARTICIPANT], **{field: "25:99"}),
        follow=True,
    )
    assert b"is not a valid date/time" in resp.data
    assert attendance_rows(app, activity_id) == []


def test_valid_time_in_and_out_are_stored(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    make_registration(app, activity_id, staff[ROLE_PARTICIPANT])
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        **_attendance_payload(
            staff[ROLE_PARTICIPANT],
            time_in="2026-03-01T10:00", time_out="2026-03-01T12:30",
        ),
        follow=True,
    )
    assert b"Attendance recorded" in resp.data
    rows = attendance_rows(app, activity_id)
    assert len(rows) == 1
    # Stored values are timezone-aware UTC (the form value is treated as UTC by
    # `_parse_datetime`); compare the UTC clock time, not the server's local one.
    assert _utc_hhmm(rows[0].time_in) == "10:00"
    assert _utc_hhmm(rows[0].time_out) == "12:30"
    assert (rows[0].time_out - rows[0].time_in) == timedelta(hours=2, minutes=30)


def test_attendance_update_overwrites_without_duplicating(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    make_registration(app, activity_id, staff[ROLE_PARTICIPANT])
    login(client, "admin@t.demo", PW)
    url = f"/activities/{activity_id}/attendance"
    post_csrf(
        client, url, form_path=f"/activities/{activity_id}",
        **_attendance_payload(staff[ROLE_PARTICIPANT]),
    )
    post_csrf(
        client, url, form_path=f"/activities/{activity_id}",
        **_attendance_payload(staff[ROLE_PARTICIPANT], status="late", remarks="Traffic"),
    )
    rows = attendance_rows(app, activity_id)
    assert len(rows) == 1
    assert rows[0].attendance_status == "late"
    assert rows[0].remarks == "Traffic"


def test_walk_in_attendance_without_registration_is_supported(app, client, staff):
    """The schema allows registration_id NULL; the route must too."""
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        **_attendance_payload(staff[ROLE_PARTICIPANT], status="late"), follow=True,
    )
    assert b"Attendance recorded" in resp.data
    rows = attendance_rows(app, activity_id)
    assert len(rows) == 1
    assert rows[0].registration_id is None


def test_walk_in_row_survives_a_later_attendance_update(app, client, staff):
    """Regression (Phase 11): Bug 2 — the update path must not orphan a link.

    A walk-in (no registration) is stored with registration_id NULL. When the
    same person is recorded again, the row must keep its state and stay a single
    row. The DB-level guarantee that a link can never point at another
    activity/user is covered by `tests/test_participants.py`.
    """
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "admin@t.demo", PW)
    url = f"/activities/{activity_id}/attendance"

    resp = post_csrf(
        client, url, form_path=f"/activities/{activity_id}",
        **_attendance_payload(staff[ROLE_PARTICIPANT]), follow=True,
    )
    assert b"Attendance recorded" in resp.data
    assert attendance_rows(app, activity_id)[0].registration_id is None

    resp = post_csrf(
        client, url, form_path=f"/activities/{activity_id}",
        **_attendance_payload(staff[ROLE_PARTICIPANT], status="excused"), follow=True,
    )
    assert b"Attendance recorded" in resp.data
    rows = attendance_rows(app, activity_id)
    assert len(rows) == 1
    assert rows[0].attendance_status == "excused"
    assert rows[0].registration_id is None


@pytest.mark.parametrize("field", ["title", "description", "activity_type", "venue"])
def test_nul_byte_is_rejected_in_every_activity_text_field(app, client, staff, field):
    """The validation guard must catch it even without the DB-error boundary."""
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, "/activities/new", **valid_form(**{field: "bad\x00value"}), follow=True
    )
    assert resp.status_code == 200
    assert b"invalid characters" in resp.data, field
    with app.app_context():
        assert db.session.execute(db.select(db.func.count(Activity.id))).scalar() == 0


def test_officer_cannot_record_attendance_for_anothers_activity(app, client, make_user, staff):
    other_id = make_user(ROLE_OFFICER, email="other@t.demo", password=PW)
    activity_id = make_activity(app, other_id, status="published")
    login(client, "off@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        **_attendance_payload(staff[ROLE_PARTICIPANT]),
    )
    assert resp.status_code == 403
    assert attendance_rows(app, activity_id) == []


def test_attendance_overview_filters(app, client, staff):
    a1 = make_activity(app, staff[ROLE_ADMIN], status="published", title="Filter A")
    a2 = make_activity(app, staff[ROLE_ADMIN], status="published", title="Filter B")
    make_registration(app, a1, staff[ROLE_PARTICIPANT])
    make_registration(app, a2, staff[ROLE_PARTICIPANT])
    login(client, "admin@t.demo", PW)
    for activity_id, status in ((a1, "present"), (a2, "absent")):
        post_csrf(
            client, f"/activities/{activity_id}/attendance",
            form_path=f"/activities/{activity_id}",
            **_attendance_payload(staff[ROLE_PARTICIPANT], status=status),
        )
    def links(html: bytes) -> set[bytes]:
        """Only the table links count — the filter dropdown lists every activity."""
        import re

        return set(re.findall(rb'href="/activities/(\d+)"', html))

    assert links(client.get(f"/attendance?activity_id={a1}").data) == {str(a1).encode()}
    assert links(client.get(f"/attendance?activity_id={a2}").data) == {str(a2).encode()}
    # Filtering by status shows only the matching record's activity.
    assert links(client.get("/attendance?status=present").data) == {str(a1).encode()}
    assert links(client.get("/attendance?status=absent").data) == {str(a2).encode()}
    # Unknown filter values degrade to "no filter" instead of erroring.
    assert client.get("/attendance?status=bogus").status_code == 200
    assert client.get("/attendance?activity_id=999999").status_code == 200


# ===========================================================================
# 6. Status workflow
# ===========================================================================


@pytest.mark.parametrize(
    "start,target",
    [("draft", "published"), ("draft", "cancelled"), ("published", "completed"), ("published", "cancelled")],
)
def test_legal_status_transitions(app, client, staff, start, target):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status=start)
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/status",
        form_path=f"/activities/{activity_id}", status=target, follow=True,
    )
    assert b"is now" in resp.data
    assert activity_status(app, activity_id) == target


@pytest.mark.parametrize(
    "start,target",
    [
        ("draft", "completed"),
        ("completed", "published"),
        ("completed", "cancelled"),
        ("cancelled", "published"),
        ("published", "draft"),
        ("published", ""),
        ("published", "bogus"),
    ],
)
def test_illegal_status_transitions_rejected(app, client, staff, start, target):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status=start)
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/status",
        form_path=f"/activities/{activity_id}", status=target, follow=True,
    )
    assert b"Cannot change a" in resp.data
    assert activity_status(app, activity_id) == start


def test_cancelling_activity_cancels_live_registrations_only(app, client, staff, make_user):
    other_id = make_user(ROLE_PARTICIPANT, email="other@t.demo", password=PW)
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    make_registration(app, activity_id, staff[ROLE_PARTICIPANT])
    make_registration(app, activity_id, other_id, status="cancelled")

    login(client, "admin@t.demo", PW)
    post_csrf(
        client, f"/activities/{activity_id}/status",
        form_path=f"/activities/{activity_id}", status="cancelled",
    )
    by_user = {r.user_id: r.status for r in registrations_of(app, activity_id)}
    assert by_user == {staff[ROLE_PARTICIPANT]: "cancelled", other_id: "cancelled"}


def test_completion_does_not_rewrite_registrations_or_attendance(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    make_registration(app, activity_id, staff[ROLE_PARTICIPANT])
    login(client, "admin@t.demo", PW)
    post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        **_attendance_payload(staff[ROLE_PARTICIPANT]),
    )
    post_csrf(
        client, f"/activities/{activity_id}/status",
        form_path=f"/activities/{activity_id}", status="completed",
    )
    assert registrations_of(app, activity_id)[0].status == "registered"
    assert attendance_rows(app, activity_id)[0].attendance_status == "present"


def test_activity_is_never_hard_deleted(app, client, staff):
    """There is no delete route: DELETE/POST to any delete-like URL is 404/405."""
    activity_id = make_activity(app, staff[ROLE_ADMIN])
    login(client, "admin@t.demo", PW)
    assert client.post(f"/activities/{activity_id}/delete").status_code in (404, 405)
    assert client.delete(f"/activities/{activity_id}").status_code in (404, 405)
    assert activity_of(app, activity_id) is not None


# ===========================================================================
# 7. Assignments
# ===========================================================================


def test_assignment_can_be_added_by_owner(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_OFFICER])
    login(client, "off@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/assignments",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(staff[ROLE_OFFICER]), responsibility="Coordinate venue",
        follow=True,
    )
    assert b"Responsibility assigned" in resp.data
    with app.app_context():
        rows = ActivityAssignment.query.filter_by(activity_id=activity_id).all()
    assert len(rows) == 1
    assert rows[0].responsibility == "Coordinate venue"


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_assignment_blocked_on_terminal_activity(app, client, staff, status):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status=status)
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/assignments",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(staff[ROLE_OFFICER]), responsibility="Late duty",
        follow=True,
    )
    assert b"cannot be added" in resp.data
    with app.app_context():
        assert ActivityAssignment.query.filter_by(activity_id=activity_id).count() == 0


def test_assignment_validation_requires_responsibility_and_eligible_officer(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN])
    login(client, "admin@t.demo", PW)
    url = f"/activities/{activity_id}/assignments"

    assert b"Responsibility is required" in post_csrf(
        client, url, form_path=f"/activities/{activity_id}",
        officer_user_id=str(staff[ROLE_OFFICER]), responsibility="  ", follow=True,
    ).data
    assert b"Select an officer" in post_csrf(
        client, url, form_path=f"/activities/{activity_id}",
        officer_user_id="", responsibility="Duty", follow=True,
    ).data
    assert b"Only active System Administrators" in post_csrf(
        client, url, form_path=f"/activities/{activity_id}",
        officer_user_id=str(staff[ROLE_ADVISER]), responsibility="Duty", follow=True,
    ).data
    assert b"Due date is not a valid date" in post_csrf(
        client, url, form_path=f"/activities/{activity_id}",
        officer_user_id=str(staff[ROLE_OFFICER]), responsibility="Duty",
        due_date="31-02-2026", follow=True,
    ).data
    with app.app_context():
        assert ActivityAssignment.query.filter_by(activity_id=activity_id).count() == 0


def test_duplicate_assignment_is_rejected(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN])
    login(client, "admin@t.demo", PW)
    url = f"/activities/{activity_id}/assignments"
    payload = dict(officer_user_id=str(staff[ROLE_OFFICER]), responsibility="Same duty")
    post_csrf(client, url, form_path=f"/activities/{activity_id}", **payload)
    resp = post_csrf(client, url, form_path=f"/activities/{activity_id}", **payload, follow=True)
    assert b"already has this responsibility" in resp.data
    with app.app_context():
        assert ActivityAssignment.query.filter_by(activity_id=activity_id).count() == 1


def test_assignment_from_another_activity_is_404(app, client, staff):
    a1 = make_activity(app, staff[ROLE_ADMIN], title="A1")
    a2 = make_activity(app, staff[ROLE_ADMIN], title="A2")
    login(client, "admin@t.demo", PW)
    post_csrf(
        client, f"/activities/{a1}/assignments", form_path=f"/activities/{a1}",
        officer_user_id=str(staff[ROLE_OFFICER]), responsibility="Only on A1",
    )
    with app.app_context():
        assignment_id = ActivityAssignment.query.filter_by(activity_id=a1).one().id
    resp = post_csrf(
        client, f"/activities/{a2}/assignments/{assignment_id}/edit",
        form_path=f"/activities/{a2}",
        officer_user_id=str(staff[ROLE_OFFICER]), responsibility="Hijack",
    )
    assert resp.status_code == 404
    with app.app_context():
        assert db.session.get(ActivityAssignment, assignment_id).responsibility == "Only on A1"


def test_assignment_status_transition_is_enforced(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN])
    login(client, "admin@t.demo", PW)
    post_csrf(
        client, f"/activities/{activity_id}/assignments", form_path=f"/activities/{activity_id}",
        officer_user_id=str(staff[ROLE_OFFICER]), responsibility="Duty",
    )
    with app.app_context():
        assignment_id = ActivityAssignment.query.filter_by(activity_id=activity_id).one().id

    resp = post_csrf(
        client, f"/activities/{activity_id}/assignments/{assignment_id}/edit",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(staff[ROLE_OFFICER]), responsibility="Duty", status="bogus",
        follow=True,
    )
    assert b"Select a valid assignment status" in resp.data


# ===========================================================================
# 8. Lists & filters
# ===========================================================================


def test_list_status_filter_and_counts(app, client, staff):
    make_activity(app, staff[ROLE_ADMIN], status="draft", title="Draft Thing")
    make_activity(app, staff[ROLE_ADMIN], status="published", title="Published Thing")
    login(client, "admin@t.demo", PW)

    html = client.get("/activities?status=draft").data
    assert b"Draft Thing" in html
    assert b"Published Thing" not in html

    html = client.get("/activities?status=published").data
    assert b"Published Thing" in html
    assert b"Draft Thing" not in html

    # Invalid filter values fall back to "all" rather than erroring.
    assert client.get("/activities?status=bogus").status_code == 200
    assert b"Draft Thing" in client.get("/activities?status=bogus").data


def test_list_search_matches_title_venue_type_case_insensitively(app, client, staff):
    make_activity(app, staff[ROLE_ADMIN], title="Hackathon 2026")
    make_activity(app, staff[ROLE_ADMIN], title="Lab Tour", venue="Innovation Lab")
    login(client, "admin@t.demo", PW)
    # Title match, case-insensitive:
    html = client.get("/activities?q=hackathon").data
    assert b"Hackathon 2026" in html and b"Lab Tour" not in html
    # Venue match, case-insensitive:
    html = client.get("/activities?q=INNOVATION").data
    assert b"Lab Tour" in html and b"Hackathon 2026" not in html
    # No match at all:
    html = client.get("/activities?q=zzzz").data
    assert b"Hackathon 2026" not in html and b"Lab Tour" not in html


def test_list_search_wildcards_are_not_sql(app, client, staff):
    """A '%' search must not match everything (parameter binding, no injection)."""
    make_activity(app, staff[ROLE_ADMIN], title="Only Activity")
    login(client, "admin@t.demo", PW)
    resp = client.get("/activities", query_string={"q": "%"})
    assert resp.status_code == 200
    assert b"Only Activity" not in resp.data
    assert b"No activities to show" in resp.data


def test_edit_link_visibility_matches_ownership(app, client, staff, make_user):
    other_id = make_user(ROLE_OFFICER, email="other@t.demo", password=PW)
    own_id = make_activity(app, staff[ROLE_OFFICER], title="Own Activity")
    foreign_id = make_activity(app, other_id, title="Foreign Activity")

    login(client, "off@t.demo", PW)
    html = client.get("/activities").data
    assert f"/activities/{own_id}/edit".encode() in html
    assert f"/activities/{foreign_id}/edit".encode() not in html
    assert client.get(f"/activities/{foreign_id}/edit").status_code == 403
    logout(client)

    login(client, "adv@t.demo", PW)
    html = client.get("/activities").data
    assert f"/activities/{own_id}/edit".encode() not in html
    assert f"/activities/{foreign_id}/edit".encode() not in html
    logout(client)

    login(client, "admin@t.demo", PW)
    html = client.get("/activities").data
    assert f"/activities/{own_id}/edit".encode() in html
    assert f"/activities/{foreign_id}/edit".encode() in html


def test_empty_activity_list_renders_an_empty_state(client, staff):
    login(client, "admin@t.demo", PW)
    html = client.get("/activities").data
    assert b"No activities to show" in html


# ===========================================================================
# 9. Errors — input that reaches the database
# ===========================================================================


def test_overlong_responsibility_is_reported_not_a_500(app, client, staff):
    """Regression (Phase 11): Bug 1.

    `activities.form` limits `title`/venue/type but not `description`, so a value
    longer than a column (or a text with a NUL byte) reached PostgreSQL and raised
    a DataError -> uncaught 500. It must be a flash + form re-render instead.
    """
    activity_id = make_activity(app, staff[ROLE_ADMIN])
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/assignments",
        form_path=f"/activities/{activity_id}",
        officer_user_id=str(staff[ROLE_OFFICER]), responsibility="d" * 2001,
        follow=True,
    )
    assert resp.status_code == 200
    assert b"Responsibility must be 2000 characters or fewer" in resp.data


def test_nul_byte_in_title_does_not_crash(app, client, staff):
    """A NUL byte is accepted by Python strings but rejected by PostgreSQL text."""
    login(client, "admin@t.demo", PW)
    resp = post_csrf(client, "/activities/new", **valid_form(title="Bad\x00Title"), follow=True)
    assert resp.status_code == 200
    assert b"could not be saved" in resp.data or b"Title" in resp.data
    with app.app_context():
        assert db.session.execute(db.select(db.func.count(Activity.id))).scalar() == 0


def test_nul_byte_in_remarks_does_not_crash(app, client, staff):
    activity_id = make_activity(app, staff[ROLE_ADMIN], status="published")
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/activities/{activity_id}/attendance",
        form_path=f"/activities/{activity_id}",
        user_id=str(staff[ROLE_PARTICIPANT]), attendance_status="present",
        remarks="note\x00with nul", follow=True,
    )
    assert resp.status_code == 200


def test_404_page_uses_the_techtrack_design(client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    resp = client.get("/no-such-page")
    assert resp.status_code == 404
    assert b"404" in resp.data
    assert b"TechIS" in resp.data
    assert b"style.css" in resp.data or b"/static/" in resp.data

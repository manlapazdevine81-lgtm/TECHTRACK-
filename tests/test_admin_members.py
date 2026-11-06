"""Member Management (admin CRUD) tests — CSRF-protected routes."""
from app.extensions import db
from app.models.user import (
    APPROVED_ROLES,
    ROLE_ADMIN,
    ROLE_ADVISER,
    ROLE_OFFICER,
    ROLE_PARTICIPANT,
    Role,
    User,
)

from .conftest import login, logout, post_csrf

PW = "Passw0rd!"
CREATE_URL = "/admin/users/create"


def _login_admin(client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW, full_name="The Admin")
    login(client, "admin@t.demo", PW)


def _member_data(**overrides):
    """Create payload. No password field: the server generates a temporary one."""
    data = {
        "full_name": "New Member",
        "email": "new@t.demo",
        "student_id": "2026-1000",
        "role_name": ROLE_OFFICER,
        "is_active": "y",
    }
    data.update(overrides)
    return data


# ---------- Create ----------

def test_create_member_success(client, make_user, monkeypatch):
    """Creation now provisions a temporary password and emails it."""
    from app.services import email_service

    sent = {}
    monkeypatch.setattr(
        email_service, "send_credentials_email",
        lambda r, n, l, p: (sent.update(password=p), True)[1],
    )
    _login_admin(client, make_user)
    resp = post_csrf(client, CREATE_URL, **_member_data())
    assert resp.status_code == 302
    with client.application.app_context():
        user = User.query.filter_by(email="new@t.demo").first()
        assert user is not None
        assert user.role_name == ROLE_OFFICER
        assert user.is_active is True
        # A generated temporary password was emailed and stored HASHED.
        assert sent["password"]
        assert user.password_hash != sent["password"]     # never plain text
        assert user.check_password(sent["password"])      # hashed correctly
        assert user.must_change_password is True


def test_create_duplicate_email_rejected(client, make_user):
    _login_admin(client, make_user)
    post_csrf(client, CREATE_URL, **_member_data())
    logout(client)
    login(client, "admin@t.demo", PW)
    resp = post_csrf(client, CREATE_URL, **_member_data(email="new@t.demo"))
    assert b"already exists" in resp.data
    with client.application.app_context():
        assert User.query.filter_by(email="new@t.demo").count() == 1


def test_create_duplicate_student_id_rejected(client, make_user):
    _login_admin(client, make_user)
    post_csrf(client, CREATE_URL, **_member_data())
    logout(client)
    login(client, "admin@t.demo", PW)
    resp = post_csrf(client, CREATE_URL, **_member_data(email="other@t.demo"))
    assert b"student ID already exists" in resp.data


def test_create_validation_failures(client, make_user):
    _login_admin(client, make_user)
    resp = post_csrf(client, CREATE_URL, full_name="", email="", role_name="", password="")
    assert b"Full name is required" in resp.data
    assert b"Email is required" in resp.data
    assert b"Invalid role selection" in resp.data
    # No password requirement any more: the server generates one.
    assert b"Password is required for a new account" not in resp.data
    resp = post_csrf(
        client,
        CREATE_URL,
        full_name="X",
        email="not-an-email",
        role_name=ROLE_OFFICER,
    )
    assert b"valid email" in resp.data


def test_create_rejects_unapproved_role(client, make_user):
    """Only the four approved roles may ever be assigned (T19)."""
    _login_admin(client, make_user)
    resp = post_csrf(client, CREATE_URL, **_member_data(role_name="superuser"))
    assert b"Invalid role selection" in resp.data
    with client.application.app_context():
        assert User.query.filter_by(email="new@t.demo").first() is None


def test_role_definitions_never_change(client, make_user):
    """Creating/editing members must not touch the four approved role rows."""
    _login_admin(client, make_user)
    post_csrf(client, CREATE_URL, **_member_data())
    with client.application.app_context():
        assert Role.query.count() == 4
        assert {r.name for r in Role.query.all()} == set(APPROVED_ROLES)


# ---------- Edit ----------

def test_edit_member_success(client, make_user):
    _login_admin(client, make_user)
    target_id = make_user(ROLE_PARTICIPANT, email="t@t.demo", password=PW, full_name="Target")
    resp = post_csrf(
        client,
        f"/admin/users/{target_id}/edit",
        full_name="Target Renamed",
        email="renamed@t.demo",
        student_id="2026-2000",
        role_name=ROLE_ADVISER,          # promote participant -> adviser
        password="",                     # keep existing password
        is_active="y",
    )
    assert resp.status_code == 302
    with client.application.app_context():
        user = db.session.get(User, target_id)
        assert user.full_name == "Target Renamed"
        assert user.email == "renamed@t.demo"
        assert user.role_name == ROLE_ADVISER
        assert user.check_password(PW)   # unchanged when left blank


def test_edit_sets_new_password(client, make_user):
    _login_admin(client, make_user)
    target_id = make_user(ROLE_PARTICIPANT, email="t@t.demo", password=PW)
    post_csrf(
        client,
        f"/admin/users/{target_id}/edit",
        full_name="Target",
        email="t@t.demo",
        role_name=ROLE_PARTICIPANT,
        password="NewPass99!",
        is_active="y",
    )
    with client.application.app_context():
        user = db.session.get(User, target_id)
        assert user.check_password("NewPass99!")
        assert not user.check_password(PW)


def test_admin_cannot_deactivate_self_via_edit(client, make_user):
    _login_admin(client, make_user)
    admin = User.query.filter_by(email="admin@t.demo").first()
    resp = post_csrf(
        client,
        f"/admin/users/{admin.id}/edit",
        full_name="The Admin",
        email="admin@t.demo",
        role_name=ROLE_ADMIN,
        password="",
        # NOTE: is_active intentionally omitted -> would deactivate
    )
    assert b"You cannot deactivate your own account" in resp.data
    with client.application.app_context():
        assert db.session.get(User, admin.id).is_active is True


def test_edit_unknown_user_404(client, make_user):
    _login_admin(client, make_user)
    resp = post_csrf(
        client,
        "/admin/users/9999/edit",
        form_path="/admin/users",  # token lives on the list page (404 page has none)
        full_name="X",
        email="x@t.demo",
        role_name=ROLE_OFFICER,
    )
    assert resp.status_code == 404


# ---------- Toggle (activate/deactivate) ----------

def test_toggle_deactivate_and_activate(client, make_user):
    _login_admin(client, make_user)
    target_id = make_user(ROLE_PARTICIPANT, email="t@t.demo", password=PW)
    resp = post_csrf(client, f"/admin/users/{target_id}/toggle", form_path="/admin/users")
    assert resp.status_code == 302
    with client.application.app_context():
        assert db.session.get(User, target_id).is_active is False
    # Deactivated member may no longer log in:
    logout(client)
    login(client, "t@t.demo", PW)
    assert client.get("/dashboard").status_code == 302
    # Reactivate and login works again:
    login(client, "admin@t.demo", PW)
    post_csrf(client, f"/admin/users/{target_id}/toggle", form_path="/admin/users")
    with client.application.app_context():
        assert db.session.get(User, target_id).is_active is True


def test_admin_cannot_toggle_self(client, make_user):
    _login_admin(client, make_user)
    admin = User.query.filter_by(email="admin@t.demo").first()
    resp = post_csrf(client, f"/admin/users/{admin.id}/toggle", form_path="/admin/users", follow=True)
    assert b"You cannot deactivate your own account" in resp.data
    with client.application.app_context():
        assert db.session.get(User, admin.id).is_active is True


# ---------- CSRF + authorization on every new route ----------

def test_new_routes_reject_missing_csrf(client, make_user):
    _login_admin(client, make_user)
    target_id = make_user(ROLE_PARTICIPANT, email="t@t.demo", password=PW)
    for url in (CREATE_URL, f"/admin/users/{target_id}/edit", f"/admin/users/{target_id}/toggle"):
        resp = client.post(url, data={"full_name": "NoToken"})
        assert resp.status_code == 400, url
    with client.application.app_context():
        assert User.query.filter_by(email="t@t.demo").count() == 1  # unchanged


def test_new_routes_403_for_other_roles(client, make_user):
    """Direct URL access blocked server-side for every non-admin role."""
    target_id = make_user(ROLE_PARTICIPANT, email="t@t.demo", password=PW)
    for email, role in (
        ("off@t.demo", ROLE_OFFICER),
        ("adv@t.demo", ROLE_ADVISER),
        ("part@t.demo", ROLE_PARTICIPANT),
    ):
        make_user(role, email=email, password=PW)
        login(client, email, PW)
        assert client.get(CREATE_URL).status_code == 403, role
        assert client.get(f"/admin/users/{target_id}/edit").status_code == 403, role
        # Tokens fetched from /dashboard (accessible to every role; admin pages 403).
        assert post_csrf(
            client, f"/admin/users/{target_id}/toggle", form_path="/dashboard"
        ).status_code == 403, role
        assert post_csrf(
            client, CREATE_URL, form_path="/dashboard", **_member_data()
        ).status_code == 403, role
        logout(client)


def test_anonymous_redirected_to_login(client, make_user):
    for url in (CREATE_URL, "/admin/users/1/edit"):
        resp = client.get(url)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

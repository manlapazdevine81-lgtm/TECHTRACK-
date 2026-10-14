"""Registration, login, logout, and session-protection tests."""
from app.extensions import db
from app.models.user import ROLE_ADMIN, ROLE_PARTICIPANT, User

from .conftest import login

VALID = {
    "full_name": "Juan Dela Cruz",
    "email": "juan@student.demo",
    "student_id": "2026-0001",
    "password": "Secret123",
    "confirm_password": "Secret123",
}


def _register(client, **overrides):
    data = {**VALID, **overrides}
    return client.post("/register", data=data, follow_redirects=True)


# ---------- Registration ----------

def test_register_valid(client):
    resp = _register(client)
    assert resp.status_code == 200
    assert b"Registration successful" in resp.data
    with client.application.app_context():
        user = User.query.filter_by(email="juan@student.demo").first()
        assert user is not None
        assert user.role_name == ROLE_PARTICIPANT  # never privileged
        assert user.password_hash != "Secret123"  # hashed, never plain
        assert user.check_password("Secret123")


def test_register_rejects_privileged_role_field(client):
    """A forged `role` field in the POST must be ignored (server-assigned only)."""
    _register(client, role=ROLE_ADMIN, role_id="1")
    with client.application.app_context():
        user = User.query.filter_by(email="juan@student.demo").first()
        assert user.role_name == ROLE_PARTICIPANT


def test_register_missing_fields(client):
    resp = client.post("/register", data={}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Full name is required" in resp.data
    assert b"Email is required" in resp.data
    assert b"Password is required" in resp.data


def test_register_password_mismatch(client):
    resp = _register(client, confirm_password="Different1")
    assert b"Passwords do not match" in resp.data
    with client.application.app_context():
        assert User.query.filter_by(email="juan@student.demo").first() is None


def test_register_invalid_email(client):
    resp = _register(client, email="not-an-email")
    assert b"valid email" in resp.data


def test_register_short_password(client):
    resp = _register(client, password="short", confirm_password="short")
    assert b"at least 8 characters" in resp.data


def test_register_duplicate_email(client):
    _register(client)
    resp = _register(client)  # same email again
    assert b"already exists" in resp.data
    with client.application.app_context():
        count = User.query.filter_by(email="juan@student.demo").count()
        assert count == 1


# ---------- Login / logout ----------

def test_login_success_and_session(client, make_user):
    make_user(ROLE_PARTICIPANT, email="p@test.demo", password="Passw0rd!")
    resp = login(client, "p@test.demo", "Passw0rd!")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")
    dash = client.get("/dashboard")
    assert dash.status_code == 200
    assert b"Dashboard" in dash.data


def test_login_wrong_password(client, make_user):
    make_user(ROLE_PARTICIPANT, email="p@test.demo", password="Passw0rd!")
    resp = client.post(
        "/login",
        data={"email": "p@test.demo", "password": "WRONG"},
        follow_redirects=True,
    )
    assert b"Invalid email or password" in resp.data
    # No session established:
    assert client.get("/dashboard").status_code == 302


def test_login_unknown_email_same_message(client):
    resp = client.post(
        "/login",
        data={"email": "ghost@test.demo", "password": "whatever1"},
        follow_redirects=True,
    )
    assert b"Invalid email or password" in resp.data  # no user enumeration


def test_logout_invalidates_session(client, make_user):
    make_user(ROLE_PARTICIPANT, email="p@test.demo", password="Passw0rd!")
    login(client, "p@test.demo", "Passw0rd!")
    assert client.get("/dashboard").status_code == 200
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 302
    # Protected route requires login again after logout:
    dash = client.get("/dashboard")
    assert dash.status_code == 302
    assert "/login" in dash.headers["Location"]


# ---------- Session protection ----------

def test_protected_routes_redirect_anonymous(client):
    for url in ("/dashboard", "/admin/users"):
        resp = client.get(url)
        assert resp.status_code == 302, url
        assert "/login" in resp.headers["Location"], url
    # Logout is POST-only (405 on GET) and anonymous POSTs are sent to login:
    assert client.get("/logout").status_code == 405
    resp = client.post("/logout")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

"""Account provisioning: temp passwords, credentials email, first-login gate.

Covers the approved requirements A-F:
  * temp password generation and policy;
  * admin account creation (no password field) + email delivery;
  * SMTP failure handling and the resend/retry action;
  * the server-side first-login password-change gate;
  * existing accounts (must_change_password=False) are unaffected.

Email delivery is always mocked — no real SMTP connection is opened.
"""
import pytest

from app.extensions import db
from app.models.user import (
    ROLE_ADMIN,
    ROLE_ADVISER,
    ROLE_OFFICER,
    ROLE_PARTICIPANT,
    User,
)
from app.services import email_service
from app.utils import passwords

from .conftest import get_csrf, login, logout

PW = "Passw0rd!"


# ---------------------------------------------------------------------------
# 1-3. Password utility
# ---------------------------------------------------------------------------


def test_generate_temp_password_length_and_type():
    generated = passwords.generate_temp_password()
    assert isinstance(generated, str)
    assert len(generated) >= passwords.MIN_LENGTH


@pytest.mark.parametrize("_run", range(50))
def test_generated_password_always_satisfies_policy(_run):
    """Every generated password must pass all four rules (not just most)."""
    pwd = passwords.generate_temp_password()
    assert passwords.password_policy_ok(pwd), pwd
    assert len(pwd) >= 8
    assert any(c.isupper() for c in pwd)
    assert any(c.isdigit() for c in pwd)
    assert any(c in passwords.SPECIALS for c in pwd)


def test_generated_passwords_are_unique():
    values = {passwords.generate_temp_password() for _ in range(50)}
    assert len(values) == 50


@pytest.mark.parametrize(
    "pwd,expected_fragment",
    [
        ("Abc1!", "at least 8"),                     # too short
        ("abcdefg1!", "uppercase"),                  # no uppercase
        ("Abcdefgh!", "digit"),                      # no digit
        ("Abcdefg1", "special"),                     # no special
        ("", "at least 8"),                          # empty
    ],
)
def test_password_policy_rejects_each_missing_rule(pwd, expected_fragment):
    errors = passwords.password_policy_errors(pwd)
    assert errors, pwd
    assert any(expected_fragment in e for e in errors), errors


def test_password_policy_accepts_a_compliant_password():
    assert passwords.password_policy_errors("GoodPass1!") == []
    assert passwords.password_policy_ok("GoodPass1!")


# ---------------------------------------------------------------------------
# 4-6. Admin account creation
# ---------------------------------------------------------------------------


@pytest.fixture()
def admin(app, client, make_user):
    return make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)


def _create_account(client, email="new@t.demo", role=ROLE_OFFICER, **extra):
    data = {
        "full_name": "New Member",
        "email": email,
        "student_id": extra.pop("student_id", "2026-9999"),
        "role_name": role,
        "is_active": "y",
        "csrf_token": get_csrf(client, "/admin/users/create"),
    }
    data.update(extra)
    return client.post("/admin/users/create", data=data, follow_redirects=True)


def _by_email(app, email):
    """Return plain values, not an ORM instance (avoids detached-attribute reads).

    Scalar columns are safe to touch after the context exits; a lazy
    relationship (`role`) is not.
    """
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if user is None:
            return None
        return {
            "id": user.id,
            "email": user.email,
            "role_name": user.role_name,
            "must_change_password": user.must_change_password,
            "password_hash": user.password_hash,
            "check": user.check_password,
        }


def test_create_form_explains_provisioning_split(app, client, admin):
    """Staff get emailed temp credentials; Participants get an initial password."""
    login(client, "admin@t.demo", PW)
    html = client.get("/admin/users/create").data
    assert b"temporary password" in html.lower()
    # The participant initial-password field exists (required only for that role).
    assert b'name="password"' in html
    assert b"Event Participant" in html or b"event_participant" in html


def test_admin_creation_generates_temp_password_and_emails_it(
    app, client, admin, monkeypatch
):
    sent = {}

    def fake_send(recipient, full_name, login_email, temp_password):
        sent.update(
            recipient=recipient, full_name=full_name, login=login_email,
            password=temp_password,
        )
        return True

    monkeypatch.setattr(email_service, "send_credentials_email", fake_send)
    login(client, "admin@t.demo", PW)

    resp = _create_account(client, email="officer1@t.demo")
    assert b"emailed" in resp.data.lower()

    user = _by_email(app, "officer1@t.demo")
    assert user is not None
    assert user["must_change_password"] is True
    assert user["role_name"] == ROLE_OFFICER

    # The emailed password is the one that was hashed.
    assert sent["recipient"] == "officer1@t.demo"
    assert passwords.password_policy_ok(sent["password"])
    assert user["check"](sent["password"])


def test_password_is_hashed_never_stored_plaintext(app, client, admin, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        email_service, "send_credentials_email",
        lambda r, n, l, p: (captured.setdefault("p", p), True)[1],
    )
    login(client, "admin@t.demo", PW)
    _create_account(client, email="hashed@t.demo")

    user = _by_email(app, "hashed@t.demo")
    assert user["password_hash"] != captured["p"]
    assert captured["p"] not in user["password_hash"]
    assert user["check"](captured["p"])


def test_temp_password_never_appears_in_page_after_creation(
    app, client, admin, monkeypatch
):
    captured = {}
    monkeypatch.setattr(
        email_service, "send_credentials_email",
        lambda r, n, l, p: (captured.setdefault("p", p), True)[1],
    )
    login(client, "admin@t.demo", PW)
    resp = _create_account(client, email="nosee@t.demo")
    assert captured["p"].encode() not in resp.data


def test_duplicate_email_does_not_create_or_email(app, client, admin, monkeypatch):
    calls = []
    monkeypatch.setattr(
        email_service, "send_credentials_email",
        lambda *a, **k: (calls.append(1), True)[1],
    )
    login(client, "admin@t.demo", PW)
    _create_account(client, email="dup@t.demo")
    resp = _create_account(client, email="dup@t.demo", student_id="2026-8888")
    assert b"already exists" in resp.data
    with app.app_context():
        assert User.query.filter_by(email="dup@t.demo").count() == 1
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# 7. SMTP failure
# ---------------------------------------------------------------------------


def test_smtp_failure_warns_and_keeps_account(app, client, admin, monkeypatch):
    monkeypatch.setattr(email_service, "send_credentials_email", lambda *a, **k: False)
    login(client, "admin@t.demo", PW)

    resp = _create_account(client, email="failed@t.demo")
    body = resp.data.lower()
    assert b"could not be sent" in body
    assert b"emailed to them" not in body

    user = _by_email(app, "failed@t.demo")
    assert user is not None                       # account kept
    assert user["must_change_password"] is True   # gate retained


def test_failure_message_does_not_leak_the_password(app, client, admin, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        email_service, "send_credentials_email",
        lambda r, n, l, p: (captured.setdefault("p", p), False)[1],
    )
    login(client, "admin@t.demo", PW)
    resp = _create_account(client, email="leak@t.demo")
    assert captured["p"].encode() not in resp.data


# ---------------------------------------------------------------------------
# 8. Resend / retry
# ---------------------------------------------------------------------------


def test_admin_can_resend_credentials(app, client, admin, monkeypatch):
    calls = []
    monkeypatch.setattr(email_service, "send_credentials_email", lambda *a, **k: True)
    monkeypatch.setattr(
        email_service, "send_credentials_resent_email",
        lambda r, n, l, p: (calls.append(p), True)[1],
    )
    login(client, "admin@t.demo", PW)
    _create_account(client, email="resend@t.demo")
    user = _by_email(app, "resend@t.demo")

    resp = client.post(
        f"/admin/users/{user['id']}/resend-credentials",
        data={"csrf_token": get_csrf(client, "/admin/users")},
        follow_redirects=True,
    )
    assert b"emailed" in resp.data.lower()
    assert len(calls) == 1

    with app.app_context():
        refreshed = db.session.get(User, user["id"])
        assert refreshed.must_change_password is True
        assert refreshed.check_password(calls[0])

    # No duplicate account.
    with app.app_context():
        assert User.query.filter_by(email="resend@t.demo").count() == 1


def test_resend_failure_is_reported_honestly(app, client, admin, monkeypatch):
    monkeypatch.setattr(email_service, "send_credentials_email", lambda *a, **k: True)
    monkeypatch.setattr(email_service, "send_credentials_resent_email", lambda *a, **k: False)
    login(client, "admin@t.demo", PW)
    _create_account(client, email="resendfail@t.demo")
    user = _by_email(app, "resendfail@t.demo")

    resp = client.post(
        f"/admin/users/{user['id']}/resend-credentials",
        data={"csrf_token": get_csrf(client, "/admin/users")},
        follow_redirects=True,
    )
    assert b"could not be sent" in resp.data.lower()
    with app.app_context():
        assert db.session.get(User, user["id"]).must_change_password is True


# ---------------------------------------------------------------------------
# 9-12. First-login gate and password change
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_user(app, client, make_user):
    """An officer holding a temporary password."""
    uid = make_user(ROLE_OFFICER, email="temp@t.demo", password=PW)
    with app.app_context():
        user = db.session.get(User, uid)
        user.must_change_password = True
        db.session.commit()
    return uid


def test_temp_user_is_redirected_to_change_password(app, client, temp_user):
    resp = login(client, "temp@t.demo", PW)
    assert resp.status_code == 302
    assert "/password/change" in resp.headers["Location"]


@pytest.mark.parametrize("url", [
    "/dashboard", "/activities", "/reports", "/records", "/participants", "/admin/users",
])
def test_temp_user_cannot_reach_protected_routes(app, client, temp_user, url):
    """The GATE must block these, not just the login redirect."""
    login(client, "temp@t.demo", PW)
    resp = client.get(url)
    assert resp.status_code == 302
    assert "/password/change" in resp.headers["Location"]


def test_temp_user_cannot_post_to_protected_routes(app, client, temp_user):
    login(client, "temp@t.demo", PW)
    # A valid CSRF token so the request reaches the gate rather than CSRF.
    token = get_csrf(client, "/password/change")
    resp = client.post("/activities/new", data={"csrf_token": token})
    assert resp.status_code in (302, 403)
    if resp.status_code == 302:
        assert "/password/change" in resp.headers["Location"]


def test_temp_user_can_reach_change_page_and_logout(app, client, temp_user):
    login(client, "temp@t.demo", PW)
    assert client.get("/password/change").status_code == 200
    token = get_csrf(client, "/password/change")
    assert client.post("/logout", data={"csrf_token": token}).status_code == 302


def test_password_change_requires_policy_and_confirmation(app, client, temp_user):
    login(client, "temp@t.demo", PW)
    token = get_csrf(client, "/password/change")

    # Missing uppercase.
    resp = client.post("/password/change", data={
        "current_password": PW, "new_password": "lowercase1!",
        "confirm_password": "lowercase1!", "csrf_token": token,
    }, follow_redirects=True)
    assert b"uppercase" in resp.data

    # Mismatch.
    resp = client.post("/password/change", data={
        "current_password": PW, "new_password": "GoodPass1!",
        "confirm_password": "Different1!", "csrf_token": token,
    }, follow_redirects=True)
    assert b"do not match" in resp.data

    # Wrong current password.
    resp = client.post("/password/change", data={
        "current_password": "wrong", "new_password": "GoodPass1!",
        "confirm_password": "GoodPass1!", "csrf_token": token,
    }, follow_redirects=True)
    assert b"current password is incorrect" in resp.data

    with app.app_context():
        assert db.session.get(User, temp_user).must_change_password is True


def test_successful_change_clears_flag_and_restores_access(app, client, temp_user):
    login(client, "temp@t.demo", PW)
    token = get_csrf(client, "/password/change")
    resp = client.post("/password/change", data={
        "current_password": PW, "new_password": "BrandNew1!",
        "confirm_password": "BrandNew1!", "csrf_token": token,
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        user = db.session.get(User, temp_user)
        assert user.must_change_password is False
        assert user.check_password("BrandNew1!")

    # Normal access is restored.
    assert client.get("/dashboard").status_code == 200
    assert client.get("/activities").status_code == 200


def test_existing_account_unaffected(app, client, make_user):
    """must_change_password=False users keep normal access immediately."""
    make_user(ROLE_OFFICER, email="normal@t.demo", password=PW)
    resp = login(client, "normal@t.demo", PW)
    assert resp.headers["Location"].endswith("/dashboard")
    assert client.get("/dashboard").status_code == 200
    assert client.get("/activities").status_code == 200


def test_new_self_registration_does_not_require_change(app, client):
    token = get_csrf(client, "/register")
    client.post("/register", data={
        "full_name": "Self Reg", "email": "self@t.demo",
        "password": "SelfPass1!", "confirm_password": "SelfPass1!",
        "csrf_token": token,
    }, follow_redirects=True)
    with app.app_context():
        assert User.query.filter_by(email="self@t.demo").one().must_change_password is False

    login(client, "self@t.demo", "SelfPass1!")
    assert client.get("/dashboard").status_code == 200


# ---------------------------------------------------------------------------
# 13. Authorization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role,email", [
    (ROLE_OFFICER, "off@t.demo"),
    (ROLE_ADVISER, "adv@t.demo"),
    (ROLE_PARTICIPANT, "part@t.demo"),
])
def test_non_admin_cannot_create_or_resend(app, client, make_user, role, email):
    make_user(role, email=email, password=PW)
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, email, PW)

    assert client.get("/admin/users/create").status_code == 403
    # Send a valid CSRF token so the 403 comes from the ROLE check, not CSRF.
    token = get_csrf(client, "/dashboard")
    assert client.post(
        "/admin/users/create",
        data={
            "full_name": "X", "email": "x@t.demo",
            "role_name": ROLE_OFFICER, "csrf_token": token,
        },
    ).status_code == 403
    assert client.post(
        f"/admin/users/{admin_id}/resend-credentials",
        data={"csrf_token": token},
    ).status_code == 403


def test_anonymous_cannot_reach_change_password(client):
    resp = client.get("/password/change")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# Registration now uses the shared policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["short1!", "lowercase1!", "NoDigits!", "NoSpecial1"])
def test_registration_enforces_shared_policy(client, bad):
    token = get_csrf(client, "/register")
    resp = client.post("/register", data={
        "full_name": "Policy User", "email": "policy@t.demo",
        "password": bad, "confirm_password": bad, "csrf_token": token,
    }, follow_redirects=True)
    assert b"must" in resp.data.lower()
    with client.application.app_context():
        assert User.query.filter_by(email="policy@t.demo").first() is None
# ===========================================================================
# Temporary-password provisioning applies to STAFF accounts only
# ===========================================================================


@pytest.mark.parametrize("role", [ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER])
def test_staff_accounts_are_provisioned_with_temp_password(
    app, client, admin, monkeypatch, role
):
    """Admin-created Admin / Officer / Adviser accounts get the first-login gate."""
    sent = {}
    monkeypatch.setattr(
        email_service, "send_credentials_email",
        lambda r, n, l, p: (sent.update(password=p), True)[1],
    )
    login(client, "admin@t.demo", PW)
    email = f"staff-{role}@t.demo"
    _create_account(client, email=email, role=role,
                    student_id=f"2026-{abs(hash(role)) % 9000 + 1000}")

    user = _by_email(app, email)
    assert user is not None
    assert user["must_change_password"] is True
    assert "password" in sent                      # an email WAS sent
    assert user["check"](sent["password"])


def test_admin_created_participant_is_not_provisioned(
    app, client, admin, monkeypatch
):
    """No temporary password and NO credentials email for a Participant."""
    calls = []
    monkeypatch.setattr(
        email_service, "send_credentials_email",
        lambda *a, **k: (calls.append(1), True)[1],
    )
    login(client, "admin@t.demo", PW)
    _create_account(client, email="newpart@t.demo", role=ROLE_PARTICIPANT,
                    password="PartInitial1!")

    user = _by_email(app, "newpart@t.demo")
    assert user is not None
    assert user["must_change_password"] is False
    assert user["role_name"] == ROLE_PARTICIPANT
    assert calls == []                              # no email sent


def test_admin_created_participant_is_not_forced_to_change_password(
    app, client, admin, monkeypatch
):
    monkeypatch.setattr(email_service, "send_credentials_email", lambda *a, **k: True)
    login(client, "admin@t.demo", PW)
    _create_account(client, email="newpart2@t.demo", role=ROLE_PARTICIPANT,
                    password="PartInitial1!")
    logout(client)

    # The participant signs in with the initial password and lands on the
    # dashboard — no forced redirect to /password/change.
    resp = login(client, "newpart2@t.demo", "PartInitial1!")
    assert resp.headers["Location"].endswith("/dashboard")
    assert client.get("/dashboard").status_code == 200
    assert client.get("/my-activities").status_code == 200


def test_self_registered_participant_sets_flag_false(app, client):
    token = get_csrf(client, "/register")
    client.post("/register", data={
        "full_name": "Self Participant", "email": "sp@t.demo",
        "password": "SelfPass1!", "confirm_password": "SelfPass1!",
        "csrf_token": token,
    }, follow_redirects=True)
    with app.app_context():
        user = User.query.filter_by(email="sp@t.demo").one()
        assert user.must_change_password is False
        assert user.role_name == ROLE_PARTICIPANT


def test_self_registered_participant_reaches_participant_pages(app, client):
    token = get_csrf(client, "/register")
    client.post("/register", data={
        "full_name": "Self Participant", "email": "sp2@t.demo",
        "password": "SelfPass1!", "confirm_password": "SelfPass1!",
        "csrf_token": token,
    }, follow_redirects=True)

    resp = login(client, "sp2@t.demo", "SelfPass1!")
    assert resp.headers["Location"].endswith("/dashboard")
    assert "/password/change" not in resp.headers["Location"]
    for url in ("/dashboard", "/my-activities", "/feedback"):
        assert client.get(url).status_code == 200, url


def test_self_registration_sends_no_email(app, client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        email_service, "send_credentials_email",
        lambda *a, **k: (calls.append(1), True)[1],
    )
    token = get_csrf(client, "/register")
    client.post("/register", data={
        "full_name": "No Mail", "email": "nomail@t.demo",
        "password": "SelfPass1!", "confirm_password": "SelfPass1!",
        "csrf_token": token,
    }, follow_redirects=True)
    assert calls == []


@pytest.mark.parametrize("role,email", [
    (ROLE_ADMIN, "prov-admin@t.demo"),
    (ROLE_OFFICER, "prov-off@t.demo"),
    (ROLE_ADVISER, "prov-adv@t.demo"),
])
def test_provisioned_staff_blocked_until_password_changed(
    app, client, admin, monkeypatch, role, email
):
    """End-to-end: create via admin, sign in, verify the gate, then clear it."""
    captured = {}
    monkeypatch.setattr(
        email_service, "send_credentials_email",
        lambda r, n, l, p: (captured.update(password=p), True)[1],
    )
    login(client, "admin@t.demo", PW)
    _create_account(client, email=email, role=role,
                    student_id=f"2026-{abs(hash(email)) % 9000 + 1000}")
    temp = captured["password"]
    logout(client)

    login(client, email, temp)
    assert client.get("/dashboard").status_code == 302
    assert "/password/change" in client.get("/dashboard").headers["Location"]

    token = get_csrf(client, "/password/change")
    client.post("/password/change", data={
        "current_password": temp, "new_password": "Changed1!",
        "confirm_password": "Changed1!", "csrf_token": token,
    }, follow_redirects=True)
    assert client.get("/dashboard").status_code == 200
def test_admin_created_participant_requires_a_password(app, client, admin, monkeypatch):
    """An empty initial password must never create a sign-in-able account.

    `generate_password_hash("")` is verifiable, so this is a real hazard.
    """
    calls = []
    monkeypatch.setattr(
        email_service, "send_credentials_email",
        lambda *a, **k: (calls.append(1), True)[1],
    )
    login(client, "admin@t.demo", PW)
    resp = _create_account(client, email="nopass@t.demo", role=ROLE_PARTICIPANT,
                           password="")
    assert b"at least 8 characters" in resp.data
    with app.app_context():
        assert User.query.filter_by(email="nopass@t.demo").first() is None
    assert calls == []


def test_admin_created_participant_password_must_satisfy_policy(
    app, client, admin, monkeypatch
):
    monkeypatch.setattr(email_service, "send_credentials_email", lambda *a, **k: True)
    login(client, "admin@t.demo", PW)
    resp = _create_account(client, email="weak@t.demo", role=ROLE_PARTICIPANT,
                           password="weakpass")
    assert b"uppercase" in resp.data or b"digit" in resp.data
    with app.app_context():
        assert User.query.filter_by(email="weak@t.demo").first() is None

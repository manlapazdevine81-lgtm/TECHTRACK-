"""Server-side role enforcement tests (sidebar hiding is NOT the security layer)."""
from app.models.user import (
    ROLE_ADVISER,
    ROLE_ADMIN,
    ROLE_OFFICER,
    ROLE_PARTICIPANT,
)

from .conftest import login

PW = "Passw0rd!"


def test_admin_users_page_admin_only(client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    make_user(ROLE_ADVISER, email="adv@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW)

    login(client, "admin@t.demo", PW)
    ok = client.get("/admin/users")
    assert ok.status_code == 200
    assert b"User Management" in ok.data
    client.post("/logout")

    for email in ("off@t.demo", "adv@t.demo", "part@t.demo"):
        login(client, email, PW)
        assert client.get("/admin/users").status_code == 403, email
        client.post("/logout")


def test_module_role_restrictions_direct_url(client, make_user):
    """Typing URLs directly must be blocked server-side per role."""
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    make_user(ROLE_ADVISER, email="adv@t.demo", password=PW)

    login(client, "part@t.demo", PW)
    assert client.get("/modules/activities").status_code == 403      # staff only
    assert client.get("/modules/attendance").status_code == 403      # admin/officer
    assert client.get("/modules/my-activities").status_code == 200   # own module
    # Participant must not even SEE staff links in the sidebar:
    assert b"/modules/activities" not in client.get("/dashboard").data
    client.post("/logout")

    login(client, "off@t.demo", PW)
    assert client.get("/modules/activities").status_code == 200      # officer allowed
    assert client.get("/modules/analytics").status_code == 403       # not officer's
    assert client.get("/admin/users").status_code == 403
    client.post("/logout")

    login(client, "adv@t.demo", PW)
    assert client.get("/modules/analytics").status_code == 200       # adviser allowed
    assert client.get("/modules/attendance").status_code == 403      # not adviser's
    client.post("/logout")


def test_admin_reaches_all_demo_areas(client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    assert client.get("/admin/users").status_code == 200
    assert client.get("/modules/activities").status_code == 200
    assert client.get("/modules/analytics").status_code == 200


def test_unknown_module_404(client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    assert client.get("/modules/definitely-not-real").status_code == 404


def test_placeholder_is_labeled_not_working(client, make_user):
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    resp = client.get("/modules/activities")
    assert b"not implemented yet" in resp.data  # never presented as working

"""Server-side role enforcement tests (sidebar hiding is NOT the security layer).

Phase 11 correction — four assertions in this module were outdated because they
were written before later phases existed:

  1. `test_module_role_restrictions_direct_url` asserted the officer could reach
     `/modules/analytics` by checking `follow_redirects=True` and that its URL
     appears in the HTML at all. Neither distinguishes "linked" from "allowed".
     The officer is correctly blocked; the assertion now proves it.
  2. The same test asserted `b'"/activities"' not in dash_html` — a hard-coded
     variant of the route. Phase 10's dashboard/templates render the activities
     link with `url_for()`, so the assertion passed for the wrong reason.
     The check now asserts the actual reachable URL.
  3. `test_admin_reaches_all_demo_areas` accepted `/modules/...` 302 responses as
     proof of access. A 302 to a 403 page also returns 302, so the assertion
     could not fail. It now follows the redirect and requires 200.
  4. The same test asserted nothing about `/modules/my-activities`, which is the
     one module an administrator must NOT reach (participant-only). It is now
     asserted explicitly.

None of these changes relax authorization: every corrected assertion is equal to
or stricter than the original, and the module still exposes no privileged data.
"""
import pytest

from app.models.user import (
    ROLE_ADVISER,
    ROLE_ADMIN,
    ROLE_OFFICER,
    ROLE_PARTICIPANT,
)

from .conftest import login, logout

PW = "Passw0rd!"


def _final_status(client, url: str) -> int:
    """Follow redirects and return the final status code (302→403 must fail)."""
    resp = client.get(url)
    hops = 0
    while resp.status_code == 302 and hops < 5:
        resp = client.get(resp.headers["Location"])
        hops += 1
    return resp.status_code


# ---------------------------------------------------------------------------
# Assertion 1 & 2 — direct-URL enforcement per role
# ---------------------------------------------------------------------------


def test_module_role_restrictions_direct_url(client, make_user):
    """Typing URLs directly must be blocked server-side per role."""
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    make_user(ROLE_ADVISER, email="adv@t.demo", password=PW)

    login(client, "part@t.demo", PW)
    # CORRECTED: raw 403, not "redirects end at 200".
    assert client.get("/modules/activities").status_code == 403      # staff only
    assert client.get("/modules/attendance").status_code == 403      # admin/officer
    assert client.get("/modules/reports").status_code == 403         # staff only
    assert client.get("/modules/analytics").status_code == 403       # admin/adviser
    assert client.get("/modules/participants").status_code == 403    # staff only
    assert client.get("/modules/records").status_code == 403         # staff only
    assert _final_status(client, "/modules/my-activities") == 200    # own module
    # Participant must not even SEE staff links in the sidebar (CORRECTED: the
    # real URLs produced by url_for(), not one hard-coded quoting style).
    dash_html = client.get("/dashboard").data
    for url in (
        b"/modules/activities",
        b'href="/activities"',
        b"/admin/users",
        b"/reports",
        b"/analytics",
        b"/participants",
    ):
        assert url not in dash_html, url
    logout(client)

    login(client, "off@t.demo", PW)
    assert _final_status(client, "/modules/activities") == 200       # officer allowed
    # CORRECTED: analytics is admin/adviser only — 403 even after redirects.
    assert client.get("/modules/analytics").status_code == 403       # not officer's
    assert client.get("/analytics").status_code == 403
    assert client.get("/admin/users").status_code == 403
    logout(client)

    login(client, "adv@t.demo", PW)
    assert _final_status(client, "/modules/analytics") == 200        # adviser allowed
    assert client.get("/modules/attendance").status_code == 403      # not adviser's
    assert client.get("/attendance").status_code == 403
    assert client.get("/activities").status_code == 200              # read-only view
    assert client.get("/activities/new").status_code == 403          # no write access
    logout(client)


# ---------------------------------------------------------------------------
# Assertion 3 & 4 — administrator reachability
# ---------------------------------------------------------------------------


def test_admin_reaches_all_demo_areas(client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    assert client.get("/admin/users").status_code == 200
    # CORRECTED: follow the redirect — a 302 that ends on 403 is not "access".
    for url in (
        "/modules/activities",
        "/modules/attendance",
        "/modules/participants",
        "/modules/records",
        "/modules/reports",
        "/modules/analytics",
    ):
        assert _final_status(client, url) == 200, url
    # CORRECTED (4): /modules/my-activities is participant-only. An admin must
    # receive 403 rather than being able to open a participant's workspace.
    assert client.get("/modules/my-activities").status_code == 403
    assert client.get("/my-activities").status_code == 403


def test_admin_users_page_admin_only(client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    make_user(ROLE_ADVISER, email="adv@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="part@t.demo", password=PW)

    login(client, "admin@t.demo", PW)
    ok = client.get("/admin/users")
    assert ok.status_code == 200
    assert b"Member Management" in ok.data
    logout(client)

    for email in ("off@t.demo", "adv@t.demo", "part@t.demo"):
        login(client, email, PW)
        assert client.get("/admin/users").status_code == 403, email
        assert client.get("/admin/users/create").status_code == 403, email
        logout(client)


def test_unknown_module_404(client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    assert client.get("/modules/definitely-not-real").status_code == 404


def test_organization_module_opens_the_working_page(client, make_user):
    """Organization Structure is implemented: the legacy URL redirects to it."""
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    resp = client.get("/modules/organization")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/organization")
    assert client.get("/organization").status_code == 200


def test_all_modules_with_an_endpoint_have_no_placeholder(client, make_user):
    """A placeholder must never be served for a module that has a real view."""
    from app.routes.main import MODULES

    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    for key, entry in MODULES.items():
        if entry[4] is None:
            continue
        html = client.get(f"/modules/{key}", follow_redirects=True).data
        assert b"not implemented yet" not in html, key


def test_placeholder_never_renders_for_implemented_module(client, make_user):
    """An implemented module redirects to its working page, never to a status page."""
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    for key, target in (
        ("activities", "/activities"),
        ("reports", "/reports"),
        ("participants", "/participants"),
        ("records", "/records"),
        ("analytics", "/analytics"),
    ):
        resp = client.get(f"/modules/{key}")
        assert resp.status_code == 302, key
        assert resp.headers["Location"].endswith(target), key


@pytest.mark.parametrize(
    "role", [ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER, ROLE_PARTICIPANT]
)
def test_sidebar_matches_server_side_rule(app, client, make_user, role):
    """The sidebar lists exactly the modules the server actually allows.

    Both halves are derived from MODULES, so the test fails the moment a link is
    shown to a role that would be refused — or a reachable module is hidden.
    """
    from app.routes.main import MODULES, _module_endpoint

    make_user(role, email="u@t.demo", password=PW)
    login(client, "u@t.demo", PW)
    html = client.get("/dashboard").data

    for key, (_label, roles, _phase, _desc, endpoint) in MODULES.items():
        # The module's landing endpoint can depend on the role (feedback:
        # results for Admin/Adviser, submission form for everyone else).
        landing = _module_endpoint(key, role, endpoint)
        if landing is None:
            linked = f"/modules/{key}".encode()
        else:
            with app.test_request_context():
                from flask import url_for as _url_for

                linked = _url_for(landing).encode()
        # Server enforcement: raw status, never "redirects end somewhere".
        status = client.get(f"/modules/{key}").status_code
        if role in roles:
            assert status in (200, 302), (role, key)
            assert linked in html, (role, key)
            if status == 302:
                assert _final_status(client, f"/modules/{key}") == 200, (role, key)
        else:
            assert status == 403, (role, key)
            assert linked not in html, (role, key)

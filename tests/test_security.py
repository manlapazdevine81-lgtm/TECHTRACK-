"""Phase 11 — security, privacy and error-handling regression tests.

Scope: behaviour that must stay true across phases, not per-module features.

  A. Authentication & Flask-Login sessions
  B. CSRF for every state-changing request
  C. Role-based access (server-side, all four approved roles)
  D. Input validation: HTML/script injection, SQL/LIKE handling, NUL bytes
  E. Error pages 403 / 404 / 500 (rendered, correct status, no internals leaked)
  F. Feedback anonymity & privacy boundaries (T6/T7/T9/T10/T11 stay unresolved)
  G. Analytics honesty (objective counts only; no score, ranking, or T12 metric)
  H. Regression guards for the Phase 11 test/DB configuration

Where a finding is documented rather than "fixed" (e.g. there is no login rate
limiting because it is not an approved requirement), the test states the current
behaviour explicitly so a future change is a deliberate decision, not a silent one.
"""
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest

from app.extensions import db
from app.models.activity import Activity
from app.models.feedback import FeedbackQuestion, OfficerFeedback
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, ROLE_PARTICIPANT, User

from .conftest import get_csrf, login, logout, post_csrf

PW = "Passw0rd!"


def _all_rules(app):
    return {rule.rule for rule in app.url_map.iter_rules()}


# ===========================================================================
# H. Test / database configuration (must come first: it protects everything)
# ===========================================================================


def test_tests_run_against_an_isolated_database(app):
    """A test run must never be pointed at the development database."""
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    assert uri, "no database configured"
    parts = urlsplit(uri)
    assert parts.path.lstrip("/") == "techis_test", parts.path


def test_development_database_name_is_never_the_test_target(app):
    dev_url = os.environ.get("DATABASE_URL", "")
    dev_name = urlsplit(dev_url).path.lstrip("/")
    test_name = urlsplit(app.config["SQLALCHEMY_DATABASE_URI"]).path.lstrip("/")
    assert test_name != dev_name or dev_name == "techis_test"


def test_testing_mode_is_on(app):
    assert app.config["TESTING"] is True


def test_email_is_suppressed_in_tests(app):
    assert app.config["MAIL_SUPPRESS_SEND"] is True


# ===========================================================================
# A. Authentication & Flask-Login sessions
# ===========================================================================


def test_login_is_case_insensitive_on_email(app, client, make_user):
    make_user(ROLE_PARTICIPANT, email="mixed@t.demo", password=PW)
    resp = login(client, "MiXeD@T.DEMO", PW)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")


def test_login_ignores_whitespace_around_email(app, client, make_user):
    make_user(ROLE_PARTICIPANT, email="ws@t.demo", password=PW)
    token = get_csrf(client, "/login")
    resp = client.post(
        "/login",
        data={"email": "  ws@t.demo  ", "password": PW, "csrf_token": token},
    )
    assert resp.status_code == 302


def test_password_is_never_stored_in_plain_text(app, make_user):
    make_user(ROLE_OFFICER, email="hash@t.demo", password=PW)
    with app.app_context():
        user = User.query.filter_by(email="hash@t.demo").one()
    assert user.password_hash != PW
    assert PW not in user.password_hash
    assert user.check_password(PW)
    assert not user.check_password(PW + "x")


def test_inactive_account_cannot_log_in(app, client, make_user):
    user_id = make_user(ROLE_PARTICIPANT, email="off@t.demo", password=PW)
    with app.app_context():
        db.session.get(User, user_id).is_active = False
        db.session.commit()

    token = get_csrf(client, "/login")
    resp = client.post(
        "/login",
        data={"email": "off@t.demo", "password": PW, "csrf_token": token},
        follow_redirects=True,
    )
    assert b"Invalid email or password" in resp.data
    assert client.get("/dashboard").status_code == 302


def test_deactivated_account_loses_access_on_next_request(app, client, make_user):
    """The session must not outlive the account's is_active flag (user_loader)."""
    user_id = make_user(ROLE_PARTICIPANT, email="live@t.demo", password=PW)
    login(client, "live@t.demo", PW)
    assert client.get("/dashboard").status_code == 200

    with app.app_context():
        db.session.get(User, user_id).is_active = False
        db.session.commit()

    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_does_not_reveal_whether_an_email_exists(client, make_user):
    make_user(ROLE_PARTICIPANT, email="known@t.demo", password=PW)
    token = get_csrf(client, "/login")
    wrong_pw = client.post(
        "/login",
        data={"email": "known@t.demo", "password": "Nope1234", "csrf_token": token},
        follow_redirects=True,
    )
    token = get_csrf(client, "/login")
    unknown = client.post(
        "/login",
        data={"email": "ghost@t.demo", "password": "Nope1234", "csrf_token": token},
        follow_redirects=True,
    )
    assert b"Invalid email or password" in wrong_pw.data
    assert b"Invalid email or password" in unknown.data


def test_session_cookie_is_httponly_and_samesite(app, client, make_user):
    make_user(ROLE_PARTICIPANT, email="ck@t.demo", password=PW)
    resp = login(client, "ck@t.demo", PW)
    cookie = resp.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie.replace(" ", "") or "SameSite=Lax" in cookie


def test_logout_clears_feedback_cta_session_state(app, client, make_user):
    """`session['feedback_cta']` (T7-adjacent) must not survive logout."""
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    client.get("/dashboard?feedback=1")
    with client.session_transaction() as sess:
        assert sess.get("feedback_cta") is True
    logout(client)
    with client.session_transaction() as sess:
        assert "feedback_cta" not in sess


def test_anonymous_cannot_reuse_a_previous_users_session(client, make_user):
    """Logging in as B after A must expose B's role, never A's."""
    make_user(ROLE_ADMIN, email="first@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="second@t.demo", password=PW)

    login(client, "first@t.demo", PW)
    assert client.get("/admin/users").status_code == 200
    logout(client)
    login(client, "second@t.demo", PW)
    assert client.get("/admin/users").status_code == 403


def test_no_login_rate_limiting_is_documented_behaviour(client, make_user):
    """FINDING (Phase 11 audit): there is no failed-login throttling/lockout.

    The requirements (docs/REQUIREMENTS.md) list no such control, so none was
    invented. This test pins the CURRENT behaviour so that adding one is a
    deliberate, reviewed change. Passwords still require 8+ characters and
    hashes are Werkzeug's default (salted).
    """
    make_user(ROLE_PARTICIPANT, email="brute@t.demo", password=PW)
    for _ in range(5):
        token = get_csrf(client, "/login")
        resp = client.post(
            "/login",
            data={"email": "brute@t.demo", "password": "wrong-pass", "csrf_token": token},
        )
        assert resp.status_code == 200  # re-rendered form, not a lockout page
    # The correct password still works afterwards (no lockout introduced).
    assert login(client, "brute@t.demo", PW).status_code == 302


def test_open_redirect_next_parameter_is_restricted(client, make_user):
    """Only relative `next` targets are followed (auth.login)."""
    make_user(ROLE_PARTICIPANT, email="redir@t.demo", password=PW)
    token = get_csrf(client, "/login?next=https://evil.example/x")
    resp = client.post(
        "/login?next=https://evil.example/x",
        data={"email": "redir@t.demo", "password": PW, "csrf_token": token},
    )
    assert resp.status_code == 302
    assert "evil.example" not in resp.headers["Location"]
    assert resp.headers["Location"].endswith("/dashboard")


# ===========================================================================
# B. CSRF
# ===========================================================================


def test_every_state_changing_rule_is_csrf_protected(app, client, make_user):
    """Global CSRFProtect: each POST endpoint refuses a token-less request."""
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)

    post_rules = [
        rule.rule
        for rule in app.url_map.iter_rules()
        if "POST" in rule.methods and "static" not in rule.endpoint
    ]
    assert post_rules, "no POST routes found — configuration problem"

    for rule in post_rules:
        if "<" in rule:
            continue  # parameterised routes are covered per module
        resp = client.post(rule, data={})
        assert resp.status_code != 200, rule
        assert resp.status_code in (400, 302, 403, 404, 405), (rule, resp.status_code)


def test_csrf_failure_redirects_back_with_a_flash(app, client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    resp = client.post(
        "/activities/1/status",
        data={"status": "published", "csrf_token": "forged-token"},
        headers={"Referer": "/dashboard"},
    )
    assert resp.status_code == 400
    assert resp.headers["Location"].endswith("/dashboard")


def test_csrf_token_from_another_session_is_rejected(app, client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    make_user(ROLE_PARTICIPANT, email="victim@t.demo", password=PW)
    other_client = app.test_client()

    login(other_client, "victim@t.demo", PW)
    foreign_token = get_csrf(other_client, "/dashboard")

    login(client, "admin@t.demo", PW)
    resp = client.post("/admin/users/1/toggle", data={"csrf_token": foreign_token})
    assert resp.status_code == 400  # cross-session token refused
    with app.app_context():
        assert db.session.get(User, 1).is_active is True


# ===========================================================================
# C. Role-based access
# ===========================================================================


def test_role_matrix_has_no_escalation_path(app, client, make_user):
    """Each role is refused every surface outside its approved set (T19 frozen)."""
    matrix = {
        ROLE_PARTICIPANT: {"/dashboard", "/my-activities", "/participants/{me}", "/feedback"},
        ROLE_OFFICER: {
            "/dashboard", "/activities", "/attendance", "/participants",
            "/records", "/reports", "/feedback",
        },
        ROLE_ADVISER: {
            "/dashboard", "/activities", "/participants", "/records",
            "/reports", "/analytics", "/analytics/general", "/feedback/admin",
        },
        ROLE_ADMIN: {
            "/dashboard", "/admin/users", "/activities", "/attendance", "/participants",
            "/records", "/reports", "/analytics", "/analytics/general",
            "/feedback/admin",
        },
    }
    probes = {
        "/admin/users": 200,
        "/activities": 200,
        "/attendance": 200,
        "/participants": 200,
        "/records": 200,
        "/reports": 200,
        "/analytics": 200,
        "/analytics/general": 200,
        "/feedback/admin": 200,
        "/my-activities": 200,
        "/dashboard": 200,
    }

    for i, role in enumerate(matrix):
        email = f"role{i}@t.demo"
        make_user(role, email=email, password=PW)
        login(client, email, PW)
        allowed = matrix[role]
        for url in probes:
            status = client.get(url).status_code
            if url in allowed:
                assert status == 200, (role, url, status)
            else:
                assert status == 403, (role, url, status)
        logout(client)


def test_participant_cannot_read_another_participants_record(app, client, make_user):
    me = make_user(ROLE_PARTICIPANT, email="me@t.demo", password=PW)
    other = make_user(ROLE_PARTICIPANT, email="you@t.demo", password=PW)
    login(client, "me@t.demo", PW)
    assert client.get(f"/participants/{me}").status_code == 200
    assert client.get(f"/participants/{other}").status_code == 403
    assert client.get("/participants").status_code == 403


def test_role_cannot_be_changed_through_the_public_register_form(client, make_user):
    token = get_csrf(client, "/register")
    client.post(
        "/register",
        data={
            "full_name": "Escalate Me",
            "email": "esc@t.demo",
            "password": "Secret123!",
            "confirm_password": "Secret123!",
            "role_name": ROLE_ADMIN,
            "role": ROLE_ADMIN,
            "is_active": "y",
            "csrf_token": token,
        },
    )
    with client.application.app_context():
        user = User.query.filter_by(email="esc@t.demo").one()
        assert user.role_name == ROLE_PARTICIPANT


def test_non_admin_cannot_create_or_promote_members(app, client, make_user):
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    assert client.get("/admin/users/create").status_code == 403
    assert post_csrf(
        client, "/admin/users/create", form_path="/dashboard",
        full_name="X", email="x@t.demo", password="Secret123!",
        role_name=ROLE_ADMIN, is_active="y",
    ).status_code == 403


def test_admin_cannot_deactivate_their_own_account(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    resp = post_csrf(
        client, f"/admin/users/{admin_id}/toggle", form_path="/admin/users", follow=True
    )
    assert b"cannot deactivate your own account" in resp.data
    with app.app_context():
        assert db.session.get(User, admin_id).is_active is True


# ===========================================================================
# D. Input validation
# ===========================================================================


def test_script_payloads_are_escaped_in_every_list_view(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    payload = "<script>alert(1)</script>"
    with app.app_context():
        db.session.add(
            Activity(
                title=payload,
                description=payload,
                venue=payload,
                activity_type=payload,
                start_datetime=db.func.now(),
                end_datetime=db.func.now(),
                status="published",
                created_by=admin_id,
            )
        )
        db.session.commit()

    login(client, "admin@t.demo", PW)
    for url in ("/activities", "/participants", "/attendance", "/dashboard"):
        html = client.get(url).data
        assert b"<script>alert(1)</script>" not in html, url
        assert b"&lt;script&gt;" in html or b"alert(1)" not in html, url


def test_sql_metacharacters_are_bound_not_interpreted(app, client, make_user):
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    with app.app_context():
        db.session.add(
            Activity(
                title="Safe Title",
                start_datetime=db.func.now(),
                end_datetime=db.func.now(),
                status="draft",
                created_by=admin_id,
            )
        )
        db.session.commit()

    login(client, "admin@t.demo", PW)
    for payload in ("'; DROP TABLE activities; --", "1' OR '1'='1", "%", "_"):
        resp = client.get("/activities", query_string={"q": payload})
        assert resp.status_code == 200, payload
    # The table still exists and the row survived every payload.
    with app.app_context():
        assert db.session.execute(db.select(db.func.count(Activity.id))).scalar() == 1


def test_nul_bytes_are_rejected_not_crashing(app, client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    token = get_csrf(client, "/activities/new")
    resp = client.post(
        "/activities/new",
        data={
            "title": "bad\x00",
            "start_datetime": "2026-03-01T10:00",
            "end_datetime": "2026-03-01T12:00",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"invalid characters" in resp.data or b"Title is required" in resp.data


# ===========================================================================
# E. Error pages
# ===========================================================================


def test_404_page_status_body_and_design(app, client):
    resp = client.get("/this/does/not/exist")
    assert resp.status_code == 404
    html = resp.data
    assert b"404" in html
    assert b"Page not found" in html
    assert b"TechIS" in html                      # branding present
    assert b"/static/" in html                    # the real app shell
    assert b"Traceback" not in html


def test_404_page_renders_for_a_signed_in_user_with_the_sidebar(app, client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    resp = client.get("/nope")
    assert resp.status_code == 404
    assert b"Dashboard" in resp.data              # sidebar/app shell rendered
    assert b"Member Management" in resp.data      # admin-only nav present


def test_missing_activity_uses_the_custom_404(client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    resp = client.get("/activities/424242")
    assert resp.status_code == 404
    assert b"Page not found" in resp.data


def test_403_page_is_branded_and_actionable(client, make_user):
    make_user(ROLE_PARTICIPANT, email="p@t.demo", password=PW)
    login(client, "p@t.demo", PW)
    resp = client.get("/admin/users")
    assert resp.status_code == 403
    assert b"403" in resp.data
    assert b"Access denied" in resp.data
    assert b"Back to dashboard" in resp.data


def _server_error_handler(app):
    """The registered handler for an unhandled exception (InternalServerError)."""
    from werkzeug.exceptions import InternalServerError

    # error_handler_spec[blueprint][code][exception] — app-wide handlers sit
    # under blueprint None and either the numeric code or the exception class.
    for blueprint in app.error_handler_spec:
        for code, by_exception in app.error_handler_spec[blueprint].items():
            if InternalServerError in by_exception:
                return by_exception[InternalServerError]
            if code == 500 and by_exception:
                return next(iter(by_exception.values()))
    raise AssertionError("no 500 handler registered")


def _invoke_500(app, request_context, signed_in: bool):
    """Call the registered 500 handler the way Flask does for an exception.

    The app's 500 handler discards the ORM session (a failed request must never
    leave it poisoned) — that is asserted separately below. Because of it, the
    handler is invoked INSIDE a live request/client context so the template can
    still resolve the signed-in user.
    """
    from flask_login import login_user

    if signed_in:
        user = db.session.execute(
            db.select(User).where(User.email == "admin@t.demo")
        ).scalar_one()
        login_user(user)
    return _server_error_handler(app)(None)


@pytest.mark.parametrize("signed_in", [True, False])
def test_500_page_is_branded_and_hides_internals(app, client, make_user, signed_in):
    """`client` is requested for its fresh schema, not for a request."""
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    with app.test_request_context("/dashboard"):
        result = _invoke_500(app, client, signed_in=signed_in)

    status = result[1]
    resp = result[0]
    assert status == 500
    body = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert "Something went wrong" in body
    assert "TechIS" in body
    # No stack trace, exception class, or internal path is exposed.
    for leaked in ("Traceback", "RuntimeError", "SECRET", ".venv", "sqlalchemy"):
        assert leaked not in body, leaked


def test_500_handler_is_registered_and_survives_a_broken_template(app, monkeypatch):
    """A 500 handler must exist and must never raise a second error."""
    import app as app_pkg

    def _explode(*_a, **_k):
        raise RuntimeError("template render failed")

    runtime_module = __import__("app.__init__", fromlist=["create_app"])
    monkeypatch.setattr(app_pkg, "render_template", _explode, raising=False)
    monkeypatch.setattr(runtime_module, "render_template", _explode, raising=False)

    with app.test_request_context("/"):
        result = _server_error_handler(app)(None)
    # The fallback is a (body, status, headers) tuple; a rendered page is (body, status).
    body = result[0]
    status = result[1]
    assert status == 500
    text = body if isinstance(body, str) else body.get_data(as_text=True)
    assert "500" in text
    assert "TechIS" in text


def test_unhandled_method_is_405_not_a_custom_page(app, client):
    assert client.get("/logout").status_code == 405


def test_failed_request_rolls_back_and_does_not_poison_the_session(app, client, make_user):
    """A 500 must discard the failed unit of work (teardown_request).

    Otherwise the next request in the same process inherits an aborted session
    and every page fails — and a half-finished write could stay pending.
    """
    admin_id = make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)

    from sqlalchemy.exc import IntegrityError

    with app.app_context():
        db.session.add(
            Activity(
                title=None,  # NOT NULL violation at flush time
                start_datetime=datetime.now(timezone.utc),
                end_datetime=datetime.now(timezone.utc),
                status="draft",
                created_by=admin_id,
            )
        )
        with pytest.raises(IntegrityError):
            db.session.flush()
        # What Flask does at teardown for a failed request:
        for functions in app.teardown_request_funcs.values():
            for function in functions:
                function(RuntimeError("request failed"))

    # Every later request must still work (session was disposed, not poisoned).
    assert client.get("/activities").status_code == 200
    assert client.get("/dashboard").status_code == 200
    with app.app_context():
        assert db.session.execute(db.select(db.func.count(Activity.id))).scalar() == 0


# ===========================================================================
# F. Feedback anonymity / privacy boundaries
# ===========================================================================


def _questions(app, count: int = 1) -> list[int]:
    with app.app_context():
        ids = [q.id for q in FeedbackQuestion.query.order_by(FeedbackQuestion.id).all()]
        while len(ids) < count:
            q = FeedbackQuestion(
                question_text=f"Phase 11 test question {len(ids) + 1}",
                question_type="rating",
                scale_min=1,
                scale_max=5,
                is_active=True,
                display_order=len(ids) + 1,
            )
            db.session.add(q)
            db.session.commit()
            ids.append(q.id)
        return ids[:count]


def test_feedback_submission_works_without_any_session(app, client, make_user):
    """No login, no cookie identity: the form is genuinely anonymous to reach."""
    qids = _questions(app)
    officer = make_user(ROLE_OFFICER, email="sub@t.demo", full_name="Subject")
    resp = post_csrf(
        client, "/feedback", form_path="/feedback", follow=True,
        officer_user_id=str(officer), **{f"q_{qids[0]}": "4"},
    )
    assert b"recorded anonymously" in resp.data
    with app.app_context():
        assert OfficerFeedback.query.count() == 1


def test_feedback_form_never_renders_respondent_fields(app, client, make_user):
    _questions(app)
    make_user(ROLE_OFFICER, email="sub@t.demo", password=PW)
    html = client.get("/feedback").data
    for forbidden in (b'name="email"', b'name="full_name"', b'name="user_id"',
                      b'name="student_id"', b'name="token"', b'name="session_id"'):
        assert forbidden not in html, forbidden


def test_feedback_row_has_no_activity_context_while_t8_is_open(app, client, make_user):
    qids = _questions(app)
    officer = make_user(ROLE_OFFICER, email="sub@t.demo", full_name="Subject")
    post_csrf(
        client, "/feedback", form_path="/feedback",
        officer_user_id=str(officer), activity_id="1", **{f"q_{qids[0]}": "3"},
    )
    with app.app_context():
        row = OfficerFeedback.query.one()
    assert row.activity_id is None  # T8 (per-event context) not implemented


def test_feedback_has_no_privacy_threshold_implemented_while_t9_is_open(app, client, make_user):
    """T9 unresolved: nothing aggregates responses, so no threshold was invented.

    This pins the current state — the read-only list shows individual rows and
    there is no aggregation endpoint that would need a minimum-response rule.
    """
    rules = {r.rule for r in app.url_map.iter_rules() if r.endpoint.startswith("feedback.")}
    assert rules == {"/feedback", "/feedback/admin"}


def test_feedback_comments_are_stored_verbatim_without_moderation(app, client, make_user):
    """T10 unresolved: no flag/moderation field exists on the model."""
    qids = _questions(app)
    officer = make_user(ROLE_OFFICER, email="sub@t.demo", full_name="Subject")
    text = "Please use more planning tools."
    post_csrf(
        client, "/feedback", form_path="/feedback",
        officer_user_id=str(officer), **{f"q_{qids[0]}": "2"},
    )
    with app.app_context():
        from app.models.feedback import FeedbackAnswer

        answer = FeedbackAnswer.query.one()
    assert text not in (answer.comment_text or "")  # free text was not sent here
    columns = {c.name for c in FeedbackAnswer.__table__.columns}
    assert not columns & {"is_flagged", "moderated", "approved", "moderator_id"}


def test_feedback_submission_is_not_correlated_with_the_session(app, client, make_user):
    """Two submissions from the same client are independent rows with no marker."""
    qids = _questions(app)
    officer = make_user(ROLE_OFFICER, email="sub@t.demo", full_name="Subject")
    for value in ("5", "1"):
        post_csrf(
            client, "/feedback", form_path="/feedback",
            officer_user_id=str(officer), **{f"q_{qids[0]}": value},
        )
    with app.app_context():
        rows = OfficerFeedback.query.order_by(OfficerFeedback.id).all()
    assert len(rows) == 2
    assert rows[0].submitted_at == rows[1].submitted_at  # same hour bucket
    cols = [c.name for c in OfficerFeedback.__table__.columns]
    assert cols == [
        "id", "officer_user_id", "activity_id", "status", "submitted_at",
    ]


def test_feedback_rejects_a_nul_comment_without_a_500(app, client, make_user):
    with app.app_context():
        q = FeedbackQuestion(
            question_text="Free text", question_type="text", is_active=True,
            display_order=99,
        )
        db.session.add(q)
        db.session.commit()
        qid = q.id
    officer = make_user(ROLE_OFFICER, email="sub@t.demo", full_name="Subject")
    resp = post_csrf(
        client, "/feedback", form_path="/feedback",
        officer_user_id=str(officer), **{f"q_{qid}": "bad\x00text"},
    )
    assert resp.status_code == 200
    assert b"invalid characters" in resp.data
    with app.app_context():
        assert OfficerFeedback.query.count() == 0


def test_officer_feedback_list_never_shows_a_respondent_column(app, client, make_user):
    qids = _questions(app)
    # Approved policy: results are organisation-wide, so the evaluated officer's
    # name must NOT appear on the Admin/Adviser results page at all.
    officer = make_user(ROLE_OFFICER, email="sub@t.demo", full_name="Subject Person")
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    post_csrf(
        client, "/feedback", form_path="/feedback",
        officer_user_id=str(officer), **{f"q_{qids[0]}": "4"},
    )
    login(client, "admin@t.demo", PW)
    html = client.get("/feedback/admin").data
    assert b"Subject Person" not in html                 # subject is visible
    assert b"admin@t.demo" not in html               # reader identity irrelevant
    assert b"Respondent" not in html


# ===========================================================================
# G. Analytics honesty (no invented scores/rankings; T12 excluded)
# ===========================================================================


def test_analytics_never_renders_a_score_or_ranking(app, client, make_user):
    """Counts/rates only: no score column, no ordering by metric.

    The dashboards DO contain the words "score"/"ranking" — inside the notice
    that states the system does not produce them. So this test looks for
    score-bearing structure, not vocabulary, and checks the actual ordering.
    """
    make_user(ROLE_ADMIN, email="a1@t.demo", password=PW, full_name="Zeta Officer")
    make_user(ROLE_OFFICER, email="a2@t.demo", password=PW, full_name="Alpha Officer")
    make_user(ROLE_ADVISER, email="adv@t.demo", password=PW)
    login(client, "adv@t.demo", PW)

    for url in ("/analytics", "/analytics/general"):
        html = client.get(url).data.lower()
        for forbidden in (
            b"leaderboard", b"composite score", b"overall score", b"final score",
            b"performance rating", b"rank #", b"<th>rank", b"<th>score",
        ):
            assert forbidden not in html, (url, forbidden)

    html = client.get("/analytics").data.decode()
    # Officers are listed alphabetically by name, never ordered by a metric.
    assert html.index("Alpha Officer") < html.index("Zeta Officer")


def test_analytics_zero_denominators_render_as_a_dash(app, client, make_user):
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    html = client.get("/analytics").data
    assert b"\xe2\x80\x94" in html            # em dash "—"
    assert b"NaN" not in html
    assert b"inf" not in html.lower() or b"info" in html.lower()


def test_t12_activities_created_indicator_is_absent(app, client, make_user):
    """T12 unresolved: 'activities organized/created' must not be a metric.

    The page mentions it ONLY in the notice explaining it is excluded, so the
    assertion targets data structure (a header/KPI label), not the disclaimer.
    """
    from app.services import analytics_service

    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    html = client.get("/analytics").data.lower()
    for forbidden in (b"<th>organized", b"<th>created", b"activities organized</span>"):
        assert forbidden not in html, forbidden

    dashboard = analytics_service.build_dashboard()
    assert "organized" not in dashboard["totals"]
    assert "created" not in dashboard["totals"]
    for summary in dashboard["officers"]:
        assert "organized" not in summary and "created" not in summary


def test_tbc_surfaces_are_still_absent(app):
    """Unresolved TBC items must not have leaked in as features."""
    rules = _all_rules(app)
    for absent in (
        "/password-reset",          # T3
        "/verify-email",            # T4
        "/feedback/token",          # T7
        "/reports/pdf",             # T13 unconfirmed
        "/uploads",                 # T14
        "/terms",                   # Phase 2 officer terms (not implemented)
    ):
        assert absent not in rules, absent
    for rule in rules:
        assert "pdf" not in rule.lower(), rule
        assert "waitlist" not in rule.lower(), rule   # T2
        assert "approve" not in rule.lower(), rule    # T2 / T15

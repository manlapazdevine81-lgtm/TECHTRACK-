"""Phase 6 — anonymous officer feedback: anonymity, write-once, validation, access.

The anonymity assertions are the point of this file: they inspect the DATABASE
schema, the stored rows, and the LOG OUTPUT for any trace of a respondent.
Runs against techis_test via the shared fixtures.
"""
import logging

import pytest

from app.extensions import db
from app.models.feedback import FeedbackAnswer, FeedbackQuestion, OfficerFeedback
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, ROLE_PARTICIPANT, User

from .conftest import login, logout, post_csrf

PW = "Passw0rd!"
FORM_URL = "/feedback"


def _questions(app, count: int = 2):
    """Create question structure ONLY (text is T6; any wording is test-local)."""
    with app.app_context():
        existing = FeedbackQuestion.query.count()
        if existing >= count:
            return [q.id for q in FeedbackQuestion.query.order_by(FeedbackQuestion.id).all()]
        made = []
        for i in range(existing, count):
            # Question 1 is a rating; later ones are free text, so the
            # validation tests can exercise both answer kinds.
            is_rating = i == 0
            q = FeedbackQuestion(
                question_text=f"Test question {i + 1}",
                question_type="rating" if is_rating else "text",
                scale_min=1 if is_rating else None,
                scale_max=5 if is_rating else None,
                is_active=True,
                display_order=i + 1,
            )
            db.session.add(q)
            made.append(q)
        db.session.commit()
        return [q.id for q in FeedbackQuestion.query.order_by(FeedbackQuestion.id).all()]


def _officer(app, make_user, email="off@t.demo") -> int:
    return make_user(ROLE_OFFICER, email=email, password=PW, full_name="Officer Subject")


def _submit(client, officer_id, qids, values=None, follow=True):
    data = {"officer_user_id": str(officer_id)}
    for i, qid in enumerate(qids):
        v = (values[i] if values and i < len(values) else "4")
        if v is not None:
            data[f"q_{qid}"] = str(v)
    return post_csrf(client, FORM_URL, form_path=FORM_URL, follow=follow, **data)


def _all_feedback(app) -> list:
    with app.app_context():
        return OfficerFeedback.query.order_by(OfficerFeedback.id).all()


# ---------------------------------------------------------------------------
# Schema-level anonymity
# ---------------------------------------------------------------------------


def test_no_respondent_columns_exist_in_schema():
    """The table itself must have no way to identify the submitter."""
    columns = {c.name for c in OfficerFeedback.__table__.columns}
    forbidden = {
        "respondent_id", "user_id", "submitter_id", "submitter_email",
        "ip_address", "user_agent", "response_token", "session_id",
    }
    assert not (columns & forbidden), columns & forbidden
    # The ONLY user link is the officer being evaluated.
    user_fks = [
        fk.parent.name
        for fk in OfficerFeedback.__table__.foreign_keys
        if fk.target_fullname.startswith("users.")
    ]
    assert user_fks == ["officer_user_id"]


def test_answers_table_has_no_respondent_columns():
    columns = {c.name for c in FeedbackAnswer.__table__.columns}
    assert not (columns & {"respondent_id", "user_id", "submitter_id", "response_token"})


# ---------------------------------------------------------------------------
# Storage-level anonymity
# ---------------------------------------------------------------------------


def test_submission_stores_only_the_officer_being_evaluated(app, client, make_user):
    qids = _questions(app)
    officer_id = _officer(app, make_user)

    resp = _submit(client, officer_id, qids)
    assert b"recorded anonymously" in resp.data

    rows = _all_feedback(app)
    assert len(rows) == 1
    row = rows[0]
    assert row.officer_user_id == officer_id
    assert row.activity_id is None
    # Nothing on the row mentions any account other than the subject.
    values = [getattr(row, c.name) for c in OfficerFeedback.__table__.columns]
    assert not any(isinstance(v, str) and "@" in v for v in values)


def test_submitted_at_is_rounded_to_the_hour(app, client, make_user):
    """No per-response timestamp precision may survive storage (C1.4)."""
    qids = _questions(app)
    officer_id = _officer(app, make_user)

    _submit(client, officer_id, qids)
    row = _all_feedback(app)[0]
    assert row.submitted_at.minute == 0
    assert row.submitted_at.second == 0
    assert row.submitted_at.microsecond == 0


def test_two_submissions_are_indistinguishable_by_time(app, client, make_user):
    qids = _questions(app)
    officer_a = _officer(app, make_user, email="a@t.demo")
    officer_b = _officer(app, make_user, email="b@t.demo")

    _submit(client, officer_a, qids)
    _submit(client, officer_b, qids)
    rows = _all_feedback(app)
    assert len(rows) == 2
    assert rows[0].submitted_at == rows[1].submitted_at


# ---------------------------------------------------------------------------
# Log-level anonymity
# ---------------------------------------------------------------------------


def test_submission_logs_do_not_leak_respondent(app, client, make_user, caplog):
    """Logs must not contain session/user identity, IP, or user agent (C1.3)."""
    qids = _questions(app)
    officer_id = _officer(app, make_user)

    with caplog.at_level(logging.INFO):
        _submit(client, officer_id, qids)

    text = caplog.text.lower()
    for leaked in (
        "127.0.0.1", "localhost", "ip=", "user-agent", "mozilla",
        "password", "session", "off@t.demo",
    ):
        assert leaked not in text, leaked
    # It may name the officer being evaluated and the answer count.
    assert "anonymous feedback recorded" in text


def test_anonymous_user_submission_is_logged_the_same_as_logged_in(
    app, client, make_user, caplog
):
    """A logged-in submitter leaves no extra log trace."""
    qids = _questions(app)
    officer_id = _officer(app, make_user)
    make_user(ROLE_PARTICIPANT, email="respondent@t.demo", password=PW)

    login(client, "respondent@t.demo", PW)
    with caplog.at_level(logging.INFO):
        _submit(client, officer_id, qids)

    assert "respondent@t.demo" not in caplog.text
    assert "Participant" not in caplog.text


# ---------------------------------------------------------------------------
# Write-once
# ---------------------------------------------------------------------------


def test_no_edit_or_delete_routes_exist(app):
    """Write-once means no user-facing mutation beyond creation."""
    rules = {r.rule for r in app.url_map.iter_rules() if r.endpoint.startswith("feedback.")}
    assert rules == {"/feedback", "/feedback/admin"}
    for rule in rules:
        methods = {
            m
            for r in app.url_map.iter_rules()
            if r.rule == rule
            for m in r.methods
        }
        assert "DELETE" not in methods
        assert "PUT" not in methods
        assert "PATCH" not in methods


def test_resubmission_creates_a_new_row_never_edits(app, client, make_user):
    """A second submission is a separate anonymous row, not an update."""
    qids = _questions(app)
    officer_id = _officer(app, make_user)

    _submit(client, officer_id, qids, values=["5", "First"])
    _submit(client, officer_id, qids, values=["3", "Second"])

    rows = _all_feedback(app)
    assert len(rows) == 2
    assert rows[0].id != rows[1].id
    with app.app_context():
        first = OfficerFeedback.query.order_by(OfficerFeedback.id).first()
        comments = [a.comment_text for a in first.answers]
    assert "First" in comments


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_missing_officer_is_rejected(app, client, make_user):
    qids = _questions(app)
    _officer(app, make_user)

    resp = post_csrf(
        client, FORM_URL, form_path=FORM_URL, follow=True,
        officer_user_id="", **{f"q_{qids[0]}": "4"},
    )
    assert b"Select the officer" in resp.data
    assert _all_feedback(app) == []


def test_participant_cannot_be_evaluated(app, client, make_user):
    qids = _questions(app)
    participant_id = make_user(ROLE_PARTICIPANT, email="p@t.demo", full_name="P")
    _officer(app, make_user)

    resp = _submit(client, participant_id, qids)
    assert b"could not be found" in resp.data
    assert _all_feedback(app) == []

def test_out_of_scale_rating_rejected(app, client, make_user):
    qids = _questions(app)
    officer_id = _officer(app, make_user)
    resp = _submit(client, officer_id, qids, values=["99"])
    assert b"must be between" in resp.data
    assert _all_feedback(app) == []


def test_non_numeric_rating_rejected(app, client, make_user):
    qids = _questions(app)
    officer_id = _officer(app, make_user)

    resp = _submit(client, officer_id, qids, values=["excellent"])
    assert b"whole number" in resp.data
    assert _all_feedback(app) == []


def test_missing_required_rating_rejected(app, client, make_user):
    qids = _questions(app)
    officer_id = _officer(app, make_user)

    resp = _submit(client, officer_id, qids, values=[""])
    assert b"Answer required" in resp.data
    assert _all_feedback(app) == []


def test_submission_without_csrf_rejected(app, client, make_user):
    qids = _questions(app)
    officer_id = _officer(app, make_user)

    resp = client.post(
        FORM_URL, data={"officer_user_id": str(officer_id), f"q_{qids[0]}": "4"}
    )
    assert resp.status_code == 400
    assert _all_feedback(app) == []


# ---------------------------------------------------------------------------
# Access & anonymous reachability
# ---------------------------------------------------------------------------


def test_form_is_reachable_without_login(app, client, make_user):
    """Requiring a session would link an account to the response moment."""
    _questions(app)
    _officer(app, make_user)
    resp = client.get(FORM_URL)
    assert resp.status_code == 200
    assert b"anonymous" in resp.data.lower()


def test_form_renders_when_no_questions_exist(app, client, make_user):
    _officer(app, make_user)
    resp = client.get(FORM_URL)
    assert resp.status_code == 200
    assert b"not finalized yet" in resp.data


@pytest.mark.parametrize("email,role", [
    ("admin@t.demo", ROLE_ADMIN),
    ("adv@t.demo", ROLE_ADVISER),
])
def test_reviewers_can_read_results(app, client, make_user, email, role):
    """Approved: Admin and Adviser see the ratings-only results page."""
    qids = _questions(app)
    officer_id = _officer(app, make_user)
    make_user(role, email=email, password=PW, full_name="Reader")
    _submit(client, officer_id, qids)

    login(client, email, PW)
    resp = client.get("/feedback/admin")
    assert resp.status_code == 200
    assert b"Officer Feedback" in resp.data
    # The subject's name is NOT shown: results are organisation-wide only.
    assert b"Officer Subject" not in resp.data


def test_officer_cannot_read_results(app, client, make_user):
    """Approved: reviewing is the Admin/Adviser job; officers submit."""
    make_user(ROLE_OFFICER, email="reader@t.demo", password=PW)
    login(client, "reader@t.demo", PW)
    assert client.get("/feedback/admin").status_code == 403


def test_participant_cannot_read_feedback_list(app, client, make_user):
    make_user(ROLE_PARTICIPANT, email="p@t.demo", password=PW)
    login(client, "p@t.demo", PW)
    assert client.get("/feedback/admin").status_code == 403


def test_anonymous_redirected_from_feedback_list(app, client):
    resp = client.get("/feedback/admin")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_feedback_list_shows_no_per_response_timestamps(app, client, make_user):
    """Approved: no per-response metadata of any kind on the results page."""
    qids = _questions(app)
    officer_id = _officer(app, make_user)
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    _submit(client, officer_id, qids)

    login(client, "admin@t.demo", PW)
    html = client.get("/feedback/admin").data
    assert b"submitted_at" not in html
    assert b"2026-" not in html


# ---------------------------------------------------------------------------
# Officer write path (Phase 6 — officers can write feedback about other officers)
# ---------------------------------------------------------------------------

def test_logged_in_officer_can_access_feedback_form(app, client, make_user):
    """An officer logged in can reach the anonymous submission form."""
    qids = _questions(app)
    subject_id = _officer(app, make_user, email="subject@t.demo")
    make_user(ROLE_OFFICER, email="writer@t.demo", password=PW, full_name="Feedback Writer")

    login(client, "writer@t.demo", PW)
    resp = client.get("/feedback")
    assert resp.status_code == 200
    assert b"Officer being evaluated" in resp.data
    assert b"Submit anonymously" in resp.data


def test_logged_in_officer_can_submit_feedback(app, client, make_user):
    """An officer logged in can submit feedback about another officer."""
    qids = _questions(app)
    subject_id = _officer(app, make_user, email="subject@t.demo")
    make_user(ROLE_OFFICER, email="writer@t.demo", password=PW, full_name="Feedback Writer")

    login(client, "writer@t.demo", PW)
    resp = _submit(client, subject_id, qids)
    assert b"recorded anonymously" in resp.data

    rows = _all_feedback(app)
    assert len(rows) == 1
    assert rows[0].officer_user_id == subject_id


def test_feedback_submission_anonymous_even_when_logged_in(app, client, make_user):
    """No respondent identity is stored even when the submitter is logged in."""
    qids = _questions(app)
    subject_id = _officer(app, make_user, email="subject@t.demo")
    make_user(ROLE_OFFICER, email="writer@t.demo", password=PW, full_name="Feedback Writer")

    login(client, "writer@t.demo", PW)
    _submit(client, subject_id, qids)

    rows = _all_feedback(app)
    assert len(rows) == 1
    row = rows[0]
    values = [getattr(row, c.name) for c in OfficerFeedback.__table__.columns]
    # No email, name, or other identifying string of any account on the row.
    assert not any(isinstance(v, str) and "@" in v for v in values)
    # The only user FK is the officer being evaluated.
    user_fks = [
        fk.parent.name
        for fk in OfficerFeedback.__table__.foreign_keys
        if fk.target_fullname.startswith("users.")
    ]
    assert user_fks == ["officer_user_id"]
# ---------------------------------------------------------------------------
# Approved role split: public submission, Admin/Adviser ratings-only results
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("email,role", [
    ("admin@t.demo", ROLE_ADMIN),
    ("adv@t.demo", ROLE_ADVISER),
])
def test_reviewer_roles_cannot_open_the_submission_form(app, client, make_user, email, role):
    """GET /feedback is refused for Admin and Adviser (server-side, not hidden)."""
    _questions(app)
    _officer(app, make_user)
    make_user(role, email=email, password=PW)
    login(client, email, PW)
    assert client.get("/feedback").status_code == 403


@pytest.mark.parametrize("email,role", [
    ("admin@t.demo", ROLE_ADMIN),
    ("adv@t.demo", ROLE_ADVISER),
])
def test_reviewer_roles_cannot_submit_feedback(app, client, make_user, email, role):
    """POST is refused too — a hidden form alone would not be protection."""
    qids = _questions(app)
    officer_id = _officer(app, make_user)
    make_user(role, email=email, password=PW)

    login(client, email, PW)
    resp = client.post(
        FORM_URL,
        data={"officer_user_id": str(officer_id), f"q_{qids[0]}": "4"},
    )
    # CSRF runs first for a logged-in session, so nothing is written either way.
    assert resp.status_code in (400, 403)
    assert _all_feedback(app) == []


def test_anonymous_visitor_still_reaches_the_form(app, client, make_user):
    """The public/anonymous path is unchanged (T7 unresolved, no login added)."""
    _questions(app)
    _officer(app, make_user)
    assert client.get(FORM_URL).status_code == 200


def test_anonymous_submission_still_works(app, client, make_user):
    qids = _questions(app)
    officer_id = _officer(app, make_user)
    resp = _submit(client, officer_id, qids)
    assert b"recorded anonymously" in resp.data
    assert len(_all_feedback(app)) == 1
    # No cookie/session identity was required to submit.
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


@pytest.mark.parametrize("email,role", [
    ("admin@t.demo", ROLE_ADMIN),
    ("adv@t.demo", ROLE_ADVISER),
])
def test_reviewers_can_open_the_results_page(app, client, make_user, email, role):
    _questions(app)
    _officer(app, make_user)
    make_user(role, email=email, password=PW)
    login(client, email, PW)
    resp = client.get("/feedback/admin")
    assert resp.status_code == 200
    assert b"Ratings only" in resp.data


def test_officer_is_denied_the_results_page(app, client, make_user):
    make_user(ROLE_OFFICER, email="off@t.demo", password=PW)
    login(client, "off@t.demo", PW)
    assert client.get("/feedback/admin").status_code == 403


def test_anonymous_is_redirected_from_the_results_page(client):
    resp = client.get("/feedback/admin")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# --- privacy while T9 is unresolved ----------------------------------------


def test_results_page_hides_all_figures_while_t9_is_unresolved(app, client, make_user):
    """Even WITH data, no averages / counts / distributions may appear."""
    qids = _questions(app)
    officer_id = _officer(app, make_user)
    for value in ("5", "4", "3"):
        _submit(client, officer_id, qids, values=[value])
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)

    login(client, "admin@t.demo", PW)
    page = client.get("/feedback/admin").data.decode()

    # Inspect only the BODY region (the shell contributes kpi/JS numbers).
    start = page.index('<div class="page-head">')
    end = page.index("</main>", start)
    body = page[start:end]

    for leaked in ("5.0", "4.0", " (5)", " (4)"):
        assert leaked not in body, leaked
    for forbidden in ("Average", "Distribution", "Response count", "Trend"):
        assert forbidden not in body, forbidden

    # And it explains WHY, rather than showing an empty table.
    assert "pending privacy-threshold approval" in body
    assert "<table" not in body


def test_results_page_shows_neutral_state_without_data(app, client, make_user):
    """No submissions at all must still render the approved neutral state."""
    _questions(app)
    _officer(app, make_user)
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    page = client.get("/feedback/admin").data.decode()
    assert "No responses recorded yet" in page
    start = page.index('<div class="page-head">')
    body = page[start : page.index("</main>", start)]
    assert "<table" not in body


def test_results_page_never_renders_comments(app, client, make_user):
    with app.app_context():
        q = FeedbackQuestion(
            question_text="Free text", question_type="text",
            is_active=True, display_order=99,
        )
        db.session.add(q)
        db.session.commit()
        free_text_id = q.id

    officer_id = _officer(app, make_user)
    secret = "UNIQUE-COMMENT-MARKER-7788"
    post_csrf(
        client, FORM_URL, form_path=FORM_URL,
        officer_user_id=str(officer_id), **{f"q_{free_text_id}": secret},
    )
    with app.app_context():
        assert FeedbackAnswer.query.filter_by(comment_text=secret).count() == 1

    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    login(client, "admin@t.demo", PW)
    body = client.get("/feedback/admin").data
    assert secret.encode() not in body


def test_results_page_contains_no_per_response_records(app, client, make_user):
    qids = _questions(app)
    officer_id = _officer(app, make_user)
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    _submit(client, officer_id, qids)

    login(client, "admin@t.demo", PW)
    body = client.get("/feedback/admin").data
    for forbidden in (b"Officer Subject", b"submitted_at", b"<table", b"<tbody"):
        assert forbidden not in body, forbidden


def test_results_route_loads_no_comments(app, client, make_user, monkeypatch):
    """The results query must not select `feedback_answers` at all."""
    qids = _questions(app)
    officer_id = _officer(app, make_user)
    make_user(ROLE_ADMIN, email="admin@t.demo", password=PW)
    _submit(client, officer_id, qids)

    from app.services import feedback_service

    executed = []

    real_execute = db.session.execute

    def _spy(statement, *args, **kwargs):
        executed.append(str(statement))
        return real_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db.session, "execute", _spy)
    login(client, "admin@t.demo", PW)
    client.get("/feedback/admin")
    monkeypatch.undo()

    joined = " | ".join(executed)
    assert "feedback_answers" not in joined
    assert "officer_feedback" in joined  # it does count submissions, nothing more


# --- evaluated-officer label -------------------------------------------------


def test_form_labels_officer_with_active_position(app, client, make_user):
    from app.models.organization import Organization
    from app.models.position import Position
    from app.services import position_service

    _questions(app)
    officer_id = _officer(app, make_user)
    with app.app_context():
        org = Organization(name="Tech Innovators Society")
        db.session.add(org)
        db.session.flush()
        position = Position(
            organization_id=org.id, title="Chief Operating Officer",
            department=None, duties="Duties", sort_order=0,
        )
        db.session.add(position)
        db.session.commit()
        user = db.session.get(User, officer_id)
        position_service.assign_position(user, position)

    html = client.get(FORM_URL).data.decode()
    assert "Officer Subject (Chief Operating Officer)" in html


def test_form_falls_back_to_role_without_a_position(app, client, make_user):
    _questions(app)
    _officer(app, make_user)
    html = client.get(FORM_URL).data.decode()
    assert "Officer Subject (TechIS Officer)" in html


def test_login_is_not_required_and_no_session_is_created_by_submitting(app, client, make_user):
    """Anonymity: a submission must not leave any session identity behind."""
    qids = _questions(app)
    officer_id = _officer(app, make_user)
    _submit(client, officer_id, qids)
    with client.session_transaction() as sess:
        assert sess.get("_user_id") is None
    # The stored row has no respondent column at all.
    row = _all_feedback(app)[0]
    assert {c.name for c in OfficerFeedback.__table__.columns} == {
        "id", "officer_user_id", "activity_id", "status", "submitted_at",
    }

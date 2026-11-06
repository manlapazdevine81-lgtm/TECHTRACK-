"""Phase 6: anonymous officer feedback submission (ERD contract C1).

Design decisions and their justification:
  * The submission form is reachable WITHOUT logging in. Requiring a session
    would create a direct link between an authenticated account and the response
    moment — exactly what C1 forbids. T7 (distribution method) is unresolved, so
    the form is openly reachable at a stable URL and NO token, invitation, or
    per-respondent link exists. TechIS can decide distribution later (T7)
    without changing this module's anonymity guarantees.
  * Question structure is created by the Phase 6 migration as DRAFT rows that
    explicitly state T6 is unresolved. This module never invents final question
    wording or a rating scale; it renders whatever active rows exist.

Write-once: there is no edit or delete endpoint anywhere in this blueprint.
"""
import logging

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.feedback import OfficerFeedback
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER, Role, User
from app.services import feedback_service
from app.utils.decorators import role_required

bp = Blueprint("feedback", __name__)

# Roles that may READ results. Exactly these two.
_REVIEW_ROLES = (ROLE_ADMIN, ROLE_ADVISER)
# The officers who may be the SUBJECT of feedback.
_SUBJECT_ROLES = (ROLE_ADMIN, ROLE_OFFICER)

logger = logging.getLogger(__name__)


def subjects() -> list[User]:
    """Active accounts eligible to be evaluated."""
    return list(
        db.session.execute(
            db.select(User)
            .join(Role, User.role_id == Role.id)
            .where(User.is_active.is_(True), Role.name.in_(_SUBJECT_ROLES))
            .order_by(User.full_name)
        )
        .scalars()
        .all()
    )


def _resolve_subject(raw: str):
    """Return the officer being evaluated, or (None, error)."""
    raw = (raw or "").strip()
    if not raw:
        return None, "Select the officer this feedback is about."
    if not raw.isdigit():
        return None, "Officer is not a valid selection."
    user = db.session.get(User, int(raw))
    if user is None or not user.is_active or user.role_name not in _SUBJECT_ROLES:
        return None, "That officer could not be found."
    return user, None


@bp.route("/feedback", methods=["GET", "POST"])
def submit():
    """Anonymous submission form. No login, no session identity recorded.

    ACCESS POLICY (approved): submission stays PUBLIC and anonymous — no login,
    no token, no session correlation (T7 unresolved). The two review roles are
    the exception: a System Administrator or TechIS Adviser who is currently
    signed in is refused, because their job is to read the aggregate results,
    not to write into them. That check is enforced here in the VIEW (not by
    hiding a link) and applies to GET and POST alike.

    An anonymous visitor is unaffected: the check is skipped entirely when
    nobody is signed in, so the public form remains reachable.
    """
    from flask_login import current_user

    if current_user.is_authenticated and current_user.role_name in _REVIEW_ROLES:
        abort(403)

    # Officers being evaluated are labelled with their current organizational
    # position, falling back to the system role when none is assigned.
    officers = subjects()
    labels = feedback_service.subject_labels_with_position()
    questions = feedback_service.active_questions()

    if request.method == "POST":
        officer, error = _resolve_subject(request.form.get("officer_user_id"))
        answers, errors = feedback_service.validate_answers(request.form, questions)
        if error:
            errors.insert(0, error)

        if not errors:
            try:
                feedback_service.create_submission(officer.id, answers)
            except IntegrityError:
                db.session.rollback()
                flash(
                    "Your feedback could not be saved. Please try again.", "error"
                )
                return redirect(url_for("feedback.submit"))
            flash(
                "Thank you — your feedback was recorded anonymously.", "success"
            )
            return redirect(url_for("feedback.submit"))

        for msg in errors:
            flash(msg, "error")
        return render_template(
            "feedback/form.html",
            officers=officers,
            officer_labels=labels,
            questions=questions,
            form_values=request.form.to_dict(),
        )

    return render_template(
        "feedback/form.html",
        officers=officers,
        officer_labels=labels,
        questions=questions,
        form_values={},
    )


@bp.route("/feedback/admin")
@login_required
@role_required(*_REVIEW_ROLES)
def feedback_list():
    """Ratings-only results, organisation-wide (Admin + Adviser).

    PRIVACY CONTRACT while T9 (privacy threshold) is unresolved:
      * NO raw averages, response counts, distributions, trends or per-officer
        breakdowns are computed or displayed.
      * NO comments are loaded — `feedback_answers.comment_text` is never
        selected by any query this view runs.
      * NO respondent identity, submission timestamps or individual-response
        rows exist in the template context, the HTML, or any JSON.

    The only fact exposed is a single boolean: whether any response has ever
    been recorded. That is what lets the page distinguish "nothing submitted
    yet" from "results are pending privacy-threshold approval" without leaking
    a number.
    """
    state = feedback_service.organisation_wide_rating_metadata()
    return render_template("feedback/results.html", **state)

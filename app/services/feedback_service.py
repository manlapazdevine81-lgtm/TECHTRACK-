"""Phase 6 service: anonymous officer feedback (ERD contract C1).

Anonymity safeguards implemented HERE:
  * `create_submission()` accepts NO submitter identity of any kind — not a user
    object, id, email, session, IP, or user agent. The signature itself makes
    storing a respondent impossible.
  * Logging: this module logs only COUNTS and the officer being evaluated.
    It never logs `current_user`, session data, request IP, `User-Agent`, or any
    value that could be tied to a specific submission row (C1.3).
  * `submitted_at` is rounded to the hour on write (`_round_to_hour`) so
    analytics cannot reconstruct per-response timing (C1.4).
  * Write-once: the service exposes create + read only; there is no update or
    delete path.

T6 (question content) and T7 (distribution) remain unresolved — nothing here
invents question text, scale, tokens, or a distribution mechanism.
"""
import logging
from datetime import datetime, timezone

from app.extensions import db
from app.models.feedback import FeedbackAnswer, FeedbackQuestion, OfficerFeedback
from app.models.user import Role, User

logger = logging.getLogger(__name__)

# Answer payload limits (validation only — not business rules from T6).
MAX_COMMENT_LEN = 2000


def _round_to_hour(moment: datetime) -> datetime:
    """Strip minute/second precision so individual responses are not timed."""
    return moment.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def active_questions() -> list[FeedbackQuestion]:
    """Active questions in display order. Empty until T6 provides content."""
    return list(
        db.session.execute(
            db.select(FeedbackQuestion)
            .where(FeedbackQuestion.is_active.is_(True))
            .order_by(FeedbackQuestion.display_order, FeedbackQuestion.id)
        )
        .scalars()
        .all()
    )


def validate_answers(form, questions: list[FeedbackQuestion]):
    """Validate a submission. Returns (answers, errors).

    `answers` is a list of plain dicts — no identity is attached anywhere.
    """
    answers: list[dict] = []
    errors: list[str] = []

    for question in questions:
        raw = (form.get(f"q_{question.id}") or "").strip()

        if question.is_rating:
            if raw == "":
                errors.append(f"Answer required for question {question.id}.")
                continue
            try:
                value = int(raw)
            except ValueError:
                errors.append(f"Question {question.id} requires a whole number.")
                continue
            low = question.scale_min if question.scale_min is not None else 1
            high = question.scale_max if question.scale_max is not None else 5
            if value < low or value > high:
                errors.append(
                    f"Question {question.id} must be between {low} and {high}."
                )
                continue
            answers.append({"question_id": question.id, "rating_value": value})
        else:
            if len(raw) > MAX_COMMENT_LEN:
                errors.append(
                    f"Answer {question.id} must be {MAX_COMMENT_LEN} characters or fewer."
                )
                continue
            # PostgreSQL text cannot store NUL; psycopg2 raises ValueError, which
            # would otherwise surface as a 500 on the anonymous form (Phase 11).
            if "\x00" in raw:
                errors.append(f"Answer {question.id} contains invalid characters.")
                continue
            if raw == "":
                continue  # optional free text
            answers.append({"question_id": question.id, "comment_text": raw})

    if not answers and not errors:
        errors.append("Provide at least one answer.")

    return answers, errors


def create_submission(officer_user_id: int, answers: list[dict]) -> OfficerFeedback:
    """Persist one anonymous submission. Deliberately takes no respondent data."""
    submission = OfficerFeedback(
        officer_user_id=officer_user_id,
        status="submitted",
        submitted_at=_round_to_hour(datetime.now(timezone.utc)),
    )
    db.session.add(submission)
    db.session.flush()  # assign id without committing

    for answer in answers:
        db.session.add(
            FeedbackAnswer(
                feedback_id=submission.id,
                question_id=answer["question_id"],
                rating_value=answer.get("rating_value"),
                comment_text=answer.get("comment_text"),
            )
        )

    # Log COUNT only — never the respondent, never the session, never request
    # metadata. This line is what the anonymity log tests assert against.
    logger.info(
        "Anonymous feedback recorded (officer_id=%s, answers=%d).",
        officer_user_id,
        len(answers),
    )
    db.session.commit()
    return submission
def subject_labels_with_position() -> dict[int, str]:
    """Officer id -> the label shown in the "officer being evaluated" picker.

    Label = ``Full name (Organizational Position)`` when the officer currently
    holds one, otherwise ``Full name (System role)``. Display only — the
    Constitution/positions grant nothing (T19).
    """
    from app.services import position_service

    officers = db.session.execute(
        db.select(User)
        .join(Role, User.role_id == Role.id)
        .where(User.is_active.is_(True), Role.name.in_(("system_administrator", "techis_officer")))
        .order_by(User.full_name)
    ).scalars().all()

    labels = position_service.active_labels_by_user([u.id for u in officers])
    return {
        u.id: f"{u.full_name} ({labels.get(u.id) or u.role_display})" for u in officers
    }


def organisation_wide_rating_metadata() -> dict:
    """NON-AGGREGATED metadata safe for the Admin/Adviser results page.

    While T9 (privacy threshold) is unresolved the results view must not reveal
    raw averages, response counts, distributions, comments, timestamps or any
    per-response detail. This function therefore:

      * issues a COUNT-only query -- it never loads a row, and it never touches
        `feedback_answers.comment_text` (that column is not even selected);
      * returns only whether ANY response exists at all (a single boolean), which
        is needed to choose between "nothing yet" and "pending T9" wording.

    There is deliberately no function here that returns per-officer or
    per-question numbers: adding one would require T9 and T6 to be resolved first.
    """
    total = db.session.execute(
        db.select(db.func.count(OfficerFeedback.id))
    ).scalar() or 0
    return {"has_responses": total > 0}

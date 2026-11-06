"""Phase 6 models: anonymous officer feedback (ERD contract C1).

ANONYMITY IS ABSOLUTE — enforced here at the data-model level:
  * `OfficerFeedback` has NO column that can link a response to its submitter.
    The ONLY user link is `officer_user_id` = the officer being evaluated.
    Explicitly excluded by design: respondent_id, any submitter FK/name/ID/email,
    response tokens, hashed IPs, user agents (see docs/ERD.md C1 and T7).
  * Rows are WRITE-ONCE: there are no user-facing update/delete paths and
    `mark_submitted()` is the only mutator.
  * No `created_at`/`updated_at` pair is exposed; `submitted_at` is rounded to
    the hour by the service layer so no per-response timestamp leaks into
    analytics (C1.4).

TBC boundaries respected:
  * T6 (question content/scale) — `feedback_questions` stores STRUCTURE only.
    No question text or scale is invented by this module.
  * T7 (distribution) — no token, no per-respondent mechanism exists.
  * T8 (context) — `activity_id` is nullable and unused by the current form.
  * T10 (moderation) — `comment_text` is stored verbatim; nothing is moderated.
"""
from datetime import datetime, timezone

from app.extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


class FeedbackQuestion(db.Model):
    """Structure only — question text and scale are T6, not yet provided."""

    __tablename__ = "feedback_questions"

    TYPES = ("rating", "text")

    id = db.Column(db.Integer, primary_key=True)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(16), nullable=False, default="rating")
    scale_min = db.Column(db.Integer, nullable=True)
    scale_max = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    display_order = db.Column(db.Integer, nullable=False, default=0)

    answers = db.relationship(
        "FeedbackAnswer",
        back_populates="question",
        lazy="select",
        cascade="save-update, merge",
    )

    @property
    def is_rating(self) -> bool:
        return self.question_type == "rating"


class OfficerFeedback(db.Model):
    """One anonymous feedback submission about one officer.

    There is deliberately NO respondent column of any kind.
    """

    __tablename__ = "officer_feedback"

    STATUSES = ("submitted",)

    id = db.Column(db.Integer, primary_key=True)
    # The ONLY user link: the officer BEING EVALUATED (never the submitter).
    officer_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    # Reserved for T8 (per-event vs. general context); not populated yet.
    activity_id = db.Column(
        db.Integer, db.ForeignKey("activities.id"), nullable=True, index=True
    )
    status = db.Column(db.String(16), nullable=False, default="submitted")
    submitted_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )

    officer = db.relationship("User", foreign_keys=[officer_user_id])
    activity = db.relationship("Activity", foreign_keys=[activity_id])
    answers = db.relationship(
        "FeedbackAnswer",
        back_populates="feedback",
        lazy="select",
        cascade="save-update, merge",
    )

    def mark_submitted(self) -> None:
        """The only permitted mutation — stamps the submission time."""
        self.status = "submitted"
        self.submitted_at = _utcnow()


class FeedbackAnswer(db.Model):
    """One answer within a submission. No respondent columns here either."""

    __tablename__ = "feedback_answers"
    __table_args__ = (
        # One answer per question per submission.
        db.UniqueConstraint(
            "feedback_id", "question_id", name="uq_answer_feedback_question"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(
        db.Integer, db.ForeignKey("officer_feedback.id"), nullable=False, index=True
    )
    question_id = db.Column(
        db.Integer, db.ForeignKey("feedback_questions.id"), nullable=False, index=True
    )
    rating_value = db.Column(db.Integer, nullable=True)
    comment_text = db.Column(db.Text, nullable=True)

    feedback = db.relationship("OfficerFeedback", back_populates="answers")
    question = db.relationship("FeedbackQuestion", back_populates="answers")

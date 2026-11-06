"""Phase 3 model: ActivityAssignment — the single officer-responsibility mechanism.

Design contract (docs/ERD.md, C4): `activity_assignments` is the ONLY mechanism
for officer responsibilities. There is no separate "task" module or entity.

Rules honoured here:
  * One activity may carry MANY officer assignments; each assignment has its own
    responsibility description (no deduplication of duties across officers).
  * A duplicate duty for the same officer on the same activity is prevented by
    UNIQUE (activity_id, officer_user_id, responsibility).
  * Officer eligibility is based on the FOUR CONFIRMED ROLES only. Positions and
    `positions.permission_level` do not exist yet and must never authorize
    anything (T19 frozen). The route layer validates the role; the model exposes
    `ELIGIBLE_ROLES` so the rule lives in one place.
  * `overdue` is a DERIVED state (due_date passed while not completed). It is an
    accepted stored status for completeness with the ERD, but nothing in this
    project writes it automatically.

T12 ("activities organized/created" as a performance indicator) is unresolved:
nothing here aggregates these rows into "activities created" counts.
"""
from datetime import datetime, timezone

from app.extensions import db
from app.models.user import ROLE_ADMIN, ROLE_OFFICER


def _utcnow():
    return datetime.now(timezone.utc)


class ActivityAssignment(db.Model):
    __tablename__ = "activity_assignments"
    __table_args__ = (
        # The same officer cannot hold the same duty twice on one activity.
        db.UniqueConstraint(
            "activity_id",
            "officer_user_id",
            "responsibility",
            name="uq_assignment_activity_officer_responsibility",
        ),
    )

    STATUSES = ("assigned", "in_progress", "completed", "overdue")

    # "completed" and "overdue" are terminal-ish: an overdue duty can still be
    # completed late; a completed duty can be reopened for correction.
    STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
        "assigned": ("in_progress", "completed"),
        "in_progress": ("completed", "assigned"),
        "completed": ("in_progress",),
        "overdue": ("in_progress", "completed"),
    }

    # Only these confirmed roles may be assigned officer responsibilities.
    ELIGIBLE_ROLES = (ROLE_ADMIN, ROLE_OFFICER)

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(
        db.Integer, db.ForeignKey("activities.id"), nullable=False, index=True
    )
    officer_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    responsibility = db.Column(db.Text, nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="assigned", index=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    activity = db.relationship("Activity", back_populates="assignments")
    officer = db.relationship("User", foreign_keys=[officer_user_id])
    assigner = db.relationship("User", foreign_keys=[assigned_by])

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def is_overdue(self) -> bool:
        """Derived only — never written to `status` automatically."""
        if self.status == "completed":
            return False
        if self.due_date is None:
            return False
        return self.due_date < datetime.now(timezone.utc).date()

    def set_status(self, new_status: str) -> bool:
        """Apply a legal status transition. Returns False when rejected.

        Keeps `completed_at` consistent with the status; callers still own the
        session commit.
        """
        if new_status not in self.STATUSES:
            return False
        if new_status not in self.STATUS_TRANSITIONS.get(self.status, ()):
            return False
        self.status = new_status
        self.completed_at = _utcnow() if new_status == "completed" else None
        return True


def is_eligible_officer(user) -> bool:
    """True when the user may hold an assignment (confirmed roles only)."""
    if user is None or not user.is_active:
        return False
    return user.role_name in ActivityAssignment.ELIGIBLE_ROLES

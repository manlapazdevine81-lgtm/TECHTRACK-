"""Organization Structure model: OfficerTerm (docs/ERD.md `officer_terms`).

A term links a USER to an organizational POSITION for a bounded period. This is
the only place the two concepts meet:

    users ──< officer_terms >── positions

Separation of concerns (deliberate, and required by T19)
--------------------------------------------------------
    * `users.role_id` is the SYSTEM role and is the ONLY thing that grants or
      denies access (`app/utils/decorators.py`).
    * `officer_terms` is an ORGANIZATIONAL assignment. Nothing in the
      authorization path reads it: holding "Chief Executive Officer" confers no
      system permission whatsoever, and ending a term removes none.

History
-------
Terms are never deleted: ending a term sets `status='ended'` and stamps
`end_date`. A user therefore accumulates a readable history of the positions
they have held, and a position can be held by several users simultaneously.

"Active" is defined in ONE place (`ACTIVE_STATUSES` / `is_active`) so the
dropdown, the admin list and the tests cannot disagree.
"""
from datetime import date, datetime, timezone

from app.extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


class OfficerTerm(db.Model):
    __tablename__ = "officer_terms"

    # `active` = currently held; `ended` = historical record.
    STATUSES = ("active", "ended")
    ACTIVE_STATUSES = ("active",)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    position_id = db.Column(
        db.Integer, db.ForeignKey("positions.id"), nullable=False, index=True
    )
    start_date = db.Column(db.Date, nullable=False)
    # NULL while the term is open; stamped when the term is ended.
    end_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="active", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    user = db.relationship("User", foreign_keys=[user_id])
    position = db.relationship("Position", foreign_keys=[position_id])

    __table_args__ = (
        # The same user may hold several positions, and a position may be held
        # by several users — but not the SAME pair twice in one term window.
        db.UniqueConstraint(
            "user_id", "position_id", "start_date",
            name="uq_term_user_position_start",
        ),
    )

    @property
    def is_active(self) -> bool:
        """True while the term is currently held (status=active, not ended)."""
        return self.status in self.ACTIVE_STATUSES

    def end(self, on: date | None = None) -> None:
        """Close this term. Never deletes the row — history is preserved."""
        self.status = "ended"
        self.end_date = on or datetime.now(timezone.utc).date()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        title = self.position.title if self.position else "?"
        return f"<OfficerTerm user={self.user_id} position={title!r} {self.status}>"

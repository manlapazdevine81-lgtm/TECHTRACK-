"""Organization Structure model: Position (docs/ERD.md `positions`).

Scope
    * Each position belongs to an `organizations` row (the TechIS record) and is
      assigned to a display section through `department`.
    * `department` is a DISPLAY GROUPING, not an entity: there is no departments
      table and no department CRUD. `None` means the Executive Board; any other
      value must be one of `organizational_structure.DEPARTMENTS`.
    * `duties` holds the paraphrased responsibilities. It is TEXT and rendered
      read-only; this module exposes no create/update/delete route.
    * `sort_order` orders positions within their section for display only. It is
      not a seniority, rank, or permission signal.

T19 (position permission matrix) stays FROZEN
    The ERD lists `positions.permission_level` but freezes it: values are
    undefined and no authorization logic may read it. The column is deliberately
    NOT modelled here — access is decided solely by the four approved roles
    (see `app/utils/decorators.py`). Nothing in this feature can grant or imply
    a system permission.
"""
from datetime import datetime, timezone

from app.extensions import db

# `None` = Executive Board. Kept as a constant so callers never test truthiness.
BOARD_DEPARTMENT = None


def _utcnow():
    return datetime.now(timezone.utc)


class Position(db.Model):
    __tablename__ = "positions"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True
    )
    title = db.Column(db.String(128), nullable=False)
    # None = Executive Board; otherwise one of organizational_structure.DEPARTMENTS.
    department = db.Column(db.String(64), nullable=True, index=True)
    # Paraphrased responsibilities, one per line, rendered as bullet points.
    duties = db.Column(db.Text, nullable=True)
    # Display order inside the position's section only.
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    organization = db.relationship("Organization", foreign_keys=[organization_id])

    __table_args__ = (
        # The same title may not appear twice in one organization — this is what
        # makes the seeder idempotent ("do not duplicate position records").
        db.UniqueConstraint(
            "organization_id", "title", name="uq_position_org_title"
        ),
    )

    @property
    def section_label(self) -> str:
        """The display section this position belongs to."""
        return self.department or "Executive Board"

    @property
    def duty_list(self) -> list[str]:
        """`duties` split into non-empty, stripped lines."""
        if not self.duties:
            return []
        return [line.strip() for line in self.duties.splitlines() if line.strip()]

    def as_display_dict(self) -> dict:
        """Explicit projection for templates.

        Only these three fields exist, so `permission_level` (or any future
        column) can never leak into a page by accident.
        """
        return {
            "title": self.title,
            "duties": self.duty_list,
            "department": self.department,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<Position {self.title!r} {self.section_label}>"

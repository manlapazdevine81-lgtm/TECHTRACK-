"""Phase 4C model: Organization — the TechIS organization record.

Scope (docs/ERD.md, `organizations`):
  * TechIS-only; retained for academic-year history.
  * `adviser_id` is a nullable FK to `users.id` (the adviser's account). Role
    remains the authorization axis — nothing here reads `positions` or any
    numeric permission level (T19 frozen).
  * `logo_url` is deliberately NOT implemented: official branding assets are
    unconfirmed (T17).
  * Records are reachable through the reverse relationship `records` with
    `cascade="save-update, merge"` — organizational records are never silently
    deleted, matching the project's "never hard-delete history" convention.
"""
from datetime import datetime, timezone

from app.extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


class Organization(db.Model):
    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    # e.g. "2025-2026" — free text; no academic-year table exists in the ERD.
    academic_year = db.Column(db.String(32), nullable=True)
    adviser_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True, index=True
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    adviser = db.relationship("User", foreign_keys=[adviser_id])
    records = db.relationship(
        "OrganizationalRecord",
        back_populates="organization",
        lazy="select",
        cascade="save-update, merge",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<Organization {self.name!r} {self.academic_year or ''}>"

"""Phase 4C model: OrganizationalRecord — documents, awards, assets, meetings.

Scope (docs/ERD.md, `organizational_records`):
  * Belongs to exactly one `organizations` row (`organization_id` required).
  * `record_type` is restricted to the four approved values in `TYPES`.
  * `file_url` stores the OPAQUE storage key of an optional attachment (T14
    approved). The original filename lives in `attachment_name`, the byte size in
    `attachment_size`. Files are stored under `instance/uploads/records/` — never
    inside `static/` — and are served only through an authorized route.
  * `created_by` / `updated_by` reference `users.id` for attribution only; they
    grant no authorization (the four confirmed roles still govern access,
    T19 frozen).

Timestamps follow the project convention: `created_at` defaults to UTC now and
`updated_at` refreshes on every change (`onupdate`).
"""
from datetime import datetime, timezone

from app.extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


class OrganizationalRecord(db.Model):
    __tablename__ = "organizational_records"

    # The only approved record categories.
    TYPES = ("document", "award", "asset", "meeting")
    TYPE_LABELS = {
        "document": "Document",
        "award": "Award",
        "asset": "Asset",
        "meeting": "Meeting",
    }

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True
    )
    record_type = db.Column(db.String(32), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    # Nullable and unused until file uploads are approved (T14).
    # T14 APPROVED: this now holds the opaque UUID storage key of the attachment
    # (never a filesystem path and never the original filename).
    file_url = db.Column(db.String(512), nullable=True)
    # Original (sanitised) filename, shown to staff. NULL = no attachment.
    attachment_name = db.Column(db.String(255), nullable=True)
    # Size in bytes, shown alongside the filename.
    attachment_size = db.Column(db.Integer, nullable=True)
    # Required for every record (application validation enforces it; the Phase 4C
    # migration creates the column NOT NULL for fresh installations).
    record_date = db.Column(db.Date, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    organization = db.relationship("Organization", back_populates="records")
    creator = db.relationship("User", foreign_keys=[created_by])
    updater = db.relationship("User", foreign_keys=[updated_by])

    @property
    def type_label(self) -> str:
        return self.TYPE_LABELS.get(self.record_type, self.record_type)

    @property
    def is_valid_type(self) -> bool:
        return self.record_type in self.TYPES

    @property
    def attachment_label(self) -> str:
        """Human-readable attachment description, or '' when there is none."""
        if not self.attachment_name:
            return ""
        if self.attachment_size:
            kb = self.attachment_size / 1024
            size = f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"
            return f"{self.attachment_name} ({size})"
        return self.attachment_name

    @property
    def has_attachment(self) -> bool:
        return bool(self.file_url and self.attachment_name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<OrganizationalRecord {self.record_type}:{self.title!r}>"

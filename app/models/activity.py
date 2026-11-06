"""Phase 2 models: Activities, Registrations, Attendance.

Approved additive schema (see migration alembic/versions/...phase2...).
Design guarantees (safeguards):
  * Duplicate registrations prevented: UNIQUE (activity_id, user_id).
  * Duplicate attendance prevented: UNIQUE (activity_id, user_id).
  * An attendance row can only reference a registration that belongs to the
    SAME activity AND the SAME user — enforced in the database via a
    composite foreign key (registration_id, activity_id, user_id) ->
    activity_registrations(id, activity_id, user_id).
  * Activities are never hard-deleted once they have registrations or
    attendance; status transitions (publish/complete/cancel) preserve history.
"""
from datetime import datetime, timezone

from app.extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


class Activity(db.Model):
    __tablename__ = "activities"

    STATUSES = ("draft", "published", "completed", "cancelled")

    # Legal status transitions. `completed` and `cancelled` are terminal so an
    # activity's history is never rewritten (activities are never hard-deleted).
    STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
        "draft": ("published", "cancelled"),
        "published": ("completed", "cancelled"),
        "completed": (),
        "cancelled": (),
    }

    # Derived: statuses with no outgoing transitions. Assignments may not be
    # added or changed once an activity reaches a terminal status.
    TERMINAL_STATUSES = tuple(
        s for s, targets in STATUS_TRANSITIONS.items() if not targets
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    activity_type = db.Column(db.String(64))
    venue = db.Column(db.String(255))
    start_datetime = db.Column(db.DateTime(timezone=True), nullable=False)
    end_datetime = db.Column(db.DateTime(timezone=True), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="draft", index=True)
    responsible_officer_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True
    )
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    responsible_officer = db.relationship(
        "User", foreign_keys=[responsible_officer_id]
    )
    creator = db.relationship("User", foreign_keys=[created_by])
    registrations = db.relationship(
        "ActivityRegistration", back_populates="activity", lazy="select"
    )
    attendance = db.relationship(
        "AttendanceRecord", back_populates="activity", lazy="select"
    )
    # Phase 3 (ERD C4): the only officer-responsibility mechanism. Multiple
    # assignments per activity; `responsible_officer_id` above is retained
    # unchanged for backward compatibility with existing routes/templates.
    assignments = db.relationship(
        "ActivityAssignment",
        back_populates="activity",
        lazy="select",
        cascade="save-update, merge",
    )


class ActivityRegistration(db.Model):
    __tablename__ = "activity_registrations"
    __table_args__ = (
        # Duplicate-registration protection.
        db.UniqueConstraint(
            "activity_id", "user_id", name="uq_reg_activity_user"
        ),
        # Composite key used as the target of the attendance FK below.
        db.UniqueConstraint(
            "id", "activity_id", "user_id", name="uq_reg_composite_fk_target"
        ),
    )

    STATUSES = ("registered", "cancelled")

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(
        db.Integer, db.ForeignKey("activities.id"), nullable=False, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    registration_date = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    status = db.Column(db.String(16), nullable=False, default="registered")

    activity = db.relationship("Activity", back_populates="registrations")
    user = db.relationship("User")

    @property
    def is_active(self) -> bool:
        """True while the registration still counts (cancelled ones do not)."""
        return self.status == "registered"


class AttendanceRecord(db.Model):
    __tablename__ = "attendance_records"
    __table_args__ = (
        # Duplicate-attendance protection.
        db.UniqueConstraint(
            "activity_id", "user_id", name="uq_att_activity_user"
        ),
        # Composite FK: the referenced registration MUST belong to the same
        # activity AND the same user as this attendance row.
        db.ForeignKeyConstraint(
            ["registration_id", "activity_id", "user_id"],
            [
                "activity_registrations.id",
                "activity_registrations.activity_id",
                "activity_registrations.user_id",
            ],
            name="fk_att_same_registration_activity_user",
        ),
    )

    STATUSES = ("present", "late", "absent", "excused")

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(
        db.Integer, db.ForeignKey("activities.id"), nullable=False, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # NULL = attendance recorded without linking to a registration row;
    # when set, the composite FK guarantees activity/user consistency.
    registration_id = db.Column(db.Integer, nullable=True)
    attendance_status = db.Column(
        db.String(16), nullable=False, default="present"
    )
    time_in = db.Column(db.DateTime(timezone=True))
    time_out = db.Column(db.DateTime(timezone=True))
    remarks = db.Column(db.Text)
    # Who recorded the row, and when. Both are refreshed by every later
    # correction (they reflect the most recent write), so they are not a
    # creation audit trail — `last_edited_*` below is what marks a correction.
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    recorded_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    # Set only when an EXISTING row is corrected. NULL means the row has never
    # been edited since it was created. No correction history is kept (no
    # delete/void/history feature is approved).
    last_edited_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    last_edited_at = db.Column(db.DateTime(timezone=True), nullable=True)

    activity = db.relationship("Activity", back_populates="attendance")
    user = db.relationship("User", foreign_keys=[user_id])
    recorder = db.relationship("User", foreign_keys=[recorded_by])
    last_editor = db.relationship("User", foreign_keys=[last_edited_by])

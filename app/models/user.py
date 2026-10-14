"""Data models for the authentication demo (Phase 1).

Scope: Role + User only. The full ERD (docs/ERD.md) is implemented gradually
across later phases.
"""
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager

# The four approved roles — nothing else may exist.
ROLE_ADMIN = "system_administrator"
ROLE_OFFICER = "techis_officer"
ROLE_ADVISER = "techis_adviser"
ROLE_PARTICIPANT = "event_participant"

APPROVED_ROLES = {
    ROLE_ADMIN: "System Administrator",
    ROLE_OFFICER: "TechIS Officer",
    ROLE_ADVISER: "TechIS Adviser",
    ROLE_PARTICIPANT: "Event Participant",
}


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    display_name = db.Column(db.String(64), nullable=False)

    users = db.relationship("User", back_populates="role", lazy="select")

    @classmethod
    def ensure_defaults(cls):
        """Idempotently create the four approved roles (no others)."""
        changed = False
        for name, display in APPROVED_ROLES.items():
            if not cls.query.filter_by(name=name).first():
                db.session.add(cls(name=name, display_name=display))
                changed = True
        if changed:
            db.session.commit()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    student_id = db.Column(db.String(64), unique=True, nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    role = db.relationship("Role", back_populates="users")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def role_name(self) -> str:
        return self.role.name if self.role else ""

    @property
    def role_display(self) -> str:
        return self.role.display_name if self.role else ""


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))

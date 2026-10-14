"""Seeds the four approved demo accounts for the professor's demonstration.

DEMO CREDENTIALS (demonstration only — replace before any real deployment):
    admin@techis.demo       / AdminDemo123!        (System Administrator)
    officer@techis.demo     / OfficerDemo123!      (TechIS Officer)
    adviser@techis.demo     / AdviserDemo123!      (TechIS Adviser)
    participant@techis.demo / ParticipantDemo123!  (Event Participant)

Run from the project root:
    .\\.venv\\Scripts\\python.exe scripts\\seed_demo.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db
from app.models.user import APPROVED_ROLES, Role, User

DEMO_ACCOUNTS = [
    ("system_administrator", "Demo System Administrator", "admin@techis.demo", "AdminDemo123!", "DEMO-0001"),
    ("techis_officer", "Demo TechIS Officer", "officer@techis.demo", "OfficerDemo123!", "DEMO-0002"),
    ("techis_adviser", "Demo TechIS Adviser", "adviser@techis.demo", "AdviserDemo123!", "DEMO-0003"),
    ("event_participant", "Demo Event Participant", "participant@techis.demo", "ParticipantDemo123!", "DEMO-0004"),
]


def main() -> None:
    app = create_app()
    with app.app_context():
        db.create_all()
        Role.ensure_defaults()
        assert set(APPROVED_ROLES) == {
            r.name for r in Role.query.all()
        }, "Only the four approved roles may exist"

        for role_name, full_name, email, password, student_id in DEMO_ACCOUNTS:
            if User.query.filter_by(email=email).first():
                print(f"exists : {email}")
                continue
            role = Role.query.filter_by(name=role_name).first()
            user = User(
                full_name=full_name,
                email=email,
                student_id=student_id,
                role=role,
                is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            print(f"seeded : {email} ({role_name})")


if __name__ == "__main__":
    main()

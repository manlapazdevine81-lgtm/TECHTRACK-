"""Dashboard, sidebar module navigation, and server-side role enforcement.

Every module entry below maps to the approved module list (README.md).
Modules not yet implemented render an explicitly labeled placeholder page —
unfinished features are never presented as working.

Role access uses ONLY the four approved roles (T19 frozen — no permission
levels, no numeric ranks, no invented TechIS positions).
"""
from flask import Blueprint, abort, render_template
from flask_login import current_user, login_required

from app.models.user import (
    ROLE_ADMIN,
    ROLE_ADVISER,
    ROLE_OFFICER,
    ROLE_PARTICIPANT,
)
from app.utils.decorators import role_required

bp = Blueprint("main", __name__)

_ALL = (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER, ROLE_PARTICIPANT)
_STAFF = (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER)

# key -> (label, allowed roles, planned phase, short description)
MODULES: dict[str, tuple[str, tuple, str, str]] = {
    "organization": (
        "Organization Structure",
        _STAFF,
        "Phase 2",
        "TechIS positions, officer terms, and academic year history.",
    ),
    "activities": (
        "Activities",
        _STAFF,
        "Phase 3",
        "Create and manage TechIS activities and events.",
    ),
    "participants": (
        "Event Participants",
        _STAFF,
        "Phase 4",
        "Enrollment records for event participants (identity model pending T18).",
    ),
    "attendance": (
        "Attendance / Participation",
        (ROLE_ADMIN, ROLE_OFFICER),
        "Phase 4",
        "Time in/out and attendance status per activity.",
    ),
    "records": (
        "Organizational Records",
        _STAFF,
        "Phase 4",
        "Documents, achievements, assets, and meeting records.",
    ),
    "feedback": (
        "Officer Feedback (view only)",
        (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER),
        "Phase 6-7",
        "Anonymous aggregated feedback views. Submission form is NOT implemented "
        "pending T7 (distribution method unconfirmed).",
    ),
    "analytics": (
        "Analytics",
        (ROLE_ADMIN, ROLE_ADVISER),
        "Phase 5-8",
        "Objective officer performance metrics and Pandas analytics. No scores "
        "or formulas are implemented yet.",
    ),
    "reports": (
        "Reports",
        (ROLE_ADMIN, ROLE_ADVISER),
        "Phase 9",
        "Exportable reports (formats pending T13).",
    ),
    "my-activities": (
        "My Activities",
        (ROLE_PARTICIPANT,),
        "Phase 4",
        "Activities you have joined (participant view).",
    ),
}


def modules_for(role_name: str) -> list[dict]:
    """Modules the given role may open — drives the sidebar AND the dashboard."""
    return [
        {"key": key, "label": label, "phase": phase, "description": desc}
        for key, (label, roles, phase, desc) in MODULES.items()
        if role_name in roles
    ]


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        modules=modules_for(current_user.role_name),
    )


@bp.route("/admin/users")
@login_required
@role_required(ROLE_ADMIN)
def admin_users():
    """Functional demo page for the User/Role Management module (read-only list)."""
    from app.extensions import db
    from app.models.user import User

    users = db.session.execute(db.select(User).order_by(User.id)).scalars().all()
    return render_template("admin/users.html", users=users)


@bp.route("/modules/<key>")
@login_required
def module_placeholder(key: str):
    entry = MODULES.get(key)
    if entry is None:
        abort(404)
    label, roles, phase, desc = entry
    # SERVER-SIDE enforcement: 403 even if someone types the URL directly.
    if current_user.role_name not in roles:
        abort(403)
    return render_template(
        "placeholder.html",
        module={"key": key, "label": label, "phase": phase, "description": desc},
    )

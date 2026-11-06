"""Dashboard, sidebar module navigation, and server-side role enforcement.

Every module entry below maps to the approved module list (README.md).
Modules not yet implemented render an explicitly labeled placeholder page —
unfinished features are never presented as working.

Role access uses ONLY the four approved roles (T19 frozen — no permission
levels, no numeric ranks, no invented TechIS positions).
"""
from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.models.user import (
    APPROVED_ROLES,
    ROLE_ADMIN,
    ROLE_ADVISER,
    ROLE_OFFICER,
    ROLE_PARTICIPANT,
    Role,
    User,
)
from app.utils.decorators import role_required

bp = Blueprint("main", __name__)

_ALL = (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER, ROLE_PARTICIPANT)
_STAFF = (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER)

# key -> (label, allowed roles, planned phase, short description, endpoint)
# `endpoint` is the working view for implemented modules; None means the module
# is still a placeholder (it opens a clearly labeled status page).
MODULES: dict[str, tuple[str, tuple, str, str, str | None]] = {
    "organization": (
        "Organization Structure",
        _STAFF,
        "Phase 2",
        "The Executive Board and departments, with the official duties of each "
        "TechIS position (read-only).",
        "organization.structure",
    ),
    "activities": (
        "Activities",
        _STAFF,
        "Phase 3",
        "Create and manage TechIS activities and events.",
        "activities.activity_list",
    ),
    "participants": (
        "Event Participants",
        _STAFF,
        "Phase 4",
        "Read-only roster of accounts with registration and attendance records "
        "(identity model pending T18).",
        "participants.participant_list",
    ),
    "attendance": (
        "Attendance / Participation",
        (ROLE_ADMIN, ROLE_OFFICER),
        "Phase 4",
        "Time in/out and attendance status per activity.",
        "activities.attendance_list",
    ),
    "records": (
        "Organizational Records",
        _STAFF,
        "Phase 4C",
        "Documents, achievements, assets, and meeting records.",
        "records.record_list",
    ),
    "feedback": (
        "Officer Feedback",
        (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER),
        "Phase 6-7",
        "Anonymous feedback: the public form takes responses without identifying "
        "any respondent. Administrators and Advisers see organisation-wide, "
        "ratings-only results — figures stay hidden until the T9 privacy "
        "threshold is approved. Comments are never shown.",
        # Readers land on the results view; everyone else on the public form.
        # Both are enforced server-side in app/routes/feedback.py.
        "feedback.feedback_list",
    ),
    "analytics": (
        "Analytics",
        (ROLE_ADMIN, ROLE_ADVISER),
        "Phase 5",
        "Objective officer performance metrics: assigned vs. completed "
        "responsibilities, participation, attendance rates, and timelines. "
        "Counts and percentages only — no scores or rankings.",
        "analytics.analytics_dashboard",
    ),
    "reports": (
        "Reports",
        _STAFF,
        "Phase 9",
        "Downloadable CSV reports (attendance, participation, activities, "
        "registrations). PDF pending T13.",
        "reports.report_list",
    ),
    "my-activities": (
        "My Activities",
        (ROLE_PARTICIPANT,),
        "Phase 4",
        "Activities you have joined (participant view).",
        "activities.my_activities",
    ),
}


# Modules whose landing page depends on the ROLE, not just the module.
# Feedback is the only one: Admin/Adviser read results, everyone else submits.
# Both destinations are enforced server-side in app/routes/feedback.py.
_FEEDBACK_RESULT_ROLES = (ROLE_ADMIN, ROLE_ADVISER)


def _module_endpoint(key: str, role_name: str, endpoint: str | None) -> str | None:
    """The endpoint a given role should be sent to for this module."""
    if key == "feedback":
        return (
            "feedback.feedback_list"
            if role_name in _FEEDBACK_RESULT_ROLES
            else "feedback.submit"
        )
    return endpoint


def modules_for(role_name: str) -> list[dict]:
    """Modules the given role may open — drives the sidebar AND the dashboard."""
    modules = []
    for key, (label, roles, phase, desc, endpoint) in MODULES.items():
        if role_name not in roles:
            continue
        endpoint = _module_endpoint(key, role_name, endpoint)
        modules.append(
            {
                "key": key,
                "label": label,
                "phase": phase,
                "description": desc,
                "endpoint": endpoint,
                "implemented": endpoint is not None,
                "url": (
                    url_for(endpoint)
                    if endpoint
                    else url_for("main.module_placeholder", key=key)
                ),
            }
        )
    return modules


# Phase 10 landing-page imagery. These are the ACTUAL files in app/static/
# (verified on disk — no filenames are invented). Alt text describes what each
# photo shows; no officer portraits are used and there is no background video.
_LANDING_ASSETS = {
    "logo": "techis-logo.jpg",
    "hero_main": {
        "file": "techis-workshop.jpg",
        "alt": "TechIS members attending a hands-on technology workshop",
    },
    "hero_secondary": {
        "file": "techis-project.jpg",
        "alt": "TechIS students presenting a technology project",
    },
    "hero_event": {
        "file": "techis-event.jpg",
        "alt": "TechIS members at an organization event",
    },
    "campus": {
        "file": "campus.jpg",
        "alt": "Batangas State University – The National Engineering University, "
        "Lipa Campus building",
    },
}


@bp.route("/")
def index():
    """Public landing page (Phase 10).

    Renders standalone (see templates/index.html) so the marketing layout never
    inherits the signed-in app shell. Purely presentational: no data is read and
    every call-to-action points at the existing auth/dashboard endpoints.
    """
    from datetime import datetime, timezone

    return render_template(
        "index.html",
        techis_assets=_LANDING_ASSETS,
        current_year=datetime.now(timezone.utc).year,
    )


@bp.route("/dashboard")
@login_required
def dashboard():
    """Role-aware dashboard with REAL metrics only (no fabricated numbers)."""
    from app.models.user import User

    stats = None
    recent = []
    if current_user.role_name == ROLE_ADMIN:
        # Feedback CTA visibility is an OFFLINE distribution decision answered per
        # session (T7 stays unresolved). No token, no per-respondent link, and the
        # choice is never stored in the database or logged.
        session["feedback_cta"] = request.args.get("feedback") == "1"
        total = db.session.execute(db.select(db.func.count(User.id))).scalar() or 0
        active = (
            db.session.execute(
                db.select(db.func.count(User.id)).where(User.is_active.is_(True))
            ).scalar()
            or 0
        )
        by_role = {
            r: (
                db.session.execute(
                    db.select(db.func.count(User.id))
                    .join(Role)
                    .where(Role.name == r)
                ).scalar()
                or 0
            )
            for r in (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER, ROLE_PARTICIPANT)
        }
        stats = {
            "total_members": total,
            "active_members": active,
            "inactive_members": total - active,
            "active_pct": round(active * 100 / total, 1) if total else 0.0,
            "by_role": by_role,
        }
        recent = db.session.execute(
            db.select(User).order_by(User.created_at.desc()).limit(5)
        ).scalars().all()
    elif current_user.role_name in (ROLE_OFFICER, ROLE_ADVISER):
        total = db.session.execute(db.select(db.func.count(User.id))).scalar() or 0
        stats = {"total_members": total}

    return render_template(
        "dashboard.html",
        modules=modules_for(current_user.role_name),
        stats=stats,
        recent=recent,
    )


@bp.route("/admin/users")
@login_required
@role_required(ROLE_ADMIN)
def admin_users():
    """Member management list (admin only)."""
    from app.services import position_service

    users = db.session.execute(db.select(User).order_by(User.id)).scalars().all()
    position_labels = position_service.active_labels_by_user([u.id for u in users])
    return render_template(
        "admin/users.html", users=users, position_labels=position_labels
    )


# ---------------------------------------------------------------------------
# Member Management (admin CRUD over the existing users/roles tables).
# No new models: members with accounts ARE users (docs/ERD.md).
# Role definitions are never modified here — only role ASSIGNMENTS.
# ---------------------------------------------------------------------------

import re

from app.services import email_service
from app.utils import passwords

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Accounts that are PROVISIONED with a server-generated temporary password and
# must change it at first login. Participants are deliberately excluded: they
# self-register with their own password (T5 provisional rule).
_PROVISIONED_ROLES = (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER)


def _member_errors(form, user: "User | None" = None) -> list:
    """Server-side validation shared by create and edit forms."""
    errors: list = []
    full_name = (form.get("full_name") or "").strip()
    email = (form.get("email") or "").strip().lower()
    student_id = (form.get("student_id") or "").strip()
    role_name = form.get("role_name") or ""
    password = form.get("password") or ""

    if not full_name:
        errors.append("Full name is required.")
    if not email:
        errors.append("Email is required.")
    elif not _EMAIL_RE.match(email):
        errors.append("Enter a valid email address.")
    if role_name not in APPROVED_ROLES:
        errors.append("Invalid role selection.")
    # New accounts no longer take a password: the server generates a temporary
    # one and emails it. On EDIT an administrator may still set a password
    # directly, and when they do it must satisfy the shared policy.
    if user is not None and password:
        errors.extend(passwords.password_policy_errors(password))
    if user and user.id == current_user.id and not form.get("is_active"):
        errors.append("You cannot deactivate your own account.")

    if not errors:
        exclude_id = user.id if user else -1
        if User.query.filter(User.email == email, User.id != exclude_id).first():
            errors.append("An account with this email already exists.")
        elif student_id and User.query.filter(
            User.student_id == student_id, User.id != exclude_id
        ).first():
            errors.append("An account with this student ID already exists.")
    return errors


@bp.route("/admin/users/create", methods=["GET", "POST"])
@login_required
@role_required(ROLE_ADMIN)
def admin_user_create():
    roles = Role.query.order_by(Role.id).all()
    if request.method == "POST":
        errors = _member_errors(request.form, user=None)
        if not errors:
            role = Role.query.filter_by(name=request.form.get("role_name")).first()

            # Temporary-password provisioning applies ONLY to staff accounts
            # (System Administrator, TechIS Officer, Adviser). A Participant
            # account created here is not provisioned: no temporary password and
            # no forced first-login change, because participants normally
            # self-register with a password they choose themselves.
            provisioned = role.name in _PROVISIONED_ROLES

            user = User(
                full_name=(request.form.get("full_name") or "").strip(),
                email=(request.form.get("email") or "").strip().lower(),
                student_id=(request.form.get("student_id") or "").strip() or None,
                role=role,
                is_active=bool(request.form.get("is_active")),
                must_change_password=provisioned,
            )

            if not provisioned:
                # Participant account: no temporary credential, no email, no gate.
                # A password must still be supplied here, because
                # `generate_password_hash("")` IS verifiable — creating the row
                # with an empty password would produce an account anyone could
                # sign into without knowing anything.
                initial = request.form.get("password") or ""
                errors.extend(passwords.password_policy_errors(initial))
                if not errors:
                    user.set_password(initial)
                    db.session.add(user)
                    db.session.commit()
                    flash(
                        f"Participant account created for {user.full_name}. They can "
                        "sign in with the password you set and are not required to "
                        "change it.",
                        "success",
                    )
                    return redirect(url_for("main.admin_users"))
            else:
                # Staff account: server-generated temporary password. It is NEVER
                # flashed, logged, or rendered — it exists only long enough to be
                # hashed, committed, and emailed.
                temp_password = passwords.generate_temp_password()
                user.set_password(temp_password)

                db.session.add(user)
                db.session.commit()          # commit BEFORE any email is attempted

                # Email only after a successful commit (approved ordering).
                delivered = email_service.send_credentials_email(
                    user.email, user.full_name, user.email, temp_password
                )
                del temp_password            # drop the plaintext as early as possible

                if delivered:
                    flash(
                        f"Account created for {user.full_name}. Temporary credentials "
                        "were emailed to them; they must change the password at first login.",
                        "success",
                    )
                else:
                    flash(
                        f"Account created for {user.full_name}, but the credentials email "
                        "could NOT be sent. Use \u201cResend credentials\u201d on the member "
                        "list to generate a new temporary password and try again.",
                        "error",
                    )
                return redirect(url_for("main.admin_users"))
        for msg in errors:
            flash(msg, "error")
        form_values = request.form.to_dict()
        if request.form.get("is_active"):
            form_values["is_active"] = "y"
    else:
        form_values = {"is_active": "y"}
    return render_template(
        "admin/user_form.html",
        form_title="Add member",
        user=None,
        roles=roles,
        approved_roles=APPROVED_ROLES,
        form_values=form_values,
    )


@bp.route("/admin/users/<int:user_id>/resend-credentials", methods=["POST"])
@login_required
@role_required(ROLE_ADMIN)
def admin_user_resend_credentials(user_id: int):
    """Regenerate a temporary password and retry credential delivery.

    Used when account creation succeeded but the credentials email failed. The
    account is NEVER duplicated: this updates the existing row, replaces the
    stored hash, and keeps `must_change_password = True`.

    The generated password is never flashed, logged, or displayed — if delivery
    fails again the administrator is told so and may retry.
    """
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    temp_password = passwords.generate_temp_password()
    user.set_password(temp_password)
    # Keep the first-login gate in force: the account still holds a temporary
    # password, so the user must still change it.
    user.must_change_password = True
    db.session.commit()

    delivered = email_service.send_credentials_resent_email(
        user.email, user.full_name, user.email, temp_password
    )
    del temp_password

    if delivered:
        flash(
            f"A new temporary password was emailed to {user.full_name}. They must "
            "change it at their next login.",
            "success",
        )
    else:
        # Be explicit: never imply delivery that did not happen.
        flash(
            f"A new temporary password was set for {user.full_name}, but the email "
            "could NOT be sent. The account still requires a password change at "
            "login; retry once SMTP is available.",
            "error",
        )
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@role_required(ROLE_ADMIN)
def admin_user_edit(user_id: int):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    roles = Role.query.order_by(Role.id).all()

    if request.method == "POST":
        errors = _member_errors(request.form, user=user)
        if not errors:
            user.full_name = (request.form.get("full_name") or "").strip()
            user.email = (request.form.get("email") or "").strip().lower()
            user.student_id = (request.form.get("student_id") or "").strip() or None
            user.role = Role.query.filter_by(name=request.form.get("role_name")).first()
            user.is_active = bool(request.form.get("is_active"))
            password = request.form.get("password") or ""
            if password:
                user.set_password(password)
            db.session.commit()
            flash(f"Account updated for {user.full_name}.", "success")
            return redirect(url_for("main.admin_users"))
        for msg in errors:
            flash(msg, "error")
        form_values = request.form.to_dict()
        if request.form.get("is_active"):
            form_values["is_active"] = "y"
    else:
        form_values = {
            "full_name": user.full_name,
            "email": user.email,
            "student_id": user.student_id or "",
            "role_name": user.role_name,
            "is_active": "y" if user.is_active else "",
        }
    return render_template(
        "admin/user_form.html",
        form_title=f"Edit member — {user.full_name}",
        user=user,
        roles=roles,
        approved_roles=APPROVED_ROLES,
        form_values=form_values,
    )


@bp.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@role_required(ROLE_ADMIN)
def admin_user_toggle(user_id: int):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("main.admin_users"))
    user.is_active = not user.is_active
    db.session.commit()
    state = "activated" if user.is_active else "deactivated"
    flash(f"{user.full_name} {state}.", "success")
    return redirect(url_for("main.admin_users"))


@bp.route("/modules/<key>")
@login_required
def module_placeholder(key: str):
    """Legacy module URL.

    Modules that are implemented redirect to their working page so an old
    bookmark never lands on a page claiming the feature is missing. Modules
    that are still placeholders render a clearly labeled status page.
    """
    entry = MODULES.get(key)
    if entry is None:
        abort(404)
    label, roles, phase, desc, endpoint = entry
    # SERVER-SIDE enforcement: 403 even if someone types the URL directly.
    if current_user.role_name not in roles:
        abort(403)
    # The landing page may depend on the role (feedback: results for
    # Admin/Adviser, public submission form for everyone else).
    endpoint = _module_endpoint(key, current_user.role_name, endpoint)
    if endpoint is not None:
        return redirect(url_for(endpoint))
    return render_template(
        "placeholder.html",
        module={"key": key, "label": label, "phase": phase, "description": desc},
    )

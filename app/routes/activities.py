"""Activities module — create, list, view, edit and manage TechIS activities.

Reuses the approved Phase 2 schema (`activities` table, migration
625c94493a3d). NO schema changes are introduced here.

Authorization (server-side, T19 frozen — only the four approved roles):
  * System Administrator  — full control over every activity.
  * TechIS Officer        — full control over activities they created.
  * TechIS Adviser        — read-only (T15 adviser approval rights unconfirmed).
  * Event Participant     — may only register for / view published activities.

Activities are never hard-deleted; status transitions preserve the history.
"""
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import DataError, IntegrityError

from app.extensions import db
from app.models.activity import Activity, ActivityRegistration, AttendanceRecord
from app.models.assignment import ActivityAssignment, is_eligible_officer
from app.models.user import (
    ROLE_ADMIN,
    ROLE_ADVISER,
    ROLE_OFFICER,
    ROLE_PARTICIPANT,
    Role,
    User,
)
from app.utils.decorators import role_required

bp = Blueprint("activities", __name__)

# Staff that may open the activities workspace (adviser included — read-only).
_STAFF = (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER)
# Staff that may CREATE / EDIT / change status.
_MANAGERS = (ROLE_ADMIN, ROLE_OFFICER)

# Datetime inputs are submitted as "YYYY-MM-DDTHH:MM" (datetime-local).
_DATETIME_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S")

# Errors a user can provoke with input the form validation does not cover (a
# value longer than its column, a bad timestamp, a broken constraint). They must
# become a flash message on a normal page — never an uncaught 500.
#
# ValueError is included on purpose: psycopg2/SQLAlchemy raise a plain
# `ValueError: A string literal cannot contain NUL (0x00) characters` for a text
# value with a NUL byte, which is NOT a DBAPIError and used to escape the
# IntegrityError handler (Phase 11 Bug 1).
_DB_INPUT_ERRORS = (IntegrityError, DataError, ValueError)


def _has_nul(value: str) -> bool:
    """PostgreSQL text cannot store NUL — reject it before it reaches the DB."""
    return "\x00" in value


def _parse_datetime(raw: str) -> datetime | None:
    """Parse a datetime-local input into an aware UTC datetime (or None)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in _DATETIME_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        # Values are entered in local wall-clock time; store as UTC.
        return parsed.replace(tzinfo=timezone.utc)
    return None


def _escape_like(term: str) -> str:
    """Escape LIKE metacharacters so user input is matched literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fmt(dt: datetime | None) -> str:
    """Render a stored datetime for a datetime-local input value."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")


def _may_manage(activity: Activity) -> bool:
    """Admins manage everything; officers manage only what they created."""
    if current_user.role_name == ROLE_ADMIN:
        return True
    if current_user.role_name == ROLE_OFFICER:
        return activity.created_by == current_user.id
    return False


def _staff_users() -> list[User]:
    """Administrators and officers — the only assignable responsible officers."""
    rows = db.session.execute(
        db.select(User)
        .join(Role, User.role_id == Role.id)
        .where(Role.name.in_((ROLE_ADMIN, ROLE_OFFICER)))
        .order_by(Role.name, User.full_name)
    ).scalars().all()
    return list(rows)


def staff_officer_options() -> list[dict]:
    """Staff users with the label shown by the Responsible Officer dropdown.

    The label is `Full name (Organizational Position)`, falling back to
    `Full name (System role)` when the member holds no active position. The
    eligible set is EXACTLY `_staff_users()` — the eligibility filter is not
    touched by this, and no authorization is derived from the label.

    One extra query for every candidate (not one per candidate), so the form
    stays cheap as the roster grows.
    """
    from app.services import position_service

    officers = _staff_users()
    labels = position_service.active_labels_by_user([u.id for u in officers])
    return [
        {
            "id": u.id,
            "full_name": u.full_name,
            "role_display": u.role_display,
            "position_title": labels.get(u.id),
            "label": f"{u.full_name} ({labels.get(u.id) or u.role_display})",
        }
        for u in officers
    ]


def _active_users() -> list[User]:
    """Every active account, ordered by name (used by the pickers)."""
    rows = db.session.execute(
        db.select(User).where(User.is_active.is_(True)).order_by(User.full_name)
    ).scalars().all()
    return list(rows)


def _registration_candidates(activity: Activity) -> list[User]:
    """Active accounts that are not yet registered for this activity."""
    taken = {r.user_id for r in activity.registrations if r.is_active}
    return [u for u in _active_users() if u.id not in taken]


def _attendance_candidates(activity: Activity) -> list[User]:
    """Accounts attendance may be recorded for.

    Everyone who holds a registration row (active or cancelled) comes first —
    those are the people who were expected at the activity. Accounts without a
    registration remain selectable because the schema allows an attendance row
    with no linked registration.
    """
    users = _active_users()
    by_id = {u.id: u for u in users}
    registered = [by_id[r.user_id] for r in activity.registrations if r.user_id in by_id]
    registered_ids = {u.id for u in registered}
    others = [u for u in users if u.id not in registered_ids]
    return registered + others


def _validate_activity_form(form) -> tuple[dict, list[str]]:
    """Validate the activity form server-side. Returns (values, errors)."""
    values = {
        "title": (form.get("title") or "").strip(),
        "description": (form.get("description") or "").strip(),
        "activity_type": (form.get("activity_type") or "").strip(),
        "venue": (form.get("venue") or "").strip(),
        "start_datetime": (form.get("start_datetime") or "").strip(),
        "end_datetime": (form.get("end_datetime") or "").strip(),
        "responsible_officer_id": (form.get("responsible_officer_id") or "").strip(),
    }
    errors: list[str] = []

    if not values["title"]:
        errors.append("Title is required.")
    elif len(values["title"]) > 255:
        errors.append("Title must be 255 characters or fewer.")
    elif _has_nul(values["title"]):
        errors.append("Title contains invalid characters.")

    if any(_has_nul(values[k]) for k in ("description", "activity_type", "venue")):
        errors.append("One of the text fields contains invalid characters.")

    if len(values["activity_type"]) > 64:
        errors.append("Activity type must be 64 characters or fewer.")
    if len(values["venue"]) > 255:
        errors.append("Venue must be 255 characters or fewer.")

    start = _parse_datetime(values["start_datetime"])
    end = _parse_datetime(values["end_datetime"])
    if not values["start_datetime"]:
        errors.append("Start date and time is required.")
    elif start is None:
        errors.append("Start date and time is not a valid date/time.")
    if not values["end_datetime"]:
        errors.append("End date and time is required.")
    elif end is None:
        errors.append("End date and time is not a valid date/time.")
    if start and end and end <= start:
        errors.append("End date and time must be after the start date and time.")

    if values["responsible_officer_id"]:
        if not values["responsible_officer_id"].isdigit():
            errors.append("Responsible officer is not a valid selection.")
        else:
            officer = db.session.get(User, int(values["responsible_officer_id"]))
            if officer is None:
                errors.append("Responsible officer could not be found.")
            elif officer.role_name not in (ROLE_ADMIN, ROLE_OFFICER):
                errors.append(
                    "Responsible officer must be a System Administrator or a TechIS Officer."
                )
    else:
        values["responsible_officer_id"] = ""

    values["_start"] = start
    values["_end"] = end
    return values, errors


@bp.route("/activities")
@login_required
@role_required(*_STAFF)
def activity_list():
    """List activities with a status filter and a search term."""
    status = (request.args.get("status") or "").strip()
    if status and status not in Activity.STATUSES:
        status = ""
    search = (request.args.get("q") or "").strip()

    stmt = db.select(Activity).order_by(Activity.start_datetime.desc())
    if status:
        stmt = stmt.where(Activity.status == status)
    if search:
        # `%` and `_` are LIKE wildcards: a search for "%" used to match every
        # row. They are escaped so the term is matched literally (binding already
        # prevents SQL injection; this fixes the wildcard semantics).
        like = "%" + _escape_like(search) + "%"
        stmt = stmt.where(
            db.or_(
                Activity.title.ilike(like, escape="\\"),
                Activity.venue.ilike(like, escape="\\"),
                Activity.activity_type.ilike(like, escape="\\"),
            )
        )
    activities = db.session.execute(stmt).scalars().all()

    counts = {s: 0 for s in Activity.STATUSES}
    for row in db.session.execute(
        db.select(Activity.status, db.func.count(Activity.id)).group_by(Activity.status)
    ).all():
        counts[row[0]] = row[1]

    return render_template(
        "activities/list.html",
        activities=activities,
        status=status,
        search=search,
        counts=counts,
        can_manage=current_user.role_name in _MANAGERS,
        manageable_ids={a.id for a in activities if _may_manage(a)},
    )


@bp.route("/activities/new", methods=["GET", "POST"])
@login_required
@role_required(*_MANAGERS)
def activity_create():
    """Create a new activity (starts as a draft)."""
    officers = staff_officer_options()

    if request.method == "POST":
        values, errors = _validate_activity_form(request.form)
        if not errors:
            activity = Activity(
                title=values["title"],
                description=values["description"] or None,
                activity_type=values["activity_type"] or None,
                venue=values["venue"] or None,
                start_datetime=values["_start"],
                end_datetime=values["_end"],
                status="draft",
                responsible_officer_id=int(values["responsible_officer_id"])
                if values["responsible_officer_id"]
                else None,
                created_by=current_user.id,
            )
            db.session.add(activity)
            try:
                db.session.commit()
            except _DB_INPUT_ERRORS:
                db.session.rollback()
                flash("The activity could not be saved. Please try again.", "error")
                return redirect(url_for("activities.activity_create"))
            flash(f"Activity “{activity.title}” created as a draft.", "success")
            return redirect(url_for("activities.activity_detail", activity_id=activity.id))
        for msg in errors:
            flash(msg, "error")
        form_values = request.form.to_dict()
    else:
        form_values = {}

    return render_template(
        "activities/form.html",
        form_title="Create activity",
        activity=None,
        officers=officers,
        form_values=form_values,
    )


@bp.route("/activities/<int:activity_id>")
@login_required
def activity_detail(activity_id: int):
    """Activity detail with its registrations and attendance records.

    Staff (any role) may open any activity. A participant may only open an
    activity they are registered for, or one that is published (so they can
    register for it).
    """
    activity = db.get_or_404(Activity, activity_id)

    if current_user.role_name not in _STAFF:
        # Participant: only published activities or their own registrations.
        registration = _registration_for(activity, current_user.id)
        if activity.status != "published" and registration is None:
            abort(403)

    registrations = sorted(
        activity.registrations, key=lambda r: (r.user.full_name or "").lower()
    )
    attendance = sorted(
        activity.attendance, key=lambda r: (r.user.full_name or "").lower()
    )
    registered_user_ids = {r.user_id for r in registrations if r.is_active}
    can_manage = _may_manage(activity)

    assignments = sorted(
        activity.assignments,
        key=lambda a: (a.officer.full_name or "").lower() if a.officer else "",
    )

    # The responsible officer's CURRENT organizational position, falling back to
    # their system role. Display only: no authorization reads this.
    responsible_officer_label = None
    if activity.responsible_officer is not None:
        from app.services import position_service

        title = position_service.active_position_label(activity.responsible_officer.id)
        responsible_officer_label = title or activity.responsible_officer.role_display

    return render_template(
        "activities/detail.html",
        activity=activity,
        responsible_officer_label=responsible_officer_label,
        registrations=registrations,
        attendance=attendance,
        registered_user_ids=registered_user_ids,
        can_manage=can_manage,
        attendance_statuses=AttendanceRecord.STATUSES,
        activity_statuses_map=Activity.STATUS_TRANSITIONS,
        assignments=assignments,
        assignment_statuses=ActivityAssignment.STATUSES,
        assignment_candidates=_staff_users(),
        can_edit_assignments=can_manage
        and activity.status not in Activity.TERMINAL_STATUSES,
        registration_candidates=(
            _registration_candidates(activity) if can_manage else []
        ),
        attendance_candidates=(
            _attendance_candidates(activity) if can_manage else []
        ),
        my_registration=(
            _registration_for(activity, current_user.id)
            if current_user.role_name not in _STAFF
            else None
        ),
    )


@bp.route("/activities/<int:activity_id>/edit", methods=["GET", "POST"])
@login_required
@role_required(*_MANAGERS)
def activity_edit(activity_id: int):
    """Edit an activity's details. Status is changed via the status route."""
    activity = db.get_or_404(Activity, activity_id)
    if not _may_manage(activity):
        abort(403)

    officers = staff_officer_options()

    if request.method == "POST":
        values, errors = _validate_activity_form(request.form)
        if not errors:
            activity.title = values["title"]
            activity.description = values["description"] or None
            activity.activity_type = values["activity_type"] or None
            activity.venue = values["venue"] or None
            activity.start_datetime = values["_start"]
            activity.end_datetime = values["_end"]
            activity.responsible_officer_id = (
                int(values["responsible_officer_id"])
                if values["responsible_officer_id"]
                else None
            )
            try:
                db.session.commit()
            except _DB_INPUT_ERRORS:
                db.session.rollback()
                flash("The activity could not be saved. Please try again.", "error")
                return redirect(url_for("activities.activity_edit", activity_id=activity.id))
            flash(f"Activity “{activity.title}” updated.", "success")
            return redirect(url_for("activities.activity_detail", activity_id=activity.id))
        for msg in errors:
            flash(msg, "error")
        form_values = request.form.to_dict()
    else:
        form_values = {
            "title": activity.title or "",
            "description": activity.description or "",
            "activity_type": activity.activity_type or "",
            "venue": activity.venue or "",
            "start_datetime": _fmt(activity.start_datetime),
            "end_datetime": _fmt(activity.end_datetime),
            "responsible_officer_id": str(activity.responsible_officer_id or ""),
        }

    return render_template(
        "activities/form.html",
        form_title="Edit activity",
        activity=activity,
        officers=officers,
        form_values=form_values,
    )


@bp.route("/activities/<int:activity_id>/status", methods=["POST"])
@login_required
@role_required(*_MANAGERS)
def activity_status(activity_id: int):
    """Move an activity through its legal status transitions."""
    activity = db.get_or_404(Activity, activity_id)
    if not _may_manage(activity):
        abort(403)

    new_status = (request.form.get("status") or "").strip()
    allowed = Activity.STATUS_TRANSITIONS.get(activity.status, ())
    if new_status not in allowed:
        flash(
            f"Cannot change a {activity.status} activity to "
            f"“{new_status or 'an empty status'}”.",
            "error",
        )
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    if new_status == "cancelled":
        _cancel_registrations(activity)

    activity.status = new_status
    db.session.commit()
    flash(f"Activity “{activity.title}” is now {new_status}.", "success")
    return redirect(url_for("activities.activity_detail", activity_id=activity.id))


def _cancel_registrations(activity: Activity) -> None:
    """Cancel all live registrations when an activity is cancelled."""
    for registration in activity.registrations:
        if registration.is_active:
            registration.status = "cancelled"


# ---------------------------------------------------------------------------
# Officer responsibility assignments (ERD C4)
# ---------------------------------------------------------------------------


def _assignment_for(activity: Activity, assignment_id: int) -> ActivityAssignment:
    """Fetch an assignment that provably belongs to this activity (or 404)."""
    assignment = db.session.get(ActivityAssignment, assignment_id)
    if assignment is None or assignment.activity_id != activity.id:
        abort(404)
    return assignment


def _parse_due_date(raw: str):
    """Parse an optional <input type="date"> value (YYYY-MM-DD) or None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return "invalid"


def _validate_assignment_form(
    activity: Activity, form, assignment: ActivityAssignment | None = None
) -> tuple[dict, list[str]]:
    """Validate an assignment form server-side. Returns (values, errors)."""
    values = {
        "officer_user_id": (form.get("officer_user_id") or "").strip(),
        "responsibility": (form.get("responsibility") or "").strip(),
        "due_date": (form.get("due_date") or "").strip(),
        "status": (form.get("status") or "").strip(),
    }
    errors: list[str] = []

    if not values["responsibility"]:
        errors.append("Responsibility is required.")
    elif len(values["responsibility"]) > 2000:
        errors.append("Responsibility must be 2000 characters or fewer.")
    elif _has_nul(values["responsibility"]):
        errors.append("Responsibility contains invalid characters.")

    officer = None
    if not values["officer_user_id"]:
        errors.append("Select an officer.")
    elif not values["officer_user_id"].isdigit():
        errors.append("Officer is not a valid selection.")
    else:
        officer = db.session.get(User, int(values["officer_user_id"]))
        if officer is None:
            errors.append("That officer could not be found.")
        elif not is_eligible_officer(officer):
            errors.append(
                "Only active System Administrators and TechIS Officers "
                "can be assigned responsibilities."
            )

    values["_due_date"] = _parse_due_date(values["due_date"])
    if values["_due_date"] == "invalid":
        errors.append("Due date is not a valid date.")
        values["_due_date"] = None
    elif values["_due_date"] is not None and values["_due_date"] < datetime.now(
        timezone.utc
    ).date() and (assignment is None or assignment.status != "completed"):
        # Due dates in the past are allowed (duties can be backdated); nothing is
        # written for `overdue` here — it stays a derived state.
        pass

    target_status = values["status"] or "assigned"
    if target_status not in ActivityAssignment.STATUSES:
        errors.append("Select a valid assignment status.")
    elif assignment is not None and target_status != assignment.status:
        if target_status not in ActivityAssignment.STATUS_TRANSITIONS.get(
            assignment.status, ()
        ):
            errors.append(
                f"Cannot change a {assignment.status} assignment to {target_status}."
            )
    elif assignment is None and target_status not in (
        "assigned",
        "in_progress",
        "completed",
    ):
        errors.append("A new assignment must start as assigned, in progress, or completed.")

    values["status"] = target_status
    values["officer"] = officer

    if not errors and officer is not None:
        duplicate = db.session.execute(
            db.select(ActivityAssignment).where(
                ActivityAssignment.activity_id == activity.id,
                ActivityAssignment.officer_user_id == officer.id,
                ActivityAssignment.responsibility == values["responsibility"],
            )
        ).scalar_one_or_none()
        if duplicate is not None and (
            assignment is None or duplicate.id != assignment.id
        ):
            errors.append(
                "That officer already has this responsibility on this activity."
            )

    return values, errors


def _apply_assignment(assignment: ActivityAssignment, values: dict) -> None:
    """Copy validated values onto a fresh assignment (status via set_status)."""
    assignment.officer_user_id = values["officer"].id
    assignment.responsibility = values["responsibility"]
    assignment.due_date = values["_due_date"]
    if values["status"] == "completed":
        assignment.completed_at = datetime.now(timezone.utc)
    else:
        assignment.completed_at = None
    assignment.status = values["status"]


@bp.route("/activities/<int:activity_id>/assignments", methods=["POST"])
@login_required
@role_required(*_MANAGERS)
def activity_assignment_create(activity_id: int):
    """Add one officer responsibility to an activity (multiple allowed)."""
    activity = db.get_or_404(Activity, activity_id)
    if not _may_manage(activity):
        abort(403)
    if activity.status in Activity.TERMINAL_STATUSES:
        flash(
            f"Assignments cannot be added to a {activity.status} activity.", "error"
        )
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    values, errors = _validate_assignment_form(activity, request.form)
    if not errors:
        assignment = ActivityAssignment(activity=activity, assigned_by=current_user.id)
        _apply_assignment(assignment, values)
        db.session.add(assignment)
        try:
            db.session.commit()
        except _DB_INPUT_ERRORS:
            db.session.rollback()
            flash("That assignment already exists for this activity.", "error")
        else:
            flash(f"Responsibility assigned to {values['officer'].full_name}.", "success")
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    for msg in errors:
        flash(msg, "error")
    return redirect(url_for("activities.activity_detail", activity_id=activity.id))


@bp.route(
    "/activities/<int:activity_id>/assignments/<int:assignment_id>/edit",
    methods=["POST"],
)
@login_required
@role_required(*_MANAGERS)
def activity_assignment_edit(activity_id: int, assignment_id: int):
    """Update an assignment's responsibility, officer, due date, or status."""
    activity = db.get_or_404(Activity, activity_id)
    if not _may_manage(activity):
        abort(403)
    assignment = _assignment_for(activity, assignment_id)

    if activity.status in Activity.TERMINAL_STATUSES:
        flash(
            f"Assignments cannot be changed on a {activity.status} activity.", "error"
        )
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    values, errors = _validate_assignment_form(
        activity, request.form, assignment=assignment
    )
    if not errors and values["status"] != assignment.status:
        # Use the model's transition guard as the single source of truth.
        assignment.officer_user_id = values["officer"].id
        assignment.responsibility = values["responsibility"]
        assignment.due_date = values["_due_date"]
        if not assignment.set_status(values["status"]):
            errors.append("That status change is not allowed.")
    if not errors:
        _apply_assignment(assignment, values)
        try:
            db.session.commit()
        except _DB_INPUT_ERRORS:
            db.session.rollback()
            flash("The assignment could not be saved. Please try again.", "error")
        else:
            flash("Assignment updated.", "success")
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    for msg in errors:
        flash(msg, "error")
    return redirect(url_for("activities.activity_detail", activity_id=activity.id))


# ---------------------------------------------------------------------------
# Participation — registration, cancellation, "My Activities"
# ---------------------------------------------------------------------------


def _registration_for(activity: Activity, user_id: int) -> ActivityRegistration | None:
    """The registration row linking this activity to this user (if any)."""
    return db.session.execute(
        db.select(ActivityRegistration).where(
            ActivityRegistration.activity_id == activity.id,
            ActivityRegistration.user_id == user_id,
        )
    ).scalar_one_or_none()


def _register(activity: Activity, user: User) -> str:
    """Register a user for an activity. Returns "success" or "error".

    The schema enforces UNIQUE (activity_id, user_id), so a cancelled
    registration is reactivated rather than duplicated.
    """
    if activity.status != "published":
        return "error"

    existing = _registration_for(activity, user.id)
    if existing is not None:
        if existing.is_active:
            return "error"
        # Rejoin: reactivate the existing row (no duplicate is possible).
        existing.status = "registered"
        existing.registration_date = datetime.now(timezone.utc)
        db.session.commit()
        return "success"

    db.session.add(
        ActivityRegistration(
            activity_id=activity.id,
            user_id=user.id,
            status="registered",
            registration_date=datetime.now(timezone.utc),
        )
    )
    try:
        db.session.commit()
    except _DB_INPUT_ERRORS:
        db.session.rollback()
        return "error"
    return "success"


@bp.route("/activities/<int:activity_id>/register", methods=["POST"])
@login_required
def activity_register(activity_id: int):
    """Self-registration — only published activities accept participants."""
    activity = db.get_or_404(Activity, activity_id)

    if activity.status != "published":
        flash(
            f"“{activity.title}” is not open for registration "
            f"(status: {activity.status}).",
            "error",
        )
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    result = _register(activity, current_user)
    if result == "success":
        flash(f"You are registered for “{activity.title}”.", "success")
    else:
        flash(f"You are already registered for “{activity.title}”.", "error")

    if current_user.role_name == ROLE_PARTICIPANT:
        return redirect(url_for("activities.my_activities"))
    return redirect(url_for("activities.activity_detail", activity_id=activity.id))


@bp.route("/activities/<int:activity_id>/registrations", methods=["POST"])
@login_required
@role_required(*_MANAGERS)
def activity_add_registration(activity_id: int):
    """Staff adds a participant to an activity on their behalf."""
    activity = db.get_or_404(Activity, activity_id)
    if not _may_manage(activity):
        abort(403)

    if activity.status != "published":
        flash(
            f"“{activity.title}” is not open for registration "
            f"(status: {activity.status}).",
            "error",
        )
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    raw_id = (request.form.get("user_id") or "").strip()
    if not raw_id.isdigit():
        flash("Select a participant to add.", "error")
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    user = db.session.get(User, int(raw_id))
    if user is None:
        flash("That participant could not be found.", "error")
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    result = _register(activity, user)
    if result == "success":
        flash(f"{user.full_name} was added to “{activity.title}”.", "success")
    else:
        flash(f"{user.full_name} is already registered for “{activity.title}”.", "error")

    return redirect(url_for("activities.activity_detail", activity_id=activity.id))


@bp.route("/activities/<int:activity_id>/registrations/<int:user_id>/cancel", methods=["POST"])
@login_required
def activity_cancel_registration(activity_id: int, user_id: int):
    """Cancel a registration — the participant's own, or one staff manages."""
    activity = db.get_or_404(Activity, activity_id)
    registration = _registration_for(activity, user_id)
    if registration is None:
        abort(404)

    is_owner = registration.user_id == current_user.id
    may_manage = _may_manage(activity)
    if not (is_owner or may_manage):
        abort(403)

    if registration.is_active:
        registration.status = "cancelled"
        db.session.commit()
        who = "Your registration" if is_owner else f"{registration.user.full_name}'s registration"
        flash(f"{who} for “{activity.title}” was cancelled.", "success")
    else:
        flash("That registration was already cancelled.", "error")

    if is_owner and current_user.role_name == ROLE_PARTICIPANT:
        return redirect(url_for("activities.my_activities"))
    return redirect(url_for("activities.activity_detail", activity_id=activity.id))


@bp.route("/my-activities")
@login_required
@role_required(ROLE_PARTICIPANT)
def my_activities():
    """Participant view — activities joined and activities open for joining."""
    registrations = db.session.execute(
        db.select(ActivityRegistration)
        .where(ActivityRegistration.user_id == current_user.id)
        .order_by(ActivityRegistration.registration_date.desc())
    ).scalars().all()

    joined = [(registration.activity, registration) for registration in registrations]

    open_activities = db.session.execute(
        db.select(Activity)
        .where(Activity.status == "published")
        .order_by(Activity.start_datetime.asc())
    ).scalars().all()
    joined_ids = {activity.id for activity, _ in joined}

    return render_template(
        "activities/my_activities.html",
        joined=joined,
        open_activities=[a for a in open_activities if a.id not in joined_ids],
    )


# ---------------------------------------------------------------------------
# Attendance — recording and listing
# ---------------------------------------------------------------------------

# Activities whose attendance may be recorded (draft not included: nobody has
# attended an activity that was never published).
_ATTENDANCE_ACTIVITY_STATUSES = ("published", "completed")
_ATTENDANCE_STATUSES = AttendanceRecord.STATUSES


def _record_attendance(
    activity: Activity,
    user: User,
    attendance_status: str,
    time_in: datetime | None,
    time_out: datetime | None,
    remarks: str,
    recorded_by: int,
) -> str:
    """Create or update one attendance row. Returns "success" or "error".

    The schema enforces UNIQUE (activity_id, user_id) and a composite foreign
    key that ties an attendance row to a registration of the SAME activity
    and the SAME user.
    """
    if activity.status not in _ATTENDANCE_ACTIVITY_STATUSES:
        return "error"
    if attendance_status not in _ATTENDANCE_STATUSES:
        return "error"
    if time_in and time_out and time_out < time_in:
        return "error"

    registration = _registration_for(activity, user.id)
    existing = db.session.execute(
        db.select(AttendanceRecord).where(
            AttendanceRecord.activity_id == activity.id,
            AttendanceRecord.user_id == user.id,
        )
    ).scalar_one_or_none()

    # Bug 2 (Phase 11): the link is computed once and applied identically on
    # create AND on update. Previously the update path only rewrote the link
    # when a registration happened to be found, so a row could keep pointing at
    # a registration that belonged to a *different* activity/user — which the
    # composite FK rejects at commit time (surfacing as "could not be saved"
    # on every later edit). A person with no registration row is a legitimate
    # walk-in and is stored with registration_id NULL.
    registration_id = registration.id if registration is not None else None

    if existing is not None:
        # Correction of an existing row. `recorded_by`/`recorded_at` keep the
        # established behaviour of tracking the latest write; the new
        # `last_edited_*` pair marks the row as corrected and always reflects
        # the MOST RECENT correction (it is re-stamped on every edit).
        # No correction history is stored.
        corrected_at = datetime.now(timezone.utc)
        existing.attendance_status = attendance_status
        existing.time_in = time_in
        existing.time_out = time_out
        existing.remarks = remarks or None
        existing.registration_id = registration_id
        existing.recorded_by = recorded_by
        existing.recorded_at = corrected_at
        existing.last_edited_by = recorded_by
        existing.last_edited_at = corrected_at
    else:
        db.session.add(
            AttendanceRecord(
                activity_id=activity.id,
                user_id=user.id,
                registration_id=registration_id,
                attendance_status=attendance_status,
                time_in=time_in,
                time_out=time_out,
                remarks=remarks or None,
                recorded_by=recorded_by,
                recorded_at=datetime.now(timezone.utc),
            )
        )

    try:
        db.session.commit()
    except _DB_INPUT_ERRORS:
        db.session.rollback()
        return "error"
    return "success"


@bp.route("/activities/<int:activity_id>/attendance", methods=["POST"])
@login_required
@role_required(*_MANAGERS)
def activity_attendance_record(activity_id: int):
    """Record (or update) one attendance row for an activity."""
    activity = db.get_or_404(Activity, activity_id)
    if not _may_manage(activity):
        abort(403)

    if activity.status not in _ATTENDANCE_ACTIVITY_STATUSES:
        flash(
            f"Attendance cannot be recorded for “{activity.title}” "
            f"(status: {activity.status}).",
            "error",
        )
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    raw_user_id = (request.form.get("user_id") or "").strip()
    if not raw_user_id.isdigit():
        flash("Select a participant to record attendance for.", "error")
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    user = db.session.get(User, int(raw_user_id))
    if user is None:
        flash("That participant could not be found.", "error")
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    status = (request.form.get("attendance_status") or "").strip()
    raw_time_in = (request.form.get("time_in") or "").strip()
    raw_time_out = (request.form.get("time_out") or "").strip()
    time_in = _parse_datetime(raw_time_in)
    time_out = _parse_datetime(raw_time_out)
    remarks = (request.form.get("remarks") or "").strip()

    if _has_nul(remarks):
        flash("Remarks contain invalid characters.", "error")
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    if status not in _ATTENDANCE_STATUSES:
        flash("Select a valid attendance status.", "error")
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))
    if raw_time_in and time_in is None:
        flash("Time in is not a valid date/time.", "error")
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))
    if raw_time_out and time_out is None:
        flash("Time out is not a valid date/time.", "error")
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))
    if time_in and time_out and time_out < time_in:
        flash("Time out cannot be earlier than time in.", "error")
        return redirect(url_for("activities.activity_detail", activity_id=activity.id))

    result = _record_attendance(
        activity, user, status, time_in, time_out, remarks, current_user.id
    )
    if result == "success":
        flash(f"Attendance recorded for {user.full_name}.", "success")
    else:
        flash(f"Attendance for {user.full_name} could not be saved.", "error")

    return redirect(url_for("activities.activity_detail", activity_id=activity.id))


@bp.route("/attendance")
@login_required
@role_required(*_MANAGERS)
def attendance_list():
    """Attendance overview across activities."""
    activity_id = request.args.get("activity_id", type=int)
    status = (request.args.get("status") or "").strip()
    if status and status not in _ATTENDANCE_STATUSES:
        status = ""

    stmt = db.select(AttendanceRecord).order_by(
        AttendanceRecord.recorded_at.desc(), AttendanceRecord.id.desc()
    )
    if activity_id:
        stmt = stmt.where(AttendanceRecord.activity_id == activity_id)
    if status:
        stmt = stmt.where(AttendanceRecord.attendance_status == status)

    records = db.session.execute(stmt).scalars().all()

    activities = db.session.execute(
        db.select(Activity).order_by(Activity.start_datetime.desc())
    ).scalars().all()

    counts = {s: 0 for s in _ATTENDANCE_STATUSES}
    for row in db.session.execute(
        db.select(
            AttendanceRecord.attendance_status, db.func.count(AttendanceRecord.id)
        ).group_by(AttendanceRecord.attendance_status)
    ).all():
        counts[row[0]] = row[1]

    return render_template(
        "activities/attendance.html",
        records=records,
        activities=activities,
        selected_activity=activity_id,
        status=status,
        counts=counts,
        attendance_statuses=_ATTENDANCE_STATUSES,
    )

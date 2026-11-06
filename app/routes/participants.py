"""Event Participants module (Phase 4A) — READ-ONLY views.

Scope and guarantees:
  * Reads ONLY the existing `activity_registrations` and `attendance_records`
    tables. No new tables, columns, identity model, or status values.
  * T18 is unresolved: this module therefore does not create, edit, or imply a
    participant identity of its own. Everyone listed here is an existing system
    account that holds a registration row — the same assumption the Phase 2/3
    registration code already makes.
  * T2 is unresolved: no approval queue, waitlist, or new registration status is
    introduced. Registration statuses stay `registered` / `cancelled`.
  * T1 participation points are excluded; nothing here scores participants.
  * Authorization reuses the four confirmed roles (T19 frozen): the roster and
    detail pages are staff-only, matching `MODULES["participants"]`.
    A participant can only see their own record.
"""
from flask import Blueprint, abort, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db
from app.models.activity import Activity, ActivityRegistration, AttendanceRecord
from app.models.user import (
    ROLE_ADMIN,
    ROLE_ADVISER,
    ROLE_OFFICER,
    Role,
    User,
)
from app.utils.decorators import role_required

bp = Blueprint("participants", __name__)

# Same staff set as MODULES["participants"] (adviser included, read-only by design).
_STAFF = (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER)


def _roles() -> list:
    return Role.query.order_by(Role.id).all()


@bp.route("/participants")
@login_required
@role_required(*_STAFF)
def participant_list():
    """Roster of accounts holding at least one registration row.

    Filters: free-text search (name/email/student ID), role, and activity.
    Counts are derived from existing rows only.
    """
    search = (request.args.get("q") or "").strip()
    role_name = (request.args.get("role") or "").strip()
    activity_id = request.args.get("activity_id", type=int)

    # One row per user, aggregated over their registration and attendance rows.
    reg_count = func.count(func.distinct(ActivityRegistration.id))
    att_count = func.count(func.distinct(AttendanceRecord.id))

    stmt = (
        db.select(
            User,
            reg_count.label("registration_count"),
            att_count.label("attendance_count"),
        )
        .join(ActivityRegistration, ActivityRegistration.user_id == User.id)
        .join(Role, User.role_id == Role.id)
        .outerjoin(
            AttendanceRecord,
            db.and_(
                AttendanceRecord.user_id == User.id,
                AttendanceRecord.activity_id == ActivityRegistration.activity_id,
            ),
        )
        .group_by(User.id)
        .order_by(User.full_name.asc())
    )

    if role_name:
        stmt = stmt.where(Role.name == role_name)
    if activity_id:
        stmt = stmt.where(ActivityRegistration.activity_id == activity_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            db.or_(
                User.full_name.ilike(like),
                User.email.ilike(like),
                User.student_id.ilike(like),
            )
        )

    rows = db.session.execute(stmt).all()

    activities = db.session.execute(
        db.select(Activity).order_by(Activity.start_datetime.desc())
    ).scalars().all()

    return render_template(
        "participants/list.html",
        rows=rows,
        search=search,
        role=role_name,
        activity_id=activity_id,
        activities=activities,
        roles=_roles(),
        total=len(rows),
    )


@bp.route("/participants/<int:user_id>")
@login_required
def participant_detail(user_id: int):
    """One participant's registration and attendance history (read-only).

    Staff may open any participant. A participant may open only their own
    record (same all-or-nothing rule as the surrounding modules).
    """
    if current_user.role_name not in _STAFF and current_user.id != user_id:
        abort(403)

    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    registrations = db.session.execute(
        db.select(ActivityRegistration)
        .where(ActivityRegistration.user_id == user.id)
        .order_by(ActivityRegistration.registration_date.desc())
    ).scalars().all()

    attendance = db.session.execute(
        db.select(AttendanceRecord)
        .where(AttendanceRecord.user_id == user.id)
        .order_by(AttendanceRecord.recorded_at.desc())
    ).scalars().all()

    counts = {s: 0 for s in AttendanceRecord.STATUSES}
    for record in attendance:
        counts[record.attendance_status] = counts.get(record.attendance_status, 0) + 1

    attendance_by_activity = {a.activity_id: a for a in attendance}

    return render_template(
        "participants/detail.html",
        participant=user,
        registrations=registrations,
        attendance=attendance,
        attendance_counts=counts,
        attendance_by_activity=attendance_by_activity,
        is_staff=current_user.role_name in _STAFF,
    )

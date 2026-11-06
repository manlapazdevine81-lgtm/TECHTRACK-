"""Officer performance analytics — OBJECTIVE metrics only (Phase 5).

Design constraints (docs/REQUIREMENTS.md, ERD "Analytics data sources"):
  * Counts, percentages, and timelines ONLY. No composite scores, no weights,
    no rankings, no leaderboards, no subjective grades, no invented formulas.
  * "Activities organized/created" is EXCLUDED until T12 is resolved.
  * Every rate is computed against an explicit denominator; when that
    denominator is zero the rate is reported as None (rendered as "—") instead
    of 0 or an exception.
  * Officers are listed in alphabetical order by name — never ordered by a
    metric — so the ordering itself cannot imply a ranking.

Metric definitions (all derived from existing rows only):
  * Assigned responsibilities        = COUNT(activity_assignments)
  * Completed responsibilities       = COUNT(assignments WHERE status='completed')
  * Overdue responsibilities         = assignments with a passed due_date that are
                                       not completed (the model's derived
                                       `is_overdue` rule, computed here in SQL so
                                       it matches the model without writing it)
  * Open responsibilities            = assigned / in_progress / overdue (stored)
  * Completion rate                  = completed / assigned  (None if assigned == 0)
  * Participation (registrations)    = COUNT(activity_registrations) for the officer
  * Attendance records               = COUNT(attendance_records) for the officer
  * Attendance present/late/absent/excused = per-status counts
  * Attendance rate                  = (present + late) / attendance records
                                       (None if no attendance rows)
  * Timeline                         = activity start dates for the officer's
                                       assigned responsibilities (month buckets)
"""
from datetime import date, datetime, timezone

from sqlalchemy import func

from app.extensions import db
from app.models.activity import Activity, ActivityRegistration, AttendanceRecord
from app.models.assignment import ActivityAssignment
from app.models.user import ROLE_ADMIN, ROLE_OFFICER, Role, User

# Only confirmed officer roles (T19 frozen: never a numeric permission level).
OFFICER_ROLES = (ROLE_ADMIN, ROLE_OFFICER)

# Attendance statuses that count as "attended" for the attendance rate.
_ATTENDED = ("present", "late")


def _rate(numerator: int, denominator: int):
    """Percentage rounded to one decimal, or None when the denominator is 0."""
    if not denominator:
        return None
    return round(numerator * 100.0 / denominator, 1)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def officer_summaries() -> list[dict]:
    """One objective summary row per eligible officer, ordered by name.

    Officers with no data are still returned (all zeros / None rates) so the
    dashboard is honest about "no assignments yet" rather than hiding people.
    """
    officers = db.session.execute(
        db.select(User)
        .join(Role, User.role_id == Role.id)
        .where(Role.name.in_(OFFICER_ROLES), User.is_active.is_(True))
        .order_by(User.full_name.asc(), User.id.asc())
    ).scalars().all()

    today = _today()
    summaries: list[dict] = []

    for officer in officers:
        assignments = db.session.execute(
            db.select(ActivityAssignment).where(
                ActivityAssignment.officer_user_id == officer.id
            )
        ).scalars().all()

        assigned = len(assignments)
        completed = sum(1 for a in assignments if a.status == "completed")
        overdue = sum(
            1
            for a in assignments
            if a.status != "completed" and a.due_date is not None and a.due_date < today
        )
        open_count = sum(
            1 for a in assignments if a.status in ("assigned", "in_progress")
        )

        registrations = db.session.execute(
            db.select(func.count(ActivityRegistration.id)).where(
                ActivityRegistration.user_id == officer.id
            )
        ).scalar() or 0

        attendance_counts = {s: 0 for s in AttendanceRecord.STATUSES}
        for status, count in db.session.execute(
            db.select(
                AttendanceRecord.attendance_status, func.count(AttendanceRecord.id)
            )
            .where(AttendanceRecord.user_id == officer.id)
            .group_by(AttendanceRecord.attendance_status)
        ).all():
            if status in attendance_counts:
                attendance_counts[status] = count

        attendance_total = sum(attendance_counts.values())
        attended = sum(attendance_counts.get(s, 0) for s in _ATTENDED)

        summaries.append(
            {
                "officer": officer,
                "assigned": assigned,
                "completed": completed,
                "open": open_count + overdue,
                "overdue": overdue,
                "completion_rate": _rate(completed, assigned),
                "registrations": registrations,
                "attendance_total": attendance_total,
                "attendance": attendance_counts,
                "attendance_rate": _rate(attended, attendance_total),
            }
        )

    return summaries


def responsibility_timeline(months: int = 12) -> dict:
    """Monthly counts of assigned responsibilities by activity start month.

    Returns the last `months` calendar months (oldest first) so the chart has a
    stable axis even when there is no data. Counts only — no rate, no score.
    """
    today = _today()
    buckets: list[tuple[int, int]] = []
    year, month = today.year, today.month
    for _ in range(months):
        buckets.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    buckets.reverse()

    rows = db.session.execute(
        db.select(
            func.extract("year", Activity.start_datetime).label("y"),
            func.extract("month", Activity.start_datetime).label("m"),
            func.count(ActivityAssignment.id),
        )
        .join(Activity, Activity.id == ActivityAssignment.activity_id)
        .group_by("y", "m")
    ).all()

    counts = {(int(y), int(m)): n for (y, m, n) in rows}

    labels = [f"{y}-{m:02d}" for (y, m) in buckets]
    values = [counts.get(b, 0) for b in buckets]
    return {"labels": labels, "counts": values}


def attendance_distribution() -> dict:
    """Aggregate attendance status counts across all officers (no per-person ranking)."""
    counts = {s: 0 for s in AttendanceRecord.STATUSES}
    for status, count in db.session.execute(
        db.select(AttendanceRecord.attendance_status, func.count(AttendanceRecord.id))
        .group_by(AttendanceRecord.attendance_status)
    ).all():
        if status in counts:
            counts[status] = count
    return counts


def overall_totals() -> dict:
    """Dashboard KPI totals. Counts and rates only; T12 metric deliberately absent."""
    assigned = db.session.execute(
        db.select(func.count(ActivityAssignment.id))
    ).scalar() or 0
    completed = db.session.execute(
        db.select(func.count(ActivityAssignment.id)).where(
            ActivityAssignment.status == "completed"
        )
    ).scalar() or 0

    today = _today()
    overdue = db.session.execute(
        db.select(func.count(ActivityAssignment.id)).where(
            ActivityAssignment.status != "completed",
            ActivityAssignment.due_date.is_not(None),
            ActivityAssignment.due_date < today,
        )
    ).scalar() or 0

    attendance = attendance_distribution()
    attendance_total = sum(attendance.values())
    attended = sum(attendance.get(s, 0) for s in _ATTENDED)

    return {
        "assigned": assigned,
        "completed": completed,
        "overdue": overdue,
        "completion_rate": _rate(completed, assigned),
        "attendance_total": attendance_total,
        "attendance_rate": _rate(attended, attendance_total),
    }


def build_dashboard(months: int = 12) -> dict:
    """Everything the Phase 5 dashboard needs, in one call."""
    return {
        "totals": overall_totals(),
        "officers": officer_summaries(),
        "timeline": responsibility_timeline(months=months),
        "attendance": attendance_distribution(),
        "has_data": bool(
            db.session.execute(
                db.select(func.count(ActivityAssignment.id))
            ).scalar()
            or 0
        ),
    }

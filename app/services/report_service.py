"""Phase 9 report builders — CSV only (PDF stays blocked by T13).

Approved scope (docs/REQUIREMENTS.md "Reports (formats: T13)", docs/PHASE_PLAN.md
Phase 9 "CSV (+PDF if confirmed per T13)"). T13 has NOT confirmed a report list
or PDF, so this module implements only the four reports the requirements and the
already-built modules explicitly name, and nothing else:

  attendance    — per attendance row (activity, participant, status, time in/out)
  participation — per activity (registrations, attendance, conversion, rates)
  activities    — activity registration/attendance summary
  registrations — per registration row (who registered for what, and its status)

Reuse, not duplication:
  * CSV text, formula-injection neutralization, filename sanitizing and the
    download Response all come from ``app.utils.csv_export`` — this module never
    writes CSV itself.
  * Filter parsing comes from ``general_analytics_service.parse_filters`` (same
    ``activity_id`` / ``academic_year`` rules as the Phase 8 page).
  * Participation/conversion numbers come from
    ``general_analytics_service.build_activity_frame`` + ``_totals`` so the CSV
    cannot drift from the dashboard.

Data-safety rules applied to every export:
  * Cells starting with ``=``, ``+``, ``-``, ``@``, TAB or CR are neutralized by
    ``csv_export.sanitize_cell`` (OWASP CSV injection).
  * Timestamps are written as ISO-8601 UTC text (``YYYY-MM-DD HH:MM:SS``) so a
    spreadsheet cannot reinterpret them in the viewer's local locale.
  * Statuses/roles are rendered from the stored values; no new values invented.

T18 stays unresolved: participant emails/student IDs are included ONLY for the
staff roles already allowed to read them on the participant roster, and are
omitted entirely from the participant-facing report.
"""
from datetime import datetime, timezone

from sqlalchemy import func

from app.extensions import db
from app.models.activity import Activity, ActivityRegistration, AttendanceRecord
from app.models.user import Role, User
from app.services import general_analytics_service as ga
from app.utils.csv_export import csv_response

from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER

# Staff set that may read participant contact details (matches the roster).
# Adviser is deliberately excluded: their in-app roster view omits contact data.
_FULL_FIELDS_ROLES = (ROLE_ADMIN, ROLE_OFFICER)

# Cell text used when a rate has no denominator (never 0, never NaN).
_EMPTY_RATE = ""


def _iso(moment) -> str:
    """ISO-8601 UTC text, or empty string when absent.

    Aware datetimes are converted to UTC first so the exported value does not
    depend on the exporting machine's timezone. Naive values (possible with
    older rows) are assumed to be UTC and labelled as such.
    """
    if moment is None:
        return ""
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _pct(value) -> str:
    """Render a rate for CSV: "75.0" (no % sign, so it stays numeric) or ""."""
    if value is None:
        return _EMPTY_RATE
    return f"{value:.1f}"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _filename(base: str, filters: dict) -> str:
    """Stable, descriptive name that records the applied filters."""
    parts = [base]
    if filters.get("academic_year"):
        parts.append(f"ay{filters['academic_year']}")
    if filters.get("activity_id"):
        parts.append(f"activity{filters['activity_id']}")
    parts.append(_stamp())
    return "_".join(parts) + ".csv"


def can_see_participant_contact(role_name: str) -> bool:
    """True for staff roles that already read emails/student IDs in-app."""
    return role_name in _FULL_FIELDS_ROLES


def _current_role_name() -> str:
    """Role of the caller, taken from the authenticated session.

    The route already enforced the staff-only rule; this is the second check
    that decides whether participant contact columns may be written.
    """
    from flask_login import current_user

    if not current_user.is_authenticated:
        return ""
    return current_user.role_name


# ---------------------------------------------------------------------------
# Shared query helpers
# ---------------------------------------------------------------------------


def available_activities() -> list[dict]:
    """Activity options for the report page (newest first)."""
    rows = db.session.execute(
        db.select(Activity.id, Activity.title).order_by(
            Activity.start_datetime.desc(), Activity.id.desc()
        )
    ).all()
    return [{"activity_id": r[0], "title": r[1]} for r in rows]


def available_academic_years() -> list[str]:
    return ga.academic_years()


def resolve_filters(args) -> dict:
    """Parse + validate report filters.

    Uses the Phase 8 rules, then drops (and reports) an activity id or school
    year that does not exist, so an export never silently looks empty because
    of a typo.
    """
    filters = ga.parse_filters(args)
    ignored: list[str] = []

    activity_id = filters.get("activity_id")
    if activity_id is not None:
        exists = db.session.get(Activity, activity_id) is not None
        if not exists:
            ignored.append(
                "The activity filter was ignored: no activity has that number."
            )
            filters["activity_id"] = None

    year = filters.get("academic_year")
    if year is not None:
        if year not in available_academic_years():
            ignored.append(
                f"The academic-year filter {year} was ignored: no activity starts "
                "in that school year."
            )
            filters["academic_year"] = None

    filters["errors"] = list(filters.get("errors") or []) + ignored
    return filters


def _activity_ids_for(filters: dict) -> list[int] | None:
    """Activity ids matching the filters, or None for "no activity filter"."""
    if not filters.get("activity_id") and not filters.get("academic_year"):
        return None
    query = db.select(Activity.id)
    if filters.get("activity_id"):
        query = query.where(Activity.id == filters["activity_id"])
    if filters.get("academic_year"):
        # School year is derived, not stored: match it in Python via the same
        # helper Phase 8 uses, so both views always agree.
        year_ids = [
            activity_id
            for activity_id, start in db.session.execute(
                db.select(Activity.id, Activity.start_datetime)
            ).all()
            if ga.academic_year_for(start) == filters["academic_year"]
        ]
        if not year_ids:
            return []
        query = query.where(Activity.id.in_(year_ids))
    return list(db.session.execute(query).scalars().all())


# ---------------------------------------------------------------------------
# 1. Attendance report (one row per attendance record)
# ---------------------------------------------------------------------------


def attendance_report(args, role_name: str | None = None):
    """Per-attendance-row export. Participant contact data is role-gated."""
    filters = resolve_filters(args)
    include_contact = can_see_participant_contact(role_name or _current_role_name())

    query = (
        db.select(
            Activity.title,
            Activity.status,
            Activity.start_datetime,
            User.full_name,
            User.email,
            User.student_id,
            Role.display_name,
            AttendanceRecord.attendance_status,
            AttendanceRecord.time_in,
            AttendanceRecord.time_out,
            AttendanceRecord.registration_id,
            AttendanceRecord.remarks,
            AttendanceRecord.recorded_at,
        )
        .join(Activity, Activity.id == AttendanceRecord.activity_id)
        .join(User, User.id == AttendanceRecord.user_id)
        .join(Role, Role.id == User.role_id)
    )
    ids = _activity_ids_for(filters)
    if ids is not None:
        query = query.where(AttendanceRecord.activity_id.in_(ids))
    query = query.order_by(
        Activity.start_datetime.asc(),
        Activity.id.asc(),
        User.full_name.asc(),
    )
    rows = db.session.execute(query).all()

    headers = ["Activity", "Activity Status", "Activity Date", "Participant"]
    if include_contact:
        headers += ["Email", "Student ID"]
    headers += [
        "Role",
        "Attendance Status",
        "Time In (UTC)",
        "Time Out (UTC)",
        "Registration Linked",
        "Remarks",
        "Recorded At (UTC)",
    ]

    def build_row(r):
        row = [r[0], r[1], _iso(r[2]), r[3]]
        if include_contact:
            row += [r[4] or "", r[5] or ""]
        row += [
            r[6],
            r[7],
            _iso(r[8]),
            _iso(r[9]),
            "Yes" if r[10] is not None else "No",
            r[11] or "",
            _iso(r[12]),
        ]
        return row

    return csv_response(
        headers,
        [build_row(r) for r in rows],
        _filename("attendance_report", filters),
    )


# ---------------------------------------------------------------------------
# 2. Participation report (per activity, reuses Phase 8 math)
# ---------------------------------------------------------------------------


def participation_report(args, role_name: str | None = None):  # noqa: ARG001
    """Per-activity participation/conversion export (same numbers as Phase 8)."""
    filters = resolve_filters(args)

    filtered, _ignored = ga.filtered_activity_frame(filters)

    headers = [
        "Activity ID",
        "Activity",
        "Type",
        "Status",
        "Start (UTC)",
        "School Year",
        "Active Registrations",
        "Cancelled Registrations",
        "Attendance Rows",
        "Walk-ins",
        "Present",
        "Late",
        "Absent",
        "Excused",
        "Conversion (%)",
        "Attendance Rate (%)",
    ]
    rows = []
    if not filtered.empty:
        # Long text cell -> NaN; NaN is not a value, so it must be normalized
        # back to "" or it would leak as the literal string "nan" in the CSV.
        filtered = filtered.assign(activity_type=filtered["activity_type"].fillna(""))
        for r in filtered.sort_values(
            by=["start", "activity_id"], ascending=[True, True]
        ).itertuples(index=False):
            start = r.start.to_pydatetime() if hasattr(r.start, "to_pydatetime") else r.start
            rows.append(
                [
                    r.activity_id,
                    r.title,
                    r.activity_type,
                    r.status,
                    _iso(start),
                    r.academic_year or "",
                    r.registered,
                    r.cancelled,
                    r.attendance_rows,
                    r.walk_ins,
                    r.present,
                    r.late,
                    r.absent,
                    r.excused,
                    _pct(r.conversion),
                    _pct(r.attendance_rate),
                ]
            )
    return csv_response(
        headers, rows, _filename("participation_report", filters)
    )


# ---------------------------------------------------------------------------
# 3. Activities report (registration + attendance summary + totals)
# ---------------------------------------------------------------------------


def activities_report(args, role_name: str | None = None):  # noqa: ARG001
    """One row per activity plus a clearly labelled TOTAL row."""
    filters = resolve_filters(args)

    registered = (
        db.select(func.count(ActivityRegistration.id))
        .where(
            ActivityRegistration.activity_id == Activity.id,
            ActivityRegistration.status == "registered",
        )
        .correlate(Activity)
        .scalar_subquery()
    )
    cancelled = (
        db.select(func.count(ActivityRegistration.id))
        .where(
            ActivityRegistration.activity_id == Activity.id,
            ActivityRegistration.status == "cancelled",
        )
        .correlate(Activity)
        .scalar_subquery()
    )
    attendance_total = (
        db.select(func.count(AttendanceRecord.id))
        .where(AttendanceRecord.activity_id == Activity.id)
        .correlate(Activity)
        .scalar_subquery()
    )
    attended = (
        db.select(func.count(AttendanceRecord.id))
        .where(
            AttendanceRecord.activity_id == Activity.id,
            AttendanceRecord.attendance_status.in_(("present", "late")),
        )
        .correlate(Activity)
        .scalar_subquery()
    )

    rows = []
    totals = {"registered": 0, "cancelled": 0, "attendance": 0, "attended": 0}
    for activity, reg, canc, att, att_present in db.session.execute(
        db.select(Activity, registered, cancelled, attendance_total, attended).order_by(
            Activity.start_datetime.asc(), Activity.id.asc()
        )
    ).all():
        reg, canc, att, att_present = int(reg or 0), int(canc or 0), int(att or 0), int(att_present or 0)
        totals["registered"] += reg
        totals["cancelled"] += canc
        totals["attendance"] += att
        totals["attended"] += att_present
        rows.append(
            [
                activity.id,
                activity.title,
                activity.activity_type or "",
                activity.status,
                _iso(activity.start_datetime),
                _iso(activity.end_datetime),
                ga.academic_year_for(activity.start_datetime) or "",
                reg,
                canc,
                att,
                _pct(ga.rate(att, reg)),
                _pct(ga.rate(att_present, att)),
            ]
        )

    headers = [
        "Activity ID",
        "Activity",
        "Type",
        "Status",
        "Start (UTC)",
        "End (UTC)",
        "School Year",
        "Active Registrations",
        "Cancelled Registrations",
        "Attendance Rows",
        "Conversion (%)",
        "Attendance Rate (%)",
    ]
    if rows:
        rows.append(
            [
                "",
                "TOTAL",
                "",
                "",
                "",
                "",
                "",
                totals["registered"],
                totals["cancelled"],
                totals["attendance"],
                _pct(ga.rate(totals["attendance"], totals["registered"])),
                _pct(ga.rate(totals["attended"], totals["attendance"])),
            ]
        )
    return csv_response(headers, rows, _filename("activities_report", filters))


# ---------------------------------------------------------------------------
# 4. Registrations report (one row per registration record)
# ---------------------------------------------------------------------------


def registrations_report(args, role_name: str | None = None):
    """Per-registration export. Participant contact data is role-gated."""
    filters = resolve_filters(args)
    include_contact = can_see_participant_contact(role_name or _current_role_name())

    query = (
        db.select(
            Activity.id,
            Activity.title,
            Activity.status,
            Activity.start_datetime,
            User.full_name,
            User.email,
            User.student_id,
            Role.display_name,
            ActivityRegistration.status,
            ActivityRegistration.registration_date,
            AttendanceRecord.attendance_status,
        )
        .join(Activity, Activity.id == ActivityRegistration.activity_id)
        .join(User, User.id == ActivityRegistration.user_id)
        .join(Role, Role.id == User.role_id)
        .outerjoin(
            AttendanceRecord,
            db.and_(
                AttendanceRecord.activity_id == ActivityRegistration.activity_id,
                AttendanceRecord.user_id == ActivityRegistration.user_id,
            ),
        )
    )
    ids = _activity_ids_for(filters)
    if ids is not None:
        query = query.where(ActivityRegistration.activity_id.in_(ids))
    query = query.order_by(
        Activity.start_datetime.asc(),
        Activity.id.asc(),
        User.full_name.asc(),
    )
    rows = db.session.execute(query).all()

    headers = ["Activity ID", "Activity", "Activity Status", "Activity Date", "Participant"]
    if include_contact:
        headers += ["Email", "Student ID"]
    headers += [
        "Role",
        "Registration Status",
        "Registered At (UTC)",
        "Attendance Status",
    ]

    def build_row(r):
        row = [r[0], r[1], r[2], _iso(r[3]), r[4]]
        if include_contact:
            row += [r[5] or "", r[6] or ""]
        row += [
            r[7],
            r[8],
            _iso(r[9]),
            r[10] or "Not recorded",
        ]
        return row

    return csv_response(
        headers,
        [build_row(r) for r in rows],
        _filename("registrations_report", filters),
    )


# ---------------------------------------------------------------------------
# Registry used by the route layer and the page
# ---------------------------------------------------------------------------


REPORTS = {
    "attendance": {
        "label": "Attendance",
        "description": "One row per attendance record: status, time in/out, "
        "registration link, and remarks.",
        "builder": attendance_report,
        "filters": ["activity_id", "academic_year"],
    },
    "participation": {
        "label": "Participation & conversion",
        "description": "One row per activity: active/cancelled registrations, "
        "attendance rows, walk-ins, per-status counts, conversion rate.",
        "builder": participation_report,
        "filters": ["activity_id", "academic_year"],
    },
    "activities": {
        "label": "Activity summary",
        "description": "Registration and attendance summary per activity, with a "
        "TOTAL row.",
        "builder": activities_report,
        "filters": ["activity_id", "academic_year"],
    },
    "registrations": {
        "label": "Registrations",
        "description": "One row per registration: participant, status, date "
        "registered, and whether attendance was recorded.",
        "builder": registrations_report,
        "filters": ["activity_id", "academic_year"],
    },
}

"""General attendance and participation analytics (Phase 8).

Scope (docs/PHASE_PLAN.md, Phase 8): "Attendance/participation trends, KPIs,
registration→attendance conversion, filters by AY/event".

Design constraints:
  * OBJECTIVE counts, percentages and dates only — no composite scores, no
    rankings, no invented targets. Phase 5 (`analytics_service`) already owns
    per-officer *responsibility* metrics; nothing here repeats those. The two
    officer-related figures below exist only as the denominators of the
    conversion rate and are labelled as such.
  * Pandas does the aggregation. The SQL layer only reads the approved rows
    (activities, registrations, attendance); all grouping/joins/rates happen
    in a DataFrame so zero denominators are handled once, in one place.
  * An empty rate/percentage is ALWAYS ``None`` and renders as "—", never 0,
    never a NaN, never a division-by-zero exception.
  * Filters never trust input: an unparseable activity id or an academic year
    that would have no matching activities is reported as an *ignored filter*
    instead of silently returning an empty dashboard that looks genuine.

Metric definitions (every denominator is explicit):
  * Registered / Attended counts use ACTIVE registrations only
    (`status == 'registered'`); cancelled registrations are excluded from the
    participation denominator but reported separately.
  * Sessions (activities) with a denominator are counted per distinct activity.
  * Conversion ("conversion") = attendance rows ÷ active registrations, per
    activity. Attendance rows for people who never registered (walk-ins) can
    push a single activity above 100% — the rate is NOT clamped, because
    clamping would hide walk-ins. Walk-ins are reported separately.
  * Attendance rate = (present + late) ÷ attendance rows.
  * Turnout = attendance rows ÷ active registrations (same conversion, but
    measured from the attendance side; differs from "conversion" only when a
    registration is missing).

Academic-year (AY) filter:
  * `organizations.academic_year` is free text and not linked to activities,
    so an AY is DERIVED from an activity's `start_datetime` using the
    Philippine school-year convention (June → March boundary):
      start month >= 6  ->  f"{year}-{year + 1}"
      start month <= 5  ->  f"{year - 1}-{year}"
    (e.g. 2026-02-10 → "2025-2026"; 2026-07-01 → "2026-2027").
  * No academic-year table, column, or migration is introduced.
"""
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import func

from app.extensions import db
from app.models.activity import Activity, ActivityRegistration, AttendanceRecord
from app.models.organization import Organization

# "Attended" = present + late (same rule as Phase 5); the other statuses are
# still counted so the distribution is complete. Aggregation happens in Pandas,
# so there are no SQL-level status constants here.

# Row → named aggregate defaults so a DataFrame with zero rows still has
# every expected column (Pandas 3 keeps declared dtypes here).
_ACTIVITY_COLUMNS = {
    "activity_id": "int64",
    "title": "object",
    "activity_type": "object",
    "status": "object",
    "start": "datetime64[ns, UTC]",
    "academic_year": "object",
    "registered": "int64",
    "cancelled": "int64",
    "attendance_rows": "int64",
    "present": "int64",
    "late": "int64",
    "absent": "int64",
    "excused": "int64",
    "walk_ins": "int64",
}


def rate(numerator, denominator):
    """Percentage rounded to one decimal, or None when the denominator is 0.

    Accepts Pandas scalars/NaN; any non-finite or zero denominator → None.
    """
    if denominator is None or pd.isna(denominator) or denominator == 0:
        return None
    if numerator is None or pd.isna(numerator):
        return None
    return round(float(numerator) * 100.0 / float(denominator), 1)


def academic_year_for(moment) -> str | None:
    """Derive the school year label for a datetime (June–May convention)."""
    if moment is None or pd.isna(moment):
        return None
    year = int(moment.year)
    return f"{year}-{year + 1}" if moment.month >= 6 else f"{year - 1}-{year}"


# ---------------------------------------------------------------------------
# Filter parsing (never raises, never trusts input)
# ---------------------------------------------------------------------------


def parse_filters(args) -> dict:
    """Normalise query-string filters.

    Returns ``{"activity_id": int | None, "academic_year": str | None,
    "errors": [str, ...]}``. Invalid values are dropped and logged in
    ``errors`` so the view can tell the user the filter was ignored.
    """
    filters = {"activity_id": None, "academic_year": None, "errors": []}

    raw_activity = (args.get("activity_id") or "").strip()
    if raw_activity:
        if raw_activity.isdigit() and int(raw_activity) > 0:
            filters["activity_id"] = int(raw_activity)
        else:
            filters["errors"].append(
                "The activity filter was ignored: it must be a valid activity number."
            )

    raw_year = (args.get("academic_year") or "").strip()
    if raw_year:
        # Accept only the "YYYY-YYYY" shape with consecutive years.
        parts = raw_year.split("-")
        valid = (
            len(parts) == 2
            and all(p.isdigit() and len(p) == 4 for p in parts)
            and int(parts[1]) == int(parts[0]) + 1
        )
        if valid:
            filters["academic_year"] = raw_year
        else:
            filters["errors"].append(
                "The academic-year filter was ignored: use the form 2025-2026."
            )
    return filters


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------


def _load_registrations() -> pd.DataFrame:
    """Every registration row with its activity (active flag included)."""
    rows = db.session.execute(
        db.select(
            ActivityRegistration.id,
            ActivityRegistration.activity_id,
            ActivityRegistration.user_id,
            ActivityRegistration.status,
        )
    ).all()
    return pd.DataFrame(
        rows,
        columns=["registration_id", "activity_id", "user_id", "reg_status"],
    )


def _load_attendance() -> pd.DataFrame:
    """Every attendance row (registration link optional — walk-ins have NULL)."""
    rows = db.session.execute(
        db.select(
            AttendanceRecord.id,
            AttendanceRecord.activity_id,
            AttendanceRecord.user_id,
            AttendanceRecord.registration_id,
            AttendanceRecord.attendance_status,
        )
    ).all()
    return pd.DataFrame(
        rows,
        columns=[
            "attendance_id",
            "activity_id",
            "user_id",
            "registration_id",
            "attendance_status",
        ],
    )


def _load_activities() -> pd.DataFrame:
    rows = db.session.execute(
        db.select(
            Activity.id,
            Activity.title,
            Activity.activity_type,
            Activity.status,
            Activity.start_datetime,
        ).order_by(Activity.start_datetime.asc(), Activity.id.asc())
    ).all()
    frame = pd.DataFrame(
        rows,
        columns=["activity_id", "title", "activity_type", "status", "start"],
    )
    if not frame.empty:
        starts = pd.to_datetime(frame["start"], utc=True)
        frame["start"] = starts
        frame["academic_year"] = starts.map(academic_year_for)
    else:
        frame = pd.DataFrame(
            {k: [] for k in ("activity_id", "title", "activity_type", "status", "start")}
        )
        frame["academic_year"] = pd.Series(dtype="object")
    return frame


# ---------------------------------------------------------------------------
# Aggregation core (pure Pandas — takes frames, returns frames)
# ---------------------------------------------------------------------------


def build_activity_frame(
    activities: pd.DataFrame,
    registrations: pd.DataFrame,
    attendance: pd.DataFrame,
) -> pd.DataFrame:
    """One row per activity with explicit numerators/denominators.

    Pure function: no database access, so calculations are testable directly.
    """
    if activities.empty:
        return pd.DataFrame(
            {k: pd.Series(dtype=v) for k, v in _ACTIVITY_COLUMNS.items()}
        )

    base = activities[
        [
            "activity_id",
            "title",
            "activity_type",
            "status",
            "start",
            "academic_year",
        ]
    ].copy()

    # Registrations: active vs cancelled.
    if registrations.empty:
        reg_counts = pd.DataFrame(
            {
                "activity_id": pd.Series(dtype="int64"),
                "registered": pd.Series(dtype="int64"),
                "cancelled": pd.Series(dtype="int64"),
            }
        )
    else:
        active = registrations[registrations["reg_status"] == "registered"]
        reg_counts = pd.DataFrame(
            {
                "registered": active.groupby("activity_id").size(),
                "cancelled": registrations[registrations["reg_status"] == "cancelled"]
                .groupby("activity_id")
                .size(),
            }
        ).reset_index()
        reg_counts = reg_counts.fillna({"registered": 0, "cancelled": 0})
        reg_counts[["registered", "cancelled"]] = reg_counts[
            ["registered", "cancelled"]
        ].astype("int64")

    # Attendance: totals, per-status counts, and walk-ins (no registration link).
    if attendance.empty:
        att_counts = pd.DataFrame(
            {
                "activity_id": pd.Series(dtype="int64"),
                "attendance_rows": pd.Series(dtype="int64"),
                "walk_ins": pd.Series(dtype="int64"),
                "_present": pd.Series(dtype="int64"),
                "_late": pd.Series(dtype="int64"),
                "_absent": pd.Series(dtype="int64"),
                "_excused": pd.Series(dtype="int64"),
            }
        )
    else:
        att = attendance.copy()
        att["is_present"] = (att["attendance_status"] == "present").astype("int64")
        att["is_late"] = (att["attendance_status"] == "late").astype("int64")
        att["is_absent"] = (att["attendance_status"] == "absent").astype("int64")
        att["is_excused"] = (att["attendance_status"] == "excused").astype("int64")
        att["is_walkin"] = att["registration_id"].isna().astype("int64")
        grouped = att.groupby("activity_id").agg(
            attendance_rows=("attendance_id", "size"),
            walk_ins=("is_walkin", "sum"),
            _present=("is_present", "sum"),
            _late=("is_late", "sum"),
            _absent=("is_absent", "sum"),
            _excused=("is_excused", "sum"),
        )
        att_counts = grouped.reset_index()
        count_cols = [
            "attendance_rows",
            "walk_ins",
            "_present",
            "_late",
            "_absent",
            "_excused",
        ]
        att_counts[count_cols] = att_counts[count_cols].astype("int64")

    frame = (
        base.merge(reg_counts, on="activity_id", how="left")
        .merge(att_counts, on="activity_id", how="left")
    )
    count_cols = [
        "registered",
        "cancelled",
        "attendance_rows",
        "walk_ins",
        "_present",
        "_late",
        "_absent",
        "_excused",
    ]
    frame[count_cols] = frame[count_cols].fillna(0).astype("int64")

    frame = frame.rename(
        columns={
            "_present": "present",
            "_late": "late",
            "_absent": "absent",
            "_excused": "excused",
        }
    )

    # Explicit denominators -> rates (None when the denominator is 0).
    # Built as a plain ``None`` list and assigned with ``object`` dtype: a NaN
    # must never reach the renderer, and a float64 column would turn ``None``
    # back into NaN.
    conversions = [
        rate(a, r) for a, r in zip(frame["attendance_rows"], frame["registered"])
    ]
    attendance_rates = [
        rate(p + l, t)
        for p, l, t in zip(
            frame["present"], frame["late"], frame["attendance_rows"]
        )
    ]
    # Force object dtype: any numeric dtype would convert the Nones to NaN.
    frame["conversion"] = pd.Series(conversions, index=frame.index, dtype=object)
    frame["attendance_rate"] = pd.Series(
        attendance_rates, index=frame.index, dtype=object
    )
    return frame


def _apply_filters(frame: pd.DataFrame, filters: dict, activities: pd.DataFrame):
    """Return (filtered frame, ignored-filter messages)."""
    ignored: list[str] = []
    result = frame

    activity_id = filters.get("activity_id")
    if activity_id is not None:
        if activity_id in set(activities["activity_id"].tolist()):
            result = result[result["activity_id"] == activity_id]
        else:
            ignored.append(
                "The activity filter was ignored: no activity has that number."
            )

    academic_year = filters.get("academic_year")
    if academic_year is not None:
        if academic_year in set(activities["academic_year"].dropna().tolist()):
            result = result[result["academic_year"] == academic_year]
        else:
            ignored.append(
                f"The academic-year filter {academic_year} was ignored: no activity "
                "starts in that school year."
            )
    return result, ignored


def _totals(frame: pd.DataFrame) -> dict:
    """KPIs for a filtered activity frame. All rates use explicit denominators."""
    registered = int(frame["registered"].sum()) if not frame.empty else 0
    cancelled = int(frame["cancelled"].sum()) if not frame.empty else 0
    attendance_rows = int(frame["attendance_rows"].sum()) if not frame.empty else 0
    present = int(frame["present"].sum()) if not frame.empty else 0
    late = int(frame["late"].sum()) if not frame.empty else 0
    absent = int(frame["absent"].sum()) if not frame.empty else 0
    excused = int(frame["excused"].sum()) if not frame.empty else 0
    walk_ins = int(frame["walk_ins"].sum()) if not frame.empty else 0

    sessions = int((frame["registered"] > 0).sum()) if not frame.empty else 0
    sessions_with_attendance = (
        int(((frame["registered"] > 0) & (frame["attendance_rows"] > 0)).sum())
        if not frame.empty
        else 0
    )

    return {
        "activities": int(len(frame)),
        "activities_with_registrations": sessions,
        "registered": registered,
        "cancelled_registrations": cancelled,
        "attendance_rows": attendance_rows,
        "present": present,
        "late": late,
        "absent": absent,
        "excused": excused,
        "walk_ins": walk_ins,
        # Conversion: attendance rows ÷ active registrations.
        "conversion_rate": rate(attendance_rows, registered),
        # Turnout: attended (present + late) ÷ active registrations.
        "turnout_rate": rate(present + late, registered),
        # Attendance rate: attended ÷ attendance rows.
        "attendance_rate": rate(present + late, attendance_rows),
        "session_coverage_rate": rate(sessions_with_attendance, sessions),
    }


def _by_type(frame: pd.DataFrame) -> list[dict]:
    """Per-activity-type participation. Blank types are labelled explicitly."""
    if frame.empty:
        return []
    work = frame.copy()
    work["activity_type"] = (
        work["activity_type"].fillna("").replace("", "(untyped)")
    )
    rows = []
    for activity_type, group in work.groupby("activity_type", sort=True):
        totals = _totals(group)
        rows.append(
            {
                "activity_type": activity_type,
                "activities": totals["activities"],
                "registered": totals["registered"],
                "attendance_rows": totals["attendance_rows"],
                "conversion_rate": totals["conversion_rate"],
                "attendance_rate": totals["attendance_rate"],
            }
        )
    # Largest participation first — a count ordering, not a quality ranking.
    rows.sort(key=lambda r: (-r["registered"], r["activity_type"]))
    return rows


def _monthly_trend(frame: pd.DataFrame) -> dict:
    """Participation per calendar month (counts only)."""
    if frame.empty:
        return {"labels": [], "registered": [], "attendance": []}
    work = frame.dropna(subset=["start"]).copy()
    if work.empty:
        return {"labels": [], "registered": [], "attendance": []}
    work["month"] = work["start"].dt.strftime("%Y-%m")
    grouped = (
        work.groupby("month")
        .agg(registered=("registered", "sum"), attendance=("attendance_rows", "sum"))
        .sort_index()
    )
    # Fill gaps so the axis is continuous (month-start dates, then %Y-%m labels).
    month_starts = pd.DatetimeIndex(
        pd.to_datetime(grouped.index + "-01", format="%Y-%m-%d")
    )
    continuous = pd.date_range(
        start=month_starts.min(), end=month_starts.max(), freq="MS"
    )
    grouped = grouped.reindex(continuous.strftime("%Y-%m"), fill_value=0)
    return {
        "labels": [str(label) for label in grouped.index],
        "registered": [int(v) for v in grouped["registered"].tolist()],
        "attendance": [int(v) for v in grouped["attendance"].tolist()],
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def filtered_activity_frame(filters: dict | None = None):
    """Load every row once and return ``(filtered_frame, ignored_messages)``.

    Shared so the Phase 9 CSV exports use exactly the same data and filtering
    as the Phase 8 page (no second implementation of the numbers).
    """
    filters = filters or {"activity_id": None, "academic_year": None, "errors": []}
    activities = _load_activities()
    frame = build_activity_frame(
        activities, _load_registrations(), _load_attendance()
    )
    return _apply_filters(frame, filters, activities)


def academic_years(activities: pd.DataFrame | None = None) -> list[str]:
    """School years that actually contain activities (newest first)."""
    if activities is None:
        activities = _load_activities()
    if activities.empty:
        return []
    years = [y for y in activities["academic_year"].dropna().unique().tolist()]
    return sorted(years, reverse=True)


def build_general_dashboard(filters: dict | None = None) -> dict:
    """Everything the Phase 8 page needs.

    Never raises on empty data: with no activities every frame is empty and
    every rate is ``None``.
    """
    filters = filters or {"activity_id": None, "academic_year": None, "errors": []}

    activities = _load_activities()
    registrations = _load_registrations()
    attendance = _load_attendance()

    frame = build_activity_frame(activities, registrations, attendance)
    filtered, ignored = _apply_filters(frame, filters, activities)

    all_years = academic_years(activities)
    activity_options = (
        activities[["activity_id", "title"]].to_dict("records")
        if not activities.empty
        else []
    )

    has_any = bool(len(activities))
    has_filtered = bool(len(filtered))

    # Row detail for the per-activity table, newest activity first.
    detail = []
    if has_filtered:
        ordered = filtered.sort_values(
            by=["start", "activity_id"], ascending=[False, False]
        )
        for row in ordered.itertuples(index=False):
            detail.append(
                {
                    "activity_id": int(row.activity_id),
                    "title": row.title,
                    "activity_type": row.activity_type or "(untyped)",
                    "status": row.status,
                    "start": row.start,
                    "academic_year": row.academic_year,
                    "registered": int(row.registered),
                    "cancelled": int(row.cancelled),
                    "attendance_rows": int(row.attendance_rows),
                    "walk_ins": int(row.walk_ins),
                    # Rates were computed once in build_activity_frame().
                    "conversion_rate": row.conversion,
                    "attendance_rate": row.attendance_rate,
                }
            )

    totals = _totals(filtered) if has_filtered else _totals(frame.iloc[0:0])

    # Organization academic years (free text) — displayed for context only.
    org_years = [
        y
        for (y,) in db.session.execute(
            db.select(Organization.academic_year)
            .where(Organization.academic_year.is_not(None))
            .order_by(Organization.id)
        ).all()
    ]
    record_count = db.session.execute(
        db.select(func.count(Organization.id))
    ).scalar() or 0

    return {
        "totals": totals,
        "detail": detail,
        "by_type": _by_type(filtered),
        "trend": _monthly_trend(filtered),
        "academic_years": all_years,
        "activity_options": activity_options,
        "applied": {
            "activity_id": filters.get("activity_id"),
            "academic_year": filters.get("academic_year"),
        },
        "filter_errors": list(filters.get("errors") or []) + ignored,
        "has_any_activities": has_any,
        "has_data": has_filtered,
        "organization_years": org_years,
        "organization_count": record_count,
        "generated_at": datetime.now(timezone.utc),
    }

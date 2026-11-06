"""Phase 9: Reports — CSV exports only (PDF stays blocked by T13).

Authorization (reuses the four confirmed roles; T19 stays frozen):
  * `/reports` and every export are STAFF-only (admin, officer, adviser),
    matching `MODULES["reports"]` in app/routes/main.py. Event Participants
    receive 403 and cannot export anything, including their own rows.
  * Participant emails/student IDs are only written for roles that already read
    them on the participant roster; the report service enforces that too, so a
    future role change cannot leak them by accident.

Validation: report key must exist (404 otherwise) and filters are parsed by the
report service — invalid values are ignored with a visible flash instead of
producing a misleading empty file.
"""
from flask import Blueprint, abort, flash, render_template, request
from flask_login import current_user, login_required

from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER
from app.services import report_service
from app.utils.decorators import role_required

bp = Blueprint("reports", __name__)

# Same set as MODULES["reports"] (adviser included; retrieval only, no changes).
_REPORT_ROLES = (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER)


@bp.route("/reports")
@login_required
@role_required(*_REPORT_ROLES)
def report_list():
    """Report catalogue with the same filters the exports accept."""
    return render_template(
        "reports/index.html",
        reports=report_service.REPORTS,
        activities=report_service.available_activities(),
        academic_years=report_service.available_academic_years(),
        selected_activity=request.args.get("activity_id", ""),
        selected_year=request.args.get("academic_year", ""),
    )


@bp.route("/reports/<report_key>.csv")
@login_required
@role_required(*_REPORT_ROLES)
def export_report(report_key: str):
    """Download one CSV report (filters optional, same rules as Phase 8)."""
    report = report_service.REPORTS.get(report_key)
    if report is None:
        abort(404)

    filters = report_service.resolve_filters(request.args)
    if filters.get("errors"):
        # Tell the user their filter was dropped, then export the full data.
        for message in filters["errors"]:
            flash(message, "error")

    builder = report["builder"]
    return builder(request.args, current_user.role_name)

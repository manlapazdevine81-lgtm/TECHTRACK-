"""Analytics blueprint — Phase 5 officer performance and Phase 8 general analytics.

Access reuses the EXISTING role rule for the analytics module
(`MODULES["analytics"]` in app/routes/main.py): System Administrator and
TechIS Adviser. TechIS Officers and Event Participants receive 403.

No scoring, ranking, or leaderboard is produced here: the dashboards render
counts, percentages, and timelines only.
"""
from flask import Blueprint, render_template, request

from flask_login import login_required
from app.models.user import ROLE_ADMIN, ROLE_ADVISER
from app.services.analytics_service import build_dashboard
from app.services.general_analytics_service import build_general_dashboard, parse_filters
from app.utils.decorators import role_required

bp = Blueprint("analytics", __name__)

_ANALYTICS_ROLES = (ROLE_ADMIN, ROLE_ADVISER)


@bp.route("/analytics")
@login_required
@role_required(*_ANALYTICS_ROLES)
def analytics_dashboard():
    """Render objective officer performance metrics.

    All calculations live in `app/services/analytics_service.py`; this view
    only shapes the response and reuses the existing project layout.
    """
    dashboard = build_dashboard()
    return render_template("analytics/dashboard.html", **dashboard)


@bp.route("/analytics/general")
@login_required
@role_required(*_ANALYTICS_ROLES)
def general_analytics():
    """Phase 8: attendance/participation KPIs, conversion and trends (Pandas).

    Filters come from the query string. `parse_filters` never raises: invalid
    values are dropped and reported so the page can say the filter was
    ignored instead of silently showing an empty result.
    """
    filters = parse_filters(request.args)
    dashboard = build_general_dashboard(filters)
    return render_template("analytics/general.html", **dashboard)

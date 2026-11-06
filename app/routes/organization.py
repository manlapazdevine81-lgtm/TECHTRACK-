"""Organization Structure blueprint — READ-ONLY display of TechIS positions.

Scope and guarantees
    * One page (`GET /organization`) shows the five fixed sections — Executive
      Board, Operations, Technology, Communications & Creatives, Community
      Development — with each position's name and its paraphrased duties.
    * There is NO create, edit, or delete route anywhere in this blueprint.
      Position data is seeded (`scripts/seed_organization.py`) and then read
      only, for every role including the System Administrator. Nothing here can
      change organizational information, so nothing here can be abused to
      escalate access.
    * Access reuses the four confirmed roles exactly as `MODULES["organization"]`
      always did: admin, officer, adviser read; participants get 403; anonymous
      visitors are sent to the login page.
    * The Constitution is a source for POSITION DESCRIPTIONS, never for
      permissions. No title shown here affects what a user may do (T19 frozen:
      `permission_level` is not modelled at all — see app/models/position.py).

Data source
    Positions are loaded from the `positions` table when the TechIS organization
    record exists. If no rows are present yet the page falls back to the
    constitution catalogue (`app/organizational_structure.py`), which is the same
    content the seeder writes — so the page is never blank, and it never shows
    invented duties.
"""
from flask import Blueprint, render_template, request

from flask_login import login_required

from app.extensions import db
from app.models.user import ROLE_ADMIN, ROLE_ADVISER, ROLE_OFFICER
from app.organizational_structure import (
    SECTIONS,
    all_positions,
    build_sections,
)
from app.utils.decorators import role_required

bp = Blueprint("organization", __name__)

# Same staff set as MODULES["organization"]: read-only for all three staff roles.
_STAFF = (ROLE_ADMIN, ROLE_OFFICER, ROLE_ADVISER)


def _escape_like(term: str) -> str:
    """Escape LIKE metacharacters so a search term is matched literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _positions_for_display(search: str = ""):
    """Load every stored position, projected for templates.

    Returns a list of ``{"title", "duties", "department"}`` dicts ordered by
    section order then `sort_order`. When the table is empty (or not yet
    created), the constitution catalogue is used instead.
    """
    from app.models.position import Position

    try:
        stmt = db.select(Position).order_by(
            Position.department.nullsfirst(),
            Position.sort_order.asc(),
            Position.id.asc(),
        )
        if search:
            like = f"%{_escape_like(search)}%"
            stmt = stmt.where(
                db.or_(
                    Position.title.ilike(like, escape="\\"),
                    Position.duties.ilike(like, escape="\\"),
                )
            )
        rows = db.session.execute(stmt).scalars().all()
    except Exception:  # pragma: no cover - table absent / DB unavailable
        db.session.rollback()
        rows = []

    if not rows and not search:
        return all_positions()

    return [row.as_display_dict() for row in rows]


def _sort_within_sections(sections: list[dict], positions: list[dict]) -> list[dict]:
    """Database order already respects `sort_order`; the catalogue is authored
    in display order. Preserve the incoming order per section."""
    ordered = {section["label"]: section for section in sections}
    grouped: dict[str, list] = {label: [] for label in ordered}
    for position in positions:
        label = position.get("department") or "Executive Board"
        if label in grouped:
            grouped[label].append(position)
    for label, section in ordered.items():
        section["positions"] = grouped[label]
        section["count"] = len(grouped[label])
    return sections


@bp.route("/organization")
@login_required
@role_required(*_STAFF)
def structure():
    """Show every section and position with its duties (search + filter)."""
    search = (request.args.get("q") or "").strip()
    selected = (request.args.get("department") or "").strip()
    if selected and selected not in SECTIONS:
        selected = ""  # unknown filter values degrade to "all sections"

    positions = _positions_for_display(search)
    sections = build_sections(positions, search="", department_filter=selected)
    sections = _sort_within_sections(sections, positions)

    total = sum(section["count"] for section in sections)
    return render_template(
        "organization/structure.html",
        sections=sections,
        section_names=SECTIONS,
        search=search,
        selected_department=selected,
        total_positions=total,
        has_results=total > 0,
    )

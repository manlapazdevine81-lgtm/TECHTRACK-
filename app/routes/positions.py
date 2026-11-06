"""Organizational position assignment — System Administrator only.

These routes let an administrator record which organizational position a member
currently holds. They are strictly separate from system roles:

  * The SYSTEM role (`users.role_id`) is untouched here. Assigning "Chief
    Technology Officer" changes nothing about what the member may access
    (T19 frozen: positions confer no permissions).
  * Only accounts with a staff role (admin / officer) are eligible, because the
    organization's positions are officer positions. The check is role-based, as
    everywhere else in this project.
  * Ending a term never deletes it: the row is kept as history.

Every route is POST-only apart from the assignment page itself, and every route
is guarded by `@role_required(ROLE_ADMIN)` server-side.
"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models.position import Position
from app.models.user import ROLE_ADMIN, ROLE_OFFICER, User
from app.services import position_service
from app.utils.decorators import role_required

bp = Blueprint("positions", __name__)

# Roles that may HOLD an organizational position. System Administrators are
# included because they also sit on the Executive Board (e.g. as CEO).
_ELIGIBLE_ROLES = (ROLE_ADMIN, ROLE_OFFICER)


@bp.route("/admin/users/<int:user_id>/position", methods=["GET", "POST"])
@login_required
@role_required(ROLE_ADMIN)
def assign(user_id: int):
    """Assign (or replace) a member's organizational position."""
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    positions = position_service.available_positions()
    history = position_service.term_history(user.id)
    current = position_service.active_term_for(user.id)

    if request.method == "POST":
        if user.role_name not in _ELIGIBLE_ROLES:
            flash(
                "Organizational positions can only be assigned to System "
                "Administrators and TechIS Officers.",
                "error",
            )
            return redirect(url_for("positions.assign", user_id=user.id))

        raw_position = (request.form.get("position_id") or "").strip()
        if not raw_position.isdigit():
            flash("Select a position to assign, or use End term.", "error")
            return redirect(url_for("positions.assign", user_id=user.id))

        position = db.session.get(Position, int(raw_position))
        if position is None:
            flash("That position could not be found.", "error")
            return redirect(url_for("positions.assign", user_id=user.id))

        position_service.assign_position(user, position)
        flash(
            f"{user.full_name} is now recorded as {position.title}.",
            "success",
        )
        return redirect(url_for("positions.assign", user_id=user.id))

    return render_template(
        "admin/assign_position.html",
        member=user,
        positions=positions,
        current=current,
        history=history,
        is_eligible=user.role_name in _ELIGIBLE_ROLES,
        eligible_roles=_ELIGIBLE_ROLES,
    )


@bp.route("/admin/users/<int:user_id>/position/end", methods=["POST"])
@login_required
@role_required(ROLE_ADMIN)
def end(user_id: int):
    """End the member's current position term (history is preserved)."""
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    ended = position_service.end_active_term(user)
    if ended is None:
        flash(f"{user.full_name} has no active position to end.", "error")
    else:
        title = ended.position.title if ended.position else "their position"
        flash(f"{user.full_name}'s term as {title} has ended.", "success")
    return redirect(url_for("positions.assign", user_id=user.id))

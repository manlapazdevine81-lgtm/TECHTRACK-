"""Organizational position assignment (officer_terms) — business logic.

All reads/writes of `officer_terms` go through here so that the rule for
"currently held position" is defined exactly once.

Authorization note
------------------
Nothing in this module touches `users.role_id` or any permission check. An
officer term is organizational metadata; assigning or ending one can never
grant or revoke system access (T19 frozen). The routes that call these helpers
enforce the System Administrator role themselves.
"""
from datetime import datetime, timezone

from app.extensions import db
from app.models.officer_term import OfficerTerm
from app.models.position import Position


def today():
    return datetime.now(timezone.utc).date()


def active_term_for(user_id: int) -> OfficerTerm | None:
    """The user's currently held term, or None.

    If somehow more than one active term exists (should not happen — the
    assignment helper closes the previous one), the most recent start wins.
    """
    return db.session.execute(
        db.select(OfficerTerm)
        .where(
            OfficerTerm.user_id == user_id,
            OfficerTerm.status.in_(OfficerTerm.ACTIVE_STATUSES),
        )
        .order_by(OfficerTerm.start_date.desc(), OfficerTerm.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def active_position_label(user_id: int) -> str | None:
    """The title of the user's current position, or None when unassigned."""
    term = active_term_for(user_id)
    if term is None or term.position is None:
        return None
    return term.position.title


def active_labels_by_user(user_ids: list[int]) -> dict[int, str]:
    """Map user id -> current position title, for the given users only.

    One query (no N+1) so the activities dropdown stays cheap regardless of how
    many officers exist. Users without an active term are simply absent.
    """
    if not user_ids:
        return {}
    rows = db.session.execute(
        db.select(OfficerTerm.user_id, Position.title)
        .join(Position, Position.id == OfficerTerm.position_id)
        .where(
            OfficerTerm.user_id.in_(user_ids),
            OfficerTerm.status.in_(OfficerTerm.ACTIVE_STATUSES),
        )
        .order_by(OfficerTerm.start_date.asc(), OfficerTerm.id.asc())
    ).all()
    # Later (most recent) rows overwrite earlier ones.
    return {user_id: title for user_id, title in rows}


def assign_position(user, position: Position, start: "date | None" = None) -> OfficerTerm:
    """Give `user` `position`, ending whatever they held before.

    A user holds at most ONE position at a time: the previous active term is
    closed (status=ended, end_date stamped) rather than deleted, so the history
    remains intact.
    """
    start_date = start or today()

    previous = active_term_for(user.id)
    if previous is not None:
        if previous.position_id == position.id:
            return previous  # already holds exactly this position
        previous.end(start_date)

    term = OfficerTerm(
        user_id=user.id,
        position_id=position.id,
        start_date=start_date,
        end_date=None,
        status="active",
    )
    db.session.add(term)
    db.session.commit()
    return term


def end_active_term(user, on: "date | None" = None) -> OfficerTerm | None:
    """End whatever position `user` currently holds. Returns the closed term.

    No row is deleted; the term becomes historical.
    """
    term = active_term_for(user.id)
    if term is None:
        return None
    term.end(on or today())
    db.session.commit()
    return term


def term_history(user_id: int) -> list[OfficerTerm]:
    """All terms for a user, newest first (active and ended)."""
    return list(
        db.session.execute(
            db.select(OfficerTerm)
            .where(OfficerTerm.user_id == user_id)
            .order_by(OfficerTerm.start_date.desc(), OfficerTerm.id.desc())
        )
        .scalars()
        .all()
    )


def available_positions() -> list[Position]:
    """Positions a user may be assigned to, in display order."""
    return list(
        db.session.execute(
            db.select(Position).order_by(
                Position.department.nullsfirst(), Position.sort_order, Position.id
            )
        )
        .scalars()
        .all()
    )

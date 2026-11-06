"""One-time initialization of the TechIS organization record (Phase 4C).

Confirmed decisions:
    name           = "Tech Innovators Society"
    academic_year  = "2026-2027"
    adviser        = adviser@techis.demo, ONLY if that account already exists and
                     its role is exactly `techis_adviser` (ROLE_ADVISER).
                     Otherwise adviser_id stays NULL with an informational message.

Idempotent and non-destructive by design:
  * Organizations are looked up by NAME first.
  * Exactly one match  -> report it and change NOTHING (no overwrite of name,
    academic year, adviser, or any other field).
  * More than one match -> print a clear error, make NO changes, exit non-zero.
  * No match           -> create one Organization and commit; roll back on error.

This script never creates users or roles, never runs `seed_demo.py`, never
deletes or edits existing organizations or records, and never creates
organizational records.

DATABASE SAFETY (Phase 11 follow-up):
Not destructive, but it targets whatever `DATABASE_URL` selects — i.e. the
development database (`techis_dev`) by default — and its first statement is
`db.create_all()`. It therefore PRINTS the real database name (from
`SELECT current_database()`) before doing anything, and refuses to run at all
unless `--allow-create-all` is passed explicitly. It is safe to point at
`techis_dev`: when an organization with the same name exists it changes
nothing (see the rules above).

Run from the project root (NOT executed as part of this step):
.\\.venv\\Scripts\\python.exe scripts\\seed_organization.py            # dry run
.\\.venv\\Scripts\\python.exe scripts\\seed_organization.py --allow-create-all
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db
from app.models.organization import Organization
from app.models.user import ROLE_ADVISER, Role, User

ORGANIZATION_NAME = "Tech Innovators Society"
ACADEMIC_YEAR = "2026-2027"
ADVISER_EMAIL = "adviser@techis.demo"

EXIT_MULTIPLE_MATCHES = 2
EXIT_COMMIT_FAILED = 3


def _resolve_adviser_id() -> int | None:
    """Return the adviser's user id only when the account exists AND is an adviser.

    No account is created or modified. Any mismatch is reported, not "fixed".
    """
    user = User.query.filter_by(email=ADVISER_EMAIL).first()
    if user is None:
        print(
            f"info   : no account found for {ADVISER_EMAIL} — "
            "the organization will be created with adviser_id = None."
        )
        return None

    role_name = user.role_name
    if role_name != ROLE_ADVISER:
        print(
            f"info   : {ADVISER_EMAIL} exists but its role is "
            f"{role_name or 'unknown'!r}, not {ROLE_ADVISER!r} — "
            "the organization will be created with adviser_id = None."
        )
        return None

    print(f"info   : adviser account found ({ADVISER_EMAIL}, role {role_name}) — "
          f"adviser_id = {user.id}.")
    return user.id


def _server_database(app) -> str:
    """The database this connection is actually in, as reported by PostgreSQL."""
    from sqlalchemy import text

    with app.app_context():
        with db.engine.connect() as connection:
            return connection.execute(text("SELECT current_database()")).scalar()


def _seed_positions(org) -> int:
    """Insert the catalogue positions that are not stored yet.

    Idempotent by design: a position is matched on (organization_id, title) and
    skipped when present, so existing rows are never duplicated or overwritten.
    Duties come from `app/organizational_structure.py` (paraphrased from the
    TechIS Constitution); nothing is invented here.
    """
    from app.models.position import Position
    from app.organizational_structure import all_positions

    existing = {
        p.title for p in Position.query.filter_by(organization_id=org.id).all()
    }
    created = skipped = 0

    for order, entry in enumerate(all_positions()):
        if entry["title"] in existing:
            skipped += 1
            continue
        db.session.add(
            Position(
                organization_id=org.id,
                title=entry["title"],
                department=entry["department"],
                duties="\n".join(entry["duties"]),
                sort_order=order,
            )
        )
        created += 1

    if not created:
        print(f"exists : all {skipped} positions already present — nothing to do.")
        return 0

    try:
        db.session.commit()
    except Exception as exc:  # noqa: BLE001 - report, roll back, never partial-write
        db.session.rollback()
        print(f"error  : position commit failed — {type(exc).__name__}: {exc}")
        print("error  : transaction rolled back; no positions were created.")
        return EXIT_COMMIT_FAILED

    print(f"seeded : {created} position(s) created, {skipped} already present.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-create-all",
        action="store_true",
        help="Permit db.create_all() (creates MISSING tables only; never drops).",
    )
    args = parser.parse_args(argv)

    app = create_app()

    # Print the real target so nobody has to guess which database this touches.
    print(f"target : database {_server_database(app)!r} (server-reported)")

    if not args.allow_create_all:
        print(
            "refused: this script runs db.create_all() before reading anything.\n"
            "         Re-run with --allow-create-all to confirm the target above."
        )
        return 4

    with app.app_context():
        # Only ensure the schema EXISTS; never destructive. Roles are read-only
        # here — this script does not create roles.
        db.create_all()

        existing_roles = {r.name for r in Role.query.all()}
        if ROLE_ADVISER not in existing_roles:
            print(
                f"warn   : role {ROLE_ADVISER!r} is not present in this database; "
                "adviser eligibility cannot be satisfied."
            )

        matches = Organization.query.filter_by(name=ORGANIZATION_NAME).all()

        if len(matches) > 1:
            print(
                f"error  : found {len(matches)} organizations named "
                f"{ORGANIZATION_NAME!r} (ids: {', '.join(str(o.id) for o in matches)})."
            )
            print("error  : refusing to continue — no changes were made.")
            print("         Resolve the duplicates manually, then re-run this script.")
            return EXIT_MULTIPLE_MATCHES

        if len(matches) == 1:
            org = matches[0]
            print(f"exists : organization '{org.name}' already present (id={org.id}).")
            print(f"         academic_year = {org.academic_year!r}")
            print(f"         adviser_id    = {org.adviser_id!r}")
            print("         No changes were made (existing data is never overwritten).")
            # Organization untouched, but positions may still be missing — seed
            # them idempotently (existing titles are skipped, never rewritten).
            return _seed_positions(org)

        # No match -> would create one.
        adviser_id = _resolve_adviser_id()

        print("plan   : would create ONE organization:")
        print(f"         name          = {ORGANIZATION_NAME!r}")
        print(f"         academic_year = {ACADEMIC_YEAR!r}")
        print(f"         adviser_id    = {adviser_id!r}")

        org = Organization(
            name=ORGANIZATION_NAME,
            academic_year=ACADEMIC_YEAR,
            adviser_id=adviser_id,
        )
        db.session.add(org)
        try:
            db.session.commit()
        except Exception as exc:  # noqa: BLE001 — report, roll back, never leave a partial write
            db.session.rollback()
            print(f"error  : commit failed — {type(exc).__name__}: {exc}")
            print("error  : transaction rolled back; no organization was created.")
            return EXIT_COMMIT_FAILED

        print(f"seeded : organization '{org.name}' created (id={org.id}).")
        return _seed_positions(org)


if __name__ == "__main__":
    raise SystemExit(main())

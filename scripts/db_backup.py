"""Timestamped PostgreSQL backup of ONE database, identified by the SERVER.

    .\\.venv\\Scripts\\python.exe scripts\\db_backup.py                      # default: techis_dev
    .\\.venv\\Scripts\\python.exe scripts\\db_backup.py --verify backups\\x.dump

Why this exists
---------------
`pg_dump` is not installed on this machine, so the backup is produced from inside
the application's own connection. That has two consequences, both handled here:

  * The target is chosen by asking the SERVER (`SELECT current_database()`), not
    by parsing DATABASE_URL. A guard refuses to write a backup for any database
    other than the one explicitly requested.
  * A custom-format dump is NOT hand-rolled: every table is read once in a
    consistent snapshot (`REPEATABLE READ`) and written to a ZIP archive of
    per-table UTF-8 CSV files, plus a JSON/SQL manifest. It is a data +
    structure description backup, adequate for disaster recovery of this
    project's scale — NOT a substitute for `pg_dump`.

No credentials are printed. No database is modified: the session is READ ONLY
during the copy.
"""
import argparse
import csv
import io
import json
import pathlib
import sys
import zipfile
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

DEFAULT_DATABASE = "techis_dev"
BACKUP_DIR = ROOT / "backups"


def server_database(app) -> tuple[str, str]:
    with app.app_context():
        with db.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT current_database(), "
                    "       coalesce(inet_server_addr()::text, 'local')"
                )
            ).one()
    return row[0], row[1]


def _tables(connection) -> tuple[list, list]:
    tables = [
        r[0]
        for r in connection.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
        ).all()
    ]
    views = [
        r[0]
        for r in connection.execute(
            text(
                "SELECT viewname FROM pg_views "
                "WHERE schemaname = 'public' ORDER BY viewname"
            )
        ).all()
    ]
    return tables, views


def _ddl(connection, tables, views) -> str:
    """Column/type/nullability description, so the structure is recoverable."""
    parts = ["-- Structure description (columns only; no data) --"]
    for table in tables:
        cols = connection.execute(
            text(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t "
                "ORDER BY ordinal_position"
            ),
            {"t": table},
        ).all()
        parts.append(f"\n-- TABLE {table}")
        for name, dtype, nullable, default in cols:
            parts.append(
                f"--   {name} {dtype} "
                f"{'NULL' if nullable == 'YES' else 'NOT NULL'}"
                f"{f' DEFAULT {default}' if default else ''}".rstrip()
            )
        idx = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = :t"
            ),
            {"t": table},
        ).scalars().all()
        for d in idx:
            parts.append(f"--   {d};")
    if views:
        parts.append("\n-- VIEWS: " + ", ".join(views))
    return "\n".join(parts) + "\n"


def create_backup(database: str) -> pathlib.Path:
    """Back up `database` after confirming the SERVER agrees it is the target."""
    app = create_app()
    actual, host = server_database(app)

    print(f"requested database : {database}")
    print(f"server-reported    : {actual} @ {host}")
    if actual != database:
        print(
            f"REFUSED: connected database is {actual!r}, not {database!r}. "
            "No backup was written.",
            file=sys.stderr,
        )
        raise SystemExit(3)

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = BACKUP_DIR / f"{actual}_{stamp}.backup.zip"

    with app.app_context():
        # SQLAlchemy 2.x autobegins a transaction; commit it first so the explicit
        # isolation-level BEGIN below is not rejected as a nested transaction.
        db.session.rollback()
        connection = db.engine.connect()
        try:
            # A single consistent snapshot: nothing changes between tables.
            connection.exec_driver_sql("BEGIN ISOLATION LEVEL REPEATABLE READ")
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")

            tables, views = _tables(connection)
            counts = {}
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                for table in tables:
                    buffer = io.StringIO()
                    writer = csv.writer(buffer, lineterminator="\n")
                    result = connection.exec_driver_sql(
                        f'SELECT * FROM "{table}"'
                    )
                    columns = list(result.keys())
                    writer.writerow(columns)
                    n = 0
                    for row in result:
                        writer.writerow(["" if v is None else v for v in row])
                        n += 1
                    archive.writestr(f"data/{table}.csv", buffer.getvalue())
                    counts[table] = n

                structure = _ddl(connection, tables, views)
                archive.writestr("structure.sql", structure)
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "database": actual,
                            "host": host,
                            "created_at_utc": stamp,
                            "tables": tables,
                            "views": views,
                            "row_counts": counts,
                            "note": (
                                "Data snapshot (per-table CSV) + structure description. "
                                "Produced without pg_dump; not a custom-format dump."
                            ),
                        },
                        indent=2,
                    ),
                )
            connection.exec_driver_sql("ROLLBACK")
        finally:
            connection.close()

    # ---- verify the artefact ----
    with zipfile.ZipFile(target) as archive:
        bad = archive.testzip()
        if bad is not None:
            print(f"REFUSED: archive is corrupt at {bad}", file=sys.stderr)
            raise SystemExit(5)
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))

    size = target.stat().st_size
    print(f"backup written     : {target}")
    print(f"size               : {size:,} bytes")
    print(f"entries            : {len(names)} ({len(manifest['tables'])} tables)")
    print("row counts         :")
    for table in manifest["tables"]:
        print(f"    {table:28s} {manifest['row_counts'][table]:>6}")
    return target


def verify_backup(path: pathlib.Path) -> int:
    """Re-open the archive and check it is structurally complete.

    For each table: the CSV must exist, its first line must be a non-empty header,
    and it must hold exactly the number of data rows the manifest recorded.
    """
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        manifest = json.loads(archive.read("manifest.json"))
        problems = []
        for table in manifest["tables"]:
            name = f"data/{table}.csv"
            if name not in archive.namelist():
                problems.append(f"{table}: missing entry")
                continue
            lines = archive.read(name).decode("utf-8").splitlines()
            if not lines or not lines[0].strip():
                problems.append(f"{table}: empty header")
                continue
            data_rows = len(lines) - 1
            if data_rows != manifest["row_counts"].get(table):
                problems.append(
                    f"{table}: {data_rows} rows, manifest says "
                    f"{manifest['row_counts'].get(table)}"
                )
        if "structure.sql" not in archive.namelist():
            problems.append("structure.sql: missing")

    print(f"archive integrity : {'OK' if bad is None else f'CORRUPT ({bad})'}")
    print(f"database          : {manifest['database']}")
    print(f"created at        : {manifest['created_at_utc']}")
    print(f"tables            : {len(manifest['tables'])}")
    print(f"row-count match   : {'OK' if not problems else problems}")
    return 0 if bad is None and not problems else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--verify", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)

    # This tool backs up the development database only. System databases and
    # anything named like a test database are refused outright.
    if args.database != DEFAULT_DATABASE:
        print(
            f"REFUSED: this tool backs up {DEFAULT_DATABASE!r} only "
            f"(got {args.database!r}).",
            file=sys.stderr,
        )
        return 3

    if args.verify:
        return verify_backup(args.verify)

    create_backup(args.database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

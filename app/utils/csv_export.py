"""CSV export utilities with spreadsheet formula-injection protection (Phase 3C).

Pure module — no database or schema dependency. Used by authorized report
exports (activities, registrations, attendance). Every exported cell passes
through sanitize_cell(), which neutralizes spreadsheet formula prefixes
(=, +, -, @, TAB, CR per OWASP) in user-controlled text so values such as
'=HYPERLINK(...)' are rendered as inert text in Excel/LibreOffice.

Numeric values (int/float) are written as-is; only strings are treated as
formula-capable. CSV quoting/escaping is handled by the stdlib csv module
(so embedded commas, quotes and newlines cannot break the file structure),
and a UTF-8 BOM is prepended so Excel detects the encoding correctly.
"""
import csv
import io
import re
from typing import Iterable, Sequence

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(value) -> str:
    """Neutralize spreadsheet formula injection in one cell value."""
    if value is None:
        return ""
    if isinstance(value, bool):  # bool is an int subclass; render explicitly
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return str(value)  # numbers cannot execute formulas
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text  # leading apostrophe makes it literal text
    return text


def sanitize_filename(filename: str) -> str:
    """Strip path segments, quotes and control chars from a download name."""
    base = (filename or "").replace("\\", "/").split("/")[-1]
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._") or "export"
    if not safe.lower().endswith(".csv"):
        safe += ".csv"
    return safe


def build_csv(headers: Sequence[str], rows: Iterable[Sequence]) -> str:
    """Return CSV text (with UTF-8 BOM, CRLF rows) from headers + row data."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([sanitize_cell(h) for h in headers])
    for row in rows:
        writer.writerow([sanitize_cell(cell) for cell in row])
    return "\ufeff" + buffer.getvalue()


def csv_response(headers: Sequence[str], rows: Iterable[Sequence], filename: str):
    """Build a Flask Response that downloads the data as a CSV attachment."""
    from flask import Response

    safe_name = sanitize_filename(filename)
    response = Response(build_csv(headers, rows), mimetype="text/csv")
    # safe_name is fully sanitized (no quotes/control chars) — header-safe.
    response.headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

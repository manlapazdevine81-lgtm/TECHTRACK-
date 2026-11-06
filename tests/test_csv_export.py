"""Tests for the CSV export utility — formula-injection protection included.

Pure unit tests: no database, no network, no email.
"""
from app.utils.csv_export import (
    build_csv,
    csv_response,
    sanitize_cell,
    sanitize_filename,
)


# ---------- Formula-injection sanitization ----------

def test_sanitize_none_and_numbers_pass_through():
    assert sanitize_cell(None) == ""
    assert sanitize_cell(5) == "5"
    assert sanitize_cell(-5) == "-5"          # negative numbers stay numeric
    assert sanitize_cell(1.5) == "1.5"
    assert sanitize_cell(True) == "True"


def test_sanitize_plain_text_unchanged():
    assert sanitize_cell("Juan Dela Cruz") == "Juan Dela Cruz"
    assert sanitize_cell("  spaced  ") == "  spaced  "
    assert sanitize_cell("name@example.com") == "name@example.com"
    assert sanitize_cell("2026-10-20 09:00") == "2026-10-20 09:00"


def test_sanitize_neutralizes_formula_prefixes():
    """OWASP: =, +, -, @, TAB, CR must be prefixed with an apostrophe."""
    assert sanitize_cell("=1+1") == "'=1+1"
    assert sanitize_cell("=HYPERLINK(\"http://evil\",\"click\")").startswith("'=")
    assert sanitize_cell("+cmd|'/C calc'!A0") == "'+cmd|'/C calc'!A0"
    assert sanitize_cell("-2+3") == "'-2+3"
    assert sanitize_cell("@SUM(A1:A9)") == "'@SUM(A1:A9)"
    assert sanitize_cell("\tTAB") == "'\tTAB"
    assert sanitize_cell("\rCR") == "'\rCR"


# ---------- Filename sanitization ----------

def test_sanitize_filename_strips_paths_and_quotes():
    assert sanitize_filename("report.csv") == "report.csv"
    assert sanitize_filename("no_extension") == "no_extension.csv"
    assert sanitize_filename("../../etc/passwd") == "passwd.csv"
    assert sanitize_filename('evil"name\r\n.csv') == "evil_name__.csv"
    assert sanitize_filename("") == "export.csv"


# ---------- CSV building ----------

def test_build_csv_bom_headers_and_crlf():
    out = build_csv(["Name", "Email"], [["Juan", "juan@x.demo"]])
    assert out.startswith("\ufeff")           # Excel-friendly BOM
    assert "\r\n" in out                      # RFC-style line endings
    assert "Name,Email" in out
    assert "Juan,juan@x.demo" in out


def test_build_csv_escapes_commas_and_quotes():
    out = build_csv(["Note"], [["a,b", ], ['say "hi"']])
    assert '"a,b"' in out                     # embedded comma -> quoted cell
    assert '"say ""hi"""' in out              # embedded quote -> doubled


def test_build_csv_sanitizes_every_cell():
    out = build_csv(["=EVIL"], [["=1+2"], ["normal"]])
    assert '"\'=EVIL"' in out or "'=EVIL" in out
    assert "'=1+2" in out
    assert "normal" in out


def test_build_csv_empty_rows():
    out = build_csv(["A", "B"], [])
    assert out.startswith("\ufeff")
    assert "A,B" in out
    assert out.count("\r\n") == 1             # header only


# ---------- Flask response ----------

def test_csv_response_headers_and_content():
    resp = csv_response(
        ["Member", "Status"],
        [["Juan", "=EVIL"], ["Maria", "Active"]],
        "members.csv",
    )
    assert resp.mimetype == "text/csv"
    assert resp.headers["Content-Disposition"] == 'attachment; filename="members.csv"'
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    data = resp.get_data(as_text=True)
    assert data.startswith("\ufeff")
    assert "'=EVIL" in data                   # injection neutralized in payload


def test_csv_response_sanitizes_malicious_filename():
    resp = csv_response(["A"], [["x"]], '../evil"name\r\n.csv')
    disposition = resp.headers["Content-Disposition"]
    assert "../" not in disposition
    assert '"' not in disposition.split("filename=\"")[1].rstrip('"')
    assert disposition.endswith('.csv"')

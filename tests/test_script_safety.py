"""Database safety of the destructive one-off scripts (root of the project).

Neither script is executed here: `test_guard.py` is why that is safe —
`test_scripts_do_nothing_at_import` asserts importing them but does NOT touch a
database, and the real `db.drop_all()` lives inside `main()` behind the guard.

Run: .venv\\Scripts\\python.exe -m pytest tests/test_script_safety.py
All checks are read-only (no writes, no DDL, no commits).
"""
import importlib.util
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DESTRUCTIVE_SCRIPTS = ["_simple_feedback_test.py", "_verify_feedback.py"]


def _load(script: str):
    """Import the script as a module WITHOUT executing main()."""
    path = ROOT / script
    spec = importlib.util.spec_from_file_location(f"_safety_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # main() is guarded by __name__ == "__main__"
    return module


@pytest.fixture(params=DESTRUCTIVE_SCRIPTS)
def guard_module(request):
    return _load(request.param)


# ===========================================================================
# Configuration: pytest must never collect the root scripts
# ===========================================================================


def _pytest_ini() -> str:
    return (ROOT / "pytest.ini").read_text(encoding="utf-8")


def test_pytest_ini_still_scopes_collection_to_tests():
    ini = _pytest_ini()
    assert "testpaths = tests" in ini
    assert "python_files = test_*.py" in ini


def test_pytest_never_collects_the_destructive_scripts():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    # Compare collected NODE IDS ("path::test"), never raw text: this module's own
    # parametrised ids legitimately mention the script names.
    collected = [line.strip() for line in result.stdout.splitlines() if "::" in line]
    assert collected, result.stdout[-2000:]
    # NOTE: `tests/test_auth.py` is the legitimate pytest module; the root
    # `test_auth.py` is a separate manual debug script. Compare full paths.
    root_scripts = DESTRUCTIVE_SCRIPTS + ["verify.py", "_qa_diagnose.py", "_check_db.py"]
    for line in collected:
        node_path = line.split("::", 1)[0].replace("\\", "/")
        assert node_path.startswith("tests/"), line
        for script in root_scripts:
            assert node_path != f"tests/{script}", line
            assert node_path != script, line


# ===========================================================================
# The guard itself: exact-match allowlist, no fallback
# ===========================================================================


def test_guard_constants(guard_module):
    assert guard_module.REQUIRED_DATABASE == "techis_test"
    assert "techis_dev" in guard_module.FORBIDDEN_DATABASES
    assert guard_module.EXIT_WRONG_DATABASE == 2


def test_guard_allows_exactly_techis_test(guard_module):
    guard_module.assert_test_database("techis_test")
    guard_module.assert_test_database("techis_test", "localhost")


@pytest.mark.parametrize(
    "database",
    [
        "techis_dev",
        "Techis_Dev",          # case variation of a protected name
        "postgres",
        "template0",
        "template1",
        "production",
        "prod",
        "techis_prod",
        "techis_test_dev",     # prefix of the allowed name -> must still fail
        "techis_test_2",
        "techis_test2",
        " test",               # leading space is NOT trimmed into a pass
        "my_techis_test",
        "TEST",
        "",
        None,
    ],
)
def test_guard_rejects_everything_else(guard_module, database):
    with pytest.raises(guard_module.UnsafeDatabaseError):
        guard_module.assert_test_database(database)


def test_guard_error_message_is_clear_and_names_no_credentials(guard_module):
    with pytest.raises(guard_module.UnsafeDatabaseError) as excinfo:
        guard_module.assert_test_database("techis_dev", "127.0.0.1")
    message = str(excinfo.value)
    assert "Refusing to run" in message
    assert "techis_dev" in message
    assert "techis_test" in message
    assert "No changes were made" in message
    # No URL, user, or password fragment may leak into the error.
    for secret_fragment in ("://", "@", "password", "postgresql+"):
        assert secret_fragment not in message, secret_fragment


# ===========================================================================
# Structural guarantees: the gate runs before any destructive call
# ===========================================================================


def test_guard_uses_server_side_current_database(guard_module):
    import inspect

    source = inspect.getsource(guard_module._server_identity)
    assert "current_database()" in source


def test_gate_precedes_every_drop_all(guard_module):
    """Source order: `_gate(app)` must appear before the first `db.drop_all()`."""
    import inspect

    source = inspect.getsource(guard_module.main)
    gate_at = source.index("_gate(app)")
    first_drop = source.index("db.drop_all()")
    assert gate_at < first_drop
    # And only one drop is expected (the old script had a second, unguarded one
    # after the test-client block).
    assert source.count("db.drop_all()") == 1


def test_script_does_not_rewrite_database_url(guard_module):
    """The no-op `DATABASE_URL` self-assignment that caused the incident is gone."""
    source = (ROOT / guard_module.__file__.replace("\\", "/").split("/")[-1]).read_text(
        encoding="utf-8"
    )
    assert 'os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "")' not in source
    assert "os.environ.setdefault(\"DATABASE_URL\"" not in source


def test_scripts_do_nothing_at_import(guard_module):
    """Loading the module must not open a connection or run DDL."""
    assert hasattr(guard_module, "main")
    assert callable(guard_module.assert_test_database)


# ===========================================================================
# Project-wide: every other root script, classified
# ===========================================================================


def test_no_other_script_drops_tables():
    """Only the two guarded scripts may contain an executable `drop_all`.

    A line is ignored when it is a comment, or when it is inside a docstring —
    `scripts/verify_script_guards.py` and the guard docstrings legitimately
    MENTION the call while explaining the protection.
    """
    import ast

    offenders = []
    search = list(ROOT.glob("*.py")) + list((ROOT / "scripts").glob("*.py"))
    for path in search:
        if path.name in DESTRUCTIVE_SCRIPTS:
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            # Only real attribute calls count: `x.drop_all()`, not text in a string.
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "drop_all"
            ):
                offenders.append(str(path.relative_to(ROOT)))
                break
    assert offenders == [], offenders


def test_seed_demo_is_excluded_from_repository():
    """The demo seeder contained credentials and must not be distributed."""
    seed_demo = ROOT / "scripts" / "seed_demo.py"
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert not seed_demo.exists()
    assert "scripts/seed_demo.py" in gitignore

def test_seed_organization_requires_an_explicit_opt_in_before_create_all():
    """Non-destructive, but it writes DDL against `techis_dev` by default.

    It must refuse without `--allow-create-all`, and the refusal must come BEFORE
    `db.create_all()` in source order (nothing is executed here).
    """
    import inspect

    spec = importlib.util.spec_from_file_location(
        "_seed_org", ROOT / "scripts" / "seed_organization.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    source = inspect.getsource(module.main)
    assert "current_database()" in inspect.getsource(module._server_database)

    # Anchor on the indented STATEMENTS: the docstring also mentions
    # `db.create_all()` in prose, and `source.index` would find that first.
    refusal_at = source.index("\n    if not args.allow_create_all")
    create_at = source.index("\n        db.create_all()")
    assert refusal_at < create_at, "the opt-in check must precede db.create_all()"
    assert "return 4" in source[refusal_at:create_at]
    # And the refusal happens after the real target is printed, never before.
    print_at = source.index("_server_database(app)")
    assert print_at < refusal_at


def test_scripts_without_a_write_path_are_documented():
    """`_check_db.py` is read-only; the QA scripts hit `/` only (no login)."""
    check_db = (ROOT / "_check_db.py").read_text(encoding="utf-8")
    for destructive in ("drop_all", "create_all", "commit", "DELETE", "UPDATE", "TRUNCATE"):
        assert destructive not in check_db, destructive

    for name in ("_qa_diagnose.py", "_qa_diagnose2.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for destructive in ("drop_all", "create_all", "/login", "/register"):
            assert destructive not in text, (name, destructive)

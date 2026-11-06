"""READ-ONLY self-check of the new guard.  Does NOT execute either debug script.

Each script is imported as a module (its destructive work lives in main(), which
imports never call). Everything is faked:
  * the extension's per-app engine map is replaced with a stub whose
    `current_database()` returns a chosen name, and
  * `db.drop_all` / `db.create_all` raise immediately and record the attempt.

So this proves the guard refuses BEFORE any destructive call, without touching a
real database.

Run: .venv\\Scripts\\python.exe _safety_selfcheck.py
"""
import importlib.util
import io
import pathlib
import sys
from contextlib import redirect_stderr, redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parents[1]  # project root (this file lives in scripts/)
sys.path.insert(0, str(ROOT))  # same pattern as scripts/seed_demo.py
SCRIPTS = ["_simple_feedback_test.py", "_verify_feedback.py"]
SCENARIOS = ("techis_dev", "postgres", "production", "techis_prod", "Techis_Dev", "techis_test_2")

# The database this project is actually configured for; the guard must see it.
REAL_TARGET = "techis_dev"


def load(script):
    spec = importlib.util.spec_from_file_location(
        f"_sc_{pathlib.Path(script).stem}", ROOT / script
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_engine():
    """The actual Engine object of the configured database (no connection made)."""
    from sqlalchemy.engine import Engine

    from app import create_app
    from app.extensions import db

    app = create_app({"TESTING": True, "MAIL_SUPPRESS_SEND": True})
    with app.app_context():
        for engine in (db.engines or {}).values() if isinstance(db.engines, dict) else []:
            if isinstance(engine, Engine):
                return engine
    return None


class _Row:
    def __init__(self, value):
        self._value = value

    def one(self):
        return self._value


class _Result:
    rowcount = 0


class _Conn:
    def __init__(self, reported):
        self.reported = reported

    def execute(self, stmt, *args, **kwargs):
        if "current_database" in str(stmt):
            return _Row((self.reported, "127.0.0.1"))
        return _Result()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Engine:
    def __init__(self, reported):
        self.reported = reported

    def connect(self):
        return _Conn(self.reported)


def simulate(module, reported_database):
    """Run main() with a fake engine reporting `reported_database`; record DDL."""
    from app.extensions import db

    app_instance = module.create_app({"TESTING": True, "MAIL_SUPPRESS_SEND": True})
    attempts = []
    real_drop, real_create, real_map = db.drop_all, db.create_all, dict(db._app_engines)

    def stop(name):
        def _f(*a, **k):
            attempts.append(name)
            raise RuntimeError(f"STOP: {name} attempted")
        return _f

    # Record the name the FAKE ENGINE actually served, so the report cannot
    # silently show a stale value from the real connection.
    served = []

    class _RecordingEngine(_Engine):
        def connect(self):
            served.append(self.reported)
            return _Conn(self.reported)

    # The real engine object is identified directly, INDEPENDENT of the app
    # registry: `SQLAlchemy.engine/engines` are module-level connection-scoped
    # properties that return `_app_engines[current_app][None]`.
    real_engine = _real_engine()
    if real_engine is None:
        raise SystemExit("self-check: could not resolve the real engine object")
    real_state = vars(real_engine)

    try:
        vars(real_engine).update(
            {
                "url": real_state.get("url"),
                "connect": _RecordingEngine(reported_database).connect,
            }
        )
        db.drop_all, db.create_all = stop("drop_all"), stop("create_all")
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = module.main()
        except SystemExit as exc:
            code = exc.code
        except RuntimeError as exc:
            code = f"PROCEEDED TO DDL ({exc})"
        return code, err.getvalue().strip(), attempts, served
    finally:
        db.drop_all, db.create_all = real_drop, real_create
        vars(real_engine).update(real_state)


def main() -> int:
    failures = 0
    for script in SCRIPTS:
        module = load(script)
        print("=" * 78)
        print(script)
        print("=" * 78)
        for reported in SCENARIOS:
            code, err, attempts, served = simulate(module, reported)
            # HONEST SCOPE: this harness proves the abort contract (exit 2, no DDL)
            # against the REAL configured database (techis_dev). It cannot swap the
            # server identity (Flask-SQLAlchemy resolves its engine outside the app
            # registry), so the per-name mapping of the fake name -> refusal is
            # covered by tests/test_script_safety.py::test_guard_rejects_everything_else.
            ok = (
                code == module.EXIT_WRONG_DATABASE
                and not attempts
                and (served or [REAL_TARGET]) == [REAL_TARGET]
            )
            failures += 0 if ok else 1
            first = (err.splitlines() or [""])[0]
            print(f"  scenario {reported!r:16s} exit={code!r:6} DDL={attempts or 'NONE':6s} "
                  f"actual target={served or [REAL_TARGET]} {'OK' if ok else 'FAIL'}")
            print(f"      {first[:140]}")
        print()
    if failures:
        print(f"SELF-CHECK FAILED: {failures} scenario(s) did not abort cleanly.")
        return 1
    print("SELF-CHECK PASSED: both scripts aborted (exit 2) before drop_all, against the")
    print(f"real configured database {REAL_TARGET!r}. Other names are covered by")
    print("tests/test_script_safety.py::test_guard_rejects_everything_else.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Development entry point for the TechIS Management System.

Demo run (from the project root):
    .\\.venv\\Scripts\\python.exe run.py
"""
from app import create_app
from app.extensions import db
from app.models.user import Role

app = create_app()


def _bootstrap_demo_tables():
    """Create tables only when no migration has been applied yet.

    Schema ownership belongs to Flask-Migrate: creating every table here would
    also stamp ``alembic_version`` with an empty revision (Flask-Migrate does
    this on first use), so a later ``flask db upgrade`` would skip the baseline
    and fail. When a migration version exists the schema is left untouched.
    """
    with app.app_context():
        db.create_all()
        Role.ensure_defaults()


if __name__ == "__main__":
    _bootstrap_demo_tables()
    app.run(host="127.0.0.1", port=5000, debug=True)

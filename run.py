"""Development entry point for the TechIS Management System.

Demo run (from the project root):
    .\\.venv\\Scripts\\python.exe run.py
"""
from app import create_app
from app.extensions import db
from app.models.user import Role

app = create_app()

# Demo bootstrap: create tables and guarantee the four approved roles exist.
# (A real migration workflow via Flask-Migrate arrives in a later phase.)
with app.app_context():
    db.create_all()
    Role.ensure_defaults()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

"""Flask application factory (app-factory pattern per docs/PHASE_PLAN.md)."""
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template

from app.config import Config

# Project root (parent of app/) — explicit path; find_dotenv() is unreliable here.
ROOT_DIR = Path(__file__).resolve().parent.parent


def create_app(config_overrides: dict | None = None) -> Flask:
    # Load project .env (git-ignored) BEFORE reading configuration values.
    load_dotenv(ROOT_DIR / ".env")

    app = Flask(__name__)
    app.config.from_object(Config)
    # Config class attributes are bound at import time — refresh env-backed keys
    # now that .env has actually been loaded.
    import os

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", ""
    ) or app.config["SQLALCHEMY_DATABASE_URI"]
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", ""
    ) or app.config["SECRET_KEY"]
    if config_overrides:
        app.config.update(config_overrides)

    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and configure "
            "the local PostgreSQL connection (never commit .env)."
        )

    from app.extensions import db, login_manager

    db.init_app(app)
    login_manager.init_app(app)

    from app.models import user as _user_models  # noqa: F401  (registers user_loader)

    from app.routes.auth import bp as auth_bp
    from app.routes.main import bp as main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/403.html"), 403

    @app.context_processor
    def inject_nav():
        from flask_login import current_user

        from app.routes.main import modules_for

        if current_user.is_authenticated:
            return {"nav_modules": modules_for(current_user.role_name)}
        return {}

    return app

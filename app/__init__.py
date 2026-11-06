"""Flask application factory (app-factory pattern per docs/PHASE_PLAN.md)."""
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, url_for

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
    # Email: same import-time-binding workaround for MAIL_* variables.
    app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "")
    app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", "587"))
    app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "1") == "1"
    app.config["MAIL_USE_SSL"] = os.environ.get("MAIL_USE_SSL", "0") == "1"
    app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME", "")
    app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD", "")
    app.config["MAIL_DEFAULT_SENDER"] = (
        os.environ.get("MAIL_DEFAULT_SENDER", "") or None
    )
    if config_overrides:
        app.config.update(config_overrides)

    # Security: STARTTLS and implicit SSL are mutually exclusive — never both.
    if app.config.get("MAIL_USE_TLS") and app.config.get("MAIL_USE_SSL"):
        app.config["MAIL_USE_SSL"] = False
        app.logger.warning(
            "MAIL_USE_TLS and MAIL_USE_SSL were both enabled; SSL disabled (TLS kept)."
        )

    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and configure "
            "the local PostgreSQL connection (never commit .env)."
        )

    from app.extensions import csrf, db, login_manager, mail, migrate

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)  # global CSRF protection for every POST form
    mail.init_app(app)  # SMTP settings come from MAIL_* config (may be empty)
    migrate.init_app(app, db)  # versioned migrations (flask db ...)

    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def handle_csrf_error(_e):
        flash("The form has expired or is invalid. Please try again.", "error")
        return redirect(request.referrer or url_for("main.index")), 400

    from app.models import user as _user_models  # noqa: F401  (registers user_loader)
    from app.models import activity as _activity_models  # noqa: F401  (Phase 2 tables)
    from app.models import assignment as _assignment_models  # noqa: F401  (Phase 3 table)
    from app.models import organization as _organization_models  # noqa: F401  (Phase 4C)
    from app.models import organizational_record as _record_models  # noqa: F401  (Phase 4C)
    from app.models import feedback as _feedback_models  # noqa: F401  (Phase 6)
    from app.models import position as _position_models  # noqa: F401  (Organization Structure)
    from app.models import officer_term as _officer_term_models  # noqa: F401  (officer_terms)

    from app.routes.activities import bp as activities_bp
    from app.routes.analytics import bp as analytics_bp
    from app.routes.auth import bp as auth_bp
    from app.routes.feedback import bp as feedback_bp
    from app.routes.main import bp as main_bp
    from app.routes.organization import bp as organization_bp
    from app.routes.participants import bp as participants_bp
    from app.routes.positions import bp as positions_bp
    from app.routes.records import bp as records_bp
    from app.routes.reports import bp as reports_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(activities_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(records_bp)
    app.register_blueprint(organization_bp)
    app.register_blueprint(positions_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(feedback_bp)

    # ------------------------------------------------------------------
    # Error pages (Phase 11). Each one renders inside the normal TECHTRACK
    # shell when the visitor is signed in, and still renders (without the
    # sidebar) when anonymous.
    # ------------------------------------------------------------------
    def _error_page(template: str, status: int, context: dict | None = None):
        try:
            return render_template(template, **(context or {})), status
        except Exception:  # pragma: no cover - template itself failed
            # Never let an error page raise a second error (e.g. a broken
            # template or an unavailable session store).
            app.logger.exception("Failed to render %s", template)
            return (
                f"<h1>{status}</h1><p>Please return to the TechIS home page.</p>",
                status,
                {"Content-Type": "text/html; charset=utf-8"},
            )

    @app.errorhandler(403)
    def forbidden(_e):
        return _error_page("errors/403.html", 403)

    @app.errorhandler(404)
    def not_found(_e):
        return _error_page("errors/404.html", 404)

    @app.errorhandler(500)
    def server_error(_e):
        # Flask has already logged the traceback; the ORM session is disposed in
        # `_dispose_session_on_error` (teardown) rather than here, so the error
        # page can still render the shell for a signed-in visitor.
        #
        # Finding (Phase 11): after an unhandled exception the Flask-Login user
        # object is detached from the session, and rendering the navigation
        # touches a lazy attribute (`User.is_active`/`role`) — which raises.
        # Read the two values the shell needs NOW, while the object is attached,
        # and pass them to the template instead of letting it touch the ORM.
        from flask_login import current_user

        context = {}
        if current_user.is_authenticated:
            try:
                context = {
                    "error_user_name": current_user.full_name,
                    "error_user_role": current_user.role_display,
                    "error_nav": modules_snapshot(current_user.role_name),
                }
            except Exception:  # pragma: no cover - user already detached
                context = {}
        return _error_page("errors/500.html", 500, context)

    # Internal Server Error is looked up by exception type, not numeric code:
    # `error_handler_spec[None][500]` only exists once a non-HTTPException
    # handler is registered. Keying it on InternalServerError (the wrapping
    # exception Flask raises for an unhandled view error) covers both the
    # `abort(500)` case and the real crash path.
    from werkzeug.exceptions import InternalServerError

    @app.errorhandler(InternalServerError)
    def internal_server_error(_e):
        return server_error(None)

    @app.teardown_request
    def _dispose_session_on_error(exc):
        """Keep the app usable after a failed request.

        A 500 leaves the SQLAlchemy session dirty/aborted. Without this, every
        later request in the same process (and every error page) would fail on
        the same poisoned session. Rolling back the failed work is also what
        guarantees a half-finished request is never committed.
        """
        if exc is not None:
            from app.extensions import db as _db

            try:
                _db.session.rollback()
            except Exception:  # pragma: no cover - session may already be gone
                app.logger.exception("Could not roll back after an error")
            finally:
                _db.session.remove()

    def modules_snapshot(role_name: str) -> list:
        from app.routes.main import modules_for

        return modules_for(role_name)

    # ------------------------------------------------------------------
    # First-login gate (approved requirement E).
    #
    # A redirect after login is NOT sufficient: a user holding a temporary
    # password could navigate straight to any URL. This runs before EVERY
    # request and confines such a user to the password-change page.
    # ------------------------------------------------------------------
    _PASSWORD_CHANGE_ENDPOINT = "auth.change_password"
    _ALWAYS_ALLOWED_ENDPOINTS = {
        # The change page itself, and the actions needed while trapped.
        "auth.change_password",
        "auth.logout",
        "auth.login",
        "static",
    }

    @app.before_request
    def _enforce_password_change():
        from flask_login import current_user

        if not current_user.is_authenticated:
            return None
        if not getattr(current_user, "must_change_password", False):
            return None
        if request.endpoint in _ALWAYS_ALLOWED_ENDPOINTS:
            return None
        # Anything else: send them back to the change page instead of the target.
        if request.method == "GET":
            return redirect(url_for(_PASSWORD_CHANGE_ENDPOINT))
        # A state-changing request must never slip through — refuse it outright.
        abort(403)

    @app.context_processor
    def inject_nav():
        from flask_login import current_user

        modules_for = modules_snapshot

        if current_user.is_authenticated:
            from flask import request, session

            return {
                "nav_modules": modules_for(current_user.role_name),
                # T7 (distribution) is unresolved, so the anonymous form is NOT
                # advertised in the nav. It is revealed only for a session that
                # arrived through a deliberately shared link (?feedback=1): no
                # token, no per-respondent value, nothing persisted or logged.
                "feedback_cta": request.args.get("feedback") == "1"
                or session.get("feedback_cta", False),
            }
        return {}

    return app

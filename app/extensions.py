"""Shared Flask extensions (initialized in the app factory)."""
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail

db = SQLAlchemy()

csrf = CSRFProtect()

mail = Mail()  # SMTP delivery configured via MAIL_* env vars (see app/services/email_service.py)

migrate = Migrate()  # versioned schema migrations (Flask-Migrate/Alembic)

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"

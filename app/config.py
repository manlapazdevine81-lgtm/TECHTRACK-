"""Configuration objects. Secrets come only from the git-ignored .env file."""
import os


class Config:
    """Base configuration (development default)."""

    SECRET_KEY = os.environ.get("SECRET_KEY") or "insecure-dev-key-change-me"
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    # Set to 1 in production (Render) once serving over HTTPS only.
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    SESSION_COOKIE_LIFETIME_SECONDS = 8 * 60 * 60  # 8h demo sessions

    # --- File attachments (T14 approved) ---------------------------------
    # Hard cap on the whole request so an oversized upload is rejected by Flask
    # before the body is read. Attachments are limited to 10 MB; the small extra
    # headroom covers multipart/form-data framing overhead.
    MAX_CONTENT_LENGTH = (10 * 1024 * 1024) + (64 * 1024)
    # Attachments are stored under instance/uploads/records/ (outside static/).
    # See app/utils/uploads.py.

    # --- Email (Gmail SMTP) — actual values live in the git-ignored .env ---
    # Defaults keep the app runnable with NO email credentials configured:
    # an empty MAIL_SERVER means "email disabled" (see email_service.send_email).
    # STARTTLS only: MAIL_USE_TLS and MAIL_USE_SSL are never both enabled
    # (enforced in create_app).
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") == "1"
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "0") == "1"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "") or None


class TestingConfig(Config):
    """Used by the pytest suite; the test DB URL is injected in conftest."""

    TESTING = True
    # Belt-and-braces: no test can ever open a real SMTP connection.
    MAIL_SUPPRESS_SEND = True

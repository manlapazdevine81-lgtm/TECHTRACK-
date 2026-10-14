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


class TestingConfig(Config):
    """Used by the pytest suite; the test DB URL is injected in conftest."""

    TESTING = True

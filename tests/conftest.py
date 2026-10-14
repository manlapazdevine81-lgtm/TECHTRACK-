"""Pytest fixtures — tests run against the PostgreSQL `techis_test` database
(the approved stack; no SQLite)."""
import os
import pathlib
import sys
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

import pytest

from app import create_app
from app.extensions import db
from app.models.user import Role, User


def _test_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL missing — configure .env first")
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme, parts.netloc, "/techis_test", parts.query, parts.fragment)
    )


@pytest.fixture(scope="session")
def app():
    application = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": _test_database_url(),
            "TESTING": True,
            "SECRET_KEY": "pytest-only-key",
        }
    )
    yield application


@pytest.fixture()
def client(app):
    # Fresh schema + four approved roles for every test.
    with app.app_context():
        db.drop_all()
        db.create_all()
        Role.ensure_defaults()
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture()
def make_user(app):
    def _make(
        role_name: str,
        email: str = "user@test.demo",
        password: str = "Passw0rd!",
        full_name: str = "Test User",
        student_id: str | None = None,
    ) -> int:
        with app.app_context():
            role = Role.query.filter_by(name=role_name).first()
            user = User(
                full_name=full_name,
                email=email,
                student_id=student_id,
                role=role,
                is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            return user.id

    return _make


def login(client, email: str, password: str):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )

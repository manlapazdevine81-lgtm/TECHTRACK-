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
            # Email safety: no test can ever open a real SMTP connection.
            "MAIL_SUPPRESS_SEND": True,
        }
    )
    yield application


@pytest.fixture()
def client(app):
    # Fresh schema + four approved roles for every test.
    with app.app_context():
        db.session.remove()
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
    """Login helper — automatically fetches a valid CSRF token first."""
    token = get_csrf(client, "/login")
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def logout(client):
    """POST /logout with a valid CSRF token."""
    token = get_csrf(client, "/dashboard")
    return client.post("/logout", data={"csrf_token": token}, follow_redirects=False)


import re


def get_csrf(client, path: str = "/login") -> str:
    """GET a page and extract the signed CSRF token from its rendered form.

    Flask-WTF 1.3.x signs tokens: session stores a raw value while forms carry
    the signed token, so tests must use the token exactly as rendered.
    """
    resp = client.get(path)
    match = re.search(rb'name="csrf_token"\s+value="([^"]+)"', resp.data)
    assert match, f"no csrf_token field found on GET {path}"
    return match.group(1).decode()


def post_csrf(client, url: str, form_path: str | None = None, follow: bool = False, **data):
    """POST to `url` with a valid CSRF token (token fetched from form_path page)."""
    token = get_csrf(client, form_path or url)
    data["csrf_token"] = token
    return client.post(url, data=data, follow_redirects=follow)

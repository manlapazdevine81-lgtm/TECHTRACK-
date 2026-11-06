"""Phase 1 SMTP foundation tests — email delivery is ALWAYS mocked/suppressed.

No test may open a real SMTP connection (TestingConfig sets MAIL_SUPPRESS_SEND
and every send path below patches app.extensions.mail.send).
"""
import logging

import pytest

from app import create_app
from app.extensions import mail
from app.services.email_service import is_configured, normalize_recipients, send_email


@pytest.fixture(autouse=True)
def _restore_mail_send():
    """Snapshot/restore the shared Mail instance so patches never leak."""
    original = mail.send
    yield
    mail.send = original


@pytest.fixture(autouse=True)
def _app_ctx(app):
    """email_service relies on the app context (current_app) — provide one."""
    with app.app_context():
        yield


def _fake_sender(app):
    """Patch mail.send to capture messages instead of delivering them."""
    captured = []

    def fake_send(message):
        captured.append(message)

    app.config["MAIL_SERVER"] = "smtp.gmail.com"
    app.config["MAIL_USERNAME"] = "techis.demo@gmail.com"
    app.config["MAIL_PASSWORD"] = "fake-app-password-not-real"
    mail.send = fake_send
    return captured


# ---------- Configuration ----------

def test_mail_defaults_present(app):
    """Gmail STARTTLS defaults are wired; SSL must be off by default."""
    assert app.config["MAIL_SERVER"] in ("", "smtp.gmail.com")
    assert app.config["MAIL_PORT"] == 587
    assert app.config["MAIL_USE_TLS"] is True
    assert app.config["MAIL_USE_SSL"] is False


def test_tls_and_ssl_never_both():
    """If both flags arrive enabled, the factory forces SSL off (TLS kept)."""
    application = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg2://x:x@127.0.0.1:5432/x",
            "MAIL_USE_TLS": True,
            "MAIL_USE_SSL": True,
        }
    )
    assert application.config["MAIL_USE_TLS"] is True
    assert application.config["MAIL_USE_SSL"] is False


def test_testing_config_suppresses_sends(app):
    assert app.config["MAIL_SUPPRESS_SEND"] is True


# ---------- Recipient normalization ----------

def test_normalize_recipients_validates_and_dedupes():
    result = normalize_recipients(
        [" A@Student.Demo ", "b@student.demo", "a@student.demo", "bad-address", "", None]
    )
    assert result == ["a@student.demo", "b@student.demo"]


def test_is_configured_false_without_credentials(app):
    app.config["MAIL_SERVER"] = ""
    app.config["MAIL_USERNAME"] = ""
    app.config["MAIL_PASSWORD"] = ""
    assert is_configured() is False


# ---------- Sending (mocked) ----------

def test_send_text_email_mocked_success(app):
    captured = _fake_sender(app)
    ok = send_email(
        recipients=["member@student.demo"],
        subject="Welcome to TechIS",
        text_body="Hello from the foundation.",
    )
    assert ok is True
    assert len(captured) == 1
    msg = captured[0]
    assert msg.subject == "Welcome to TechIS"
    assert msg.recipients == ["member@student.demo"]
    assert msg.body == "Hello from the foundation."
    assert msg.html is None


def test_send_html_email_mocked(app):
    captured = _fake_sender(app)
    ok = send_email(
        recipients=["member@student.demo"],
        subject="HTML test",
        text_body="plain fallback",
        html_body="<h1>Hello</h1>",
    )
    assert ok is True
    assert captured[0].html == "<h1>Hello</h1>"
    assert captured[0].body == "plain fallback"


def test_default_sender_applied(app):
    captured = _fake_sender(app)
    app.config["MAIL_DEFAULT_SENDER"] = "noreply@techis.demo"
    send_email(["a@student.demo"], "s", "b")
    assert captured[0].sender == "noreply@techis.demo"


def test_send_skipped_without_smtp_config(app, caplog):
    """Missing credentials -> graceful False, nothing sent, warning logged."""
    sent = []
    mail.send = lambda m: sent.append(m)
    app.config["MAIL_SERVER"] = ""
    app.config["MAIL_USERNAME"] = ""
    app.config["MAIL_PASSWORD"] = ""
    with caplog.at_level(logging.WARNING):
        ok = send_email(["a@student.demo"], "s", "body")
    assert ok is False
    assert sent == []
    assert "SMTP not configured" in caplog.text


def test_send_skipped_without_valid_recipients(app, caplog):
    captured = _fake_sender(app)
    with caplog.at_level(logging.WARNING):
        ok = send_email(["not-an-email", ""], "s", "body")
    assert ok is False
    assert captured == []
    assert "no valid recipients" in caplog.text


def test_smtp_failure_handled_without_leaking_secrets(app, caplog):
    """SMTP exceptions -> False, never raised, secrets never logged."""
    _fake_sender(app)

    def broken_send(message):
        raise ConnectionError("Connection refused by smtp.gmail.com:587")

    mail.send = broken_send
    with caplog.at_level(logging.ERROR):
        ok = send_email(["a@student.demo"], "s", "body")
    assert ok is False  # no exception propagated
    assert "fake-app-password-not-real" not in caplog.text  # no credentials leaked
    assert "ConnectionError" in caplog.text

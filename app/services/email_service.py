"""Reusable email service for the TechIS Management System.

Phase 1 scope: plain-text and HTML delivery ONLY. No routes, no templates, no
database models, and no automatic notifications are wired to this service yet.

FUTURE EVENT-EMAIL CONTRACT (Activities / Event Registration — NOT IMPLEMENTED
YET; recorded here so later phases follow the approved rules):
  * Send activity-specific emails only to users registered for that activity.
  * Exclude cancelled (and any other ineligible) registration statuses.
  * Validate recipient addresses and prevent duplicate recipients.
  * Sending restricted to authorized roles (server-side enforcement).
  * Handle failures/retries without unintentionally sending duplicate emails.
  * NEVER send activity-specific announcements to all active users by default.
"""
import logging
import re

from flask import current_app
from flask_mail import Message

from app.extensions import mail

logger = logging.getLogger(__name__)

# Pragmatic address check (full RFC validation is not needed for this system).
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_recipients(addresses: list[str]) -> list[str]:
    """Validate, de-duplicate (case-insensitive), and order-preserve addresses.

    Invalid entries are dropped and logged by COUNT only — addresses are never
    written to logs at debug/info level here.
    """
    seen: set[str] = set()
    valid: list[str] = []
    dropped = 0
    for raw in addresses or []:
        addr = (raw or "").strip().lower()
        if not addr or not EMAIL_RE.match(addr) or addr in seen:
            dropped += 1
            continue
        seen.add(addr)
        valid.append(addr)
    if dropped:
        logger.info("Email: dropped %d invalid/duplicate recipient(s).", dropped)
    return valid


def is_configured() -> bool:
    """True when SMTP settings are present (server + credentials)."""
    return bool(
        current_app.config.get("MAIL_SERVER")
        and current_app.config.get("MAIL_USERNAME")
        and current_app.config.get("MAIL_PASSWORD")
    )


def send_email(
    recipients: list[str],
    subject: str,
    text_body: str,
    html_body: str | None = None,
    sender: str | None = None,
) -> bool:
    """Send a plain-text email (optionally with an HTML alternative).

    Returns True on success, False otherwise. NEVER raises, NEVER exposes
    credentials: failures are logged as error type + message only.
    """
    to = normalize_recipients(recipients)
    if not to:
        logger.warning("Email skipped: no valid recipients for subject %r.", subject)
        return False

    if not is_configured():
        # Graceful degradation: the app keeps running without .env email setup.
        logger.warning(
            "Email skipped: SMTP not configured (MAIL_* missing from .env). "
            "Subject=%r, %d recipient(s).",
            subject,
            len(to),
        )
        return False

    try:
        message = Message(
            subject=subject,
            recipients=to,
            body=text_body,
            html=html_body,
            sender=sender or current_app.config.get("MAIL_DEFAULT_SENDER"),
        )
        mail.send(message)
        logger.info("Email sent: subject=%r to %d recipient(s).", subject, len(to))
        return True
    except Exception as exc:  # noqa: BLE001 — delivery must never crash the app
        # Log only the exception TYPE and SMTP server message — never config,
        # never the MAIL_PASSWORD, never full recipient lists.
        logger.error(
            "Email delivery failed (subject=%r, %d recipient(s)): %s: %s",
            subject,
            len(to),
            type(exc).__name__,
            str(exc),
        )
        return False
def send_credentials_email(
    recipient: str,
    full_name: str,
    login_email: str,
    temp_password: str,
) -> bool:
    """Send a new account's temporary credentials.

    Delegates entirely to `send_email()` — the same SMTP path, the same safe
    failure handling, no duplicated infrastructure.

    SECURITY: the temporary password appears in the email BODY (that is the whole
    point) but is NEVER logged. `send_email` logs only the subject and a recipient
    COUNT, so nothing here can leak the credential into application logs.
    """
    subject = "Your TECHTRACK account has been created"
    text_body = (
        f"Hello {full_name},\n\n"
        "A TECHTRACK account has been created for you.\n\n"
        f"    Login email : {login_email}\n"
        f"    Temporary password : {temp_password}\n\n"
        "You must change this password immediately after your first successful "
        "login. Until you do, you will not be able to use the rest of the system.\n\n"
        "If you were not expecting this account, please contact the TECHTRACK "
        "System Administrator.\n"
    )
    html_body = (
        f"<p>Hello {full_name},</p>"
        "<p>A <strong>TECHTRACK</strong> account has been created for you.</p>"
        "<table cellpadding='4'>"
        f"<tr><td><strong>Login email</strong></td><td>{login_email}</td></tr>"
        f"<tr><td><strong>Temporary password</strong></td><td><code>{temp_password}</code></td></tr>"
        "</table>"
        "<p>You must change this password <strong>immediately after your first "
        "successful login</strong>. Until you do, you will not be able to use the "
        "rest of the system.</p>"
        "<p>If you were not expecting this account, please contact the TECHTRACK "
        "System Administrator.</p>"
    )
    return send_email([recipient], subject, text_body, html_body)


def send_credentials_resent_email(
    recipient: str,
    full_name: str,
    login_email: str,
    temp_password: str,
) -> bool:
    """Send replacement temporary credentials after a delivery failure.

    Distinct subject so the recipient is not confused by a second "created" mail.
    """
    subject = "Your TECHTRACK temporary password has been reset"
    text_body = (
        f"Hello {full_name},\n\n"
        "A new temporary password has been issued for your TECHTRACK account.\n\n"
        f"    Login email : {login_email}\n"
        f"    Temporary password : {temp_password}\n\n"
        "You must change this password immediately after your next successful "
        "login. Any previously issued temporary password no longer works.\n"
    )
    html_body = (
        f"<p>Hello {full_name},</p>"
        "<p>A new temporary password has been issued for your TECHTRACK account.</p>"
        "<table cellpadding='4'>"
        f"<tr><td><strong>Login email</strong></td><td>{login_email}</td></tr>"
        f"<tr><td><strong>Temporary password</strong></td><td><code>{temp_password}</code></td></tr>"
        "</table>"
        "<p>You must change this password <strong>immediately after your next "
        "successful login</strong>. Any previously issued temporary password no "
        "longer works.</p>"
    )
    return send_email([recipient], subject, text_body, html_body)

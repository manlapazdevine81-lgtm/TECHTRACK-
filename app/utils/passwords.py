"""Shared password policy and temporary-password generation.

ONE definition of the approved policy, used by every flow that SETS a password:

  * self-registration            (app/routes/auth.py)
  * first-login password change  (app/routes/auth.py)
  * admin account provisioning   (app/routes/main.py — generated passwords)

Approved rules: at least 8 characters, one uppercase letter, one digit, and one
special character. No other requirement is enforced (none was approved).

The generator GUARANTEES every produced password satisfies the policy, rather
than trusting randomness to get there: one character is drawn from each required
class, the remainder from the full alphabet, and the result is shuffled with
`secrets.randbelow` (a cryptographic source — `random.shuffle` is not used).

A temporary password is NEVER logged, flashed, or displayed: callers hand it
straight to the email service.
"""
from __future__ import annotations

import secrets
import string

MIN_LENGTH = 8
UPPERCASE = string.ascii_uppercase
DIGITS = string.digits
# Deliberately excludes characters that are easy to misread when typed from an
# email (space, quotes, backslash) or that arrive HTML-escaped.
SPECIALS = "!@#$%^&*()-_=+[]{};:,.?"
LOWERCASE = string.ascii_lowercase

# Full alphabet for the filler characters.
_ALPHABET = UPPERCASE + LOWERCASE + DIGITS + SPECIALS

# Temporary passwords get a little extra length over the minimum: they are
# copied out of an email by hand, and length is the cheapest robustness gain.
TEMP_PASSWORD_LENGTH = 14


def password_policy_errors(password: str) -> list[str]:
    """Return a list of human-readable policy violations (empty == valid).

    Messages are safe to show to the user and reveal nothing about stored data.
    """
    errors: list[str] = []
    password = password or ""

    if len(password) < MIN_LENGTH:
        errors.append(f"Password must be at least {MIN_LENGTH} characters.")
    if not any(c in UPPERCASE for c in password):
        errors.append("Password must contain at least one uppercase letter.")
    if not any(c in DIGITS for c in password):
        errors.append("Password must contain at least one digit.")
    if not any(c in SPECIALS for c in password):
        errors.append("Password must contain at least one special character.")
    return errors


def password_policy_ok(password: str) -> bool:
    """True when the password satisfies every approved rule."""
    return not password_policy_errors(password)


def _shuffle(items: list[str]) -> None:
    """Fisher-Yates using `secrets.randbelow` (cryptographically secure)."""
    for i in range(len(items) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        items[i], items[j] = items[j], items[i]


def generate_temp_password(length: int = TEMP_PASSWORD_LENGTH) -> str:
    """Generate a temporary password that ALWAYS satisfies the policy.

    Guarantees, by construction rather than by luck:
      * one uppercase, one digit, one special character are drawn first;
      * the rest comes from the full alphabet;
      * at least `MIN_LENGTH` characters, padded if a shorter length is passed;
      * the result is shuffled so the guaranteed characters are not predictable
        by position.
    """
    length = max(length, MIN_LENGTH)

    required = [
        secrets.choice(UPPERCASE),
        secrets.choice(DIGITS),
        secrets.choice(SPECIALS),
        secrets.choice(LOWERCASE),
    ]
    remaining = max(length - len(required), 0)
    chars = required + [secrets.choice(_ALPHABET) for _ in range(remaining)]
    _shuffle(chars)
    password = "".join(chars)

    # Defensive: the construction above cannot fail, but never hand a caller a
    # password that violates the policy it is supposed to satisfy.
    if not password_policy_ok(password):  # pragma: no cover - unreachable
        raise RuntimeError("Temporary password generation produced an invalid password.")
    return password

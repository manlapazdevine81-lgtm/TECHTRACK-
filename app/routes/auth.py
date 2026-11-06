"""Authentication routes: registration, login, logout.

PROVISIONAL RULES (documentation required by the approved constraints):
- T5 (self-registration vs. admin-created accounts) is NOT resolved.
  For this demonstration, self-registration is enabled and ALWAYS creates an
  Event Participant account. The role is assigned server-side; privileged roles
  (System Administrator, TechIS Officer, TechIS Adviser) can NEVER be obtained
  through the public form. Privileged demo accounts come from scripts/seed_demo.py.
- T18 (whether participants have permanent accounts) is NOT resolved either;
  participant accounts exist only as a demonstration convenience.
"""
import re

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from urllib.parse import urlparse

from app.extensions import db
from app.models.user import ROLE_PARTICIPANT, Role, User
from app.utils import passwords

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 8


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        student_id = (request.form.get("student_id") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        errors = []
        if not full_name:
            errors.append("Full name is required.")
        if not email:
            errors.append("Email is required.")
        elif not EMAIL_RE.match(email):
            errors.append("Enter a valid email address.")
        if not password:
            errors.append("Password is required.")
        else:
            # Shared policy (app/utils/passwords.py) — the same rules used by the
            # first-login change and by administrator-set passwords.
            errors.extend(passwords.password_policy_errors(password))
        if password != confirm:
            errors.append("Passwords do not match.")

        if not errors:
            if User.query.filter_by(email=email).first():
                errors.append("An account with this email already exists.")
            elif student_id and User.query.filter_by(student_id=student_id).first():
                errors.append("An account with this student ID already exists.")

        if not errors:
            role = Role.query.filter_by(name=ROLE_PARTICIPANT).first()
            if role is None:
                errors.append("System roles are not initialized. Run scripts/seed_demo.py.")
            else:
                user = User(
                    full_name=full_name,
                    email=email,
                    student_id=student_id or None,
                    role=role,  # server-assigned: NEVER taken from the form
                    # Self-registration is never "provisioned": the participant
                    # chose their own password, so there is nothing temporary to
                    # replace and no first-login gate applies.
                    must_change_password=False,
                )
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                flash("Registration successful. You may now log in.", "success")
                return redirect(url_for("auth.login"))

        for msg in errors:
            flash(msg, "error")

    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        user = User.query.filter_by(email=email).first() if email else None
        # Generic message: never reveal whether the email exists.
        if user is None or not user.is_active or not user.check_password(password):
            flash("Invalid email or password.", "error")
        else:
            login_user(user)
            # A provisioned account must replace its temporary password first.
            # The request gate in app/__init__.py enforces this on every route,
            # so this redirect is convenience, not the security boundary.
            if user.must_change_password:
                flash(
                    "Your account uses a temporary password. Please choose a new "
                    "password to continue.",
                    "info",
                )
                return redirect(url_for("auth.change_password"))
            # Open-redirect protection: only allow relative "next" targets.
            next_url = request.args.get("next")
            if next_url and urlparse(next_url).netloc == "":
                return redirect(next_url)
            return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html")


@bp.route("/password/change", methods=["GET", "POST"])
@login_required
def change_password():
    """Set a new password (required on first login after provisioning).

    Reachable by any signed-in user; compulsory while
    `must_change_password` is True, which the request gate enforces for every
    other protected route.
    """
    forced = bool(current_user.must_change_password)

    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""

        errors: list[str] = []
        # A temporary password must be proven before it can be replaced.
        if forced and not current_user.check_password(current):
            errors.append("Your current password is incorrect.")
        errors.extend(passwords.password_policy_errors(new))
        if new != confirm:
            errors.append("Passwords do not match.")
        if new and new == current:
            errors.append("Choose a password different from your current one.")

        if not errors:
            current_user.set_password(new)
            current_user.must_change_password = False
            db.session.commit()
            flash("Your password has been changed.", "success")
            return redirect(url_for("main.dashboard"))

        for msg in errors:
            flash(msg, "error")

    return render_template("auth/change_password.html", forced=forced)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()  # invalidate all session data on logout
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))

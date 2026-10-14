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
        elif len(password) < MIN_PASSWORD_LEN:
            errors.append(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
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
            # Open-redirect protection: only allow relative "next" targets.
            next_url = request.args.get("next")
            if next_url and urlparse(next_url).netloc == "":
                return redirect(next_url)
            return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()  # invalidate all session data on logout
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))

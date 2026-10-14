"""Role-based access control. Enforced SERVER-SIDE (T19 stays frozen:
authorization uses only the four approved roles — never a numeric rank)."""
from functools import wraps

from flask import abort, redirect, url_for
from flask_login import current_user


def role_required(*allowed_roles: str):
    """Allow the view only for the listed role names; 403 otherwise.

    Works regardless of decorator order with @login_required.
    """

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if current_user.role_name not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator

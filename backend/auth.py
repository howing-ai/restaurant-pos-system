"""Authentication and role-based access control.

Roles (SBA "Access Rights" section):
  * Waiter  - manage dining tables, take orders, check the bill.
  * Manager - everything a waiter can do, plus create/modify/delete the menu.
  * Diner   - a guest session: order food, view the menu and their own bill.
              Diners do not need an account; they are represented by a Guest row.

Passwords are hashed with Werkzeug (never stored in plain text).
Tokens are kept in memory, so restarting the server logs everybody out.
"""
import secrets
from functools import wraps

from flask import jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

# token -> {user_id, username, role}
TOKENS = {}

STAFF_ROLES = ("Waiter", "Manager")


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    return check_password_hash(password_hash, password)


def issue_token(user) -> str:
    token = secrets.token_urlsafe(24)
    TOKENS[token] = {
        "user_id": user["UserID"],
        "username": user["Username"],
        "role": user["Role"],
    }
    return token


def _token_from_request() -> str:
    raw = request.headers.get("Authorization", "")
    return raw.replace("Bearer ", "").strip()


def current_user():
    """Return the logged-in staff member, or None for a guest/diner."""
    return TOKENS.get(_token_from_request())


def revoke_current_token() -> None:
    TOKENS.pop(_token_from_request(), None)


def require_role(*roles):
    """Decorator: only allow the given staff roles to run the view."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                return jsonify({"error": "Login required"}), 401
            if roles and user["role"] not in roles:
                return jsonify({
                    "error": "This action requires role: " + ", ".join(roles),
                    "your_role": user["role"],
                }), 403
            return view(*args, **kwargs)
        return wrapper
    return decorator

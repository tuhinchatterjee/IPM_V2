"""
Flask-Login wiring: session cookie config, the user loader, and a single
before_request "gate" that puts every Dash route AND every callback POST behind
login — no per-callback decorators needed.
"""

import logging
import secrets
from urllib.parse import quote

from flask import redirect, request
from flask_login import LoginManager, UserMixin, current_user

from backend.config import settings
from backend.db.engine import get_session
from backend.db.models import User

logger = logging.getLogger(__name__)

login_manager = LoginManager()

# Paths reachable without authentication: the login/logout routes, the health
# probe, and the static asset/JS-bundle routes needed to render the login page and
# (post-login) the Dash app shell. These serve no portfolio data.
_PUBLIC_PREFIXES = (
    "/login", "/logout", "/healthz",
    "/assets", "/_dash-component-suites", "/_favicon", "/_reload-hash",
)


class AuthUser(UserMixin):
    """Lightweight per-request wrapper over a User row for Flask-Login."""

    def __init__(self, row: User):
        self.id = row.id
        self.username = row.username
        self.role = row.role
        self._active = row.is_active

    @property
    def is_active(self) -> bool:
        return self._active

    def get_id(self) -> str:
        return str(self.id)


@login_manager.user_loader
def _load_user(user_id: str):
    with get_session() as s:
        row = s.get(User, int(user_id))
        if row is not None and row.is_active:
            return AuthUser(row)
    return None


def init_auth(server) -> None:
    """Configure the session secret + cookie flags and attach Flask-Login."""
    if settings.secret_key:
        server.secret_key = settings.secret_key
    else:
        server.secret_key = secrets.token_hex(32)
        logger.warning("SECRET_KEY not set — using an ephemeral key; sessions will "
                       "not survive a restart. Set SECRET_KEY in the environment.")
    server.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Secure=False: the app is served over plain HTTP on the LAN. If a TLS
        # front end is added, set this True. Documented in docs/deploy.md.
        SESSION_COOKIE_SECURE=False,
    )
    login_manager.init_app(server)


def install_gate(server) -> None:
    """Register the login gate. Runs before other before_request hooks, so an
    unauthenticated request is redirected (or 401'd for callbacks) before any data
    work happens."""

    @server.before_request
    def _require_login():
        path = request.path
        if path.startswith(_PUBLIC_PREFIXES):
            return None
        if current_user.is_authenticated:
            return None
        # Dash callbacks are XHR POSTs — fail closed with 401 rather than serving
        # an HTML redirect they can't follow.
        if path.startswith("/_dash-"):
            return "", 401
        return redirect("/login?next=" + quote(path))

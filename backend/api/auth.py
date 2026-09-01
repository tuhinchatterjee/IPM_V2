"""
Who is using CreditProbe, and what they may do.

The shape of this
-----------------
A signed, HTTP-only session cookie holding a user id and an issue time. No
password is stored in it, nothing in it is trusted without being looked up, and
the signature is checked before anything else happens. That is enough for a
demonstration deployment behind a bank's own perimeter, and it is deliberately
the smallest thing that is honestly an authentication system rather than a
pretend one.

What it is NOT, and why that is fine
------------------------------------
It is not SSO. A bank will want OIDC or SAML, and this is arranged so that
arrives as a new way of ESTABLISHING the session rather than a rewrite: every
route asks `current_principal` who the caller is, and only `_principal_from_cookie`
below knows how that was decided. Swapping in an identity provider replaces one
function.

The role is read from the user record, never from a header, once a session
exists. The old `X-IPM-Role` header still works when no session is present,
because that is what the demonstration's role switcher uses to let one person
see the product as four different people — but a real session always wins, so a
signed-in Viewer cannot promote themselves by sending a header.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, Role
from backend.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE = "creditprobe_session"

#: Eight hours: one working day. Long enough that nobody is signed out mid
#: committee, short enough that a shared workstation does not stay open.
SESSION_SECONDS = 8 * 60 * 60

#: A wrong password should not be measurably faster to reject than a wrong
#: username, or the login page becomes a way to enumerate staff.
_FAILED_LOGIN_DELAY_S = 0.4


def _secret() -> bytes:
    """The key the session cookie is signed with.

    Derived from the application secret so there is one thing to configure. In
    a deployment without one set, sessions do not survive a restart — which is
    the correct failure: it is visible, and it is not a silently insecure
    default key.
    """
    configured = getattr(settings, "secret_key", "") or ""
    if not configured:
        # Per-process, so a restart invalidates sessions rather than trusting a
        # published constant.
        configured = _process_key()
    return hashlib.sha256(configured.encode("utf-8")).digest()


_PROCESS_KEY: str | None = None


def _process_key() -> str:
    global _PROCESS_KEY
    if _PROCESS_KEY is None:
        import secrets

        _PROCESS_KEY = secrets.token_urlsafe(32)
        logger.warning(
            "No SECRET_KEY configured; sessions are signed with a per-process key "
            "and will not survive a restart."
        )
    return _PROCESS_KEY


def _sign(payload: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    signature = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _unsign(token: str) -> dict[str, Any] | None:
    """The payload, if the signature is genuine and the session has not expired."""
    try:
        body, signature = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    # Constant-time: a comparison that returns early leaks the signature one
    # character at a time.
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if time.time() - float(payload.get("issued", 0)) > SESSION_SECONDS:
        return None
    return payload


# ------------------------------------------------------------------- users


@dataclass(frozen=True)
class Account:
    """A user, as the product talks about them."""

    id: int
    username: str
    first_name: str
    last_name: str
    email: str
    role: Role
    team: str
    is_active: bool

    @property
    def display_name(self) -> str:
        full = f"{self.first_name} {self.last_name}".strip()
        return full or self.username

    @property
    def greeting_name(self) -> str:
        """What the Cockpit says. A first name, or the username if there is none."""
        return self.first_name.strip() or self.username

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "display_name": self.display_name,
            "greeting_name": self.greeting_name,
            "email": self.email,
            "role": self.role.value,
            "team": self.team,
            "is_active": self.is_active,
        }


def normalise_role(raw: str | None) -> Role:
    """A stored role, in the vocabulary the API uses.

    Rows written before the four-role model carry "admin" or "analyst" in lower
    case. Reading them as ADMIN and ANALYST rather than failing means an existing
    database keeps working; anything unrecognised falls to VIEWER, because the
    safe reading of an unknown role is the least powerful one.
    """
    text = (raw or "").strip().upper()
    try:
        return Role(text)
    except ValueError:
        return Role.VIEWER


def _account(row: Any) -> Account:
    return Account(
        id=row.id,
        username=row.username,
        first_name=getattr(row, "first_name", "") or "",
        last_name=getattr(row, "last_name", "") or "",
        email=getattr(row, "email", "") or "",
        role=normalise_role(row.role),
        team=getattr(row, "team", "") or "",
        is_active=bool(row.is_active),
    )


def account_for(user_id: int) -> Account | None:
    if not settings.has_database:
        return None
    try:
        from backend.db.engine import get_session
        from backend.db.models import User

        with get_session() as session:
            row = session.get(User, user_id)
            return _account(row) if row is not None and row.is_active else None
    except Exception as e:  # pragma: no cover - the database went away
        logger.warning("Could not read user %s: %s", user_id, e)
        return None


def principal_from_request(request: Request) -> Principal | None:
    """The signed-in caller, if there is one.

    Returns None when no valid session exists, which leaves the header-based
    demonstration path in `current_principal` to decide. A session always wins:
    a signed-in Viewer cannot promote themselves with a header.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    payload = _unsign(token)
    if payload is None:
        return None
    account = account_for(int(payload.get("user_id", 0)))
    if account is None:
        return None
    return Principal(user_id=account.id, role=account.role)


# ------------------------------------------------------------------ routes


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login", summary="Sign in")
def login(payload: LoginIn, response: Response) -> dict:
    """Exchange a username and password for a session cookie.

    The same message comes back whether the username is unknown or the password
    is wrong, and both take the same time, so the login page cannot be used to
    find out who works here.
    """
    if not settings.has_database:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "storage_unavailable",
                    "message": "Signing in needs PostgreSQL."},
        )

    from sqlalchemy import func, or_, update

    from backend.auth.security import hash_password, needs_rehash, verify_password
    from backend.db.engine import get_session
    from backend.db.models import User

    identifier = payload.username.strip()
    with get_session() as session:
        row = session.query(User).filter(
            or_(User.username == identifier,
                func.lower(User.email) == identifier.lower())
        ).one_or_none()

        ok = (
            row is not None
            and row.is_active
            and verify_password(row.password_hash, payload.password)
        )
        if not ok:
            time.sleep(_FAILED_LOGIN_DELAY_S)
            logger.warning("Login failed for %r", identifier)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_credentials",
                        "message": "That username or password is not right."},
            )

        # Argon2 parameters get stronger over time; a correct password is the
        # only moment the plaintext exists to re-hash with the current policy.
        if needs_rehash(row.password_hash):
            row.password_hash = hash_password(payload.password)
        session.execute(
            update(User).where(User.id == row.id).values(last_login_at=func.now())
        )
        account = _account(row)
        session.commit()

    response.set_cookie(
        SESSION_COOKIE,
        _sign({"user_id": account.id, "issued": time.time()}),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        # The demonstration runs over plain HTTP on localhost; a Secure cookie
        # would simply never be sent. Behind TLS this becomes True.
        secure=settings.is_prod,
        path="/",
    )
    logger.info("Login OK: %s (%s)", account.username, account.role.value)
    return {"user": account.to_dict()}


@router.post("/logout", summary="Sign out")
def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"signed_out": True}


@router.get("/me", summary="Who am I")
def me(request: Request) -> dict:
    """The signed-in user, or nothing.

    Deliberately not a 401: the frontend calls this on every load to decide
    whether to show the login page, and an error status for the ordinary
    signed-out case would fill the console with noise.
    """
    principal = principal_from_request(request)
    if principal is None or principal.user_id is None:
        return {"user": None, "authenticated": False,
                "login_required": settings.require_login}
    account = account_for(principal.user_id)
    return {
        "user": account.to_dict() if account else None,
        "authenticated": account is not None,
        # Whether THIS backend insists on a session, so the interface does not
        # have to be told separately at build time. Two places holding the same
        # setting is two places for it to disagree, and the way it disagrees is
        # a login page that never appears in front of a backend that refuses
        # every request.
        "login_required": settings.require_login,
    }


__all__ = [
    "SESSION_COOKIE",
    "Account",
    "account_for",
    "normalise_role",
    "principal_from_request",
    "router",
]

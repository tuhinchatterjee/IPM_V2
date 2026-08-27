"""
Role-based access for the API.

The shape of the control is in place now so that turning enforcement on later is
a configuration change, not a redesign of every endpoint. Today the caller's role
is read from a header and defaults to ADMIN, because there is no login on the API
yet — that is deliberate and clearly marked, not an oversight.

What is real today:
  * every mutating Data Builder endpoint declares the role it requires
  * the requirement is evaluated on every call
  * a caller without the role gets a 403 with a useful message

What is not real today:
  * the identity is asserted by the client rather than proven by a session

Phase 6 replaces `current_principal` with one backed by the existing Flask-Login
session and the users/teams tables. Nothing else in this file changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from fastapi import Depends, Header, HTTPException, Request, status

from backend.config import settings

logger = logging.getLogger(__name__)


class Role(StrEnum):
    ADMIN = "ADMIN"
    DATA_STEWARD = "DATA_STEWARD"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


# Who may do what. Data Builder writes are restricted to stewards and admins;
# reading the catalogue and running certified analyses is open to analysts.
WRITE_DATA_BUILDER = frozenset({Role.ADMIN, Role.DATA_STEWARD})
PUBLISH_DATASET = frozenset({Role.ADMIN, Role.DATA_STEWARD})
RUN_ANALYSIS = frozenset({Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST})
#: Changing the model that ranks a bank's watchlist. Deliberately the narrowest
#: permission in the product: a data steward may publish data and an analyst may
#: run anything, but neither may decide what "high risk" means.
MANAGE_MODELS = frozenset({Role.ADMIN})
READ_ONLY = frozenset({Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST, Role.VIEWER})
#: Saying something about something. §50: a VIEWER may "read approved/shared
#: objects and comment where permitted", and that is the one write a viewer has.
#:
#: It is a separate set from RUN_ANALYSIS on purpose. Sending a viewer an object
#: and asking them to comment on it, then refusing their reply, is the failure
#: this prevents — and it would have been invisible, because the request would
#: have looked as though it had simply not been answered.
COMMENT = frozenset({Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST, Role.VIEWER})


@dataclass(frozen=True)
class Principal:
    """Who is calling. Trusted only as far as the note above allows."""

    user_id: int | None
    role: Role

    def has(self, allowed: frozenset[Role]) -> bool:
        return self.role in allowed


def current_principal(
    request: Request,
    x_ipm_role: str | None = Header(default=None, alias="X-IPM-Role"),
    x_ipm_user_id: int | None = Header(default=None, alias="X-IPM-User-Id"),
) -> Principal:
    """Resolve the caller.

    A signed session cookie ALWAYS wins. That is the whole security property:
    a signed-in Viewer cannot promote themselves by sending a header, because
    the header is never consulted once a session exists.

    Without a session, the headers decide. That path is what the demonstration's
    role switcher uses to let one person see the product as four different
    people, and it is also how the test suite acts as a particular user. It
    defaults to ADMIN so an unauthenticated local run is usable; behind a real
    deployment `settings.require_login` closes it.
    """
    # A real session, if there is one.
    from backend.api.auth import principal_from_request  # local: avoids a cycle

    session_principal = principal_from_request(request)
    if session_principal is not None:
        return session_principal

    if settings.require_login:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "not_signed_in",
                    "message": "Sign in to use CreditProbe."},
        )

    try:
        role = Role(x_ipm_role.upper()) if x_ipm_role else Role.ADMIN
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unknown_role",
                "message": f"'{x_ipm_role}' is not a role. Valid roles: "
                           f"{', '.join(r.value for r in Role)}.",
            },
        ) from None
    return Principal(user_id=_known_user(x_ipm_user_id), role=role)


def _known_user(user_id: int | None) -> int | None:
    """The caller's id, but only if that user actually exists.

    Several tables record who did something with a foreign key to `users`. An id
    that names nobody would fail that constraint deep inside a service and
    surface as a 500 — "something went wrong on the server" — for what is really
    "the id you sent is not a user here".

    Treating an unknown id as anonymous instead means the action still happens
    and is simply recorded as having no named actor, which is the honest reading
    of a caller who could not be identified. Nothing about permissions depends on
    it: the ROLE decides what may be done, and the role is unaffected.
    """
    if user_id is None or not settings.has_database:
        return None
    try:
        from backend.db.engine import get_session
        from backend.db.models import User

        with get_session() as session:
            return user_id if session.get(User, user_id) is not None else None
    except Exception as e:  # pragma: no cover - the database went away
        logger.warning("Could not confirm user %s: %s", user_id, e)
        return None


def require(allowed: frozenset[Role]):
    """Dependency factory: refuse a caller without one of these roles."""

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has(allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "forbidden",
                    "message": (
                        f"This action requires one of: "
                        f"{', '.join(sorted(r.value for r in allowed))}. "
                        f"You are {principal.role.value}."
                    ),
                },
            )
        return principal

    return dependency


RequireDataSteward = Depends(require(WRITE_DATA_BUILDER))
RequirePublisher = Depends(require(PUBLISH_DATASET))
RequireAnalyst = Depends(require(RUN_ANALYSIS))
RequireAdmin = Depends(require(MANAGE_MODELS))
#: Everybody signed in, including a Viewer. Comments and workflow replies only.
RequireCommenter = Depends(require(COMMENT))

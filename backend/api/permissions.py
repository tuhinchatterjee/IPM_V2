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

from fastapi import Depends, Header, HTTPException, status

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
READ_ONLY = frozenset({Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST, Role.VIEWER})


@dataclass(frozen=True)
class Principal:
    """Who is calling. Trusted only as far as the note above allows."""

    user_id: int | None
    role: Role

    def has(self, allowed: frozenset[Role]) -> bool:
        return self.role in allowed


def current_principal(
    x_ipm_role: str | None = Header(default=None, alias="X-IPM-Role"),
    x_ipm_user_id: int | None = Header(default=None, alias="X-IPM-User-Id"),
) -> Principal:
    """Resolve the caller.

    Defaults to ADMIN because the API has no authentication yet. This is the one
    line that changes when real sessions arrive.
    """
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
    return Principal(user_id=x_ipm_user_id, role=role)


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

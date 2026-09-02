"""What a person has chosen about how the product looks to them.

Presentation only. Every route here reads and writes the CALLING user's own
preferences — there is no user id in any path, because a preference is not
something one account sets for another, and a route that accepted one would be
a route somebody could use to change what a colleague's screen says.

Nothing here touches identity. The greeting name is what the Cockpit prints; the
account, the role, the permissions and the audit trail are unchanged by it, and
`tests/api/test_preferences.py` asserts exactly that.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireCommenter
from backend.config import settings
from backend.services import preferences as prefs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/preferences", tags=["preferences"])


class GreetingIn(BaseModel):
    greeting_name: str = Field(
        ..., description="What the Cockpit should greet this person by.")


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "storage_unavailable",
                "message": "Preferences need PostgreSQL."},
    )


def _signed_out() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "not_signed_in",
                "message": "A preference belongs to an account, so this needs "
                           "somebody signed in."},
    )


@router.get("", summary="This person's presentation preferences")
def read_preferences(principal: Principal = RequireCommenter) -> dict:
    """The calling user's preferences, with defaults filled in.

    Never fails because nothing has been stored: a user who has not opened the
    personalisation control has the defaults, which IS their preference until
    they say otherwise.
    """
    if not settings.has_database:
        # The defaults do not need a database, and a Cockpit that cannot greet
        # anybody because a preference store is down is a worse product than
        # one that greets them by the default name.
        return prefs.read(None, None)
    from backend.db.engine import get_session

    with get_session() as session:
        return prefs.read(session, principal.user_id)


@router.put("/greeting-name", summary="Change how the Cockpit greets you")
def set_greeting_name(payload: GreetingIn,
                      principal: Principal = RequireCommenter) -> dict:
    if principal.user_id is None:
        raise _signed_out()
    if not settings.has_database:
        raise _unavailable()
    from backend.db.engine import get_session

    with get_session() as session:
        try:
            return prefs.set_greeting_name(session, principal.user_id,
                                           payload.greeting_name)
        except prefs.PreferenceRejected as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error": "rejected", "message": str(e)}) from e


@router.delete("/greeting-name", summary="Go back to the default greeting")
def reset_greeting_name(principal: Principal = RequireCommenter) -> dict:
    if principal.user_id is None:
        raise _signed_out()
    if not settings.has_database:
        raise _unavailable()
    from backend.db.engine import get_session

    with get_session() as session:
        return prefs.clear_greeting_name(session, principal.user_id)

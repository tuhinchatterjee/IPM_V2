"""Per-user presentation preferences, which are never per-user identity.

The distinction this module exists to hold
------------------------------------------
The Cockpit greets somebody by name. Which name that is, is a matter of taste:
"Mr. Sajid", "Dr. Ahmed", "Corporate Risk Team". Who they ARE is not — it is
the authenticated account, and it decides permissions, ownership, approval
authority and every line of the audit trail.

Those two must never be the same field. A greeting stored on the user record
means changing what the screen says changes who the system thinks you are, and
a Trace that records the name somebody typed into a settings box is not an
audit trail. So the greeting lives here, in a preference, and `Account` — the
identity — is not touched by anything in this file.

What a preference is allowed to be
----------------------------------
Text a person will read, and nothing else. It is rendered as plain text, so
markup and control characters are rejected at the door rather than escaped on
the way out: a value that cannot be stored cannot be mis-rendered later by a
surface that forgot to escape it.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

PREFERENCES_VERSION = "1.0.0"

#: The key the greeting name is stored under, inside `user_preferences.
#: preferences`. Namespaced by intent — `cockpit.` — so a later preference on
#: another surface cannot collide with it.
GREETING_NAME = "cockpit.greeting_name"

#: What the Cockpit says when nobody has chosen anything. Configured for this
#: installation; a different deployment changes this one line.
DEFAULT_GREETING_NAME = "Mr. Sajid"

#: Long enough for "Corporate Risk Team" and a title, short enough that the
#: Cockpit heading cannot be turned into a paragraph.
MAX_LENGTH = 48

#: Characters that have no business in a name a screen will render. Control
#: characters, and the markup delimiters — a preference is plain text, and a
#: value carrying a tag is a value somebody intended to be interpreted.
_UNSAFE = re.compile(r"[\x00-\x1f\x7f<>{}\\]|&#|&[a-zA-Z]+;|javascript:", re.I)

#: A name is letters, marks, digits and the punctuation names actually use:
#: the full stop in "Mr.", the hyphen in "Al-Rashid", the apostrophe in
#: "O'Brien", and spaces between words.
_ALLOWED = re.compile(r"^[^\W\d_][\w .'\-]*$", re.UNICODE)


class PreferenceRejected(ValueError):
    """The value cannot be stored. The message is shown to the user."""


def clean_greeting_name(raw: Any) -> str:
    """The greeting name as it will be stored, or a reason it will not be.

    Whitespace is trimmed and collapsed, because "Mr.   Sajid" and "Mr. Sajid"
    are the same name and storing both makes two users who typed the same thing
    look different.
    """
    text = " ".join(str(raw or "").split())
    if not text:
        raise PreferenceRejected(
            "A greeting name cannot be empty. Use Reset to default to go back "
            f"to {DEFAULT_GREETING_NAME}.")
    if len(text) > MAX_LENGTH:
        raise PreferenceRejected(
            f"A greeting name can be at most {MAX_LENGTH} characters, and that "
            f"one is {len(text)}.")
    if _UNSAFE.search(text):
        raise PreferenceRejected(
            "A greeting name is shown as plain text, so it cannot contain "
            "markup or control characters.")
    if not _ALLOWED.match(text):
        raise PreferenceRejected(
            "A greeting name can use letters, spaces, and the full stop, "
            "hyphen and apostrophe that names contain — for example "
            "“Mr. Sajid”, “Dr. Ahmed” or “Corporate Risk Team”.")
    return text


# ------------------------------------------------------------------ storage


def _row(session: Any, user_id: int) -> Any:
    from backend.models.platform import UserPreference

    return session.get(UserPreference, user_id)


def read(session: Any, user_id: int | None) -> dict[str, Any]:
    """Every preference this user has set, with the defaults filled in.

    A user who has never opened the personalisation control has no row, and
    that is not an error: the defaults ARE the preference until somebody says
    otherwise.
    """
    stored: dict[str, Any] = {}
    if user_id:
        try:
            row = _row(session, int(user_id))
            if row is not None and isinstance(row.preferences, dict):
                stored = dict(row.preferences)
        except Exception as e:  # noqa: BLE001 - a missing table is not a failure
            logger.info("Could not read preferences for user %s: %s", user_id, e)
    name = str(stored.get(GREETING_NAME) or "").strip()
    return {
        "greeting_name": name or DEFAULT_GREETING_NAME,
        "greeting_name_is_default": not name,
        "default_greeting_name": DEFAULT_GREETING_NAME,
        "max_length": MAX_LENGTH,
    }


def set_greeting_name(session: Any, user_id: int, raw: Any) -> dict[str, Any]:
    """Store a greeting name. Returns the preferences as they now stand."""
    from backend.models.platform import UserPreference

    value = clean_greeting_name(raw)
    row = _row(session, int(user_id))
    if row is None:
        row = UserPreference(user_id=int(user_id), preferences={})
        session.add(row)
    # Replaced rather than mutated: SQLAlchemy does not see an in-place change
    # to a JSONB dict, and a preference that silently fails to persist is
    # worse than one that refuses to save.
    row.preferences = {**(row.preferences or {}), GREETING_NAME: value}
    session.commit()
    return read(session, user_id)


def clear_greeting_name(session: Any, user_id: int) -> dict[str, Any]:
    """Reset to the default, leaving every other preference alone."""
    row = _row(session, int(user_id))
    if row is not None and isinstance(row.preferences, dict):
        remaining = {k: v for k, v in row.preferences.items()
                     if k != GREETING_NAME}
        row.preferences = remaining
        session.commit()
    return read(session, user_id)


__all__ = [
    "DEFAULT_GREETING_NAME", "GREETING_NAME", "MAX_LENGTH",
    "PREFERENCES_VERSION", "PreferenceRejected", "clean_greeting_name",
    "clear_greeting_name", "read", "set_greeting_name",
]

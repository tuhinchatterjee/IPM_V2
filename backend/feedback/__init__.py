"""
The governed user-feedback learning loop. Part E, §148-§160.

    "unreviewed feedback never changes production behavior automatically"

``schema``      the Feedback object, its reasons, its privacy rules and the
                only transitions §155's loop permits.
``components``  which component a reason points at (a suggestion, never a
                verdict), and the two numbers that must never mix — what users
                did, and what evaluation established.
"""

from backend.feedback import components, schema

__all__ = ["components", "schema"]

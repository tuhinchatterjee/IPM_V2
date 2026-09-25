"""Per-book enablement, off by default, read nowhere else.

Section 2: *"Add feature flags separately for Corporate and Retail. Disabling
both must restore baseline behavior and routes."*

`V4Config` (`config.py:265-319`) is a frozen dataclass with fixed fields and no
open namespace, and its three `_flag` callers are global rather than per-book
(`config.py:379, 396, 404`). Adding a field to it would be a protected-core
change, so the flags live here and read the environment directly, the same way
`config._flag` does.

That makes "both off restores baseline" provable in the strongest way
available: not by a code path that checks a flag and does nothing, but because
nothing in the accepted runtime imports this package at all. With both flags
off there is no scenario code on any path, and `protected_hashes.py --check`
shows the accepted files are the accepted files.
"""

from __future__ import annotations

import os

from backend.cockpit_v4 import domains as dom

#: One variable per book. Named for the book, not numbered, because a reader
#: turning Retail on should not have to remember which of FLAG_1 and FLAG_2 it
#: is.
VARIABLES: dict[str, str] = {
    dom.CORPORATE: "COCKPIT_V4_WHATIF_CORPORATE",
    dom.RETAIL: "COCKPIT_V4_WHATIF_RETAIL",
}

#: The same truthy set `config._flag` uses, so an operator who has learned one
#: has learned both.
_TRUE = {"1", "true", "yes", "on"}


def enabled(domain_id: str) -> bool:
    """Is What-If on for this book?

    Unknown book is False rather than an error: a caller asking about a
    domain that does not exist has its answer, and raising here would turn a
    capability check into a failure mode.
    """
    variable = VARIABLES.get(str(domain_id or "").strip().lower())
    if not variable:
        return False
    return str(os.environ.get(variable, "")).strip().lower() in _TRUE


def any_enabled() -> bool:
    """True when at least one book has it on."""
    return any(enabled(d) for d in VARIABLES)


def status() -> dict[str, object]:
    """What a readiness answer says about itself, before anything is run.

    Section 2 asks that the chat be able to say which methods and mappings are
    available before the user confirms execution. This is the flag half of
    that; method readiness is `methods.readiness()`.
    """
    return {
        "books": {d: enabled(d) for d in VARIABLES},
        "variables": dict(VARIABLES),
        "any": any_enabled(),
        "note": (
            "What-If is off unless a book's variable is set. With both off "
            "nothing in this package is imported by the accepted runtime, so "
            "baseline behaviour is not merely restored -- it is untouched."),
    }


__all__ = ["VARIABLES", "any_enabled", "enabled", "status"]

"""
The Analysis Studio's operations, above HTTP and below the API.

The flow a person actually goes through:

    describe → CreditProbe reads it back → answer what it could not decide
    → build → validate → certify

Each step is a function here, and each one refuses rather than degrades. A
description that is not understood produces a question, not a guess. A method
whose validation pack has not passed cannot be certified, whoever is asking.
Certification is the only irreversible-feeling act in the Studio, so it is the
one with the narrowest gate.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from backend.studio.builder import Reading, build_method, read_description
from backend.studio.model import CERTIFIED_STATES, Lifecycle, MethodDefinition
from backend.studio.registry import MethodNotFound, Registry, get_registry
from backend.studio.validation import ValidationPack, build_forward_rate_pack, run_pack

logger = logging.getLogger(__name__)


class StudioError(ValueError):
    """Something the Studio refuses to do, with the reason attached."""


def describe(text: str) -> Reading:
    """Read a description and work out what still has to be decided."""
    return read_description(text)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    return slug or "method"


def build(*, name: str, description: str, answers: dict[str, str],
          opening_period: str, closing_period: str,
          dataset: str = "portfolio_facility", author: str = "",
          method_id: str = "") -> tuple[MethodDefinition, ValidationPack]:
    """Build a method from a description and run its validation pack.

    Build and validate together, always. A method that exists but has never been
    run against anything is the state this product is trying to eliminate — the
    plausible calculation nobody checked.
    """
    reading = describe(description)
    if not reading.understood:
        raise StudioError(reading.note)

    unresolved = [c.id for c in reading.clarifications
                  if c.id not in answers and c.default == ""]
    if unresolved:
        raise StudioError(
            "These decisions change the answer and have not been made: "
            + ", ".join(unresolved))

    filled = {c.id: c.default for c in reading.clarifications if c.default}
    filled.update({k: v for k, v in answers.items() if v})

    try:
        method = build_method(
            id=method_id or slugify(name), name=name, description=description,
            reading=reading, answers=filled, opening_period=opening_period,
            closing_period=closing_period, dataset=dataset, author=author,
        )
    except ValueError as e:
        # The builder refuses what it cannot compute honestly — "default at any
        # point in the horizon" being the one that matters. Surfaced as-is:
        # the reason is the useful part.
        raise StudioError(str(e)) from e

    pack = run_pack(build_forward_rate_pack(method), method)
    method.test_cases = pack.cases
    if pack.all_passed:
        method.lifecycle = Lifecycle.VALIDATED
    method.updated_at = datetime.now(UTC).isoformat()
    return method, pack


def revalidate(method: MethodDefinition) -> ValidationPack:
    """Run the pack again — after an edit, or before a sign-off."""
    pack = run_pack(build_forward_rate_pack(method), method)
    method.test_cases = pack.cases
    method.updated_at = datetime.now(UTC).isoformat()
    return pack


def certify(method: MethodDefinition, *, by: str) -> MethodDefinition:
    """Award the tick, or refuse and say what is missing.

    `can_certify` reports every gap rather than the first, because somebody
    preparing a method for sign-off needs the whole list, not a queue of one
    rejection at a time.
    """
    if not by.strip():
        raise StudioError("Certification has to be attributed to somebody.")
    ok, missing = method.can_certify()
    if not ok:
        raise StudioError(
            "This method cannot be certified yet. It is missing: "
            + "; ".join(missing))
    method.lifecycle = Lifecycle.CERTIFIED
    method.certified_at = datetime.now(UTC).isoformat()
    method.certified_by = by
    method.updated_at = method.certified_at
    return method


def fork(source: MethodDefinition, *, name: str, by: str = "",
         method_id: str = "") -> MethodDefinition:
    """Copy a method so a bank can change it without touching the original.

    The fork starts as a DRAFT with no tick and no test results, however
    certified its parent was. Inheriting evidence for a method nobody has run is
    exactly how a certification claim becomes meaningless.
    """
    new_id = method_id or f"{slugify(name)}"
    if new_id == source.id:
        raise StudioError("A fork needs a different id from its source.")

    copy = MethodDefinition.from_dict(source.to_dict(full=True))
    copy.id = new_id
    copy.name = name
    copy.aliases = []
    copy.lifecycle = Lifecycle.DRAFT
    copy.version = "1.0.0"
    copy.versions = []
    copy.certified_at = ""
    copy.certified_by = ""
    copy.forked_from = source.id
    copy.source = "bank"
    copy.owner = by or source.owner
    copy.created_at = datetime.now(UTC).isoformat()
    copy.updated_at = copy.created_at
    for case in copy.test_cases:
        case.passed = None
        case.actual = {}
        case.note = ("Inherited from the source method and not yet run against "
                     "this fork.")
    return copy


def edit(method: MethodDefinition, changes: dict[str, Any], *,
         change_note: str, by: str = "") -> tuple[MethodDefinition, list[str]]:
    """Apply an edit, recording the previous version if one was certified.

    Returns the method and a plain-English diff, because "what changed" is the
    question asked of an edited method and reading two JSON documents is not an
    answer.
    """
    editable = {
        "name", "definition", "purpose", "methodology", "when_to_use",
        "when_not_to_use", "interpretation", "limitations", "output_type",
        "aliases", "applicable_segments", "weighting_options", "owner",
    }
    rejected = set(changes) - editable
    if rejected:
        raise StudioError(
            "These are computed from the plan and cannot be edited as prose: "
            + ", ".join(sorted(rejected)))

    diff: list[str] = []
    for key, value in changes.items():
        before = getattr(method, key)
        if before == value:
            continue
        diff.append(f"{key}: {_short(before)} → {_short(value)}")
        setattr(method, key, value)

    if not diff:
        return method, []

    if method.lifecycle in CERTIFIED_STATES:
        # The signed-off version stays in the history exactly as it was. That is
        # the whole reason for keeping versions rather than a modified date.
        method.bump(change_note=change_note or "; ".join(diff), by=by,
                    lifecycle=Lifecycle.DRAFT)
    else:
        method.updated_at = datetime.now(UTC).isoformat()
    return method, diff


def _short(value: Any, limit: int = 60) -> str:
    text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------- persistence


def save(method: MethodDefinition, *, user_id: int | None = None) -> bool:
    """Store the method and put it in the live registry.

    Registers either way. A Studio running without a database is still usable
    for the length of a session, and the caller is told the difference so the UI
    can say "saved" or "saved for this session only" honestly.
    """
    from backend.services.studio import persist

    method.source = "bank"
    stored = persist(method, user_id=user_id)
    get_registry().register(method)
    return stored


def load(method_id: str, *, registry: Registry | None = None) -> MethodDefinition:
    try:
        return (registry or get_registry()).get(method_id)
    except MethodNotFound as e:
        raise StudioError(str(e)) from e


__all__ = ["StudioError", "build", "certify", "describe", "edit", "fork",
           "load", "revalidate", "save", "slugify"]

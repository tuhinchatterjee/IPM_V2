"""
Where Cockpit V2 meets the existing answer paths. Brief §7.3, §9.

The Cockpit is reached two ways, and both have to carry the V2 answer or the
browser sees one thing and the API another:

* `POST /api/v1/ask` — the direct API surface;
* `POST /api/v1/investigations` and `.../messages` — what the Cockpit's own
  composer actually calls. The first browser run of the UAT found this the hard
  way: `/ask` had been wired, the screen had not, and the Cockpit still showed
  the base build's clarification about horizons.

`apply` mutates the `Investigation` BEFORE it is serialised, so the stored
message, the thread's memory, the API response and the screen all carry the
same narrative. Wiring it at each call site's response dict instead would have
stored one answer and rendered another.

Everything here is a no-op when the switch is off: `answer_for` returns None on
its first line and the caller's own path stands exactly as it did on the base
commit.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def answer_for(question: str, principal: Any, *,
               turns: list[dict[str, Any]] | None = None,
               clarification: str = "", to_period: str = "",
               from_period: str = "") -> dict[str, Any] | None:
    """The Cockpit V2 answer, or None to leave the question to the base path."""
    try:
        from backend.cockpit_v2 import service
    except Exception:  # noqa: BLE001 - a partial deployment is not an error
        return None
    try:
        return service.answer(question, principal, turns=turns,
                              clarification=clarification,
                              to_period=to_period, from_period=from_period)
    except Exception as e:  # noqa: BLE001 - the base path still answers
        logger.warning("Cockpit V2 could not answer: %s", e)
        return None


def apply(investigation: Any, v2: dict[str, Any]) -> bool:
    """Make the V2 answer the canonical narrative on this investigation.

    The deterministic table, plan, steps and Trace are left exactly as they
    are — they are what the prose describes and brief §7.3 is explicit that
    they must not change. What changes is which prose the reader sees, and
    `narrative.prose_source` records it.

    A V2 answer also SETTLES the turn: an investigation the base path wanted to
    ask a clarification about is answered, so `status` moves off
    `needs_clarification` and the clarification is dropped. Leaving it would
    show the reader a question and an answer to it at the same time.
    """
    # A V2 answer that could not answer is still a V2 answer: the turn belongs
    # to it and the gap it states is the response. Handing the turn back would
    # let the base path answer a different question instead.
    if not v2 or not (v2.get("direct_answer") or v2.get("unanswered")):
        return False
    if not v2.get("direct_answer"):
        return False
    narrative = getattr(investigation, "narrative", None)
    if narrative is None:
        return False

    narrative.direct_answer = v2["direct_answer"]
    narrative.summary = v2["direct_answer"]
    narrative.interpretation = v2.get("narrative", "")
    narrative.interpretation_points = list(v2.get("findings", []))
    for limitation in v2.get("limitations", []):
        if limitation not in narrative.caveats:
            narrative.caveats.append(limitation)
    narrative.prose_source = v2.get("prose_source", "deterministic_v2")
    narrative.prose_fallback_reason = v2.get("fallback_reason", "")

    # Carried on the investigation itself, so the stored turn and a page
    # reload serialise the same thing the first response did.
    try:
        investigation.cockpit_v2 = dict(v2)
    except Exception:  # noqa: BLE001 - an older Investigation shape still works
        logger.debug("This Investigation cannot carry the V2 payload")

    if getattr(investigation, "status", "") == "needs_clarification":
        investigation.status = "succeeded"
        investigation.clarification = None
        # The deterministic path's own account of the turn said it stopped to
        # ask. It did not: V2 answered. Leaving those behind showed the reader
        # an amber "stopped to ask" banner directly above a complete answer.
        plan = getattr(investigation, "plan", None)
        notes = getattr(plan, "notes", None)
        if isinstance(notes, list):
            notes[:] = [n for n in notes
                        if "stopped to ask" not in str(n).lower()]
        compound = getattr(investigation, "compound", None)
        if isinstance(compound, dict):
            compound.clear()

    # The deterministic layer's coverage note describes ITS reading of the
    # question, not V2's. "The coverage of this request could not be
    # established" sat above a complete, reconciled answer.
    compound = getattr(investigation, "compound", None)
    if isinstance(compound, dict) and compound.get("why"):
        compound.pop("why", None)

    # When V2 took the turn but could NOT answer — an unpublished quarter, a
    # scope it may not read — the deterministic figures underneath it answer a
    # DIFFERENT question, and leaving them on screen recreates the substitution
    # the gap statement exists to prevent. The browser showed "Q4 2019 is not
    # loaded" directly above a Q1-to-Q2 comparison of the other book.
    answered_something = any(section.get("answered")
                             for section in (v2.get("sections") or []))
    if not answered_something:
        narrative.metrics = []
        narrative.findings = []
        narrative.drivers = []
        steps = getattr(investigation, "steps", None)
        if isinstance(steps, list):
            steps.clear()
    return True


def attach(payload: dict[str, Any], v2: dict[str, Any] | None) -> dict[str, Any]:
    """Put the V2 answer on a serialised run, for the screen to render."""
    if v2:
        payload["cockpit_v2"] = v2
    return payload


def record_prose_source(payload: dict[str, Any]) -> None:
    """Stamp which path wrote the visible prose. Runs on EVERY response.

    Including the flag-off one, so the field is always present and always
    honest rather than appearing only when V2 is on. When the analyst answered
    and nothing has overridden it, the analyst's own prose becomes the visible
    narrative — the precedence the original Phase 1 review asked for, in the
    direction the code actually needed.
    """
    narrative = payload.get("narrative")
    if not isinstance(narrative, dict):
        return
    if narrative.get("prose_source") not in (None, "", "deterministic"):
        return

    analyst = payload.get("analyst") or {}
    try:
        from backend.analyst import route as analyst_route
        from backend.analyst import session as analyst_session

        answered = (analyst.get("path") == analyst_route.ANALYST
                    and analyst.get("outcome") == analyst_session.ANSWER
                    and analyst.get("answer"))
    except Exception:  # noqa: BLE001 - a partial deployment is not an error
        answered = False

    if answered:
        narrative["direct_answer"] = analyst["answer"]
        narrative["summary"] = analyst["answer"]
        narrative["interpretation_points"] = list(analyst.get("findings") or [])
        narrative["prose_source"] = "analyst"
        narrative["prose_fallback_reason"] = ""
        return

    narrative["prose_source"] = narrative.get("prose_source") or "deterministic"
    narrative["prose_fallback_reason"] = (
        analyst.get("why") or analyst.get("why_fallback") or "")


__all__ = ["answer_for", "apply", "attach", "record_prose_source"]

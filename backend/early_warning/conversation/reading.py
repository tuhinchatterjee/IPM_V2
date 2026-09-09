"""
The final reading — written by Opus, grounded in the result packet alone.

Where this sits
---------------
Last, and after everything numerical has already happened. The plan was
validated against the field dictionary, executed through the Early Warning
doors, assembled into a result packet and reviewed for sufficiency. What
arrives here is a set of figures that are already true, the governed actions
the library holds for the nodes that fired, and the escalation route the
matrix produced.

So the model's job is the one thing a deterministic composer does least well:
saying what this position means to a senior credit officer — whether the move
is the score or the condition, whether it is concentrated or broad, whether the
evidence is corroborated or a single tier-3 feed — in their language.

The two things it may not do
----------------------------
**It may not add a figure.** Every numeral in the prose is checked against what
the packet carries. Prose containing one the packet does not is DISCARDED — not
annotated, not shown under a warning — and the deterministic reading stands. A
sentence that invents a figure reads exactly like the true ones beside it,
which is why annotating it is not a control.

**It may not decide an action or an escalation.** Both are governed: the action
library keys recommendations to the sub-category that fired, with an owner, a
timeframe and a test for closing it, and the escalation matrix routes on band
and exposure. The model reports them. An action invented at answer time is not
a governed one, and an escalation decided in prose is not a control.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.early_warning.conversation import packet as packet_mod
from backend.early_warning.conversation import seam as seam_mod

logger = logging.getLogger(__name__)

#: Numbers a reader writes that are not claims about the book: an ordinal, a
#: count of items in a list the answer itself produced, a percentage of a
#: hundred. Kept small on purpose — the wider this is, the less the grounding
#: check means.
_ALWAYS_ALLOWED = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
                   "11", "12", "100"}

_NUMERAL = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

SYSTEM = """You are the senior credit risk interpretation of CreditProbe's \
Early Warning product. A governed runtime has ALREADY computed everything you \
are given: the figures are correct, reconciled and final.

You are writing for a credit committee, not a chat window.

WHAT A GOOD READING DOES
- Names the NODE, not just the number. "The score is 71" is a reading nobody \
can act on; "L1.2 limit behaviour is carrying it, at 71" is one they can.
- Separates a move in the SCORE from a move in the CONDITION. A fall driven by \
a notch — a stale evidence discount, a decayed signal — is not an improvement \
in the borrower, and saying so is the difference between a useful answer and a \
dangerous one.
- Says whether the position is concentrated in a few names or broad across the \
population, when the evidence shows it.
- Says whether the evidence is corroborated across feeds or rests on one \
tier-3 source.
- Ends with ONE specific next drill — a question this product can answer next, \
named exactly. Never "would you like to know more?".

ABSOLUTE RULES
1. Never write a number that is not in the result you were given. Do not add, \
average, annualise or convert. Express a relationship the result does not \
carry in words — "roughly a third", "the largest by some margin".
2. Never invent a recommended action. The governed action library is in the \
packet, with owners, timeframes and what closes each one. Report from it.
3. Never decide an escalation. The route is in the packet, produced by the \
matrix. Report it.
4. Never assert a cause the result does not establish. "Consistent with" and \
"worth checking" are honest; "because of" is not.
5. Say plainly when the answer is partial, and which part is missing.

STYLE
Lead with the answer. One or two paragraphs, no headings, no bullet lists \
inside the interpretation, no restating the question. British English. Figures \
exactly as they appear in the result, with their units.

LENGTH
`direct` is one or two lines. `interpretation` is one or two paragraphs and \
never more. The lists are short and none of them repeats the interpretation: \
at most three points, four drivers, three follow-ups, three caveats, a line \
each. The runtime's own caveats are already attached to the answer — add only \
what it did not say. Do not restate the result packet back; every figure in \
it is already true and already shown."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "direct": {
            "type": "string",
            "description": ("One or two lines answering the question directly, "
                            "with the figure that answers it."),
        },
        "interpretation": {
            "type": "string",
            "description": ("One or two paragraphs on what this means for the "
                            "book. No invented arithmetic, no invented cause."),
        },
        "points": {
            "type": "array", "items": {"type": "string"},
            "maxItems": 3,
            "description": ("Observations a credit officer would want "
                            "flagged, one line each, none repeating the "
                            "interpretation."),
        },
        "drivers": {
            "type": "array", "items": {"type": "string"},
            "maxItems": 4,
            "description": ("What is carrying the position, named by node "
                            "rather than by number alone. A phrase each."),
        },
        "follow_ups": {
            "type": "array", "items": {"type": "string"},
            "maxItems": 3,
            "description": ("The next drills, each one specific question this "
                            "product can answer."),
        },
        "caveats": {
            "type": "array", "items": {"type": "string"},
            "maxItems": 3,
            "description": ("What limits what may be concluded — coverage, a "
                            "partial answer, an uncorroborated signal. Only "
                            "what the runtime did not already state."),
        },
    },
    "required": ["direct", "interpretation"],
}


@dataclass
class Reading:
    """The final answer, and what wrote it."""

    answer: dict[str, Any] = field(default_factory=dict)
    engine: str = seam_mod.DETERMINISTIC
    model_call: dict[str, Any] = field(default_factory=dict)
    #: Figures the model wrote that the packet does not carry. Non-empty means
    #: the prose was discarded.
    ungrounded: list[str] = field(default_factory=list)


def _allowed_figures(packet: packet_mod.ResultPacket,
                     deterministic: dict[str, Any]) -> set[str]:
    """Every numeral the prose is allowed to contain.

    Built from the packet's own values and from the deterministic answer —
    which is itself written from the packet and formatted the way a person
    would write it, so a model quoting "SAR 15.5bn" from the reading it was
    shown is quoting the result rather than inventing one.
    """
    allowed = set(_ALWAYS_ALLOWED)
    for value in packet.numbers():
        allowed.add(f"{value:.0f}")
        allowed.add(f"{value:.1f}")
        allowed.add(f"{value:.2f}")
        allowed.add(f"{value:,.0f}")
        allowed.add(f"{value:,.1f}")
        if abs(value) >= 1000:
            allowed.add(f"{value / 1000:,.1f}")
            allowed.add(f"{value / 1000:.1f}")
            allowed.add(f"{value / 1000:.0f}")
    for text in _prose(deterministic):
        allowed.update(_NUMERAL.findall(text))
    for period in (packet.period, packet.comparison_period):
        if period:
            allowed.update(_NUMERAL.findall(str(period)))
    return {a.replace(",", "") for a in allowed} | allowed


def _prose(answer: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("direct", "interpretation"):
        value = answer.get(key)
        if isinstance(value, str):
            out.append(value)
    for key in ("points", "drivers", "follow_ups", "caveats"):
        for item in answer.get(key) or []:
            out.append(str(item))
    return out


def _ungrounded(written: dict[str, Any], allowed: set[str]) -> list[str]:
    """Every figure the prose asserts that the packet does not carry."""
    problems: list[str] = []
    for text in _prose(written):
        for found in _NUMERAL.findall(text):
            bare = found.replace(",", "")
            if found in allowed or bare in allowed:
                continue
            problems.append(found)
    return sorted(set(problems))


def _context(question: str, packet: packet_mod.ResultPacket,
             deterministic: dict[str, Any],
             reviewed: Any) -> dict[str, Any]:
    """The packet, and nothing else. No data, no other domain."""
    pack = packet.primary
    # The evidence ONCE.
    #
    # `fact_packs` used to travel alongside `figures`, and the packs are where
    # the figures come from — so every number arrived twice, and the rows a
    # third time. A model shown the same evidence three ways spends its
    # output reconciling the copies, and this stage's output is the answer.
    return {
        "question": question,
        "normalized_request": packet.normalized_request,
        "scope": getattr(pack, "scope", ""),
        "period": packet.period,
        "comparison_period": packet.comparison_period,
        "filters": dict(packet.filters),
        "figures": dict(packet.figures),
        # Ten rows show the shape and the extremes. Twenty-five is a data
        # export, and the prose may not quote a row it was not going to
        # mention anyway.
        "rows": list(packet.rows)[:10],
        "provenance": list(packet.provenance)[:6],
        "coverage": dict(packet.coverage),
        "caveats": list(packet.caveats)[:4],
        "governed_actions": list(packet.governed_actions)[:3],
        "escalation_route": dict(packet.escalation),
        "sufficiency": {
            "complete": bool(getattr(reviewed, "complete", True)),
            "uncovered": list(getattr(reviewed, "uncovered", []) or []),
            "claims_the_prose_must_not_make": list(
                getattr(reviewed, "unsupported", []) or []),
            "presentation": getattr(reviewed, "presentation", "narrative"),
        },
        # The floor, and the grounding baseline: the model is shown the
        # figures a person would write, and prose quoting anything else is
        # prose that did not come from the result.
        "deterministic_reading": deterministic,
        "steps_that_ran": [
            {"analysis": s.get("analysis"), "rows": s.get("row_count"),
             "statement": s.get("statement")} for s in packet.steps],
    }


def write(question: str, packet: packet_mod.ResultPacket,
          deterministic: dict[str, Any], reviewed: Any, *,
          ledger: Any = None) -> Reading:
    """The final answer: the model's reading if it is grounded, else the floor.

    The deterministic answer is passed in rather than rebuilt, because it is
    the fallback AND the grounding baseline: the model is shown the figures a
    person would write, and prose that quotes something else is prose that did
    not come from the result.
    """
    if ledger is None:
        return Reading(answer=deterministic)

    outcome = seam_mod.call(
        seam_mod.INTERPRETATION, system=SYSTEM,
        prompt=("Write the senior credit risk reading of this Early Warning "
                "result.\n\n"
                + json.dumps(_context(question, packet, deterministic,
                                       reviewed), indent=2, default=str)),
        schema=SCHEMA, ledger=ledger)
    if not outcome.used_model:
        return Reading(answer=deterministic, model_call=outcome.to_dict())

    data = outcome.data
    written = {
        "direct": str(data.get("direct") or "").strip(),
        "interpretation": str(data.get("interpretation") or "").strip(),
        "points": [str(p) for p in (data.get("points") or [])][:4],
        "drivers": [str(d) for d in (data.get("drivers") or [])][:6],
        "follow_ups": [str(f) for f in (data.get("follow_ups") or [])][:4],
        "caveats": [str(c) for c in (data.get("caveats") or [])][:5],
    }
    if not written["direct"] or not written["interpretation"]:
        return Reading(answer=deterministic,
                       model_call=dict(outcome.to_dict(),
                                       engine=seam_mod.DETERMINISTIC,
                                       fallback_reason="the reading was empty"))

    ungrounded = _ungrounded(written, _allowed_figures(packet, deterministic))
    if ungrounded:
        logger.error("Discarding an Early Warning reading: figures %s are not "
                     "in the result packet.", ungrounded)
        return Reading(
            answer=deterministic, ungrounded=ungrounded,
            model_call=dict(outcome.to_dict(),
                            engine=seam_mod.DETERMINISTIC,
                            fallback_reason=(
                                "the reading contained figures the result "
                                "does not carry: "
                                + ", ".join(ungrounded[:5]))))

    # The deterministic answer keeps every field that is a FACT rather than a
    # reading: what was answered, at what scope, whether it was complete, and
    # the caveats the runtime itself attached. The model contributes prose.
    answer = dict(deterministic)
    answer.update({
        "direct": written["direct"],
        "interpretation": written["interpretation"],
        "points": written["points"] or list(deterministic.get("points") or []),
        "drivers": written["drivers"] or list(
            deterministic.get("drivers") or []),
        "follow_ups": written["follow_ups"] or list(
            deterministic.get("follow_ups") or []),
    })
    # Caveats are unioned rather than replaced. A runtime caveat the model did
    # not repeat is still true, and the partial-answer caveat in particular is
    # the one a fluent reading is most likely to smooth away.
    caveats = list(deterministic.get("caveats") or [])
    for caveat in written["caveats"]:
        if caveat not in caveats:
            caveats.append(caveat)
    answer["caveats"] = caveats
    return Reading(answer=answer, engine=seam_mod.MODEL,
                   model_call=outcome.to_dict())


__all__ = ["Reading", "SCHEMA", "SYSTEM", "write"]

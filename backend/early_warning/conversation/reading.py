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

from backend.early_warning.conversation import derivation as dv
from backend.early_warning.conversation import packet as packet_mod
from backend.early_warning.conversation import seam as seam_mod

logger = logging.getLogger(__name__)

#: Numbers a reader writes that are not claims about the book: an ordinal, a
#: count of items in a list the answer itself produced, a percentage of a
#: hundred. Kept small on purpose — the wider this is, the less the grounding
#: check means.
_ALWAYS_ALLOWED = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
                   "11", "12", "100"}

#: A published month, as `YYYY-MM`. Matched and set aside BEFORE any numeral
#: scanning, because a date is one token and not three.
#:
#: Without this, "2026-06," gave the numeral scanner `-06,` — the hyphen read
#: as a minus sign, the trailing comma swallowed — and a reading that quoted
#: its own period correctly was discarded for citing a figure of minus six.
_PERIOD_TOKEN = re.compile(r"\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])\b")

#: A figure the prose STATES.
#:
#: The lookbehind refuses any word character, not merely a digit, and that is
#: the whole of it. A hyphen between two word characters is a hyphen: `top-5`
#: is five names and `tier-3` is a source tier, and a scanner that reads them
#: as minus five and minus three reports true prose for quoting figures nobody
#: computed — which is how a live reading was discarded for writing the phrase
#: this module's own system prompt asks it to write.
#:
#: The same lookbehind keeps a node code out of the figure stream. `L1` is a
#: layer and `L1.2` is a sub-category; read as 1 and 1.2 they are figures the
#: packet has no reason to carry, and naming the node is exactly what a good
#: reading does.
#:
#: The trailing lookbehind stops the match ending on a separator — `1,049` is
#: one figure, `049,` is not a figure at all.
_NUMERAL = re.compile(r"(?<![\w.,\-])-?\d[\d,]*(?:\.\d+)?(?<![.,])")

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
1. Never write a number that is not in the result you were given, unless you \
DECLARE it (rule 1a). Do not annualise, convert, or estimate.
1a. ARITHMETIC MUST BE DECLARED. You may state a figure the result implies — a \
total, a difference, a share, the size of a signed move — only by listing it in \
`derived_claims`, naming the exact result fields it came from and which of \
these operations produced it: sum, difference, delta, product, ratio, share, \
percent, mean, magnitude, minimum, maximum, count. The runtime recomputes every \
one of them from the result itself and DISCARDS your whole reading if its \
answer differs from yours, so declare only arithmetic you are certain of, and \
express anything else in words — "roughly a third", "the largest by some \
margin". A movement stored as a negative number is the commonest case: to \
write "fell 11.31 points" from `movement.ews_change: -11.31`, declare \
{"value": 11.31, "op": "magnitude", "refs": ["movement.ews_change"]}.
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
        "derived_claims": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "number",
                        "description": "The figure exactly as your prose writes it.",
                    },
                    "op": {
                        "type": "string",
                        "enum": sorted(dv.OPERATIONS),
                        "description": "The operation the runtime should apply.",
                    },
                    "refs": {
                        "type": "array", "items": {"type": "string"},
                        "maxItems": 8,
                        "description": ("The result fields it is computed from, "
                                        "in order — for example "
                                        "\"movement.ews_change\" or "
                                        "\"rows[0].exposure\"."),
                    },
                },
                "required": ["value", "op", "refs"],
            },
            "description": ("Every figure in your prose that the result implies "
                            "rather than states outright. The runtime "
                            "recomputes each one and discards the reading if it "
                            "disagrees."),
        },
        "fact_refs": {
            "type": "array", "items": {"type": "string"},
            "maxItems": 8,
            "description": ("The names of the result fields your figures came "
                            "from, exactly as they are spelled in `figures` — "
                            "for example \"exposure\", \"high_plus_count\". "
                            "One per figure you quote."),
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
    #: The result fields the reading says its figures came from, kept where
    #: they resolve to something the packet actually holds.
    fact_refs: list[str] = field(default_factory=list)
    #: Names it gave that resolve to nothing. Recorded rather than fatal: the
    #: numeric check is what rejects a reading, and a mistyped field name on a
    #: reading whose every figure IS in the packet is a bookkeeping slip, not
    #: an invented number. It is on the trace so a pattern of them is visible.
    unresolved_refs: list[str] = field(default_factory=list)
    #: Arithmetic the reading declared, each one recomputed by the server. An
    #: accepted claim permits its figure; a refused one permits nothing and
    #: the figure falls through to the direct check.
    derived_claims: list[dict[str, Any]] = field(default_factory=list)


#: The sections of the interpretation packet whose numerals the reading may
#: cite — the user's request, the scope, the executed result, the governed
#: action and escalation metadata, and the periods.
#:
#: This is the whole control. The guard checks prose against what the writer
#: was ALLOWED to see, so anything in the packet that is not evidence is a
#: number the writer can read and must not use — and `_context` therefore
#: carries nothing else.
#:
#: The field dictionary's coverage summary is what taught us that. It said
#: 2,521 fields described, 1,049 fully populated, 1,179 empty; those are
#: statistics about the SCHEMA, not about the book, and a live Opus reading
#: quoted them into a credit paragraph. Planning needs them. The final answer
#: writer has no business with them, and `test_grounding.py` asserts that no
#: section outside this list ever reaches it.
CITABLE_SECTIONS: tuple[str, ...] = (
    "question", "normalized_request", "period", "comparison_period",
    "filters", "figures", "rows", "provenance", "caveats",
    "governed_actions", "escalation_route", "steps_that_ran",
    "deterministic_reading")

#: Sections that carry no figure at all — a scope label, a verdict, a
#: presentation choice. Listed so the contract test can tell "carries no
#: number" apart from "carries numbers nobody checked".
NON_NUMERIC_SECTIONS: tuple[str, ...] = ("scope", "sufficiency")


def _allowed_figures(packet: packet_mod.ResultPacket,
                     deterministic: dict[str, Any],
                     context: dict[str, Any] | None = None,
                     claims: list[dv.Claim] | None = None) -> set[str]:
    """Every numeral the prose is allowed to contain.

    Built from the packet's own values, from the deterministic answer — which
    is itself written from the packet and formatted the way a person would
    write it, so a model quoting "SAR 15.5bn" from the reading it was shown is
    quoting the result rather than inventing one — and from the citable
    sections of the packet the writer was given.

    That last part is the point. The allowed set is derived from what the
    writer may SEE, and `_context` puts nothing in front of it that is not
    evidence, so the two agree by construction rather than by a whitelist
    somebody has to remember to update. A figure the model produced from
    somewhere else is still rejected, which is the guard doing its job.
    """
    allowed = set(_ALWAYS_ALLOWED)
    for value in packet.numbers():
        allowed |= dv.spellings(value)
        # And its size. A movement is stored signed and written in words: the
        # packet holds `ews_change: -3.67` and every credit paragraph anybody
        # writes says "the score fell 3.67 points". Refusing that discarded
        # four true live readings for quoting figures the result was holding.
        #
        # This is a FIGURE guard and 3.67 is the packet's figure, so the size
        # is permitted here rather than made to travel through a declaration.
        # It does mean the guard alone cannot catch a reading that inverts a
        # direction — that is the composer's "It improved / It deteriorated"
        # verdict and the deterministic reading shown alongside, not this.
        if value < 0:
            allowed |= dv.spellings(-value)
    for claim in claims or []:
        if claim.accepted and claim.recomputed is not None:
            allowed |= dv.spellings(claim.recomputed)
    for text in _prose(deterministic):
        allowed.update(_NUMERAL.findall(text))
    for section in CITABLE_SECTIONS:
        value = (context or {}).get(section)
        if value is None:
            continue
        allowed.update(_NUMERAL.findall(
            json.dumps(value, default=str)))
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


def _ungrounded(written: dict[str, Any], allowed: set[str],
                periods: set[str]) -> list[str]:
    """Every figure the prose asserts that the packet does not carry.

    Periods are taken out first and checked as whole tokens. A month is one
    thing, and reading `2026-06` as a minus sign followed by six is how a
    reading that quoted its own period correctly came to be discarded.
    """
    problems: list[str] = []
    for text in _prose(written):
        # A month the answer names has to be a month the answer read. A
        # reading that quotes a period nobody published is as wrong as one
        # that quotes a figure nobody computed.
        for month in _PERIOD_TOKEN.findall(text):
            if month not in periods:
                problems.append(month)
        for found in _NUMERAL.findall(_PERIOD_TOKEN.sub(" ", text)):
            bare = found.replace(",", "")
            if found in allowed or bare in allowed:
                continue
            problems.append(found)
    return sorted(set(problems))


def _permitted_periods(packet: packet_mod.ResultPacket) -> set[str]:
    """The months this answer is allowed to name.

    The ones it read, and the ones the domain published. A period is a
    non-analytical reference and citable as such; a month nobody published is
    not a reference to anything.
    """
    months = {str(p) for p in (packet.period, packet.comparison_period) if p}
    for step in packet.steps:
        for key in ("period", "comparison_period"):
            value = step.get(key)
            if value:
                months.add(str(value))
        months.update(_PERIOD_TOKEN.findall(str(step.get("statement") or "")))
    try:
        from backend.early_warning import v2_service as svc

        months.update(str(p) for p in svc.periods())
    except Exception:  # noqa: BLE001 - an unreadable domain permits what it read
        pass
    return months


def _checked_refs(named: Any,
                  packet: packet_mod.ResultPacket) -> tuple[list[str],
                                                            list[str]]:
    """The result fields a reading says it drew on, checked against the packet.

    Structured grounding beside the numeric one: a reading that names
    `high_plus_count` can be traced back to the value it quoted, which a bare
    numeral cannot. Both are recorded; only the numeric check rejects, because
    a mistyped field name on a reading whose every figure IS in the packet is
    a bookkeeping slip rather than an invented number.
    """
    known = set(packet.figures)
    for row in packet.rows[:50]:
        known.update(str(k) for k in row)
    for action in packet.governed_actions:
        known.update(str(k) for k in action)
    known.update(str(k) for k in packet.escalation)

    resolved: list[str] = []
    unresolved: list[str] = []
    for name in (named or [])[:8]:
        text = str(name).strip()
        if not text:
            continue
        (resolved if text in known else unresolved).append(text)
    return resolved, unresolved


def _facts_of(packet: packet_mod.ResultPacket) -> dict[str, Any]:
    """The governed facts a declared derivation may be computed from.

    The same evidence the direct check is built from, under the names the
    reading is shown: `figures` at the top so `movement.ews_change` resolves,
    the rows it can see, the governed actions and the escalation route. Not
    the question, not the request text, not the deterministic prose — a
    derivation is arithmetic over RESULTS, and a number that only exists in a
    sentence is not a result.
    """
    return {
        **{str(k): v for k, v in packet.figures.items()},
        "figures": dict(packet.figures),
        "rows": list(packet.rows)[:10],
        "governed_actions": list(packet.governed_actions)[:3],
        "escalation_route": dict(packet.escalation),
        "steps": [{"analysis": s.get("analysis"),
                   "figures": s.get("figures"),
                   "row_count": s.get("row_count")}
                  for s in packet.steps],
    }


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
        # The field dictionary's coverage summary is NOT here, and that is
        # deliberate. It says how many of the 2,521 described fields are
        # populated — a statistic about the schema, not about the book — and
        # a live Opus reading quoted "1,049" and "2,521" into a credit
        # paragraph, where they meant nothing and were rightly discarded.
        # Planning needs those counts; the answer writer does not.
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

    context = _context(question, packet, deterministic, reviewed)
    outcome = seam_mod.call(
        seam_mod.INTERPRETATION, system=SYSTEM,
        prompt=("Write the senior credit risk reading of this Early Warning "
                "result.\n\n"
                + json.dumps(context, indent=2, default=str)),
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

    refs, unresolved = _checked_refs(data.get("fact_refs"), packet)
    periods = _permitted_periods(packet)
    # Arithmetic the reading declared, recomputed here from the packet's own
    # facts. The model named the fields and the operation; the server did the
    # sum. A claim it agrees with permits its figure, and one it does not
    # permits nothing.
    claims = dv.check(data.get("derived_claims"), dv.index(_facts_of(packet)))
    ungrounded = _ungrounded(
        written, _allowed_figures(packet, deterministic, context, claims),
        periods)
    declared = [c.to_dict() for c in claims]
    refused = [c for c in claims if not c.accepted]
    if refused:
        logger.warning(
            "An Early Warning reading declared arithmetic the runtime did not "
            "reproduce: %s", "; ".join(c.reason for c in refused[:3]))
    if ungrounded:
        logger.error("Discarding an Early Warning reading: figures %s are not "
                     "in the result packet.", ungrounded)
        return Reading(
            answer=deterministic, ungrounded=ungrounded, fact_refs=refs,
            unresolved_refs=unresolved, derived_claims=declared,
            model_call=dict(outcome.to_dict(),
                            engine=seam_mod.DETERMINISTIC,
                            derived_claims=declared,
                            # What it actually wrote. Not shown to the reader
                            # — that is the whole point of a discard — but on
                            # the trace, because "figures 11.31 and 3.67 were
                            # not in the packet" is a bare fact and the
                            # sentence they sat in is a diagnosis.
                            discarded_prose=" ".join(
                                _prose(written))[:1200],
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
    return Reading(answer=answer, engine=seam_mod.MODEL, fact_refs=refs,
                   unresolved_refs=unresolved, derived_claims=declared,
                   model_call=dict(outcome.to_dict(), fact_refs=refs,
                                   unresolved_refs=unresolved,
                                   derived_claims=declared))


__all__ = ["Reading", "SCHEMA", "SYSTEM", "write"]

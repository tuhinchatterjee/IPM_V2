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

from backend.early_warning import metrics as mt
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
1a. LOOK FOR THE FIGURE BEFORE YOU COMPUTE ONE. In this order, always:
   (i) a figure in `figures`, `rows` or the deterministic reading — quote it;
   (ii) a figure the runtime has already derived for you. It computes the \
common ones: each layer's `points_contributed` and `share_of_move_pct`, the \
`leading_layer_contribution`, `ews_change_size`, each group's \
`exposure_share_pct` and `obligor_share_pct`, and the improved / unchanged / \
worsened counts. `fact_index` lists every one of them by name with its value. \
Read it before you reach for arithmetic;
   (iii) only then, a declared derivation.
1b. ARITHMETIC MUST BE DECLARED, AND SIGNED. A figure the result implies \
rather than states goes in `derived_claims`: the value, one operation from the \
list, and the fields it came from. Two rules decide whether it is accepted.
   **The refs must be names from `fact_index`, exactly as spelled there.** \
That list is the whole vocabulary. A name not in it resolves to nothing and \
your claim is dropped — `rows` is not a fact, `rows[0].exposure` may be.
   **`value` is the exact SIGNED number the operation produces.** A fall is \
negative. Write {"value": -4.86, "op": "sum", "refs": \
["movement.layers.L1.points_contributed", \
"movement.layers.L4.points_contributed"]} and then say "together they took \
4.86 points off it" in the prose — the sentence may use the size, the claim \
may not.
   The runtime recomputes every claim and DISCARDS your whole reading if its \
answer differs, so declare only arithmetic you are certain of and express \
anything else in words: "roughly a third", "the largest by some margin".
1c. THE DIRECTION MUST MATCH THE FACT, AND YOU MUST SAY WHICH FACT. For the \
Early Warning score, UP is worse: a positive change is a deterioration and a \
negative one an improvement. Within one population the same size goes both \
ways — an obligor improving by 8.0 while five others deteriorate by 8.0 — so \
the figure alone cannot say which you mean. Every sentence that puts a figure \
on a direction goes in `movement_claims` with the fact it is about: \
{"fact_ref": "movement_census.largest_deterioration.change", "direction": \
"deteriorated", "value": 8.0}. The runtime reads that fact, applies the \
metric's own semantics and checks your wording against it. Saying \
"deteriorated" of a fact the result shows improving discards the reading, \
however correct the number.
1d. THE COUNTS AND THE EXTREMES ARE FACTS. `movement_census` carries \
`total`, `improved_count`, `held_count`, `deteriorated_count`, and \
`largest_improvement` and `largest_deterioration` with the obligor's name and \
signed change. Quote them. Do not count rows and do not pick an extreme out of \
a list.
1e. A FOLLOW-UP IS HELD TO THE SAME STANDARD as the answer. It may name a \
figure only if that figure is a fact you could cite, and it does not need one \
to be a good question: "Which six Contracting obligors deteriorated, and by \
how much?" is a better drill than the same question with a benchmark bolted \
on. Never manufacture a comparison to make a follow-up sound richer.
1f. DO NOT MAKE THE ANSWER MORE ARITHMETICAL THAN THE QUESTION. A subtotal or \
a complement that carries no decision — "SAR 6,301.85m of the SAR 6,460.56m in \
scope" — is a figure to get wrong for nothing. If the result gives you a share, \
say the share.
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
        "movement_claims": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "fact_ref": {
                        "type": "string",
                        "description": ("The movement fact this sentence is "
                                        "about, named exactly as `fact_index` "
                                        "spells it."),
                    },
                    "direction": {
                        "type": "string",
                        "enum": sorted(mt.DIRECTIONS),
                        "description": "Which way you said it went.",
                    },
                    "value": {
                        "type": "number",
                        "description": ("The figure your prose states for it, "
                                        "signed or as a size."),
                    },
                },
                "required": ["fact_ref", "direction"],
            },
            "description": (
                "Every sentence that says which WAY something moved and puts a "
                "figure on it. Name the fact and the runtime checks your "
                "wording against it: within one population an obligor can "
                "improve by 8.0 while five others deteriorate by 8.0, and the "
                "figure alone cannot tell them apart."),
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
    #: Movements the reading declared, each checked against its own fact.
    movement_claims: list[dict[str, Any]] = field(default_factory=list)
    #: Figures the prose stated the size of, with the wrong direction word.
    #: Every number in such a sentence is grounded and the sentence is still
    #: false, so this discards the reading exactly as an invented figure does.
    direction_conflicts: list[dict[str, Any]] = field(default_factory=list)
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
    #: One record per rejected figure: the token, the words either side of it,
    #: and what it was attached to. A bare list of numbers is not a diagnosis
    #: — a live case was rejected for `25` and working out what 25 meant took
    #: rebuilding the packet by hand, because the prose was truncated before
    #: the token appeared.
    rejected_context: list[dict[str, Any]] = field(default_factory=list)


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
    "deterministic_reading",
    # The fact index is the SAME evidence under the names a derived claim
    # must cite. Citable by construction: every value in it was read out of
    # the packet, so listing it here adds no figure the writer could not
    # already see in `figures` or `rows` — it names them.
    "fact_index")

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
            # And its size, on the same terms as a direct fact: a
            # contribution of -4.86 is "took 4.86 points off it" in the
            # sentence anybody writes. `_direction_conflicts` is what stops
            # that becoming "added 4.86".
            if claim.recomputed < 0:
                allowed |= dv.spellings(-claim.recomputed)
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


#: How much of the sentence to keep either side of a rejected figure. Enough
#: to read the clause it sat in; not enough to be a copy of the answer.
_WINDOW = 120

#: What a figure is attached to, read from the characters after it. Enough to
#: tell a percentage from a count from a money amount, which is most of the
#: work of classifying a rejected token.
_SUFFIX = re.compile(
    r"\s*(%|per ?cent\w*|bps|basis ?points?|bn|m\b|k\b|million|billion|"
    r"points?|notch\w*|obligors?|names?|days?|months?|weeks?|years?)",
    re.I)

#: And what it is a figure OF, read from the characters before it.
_PREFIX = re.compile(r"(SAR|USD|EUR|\$|£|€)\s*$", re.I)


def _rejected_context(written: dict[str, Any],
                      problems: list[str]) -> list[dict[str, Any]]:
    """Every rejected figure, with the words around it.

    Sanitised by construction: this reads the model's own ANSWER, which is
    prose about the result packet. It never touches the prompt, the system
    text, any provider credential or any reasoning the model did not publish
    — there is nothing else in scope here to touch.
    """
    if not problems:
        return []
    wanted = set(problems)
    out: list[dict[str, Any]] = []
    #: Up to two occurrences of each rejected token. One is often ambiguous —
    #: `25` as "the other 25" and `25` as "25% of the exposure" are different
    #: findings — and all of them would be the answer pasted back.
    seen: dict[str, int] = {}

    def once_more(token: str) -> bool:
        seen[token] = seen.get(token, 0) + 1
        return seen[token] <= 2

    for field_name, text in _prose_by_field(written):
        stripped = _PERIOD_TOKEN.sub(lambda m: " " * len(m.group(0)), text)
        for match in _NUMERAL.finditer(stripped):
            token = match.group(0)
            if token not in wanted or not once_more(token):
                continue
            start, end = match.span()
            before = text[max(0, start - _WINDOW):start]
            after = text[end:end + _WINDOW]
            suffix = _SUFFIX.match(after)
            prefix = _PREFIX.search(before.rstrip() + " ")
            out.append({
                "token": token,
                "field": field_name,
                "context_before": before.strip(),
                "context_after": after.strip(),
                "unit_or_suffix": (suffix.group(1).strip() if suffix
                                   else (prefix.group(1) if prefix else "")),
                "source_stage": seam_mod.INTERPRETATION,
            })
    # A period the answer named that nobody published is rejected too, and it
    # is not found by the numeral scanner — it was taken out before it ran.
    for field_name, text in _prose_by_field(written):
        for month in _PERIOD_TOKEN.findall(text):
            if month not in wanted or not once_more(month):
                continue
            at = text.find(month)
            out.append({
                "token": month, "field": field_name,
                "context_before": text[max(0, at - _WINDOW):at].strip(),
                "context_after": text[at + len(month):
                                      at + len(month) + _WINDOW].strip(),
                "unit_or_suffix": "period",
                "source_stage": seam_mod.INTERPRETATION,
            })
    return out


def _prose_by_field(answer: dict[str, Any]) -> list[tuple[str, str]]:
    """The same text `_prose` scans, with the field each piece came from."""
    out: list[tuple[str, str]] = []
    for key in ("direct", "interpretation"):
        value = answer.get(key)
        if isinstance(value, str):
            out.append((key, value))
    for key in ("points", "drivers", "follow_ups", "caveats"):
        for i, item in enumerate(answer.get(key) or []):
            out.append((f"{key}[{i}]", str(item)))
    return out


# ------------------------------------------------------------------ direction
#
# A figure can be grounded and the sentence around it still wrong. The packet
# holds L4 at 18.77 falling to 3.31, a change of -15.46; "fell 15.46 to 3.31"
# and "rose 15.46 to 3.31" quote exactly the same three governed numbers, and
# only one of them is true. Grounding checks figures. This checks the verb.
#
# Only CHANGE facts are checked, and that is the whole of the precision here.
# A score of 3.31 is not going anywhere — it is a level, and the direction
# word near it belongs to the change, not to it. A check that treated every
# positive fact as a rise would report "fell from 15.46 to 3.31" as a
# conflict on the 3.31.

#: Whether a fact name measures a move, and which way is worse, are the
#: metric module's to answer. They were a regex here, and the regex did not
#: know `largest_deterioration` was a movement — so a packet holding
#: `largest_deterioration: +8.0` beside two obligors at `ews_change_1m: -8.0`
#: registered the size 8.0 as unambiguously a FALL, and a true sentence about
#: the largest deterioration was refused.

#: The wording a reading uses for a direction. Metric semantics decide what
#: the wording has to agree with; this only spots that a direction was named.
_FELL = (r"fell|fallen|falling|\bfall\b|dropp?ed|dropping|declin\w+|"
         r"decreas\w+|reduc\w+|eas\w+|narrow\w+|shrank|shrunk|"
         r"improv\w+|recover\w+|strengthen\w+|lower\w*|down\b|"
         r"better\b|unwound|receded")
_ROSE = (r"ros[e]\b|risen|rising|\brise\b|increas\w+|grew\b|grown\b|"
         r"climb\w+|jump\w+|spik\w+|widen\w+|deteriorat\w+|worsen\w+|"
         r"weaken\w+|higher\b|\bup\b|steepen\w+")

_DIRECTION = re.compile(rf"\b(?P<down>{_FELL})\b|\b(?P<up>{_ROSE})\b", re.I)

#: How far back to look for the verb that governs a figure. Far enough for
#: "L4 network and relationship fell 15.46"; the sentence boundary below is
#: what actually stops it, and this only bounds the work.
_VERB_WINDOW = 160

#: Where a sentence starts. The verb that governs a figure is in the same
#: sentence as the figure — "...has not had its underlying condition ease. 4
#: of the 10 share L2.T1..." puts a falling verb three words before a four,
#: and they have nothing to do with each other.
_SENTENCE_END = re.compile(r"[.;?!]\s")


def _signed_changes(packet: packet_mod.ResultPacket,
                    claims: list[dv.Claim] | None) -> dict[str, int]:
    """Every move the result carries, as `size -> which way`.

    "Which way" is the direction of the CONDITION, decided per fact by the
    metric module, not the sign of the number: a fall of eight in a score
    where higher is worse is an improvement, and `largest_deterioration: 8.0`
    is a deterioration whatever its sign.

    A size the result carries BOTH ways is dropped, and that is the whole
    safety of this map. Within one population an obligor can improve by eight
    while five others deteriorate by eight; the reading has two true things it
    could be saying about `8.0` and nothing here can tell which, so the map
    says nothing. It said the wrong thing once, and only because a movement
    fact went unrecognised and the collision therefore looked like a
    certainty.
    """
    signs: dict[str, set[int]] = {}

    def note(name: str, value: float) -> None:
        way = mt.movement_sign(name, value)
        if not way:
            return
        for spelling in dv.spellings(abs(value)):
            signs.setdefault(spelling, set()).add(way)

    for name, value in dv.index(_facts_of(packet)).items():
        note(name, value)
    for claim in claims or []:
        if claim.accepted and claim.recomputed is not None:
            # A declared derivation over movement facts is a movement. Over
            # anything else it is not, and its direction goes unchecked.
            if all(mt.is_a_movement(ref) for ref in claim.refs):
                note(claim.refs[0], claim.recomputed)
    return {size: next(iter(ways)) for size, ways in signs.items()
            if len(ways) == 1}


def _checked_movements(declared: Any, facts: dict[str, float]
                       ) -> tuple[list[dict[str, Any]], set[str]]:
    """Every movement the reading declared, checked against its own fact.

    This is the route that works where the size alone cannot: the reading
    names WHICH fact it is talking about, and the server decides what that
    fact did. The model supplies wording; the direction, the signed value and
    the metric's semantics are all read here.

    Returns the verdicts, and the sizes a valid claim has accounted for —
    those are then exempt from the size-based check below, because a bound
    claim is a better answer than a guess about a nearby verb.
    """
    out: list[dict[str, Any]] = []
    settled: set[str] = set()
    for raw in list(declared or [])[:8]:
        if not isinstance(raw, dict):
            continue
        ref = str(raw.get("fact_ref") or "").strip()
        word = str(raw.get("direction") or "").strip().lower()
        said = mt.direction_word(word)
        record: dict[str, Any] = {"fact_ref": ref, "direction": word,
                                  "accepted": False}
        stated = raw.get("value")
        if isinstance(stated, (int, float)) and not isinstance(stated, bool):
            record["value"] = float(stated)

        resolved = dv._resolve(ref, facts) if ref else None
        if resolved is None:
            record["reason"] = f"the result carries no fact called {ref!r}"
            out.append(record)
            continue
        record["fact_value"] = resolved
        if said is None:
            record["reason"] = f"{word!r} is not a direction this product reads"
            out.append(record)
            continue
        way = mt.movement_sign(ref, resolved)
        record["fact_direction"] = mt.describes(ref, resolved)
        if not way:
            # A level, or a metric nobody has classified. Not a movement, so
            # there is no direction to disagree with.
            record["reason"] = (f"{mt.leaf(ref)!r} does not measure a move, so "
                                f"its direction is not checked")
            record["accepted"] = True
            out.append(record)
            continue
        if said != way:
            record["reason"] = (
                f"the reading said {word!r} of {ref}, which the result shows "
                f"{mt.describes(ref, resolved)} at {resolved:g}")
            out.append(record)
            continue
        if "value" in record and not dv.agrees(abs(record["value"]),
                                               abs(resolved)):
            record["reason"] = (
                f"the reading put {record['value']:g} on {ref}, which the "
                f"result carries at {resolved:g}")
            out.append(record)
            continue
        record["accepted"] = True
        out.append(record)
        settled |= dv.spellings(abs(resolved))
    return out, settled


def _direction_conflicts(written: dict[str, Any],
                         changes: dict[str, int],
                         settled: set[str] | None = None
                         ) -> list[dict[str, Any]]:
    """Prose that states the size of a move and names the wrong direction.

    The verb nearest before the figure, with no other figure in between —
    because "fell from 15.46 to 3.31" governs the 15.46 with "fell", and
    whatever governs the 3.31 is not that verb.
    """
    out: list[dict[str, Any]] = []
    for field_name, text in _prose_by_field(written):
        stripped = _PERIOD_TOKEN.sub(lambda m: " " * len(m.group(0)), text)
        for match in _NUMERAL.finditer(stripped):
            token = match.group(0)
            if token.startswith("-"):
                # A signed figure says its own direction, and the reader can
                # see it. Only a bare size can be given the wrong verb.
                continue
            if settled and (token in settled
                            or token.replace(",", "") in settled):
                # The reading named the fact this figure is about and the
                # server checked it. A bound claim beats a guess about a
                # nearby verb.
                continue
            if token in _ALWAYS_ALLOWED:
                # An ordinal or a count of the answer's own list. "4 of the
                # 10 share L2.T1" is not the size of anything, and a change
                # of four points elsewhere in the packet does not make it
                # one.
                continue
            wanted = changes.get(token) or changes.get(token.replace(",", ""))
            if wanted is None:
                continue
            before = text[max(0, match.start() - _VERB_WINDOW):match.start()]
            # Same sentence, and after any earlier figure: neither the
            # previous sentence's verb nor the previous figure's is this
            # figure's.
            boundaries = list(_SENTENCE_END.finditer(before))
            if boundaries:
                before = before[boundaries[-1].end():]
            previous = list(_NUMERAL.finditer(before))
            if previous:
                before = before[previous[-1].end():]
            verbs = list(_DIRECTION.finditer(before))
            if not verbs:
                continue
            last = verbs[-1]
            said = -1 if last.group("down") else 1
            if said == wanted:
                continue
            out.append({
                "token": token,
                "field": field_name,
                "said": last.group(0),
                "direction_written": "down" if said < 0 else "up",
                "direction_in_the_result": "down" if wanted < 0 else "up",
                "context": text[max(0, match.start() - _VERB_WINDOW):
                                match.end() + 40].strip(),
            })
    return out


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


#: How many named facts to publish. Enough for any reading; short of a data
#: export. The packet's own figures and its first ten rows are what the
#: writer can already see, so the index describes what it is looking at
#: rather than adding to it.
_INDEX_LIMIT = 160


def _published_index(packet: packet_mod.ResultPacket) -> dict[str, Any]:
    """The citable fact names, with their values, exactly as `check` resolves.

    Built from the same `_facts_of` the derived-claim contract indexes, so a
    name the writer reads here is a name the server will resolve. The two
    cannot drift: there is one index and this publishes it.
    """
    index = dv.index(_facts_of(packet))

    def rank(name: str) -> tuple[int, int, str]:
        # Shortest and plainest first, and a positional index last. Every
        # fact appears under several names — `movement.ews_change`,
        # `figures.movement.ews_change`, `layers[0].score_change`,
        # `layers.L1.score_change` — and the cap should keep the one a
        # person would write. `_resolve` matches on the tail of a path, so
        # the short name resolves for free.
        positional = 1 if "[" in name else 0
        prefixed = 1 if name.startswith(("figures.", "steps[")) else 0
        return (positional, prefixed, name)

    kept: dict[str, float] = {}
    seen: set[tuple[str, float]] = set()
    for name in sorted(index, key=rank):
        leaf = name.rsplit(".", 1)[-1]
        if (leaf, index[name]) in seen:
            # The same value under the same leaf name, reached by a longer
            # path. One way of saying it is enough.
            continue
        seen.add((leaf, index[name]))
        kept[name] = index[name]
        if len(kept) >= _INDEX_LIMIT:
            break
    return kept


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
        # Every fact a derived claim may be built from, under the exact name
        # it must be cited by.
        #
        # Without this the writer had to guess the vocabulary, and a live
        # reading declared a claim against `rows` — a name that resolves to
        # nothing, because `rows` is a list and the index holds numbers. The
        # claim was dropped, the figure fell through to the direct check, and
        # a paragraph was discarded over a naming convention nobody had
        # published. The server knows these names; not telling the writer
        # what they are is asking it to invent them.
        "fact_index": _published_index(packet),
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
    facts = dv.index(_facts_of(packet))
    claims = dv.check(data.get("derived_claims"), facts)
    # Movements the reading BOUND to a fact. Checked first, because a bound
    # claim settles a figure the size-based check could only guess at — and
    # within one population the same size can be an improvement and a
    # deterioration at once.
    movements, settled = _checked_movements(data.get("movement_claims"), facts)
    misdirected = [m for m in movements if not m["accepted"]]
    ungrounded = _ungrounded(
        written, _allowed_figures(packet, deterministic, context, claims),
        periods)
    # Grounded, and still possibly false. A figure can be exactly the one the
    # result carries and the verb in front of it can point the other way.
    conflicts = _direction_conflicts(
        written, _signed_changes(packet, claims), settled)
    # A declared movement the server disagrees with is a conflict of the same
    # kind, and a better-evidenced one: the reading named the fact itself.
    conflicts = [
        {"token": f"{m.get('value', m.get('fact_value', 0)):g}",
         "field": "movement_claims", "said": m["direction"],
         "direction_written": m["direction"],
         "direction_in_the_result": m.get("fact_direction", "unknown"),
         "context": m.get("reason", ""), "fact_ref": m.get("fact_ref", "")}
        for m in misdirected] + conflicts
    declared = [c.to_dict() for c in claims]
    refused = [c for c in claims if not c.accepted]
    if refused:
        logger.warning(
            "An Early Warning reading declared arithmetic the runtime did not "
            "reproduce: %s", "; ".join(c.reason for c in refused[:3]))
    if conflicts and not ungrounded:
        said = conflicts[0]
        logger.error(
            "Discarding an Early Warning reading: it wrote %r before %s, "
            "which the result shows moving the other way.",
            said["said"], said["token"])
        return Reading(
            answer=deterministic, fact_refs=refs, unresolved_refs=unresolved,
            derived_claims=declared, direction_conflicts=conflicts,
            movement_claims=movements,
            model_call=dict(outcome.to_dict(),
                            engine=seam_mod.DETERMINISTIC,
                            derived_claims=declared,
                            direction_conflicts=conflicts,
                            movement_claims=movements,
                            discarded_prose=" ".join(_prose(written))[:1200],
                            fallback_reason=(
                                "the reading gave a move the wrong direction: "
                                + "; ".join(
                                    f"{c['said']!r} before {c['token']}, "
                                    f"which the result shows going "
                                    f"{c['direction_in_the_result']}"
                                    for c in conflicts[:3]))))

    if ungrounded:
        context = _rejected_context(written, ungrounded)
        logger.error("Discarding an Early Warning reading: figures %s are not "
                     "in the result packet. %s", ungrounded,
                     "; ".join(f"{c['token']} in \u2026{c['context_before'][-60:]}"
                               f" [{c['token']}] {c['context_after'][:60]}\u2026"
                               for c in context[:3]))
        return Reading(
            answer=deterministic, ungrounded=ungrounded, fact_refs=refs,
            unresolved_refs=unresolved, derived_claims=declared,
            rejected_context=context, direction_conflicts=conflicts,
            movement_claims=movements,
            model_call=dict(outcome.to_dict(),
                            engine=seam_mod.DETERMINISTIC,
                            derived_claims=declared,
                            rejected_context=context,
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
                   direction_conflicts=[], movement_claims=movements,
                   model_call=dict(outcome.to_dict(), fact_refs=refs,
                                   unresolved_refs=unresolved,
                                   derived_claims=declared))


__all__ = ["Reading", "SCHEMA", "SYSTEM", "write"]

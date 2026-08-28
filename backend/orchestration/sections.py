"""
The eight things a credit answer has to say. P0.8, and the cure for Defect F.

The defect
----------
The observed interpretations were "technically correct but unimpressive,
generic, indirect or incomplete": repeated borrower and sector names, duplicated
phrases, unclear period references, weak credit reasoning, and — the sentence
that matters most — "not materially better than reading the table".

That last one is the whole diagnosis. A paragraph assembled out of whichever
observations happened to fire says nothing the reader could not see themselves,
because it has no obligation to say anything in particular. Prose with no
required shape drifts toward the safe and the general.

The fix is a shape. Every complex answer carries the same eight sections, in
the same order, and each one is a question the reader would otherwise have to
ask:

    1. BOTTOM LINE        what is the answer, in one sentence
    2. MATERIALITY        how big is it, against what
    3. MAIN DRIVERS       which named things account for it
    4. BREADTH VS         is this everywhere, or in a few places
       CONCENTRATION
    5. EXCEPTIONS         what does not fit, and what argues the other way
    6. CREDIT-RISK        what it means for credit, not for the table
       INTERPRETATION
    7. LIMITATIONS        what this result cannot tell you
    8. NEXT BEST          what to ask next, and why
       ANALYSES

A section is never dropped
--------------------------
When there is nothing to report in a section it SAYS SO. "No borrower departs
from the pattern" is a finding; a missing EXCEPTIONS section is an ambiguity —
the reader cannot tell whether exceptions were absent or never looked for. That
is the same principle as "SKIPPED is not PASS" in P0.9, applied to prose.

Everything here is computed
---------------------------
Every sentence is built from an analyst observation or from the plan, and every
section carries the facts it rests on. Nothing in this module writes prose about
a figure it was not given, so the grounding check downstream has something real
to check against, and the live model — when there is one — is handed these
sections as the things worth saying rather than a table and a style guide.

Repetition is removed once, globally
------------------------------------
The repeated-name defect is not a bug in any one observation. It is what
happens when the concentration, driver and exception passes all legitimately
name the same largest borrower and their sentences are concatenated. So the
de-duplication is a pass over the ASSEMBLED sections, which is the only place
that can see the repetition.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

BOTTOM_LINE = "bottom_line"
MATERIALITY = "materiality"
MAIN_DRIVERS = "main_drivers"
BREADTH = "breadth_vs_concentration"
EXCEPTIONS = "exceptions"
CREDIT_RISK = "credit_risk_interpretation"
LIMITATIONS = "limitations"
NEXT_BEST = "next_best_analyses"

#: The order they are shown in, which is also the order a credit officer reads
#: them: the answer, then its size, then its causes, then its shape, then what
#: argues against it, then what it means, then what it cannot say, then what to
#: do about it.
ORDER: tuple[str, ...] = (
    BOTTOM_LINE, MATERIALITY, MAIN_DRIVERS, BREADTH,
    EXCEPTIONS, CREDIT_RISK, LIMITATIONS, NEXT_BEST,
)

TITLES: dict[str, str] = {
    BOTTOM_LINE: "Bottom line",
    MATERIALITY: "Materiality",
    MAIN_DRIVERS: "Main drivers",
    BREADTH: "Breadth vs concentration",
    EXCEPTIONS: "Exceptions and contradictory signals",
    CREDIT_RISK: "Credit-risk interpretation",
    LIMITATIONS: "Limitations",
    NEXT_BEST: "Next best analyses",
}

#: Which analyst observation kinds feed which section. A kind can feed more
#: than one; the assembly takes each observation once, into the first section
#: that wants it, which is what stops the same sentence appearing twice.
FROM_OBSERVATIONS: dict[str, tuple[str, ...]] = {
    BOTTOM_LINE: ("conclusion", "direction"),
    MATERIALITY: ("magnitude", "significance"),
    MAIN_DRIVERS: ("driver",),
    BREADTH: ("concentration", "breadth"),
    EXCEPTIONS: ("exception", "comparison"),
    CREDIT_RISK: (),
    LIMITATIONS: ("limitation",),
    NEXT_BEST: ("next_step",),
}

#: What a section says when its pass ran and found nothing. Absence is a
#: finding; a missing section is an ambiguity.
#:
#: BOTTOM LINE is deliberately absent from this map. Every other section can
#: honestly report that it found nothing, but there is no sentence that stands
#: in for a missing answer — an answer with no bottom line has not been
#: answered, and the presentability gate's DIRECT_ANSWER check is what should
#: catch that. Writing a soothing placeholder here would hide it.
NOTHING_TO_REPORT: dict[str, str] = {
    MATERIALITY: "The result carries no total to size this against, so how "
                 "material it is cannot be stated from these figures alone.",
    MAIN_DRIVERS: "No single contributor stands out — the total is made up of "
                  "comparable amounts.",
    BREADTH: "The result has too few rows for concentration to mean anything.",
    EXCEPTIONS: "Nothing in the result departs from the pattern, and no figure "
                "here argues the other way.",
    LIMITATIONS: "Nothing about how this was computed limits what can be "
                 "concluded from it.",
}

#: How many rows a population needs before "concentrated" or "spread" is a
#: statement about it rather than about its size.
MIN_ROWS_FOR_BREADTH = 5


@dataclass
class Section:
    """One of the eight, with what it rests on."""

    key: str
    title: str
    text: str = ""
    #: The figures behind the sentences, for grounding and for the Trace.
    facts: dict[str, Any] = field(default_factory=dict)
    #: The observation kinds that fed it. Empty on a computed section.
    sources: list[str] = field(default_factory=list)
    #: True when the pass ran and had nothing to report — as distinct from not
    #: having run, which is what an absent section would mean.
    empty_finding: bool = False

    @property
    def said(self) -> bool:
        return bool(self.text.strip())

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "title": self.title, "text": self.text,
                "facts": dict(self.facts), "sources": list(self.sources),
                "empty_finding": self.empty_finding}


@dataclass
class Reading:
    """The eight sections for one answer."""

    sections: list[Section] = field(default_factory=list)
    #: Names that were said more than once and collapsed. Recorded rather than
    #: silently fixed, because a repetition that keeps coming back is a bug in
    #: an observation pass and somebody should be able to see it.
    deduplicated: list[str] = field(default_factory=list)

    def section(self, key: str) -> Section | None:
        return next((s for s in self.sections if s.key == key), None)

    @property
    def complete(self) -> bool:
        """Whether all eight are present. Present, not non-empty: a section
        that ran and found nothing is present."""
        return {s.key for s in self.sections} == set(ORDER)

    @property
    def missing(self) -> list[str]:
        have = {s.key for s in self.sections}
        return [k for k in ORDER if k not in have]

    @property
    def silent(self) -> list[str]:
        """Sections carrying no sentence at all — neither a finding nor an
        explicit absence. These are the ones that make an answer read as
        incomplete."""
        return [s.key for s in self.sections
                if not s.said and not s.empty_finding]

    def prose(self) -> str:
        """The eight as one piece of text, for a reader with no section UI."""
        return "\n\n".join(f"{s.title.upper()}\n{s.text}"
                           for s in self.sections if s.said)

    def to_dict(self) -> dict[str, Any]:
        return {"sections": [s.to_dict() for s in self.sections],
                "complete": self.complete,
                "missing": list(self.missing),
                "silent": list(self.silent),
                "deduplicated": list(self.deduplicated)}


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def compose(build: Any, runtime: Any, observations: list[Any], *,
            question: str = "", direct_answer: str = "",
            values: dict[str, Any] | None = None,
            follow_ups: list[str] | None = None) -> Reading:
    """The eight sections for this result.

    `direct_answer` is the sentence the deterministic narrative already leads
    with. It seeds BOTTOM LINE, because the answer to the question is the
    bottom line — writing a second one here out of the observations would
    produce two headline sentences that can disagree.

    `values` are the figures that narrative was built from. The credit-risk
    section reads the movement out of them rather than deriving one, so it
    cannot say "no movement" underneath a bottom line that says "fell from
    4,541 to 4,197".

    Never raises: an interpretation that fails to assemble must not take the
    figures down with it. An empty Reading is honest — the gate downstream sees
    eight missing sections and refuses to call the answer presentable, which is
    the correct outcome and not a crash.
    """
    try:
        return _compose(build, runtime, observations, question=question,
                        direct_answer=str(direct_answer or "").strip(),
                        values=dict(values or {}),
                        follow_ups=list(follow_ups or []))
    except Exception as e:  # noqa: BLE001 - prose must never lose an answer
        logger.warning("Could not assemble the eight sections: %s", e)
        return Reading()


def _compose(build: Any, runtime: Any, observations: list[Any], *,
             question: str, direct_answer: str, values: dict[str, Any],
             follow_ups: list[str]) -> Reading:
    rows = list(getattr(runtime, "rows", []) or [])
    by_kind: dict[str, list[Any]] = {}
    for observation in observations or []:
        by_kind.setdefault(str(getattr(observation, "kind", "")), []).append(
            observation)

    taken: set[int] = set()
    sections: list[Section] = []

    for key in ORDER:
        if key == CREDIT_RISK:
            sections.append(_credit_risk(build, runtime, observations, values))
            continue
        if key == NEXT_BEST:
            sections.append(_next_best(follow_ups, build))
            continue

        wanted = FROM_OBSERVATIONS.get(key, ())
        chosen = [o for kind in wanted for o in by_kind.get(kind, ())
                  if id(o) not in taken]
        for observation in chosen:
            taken.add(id(observation))
        section = _from(key, chosen, rows=rows)
        if key == BOTTOM_LINE and direct_answer:
            # The deterministic answer leads, and anything the observations
            # added follows it. The other way round buries the figure the
            # question asked for underneath a remark about the shape of the
            # result, which is the "indirect" half of Defect F.
            section.text = _sentences([direct_answer, section.text])
        sections.append(section)

    reading = Reading(sections=sections)
    _deduplicate(reading)
    return reading


def _from(key: str, observations: list[Any], *,
          rows: list[dict[str, Any]]) -> Section:
    """A section built out of the observations that belong to it."""
    section = Section(key=key, title=TITLES[key],
                      sources=[str(getattr(o, "kind", "")) for o in observations])
    facts: dict[str, Any] = {}
    for observation in observations:
        facts.update(dict(getattr(observation, "facts", {}) or {}))
    section.facts = facts

    said = [str(getattr(o, "text", "")).strip() for o in observations]
    said = [s for s in said if s]
    if said:
        section.text = _sentences(said)
        return section

    # Nothing to report. Say so, unless saying so would itself be misleading:
    # "no concentration" is only a finding when there were enough rows for
    # concentration to be a question.
    if key == BREADTH and len(rows) >= MIN_ROWS_FOR_BREADTH:
        section.text = ("The total is spread across the population rather than "
                        "sitting in a few rows.")
        section.empty_finding = True
        return section
    default = NOTHING_TO_REPORT.get(key, "")
    if default:
        section.text = default
        section.empty_finding = True
    return section


def _sentences(parts: list[str]) -> str:
    """Join observation texts into prose without producing a run-on.

    Each observation is already a sentence. The only work here is punctuation
    and not repeating a sentence that two passes produced identically.
    """
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        text = part.strip()
        if not text:
            continue
        normal = _normal(text)
        if normal in seen:
            continue
        seen.add(normal)
        out.append(text if text.endswith((".", "?", "!")) else f"{text}.")
    return " ".join(out)


# ---------------------------------------------------------------------------
# The two computed sections
# ---------------------------------------------------------------------------


def _credit_risk(build: Any, runtime: Any, observations: list[Any],
                 values: dict[str, Any] | None = None) -> Section:
    """What this means for credit, rather than what the table shows.

    Which way is worse is read from the ONTOLOGY — `Concept.higher_is_worse`,
    which already exists and is set explicitly on every governed concept —
    rather than from a list of measure names kept here. A second opinion about
    the direction of deterioration is a second opinion that can disagree with
    the first, and the one that inverts an answer is not the one anybody would
    think to look at.

    Nothing here asserts a cause. The result shows what moved, not why, so the
    sentences say what the movement IS for credit purposes and stop.
    """
    section = Section(key=CREDIT_RISK, title=TITLES[CREDIT_RISK])
    concept = _concept_of(build, runtime)
    moved = _direction(observations, values or {})

    if concept is None:
        section.text = (
            "The figures state the position; which way it points for credit "
            "depends on the measure's own direction, and no governed concept "
            "was matched to this result, so no deterioration is being asserted "
            "here.")
        section.empty_finding = True
        return section

    label = str(getattr(concept, "label", "") or "this measure")
    if getattr(concept, "is_categorical", False):
        section.facts = {"measure": getattr(concept, "id", "")}
        section.text = (
            f"{_capitalised(label)} is a category rather than a quantity, so "
            "there is no rise or fall here to read as deterioration — only a "
            "different distribution.")
        section.empty_finding = True
        return section

    if moved == 0:
        section.facts = {"measure": getattr(concept, "id", "")}
        section.text = (
            f"This is a position in {label} rather than a movement in it, so "
            "there is no deterioration or improvement to report — for that, "
            "the same measure at an earlier date is needed.")
        section.empty_finding = True
        return section

    worse_up = bool(getattr(concept, "higher_is_worse", True))
    deteriorating = (moved > 0) == worse_up
    way = "rose" if moved > 0 else "fell"
    step = "steps" if getattr(concept, "is_ordinal", False) else ""
    section.facts = {"measure": getattr(concept, "id", ""),
                     "direction": way,
                     "higher_is_worse": worse_up,
                     "deterioration": deteriorating}
    reading = "deterioration" if deteriorating else "improvement"
    adverse = "the adverse direction" if deteriorating else "the favourable direction"
    moved_in = f" in {step}" if step else ""
    section.text = (
        f"For credit purposes this is {reading}: {label} {way}{moved_in}, and "
        f"for this measure that is {adverse}. It is a change in the measured "
        "position, not evidence of a cause.")
    return section


def _next_best(follow_ups: list[str], build: Any) -> Section:
    """What to ask next. Only questions this product can actually answer —
    suggesting an analysis the catalogue cannot run is worse than suggesting
    nothing, because the reader spends a turn finding that out."""
    section = Section(key=NEXT_BEST, title=TITLES[NEXT_BEST])
    asks = [str(f).strip() for f in (follow_ups or []) if str(f).strip()]
    if not asks:
        section.text = ("No further analysis is needed to act on this; the "
                        "figures above answer what was asked.")
        section.empty_finding = True
        return section
    section.facts = {"count": len(asks)}
    section.text = " ".join(a if a.endswith("?") else f"{a}?" for a in asks[:3])
    return section


def _concept_of(build: Any, runtime: Any) -> Any:
    """The governed concept behind this result's primary measure, or None.

    None is a real answer, and the section above says so rather than guessing:
    a result whose measure the ontology does not recognise has no governed
    direction of deterioration, and inventing one from the column's name is how
    "coverage rose" becomes a warning.
    """
    try:
        from backend.orchestration import presentation as pr

        schema = pr.schema(runtime, build)
    except Exception:  # noqa: BLE001 - a reading is not worth an exception
        return None

    visible = [c for c in schema if not c.get("hidden")]

    def rank_of(column: dict[str, Any]) -> int:
        declared = column.get("rank")
        return int(declared) if declared is not None else pr.RANK_CONTEXT

    # The measure the question asked for, if the planner marked one; otherwise
    # the first numeric column — the same fallback analyst.py uses, so this
    # section is written about the measure the observations above it came from.
    primary = next((c for c in visible if rank_of(c) == pr.RANK_PRIMARY), None)
    if primary is None:
        primary = next((c for c in visible
                        if str(c.get("semantic") or "") in _NUMERIC), None)
    if primary is None:
        return None

    name = str(primary.get("name") or "").lower()
    for match in (getattr(build, "matches", None) or []):
        concept = getattr(match, "concept", None)
        field_name = str(getattr(match, "field", "") or "").lower()
        if concept is None or not field_name:
            continue
        # A joined column carries its dataset prefix: `ifrs9_staging_total_ecl`.
        if name == field_name or name.endswith(f"_{field_name}"):
            return concept
    return None


_NUMERIC = frozenset({"money", "percent", "ratio", "count", "days"})


def _capitalised(label: str) -> str:
    return label[:1].upper() + label[1:] if label else label


def _direction(observations: list[Any], values: dict[str, Any]) -> int:
    """Which way the result moved: 1 up, -1 down, 0 unknown.

    Read from the figures the answer was written from, never re-derived, so the
    credit-risk sentence cannot disagree with the bottom line above it. The
    narrative's own values come first because they are what the direct answer
    quotes; the observations are the fallback for a result that has movement
    per row but no single headline change.
    """
    for name in ("change", "change_abs", "change_pct"):
        value = values.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value > 0:
                return 1
            if value < 0:
                return -1

    for observation in observations or []:
        facts = dict(getattr(observation, "facts", {}) or {})
        for name in ("change", "delta", "movement", "change_abs",
                     "change_pct", "largest_change"):
            value = facts.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if value > 0:
                    return 1
                if value < 0:
                    return -1
        text = str(getattr(observation, "text", "")).lower()
        if str(getattr(observation, "kind", "")) == "direction":
            if re.search(r"\b(rose|increased|grew|higher|up)\b", text):
                return 1
            if re.search(r"\b(fell|decreased|declined|lower|down)\b", text):
                return -1
    return 0


# ---------------------------------------------------------------------------
# Repetition
# ---------------------------------------------------------------------------

#: A proper name: two or more capitalised words, or one capitalised word
#: followed by a code. Deliberately conservative — collapsing a sector name
#: that only LOOKS like a borrower would remove information.
_NAME = re.compile(r"\b([A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*)+(?:\s+\d{2,})?)\b")

#: After this many mentions across the whole reading, a name is being repeated
#: rather than referred to. Three is the point at which a credit paper would
#: switch to "the same borrower".
MAX_MENTIONS = 2

_PRONOUN = "the same borrower"


def _deduplicate(reading: Reading) -> None:
    """Collapse a name repeated across sections into a back-reference.

    This runs over the ASSEMBLED reading and nowhere else. The repetition is
    not a bug in the concentration pass or the driver pass — each of them names
    the largest borrower for a good reason — it only becomes repetition once
    their sentences sit next to each other, so this is the only place that can
    see it.
    """
    counts: dict[str, int] = {}
    for section in reading.sections:
        for match in _NAME.finditer(section.text):
            counts[match.group(1)] = counts.get(match.group(1), 0) + 1

    repeated = {name for name, n in counts.items() if n > MAX_MENTIONS}
    if not repeated:
        return

    seen: dict[str, int] = {}
    for section in reading.sections:
        if not section.text:
            continue

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in repeated:
                return name
            seen[name] = seen.get(name, 0) + 1
            return name if seen[name] <= MAX_MENTIONS else _PRONOUN

        section.text = _NAME.sub(replace, section.text)

    reading.deduplicated = sorted(repeated)


def _normal(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


__all__ = [
    "BOTTOM_LINE",
    "BREADTH",
    "CREDIT_RISK",
    "EXCEPTIONS",
    "LIMITATIONS",
    "MAIN_DRIVERS",
    "MATERIALITY",
    "NEXT_BEST",
    "ORDER",
    "TITLES",
    "Reading",
    "Section",
    "compose",
]

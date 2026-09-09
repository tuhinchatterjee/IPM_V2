"""
What the current answer is actually about, and how each turn changed it.

The failure this prevents
-------------------------
A thread narrows: five Real Estate customers, then the two with worsening DPD.
Then somebody asks a portfolio question. If the two customers are still in
scope, the answer is a portfolio figure computed over two names — correct
arithmetic, correct-looking table, and wrong by three orders of magnitude with
nothing on the screen to say so.

The opposite failure is the same shape. "Which of those also had an increase in
ECL?" answered over the whole book returns five hundred facilities where ten
customers were meant, and it looks like a bigger version of the right answer.

Both are invisible unless the scope is a thing rather than an implication. So it
is a thing: a typed frame carried on every turn, a classified delta saying what
this turn did to it, and a line on the answer saying what the figures cover.

What a delta is for
-------------------
Not bookkeeping. It decides work. A **narrowing** can reuse the population the
previous turn established rather than re-deriving "the five largest", which
could quietly come back as a different five. A **widening** cannot, and has to
say so before it spends a minute reading four more datasets. A
**presentation-only** change recomputes nothing at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deltas
# ---------------------------------------------------------------------------

NARROW = "NARROW"
WIDEN = "WIDEN"
RESET = "RESET"
ENRICH = "ENRICH"
CHANGE_MEASURE = "CHANGE_MEASURE"
CHANGE_DIMENSION = "CHANGE_DIMENSION"
CHANGE_PERIOD = "CHANGE_PERIOD"
PRESENTATION_ONLY = "PRESENTATION_ONLY"
NEW_TOPIC = "NEW_TOPIC"
UNCHANGED = "UNCHANGED"

DELTAS: tuple[str, ...] = (
    NARROW, WIDEN, RESET, ENRICH, CHANGE_MEASURE, CHANGE_DIMENSION,
    CHANGE_PERIOD, PRESENTATION_ONLY, NEW_TOPIC, UNCHANGED,
)

#: How much bigger a requested scope has to get before the user is told about
#: it rather than simply being given it. Ten times is the point at which a
#: question about five customers has become a question about the book.
MATERIAL_WIDENING = 10


# ---------------------------------------------------------------------------
# Saying a filter out loud
# ---------------------------------------------------------------------------

#: A governed field whose VALUE is meaningless without the field's own name.
#: "Shipping" is a sector and says so; "2" is a stage and says nothing, and
#: "Together these 10 hold 11.50% of 2 exposure at default" is the sentence a
#: bare value produces. Sector, country and rating are names already and are
#: left alone — "Real Estate exposure" needs no prefix, and "sector Real
#: Estate exposure" is worse English than the value on its own.
NEEDS_ITS_NAME: dict[str, str] = {
    "ifrs9_stage": "Stage", "internal_grade": "grade",
    "dpd_bucket": "DPD bucket", "charge_rank": "charge rank",
}

#: How a widened restriction reads. "Stage 2" and "Stage 2 or worse" are
#: different populations, and an answer that says the first over the rows of
#: the second has misdescribed what the reader is looking at.
WIDENED_SAYS: dict[str, str] = {"gte": "or worse", "lte": "or better"}


def say(field_name: str, value: Any, widened_op: str = "") -> str:
    """One filter, as a credit officer would say it.

    A coded value is named by its field; a value that is already a name is
    said as it is. This is the ONE place that rule lives: the answer's first
    sentence, the share finding, the interpretation, the formula gloss and the
    scope line above the table all read the same restriction, and when each of
    them joined the raw values itself four surfaces disagreed about what the
    population was called.
    """
    said = str(value)
    prefix = NEEDS_ITS_NAME.get(field_name)
    if prefix is None and said.replace(".", "").replace("-", "").isdigit():
        # An unmapped field with a numeric value is still unreadable bare, so
        # it falls back to its own name rather than to the digit alone.
        prefix = str(field_name).replace("_", " ")
    if prefix:
        said = f"{prefix} {said}"
    tail = WIDENED_SAYS.get(widened_op or "", "")
    return f"{said} {tail}" if tail else said


def phrase(filters: Any, widened: Any = None) -> str:
    """Every filter on a population, as one readable phrase.

    `filters` may be pairs — ``[("ifrs9_stage", "2")]`` — or the mapping form
    the frame stores, ``[{"field": ..., "value": ...}]``. Both are the same
    fact written down twice, and refusing one of them here would only push the
    conversion out to every caller.
    """
    widened_ops: dict[tuple[str, str], str] = {
        (getattr(q, "field", ""), str(getattr(q, "value", ""))):
            getattr(q, "op", "") for q in (widened or [])
    }
    parts: list[str] = []
    for entry in (filters or []):
        stored_op = ""
        if isinstance(entry, dict):
            field_name, value = str(entry.get("field", "")), entry.get("value")
            # A frame carries the qualifier WITH the restriction, because the
            # frame is what survives into the next turn and into the payload.
            # Without it the line above the table said "Stage 2" over rows the
            # sentence below correctly called "Stage 2 or worse".
            stored_op = str(entry.get("op", "") or "")
        else:
            field_name, value = str(entry[0]), entry[1]
        op = widened_ops.get((field_name, str(value)), "") or stored_op
        parts.append(say(field_name, value, op))
    return ", ".join(p for p in parts if p)


@dataclass
class ScopeFrame:
    """What the current answer covers.

    Every field is something a figure depends on. If two frames differ in any
    of them, the same question has two different correct answers, and a user
    comparing them without seeing the difference is being misled by the
    product rather than by the data.
    """

    #: Where the population came from — "the five largest Real Estate
    #: customers". Human-readable, because this is what the answer says.
    population: str = ""
    entity_key: str = ""
    entity_ids: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    #: [{"field": "sector", "value": "Real Estate"}]
    filters: list[dict[str, str]] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    dimension: str = ""
    period: str = ""
    opening: str = ""
    closing: str = ""
    grain: str = ""
    #: Why the answer is at that grain, in the sentence the user is shown. §4.
    #: Carried on the frame rather than recomputed, so the Scope line and the
    #: Trace say the same thing about the same turn.
    grain_because: str = ""
    top_n: int = 0
    presentation: str = ""
    fingerprint: str = ""

    @property
    def empty(self) -> bool:
        """Whether anything has been established yet.

        A pinned population counts even with no measure recorded beside it:
        five customer ids ARE a scope, and treating that frame as empty made
        the next turn look like the first one in the thread — which is exactly
        how a carried population goes missing.
        """
        return not (self.population or self.metrics or self.datasets
                    or self.entity_ids or self.filters)

    @property
    def size(self) -> int:
        """How many identities the scope is pinned to. 0 means the whole book."""
        return len(self.entity_ids)

    def line(self) -> str:
        """The one line an answer carries so its scope is never implied.

        Reads as a sentence rather than a key/value dump, because it is shown
        above a table a credit officer is about to act on.
        """
        parts: list[str] = []
        if self.entity_ids:
            parts.append(f"{len(self.entity_ids)} "
                         f"{(self.entity_key or 'row').replace('_id', '')}s "
                         "carried from the previous answer")
        elif self.filters:
            # Through the shared reader, not by joining the raw values: the
            # line above the table has to name the same population the answer
            # names, and "2 · Q2 2026 · exposure at default" names none.
            parts.append(phrase(self.filters))
        else:
            parts.append("the whole portfolio")

        if self.opening and self.closing:
            parts.append(f"{self.opening} to {self.closing}")
        elif self.period:
            parts.append(self.period)

        if self.metrics:
            parts.append(", ".join(self.metrics[:3]))
        if self.dimension:
            parts.append(f"by {self.dimension.replace('_', ' ')}")
        return " · ".join(p for p in parts if p)

    def to_dict(self) -> dict[str, Any]:
        return {
            "population": self.population,
            "entity_key": self.entity_key,
            "entity_count": len(self.entity_ids),
            "datasets": list(self.datasets),
            "domains": list(self.domains),
            "filters": [dict(f) for f in self.filters],
            "metrics": list(self.metrics),
            "dimension": self.dimension,
            "period": self.period,
            "opening": self.opening,
            "closing": self.closing,
            "grain": self.grain,
            "grain_because": self.grain_because,
            "top_n": self.top_n,
            "presentation": self.presentation,
            "fingerprint": self.fingerprint,
            "line": self.line(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ScopeFrame:
        raw = raw or {}
        return cls(
            population=str(raw.get("population") or ""),
            entity_key=str(raw.get("entity_key") or ""),
            entity_ids=[str(i) for i in (raw.get("entity_ids") or [])],
            datasets=[str(d) for d in (raw.get("datasets") or [])],
            domains=[str(d) for d in (raw.get("domains") or [])],
            filters=[dict(f) for f in (raw.get("filters") or [])],
            metrics=[str(m) for m in (raw.get("metrics") or [])],
            dimension=str(raw.get("dimension") or ""),
            period=str(raw.get("period") or ""),
            opening=str(raw.get("opening") or ""),
            closing=str(raw.get("closing") or ""),
            grain=str(raw.get("grain") or ""),
            grain_because=str(raw.get("grain_because") or ""),
            top_n=int(raw.get("top_n") or 0),
            presentation=str(raw.get("presentation") or ""),
            fingerprint=str(raw.get("fingerprint") or ""),
        )


@dataclass
class Delta:
    """What one turn did to the scope."""

    kind: str = UNCHANGED
    before: ScopeFrame = field(default_factory=ScopeFrame)
    after: ScopeFrame = field(default_factory=ScopeFrame)
    #: Plain sentences: "restricted to Contracting", "extended to Q2 2024".
    changes: list[str] = field(default_factory=list)
    #: Set when the new scope is materially larger than the old one.
    widening_note: str = ""

    @property
    def reuses_population(self) -> bool:
        """Whether the previous turn's identities are still the population."""
        return self.kind in (NARROW, ENRICH, CHANGE_MEASURE, PRESENTATION_ONLY)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "changes": list(self.changes),
            "widening_note": self.widening_note,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
        }


# ---------------------------------------------------------------------------
# Reading a frame off a turn
# ---------------------------------------------------------------------------


def _frame_filters(build: Any) -> list[dict[str, str]]:
    """The build's restrictions, each carrying how it was compiled.

    `widened` is the plan's own record that "Stage 2" ran as ``stage >= 2``.
    Recording it beside the value is what lets the scope line say "Stage 2 or
    worse" without re-reading the question — the phrase on the screen and the
    predicate that ran stay the same fact.
    """
    widened = {(getattr(q, "field", ""), str(getattr(q, "value", ""))):
               str(getattr(q, "op", "") or "")
               for q in (getattr(build, "widened", None) or [])}
    out: list[dict[str, str]] = []
    for f, v in (getattr(build, "filters", None) or []):
        entry = {"field": str(f), "value": str(v)}
        op = widened.get((str(f), str(v)), "")
        if op:
            entry["op"] = op
        out.append(entry)
    return out


def frame_of(build: Any, continuation: Any = None,
             presentation: str = "") -> ScopeFrame:
    """The scope one answer covers, read from the plan that produced it."""
    if build is None:
        return ScopeFrame(presentation=presentation)

    entity_ids = list(getattr(continuation, "entity_ids", []) or [])
    return ScopeFrame(
        population=str(getattr(continuation, "referent", "") or ""),
        entity_key=str(getattr(continuation, "entity_key", "") or ""),
        entity_ids=entity_ids,
        datasets=list(((build.plan.get("meta") or {}).get("datasets")) or []),
        filters=_frame_filters(build),
        metrics=[m.concept.label for m in (getattr(build, "matches", None) or [])],
        dimension=str(getattr(build, "dimension", "") or ""),
        period=str(getattr(build, "period", "") or ""),
        opening=str(getattr(build, "opening", "") or ""),
        closing=str(getattr(build, "closing", "") or ""),
        # The grain of the ANSWER, not of the table it was read from. A
        # by-sector aggregate over a facility-keyed source used to declare
        # itself facility-grained here, which is true of what it scanned and
        # false of what the user is looking at. §4.
        grain=str(getattr(build, "output_grain", "")
                  or getattr(build, "grain", "") or ""),
        grain_because=str(getattr(
            getattr(getattr(build, "grain_contract", None), "want", None),
            "because", "") or ""),
        top_n=int(getattr(build, "top_n", 0) or 0),
        presentation=presentation,
        fingerprint=str((build.plan.get("meta") or {}).get("fingerprint") or ""),
    )


# ---------------------------------------------------------------------------
# Classifying the change
# ---------------------------------------------------------------------------

#: Which conversation action implies which delta, where the action settles it.
_BY_ACTION: dict[str, str] = {
    "NEW_REQUEST": NEW_TOPIC,
    "RESET_SCOPE": RESET,
    "WIDEN_SCOPE": WIDEN,
    "ENRICH_PREVIOUS": ENRICH,
    "MODIFY_PRESENTATION": PRESENTATION_ONLY,
    # An assessment reads the result that is already on the table. The scope
    # it covers is, by construction, exactly the scope of the turn before it —
    # which is the property the answer states and the Trace has to show.
    "ASSESS_PREVIOUS_RESULT": UNCHANGED,
    "MODIFY_PERIOD": CHANGE_PERIOD,
    "MODIFY_CALCULATION": CHANGE_MEASURE,
    "MODIFY_FILTER": NARROW,
    "MODIFY_POPULATION": NARROW,
}


def classify(before: ScopeFrame, after: ScopeFrame, action: str = "") -> Delta:
    """What this turn did to the scope, and what to say about it."""
    delta = Delta(before=before, after=after)

    if before.empty:
        delta.kind = NEW_TOPIC
        return delta

    named = _BY_ACTION.get((action or "").upper())
    delta.changes = _differences(before, after)

    if named is not None:
        delta.kind = named
    elif len(after.filters) > len(before.filters):
        # Checked BEFORE the measure comparison. Narrowing almost always adds
        # a concept too — "which of these are Stage 2?" adds both a filter and
        # the stage — and calling that a change of measure describes the least
        # important half of what happened.
        delta.kind = NARROW
    elif after.size and before.size and after.size < before.size:
        delta.kind = NARROW
    elif not after.size and before.size:
        # Losing the population outranks everything else that changed with it.
        # A turn that drops five names AND groups by sector is a widening that
        # happens to have a breakdown, not a breakdown that happens to cover
        # the whole book — and only one of those descriptions warns anybody.
        delta.kind = WIDEN
    elif set(after.metrics) != set(before.metrics) and after.metrics:
        delta.kind = CHANGE_MEASURE
    elif after.dimension != before.dimension and after.dimension:
        delta.kind = CHANGE_DIMENSION
    elif (after.opening, after.closing, after.period) != (
            before.opening, before.closing, before.period):
        delta.kind = CHANGE_PERIOD
    elif not delta.changes:
        delta.kind = UNCHANGED
    else:
        delta.kind = NARROW

    if delta.kind in (WIDEN, RESET):
        delta.widening_note = _widening(before, after)
    return delta


def _differences(before: ScopeFrame, after: ScopeFrame) -> list[str]:
    """What actually changed, as sentences."""
    out: list[str] = []

    added = [f for f in after.filters if f not in before.filters]
    dropped = [f for f in before.filters if f not in after.filters]
    for entry in added:
        out.append(f"restricted to {entry['value']}")
    for entry in dropped:
        out.append(f"no longer restricted to {entry['value']}")

    if set(after.metrics) != set(before.metrics):
        gained = [m for m in after.metrics if m not in before.metrics]
        lost = [m for m in before.metrics if m not in after.metrics]
        if gained and lost:
            out.append(f"{', '.join(lost)} replaced by {', '.join(gained)}")
        elif gained:
            out.append(f"{', '.join(gained)} added")
        elif lost:
            out.append(f"{', '.join(lost)} dropped")

    if after.dimension != before.dimension:
        if after.dimension:
            out.append(f"broken down by {after.dimension.replace('_', ' ')}")
        else:
            out.append("no longer broken down")

    window_before = (before.opening, before.closing, before.period)
    window_after = (after.opening, after.closing, after.period)
    if window_before != window_after:
        if after.opening and after.closing:
            out.append(f"comparing {after.opening} with {after.closing}")
        elif after.period:
            out.append(f"at {after.period}")

    if after.top_n and after.top_n != before.top_n:
        out.append(f"cut to {after.top_n}")

    if after.size != before.size:
        if after.size and before.size:
            out.append(f"{before.size} rows narrowed to {after.size}")
        elif after.size:
            out.append(f"pinned to {after.size} rows")
        else:
            out.append("no longer pinned to a carried population")

    if after.presentation and after.presentation != before.presentation:
        out.append(f"shown as a {after.presentation}")
    return out


def _widening(before: ScopeFrame, after: ScopeFrame) -> str:
    """What to tell the user before answering a materially larger question.

    Only when it is material. Narrating every small change would train people
    to skip the line, and the line matters exactly once — when the scope has
    silently become the whole book.
    """
    grew_population = before.size and not after.size
    grew_datasets = len(after.datasets) > len(before.datasets)
    if not (grew_population or grew_datasets):
        return ""

    from_scope = (f"{before.size} {(before.entity_key or 'row').replace('_id', '')}s"
                  if before.size else "the current population")
    to_scope = ("the full portfolio" if not after.size
                else f"{after.size} rows")
    detail = f"from {from_scope} and {_count(len(before.datasets), 'dataset')}"
    detail += f" to {to_scope} and {_count(len(after.datasets), 'dataset')}"
    return (f"This question is materially wider than the last one: it expands "
            f"the analysis {detail}.")


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


def is_material(before: ScopeFrame, after: ScopeFrame) -> bool:
    """Whether a widening is large enough to be worth a sentence."""
    if before.size and not after.size:
        return True
    if after.size and before.size:
        return after.size >= before.size * MATERIAL_WIDENING
    return len(after.datasets) > len(before.datasets) + 1


__all__ = [
    "CHANGE_DIMENSION",
    "CHANGE_MEASURE",
    "CHANGE_PERIOD",
    "DELTAS",
    "ENRICH",
    "MATERIAL_WIDENING",
    "NARROW",
    "NEW_TOPIC",
    "PRESENTATION_ONLY",
    "RESET",
    "UNCHANGED",
    "WIDEN",
    "Delta",
    "ScopeFrame",
    "classify",
    "frame_of",
    "is_material",
]

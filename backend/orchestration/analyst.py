"""
What an analyst would notice, computed rather than written.

The failure
-----------
"Interpretations are often technically correct but unimpressive, generic,
indirect or incomplete." Every word of that is fair. The deterministic
narrative restated the headline in longer words, and the live model was handed
a table and a style guide and asked to be insightful — which produces prose
that sounds like analysis and contains no observation the reader could not make
by looking at the table.

What an analyst actually does with a result is a short list of specific things,
and every one of them is arithmetic:

* how big is it, and against what
* which way did it move, and by how much
* is it concentrated or spread
* who are the largest contributors, by name
* which rows do not fit the pattern
* did it move everywhere or in one place
* what limits what can be concluded

This module does that arithmetic. Nothing here writes prose about a number it
has not computed, and nothing here reads the data — only the result the runtime
already produced.

Where the observations go
-------------------------
Two places, and that is the point. With no provider they ARE the
interpretation, assembled into a paragraph. With a provider they are given to
the model as the things worth saying, so it writes about the largest driver by
name instead of about the portfolio in general. Either way the reader gets the
same observations; only the sentences differ.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# What kind of thing was noticed. Ordered by how an analyst would say them.
CONCLUSION = "conclusion"
MAGNITUDE = "magnitude"
DIRECTION = "direction"
CONCENTRATION = "concentration"
DRIVER = "driver"
EXCEPTION = "exception"
BREADTH = "breadth"
COMPARISON = "comparison"
SIGNIFICANCE = "significance"
LIMITATION = "limitation"
NEXT_STEP = "next_step"

ORDER = (CONCLUSION, MAGNITUDE, DIRECTION, CONCENTRATION, DRIVER, EXCEPTION,
         BREADTH, COMPARISON, SIGNIFICANCE, LIMITATION, NEXT_STEP)

#: A top row holding more than this share of the total is a concentration
#: worth saying out loud rather than a large row.
CONCENTRATED_AT = 25.0

#: And the top three above this is a concentrated population however evenly the
#: tail is spread.
TOP_THREE_AT = 60.0

#: How far from the middle a row has to sit to be an exception. Measured in
#: median absolute deviations, which a single enormous row does not distort the
#: way a standard deviation does.
OUTLIER_DEVIATIONS = 3.5

#: Below this many rows there is no pattern for a row to be an exception to.
MIN_ROWS_FOR_SHAPE = 5

#: How many observations reach the reader. More than this is a report, and the
#: interpretation is supposed to be the thing you read instead of one.
MAX_OBSERVATIONS = 5


@dataclass
class Observation:
    """One thing worth saying, and the figures that support it."""

    kind: str
    text: str
    #: The figures this rests on, so a grounding check can see them and a
    #: reader can be shown what it was derived from.
    facts: dict[str, Any] = field(default_factory=dict)
    #: Higher is more worth saying. Used only to choose between observations of
    #: the same kind.
    weight: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text,
                "facts": dict(self.facts), "weight": self.weight}


# ---------------------------------------------------------------------------
# Reading the result
# ---------------------------------------------------------------------------


def observe(build: Any, runtime: Any,
            values: dict[str, Any] | None = None) -> list[Observation]:
    """Everything worth noticing about this result, computed from it."""
    try:
        return _observe(build, runtime, values or {})
    except Exception as e:  # noqa: BLE001 - a reading must not lose an answer
        logger.warning("The analyst pass failed: %s", e)
        return []


def _observe(build: Any, runtime: Any,
             values: dict[str, Any]) -> list[Observation]:
    from backend.orchestration import figures
    from backend.orchestration import presentation as pr

    rows = list(getattr(runtime, "rows", []) or [])
    if not rows:
        return []

    schema = pr.schema(runtime, build)
    subject = next((c for c in schema
                    if not c.get("hidden") and _rank(c) <= pr.RANK_SUBJECT), None)
    measure = next((c for c in schema
                    if not c.get("hidden") and _rank(c) == pr.RANK_PRIMARY
                    and c.get("semantic") in _NUMERIC), None)
    if measure is None:
        measure = next((c for c in schema
                        if not c.get("hidden")
                        and c.get("semantic") in _NUMERIC), None)
    if measure is None:
        return []

    column = str(measure.get("name"))
    label = pr.in_sentence(str(measure.get("label") or column))
    key = str(subject.get("name")) if subject else ""

    # "8, 10, 9 together hold 67.67%" is a sentence about three numbers. A
    # grade stored as an integer needs its noun in front of it, or the reader
    # has to work out that they are grades rather than counts.
    noun = _in_sentence(str(subject.get("label") or "")) if subject else ""

    def named(value: Any) -> str:
        text = str(value if value is not None else "").strip()
        if not text:
            return ""
        return f"{noun} {text}" if noun and _is_bare_number(text) else text

    series: list[tuple[str, float]] = []
    for row in rows:
        value = row.get(column)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        series.append((named(row.get(key)) if key else "", float(value)))
    if not series:
        return []

    def shown(value: float) -> str:
        return pr.render(value, measure)

    out: list[Observation] = []
    # Concentration is a statement about a SHARE OF A TOTAL, so it needs a
    # measure that adds up. Ten per-grade coverage ratios have no total, and
    # "grade 10 accounts for 44.75% of ECL coverage" is a sentence about a
    # quantity that does not exist.
    if str(measure.get("semantic") or "") in _ADDITIVE:
        out.extend(_concentration(series, label, shown))
    out.extend(_drivers(series, label, shown))
    out.extend(_exceptions(series, label, shown))
    out.extend(_movement(build, rows, schema, values, figures))
    out.extend(_limitations(build, runtime))
    return out


_NUMERIC = frozenset({"money", "percent", "ratio", "count", "days"})

#: Measures whose values sum to something meaningful. A percentage and a
#: multiple do not: adding ten coverage ratios produces a number that is
#: neither a ratio nor a total.
_ADDITIVE = frozenset({"money", "count", "days"})


def _is_bare_number(text: str) -> bool:
    return text.replace(".", "", 1).replace("-", "", 1).isdigit()


def _in_sentence(label: str) -> str:
    from backend.orchestration import presentation as pr

    return pr.in_sentence(label)


def _rank(column: dict[str, Any]) -> int:
    from backend.orchestration import presentation as pr

    value = column.get("rank")
    return int(value) if value is not None else pr.RANK_CONTEXT


# ---------------------------------------------------------------------------
# The observations themselves
# ---------------------------------------------------------------------------


def _concentration(series: list[tuple[str, float]], label: str,
                   shown: Any) -> list[Observation]:
    """Whether the population is concentrated, and by how much."""
    from backend.orchestration import figures

    positive = [(name, value) for name, value in series if value > 0]
    total = sum(value for _, value in positive)
    if len(positive) < 3 or total <= 0:
        return []

    ranked = sorted(positive, key=lambda pair: pair[1], reverse=True)
    top_name, top_value = ranked[0]
    top_share = 100.0 * top_value / total
    three_share = 100.0 * sum(v for _, v in ranked[:3]) / total

    if top_share >= CONCENTRATED_AT and top_name:
        return [Observation(
            kind=CONCENTRATION, weight=top_share,
            text=(f"{top_name} alone accounts for "
                  f"{figures.percent(top_share)} of {label} across the "
                  f"{len(positive)} shown."),
            facts={"top": top_name, "top_share_pct": round(top_share, 2),
                   "of": len(positive)})]
    if three_share >= TOP_THREE_AT:
        names = ", ".join(name for name, _ in ranked[:3] if name)
        return [Observation(
            kind=CONCENTRATION, weight=three_share,
            text=(f"The population is concentrated: {names} together hold "
                  f"{figures.percent(three_share)} of {label}."),
            facts={"top_three_share_pct": round(three_share, 2)})]
    # An evenly spread population is the ordinary case. "Spread rather than
    # concentrated" is a sentence that describes almost every result and tells
    # a reader nothing they would act on.
    return []


def _drivers(series: list[tuple[str, float]], label: str,
             shown: Any) -> list[Observation]:
    """The largest contributor, by name, and the gap to the next.

    Only for a LEVEL. "Healthcare leads on change at 0.04 pp, 2,352% above
    Financial Services" is arithmetically true and analytically nonsense: a
    proportional gap between two signed movements says nothing about either.
    """
    named = [(name, value) for name, value in series if name]
    if len(named) < 2:
        return []
    ranked = sorted(named, key=lambda pair: pair[1], reverse=True)
    (first, top), (second, runner) = ranked[0], ranked[1]
    # A proportional gap needs both sides on the same side of zero and a
    # denominator that means something.
    if top <= 0 or runner < 0:
        return []

    gap = 100.0 * (top - runner) / top if top else 0.0
    if gap < 15.0:
        return []

    from backend.orchestration import figures

    return [Observation(
        kind=DRIVER, weight=gap,
        text=(f"{first} leads on {label} at {shown(top)}, "
              f"{figures.percent(gap)} above {second} behind it."),
        facts={"leader": first, "leader_value": top, "runner_up": second,
               "gap_pct": round(gap, 2)})]


def _exceptions(series: list[tuple[str, float]], label: str,
                shown: Any) -> list[Observation]:
    """The rows that do not fit the shape of the rest.

    Measured in median absolute deviations rather than standard deviations. One
    enormous row inflates a standard deviation until nothing looks unusual,
    which is exactly the case where an exception matters most.
    """
    named = [(name, value) for name, value in series if name]
    if len(named) < MIN_ROWS_FOR_SHAPE:
        return []

    ordered = sorted(value for _, value in named)
    middle = _median(ordered)
    spread = _median(sorted(abs(value - middle) for _, value in named))
    if spread <= 0:
        return []

    unusual = [(name, value) for name, value in named
               if abs(value - middle) / spread >= OUTLIER_DEVIATIONS]
    if not unusual or len(unusual) > len(named) // 3:
        return []

    unusual.sort(key=lambda pair: abs(pair[1] - middle), reverse=True)
    names = ", ".join(name for name, _ in unusual[:3])
    more = f" and {len(unusual) - 3} others" if len(unusual) > 3 else ""
    plural = len(unusual[:3]) > 1 or bool(more)
    return [Observation(
        kind=EXCEPTION, weight=100.0,
        text=(f"{names}{more} {'sit' if plural else 'sits'} well outside the "
              f"rest — the typical {label} here is {shown(middle)}, "
              f"and {unusual[0][0]} is at {shown(unusual[0][1])}."),
        facts={"exceptions": [name for name, _ in unusual[:3]],
               "median": round(middle, 4)})]


def _movement(build: Any, rows: list[dict[str, Any]], schema: list[dict[str, Any]],
              values: dict[str, Any], figures: Any) -> list[Observation]:
    """Which way it moved, and whether the movement is broad or narrow."""
    from backend.orchestration import presentation as pr

    change = next((c for c in schema
                   if not c.get("hidden") and _rank(c) == pr.RANK_DERIVED
                   and str(c.get("name")).endswith(("_change", "_change_pct",
                                                    "change_pp"))), None)
    if change is None:
        return []

    column = str(change.get("name"))

    # A cohort selected ON a movement moved that way in every row by
    # construction. "170 of 170 rose and 0 fell on change in internal rating"
    # is true, tautological, and reads as though CreditProbe has not noticed
    # what it just did.
    if _was_selected_on(build, column):
        return []

    label = _in_sentence(str(change.get("label") or column))
    moved = [(str(row.get(_subject_key(schema), "")), float(row[column]))
             for row in rows
             if isinstance(row.get(column), (int, float))
             and not isinstance(row.get(column), bool)]
    if not moved:
        return []

    rose = [pair for pair in moved if pair[1] > 0]
    fell = [pair for pair in moved if pair[1] < 0]
    biggest = max(moved, key=lambda pair: abs(pair[1]))

    where = f" — {biggest[0]} most, at {pr.render(biggest[1], change)}" \
        if biggest[0] else ""
    return [Observation(
        kind=DIRECTION, weight=abs(biggest[1]),
        text=(f"{len(rose)} of {len(moved)} rose and {len(fell)} fell on "
              f"{label}{where}."),
        facts={"rose": len(rose), "fell": len(fell), "of": len(moved),
               "largest": biggest[0], "largest_change": biggest[1]})]


def _was_selected_on(build: Any, column: str) -> bool:
    """Whether the population was chosen by how this very column moved."""
    lowered = column.lower()
    for condition in (getattr(build, "conditions", None) or []):
        if str(getattr(condition, "kind", "")) in ("change_pct", "change_abs"):
            field = str(getattr(condition, "field", "") or "").lower()
            if field and field in lowered:
                return True
    return False


def _limitations(build: Any, runtime: Any) -> list[Observation]:
    """What stops a reader concluding more than the result supports."""
    out: list[Observation] = []
    truncated = int(getattr(runtime, "truncated", 0) or 0)
    if truncated:
        out.append(Observation(
            kind=LIMITATION, weight=100.0,
            text=(f"{truncated:,} further rows met the same test and are not "
                  "shown, so the figures here describe the top of the "
                  "population rather than all of it."),
            facts={"truncated": truncated}))

    population = (getattr(build, "plan", None) or {}).get("meta") or {}
    carried = int((population.get("population") or {}).get("count") or 0)
    if carried:
        out.append(Observation(
            kind=LIMITATION, weight=50.0,
            text=(f"This covers the {carried} carried forward from the "
                  "previous answer, not the whole book."),
            facts={"population": carried}))
    return out


# ---------------------------------------------------------------------------
# Turning them into an interpretation
# ---------------------------------------------------------------------------


def _opening(text: str) -> str:
    """A sentence starting with a capital, without mangling an acronym."""
    stripped = str(text or "").strip()
    if not stripped:
        return stripped
    return stripped[:1].upper() + stripped[1:]


def summarise(observations: list[Observation], *, limit: int = 3) -> str:
    """The observations as a paragraph, in the order an analyst would say them.

    Used when there is no provider, and as the floor when a live interpretation
    is withheld. Deliberately short: three specific sentences beat a paragraph
    of hedging, and the figures are directly beneath.
    """
    chosen = rank(observations)[:limit]
    return " ".join(_opening(o.text) for o in chosen)


def rank(observations: list[Observation]) -> list[Observation]:
    """The observations worth making, most useful first, one per kind.

    And one per SUBJECT. Three sentences about the same borrower — it holds the
    largest share, it leads the ranking, it sits outside the rest — are one
    observation said three ways, and a reader who gets all three concludes the
    product has nothing else to say.
    """
    best: dict[str, Observation] = {}
    for observation in observations:
        current = best.get(observation.kind)
        if current is None or observation.weight > current.weight:
            best[observation.kind] = observation

    ordered: list[Observation] = []
    spoken_for: set[str] = set()
    for kind in ORDER:
        observation = best.get(kind)
        if observation is None:
            continue
        about = _about(observation)
        if about and about in spoken_for:
            continue
        if about:
            spoken_for.add(about)
        ordered.append(observation)
    return ordered[:MAX_OBSERVATIONS]


def _about(observation: Observation) -> str:
    """Which row this observation is about, where it is about one."""
    facts = observation.facts or {}
    for key in ("top", "leader", "largest"):
        value = facts.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    exceptions = facts.get("exceptions")
    if isinstance(exceptions, list) and len(exceptions) == 1:
        return str(exceptions[0])
    return ""


def prompt_block(observations: list[Observation]) -> str:
    """What the model is told an analyst would notice about this result.

    Given as observations rather than as instructions. A style guide produces
    prose that sounds like analysis; a list of specific computed facts produces
    prose about the largest driver by name.
    """
    chosen = rank(observations)
    if not chosen:
        return ""
    lines = ["", "WHAT AN ANALYST WOULD NOTICE (computed from the result "
                 "above — use these, and add nothing they do not support):"]
    lines.extend(f"  - {o.text}" for o in chosen)
    return "\n".join(lines)


def _median(ordered: list[float]) -> float:
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _subject_key(schema: list[dict[str, Any]]) -> str:
    from backend.orchestration import presentation as pr

    for column in schema:
        if not column.get("hidden") and _rank(column) <= pr.RANK_SUBJECT:
            return str(column.get("name"))
    return ""


__all__ = ["BREADTH", "COMPARISON", "CONCENTRATED_AT", "CONCENTRATION",
           "CONCLUSION", "DIRECTION", "DRIVER", "EXCEPTION", "LIMITATION",
           "MAGNITUDE", "MAX_OBSERVATIONS", "NEXT_STEP", "ORDER",
           "OUTLIER_DEVIATIONS", "Observation", "SIGNIFICANCE", "TOP_THREE_AT",
           "observe", "prompt_block", "rank", "summarise"]

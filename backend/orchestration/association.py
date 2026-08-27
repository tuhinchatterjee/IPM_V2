"""
"Does this trend make sense?" is a question, not a refusal.

The failure
-----------
A credit officer looked at ECL coverage and DSCR across rating grades and asked
whether the relationship was consistent. CreditProbe replied that it holds no
governed data about "make sense" — the coverage check had read the sentence for
nouns, found one it did not recognise, and declined.

That is the wrong answer twice over. The data to answer it was on the screen,
and the question is one of the most common things an analyst is asked.

What this does
--------------
Computes the association and describes it. Never asserts a cause.

* **Monotonicity** — does the measure move in one direction across the ordered
  groups, and how many steps break it.
* **Rank association** — Spearman's rho between each pair of measures across
  the groups. Rank rather than level, because a credit relationship is usually
  ordinal ("worse grades have thinner cover") rather than linear.
* **Linear association** — Pearson, reported beside it. Where the two disagree
  the relationship is not linear, and saying so is more useful than either
  number alone.
* **Exceptions** — the groups that break the pattern, named. An analyst's first
  question about any trend is which rows do not fit it, and a correlation
  coefficient with no exceptions listed is a number nobody can act on.

What it will not do
-------------------
Say that one thing caused another. The wording is fixed and deliberate:
"consistent with", "moves with", "does not fit". A dataset of quarterly
aggregates cannot establish causation, and prose that implies it would pass
every numerical check in this product while being the most damaging thing it
could write.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import kernels

logger = logging.getLogger(__name__)

#: Below this many groups no association is reported. Three points can be made
#: to correlate perfectly with anything, and a coefficient over four grades is
#: a description of four numbers rather than a finding.
MIN_GROUPS = 5

#: |rho| bands, in the words a credit paper uses.
STRONG = 0.7
MODERATE = 0.4

#: How many exceptions are named before the sentence stops listing them.
MAX_EXCEPTIONS = 3

#: Questions that ask whether a pattern holds, rather than for a figure.
#:
#: Deliberately narrow. "Why is Contracting highest?" is a different question —
#: it asks for a cause, and the honest answer to it is that the result shows
#: what moved rather than why.
_ASKS: tuple[str, ...] = (
    r"\bdoes .{0,60}\bmake sense\b",
    r"\bmakes? sense\b",
    r"\b(?:is|are) (?:this|that|these|those|the) .{0,40}"
    r"(?:justified|reasonable|plausible|consistent|expected)\b",
    r"\b(?:does|do) .{0,60}\b(?:appear|look|seem) (?:consistent|reasonable|"
    r"plausible|sensible|right)\b",
    r"\bconsistent across\b",
    r"\bdo you see a (?:pattern|relationship|trend|association)\b",
    r"\b(?:is there|any) (?:a )?(?:pattern|relationship|association|correlation)\b",
    r"\bhow (?:closely|strongly) (?:are|do) .{0,50}(?:related|relate|move)\b",
    r"\b(?:relationship|association|correlation) between\b.{0,80}"
    r"\b(?:consistent|hold|appear|justified|meaningful)\b",
    r"\bmonotonic\b", r"\bcorrelated?\b",
)

_PATTERN = re.compile("|".join(_ASKS), re.I)

#: Words that make it a request for a cause rather than for a description.
#: These are still answered — with the association AND the statement that the
#: data cannot establish why.
_CAUSAL = re.compile(r"\bwhy\b|\bcause[sd]?\b|\bbecause\b|\bdrives?\b|\bdriven\b",
                     re.I)


def wants(question: str) -> bool:
    """Whether this sentence asks whether a pattern holds."""
    return bool(_PATTERN.search(question or ""))


def asks_why(question: str) -> bool:
    return bool(_CAUSAL.search(question or ""))


# ---------------------------------------------------------------------------
# The statistics
# ---------------------------------------------------------------------------


@dataclass
class Pair:
    """How two measures move together across the groups."""

    a: str
    b: str
    a_label: str = ""
    b_label: str = ""
    spearman: float | None = None
    pearson: float | None = None
    #: Groups whose rank on `b` is far from where its rank on `a` puts it.
    exceptions: list[str] = field(default_factory=list)
    groups: int = 0

    @property
    def strength(self) -> str:
        rho = abs(self.spearman or 0.0)
        if rho >= STRONG:
            return "strong"
        if rho >= MODERATE:
            return "moderate"
        return "weak"

    @property
    def direction(self) -> str:
        if self.spearman is None:
            return "unclear"
        return "same" if self.spearman >= 0 else "opposite"

    @property
    def linear(self) -> bool:
        """Whether the level relationship agrees with the rank one."""
        if self.spearman is None or self.pearson is None:
            return True
        return abs(abs(self.spearman) - abs(self.pearson)) < 0.2

    def to_dict(self) -> dict[str, Any]:
        return {"a": self.a, "b": self.b,
                "a_label": self.a_label or self.a,
                "b_label": self.b_label or self.b,
                "spearman": self.spearman, "pearson": self.pearson,
                "strength": self.strength, "direction": self.direction,
                "linear": self.linear, "groups": self.groups,
                "exceptions": list(self.exceptions)}


@dataclass
class Trend:
    """Whether one measure moves in one direction across ordered groups."""

    measure: str
    label: str = ""
    direction: str = ""      # rising | falling | mixed
    monotonic: bool = False
    breaks: list[str] = field(default_factory=list)
    first: float | None = None
    last: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"measure": self.measure, "label": self.label or self.measure,
                "direction": self.direction, "monotonic": self.monotonic,
                "breaks": list(self.breaks), "first": self.first,
                "last": self.last}


@dataclass
class Analysis:
    """Everything the answer is allowed to say about the pattern."""

    subject: str = ""
    subject_label: str = ""
    groups: int = 0
    trends: list[Trend] = field(default_factory=list)
    pairs: list[Pair] = field(default_factory=list)
    #: Why no analysis, when there is none.
    unavailable: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.groups >= MIN_GROUPS and (self.trends or self.pairs))

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject,
                "subject_label": self.subject_label or self.subject,
                "groups": self.groups,
                "trends": [t.to_dict() for t in self.trends],
                "pairs": [p.to_dict() for p in self.pairs],
                "unavailable": self.unavailable}


def _ranks(values: list[float]) -> list[float]:
    """Average ranks. The implementation lives in the approved kernels."""
    return kernels.ranks(values)


def _pearson(left: list[float], right: list[float]) -> float | None:
    return kernels.pearson(left, right).value


def _spearman(left: list[float], right: list[float]) -> float | None:
    return kernels.spearman(left, right).value


def _trend(labels: list[str], values: list[float], measure: str,
           label: str) -> Trend:
    steps = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    rising = sum(1 for s in steps if s > 0)
    falling = sum(1 for s in steps if s < 0)
    direction = ("rising" if rising and not falling else
                 "falling" if falling and not rising else "mixed")
    breaks: list[str] = []
    if direction == "mixed":
        # The steps that go against the majority direction. Named, because the
        # exception is what an analyst asks about first.
        against = (lambda s: s < 0) if rising >= falling else (lambda s: s > 0)
        breaks = [labels[i + 1] for i, s in enumerate(steps) if against(s)]
    return Trend(measure=measure, label=label, direction=direction,
                 monotonic=direction in ("rising", "falling"),
                 breaks=breaks[:MAX_EXCEPTIONS],
                 first=values[0] if values else None,
                 last=values[-1] if values else None)


def _exceptions(labels: list[str], left: list[float], right: list[float],
                rho: float | None) -> list[str]:
    """Groups that do not fit the association the other groups describe.

    The arithmetic is `kernels.exceptions`, which is the same operation this
    module used to own privately. It moved because "does this trend make
    sense?" answers itself from a STORED result and may run only approved
    kernels — and two implementations of the same statistic would eventually
    disagree about which grades are exceptions depending on how the question
    was phrased.
    """
    return kernels.exceptions(left, right, labels, rho).labels


# ---------------------------------------------------------------------------
# Reading a result
# ---------------------------------------------------------------------------


def analyse(columns: list[dict[str, Any]], rows: list[dict[str, Any]]) -> Analysis:
    """The association in a result that is already on the table.

    Reads the presentation schema rather than the raw frame, so a rating grade
    stored as an integer is the SUBJECT and not a third measure to correlate
    against the other two.
    """
    try:
        return _analyse(columns, rows)
    except Exception as e:  # noqa: BLE001 - a description must not lose an answer
        logger.warning("Could not compute an association: %s", e)
        return Analysis(unavailable="the association could not be computed")


def _analyse(columns: list[dict[str, Any]],
             rows: list[dict[str, Any]]) -> Analysis:
    from backend.orchestration import presentation as pr

    visible = [c for c in (columns or []) if not c.get("hidden")]
    # `or` would read rank 0 — the subject rank — as missing, which is the one
    # value this has to recognise.
    def rank_of(column: dict[str, Any]) -> int:
        value = column.get("rank")
        return int(value) if value is not None else pr.RANK_CONTEXT

    subject = next((c for c in visible if rank_of(c) <= pr.RANK_SUBJECT), None)
    measures = [c for c in visible
                if str(c.get("semantic") or "") in
                (pr.MONEY, pr.PERCENT, pr.RATIO, pr.COUNT, pr.DAYS)]

    if subject is None or not measures:
        return Analysis(unavailable=(
            "this result has no group to compare measures across"))

    name = str(subject.get("name"))
    labels: list[str] = []
    series: dict[str, list[float]] = {str(m.get("name")): [] for m in measures}
    for row in (rows or []):
        values = {}
        ok = True
        for measure in measures:
            key = str(measure.get("name"))
            value = row.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                ok = False
                break
            values[key] = float(value)
        if not ok:
            continue
        labels.append(str(row.get(name)))
        for key, value in values.items():
            series[key].append(value)

    found = Analysis(subject=name,
                     subject_label=str(subject.get("label") or name),
                     groups=len(labels))
    if len(labels) < MIN_GROUPS:
        found.unavailable = (
            f"{len(labels)} groups is too few to describe a pattern — "
            f"{MIN_GROUPS} is the minimum this reports on")
        return found

    by_name = {str(m.get("name")): str(m.get("label") or m.get("name"))
               for m in measures}
    for key, values in series.items():
        found.trends.append(_trend(labels, values, key, by_name[key]))

    names = list(series)
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            rho = _spearman(series[left], series[right])
            found.pairs.append(Pair(
                a=left, b=right,
                a_label=by_name[left], b_label=by_name[right],
                spearman=rho,
                pearson=_pearson(series[left], series[right]),
                exceptions=_exceptions(labels, series[left], series[right], rho),
                groups=len(labels)))
    return found


# ---------------------------------------------------------------------------
# Saying it
# ---------------------------------------------------------------------------

#: The sentence that ends every association answer. Fixed wording, because the
#: one thing this must never do is drift into implying a cause.
CAVEAT = (
    "This describes how the figures move together across the groups; it does "
    "not establish that one causes the other. Ordering effects, portfolio mix "
    "and the vintage of each group all produce the same pattern, and "
    "separating them needs a controlled comparison rather than an aggregate.")


def describe(found: Analysis) -> str:
    """The association in the words a credit paper would use."""
    from backend.orchestration import figures

    if not found.usable:
        return found.unavailable or "no pattern could be described"

    def said(label: str) -> str:
        """A measure name mid-sentence. "ECL coverage", never "ecl coverage"."""
        text = str(label or "").strip()
        if not text:
            return text
        first = text.split()[0]
        if first.isupper() or any(c.isdigit() for c in first):
            return text
        return text[:1].lower() + text[1:]

    parts: list[str] = []
    # The group context is stated once. Repeating "across 10 internal grade
    # groups" in front of every pair turns three findings into one paragraph
    # nobody finishes.
    where = f"Across {found.groups} {said(found.subject_label)} groups"
    first = True
    for pair in found.pairs:
        if pair.spearman is None:
            continue
        moves = ("move together" if pair.direction == "same"
                 else "move in opposite directions")
        lead = f"{where}, " if first else ""
        first = False
        sentence = (
            f"{lead}{said(pair.a_label)} and {said(pair.b_label)} {moves} "
            f"{pair.strength}ly (Spearman "
            f"{figures.text(pair.spearman, figures.Spec(decimals=2))})")
        if not pair.linear and pair.pearson is not None:
            sentence += (
                f", though the level relationship is weaker than the rank one "
                f"(Pearson {figures.text(pair.pearson, figures.Spec(decimals=2))}), "
                "so the pattern is ordinal rather than proportional")
        if pair.exceptions:
            sentence += (". " + ", ".join(pair.exceptions)
                         + (" does" if len(pair.exceptions) == 1 else " do")
                         + " not fit it")
        parts.append((sentence[:1].upper() + sentence[1:] if not lead
                      else sentence) + ".")

    for trend in found.trends:
        if trend.monotonic:
            parts.append(
                f"{trend.label} is {trend.direction} consistently across every "
                f"{said(found.subject_label)} group.")
        elif trend.breaks:
            # "It reverses at 9" reads as a quantity. A grade stored as an
            # integer needs its noun in front of it or the sentence is about
            # something else.
            named = [b if not str(b).replace(".", "").isdigit()
                     else f"{said(found.subject_label)} {b}"
                     for b in trend.breaks]
            parts.append(
                f"{trend.label} does not move in one direction: it reverses at "
                + ", ".join(named) + ".")
    return " ".join(parts)


__all__ = ["CAVEAT", "MAX_EXCEPTIONS", "MIN_GROUPS", "MODERATE", "STRONG",
           "Analysis", "Pair", "Trend", "analyse", "asks_why", "describe",
           "wants"]

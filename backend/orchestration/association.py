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
    #: Where the series begins and ends, and where it turns. A V-shaped
    #: series described by the steps that go against the majority named three
    #: arbitrary months as turning points; what it actually does is fall to a
    #: low and then rise, and the low is the date a reader needs.
    first_label: str = ""
    last_label: str = ""
    low: float | None = None
    low_label: str = ""
    high: float | None = None
    high_label: str = ""
    rising_steps: int = 0
    falling_steps: int = 0
    #: The presentation contract of the column this measures, so the figures
    #: in the sentence are written as money, a percentage or days rather than
    #: as bare decimals.
    column: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"measure": self.measure, "label": self.label or self.measure,
                "direction": self.direction, "monotonic": self.monotonic,
                "breaks": list(self.breaks), "first": self.first,
                "last": self.last, "first_label": self.first_label,
                "last_label": self.last_label,
                "low": self.low, "low_label": self.low_label,
                "high": self.high, "high_label": self.high_label,
                "rising_steps": self.rising_steps,
                "falling_steps": self.falling_steps}


@dataclass
class Analysis:
    """Everything the answer is allowed to say about the pattern."""

    subject: str = ""
    subject_label: str = ""
    groups: int = 0
    trends: list[Trend] = field(default_factory=list)
    pairs: list[Pair] = field(default_factory=list)
    #: True when each row is a reporting date rather than a category. A series
    #: is read in time, and the words for it are different: twelve months are
    #: not twelve "groups", and the figure at each is a total, not an average
    #: over the members of a group.
    over_time: bool = False
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
                "over_time": self.over_time,
                "unavailable": self.unavailable}


def _ranks(values: list[float]) -> list[float]:
    """Average ranks. The implementation lives in the approved kernels."""
    return kernels.ranks(values)


def _pearson(left: list[float], right: list[float]) -> float | None:
    return kernels.pearson(left, right).value


def _spearman(left: list[float], right: list[float]) -> float | None:
    return kernels.spearman(left, right).value


def _said(label: str) -> str:
    """A column label as it reads inside a sentence."""
    return str(label or "").strip().lower()


def _trend(labels: list[str], values: list[float], measure: str,
           label: str, column: dict[str, Any] | None = None) -> Trend:
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
    low_at = min(range(len(values)), key=lambda i: values[i]) if values else 0
    high_at = max(range(len(values)), key=lambda i: values[i]) if values else 0
    return Trend(measure=measure, label=label, direction=direction,
                 monotonic=direction in ("rising", "falling"),
                 breaks=breaks[:MAX_EXCEPTIONS],
                 first=values[0] if values else None,
                 last=values[-1] if values else None,
                 first_label=labels[0] if labels else "",
                 last_label=labels[-1] if labels else "",
                 low=values[low_at] if values else None,
                 low_label=labels[low_at] if labels else "",
                 high=values[high_at] if values else None,
                 high_label=labels[high_at] if labels else "",
                 rising_steps=rising, falling_steps=falling,
                 column=dict(column or {}))


#: Suffixes a derived column carries when it restates the measure it came
#: from — a share of the population, a rank within it, a percentage of it.
_DERIVED_SUFFIXES = ("_share_pct", "_share", "_pct_of_total", "_rank",
                     "_population", "_pct")


def _one_derives_the_other(left: str, right: str) -> bool:
    """Whether one of these columns is the other restated."""
    a, b = str(left or ""), str(right or "")
    for base, other in ((a, b), (b, a)):
        for suffix in _DERIVED_SUFFIXES:
            if other == f"{base}{suffix}":
                return True
    return False


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


def _one_row_per_group(columns: list[dict[str, Any]],
                       rows: list[dict[str, Any]]
                       ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A breakdown read at two dates, laid out one row per group.

    A movement broken down by region returns one row per region PER DATE —
    thirteen regions at two dates is twenty-six rows, and read as it stands it
    described "26 region label groups" and could find only one measure to
    reason about. Pivoted, it is thirteen groups carrying the measure at each
    date, which is what the reader is looking at and what makes "does that
    look consistent?" answerable.

    Returns the input unchanged whenever the result is not that shape.
    """
    from backend.orchestration import presentation as pr

    def rank_of(column: dict[str, Any]) -> int:
        value = column.get("rank")
        return int(value) if value is not None else pr.RANK_CONTEXT

    visible = [c for c in (columns or []) if not c.get("hidden")]
    period = next((c for c in visible if rank_of(c) == pr.RANK_PERIOD), None)
    subject = next((c for c in visible if rank_of(c) <= pr.RANK_SUBJECT), None)
    if period is None or subject is None or not rows:
        return columns, rows

    key, at = str(subject.get("name")), str(period.get("name"))
    dates = []
    for row in rows:
        value = str(row.get(at) or "")
        if value and value not in dates:
            dates.append(value)
    groups = {str(r.get(key) or "") for r in rows}
    if len(dates) < 2 or len(groups) * len(dates) != len(rows):
        return columns, rows

    measures = [c for c in visible
                if str(c.get("semantic") or "") in
                (pr.MONEY, pr.PERCENT, pr.RATIO, pr.COUNT, pr.DAYS)
                and rank_of(c) < pr.RANK_CONTEXT]
    if not measures:
        return columns, rows

    dates = sorted(dates)
    out_columns: list[dict[str, Any]] = [dict(subject)]
    for measure in measures:
        for index, date in enumerate(dates):
            out_columns.append({
                **measure,
                "name": f"{measure.get('name')}__{date}",
                "label": f"{measure.get('label') or measure.get('name')} "
                         f"at {date}",
                "rank": pr.RANK_PRIMARY if index == 0 else pr.RANK_COMPARISON,
            })

    built: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = str(row.get(key) or "")
        date = str(row.get(at) or "")
        if not group or date not in dates:
            continue
        held = built.setdefault(group, {key: row.get(key)})
        for measure in measures:
            name = str(measure.get("name"))
            held[f"{name}__{date}"] = row.get(name)
    return out_columns, list(built.values())


def analyse(columns: list[dict[str, Any]], rows: list[dict[str, Any]]) -> Analysis:
    """The association in a result that is already on the table.

    Reads the presentation schema rather than the raw frame, so a rating grade
    stored as an integer is the SUBJECT and not a third measure to correlate
    against the other two.
    """
    try:
        columns, rows = _one_row_per_group(columns, rows)
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
    # A SERIES has no grouping column: what each row is about is the reporting
    # month, which the presentation layer ranks as a period rather than as a
    # subject. Without this, "does this trend make sense?" asked of a twelve
    # month series — the one result the question is most often asked of — was
    # told the result had no group to compare measures across.
    period = next((c for c in visible if rank_of(c) == pr.RANK_PERIOD), None)
    if subject is None:
        subject = period
    # A measure the question asked for, or one derived from it — never a
    # CONTEXT column. The number of facilities behind each group qualifies the
    # row; it is not a figure the reader asked about. Correlated as though it
    # were, an ECL coverage ranking came back as "groups with higher ECL
    # Coverage carry lower facilities (Spearman -0.12)": a real statistic over
    # two columns nobody had asked to compare.
    measures = [c for c in visible
                if str(c.get("semantic") or "") in
                (pr.MONEY, pr.PERCENT, pr.RATIO, pr.COUNT, pr.DAYS)
                and rank_of(c) < pr.RANK_CONTEXT]

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
                     groups=len(labels),
                     over_time=bool(period is not None and subject is period))
    # A TREND needs the subject to have an order of its own — a month, a
    # rating grade, a delinquency bucket. Thirteen regions have none, and a
    # ranking is written largest first, so "ECL Coverage falls consistently
    # across all 13 regions" was the sort order restated as a finding.
    ordered_subject = (
        str(subject.get("semantic") or "") in (pr.ORDINAL, pr.PERIOD)
        or bool(subject.get("ordered"))
        or (period is not None and subject is period))
    if len(labels) < MIN_GROUPS:
        found.unavailable = (
            f"{len(labels)} groups is too few to describe a pattern — "
            f"{MIN_GROUPS} is the minimum this reports on")
        return found

    by_name = {str(m.get("name")): str(m.get("label") or m.get("name"))
               for m in measures}
    by_column = {str(m.get("name")): dict(m) for m in measures}
    if ordered_subject:
        for key, values in series.items():
            found.trends.append(
                _trend(labels, values, key, by_name[key], by_column.get(key)))
    elif len(measures) < 2:
        # One measure, over groups with no order of their own. There is
        # nothing to correlate it against and nothing to trend it along, and
        # saying so is the answer.
        one = by_name[str(measures[0].get("name"))]
        found.unavailable = (
            f"this result holds one measure — {one} — across "
            f"{len(labels)} {_said(found.subject_label)} groups that have no "
            "order of their own, so there is no second figure to compare it "
            "with and no sequence to trend it along")
        return found

    names = list(series)
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            # A measure against its own share of the total is one figure
            # divided by a constant. The rank correlation is 1.00 by
            # construction, and reporting it read as a finding: "expected
            # credit loss and expected credit loss share move together
            # strongly (Spearman 1.00)".
            if _one_derives_the_other(left, right):
                continue
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

#: The same sentence for a SERIES, where there are no groups and often only
#: one figure. Said of a twelve-month line, the wording above described a
#: comparison the result does not contain.
CAVEAT_OVER_TIME = (
    "This describes the shape of the series; it does not establish what moved "
    "it. New lending, run-off, write-offs and model or staging changes all "
    "move the line, and separating them needs the movement decomposed rather "
    "than the totals compared.")


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


__all__ = ["CAVEAT", "CAVEAT_OVER_TIME", "MAX_EXCEPTIONS", "MIN_GROUPS", "MODERATE", "STRONG",
           "Analysis", "Pair", "Trend", "analyse", "asks_why", "describe",
           "wants"]

"""
Answering an analytical question about the book, before anything is shocked.

The defect this exists to fix
-----------------------------
A person opened a What-If thread and asked:

    "Can you give me the rating-wise PDs, getting rid of stages?"

and was told:

    "That asks about the book rather than changing it. The profile views
     answer it without an ECL calculation, so no methodology is needed."

Every clause of that is true and the whole of it is useless. The person is
looking at a composer, they have asked a precise analytical question with a
dimension (rating), a metric (PD) and an explicit instruction about the Stage
split (remove it), and the product has replied by naming a different screen.
Pointing at a tab is not an answer; it is a redirect with a paragraph of
justification attached.

Worse, it defeats the reason the question was asked. Nobody asks for
rating-wise PDs out of curiosity in a scenario builder. They ask because they
are deciding what shock to configure, and "increase BBB PD by 20%" is a
different instruction depending on whether BBB PD is 0.18% or 1.8%. The
question is PART of configuring the scenario, so it has to be answered where
the scenario is being built.

What this module is
-------------------
A deterministic reader and a deterministic calculator. `read()` turns a
sentence into a `Request` — a dimension, a set of metrics, filters, and what to
do about the Stage split — and `run()` computes the table from the reported
book. No model is consulted to decide what was asked, and no model produces a
figure: an interpretation is written over the table afterwards, and it is
written over numbers that already exist.

Nothing here changes the scenario. A quick analysis is a read, and the
scenario state it is handed comes back untouched.

Follow-ups
----------
The second question in a conversation is rarely a whole question. "Only show
BBB- and weaker" names no metric; "show exposure too" names no dimension;
"which sector has the highest PD within BB?" changes the dimension and keeps
the metric. So `read()` takes the PREVIOUS request and merges into it, and the
merge is deliberately asymmetric: a follow-up may add a metric, narrow a
filter, change the dimension or reorder, and it never silently drops something
the reader did not mention.

Exposure weighting
------------------
Every rate here is reported twice, under two names, because the two answer
different questions and quietly picking one is how a screen ends up disagreeing
with the ECL underneath it. `mean` answers "what is the average borrower like";
`weighted` answers "what is the book exposed to". A coverage ratio is always
summed-over-summed and never an average of ratios.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from backend.corporate import ratingscale as rs
from backend.whatif import domain as dm
from backend.whatif import profiles as pf

ANALYSIS_VERSION = "1.0.0"

# ------------------------------------------------------------- dimensions

RATING = "rating"
STAGE = "stage"
SECTOR = "sector"
SEGMENT = "segment"
BAND = "rating_band"
SECURED = "secured"
BORROWER = "borrower"
NONE = "none"

DIMENSIONS: tuple[str, ...] = (RATING, STAGE, SECTOR, SEGMENT, BAND, SECURED,
                               BORROWER, NONE)

DIMENSION_LABEL: dict[str, str] = {
    RATING: "Rating", STAGE: "Stage", SECTOR: "Sector", SEGMENT: "Segment",
    BAND: "Rating band", SECURED: "Security", BORROWER: "Borrower",
    NONE: "Portfolio",
}

#: The broad bands, in scale order. Used when somebody asks for "AAA to A" or
#: for a table that is nineteen rows too long to read.
BROAD_BANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AAA", ("AAA",)), ("AA", ("AA+", "AA", "AA-")), ("A", ("A+", "A", "A-")),
    ("BBB", ("BBB+", "BBB", "BBB-")), ("BB", ("BB+", "BB", "BB-")),
    ("B", ("B+", "B", "B-")), ("CCC", ("CCC",)), ("CC", ("CC",)), ("C", ("C",)),
    ("D", (rs.DEFAULT_GRADE,)),
)

# ---------------------------------------------------------------- metrics


@dataclass(frozen=True)
class Metric:
    """One measure a breakdown can carry, and how it is aggregated.

    `kind` is what the aggregation MEANS, not merely which function to call:
    a `total` is summed, a `rate` is reported as both a plain and an
    exposure-weighted mean, and a `ratio` is summed-over-summed. Getting that
    wrong is the difference between "the book's ECL coverage is 1.4%" and "the
    average borrower's coverage ratio is 3.1%", which are both true and are not
    the same number.
    """

    key: str
    label: str
    column: str
    unit: str
    kind: str          # "count" | "total" | "rate" | "ratio"
    over: str = ""     # for a ratio: the denominator column


COUNT = Metric("borrowers", "Borrowers", "", "", "count")
EXPOSURE = Metric("exposure", "Exposure", "ead", dm.CURRENCY, "total")
ECL = Metric("ecl", "ECL", "final_ecl", dm.CURRENCY, "total")
COVERAGE = Metric("ecl_coverage", "ECL coverage", "final_ecl", "%", "ratio",
                  over="ead")
TTC = Metric("ttc_pd", "TTC PD", "ttc_pd_pct", "%", "rate")
PIT = Metric("pit_pd_12m", "PIT 12m PD", "pd_12m", "%", "rate")
LIFETIME = Metric("lifetime_pd", "Lifetime PD", "pd_lifetime", "%", "rate")
APPLICABLE = Metric("applicable_pd", "Applicable PD", "_applicable", "%", "rate")
LGD = Metric("lgd", "LGD", "lgd", "%", "rate")
CCF = Metric("ccf", "CCF", "ccf", "%", "rate")
COLLATERAL = Metric("collateral_coverage", "Collateral coverage",
                    "collateral_coverage_pct", "%", "rate")
DPD = Metric("dpd", "Days past due", "current_dpd", "days", "rate")
STAGE_MEAN = Metric("stage", "Stage", "stage", "", "rate")

METRICS: dict[str, Metric] = {
    m.key: m for m in (COUNT, EXPOSURE, ECL, COVERAGE, TTC, PIT, LIFETIME,
                       APPLICABLE, LGD, CCF, COLLATERAL, DPD, STAGE_MEAN)
}

#: What "PD" means when somebody says it without qualifying. All three, plus
#: the one the measurement actually uses, because the interesting thing about a
#: rating-wise PD table is precisely how far the three diverge.
ALL_PDS: tuple[Metric, ...] = (TTC, PIT, LIFETIME, APPLICABLE)

#: Always shown, whatever was asked, because a rate without a population behind
#: it is unreadable: "CCC PD is 19%" means something different over four
#: borrowers than over four hundred.
CONTEXT: tuple[Metric, ...] = (COUNT, EXPOSURE)


class AnalysisError(dm.DomainError):
    """A question this cannot answer, said rather than approximated."""


# ------------------------------------------------------------- the request


@dataclass(frozen=True)
class Request:
    """What was asked, in a form that can be computed and re-asked."""

    dimension: str = RATING
    metrics: tuple[str, ...] = ()
    #: Stage 1 / 2 / 3 to restrict to. Empty means the whole book.
    stages: tuple[int, ...] = ()
    #: Grades to restrict to, in scale order. Empty means all of them.
    grades: tuple[str, ...] = ()
    sectors: tuple[str, ...] = ()
    segments: tuple[str, ...] = ()
    #: (metric key, ">" or "<", value in the metric's own unit).
    threshold: tuple[str, str, float] | None = None
    #: Split each row of the table by Stage as well as by the dimension.
    by_stage: bool = False
    #: Order by this metric, weakest-first when empty (the scale's own order).
    order_by: str = ""
    descending: bool = True
    limit: int = 0
    #: "highest" or "lowest" — the reader wants one row, not a table.
    superlative: str = ""
    period: str = ""
    question: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "dimension_label": DIMENSION_LABEL.get(self.dimension, self.dimension),
            "metrics": list(self.metrics),
            "stages": list(self.stages),
            "grades": list(self.grades),
            "sectors": list(self.sectors),
            "segments": list(self.segments),
            "threshold": list(self.threshold) if self.threshold else None,
            "by_stage": self.by_stage,
            "order_by": self.order_by,
            "descending": self.descending,
            "limit": self.limit,
            "superlative": self.superlative,
            "period": self.period,
            "question": self.question,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, body: Any) -> Request | None:
        if not isinstance(body, dict) or not body:
            return None
        threshold = body.get("threshold")
        return cls(
            dimension=str(body.get("dimension") or RATING),
            metrics=tuple(str(m) for m in (body.get("metrics") or [])),
            stages=tuple(int(s) for s in (body.get("stages") or [])),
            grades=tuple(str(g) for g in (body.get("grades") or [])),
            sectors=tuple(str(s) for s in (body.get("sectors") or [])),
            segments=tuple(str(s) for s in (body.get("segments") or [])),
            threshold=((str(threshold[0]), str(threshold[1]), float(threshold[2]))
                       if isinstance(threshold, (list, tuple)) and len(threshold) == 3
                       else None),
            by_stage=bool(body.get("by_stage")),
            order_by=str(body.get("order_by") or ""),
            descending=bool(body.get("descending", True)),
            limit=int(body.get("limit") or 0),
            superlative=str(body.get("superlative") or ""),
            period=str(body.get("period") or ""),
            question=str(body.get("question") or ""),
        )

    def describe(self) -> str:
        """The request in a sentence, so the answer can restate what it read."""
        metrics = ", ".join(METRICS[m].label for m in self.metrics
                            if m in METRICS) or "the standard measures"
        where = ", ".join(self._conditions())
        by = ("across the whole portfolio" if self.dimension == NONE
              else f"by {DIMENSION_LABEL[self.dimension].lower()}")
        split = " split by Stage" if self.by_stage else ""
        return (f"{metrics} {by}{split}"
                + (f", for {where}" if where else "") + ".")

    def _conditions(self) -> list[str]:
        out: list[str] = []
        if self.stages:
            out.append("Stage " + " and ".join(str(s) for s in self.stages))
        if self.grades:
            out.append(_grade_phrase(self.grades))
        if self.sectors:
            out.append(" and ".join(self.sectors))
        if self.segments:
            out.append(" and ".join(self.segments))
        if self.threshold:
            key, direction, value = self.threshold
            label = METRICS[key].label if key in METRICS else key
            out.append(f"{label} {'above' if direction == '>' else 'below'} "
                       f"{value:g}{METRICS[key].unit if key in METRICS else ''}")
        return out


def _grade_phrase(grades: tuple[str, ...]) -> str:
    if len(grades) == 1:
        return grades[0]
    ordered = [g for g in rs.ALL_STATES if g in grades]
    if not ordered:
        return ", ".join(grades)
    contiguous = [rs.ORDINAL[g] for g in ordered]
    if contiguous == list(range(contiguous[0], contiguous[-1] + 1)):
        return f"{ordered[0]} to {ordered[-1]}"
    return ", ".join(ordered)


# --------------------------------------------------------------- reading


_STAGE = re.compile(r"\bstage\s*([123])\b", re.IGNORECASE)
_TOP = re.compile(r"\btop\s+(\d{1,4})\b", re.IGNORECASE)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|per\s*cent|percent)", re.IGNORECASE)

#: A grade, spelled the way people spell them. `\+` and `-` are part of the
#: token, and the pattern is anchored so "A" in "A borrower" is not a grade.
_GRADE = re.compile(
    r"(?<![A-Za-z0-9+-])(AAA|AA[+-]?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|CCC|CC|C|D)"
    r"(?![A-Za-z0-9+-])")

_METRIC_WORDS: tuple[tuple[re.Pattern[str], tuple[Metric, ...]], ...] = (
    (re.compile(r"\bttc\b|\bthrough[\s-]?the[\s-]?cycle\b", re.I), (TTC,)),
    (re.compile(r"\bpit\b|\bpoint[\s-]?in[\s-]?time\b", re.I), (PIT,)),
    (re.compile(r"\blifetime\b", re.I), (LIFETIME,)),
    (re.compile(r"\bapplicable\b|\bmeasurement pd\b", re.I), (APPLICABLE,)),
    (re.compile(r"\b12[\s-]?month\b|\btwelve[\s-]?month\b", re.I), (PIT,)),
    (re.compile(r"\blgd\b|\bloss given default\b", re.I), (LGD,)),
    (re.compile(r"\bccf\b|\bcredit conversion\b", re.I), (CCF,)),
    (re.compile(r"\bcollateral\b|\bsecurity coverage\b", re.I), (COLLATERAL,)),
    # "coverage" on its own is the provision rate. After "collateral" it is
    # the security ratio, which the line above has already read, so the word
    # is consumed there and must not produce a second column here.
    (re.compile(r"(?<!collateral )\bcoverage\b|\becl rate\b"
                r"|\bprovision rate\b", re.I), (COVERAGE,)),
    (re.compile(r"\becl\b|\bprovision\b|\bimpairment\b", re.I), (ECL,)),
    (re.compile(r"\bexposure\b|\bead\b|\bbalance\b", re.I), (EXPOSURE,)),
    (re.compile(r"\bdpd\b|\bdays past due\b|\bdelinquen\w*\b", re.I), (DPD,)),
    (re.compile(r"\bborrowers?\b|\bcounts?\b|\bnames\b|\bhow many\b", re.I), (COUNT,)),
    # Last, so a qualified PD above wins: "lifetime PD" is not all four.
    (re.compile(r"\bpds?\b|\bprobabilit(?:y|ies) of default\b", re.I), ALL_PDS),
)

_DIMENSION_WORDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bby sector\b|\bsector[\s-]?wise\b|\bper sector\b"
                r"|\bacross sectors\b|\bwhich sector\b", re.I), SECTOR),
    (re.compile(r"\bby segment\b|\bsegment[\s-]?wise\b|\bper segment\b"
                r"|\bwhich segment\b", re.I), SEGMENT),
    (re.compile(r"\bby (?:rating )?band\b|\bbroad (?:rating )?bands?\b"
                r"|\bband[\s-]?wise\b", re.I), BAND),
    (re.compile(r"\bby stage\b|\bstage[\s-]?wise\b|\bper stage\b"
                r"|\bstage 1 vs stage 2\b|\bacross stages\b", re.I), STAGE),
    (re.compile(r"\bsecured\b.*\bunsecured\b|\bunsecured\b.*\bsecured\b", re.I),
     SECURED),
    (re.compile(r"\bby (?:internal )?rating\b|\brating[\s-]?wise\b"
                r"|\bper rating\b|\bby grade\b|\bgrade[\s-]?wise\b"
                r"|\bacross ratings\b|\bfor each rating\b", re.I), RATING),
    (re.compile(r"\btop\s+\d+\b[\w\s-]{0,24}\bborrowers?\b"
                r"|\bwhich borrowers?\b|\blargest borrowers?\b"
                r"|\bbiggest names\b|\bname the borrowers?\b", re.I), BORROWER),
)

#: "getting rid of stages", "without splitting by Stage", "ignore stage".
_DROP_STAGE = re.compile(
    r"\bgetting rid of stages?\b|\bwithout (?:the )?stages?\b"
    r"|\bwithout splitting by stage\b|\bignor\w+ (?:the )?stages?\b"
    r"|\bremove (?:the )?stage(?: split)?\b|\bno stage split\b"
    r"|\bnot? split by stage\b|\bregardless of stage\b|\bacross all stages\b",
    re.IGNORECASE)
_ADD_STAGE = re.compile(
    r"\bsplit by stage\b|\bbreak (?:it )?down by stage\b|\bwithin each stage\b"
    r"|\band by stage\b|\bstage split\b", re.IGNORECASE)

_SUPERLATIVE = re.compile(
    r"\b(highest|largest|biggest|worst|most)\b|\b(lowest|smallest|best|least)\b",
    re.IGNORECASE)
_ABOVE = re.compile(
    r"\b(?:above|over|greater than|more than|exceed\w*|higher than|>)\b",
    re.IGNORECASE)
_BELOW = re.compile(
    r"\b(?:below|under|less than|lower than|beneath|<)\b", re.IGNORECASE)
_AND_WEAKER = re.compile(
    r"\b(?:and|or)\s+(?:weaker|worse|below|lower)\b|\bor\s+worse\b", re.IGNORECASE)
_AND_STRONGER = re.compile(
    r"\b(?:and|or)\s+(?:stronger|better|above|higher)\b", re.IGNORECASE)
_DISTRIBUTION = re.compile(
    r"\bdistribution\b|\bspread\b|\bpercentiles?\b|\bhistogram\b", re.IGNORECASE)

#: Phrases that mean "this is a question about the book", used to recognise a
#: quick analysis even when it names no dimension at all.
_ANALYTICAL = re.compile(
    r"\bshow\b|\bgive me\b|\blist\b|\bwhat is the\b|\bwhat are the\b"
    r"|\bhow many\b|\bhow much\b|\bbreak\s?down\b|\bbreak it down\b"
    r"|\btable of\b|\bdistribution\b|\bwhich \w+ has\b|\bcan you give\b"
    r"|\btell me the\b|\bwhat does the book\b"
    r"|\bborrowers?\s+(?:with|above|below|over|under)\b"
    r"|\bwhich borrowers?\b|\bcompare\b", re.IGNORECASE)


def _grades_in(said: str) -> tuple[str, ...]:
    """Every grade the sentence names, expanded for "and weaker" and bands."""
    found = [m.group(1).upper() for m in _GRADE.finditer(said)]
    # A bare band name means the whole band: "BBB borrowers" is three grades.
    grades: list[str] = []
    for token in found:
        if token in ("AA", "A", "BBB", "BB", "B") and not _looks_like_a_notch(
                said, token):
            grades.extend(dict(BROAD_BANDS)[token])
        elif token in rs.ORDINAL:
            grades.append(token)
    if not grades:
        return ()
    ordered = sorted(set(grades), key=lambda g: rs.ORDINAL[g])
    if _AND_WEAKER.search(said):
        weakest = rs.ORDINAL[ordered[0]]
        return tuple(g for g in rs.PERFORMING if rs.ORDINAL[g] >= weakest)
    if _AND_STRONGER.search(said):
        strongest = rs.ORDINAL[ordered[-1]]
        return tuple(g for g in rs.PERFORMING if rs.ORDINAL[g] <= strongest)
    return tuple(ordered)


def _looks_like_a_notch(said: str, token: str) -> bool:
    """Whether "BBB" in this sentence meant the grade rather than the band.

    "BBB+ and BBB-" names two grades and the bare "BBB" between them is a
    third; "BBB borrowers" means all three. The distinction is whether the
    sentence also names a modified grade in the same family.
    """
    return bool(re.search(rf"(?<![A-Za-z]){re.escape(token)}[+-]", said))


def _named(said: str, known: tuple[str, ...]) -> tuple[str, ...]:
    """The values of one categorical column the sentence names.

    Matched against what the book actually holds rather than against a list
    kept here, so a sector added to the universe is understood the day it
    appears and a sector that was renamed stops being silently unmatched.
    """
    found = []
    for value in known:
        text = str(value).strip()
        if not text:
            continue
        # Word-boundary on the whole phrase: "Mining" must not match
        # "Determining", and "Real Estate" is one name and not two.
        if re.search(rf"(?<![A-Za-z]){re.escape(text)}(?![A-Za-z])", said,
                     re.IGNORECASE):
            found.append(text)
    # The longest match wins where one name contains another.
    return tuple(v for v in found
                 if not any(v != o and v in o for o in found))


def _metrics_in(said: str) -> tuple[str, ...]:
    out: list[str] = []
    for pattern, metrics in _METRIC_WORDS:
        if pattern.search(said):
            for metric in metrics:
                if metric.key not in out:
                    out.append(metric.key)
            # A qualified PD stops the bare-PD fallback from adding all four,
            # and "collateral coverage" stops the coverage line from adding
            # the provision rate as well.
            if metrics in ((TTC,), (PIT,), (LIFETIME,), (APPLICABLE,)):
                said = re.sub(r"\bpds?\b", " ", said, flags=re.IGNORECASE)
            elif metrics == (COLLATERAL,):
                said = re.sub(r"\bcollateral\s+coverage\b", " ", said,
                              flags=re.IGNORECASE)
    return tuple(out)


def _threshold_in(said: str, metrics: tuple[str, ...]) -> tuple[str, str, float] | None:
    match = _PCT.search(said)
    if not match:
        return None
    direction = ">" if _ABOVE.search(said) else "<" if _BELOW.search(said) else ""
    if not direction:
        return None
    # The metric the threshold is about: the last one named before the number,
    # falling back to the first metric of the request.
    before = said[:match.start()]
    named = _metrics_in(before)
    # An unqualified "PD" resolves to all four, and a threshold has to pick
    # ONE. It picks the twelve-month PD, which is what a credit person means
    # by a bare "PD above 10%" — and the table says which it used rather than
    # leaving the reader to guess.
    family = tuple(m.key for m in ALL_PDS)
    if tuple(named[-len(family):]) == family:
        return (PIT.key, direction, float(match.group(1)))
    key = named[-1] if named else (metrics[0] if metrics else PIT.key)
    if key in {m.key for m in CONTEXT}:
        key = next((k for k in metrics if k not in {m.key for m in CONTEXT}),
                   PIT.key)
    return (key, direction, float(match.group(1)))


_VOCABULARY: dict[str, tuple[str, ...]] = {}


def vocabulary(source: Any = None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The sector and segment names the book actually holds.

    Read from the book rather than listed here, so a sector added to the
    universe is understood the day it appears and a renamed one stops being
    silently unmatched. Cached because it is asked once per message and does
    not change within a period; absent when no book is built, in which case a
    question naming a sector still reads — it simply does not narrow.
    """
    if not _VOCABULARY:
        try:
            work, _ = dm.book("")
            _VOCABULARY["sector"] = _values(work, "sector")
            _VOCABULARY["segment"] = _values(work, "segment")
        except Exception:  # pragma: no cover - no book here
            _VOCABULARY["sector"] = ()
            _VOCABULARY["segment"] = ()
    return _VOCABULARY.get("sector", ()), _VOCABULARY.get("segment", ())


def forget_vocabulary() -> None:
    """Drop the cached names, for a test that rebuilds the book underneath."""
    _VOCABULARY.clear()


def read(question: str, *, previous: Request | None = None,
         period: str = "", sectors: tuple[str, ...] | None = None,
         segments: tuple[str, ...] | None = None) -> Request | None:
    """The analysis a sentence asks for, or None when it asks for none.

    Returning None is a real answer: "increase BBB PD by 20%" is a scenario,
    not a breakdown, and reading it as one would answer a question nobody
    asked while the shock they wanted went unconfigured.
    """
    said = str(question or "").strip()
    if not said:
        return None

    # "Show rating-wise PDs without splitting by Stage" names the dimension
    # once (rating) and the SPLIT twice. Reading the dimension out of the
    # sentence with the split phrases still in it made every such question a
    # Stage table, which is the opposite of what was asked — so the split is
    # taken out first and read separately.
    stripped = _ADD_STAGE.sub(" ", _DROP_STAGE.sub(" ", said))
    dimension = ""
    for pattern, name in _DIMENSION_WORDS:
        if pattern.search(stripped):
            dimension = name
            break
    metrics = _metrics_in(said)
    grades = _grades_in(said)
    stages = tuple(sorted({int(m.group(1)) for m in _STAGE.finditer(said)}))
    if sectors is None or segments is None:
        known_sectors, known_segments = vocabulary()
        sectors = known_sectors if sectors is None else sectors
        segments = known_segments if segments is None else segments
    named_sectors = _named(said, sectors)
    named_segments = _named(said, segments)
    top = _TOP.search(said)
    superlative = ""
    if (found := _SUPERLATIVE.search(said)):
        superlative = "highest" if found.group(1) else "lowest"

    # Is this an analysis at all? It is when it names a dimension, or when it
    # names a metric in a sentence that is phrased as a question about the
    # book. A follow-up is always one, because the previous turn established it.
    analytical = bool(dimension) or bool(
        metrics and (_ANALYTICAL.search(said) or _DISTRIBUTION.search(said)))
    if not analytical and previous is None:
        return None

    base = previous or Request(dimension=RATING, metrics=(), period=period)
    if previous is not None and not analytical and not (
            grades or stages or metrics or top or superlative
            or named_sectors or named_segments
            or _DROP_STAGE.search(said) or _ADD_STAGE.search(said)):
        return None

    by_stage = base.by_stage
    if _DROP_STAGE.search(said):
        by_stage = False
    elif _ADD_STAGE.search(said):
        by_stage = True

    # A follow-up ADDS a metric rather than replacing the table. "Show exposure
    # too" means the previous columns plus one, and reading it as a replacement
    # would throw away the table the reader is looking at.
    adding = bool(previous) and bool(
        re.search(r"\b(?:too|as well|also|add|alongside|and)\b", said, re.I))
    if metrics and adding:
        merged = list(base.metrics)
        for key in metrics:
            if key not in merged:
                merged.append(key)
        metrics = tuple(merged)
    elif not metrics:
        metrics = base.metrics

    request = replace(
        base,
        dimension=dimension or (base.dimension if previous else _default_dimension(said)),
        metrics=metrics,
        grades=grades or (base.grades if previous else ()),
        stages=stages or (base.stages if previous else ()),
        sectors=named_sectors or (base.sectors if previous else ()),
        segments=named_segments or (base.segments if previous else ()),
        by_stage=by_stage,
        limit=int(top.group(1)) if top else (base.limit if previous else 0),
        superlative=superlative,
        period=period or base.period,
        question=said,
    )
    request = replace(request,
                      threshold=_threshold_in(said, request.metrics)
                      or (base.threshold if previous and not analytical else None))

    # A superlative wants the table ordered by what it asked about.
    if request.superlative and request.metrics:
        request = replace(request, order_by=_ranked_by(request.metrics),
                          descending=request.superlative == "highest")
    if request.dimension == BORROWER and not request.limit:
        request = replace(request, limit=20)
    if request.dimension == BORROWER and not request.order_by:
        request = replace(request, order_by=(request.metrics[0]
                                             if request.metrics else ECL.key),
                          descending=True)
    return replace(request, metrics=_settle(request.metrics))


def _ranked_by(metrics: tuple[str, ...]) -> str:
    """Which measure a "which has the highest" question is really about.

    Never the TTC PD when something else is available. TTC is a property of
    the GRADE, so ranking sectors by it inside a single rating band ranks them
    by their mix within that band rather than by their risk — "Real Estate has
    the highest TTC PD in BB" is a statement about how many BB- names it holds,
    which is not what the question meant.
    """
    for preferred in (APPLICABLE.key, PIT.key, LIFETIME.key):
        if preferred in metrics:
            return preferred
    context = {m.key for m in CONTEXT}
    for key in metrics:
        if key not in context and key != TTC.key:
            return key
    return metrics[0]


def _default_dimension(said: str) -> str:
    """What to cut by when the question named nothing to cut by.

    A distribution question — "what is the spread of CCF?" — is about the
    portfolio, and answering it nineteen times by rating buries the answer.
    Everything else defaults to the rating, which is the dimension a credit
    officer reaches for first.
    """
    return NONE if _DISTRIBUTION.search(said) else RATING


def _settle(metrics: tuple[str, ...]) -> tuple[str, ...]:
    """The columns a table actually shows: context first, then what was asked.

    A rate with no population behind it is unreadable, so the borrower count
    and the exposure are always present whatever the question named. That is
    why "asked for nothing" is decided from what the READER named and not from
    the length of this list: "show Stage 1 vs Stage 2 exposure" names exposure,
    which is already a context column, and treating it as naming nothing added
    four PD columns to a question about exposure.
    """
    out = [m.key for m in CONTEXT]
    for key in metrics:
        if key in METRICS and key not in out:
            out.append(key)
    if not [k for k in metrics if k in METRICS]:
        out.extend(m.key for m in ALL_PDS)
    return tuple(out)


# ------------------------------------------------------------- computing


def _values(work: pd.DataFrame, column: str) -> tuple[str, ...]:
    """The distinct values one categorical column holds, longest name first."""
    if column not in work.columns:
        return ()
    found = {str(v).strip() for v in work[column].dropna().unique()}
    return tuple(sorted((v for v in found if v), key=len, reverse=True))


def _prepare(period: str, source: Any = None) -> tuple[pd.DataFrame, str]:
    frame, settled = dm.book(period, source=source)
    work = pf._enrich(frame, settled, source)
    work["_applicable"] = pf.stage_appropriate_pd(work)
    if "ttc_pd_pct" not in work.columns:
        work["ttc_pd_pct"] = rs.ttc_pd(
            work.get("internal_rating", pd.Series([""] * len(work))).astype(str))
    if "collateral_coverage_pct" not in work.columns:
        collateral = pd.to_numeric(work.get("collateral_value"), errors="coerce") \
            if "collateral_value" in work.columns else pd.Series(np.nan, index=work.index)
        ead = pf._num(work, "ead").replace(0, np.nan)
        work["collateral_coverage_pct"] = (collateral / ead * 100.0).clip(upper=1000.0)
    return work, settled


def _narrow(work: pd.DataFrame, request: Request) -> tuple[pd.DataFrame, list[str]]:
    """The population the question asked about, and what narrowing cost."""
    notes: list[str] = []
    part = work
    if request.stages:
        part = part[pf._num(part, "stage").astype(int).isin(request.stages)]
    if request.grades:
        said = part.get("internal_rating", pd.Series([""] * len(part))) \
            .astype(str).str.strip().str.upper()
        part = part[said.isin(request.grades)]
    if request.sectors:
        wanted = {s.casefold() for s in request.sectors}
        part = part[part.get("sector", pd.Series([""] * len(part)))
                    .astype(str).str.casefold().isin(wanted)]
    if request.segments:
        wanted = {s.casefold() for s in request.segments}
        part = part[part.get("segment", pd.Series([""] * len(part)))
                    .astype(str).str.casefold().isin(wanted)]
    if request.threshold:
        key, direction, value = request.threshold
        if key == PIT.key and re.search(
                r"\bpds?\b", request.question or "", re.IGNORECASE) and not \
                re.search(r"\b(?:lifetime|ttc|applicable|through)\b",
                          request.question or "", re.IGNORECASE):
            notes.append(
                "'PD' was read as the twelve-month point-in-time PD. Say "
                "'lifetime PD' or 'applicable PD' for a different basis.")
        metric = METRICS.get(key)
        if metric and metric.column and metric.column in part.columns:
            values = pd.to_numeric(part[metric.column], errors="coerce")
            part = part[values > value] if direction == ">" else part[values < value]
        else:
            notes.append(
                f"'{key}' is not a measure this book carries, so the "
                "threshold was not applied and the table is unfiltered.")
    if part.empty and not work.empty:
        notes.append("No borrower in the book matches that. The table below is "
                     "empty rather than approximated.")
    return part, notes


def _keys(work: pd.DataFrame, dimension: str) -> tuple[pd.Series, list[str]]:
    """The grouping key per row, and the order its values are shown in.

    The order is the GOVERNED one for a rating or a Stage — never alphabetical,
    which would put AA- before AA+ and CCC before CC. For a sector or a segment
    there is no governed order, so it is by exposure, largest first, which is
    the order a credit officer reads a concentration table in.
    """
    if dimension == RATING:
        key = work.get("internal_rating", pd.Series([""] * len(work))) \
            .astype(str).str.strip().str.upper()
        return key, [g for g in rs.ALL_STATES]
    if dimension == BAND:
        grade = work.get("internal_rating", pd.Series([""] * len(work))) \
            .astype(str).str.strip().str.upper()
        lookup = {g: name for name, grades in BROAD_BANDS for g in grades}
        return grade.map(lookup).fillna(""), [name for name, _ in BROAD_BANDS]
    if dimension == STAGE:
        key = pf._num(work, "stage").astype(int).map(lambda s: f"Stage {s}")
        return key, [f"Stage {s}" for s in pf.STAGES]
    if dimension == SECURED:
        coverage = pd.to_numeric(work.get("collateral_coverage_pct"),
                                 errors="coerce").fillna(0.0)
        key = pd.Series(np.where(coverage > 0, "Secured", "Unsecured"),
                        index=work.index)
        return key, ["Secured", "Unsecured"]
    if dimension in (SECTOR, SEGMENT):
        key = work.get(dimension, pd.Series([""] * len(work))).astype(str)
        order = (work.assign(_k=key).groupby("_k")["ead"].sum()
                 .sort_values(ascending=False).index.tolist()
                 if "ead" in work.columns and len(work) else
                 sorted(set(key)))
        return key, [str(v) for v in order]
    if dimension == NONE:
        return pd.Series(["Portfolio"] * len(work), index=work.index), ["Portfolio"]
    raise AnalysisError(
        f"'{dimension}' is not a dimension this book can be cut by. The "
        f"choices are: {', '.join(DIMENSION_LABEL[d] for d in DIMENSIONS)}.")


def _cell(metric: Metric, part: pd.DataFrame, whole: pd.DataFrame) -> dict[str, Any]:
    """One measure over one group, aggregated the way its kind requires."""
    ead = pf._num(part, "ead")
    if metric.kind == "count":
        return {"value": int(len(part)),
                "share_pct": pf._share(len(part), len(whole))}
    if metric.kind == "total":
        total = float(pf._num(part, metric.column).sum())
        return {"value": total,
                "share_pct": pf._share(total, float(pf._num(whole, metric.column).sum()))}
    if metric.kind == "ratio":
        top = float(pf._num(part, metric.column).sum())
        bottom = float(pf._num(part, metric.over).sum())
        return {"value": round(pf._share(top, bottom), 4)}
    values = pd.to_numeric(part.get(metric.column), errors="coerce") \
        if metric.column in part.columns else pd.Series(dtype=float)
    clean = values.dropna()
    if clean.empty:
        return {"value": None, "weighted": None, "note": "not carried on this book"}
    return {"value": round(float(clean.mean()), 4),
            "weighted": round(pf._weighted(values.fillna(0.0), ead), 4)}


def _line(label: str, part: pd.DataFrame, whole: pd.DataFrame,
          metrics: tuple[str, ...]) -> dict[str, Any]:
    return {"label": label,
            "cells": {key: _cell(METRICS[key], part, whole) for key in metrics}}


def run(request: Request, *, source: Any = None) -> dict[str, Any]:
    """The table the question asked for, computed from the reported book."""
    work, settled = _prepare(request.period, source)
    part, notes = _narrow(work, request)

    if request.dimension == BORROWER:
        return _borrower_table(request, part, work, settled, notes)

    key, order = _keys(part if len(part) else work, request.dimension)
    part = part.assign(_key=key.reindex(part.index))
    present = [v for v in order if v in set(part["_key"])]
    # A rating or a Stage shows every value even when the book holds none of
    # it: a table that silently omits AAA reads as though the scale stops.
    labels = order if request.dimension in (RATING, BAND, STAGE, SECURED) \
        else present

    rows: list[dict[str, Any]] = []
    for label in labels:
        here = part[part["_key"] == label]
        line = _line(label, here, part, request.metrics)
        if request.dimension == RATING:
            line["ordinal"] = rs.ORDINAL.get(label)
            line["performing"] = label != rs.DEFAULT_GRADE
        if request.by_stage:
            line["by_stage"] = [
                _line(f"Stage {stage}",
                      here[pf._num(here, "stage").astype(int) == stage],
                      part, request.metrics)
                for stage in pf.STAGES]
        rows.append(line)

    if request.order_by and request.order_by in request.metrics:
        rows.sort(key=lambda r: _sortable(r["cells"][request.order_by]),
                  reverse=request.descending)
    if request.limit:
        rows = rows[:request.limit]

    total = _line("Total", part, part, request.metrics)
    body: dict[str, Any] = {
        "kind": "breakdown",
        "version": ANALYSIS_VERSION,
        "period": settled,
        "currency": dm.CURRENCY,
        "grain": dm.GRAIN,
        "dimension": request.dimension,
        "dimension_label": DIMENSION_LABEL[request.dimension],
        "columns": [{"key": k, "label": METRICS[k].label,
                     "unit": METRICS[k].unit, "kind": METRICS[k].kind}
                    for k in request.metrics],
        "rows": rows,
        "total": total,
        "by_stage": request.by_stage,
        "borrowers": int(len(part)),
        "population": request.describe(),
        "request": request.to_dict(),
        "notes": notes + list(request.notes),
        "measurement": (
            "Applicable PD is the twelve-month PD in Stage 1, the lifetime PD "
            "in Stage 2 and 100% in Stage 3 — the default has already "
            "happened. Every rate is reported as a plain mean and as an "
            "exposure-weighted mean; coverage is summed over summed."),
    }
    if request.superlative and rows:
        body["answer"] = _superlative_answer(request, rows)
    if _DISTRIBUTION.search(request.question or ""):
        body["distribution"] = {
            key: pf.distribution(pd.to_numeric(part.get(METRICS[key].column),
                                               errors="coerce"),
                                 pf._num(part, "ead"))
            for key in request.metrics
            if METRICS[key].kind == "rate" and METRICS[key].column in part.columns}
    return body


def _sortable(cell: dict[str, Any]) -> float:
    """The number a row is ranked on.

    A rate is ranked on its EXPOSURE-WEIGHTED value where it has one, because
    the question "which sector carries the most risk" is about the book's
    money and not about its average borrower.
    """
    value = cell.get("weighted")
    if not isinstance(value, (int, float)):
        value = cell.get("value")
    return float(value) if isinstance(value, (int, float)) else float("-inf")


def _superlative_answer(request: Request, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The one row a "which has the highest" question actually wanted."""
    key = request.order_by or request.metrics[0]
    metric = METRICS[key]
    winner = rows[0]
    cell = winner["cells"][key]
    shown = cell.get("weighted") if cell.get("weighted") is not None else cell.get("value")
    basis = (" on an exposure-weighted basis"
             if cell.get("weighted") is not None else "")
    return {
        "label": winner["label"],
        "metric": key,
        "metric_label": metric.label,
        "value": shown,
        "unit": metric.unit,
        "basis": "exposure-weighted" if basis else "total",
        "sentence": (
            f"{winner['label']} has the {request.superlative} "
            f"{metric.label} at {_pretty(shown, metric.unit)}{basis}"
            + (f", over {winner['cells'][COUNT.key]['value']} borrowers"
               if COUNT.key in winner["cells"] else "") + "."),
    }


def _pretty(value: Any, unit: str) -> str:
    if value is None:
        return "not available"
    if unit == "%":
        return f"{float(value):.2f}%"
    if unit == dm.CURRENCY:
        return f"{dm.CURRENCY} {float(value):,.0f}"
    return f"{float(value):,.2f}"


def _borrower_table(request: Request, part: pd.DataFrame, whole: pd.DataFrame,
                    settled: str, notes: list[str]) -> dict[str, Any]:
    """A named list rather than a grouped table: "top 20 borrowers by ECL"."""
    key = request.order_by if request.order_by in METRICS else ECL.key
    metric = METRICS[key]
    column = metric.column or "final_ecl"
    values = pd.to_numeric(part.get(column), errors="coerce").fillna(0.0) \
        if column in part.columns else pd.Series(0.0, index=part.index)
    ordered = part.assign(_sort=values).sort_values(
        "_sort", ascending=not request.descending).head(request.limit or 20)
    rows = [{
        "borrower_id": str(row.get("borrower_id", "")),
        "name": str(row.get("display_name") or row.get("legal_name") or ""),
        "sector": str(row.get("sector", "")),
        "segment": str(row.get("segment", "")),
        "rating": str(row.get("internal_rating", "")),
        "rating_ordinal": int(row.get("internal_rating_ordinal")
                              or rs.ORDINAL.get(str(row.get("internal_rating", "")), 0)),
        "stage": int(pd.to_numeric(row.get("stage"), errors="coerce") or 0),
        "exposure": float(pd.to_numeric(row.get("ead"), errors="coerce") or 0.0),
        "ecl": float(pd.to_numeric(row.get("final_ecl"), errors="coerce") or 0.0),
        "applicable_pd": float(pd.to_numeric(row.get("_applicable"),
                                             errors="coerce") or 0.0),
        "lgd": float(pd.to_numeric(row.get("lgd"), errors="coerce") or 0.0),
        "value": float(row.get("_sort") or 0.0),
    } for _, row in ordered.iterrows()]
    shown = float(sum(r["value"] for r in rows))
    everything = float(values.sum())
    return {
        "kind": "borrowers",
        "version": ANALYSIS_VERSION,
        "period": settled,
        "currency": dm.CURRENCY,
        "grain": dm.GRAIN,
        "ordered_by": {"key": key, "label": metric.label, "unit": metric.unit,
                       "descending": request.descending},
        "rows": rows,
        "shown": len(rows),
        "borrowers": int(len(part)),
        "concentration_pct": round(pf._share(shown, everything), 4),
        "population": request.describe(),
        "request": request.to_dict(),
        "notes": notes + list(request.notes),
    }


# --------------------------------------------- what shock would be sensible

#: What a person means by each measure when they ask how far to move it, and
#: which column of the book carries the history of that movement.
SHOCKABLE: dict[str, tuple[str, str, str, bool]] = {
    # key: (column, label, unit, read as a relative % move)
    "pd": ("pd_12m", "twelve-month PD", "%", True),
    "lifetime_pd": ("pd_lifetime", "lifetime PD", "%", True),
    "lgd": ("lgd", "loss given default", "pp", False),
    "ead": ("ead", "exposure at default", "%", True),
    "ccf": ("credit_conversion_factor", "credit conversion factor", "pp", False),
    "collateral": ("collateral_market_value", "collateral value", "%", True),
}

_SUGGEST = re.compile(
    r"\bwhat would be (?:a |an )?(?:sensible|reasonable|appropriate|plausible)\b"
    r"|\bhow (?:big|much|far)\b.*\b(?:shock|stress|move|shift)\b"
    r"|\bsuggest\b.*\b(?:shock|stress|magnitude|scenario)\b"
    r"|\bwhat (?:shock|magnitude|size)\b"
    r"|\bsensible (?:pd |lgd |ead )?shock\b"
    r"|\bhow much should i (?:shock|stress|move)\b", re.IGNORECASE)

#: The percentiles a suggestion is drawn at, and what each one is.
LADDER: tuple[tuple[float, str, str], ...] = (
    (0.50, "Typical quarter", "the median quarter-on-quarter move"),
    (0.75, "Mild stress", "worse than three quarters of observed moves"),
    (0.90, "Moderate stress", "worse than nine in ten observed moves"),
    (0.95, "Severe", "in the worst one in twenty quarters observed"),
    (0.99, "Extreme", "at the edge of what this book has ever done"),
)


def wants_a_suggestion(question: str) -> bool:
    """Whether the reader is asking how far to move something, not what it is."""
    return bool(_SUGGEST.search(str(question or "")))


def suggest(question: str, *, previous: Request | None = None,
            period: str = "", source: Any = None) -> dict[str, Any]:
    """Evidence-based magnitudes for a shock the reader is still deciding on.

    "I want to stress BBB borrowers but what would be a sensible PD shock?" is
    not a scenario and not a breakdown. It is the question in between, and it
    is the one the product is worst at if it answers with a blank magnitude
    prompt: the reader is asking precisely because they do not know, and
    "tell me the size" hands the question back.

    So the answer is the book's own history. Where does this population's PD
    sit today, how far has it moved quarter on quarter and year on year, and
    what magnitude would put a scenario at the median, at the three-quarter
    mark, or in the worst one quarter in twenty. Those are the numbers a credit
    committee argues over, and every one of them is measured rather than
    chosen.
    """
    from backend.whatif import plausibility as pl

    said = str(question or "")
    measure = next((k for k in ("lifetime_pd", "collateral", "lgd", "ccf", "ead")
                    if re.search(rf"\b{k.replace('_', '[ _]?')}\b", said, re.I)),
                   "pd")
    column, label, unit, relative = SHOCKABLE[measure]

    work, settled = _prepare(period, source)
    known_sectors, known_segments = vocabulary(source)
    # "I want to stress BBB borrowers but what would be a sensible PD shock?"
    # is not phrased as a breakdown, so `read` may decline it entirely. The
    # POPULATION in it is still real, and answering over the whole book when
    # the reader named BBB would give them the wrong magnitudes — so the
    # narrowing is taken from the sentence directly rather than from whether
    # it parsed as a table.
    request = read(said, previous=previous, period=period,
                   sectors=known_sectors, segments=known_segments) or (
        previous or Request(period=period))
    request = replace(
        request,
        period=period or request.period,
        grades=_grades_in(said) or request.grades,
        stages=tuple(sorted({int(m.group(1)) for m in _STAGE.finditer(said)}))
        or request.stages,
        sectors=_named(said, known_sectors) or request.sectors,
        segments=_named(said, known_segments) or request.segments)
    part, notes = _narrow(work, request)

    panel = pl._panel(pl._COLUMNS, source)
    if not panel.empty and request.grades:
        panel = panel[panel["internal_rating"].astype(str).str.upper()
                      .isin(request.grades)]
    if not panel.empty and request.sectors:
        wanted = {s.casefold() for s in request.sectors}
        panel = panel[panel["sector"].astype(str).str.casefold().isin(wanted)]
    if not panel.empty and request.stages:
        panel = panel[pd.to_numeric(panel["stage"], errors="coerce")
                      .isin(request.stages)]

    field = "_relative_pct" if relative else "_absolute"
    ladder: list[dict[str, Any]] = []
    history: dict[str, Any] = {}
    if not panel.empty and column in panel.columns:
        qoq = pl._movements(panel, column, lag=1)
        yoy = pl._movements(panel, column, lag=4)
        moves = pd.to_numeric(qoq.get(field), errors="coerce").dropna() \
            if not qoq.empty else pd.Series(dtype=float)
        annual = pd.to_numeric(yoy.get(field), errors="coerce").dropna() \
            if not yoy.empty else pd.Series(dtype=float)
        history = {
            "observations": int(len(moves)),
            "quarters": len(pl._ordered(list(panel["period"].unique()))),
            "quarter_on_quarter": {
                f"p{int(q * 100)}": round(float(moves.quantile(q)), 4)
                for q, _, _ in LADDER} if len(moves) else {},
            "year_on_year": {
                f"p{int(q * 100)}": round(float(annual.quantile(q)), 4)
                for q, _, _ in LADDER} if len(annual) else {},
        }
        for quantile, name, because in LADDER:
            if not len(moves):
                break
            magnitude = float(moves.quantile(quantile))
            if magnitude <= 0:
                continue
            ladder.append({
                "severity": name,
                "magnitude": round(magnitude, 2),
                "unit": "%" if relative else unit,
                "basis": "relative" if relative else "absolute",
                "because": (f"{because} in {label} over the "
                            f"{history['quarters']} quarters this book "
                            "publishes"),
                "instruction": _instruction(measure, magnitude, relative,
                                            request),
            })

    metric_key = {"pd": PIT.key, "lifetime_pd": LIFETIME.key, "lgd": LGD.key,
                  "ead": EXPOSURE.key, "ccf": CCF.key,
                  "collateral": COLLATERAL.key}[measure]
    current = _cell(METRICS[metric_key], part, work) if metric_key in METRICS else {}

    return {
        "kind": "suggestion",
        "version": ANALYSIS_VERSION,
        "period": settled,
        "currency": dm.CURRENCY,
        "measure": measure,
        "measure_label": label,
        "population": (", ".join(request._conditions())
                       or "the whole Corporate IFRS 9 book"),
        "borrowers": int(len(part)),
        "exposure": float(pf._num(part, "ead").sum()),
        "current": current,
        "history": history,
        "options": ladder,
        "request": request.to_dict(),
        "notes": notes,
        "question": ("Would you like to use one of these, or define another "
                     "shock?"),
        "measured_not_chosen": (
            "Every magnitude above is a percentile of what this book has "
            "actually done, not a round number picked to look severe. Nothing "
            "has been applied to the scenario."),
    }


def _instruction(measure: str, magnitude: float, relative: bool,
                 request: Request) -> str:
    """The sentence that would configure this shock, ready to be sent back."""
    where = []
    if request.stages:
        where.append("Stage " + " and ".join(str(s) for s in request.stages))
    if request.grades:
        where.append(_grade_phrase(request.grades))
    if request.sectors:
        where.append(" and ".join(request.sectors))
    population = (" for " + ", ".join(where)) if where else ""
    verb = {"pd": "Increase PD", "lifetime_pd": "Increase lifetime PD",
            "lgd": "Increase LGD", "ead": "Increase EAD",
            "ccf": "Increase CCF", "collateral": "Reduce collateral"}[measure]
    size = (f"by {magnitude:.0f}%" if relative
            else f"by {magnitude:.1f} percentage points")
    return f"{verb}{population} {size}"


__all__ = [
    "ALL_PDS", "ANALYSIS_VERSION", "BAND", "BORROWER", "BROAD_BANDS",
    "CONTEXT", "DIMENSIONS", "DIMENSION_LABEL", "METRICS", "NONE", "RATING",
    "LADDER", "SECTOR", "SECURED", "SEGMENT", "SHOCKABLE", "STAGE",
    "AnalysisError", "Metric", "Request", "forget_vocabulary", "read",
    "run", "suggest", "vocabulary", "wants_a_suggestion",
]

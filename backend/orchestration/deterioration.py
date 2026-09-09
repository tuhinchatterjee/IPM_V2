"""The Sector / Segment Deterioration Investigation Blueprint.

"Shipping has deteriorated. Show me everything." is one question and about ten
analyses, and until this module existed the product answered it with whichever
one it happened to read first.

What a complete deterioration review is
---------------------------------------
A credit officer looking at a segment that has gone wrong asks the same set of
questions every time, in the same order, and each one is a different measure
over the same population and the same two dates:

    how much is there            exposure at default
    how likely is default now    12-month point-in-time PD
    over the life                lifetime point-in-time PD
    against the cycle            PD at origination, the through-the-cycle anchor
    how much is lost             loss given default
    what it provisions to        expected credit loss, and its coverage
    where the book has moved     IFRS 9 stage, by BALANCE and by ACCOUNT COUNT
    how far the grades slipped   notches since origination
    who did it                   the borrowers behind the movement

Balance and account count are two analyses rather than one because they answer
different questions and routinely disagree: a stage-2 balance that rose 30%
while the stage-2 account count rose 3% is a handful of large names, and a
review that showed only the first would have sent an officer looking for a
trend that is really three borrowers.

One dataset, on purpose
-----------------------
Every measure above is read from `ifrs9_staging`, which carries sector, segment,
exposure, all three PDs, LGD, ECL, stage, prior stage and notches since
origination at one row per facility per period. Nothing here joins anything: a
join costs a relationship path, a grain contract and a reconciliation, and buys
nothing when the fields are already in one table.

`corporate_ifrs9` is the obligor-grain IFRS 9 record and carries no sector or
segment column, so a SECTOR review built on it would need precisely the join
this blueprint is meant to avoid. Where a listed measure is genuinely absent —
an agency rating grade, for instance, which lives in `corporate_ratings` — the
blueprint says so in `unavailable` rather than joining for it or quietly
dropping it.

Windows
-------
`QOQ`, `YOY` and an explicit A-versus-B are all supported, resolved against the
periods the dataset actually publishes. `MOM` is accepted and refused with a
reason: this book is quarterly, and a month-over-month movement over quarterly
data is a number with no meaning behind it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

BLUEPRINT_VERSION = "1.0.0"

#: The one dataset this blueprint reads. See the module docstring for why it is
#: one and why it is this one.
DATASET = "ifrs9_staging"

#: The dimensions a segment can be named on.
DIMENSIONS: tuple[str, ...] = ("sector", "segment")

# ------------------------------------------------------------------- windows

MOM = "MOM"
QOQ = "QOQ"
YOY = "YOY"
EXPLICIT = "EXPLICIT"

#: How many published periods back each window steps. Quarterly data, so a
#: year is four of them.
_STEPS: dict[str, int] = {QOQ: 1, YOY: 4}

_WINDOW_WORDS: tuple[tuple[str, str], ...] = (
    (r"month[- ]on[- ]month|month[- ]over[- ]month|\bmom\b|since last month",
     MOM),
    (r"year[- ]on[- ]year|year[- ]over[- ]year|\byoy\b|over the (?:latest |past )?year"
     r"|since last year|compared with last year", YOY),
    (r"quarter[- ]on[- ]quarter|quarter[- ]over[- ]quarter|\bqoq\b"
     r"|since last quarter|from the previous quarter|versus the previous quarter",
     QOQ),
)


def read_window(text: str) -> str:
    """Which comparison a sentence asked for. QoQ when it did not say.

    QoQ rather than YoY as the default because this book publishes quarterly:
    the most recent movement anybody can see is one quarter, and defaulting to
    a year would answer a question about "the latest deterioration" with three
    quarters of history folded into it.
    """
    lowered = " ".join((text or "").lower().split())
    for pattern, window in _WINDOW_WORDS:
        if re.search(pattern, lowered):
            return window
    return QOQ


# -------------------------------------------------------------------- lenses


@dataclass(frozen=True)
class Lens:
    """One measure the blueprint reads, and what a rise in it means."""

    key: str
    label: str
    field: str
    #: sum | weighted_mean | mean. A PD is not additive and an exposure is not
    #: an average; getting this wrong is the difference between a portfolio
    #: figure and a type error with a unit printed after it.
    aggregation: str
    unit: str
    higher_is_worse: bool
    because: str
    #: The field to weight by, for a `weighted_mean`. Exposure, always: an
    #: unweighted average PD lets a 50,000 riyal facility move the portfolio
    #: number as far as a 500 million riyal one.
    weight: str = "ead"

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "field": self.field,
                "aggregation": self.aggregation, "unit": self.unit,
                "higher_is_worse": self.higher_is_worse,
                "because": self.because,
                "weight": self.weight if self.aggregation == "weighted_mean"
                else ""}


#: The measures, in the order an officer asks for them. Order is part of the
#: blueprint: how much is there comes before how bad it is, and who did it
#: comes last because it only means something once the size is known.
LENSES: tuple[Lens, ...] = (
    Lens("exposure", "Exposure at default", "ead", "sum", "SAR mn", True,
         "How much of the book is in this segment at all. Every other measure "
         "below is read against this one."),
    Lens("pd_12m", "12-month point-in-time PD", "pd_12m_pct",
         "weighted_mean", "%", True,
         "The forward default rate the book is currently carrying, weighted "
         "by exposure so large facilities count for what they are."),
    Lens("pd_lifetime", "Lifetime point-in-time PD", "pd_lifetime_pct",
         "weighted_mean", "%", True,
         "What stage 2 provisions against. A 12-month PD that held while the "
         "lifetime PD moved is a term-structure change, not a level change."),
    Lens("pd_ttc", "PD at origination", "pd_at_origination_pct",
         "weighted_mean", "%", True,
         "The through-the-cycle anchor the current PD is measured against. "
         "It moves only as the book turns over, so a move here is a change in "
         "what was written, not in how it is performing."),
    Lens("lgd", "Loss given default", "lgd_pct", "weighted_mean", "%", True,
         "The loss rate applied to the exposure. A collateral or recovery "
         "change shows here and nowhere else."),
    Lens("ecl", "Expected credit loss", "total_ecl", "sum", "SAR mn", True,
         "What the segment provisions to, which is the consequence of every "
         "measure above it."),
    Lens("coverage", "ECL coverage", "ecl_coverage_pct", "weighted_mean", "%",
         True,
         "Provision as a share of exposure. Separates a book that provisioned "
         "more because it grew from one that provisioned more because it "
         "worsened."),
)

#: Measures a complete deterioration review would want and this dataset does
#: not carry. Named rather than omitted: a review that silently drops the
#: rating migration reads as one that found nothing there.
UNAVAILABLE: tuple[tuple[str, str], ...] = (
    ("Agency and internal rating migration",
     "Rating grades are published in `corporate_ratings`, at borrower grain "
     "and without a sector column. The grade-slippage question is answered "
     "here from notches since origination, which this dataset does carry; the "
     "full from-grade/to-grade matrix needs that other dataset and is not "
     "joined in silently."),
)


# ------------------------------------------------------------------- results


@dataclass
class Movement:
    """One lens, measured at two dates."""

    lens: Lens
    opening: float = 0.0
    closing: float = 0.0
    #: Facilities behind each figure, so a movement in a measure can be told
    #: apart from a movement in the population under it.
    opening_rows: int = 0
    closing_rows: int = 0

    @property
    def change(self) -> float:
        return round(self.closing - self.opening, 6)

    @property
    def change_pct(self) -> float | None:
        if not self.opening:
            return None
        return round((self.closing - self.opening) / abs(self.opening) * 100, 4)

    @property
    def deteriorated(self) -> bool:
        return (self.change > 0) if self.lens.higher_is_worse \
            else (self.change < 0)

    def to_dict(self) -> dict[str, Any]:
        return {**self.lens.to_dict(),
                "opening": round(self.opening, 6),
                "closing": round(self.closing, 6),
                "change": self.change, "change_pct": self.change_pct,
                "opening_rows": self.opening_rows,
                "closing_rows": self.closing_rows,
                "deteriorated": self.deteriorated}


@dataclass
class Review:
    """A complete segment deterioration review."""

    subject: str = ""
    dimension: str = "sector"
    window: str = QOQ
    opening: str = ""
    closing: str = ""
    movements: list[Movement] = field(default_factory=list)
    #: Exposure by IFRS 9 stage at both dates.
    stage_balance: list[dict[str, Any]] = field(default_factory=list)
    #: Facility COUNT by IFRS 9 stage at both dates. A separate analysis
    #: because it routinely disagrees with the balance and the disagreement is
    #: the finding.
    stage_count: list[dict[str, Any]] = field(default_factory=list)
    #: Notches since origination, banded. The grade-slippage question this
    #: dataset can answer without a join.
    notches: list[dict[str, Any]] = field(default_factory=list)
    #: The borrowers behind the ECL movement, largest contribution first.
    contributors: list[dict[str, Any]] = field(default_factory=list)
    unavailable: list[dict[str, str]] = field(default_factory=list)
    refusal: str = ""
    version: str = BLUEPRINT_VERSION

    @property
    def ok(self) -> bool:
        return not self.refusal and bool(self.movements)

    @property
    def analysis_count(self) -> int:
        """How many governed analyses this review is. Not a constant."""
        parts = [bool(self.movements) and len(self.movements),
                 bool(self.stage_balance), bool(self.stage_count),
                 bool(self.notches), bool(self.contributors)]
        return sum(int(p) for p in parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "subject": self.subject,
            "dimension": self.dimension, "window": self.window,
            "opening": self.opening, "closing": self.closing,
            "dataset": DATASET,
            "movements": [m.to_dict() for m in self.movements],
            "stage_balance": list(self.stage_balance),
            "stage_count": list(self.stage_count),
            "notches": list(self.notches),
            "contributors": list(self.contributors),
            "unavailable": list(self.unavailable),
            "refusal": self.refusal,
            "analysis_count": self.analysis_count,
        }


# --------------------------------------------------------------- the reading


def periods_for(window: str, published: list[str], *,
                opening: str = "", closing: str = "") -> tuple[str, str, str]:
    """The two dates to measure, or a reason there are none.

    Returns `(opening, closing, refusal)`. Every date is one the dataset
    actually publishes: a window that would step off the end of the history is
    refused rather than clamped, because a "year-on-year" movement silently
    measured over two quarters is a wrong answer wearing a right label.
    """
    published = [p for p in published if p]
    if not published:
        return "", "", (f"{DATASET} has no published periods, so there is "
                        "nothing to compare.")

    if window == EXPLICIT or (opening and closing):
        for value in (opening, closing):
            if value not in published:
                return "", "", (f"{value!r} is not a published period of "
                                f"{DATASET}. It publishes "
                                f"{published[0]} to {published[-1]}.")
        return opening, closing, ""

    if window == MOM:
        return "", "", (f"{DATASET} publishes quarterly, so there is no "
                        "month-on-month movement to measure. Ask for the "
                        "quarter or the year instead.")

    step = _STEPS.get(window)
    if step is None:
        return "", "", f"{window!r} is not a comparison this blueprint knows."

    end = closing or published[-1]
    if end not in published:
        return "", "", (f"{end!r} is not a published period of {DATASET}.")
    index = published.index(end)
    if index < step:
        return "", "", (
            f"{DATASET} publishes from {published[0]}, which is not far "
            f"enough back to measure {window} against {end}.")
    return published[index - step], end, ""


def review(subject: str, *, dimension: str = "sector", window: str = QOQ,
           opening: str = "", closing: str = "", top_n: int = 10) -> Review:
    """Run the blueprint over one named segment.

    Every figure comes from one governed read of `DATASET` per date. Nothing
    is estimated, nothing is joined, and a measure the dataset does not carry
    is reported in `unavailable` rather than approximated.
    """
    from backend.data_access import get_data_source
    from backend.data_access.context import AnalysisContext

    out = Review(subject=subject, dimension=dimension, window=window,
                 unavailable=[{"measure": m, "why": w} for m, w in UNAVAILABLE])
    if dimension not in DIMENSIONS:
        out.refusal = (f"{dimension!r} is not a segmentation this blueprint "
                       f"reads. It reads {' and '.join(DIMENSIONS)}.")
        return out

    source = get_data_source()
    try:
        published = list(source.periods(DATASET))
    except Exception as e:  # noqa: BLE001 - refuse with the reason
        logger.warning("Could not read the periods of %s: %s", DATASET, e)
        out.refusal = f"{DATASET} could not be read: {e}"
        return out

    out.opening, out.closing, out.refusal = periods_for(
        window, published, opening=opening, closing=closing)
    if out.refusal:
        return out

    frames = {}
    for label in (out.opening, out.closing):
        context = AnalysisContext(period=label,
                                  filters={dimension: subject} if subject
                                  else {})
        try:
            frame = source.fetch(DATASET, fields=list(_FIELDS), context=context)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not read %s at %s: %s", DATASET, label, e)
            out.refusal = f"{DATASET} could not be read at {label}: {e}"
            return out
        if subject and dimension in frame.columns:
            frame = frame[frame[dimension].astype(str).str.casefold()
                          == str(subject).casefold()]
        frames[label] = frame

    if all(f.empty for f in frames.values()):
        out.refusal = (f"No {DATASET} rows for {subject or 'the book'} at "
                       f"{out.opening} or {out.closing}.")
        return out

    before, after = frames[out.opening], frames[out.closing]
    out.movements = [_measure(lens, before, after) for lens in LENSES]
    out.stage_balance = _by_stage(before, after, "ead", out)
    out.stage_count = _by_stage(before, after, "", out)
    out.notches = _notches(before, after, out)
    out.contributors = _contributors(before, after, top_n=top_n)
    return out


#: Everything the blueprint reads, in one list, so the read is one read.
_FIELDS: tuple[str, ...] = (
    "account_id", "customer_id", "sector", "segment", "period",
    "ead", "pd_12m_pct", "pd_lifetime_pct", "pd_at_origination_pct",
    "lgd_pct", "total_ecl", "ecl_coverage_pct", "ifrs9_stage", "prior_stage",
    "notches_since_origination",
)


def _numeric(frame: Any, column: str) -> Any:
    import pandas as pd

    if column not in frame.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _aggregate(lens: Lens, frame: Any) -> float:
    if frame is None or frame.empty:
        return 0.0
    values = _numeric(frame, lens.field)
    if values.empty:
        return 0.0
    if lens.aggregation == "sum":
        return float(values.sum())
    if lens.aggregation == "weighted_mean":
        weights = _numeric(frame, lens.weight)
        total = float(weights.sum())
        if total <= 0:
            # No exposure to weight by. The unweighted mean is stated rather
            # than a zero, because a segment with no EAD still has PDs.
            return float(values.mean())
        return float((values * weights).sum() / total)
    return float(values.mean())


def _measure(lens: Lens, before: Any, after: Any) -> Movement:
    return Movement(lens=lens,
                    opening=_aggregate(lens, before),
                    closing=_aggregate(lens, after),
                    opening_rows=int(len(before)),
                    closing_rows=int(len(after)))


def _by_stage(before: Any, after: Any, measure: str, out: Review
              ) -> list[dict[str, Any]]:
    """Stage distribution at both dates, by balance or by account count.

    `measure` empty means count the facilities. Two calls rather than one
    result with two columns, because they are two analyses: one says how much
    money moved and one says how many names did, and a reader who is shown
    only the first cannot tell three large borrowers from a trend.
    """
    import pandas as pd

    stages: set[str] = set()
    for frame in (before, after):
        if "ifrs9_stage" in frame.columns:
            stages |= {str(s) for s in frame["ifrs9_stage"].dropna().unique()}
    rows: list[dict[str, Any]] = []
    for stage in sorted(stages):
        row: dict[str, Any] = {"ifrs9_stage": stage}
        for label, frame in ((out.opening, before), (out.closing, after)):
            if "ifrs9_stage" not in frame.columns:
                row[label] = 0.0
                continue
            subset = frame[frame["ifrs9_stage"].astype(str) == stage]
            row[label] = (float(_numeric(subset, measure).sum()) if measure
                          else int(len(subset)))
        change = (float(row.get(out.closing) or 0)
                  - float(row.get(out.opening) or 0))
        # A count that changed by -129.0 is a float where a number of
        # facilities should be. The unit is facilities either way, and
        # printing it with a decimal point makes a reader wonder what a
        # fractional facility is.
        row["change"] = round(change, 6) if measure else int(change)
        rows.append(row)
    del pd
    return rows


def _notches(before: Any, after: Any, out: Review) -> list[dict[str, Any]]:
    """Facilities by how far their grade has slipped since origination.

    Banded rather than averaged: "0.4 notches on average" describes no
    facility, while "31 facilities are three or more notches below where they
    were written" is a population somebody can go and look at.
    """
    bands = ((0, 0, "At origination"), (1, 1, "1 notch below"),
             (2, 2, "2 notches below"), (3, 99, "3 or more notches below"))
    rows: list[dict[str, Any]] = []
    for low, high, label in bands:
        row: dict[str, Any] = {"band": label}
        for period, frame in ((out.opening, before), (out.closing, after)):
            values = _numeric(frame, "notches_since_origination")
            row[period] = int(((values >= low) & (values <= high)).sum()) \
                if not values.empty else 0
        row["change"] = int(row.get(out.closing) or 0) - int(
            row.get(out.opening) or 0)
        rows.append(row)
    return rows


def _contributors(before: Any, after: Any, *, top_n: int = 10
                  ) -> list[dict[str, Any]]:
    """The borrowers behind the ECL movement, largest contribution first.

    A segment total says how much moved; this says who, and it is the line a
    review is acted on. Borrowers present at only one date are included with
    the missing side at zero — a name that arrived or left is exactly the kind
    of contribution a reader must not have hidden from them.
    """
    if "customer_id" not in getattr(before, "columns", []) \
            and "customer_id" not in getattr(after, "columns", []):
        return []

    def totals(frame: Any) -> dict[str, tuple[float, float]]:
        if frame is None or frame.empty or "customer_id" not in frame.columns:
            return {}
        grouped = frame.assign(
            _ecl=_numeric(frame, "total_ecl"),
            _ead=_numeric(frame, "ead"),
        ).groupby("customer_id", dropna=True)[["_ecl", "_ead"]].sum()
        return {str(k): (float(v["_ecl"]), float(v["_ead"]))
                for k, v in grouped.to_dict("index").items()}

    opening, closing = totals(before), totals(after)
    rows = []
    for customer in set(opening) | set(closing):
        was_ecl, was_ead = opening.get(customer, (0.0, 0.0))
        now_ecl, now_ead = closing.get(customer, (0.0, 0.0))
        rows.append({
            "customer_id": customer,
            "ecl_opening": round(was_ecl, 4),
            "ecl_closing": round(now_ecl, 4),
            "ecl_change": round(now_ecl - was_ecl, 4),
            "ead_opening": round(was_ead, 4),
            "ead_closing": round(now_ead, 4),
        })
    rows.sort(key=lambda r: r["ecl_change"], reverse=True)
    return rows[:max(top_n, 1)]


# ---------------------------------------------------- the blueprint as asked


#: How each lens is asked for as an ordinary governed question. Written per
#: lens rather than formatted from the label, because the right sentence
#: differs: exposure MOVES, a PD is WEIGHTED, and a stage MIGRATES. A review
#: that asked "how has 12-month point-in-time PD moved" and got an unweighted
#: mean back would have answered a different question in the right words.
#: Deliberately plain. "How has the EXPOSURE-WEIGHTED 12-month PD moved" made
#: the reader see "exposure" as the measure and ask which exposure figure was
#: meant — a clarification instead of an answer, on all four parameter
#: questions at once. Weighting is a method decision the concept contract
#: already carries; saying it in the question changes what the question is
#: about. Likewise "modelled" on LGD, which is a real governed distinction the
#: reader asks about when the question leaves it open.
_ASKED: dict[str, str] = {
    "exposure": "How has exposure at default moved in {subject} {window}?",
    "pd_12m": "How has the 12-month PD moved in {subject} {window}?",
    "pd_lifetime": "How has the lifetime PD moved in {subject} {window}?",
    "pd_ttc": "How has the PD at origination moved in {subject} {window}?",
    "lgd": "How has modelled loss given default moved in {subject} {window}?",
    "ecl": "How has expected credit loss moved in {subject} {window}?",
    "coverage": "How has ECL coverage moved in {subject} {window}?",
}

#: The four analyses that are not a single measure over two dates.
_STRUCTURAL: tuple[tuple[str, str, str], ...] = (
    ("stage_balance",
     "What is total exposure at default in {subject} by IFRS 9 stage?",
     "Where the money sits. A stage 2 balance that grew is the provision "
     "consequence before it is a provision."),
    ("stage_count",
     "How many {subject} facilities are there in each IFRS 9 stage?",
     "How many names moved, which is a different question from how much "
     "balance moved and routinely has a different answer."),
    ("notches",
     "How has the average notches since origination moved in {subject} "
     "{window}?",
     "How far the grades slipped. A book can migrate stage without any "
     "grade moving, and the two together say whether the model or the "
     "obligors led."),
    ("contributors",
     "Show me the top ten {subject} customers by increase in expected credit "
     "loss {window}.",
     "A segment total says how much moved; this says who, and it is the "
     "line a review is acted on."),
)

#: How each window reads in a question. The blueprint asks in the words a
#: person would use, because these questions are answered by the same reader
#: that answers a person's.
_WINDOW_PHRASE: dict[str, str] = {
    QOQ: "over the latest quarter",
    YOY: "over the latest year",
}


def questions(subject: str, *, dimension: str = "sector", window: str = QOQ,
              opening: str = "", closing: str = "") -> list[dict[str, str]]:
    """The governed questions a complete deterioration review asks.

    Returned as questions rather than as figures on purpose. Each one goes
    through exactly the path a user's own question goes through — the same
    reader, the same validator, the same runtime, the same Trace — so every
    number in the review reconciles like any other answer and none of it is a
    second computation nobody can check. `review()` computes the same measures
    directly and exists to CHECK these, not to replace them.
    """
    phrase = (f"between {opening} and {closing}" if opening and closing
              else _WINDOW_PHRASE.get(window, "over the latest quarter"))
    named = subject or "the book"
    del dimension
    asked: list[dict[str, str]] = []
    for lens in LENSES:
        template = _ASKED.get(lens.key)
        if not template:
            continue
        asked.append({
            "key": lens.key,
            "label": lens.label,
            "question": template.format(subject=named, window=phrase).replace(
                "  ", " "),
            "because": lens.because,
        })
    for key, template, because in _STRUCTURAL:
        asked.append({
            "key": key,
            "label": {"stage_balance": "IFRS 9 stage, by balance",
                      "stage_count": "IFRS 9 stage, by account count",
                      "notches": "Grade slippage",
                      "contributors": "Borrowers behind the movement"}[key],
            "question": template.format(subject=named,
                                        window=phrase).replace("  ", " "),
            "because": because,
        })
    return asked


#: The sentence shapes that mean "this segment has gone wrong, show me
#: everything", as opposed to "compute one figure about it".
_COMPLETE = (
    r"\bshow me everything\b",
    r"\bfull (?:review|picture|analysis)\b",
    r"\bcomplete (?:review|picture|analysis)\b",
    r"\beverything (?:about|on)\b",
    r"\b(?:has|have) deteriorated\b",
    r"\bdeterioration review\b",
    r"\bwhat(?:'s| is) driving the deterioration\b",
)


def wants_complete_review(question: str) -> bool:
    """Whether this asks for the whole blueprint rather than one probe."""
    text = " ".join((question or "").lower().split())
    return any(re.search(pattern, text) for pattern in _COMPLETE)


__all__ = ["Lens", "Movement", "Review", "LENSES", "UNAVAILABLE", "DATASET",
           "DIMENSIONS", "MOM", "QOQ", "YOY", "EXPLICIT", "BLUEPRINT_VERSION",
           "read_window", "periods_for", "review", "questions",
           "wants_complete_review"]

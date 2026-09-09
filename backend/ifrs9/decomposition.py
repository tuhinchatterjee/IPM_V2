"""The IFRS 9 ECL bridge: how the book gets from a flat PD to reported ECL.

The defect this exists for
--------------------------
    "Give me an ECL decomposition."   →   5,313 SAR mn

One number. Correct, and not a decomposition of anything. The question asks how
the provision is BUILT — which part of it is the shape of the rating book, which
part is the forward-looking view, which part is staging, which part is
collateral — and a total answers none of that.

What this is, and what it is not
--------------------------------
It is a **step bridge**. Each step replaces exactly one governed input with the
next and re-measures the whole book, so the difference between two consecutive
steps IS that input's contribution and nothing else.

It is not the period-over-period ECL movement (`ecl_movement`), which asks why
the provision changed between two dates. It is not the order-neutral driver
attribution (`orchestration.decomposition`), which splits one period's change
across EAD, PD and LGD. Both of those answer "what changed". This answers "what
is it made of".

Why it reconciles exactly
-------------------------
The last two steps are the reported columns themselves. Step 5 applies each
facility's own governed LGD, which by construction reproduces `model_ecl`; step
6 adds the governed `macro_overlay`, which reproduces `total_ecl`. So the bridge
lands on the reported provision by arithmetic rather than by assertion, and the
residual is the rounding already in the stored columns.

What is deliberately NOT here
------------------------------
**A TTC calibration step.** A bank that calibrates its grade-level PDs to
observed defaults has a calibration artefact, and the bridge should show what it
contributes. This installation carries no such artefact — there is no
calibration factor, no calibration table and no calibrated-PD column in the
governed catalogue — so the step is omitted and said to be omitted. Inventing a
calibration to fill a row would put a number in front of a credit committee that
no model produced.

**A non-calibrated sub-portfolio step.** Same reason: there is no separately
treated non-calibrated component in this book.

Both omissions are reported on the bridge (`OMITTED`) rather than left as a gap
in the step numbering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DECOMPOSITION_VERSION = "1.0.0"

#: The unit every money figure on this bridge is in. Read from the governed
#: catalogue's own declaration rather than assumed — a bridge labelled in the
#: wrong currency is worse than one with no label.
DEFAULT_UNIT = "SAR mn"

#: How close the final step must land to the reported provision before the
#: bridge may be shown. Fifteen basis points of one per cent: tight enough that
#: only the rounding already in the stored columns can pass, loose enough that
#: it does not fail on it.
RECONCILIATION_TOLERANCE_PCT = 0.01

#: The facility columns the bridge reads, and the staging columns it joins.
FACILITY_FIELDS = (
    "account_id", "customer_id", "borrower_name", "segment", "sector",
    "internal_grade", "rating_bucket", "ead", "lgd_pct", "pd_12m_pct",
    "pd_lifetime_pct", "ifrs9_stage", "collateral_value", "limit_amount",
    "model_ecl", "macro_overlay", "total_ecl",
)
STAGING_FIELDS = ("account_id", "pd_at_origination_pct")

#: The governed through-the-cycle anchor. `pd_at_origination_pct` is the PD the
#: facility was underwritten at, before the cycle moved it — which is what the
#: SICR relative trigger compares against, and the only through-the-cycle PD
#: this installation governs. `pd_12m_pct` is the current point-in-time PD.
TTC_COLUMN = "pd_at_origination_pct"
PIT_COLUMN = "pd_12m_pct"

#: Step identifiers, in bridge order. Stable: the Trace, the chart and the
#: drill-downs all address steps by key.
BASELINE = "flat_ttc_baseline"
RATING = "rating_distribution"
MACRO = "pit_macro"
STAGE = "sicr_stage"
COLLATERAL = "collateral_lgd"
OVERLAY = "management_overlay"

STEP_ORDER: tuple[str, ...] = (BASELINE, RATING, MACRO, STAGE, COLLATERAL,
                               OVERLAY)

#: Steps a bank with a calibration model would carry, and why this one does not.
OMITTED: tuple[dict[str, str], ...] = (
    {"step": "ttc_calibration",
     "name": "Calibrated TTC PD",
     "because": "This installation carries no PD calibration artefact — no "
                "calibration factor, calibration table or calibrated-PD column "
                "is governed — so there is nothing to measure the step "
                "against. It is omitted rather than estimated."},
    {"step": "non_calibrated_portfolio",
     "name": "Non-calibrated portfolio treatment",
     "because": "The book has no separately treated non-calibrated component. "
                "A step reporting zero for one that does not exist would read "
                "as a component that contributes nothing."},
)

STEP_LABELS: dict[str, tuple[str, str]] = {
    BASELINE: (
        "Flat TTC PD baseline",
        "Every facility measured at one through-the-cycle PD — the average "
        "credit quality of the book, counting each facility once — on the "
        "portfolio's average loss-given-default. The neutral starting "
        "benchmark, before the book's own shape enters.",
    ),
    RATING: (
        "Rating distribution applied",
        "The flat PD replaced by each facility's rating-grade through-the-cycle "
        "PD. Measures how much the provision moves purely because exposure sits "
        "in particular internal grades rather than at one portfolio PD.",
    ),
    MACRO: (
        "Point-in-time / forward-looking PD",
        "Through-the-cycle PDs replaced by the governed point-in-time PD, which "
        "carries the forward-looking and scenario-weighted view. The macro "
        "contribution to the provision.",
    ),
    STAGE: (
        "SICR / stage migration",
        "The governed IFRS 9 measurement basis applied: Stage 1 on the "
        "twelve-month PD, Stage 2 on the lifetime PD, Stage 3 at the "
        "credit-impaired treatment. The cost of where the book is staged.",
    ),
    COLLATERAL: (
        "Collateral and LGD mitigation",
        "The portfolio average loss-given-default replaced by each facility's "
        "own governed LGD, which carries its collateral and security. "
        "Reproduces the reported model ECL.",
    ),
    OVERLAY: (
        "Management overlay — final reported ECL",
        "The governed management overlay added to model output. Reproduces the "
        "reported provision.",
    ),
}


@dataclass(frozen=True)
class Step:
    """One rung of the bridge, and what it contributed."""

    key: str
    number: int
    name: str
    description: str
    #: ECL after this step, for the whole selected population.
    ecl: float
    #: This step minus the one before it. Zero for the baseline.
    impact: float
    #: The impact as a percentage of the previous step. None at the baseline
    #: and wherever the previous step was zero — a share of nothing is not a
    #: number, and printing one is how a bridge acquires an infinity.
    change_pct: float | None
    #: ECL after this step, per configured segment.
    by_segment: dict[str, float] = field(default_factory=dict)
    #: The step's impact, per configured segment.
    impact_by_segment: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The presented row: the columns a reader is meant to read.

        `description` leads the categorical columns because it is what names
        the step on the chart's axis, and the step key and the long method note
        are deliberately absent — a paragraph of methodology inside a table
        cell is not a column, and both are carried on the bridge's own
        dictionary where a drill-down and the Trace can reach them.
        """
        return {"step": self.number, "description": self.name,
                "ecl": round(self.ecl, 3),
                "step_impact": round(self.impact, 3),
                "change_pct": (None if self.change_pct is None
                               else round(self.change_pct, 2)),
                **{f"{_column(name)}_ecl": round(value, 3)
                   for name, value in self.by_segment.items()}}

    def to_full_dict(self) -> dict[str, Any]:
        """The row plus everything behind it, for the Trace and the drill-down."""
        return {**self.to_dict(), "key": self.key, "detail": self.description,
                "impact_by_segment": {_column(name): round(value, 3)
                                      for name, value in
                                      self.impact_by_segment.items()}}


@dataclass(frozen=True)
class Reconciliation:
    """Whether the bridge lands where the book says it should."""

    final_step_ecl: float
    reported_ecl: float
    residual: float
    residual_pct: float
    tolerance_pct: float
    reconciles: bool

    def to_dict(self) -> dict[str, Any]:
        return {"final_step_ecl": round(self.final_step_ecl, 3),
                "reported_ecl": round(self.reported_ecl, 3),
                "residual": round(self.residual, 4),
                "residual_pct": round(self.residual_pct, 5),
                "tolerance_pct": self.tolerance_pct,
                "reconciles": self.reconciles}


@dataclass(frozen=True)
class Bridge:
    """The whole decomposition, at every grain it was computed on."""

    period: str
    unit: str
    steps: tuple[Step, ...]
    segments: tuple[str, ...]
    reconciliation: Reconciliation
    #: One row per borrower, carrying its ECL at every step. The audit path
    #: behind the six totals, and what a "which borrowers drove step 4?"
    #: follow-up reads.
    contributions: pd.DataFrame
    facilities: int
    borrowers: int
    filters: dict[str, str] = field(default_factory=dict)
    assumptions: dict[str, float] = field(default_factory=dict)
    omitted: tuple[dict[str, str], ...] = OMITTED

    @property
    def final(self) -> Step:
        return self.steps[-1]

    def rows(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.steps]

    def step(self, key: str) -> Step | None:
        return next((s for s in self.steps if s.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": DECOMPOSITION_VERSION,
            "period": self.period, "unit": self.unit,
            "steps": [s.to_full_dict() for s in self.steps],
            "segments": list(self.segments),
            "reconciliation": self.reconciliation.to_dict(),
            "facilities": self.facilities, "borrowers": self.borrowers,
            "filters": dict(self.filters),
            "assumptions": {k: round(v, 4) for k, v in self.assumptions.items()},
            "omitted": [dict(o) for o in self.omitted],
        }


def _column(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in str(name).lower()).strip("_")


# --------------------------------------------------------------- reading


def read_book(period: str, *, filters: dict[str, str] | None = None,
              context: Any = None, user_id: int | None = None) -> pd.DataFrame:
    """The facility book for one period, with its governed TTC anchor joined.

    Facility level, because every step of the bridge is a re-measurement of
    each facility. Six portfolio totals with no rows behind them cannot answer
    "which borrowers drove the stage migration", and a decomposition nobody can
    drill into is a picture of an audit trail rather than one.
    """
    from backend.data_access import get_data_source
    from backend.data_access.context import AnalysisContext
    from backend.engine.helpers import FACILITY, resolve_periods

    source = get_data_source()
    # "latest" is a word, not a partition. Resolving it here means a caller can
    # say what a person would say and still read the same period the certified
    # analysis does.
    resolved, _, _ = resolve_periods(source, FACILITY, period, None)
    scope = context or AnalysisContext(period=resolved, user_id=user_id)
    facility = source.fetch("portfolio_facility", fields=list(FACILITY_FIELDS),
                            context=scope)
    staging = source.fetch("ifrs9_staging", fields=list(STAGING_FIELDS),
                           context=scope)
    return join_book(facility, staging, filters=filters)


def join_book(facility: pd.DataFrame, staging: pd.DataFrame, *,
              filters: dict[str, str] | None = None) -> pd.DataFrame:
    """Join the facility book to its staging record and apply any filters.

    Split out from `read_book` so the certified analysis, which reads both
    datasets through the Trace-recording execution context rather than through
    the data source directly, still assembles the population exactly the same
    way. Two joins would be two populations waiting to disagree.
    """
    book = facility.merge(staging, on="account_id", how="inner")
    for name, value in (filters or {}).items():
        if name in book.columns:
            book = book[book[name].astype(str) == str(value)]
    return book.reset_index(drop=True)


# --------------------------------------------------------------- the bridge


def build(book: pd.DataFrame, *, period: str, unit: str = DEFAULT_UNIT,
          filters: dict[str, str] | None = None) -> Bridge:
    """Measure the book six times, replacing one governed input each time.

    Every step is the same arithmetic — exposure times loss rate times the
    applicable PD — with exactly one term swapped. That is what makes the
    difference between two steps attributable to that term and to nothing else,
    and it is why the bridge adds up without a plug.
    """
    if book.empty:
        raise ValueError("The bridge needs at least one facility to measure.")

    ead = _numeric(book, "ead")
    lgd = _numeric(book, "lgd_pct")
    ttc = _numeric(book, TTC_COLUMN)
    pit = _numeric(book, PIT_COLUMN)
    lifetime = _numeric(book, "pd_lifetime_pct")
    stage = _numeric(book, "ifrs9_stage")
    overlay = _numeric(book, "macro_overlay")
    grade = book.get("internal_grade")

    exposure = float(ead.sum())
    if exposure <= 0:
        raise ValueError("The selected population carries no exposure.")

    # The two neutral settings the early steps hold constant. Both are computed
    # from the book rather than chosen: the loss rate is the exposure-weighted
    # average, because a provision is a money-weighted quantity; the flat PD
    # counts each facility once, because it is a statement about the average
    # credit quality of the book and not about where its money sits — which is
    # precisely what the next step measures.
    flat_lgd = float(np.average(lgd, weights=ead))
    flat_ttc = float(ttc.mean())

    grade_ttc = _grade_pd(grade, ttc, ead)
    horizon = np.where(stage <= 1, pit, np.where(stage >= 3, 100.0, lifetime))

    per_facility = {
        BASELINE: ead * (flat_lgd / 100.0) * (flat_ttc / 100.0),
        RATING: ead * (flat_lgd / 100.0) * (grade_ttc / 100.0),
        MACRO: ead * (flat_lgd / 100.0) * (pit / 100.0),
        STAGE: ead * (flat_lgd / 100.0) * (horizon / 100.0),
        COLLATERAL: ead * (lgd / 100.0) * (horizon / 100.0),
    }
    per_facility[OVERLAY] = per_facility[COLLATERAL] + overlay

    segments = tuple(sorted({str(s) for s in book.get("segment", pd.Series(dtype=str))
                             .dropna().unique()}))
    steps: list[Step] = []
    previous: float | None = None
    previous_by_segment: dict[str, float] = {}
    for number, key in enumerate(STEP_ORDER, start=1):
        values = per_facility[key]
        total = float(np.sum(values))
        by_segment = _by_segment(book, values, segments)
        name, description = STEP_LABELS[key]
        impact = 0.0 if previous is None else total - previous
        steps.append(Step(
            key=key, number=number, name=name, description=description,
            ecl=total, impact=impact,
            change_pct=_share(impact, previous),
            by_segment=by_segment,
            impact_by_segment={s: by_segment.get(s, 0.0)
                               - previous_by_segment.get(s, 0.0)
                               for s in segments} if previous is not None else
            {s: 0.0 for s in segments}))
        previous, previous_by_segment = total, by_segment

    reported = float(_numeric(book, "total_ecl").sum())
    final = steps[-1].ecl
    residual = reported - final
    reconciliation = Reconciliation(
        final_step_ecl=final, reported_ecl=reported, residual=residual,
        residual_pct=abs(residual) / reported * 100.0 if reported else 0.0,
        tolerance_pct=RECONCILIATION_TOLERANCE_PCT,
        reconciles=(abs(residual) / reported * 100.0
                    <= RECONCILIATION_TOLERANCE_PCT) if reported else False)

    return Bridge(
        period=period, unit=unit, steps=tuple(steps), segments=segments,
        reconciliation=reconciliation,
        contributions=_contributions(book, per_facility),
        facilities=int(len(book)),
        borrowers=int(book["customer_id"].nunique())
        if "customer_id" in book.columns else 0,
        filters=dict(filters or {}),
        assumptions={"flat_ttc_pd_pct": flat_ttc, "flat_lgd_pct": flat_lgd,
                     "total_ead": exposure})


def _numeric(book: pd.DataFrame, column: str) -> np.ndarray:
    return pd.to_numeric(book.get(column), errors="coerce").fillna(0.0).to_numpy()


def _share(impact: float, previous: float | None) -> float | None:
    """The step's impact as a share of the step before it.

    None rather than zero or an infinity where there is no previous step or it
    was zero. A percentage change from nothing is not a number, and a bridge
    that prints one has said something untrue in its most scannable column.
    """
    if previous is None or previous == 0:
        return None
    return impact / previous * 100.0


def _grade_pd(grade: Any, ttc: np.ndarray, ead: np.ndarray) -> np.ndarray:
    """Each facility's rating-grade through-the-cycle PD.

    Exposure-weighted within the grade, so the grade PD is the PD of the money
    in that grade. Where a grade is missing the facility keeps its own TTC PD,
    which leaves this step neutral for it rather than pushing it to a portfolio
    average it does not belong to.
    """
    if grade is None:
        return ttc
    frame = pd.DataFrame({"grade": grade.to_numpy(), "ttc": ttc, "ead": ead})
    weighted = frame.groupby("grade", dropna=True).apply(
        lambda rows: (float(np.average(rows["ttc"], weights=rows["ead"]))
                      if rows["ead"].sum() > 0 else float(rows["ttc"].mean())),
        include_groups=False)
    mapped = frame["grade"].map(weighted)
    return pd.to_numeric(mapped, errors="coerce").fillna(
        pd.Series(ttc, index=frame.index)).to_numpy()


def _by_segment(book: pd.DataFrame, values: np.ndarray,
                segments: tuple[str, ...]) -> dict[str, float]:
    if "segment" not in book.columns or not segments:
        return {}
    frame = pd.DataFrame({"segment": book["segment"].astype(str),
                          "value": values})
    totals = frame.groupby("segment")["value"].sum()
    return {name: float(totals.get(name, 0.0)) for name in segments}


def _contributions(book: pd.DataFrame,
                   per_facility: dict[str, np.ndarray]) -> pd.DataFrame:
    """One row per borrower, with its ECL at every step and every step impact.

    The audit path. A borrower's stage-migration contribution is the difference
    between its own step 4 and step 3, summed across its facilities — the same
    subtraction the portfolio bridge does, at the grain a credit officer works
    at.
    """
    frame = pd.DataFrame({
        "customer_id": book.get("customer_id", pd.Series(dtype=str)),
        "borrower_name": book.get("borrower_name", pd.Series(dtype=str)),
        "segment": book.get("segment", pd.Series(dtype=str)),
        "sector": book.get("sector", pd.Series(dtype=str)),
        "internal_grade": book.get("internal_grade", pd.Series(dtype=float)),
        "ifrs9_stage": book.get("ifrs9_stage", pd.Series(dtype=float)),
        "ead": _numeric(book, "ead"),
        "reported_ecl": _numeric(book, "total_ecl"),
    })
    for key in STEP_ORDER:
        frame[f"ecl_{key}"] = per_facility[key]

    keys = ["customer_id", "borrower_name", "segment", "sector"]
    grouped = frame.groupby(keys, dropna=False).agg(
        facilities=("ead", "size"), ead=("ead", "sum"),
        reported_ecl=("reported_ecl", "sum"),
        internal_grade=("internal_grade", "max"),
        worst_stage=("ifrs9_stage", "max"),
        **{f"ecl_{key}": (f"ecl_{key}", "sum") for key in STEP_ORDER},
    ).reset_index()

    previous = ""
    for key in STEP_ORDER:
        grouped[f"impact_{key}"] = (
            0.0 if not previous else grouped[f"ecl_{key}"] - grouped[f"ecl_{previous}"])
        previous = key
    return grouped


def contributors(bridge: Bridge, step: str, *, limit: int = 10,
                 by: str = "customer_id") -> pd.DataFrame:
    """The borrowers that contributed most to one step, largest first.

    Read out of the same per-facility calculation the portfolio total came
    from, so the contributions sum to the step impact exactly.
    """
    column = f"impact_{step}"
    frame = bridge.contributions
    if column not in frame.columns:
        return frame.head(0)
    ordered = frame.reindex(frame[column].abs().sort_values(ascending=False).index)
    keep = ["customer_id", "borrower_name", "segment", "sector",
            "internal_grade", "worst_stage", "ead", column,
            f"ecl_{step}", "reported_ecl"]
    del by
    return ordered[[c for c in keep if c in ordered.columns]].head(limit)


__all__ = [
    "BASELINE", "COLLATERAL", "DECOMPOSITION_VERSION", "DEFAULT_UNIT",
    "FACILITY_FIELDS", "MACRO", "OMITTED", "OVERLAY", "PIT_COLUMN", "RATING",
    "RECONCILIATION_TOLERANCE_PCT", "STAGE", "STEP_LABELS", "STEP_ORDER",
    "STAGING_FIELDS", "TTC_COLUMN", "Bridge", "Reconciliation", "Step",
    "build", "contributors", "join_book", "read_book",
]

"""The retail portfolio review: what needs attention, from the retail book.

The defect this exists for
--------------------------
The Cockpit opens on a panel headed **Requires attention**. On the retail
installation it read

    "No portfolio review has been completed, so nothing here has been checked
     yet."

and All / Portfolio / Segments / Customers / Data each showed **0** — not
because the book is quiet but because the review that fills the panel reads
`corporate_borrower_360`, and a retail installation deliberately holds no
corporate book. The panel could not populate at all, and the only instruction
the product could offer was to go and build a corporate universe.

So there is a retail review, and it reads the retail book.

What it raises
--------------
Two classes, because those are the two things that bring a Head of Retail Risk
into the room:

* **Deterioration** — a product whose arrears or default entry has been rising
  for consecutive months. Persistence matters more than level here: one bad
  month is noise, three in a row is a trend.
* **Impairment** — a product whose ECL has risen materially this month, with
  the size of the move and what it did to coverage.

Every case names its product, its figures, both periods and the rule that
raised it. Nothing is scored by judgement: the severity comes from the size of
the move and how long it has run, and the sentence is generated from that
arithmetic so it cannot disagree with the number beside it.

Everything here is synthetic demonstration material. No threshold in it is a
bank policy and none of it has been approved by anybody.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.agentic import cases as rc
from backend.agentic import severity as sv

logger = logging.getLogger(__name__)

REVIEWER = "retail-portfolio-review"

#: Synthetic demonstration thresholds. Bank-configurable; not a policy.
#: A move smaller than this is not worth a Head of Retail Risk's morning.
ECL_RISE_PCT = 5.0
#: Consecutive months of a rising arrears rate before it reads as a trend.
DETERIORATION_MONTHS = 3
#: How many months of history the persistence test looks back over.
LOOKBACK = 6

BOOK = "retail_facility_month"


@dataclass
class Outcome:
    """What one review found."""

    period: str = ""
    previous_period: str = ""
    evaluated: int = 0
    qualified: int = 0
    opened: int = 0
    refreshed: int = 0
    case_ids: list[int] = field(default_factory=list)
    bands: dict[str, int] = field(default_factory=dict)
    rules: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.period}: {self.evaluated} product(s) evaluated, "
                f"{self.qualified} qualified, {self.opened} opened, "
                f"{self.refreshed} refreshed")


# ------------------------------------------------------------------ reading

def _frame(period: str) -> Any:
    """One month of the canonical book, through the governed source."""
    import pandas as pd  # noqa: F401  - used by the source

    from backend.data_access import get_data_source

    data = get_data_source()
    return data.read(BOOK, period=period) if hasattr(data, "read") else None


def _months() -> list[str]:
    from backend.data_access import get_data_source

    return list(get_data_source().periods(BOOK) or [])


@dataclass(frozen=True)
class Series:
    """One product's history of the two things this review watches."""

    product: str
    months: tuple[str, ...]
    dpd30: tuple[float, ...]
    ecl: tuple[float, ...]
    gca: tuple[float, ...]
    facilities: tuple[int, ...]

    @property
    def latest(self) -> str:
        return self.months[-1] if self.months else ""

    @property
    def previous(self) -> str:
        return self.months[-2] if len(self.months) > 1 else ""


def _history(months: list[str]) -> list[Series]:
    """Each product's arrears rate, ECL and exposure over the lookback.

    Read straight off the canonical parquet with pandas. Every figure a case
    quotes comes from here, so a case and an answer to the same question
    cannot disagree.
    """
    import glob

    import pandas as pd

    from backend.config import settings

    by_product: dict[str, dict[str, dict[str, float]]] = {}
    for month in months:
        paths = sorted(glob.glob(
            f"{settings.analytics_dir}/{BOOK}/reporting_month={month}/"
            "*.parquet"))
        if not paths:
            continue
        frame = pd.read_parquet(paths[0], columns=[
            "product_label", "dpd", "gross_carrying_amount_sar",
            "ecl_final_sar", "facility_id"])
        for product, rows in frame.groupby("product_label"):
            gca = float(rows.gross_carrying_amount_sar.sum())
            behind = float(
                rows[rows.dpd >= 30].gross_carrying_amount_sar.sum())
            by_product.setdefault(str(product), {})[month] = {
                "dpd30": (behind / gca * 100) if gca else 0.0,
                "ecl": float(rows.ecl_final_sar.sum()),
                "gca": gca,
                "facilities": float(rows.facility_id.nunique()),
            }

    out: list[Series] = []
    for product, per_month in sorted(by_product.items()):
        ordered = [m for m in months if m in per_month]
        out.append(Series(
            product=product,
            months=tuple(ordered),
            dpd30=tuple(per_month[m]["dpd30"] for m in ordered),
            ecl=tuple(per_month[m]["ecl"] for m in ordered),
            gca=tuple(per_month[m]["gca"] for m in ordered),
            facilities=tuple(int(per_month[m]["facilities"]) for m in ordered),
        ))
    return out


# ------------------------------------------------------------------- rules

def _rising_for(values: tuple[float, ...]) -> int:
    """How many consecutive months to the end of the series rose."""
    run = 0
    for earlier, later in zip(values, values[1:], strict=False):
        run = run + 1 if later > earlier else 0
    return run


def _score(*, size: float, months: int, what: str = "") -> sv.Score:
    """Severity from the size of the move and how long it has run.

    Two components and no judgement: a bigger move scores higher, and a move
    that has run for longer scores higher. Both are capped, so one very large
    month cannot produce a critical case on its own, and each carries the raw
    figure behind it so the arithmetic is checkable.
    """
    magnitude = min(abs(size) / 25.0, 1.0)
    persistence = min(months / 4.0, 1.0)
    components = [
        sv.Component(
            key=sv.MAGNITUDE, value=magnitude, weight=0.6,
            detail=(f"{what or 'the move'} of {size:+.2f}, capped at 25"),
            observed=round(size, 4)),
        sv.Component(
            key=sv.PERSISTENCE, value=persistence, weight=0.4,
            detail=(f"{months} month(s) of it, capped at 4"),
            observed=months),
    ]
    total = magnitude * 0.6 + persistence * 0.4
    band = next(name for floor, name in sv.BANDS if total >= floor)
    return sv.Score(score=round(total, 4), band=band, components=components)


def _deterioration(series: Series) -> rc.Draft | None:
    """A product whose arrears have been rising month after month."""
    if len(series.months) < DETERIORATION_MONTHS + 1:
        return None
    run = _rising_for(series.dpd30)
    if run < DETERIORATION_MONTHS:
        return None
    now, before = series.dpd30[-1], series.dpd30[-1 - run]
    moved = now - before
    return rc.Draft(
        level=rc.SEGMENT,
        title=(f"{series.product} 30+ DPD has risen for {run} consecutive "
               f"months"),
        period=series.latest,
        prior_period=series.previous,
        entity=series.product,
        entity_id=series.product,
        entity_kind="product",
        about="retail_deterioration",
        conclusion=(
            f"{series.product} is at {now:.2f}% 30+ DPD by exposure at "
            f"{series.latest}, up from {before:.2f}% {run} months earlier — "
            f"{moved:+.2f} percentage points, rising every month in between."),
        why=(
            "Raised because the rate rose in each of the last "
            f"{run} months, which is the synthetic demonstration threshold of "
            f"{DETERIORATION_MONTHS} consecutive months. The rate is "
            "SUM(gross carrying amount WHERE dpd >= 30) / SUM(gross carrying "
            "amount), recomputed for the product at each month-end rather "
            "than averaged across facilities."),
        exposure=round(series.gca[-1] / 1e6, 2),
        exposure_unit="SAR mn",
        metrics=[
            {"label": "30+ DPD rate", "value": round(now, 4), "unit": "%",
             "period": series.latest},
            {"label": f"30+ DPD rate {run} months earlier",
             "value": round(before, 4), "unit": "%",
             "period": series.months[-1 - run]},
            {"label": "Change", "value": round(moved, 4), "unit": "pp"},
            {"label": "Exposure", "value": round(series.gca[-1], 2),
             "unit": "SAR", "period": series.latest},
            {"label": "Facilities", "value": series.facilities[-1],
             "unit": "count", "period": series.latest},
        ],
        signals=[f"{run} consecutive monthly rises in the 30+ DPD rate"],
        evidence={"dataset": BOOK, "product": series.product,
                  "months": list(series.months[-1 - run:]),
                  "series": [round(v, 4) for v in series.dpd30[-1 - run:]],
                  "rule": "retail.deterioration.dpd30_consecutive_rises",
                  "threshold_source": (
                      "Synthetic demo threshold, bank-configurable: "
                      f"{DETERIORATION_MONTHS} consecutive monthly rises.")},
        score=_score(size=moved * 10, months=run,
                     what="a rise in the 30+ DPD rate"),
    )


def _impairment(series: Series) -> rc.Draft | None:
    """A product whose ECL rose materially this month."""
    if len(series.months) < 2:
        return None
    now, before = series.ecl[-1], series.ecl[-2]
    if before <= 0:
        return None
    moved = now - before
    pct = moved / before * 100
    if pct < ECL_RISE_PCT:
        return None
    coverage_now = (now / series.gca[-1] * 100) if series.gca[-1] else 0.0
    coverage_before = (before / series.gca[-2] * 100) if series.gca[-2] else 0.0
    return rc.Draft(
        level=rc.SEGMENT,
        title=f"{series.product} ECL rose {pct:.1f}% this month",
        period=series.latest,
        prior_period=series.previous,
        entity=series.product,
        entity_id=series.product,
        entity_kind="product",
        about="retail_impairment",
        conclusion=(
            f"{series.product} expected credit loss rose from "
            f"{before:,.0f} to {now:,.0f} SAR between {series.previous} and "
            f"{series.latest} — {moved:+,.0f} SAR, {pct:+.1f}%. Coverage "
            f"moved from {coverage_before:.2f}% to {coverage_now:.2f}%."),
        why=(
            f"Raised because the month-on-month rise exceeded the synthetic "
            f"demonstration threshold of {ECL_RISE_PCT:.0f}%. The figure is "
            "SUM(ecl_final_sar) for the product — the probability-weighted "
            "ECL across the three scenarios plus any overlay, which is what "
            "the reported allowance means."),
        exposure=round(series.gca[-1] / 1e6, 2),
        exposure_unit="SAR mn",
        metrics=[
            {"label": "Weighted ECL", "value": round(now, 2), "unit": "SAR",
             "period": series.latest},
            {"label": "Weighted ECL, prior month", "value": round(before, 2),
             "unit": "SAR", "period": series.previous},
            {"label": "Change", "value": round(moved, 2), "unit": "SAR"},
            {"label": "Change", "value": round(pct, 4), "unit": "%"},
            {"label": "ECL coverage", "value": round(coverage_now, 4),
             "unit": "%", "period": series.latest},
        ],
        signals=[f"weighted ECL up {pct:.1f}% month on month"],
        evidence={"dataset": BOOK, "product": series.product,
                  "months": [series.previous, series.latest],
                  "series": [round(before, 2), round(now, 2)],
                  "rule": "retail.impairment.ecl_month_on_month",
                  "threshold_source": (
                      "Synthetic demo threshold, bank-configurable: "
                      f"{ECL_RISE_PCT:.0f}% month on month.")},
        score=_score(size=pct, months=1,
                     what="a month-on-month rise in ECL"),
    )


RULES = (_deterioration, _impairment)


# --------------------------------------------------------------------- run

def run(session: Any, *, period: str = "", actor: str = REVIEWER,
        record_run: bool = True) -> Outcome:
    """Review the retail book at one reporting date and write the findings.

    Deterministic: the same book at the same period produces the same cases in
    the same order, because the rules are total and the dedupe key is the
    product, the period and the rule.

    `record_run` writes the agent run the Cockpit's panel reads. The panel
    separates "we looked and found nothing" from "nothing has looked", and
    only the run answers the second — so a review that wrote cases without one
    would leave the panel saying nothing had been checked while showing five
    things that had.
    """
    months = _months()
    if not months:
        return Outcome(notes=["the retail book holds no months"])
    if period and period in months:
        months = months[:months.index(period) + 1]
    window = months[-(LOOKBACK + 1):]

    history = _history(window)
    out = Outcome(period=window[-1],
                  previous_period=window[-2] if len(window) > 1 else "",
                  evaluated=len(history))

    from backend.agentic import runs as agent_runs

    run_row = None
    if record_run:
        run_row = agent_runs.start(
            session, trigger=agent_runs.MANUAL_REVIEW,
            question=(f"Review the retail book at {out.period} for "
                      "deterioration and for movements in the allowance."),
            period=out.period, prior_period=out.previous_period,
            service_identity=actor)
        session.flush()

    for series in history:
        for rule in RULES:
            draft = rule(series)
            name = rule.__name__.strip("_")
            out.rules[name] = out.rules.get(name, 0) + (1 if draft else 0)
            if draft is None:
                continue
            out.qualified += 1
            existing = _existing(session, draft)
            case = rc.upsert(session, draft, actor_agent=actor)
            out.case_ids.append(int(case.id))
            out.bands[case.severity] = out.bands.get(case.severity, 0) + 1
            if existing:
                out.refreshed += 1
            else:
                out.opened += 1

    if run_row is not None:
        agent_runs.finish(
            session, run_row,
            findings=[{"title": f"{name}: {count} raised", "rule": name}
                      for name, count in sorted(out.rules.items())],
            synthesis=out.summary(), cases=list(out.case_ids))
    return out


def _existing(session: Any, draft: rc.Draft) -> bool:
    from sqlalchemy import select

    from backend.models.platform import RiskCase

    return session.execute(
        select(RiskCase).where(RiskCase.dedupe_key == draft.key)
    ).scalar_one_or_none() is not None

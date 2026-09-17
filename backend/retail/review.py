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
Three classes, because those are the things that bring a Head of Retail Risk
into the room:

* **Deterioration** — a product whose arrears or default entry has been rising
  for consecutive months. Persistence matters more than level here: one bad
  month is noise, three in a row is a trend.
* **Impairment** — a product whose ECL has risen materially this month, with
  the size of the move and what it did to coverage.
* **Early-delinquency migration** — a product whose population has moved out of
  current status into the first arrears bucket without the later buckets moving
  with it. Not a deterioration in the sense above and not an impairment: no
  money has been lost yet. It is raised because it is the earliest point at
  which anything can still be done, and because by the time it reaches the
  later buckets the decision that mattered has already been taken.

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
from backend.retail import episode_cases

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
CARD_LABEL = "Credit Card"

#: Synthetic demonstration thresholds for the early-delinquency migration.
#: Bank-configurable; none of them is a policy.
#: How far above its recent baseline the 1-29 population has to be.
EARLY_MULTIPLE = 1.6
#: And how many percentage points above the prior month, so a small book
#: doubling from a fraction of a percent does not raise a case.
EARLY_RISE_PP = 2.5
#: How much of that rise the fall in 0 DPD has to account for, before it reads
#: as a migration rather than as a book that grew.
MIGRATION_MATCH = 0.7
#: How far a later bucket may move and still leave this an EARLY finding.
EARLY_LATER_TOLERANCE_PP = 1.5


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


def _early_delinquency(period: str) -> rc.Draft | None:
    """The card book's population moving out of current into early arrears.

    NOT a rule about the default rate, and the case says so in its first
    sentence. What it watches is the 1-29 DPD POPULATION: how many card
    accounts are one cycle behind, against how many were one cycle behind in
    the months before. A book whose later buckets are unchanged and whose early
    bucket has doubled has not lost more money this month — it has lost
    something more useful, which is the assumption that the customers in it
    were going to pay.

    Raised on three conditions together, so that none of them can carry the
    case alone:

      * the 1-29 population is materially above the recent baseline, both as a
        multiple and in percentage points;
      * the current population fell by a comparable amount, which is what makes
        it a MIGRATION rather than a book that grew;
      * the later buckets did not move with it, which is what makes it early
        rather than an arrears problem already in train.

    The severity is the published arithmetic of `backend.agentic.severity`, and
    every component carries the figure it was computed from.
    """
    from backend.retail import anb_demo as anb

    found = anb.early_delinquency(period)
    if not found.get("available"):
        return None

    early, current = found["early"], found["current"]
    baseline, multiple = found["baseline"], found["baseline_multiple"]
    if (multiple < EARLY_MULTIPLE or early.change < EARLY_RISE_PP
            or current.change > -EARLY_RISE_PP * MIGRATION_MATCH):
        return None
    if found["later_worst"] > EARLY_LATER_TOLERANCE_PP:
        return None

    at, prior = found["period"], found["previous_period"]
    accounts = found["accounts"]
    moved = early.now_count - early.before_count
    later = ", ".join(f"{m.label} {m.now:.2f}%" for m in found["later"])
    weighted, balances = found["later_by_balance"], found["balances"]
    # The same ladder weighted by balance rather than by account. On a book
    # whose balances are growing, the two disagree — and the disagreement is
    # itself information, so the case carries it rather than picking the
    # reading that suits its own headline.
    divergence = ""
    if weighted.change > 0.2 and balances.now > balances.before:
        divergence = (
            f" Measured by BALANCE rather than by account the 30+ share did "
            f"move, from {weighted.before:.2f}% to {weighted.now:.2f}%, but "
            f"that is the same event seen from the other side: card balances "
            f"rose {(balances.now / balances.before - 1) * 100:.0f}% in the "
            f"month, so the accounts already past due are carrying more. The "
            f"figures above count CUSTOMERS, which is the question here.")

    return rc.Draft(
        level=rc.SEGMENT,
        title="Credit cards: rising population in 1-29 DPD",
        period=at,
        prior_period=prior,
        entity=CARD_LABEL,
        entity_id=CARD_LABEL,
        entity_kind="product",
        about="retail_early_delinquency",
        conclusion=(
            f"{early.now:.1f}% of credit-card accounts are 1-29 days past due "
            f"at {at}, against {early.before:.1f}% at {prior} and a "
            f"{baseline:.1f}% average over the {len(found['baseline_months'])} "
            f"months before it — {early.change:+.1f} percentage points and "
            f"{multiple:.1f} times the recent baseline, or {moved:+,} accounts. "
            f"The current population fell by {abs(current.change):.1f} points "
            f"over the same month, so these are accounts that have moved out of "
            f"0 DPD rather than accounts the book has added. Later delinquency "
            f"has not moved with them ({later}), so nothing has been lost yet — "
            f"what has changed is how many customers are one cycle behind."
            + divergence),
        why=(
            "Raised because three things hold together at this month-end, and "
            "no one of them would have raised it alone: the 1-29 population is "
            f"at least {EARLY_MULTIPLE:.1f} times its recent baseline and at "
            f"least {EARLY_RISE_PP:.0f} percentage points above last month; the "
            "0 DPD population fell by a comparable amount, which is what makes "
            "this a migration between buckets rather than a larger book; and no "
            f"later bucket moved by more than {EARLY_LATER_TOLERANCE_PP:.1f} "
            "points, which is what makes it early. Population shares are "
            "COUNT(accounts in the bucket) / COUNT(open card accounts) at each "
            "month-end, recomputed each month rather than carried forward, so a "
            "month in which the book grew cannot read as a month in which "
            "arrears fell. Thresholds are synthetic demonstration settings and "
            "bank-configurable; none of them is a policy."),
        exposure=found["exposure_sar_mn"],
        exposure_unit="SAR mn",
        metrics=[
            {"label": "1-29 DPD population", "value": early.now, "unit": "%",
             "period": at},
            {"label": "1-29 DPD population, prior month", "value": early.before,
             "unit": "%", "period": prior},
            {"label": "Change", "value": early.change, "unit": "pp"},
            {"label": "Recent baseline", "value": baseline, "unit": "%"},
            {"label": "Against the recent baseline", "value": multiple,
             "unit": "x"},
            {"label": "0 DPD population", "value": current.now, "unit": "%",
             "period": at},
            {"label": "Accounts now 1-29 DPD", "value": early.now_count,
             "unit": "count", "period": at},
            {"label": "Card accounts", "value": accounts, "unit": "count",
             "period": at},
            {"label": "Balance carried by accounts 1-29 DPD",
             "value": found["exposure_sar_mn"], "unit": "SAR mn",
             "period": at},
            {"label": "30+ DPD share of card balances",
             "value": weighted.now, "unit": "%", "period": at},
            {"label": "Card balances", "value": balances.now,
             "unit": "SAR mn", "period": at},
        ],
        signals=[
            f"1-29 DPD at {multiple:.1f} times its {len(found['baseline_months'])}"
            f"-month baseline",
            f"0 DPD down {abs(current.change):.1f} points in the same month",
            f"no later bucket moved by more than "
            f"{found['later_worst']:+.2f} points",
            f"{found['focus_now']:.1f}% of card accounts are 20-29 days past "
            f"due, {found['focus_share_of_early']:.0f}% of the 1-29 population",
            f"card balances up {(balances.now / balances.before - 1) * 100:.0f}% "
            f"in the month, which moves every balance-weighted rate on this "
            f"product without any more customers falling behind",
        ],
        evidence={
            "dataset": anb.BOOK,
            "product": CARD_LABEL,
            "months": list(found["trend"]["months"]),
            "rule": "retail.early_delinquency.bucket_migration",
            "threshold_source": (
                "Synthetic demo thresholds, bank-configurable: at least "
                f"{EARLY_MULTIPLE:.1f}x the recent baseline, at least "
                f"{EARLY_RISE_PP:.0f}pp above the prior month, a matching fall "
                "in 0 DPD, and no later bucket moving more than "
                f"{EARLY_LATER_TOLERANCE_PP:.1f}pp."),
            # What the drawer draws. Carried on the case rather than recomputed
            # by the screen, so the chart and the sentence above it cannot come
            # from two different readings of the book.
            "chart": {
                "title": "Credit-card accounts by delinquency bucket",
                "unit": "% of open card accounts",
                "series": list(found["trend"]["series"]),
                "focus": [label for label in found["trend"]["series"]
                          if label != "0 DPD"],
                "rows": list(found["trend"]["rows"]),
                "note": ("0 DPD is shown as a figure rather than a line: on one "
                         "axis with the others it flattens every bucket the "
                         "question is about."),
            },
            "narrative": (
                "The increase is driven by accounts migrating out of current "
                "status into early delinquency. Later-stage delinquency has "
                "not risen with it."),
        },
        score=_early_score(found),
    )


def _early_score(found: dict[str, Any]) -> sv.Score:
    """Severity for the migration, from the size of it and what it touches."""
    early = found["early"]
    accounts = max(found["accounts"], 1)
    magnitude = min(abs(early.change) / 10.0, 1.0)
    concentration = min(found["focus_share_of_early"] / 100.0, 1.0)
    materiality = min(early.now_count / (accounts * 0.15), 1.0)
    signals = min(found["baseline_multiple"] / 3.0, 1.0)
    components = [
        sv.Component(key=sv.MAGNITUDE, value=magnitude, weight=0.34,
                     detail=(f"a {early.change:+.2f} point move in the 1-29 "
                             "population, capped at 10 points"),
                     observed=round(early.change, 4)),
        sv.Component(key=sv.MATERIALITY, value=materiality, weight=0.26,
                     detail=(f"{early.now_count:,} of {accounts:,} card "
                             "accounts, against a 15% cap"),
                     observed=early.now_count),
        sv.Component(key=sv.SIGNALS, value=signals, weight=0.22,
                     detail=(f"{found['baseline_multiple']:.2f} times the "
                             "recent baseline, capped at 3"),
                     observed=round(found["baseline_multiple"], 4)),
        sv.Component(key=sv.CONCENTRATION, value=concentration, weight=0.18,
                     detail=(f"{found['focus_share_of_early']:.0f}% of the "
                             "1-29 population is 20-29 days past due"),
                     observed=round(found["focus_share_of_early"], 4)),
    ]
    total = sum(c.value * c.weight for c in components)
    band = next(name for floor, name in sv.BANDS if total >= floor)
    return sv.Score(score=round(total, 4), band=band, components=components)


RULES = (_deterioration, _impairment)

#: Rules that read the BOOK at a period rather than one product's series. The
#: migration rule is one: it is about how a single product's population is
#: distributed across the delinquency ladder, which is not a number a
#: per-product time series carries.
BOOK_RULES = (_early_delinquency,)


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

    for rule in BOOK_RULES:
        draft = rule(out.period)
        name = rule.__name__.strip("_")
        out.rules[name] = out.rules.get(name, 0) + (1 if draft else 0)
        if draft is not None:
            out.qualified += 1
            existing = _existing(session, draft)
            case = rc.upsert(session, draft, actor_agent=actor)
            out.case_ids.append(int(case.id))
            out.bands[case.severity] = out.bands.get(case.severity, 0) + 1
            if existing:
                out.refreshed += 1
            else:
                out.opened += 1

    # The nine episode stories. One adapter rather than nine rules, because
    # each of them answers the same six questions of a different pocket, and
    # nine functions that differed only in their wording would be nine places
    # for the wording to stop matching the figures.
    #
    # A story that does not reach its raising thresholds returns nothing and
    # no card appears. That path is not decorative: two of the nine sit close
    # to the thresholds, and a demonstration where every card always appears
    # whatever the book says is a demonstration of nothing.
    for draft in episode_cases.rule(out.period):
        name = f"episode_{(draft.entity_id or '').lower()}"
        out.rules[name] = out.rules.get(name, 0) + 1
        out.qualified += 1
        existing = _existing(session, draft)
        case = rc.upsert(session, draft, actor_agent=actor)
        out.case_ids.append(int(case.id))
        out.bands[case.severity] = out.bands.get(case.severity, 0) + 1
        if existing:
            out.refreshed += 1
        else:
            out.opened += 1

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

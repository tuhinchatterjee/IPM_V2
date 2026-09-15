"""
The card book's early-delinquency migration, and everything the investigation
of it reads.

WHY THIS MODULE EXISTS
----------------------
The Cockpit raises a Risk Case when the card book's 1-29 DPD population moves,
and the investigation that follows asks five questions of it: split the bucket,
look at the cohort's behavioural scores, decompose the score move by model
variable, find where the stress is concentrated, and say what to do. Every one
of those is a figure out of `retail_facility_month`.

They are computed HERE, once, rather than five times in five places. A case
that says 1-29 DPD doubled and an answer that says it rose by a third are not a
disagreement about presentation — they are two readings of the same book, and
the reader has no way to tell which one is wrong. So the drawer's chart, the
investigation's charts, the cohort counts, the concentration table and the
action table all come from these functions, and they cannot disagree because
there is only one of each.

WHAT IT WILL NOT DO
-------------------
* It computes no figure it cannot name the column for.
* It never widens a cohort silently. A function that is asked about the 20-29
  DPD card population at a month returns that population or an empty one, and
  says which.
* It reports the evidence behind a number alongside it — the population, the
  months compared, the definition used — because a percentage-point move with
  no denominator on screen is the number this product exists to stop shipping.

Everything it reads is SYNTHETIC demonstration data. Alpha Card is a
demonstration product. No threshold, policy or figure here is Arab National
Bank's, and none of it is a statement about any bank's performance.
"""

from __future__ import annotations

import glob
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

BOOK = "retail_facility_month"
CARD = "CREDIT_CARD"
CARD_LABEL = "Credit Card"

#: The sub-buckets the first investigation question splits 1-29 into.
SUB_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("1-9 DPD", 1, 9),
    ("10-19 DPD", 10, 19),
    ("20-29 DPD", 20, 29),
)
#: The sub-bucket the story is about. Named once.
FOCUS = "20-29 DPD"
FOCUS_LO, FOCUS_HI = 20, 29

#: The full delinquency ladder, in reading order.
BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0 DPD", 0, 0),
    ("1-29 DPD", 1, 29),
    ("30-59 DPD", 30, 59),
    ("60-89 DPD", 60, 89),
    ("90+ DPD", 90, None),
)

#: Behavioural bands, weakest first, with the words a reader uses for them. The
#: letters are the scorecard's; the words are what a credit committee says.
BAND_ORDER: tuple[str, ...] = ("E", "D", "C", "B", "A", "A+")
BAND_WORDS: dict[str, str] = {
    "E": "Very weak", "D": "Weak", "C": "Fair",
    "B": "Good", "A": "Strong", "A+": "Very strong",
}
#: What "weak and very weak" means, once, so every answer counts the same rows.
WEAK_BANDS: tuple[str, ...] = ("D", "E")

#: Which behavioural-model variables are delinquency information. The point of
#: the decomposition is to separate these from the rest, so the line is drawn
#: once, here, and stated on screen wherever the split is shown.
DELINQUENCY_VARIABLES: frozenset[str] = frozenset({
    "dpd", "max_dpd_6m", "missed_6m", "bureau_dpd",
    "broken_promise", "autopay_fail",
})
#: The two independent signals the third question is about.
DRAWING_VARIABLES: frozenset[str] = frozenset({
    "utilisation", "util_change", "overlimit", "cash_advance"})
REPAYMENT_VARIABLES: frozenset[str] = frozenset({"pay_ratio_3m", "min_pay"})

#: How many months of history a trend shows. Long enough that a stable baseline
#: is visible before the break, short enough that the break is not a pixel.
TREND_MONTHS = 8


# ---------------------------------------------------------------- reading

def _analytics_dir() -> str:
    from backend.config import settings

    return str(settings.analytics_dir)


@lru_cache(maxsize=1)
def months() -> tuple[str, ...]:
    """Every published month of the book, oldest first."""
    found = sorted(
        path.rsplit("=", 1)[-1]
        for path in glob.glob(f"{_analytics_dir()}/{BOOK}/reporting_month=*"))
    return tuple(found)


def latest_month() -> str:
    found = months()
    return found[-1] if found else ""


def previous_month(month: str = "") -> str:
    found = months()
    at = month or latest_month()
    if at in found:
        i = found.index(at)
        return found[i - 1] if i > 0 else ""
    return ""


def baseline_month(month: str = "") -> str:
    """The last month before the deterioration began.

    Read from the generator's own configuration rather than named here: the
    behavioural deterioration runs over a window the book was built with, and
    the month to compare against is the one before that window opened. A
    constant would be right until somebody changed the window and then wrong
    without saying so.

    The immediately preceding month is NOT that comparison. It is already
    inside the window: comparing against it would understate every behavioural
    movement the investigation is about, and it is the reason a
    quarter-on-quarter reading is the honest one here.
    """
    found = months()
    at = month or latest_month()
    if at not in found:
        return ""
    back = 3
    try:
        from backend.retail.config import get_config

        opts = get_config().card_programmes or {}
        back = max(int(opts.get("behaviour_months", 3)), 1)
    except Exception:  # noqa: BLE001 - a missing config is the default window
        logger.debug("no card-programme window configured; using %d months", back)
    i = found.index(at) - back
    return found[i] if i >= 0 else found[0]


def trend_months(month: str = "", count: int = TREND_MONTHS) -> list[str]:
    found = months()
    at = month or latest_month()
    if at not in found:
        return list(found[-count:])
    end = found.index(at) + 1
    return list(found[max(end - count, 0):end])


@lru_cache(maxsize=64)
def _read(month: str, columns: tuple[str, ...]) -> Any:
    """One month of the card book, only the columns asked for.

    Cached because the Cockpit, the drawer and five investigation answers read
    overlapping slices of the same few months, and re-reading a 546-column
    parquet for each of them is the difference between a demonstration that
    answers and one the presenter apologises for.
    """
    import pandas as pd

    paths = sorted(glob.glob(
        f"{_analytics_dir()}/{BOOK}/reporting_month={month}/*.parquet"))
    if not paths:
        return pd.DataFrame(columns=list(columns))
    want = list(dict.fromkeys(columns))
    frame = pd.read_parquet(paths[0], columns=want)
    return frame


def cards(month: str, columns: Sequence[str]) -> Any:
    """The credit-card rows of one month, with `product_code` always present."""
    want = tuple(dict.fromkeys(["product_code", *columns]))
    frame = _read(month, want)
    if frame.empty:
        return frame
    return frame[frame["product_code"] == CARD]


def available() -> bool:
    """Whether the book this module reads is published at all."""
    return bool(months())


def reset_cache() -> None:
    """Forget what was read. For a rebuild, and for the tests."""
    months.cache_clear()
    _read.cache_clear()


# ---------------------------------------------------------------- helpers

def _pct(part: float, whole: float) -> float:
    return round(part / whole * 100, 2) if whole else 0.0


def _in(series: Any, lo: int, hi: int | None) -> Any:
    return (series >= lo) if hi is None else ((series >= lo) & (series <= hi))


@dataclass
class Movement:
    """One figure at two dates, and what it did in between.

    Carries the denominators. A percentage-point move whose population is not
    on the same object is a number that can be quoted without its evidence,
    which is how a demonstration acquires a figure nobody can source.
    """

    label: str
    now: float = 0.0
    before: float = 0.0
    unit: str = "%"
    now_count: int = 0
    before_count: int = 0
    now_period: str = ""
    before_period: str = ""

    @property
    def change(self) -> float:
        return round(self.now - self.before, 2)

    @property
    def multiple(self) -> float:
        return round(self.now / self.before, 2) if self.before else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "now": self.now, "before": self.before,
            "change": self.change, "multiple": self.multiple, "unit": self.unit,
            "now_count": self.now_count, "before_count": self.before_count,
            "now_period": self.now_period, "before_period": self.before_period,
        }


# ------------------------------------------------- the delinquency ladder

def bucket_trend(month: str = "", count: int = TREND_MONTHS) -> dict[str, Any]:
    """The card book's delinquency ladder, month by month.

    What the Risk Case is raised from and what its drawer draws. Percentages
    are of the card accounts open at each month-end, so a month in which the
    book grew does not read as a month in which arrears fell.
    """
    at = month or latest_month()
    window = trend_months(at, count)
    rows: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {}
    for one in window:
        frame = cards(one, ["dpd"])
        total = len(frame)
        if not total:
            continue
        dpd = frame["dpd"]
        row: dict[str, Any] = {"Month": one}
        counts[one] = {"Accounts": total}
        for label, lo, hi in BUCKETS:
            n = int(_in(dpd, lo, hi).sum())
            row[label] = _pct(n, total)
            counts[one][label] = n
        rows.append(row)

    return {
        "rows": rows,
        "counts": counts,
        "months": window,
        "latest": at,
        "previous": previous_month(at),
        "series": [label for label, _, _ in BUCKETS],
    }


def early_delinquency(month: str = "") -> dict[str, Any]:
    """The 1-29 DPD movement the Risk Case is about, with its arithmetic.

    Three comparisons, because the honest answer needs all three: against last
    month, against the recent baseline (the months before this began), and what
    happened to the current population at the same time. A migration that is
    not matched by a fall in 0 DPD is a book that grew, not a book that moved,
    and the difference is the whole claim.
    """
    at = month or latest_month()
    trend = bucket_trend(at)
    rows, counts = trend["rows"], trend["counts"]
    if not rows:
        return {"available": False, "period": at}

    now_row = rows[-1]
    before_row = rows[-2] if len(rows) > 1 else now_row
    prior = str(before_row["Month"])

    # The recent baseline is every month shown BEFORE the latest one, which is
    # what "this had been running at" means to a reader looking at the chart.
    history = [float(r["1-29 DPD"]) for r in rows[:-1]]
    baseline = round(sum(history) / len(history), 2) if history else 0.0
    focus_history = []
    for one in trend["months"][:-1]:
        frame = cards(one, ["dpd"])
        if len(frame):
            focus_history.append(
                _pct(int(_in(frame["dpd"], FOCUS_LO, FOCUS_HI).sum()), len(frame)))
    focus_baseline = (round(sum(focus_history) / len(focus_history), 2)
                      if focus_history else 0.0)

    now_frame = cards(at, ["dpd", "gross_carrying_amount_sar"])
    focus_now = _pct(int(_in(now_frame["dpd"], FOCUS_LO, FOCUS_HI).sum()),
                     len(now_frame)) if len(now_frame) else 0.0
    # What the accounts one cycle behind are carrying. The severity arithmetic
    # weighs a movement by what it touches, and a percentage of a book says
    # nothing about that on its own.
    behind = now_frame[_in(now_frame["dpd"], 1, 29)]
    exposure = round(float(behind["gross_carrying_amount_sar"].fillna(0).sum()) / 1e6, 2)

    early = Movement(
        label="1-29 DPD", unit="% of card accounts",
        now=float(now_row["1-29 DPD"]), before=float(before_row["1-29 DPD"]),
        now_count=counts[at]["1-29 DPD"], before_count=counts[prior]["1-29 DPD"],
        now_period=at, before_period=prior)
    current = Movement(
        label="0 DPD", unit="% of card accounts",
        now=float(now_row["0 DPD"]), before=float(before_row["0 DPD"]),
        now_count=counts[at]["0 DPD"], before_count=counts[prior]["0 DPD"],
        now_period=at, before_period=prior)
    later = [
        Movement(label=label, unit="% of card accounts",
                 now=float(now_row[label]), before=float(before_row[label]),
                 now_count=counts[at][label], before_count=counts[prior][label],
                 now_period=at, before_period=prior)
        for label, _, _ in BUCKETS if label not in ("0 DPD", "1-29 DPD")
    ]

    return {
        "available": True,
        "period": at,
        "previous_period": prior,
        "accounts": counts[at]["Accounts"],
        "previous_accounts": counts[prior]["Accounts"],
        "early": early,
        "current": current,
        "later": later,
        "baseline": baseline,
        "baseline_months": trend["months"][:-1],
        "baseline_multiple": round(early.now / baseline, 2) if baseline else 0.0,
        "focus_now": focus_now,
        "focus_baseline": focus_baseline,
        "focus_baseline_multiple": (round(focus_now / focus_baseline, 2)
                                    if focus_baseline else 0.0),
        "focus_share_of_early": _pct(focus_now, early.now),
        "exposure_sar_mn": exposure,
        "later_worst": max((m.change for m in later), default=0.0),
        "trend": trend,
    }


# --------------------------------------------- question 1: the split

def sub_bucket_trend(month: str = "", count: int = TREND_MONTHS) -> dict[str, Any]:
    """1-29 DPD split into 1-9, 10-19 and 20-29, month by month."""
    at = month or latest_month()
    window = trend_months(at, count)
    rows: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {}
    for one in window:
        frame = cards(one, ["dpd"])
        total = len(frame)
        if not total:
            continue
        row: dict[str, Any] = {"Month": one}
        counts[one] = {"Accounts": total}
        for label, lo, hi in SUB_BUCKETS:
            n = int(_in(frame["dpd"], lo, hi).sum())
            row[label] = _pct(n, total)
            counts[one][label] = n
        rows.append(row)
    if not rows:
        return {"available": False, "period": at}

    now_row, before_row = rows[-1], (rows[-2] if len(rows) > 1 else rows[-1])
    prior = str(before_row["Month"])
    moves = []
    for label, _, _ in SUB_BUCKETS:
        history = [float(r[label]) for r in rows[:-1]]
        baseline = round(sum(history) / len(history), 2) if history else 0.0
        move = Movement(
            label=label, unit="% of card accounts",
            now=float(now_row[label]), before=float(before_row[label]),
            now_count=counts[at][label], before_count=counts[prior][label],
            now_period=at, before_period=prior)
        moves.append({"move": move, "baseline": baseline,
                      "baseline_multiple": (round(move.now / baseline, 2)
                                            if baseline else 0.0)})
    early_now = sum(float(now_row[label]) for label, _, _ in SUB_BUCKETS)
    focus = next(m for m in moves if m["move"].label == FOCUS)
    return {
        "available": True, "period": at, "previous_period": prior,
        "rows": rows, "counts": counts, "months": window,
        "series": [label for label, _, _ in SUB_BUCKETS],
        "moves": moves, "focus": focus,
        "early_now": round(early_now, 2),
        "focus_share_of_early": _pct(focus["move"].now, early_now),
        "accounts": counts[at]["Accounts"],
    }


def cohort(month: str = "", *, columns: Sequence[str] = ()) -> Any:
    """The card accounts at 20-29 DPD at a month-end. The thread's population."""
    at = month or latest_month()
    frame = cards(at, ["dpd", *columns])
    if frame.empty:
        return frame
    return frame[_in(frame["dpd"], FOCUS_LO, FOCUS_HI)]


# ------------------------------- question 2: the cohort's behavioural scores

def behaviour_distribution(month: str = "", against: str = "") -> dict[str, Any]:
    """Where the 20-29 DPD cohort's behavioural scores sit, now and before.

    THE SAME ACCOUNTS, not the same band. The cohort is fixed at the latest
    month and then looked up in the earlier one, so the migration on screen is
    these customers' scores moving rather than a different set of customers
    being compared with them. A distribution of "whoever was at 20-29 last
    month" against "whoever is at 20-29 now" is two populations, and any
    difference between them could be either a change in behaviour or a change
    in who is in the group.

    The comparison month is the BASELINE — the last month before the
    deterioration began — not the immediately preceding one, which is already
    inside it. `against` overrides that where a caller has a reason to.
    """
    at = month or latest_month()
    base = against or baseline_month(at)
    want = ["facility_id", "behavioural_score", "behavioural_score_band"]
    now = cohort(at, columns=want)
    if now.empty:
        return {"available": False, "period": at}

    earlier = cards(base, want)
    traced = now.merge(earlier[want], on="facility_id", suffixes=("", "_before"))

    def spread(frame: Any, column: str) -> tuple[list[dict[str, Any]], float]:
        total = len(frame)
        bands = frame[column].fillna("(not scored)")
        out = []
        for band in BAND_ORDER:
            n = int((bands == band).sum())
            out.append({"band": band, "label": BAND_WORDS.get(band, band),
                        "count": n, "share": _pct(n, total)})
        missing = int((bands == "(not scored)").sum())
        if missing:
            out.append({"band": "(not scored)", "label": "Not scored",
                        "count": missing, "share": _pct(missing, total)})
        weak = sum(o["share"] for o in out if o["band"] in WEAK_BANDS)
        return out, round(weak, 2)

    now_bands, weak_now = spread(traced, "behavioural_score_band")
    before_bands, weak_before = spread(traced, "behavioural_score_band_before")

    rows = []
    for band in BAND_ORDER:
        b = next(o for o in before_bands if o["band"] == band)
        n = next(o for o in now_bands if o["band"] == band)
        rows.append({
            "Behavioural band": f"{BAND_WORDS.get(band, band)} ({band})",
            base: b["share"], at: n["share"],
            "Change (pp)": round(n["share"] - b["share"], 2),
        })

    score_now = float(traced["behavioural_score"].mean())
    score_before = float(traced["behavioural_score_before"].mean())
    return {
        "available": True,
        "period": at,
        "baseline": base,
        "cohort": len(now),
        "traced": len(traced),
        "rows": rows,
        "now": now_bands,
        "before": before_bands,
        "weak_now": weak_now,
        "weak_before": weak_before,
        "weak_change": round(weak_now - weak_before, 2),
        "score": Movement(label="Average behavioural score", unit="points",
                          now=round(score_now, 1), before=round(score_before, 1),
                          now_count=len(traced), before_count=len(traced),
                          now_period=at, before_period=base),
    }


# --------------------------- question 3: what moved the behavioural score

def _feature_columns() -> list[tuple[str, str, str]]:
    """Every behavioural feature, as (short name, points column, business name)."""
    from backend.retail.models_registry import BEH_FEATURES

    return [(short, f"beh_{short}_points", f.business_name)
            for short, f in BEH_FEATURES.items()]


def score_decomposition(month: str = "", against: str = "") -> dict[str, Any]:
    """Which behavioural-model variables moved the cohort's score, and by how much.

    This is arithmetic on the scorecard, not an attribution model. The
    behavioural score is `base points + the sum of one points contribution per
    variable`, every one of which is published on the row. So the change in the
    score between two dates is the sum of the changes in those contributions,
    exactly, and each variable's share of the deterioration is its own change
    over the total of the negative ones. Nothing is estimated and nothing is
    allocated: the columns add up, and the answer says so.

    The split that matters is delinquency information against everything else,
    because the challenge this answers is "the score is only worse because they
    are already late". `DELINQUENCY_VARIABLES` draws that line, and it is drawn
    generously — a variable that carries ANY arrears information is counted on
    the delinquency side, so the non-delinquency share is understated rather
    than flattered.

    It also reports the deterioration that was already on the book BEFORE the
    cohort missed anything, which is the part of the answer that settles the
    challenge rather than arguing with it.
    """
    at = month or latest_month()
    base = against or baseline_month(at)
    features = _feature_columns()
    want = ["facility_id", "behavioural_score",
            "beh_score_base_points", *[c for _, c, _ in features]]

    now = cohort(at, columns=want)
    if now.empty:
        return {"available": False, "period": at}
    earlier = cards(base, want)
    traced = now.merge(earlier, on="facility_id", suffixes=("", "_before"))
    # Only accounts SCORED at both dates. An account with too little history to
    # be scored at one end has no score change to decompose, and leaving it in
    # silently broke the arithmetic this answer's whole claim rests on: the
    # per-variable averages were taken over every traced row while the score
    # change was taken over the scored ones, so the contributions summed to
    # five points less than the movement they were supposed to explain. Two
    # populations, one subtraction. The accounts dropped here are counted and
    # reported rather than absorbed.
    scored = traced[traced["behavioural_score"].notna()
                    & traced["behavioural_score_before"].notna()]
    unscored = len(traced) - len(scored)
    traced = scored
    if traced.empty:
        return {"available": False, "period": at}

    moved: list[dict[str, Any]] = []
    for short, column, name in features:
        if column not in traced or f"{column}_before" not in traced:
            continue
        change = float((traced[column].fillna(0)
                        - traced[f"{column}_before"].fillna(0)).mean())
        if abs(change) < 0.05:
            continue
        moved.append({
            "variable": short, "name": name, "points": round(change, 2),
            "delinquency": short in DELINQUENCY_VARIABLES,
            "kind": ("Drawing on the limit" if short in DRAWING_VARIABLES else
                     "Repayment behaviour" if short in REPAYMENT_VARIABLES else
                     "Delinquency" if short in DELINQUENCY_VARIABLES else "Other"),
        })
    moved.sort(key=lambda m: m["points"])

    worse = sum(m["points"] for m in moved if m["points"] < 0) or -1.0
    for m in moved:
        m["share"] = round(m["points"] / worse * 100, 1) if m["points"] < 0 else 0.0

    def share_of(keys: Iterable[str]) -> float:
        wanted = set(keys)
        return round(sum(m["points"] for m in moved
                         if m["points"] < 0 and m["variable"] in wanted)
                     / worse * 100, 1)

    non_delinquency = round(sum(m["points"] for m in moved if m["points"] < 0
                                and not m["delinquency"]) / worse * 100, 1)

    # What had already happened before a payment was missed. The cohort was
    # current at the baseline and current at the month before the arrears, so
    # every point of THIS move is behaviour rather than delinquency.
    ahead = ""
    before_arrears: dict[str, Any] = {}
    prior = previous_month(at)
    if prior and prior != base:
        earlier_prior = cards(prior, want)
        pair = now[["facility_id"]].merge(
            earlier[want], on="facility_id").merge(
            earlier_prior[want], on="facility_id", suffixes=("_base", "_prior"))
        if not pair.empty:
            ahead = prior
            fell = float((pair["behavioural_score_prior"]
                          - pair["behavioural_score_base"]).mean())
            total_fell = float((traced["behavioural_score"]
                                - traced["behavioural_score_before"]).mean())
            before_arrears = {
                "from": base, "to": prior,
                "points": round(fell, 1),
                "share_of_total": (round(fell / total_fell * 100, 1)
                                   if total_fell else 0.0),
                "accounts": len(pair),
            }

    rows = [{"Behavioural variable": m["name"],
             "Points change": m["points"],
             "Share of deterioration (%)": m["share"],
             "Type": m["kind"]}
            for m in moved if m["points"] < 0]

    # What the listed variables do NOT account for. It should be the handful of
    # contributions too small to list, and it is reported rather than assumed:
    # a decomposition that silently absorbs its own residual is a decomposition
    # nobody can check.
    change = float((traced["behavioural_score"]
                    - traced["behavioural_score_before"]).mean())
    residual = round(change - sum(m["points"] for m in moved), 2)

    return {
        "available": True,
        "period": at,
        "baseline": base,
        "residual": residual,
        "unscored": unscored,
        "before_arrears_month": ahead,
        "before_arrears": before_arrears,
        "cohort": len(now),
        "traced": len(traced),
        "variables": moved,
        "rows": rows,
        "score": Movement(
            label="Average behavioural score", unit="points",
            now=round(float(traced["behavioural_score"].mean()), 1),
            before=round(float(traced["behavioural_score_before"].mean()), 1),
            now_count=len(traced), before_count=len(traced),
            now_period=at, before_period=base),
        "non_delinquency_share": non_delinquency,
        "drawing_share": share_of(DRAWING_VARIABLES),
        "repayment_share": share_of(REPAYMENT_VARIABLES),
        "two_signal_share": share_of(DRAWING_VARIABLES | REPAYMENT_VARIABLES),
        "metrics": behaviour_metrics(at, base),
    }


def behaviour_metrics(month: str = "", against: str = "") -> list[Movement]:
    """The cohort's drawing and repayment, in the units a reader argues in.

    The decomposition is in scorecard points, which is the right unit for
    "what moved the score" and the wrong one for "is this cohort in trouble".
    These are the same movement in percentages and ratios.
    """
    at = month or latest_month()
    base = against or baseline_month(at)
    want = ["facility_id", "utilisation_ratio", "payment_to_due_ratio_3m",
            "minimum_payment_only_months_3m", "missed_payment_count_3m",
            "cash_advance_share_3m", "overlimit_days_3m",
            "current_credit_limit_sar", "outstanding_principal_sar"]
    now = cohort(at, columns=want)
    if now.empty:
        return []
    earlier = cards(base, want)
    t = now.merge(earlier, on="facility_id", suffixes=("", "_b"))
    if t.empty:
        return []
    n = len(t)

    def mean(column: str, scale: float = 1.0) -> float:
        return round(float(t[column].fillna(0).mean()) * scale, 2)

    # "Months in the last three without a real repayment" is minimum-only
    # months plus missed months. Counting only minimum-only months understates
    # a cohort that has stopped paying altogether: a missed cycle is not a
    # month in which they repaid a healthy share, and leaving it out would let
    # the measure IMPROVE as the cohort got worse.
    def stalled(suffix: str = "") -> float:
        months_stalled = (t[f"minimum_payment_only_months_3m{suffix}"].fillna(0)
                          + t[f"missed_payment_count_3m{suffix}"].fillna(0))
        return round(float((months_stalled >= 2).mean()) * 100, 2)

    return [
        Movement(label="Average card utilisation", unit="%",
                 now=mean("utilisation_ratio", 100), before=mean("utilisation_ratio_b", 100),
                 now_count=n, before_count=n, now_period=at, before_period=base),
        Movement(label="Payments received against amounts due, 3 months", unit="x",
                 now=mean("payment_to_due_ratio_3m"), before=mean("payment_to_due_ratio_3m_b"),
                 now_count=n, before_count=n, now_period=at, before_period=base),
        Movement(label="At least two of the last three months at the minimum or missed",
                 unit="% of cohort", now=stalled(), before=stalled("_b"),
                 now_count=n, before_count=n, now_period=at, before_period=base),
        Movement(label="Cash advances as a share of card spend, 3 months", unit="%",
                 now=mean("cash_advance_share_3m", 100), before=mean("cash_advance_share_3m_b", 100),
                 now_count=n, before_count=n, now_period=at, before_period=base),
        Movement(label="Days over the credit limit, 3 months", unit="days",
                 now=mean("overlimit_days_3m"), before=mean("overlimit_days_3m_b"),
                 now_count=n, before_count=n, now_period=at, before_period=base),
    ]


# -------------------------------- question 4: where the stress is concentrated

def _new_cases(frame: Any) -> Any:
    """The accounts that entered 20-29 DPD this month from being current.

    A concentration measured on the whole 20-29 population mixes this month's
    entrants with accounts that were already there, and the question is about
    what just happened. `previous_month_dpd` is on the row, so this is a
    reading rather than an inference.
    """
    return frame[(frame["previous_month_dpd"].fillna(0) == 0)]


def concentration(month: str = "") -> dict[str, Any]:
    """Which card programme and which origination band the new cases came from.

    Two cuts, and both are stated as EXPOSURE SHARE against PROBLEM SHARE,
    because a programme that holds a quarter of the book and produces a quarter
    of the cases is not a concentration however large its case count looks. The
    finding is the gap between the two shares, so both are on screen.
    """
    from backend.retail import taxonomy as tax
    from backend.retail.policy import CARD_PROGRAMME_POLICY as policy

    at = month or latest_month()
    want = ["facility_id", "dpd", "previous_month_dpd", "product_subsegment",
            "origination_score_band", "application_score_at_origination",
            "utilisation_ratio", "payment_to_due_ratio_3m",
            "current_credit_limit_sar", "gross_carrying_amount_sar"]
    book = cards(at, want)
    if book.empty:
        return {"available": False, "period": at}

    focus = book[_in(book["dpd"], FOCUS_LO, FOCUS_HI)]
    fresh = _new_cases(focus)
    total, new_total = len(book), len(fresh)
    if not new_total:
        return {"available": False, "period": at}

    programmes: list[dict[str, Any]] = []
    for code in tax.CARD_PROGRAMMES:
        held = int((book["product_subsegment"] == code).sum())
        if not held:
            continue
        raised = int((fresh["product_subsegment"] == code).sum())
        programmes.append({
            "programme": code,
            "label": tax.CARD_PROGRAMME_LABELS.get(code, code),
            "accounts": held,
            "exposure_share": _pct(held, total),
            "new_cases": raised,
            "problem_share": _pct(raised, new_total),
            "rate": _pct(raised, held),
        })
    programmes.sort(key=lambda p: p["problem_share"], reverse=True)
    lead = programmes[0] if programmes else {}

    expansion = policy.expansion_programme
    inside = book[book["product_subsegment"] == expansion]
    inside_new = fresh[fresh["product_subsegment"] == expansion]
    bands: list[dict[str, Any]] = []
    for band in tax.ORIGINATION_SCORE_BANDS:
        held = int((inside["origination_score_band"] == band).sum())
        if not held:
            continue
        raised = int((inside_new["origination_score_band"] == band).sum())
        slice_ = inside[inside["origination_score_band"] == band]
        bands.append({
            "band": band,
            "accounts": held,
            "share_of_programme": _pct(held, len(inside)),
            "new_cases": raised,
            "share_of_programme_cases": _pct(raised, len(inside_new)),
            "rate": _pct(raised, held),
            "utilisation": round(float(slice_["utilisation_ratio"].fillna(0).mean()) * 100, 1),
            "payment_to_due": round(float(slice_["payment_to_due_ratio_3m"].fillna(0).mean()), 2),
            "limit": round(float(slice_["current_credit_limit_sar"].fillna(0).median()), 0),
            "exposure": round(float(slice_["gross_carrying_amount_sar"].fillna(0).sum()), 0),
        })

    opened = [b for b in bands if b["band"] in OPENED_BANDS]
    opened_accounts = sum(b["accounts"] for b in opened)
    opened_cases = sum(b["new_cases"] for b in opened)
    ranked = [b for b in bands if b["accounts"] >= 20]
    steepest = (round(ranked[0]["rate"] / ranked[-1]["rate"], 1)
                if len(ranked) > 1 and ranked[-1]["rate"] else 0.0)

    return {
        "available": True,
        "period": at,
        "accounts": total,
        "new_cases": new_total,
        "programmes": programmes,
        "lead": lead,
        "expansion": expansion,
        "expansion_label": policy.expansion_label,
        "expansion_context": policy.expansion_context,
        "established_floor": policy.established_floor,
        "expansion_floor": policy.expansion_floor,
        "expansion_opened": policy.expansion_opened,
        "policy_version": policy.version,
        "bands": bands,
        "band_rows": [{"Origination score band": b["band"],
                       "Accounts": b["accounts"],
                       "Share of Alpha Card (%)": b["share_of_programme"],
                       "New 20-29 DPD cases": b["new_cases"],
                       "Share of its new cases (%)": b["share_of_programme_cases"],
                       "Entered 20-29 DPD (%)": b["rate"],
                       "Average utilisation (%)": b["utilisation"]}
                      for b in bands],
        "opened_accounts": opened_accounts,
        "opened_share": _pct(opened_accounts, len(inside)),
        "opened_cases": opened_cases,
        "opened_case_share": _pct(opened_cases, len(inside_new)),
        "gradient": steepest,
    }


# ------------------------------------------- question 5: what to do about it

#: How far a band's limit is proposed to come down, against how much worse its
#: observed entry rate is than the reference band's. A published, auditable
#: rule rather than a set of chosen percentages: the reduction is the band's
#: excess risk, damped and capped, so a reader can check every row against the
#: column beside it.
#:
#: Damped because a band running at eight times the reference's rate is not a
#: case for cutting its limits eightfold — limit is exposure at default, not
#: probability of it, and the two do not move together. Capped because a
#: recommendation with no ceiling is a recommendation nobody will take to a
#: credit committee.
REDUCTION_DAMPING = 0.038
REDUCTION_CAP = 0.25
#: Bands at or above this are the reference: normal policy unless the account
#: itself deteriorates.
REFERENCE_BAND = "620-649"
#: The bands the expansion opened — the ones below the established floor. Named
#: rather than compared as text, because "600-619" < "620-649" is true of these
#: particular strings and not of banding in general.
OPENED_BANDS: tuple[str, ...] = ("580-589", "590-599", "600-619")


def actions(month: str = "") -> dict[str, Any]:
    """What to do, band by band, and the arithmetic behind each row.

    The recommendation is NOT a table of percentages somebody chose. Each
    band's proposed reduction is computed from how much worse its own observed
    entry rate is than the reference band's, damped and capped, and the inputs
    are printed beside the output so the row can be checked.

    It also distinguishes the existing book from the new book, because they are
    different decisions with different constraints. A limit on an account
    somebody already holds is contractual and cannot be reduced by an analysis;
    what CAN be done to it is monitoring, pausing increases and contacting the
    customer. A starting limit on an account not yet written is a policy
    parameter, and that is where a reduction belongs.
    """
    at = month or latest_month()
    found = concentration(at)
    if not found.get("available"):
        return {"available": False, "period": at}

    bands = [b for b in found["bands"] if b["accounts"] >= 20]
    reference = next((b for b in bands if b["band"] == REFERENCE_BAND), None)
    if reference is None or not reference["rate"]:
        reference = min(bands, key=lambda b: b["rate"]) if bands else None
    if reference is None:
        return {"available": False, "period": at}
    ref_rate = reference["rate"] or 1.0

    rows: list[dict[str, Any]] = []
    for band in bands:
        excess = round(band["rate"] / ref_rate, 2)
        if band["band"] not in OPENED_BANDS or excess <= 1.2:
            cut = 0.0
        else:
            cut = min((excess - 1.0) * REDUCTION_DAMPING, REDUCTION_CAP)
        current = float(band["limit"] or 0.0)
        # Rounded to the nearest 500 SAR, because a starting limit is set in
        # round money and "SAR 16,847" is an arithmetic result rather than a
        # policy anybody would publish.
        proposed = round(current * (1.0 - cut) / 500.0) * 500.0 if cut else current
        heavy = cut >= 0.20
        rows.append({
            "band": band["band"],
            "accounts": band["accounts"],
            "rate": band["rate"],
            "excess": excess,
            "utilisation": band["utilisation"],
            "current_limit": current,
            "proposed_limit": proposed,
            "reduction": round(cut * 100, 1),
            "monitoring": ("Highest intensity, monthly" if heavy else
                           "Enhanced monthly watchlist" if cut else
                           "Standard monitoring"),
            "limit_policy": (
                "No increases; tighten the starting limit on new business"
                if heavy else
                "Pause automatic increases until performance is clean"
                if cut else
                "Normal policy unless the account itself deteriorates"),
            "customer_action": (
                "Proactive contact and an affordability conversation; "
                "review eligibility for new business in this band"
                if heavy else
                "Early contact where utilisation is above 80% or repayment weakens"
                if cut else
                "No blanket intervention"),
        })

    exposure = sum(b["exposure"] for b in found["bands"]
                   if b["band"] in OPENED_BANDS)
    return {
        "available": True,
        "period": at,
        "reference": reference["band"],
        "reference_rate": reference["rate"],
        "rows": rows,
        "table": [{"Origination score band": r["band"],
                   "Accounts": r["accounts"],
                   "Entered 20-29 DPD (%)": r["rate"],
                   "Against the reference band (x)": r["excess"],
                   "Typical limit today (SAR)": r["current_limit"],
                   "Recommended new-business limit (SAR)": r["proposed_limit"],
                   "Reduction (%)": r["reduction"],
                   "Monitoring": r["monitoring"],
                   "Limit policy": r["limit_policy"],
                   "Customer action": r["customer_action"]}
                  for r in rows],
        "expansion_label": found["expansion_label"],
        "opened_exposure": exposure,
        "damping": REDUCTION_DAMPING,
        "cap": round(REDUCTION_CAP * 100, 1),
    }

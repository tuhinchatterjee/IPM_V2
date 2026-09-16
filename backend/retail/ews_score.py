"""
The Retail Early Warning Score: derived, persisted, and served.

What this is
------------
One governed domain — `retail_ews_score` — holding TWENTY monthly snapshots at
**customer-facility-month** grain, derived from the canonical retail book and
the model configured in `backend.retail.ews_model`. Every number the Early
Warning workspace shows comes from here. Nothing is computed in the browser and
nothing is hard-coded in a screen.

Why it is persisted rather than computed on demand
--------------------------------------------------
Scoring thirty-four triggers with six action dimensions each, over twenty
months of a twenty-thousand-facility book, takes minutes. A page load cannot
wait for it and a presenter must never be asked to press "fit". So it is built
once — at bootstrap, or by hand after the book is regenerated — and the API
reads parquet.

The shape of a month
--------------------
    reporting_month, customer_id, facility_id            the key
    + identity and hierarchy, including sub_product
    + exposure and facility structure
    + credit status, including default_entry_this_month
    + the existing scores
    + the bureau classifier block, on DATED observations only
    + affordability and cash flow
    + one column per trigger: fired, value, comparator
    + six action-dimension columns per fired trigger
    + nineteen sublayer scores
    + four layer scores
    + the overall score, its severity, the flags and the reason codes

A customer-grain measure repeated across a customer's facilities is named so
in the dictionary, and every aggregate here counts customers with `nunique`
rather than summing rows.

ODR
---
`observed default rate` is a PORTFOLIO measure and is never stored against a
customer. What is stored is `default_entry_this_month` and
`eligible_for_default_this_month`; the rate is computed where a denominator
exists — product, sub-product, book — and nowhere else.

Everything here is SYNTHETIC demonstration data and a synthetic demonstration
model. Not an ANB model, not an ANB policy, not a SAMA requirement, not
independently validated.
"""

from __future__ import annotations

import glob
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.retail import ews_model as M

logger = logging.getLogger(__name__)

#: The governed domain this module writes and every screen reads.
DOMAIN = "retail_ews_score"
DOMAIN_NAME = "Early Warning Score"
BOOK = "retail_facility_month"

#: Bumped when the persisted shape changes.
EWS_PANEL_VERSION = "3.0.0"

#: §23: exactly twenty monthly snapshots, ending at the latest published month.
MONTHS_KEPT = 20

#: How many months of history the screens plot.
TREND_MONTHS = 6

CURRENT_BAD_RULE = (
    "Thirty or more days past due on any facility, or flagged in default, or "
    "in IFRS 9 Stage 3 at this month-end.")

FORWARD_RISK_RULE = (
    "Not currently bad, and an Early Warning Score in the HIGH or CRITICAL "
    "band. A prediction about a customer who is still paying.")

#: §21's stricter cohort, and the reason it exists beside the wider one.
#:
#: "Not currently bad" means under thirty days. That includes everybody
#: sitting in one to twenty-nine, which is a population collections is
#: already working — so a forward-risk list built on it spends most of its
#: length on customers somebody has already phoned. The presenter's question
#: is the other one: who is completely up to date, has tripped no hard
#: trigger, and is deteriorating anyway. That is the population a decision is
#: still available for, and it needs its own filter rather than a note asking
#: the reader to ignore some rows.
CLEAN_RULE = (
    "Zero days past due on every facility, not flagged in default, not in "
    "IFRS 9 Stage 3, and no hard trigger applied. Completely up to date — "
    "not merely under thirty days.")

CLEAN_FORWARD_RISK_RULE = (
    CLEAN_RULE + " With an Early Warning Score in the HIGH or CRITICAL "
    "band: elevated forward risk on a customer who owes nothing yet. For "
    "the latest month this says needs review, not will default.")

ODR_DEFINITION = (
    "Facilities entering default during the month, over facilities that were "
    "not in default at the start of it. A portfolio measure; it is never a "
    "property of one customer.")

SYNTHETIC_NAME_NOTE = (
    "Synthetic display name, generated deterministically from the customer "
    "id. Not a real person and not an ANB customer.")


# --------------------------------------------------------------- the names

#: Deterministic synthetic display names.
#:
#: The published book carries no `customer_name`, and the specification asks
#: for one on every card. Rather than leave the field blank or invent one at
#: render time — which would give the same customer a different name on two
#: screens — a stable name is derived from the customer id and labelled
#: synthetic wherever it appears.
_GIVEN = (
    "Abdullah", "Mohammed", "Fahad", "Khalid", "Sultan", "Faisal", "Saud",
    "Nasser", "Turki", "Bandar", "Majed", "Yousef", "Omar", "Ibrahim",
    "Salman", "Rayan", "Ziyad", "Hatim", "Waleed", "Anas",
    "Noura", "Sara", "Maha", "Lulwa", "Reem", "Hessa", "Amal", "Dana",
    "Latifa", "Jawaher", "Munira", "Shaikha", "Aisha", "Fatima", "Haya",
    "Ruba", "Shahad", "Ghada", "Nada", "Wijdan",
)
_FAMILY = (
    "Al-Qahtani", "Al-Ghamdi", "Al-Otaibi", "Al-Shehri", "Al-Harbi",
    "Al-Zahrani", "Al-Dosari", "Al-Mutairi", "Al-Anzi", "Al-Subaie",
    "Al-Juhani", "Al-Amri", "Al-Balawi", "Al-Rashidi", "Al-Shammari",
    "Al-Maliki", "Al-Yami", "Al-Asiri", "Al-Khaldi", "Al-Sulami",
    "Al-Faraj", "Al-Nasser", "Al-Sudairi", "Al-Rajhi", "Al-Turki",
)


def display_name(customer_id: str) -> str:
    """A stable synthetic name for one customer id."""
    digest = hashlib.sha256(str(customer_id).encode()).digest()
    given = _GIVEN[digest[0] % len(_GIVEN)]
    family = _FAMILY[digest[1] % len(_FAMILY)]
    return f"{given} {family}"


# ------------------------------------------------------- reading the lake

def _root(analytics_dir: str | Path | None = None) -> Path:
    from backend.config import settings

    return Path(analytics_dir or settings.analytics_dir)


def _months_of(dataset: str, analytics_dir: str | Path | None = None
               ) -> list[str]:
    root = _root(analytics_dir) / dataset
    if not root.exists():
        return []
    return sorted(p.name.split("=", 1)[1] for p in root.iterdir()
                  if p.is_dir() and p.name.startswith("reporting_month="))


def book_months(analytics_dir: str | Path | None = None) -> list[str]:
    return _months_of(BOOK, analytics_dir)


def panel_months(analytics_dir: str | Path | None = None) -> list[str]:
    return _months_of(DOMAIN, analytics_dir)


def scored_months(analytics_dir: str | Path | None = None) -> list[str]:
    """The twenty months the domain is meant to hold, from the book."""
    every = book_months(analytics_dir)
    return every[-MONTHS_KEPT:] if len(every) >= MONTHS_KEPT else every


_CACHE: dict[str, Any] = {}
_BOOK_CACHE: dict[str, Any] = {}


def _read_book(month: str, analytics_dir: str | Path | None = None) -> Any:
    """One month of the canonical book, held the way the panel is held.

    This was the only uncached reader of the four, and it costs 1.20 seconds
    for 59,449 rows over 546 columns. A single workbook download read it three
    times — once inside the scenario run, once for the facility detail, once
    for the customer roll-up — so three and a half seconds of a fifteen-second
    download were the same parquet files being parsed again.

    Returned as the SAME frame rather than a copy, exactly as `read` does: the
    callers narrow and filter, which produces new frames, and none of them
    mutates what they are given.
    """
    import pandas as pd

    key = f"{month}|{analytics_dir or ''}"
    held = _BOOK_CACHE.get(key)
    if held is not None:
        return held
    parts = sorted(glob.glob(str(
        _root(analytics_dir) / BOOK / f"reporting_month={month}" / "*.parquet")))
    if not parts:
        raise FileNotFoundError(f"the retail book has no {month}")
    frame = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    # The book is wider than the panel — 546 columns against 498 — so fewer
    # months are held before the cache is cleared.
    if len(_BOOK_CACHE) > 8:
        _BOOK_CACHE.clear()
    _BOOK_CACHE[key] = frame
    return frame


def read(month: str, analytics_dir: str | Path | None = None) -> Any:
    """One month of the EWS domain."""
    import pandas as pd

    key = f"{month}|{analytics_dir or ''}"
    if key in _CACHE:
        return _CACHE[key]
    parts = sorted(glob.glob(str(
        _root(analytics_dir) / DOMAIN / f"reporting_month={month}"
        / "*.parquet")))
    if not parts:
        # Truncated, and deliberately. Called with the wrong kind of argument —
        # a selection object rather than its month — this interpolated six
        # thousand customer ids into the message and produced a hundred and
        # eighty kilobytes of traceback, which tells a reader nothing about
        # what went wrong.
        said = str(month)
        raise FileNotFoundError(
            "the Early Warning Score domain has no "
            + (said if len(said) <= 80 else said[:80] + "…"))
    frame = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    if len(_CACHE) > 26:
        _CACHE.clear()
    _CACHE[key] = frame
    return frame


def forget() -> None:
    """Drop the read cache. Called after a rebuild, and by the tests.

    The serving layer memoises series computed over these frames, so that goes
    with them: a rebuilt panel with a stale six-month trend beside it would be
    worse than no cache at all.
    """
    _CACHE.clear()
    _BOOK_CACHE.clear()
    try:
        from backend.retail import ews_views
    except ImportError:  # pragma: no cover - scoring can run without serving
        return
    ews_views._SERIES.clear()
    ews_views._ANSWERS.clear()
    try:
        from backend.retail import ews_registry
    except ImportError:  # pragma: no cover
        return
    ews_registry.forget()


def window(at: str, back: int = TREND_MONTHS,
           analytics_dir: str | Path | None = None) -> list[str]:
    every = panel_months(analytics_dir)
    if at not in every:
        return every[-back:]
    end = every.index(at) + 1
    return every[max(0, end - back):end]


# ------------------------------------------------------- the sub-products

def sub_product_of(frame: Any) -> Any:
    """The governed sub-product for every row, derived from the book.

    Deterministic: the same facility lands in the same sub-product on every
    rebuild, because the derivation reads only published columns. The rule for
    each code is written beside its label in `ews_model.SUB_PRODUCTS` and is
    shown on the model screen.
    """
    import numpy as np
    import pandas as pd

    product = frame["product_code"].astype(str)
    segment = frame.get("customer_segment")
    segment = (segment.astype(str) if segment is not None
               else pd.Series("MASS", index=frame.index))
    limit = pd.to_numeric(frame.get("current_credit_limit_sar"),
                          errors="coerce").fillna(0.0)
    subsegment = frame.get("product_subsegment")
    subsegment = (subsegment.astype(str) if subsegment is not None
                  else pd.Series("", index=frame.index))

    out = pd.Series("", index=frame.index, dtype="object")

    card = product == "CREDIT_CARD"
    top = segment.isin(("PRIVATE", "AFFLUENT"))
    out[card] = "CC_CLASSIC"
    out[card & (segment == "MASS_AFFLUENT")] = "CC_PLATINUM"
    out[card & (segment == "MASS") & (limit >= 25_000)] = "CC_PLATINUM"
    out[card & top] = "CC_SIGNATURE"
    out[card & (segment == "MASS_AFFLUENT") & (limit >= 50_000)] = "CC_SIGNATURE"
    out[card & top & (limit >= 60_000)] = "CC_INFINITE"

    personal = product == "PERSONAL_LOAN"
    out[personal] = "PF_STANDARD"
    out[personal & (subsegment == "TOP_UP")] = "PF_TOPUP"
    out[personal & (subsegment == "REFINANCE_BUYOUT")] = "PF_BUYOUT"

    auto = product == "AUTO_LOAN"
    out[auto] = "AL_STANDARD"
    out[auto & (subsegment == "USED")] = "AL_USED"

    home = product == "HOME_LOAN"
    out[home] = "HL_FIRST"
    out[home & (subsegment == "SECOND_PROPERTY")] = "HL_STANDARD"
    out[home & (subsegment == "REFINANCE")] = "HL_BUYOUT"

    return out.replace("", np.nan).fillna("UNCLASSIFIED")


def classification_of(frame: Any) -> Any:
    """Salaried or Non-Salaried, for every row.

    Read from EMPLOYMENT, which is what the classification means. The book
    also carries `salary_transfer_flag` and that is a different fact — where
    the income lands, not whether it is a salary — so it is reported beside
    this and never used as it.
    """
    import pandas as pd

    status = frame.get("employment_status")
    if status is None:
        return pd.Series("UNCLASSIFIED", index=frame.index, dtype="object")
    return status.astype(str).str.upper().map(
        M.EMPLOYMENT_TO_CLASSIFICATION).fillna("UNCLASSIFIED")


# ------------------------------------------------------ the bureau schedule

def _bureau_observed(frame: Any, month: str) -> Any:
    """Which rows hold a GENUINE bureau observation this month.

    The book stamps a bureau date on every month-end. The model says the bank
    receives a file at origination, on the customer's own re-pull cadence, and
    on entry to thirty days past due — see `ews_model.BUREAU_RULE`. This
    returns the boolean for that rule, and everything downstream carries the
    last observed value forward between the months it marks.
    """
    import numpy as np
    import pandas as pd

    cadences = M.BUREAU_RULE.cadence_months
    # A stable per-customer cadence and phase, hashed from the id so it does
    # not move between builds and does not depend on row order.
    digest = frame["customer_id"].astype(str).map(
        lambda who: hashlib.sha256(who.encode()).digest())
    cadence = digest.map(lambda d: cadences[d[2] % len(cadences)])
    phase = digest.map(lambda d: d[3]) % cadence

    months_on_book = pd.to_numeric(frame.get("months_on_book"),
                                   errors="coerce").fillna(0).astype(int)
    at_origination = months_on_book <= 0
    on_cadence = (months_on_book > 0) & (
        ((months_on_book - phase) % cadence) == 0)

    dpd = pd.to_numeric(frame.get("dpd"), errors="coerce").fillna(0.0)
    previous = pd.to_numeric(frame.get("previous_month_dpd"),
                             errors="coerce").fillna(0.0)
    trigger_dpd = M.BUREAU_RULE.delinquency_pull_at_dpd
    on_delinquency = (dpd >= trigger_dpd) & (previous < trigger_dpd)

    del month, np
    return (at_origination | on_cadence | on_delinquency).to_numpy()


# ------------------------------------------------------------ the triggers

@dataclass
class Fired:
    """One trigger's result for a whole month, column by column."""

    fired: Any
    value: Any
    comparator: Any


def _num(frame: Any, column: str) -> Any:
    import numpy as np
    import pandas as pd

    if column not in frame.columns:
        return np.full(len(frame), np.nan)
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(
        dtype="float64")


def _flag(frame: Any, column: str) -> Any:
    import numpy as np

    if column not in frame.columns:
        return np.zeros(len(frame), dtype=bool)
    return frame[column].fillna(False).astype(bool).to_numpy()


def evaluate(frame: Any, trigger: M.Trigger) -> Fired:
    """One trigger over one month. Never raises on a missing column."""
    import numpy as np

    rows = len(frame)
    blank = Fired(np.zeros(rows, dtype=bool),
                  np.full(rows, np.nan), np.full(rows, np.nan))
    if trigger.absent_because:
        return blank

    products = trigger.products or M.ALL_PRODUCTS
    applies = frame["product_code"].isin(products).to_numpy()

    key, value, comparator = trigger.key, None, None

    if key == "early_life_failure":
        missed = _num(frame, "missed_payment_count_3m")
        on_book = _num(frame, "months_on_book")
        fired = (on_book <= 6) & (missed >= trigger.threshold)
        value, comparator = missed, on_book
    elif key == "delinquency_recurrence":
        worst = _num(frame, "max_dpd_6m")
        now = _num(frame, "dpd")
        fired = (worst >= trigger.threshold) & (now < 30.0)
        value, comparator = worst, now
    elif key == "band_migration":
        now = frame.get("behavioural_score_band")
        was = frame.get("behavioural_score_band_previous")
        if now is None or was is None:
            return blank
        order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5}
        now_rank = now.map(order)
        was_rank = was.map(order)
        fired = (now_rank.notna() & was_rank.notna()
                 & (now_rank > was_rank)).to_numpy()
        value = now_rank.to_numpy(dtype="float64")
        comparator = was_rank.to_numpy(dtype="float64")
    elif key == "forbearance_strain":
        dpd = _num(frame, "dpd")
        forborne = _flag(frame, "forbearance_flag")
        fired = forborne & (dpd >= 30.0)
        value, comparator = dpd, forborne.astype("float64")
    elif key == "consecutive_salary_missing":
        missed = _num(frame, "salary_missed_cycle_count_3m")
        fired = missed >= trigger.threshold
        value, comparator = missed, np.full(rows, trigger.threshold)
    elif key == "balance_build":
        now = _num(frame, "gross_carrying_amount_sar")
        was = _num(frame, "previous_month_gross_carrying_amount_sar")
        with np.errstate(divide="ignore", invalid="ignore"):
            growth = np.where(was > 0, (now - was) / was, np.nan)
        fired = growth >= trigger.threshold
        value, comparator = growth, was
    elif trigger.test == "rise":
        now = _num(frame, trigger.column)
        was = _num(frame, trigger.comparator) if trigger.comparator else None
        if was is None:
            fired = now >= trigger.threshold
            comparator = np.full(rows, trigger.threshold)
        else:
            fired = (now - was) >= trigger.threshold
            comparator = was
        value = now
        if key == "dpd_worsening":
            fired = fired & (now >= 30.0)
    elif trigger.test == "fall":
        now = _num(frame, trigger.column)
        was = _num(frame, trigger.comparator) if trigger.comparator else None
        if was is None:
            fired = now <= trigger.threshold
            comparator = np.full(rows, trigger.threshold)
        else:
            fired = (was - now) >= trigger.threshold
            comparator = was
        value = now
    elif trigger.test in ("below", "ratio_fall"):
        now = _num(frame, trigger.column)
        fired = now <= trigger.threshold
        value, comparator = now, np.full(rows, trigger.threshold)
    elif trigger.test == "flag":
        fired = _flag(frame, trigger.column)
        value = fired.astype("float64")
        comparator = np.full(rows, np.nan)
    else:  # "level"
        now = _num(frame, trigger.column)
        fired = now >= trigger.threshold
        value, comparator = now, np.full(rows, trigger.threshold)

    fired = np.nan_to_num(fired, nan=False).astype(bool) & applies

    # §17's locked rule: a bureau trigger cannot fire in a month with no new
    # observation, however far the carried-forward value happens to sit from
    # the one before it.
    if trigger.needs_new_observation and "bureau_observed" in frame.columns:
        fired = fired & frame["bureau_observed"].fillna(False).to_numpy()

    return Fired(fired,
                 np.asarray(value, dtype="float64"),
                 np.asarray(comparator, dtype="float64"))


# ------------------------------------------------------- action dimensions

_DIRECTIONS = ("IMPROVING", "STABLE", "DETERIORATING")
_MOMENTUM = ("DECELERATING", "STEADY", "ACCELERATING")


def _worsens_upward(trigger: M.Trigger) -> bool:
    """Whether a RISE in the measured value is the bad direction."""
    return trigger.test not in ("fall", "below", "ratio_fall")


@dataclass
class Action:
    direction: Any
    magnitude: Any
    velocity: Any
    momentum: Any
    persistence: Any
    recency: Any
    multiplier: Any


def action_dimensions(trigger: M.Trigger, history: list[dict[str, Any]],
                      recency: Any) -> Action:
    """The six dimensions for one trigger, from its own recent history.

    `history` is this month first, then the months behind it: each entry holds
    the trigger's `value` array and its `fired` array, aligned on the current
    month's rows. A row with no history takes the neutral value, which is what
    a first published month honestly supports.
    """
    import numpy as np

    rows = len(history[0]["value"]) if history else 0
    values = [h["value"] for h in history]
    fired = [h["fired"] for h in history]

    now = values[0]
    was = values[1] if len(values) > 1 else np.full(rows, np.nan)
    before = values[2] if len(values) > 2 else np.full(rows, np.nan)
    earlier = values[3] if len(values) > 3 else np.full(rows, np.nan)

    worse_up = 1.0 if _worsens_upward(trigger) else -1.0
    change = (now - was) * worse_up

    direction = np.full(rows, _DIRECTIONS[1], dtype=object)
    tol = max(abs(trigger.threshold) * 0.05, 1e-9)
    direction = np.where(change > tol, _DIRECTIONS[2], direction)
    direction = np.where(change < -tol, _DIRECTIONS[0], direction)
    direction = np.where(np.isnan(change), _DIRECTIONS[1], direction)

    denominator = abs(trigger.threshold) if trigger.threshold else 1.0
    magnitude = np.clip(np.abs(np.nan_to_num(now - was)) / denominator, 0.0, 3.0)

    # Mean monthly change across the three most recent gaps that exist.
    gaps = []
    for later, older in ((now, was), (was, before), (before, earlier)):
        gaps.append((later - older) * worse_up)
    stacked = np.vstack(gaps)
    with np.errstate(invalid="ignore"):
        velocity = np.nanmean(stacked, axis=0)
    velocity = np.nan_to_num(velocity)

    recent = (now - was) * worse_up
    with np.errstate(invalid="ignore"):
        prior = np.nanmean(np.vstack(gaps[1:]), axis=0)
    shift = np.nan_to_num(recent) - np.nan_to_num(prior)
    momentum = np.full(rows, _MOMENTUM[1], dtype=object)
    momentum = np.where(shift > tol, _MOMENTUM[2], momentum)
    momentum = np.where(shift < -tol, _MOMENTUM[0], momentum)

    # Consecutive months fired, counting back from this month.
    persistence = np.zeros(rows, dtype="float64")
    still = np.ones(rows, dtype=bool)
    for month_fired in fired:
        hit = still & month_fired
        persistence += hit.astype("float64")
        still = hit

    scale = M.ACTION_WEIGHTS
    parts = (
        scale["direction"] * np.where(
            direction == _DIRECTIONS[2], 1.0,
            np.where(direction == _DIRECTIONS[0], -1.0, 0.0)),
        scale["magnitude"] * np.clip(magnitude - 1.0, -1.0, 1.0),
        scale["velocity"] * np.clip(
            np.sign(velocity) * np.minimum(np.abs(velocity) / denominator, 1.0),
            -1.0, 1.0),
        scale["momentum"] * np.where(
            momentum == _MOMENTUM[2], 1.0,
            np.where(momentum == _MOMENTUM[0], -1.0, 0.0)),
        scale["persistence"] * np.clip((persistence - 1.0) / 5.0, -1.0, 1.0),
        # Staleness reduces confidence rather than raising alarm.
        scale["recency"] * -np.clip(np.nan_to_num(recency) / 12.0, 0.0, 1.0),
    )
    pull = sum(parts)
    span = (M.ACTION_MULTIPLIER_CEILING - M.ACTION_MULTIPLIER_FLOOR) / 2.0
    middle = (M.ACTION_MULTIPLIER_CEILING + M.ACTION_MULTIPLIER_FLOOR) / 2.0
    multiplier = np.clip(middle + span * pull,
                         M.ACTION_MULTIPLIER_FLOOR,
                         M.ACTION_MULTIPLIER_CEILING)

    return Action(direction, magnitude, velocity, momentum, persistence,
                  np.nan_to_num(recency), multiplier)


# ----------------------------------------------------------------- the build

@dataclass
class Built:
    months: int = 0
    rows: int = 0
    skipped: int = 0
    fields: int = 0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.months} month(s) scored, {self.skipped} already "
                f"present, {self.rows} rows, {self.fields} fields")


def _prepare(month: str, previous: Any, analytics_dir: str | Path | None
             ) -> Any:
    """One month of the book, with the derived inputs the model needs.

    Everything added here is derived from the book and the month before it.
    Nothing is invented: a field the book cannot support is left out and the
    trigger that reads it carries its `absent_because`.
    """
    import numpy as np
    import pandas as pd

    frame = _read_book(month, analytics_dir).copy()
    frame["reporting_month"] = month
    frame["sub_product"] = sub_product_of(frame)
    frame["sub_product_label"] = frame["sub_product"].map(
        M.SUB_PRODUCT_LABELS).fillna("Unclassified")
    frame["sub_product_taxonomy_version"] = M.SUB_PRODUCT_TAXONOMY_VERSION
    frame["classification"] = classification_of(frame)
    frame["classification_label"] = frame["classification"].map(
        M.CLASSIFICATION_LABELS).fillna("Unclassified")
    frame["customer_name"] = frame["customer_id"].map(display_name)

    # --- prior-month comparators the book does not carry on the row.
    carried = ("debt_burden_ratio", "disposable_income_sar",
               "gross_carrying_amount_sar", "behavioural_score_band")
    if previous is not None and len(previous):
        prior = previous.set_index("facility_id")
        for column in carried:
            if column in prior.columns:
                frame[f"previous_month_{column}"] = (
                    frame["facility_id"].map(prior[column]))
    for column in carried:
        target = f"previous_month_{column}"
        if target not in frame.columns:
            frame[target] = np.nan
    frame["behavioural_score_band_previous"] = frame[
        "previous_month_behavioural_score_band"]

    # --- salary volatility, from what the book publishes about salary.
    one = pd.to_numeric(frame.get("salary_credit_amount_1m_sar"),
                        errors="coerce")
    six = pd.to_numeric(frame.get("salary_credit_average_6m_sar"),
                        errors="coerce")
    frame["salary_volatility_6m"] = (
        (one - six).abs() / six.where(six > 0)).fillna(0.0).round(4)

    # --- the three-month inflow average, for the cash-flow trigger.
    inflow = pd.to_numeric(frame.get("account_inflows_1m_sar"),
                           errors="coerce")
    # The book publishes one month of account inflows, so the comparator is
    # built from the panel's OWN history rather than invented. Until three
    # months exist the average is over what does, and in the first month the
    # trigger has nothing to compare against and does not fire.
    if previous is not None and len(previous):
        prior = previous.set_index("facility_id")
        frame["previous_month_account_inflows_1m_sar"] = frame[
            "facility_id"].map(prior.get("account_inflows_1m_sar",
                                         pd.Series(dtype="float64")))
        frame["previous_2_account_inflows_1m_sar"] = frame[
            "facility_id"].map(prior.get("previous_month_account_inflows_1m_sar",
                                         pd.Series(dtype="float64")))
    else:
        frame["previous_month_account_inflows_1m_sar"] = np.nan
        frame["previous_2_account_inflows_1m_sar"] = np.nan
    history = frame[["previous_month_account_inflows_1m_sar",
                     "previous_2_account_inflows_1m_sar"]].apply(
                         pd.to_numeric, errors="coerce")
    frame["account_inflows_3m_average_sar"] = history.mean(
        axis=1, skipna=True).round(2)
    del inflow

    # --- default entry, and what is eligible to enter. ODR's two halves.
    now_default = frame.get("current_default_flag")
    now_default = (now_default.fillna(False).astype(bool)
                   if now_default is not None
                   else pd.Series(False, index=frame.index))
    if previous is not None and len(previous):
        prior_default = frame["facility_id"].map(
            previous.set_index("facility_id")["current_default_flag"]
            if "current_default_flag" in previous.columns
            else pd.Series(dtype=bool))
        prior_default = prior_default.fillna(False).astype(bool)
    else:
        prior_default = pd.Series(False, index=frame.index)
    frame["prior_month_default_flag"] = prior_default
    frame["default_entry_this_month"] = now_default & (~prior_default)
    frame["eligible_for_default_this_month"] = ~prior_default

    # --- the bureau observation schedule, and the carried-forward position.
    frame["bureau_observed"] = _bureau_observed(frame, month)
    return frame


def _carry_bureau(frame: Any, previous: Any) -> Any:
    """Carry the last observed bureau position forward, unchanged.

    This is the whole of §17's locked rule in one function. In a month that
    holds an observation the book's bureau columns ARE the observation. In a
    month that does not, last month's carried values are used again and the
    recency counter advances. No monthly bureau movement is generated.
    """
    import numpy as np
    import pandas as pd

    observed = frame["bureau_observed"].fillna(False).astype(bool)
    month = str(frame["reporting_month"].iloc[0]) if len(frame) else ""

    fresh = {
        "latest_bureau_score": pd.to_numeric(
            frame.get("bureau_score_current"), errors="coerce"),
        "bureau_external_dpd_max_observed": pd.to_numeric(
            frame.get("bureau_external_dpd_max"), errors="coerce"),
        "bureau_total_exposure_observed": pd.to_numeric(
            frame.get("bureau_total_exposure_sar"), errors="coerce"),
        "bureau_enquiries_observed": pd.to_numeric(
            frame.get("bureau_enquiries_3m"), errors="coerce"),
        "external_obligations_observed": pd.to_numeric(
            frame.get("monthly_external_credit_obligations_sar"),
            errors="coerce"),
    }

    if previous is not None and len(previous):
        prior = previous.set_index("facility_id")
        for name, values in fresh.items():
            carried = frame["facility_id"].map(
                prior[name] if name in prior.columns
                else pd.Series(dtype="float64"))
            frame[name] = values.where(observed, carried)
        last_date = frame["facility_id"].map(
            prior["bureau_last_observed_date"]
            if "bureau_last_observed_date" in prior.columns
            else pd.Series(dtype=object))
        frame["bureau_last_observed_date"] = np.where(
            observed, month, last_date.fillna(month))
        # What the position was at the PREVIOUS observation, so a bureau
        # trigger compares two dated pulls rather than two carried copies.
        for name, target in (
            ("latest_bureau_score", "previous_observed_bureau_score"),
            ("bureau_external_dpd_max_observed", "previous_observed_external_dpd"),
            ("bureau_total_exposure_observed", "previous_observed_bureau_exposure"),
            ("bureau_enquiries_observed", "previous_observed_enquiries"),
        ):
            carried_prev = frame["facility_id"].map(
                prior[target] if target in prior.columns
                else pd.Series(dtype="float64"))
            carried_now = frame["facility_id"].map(
                prior[name] if name in prior.columns
                else pd.Series(dtype="float64"))
            frame[target] = np.where(observed, carried_now, carried_prev)
    else:
        for name, values in fresh.items():
            frame[name] = values
        frame["bureau_last_observed_date"] = month
        for target in ("previous_observed_bureau_score",
                       "previous_observed_external_dpd",
                       "previous_observed_bureau_exposure",
                       "previous_observed_enquiries"):
            frame[target] = np.nan

    frame["bureau_recency_months"] = [
        _months_between(str(seen), month)
        for seen in frame["bureau_last_observed_date"]]
    score = pd.to_numeric(frame["latest_bureau_score"], errors="coerce")
    frame["bureau_risk_band"] = pd.cut(
        score, bins=[-np.inf, 550, 620, 680, 740, np.inf],
        labels=["E", "D", "C", "B", "A"]).astype(object)
    frame["external_delinquency_flag"] = (
        pd.to_numeric(frame["bureau_external_dpd_max_observed"],
                      errors="coerce").fillna(0.0) >= 30.0)
    frame["external_default_flag"] = (
        pd.to_numeric(frame["bureau_external_dpd_max_observed"],
                      errors="coerce").fillna(0.0) >= 90.0)
    frame["synthetic_bureau_proxy_flag"] = True
    return frame


def _months_between(earlier: str, later: str) -> int:
    try:
        a_year, a_month = int(earlier[:4]), int(earlier[5:7])
        b_year, b_month = int(later[:4]), int(later[5:7])
    except (ValueError, IndexError):
        return 0
    return max(0, (b_year - a_year) * 12 + (b_month - a_month))


def build(*, analytics_dir: str | Path | None = None,
          replace: bool = False, months: list[str] | None = None) -> Built:
    """Score the twenty months and persist the Early Warning Score domain."""
    import numpy as np
    import pandas as pd

    from backend.retail import guard

    root = _root(analytics_dir)
    guard.require_retail_directory(root, what="the Early Warning Score domain")

    wanted = months or scored_months(analytics_dir)
    out = Built()
    if not wanted:
        out.notes.append("the retail book holds no months")
        return out

    every = book_months(analytics_dir)
    target = root / DOMAIN
    triggers = M.evaluated_triggers()

    # A regenerated book keeps its period names, so every marker this build
    # looks for is still on disk and it skips all of them — leaving the domain
    # serving a book that no longer exists. The stamp is what notices.
    from backend.retail import source_stamp

    if source_stamp.stale(root, DOMAIN):
        replace = True
        out.notes.append(
            "the book was rebuilt since this domain was, so every month is "
            "rescored rather than skipped")

    # Two months of lead-in, so the first SCORED month already has the prior
    # month its comparators need. Scoring twenty months from a twenty-five
    # month book costs nothing; scoring the first of them with no history
    # would silently report every action dimension as neutral.
    prepared: dict[str, Any] = {}
    fired_history: dict[str, list[dict[str, Any]]] = {t.key: [] for t in triggers}

    lead_in = every[max(0, every.index(wanted[0]) - 4):every.index(wanted[0])]
    ordered = lead_in + wanted

    #: How far back an action dimension looks. The history loop below reads
    #: `index - 1` to `index - 3`, so a month older than this can never be
    #: consulted again.
    LOOKBACK = 3
    dropped_too_early = 0

    # Prepared as they are reached, and dropped once nothing can read them.
    #
    # This used to prepare all twenty-four months before scoring any of them,
    # and hold every one of them for the whole run. On a twenty-thousand
    # facility book that was a few gigabytes and nobody noticed; on sixty
    # thousand it reached ten gigabytes of resident memory and the kernel
    # killed the build half way through, leaving twelve months of the domain
    # rebuilt and eight missing. Nothing beyond three months back is ever
    # read, so nothing beyond three months back is kept.
    previous_frame = None
    for index, month in enumerate(ordered):
        frame = _prepare(month, previous_frame, analytics_dir)
        frame = _carry_bureau(frame, previous_frame)
        prepared[month] = frame
        previous_frame = frame

        # Everything the history can no longer reach.
        for stale_month in ordered[:max(0, index - LOOKBACK)]:
            dropped = prepared.pop(stale_month, None)
            del dropped
            for trigger in triggers:
                fired_history.pop(f"{stale_month}|{trigger.key}", None)

        results = {t.key: evaluate(frame, t) for t in triggers}
        # Align the previous months' values onto THIS month's rows, by
        # facility, so an action dimension compares the same facility rather
        # than the same row position.
        history: dict[str, list[dict[str, Any]]] = {}
        for trigger in triggers:
            series = [{"value": results[trigger.key].value,
                       "fired": results[trigger.key].fired}]
            for back in range(1, 4):
                if index - back < 0:
                    break
                older_month = ordered[index - back]
                older = prepared.get(older_month)
                older_results = fired_history.get(
                    f"{older_month}|{trigger.key}")
                if older is None and older_results is not None:
                    # The sliding window dropped a month the history still
                    # wants. That would silently shorten an action dimension's
                    # look-back, so it is counted and reported rather than
                    # absorbed — if this is ever non-zero the window is wrong.
                    dropped_too_early += 1
                if older is None or older_results is None:
                    break
                mapped_value = frame["facility_id"].map(
                    pd.Series(older_results["value"],
                              index=older["facility_id"])).to_numpy(
                                  dtype="float64")
                mapped_fired = frame["facility_id"].map(
                    pd.Series(older_results["fired"],
                              index=older["facility_id"])).fillna(
                                  False).to_numpy(dtype=bool)
                series.append({"value": mapped_value, "fired": mapped_fired})
            history[trigger.key] = series
            fired_history[f"{month}|{trigger.key}"] = {
                "value": results[trigger.key].value,
                "fired": results[trigger.key].fired}

        if month not in wanted:
            continue

        destination = target / f"reporting_month={month}"
        marker = destination / "part-0.parquet"
        if marker.exists() and not replace:
            out.skipped += 1
            continue

        scored = _score_month(frame, results, history, triggers)
        destination.mkdir(parents=True, exist_ok=True)
        scored.to_parquet(marker, index=False)
        out.months += 1
        out.rows += len(scored)
        out.fields = max(out.fields, len(scored.columns))
        # The scored month is five hundred columns wide and has just been
        # written; holding it while the next month is prepared doubles the
        # peak for no reason.
        del scored

    if dropped_too_early:
        out.notes.append(
            f"the sliding window dropped a prepared month the action "
            f"dimensions still needed, {dropped_too_early} time(s); the "
            f"look-back is shorter than the model declares")

    # Anything older than the twenty months is removed, so the domain holds
    # exactly what it claims to and a stale month cannot be read by accident.
    #
    # Pruned against the RETENTION WINDOW, never against the caller's request.
    # These were the same list while `build()` was only ever called for
    # everything, and the moment it was called for three months it deleted the
    # other seventeen — a targeted rebuild is not a statement about what the
    # domain should contain.
    keep = set(scored_months(analytics_dir)) | set(wanted)
    if target.exists():
        for directory in sorted(target.iterdir()):
            if not directory.is_dir():
                continue
            month = directory.name.split("=", 1)[-1]
            if month not in keep:
                for part in directory.iterdir():
                    part.unlink()
                directory.rmdir()
                out.notes.append(
                    f"{month} removed: the domain holds the latest "
                    f"{MONTHS_KEPT} months only")
    forget()
    source_stamp.record(root, DOMAIN)
    del np
    return out


def _score_month(frame: Any, results: dict[str, Fired],
                 history: dict[str, list[dict[str, Any]]],
                 triggers: tuple[M.Trigger, ...]) -> Any:
    """Turn one prepared month into one row per customer-facility."""
    import numpy as np
    import pandas as pd

    rows = len(frame)
    out = pd.DataFrame(index=frame.index)

    def carry(name: str, source: str | None = None, default: Any = None) -> None:
        column = source or name
        if column in frame.columns:
            out[name] = frame[column].to_numpy()
        elif default is not None:
            out[name] = default

    # --- identity and hierarchy
    for name in ("reporting_month", "customer_id", "customer_name",
                 "facility_id", "product_code", "product_label",
                 "sub_product", "sub_product_label",
                 "sub_product_taxonomy_version",
                 "classification", "classification_label",
                 "product_subsegment",
                 "customer_segment", "origination_channel",
                 "origination_date", "origination_vintage", "months_on_book",
                 "employment_status", "employer_sector",
                 "salary_transfer_flag", "customer_tenure_months"):
        carry(name)
    out["segment"] = out.get("customer_segment")
    out["sub_segment"] = out.get("product_subsegment")

    # --- exposure and facility structure
    for name in ("gross_carrying_amount_sar", "ead_base_sar",
                 "current_credit_limit_sar", "original_credit_limit_sar",
                 "undrawn_commitment_sar", "utilisation_ratio",
                 "utilisation_band", "original_finance_amount_sar",
                 "original_tenor_months", "remaining_contractual_tenor_months",
                 "secured_flag", "collateral_type",
                 "collateral_value_current_sar",
                 "collateral_value_origination_sar", "collateral_valuation_date",
                 "ltv_current_ratio", "ltv_origination_ratio", "balloon_band",
                 "balloon_payment_sar", "months_to_balloon",
                 "contract_structure"):
        carry(name)
    limit = pd.to_numeric(out.get("current_credit_limit_sar"),
                          errors="coerce")
    drawn = pd.to_numeric(out.get("gross_carrying_amount_sar"),
                          errors="coerce")
    out["utilised_amount_sar"] = drawn
    out["balloon_flag"] = (
        pd.to_numeric(out.get("balloon_payment_sar"),
                      errors="coerce").fillna(0.0) > 0)

    # --- credit status
    for name in ("dpd", "previous_month_dpd", "dpd_bucket", "max_dpd_3m",
                 "max_dpd_6m", "ifrs9_stage", "previous_month_stage",
                 "sicr_flag", "current_default_flag", "cure_flag",
                 "forbearance_flag", "restructured_flag",
                 "credit_impaired_flag", "collections_stage",
                 "prior_month_default_flag", "default_entry_this_month",
                 "eligible_for_default_this_month"):
        carry(name)
    dpd = pd.to_numeric(out["dpd"], errors="coerce").fillna(0.0)
    prior_dpd = pd.to_numeric(out.get("previous_month_dpd"),
                              errors="coerce").fillna(0.0)
    out["dpd_change"] = (dpd - prior_dpd).round(2)
    stage = pd.to_numeric(out.get("ifrs9_stage"), errors="coerce").fillna(0)
    prior_stage = pd.to_numeric(out.get("previous_month_stage"),
                                errors="coerce").fillna(stage)
    out["stage_change"] = (stage - prior_stage).astype("float64")

    # --- the existing scores
    for name in ("application_score_at_origination", "application_score_band",
                 "behavioural_score", "behavioural_score_previous_month",
                 "behavioural_score_band", "behavioural_score_band_previous",
                 "behavioural_score_date"):
        carry(name)
    out["application_score"] = out.get("application_score_at_origination")
    out["prior_behavioural_score"] = out.get(
        "behavioural_score_previous_month")
    out["prior_behavioural_score_band"] = out.get(
        "behavioural_score_band_previous")
    out["behavioural_score_change"] = (
        pd.to_numeric(out.get("behavioural_score"), errors="coerce")
        - pd.to_numeric(out.get("behavioural_score_previous_month"),
                        errors="coerce")).round(2)
    out["behavioural_score_absent_because"] = np.where(
        pd.to_numeric(out.get("behavioural_score"), errors="coerce").isna(),
        NO_BEHAVIOURAL_SCORE, "")

    # --- bureau, on dated observations only
    for name in ("bureau_score_at_origination", "latest_bureau_score",
                 "bureau_last_observed_date", "bureau_recency_months",
                 "bureau_risk_band", "bureau_observed",
                 "external_delinquency_flag", "external_default_flag",
                 "bureau_external_dpd_max_observed",
                 "bureau_total_exposure_observed",
                 "bureau_enquiries_observed", "external_obligations_observed",
                 "previous_observed_bureau_score",
                 "synthetic_bureau_proxy_flag"):
        carry(name)
    out["bureau_enquiry_count"] = out.get("bureau_enquiries_observed")
    out["external_obligations_sar"] = out.get("external_obligations_observed")
    out["external_debt_burden"] = (
        pd.to_numeric(out.get("external_obligations_observed"),
                      errors="coerce")
        / pd.to_numeric(frame.get("verified_total_monthly_income_sar"),
                        errors="coerce").where(lambda s: s > 0)).round(4)

    # --- affordability and cash flow
    for name in ("verified_total_monthly_income_sar",
                 "salary_credit_amount_1m_sar", "salary_credit_last_date",
                 "salary_missed_cycle_count_3m", "salary_change_3m_ratio",
                 "salary_volatility_6m", "monthly_total_credit_obligations_sar",
                 "monthly_external_credit_obligations_sar",
                 "debt_burden_ratio", "previous_month_debt_burden_ratio",
                 "origination_debt_burden_ratio", "disposable_income_sar",
                 "previous_month_disposable_income_sar",
                 "account_inflows_1m_sar", "account_outflows_1m_sar",
                 "account_inflows_3m_average_sar",
                 "previous_month_account_inflows_1m_sar",
                 "account_average_balance_3m_sar", "balance_buffer_months",
                 "indebtedness_band", "external_obligations_change_3m_sar"):
        carry(name)
    out["verified_income"] = out.get("verified_total_monthly_income_sar")
    out["salary_credit_missing_flag"] = (
        pd.to_numeric(out.get("salary_missed_cycle_count_3m"),
                      errors="coerce").fillna(0.0) > 0)
    out["dbr"] = out.get("debt_burden_ratio")
    out["prior_dbr"] = out.get("previous_month_debt_burden_ratio")
    out["dbr_change"] = (
        pd.to_numeric(out.get("debt_burden_ratio"), errors="coerce")
        - pd.to_numeric(out.get("previous_month_debt_burden_ratio"),
                        errors="coerce")).round(4)
    out["disposable_income_change"] = (
        pd.to_numeric(out.get("disposable_income_sar"), errors="coerce")
        - pd.to_numeric(out.get("previous_month_disposable_income_sar"),
                        errors="coerce")).round(2)

    # --- behavioural and facility trigger inputs
    for name in ("missed_payment_count_3m", "missed_payment_count_6m",
                 "returned_payment_count_3m", "autopay_failure_count_3m",
                 "broken_promise_count_3m", "minimum_payment_only_months_3m",
                 "full_payment_months_6m", "payment_to_due_ratio_1m",
                 "cash_advance_share_3m", "overlimit_days_3m",
                 "utilisation_change_3m_pp",
                 "previous_month_gross_carrying_amount_sar"):
        carry(name)

    # --- one block per trigger, with its six action dimensions
    points = M.SEVERITY_POINTS
    recency_now = np.zeros(rows)
    bureau_recency = pd.to_numeric(out.get("bureau_recency_months"),
                                   errors="coerce").fillna(0.0).to_numpy()

    contributions: dict[str, list[Any]] = {}
    # Collected, then attached in one go.
    #
    # Thirty-four triggers with ten columns each is three hundred and forty
    # single-column writes, and pandas reallocates the frame as it goes —
    # which is what the fragmentation warning was about. It was being answered
    # afterwards with a full copy, which fixes the frame for whatever comes
    # next but not the cost of building it.
    trigger_columns: dict[str, Any] = {}
    for trigger in triggers:
        result = results[trigger.key]
        recency = (bureau_recency if trigger.source_class == "External"
                   else recency_now)
        action = action_dimensions(trigger, history[trigger.key], recency)

        key = trigger.key
        trigger_columns[f"trg_{key}_fired"] = result.fired
        trigger_columns[f"trg_{key}_value"] = np.round(result.value, 4)
        trigger_columns[f"trg_{key}_comparator"] = np.round(result.comparator, 4)
        trigger_columns[f"trg_{key}_direction"] = np.where(result.fired, action.direction, "")
        trigger_columns[f"trg_{key}_magnitude"] = np.where(
            result.fired, np.round(action.magnitude, 3), np.nan)
        trigger_columns[f"trg_{key}_velocity"] = np.where(
            result.fired, np.round(action.velocity, 4), np.nan)
        trigger_columns[f"trg_{key}_momentum"] = np.where(result.fired, action.momentum, "")
        trigger_columns[f"trg_{key}_persistence"] = np.where(
            result.fired, action.persistence, np.nan)
        trigger_columns[f"trg_{key}_recency"] = np.where(
            result.fired, np.round(action.recency, 2), np.nan)

        scored = np.where(
            result.fired,
            np.minimum(points.get(trigger.severity, 0.0) * action.multiplier,
                       M.TRIGGER_CONTRIBUTION_CAP),
            0.0)
        trigger_columns[f"trg_{key}_contribution"] = np.round(scored, 3)
        contributions.setdefault(
            M.sublayer_of_trigger(key).key, []).append(scored)

    if trigger_columns:
        out = pd.concat([out, pd.DataFrame(trigger_columns, index=out.index)],
                        axis=1, copy=False)

    # --- sublayer scores
    #
    # The worst contribution in the sublayer, plus a tenth of each further
    # one, capped at 100. Summing them instead would let four mild triggers
    # outrank one critical, which is not how a credit officer reads a file.
    sublayer_columns: dict[str, Any] = {}
    for sub in M.all_sublayers():
        stacked = contributions.get(sub.key)
        if not stacked:
            sublayer_columns[sub.score_column] = np.zeros(rows)
            continue
        piled = np.vstack(stacked)
        worst = piled.max(axis=0)
        others = np.clip(piled.sum(axis=0) - worst, 0.0, None)
        sublayer_columns[sub.score_column] = np.round(
            np.minimum(worst + 0.10 * others, 100.0), 3)

    # --- layer scores, from the sublayer weights
    #
    # Combined rather than averaged. See `_combine`: a weighted mean dilutes a
    # single serious signal into the bottom of the scale, and a weighted sum
    # rescaled by the largest weight overshoots the moment three parts fire,
    # pinning five per cent of the book at exactly 100.
    if sublayer_columns:
        out = pd.concat([out, pd.DataFrame(sublayer_columns, index=out.index)],
                        axis=1, copy=False)

    layer_columns: dict[str, Any] = {}
    for layer in M.LAYERS:
        heaviest = max((sub.weight for sub in layer.sublayers), default=1.0)
        layer_columns[layer.score_column] = np.round(_combine(
            [(sub.weight / (heaviest or 1.0),
              sublayer_columns[sub.score_column]) for sub in layer.sublayers],
            rows), 3)
    if layer_columns:
        out = pd.concat([out, pd.DataFrame(layer_columns, index=out.index)],
                        axis=1, copy=False)

    # --- the overall score, on the product's own weights, the same way
    #
    # The weights are per ROW, not per product, because the Bureau layer's
    # weight depends on how old that customer's bureau observation is. A pull
    # from two years ago cannot carry the same fifteen per cent as one from
    # last month; what it releases goes to the layers that still have
    # something to say this month. `M.effective_weights` does the arithmetic
    # and guarantees the four still total one.
    overall = np.zeros(rows)
    product = out["product_code"].astype(str).to_numpy()
    age = pd.to_numeric(out.get("bureau_recency_months"),
                        errors="coerce").to_numpy(dtype=float)
    observed_ever = ~np.isnan(age)
    weight_columns = {layer.key: np.zeros(rows) for layer in M.LAYERS}

    for code in M.ALL_PRODUCTS:
        mask = product == code
        if not mask.any():
            continue
        base = M.weights_for(code)
        # `_combine` divides the weights through by a reference before rolling
        # them up, and the reference has to be FIXED for the redistribution to
        # mean anything. Dividing by the heaviest EFFECTIVE weight scales the
        # three dynamic layers up and then immediately back down again: their
        # relative weights come out identical at every bureau age, and the
        # only thing a stale pull changes is that bureau contributes less.
        # That is a decay without a redistribution, and the model claims both.
        # Against the heaviest BASE weight — a constant per product — the
        # weight bureau releases genuinely lands on the layers that still have
        # something to say. At a fresh pull the effective weights ARE the base
        # weights, so this is the same arithmetic v2 ran.
        #
        # Capped at the reference, which is a governance statement and not a
        # convenience: no layer may be handed more influence than the heaviest
        # layer carries on a fresh pull. Without the cap the heaviest layer
        # crosses the reference on a stale pull, its contribution saturates,
        # and a handful of the worst customers land on exactly 100 with their
        # ordering among themselves lost — which is the failure `_combine` was
        # written to avoid. The layers below the reference still take up every
        # point bureau releases.
        heaviest = max(base.values())
        # One set of weights per distinct age, rather than per row: the ages
        # are whole months, so this is a handful of evaluations.
        ages = np.where(observed_ever, np.nan_to_num(age, nan=-1.0), -1.0)
        for one in np.unique(ages[mask]):
            here = mask & (ages == one)
            if not here.any():
                continue
            weights = M.effective_weights(
                code, None if one < 0 else float(one))
            blended = _combine(
                [(min(weights[layer.key] / heaviest, 1.0),
                  out[layer.score_column].to_numpy()) for layer in M.LAYERS],
                rows)
            overall = np.where(here, blended, overall)
            for layer in M.LAYERS:
                weight_columns[layer.key] = np.where(
                    here, weights[layer.key], weight_columns[layer.key])
        for layer in M.LAYERS:
            out[f"base_weight_{layer.key}"] = np.where(
                mask, base[layer.key], out.get(f"base_weight_{layer.key}", 0.0))

    for layer in M.LAYERS:
        out[f"effective_weight_{layer.key}"] = np.round(
            weight_columns[layer.key], 6)
    # Named for what a reader asks for by name.
    out["bureau_weight_base"] = out["base_weight_bureau"]
    out["bureau_weight_effective"] = out["effective_weight_bureau"]
    out["bureau_weight_released"] = np.round(
        out["base_weight_bureau"].to_numpy()
        - out["effective_weight_bureau"].to_numpy(), 6)
    out["effective_weight_total"] = np.round(sum(
        out[f"effective_weight_{layer.key}"].to_numpy()
        for layer in M.LAYERS), 6)
    out["ews_score_before_overrides"] = np.round(overall, 3)

    # --- hard triggers: the only place the arithmetic is overridden
    stage_now = pd.to_numeric(out.get("ifrs9_stage"),
                              errors="coerce").fillna(0).to_numpy()
    forborne = out.get("forbearance_flag")
    forborne = (forborne.fillna(False).astype(bool).to_numpy()
                if forborne is not None else np.zeros(rows, dtype=bool))
    entered = out["default_entry_this_month"].fillna(False).astype(bool).to_numpy()
    dpd_now = dpd.to_numpy()

    # A trigger of a given severity firing anywhere, for the two floors that
    # exist because a fifteen-per-cent layer cannot carry one on its own.
    def _any_fired(severity: str) -> np.ndarray:
        hit = np.zeros(rows, dtype=bool)
        for trigger in M.evaluated_triggers():
            if trigger.severity != severity:
                continue
            column = out.get(f"trg_{trigger.key}_fired")
            if column is None:
                continue
            hit = hit | column.fillna(False).astype(bool).to_numpy()
        return hit

    applied = np.full(rows, "", dtype=object)
    for hard in M.HARD_TRIGGERS:
        if hard.key == "dpd_90":
            hit = dpd_now >= 90.0
        elif hard.key == "stage_3":
            hit = stage_now >= 3
        elif hard.key == "default_entry":
            hit = entered
        elif hard.key == "high_trigger_floor":
            hit = _any_fired("HIGH")
        elif hard.key == "critical_trigger_floor":
            hit = _any_fired("CRITICAL")
        else:
            hit = forborne & (dpd_now >= 30.0)
        raise_to = hit & (overall < hard.floor_score)
        overall = np.where(raise_to, hard.floor_score, overall)
        applied = np.where(raise_to, hard.key, applied)
    out["ews_score"] = np.round(np.clip(overall, M.SCALE.minimum,
                                        M.SCALE.maximum), 3)
    out["hard_trigger_applied"] = applied
    out["ews_severity"] = [M.band_of(v) for v in out["ews_score"]]
    out["ews_threshold"] = M.SCALE.warning_cutoff
    out["ews_alert_flag"] = out["ews_score"] >= M.SCALE.warning_cutoff

    # --- the two cohorts
    out["current_bad_flag"] = (
        (dpd_now >= 30.0)
        | out.get("current_default_flag",
                  pd.Series(False, index=out.index)).fillna(False).astype(bool)
        | (stage_now >= 3))
    out["forward_risk_flag"] = (
        (~out["current_bad_flag"])
        & out["ews_severity"].isin(("HIGH", "CRITICAL")))

    # §21's clean cohort: completely up to date, not merely under thirty
    # days, and with no hard trigger applied. `applied` is the hard-trigger
    # mask computed above — a customer whose score was forced to a band by a
    # hard trigger is not a leading-indicator case, they are a rule firing,
    # and mixing the two is how a forward-risk review turns into a rerun of
    # the collections queue.
    out["clean_flag"] = (
        (dpd_now <= 0.0)
        & (~out.get("current_default_flag",
                    pd.Series(False, index=out.index)).fillna(False)
           .astype(bool))
        & (stage_now < 3)
        & (~pd.Series(applied, index=out.index).fillna(False).astype(bool)))
    out["clean_forward_risk_flag"] = (
        out["clean_flag"]
        & out["ews_severity"].isin(("HIGH", "CRITICAL")))

    # --- reason codes and the worst layer
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    ranked = sorted(
        triggers,
        key=lambda t: (order.get(t.severity, 9), t.reason_code))
    codes = np.full((rows, 3), "", dtype=object)
    names = np.full((rows, 3), "", dtype=object)
    slot = np.zeros(rows, dtype=int)
    for trigger in ranked:
        hit = out[f"trg_{trigger.key}_fired"].to_numpy()
        room = hit & (slot < 3)
        if room.any():
            index = slot[room]
            codes[np.where(room)[0], index] = trigger.reason_code
            names[np.where(room)[0], index] = trigger.name
            slot = slot + room.astype(int)
    for position in range(3):
        out[f"top_reason_code_{position + 1}"] = codes[:, position]
        out[f"top_reason_name_{position + 1}"] = names[:, position]

    layer_block = np.vstack([out[layer.score_column].to_numpy()
                             for layer in M.LAYERS])
    best = layer_block.argmax(axis=0)
    keys = [layer.key for layer in M.LAYERS]
    labels = [layer.name for layer in M.LAYERS]
    out["primary_deteriorating_layer"] = [
        keys[i] if layer_block[i, r] > 0 else ""
        for r, i in enumerate(best)]
    out["primary_deteriorating_layer_name"] = [
        labels[i] if layer_block[i, r] > 0 else ""
        for r, i in enumerate(best)]
    out["triggers_fired"] = sum(
        out[f"trg_{t.key}_fired"].astype(int) for t in triggers)

    out["model_version"] = M.EWS_MODEL_VERSION
    out["rulebook_version"] = _rulebook_version()
    out["panel_version"] = EWS_PANEL_VERSION
    return out.copy()


def _combine(parts: list[tuple[float, Any]], rows: int) -> Any:
    """Roll several 0-100 scores up into one, weighted, without dilution.

    Each part independently RAISES the result by its own share of what is
    still left to give:

        combined = 100 x (1 - product over parts of (1 - w_i x s_i / 100))

    Three properties, all of which the two arithmetics tried before this one
    failed at least one of:

    * a single part at the heaviest weight reaches its own value, so one HIGH
      trigger in one sublayer is not reported as LOW;
    * more parts firing always scores higher than fewer, so adding a mild
      second signal can never reduce the score;
    * nothing can exceed 100 and nothing piles up ON 100 — a weighted sum
      rescaled by the largest weight put five per cent of the book at exactly
      the ceiling, which loses the ordering among the worst customers.

    The weights keep their meaning: a part the model weights at half raises
    the score by half as much.
    """
    import numpy as np

    remaining = np.ones(rows)
    for weight, score in parts:
        share = np.clip(float(weight) * np.nan_to_num(score) / 100.0, 0.0, 1.0)
        remaining = remaining * (1.0 - share)
    return 100.0 * (1.0 - remaining)


NO_BEHAVIOURAL_SCORE = (
    "No behavioural score yet. The behavioural scorecard needs repayment "
    "history the facility does not have; it scores from the second month on "
    "book. The application score is shown instead.")


def _rulebook_version() -> str:
    try:
        from backend.retail import ews as rulebook

        return rulebook.RULEBOOK_VERSION
    except Exception:  # noqa: BLE001
        return "unknown"


def check(analytics_dir: str | Path | None = None) -> list[str]:
    """Everything wrong with the persisted domain, as sentences."""
    problems: list[str] = []
    held = panel_months(analytics_dir)
    wanted = scored_months(analytics_dir)
    if not held:
        problems.append(
            "the Early Warning Score domain has not been built; run "
            "scripts/bootstrap_retail_installation.py")
        return problems
    if len(held) != MONTHS_KEPT:
        problems.append(
            f"the domain holds {len(held)} monthly snapshots, not "
            f"{MONTHS_KEPT}")
    if held != wanted:
        problems.append(
            "the domain's months are not the latest "
            f"{MONTHS_KEPT} of the book: it holds {held[0]}…{held[-1]} and "
            f"the book's latest {MONTHS_KEPT} are {wanted[0]}…{wanted[-1]}")
    return problems

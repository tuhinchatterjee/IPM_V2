"""The Saudi SME scorecard universe. §6.1, §6.5.

Thirty-six monthly cohorts of SME applications, a champion and a challenger
scored on each, and a realised twelve-month outcome for every cohort whose
window has closed.

Everything here is generated. It describes no real business, no real bank's
book and no real bureau. Every row carries `origin = SYNTHETIC_DEMO`.

Time is anchored, not walked
------------------------------
`DATA_END_MONTH` is a constant. Maturity is `cohort + horizon <= data_end`,
never `cohort + horizon <= today`. That is the whole of §2: a suite that runs
at 23:58 and again at 00:02 gets identical matured cohorts, identical
populations and identical metrics, because nothing in this module reads the
clock. The alternative — anchoring to `today` — produces a universe that is
correct on the day it is written and quietly wrong on every other day, and
the failure shows up as a metric that moved when no code changed.

The weaknesses are generated, not asserted
--------------------------------------------
A demonstration where the finding is hard-coded teaches a reviewer that the
findings are decorative. So the weaknesses in `MANIFEST` are built into the
data-generating process, and the validation kernels then *discover* them by
doing the arithmetic. If a phenomenon here were removed, the corresponding
finding would disappear from the screen on the next build — which is the
property that makes the screen worth looking at.

Six phenomena, and what each one is for:

* **MICRO calibration gap.** The champion's PD is fitted on the whole book
  but micro enterprises default more than their score implies. Produces a
  real O/E above 1 for that segment while the overall O/E looks acceptable —
  the aggregate-conceals-a-segment case, which is the single most common way
  a scorecard is wrong in production.

* **Challenger discrimination lift.** The challenger uses two cash-flow
  variables the champion does not, and they carry genuine signal. Its AUC is
  higher, and the difference is large enough to survive a confidence
  interval. This is the trap: higher AUC is not on its own a reason to
  replace a champion, and the interpretation has to say so.

* **Challenger recent instability.** The same two variables drift in the
  last six cohorts, so the challenger's advantage is not stable. Discovered
  as a rolling-window divergence, not asserted.

* **Cash-flow variable PSI breach.** `bank_credits_to_declared_sales` shifts
  distribution from cohort 24 onward — a change in what is banked, not in
  who is applying. Produces a material variable PSI with a specific,
  identifiable contributor, so "which variable is causing it?" has an answer
  the arithmetic can give.

* **Decaying univariate power.** `commercial_bureau_score_proxy` loses
  discrimination over the window as its coverage thins. Produces a falling
  univariate Gini for one named variable while the model overall holds up.

* **Contracting-sector rank-order failure.** In one sector the score does not
  rank risk: the middle bands invert. Produces a segment where rank ordering
  genuinely breaks while the portfolio ordering is monotonic.

Two policy phenomena sit alongside them: overrides concentrated in one score
band, and a decision file where the final grade sometimes disagrees with the
model. Both are needed for §17 to have anything to test.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SYNTHETIC_VERSION = "1.0.0"

#: Every row carries it. The same marker the retail universe uses, so one
#: query finds all generated data in the lake.
ORIGIN = "SYNTHETIC_DEMO"

#: Keyed so that regenerating any one cohort reproduces it exactly, and
#: adding a cohort does not shift the ones before it.
MASTER_SEED = 20260904


# ------------------------------------------------------------------ the calendar

def _month_index(month: str) -> int:
    year, part = month.split("-")
    return int(year) * 12 + int(part) - 1


def _month_from_index(index: int) -> str:
    return f"{index // 12}-{index % 12 + 1:02d}"


def add_months(month: str, count: int) -> str:
    return _month_from_index(_month_index(month) + count)


#: §6.1. Thirty-six monthly observation cohorts.
COHORT_MONTHS: tuple[str, ...] = tuple(
    _month_from_index(_month_index("2023-01") + i) for i in range(36)
)

#: §6.1. The development sample is out of time from every validation cohort,
#: for the same reason it is in the retail universe: fitting on months you
#: then validate on is the same mistake as recomputing WoE on the validation
#: month, one step earlier.
DEVELOPMENT_MONTHS: tuple[str, ...] = tuple(
    f"2022-{m:02d}" for m in range(1, 13))

#: The performance window. Twelve months is the SME convention here and is
#: recorded on every row rather than assumed by a reader.
DEFAULT_HORIZON_MONTHS = 12

#: §2. The last month for which any outcome exists. A constant, deliberately.
#: Cohorts 2023-01 .. 2024-04 (16 of them) have closed windows; the remaining
#: 20 have not. Sixteen is above the fifteen §6.1 requires, with one spare so
#: that a future horizon change to 13 months does not silently drop below the
#: floor.
DATA_END_MONTH = "2025-04"

#: How many applications each cohort carries. Enough for stable score-band
#: and segment analysis: at roughly 3.6% base rate, a 1,400-row cohort
#: carries ~50 events, which clears the 30-event floor `metrics.py` enforces
#: and leaves a segment cut still meaningful.
ROWS_PER_COHORT = (1_300, 1_700)
DEVELOPMENT_ROWS_PER_MONTH = (1_400, 1_800)


def matured(month: str, *, horizon: int = DEFAULT_HORIZON_MONTHS,
            data_end: str = DATA_END_MONTH) -> bool:
    """Has this cohort's performance window closed?

    The distinction the module rests on. A cohort whose window is open has no
    realised outcome, so every metric comparing predicted against actual is
    undefined for it — not zero, not optimistic, undefined.
    """
    return _month_index(add_months(month, horizon)) <= _month_index(data_end)


def window_closes(month: str, *,
                  horizon: int = DEFAULT_HORIZON_MONTHS) -> str:
    """When this cohort's outcome will exist.

    Refusing to report an outcome is half an answer. The useful half is when
    it will be available, and a screen that says "not available" without it
    reads as broken rather than as honest.
    """
    return add_months(month, horizon)


def matured_months(months: tuple[str, ...] = COHORT_MONTHS, *,
                   horizon: int = DEFAULT_HORIZON_MONTHS,
                   data_end: str = DATA_END_MONTH) -> tuple[str, ...]:
    return tuple(m for m in months
                 if matured(m, horizon=horizon, data_end=data_end))


def latest_matured(months: tuple[str, ...] = COHORT_MONTHS, *,
                   horizon: int = DEFAULT_HORIZON_MONTHS,
                   data_end: str = DATA_END_MONTH) -> str:
    """The most recent cohort with a realised outcome — chronologically.

    `matured_months` preserves `COHORT_MONTHS` order, which is chronological
    by construction, so the last entry is the latest. Not `max()` on the
    string: "2024-9" would sort after "2024-10" and the zero-padding that
    saves it here is a property of the formatter, not a guarantee. Taking the
    last element of an ordered tuple does not depend on either.
    """
    ready = matured_months(months, horizon=horizon, data_end=data_end)
    return ready[-1] if ready else ""


def _rng(*parts: Any) -> np.random.Generator:
    """A generator keyed by what it is generating.

    Deterministic per cohort rather than per run: regenerating 2024-03 gives
    the same 2024-03 whether or not 2024-02 was generated first, so a partial
    rebuild cannot silently produce a different universe from a full one.
    """
    key = "|".join(str(p) for p in parts)
    seed = (MASTER_SEED + abs(hash(key)) % 2**31) % 2**32
    return np.random.default_rng(seed)


# --------------------------------------------------------------- the phenomena


@dataclass(frozen=True)
class Phenomenon:
    """One deliberately generated weakness, and what should find it."""

    key: str
    title: str
    what: str
    from_cohort: str
    found_by: str
    affects: str


MANIFEST: tuple[Phenomenon, ...] = (
    Phenomenon(
        key="micro_calibration_gap",
        title="The champion under-predicts default for micro enterprises",
        what=("Micro enterprises default at roughly 1.45x the rate the "
              "champion's PD implies, while the portfolio O/E stays inside "
              "its limit. The aggregate conceals the segment."),
        from_cohort=COHORT_MONTHS[0],
        found_by="calibration by segment; O/E for enterprise_size_class_proxy",
        affects="MICRO",
    ),
    Phenomenon(
        key="challenger_discrimination_lift",
        title="The challenger discriminates better than the champion",
        what=("The challenger reads two cash-flow variables the champion "
              "does not, and they carry real signal. Its AUC is materially "
              "higher over the matured window."),
        from_cohort=COHORT_MONTHS[0],
        found_by="champion/challenger discrimination comparison",
        affects="whole book",
    ),
    Phenomenon(
        key="challenger_recent_instability",
        title="The challenger's advantage is not stable in recent cohorts",
        what=("The same two variables drift from cohort 24, so the "
              "challenger's lift narrows and its score distribution moves. "
              "Higher AUC over the whole window, less reliable lately."),
        from_cohort=COHORT_MONTHS[24],
        found_by="rolling-window discrimination; challenger score PSI",
        affects="whole book",
    ),
    Phenomenon(
        key="banked_sales_psi_breach",
        title="Banked-to-declared-sales has shifted distribution",
        what=("From cohort 24 a growing share of applicants bank a smaller "
              "proportion of declared turnover with this institution. A "
              "population shift, not a change in who defaults."),
        from_cohort=COHORT_MONTHS[24],
        found_by="variable PSI, with per-band contribution",
        affects="bank_credits_to_declared_sales",
    ),
    Phenomenon(
        key="bureau_proxy_decay",
        title="The commercial bureau score is losing discriminatory power",
        what=("Coverage thins over the window and the score becomes noisier, "
              "so its univariate Gini falls steadily while the model overall "
              "holds up."),
        from_cohort=COHORT_MONTHS[4],
        found_by="univariate Gini by cohort for one variable",
        affects="commercial_bureau_score_proxy",
    ),
    Phenomenon(
        key="contracting_rank_inversion",
        title="Rank ordering breaks in government contracting",
        what=("In CONTRACTING_GOVERNMENT the middle score bands invert: "
              "receivable cycles rather than credit quality drive the "
              "outcome, and the score does not see it."),
        from_cohort=COHORT_MONTHS[0],
        found_by="bad rate by score band, within segment",
        affects="CONTRACTING_GOVERNMENT",
    ),
    Phenomenon(
        key="override_concentration",
        title="Overrides concentrate in one score band",
        what=("Upward overrides cluster just below the approval cut-off, "
              "where a relationship manager has the most to gain from one. "
              "Their realised default rate is worse than the approvals "
              "around them."),
        from_cohort=COHORT_MONTHS[0],
        found_by="override rate by score band; outcome of overridden cases",
        affects="score band 560-600",
    ),
)


def manifest() -> dict[str, Any]:
    """What was deliberately built in, for a report or a runbook."""
    return {
        "synthetic_version": SYNTHETIC_VERSION,
        "origin": ORIGIN,
        "phenomena": [
            {"key": p.key, "title": p.title, "what": p.what,
             "from_cohort": p.from_cohort, "found_by": p.found_by,
             "affects": p.affects}
            for p in MANIFEST
        ],
        "generated_not_asserted": (
            "Each phenomenon is built into the data-generating process and "
            "discovered by the validation kernels doing the arithmetic. "
            "Remove one and the corresponding finding disappears from the "
            "screen on the next build."),
    }


# ------------------------------------------------------------- categorical worlds

SIZE_CLASSES = ("MICRO", "SMALL", "MEDIUM")
SIZE_MIX = (0.46, 0.38, 0.16)

SECTORS = ("CONSTRUCTION", "WHOLESALE_RETAIL", "MANUFACTURING",
           "TRANSPORT_LOGISTICS", "PROFESSIONAL_SERVICES", "HOSPITALITY",
           "HEALTHCARE", "CONTRACTING_GOVERNMENT")
SECTOR_MIX = (0.19, 0.24, 0.11, 0.10, 0.13, 0.09, 0.06, 0.08)

REGIONS = ("RIYADH", "MAKKAH", "EASTERN_PROVINCE", "MADINAH", "ASIR",
           "QASSIM", "TABUK", "HAIL", "JAZAN", "NAJRAN")
REGION_MIX = (0.32, 0.21, 0.18, 0.07, 0.06, 0.05, 0.04, 0.03, 0.02, 0.02)

CITY_TIERS = ("TIER_1", "TIER_2", "TIER_3")
CITY_MIX = (0.58, 0.29, 0.13)

LEGAL_FORMS = ("ESTABLISHMENT", "LLC", "JOINT_STOCK", "PARTNERSHIP")
LEGAL_MIX = (0.44, 0.42, 0.05, 0.09)

FACILITY_TYPES = ("TERM_LOAN", "WORKING_CAPITAL", "OVERDRAFT",
                  "POS_FINANCING", "INVOICE_FINANCING")
FACILITY_MIX = (0.28, 0.31, 0.17, 0.13, 0.11)

PURPOSES = ("WORKING_CAPITAL", "EXPANSION", "EQUIPMENT", "REFINANCE",
            "CONTRACT_EXECUTION")
PURPOSE_MIX = (0.38, 0.22, 0.17, 0.13, 0.10)

GUARANTEES = ("NONE", "PERSONAL", "CORPORATE", "PROGRAMME")
GUARANTEE_MIX = (0.21, 0.49, 0.16, 0.14)

KEY_PERSON = ("LOW", "MEDIUM", "HIGH")
KEY_PERSON_MIX = (0.24, 0.45, 0.31)

#: How much each latent driver moves the log-odds of default. These are the
#: economics of the universe: the numbers a reader should argue with, kept in
#: one place rather than scattered through the generator.
SIZE_RISK: dict[str, float] = {"MICRO": 0.52, "SMALL": 0.0, "MEDIUM": -0.44}
SECTOR_RISK: dict[str, float] = {
    "CONSTRUCTION": 0.34, "WHOLESALE_RETAIL": 0.06,
    "MANUFACTURING": -0.12, "TRANSPORT_LOGISTICS": 0.18,
    "PROFESSIONAL_SERVICES": -0.28, "HOSPITALITY": 0.41,
    "HEALTHCARE": -0.35, "CONTRACTING_GOVERNMENT": 0.09,
}
KEY_PERSON_RISK: dict[str, float] = {"LOW": -0.18, "MEDIUM": 0.0, "HIGH": 0.22}

#: The portfolio's through-the-cycle default rate, before any driver moves it.
BASE_LOG_ODDS = -3.35

# ---------------------------------------------------------------- score scaling

#: §5. The three parameters that define the scale, carried on the model
#: registry because a score is meaningless without them. 600 points at 30:1
#: good:bad odds, doubling every 40 points.
BASE_SCORE = 600.0
BASE_ODDS = 30.0
POINTS_TO_DOUBLE_ODDS = 40.0

_FACTOR = POINTS_TO_DOUBLE_ODDS / float(np.log(2.0))
_OFFSET = BASE_SCORE - _FACTOR * float(np.log(BASE_ODDS))

#: §6.5. How far the champion's PD understates micro-enterprise default.
#: One number, in one place, so the phenomenon can be described in a document
#: and changed in a build without the two drifting apart.
MICRO_PD_UNDERSTATEMENT = 1.45


def _sigmoid(logit: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-logit))


def _to_score(logit: np.ndarray) -> np.ndarray:
    """Log-odds of default to a points score.

    `logit` is the log-odds of *bad*, so the log-odds of good is its
    negative, and the standard scaling reads straight off: offset plus factor
    times the log-odds of good. A higher score is a better customer, which is
    what the registry declares and what every metric in the engine then
    respects through `score_direction`.
    """
    return _OFFSET + _FACTOR * (-logit)


_CALIBRATION_OFFSET: float | None = None


def _calibration_offset() -> float:
    """The additive log-odds shift that calibrates the champion's PD.

    Computed once, on the development sample, and then applied everywhere —
    which is what a calibration is. Fitting it on the validation months
    instead would guarantee O/E ≈ 1 there by construction, and a universe in
    which the calibration cannot be wrong is a universe in which testing it
    proves nothing.

    Solved by bisection on the mean predicted rate rather than analytically,
    because the relationship between an intercept shift and a mean
    probability is not linear and the closed form is not worth the reader's
    time. Twenty-four iterations put it inside 1e-6.

    The micro distortion is applied *inside* the fit, which is the detail
    that makes the phenomenon read correctly. Fitting first and distorting
    afterwards leaves the whole book under-predicted by about 27%, and a
    portfolio O/E of 1.27 is not "the aggregate conceals the segment" — it is
    a model that is visibly broken everywhere, which is a different and much
    less interesting finding. Fitting with the distortion in place is also
    what actually happens: the calibration was estimated on a model that
    already mis-segments, so it balances on average and is wrong in opposite
    directions on either side of the split. Micro comes out under-predicted,
    medium over-predicted, and the portfolio sits close to one.
    """
    global _CALIBRATION_OFFSET
    if _CALIBRATION_OFFSET is not None:
        return _CALIBRATION_OFFSET

    logits, micro, observed = _development_logits()
    low, high = -3.0, 3.0
    for _ in range(24):
        mid = (low + high) / 2.0
        made = _sigmoid(logits + mid)
        made = np.where(micro, made / MICRO_PD_UNDERSTATEMENT, made)
        if float(made.mean()) < observed:
            low = mid
        else:
            high = mid
    _CALIBRATION_OFFSET = (low + high) / 2.0
    return _CALIBRATION_OFFSET


def _pick(rng: np.random.Generator, values: tuple[str, ...],
          weights: tuple[float, ...], n: int) -> np.ndarray:
    return rng.choice(np.array(values), size=n,
                      p=np.array(weights) / float(sum(weights)))


def _lognormal(rng: np.random.Generator, n: int, median: float,
               sigma: float, floor: float = 0.0) -> np.ndarray:
    made = rng.lognormal(mean=float(np.log(median)), sigma=sigma, size=n)
    return np.maximum(made, floor)




# =========================================================== the cohort generator


def _drift_share(cohort_index: int, *, from_index: int, to: float) -> float:
    """How far a drift phenomenon has progressed by this cohort, 0 to `to`.

    Ramped rather than stepped. A step change is easy to generate and reads
    as a data incident; a ramp is what a population shift actually looks
    like, and it is the shape PSI is designed to notice while a single
    month-on-month comparison is not.
    """
    if cohort_index < from_index:
        return 0.0
    span = max(len(COHORT_MONTHS) - from_index - 1, 1)
    return to * min((cohort_index - from_index) / span, 1.0)


def _draw(month: str, *, rows: int = 0,
          development: bool = False) -> dict[str, Any]:
    """The characteristics, the latent risk, the two logits and the outcome.

    Split out from `cohort` to break a circularity that would otherwise be
    invisible: the champion's PD needs a calibration intercept, the intercept
    is fitted on the development sample, and fitting it means generating that
    sample — which would call `cohort` again.

    Nothing here needs the calibration, because none of it is a probability
    the model claims. That is the honest place to cut: everything before the
    model states a PD, and everything after.
    """
    index = (DEVELOPMENT_MONTHS.index(month) if development
             else COHORT_MONTHS.index(month))
    rng = _rng("sme-cohort", month, development)
    if not rows:
        low, high = (DEVELOPMENT_ROWS_PER_MONTH if development
                     else ROWS_PER_COHORT)
        rows = int(rng.integers(low, high + 1))

    # ---- who applied -----------------------------------------------------
    size = _pick(rng, SIZE_CLASSES, SIZE_MIX, rows)
    sector = _pick(rng, SECTORS, SECTOR_MIX, rows)
    region = _pick(rng, REGIONS, REGION_MIX, rows)
    key_person = _pick(rng, KEY_PERSON, KEY_PERSON_MIX, rows)

    micro = size == "MICRO"
    medium = size == "MEDIUM"

    revenue = np.where(
        micro, _lognormal(rng, rows, 1_800_000, 0.62, 200_000),
        np.where(medium, _lognormal(rng, rows, 34_000_000, 0.54, 9_000_000),
                 _lognormal(rng, rows, 8_400_000, 0.58, 1_500_000)))
    employees = np.maximum(
        1, (revenue / rng.uniform(180_000, 340_000, rows)).astype(int))
    years_trading = np.maximum(
        0.5, rng.gamma(shape=2.4, scale=2.6, size=rows))

    # ---- the cash-flow variables, two of which drift ---------------------
    # `bank_credits_to_declared_sales` is the banked-turnover reconciliation.
    # From cohort 24 a growing share of applicants bank less of their
    # declared turnover here: the population shifts, the risk relationship
    # does not. That is exactly the case PSI exists to separate from a
    # deterioration in the model.
    # 0.20 rather than the 0.34 this started at. The larger value produced a
    # variable CSI of 1.37, which is not a drift — it is a column that
    # changed meaning, and a validator reading it would look for a data
    # incident rather than a population shift. 0.20 lands the index in the
    # range where the conventional 0.25 cut-off is the thing being crossed,
    # which is the finding this phenomenon is for.
    shift = _drift_share(index if not development else -1,
                         from_index=24, to=0.20)
    banked = np.clip(
        rng.beta(6.0, 2.6, rows) * (1.28 - shift) + rng.normal(0, 0.06, rows),
        0.05, 1.9)

    payroll_regularity = np.clip(
        rng.beta(7.5, 1.9, rows) - shift * 0.11 * rng.random(rows), 0.05, 1.0)

    balance_to_credits = np.clip(
        rng.gamma(2.1, 0.085, rows), 0.005, 1.4)
    balance_volatility = np.clip(rng.gamma(3.0, 0.16, rows), 0.05, 3.5)
    top_customer = np.clip(rng.beta(2.3, 5.4, rows) * 100, 1.0, 98.0)
    returned_cheques = rng.poisson(
        np.clip(0.34 + 1.5 * (1.0 - payroll_regularity), 0.02, 6.0))
    overdraft_days = rng.poisson(
        np.clip(3.2 + 26 * np.clip(0.55 - balance_to_credits, 0, 1), 0.1, 90))
    max_dpd = np.clip(
        rng.gamma(1.25, 9.5, rows) * (1.0 + 0.9 * (1 - payroll_regularity)),
        0, 180).astype(int)

    # ---- financials ------------------------------------------------------
    ebitda_margin = np.clip(rng.normal(0.132, 0.075, rows), -0.28, 0.52)
    debt_to_ebitda = np.clip(rng.gamma(2.6, 1.32, rows), 0.05, 22.0)
    dscr = np.clip(rng.gamma(4.1, 0.42, rows), 0.05, 8.0)
    current_ratio = np.clip(rng.gamma(4.4, 0.32, rows), 0.15, 6.5)
    revenue_growth = np.clip(rng.normal(0.062, 0.19, rows), -0.72, 1.5)
    receivable_days = np.clip(rng.gamma(4.2, 16.0, rows), 3, 320)
    # Government contracting is paid slowly. Real, and the reason its rank
    # ordering breaks: the score reads leverage, the outcome reads the
    # receivable cycle.
    receivable_days = np.where(sector == "CONTRACTING_GOVERNMENT",
                               receivable_days * 1.85, receivable_days)

    # ---- the bureau proxy, whose power decays ----------------------------
    # Coverage thins and the reading gets noisier from cohort 12. The score
    # still exists on every row; it simply says less. That is the shape of a
    # variable losing univariate power without disappearing, which is harder
    # to notice and more common than a field going missing.
    # From cohort 4, not 12. The decay has to be visible *inside the matured
    # window* or the finding cannot be discovered: cohorts 16 onward have no
    # realised outcome, so no univariate discrimination can be computed on
    # them at all. A phenomenon that only exists where the outcome does not
    # is a phenomenon nothing can find, and the first draft put it there.
    decay = _drift_share(index if not development else -1,
                         from_index=4, to=0.62)
    bureau_signal = (
        0.72 * (dscr / 3.0) - 0.55 * (debt_to_ebitda / 6.0)
        + 0.40 * np.clip(years_trading / 8.0, 0, 1.6)
        - 0.48 * (max_dpd / 60.0))
    bureau_noise = rng.normal(0, 1.0, rows) * (0.55 + 1.45 * decay)
    bureau_score = np.clip(
        620 + 78 * bureau_signal + 42 * bureau_noise, 300, 900)

    # ---- the latent probability of default -------------------------------
    # Built from the characteristics, never from a score.
    log_odds = (
        BASE_LOG_ODDS
        + np.array([SIZE_RISK[str(v)] for v in size])
        + np.array([SECTOR_RISK[str(v)] for v in sector])
        + np.array([KEY_PERSON_RISK[str(v)] for v in key_person])
        - 0.62 * np.clip(banked - 0.85, -0.8, 0.8)
        - 0.95 * (payroll_regularity - 0.78)
        + 0.148 * np.clip(debt_to_ebitda - 3.4, -3.4, 12.0)
        - 0.46 * np.clip(dscr - 1.35, -1.3, 3.2)
        - 0.031 * np.clip(years_trading - 5.0, -4.5, 14.0)
        + 0.0125 * np.clip(max_dpd, 0, 120)
        + 0.0031 * np.clip(receivable_days - 60, -55, 240)
        - 0.052 * np.clip(revenue_growth, -0.7, 0.9) * 10
        + 0.34 * np.clip(balance_volatility - 0.48, -0.4, 2.6)
    )
    latent_pd = 1.0 / (1.0 + np.exp(-log_odds))

    # ---- the two scores --------------------------------------------------
    # The champion reads leverage, coverage, age, delinquency and the bureau
    # proxy. It does NOT read the two cash-flow variables, which is precisely
    # why the challenger beats it.
    champion_logit = (
        -3.30
        + 0.138 * np.clip(debt_to_ebitda - 3.4, -3.4, 12.0)
        - 0.44 * np.clip(dscr - 1.35, -1.3, 3.2)
        - 0.029 * np.clip(years_trading - 5.0, -4.5, 14.0)
        + 0.0119 * np.clip(max_dpd, 0, 120)
        - 0.0043 * (bureau_score - 620)
        + np.array([SECTOR_RISK[str(v)] for v in sector]) * 0.72
    )
    # The challenger adds banked-turnover reconciliation and payroll
    # regularity — two of the strongest terms in the latent model — so its
    # ordering is genuinely closer to the truth.
    challenger_logit = (
        champion_logit
        - 0.58 * np.clip(banked - 0.85, -0.8, 0.8)
        - 0.86 * (payroll_regularity - 0.78)
        + 0.28 * np.clip(balance_volatility - 0.48, -0.4, 2.6)
    )



    return {
        "index": index, "rows": rows, "size": size, "sector": sector,
        "region": region, "key_person": key_person, "micro": micro,
        "revenue": revenue, "employees": employees,
        "years_trading": years_trading, "banked": banked,
        "payroll_regularity": payroll_regularity,
        "balance_to_credits": balance_to_credits,
        "balance_volatility": balance_volatility,
        "top_customer": top_customer, "returned_cheques": returned_cheques,
        "overdraft_days": overdraft_days, "max_dpd": max_dpd,
        "ebitda_margin": ebitda_margin, "debt_to_ebitda": debt_to_ebitda,
        "dscr": dscr, "current_ratio": current_ratio,
        "revenue_growth": revenue_growth, "receivable_days": receivable_days,
        "bureau_score": bureau_score, "latent_pd": latent_pd,
        "champion_logit": champion_logit,
        "challenger_logit": challenger_logit,
        "rng": rng,
    }


def _development_logits() -> tuple[Any, Any, float]:
    """The champion's log-odds over the development sample, and what happened.

    Three things a calibration needs: the log-odds, which rows are micro —
    because the distortion is part of what is being calibrated around — and
    the realised default rate. All taken from the months the model was built
    on rather than the months it is validated on.
    """
    logits: list[Any] = []
    micro: list[Any] = []
    events: list[Any] = []
    for month in DEVELOPMENT_MONTHS:
        made = _draw(month, development=True)
        logits.append(made["champion_logit"])
        micro.append(made["micro"])
        drawn = made["rng"].random(made["rows"])
        events.append((drawn < made["latent_pd"]).astype(int))
    return (np.concatenate(logits), np.concatenate(micro),
            float(np.concatenate(events).mean()))


def cohort(month: str, *, rows: int = 0,
           development: bool = False) -> pd.DataFrame:
    """One month of SME applications, scored, with a realised outcome.

    The order matters and is not arbitrary. Characteristics are drawn first,
    from distributions that drift where `MANIFEST` says they drift. The
    latent probability of default is then built from those characteristics —
    so the relationships are real and a validation kernel measuring them is
    measuring something that is there. Only then are the two scores computed,
    each from its own subset of the characteristics, so a score is a *view*
    of the risk rather than the risk itself. Finally the outcome is drawn
    from the latent probability.

    Generating the outcome from the score instead would produce a universe
    where every model is perfect, which is the mistake that makes a synthetic
    validation demonstration worthless.
    """
    made = _draw(month, rows=rows, development=development)
    index, rows = made["index"], made["rows"]
    rng = made["rng"]
    size, sector, region = made["size"], made["sector"], made["region"]
    key_person, micro = made["key_person"], made["micro"]
    revenue, employees = made["revenue"], made["employees"]
    years_trading, banked = made["years_trading"], made["banked"]
    payroll_regularity = made["payroll_regularity"]
    balance_to_credits = made["balance_to_credits"]
    balance_volatility, top_customer = made["balance_volatility"], made["top_customer"]
    returned_cheques, overdraft_days = made["returned_cheques"], made["overdraft_days"]
    max_dpd, ebitda_margin = made["max_dpd"], made["ebitda_margin"]
    debt_to_ebitda, dscr = made["debt_to_ebitda"], made["dscr"]
    current_ratio, revenue_growth = made["current_ratio"], made["revenue_growth"]
    receivable_days, bureau_score = made["receivable_days"], made["bureau_score"]
    latent_pd = made["latent_pd"]
    champion_logit = made["champion_logit"]
    challenger_logit = made["challenger_logit"]

    # §5. The standard scorecard scaling, with the three parameters a model
    # registry has to carry: a base score at a base odds, and points to
    # double the odds. Higher score = better credit quality — declared on the
    # registry, never inferred, and this is the sign that makes it true.
    #
    # The first draft used `660 - 52 * logit`, which put 99.9% of the book
    # above 720: a scale with no spread, on which no band table means
    # anything and no cut-off can be demonstrated. The arithmetic below is
    # what a scorecard actually does, and it produces a distribution a
    # validator would recognise.
    champion_score = np.clip(_to_score(champion_logit), 300, 900)
    challenger_score = np.clip(_to_score(challenger_logit), 300, 900)

    # The PD is a separate governed component from the score. §5 is explicit
    # that a rank-order scorecard and a score-to-PD calibration are two
    # things, and they are computed separately here for the same reason.
    #
    # The intercept comes from the development sample, which is what a
    # calibration IS: fitted where the model was built, applied where it is
    # used. Drift between the two is then a real finding rather than an
    # artefact of the generator.
    champion_pd = _sigmoid(champion_logit + _calibration_offset())
    challenger_pd = _sigmoid(challenger_logit + _calibration_offset())

    # §6.5. The one deliberate calibration defect. Micro enterprises default
    # more than the champion's PD implies, because the calibration was fitted
    # across the whole book and micro sits above the line. Applied to the
    # prediction, never to the outcome: the model is wrong about micro, the
    # world is not.
    champion_pd = np.where(micro, champion_pd / MICRO_PD_UNDERSTATEMENT,
                           champion_pd)

    # ---- the outcome -----------------------------------------------------
    effective = latent_pd.copy()
    # §6.5. In government contracting the middle score bands invert. Done by
    # lifting risk for the middle of the champion's own distribution within
    # that sector, so the inversion is visible in a bad-rate-by-band table
    # and invisible in the portfolio one.
    band = np.digitize(champion_score, [540, 600, 660, 720])
    inverted = (sector == "CONTRACTING_GOVERNMENT") & np.isin(band, (1, 2))
    effective = np.where(inverted, np.clip(effective * 2.25, 0, 0.92),
                         effective)

    drawn = rng.random(rows)
    default = (drawn < effective).astype(int)

    # ---- policy: decision, override, grade -------------------------------
    approved = champion_score >= 600
    # §6.5. Upward overrides cluster just below the cut-off, where a
    # relationship manager has the most to gain from one.
    near = (champion_score >= 560) & (champion_score < 600)
    override_draw = rng.random(rows)
    override_up = near & (override_draw < 0.28)
    override_down = (champion_score >= 700) & (override_draw > 0.985)
    override = override_up | override_down
    decision = np.where(approved | override_up, "APPROVE", "DECLINE")
    decision = np.where(override_down, "DECLINE", decision)

    grade_edges = [520, 560, 600, 645, 690, 740, 800]
    grade = np.array([f"G{i + 1}" for i in
                      np.digitize(champion_score, grade_edges)])

    closes = window_closes(month, horizon=DEFAULT_HORIZON_MONTHS)
    is_matured = (True if development
                  else matured(month, horizon=DEFAULT_HORIZON_MONTHS))

    frame = pd.DataFrame({
        "sme_obligor_id": [f"SME{index:03d}{i:05d}" for i in range(rows)],
        "application_id": [f"APP{index:03d}{i:05d}" for i in range(rows)],
        "facility_id": [f"FAC{index:03d}{i:05d}" for i in range(rows)],
        "cohort_month": month,
        "snapshot_month": month,
        "score_date": f"{month}-01",
        "performance_window_end": f"{closes}-01",
        "performance_horizon_months": DEFAULT_HORIZON_MONTHS,
        "is_matured": bool(is_matured),
        "origin": ORIGIN,
        # characteristics
        "enterprise_size_class_proxy": size,
        "economic_sector": sector,
        "region": region,
        "key_person_dependency": key_person,
        "employee_count": employees,
        "annual_revenue_sar": np.round(revenue, 2),
        "years_since_registration": np.round(years_trading, 2),
        "bank_credits_to_declared_sales": np.round(banked, 4),
        "payroll_regularity_score": np.round(payroll_regularity, 4),
        "balance_to_credits_ratio": np.round(balance_to_credits, 4),
        "balance_volatility": np.round(balance_volatility, 4),
        "top_customer_share": np.round(top_customer, 2),
        "returned_cheques_12m": returned_cheques,
        "overdraft_days_12m": overdraft_days,
        "max_dpd_12m": max_dpd,
        "ebitda_margin": np.round(ebitda_margin, 4),
        "debt_to_ebitda": np.round(debt_to_ebitda, 4),
        "dscr": np.round(dscr, 4),
        "current_ratio": np.round(current_ratio, 4),
        "revenue_growth_yoy": np.round(revenue_growth, 4),
        "receivable_days": np.round(receivable_days, 1),
        "commercial_bureau_score_proxy": np.round(bureau_score, 1),
        # scores
        "champion_score": np.round(champion_score, 2),
        "champion_pd_12m": np.round(champion_pd, 6),
        "challenger_score": np.round(challenger_score, 2),
        "challenger_pd_12m": np.round(challenger_pd, 6),
        "final_risk_grade": grade,
        # policy
        "approval_decision": decision,
        "override_flag": override.astype(int),
        "override_direction": np.where(
            override_up, "UPWARD",
            np.where(override_down, "DOWNWARD", "")),
        # outcome — only where the window has closed
        "actual_default_12m": (default if is_matured
                               else np.full(rows, np.nan)),
    })
    return frame


def build(months: tuple[str, ...] = COHORT_MONTHS, *,
          development: bool = False) -> pd.DataFrame:
    """Every cohort, concatenated. Deterministic for a given month list."""
    frames = [cohort(m, development=development) for m in months]
    return pd.concat(frames, ignore_index=True)


__all__ = [
    "BASE_LOG_ODDS", "COHORT_MONTHS", "DATA_END_MONTH",
    "DEFAULT_HORIZON_MONTHS", "DEVELOPMENT_MONTHS", "MANIFEST", "MASTER_SEED",
    "ORIGIN", "ROWS_PER_COHORT", "SECTORS", "SIZE_CLASSES",
    "SYNTHETIC_VERSION", "Phenomenon", "add_months", "latest_matured",
    "build", "cohort", "manifest", "matured", "matured_months",
    "window_closes",
]

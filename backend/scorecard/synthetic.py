"""
The retail scorecard demonstration universe. §2, §5-§11, §74, §75.

Realistic synthetic retail data. Not client data, not a real bank's book,
not production. Every row carries `origin = SYNTHETIC_DEMO` and the datasets
are marked synthetic in the catalogue, because the one thing worse than a
demonstration on made-up numbers is a demonstration on made-up numbers
somebody thought were real.

Why it is simulated rather than sampled
----------------------------------------
The module's claim is that scorecard validation can *find* things — that a
falling KS can be traced to a variable, that a calibration break can be
traced to a change in population mix. A claim like that can only be
demonstrated on data where those things are genuinely there to find.

Randomly generated columns give a validator nothing: every metric comes back
flat and every diagnostic comes back "no signal". Hand-tuned answers give it
exactly what somebody decided it should find. So the universe is *simulated*.
Every applicant carries a latent creditworthiness driven by a persistent
month factor, their segment and their channel; every observable variable is
a noisy reading of that latent state; and default falls out of the latent
state through a link. The signal is real, nobody wrote it into a column, and
a diagnostic that finds it has found something that was actually there.

The planted phenomena
----------------------
§74 asks for specific things to be true of the data so tests have something
to detect. They are planted by changing the *generating process* — the
channel mix genuinely shifts, income genuinely goes missing more often, one
variable's loading on the latent state genuinely decays — and never by
writing a metric result anywhere. `MANIFEST` documents them. §2: it is a
non-production diagnostic manifest used only by tests and evaluations, and
it is never handed to a planner before execution.

Determinism
------------
One seed, derived per month and per stream, so regenerating any single month
reproduces it exactly and adding a month does not perturb the ones before it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.scorecard import variables as vars_mod

SYNTHETIC_VERSION = "1.0.0"

#: §2. Every row, every dataset version, every catalogue entry.
ORIGIN = "SYNTHETIC_DEMO"

MASTER_SEED = 20260830

# ------------------------------------------------------------------ periods

#: §5. Twenty-five application months, and outcomes observable a year past
#: the last of them.
APPLICATION_MONTHS: tuple[str, ...] = tuple(
    f"{year}-{month:02d}"
    for year in (2023, 2024, 2025)
    for month in range(1, 13)
)[:25]

#: §6. The behavioral panel runs over the same window.
BEHAVIORAL_MONTHS: tuple[str, ...] = APPLICATION_MONTHS

#: §5. The development sample is *out of time* from every validation month.
#: Fitting the binning on months that are also being validated is the same
#: mistake as recomputing WoE on the validation month, one step earlier.
DEVELOPMENT_MONTHS: tuple[str, ...] = tuple(
    f"2022-{month:02d}" for month in range(1, 13))

#: §5/§6. Configurable, and 12 unless a model specification says otherwise.
DEFAULT_HORIZON_MONTHS = 12

#: §7. The last month for which any outcome exists. Everything after this is
#: raw data with no realised performance.
DATA_END_MONTH = "2026-01"

APPLICATION_ROWS_PER_MONTH = (12_000, 15_000)
BEHAVIORAL_ACCOUNTS = 19_000


def _month_index(month: str) -> int:
    year, part = month.split("-")
    return int(year) * 12 + int(part) - 1


def _month_from_index(index: int) -> str:
    return f"{index // 12}-{index % 12 + 1:02d}"


def add_months(month: str, count: int) -> str:
    return _month_from_index(_month_index(month) + count)


def matured(month: str, *, horizon: int = DEFAULT_HORIZON_MONTHS,
            data_end: str = DATA_END_MONTH) -> bool:
    """§7. Has the performance window for this cohort actually closed?

    The distinction the whole module rests on. A cohort whose window has not
    closed has no realised outcome, so every metric that compares predicted
    against actual is undefined for it — not zero, not optimistic, undefined.
    """
    return _month_index(add_months(month, horizon)) <= _month_index(data_end)


def latest_matured(months: tuple[str, ...] = APPLICATION_MONTHS, *,
                   horizon: int = DEFAULT_HORIZON_MONTHS,
                   data_end: str = DATA_END_MONTH) -> str:
    ready = [m for m in months if matured(m, horizon=horizon,
                                          data_end=data_end)]
    return ready[-1] if ready else ""


def _rng(*parts: Any) -> np.random.Generator:
    """A generator keyed by what it is generating.

    Deriving per stream rather than drawing sequentially from one generator
    means regenerating March does not shift April, which is what makes a
    single month reproducible on its own.
    """
    key = "|".join(str(p) for p in parts).encode("utf-8")
    digest = hashlib.sha256(key).digest()
    seed = int.from_bytes(digest[:8], "big") ^ MASTER_SEED
    return np.random.default_rng(seed)


# ------------------------------------------------------- planted phenomena


@dataclass
class Phenomenon:
    """One thing that is deliberately true of this data."""

    phenomenon_id: str
    scorecard_type: str
    from_month: str
    what: str
    how_it_was_planted: str
    detectable_by: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "phenomenon_id": self.phenomenon_id,
            "scorecard_type": self.scorecard_type,
            "from_month": self.from_month,
            "what": self.what,
            "how_it_was_planted": self.how_it_was_planted,
            "detectable_by": list(self.detectable_by),
        }


APP = vars_mod.APPLICATION_SCORECARD
BEH = vars_mod.BEHAVIORAL_SCORECARD

#: §74. What is deliberately true of this data, and how each was planted.
#:
#: §2: this manifest is for tests and evaluations. It is never given to a
#: planner before execution — a diagnostic that was told the answer is not a
#: diagnostic, and an evaluation against it would measure nothing.
MANIFEST: tuple[Phenomenon, ...] = (
    Phenomenon(
        "APP-CHANNEL-MIX", APP, "2024-05",
        "The digital share of applications roughly doubles, and digital "
        "applicants are younger, thinner-filed and modestly riskier.",
        "The channel mixing weights change from month 16 onward. Nothing "
        "about any variable's relationship to risk was touched — the "
        "population changed, not the model.",
        ("population mix", "score PSI", "CSI on application_channel",
         "calibration by score band")),
    Phenomenon(
        "APP-MISSING-INCOME", APP, "2024-07",
        "Declared income goes missing far more often, concentrated in the "
        "digital channel.",
        "The missingness rate on monthly_income rises from 2% to 12% from "
        "month 18, conditioned on channel.",
        ("missingness trend", "special-bin rate", "CSI on monthly_income")),
    Phenomenon(
        "APP-ENQUIRIES-DECAY", APP, "2024-01",
        "bureau_enquiries_6m stops discriminating. It was a solid predictor "
        "in the development window and is close to noise by the end.",
        "Its loading on the latent creditworthiness decays linearly to near "
        "zero from month 12. The variable is still populated and still "
        "looks healthy on every data-quality check.",
        ("univariate KS trend", "univariate Gini", "IV trend",
         "leave-one-variable-out")),
    Phenomenon(
        "APP-KS-DECLINE", APP, "2024-01",
        "Overall model KS declines moderately over the window rather than "
        "breaking suddenly.",
        "A consequence of APP-ENQUIRIES-DECAY and APP-CHANNEL-MIX, not a "
        "separate intervention. Nothing sets a KS anywhere.",
        ("KS trend", "AUC/Gini trend")),
    Phenomenon(
        "APP-CALIBRATION-DRIFT", APP, "2024-06",
        "Observed default rate runs above average predicted PD after the "
        "channel mix changes.",
        "The digital segment carries a higher latent default intensity that "
        "the frozen development binning does not know about.",
        ("ODR vs PD", "calibration-in-the-large", "Brier", "bucket RMSE")),
    Phenomenon(
        "APP-CHALLENGER-GAIN", APP, "2024-06",
        "The challenger overtakes the incumbent in the second half of the "
        "window.",
        "The challenger uses debt_burden_ratio and bureau_max_dpd_12m in "
        "place of bureau_enquiries_6m, so the decay does not touch it.",
        ("model comparison", "AUC/Gini by month")),
    Phenomenon(
        "BEH-UTILISATION-SHIFT", BEH, "2024-03",
        "Utilisation rises across the book, most sharply on credit cards.",
        "The utilisation process gains a positive drift from month 14.",
        ("CSI on utilisation_pct", "distribution overlay", "score PSI")),
    Phenomenon(
        "BEH-DPD-STRENGTHENS", BEH, "2024-03",
        "max_dpd_6m becomes a markedly stronger predictor than it was at "
        "development.",
        "Its loading on the latent state increases from month 14.",
        ("univariate KS trend", "IV trend", "variable ranking")),
    Phenomenon(
        "BEH-ODR-DETERIORATION", BEH, "2024-08",
        "Observed default rate deteriorates over months 19 to 22 and "
        "partially recovers.",
        "A latent stress factor is applied to those cohorts.",
        ("ODR trend", "ODR vs PD", "actual vs expected")),
    Phenomenon(
        "BEH-INCUMBENT-UNDERPREDICTS", BEH, "2024-08",
        "The behavioral incumbent under-predicts risk during the stress.",
        "A consequence of BEH-ODR-DETERIORATION against a frozen intercept.",
        ("calibration-in-the-large", "expected vs observed defaults")),
    Phenomenon(
        "BEH-RECALIBRATION-HELPS-CALIBRATION-ONLY", BEH, "2024-08",
        "The recalibrated candidate fixes the level and barely moves rank "
        "ordering.",
        "It refits the intercept and a single slope on the same WoE inputs, "
        "so it cannot change the ordering it was given.",
        ("model comparison", "calibration vs discrimination")),
)


def manifest() -> dict[str, Any]:
    return {
        "synthetic_version": SYNTHETIC_VERSION,
        "origin": ORIGIN,
        "phenomena": [p.to_dict() for p in MANIFEST],
        "not_for_planners": (
            "§2: this manifest exists for tests and evaluations. It is never "
            "given to a planner before execution. A diagnostic that was told "
            "the answer is not a diagnostic."),
        "nothing_here_sets_a_metric": (
            "Every phenomenon was planted by changing the generating "
            "process. No metric value is written anywhere in this module."),
    }


# ------------------------------------------------------ categorical levels

EMPLOYER_TYPES = ("GOVERNMENT", "SEMI_GOVERNMENT", "LARGE_CORPORATE",
                  "SME", "SELF_EMPLOYED")
SECTORS = ("PUBLIC_ADMIN", "OIL_AND_GAS", "BANKING", "CONSTRUCTION",
           "RETAIL_TRADE", "HOSPITALITY", "HEALTHCARE", "EDUCATION",
           "LOGISTICS", "TECHNOLOGY")
MARITAL = ("SINGLE", "MARRIED", "DIVORCED", "WIDOWED")
HOUSING = ("OWNED", "MORTGAGED", "RENTED", "COMPANY_PROVIDED")
CHANNELS = ("BRANCH", "DIGITAL", "BROKER", "TELESALES", "PARTNER")
PRODUCTS = ("PERSONAL_LOAN", "AUTO_LOAN", "CREDIT_CARD", "MORTGAGE")
SEGMENTS = ("MASS", "AFFLUENT", "PRIORITY", "PRIVATE")
BEHAVIORAL_PRODUCTS = ("CREDIT_CARD", "OVERDRAFT", "PERSONAL_LOAN",
                       "AUTO_LOAN")

#: The channel mix before and after APP-CHANNEL-MIX.
CHANNEL_MIX_EARLY = (0.34, 0.24, 0.18, 0.14, 0.10)
CHANNEL_MIX_LATE = (0.24, 0.44, 0.14, 0.10, 0.08)
CHANNEL_MIX_MONTH = 16

#: The missingness step of APP-MISSING-INCOME.
MISSING_INCOME_EARLY = 0.02
MISSING_INCOME_LATE = 0.12
MISSING_INCOME_MONTH = 18

#: APP-ENQUIRIES-DECAY: the month the decay starts and the month it is done.
ENQUIRY_DECAY_FROM = 12
ENQUIRY_DECAY_TO = 24

#: Channel effects on latent creditworthiness. Digital is modestly riskier
#: and thinner-filed; broker riskier still. These are properties of the
#: population, not of any model.
CHANNEL_LATENT: dict[str, float] = {
    "BRANCH": 0.10, "DIGITAL": -0.18, "BROKER": -0.26,
    "TELESALES": -0.05, "PARTNER": 0.02,
}
SEGMENT_LATENT: dict[str, float] = {
    "MASS": -0.12, "AFFLUENT": 0.14, "PRIORITY": 0.34, "PRIVATE": 0.55,
}

#: The link from latent creditworthiness to default. Tuned so the
#: development window lands near a 4% twelve-month default rate, which is a
#: plausible unsecured retail number and leaves enough bads to measure.
DEFAULT_INTERCEPT = -3.25
DEFAULT_SLOPE = -0.95


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _pick(rng: np.random.Generator, levels: tuple[str, ...], n: int,
          weights: tuple[float, ...] | None = None) -> np.ndarray:
    probabilities = None
    if weights is not None:
        total = float(sum(weights))
        probabilities = [w / total for w in weights]
    return rng.choice(np.array(levels, dtype=object), size=n,
                      p=probabilities)


# ---------------------------------------------------- application universe


def _channel_weights(offset: int) -> tuple[float, ...]:
    """The mix, shifting over three months rather than in one step.

    A step change in a single month is detectable by anything. A shift over
    a quarter is what an actual channel strategy looks like and is a fairer
    test of a drift diagnostic.
    """
    if offset < CHANNEL_MIX_MONTH:
        return CHANNEL_MIX_EARLY
    ramp = min((offset - CHANNEL_MIX_MONTH + 1) / 3.0, 1.0)
    return tuple(early + (late - early) * ramp
                 for early, late in zip(CHANNEL_MIX_EARLY, CHANNEL_MIX_LATE,
                                        strict=True))


def _enquiry_loading(offset: int) -> float:
    """APP-ENQUIRIES-DECAY, as a loading that decays with time."""
    if offset <= ENQUIRY_DECAY_FROM:
        return 1.0
    if offset >= ENQUIRY_DECAY_TO:
        return 0.05
    span = ENQUIRY_DECAY_TO - ENQUIRY_DECAY_FROM
    return 1.0 - 0.95 * (offset - ENQUIRY_DECAY_FROM) / span


def application_month(month: str, *, offset: int,
                      rows: int | None = None) -> pd.DataFrame:
    """One month of applications, with realised twelve-month outcomes.

    `offset` is the month's position in the simulated timeline, which is
    what the planted phenomena key off. Development months carry negative
    offsets so nothing planted in the validation window leaks backwards
    into the population the binning was fitted on.
    """
    rng = _rng("application", month)
    if rows is None:
        low, high = APPLICATION_ROWS_PER_MONTH
        rows = int(rng.integers(low, high + 1))

    channel = _pick(rng, CHANNELS, rows, _channel_weights(offset))
    segment = _pick(rng, SEGMENTS, rows, (0.58, 0.24, 0.13, 0.05))
    product = _pick(rng, PRODUCTS, rows, (0.42, 0.26, 0.24, 0.08))

    # The latent state. One persistent month factor shared by everybody,
    # plus what the applicant's channel and segment say about them.
    month_factor = float(_rng("app-cycle", month).normal(0.0, 0.11))
    latent = (
        rng.normal(0.0, 1.0, rows)
        + np.array([CHANNEL_LATENT[c] for c in channel])
        + np.array([SEGMENT_LATENT[s] for s in segment])
        + month_factor
    )

    def reading(strength: float, noise: float = 1.0) -> np.ndarray:
        """A noisy observation of the latent state."""
        return strength * latent + rng.normal(0.0, noise, rows)

    age = np.clip(np.round(31 + 9 * reading(0.30) + rng.normal(0, 6, rows)),
                  21, 68)
    income_latent = reading(0.62, 0.85)
    income = np.round(np.clip(np.exp(9.05 + 0.42 * income_latent), 3_500,
                              180_000), 2)
    tenure = np.clip(np.round(34 + 22 * reading(0.42)), 0, 420)
    residency = np.clip(np.round(58 + 34 * reading(0.24)), 3, 600)
    dependants = np.clip(np.round(2.0 - 0.55 * reading(0.20)
                                  + rng.normal(0, 0.8, rows)), 0, 9)
    rent = np.round(np.clip(income * rng.uniform(0.10, 0.34, rows), 0,
                            90_000), 2)

    obligations = np.round(np.clip(
        income * np.clip(0.31 - 0.075 * reading(0.55), 0.02, 0.85), 0,
        150_000), 2)
    dbr = np.round(np.clip(obligations / np.maximum(income, 1.0), 0.0, 1.6), 4)

    requested = np.round(np.clip(
        income * np.clip(7.5 + 2.4 * rng.normal(0, 1, rows), 0.7, 34.0),
        5_000, 3_000_000), 2)
    tenor = np.clip(np.round(rng.choice([12, 24, 36, 48, 60, 84, 120],
                                        size=rows,
                                        p=[.08, .16, .26, .21, .17, .08, .04])
                             ).astype(float), 12, 300)
    down_payment = np.round(np.clip(
        14.0 + 7.5 * reading(0.30) + rng.normal(0, 5, rows), 0, 60), 2)
    lti = np.round(np.clip(requested / np.maximum(income * 12.0, 1.0),
                           0.02, 12.0), 4)

    bureau = np.clip(np.round(640 + 62 * reading(0.78, 0.7)), 300, 900)
    outstanding = np.round(np.clip(
        np.exp(9.4 - 0.36 * reading(0.44)) , 0, 4_000_000), 2)
    active_accounts = np.clip(np.round(3.4 - 0.5 * reading(0.24)
                                       + rng.normal(0, 1.4, rows)), 0, 22)
    delinquent = rng.poisson(np.clip(0.42 - 0.20 * reading(0.60), 0.01, 4.5))
    max_dpd = np.clip(np.round(
        np.where(delinquent > 0,
                 rng.gamma(2.1, 16.0, rows) * (1 + 0.25 * delinquent), 0.0)),
        0, 360)

    # APP-ENQUIRIES-DECAY. The loading, not the values, is what changes.
    # A load-bearing predictor at development, so its decay actually costs
    # the incumbent something. At a weaker loading the incumbent barely
    # leans on it, the decay changes almost nothing, and the challenger
    # never overtakes — which is a phenomenon the manifest claims.
    enquiries = rng.poisson(np.clip(
        1.35 - 0.62 * _enquiry_loading(offset) * reading(1.20), 0.03, 9.0))
    oldest_trade = np.clip(np.round(76 + 33 * reading(0.30)), 0, 480)
    utilisation = np.round(np.clip(
        44.0 - 12.5 * reading(0.52) + rng.normal(0, 12, rows), 0, 155), 2)
    relationship = np.clip(np.round(28 + 22 * reading(0.26)), 0, 480)
    salary_transfer = (reading(0.42) + rng.normal(0, 0.6, rows) > -0.1
                       ).astype(np.int8)

    frame = pd.DataFrame({
        "application_id": [f"APP-{month.replace('-', '')}-{i:06d}"
                           for i in range(rows)],
        "customer_id": [f"CUS-{int(v):09d}"
                        for v in rng.integers(1, 4_000_000, rows)],
        "application_month": month,
        "origin": ORIGIN,
        "applicant_age": age.astype(np.int16),
        "monthly_income": income.astype(np.float32),
        "employment_tenure_months": tenure.astype(np.int16),
        "employer_type": _pick(rng, EMPLOYER_TYPES, rows,
                               (0.19, 0.14, 0.27, 0.28, 0.12)),
        "employment_sector": _pick(rng, SECTORS, rows),
        "residency_tenure_months": residency.astype(np.int16),
        "marital_status": _pick(rng, MARITAL, rows, (0.34, 0.55, 0.08, 0.03)),
        "number_of_dependants": dependants.astype(np.int8),
        "housing_status": _pick(rng, HOUSING, rows, (0.12, 0.21, 0.55, 0.12)),
        "monthly_rent": rent.astype(np.float32),
        "existing_total_monthly_obligations": obligations.astype(np.float32),
        "debt_burden_ratio": dbr.astype(np.float32),
        "requested_amount": requested.astype(np.float32),
        "requested_tenor_months": tenor.astype(np.int16),
        "down_payment_pct": down_payment.astype(np.float32),
        "loan_to_income": lti.astype(np.float32),
        "bureau_score": bureau.astype(np.int16),
        "bureau_total_outstanding": outstanding.astype(np.float32),
        "bureau_active_accounts": active_accounts.astype(np.int8),
        "bureau_delinquent_accounts_12m": np.clip(delinquent, 0,
                                                  30).astype(np.int8),
        "bureau_max_dpd_12m": max_dpd.astype(np.int16),
        "bureau_enquiries_6m": np.clip(enquiries, 0, 40).astype(np.int8),
        "bureau_oldest_trade_months": oldest_trade.astype(np.int16),
        "credit_card_utilisation": utilisation.astype(np.float32),
        "existing_bank_relationship_months": relationship.astype(np.int16),
        "salary_transfer_flag": salary_transfer,
        "application_channel": channel,
        "product_type": product,
        "customer_segment": segment,
    })

    # APP-MISSING-INCOME. Concentrated in digital, which is what makes it a
    # real diagnostic rather than a uniform sprinkle.
    rate = (MISSING_INCOME_LATE if offset >= MISSING_INCOME_MONTH
            else MISSING_INCOME_EARLY)
    weight = np.where(channel == "DIGITAL", 2.1, 0.55)
    drop = rng.random(rows) < np.clip(rate * weight, 0, 0.85)
    frame.loc[drop, "monthly_income"] = np.nan
    frame.loc[drop, "debt_burden_ratio"] = np.nan
    frame.loc[drop, "loan_to_income"] = np.nan

    # The outcome. Latent state through the link, plus the segment stress
    # that APP-CALIBRATION-DRIFT relies on.
    stress = 0.0
    if offset >= CHANNEL_MIX_MONTH:
        stress = 0.22 * np.where(channel == "DIGITAL", 1.0, 0.15)
    probability = _sigmoid(DEFAULT_INTERCEPT + DEFAULT_SLOPE * latent + stress)
    frame["default_probability_truth"] = probability.astype(np.float32)
    frame["actual_default"] = (rng.random(rows) < probability).astype(np.int8)
    frame["performance_window_end"] = add_months(month,
                                                 DEFAULT_HORIZON_MONTHS)
    frame["matured_flag"] = matured(month)
    frame["performance_horizon_months"] = DEFAULT_HORIZON_MONTHS
    if not frame["matured_flag"].iloc[0]:
        # §7: an immature cohort has no realised outcome. Leaving a 0 there
        # would be read as "did not default", which is the single most
        # damaging thing this dataset could imply.
        frame["actual_default"] = pd.NA
    return frame


def application_development() -> pd.DataFrame:
    """The out-of-time development reference the binning is fitted on."""
    frames = [application_month(month, offset=-len(DEVELOPMENT_MONTHS) + i,
                                rows=9_000)
              for i, month in enumerate(DEVELOPMENT_MONTHS)]
    return pd.concat(frames, ignore_index=True)


# ----------------------------------------------------- behavioral universe

UTILISATION_DRIFT_MONTH = 14
DPD_STRENGTHEN_MONTH = 14
STRESS_MONTHS = range(19, 23)


def _behavioral_population(rng: np.random.Generator) -> pd.DataFrame:
    """The panel. One row per account, carried across every snapshot.

    §6: a longitudinal panel rather than 25 unrelated samples. An account
    that was risky in March is the same account in April, which is what
    makes vintage analysis and a behavioral outcome mean anything.
    """
    n = BEHAVIORAL_ACCOUNTS
    quality = rng.normal(0.0, 1.0, n)
    opened = rng.integers(-72, 0, n)
    return pd.DataFrame({
        "customer_id": [f"CUS-{int(v):09d}"
                        for v in rng.integers(1, 4_000_000, n)],
        "account_id": [f"ACC-{i:08d}" for i in range(n)],
        "product": _pick(rng, BEHAVIORAL_PRODUCTS, n, (0.46, 0.16, 0.28, .10)),
        "quality": quality,
        "opened_offset": opened,
        "credit_limit": np.round(np.clip(
            np.exp(9.8 + 0.40 * quality), 2_000, 500_000), 2),
        "limit_seed": rng.random(n),
    })


def behavioral_month(month: str, *, offset: int,
                     panel: pd.DataFrame) -> pd.DataFrame:
    """One monthly snapshot of the behavioral panel."""
    rng = _rng("behavioral", month)
    active = panel[panel["opened_offset"] <= offset].reset_index(drop=True)
    n = len(active)
    quality = active["quality"].to_numpy()

    month_factor = float(_rng("beh-cycle", month).normal(0.0, 0.10))
    stress = 0.55 if offset in STRESS_MONTHS else 0.0
    latent = quality + month_factor + rng.normal(0.0, 0.42, n) - stress * 0.35

    def reading(strength: float, noise: float = 1.0) -> np.ndarray:
        return strength * latent + rng.normal(0.0, noise, n)

    months_on_book = np.clip(offset - active["opened_offset"].to_numpy(),
                             0, 400)
    limit = active["credit_limit"].to_numpy()

    # BEH-UTILISATION-SHIFT: a genuine drift in the utilisation process.
    drift = 0.0 if offset < UTILISATION_DRIFT_MONTH else min(
        (offset - UTILISATION_DRIFT_MONTH + 1) * 1.6, 14.0)
    card = (active["product"].to_numpy() == "CREDIT_CARD")
    utilisation = np.clip(
        46.0 - 13.5 * reading(0.58) + drift * np.where(card, 1.4, 0.5)
        + rng.normal(0, 9, n), 0.0, 148.0)
    balance = np.round(limit * utilisation / 100.0, 2)

    # BEH-DPD-STRENGTHENS: the loading rises, the variable does not change
    # in any way a data-quality check would notice.
    dpd_loading = 1.0 if offset < DPD_STRENGTHEN_MONTH else min(
        1.0 + 0.11 * (offset - DPD_STRENGTHEN_MONTH), 2.3)
    # Severity is what the latent state drives, and the loading scales how
    # hard it drives it. Both the incidence of delinquency and how bad it
    # gets read off the same severity, which is why raising the loading
    # makes the variable genuinely more discriminating rather than merely
    # noisier — the alternative, adding independent gamma noise on top,
    # raises the mean and leaves the ranking where it was.
    severity = -dpd_loading * reading(0.72)
    dpd_intensity = np.clip(0.45 + 0.30 * severity, 0.01, 6.0)
    gate = _sigmoid(1.15 * severity - 2.05)
    days = np.round(np.clip(
        rng.gamma(2.0, 8.0, n) * (1.0 + 0.85 * np.clip(severity, 0, None)),
        0, 360))
    current_dpd = np.where(rng.random(n) < gate, days, 0.0)
    max_dpd_3m = np.where(rng.random(n) < gate * 1.45,
                          np.maximum(current_dpd, days * 1.15), current_dpd)
    max_dpd_6m = np.where(rng.random(n) < gate * 1.9,
                          np.maximum(max_dpd_3m, days * 1.35), max_dpd_3m)

    payment_ratio = np.clip(0.42 + 0.20 * reading(0.55)
                            + rng.normal(0, 0.14, n), 0.0, 3.2)
    if offset >= UTILISATION_DRIFT_MONTH:
        payment_ratio = np.clip(payment_ratio - 0.018
                                * (offset - UTILISATION_DRIFT_MONTH), 0, 3.2)

    frame = pd.DataFrame({
        "account_id": active["account_id"],
        "customer_id": active["customer_id"],
        "observation_month": month,
        "origin": ORIGIN,
        "product": active["product"],
        "vintage": [f"V{2019 + int((o + 72) // 12)}"
                    for o in active["opened_offset"]],
        "months_on_book": months_on_book.astype(np.int16),
        "current_balance": balance.astype(np.float32),
        "credit_limit": limit.astype(np.float32),
        "available_limit": np.round(np.maximum(limit - balance, 0.0),
                                    2).astype(np.float32),
        "utilisation_pct": np.round(utilisation, 2).astype(np.float32),
        "average_utilisation_3m": np.round(
            np.clip(utilisation + rng.normal(0, 3.5, n), 0, 150),
            2).astype(np.float32),
        "average_utilisation_6m": np.round(
            np.clip(utilisation + rng.normal(0, 5.0, n), 0, 150),
            2).astype(np.float32),
        "max_utilisation_6m": np.round(
            np.clip(utilisation + np.abs(rng.normal(0, 7.5, n)), 0, 165),
            2).astype(np.float32),
        "current_dpd": np.clip(current_dpd, 0, 360).astype(np.int16),
        "max_dpd_3m": np.clip(max_dpd_3m, 0, 360).astype(np.int16),
        "max_dpd_6m": np.clip(max_dpd_6m, 0, 360).astype(np.int16),
        "times_dpd_30plus_6m": rng.poisson(
            np.clip(dpd_intensity * 0.42, 0, 6)).astype(np.int8),
        "times_dpd_60plus_12m": rng.poisson(
            np.clip(dpd_intensity * 0.22, 0, 6)).astype(np.int8),
        "payment_ratio_latest": np.round(payment_ratio,
                                         4).astype(np.float32),
        "average_payment_ratio_3m": np.round(
            np.clip(payment_ratio + rng.normal(0, 0.07, n), 0, 3.2),
            4).astype(np.float32),
        "minimum_payment_ratio_6m": np.round(
            np.clip(payment_ratio - np.abs(rng.normal(0, 0.11, n)), 0, 3.2),
            4).astype(np.float32),
        "cash_advance_ratio_3m": np.round(np.clip(
            0.06 - 0.035 * reading(0.40) + rng.normal(0, 0.04, n), 0, 1.0),
            4).astype(np.float32),
        "transaction_count_3m": np.clip(np.round(
            26 + 9 * reading(0.34) + rng.normal(0, 7, n)),
            0, 400).astype(np.int16),
        "transaction_amount_3m": np.round(np.clip(
            np.exp(8.6 + 0.32 * reading(0.36)), 0, 900_000),
            2).astype(np.float32),
        "salary_credit_stability": np.round(np.clip(
            0.78 + 0.16 * reading(0.46) + rng.normal(0, 0.10, n), 0, 1),
            4).astype(np.float32),
        "inflow_outflow_ratio": np.round(np.clip(
            1.03 + 0.16 * reading(0.42) + rng.normal(0, 0.12, n), 0, 4),
            4).astype(np.float32),
        "balance_growth_3m": np.round(np.clip(
            2.4 - 4.5 * reading(0.30) + rng.normal(0, 8, n), -95, 320),
            2).astype(np.float32),
        "missed_payment_count_6m": rng.poisson(
            np.clip(dpd_intensity * 0.36, 0, 6)).astype(np.int8),
        "overlimit_count_6m": rng.poisson(
            np.clip(np.maximum(utilisation - 92, 0) / 26.0, 0, 6)
        ).astype(np.int8),
        "bureau_score_latest": np.clip(np.round(
            648 + 57 * reading(0.70, 0.75)), 300, 900).astype(np.int16),
        "bureau_score_change_6m": np.round(np.clip(
            1.2 + 8.5 * reading(0.30) + rng.normal(0, 11, n), -180, 180),
            1).astype(np.float32),
        "bureau_enquiries_6m": rng.poisson(
            np.clip(1.15 - 0.42 * reading(0.44), 0.02, 9)).astype(np.int8),
        "external_delinquency_flag": (
            reading(0.55) + rng.normal(0, 0.8, n) < -1.35).astype(np.int8),
        "restructure_flag": (
            reading(0.62) + rng.normal(0, 0.9, n) < -1.75).astype(np.int8),
        "collections_contact_count_3m": rng.poisson(
            np.clip(dpd_intensity * 0.55, 0, 9)).astype(np.int8),
        "promise_to_pay_broken_count_6m": rng.poisson(
            np.clip(dpd_intensity * 0.20, 0, 6)).astype(np.int8),
    })

    probability = _sigmoid(-3.05 - 1.02 * latent + (0.42 if stress else 0.0))
    frame["default_probability_truth"] = probability.astype(np.float32)
    frame["actual_default"] = (rng.random(n) < probability).astype(np.int8)
    frame["performance_window_end"] = add_months(month,
                                                 DEFAULT_HORIZON_MONTHS)
    frame["matured_flag"] = matured(month)
    frame["performance_horizon_months"] = DEFAULT_HORIZON_MONTHS
    if not frame["matured_flag"].iloc[0]:
        frame["actual_default"] = pd.NA
    return frame


def behavioral_development() -> pd.DataFrame:
    panel = _behavioral_population(_rng("behavioral-panel", "development"))
    frames = []
    for i, month in enumerate(DEVELOPMENT_MONTHS):
        offset = -len(DEVELOPMENT_MONTHS) + i
        chunk = behavioral_month(month, offset=offset, panel=panel)
        frames.append(chunk.sample(frac=0.55, random_state=7 + i))
    return pd.concat(frames, ignore_index=True)


def behavioral_panel() -> pd.DataFrame:
    return _behavioral_population(_rng("behavioral-panel", "live"))


# ---------------------------------------------------------------- counting


@dataclass
class Counts:
    """What was actually generated. §91 reports these rather than the plan."""

    scorecard_type: str
    months: list[str] = field(default_factory=list)
    rows_by_month: dict[str, int] = field(default_factory=dict)
    defaults_by_month: dict[str, int] = field(default_factory=dict)
    matured_months: list[str] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return sum(self.rows_by_month.values())

    @property
    def smallest_month(self) -> int:
        return min(self.rows_by_month.values()) if self.rows_by_month else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scorecard_type": self.scorecard_type,
            "months": list(self.months),
            "month_count": len(self.months),
            "total_rows": self.total_rows,
            "rows_by_month": dict(self.rows_by_month),
            "defaults_by_month": dict(self.defaults_by_month),
            "smallest_month_rows": self.smallest_month,
            "matured_months": list(self.matured_months),
            "latest_data_month": self.months[-1] if self.months else "",
            "latest_matured_month": (self.matured_months[-1]
                                     if self.matured_months else ""),
            "origin": ORIGIN,
        }

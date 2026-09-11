"""
The Forward Risk Signal's inputs, for a retail book.

What was on screen
------------------
`/early-warning` — a top-level navigation item — described six families of
retail signal in detail:

    Repayment behaviour: days past due, missed payments, how much of what fell
    due was paid, and — on a card — utilisation, minimum-payment-only months
    and cash advances.

    Affordability and income: verified income against total credit
    obligations, disposable income, and whether the salary is still arriving
    on time.

and then said, three times: **"No model fitted for this transition yet. An
administrator can fit one in the Model Lab."** Pressing fit answered *"The
Forward Risk Signal needs at least three reporting periods"* on a book with
twenty-five months in it.

The cause is that only the DESCRIPTIONS were converted. The fifteen factors
behind them were covenant headroom, internal-grade notches, debt service
coverage, news sentiment and sector cycle beta, read from `portfolio_facility`
— a corporate dataset this installation does not hold. So the screen promised
retail signals it could not compute, over a book it could not read, and
reported that as nobody having got round to fitting a model.

This module is the other half of that conversion: sixteen factors on
`retail_facility_month`, in the same six family slots, every one of them a
published column of the book the rest of the product reads.

What is deliberately not here
------------------------------
No factor is invented to fill a slot. Where the corporate set had a covenant
headroom, this has the affordability buffer — the retail question in the same
position — and where it had news sentiment, this has the bureau's own record,
because a retail customer has no press coverage and pretending otherwise would
be a factor with nothing behind it.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

#: The governed book, and how this module addresses it. The names on the right
#: are the ones the Forward Risk Signal engine already uses throughout; the
#: reader renames rather than the engine learning a second vocabulary.
DATASET = "retail_facility_month"
KEY = "facility_id"
PERIOD_FIELD = "reporting_month"

#: Retail columns presented under the names the signal engine reads.
RENAMED: dict[str, str] = {
    "facility_id": "account_id",
    "employer_sector": "sector",
    "customer_segment": "segment",
    "ead_base_sar": "ead",
    "reporting_month": "period",
}

#: What a retail facility is called on screen. The engine shows
#: `borrower_name` beside every score; a retail book has no borrower NAME —
#: see the absent-attribute refusal in the Cockpit — so it shows the customer
#: the facility belongs to, which is what identifies it here.
NAME_FROM = "customer_id"


def factors(FactorDef: Any) -> tuple[Any, ...]:
    """The sixteen, built with the engine's own definition type."""
    return (
        # --------------------------------------------------------- behaviour
        FactorDef(
            "utilisation", "behaviour", "Card utilisation",
            "How much of the committed limit is drawn at the reporting date. "
            "On a card this is the first thing to move.",
            ("utilisation_ratio",), "up-is-worse", "%", clip=(0.0, 130.0),
            derived=True,
        ),
        FactorDef(
            "utilisation_change", "behaviour", "Utilisation change",
            "Percentage points of utilisation added over three months. A "
            "customer drawing down is a customer short of cash.",
            ("utilisation_change_3m_pp",), "up-is-worse", "pp",
            clip=(-40.0, 40.0),
        ),
        FactorDef(
            "days_past_due", "behaviour", "Days past due",
            "Days the facility has been in arrears at the reporting date.",
            ("dpd",), "up-is-worse", "days", clip=(0.0, 180.0),
        ),
        FactorDef(
            "missed_payments", "behaviour", "Missed payments",
            "Payments missed in the last three months. A single miss is an "
            "accident; a second is a pattern.",
            ("missed_payment_count_3m",), "up-is-worse", "count",
            clip=(0.0, 6.0),
        ),
        FactorDef(
            "minimum_only", "behaviour", "Minimum-payment-only months",
            "Months in the last three where only the contractual minimum was "
            "paid. A revolver paying the minimum is not repaying.",
            ("minimum_payment_only_months_3m",), "up-is-worse", "months",
            clip=(0.0, 3.0),
        ),
        # ---------------------------------------------------------- capacity
        FactorDef(
            "debt_burden", "capacity", "Debt burden ratio",
            "Total monthly credit obligations as a share of verified monthly "
            "income. The affordability rule this book is written to.",
            ("debt_burden_ratio",), "up-is-worse", "%", clip=(0.0, 120.0),
            derived=True,
        ),
        FactorDef(
            "affordability_buffer", "capacity", "Affordability buffer",
            "Months of the contractual instalment the customer's balance would "
            "cover. The retail equivalent of headroom: what is left after "
            "everything that has to be paid.",
            ("balance_buffer_months",), "up-is-better", "months",
            clip=(0.0, 12.0),
        ),
        FactorDef(
            "salary_interruption", "capacity", "Salary interruptions",
            "Salary cycles missed in the last three months. On a "
            "salary-transfer book this is the earliest capacity signal there "
            "is.",
            ("salary_missed_cycle_count_3m",), "up-is-worse", "count",
            clip=(0.0, 3.0),
        ),
        # --------------------------------------------------- score dynamics
        FactorDef(
            "behavioural_score", "rating_dynamics", "Behavioural score",
            "The current behavioural score. Higher is safer, on the "
            "installation's own 300-900 scale.",
            ("behavioural_score",), "up-is-better", "score",
            clip=(300.0, 900.0),
        ),
        FactorDef(
            "score_move", "rating_dynamics", "Score movement",
            "Points the behavioural score has moved over three months. "
            "Negative is deterioration.",
            ("behavioural_score_change_3m",), "up-is-better", "points",
            clip=(-150.0, 150.0),
        ),
        FactorDef(
            "pd_deterioration", "rating_dynamics", "PD deterioration",
            "The current twelve-month point-in-time PD divided by the PD the "
            "facility was written at. This is the quantity the IFRS 9 "
            "significant-increase test is measured on, so a facility "
            "approaching the threshold is approaching a stage migration by "
            "definition.",
            ("pd_pit_12m_base", "pd_pit_at_origination_12m"), "up-is-worse",
            "x", clip=(0.0, 8.0), derived=True,
            notes="Carries 1.0 where the origination PD is not recorded, "
                  "which leaves the factor carrying no information rather "
                  "than a guess.",
        ),
        # --------------------------------------------------------- structure
        FactorDef(
            "collateral_shortfall", "structure", "Collateral shortfall",
            "Exposure at default less current collateral value, as a share of "
            "exposure. On an unsecured facility it is 100% by construction, "
            "which is the point.",
            ("ead_base_sar", "collateral_value_current_sar"), "up-is-worse",
            "%", clip=(-50.0, 100.0), derived=True,
        ),
        FactorDef(
            "loss_given_default", "structure", "Loss given default",
            "The share of exposure the bank expects to lose if the customer "
            "defaults.",
            ("lgd_base",), "up-is-worse", "%", clip=(0.0, 100.0),
            derived=True,
        ),
        FactorDef(
            "exposure_size", "structure", "Exposure size",
            "Exposure at default on a log scale, so a facility ten times "
            "larger counts as one step rather than ten.",
            ("ead_base_sar",), "up-is-worse", "log SAR", clip=(-3.0, 25.0),
            derived=True,
        ),
        # --------------------------------------------------------- sentiment
        FactorDef(
            "bureau_dpd", "sentiment", "Bureau delinquency",
            "The worst delinquency the bureau reports on obligations this bank "
            "does not hold. Trouble elsewhere arrives here next.",
            ("bureau_external_dpd_max",), "up-is-worse", "days",
            clip=(0.0, 180.0),
        ),
        FactorDef(
            "bureau_enquiries", "sentiment", "Bureau enquiries",
            "Credit enquiries recorded against the customer in six months. "
            "Shopping for credit is what people do before they need it.",
            ("bureau_enquiries_6m",), "up-is-worse", "count", clip=(0.0, 12.0),
        ),
        # ------------------------------------------------------------- cycle
        FactorDef(
            "cycle_exposure", "cycle", "Cycle exposure",
            "The employment sector's historic sensitivity to the credit cycle "
            "multiplied by where the cycle currently sits. Positive means the "
            "economy is currently working against this customer.",
            ("employer_sector",), "up-is-worse", "z", clip=(-4.0, 4.0),
            derived=True,
        ),
    )


#: Columns the reader asks the lake for. Declared rather than inferred, so a
#: factor added without its column fails at read time instead of scoring zero.
READ_FIELDS: tuple[str, ...] = (
    "facility_id", "customer_id", "reporting_month", "ifrs9_stage",
    "employer_sector", "customer_segment", "region", "product_code",
    "ead_base_sar", "gross_carrying_amount_sar",
    "utilisation_ratio", "utilisation_change_3m_pp",
    "dpd", "missed_payment_count_3m", "minimum_payment_only_months_3m",
    "debt_burden_ratio", "balance_buffer_months",
    "salary_missed_cycle_count_3m",
    "behavioural_score", "behavioural_score_change_3m",
    "pd_pit_12m_base", "pd_pit_at_origination_12m",
    "collateral_value_current_sar", "lgd_base",
    "bureau_external_dpd_max", "bureau_enquiries_6m",
    "monitoring_eligible_flag",
)


def _series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        raise KeyError(
            f"The retail factor set needs '{column}', which the frame does "
            "not have. Every factor declares its fields; read them with "
            "READ_FIELDS.")
    return pd.to_numeric(frame[column], errors="coerce")


def compute(frame: pd.DataFrame, definitions: tuple[Any, ...],
            cycle_by_sector: dict[str, float] | None = None) -> pd.DataFrame:
    """One month of the retail book as the factor matrix.

    Every derived factor is computed here and nowhere else, so the sentence a
    reviewer reads on the screen is the arithmetic that ran. A missing value
    becomes the factor's median rather than zero: zero is a real utilisation
    and a real buffer, and scoring "unknown" as "zero" would treat a gap in
    the data as though something were known.
    """
    cycle_by_sector = cycle_by_sector or {}
    out = pd.DataFrame(index=frame.index)

    # Stored as a ratio, read as a percentage — the unit the factor declares.
    out["utilisation"] = _series(frame, "utilisation_ratio") * 100.0
    out["utilisation_change"] = _series(frame, "utilisation_change_3m_pp")
    out["days_past_due"] = _series(frame, "dpd")
    out["missed_payments"] = _series(frame, "missed_payment_count_3m")
    out["minimum_only"] = _series(frame, "minimum_payment_only_months_3m")

    out["debt_burden"] = _series(frame, "debt_burden_ratio") * 100.0
    out["affordability_buffer"] = _series(frame, "balance_buffer_months")
    out["salary_interruption"] = _series(frame, "salary_missed_cycle_count_3m")

    out["behavioural_score"] = _series(frame, "behavioural_score")
    out["score_move"] = _series(frame, "behavioural_score_change_3m")
    origination = _series(frame, "pd_pit_at_origination_12m").clip(lower=1e-6)
    out["pd_deterioration"] = (_series(frame, "pd_pit_12m_base")
                               / origination).fillna(1.0)

    # The reader has already renamed the book's columns to the engine's own
    # vocabulary — see RENAMED — so the two that were renamed are read under
    # their new names here. The factor definitions keep the SOURCE column, so
    # the Trace still shows which published field the number came from.
    ead = _series(frame, "ead" if "ead" in frame.columns else "ead_base_sar")
    collateral = _series(frame, "collateral_value_current_sar").fillna(0.0)
    out["collateral_shortfall"] = np.where(
        ead > 0, 100.0 * (ead - collateral) / ead, 100.0)
    out["loss_given_default"] = _series(frame, "lgd_base") * 100.0
    out["exposure_size"] = np.log1p(ead.clip(lower=0))

    out["bureau_dpd"] = _series(frame, "bureau_external_dpd_max")
    out["bureau_enquiries"] = _series(frame, "bureau_enquiries_6m")

    sector = ("sector" if "sector" in frame.columns
              else "employer_sector" if "employer_sector" in frame.columns
              else "")
    out["cycle_exposure"] = (frame[sector].map(cycle_by_sector).astype(float)
                             if sector else pd.Series(0.0, index=frame.index))

    for definition in definitions:
        column = out[definition.id]
        if definition.clip:
            column = column.clip(*definition.clip)
        median = column.median()
        out[definition.id] = column.fillna(0.0 if pd.isna(median) else median)
    return out[[d.id for d in definitions]]


def read_book(source: Any, period: str) -> pd.DataFrame:
    """One month of the retail book, under the names the engine reads.

    Renamed rather than translated at every call site: the signal engine has
    one vocabulary — `account_id`, `sector`, `ead` — and teaching it a second
    would mean every function downstream knowing which book it was looking at.
    """
    from backend.data_access.protocol import AnalysisContext

    frame = source.fetch(DATASET, context=AnalysisContext(period=period),
                         period=period, fields=list(READ_FIELDS))
    if "monitoring_eligible_flag" in frame.columns:
        # The book carries rows it does not hold the model accountable for.
        frame = frame[frame["monitoring_eligible_flag"].fillna(False)]
    frame = frame.rename(columns={k: v for k, v in RENAMED.items()
                                  if k in frame.columns})
    if NAME_FROM in frame.columns:
        # Copied rather than renamed: both columns are read downstream, and
        # renaming left `customer_id` empty on every scored row.
        frame["borrower_name"] = frame[NAME_FROM]
    if "period" not in frame.columns:
        frame["period"] = period
    return frame.reset_index(drop=True)





# ---------------------------------------------------------- the credit cycle


def _cycle_series(source: Any) -> "pd.Series":
    """Where the credit cycle sits at each month, read off the book itself.

    This installation publishes no macro series, so the corporate path — read
    `credit_cycle_factor` from `macro_saudi` — returns nothing and the cycle
    factor comes out constant at zero for every facility in every month. A
    factor that is the same number on every row carries no information, and a
    screen offering "Cycle sensitivity" as one of six families with nothing
    behind it is the same defect this module was written to fix, one level
    down.

    The book knows where the cycle is. The average point-in-time PD across the
    whole retail book, month by month, IS the cycle as this book experiences
    it: it rises when conditions deteriorate and falls when they improve. It is
    centred and scaled so a beta estimated against it is a sensitivity rather
    than a unit conversion.
    """
    from backend.data_access.protocol import AnalysisContext

    rows: list[tuple[str, float]] = []
    for period in source.periods(DATASET):
        try:
            frame = source.fetch(
                DATASET, context=AnalysisContext(period=period),
                period=period, fields=["pd_pit_12m_base"])
        except Exception:  # noqa: BLE001 - a month the book lacks
            continue
        if frame.empty:
            continue
        rows.append((period, float(
            pd.to_numeric(frame["pd_pit_12m_base"], errors="coerce").mean())))
    if len(rows) < 3:
        return pd.Series(dtype="float64")
    series = pd.Series({p: v for p, v in rows}, dtype="float64")
    spread = float(series.std())
    if spread < 1e-12:
        return pd.Series(dtype="float64")
    return (series - series.mean()) / spread


def cycle_exposure(source: Any, period: str) -> dict[str, float]:
    """Each employer sector's cycle exposure at one month: beta times cycle.

    Beta is d(sector mean PD)/d(cycle), estimated across every published month
    rather than asserted. A sector whose PDs rise with the cycle has a positive
    beta, so multiplying by where the cycle currently sits gives a number that
    is positive exactly when the economy is working against that sector now.
    """
    from backend.data_access.protocol import AnalysisContext

    cycle = _cycle_series(source)
    if cycle.empty or period not in cycle.index:
        return {}

    rows: list[tuple[str, float, float]] = []
    for month in cycle.index:
        try:
            frame = source.fetch(
                DATASET, context=AnalysisContext(period=str(month)),
                period=str(month),
                fields=["employer_sector", "pd_pit_12m_base"])
        except Exception:  # noqa: BLE001
            continue
        if frame.empty:
            continue
        mean_pd = (frame.assign(
            pd_pit_12m_base=pd.to_numeric(frame["pd_pit_12m_base"],
                                          errors="coerce"))
            .groupby("employer_sector")["pd_pit_12m_base"].mean())
        for sector, value in mean_pd.items():
            if sector is None or pd.isna(value):
                continue
            rows.append((str(sector), float(cycle[month]), float(value)))
    if not rows:
        return {}

    frame = pd.DataFrame(rows, columns=["sector", "cycle", "pd"])
    now = float(cycle[period])
    out: dict[str, float] = {}
    for sector, group in frame.groupby("sector"):
        variance = float(group["cycle"].var())
        if variance < 1e-12 or len(group) < 3:
            out[str(sector)] = 0.0
            continue
        covariance = float(
            ((group["cycle"] - group["cycle"].mean())
             * (group["pd"] - group["pd"].mean())).mean())
        out[str(sector)] = (covariance / variance) * now
    return out


__all__ = ["DATASET", "KEY", "NAME_FROM", "PERIOD_FIELD", "READ_FIELDS",
           "RENAMED", "compute", "cycle_exposure", "factors", "read_book"]

"""
Shared helpers for engine functions.

Two things every analysis needs and none should re-implement: EAD-weighted
averages, and reading a governed dataset through the Data Access Layer while
recording what was read for the Trace.

Weighting methodology
---------------------
A portfolio average is almost always **exposure-weighted**, not a simple mean.
The unweighted mean PD of a book treats a USD 2 million facility and a USD 2
billion facility as equally important, which is wrong for every risk question a
credit committee asks. So the default here is EAD-weighted, and where a count
view is also meaningful (how many borrowers, not how much money) the analysis
returns both explicitly rather than leaving the reader to guess which they are
looking at.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FACILITY = "portfolio_facility"
BORROWER = "borrower_financials"
STAGING = "ifrs9_staging"
RATINGS = "customer_ratings"
MACRO = "macro_saudi"
DELINQUENCY = "facility_delinquency"
MEMOS = "credit_memo_signals"

# DPD buckets, in the order a credit committee reads them.
DPD_BUCKETS = ["Current", "1-29", "30-59", "60-89", "90-179", "180+"]

# Rating grades, best to worst — the full notched scale.
#
# The notches matter. With only the whole grades listed, "AA+" and "BBB-" would
# not be found and would sort to the end alongside "D", so a one-notch downgrade
# from A+ to A would be scored as an upgrade. Every transition matrix and every
# deterioration ranking depends on this order being right.
RATING_ORDER = [
    "AAA",
    "AA+", "AA", "AA-",
    "A+", "A", "A-",
    "BBB+", "BBB", "BBB-",
    "BB+", "BB", "BB-",
    "B+", "B", "B-",
    "CCC+", "CCC", "CCC-",
    "CC", "C", "D",
]


def weighted_average(values: pd.Series, weights: pd.Series) -> float:
    """EAD-weighted average, safe when the weights sum to zero."""
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce")
    mask = v.notna() & w.notna()
    total = float(w[mask].sum())
    if total <= 0:
        return 0.0
    return float((v[mask] * w[mask]).sum() / total)


def safe_ratio(numerator: float, denominator: float, *, as_pct: bool = True) -> float:
    """A ratio that returns 0 rather than infinity when the denominator is zero.

    A zero denominator here means "no exposure in this bucket", and reporting a
    coverage of 0% is correct; reporting infinity or a crash is not.
    """
    if not denominator:
        return 0.0
    ratio = numerator / denominator
    return float(ratio * 100) if as_pct else float(ratio)


def dpd_bucket(days: pd.Series) -> pd.Series:
    """Map days-past-due to the standard reporting buckets."""
    d = pd.to_numeric(days, errors="coerce").fillna(0)
    return pd.cut(
        d,
        bins=[-np.inf, 0, 29, 59, 89, 179, np.inf],
        labels=DPD_BUCKETS,
        right=True,
    ).astype("object")


def rating_sort_key(rating: str) -> int:
    """Position of a rating on the scale, worst-last. Unknown ratings sort last."""
    try:
        return RATING_ORDER.index(str(rating).strip().upper())
    except ValueError:
        return len(RATING_ORDER)


def order_ratings(values) -> list[str]:
    """Ratings present in the data, ordered best to worst rather than alphabetically."""
    unique = {str(v).strip().upper() for v in values if pd.notna(v)}
    return sorted(unique, key=rating_sort_key)


def rounded(value: float, places: int = 2) -> float:
    """Round for presentation. Applied at the output boundary only — never to an
    intermediate, where it would compound."""
    if value is None or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
        return 0.0
    return float(round(float(value), places))


def frame_to_rows(df: pd.DataFrame) -> list[dict]:
    """DataFrame to JSON-safe rows.

    NaN is not valid JSON, and pandas' nullable integer type does not serialise,
    so both are converted here rather than in every analysis.
    """
    if df.empty:
        return []
    out = df.copy()
    for column in out.columns:
        if pd.api.types.is_integer_dtype(out[column]):
            out[column] = out[column].astype("float64")
    out = out.replace({np.nan: None, pd.NA: None})
    return out.to_dict(orient="records")


def resolve_periods(source, dataset: str, period: str | None, compare_period: str | None
                    ) -> tuple[str, str | None, list[str]]:
    """Resolve "latest" and "earliest" to real reporting periods.

    Callers — and later the LLM planner — should be able to say "the latest
    period" without knowing what data has been loaded. Resolution happens here so
    every analysis behaves identically, and the resolved value is what gets
    recorded in the Trace.
    """
    available = source.periods(dataset)
    if not available:
        raise ValueError(
            f"Dataset '{dataset}' has no reporting periods. Has it been published?"
        )

    def resolve(value: str | None, default: str | None) -> str | None:
        if value in (None, ""):
            return default
        if value == "latest":
            return available[-1]
        if value == "earliest":
            return available[0]
        if value == "previous":
            return available[-2] if len(available) > 1 else available[0]
        if value not in available:
            raise ValueError(
                f"'{value}' is not a reporting period in '{dataset}'. "
                f"Available: {', '.join(available)}"
            )
        return value

    resolved_period = resolve(period, available[-1])
    resolved_compare = resolve(compare_period, None)
    return resolved_period, resolved_compare, available


def prior_period(available: list[str], period: str) -> str | None:
    """The period immediately before `period`, or None if it is the earliest."""
    if period not in available:
        return None
    index = available.index(period)
    return available[index - 1] if index > 0 else None

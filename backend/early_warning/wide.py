"""
The Early Warning book as one row per obligor per month, flat.

Why a wide view exists at all
-----------------------------
The governed model is normalised, and it has to be: the signal catalogue, the
observations, the sub-category outputs and the lineage are separate things
with separate audit lives, and collapsing them would make the score
unauditable. But a question like "which sub-category is driving the High
population this month?" should not require a reader — or a planner writing
code against this domain — to unpack three nested dictionaries and join two
frames before it can start.

So the normalised model stays exactly as it is, and this is a projection of
it: every nested structure the borrower-month row carries — the twenty-two
sub-category scores, the six layer/dimension outputs, the five notches, the
overrides — lifted into named columns, with the names a person would use.

What it is not
--------------
Not a second source of truth. Every column here is read from the published
borrower-month rows, never recomputed, so the wide view cannot disagree with
the model: if it did, this module would be the thing that is wrong. Nothing
is derived here that the model does not already state, with two exceptions
that are explicitly labelled as derived — the dominant layer, and the
one-month and twelve-month movement — because both are read off the same
published rows and both are the questions the screen asks most.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.early_warning import aggregation as agg
from backend.early_warning import classifiers_v2 as clf
from backend.early_warning import notches as notch_mod
from backend.early_warning import reasons
from backend.early_warning import v2_service as svc

#: The twenty-two sub-category nodes, trigger-and-accelerator first.
SUBCATEGORY_CODES: tuple[str, ...] = (
    tuple(agg.TA_SUBCATEGORIES) + tuple(clf.SUBCATEGORIES))

#: The six layer/dimension outputs, in the order the model produces them.
LAYER_KEYS: tuple[str, ...] = ("l1_ta", "l2_ta", "l3_ta", "l4_ta",
                               "l2_c", "l4_c")

#: The five notches, in the order they are applied.
NOTCH_KEYS: tuple[str, ...] = tuple(notch_mod.NOTCH_KEYS)

#: Which dimension each sub-category belongs to.
TA_CODES = frozenset(agg.TA_SUBCATEGORIES)
CLASSIFIER_CODES = frozenset(clf.SUBCATEGORIES)


def subcategory_column(code: str) -> str:
    """`L2.1` becomes `sub_l2_1_score`, which is a column name a person can type."""
    return f"sub_{code.lower().replace('.', '_')}_score"


def notch_column(key: str) -> str:
    return f"notch_{key}"


def _as_list(value: Any) -> list[str]:
    """Overrides arrive comma-separated. Splitting them here stops a caller
    iterating the string one character at a time."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _subcategory_name(code: Any) -> str:
    """The node's business name, or nothing when there is no node."""
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return ""
    text = str(code).strip()
    if not text or text.lower() == "nan":
        return ""
    try:
        return reasons.subcategory_name(text)
    except KeyError:
        return text


def _dominant_layer(layers: dict[str, Any]) -> str:
    """The layer carrying the most trigger-side risk, or empty when none is."""
    ta = {k: float(v or 0.0) for k, v in (layers or {}).items()
          if k.endswith("_ta")}
    if not ta or max(ta.values()) <= 0:
        return ""
    return max(ta, key=lambda k: ta[k]).split("_")[0].upper()


def flatten(frame: pd.DataFrame) -> pd.DataFrame:
    """One published borrower-month frame, with every nested field named.

    Read rather than recomputed. A column that disagreed with the model would
    be this module's defect, so there is nothing here for it to disagree
    about.
    """
    if frame is None or frame.empty:
        return pd.DataFrame()

    out = frame.copy()

    subcats = out.get("subcategory_scores")
    layers = out.get("layer_dimension_scores")
    notch_values = out.get("notches")

    for code in SUBCATEGORY_CODES:
        column = subcategory_column(code)
        out[column] = [
            float((row or {}).get(code) or 0.0)
            for row in (subcats if subcats is not None else [{}] * len(out))
        ]

    for key in LAYER_KEYS:
        out[key] = [
            float((row or {}).get(key) or 0.0)
            for row in (layers if layers is not None else [{}] * len(out))
        ]

    for key in NOTCH_KEYS:
        out[notch_column(key)] = [
            int((row or {}).get(key) or 0)
            for row in (notch_values if notch_values is not None else [{}] * len(out))
        ]

    overrides = [_as_list(v) for v in out.get("overrides_applied", [None] * len(out))]
    out["override_applied"] = [bool(v) for v in overrides]
    out["override_count"] = [len(v) for v in overrides]
    out["override_types"] = [", ".join(v) for v in overrides]

    # Derived, and labelled as such in the dictionary: read off the same
    # published row, not recomputed from the signals.
    out["dominant_layer"] = [
        _dominant_layer(row or {})
        for row in (layers if layers is not None else [{}] * len(out))
    ]
    # An obligor with no scoring node has no dominant sub-category, and the
    # column arrives as NaN rather than as an empty string.
    out["dominant_subcategory_name"] = [
        _subcategory_name(code)
        for code in out.get("dominant_subcategory", [None] * len(out))
    ]
    out["ta_minus_classifier"] = out["ta_score"] - out["classifier_score"]
    out["notch_points"] = out["net_notches"] * notch_mod.POINTS_PER_NOTCH
    out["high_plus"] = out["ews_band"].isin(("HIGH", "VERY_HIGH"))

    # The nested originals are dropped from the wide view: keeping both would
    # give a planner two ways to ask the same question and one of them would
    # be wrong sooner or later. `overrides_applied` goes with them — the three
    # named columns above say the same thing without a comma-separated string
    # to parse. The normalised frame still carries every one of them.
    return out.drop(columns=[c for c in ("subcategory_scores",
                                          "layer_dimension_scores", "notches",
                                          "classifier_overrides",
                                          "overrides_applied")
                              if c in out.columns])


def customer_month(period: str | None = None) -> pd.DataFrame:
    """The wide view for one published month, or the latest."""
    return flatten(svc.borrower_month(period))


def with_movement(period: str | None = None) -> pd.DataFrame:
    """The wide view plus how each obligor moved, one month and twelve back.

    Derived here rather than in the model because it is a comparison of two
    published rows rather than a score: the anchor and the notch movements
    are carried separately, because a score that fell while its anchor rose
    has not improved and the two have to be readable apart.
    """
    period = period or svc.latest_period()
    periods = svc.periods()
    current = customer_month(period)
    if current.empty:
        return current
    here = periods.index(period) if period in periods else len(periods) - 1

    for label, back in (("1m", 1), ("12m", 12)):
        prior_period = periods[here - back] if here - back >= 0 else None
        if prior_period is None:
            current[f"ews_change_{label}"] = float("nan")
            current[f"anchor_change_{label}"] = float("nan")
            current[f"prior_period_{label}"] = ""
            continue
        prior = svc.borrower_month(prior_period).set_index("customer_id")
        current[f"prior_period_{label}"] = prior_period
        current[f"ews_change_{label}"] = [
            round(float(row.ews_score) - float(prior.loc[row.customer_id, "ews_score"]), 2)
            if row.customer_id in prior.index else float("nan")
            for row in current.itertuples()
        ]
        current[f"anchor_change_{label}"] = [
            round(float(row.anchor_score) - float(prior.loc[row.customer_id, "anchor_score"]), 2)
            if row.customer_id in prior.index else float("nan")
            for row in current.itertuples()
        ]
    return current


def columns() -> list[str]:
    """Every column the wide view exposes, for the dictionary to describe."""
    latest = with_movement()
    return list(latest.columns)


__all__ = ["CLASSIFIER_CODES", "LAYER_KEYS", "NOTCH_KEYS", "SUBCATEGORY_CODES",
           "TA_CODES", "columns", "customer_month", "flatten",
           "notch_column", "subcategory_column", "with_movement"]

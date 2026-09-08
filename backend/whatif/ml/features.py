"""
What the ML model is allowed to look at, and what it must never look at.

Two rules, both enforced here rather than remembered
----------------------------------------------------
**No identifiers.** `backend/learning/models.py::seal()` refuses an artifact
containing `borrower_id`, `customer_id`, `account_id`, `borrower_name` and the
rest — "Features are structural; a borrower id in a model artifact is raw
client data that has left its tenant." XGBoost writes its feature names into
the model JSON, so a feature called `borrower_id` would not merely be poor
modelling, it would be refused at the door. `FORBIDDEN` is checked before a
frame is ever handed to the trainer.

**No leakage.** The target is built from the reported ECL, so every column
derived from the reported ECL is barred from the features: `final_ecl` itself,
the twelve-month and lifetime components, the management overlay and the
coverage ratio. A model that reads `ecl_coverage` to predict the ECL rate has
learned nothing and will score beautifully.

What the target is
------------------
    ECL rate = reported ECL / EAD

EAD is the denominator the book itself uses — `ecl_coverage` is the same ratio
in percent — and it is the exposure the provision is actually held against.
Rate rather than amount because a model trained on the amount spends its
capacity learning that large borrowers have large provisions, which is not the
relationship a scenario needs.

A borrower with no exposure has no rate. Those rows are dropped, and the count
is reported rather than quietly absorbed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

FEATURE_VERSION = "1.0.0"

#: The target, and the two columns it is built from.
TARGET = "ecl_rate"
TARGET_NUMERATOR = "final_ecl"
TARGET_DENOMINATOR = "ead"

#: Anything whose name is a client identifier. Checked against the same list
#: the artifact sealer uses, so a feature set that would be refused on save is
#: refused on construction instead.
FORBIDDEN: frozenset[str] = frozenset({
    "customer_id", "borrower_id", "account_id", "borrower_name",
    "customer_name", "national_id", "iban", "cr_number",
    "legal_name", "display_name", "alias", "arabic_name",
    "customer_number", "relationship_manager", "group_name", "group_id",
})

#: Columns derived from the reported ECL. Using any of them to predict the ECL
#: rate is circular.
LEAKING: frozenset[str] = frozenset({
    "final_ecl", "ecl_12m", "ecl_lifetime", "ecl_coverage",
    "management_overlay", "scenario_weight", "ecl_rate",
})

#: Numeric features, in a fixed order so a model's inputs are reproducible.
NUMERIC: tuple[str, ...] = (
    "pd_12m", "pd_lifetime", "pd_at_origination_pct", "lgd",
    # The GRADE's through-the-cycle level, beside the borrower's own
    # point-in-time reading. The two together are what distinguish a weak name
    # on a strong grade from a strong name on a weak one, and until the book
    # published three separate PDs the model could not see the difference.
    "ttc_pd_pct",
    "stage", "current_dpd", "max_dpd_12m", "internal_rating_numeric",
    "rating_change_notches", "collateral_coverage_pct",
    "secured_share", "collateral_to_ead", "drawn_share", "undrawn_share",
    "ccf", "log_ead", "facility_count", "covenants_breached",
    # What the triggers SAY, and how much cure probation has been served.
    #
    # The book's staging has a memory: a borrower whose trigger stops firing
    # is carried at Stage 2 until it has served its probation. So `stage` — the
    # stage the book carries — and `stage_measured` — the stage the triggers
    # give this quarter — are different columns, and the difference between
    # them is exactly the population a feature-based model otherwise cannot
    # tell apart from Stage 1. Without both, the model under-steps the Stage 1
    # to Stage 2 crossing, which is the crossing a What-If exists to price.
    "stage_measured", "sicr_clear_quarters",
    "minimum_headroom_pct", "leverage", "net_leverage", "dscr",
    "interest_coverage", "ebitda_margin", "revenue_growth",
    "watchlist_flag", "restructure_flag", "forbearance_flag", "default_flag",
)

#: Categorical features. Encoded as stable integer codes rather than one-hot,
#: because XGBoost splits on them perfectly well and one-hot would turn twenty
#: sectors into twenty columns of mostly zeros.
CATEGORICAL: tuple[str, ...] = ("sector", "segment")

FEATURES: tuple[str, ...] = (*NUMERIC, *(f"{c}_code" for c in CATEGORICAL))


class FeatureError(ValueError):
    """A feature frame that must not be built or trained on."""


@dataclass(frozen=True)
class Encoding:
    """The category-to-code maps, carried with the model so scoring matches."""

    maps: dict[str, dict[str, int]]

    def code(self, column: str, value: Any) -> int:
        """The code for one value; an unseen category is -1, never a guess."""
        return self.maps.get(column, {}).get(str(value), -1)

    def to_dict(self) -> dict[str, Any]:
        return {"maps": {k: dict(v) for k, v in self.maps.items()}}

    @classmethod
    def from_dict(cls, body: dict[str, Any] | None) -> Encoding:
        raw = (body or {}).get("maps") or {}
        return cls(maps={k: {str(a): int(b) for a, b in v.items()}
                         for k, v in raw.items()})

    @classmethod
    def learn(cls, frame: pd.DataFrame) -> Encoding:
        maps: dict[str, dict[str, int]] = {}
        for column in CATEGORICAL:
            if column not in frame.columns:
                maps[column] = {}
                continue
            values = sorted({str(v) for v in frame[column].dropna().unique()})
            maps[column] = {v: i for i, v in enumerate(values)}
        return cls(maps=maps)


def _safe_ratio(top: pd.Series, bottom: pd.Series) -> pd.Series:
    return (top / bottom.replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan).fillna(0.0)


def derive(frame: pd.DataFrame) -> pd.DataFrame:
    """The columns the book does not carry but a model wants.

    Ratios rather than levels wherever the level is really about size: a
    borrower with SAR 900m of collateral against SAR 1bn of exposure is in the
    same position as one with SAR 9m against SAR 10m, and a model given the
    raw amounts has to discover that for itself.
    """
    work = frame.copy()
    ead = pd.to_numeric(work.get("ead"), errors="coerce").fillna(0.0)

    def num(name: str) -> pd.Series:
        if name not in work.columns:
            return pd.Series(np.zeros(len(work)), index=work.index)
        return pd.to_numeric(work[name], errors="coerce").fillna(0.0)

    work["log_ead"] = np.log1p(ead.clip(lower=0.0))
    work["collateral_to_ead"] = _safe_ratio(num("collateral_market_value"), ead)
    work["secured_share"] = _safe_ratio(num("secured_exposure"), ead).clip(0, 1)
    work["drawn_share"] = _safe_ratio(num("drawn_exposure"), ead).clip(0, 5)
    work["undrawn_share"] = _safe_ratio(num("undrawn_commitment"), ead).clip(0, 5)
    if "ccf" not in work.columns:
        undrawn = num("undrawn_commitment")
        work["ccf"] = _safe_ratio(ead - num("drawn_exposure"), undrawn).clip(0, 1)
    for flag in ("watchlist_flag", "restructure_flag", "forbearance_flag",
                 "default_flag"):
        work[flag] = (num(flag) > 0).astype(int) if flag in work.columns else 0
    for column in NUMERIC:
        if column not in work.columns:
            work[column] = 0.0
    return work


def target(frame: pd.DataFrame) -> pd.Series:
    """The ECL rate: reported ECL over EAD."""
    ead = pd.to_numeric(frame[TARGET_DENOMINATOR], errors="coerce")
    ecl = pd.to_numeric(frame[TARGET_NUMERATOR], errors="coerce")
    return _safe_ratio(ecl, ead)


@dataclass(frozen=True)
class Matrix:
    """A feature matrix, its target, and where every row came from."""

    X: pd.DataFrame
    y: pd.Series
    periods: pd.Series
    #: Kept beside the matrix, never inside it — identifiers must not reach
    #: the model, but a caller still needs to know which borrower a row is.
    borrower_ids: pd.Series
    dropped_no_exposure: int = 0
    encoding: Encoding = None  # type: ignore[assignment]

    @property
    def rows(self) -> int:
        return int(len(self.X))


def check(columns: list[str] | tuple[str, ...]) -> None:
    """Refuse a feature set that carries an identifier or leaks the target."""
    named = {str(c).lower() for c in columns}
    identifiers = sorted(named & FORBIDDEN)
    if identifiers:
        raise FeatureError(
            "These are client identifiers and must not be model features: "
            + ", ".join(identifiers)
            + ". Features are structural; the artifact sealer refuses a model "
              "that carries them.")
    leaks = sorted(named & LEAKING)
    if leaks:
        raise FeatureError(
            "These are derived from the reported ECL and would leak the "
            "target: " + ", ".join(leaks)
            + ". A model that reads them has learned nothing.")


def build(frame: pd.DataFrame, *, encoding: Encoding | None = None) -> Matrix:
    """The matrix a model trains or scores on."""
    check(FEATURES)
    work = derive(frame)
    ead = pd.to_numeric(work.get("ead"), errors="coerce").fillna(0.0)
    usable = work[ead > 0].copy()
    dropped = int(len(work) - len(usable))

    learnt = encoding or Encoding.learn(usable)
    for column in CATEGORICAL:
        values = (usable[column].astype(str) if column in usable.columns
                  else pd.Series([""] * len(usable), index=usable.index))
        usable[f"{column}_code"] = values.map(
            lambda v, c=column: learnt.code(c, v)).astype(int)

    X = usable[list(FEATURES)].astype(float)
    if X.isna().any().any():  # pragma: no cover - derive() fills everything
        X = X.fillna(0.0)
    return Matrix(
        X=X, y=target(usable).astype(float),
        periods=usable["period"].astype(str) if "period" in usable.columns
        else pd.Series([""] * len(usable), index=usable.index),
        borrower_ids=usable["borrower_id"].astype(str)
        if "borrower_id" in usable.columns
        else pd.Series([""] * len(usable), index=usable.index),
        dropped_no_exposure=dropped, encoding=learnt)


def describe() -> dict[str, Any]:
    """The feature contract, for the model card."""
    return {
        "version": FEATURE_VERSION,
        "target": TARGET,
        "target_definition": (
            f"{TARGET_NUMERATOR} / {TARGET_DENOMINATOR} — the reported ECL "
            "over the exposure it is held against. This is the ratio the book "
            "itself reports as ecl_coverage, expressed as a fraction."),
        "why_a_rate": (
            "A model trained on the ECL amount spends its capacity learning "
            "that large borrowers have large provisions. The rate is the "
            "relationship a scenario actually needs."),
        "feature_count": len(FEATURES),
        "numeric": list(NUMERIC),
        "categorical": [f"{c}_code" for c in CATEGORICAL],
        "excluded_as_identifiers": sorted(FORBIDDEN),
        "excluded_as_leakage": sorted(LEAKING),
        "dropped_rows": "Borrowers with no exposure have no rate and are dropped.",
    }


__all__ = [
    "CATEGORICAL", "FEATURES", "FEATURE_VERSION", "FORBIDDEN", "FeatureError",
    "LEAKING", "Matrix", "NUMERIC", "TARGET", "TARGET_DENOMINATOR",
    "TARGET_NUMERATOR", "Encoding", "build", "check", "derive", "describe",
    "target",
]

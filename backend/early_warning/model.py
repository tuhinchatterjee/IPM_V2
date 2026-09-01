"""
The Forward Risk Signal: how it scores, and how it is fitted.

The scoring form
----------------
    score        = intercept + Σ  wᵢ · zᵢ
    probability  = 1 / (1 + e^(−score))

where zᵢ is factor i standardised against the fitting population. That is a
logistic model, and it is chosen for exactly one reason: every facility's score
decomposes EXACTLY into one number per factor, and those numbers add up. There
is no approximation step, no attribution heuristic, and no argument about which
attribution method is right — the contribution of a factor IS wᵢ · zᵢ, and the
contributions plus the intercept ARE the score.

That property is what makes the screen possible. A credit officer can be shown
"this facility scores 0.31; 0.18 of it is behaviour, 0.09 is capacity, and here
is the line for every factor", and the numbers reconcile. A gradient-boosted
model would very likely rank slightly better and would make that screen a
fiction.

The fitting
-----------
Iteratively reweighted least squares — the standard way to fit a logistic
regression, written out here in about forty lines of numpy rather than imported,
so a reviewer can read the whole estimator. Ridge regularisation is applied
because factors within a family are correlated by construction (utilisation and
utilisation change, PD level and downgrade probability), and without it the
weights would swing between correlated factors from one refit to the next while
the predictions barely moved — which looks, to anyone reading the weights, like
the model changing its mind.

What is deliberately NOT here
-----------------------------
No vendor methodology is reproduced or approximated. No result of this module is
described as validated, production or regulatory anywhere in the product; see
`lifecycle.py` for the labels that are permitted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.early_warning.factors import (
    FACTOR_BY_ID,
    FACTOR_FAMILIES,
    FACTORS,
    FAMILY_BY_ID,
)

#: Ridge strength. Small enough not to shrink a genuine effect away, large
#: enough to stop correlated factors trading weight between refits.
DEFAULT_RIDGE = 1.0

#: IRLS stops when the largest coefficient move falls below this.
CONVERGENCE = 1e-7
MAX_ITERATIONS = 60


class FittingError(RuntimeError):
    """The signal could not be fitted, and the message says why."""


# ------------------------------------------------------------- specification


@dataclass(frozen=True)
class Weight:
    """One factor's part in the score."""

    factor_id: str
    weight: float
    #: The fitting population's mean and standard deviation for this factor.
    #: Kept with the weight because a weight without its standardisation is
    #: meaningless — the same coefficient means something different against a
    #: different scale.
    mean: float
    std: float

    @property
    def expected_direction(self) -> str:
        return FACTOR_BY_ID[self.factor_id].direction

    @property
    def agrees_with_expectation(self) -> bool:
        """Whether the fitted sign matches what a credit officer would expect.

        A factor that disagrees is not necessarily wrong — correlated factors
        routinely flip signs — but it is exactly the thing a reviewer should be
        made to look at rather than left to discover.
        """
        if abs(self.weight) < 1e-9:
            return True
        worse_when_higher = self.expected_direction == "up-is-worse"
        return (self.weight > 0) == worse_when_higher

    def to_dict(self) -> dict[str, Any]:
        definition = FACTOR_BY_ID[self.factor_id]
        return {
            "factor_id": self.factor_id,
            "label": definition.label,
            "family": definition.family,
            "family_label": FAMILY_BY_ID[definition.family].label,
            "weight": round(self.weight, 6),
            "mean": round(self.mean, 6),
            "std": round(self.std, 6),
            "expected_direction": self.expected_direction,
            "agrees_with_expectation": self.agrees_with_expectation,
        }


@dataclass(frozen=True)
class SignalSpecification:
    """Everything needed to reproduce a score, and nothing else.

    A specification is a value: it can be stored as JSON, read back, and will
    produce the identical score. That is what makes a model version a real
    version rather than a label on a moving target.
    """

    target_id: str
    intercept: float
    weights: tuple[Weight, ...]
    #: The periods the fit was estimated on, in order.
    fitted_periods: tuple[str, ...] = ()
    #: Rows and events in the fitting population.
    fitted_rows: int = 0
    fitted_events: int = 0
    ridge: float = DEFAULT_RIDGE
    #: Sector cycle exposures used by the cycle factor, captured with the fit so
    #: a stored specification does not depend on a table that may have moved.
    cycle_by_sector: dict[str, float] = field(default_factory=dict)
    notes: str = ""

    @property
    def base_rate(self) -> float:
        """Events per row in the fitting population, as a percentage."""
        return 100.0 * self.fitted_events / self.fitted_rows if self.fitted_rows else 0.0

    def weight_for(self, factor_id: str) -> Weight | None:
        return next((w for w in self.weights if w.factor_id == factor_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "intercept": round(self.intercept, 6),
            "weights": [w.to_dict() for w in self.weights],
            "fitted_periods": list(self.fitted_periods),
            "fitted_rows": self.fitted_rows,
            "fitted_events": self.fitted_events,
            "base_rate_pct": round(self.base_rate, 4),
            "ridge": self.ridge,
            "cycle_by_sector": {k: round(v, 6) for k, v in self.cycle_by_sector.items()},
            "notes": self.notes,
            "form": (
                "score = intercept + sum(weight x standardised factor); "
                "probability = 1 / (1 + exp(-score))"
            ),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SignalSpecification:
        return cls(
            target_id=str(payload.get("target_id") or ""),
            intercept=float(payload.get("intercept") or 0.0),
            weights=tuple(
                Weight(
                    factor_id=str(w["factor_id"]),
                    weight=float(w["weight"]),
                    mean=float(w.get("mean") or 0.0),
                    std=float(w.get("std") or 1.0),
                )
                for w in payload.get("weights") or []
                if w.get("factor_id") in FACTOR_BY_ID
            ),
            fitted_periods=tuple(payload.get("fitted_periods") or []),
            fitted_rows=int(payload.get("fitted_rows") or 0),
            fitted_events=int(payload.get("fitted_events") or 0),
            ridge=float(payload.get("ridge") or DEFAULT_RIDGE),
            cycle_by_sector={
                str(k): float(v)
                for k, v in (payload.get("cycle_by_sector") or {}).items()
            },
            notes=str(payload.get("notes") or ""),
        )


# ------------------------------------------------------------------ fitting


def _standardise(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    # A factor with no variation in the fitting window carries no information.
    # Dividing by its zero standard deviation would produce infinities; giving
    # it a scale of one leaves it at zero for every row instead, which is the
    # honest treatment of a constant.
    std = np.where(std < 1e-9, 1.0, std)
    return (matrix - mean) / std, mean, std


def _irls(design: np.ndarray, outcome: np.ndarray, ridge: float) -> np.ndarray:
    """Fit a logistic regression by iteratively reweighted least squares.

    `design` already carries its intercept column. The ridge penalty is applied
    to the slopes only — penalising the intercept would bias the fitted base
    rate away from the observed one, which is the one thing the model must get
    right.
    """
    n_features = design.shape[1]
    beta = np.zeros(n_features)
    penalty = ridge * np.eye(n_features)
    penalty[0, 0] = 0.0

    for _ in range(MAX_ITERATIONS):
        eta = np.clip(design @ beta, -30, 30)
        mu = 1.0 / (1.0 + np.exp(-eta))
        # Bound the working weights away from zero: a perfectly separated point
        # drives its weight to zero and the normal equations to a singular
        # matrix, which is a numerical accident rather than a finding.
        w = np.clip(mu * (1 - mu), 1e-6, None)
        z = eta + (outcome - mu) / w

        weighted = design * w[:, None]
        lhs = design.T @ weighted + penalty
        rhs = weighted.T @ z
        try:
            step = np.linalg.solve(lhs, rhs)
        except np.linalg.LinAlgError as e:  # pragma: no cover - ridge prevents this
            raise FittingError(
                "The factor matrix is singular even with regularisation, which "
                "means two factors are carrying identical information."
            ) from e
        if np.max(np.abs(step - beta)) < CONVERGENCE:
            beta = step
            break
        beta = step
    return beta


def fit_specification(factors: pd.DataFrame, outcome: pd.Series, *,
                      target_id: str, periods: tuple[str, ...] = (),
                      ridge: float = DEFAULT_RIDGE,
                      cycle_by_sector: dict[str, float] | None = None,
                      notes: str = "") -> SignalSpecification:
    """Fit the signal for one target on one factor matrix.

    Refuses rather than returns something meaningless when there is nothing to
    fit on. A model estimated on eleven events is not a model, and reporting it
    as one is how a prototype ends up in front of a credit committee.
    """
    if len(factors) != len(outcome):
        raise FittingError("The factor matrix and the outcome have different lengths.")
    events = int(outcome.sum())
    if len(factors) < 500:
        raise FittingError(
            f"Only {len(factors):,} eligible facilities. The signal needs at "
            "least 500 to be worth fitting."
        )
    if events < 40:
        raise FittingError(
            f"Only {events} transitions in the fitting window. The signal needs "
            "at least 40 events; below that the weights are noise."
        )

    matrix = factors[[f.id for f in FACTORS]].to_numpy(dtype=float)
    standardised, mean, std = _standardise(matrix)
    design = np.column_stack([np.ones(len(standardised)), standardised])
    beta = _irls(design, outcome.to_numpy(dtype=float), ridge)

    return SignalSpecification(
        target_id=target_id,
        intercept=float(beta[0]),
        weights=tuple(
            Weight(factor_id=f.id, weight=float(beta[i + 1]),
                   mean=float(mean[i]), std=float(std[i]))
            for i, f in enumerate(FACTORS)
        ),
        fitted_periods=tuple(periods),
        fitted_rows=len(factors),
        fitted_events=events,
        ridge=ridge,
        cycle_by_sector=dict(cycle_by_sector or {}),
        notes=notes,
    )


# ------------------------------------------------------------------ scoring


@dataclass
class ScoredFacility:
    """One facility's score, and every part of it.

    `contributions` sums with `intercept` to `score` exactly. Any screen that
    displays this can be checked with a calculator, which is the point.
    """

    account_id: str
    customer_id: str
    borrower_name: str
    sector: str
    segment: str
    ead: float
    stage: int
    score: float
    probability: float
    intercept: float
    contributions: dict[str, float]
    family_contributions: dict[str, float]
    factor_values: dict[str, float]
    standardised: dict[str, float]
    band: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "customer_id": self.customer_id,
            "borrower_name": self.borrower_name,
            "sector": self.sector,
            "segment": self.segment,
            "ead": round(self.ead, 3),
            "stage": self.stage,
            "score": round(self.score, 5),
            "probability_pct": round(100.0 * self.probability, 3),
            "band": self.band,
            "intercept": round(self.intercept, 5),
            "contributions": [
                {
                    "factor_id": fid,
                    "label": FACTOR_BY_ID[fid].label,
                    "family": FACTOR_BY_ID[fid].family,
                    "family_label": FAMILY_BY_ID[FACTOR_BY_ID[fid].family].label,
                    "value": round(self.factor_values.get(fid, 0.0), 4),
                    "unit": FACTOR_BY_ID[fid].unit,
                    "standardised": round(self.standardised.get(fid, 0.0), 4),
                    "contribution": round(value, 5),
                }
                for fid, value in sorted(
                    self.contributions.items(), key=lambda kv: -abs(kv[1])
                )
            ],
            "family_contributions": [
                {
                    "family": family.id,
                    "label": family.label,
                    "contribution": round(self.family_contributions.get(family.id, 0.0), 5),
                }
                for family in FACTOR_FAMILIES
            ],
        }


#: Score bands. Chosen as round probabilities rather than as quantiles of the
#: current book, so "High" means the same thing next quarter as it does this
#: one. A band defined by the top decile moves every time the book moves.
BANDS: tuple[tuple[str, float], ...] = (
    ("Severe", 25.0),
    ("High", 12.0),
    ("Elevated", 5.0),
    ("Moderate", 2.0),
    ("Low", 0.0),
)


def band_for(probability_pct: float) -> str:
    for label, floor in BANDS:
        if probability_pct >= floor:
            return label
    return "Low"  # pragma: no cover - the last band has a floor of zero


def score_frame(spec: SignalSpecification, frame: pd.DataFrame,
                factors: pd.DataFrame) -> list[ScoredFacility]:
    """Score every row, keeping the whole decomposition.

    `frame` is the facility book (for identity and exposure); `factors` is the
    matrix computed from it. They are passed separately because the factor
    matrix is exactly what the model sees, and mixing the two would make it
    possible for a field to influence a score without being a declared factor.
    """
    order = [w.factor_id for w in spec.weights]
    matrix = factors[order].to_numpy(dtype=float)
    means = np.array([w.mean for w in spec.weights])
    stds = np.array([w.std if abs(w.std) > 1e-9 else 1.0 for w in spec.weights])
    coefficients = np.array([w.weight for w in spec.weights])

    standardised = (matrix - means) / stds
    contributions = standardised * coefficients
    scores = spec.intercept + contributions.sum(axis=1)

    out: list[ScoredFacility] = []
    for i, (_, row) in enumerate(frame.iterrows()):
        score = float(scores[i])
        probability = 1.0 / (1.0 + math.exp(-max(min(score, 30.0), -30.0)))
        by_factor = {fid: float(contributions[i, j]) for j, fid in enumerate(order)}
        by_family: dict[str, float] = {f.id: 0.0 for f in FACTOR_FAMILIES}
        for fid, value in by_factor.items():
            by_family[FACTOR_BY_ID[fid].family] += value

        out.append(ScoredFacility(
            account_id=str(row.get("account_id", "")),
            customer_id=str(row.get("customer_id", "")),
            borrower_name=str(row.get("borrower_name", "")),
            sector=str(row.get("sector", "")),
            segment=str(row.get("segment", "")),
            ead=float(row.get("ead", 0.0) or 0.0),
            stage=int(row.get("ifrs9_stage", 0) or 0),
            score=score,
            probability=probability,
            intercept=spec.intercept,
            contributions=by_factor,
            family_contributions=by_family,
            factor_values={fid: float(matrix[i, j]) for j, fid in enumerate(order)},
            standardised={fid: float(standardised[i, j]) for j, fid in enumerate(order)},
            band=band_for(100.0 * probability),
        ))
    return out


def probabilities(spec: SignalSpecification, factors: pd.DataFrame) -> np.ndarray:
    """Just the probabilities. Used by backtesting, which does not need the rest."""
    order = [w.factor_id for w in spec.weights]
    matrix = factors[order].to_numpy(dtype=float)
    means = np.array([w.mean for w in spec.weights])
    stds = np.array([w.std if abs(w.std) > 1e-9 else 1.0 for w in spec.weights])
    coefficients = np.array([w.weight for w in spec.weights])
    eta = spec.intercept + (((matrix - means) / stds) * coefficients).sum(axis=1)
    return 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))


__all__ = [
    "BANDS",
    "DEFAULT_RIDGE",
    "FittingError",
    "ScoredFacility",
    "SignalSpecification",
    "Weight",
    "band_for",
    "fit_specification",
    "probabilities",
    "score_frame",
]

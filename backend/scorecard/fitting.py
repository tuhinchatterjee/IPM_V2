"""
Fitting a scorecard's coefficients. §12, §13, §35.

Iteratively reweighted least squares on the WoE columns — the classical way
a logistic scorecard is estimated, and small enough (five or six columns) to
write out in full rather than reach for a dependency.

Why fit at all, in a demonstration
-----------------------------------
The alternative is inventing coefficients. Invented coefficients produce an
equation that is internally consistent and describes nothing: replication
would pass, discrimination would be whatever the numbers happened to give,
and a sensitivity analysis would be measuring an arbitrary vector. Fitting
on the development population means the equation is a real answer to a real
estimation problem, so every diagnostic downstream is measuring something.

What this module will not do
-----------------------------
It will not select variables. Which five or six a model uses is a decision
recorded in the registry, made by people, and a stepwise search that quietly
picked them would make "why is this variable in the model" unanswerable —
which is exactly what §52's model-design section has to answer.

It will not fit on a validation month. `fit()` takes whatever frame it is
given, and every caller in this codebase hands it the development
population; the separation is enforced where the specs are built.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

FITTING_VERSION = "1.0.0"

MAX_ITERATIONS = 60
CONVERGENCE = 1e-9
#: Ridge term. Not for regularisation in any meaningful sense — it keeps the
#: information matrix invertible when two WoE columns are near-collinear,
#: which happens whenever two variables bin the same underlying thing.
RIDGE = 1e-6


class FittingError(Exception):
    """A fit that cannot be performed or cannot be trusted."""


@dataclass
class Fit:
    """A fitted logistic model, and how well the fit itself went."""

    intercept: float
    coefficients: dict[str, float] = field(default_factory=dict)
    iterations: int = 0
    converged: bool = False
    log_likelihood: float = 0.0
    null_log_likelihood: float = 0.0
    rows: int = 0
    bads: int = 0

    @property
    def mcfadden_r2(self) -> float:
        if self.null_log_likelihood == 0:
            return 0.0
        return round(1.0 - self.log_likelihood / self.null_log_likelihood, 6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fitting_version": FITTING_VERSION,
            "intercept": round(self.intercept, 8),
            "coefficients": {k: round(v, 8)
                             for k, v in self.coefficients.items()},
            "iterations": self.iterations,
            "converged": self.converged,
            "log_likelihood": round(self.log_likelihood, 4),
            "mcfadden_r2": self.mcfadden_r2,
            "rows": self.rows,
            "bads": self.bads,
            "method": "iteratively reweighted least squares",
        }


def _sigmoid(x: np.ndarray) -> np.ndarray:
    out = np.empty_like(x)
    positive = x >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-x[positive]))
    exponent = np.exp(x[~positive])
    out[~positive] = exponent / (1.0 + exponent)
    return out


def fit(frame: pd.DataFrame, columns: list[str], target: str) -> Fit:
    """Estimate a logistic model by IRLS.

    Refuses rather than returning a shaky answer when the design cannot
    support one: no bads, no goods, or a column that does not vary. Each of
    those produces coefficients that look like numbers and mean nothing.
    """
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise FittingError("not in the frame: " + ", ".join(missing))
    if target not in frame.columns:
        raise FittingError(f"{target!r} is not in the frame")

    usable = frame[[*columns, target]].dropna()
    y = usable[target].to_numpy(dtype=float)
    bads = int(y.sum())
    goods = int(len(y) - bads)
    if bads == 0 or goods == 0:
        raise FittingError(
            f"the fitting sample has {bads} bad(s) and {goods} good(s). A "
            "logistic model needs both; fitted on one it returns an "
            "intercept at infinity and coefficients that are noise.")

    design = np.column_stack([np.ones(len(usable)),
                              usable[columns].to_numpy(dtype=float)])
    for index, column in enumerate(columns):
        if float(np.std(design[:, index + 1])) < 1e-12:
            raise FittingError(
                f"{column} does not vary in the fitting sample, so its "
                "coefficient is unidentified. A constant column usually "
                "means the WoE mapping put every row in one bin.")

    beta = np.zeros(design.shape[1])
    beta[0] = math.log(bads / goods)
    converged = False
    iteration = 0

    for step in range(1, MAX_ITERATIONS + 1):
        iteration = step
        eta = design @ beta
        mu = _sigmoid(eta)
        weight = np.clip(mu * (1.0 - mu), 1e-10, None)
        # The IRLS normal equations, solved rather than inverted.
        working = eta + (y - mu) / weight
        weighted = design * weight[:, None]
        information = design.T @ weighted + RIDGE * np.eye(design.shape[1])
        target_vector = weighted.T @ working
        try:
            updated = np.linalg.solve(information, target_vector)
        except np.linalg.LinAlgError as exc:  # pragma: no cover - defensive
            raise FittingError(
                "the information matrix is singular, which means two of the "
                "chosen variables carry the same information") from exc
        shift = float(np.max(np.abs(updated - beta)))
        beta = updated
        if shift < CONVERGENCE:
            converged = True
            break

    eta = design @ beta
    mu = np.clip(_sigmoid(eta), 1e-12, 1 - 1e-12)
    log_likelihood = float(np.sum(y * np.log(mu) + (1 - y) * np.log(1 - mu)))
    rate = bads / len(y)
    null_ll = float(len(y) * (rate * math.log(rate)
                              + (1 - rate) * math.log(1 - rate)))

    return Fit(
        intercept=float(beta[0]),
        coefficients={c: float(b) for c, b in zip(columns, beta[1:],
                                                  strict=True)},
        iterations=iteration, converged=converged,
        log_likelihood=log_likelihood, null_log_likelihood=null_ll,
        rows=len(usable), bads=bads)


def recalibrate(frame: pd.DataFrame, logit_column: str, target: str) -> Fit:
    """§36/§74's recalibration: refit intercept and slope on an existing logit.

    This is the honest shape of a recalibration. It can move the *level* of
    predicted risk and it cannot change the *ordering*, because a monotone
    transformation of a score leaves every rank-based statistic — AUC, Gini,
    KS — exactly where it was. A recalibration that appeared to improve
    discrimination would mean somebody had changed more than they said.
    """
    result = fit(frame, [logit_column], target)
    return result

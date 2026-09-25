"""Three models that fail in different places, and a bounded search.

Section 11.3 wants an ensemble whose components can disagree. Two gradient
boosters tuned on the same data mostly do not: they split on the same
features at the same thresholds and their errors line up, so blending them
buys very little. The third component here is therefore **not a third tree
ensemble** -- it is a regularized additive model on spline bases, linear in
its coefficients, smooth where the trees are piecewise-constant, and wrong in
different places. That is the property that makes a blend worth fitting.

## The budget, declared before the search

Section 11.6 asks for bounded search with recorded seeds and trials, so the
grids below are small, fixed and published:

* at most **12 configurations per family per book**,
* at most **3 folds**,
* at most **600 boosting rounds** with **patience 50**,
* one fixed seed per component, recorded in `ml.SEEDS`.

Exhausting the budget without meeting a gate in `ML_ACCEPTANCE_TARGETS.md` is
a result to report, not a reason to raise the budget.

## The libraries are imported lazily, and their absence is an answer

`xgboost`, `lightgbm` and `scikit-learn` live in the candidate virtual
environment built from `requirements-whatif.txt`, and in the accepted
environment they are permanently absent. Every import here is inside a
function, so importing this module costs nothing and proves nothing about
what is installed; `available()` reports what is actually importable, and a
missing library becomes `MODEL_NOT_READY` rather than a crash.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_v4.scenario import ml

#: The per-family grids. Twelve each, chosen for spread rather than for
#: fineness: with eleven training periods a finer grid is fitting noise in
#: the validation window and pretending it is tuning.
GRIDS: dict[str, tuple[dict[str, Any], ...]] = {
    ml.XGBOOST: tuple(
        {"max_depth": d, "learning_rate": lr, "subsample": 0.8,
         "colsample_bytree": 0.8, "min_child_weight": mcw,
         "reg_lambda": 1.0}
        for d, lr, mcw in itertools.product((3, 5, 7), (0.05, 0.10),
                                            (5, 20))),
    ml.LIGHTGBM: tuple(
        {"num_leaves": nl, "learning_rate": lr, "feature_fraction": 0.8,
         "bagging_fraction": 0.8, "bagging_freq": 1,
         "min_data_in_leaf": mdl, "lambda_l2": 1.0}
        for nl, lr, mdl in itertools.product((15, 31, 63), (0.05, 0.10),
                                             (20, 80))),
    ml.ADDITIVE: tuple(
        {"alpha": a, "n_knots": k, "degree": 3}
        for a, k in itertools.product((0.01, 0.1, 1.0, 10.0), (4, 6, 8))),
}


@dataclass(frozen=True)
class Trial:
    """One configuration and what it scored. Every one is published."""

    component: str
    config: dict[str, Any]
    fold_errors: tuple[float, ...]
    mean_error: float
    rounds: int = 0

    def row(self) -> dict[str, Any]:
        import json

        return {"component": self.component,
                "config": json.dumps(self.config, sort_keys=True),
                "mean_error": round(self.mean_error, 8),
                "fold_errors": json.dumps(
                    [round(e, 8) for e in self.fold_errors]),
                "rounds": int(self.rounds)}


@dataclass
class Fitted:
    """A trained component: the model, its settings and its own trace."""

    component: str
    config: dict[str, Any]
    model: Any
    rounds: int
    trials: list[Trial] = field(default_factory=list)
    seed: int = 0
    library_version: str = ""


def available() -> dict[str, str]:
    """Which component libraries are importable here, and at what version.

    An empty entry is not an error: the accepted environment has none of
    these and is supposed to. `train.py` turns an absence into
    `MODEL_NOT_READY` with the missing library named.
    """
    out: dict[str, str] = {}
    try:
        import xgboost

        out[ml.XGBOOST] = str(xgboost.__version__)
    except ImportError:
        out[ml.XGBOOST] = ""
    try:
        import lightgbm

        out[ml.LIGHTGBM] = str(lightgbm.__version__)
    except ImportError:
        out[ml.LIGHTGBM] = ""
    try:
        import sklearn

        out[ml.ADDITIVE] = str(sklearn.__version__)
    except ImportError:
        out[ml.ADDITIVE] = ""
    return out


def missing() -> list[str]:
    return [name for name, version in available().items() if not version]


def grid(component: str) -> tuple[dict[str, Any], ...]:
    """This family's configurations, capped at the declared budget."""
    return GRIDS[component][:ml.MAX_CONFIGS_PER_FAMILY]


def weighted_absolute_error(actual: Sequence[float],
                            predicted: Sequence[float],
                            weights: Sequence[float]) -> float:
    """WAPE in currency: `sum|pred - actual| / sum|actual|`, both weighted.

    The scoring metric throughout, including inside the search, so the
    configuration chosen is the one that wins on the measure the acceptance
    gate is written in. Tuning on RMSE and reporting WAPE would let a
    configuration win on a metric nobody is judging it by.
    """
    top = sum(abs((p - a) * w) for a, p, w in
              zip(actual, predicted, weights, strict=True))
    bottom = sum(abs(a * w) for a, w in zip(actual, weights, strict=True))
    return top / bottom if bottom else 0.0


def build(component: str, config: dict[str, Any], *, seed: int,
          rounds: int = 0) -> Any:
    """An untrained model of this family, with its seed set.

    `rounds` distinguishes the two things a booster is built for. During
    tuning it is zero: the model gets the full round cap and stops early
    against the fold's validation set. For the FINAL refit on all
    development periods there is no held-out set to stop against -- using
    one would be training on it -- so `rounds` carries the count the folds
    already justified and early stopping is switched off.

    Refitting with the tuned round count rather than the cap matters: a
    booster given 600 rounds on data it can memorise will use them.

    The additive component is a spline expansion followed by a ridge, which
    is `scikit-learn`'s `SplineTransformer` into `Ridge`. Its predictions are
    smooth and its errors are not the trees', which is the whole reason it is
    the third component.
    """
    if component == ml.XGBOOST:
        import xgboost

        settings: dict[str, Any] = {
            "n_estimators": rounds or ml.MAX_ROUNDS,
            "random_state": seed, "n_jobs": 2, "enable_categorical": True,
            "tree_method": "hist", "objective": "reg:squarederror"}
        if not rounds:
            settings["early_stopping_rounds"] = ml.EARLY_STOPPING_PATIENCE
        return xgboost.XGBRegressor(**settings, **config)
    if component == ml.LIGHTGBM:
        import lightgbm

        return lightgbm.LGBMRegressor(
            n_estimators=rounds or ml.MAX_ROUNDS, random_state=seed,
            n_jobs=2, verbose=-1, objective="regression", **config)
    if component == ml.ADDITIVE:
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import SplineTransformer

        return make_pipeline(
            SplineTransformer(n_knots=config["n_knots"],
                              degree=config["degree"],
                              include_bias=False),
            Ridge(alpha=config["alpha"], random_state=seed))
    raise ValueError(
        f"{component!r} is not a component of this blend. They are "
        f"{', '.join(ml.COMPONENTS)}.")


__all__ = ["Fitted", "GRIDS", "Trial", "available", "build", "grid",
           "missing", "weighted_absolute_error"]

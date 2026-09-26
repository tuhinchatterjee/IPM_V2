"""An additive model on the scale the target is actually additive on.

Version 1's third component was a spline expansion of the features in their
own units, fed to a ridge. It scored **0.32** mean fold WAPE on Corporate and
**1.82** on Retail against 0.03 and 0.08 for the boosters, and the weight fit
sent it to zero in both books -- which is the correct thing to do with a
component that is wrong by a factor of twenty.

It was not badly tuned. It was the wrong shape, and the reason is arithmetic:

    the target is        ecl_rate = pd x lgd
    an additive model is f(pd) + g(lgd)

No sum of univariate functions equals a product. More knots do not help;
`f + g` is the wrong function space. Whereas

    log(pd x lgd) = log pd + log lgd

is additive **exactly**, with no approximation and no interaction term. So
this component is the same family -- spline expansion into a ridge -- asked to
be additive in logs.

`ML_ACCEPTANCE_TARGETS_V2.md` §4 declares the change, its structural argument
and the development-only evidence behind it, before either version-2 model was
fitted.

## Why the classes are here and not closures in `components.build`

They are pickled. `card.freeze` writes each fitted component to disk and
`infer.load` reads it back, so every object in the pipeline has to be
importable by name from a stable module path. A `FunctionTransformer` wrapping
a lambda, or a class defined inside a function, pickles as a reference to
something that cannot be found again.

## Two transforms, and the one that is easy to get wrong

**Features.** `log(x + EPSILON)` for a column whose fitted support is
non-negative, identity for one that can be negative. The decision is made at
`fit` from the training column itself and remembered, so a scenario that
pushes a value negative at inference does not silently change which transform
that column gets.

**The target, and the smearing.** `exp(mean(log y))` is the geometric mean, not
the mean, and it is biased low -- by a factor that grows with the residual
variance. Predicting in logs and exponentiating would therefore understate
every ECL, consistently, in a way that looks like a well-behaved model with a
small negative bias. G2 would probably still pass, which is what makes it
dangerous rather than obvious.

Duan's smearing estimator is the correction: the mean of `exp(residual)` over
the training residuals, applied as a multiplicative factor. It is computed on
the DEVELOPMENT residuals only, it is published in the model card, and
`SMEARING_FLOOR` bounds it so a pathological fit cannot scale a prediction
arbitrarily.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin, TransformerMixin

#: Added before taking a log, so a zero rate or a zero parameter is
#: representable. Small enough not to move a real value, large enough that
#: `log` of it is finite: `log(1e-9)` is about -20.7.
EPSILON = 1e-9

#: A smearing factor outside this range means the residuals are not
#: log-normal enough for the correction to be a correction. Clipped, and the
#: clipping is visible in the card rather than silent.
SMEARING_FLOOR = 0.5
SMEARING_CEILING = 3.0


class LogFeatures(BaseEstimator, TransformerMixin):
    """`log(x + EPSILON)` on the columns whose fitted support is non-negative.

    Per column, decided at `fit` and remembered. Deciding again at `transform`
    would let a scenario that drives one value negative move that column onto
    a different scale from the one the coefficients were fitted on -- a
    different model, silently, for the rows that moved most.
    """

    def fit(self, X: Any, y: Any = None) -> LogFeatures:
        values = np.asarray(X, dtype=float)
        with np.errstate(invalid="ignore"):
            self.positive_ = np.nan_to_num(
                np.nanmin(values, axis=0), nan=0.0) >= 0.0
        self.n_features_in_ = values.shape[1]
        return self

    def transform(self, X: Any) -> Any:
        values = np.array(np.asarray(X, dtype=float), copy=True)
        if getattr(self, "positive_", None) is None:  # pragma: no cover
            raise RuntimeError("LogFeatures.transform before fit")
        columns = np.where(self.positive_)[0]
        if columns.size:
            taken = values[:, columns]
            # Clipped at zero before the shift: a column fitted as
            # non-negative can still be handed a small negative value by a
            # scenario, and `log` of it is not a number.
            values[:, columns] = np.log(np.clip(taken, 0.0, None) + EPSILON)
        return values

    def get_feature_names_out(self, input_features: Any = None) -> Any:
        if input_features is None:
            return np.asarray([f"x{i}" for i in range(self.n_features_in_)])
        return np.asarray(input_features)


class LogTargetRegressor(BaseEstimator, RegressorMixin):
    """Fit in logs, predict in levels, corrected for the log-mean bias.

    `smearing_` is Duan's estimator over the training residuals. It is
    published, and it is clipped: a factor outside
    `[SMEARING_FLOOR, SMEARING_CEILING]` says the residuals are not
    log-normal enough for this correction to be one, and scaling every
    prediction by it anyway would be asserting a distribution the data does
    not have.
    """

    def __init__(self, estimator: Any = None) -> None:
        self.estimator = estimator

    def fit(self, X: Any, y: Any) -> LogTargetRegressor:
        from sklearn.base import clone

        target = np.asarray(y, dtype=float)
        logged = np.log(np.clip(target, 0.0, None) + EPSILON)
        self.estimator_ = clone(self.estimator)
        self.estimator_.fit(X, logged)
        residuals = logged - np.asarray(
            self.estimator_.predict(X), dtype=float)
        raw = float(np.mean(np.exp(residuals))) if residuals.size else 1.0
        self.smearing_raw_ = raw
        self.smearing_ = float(
            min(max(raw, SMEARING_FLOOR), SMEARING_CEILING))
        self.smearing_clipped_ = self.smearing_ != raw
        return self

    def predict(self, X: Any) -> Any:
        logged = np.asarray(self.estimator_.predict(X), dtype=float)
        # Bounded before exponentiating: a ridge extrapolating on a spline
        # basis can return a large positive log, and `exp` of it is an
        # infinity that poisons a currency total. The bound is generous --
        # `exp(2)` is about 7.4, far above any ECL rate this book carries --
        # so it bites only where the answer was already meaningless.
        logged = np.clip(logged, np.log(EPSILON), 2.0)
        return np.clip(np.exp(logged) * self.smearing_ - EPSILON, 0.0, None)

    def diagnostics(self) -> dict[str, Any]:
        """What the card publishes about the back-transform."""
        return {"smearing": getattr(self, "smearing_", 1.0),
                "smearing_raw": getattr(self, "smearing_raw_", 1.0),
                "smearing_clipped": bool(
                    getattr(self, "smearing_clipped_", False)),
                "epsilon": EPSILON}


def pipeline(*, alpha: float, n_knots: int, degree: int, seed: int) -> Any:
    """The component: log features, spline basis, ridge, log target.

    The categorical half is unchanged from version 1 -- one-hot with a
    frequency floor -- because a category has no logarithm and a sector's
    effect is additive in logs the same way it was additive in levels.
    """
    from sklearn.compose import ColumnTransformer, make_column_selector
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline, make_pipeline
    from sklearn.preprocessing import OneHotEncoder, SplineTransformer

    numeric = make_pipeline(
        SimpleImputer(strategy="median"),
        LogFeatures(),
        SplineTransformer(n_knots=n_knots, degree=degree,
                          include_bias=False))
    categorical = OneHotEncoder(handle_unknown="ignore", sparse_output=False,
                               min_frequency=25)
    inner = Pipeline([
        ("prepare", ColumnTransformer([
            ("numeric", numeric,
             make_column_selector(dtype_exclude=["category", "object"])),
            ("categorical", categorical,
             make_column_selector(dtype_include=["category", "object"])),
        ], remainder="drop")),
        ("model", Ridge(alpha=alpha, random_state=seed)),
    ])
    return LogTargetRegressor(estimator=inner)


__all__ = ["EPSILON", "SMEARING_CEILING", "SMEARING_FLOOR", "LogFeatures",
           "LogTargetRegressor", "pipeline"]

"""
Training the ML ECL methodology, and the splits that make its score mean
something.

Time, not chance
----------------
A random split of a panel is a leak. The same borrower appears in sixteen
quarters, and a random 30% holdout puts Q1's row in training and Q2's in the
holdout — the model then scores beautifully by having memorised the borrower
rather than learned the relationship.

So every split here is CHRONOLOGICAL:

    development  ...  through Q4 2025   (train on the earlier ~70%,
                                         validate on the later ~30%)
    out-of-time  ...  Q1 2026, Q2 2026  (locked; never trained on)

The out-of-time quarters are the only honest read on whether the model works on
a period it has never seen, so they are held out of both training AND
validation, and `Split.check()` refuses a configuration where they overlap.

What the score will look like, and why
--------------------------------------
On this synthetic book the reported ECL is very close to a closed form —
`PD_applicable x LGD x EAD x 1.082` plus a management overlay on about six per
cent of rows — so a model given PD, LGD and Stage can reproduce the rate almost
exactly. R-squared will be very high, and that is MECHANICAL rather than
evidence of predictive skill. It is reported honestly and said plainly on the
model card, because a screen that presented it as a discovery would be lying
about what the number means.

The model still earns its place: it responds smoothly where the governed
formula steps, it has learned what the overlay does, and it carries the
interactions between collateral, Stage and PD that a proportional sensitivity
cannot express. That is what makes it a genuinely different second opinion
rather than the Delta Model with extra arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.whatif import domain as dm
from backend.whatif.ml import features as ft

TRAIN_VERSION = "1.0.0"

#: Fixed so a rebuild reproduces the model exactly.
SEED = 20260906

#: The share of development quarters used for training; the rest validate.
TRAIN_SHARE = 0.70

#: The last quarter the reference model is developed through. Everything after
#: it is out-of-time. Resolved against the book rather than assumed to exist.
DEFAULT_DEVELOPMENT_THROUGH = "Q4 2025"

#: Deliberately modest. A book of fifty thousand rows and thirty-one features
#: does not need a deep forest, and a shallow one is easier to explain and far
#: less likely to memorise a borrower.
HYPERPARAMETERS: dict[str, Any] = {
    "n_estimators": 400,
    "max_depth": 5,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "reg_lambda": 1.0,
    "objective": "reg:squarederror",
    "tree_method": "hist",
    "random_state": SEED,
    "n_jobs": 4,
}


class TrainingError(ValueError):
    """A training run that must not proceed."""


@dataclass(frozen=True)
class Split:
    """Which quarters train, which validate, and which are locked away."""

    train: tuple[str, ...]
    validation: tuple[str, ...]
    out_of_time: tuple[str, ...]
    excluded: tuple[str, ...] = ()

    def check(self) -> None:
        """Refuse a split that cannot answer the question it is asked."""
        if not self.train:
            raise TrainingError("A model needs at least one training quarter.")
        overlaps = [
            ("training", "validation", set(self.train) & set(self.validation)),
            ("training", "out-of-time", set(self.train) & set(self.out_of_time)),
            ("validation", "out-of-time",
             set(self.validation) & set(self.out_of_time)),
        ]
        for left, right, shared in overlaps:
            if shared:
                raise TrainingError(
                    f"{', '.join(sorted(shared))} appears in both the {left} "
                    f"and the {right} set. A quarter on both sides of a split "
                    "makes the score meaningless.")

    def to_dict(self) -> dict[str, Any]:
        return {"train": list(self.train), "validation": list(self.validation),
                "out_of_time": list(self.out_of_time),
                "excluded": list(self.excluded),
                "by": "chronological",
                "why": ("A random split of a panel puts the same borrower on "
                        "both sides and scores memorisation as skill.")}

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> Split:
        return cls(train=tuple(body.get("train") or ()),
                   validation=tuple(body.get("validation") or ()),
                   out_of_time=tuple(body.get("out_of_time") or ()),
                   excluded=tuple(body.get("excluded") or ()))


def plan_split(*, development_through: str = DEFAULT_DEVELOPMENT_THROUGH,
               excluded: tuple[str, ...] = (),
               train_share: float = TRAIN_SHARE,
               source: Any = None) -> Split:
    """The default split, derived from the quarters the book actually holds.

    `development_through` is resolved against the book, so a period the lake
    does not publish is a refusal rather than a silently empty training set.
    """
    available = [p for p in dm.periods(source) if p not in set(excluded)]
    if not available:
        raise TrainingError("Corporate IFRS 9 publishes no periods to train on.")
    cut = dm.resolve_period(development_through, source)
    if cut not in available:
        raise TrainingError(
            f"'{development_through}' is excluded from training, so it cannot "
            "also be the quarter development runs through.")
    at = available.index(cut)
    development = available[: at + 1]
    out_of_time = available[at + 1:]
    if len(development) < 2:
        raise TrainingError(
            f"Development through {cut} leaves {len(development)} quarter(s), "
            "which is not enough to train and validate on separate periods.")
    edge = max(1, int(round(len(development) * float(train_share))))
    edge = min(edge, len(development) - 1)
    return Split(train=tuple(development[:edge]),
                 validation=tuple(development[edge:]),
                 out_of_time=tuple(out_of_time), excluded=tuple(excluded))


def load(periods: tuple[str, ...], *, source: Any = None) -> pd.DataFrame:
    """The book across several quarters, stacked."""
    frames = []
    for period in periods:
        frame, settled = dm.book(period, source=source)
        frames.append(frame.assign(period=settled))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def metrics(actual: pd.Series | np.ndarray, predicted: pd.Series | np.ndarray,
            *, weights: pd.Series | np.ndarray | None = None) -> dict[str, Any]:
    """The measures a validation report should carry, and not "accuracy".

    Accuracy is a classification word. This model predicts a rate, so the
    question is how far off it is and whether the error is worth anything —
    R-squared, mean absolute error, root mean squared error, and WAPE, which is
    the one a credit person reads because it is expressed relative to the
    provision actually held.
    """
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    y = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    if len(y) == 0:
        return {"count": 0, "r2": None, "mae": None, "rmse": None,
                "wape": None, "exposure_weighted_mae": None}
    total = float(np.abs(y).sum())
    body = {
        "count": int(len(y)),
        "r2": round(float(r2_score(y, p)), 6) if len(y) > 1 else None,
        "mae": round(float(mean_absolute_error(y, p)), 8),
        "rmse": round(float(np.sqrt(mean_squared_error(y, p))), 8),
        "wape": round(float(np.abs(y - p).sum() / total * 100.0), 4)
        if total > 0 else None,
        "mean_actual": round(float(y.mean()), 8),
        "mean_predicted": round(float(p.mean()), 8),
        "exposure_weighted_mae": None,
    }
    if weights is not None:
        w = np.asarray(weights, dtype=float)
        if w.sum() > 0:
            body["exposure_weighted_mae"] = round(
                float((np.abs(y - p) * w).sum() / w.sum()), 8)
    return body


def sliced(frame: pd.DataFrame, actual: np.ndarray, predicted: np.ndarray,
           column: str, *, bands: list[tuple[str, Any, Any]] | None = None
           ) -> list[dict[str, Any]]:
    """Error broken down, because a book-level average hides where it is wrong."""
    out: list[dict[str, Any]] = []
    if column not in frame.columns and not bands:
        return out
    if bands:
        values = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
        groups = [(label, (values >= low) & (values < high))
                  for label, low, high in bands]
    else:
        series = frame[column].astype(str)
        groups = [(str(v), series == str(v)) for v in sorted(series.unique())]
    ead = pd.to_numeric(frame.get("ead"), errors="coerce").fillna(0.0)
    for label, mask in groups:
        chosen = np.asarray(mask)
        if not chosen.any():
            continue
        body = metrics(actual[chosen], predicted[chosen],
                       weights=ead.to_numpy()[chosen])
        body["label"] = label
        body["exposure"] = float(ead.to_numpy()[chosen].sum())
        out.append(body)
    return out


PD_BANDS: list[tuple[str, Any, Any]] = [
    ("0 to 0.5%", 0.0, 0.5), ("0.5 to 2%", 0.5, 2.0), ("2 to 5%", 2.0, 5.0),
    ("5 to 13%", 5.0, 13.0), ("13% and above", 13.0, 1e9)]
LGD_BANDS: list[tuple[str, Any, Any]] = [
    ("under 30%", 0.0, 30.0), ("30 to 45%", 30.0, 45.0),
    ("45 to 60%", 45.0, 60.0), ("60% and above", 60.0, 1e9)]


@dataclass
class Trained:
    """A fitted model and everything needed to judge or reproduce it."""

    booster: Any
    encoding: ft.Encoding
    split: Split
    hyperparameters: dict[str, Any]
    feature_names: tuple[str, ...]
    rows: dict[str, int] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    out_of_time: dict[str, Any] = field(default_factory=dict)
    training: dict[str, Any] = field(default_factory=dict)
    slices: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: The observed range of each feature, for the out-of-distribution check.
    ranges: dict[str, dict[str, float]] = field(default_factory=dict)

    def artifact(self) -> bytes:
        """The model as XGBoost's native JSON. Never a pickle.

        `save_raw(raw_format="json")` returns the same bytes `save_model` would
        write to a .json file, without going through the filesystem.
        """
        return bytes(self.booster.get_booster().save_raw(raw_format="json"))


def fit(*, split: Split | None = None, source: Any = None,
        hyperparameters: dict[str, Any] | None = None) -> Trained:
    """Train the model, validate it, and score it out of time."""
    from xgboost import XGBRegressor

    chosen = split or plan_split(source=source)
    chosen.check()

    train_frame = load(chosen.train, source=source)
    validation_frame = load(chosen.validation, source=source)
    oot_frame = load(chosen.out_of_time, source=source)
    if train_frame.empty:
        raise TrainingError(
            "The training quarters produced no rows. Has the analytical lake "
            "been built?")

    train_matrix = ft.build(train_frame)
    encoding = train_matrix.encoding
    validation_matrix = (ft.build(validation_frame, encoding=encoding)
                         if not validation_frame.empty else None)
    oot_matrix = (ft.build(oot_frame, encoding=encoding)
                  if not oot_frame.empty else None)

    settings = {**HYPERPARAMETERS, **(hyperparameters or {})}
    model = XGBRegressor(**settings)
    if validation_matrix is not None:
        model.fit(train_matrix.X, train_matrix.y,
                  eval_set=[(validation_matrix.X, validation_matrix.y)],
                  verbose=False)
    else:  # pragma: no cover - a split with no validation is refused earlier
        model.fit(train_matrix.X, train_matrix.y, verbose=False)

    warnings: list[str] = []
    if train_matrix.dropped_no_exposure:
        warnings.append(
            f"{train_matrix.dropped_no_exposure:,} training row(s) had no "
            "exposure and therefore no ECL rate. They were dropped.")
    if not chosen.out_of_time:
        warnings.append(
            "No out-of-time quarters were held back, so there is no read on "
            "how the model behaves on a period it has never seen.")

    trained = Trained(
        booster=model, encoding=encoding, split=chosen,
        hyperparameters=settings, feature_names=tuple(ft.FEATURES),
        rows={"train": train_matrix.rows,
              "validation": validation_matrix.rows if validation_matrix else 0,
              "out_of_time": oot_matrix.rows if oot_matrix else 0},
        warnings=warnings)

    predicted_train = model.predict(train_matrix.X)
    trained.training = metrics(train_matrix.y, predicted_train)
    if validation_matrix is not None:
        predicted = model.predict(validation_matrix.X)
        weights = pd.to_numeric(
            validation_frame.loc[validation_matrix.X.index, "ead"],
            errors="coerce").fillna(0.0)
        trained.validation = metrics(validation_matrix.y, predicted, weights=weights)
        rows = validation_frame.loc[validation_matrix.X.index]
        actual = validation_matrix.y.to_numpy()
        trained.slices = {
            "stage": sliced(rows, actual, predicted, "stage"),
            "sector": sliced(rows, actual, predicted, "sector"),
            "period": sliced(rows, actual, predicted, "period"),
            "pd_band": sliced(rows, actual, predicted, "pd_12m", bands=PD_BANDS),
            "lgd_band": sliced(rows, actual, predicted, "lgd", bands=LGD_BANDS),
        }
    if oot_matrix is not None:
        predicted_oot = model.predict(oot_matrix.X)
        weights = pd.to_numeric(
            oot_frame.loc[oot_matrix.X.index, "ead"], errors="coerce").fillna(0.0)
        trained.out_of_time = metrics(oot_matrix.y, predicted_oot, weights=weights)
        trained.slices["out_of_time_period"] = sliced(
            oot_frame.loc[oot_matrix.X.index], oot_matrix.y.to_numpy(),
            predicted_oot, "period")

    trained.ranges = {
        name: {"min": float(train_matrix.X[name].min()),
               "max": float(train_matrix.X[name].max()),
               "p01": float(train_matrix.X[name].quantile(0.01)),
               "p99": float(train_matrix.X[name].quantile(0.99))}
        for name in ft.FEATURES}
    return trained


__all__ = [
    "DEFAULT_DEVELOPMENT_THROUGH", "HYPERPARAMETERS", "LGD_BANDS", "PD_BANDS",
    "SEED", "Split", "TRAIN_SHARE", "TRAIN_VERSION", "Trained",
    "TrainingError", "fit", "load", "metrics", "plan_split", "sliced",
]

"""The What-If challenger, fitted once and kept, instead of once per scenario.

The defect this exists for
---------------------------
§10.2 asks for a clickable XGBoost page with a persisted artifact and
save/load parity. This installation had neither half.

The model page at `/what-if/models/ml` reads `/whatif/models/ml`, which is the
CORPORATE registry. Asked to train here it answers, correctly, "Corporate
IFRS 9 publishes no periods to train on" — so the page showed a card with no
versions for a model that cannot exist in a retail installation.

Meanwhile the challenger that actually runs retail scenarios lived inside
`whatif_cohort._challenger`: fitted on the spot, from the whole book, on every
single run, and discarded. Three consequences, in rising order of seriousness.
It is slow — a gradient boosting fit over the book is the dominant cost of a
scenario that is otherwise arithmetic. It cannot be inspected — there is
nothing to open, no feature list to read, no metric to argue with, which is
the opposite of what a model page is for. And it is not reproducible in the
way a bank needs: "the challenger said X last Tuesday" is unanswerable when
the model that said it no longer exists.

What is stored
---------------
One directory per book: the fitted estimator, the feature list in the order
it was trained on, the library that fitted it, the training window, and the
metrics computed on a held-out slice. Stamped with the book's manifest hash,
so a regenerated book invalidates the artifact rather than serving a model
trained on data that is gone — the same rule as every other derived domain
here, and for the same reason.

Save/load parity
-----------------
The artifact is only worth keeping if loading it gives the answer fitting it
gave. `parity()` fits, saves, loads and scores the same rows through both,
and reports the largest disagreement. It is exercised by
`scripts/retail_uat/phase9_challenger.py`, not asserted here.
"""

from __future__ import annotations

import json
import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CHALLENGER_VERSION = "retail-whatif-challenger-2.0.0"

#: Where the artifact lives, beside the derived domains it is computed from.
DOMAIN = "retail_whatif_challenger"

#: The parameters the challenger is allowed to learn from. Deliberately the
#: IFRS 9 inputs and nothing else: a model that reached for `customer_id` or
#: a product label would fit the book's identifiers rather than its credit
#: relationships, and would then be unable to say anything about a shock.
FEATURES: tuple[str, ...] = (
    "pd_pit_12m_base", "pd_pit_lifetime_base", "lgd_base", "ead_base_sar",
    "ccf_base", "gross_carrying_amount_sar", "ifrs9_stage", "dpd",
)

TARGET = "ecl_weighted_sar"

#: Below this the fit is not a model, it is a memorisation.
LEAST_ROWS = 500

#: How much of the book is held back to measure on. A challenger whose only
#: metric is its training error tells the reader nothing they can use.
HELD_BACK = 0.25

SEED = 20260914


class ChallengerUnavailable(RuntimeError):
    """The artifact cannot be built or loaded, with the reason."""


@dataclass
class Card:
    """What the model page shows, and what the scenario loads."""

    version: str = CHALLENGER_VERSION
    library: str = ""
    features: tuple[str, ...] = ()
    target: str = TARGET
    source_hash: str = ""
    month: str = ""
    rows_fitted: int = 0
    rows_held_back: int = 0
    seconds: float = 0.0
    built_at: str = ""
    #: Measured on the held-back rows, never on the training rows.
    metrics: dict[str, float] = field(default_factory=dict)
    #: Measured on the training rows, for comparison — a large gap between
    #: the two is the thing a reader should see, so both are shown.
    training_metrics: dict[str, float] = field(default_factory=dict)
    importance: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "library": self.library,
            "features": list(self.features), "target": self.target,
            "source_hash": self.source_hash, "month": self.month,
            "rows_fitted": self.rows_fitted,
            "rows_held_back": self.rows_held_back,
            "seconds": round(self.seconds, 2), "built_at": self.built_at,
            "metrics": dict(self.metrics),
            "training_metrics": dict(self.training_metrics),
            "importance": list(self.importance),
        }


def _root() -> Path:
    from backend.config import settings

    return Path(settings.analytics_dir) / DOMAIN


def _estimator() -> tuple[Any, str]:
    """XGBoost where the installation has it, scikit-learn where it does not.

    Which one actually ran is recorded on the card. The method was keyed
    "xgboost" while it fitted a scikit-learn estimator, and a reader comparing
    two methodologies has to be able to see which model produced the number in
    front of them.
    """
    try:
        import xgboost
        from xgboost import XGBRegressor

        return (XGBRegressor(n_estimators=120, max_depth=6, learning_rate=0.1,
                             tree_method="hist", random_state=SEED, n_jobs=2),
                f"XGBoost {xgboost.__version__}")
    except ImportError:
        pass
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor

        return (HistGradientBoostingRegressor(
            max_iter=120, max_depth=6, learning_rate=0.1, random_state=SEED),
            "scikit-learn HistGradientBoostingRegressor — XGBoost is not "
            "installed here")
    except ImportError as problem:
        raise ChallengerUnavailable(
            "The challenger estimator needs XGBoost or scikit-learn, and this "
            "installation has neither.") from problem


def _score(model: Any, X: Any, y: Any) -> dict[str, float]:
    """The three a reader of a loss model asks for.

    WAPE rather than MAPE. Expected credit loss is near zero on most
    facilities and exactly zero on some, so a percentage error per row
    divides by something arbitrarily small and reports a number in the
    thousands for a model that is fine. WAPE divides the total error by the
    total loss, which is the question anybody actually has.
    """
    import numpy as np

    predicted = np.asarray(model.predict(X), dtype=float)
    actual = np.asarray(y, dtype=float)
    error = predicted - actual
    total = float(np.abs(actual).sum())
    spread = float(((actual - actual.mean()) ** 2).sum())
    return {
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt((error ** 2).mean())),
        "wape": (float(np.abs(error).sum() / total) if total else 0.0),
        "r2": (1.0 - float((error ** 2).sum()) / spread) if spread else 0.0,
    }


def _book(month: str = "") -> tuple[Any, str]:
    """One month of the canonical book, through the reader that caches it.

    The same `_read_book` the scenario path uses. Reading it a second way
    here would parse the parquet again for no reason, and would risk the
    challenger being fitted on a frame the scenario does not score against.
    """
    from backend.retail import ews_score, measures

    months = measures.months()
    at = month or (months[-1] if months else "")
    if not at:
        raise ChallengerUnavailable(
            "The retail book publishes no months, so there is nothing to fit "
            "a challenger on.")
    return ews_score._read_book(at), at


def build(month: str = "", *, save: bool = True) -> tuple[Any, Card]:
    """Fit the challenger on the book and, by default, keep it."""
    import numpy as np

    from backend.retail import source_stamp

    started = time.time()
    book, at = _book(month)
    have = [one for one in FEATURES if one in book.columns]
    if len(have) < 5:
        raise ChallengerUnavailable(
            f"The book carries only {len(have)} of the {len(FEATURES)} risk "
            f"parameters the challenger is fitted on, which is not enough to "
            f"say anything about a shock.")
    frame = book[have + [TARGET]].dropna()
    if len(frame) < LEAST_ROWS:
        raise ChallengerUnavailable(
            f"{len(frame)} complete rows is too few to fit a challenger; "
            f"{LEAST_ROWS} is the floor.")

    # Held back at random with a fixed seed rather than by period: this is a
    # cross-sectional model of the IFRS 9 relationship at one month, not a
    # forecast, so an out-of-time split would measure something the model does
    # not claim. The seed is fixed so two builds of the same book hold back
    # the same rows and their metrics are comparable.
    rng = np.random.default_rng(SEED)
    keep = rng.random(len(frame)) >= HELD_BACK
    train, test = frame[keep], frame[~keep]
    if len(test) < 50:
        train, test = frame, frame

    model, library = _estimator()
    X = train[have].to_numpy(dtype=float)
    y = train[TARGET].to_numpy(dtype=float)
    model.fit(X, y)

    card = Card(
        library=library, features=tuple(have), source_hash=source_stamp.book_hash(),
        month=at, rows_fitted=int(len(train)), rows_held_back=int(len(test)),
        built_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        metrics=_score(model, test[have].to_numpy(dtype=float),
                       test[TARGET].to_numpy(dtype=float)),
        training_metrics=_score(model, X, y),
        importance=_importance(model, have),
    )
    card.seconds = time.time() - started
    if save:
        _save(model, card)
    return model, card


def _importance(model: Any, names: list[str]) -> list[dict[str, Any]]:
    """Which parameters the fit leant on, where the estimator will say.

    Not an explanation of a prediction and not offered as one. It is the
    model's own weighting, which is the least a reader may ask of a model
    they are being shown beside the calculation of record.
    """
    raw = getattr(model, "feature_importances_", None)
    if raw is None:
        return []
    total = float(sum(float(one) for one in raw)) or 1.0
    rows = [{"feature": name, "share": round(float(one) / total, 4)}
            for name, one in zip(names, raw)]
    return sorted(rows, key=lambda one: one["share"], reverse=True)


def _save(model: Any, card: Card) -> Path:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "model.pkl").write_bytes(pickle.dumps(model))
    (root / "card.json").write_text(json.dumps(card.to_dict(), indent=1) + "\n")
    # The same stamp every other derived domain carries, so a regenerated
    # book invalidates this artifact by the same rule rather than a special
    # one somebody has to remember.
    from backend.retail import source_stamp
    from backend.config import settings

    source_stamp.record(Path(settings.analytics_dir), DOMAIN)
    return root


def held() -> Card | None:
    """The stored card, or None. Reads no model."""
    try:
        return Card(**{
            **json.loads((_root() / "card.json").read_text()),
            "features": tuple(json.loads(
                (_root() / "card.json").read_text()).get("features") or ()),
        })
    except Exception:  # noqa: BLE001 - an installation with no artifact yet
        return None


def stale() -> bool:
    """True when the stored artifact was fitted on a different book."""
    from backend.config import settings
    from backend.retail import source_stamp

    return source_stamp.stale(Path(settings.analytics_dir), DOMAIN)


def load(*, build_if_missing: bool = True) -> tuple[Any, Card]:
    """The challenger a scenario should score with.

    Rebuilt rather than served when the book underneath it has changed. A
    model trained on a book that no longer exists, answering questions about
    the one that does, is the failure the stamps exist to prevent — and it is
    invisible without them, because the artifact loads perfectly.
    """
    root = _root()
    card = held()
    if card is not None and not stale():
        try:
            return pickle.loads((root / "model.pkl").read_bytes()), card
        except Exception:  # noqa: BLE001 - a corrupt artifact is a rebuild
            pass
    if not build_if_missing:
        raise ChallengerUnavailable(
            "No challenger artifact is stored for the published book. Run the "
            "bootstrap, or POST to the rebuild endpoint.")
    return build()


def parity(month: str = "") -> dict[str, Any]:
    """Fit, save, load, and score the same rows through both. §10.2.

    An artifact is only worth keeping if loading it gives the answer fitting
    it gave. This is the check that says so, in the units a reader
    understands: the largest disagreement on one facility, and on the total.
    """
    import numpy as np

    fitted, card = build(month, save=True)
    loaded, stored = load(build_if_missing=False)
    book, _ = _book(month or card.month)
    have = list(card.features)
    rows = book[have].dropna().head(5000).to_numpy(dtype=float)
    if not len(rows):
        raise ChallengerUnavailable("No complete rows to score for parity.")
    a = np.asarray(fitted.predict(rows), dtype=float)
    b = np.asarray(loaded.predict(rows), dtype=float)
    worst = float(np.abs(a - b).max())
    return {
        "rows": int(len(rows)),
        "identical": bool(worst == 0.0),
        "largest_row_disagreement_sar": worst,
        "total_disagreement_sar": float(abs(a.sum() - b.sum())),
        "fitted_version": card.version,
        "loaded_version": stored.version,
        "same_book": card.source_hash == stored.source_hash,
        "says": ("The loaded artifact scores identically to the model that "
                 "was fitted." if worst == 0.0 else
                 f"The loaded artifact disagrees with the fitted model by up "
                 f"to {worst:,.6f} SAR on a facility, which means the "
                 f"artifact is not the model."),
    }


def example(rows: int = 8, month: str = "") -> dict[str, Any]:
    """One worked example: real facilities, scored, against their book value.

    §10.2 asks for a worked example on the model page. The useful one here is
    not a made-up borrower — it is facilities out of this book, with what the
    challenger says beside what the IFRS 9 engine recorded, so a reader can
    see the size of the disagreement on a row rather than being told an R².

    Chosen by exposure, largest first, because those are the rows where a
    disagreement matters and the ones a committee would ask about.
    """
    import numpy as np

    model, card = load()
    book, at = _book(month or card.month)
    have = list(card.features)
    # De-duplicated. `ifrs9_stage` is both a feature and a column worth
    # showing, and asking pandas for it twice gives the frame two columns of
    # that name — so `frame[have]` came back nine wide for an eight-feature
    # model and XGBoost refused the shape.
    wanted = list(dict.fromkeys(
        one for one in (list(have) + [TARGET, "facility_id", "product_label",
                                      "ifrs9_stage"])
        if one in book.columns))
    frame = book[wanted].dropna(subset=have + [TARGET])
    if not len(frame):
        raise ChallengerUnavailable("No complete rows to work an example on.")
    order = ("gross_carrying_amount_sar" if "gross_carrying_amount_sar"
             in frame.columns else TARGET)
    frame = frame.sort_values(order, ascending=False).head(max(1, rows))
    predicted = np.asarray(
        model.predict(frame[have].to_numpy(dtype=float)), dtype=float)
    actual = np.asarray(frame[TARGET], dtype=float)

    out: list[dict[str, Any]] = []
    for index, (_, row) in enumerate(frame.iterrows()):
        recorded = float(actual[index])
        said = float(predicted[index])
        out.append({
            "facility_id": str(row.get("facility_id", "")),
            "product": str(row.get("product_label", "")),
            "stage": (int(row["ifrs9_stage"])
                      if "ifrs9_stage" in row and row["ifrs9_stage"] == row["ifrs9_stage"]
                      else None),
            "inputs": {one: float(row[one]) for one in have},
            "recorded_ecl_sar": round(recorded, 2),
            "challenger_ecl_sar": round(said, 2),
            "difference_sar": round(said - recorded, 2),
            "difference_pct": (round((said - recorded) / recorded, 4)
                               if recorded else None),
        })
    return {
        "month": at, "version": card.version, "library": card.library,
        "rows": out,
        "says": ("Facilities from the published book, largest exposure "
                 "first, scored by the stored challenger and shown beside "
                 "the expected credit loss the IFRS 9 engine recorded for "
                 "them. The engine's figure is the one of record."),
    }


__all__ = ["CHALLENGER_VERSION", "Card", "ChallengerUnavailable", "DOMAIN",
           "FEATURES", "TARGET", "build", "example", "held", "load",
           "parity", "stale"]

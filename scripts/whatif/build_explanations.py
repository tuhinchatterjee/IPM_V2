#!/usr/bin/env python3
"""Publish the offline ML prediction explanation for each book.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------

Section 13.2 asks for two things that share the word "contribution":

* **Scenario-impact attribution** -- why ECL moved from baseline to scenario.
  That is `scenario/attribution.py`, measured by re-running the calculation
  over coalitions of the scenario's own interventions, and it reconciles to
  the ECL change because it is a measurement of it.
* **ML prediction explanation** -- why the fitted emulator returns the number
  it returns. That is this file, plus `scenario/ml/explain.py`. It describes a
  function's response to its own inputs and it reconciles to nothing about
  the scenario.

  > *"Never present feature importance as a decomposition of the scenario ECL
  > movement."*

Nothing written here carries a currency amount. Every value is in the model's
own rate space or is a dimensionless share, and `explain.never_a_decomposition`
refuses any row that carries an ECL column.

WHY OFFLINE
-----------

A partial-dependence curve needs the whole blend evaluated over a grid for
every feature. Section 7.1 forbids a reader's question triggering that kind of
work in a chat turn, so it is computed once, here, on the DEVELOPMENT window
only -- never on the untouched test split -- and published beside the model as
documentation. The rows say, in the status the reader sees, that they describe
the fitted function on the development window and not the cohort in view.

Measured on a GENERATED book. Nothing here is bank output, an accounting
figure, or a bank-validated model.

Usage:
    .venv-whatif/bin/python scripts/whatif/build_explanations.py --domain all
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.cockpit_v4.scenario.ml import explain as ex  # noqa: E402
from backend.cockpit_v4.scenario.ml import features as ft  # noqa: E402
from backend.cockpit_v4.scenario.ml import infer as inf  # noqa: E402
from backend.cockpit_v4.scenario.ml import split as sp  # noqa: E402
from backend.cockpit_v4.scenario.ml import train as tr  # noqa: E402

BOOKS = ("corporate", "retail")

#: How many rows the partial-dependence pass averages over. A curve is a mean
#: prediction per grid point, and the mean stops moving long before the rows
#: run out; 4,000 keeps the whole build inside a couple of minutes per book
#: while leaving the shape stable to the third decimal.
SAMPLE_ROWS = 4_000

#: Grid points per numeric feature. Deciles plus the two ends: enough to see a
#: bend, few enough that the curve is readable as a sentence.
GRID_POINTS = 11

#: A curve counts as flat when its whole range is this small a share of the
#: mean prediction. Stated rather than eyeballed, so "flat" means one thing.
FLAT_SHARE = 0.01

#: The seed for the row sample. The document is part of the model's
#: documentation, so two builds of the same model must produce the same file.
SEED = 20260930


def development_frame(domain_id: str, manifest: dict[str, Any]):
    """The development window, and nothing else.

    The test split is not read here. A response curve fitted or even measured
    on the untouched split would be a look at the data the gates are judged
    against, which section 12 rules out however harmless the intent.
    """
    from scripts.whatif import train_emulator as te

    _key, period_column = ft.KEYS[domain_id]
    frame = te.load(domain_id)
    embargo, rule = sp.label_embargo(
        frame.to_dict("records")[:1], period_column=period_column)
    assignment = sp.assign(sorted(frame[period_column].unique()),
                           embargo=embargo, rule=rule)
    leaks = sp.leakage(assignment)
    if leaks:
        raise SystemExit(f"the split leaks: {leaks}")
    keep = frame[period_column].astype(str).isin(
        list(assignment.train) + list(assignment.validate))
    held = sorted(set(str(p) for p in assignment.test))
    declared = sorted(str(p) for p in (manifest.get("test_periods") or []))
    if declared and held != declared:
        raise SystemExit(
            f"this split holds back {held} and the published model holds back "
            f"{declared}. A document built against a different split than the "
            f"model describes a different model.")
    return frame[keep].reset_index(drop=True), assignment


def importance(loaded: inf.Loaded, names: list[str]) -> list[dict[str, Any]]:
    """Gain-based importance, as a share, combined by blend weight.

    Only the tree components have split gain; an additive model has no splits
    and contributes nothing here, which is stated rather than silently
    treated as zero importance everywhere.
    """
    shares: dict[str, float] = {name: 0.0 for name in names}
    explained: list[str] = []
    skipped: list[str] = []
    for component, weight in sorted(loaded.weights.items()):
        if weight <= 0.0:
            continue
        model = loaded.models.get(component)
        gains = _gain_of(model, names)
        if gains is None:
            skipped.append(component)
            continue
        explained.append(component)
        total = sum(gains.values()) or 1.0
        for name, value in gains.items():
            shares[name] = shares.get(name, 0.0) + weight * value / total
    ranked = sorted(shares.items(), key=lambda kv: -kv[1])
    out = [{"feature": name, "value": round(share, 6),
            "unit": "share of split gain",
            "combined_over": ", ".join(explained) or "no tree component",
            "no_gain_from": ", ".join(skipped)}
           for name, share in ranked[:ex.TOP_FEATURES] if share > 0.0]
    return out


def _gain_of(model: Any, names: list[str]) -> dict[str, float] | None:
    """One component's gain per feature, whatever library fitted it."""
    inner = getattr(model, "model", model)
    booster = getattr(inner, "get_booster", None)
    if callable(booster):                      # xgboost
        raw = booster().get_score(importance_type="gain")
        return {name: float(raw.get(name, 0.0)) for name in names}
    gains = getattr(inner, "feature_importances_", None)
    if gains is not None and hasattr(inner, "booster_"):   # lightgbm
        used = list(getattr(inner, "feature_name_", names))
        got = {u: float(g) for u, g in zip(used, list(gains), strict=False)}
        return {name: got.get(name, 0.0) for name in names}
    return None


def responses(loaded: inf.Loaded, frame: Any, names: list[str]
              ) -> list[dict[str, Any]]:
    """A partial-dependence curve per feature, summarised as a sentence.

    The blend's OWN prediction is used, not a component's: the reader is shown
    one estimate and the relationship they are told about has to be the
    relationship of the thing that produced it.
    """
    import numpy as np

    sample = frame
    if len(frame) > SAMPLE_ROWS:
        sample = frame.sample(n=SAMPLE_ROWS, random_state=SEED)
    sample = sample.reset_index(drop=True)
    base = float(np.mean(loaded.raw(sample)))
    out: list[dict[str, Any]] = []
    for name in names:
        grid = _grid(sample[name])
        if grid is None:
            continue
        curve: list[dict[str, Any]] = []
        for point in grid:
            moved = sample.copy()
            moved[name] = point
            # THE DTYPE IS PART OF THE FRAME THE MODEL WAS FITTED ON.
            #
            # Assigning a scalar into a categorical column turns it into an
            # object column, and the boosters refuse a frame whose columns are
            # not the ones they were trained with. Restoring the dtype keeps
            # the grid pass over exactly the frame the model expects, so the
            # curve describes the fitted function rather than a coercion of it.
            moved[name] = moved[name].astype(sample[name].dtype)
            curve.append({"at": _plain(point),
                          "mean_prediction": round(
                              float(np.mean(loaded.raw(moved))), 8)})
        out.append({
            "feature": name,
            "unit": "mean prediction, model rate space",
            "base_mean_prediction": round(base, 8),
            "curve": curve,
            "shape": _shape(name, curve, base),
        })
    out.sort(key=lambda row: -_span(row["curve"]))
    return out[:ex.TOP_FEATURES]


def _grid(column: Any) -> list[Any] | None:
    """The values a feature is walked over. Its own, never invented ones."""
    import numpy as np
    import pandas as pd

    if isinstance(column.dtype, pd.CategoricalDtype) or column.dtype == object:
        seen = [v for v in column.value_counts().index[:8]]
        return seen or None
    values = pd.to_numeric(column, errors="coerce").dropna()
    if values.empty or values.nunique() < 2:
        return None
    quantiles = np.linspace(0.0, 1.0, GRID_POINTS)
    grid = sorted({float(values.quantile(q)) for q in quantiles})
    return grid if len(grid) > 1 else None


def _span(curve: list[dict[str, Any]]) -> float:
    got = [row["mean_prediction"] for row in curve]
    return max(got) - min(got) if got else 0.0


def _shape(name: str, curve: list[dict[str, Any]], base: float) -> str:
    """The relationship in words, with the numbers that make it checkable."""
    got = [row["mean_prediction"] for row in curve]
    low, high = min(got), max(got)
    span = high - low
    if base and span / abs(base) < FLAT_SHARE:
        return (f"flat: moving {name} across its own range changes the mean "
                f"prediction by {span:.8f}, under {FLAT_SHARE:.0%} of the "
                f"mean of {base:.8f}. Association in a fitted function, not "
                f"causation.")
    rising = all(b >= a for a, b in zip(got, got[1:], strict=False))
    falling = all(b <= a for a, b in zip(got, got[1:], strict=False))
    if rising:
        direction = "monotone increasing"
    elif falling:
        direction = "monotone decreasing"
    else:
        direction = "not monotone"
    return (f"{direction}: from {curve[0]['at']} to {curve[-1]['at']} the mean "
            f"prediction runs {got[0]:.8f} to {got[-1]:.8f}, a range of "
            f"{span:.8f} around a mean of {base:.8f}. Association in a fitted "
            f"function, not causation.")


def _plain(value: Any) -> Any:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return str(value)


def build(domain_id: str) -> Path:
    print(f"\n{domain_id}")
    loaded = inf.load(domain_id)
    manifest = json.loads(
        (inf.ARTIFACT_DIR / domain_id / "blend.json").read_text("utf-8"))
    frame, assignment = development_frame(domain_id, manifest)
    matrix, names = tr.matrix(frame, domain_id)
    print(f"  {len(frame):,} development rows, {len(names)} features")
    started = time.time()
    ranked = importance(loaded, names)
    curves = responses(loaded, matrix, names)
    body = {
        "domain_id": domain_id,
        "release_id": loaded.release_id,
        "model_version": loaded.model_version,
        "built_on": "the DEVELOPMENT window only",
        "development_periods": sorted(
            str(p) for p in list(assignment.train) + list(assignment.validate)),
        "held_back_and_not_read": sorted(str(p) for p in assignment.test),
        "rows": int(len(frame)),
        "rows_sampled_for_curves": min(int(len(frame)), SAMPLE_ROWS),
        "seed": SEED,
        "grid_points": GRID_POINTS,
        "importance": ranked,
        "responses": curves,
        "not_a_decomposition": ex.NOT_A_DECOMPOSITION,
        "origin": "SYNTHETIC_DEMO",
        "measured_on": ("a GENERATED book. Not bank output, not an accounting "
                        "figure, and not a bank-validated model."),
    }
    out = inf.ARTIFACT_DIR / domain_id / ex.DOCUMENT
    out.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"  {len(ranked)} ranked features, {len(curves)} response curves "
          f"in {time.time() - started:.1f}s")
    print(f"  wrote {out}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="all", choices=[*BOOKS, "all"])
    args = parser.parse_args()
    for domain_id in (BOOKS if args.domain == "all" else (args.domain,)):
        build(domain_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

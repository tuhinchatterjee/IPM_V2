"""Training, once, offline, with every number it produces written down.

Run by `scripts/whatif/train_emulator.py` inside the candidate virtual
environment. Nothing in a chat turn imports this module, and
`test_whatif_ml.py` walks the tree to keep that true.

The order is fixed and it is the order the acceptance document declares:

1. Assemble the matrix. `features.require_clean` raises if anything derived
   from the target got in -- an assertion, not a filter, because silently
   dropping a leaked column would let a wrong matrix produce a plausible
   model.
2. Split by distinct period. `split.leakage` has to come back empty.
3. Tune each component on **expanding-window folds inside development**, on
   WAPE, within the declared budget. Every trial is kept.
4. Refit each component on all development periods, and collect its
   **out-of-fold** predictions from step 3.
5. Fit blend weights on those out-of-fold predictions.
6. **Read the test periods once.** Compute every gate. Report what is
   measured.

Step 6 happens after steps 1-5 are finished and cannot change them. That is
the whole design: `ML_ACCEPTANCE_TARGETS.md` was committed before any of
this ran, and a gate that fails is reported failed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import ml
from backend.cockpit_v4.scenario.ml import blend as bl
from backend.cockpit_v4.scenario.ml import components as cp
from backend.cockpit_v4.scenario.ml import features as ft
from backend.cockpit_v4.scenario.ml import split as sp

#: The gates, from `ML_ACCEPTANCE_TARGETS.md`. Copied here so the code can
#: report pass or fail without a human reading the document, and asserted
#: against the document by a test so the two cannot drift.
GATES: dict[str, tuple[str, float]] = {
    "G1": ("out-of-time currency WAPE", 0.10),
    "G2": ("absolute aggregate bias", 0.02),
    "G3": ("worst absolute per-period bias", 0.05),
    "G4": ("worst material-group WAPE", 0.15),
}

#: A group needs this many test observations before its WAPE is judged.
#: Smaller groups are reported WITH their counts and excluded from the gate
#: rather than from the table.
MATERIAL_GROUP = 100

#: The groups each book's subgroup table reports.
GROUPS: dict[str, tuple[str, ...]] = {
    dom.CORPORATE: ("sector", "stage", "rating_current", "region",
                    "facility_class"),
    dom.RETAIL: ("product", "stage", "employer_sector", "region",
                 "score_band"),
}


@dataclass
class Result:
    """Everything one book's training produced, measured and unmeasured."""

    domain_id: str
    release_id: str
    model_version: str
    assignment: sp.Assignment
    blended: bl.Blend
    components: dict[str, cp.Fitted]
    metrics: dict[str, float] = field(default_factory=dict)
    gates: dict[str, dict[str, Any]] = field(default_factory=dict)
    subgroups: list[dict[str, Any]] = field(default_factory=list)
    reference: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    libraries: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(g["passed"] for g in self.gates.values())

    def failures(self) -> list[str]:
        return [f"{name}: {g['what']} measured {g['measured']:.4f} against a "
                f"{g['threshold']:.4f} threshold"
                for name, g in sorted(self.gates.items())
                if not g["passed"]]


def wape(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """`sum|pred - actual| / sum|actual|`, in currency.

    MAPE is unbounded on the near-zero ECLs a Stage 1 book is full of, so a
    single facility with a 0.0001 actual would decide it. WAPE cannot be
    hijacked that way, which is why the acceptance document names it.
    """
    bottom = sum(abs(a) for a in actual)
    if not bottom:
        return 0.0
    return sum(abs(p - a) for a, p in zip(actual, predicted,
                                          strict=True)) / bottom


def bias(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Signed, as a share of the actual total. Over- and under-prediction
    cancel, which is the point: a model can have a small WAPE and still be
    systematically high."""
    bottom = sum(actual)
    if not bottom:
        return 0.0
    return (sum(predicted) - sum(actual)) / bottom


def to_currency(rate: Sequence[float], denominator: Sequence[float]
                ) -> list[float]:
    """The predicted rate back to SAR mn. Every gate is measured here."""
    return [r * d for r, d in zip(rate, denominator, strict=True)]


def matrix(frame: Any, domain_id: str) -> tuple[Any, list[str]]:
    """The feature matrix, with categoricals typed and leakage refused."""
    domain_id = dom.parse(domain_id)
    wanted = [c for c in ft.names(domain_id) if c in frame.columns]
    ft.require_clean(wanted, where=f"{domain_id} X")
    out = frame[wanted].copy()
    for column in wanted:
        if column in ft.CATEGORICAL:
            out[column] = out[column].astype("category")
        else:
            out[column] = out[column].astype("float64")
    return out, wanted


def tune(component: str, frame: Any, target: Any, weights: Any,
         periods: Any, assignment: sp.Assignment
         ) -> tuple[dict[str, Any], list[cp.Trial], dict[int, float]]:
    """One family's best configuration, its whole trace, and its OOF
    predictions.

    Scored on WAPE in currency, which is what G1 is written in. Tuning on
    RMSE and reporting WAPE would let a configuration win on a measure
    nobody judges it by.
    """
    import numpy as np

    folds = sp.folds(assignment, count=ml.MAX_FOLDS)
    trials: list[cp.Trial] = []
    best: tuple[float, dict[str, Any]] | None = None
    best_oof: dict[int, float] = {}

    for config in cp.grid(component):
        errors: list[float] = []
        oof: dict[int, float] = {}
        rounds = 0
        for train_periods, valid_periods in folds:
            fit_rows = periods.isin(train_periods).to_numpy()
            check_rows = periods.isin(valid_periods).to_numpy()
            if not fit_rows.any() or not check_rows.any():
                continue
            model = cp.build(component, config,
                             seed=ml.SEEDS[component])
            x_fit, y_fit = frame[fit_rows], target[fit_rows]
            x_check, y_check = frame[check_rows], target[check_rows]
            if component in (ml.XGBOOST,):
                model.fit(x_fit, y_fit, eval_set=[(x_check, y_check)],
                          verbose=False)
                rounds = max(rounds, int(getattr(model, "best_iteration", 0)
                                         or 0))
            elif component == ml.LIGHTGBM:
                import lightgbm

                model.fit(x_fit, y_fit, eval_set=[(x_check, y_check)],
                          callbacks=[lightgbm.early_stopping(
                              ml.EARLY_STOPPING_PATIENCE, verbose=False)])
                rounds = max(rounds, int(getattr(model, "best_iteration_", 0)
                                         or 0))
            else:
                model.fit(x_fit, y_fit)
            predicted = np.asarray(model.predict(x_check), dtype=float)
            errors.append(cp.weighted_absolute_error(
                y_check.to_numpy(), predicted,
                weights[check_rows].to_numpy()))
            for index, value in zip(np.flatnonzero(check_rows), predicted,
                                    strict=True):
                oof[int(index)] = float(value)
        if not errors:  # pragma: no cover - a fold always has rows here
            continue
        mean = sum(errors) / len(errors)
        trials.append(cp.Trial(component=component, config=dict(config),
                               fold_errors=tuple(errors), mean_error=mean,
                               rounds=rounds))
        if best is None or mean < best[0]:
            best, best_oof = (mean, dict(config)), oof

    if best is None:  # pragma: no cover
        raise RuntimeError(f"{component} produced no usable configuration.")
    return best[1], trials, best_oof


def subgroup_table(frame: Any, actual: Sequence[float],
                   predicted: Sequence[float], domain_id: str
                   ) -> list[dict[str, Any]]:
    """WAPE per group, with the counts, including the groups too small to
    judge.

    G4 is measured only on groups with at least `MATERIAL_GROUP`
    observations. The smaller ones stay in the table with their counts, so a
    reader sees them and sees why they are not being gated -- excluding them
    from the table as well would hide where the model is untested.
    """
    import numpy as np

    out: list[dict[str, Any]] = []
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    for dimension in GROUPS[dom.parse(domain_id)]:
        if dimension not in frame.columns:
            continue
        for value in sorted(frame[dimension].astype(str).unique()):
            mask = (frame[dimension].astype(str) == value).to_numpy()
            count = int(mask.sum())
            if not count:
                continue
            out.append({
                "group_dimension": dimension,
                "group_value": str(value),
                "observations": count,
                "wape": round(wape(actual[mask], predicted[mask]), 6),
                "bias": round(bias(actual[mask], predicted[mask]), 6),
                "material": count >= MATERIAL_GROUP,
            })
    return out


def judge(result: Result) -> None:
    """Fill `result.gates` from `result.metrics`. Pass or fail, as measured.

    No tolerance beyond the declared threshold, and no rounding in the
    model's favour: a gate that fails is reported failed, in the card, in
    the metric rows and to the reader.
    """
    measured = {
        "G1": result.metrics["test_wape"],
        "G2": abs(result.metrics["test_bias"]),
        "G3": result.metrics["worst_period_bias"],
        "G4": result.metrics["worst_material_group_wape"],
    }
    for name, (what, threshold) in GATES.items():
        value = measured[name]
        result.gates[name] = {
            "what": what, "threshold": threshold, "measured": value,
            "passed": bool(value <= threshold)}


def metric_rows(result: Result, *, stamp: dict[str, Any],
                period_column: str, period: str) -> list[dict[str, Any]]:
    """`whatif_*_model_metric`: the model card as published data.

    Every gate, every component weight, every subgroup and the declared
    reference model, so a reader asking how the model was validated gets
    rows rather than a document, and a FAILED gate carries its measured
    value rather than a blank.
    """
    rows: list[dict[str, Any]] = []

    def add(component: str, split_name: str, dimension: str, value_name: str,
            metric: str, number: float, observations: int, validated: str,
            note: str) -> None:
        rows.append({
            **stamp, "model_id": result.model_version,
            "model_version": result.model_version, period_column: period,
            "component": component, "split": split_name,
            "group_dimension": dimension, "group_value": value_name,
            "metric_name": metric, "metric_value": round(float(number), 8),
            "observations": int(observations), "validated": validated,
            "note": note})

    for name, gate in sorted(result.gates.items()):
        add("blend", sp.TEST, "overall", "all", f"{name}_{gate['what']}",
            gate["measured"], result.counts.get("test_rows", 0),
            "PASSED" if gate["passed"] else "FAILED",
            f"{gate['what']} measured {gate['measured']:.4f} against the "
            f"predeclared {gate['threshold']:.4f} threshold in "
            f"ML_ACCEPTANCE_TARGETS.md. Fitted on generated data; this is "
            f"not bank-engine validation.")

    for component, weight in result.blended.by_name.items():
        add(component, "out_of_fold", "overall", "all", "blend_weight",
            weight, result.blended.observations,
            "MATERIAL" if weight >= ml.MATERIAL_WEIGHT else "IMMATERIAL",
            result.blended.headline)

    for component, error in sorted(
            result.blended.single_component_errors.items()):
        add(component, "out_of_fold", "overall", "all",
            "single_component_squared_error", error,
            result.blended.observations, "REPORTED",
            "This component alone, on the same out-of-fold rows the weights "
            "were fitted on.")

    for metric, number in sorted(result.reference.items()):
        add(ml.NAIVE_PRODUCT, sp.TEST, "overall", "all", metric, number,
            result.counts.get("test_rows", 0), "REFERENCE",
            "The declared reference model: ead x pd x lgd, on the same test "
            "rows. A blend that does not beat this is reported as not "
            "beating it.")

    for group in result.subgroups:
        add("blend", sp.TEST, group["group_dimension"], group["group_value"],
            "wape", group["wape"], group["observations"],
            "GATED" if group["material"] else "TOO_SMALL_TO_GATE",
            f"{group['observations']} test observations; the gate needs "
            f"{MATERIAL_GROUP}.")

    for name, count in sorted(result.counts.items()):
        add("blend", "counts", "overall", name, name, count, count,
            "REPORTED", "Row and period counts behind every figure above.")

    return rows


__all__ = ["GATES", "GROUPS", "MATERIAL_GROUP", "Result", "bias", "judge",
           "matrix", "metric_rows", "subgroup_table", "to_currency", "tune",
           "wape"]

"""Method 2 at run time: anchored, never multiplied, never applied twice.

Section 11.4 gives the arithmetic and it is three lines:

    ML_change = P1 - P0
    M1        = M0 + ML_change
    ECL1      = M1 + O0

`P0` and `P1` are the model's raw predictions on the baseline and the
shocked feature vectors. `M0` is the **observed** modelled ECL and `O0` the
observed overlay, both read from the book rather than predicted. So the
answer starts from what the reader can see on their screen and moves it by
what the model says the shock does.

## What this shape prevents, and why each matters

**The model's level error never reaches the answer.** A model that is 3%
high everywhere would, used directly, report a 3% change on a zero shock.
Anchoring cancels it: `P1 - P0` is a difference between two calls on the
same model.

**A zero shock is exactly zero.** Not approximately, not within tolerance.
`P1` and `P0` are the same call on the same vector, so their difference is
the float `0.0` and `ECL1` is the observed ECL unchanged. `zero_shock_is_zero`
asserts it on the real fitted function.

**The ML estimate is never multiplied by the Delta factor.** Method 1
computes a stressed ECL from proportional arithmetic; Method 2 computes one
from a model. They are two ANSWERS to one question and the run shows them
side by side. Multiplying them would apply the shock twice and produce a
number no method computed. `refuse_composition` exists so that reaching for
it raises instead.

**A macro move is applied once.** If a scenario moves PD through a
sensitivity and the model also sees the macro factor, the feature vector
carries the moved PD **or** the moved factor, never both for the same
underlying move. `applied_once` records which, and the preview shows it.

## When there is no model

`MODEL_NOT_READY`, with the reason. The accepted environment has none of the
component libraries and never will; an unpublished or stale artifact is the
same answer. Method 2 then reports its status and its reason, and the run
shows the other methods. A zero is never substituted for an unavailable
method, because a zero reads as "no effect".
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.cockpit_v4.generate.totals import exact_total
from backend.cockpit_v4.scenario.errors import (
    METHOD_COVERAGE_GAP,
    MODEL_NOT_READY,
    raise_for,
)

#: Where a trained book's artifacts live, relative to the repository root.
ARTIFACT_DIR = Path("artifacts") / "whatif"

#: How the moved quantity reached the feature vector. Recorded per run so a
#: reader can see that a macro move was applied once and can see where.
VIA_PARAMETER = "risk_parameter"
VIA_FACTOR = "macro_factor"


@dataclass(frozen=True)
class Loaded:
    """A frozen blend, ready to predict. Or a reason there isn't one."""

    domain_id: str
    model_version: str
    release_id: str
    features: tuple[str, ...]
    categorical: tuple[str, ...]
    weights: dict[str, float]
    headline: str
    models: dict[str, Any] = field(default_factory=dict)
    gates: dict[str, Any] = field(default_factory=dict)

    @property
    def passed_every_gate(self) -> bool:
        return all(bool(g.get("passed")) for g in self.gates.values())

    def failures(self) -> list[str]:
        return [f"{name}: {g['what']} measured {g['measured']:.4f} against "
                f"{g['threshold']:.4f}"
                for name, g in sorted(self.gates.items())
                if not g.get("passed")]

    def raw(self, frame: Any) -> list[float]:
        """The blend's raw prediction on a feature frame, in rate space."""
        import numpy as np

        ordered = frame[list(self.features)]
        total: Any = None
        for component, weight in self.weights.items():
            if weight <= 0.0:
                continue
            piece = np.asarray(self.models[component].predict(ordered),
                               dtype=float) * weight
            total = piece if total is None else total + piece
        if total is None:  # pragma: no cover - a blend has some weight
            raise_for(MODEL_NOT_READY,
                      "every component carries zero weight, so this blend "
                      "predicts nothing.", field_path="method.ml")
        return [float(v) for v in total]


@dataclass(frozen=True)
class Anchored:
    """One anchored ML estimate, with every intermediate number shown.

    Section 11.4 asks for the observed baseline, the raw `P0`, the raw `P1`,
    their difference, the overlay and the anchored result to be displayed --
    all six, because a reader shown only the last one cannot tell an
    anchored estimate from a raw one.
    """

    observed_modelled: float
    observed_overlay: float
    raw_baseline: float
    raw_scenario: float
    ml_change: float
    anchored_modelled: float
    anchored_total: float
    applied_once: str
    rows: int
    warnings: tuple[str, ...] = ()

    @property
    def observed_total(self) -> float:
        return self.observed_modelled + self.observed_overlay

    @property
    def change(self) -> float:
        return self.anchored_total - self.observed_total

    def describe(self) -> str:
        return (
            f"Observed modelled ECL {self.observed_modelled:,.2f} + overlay "
            f"{self.observed_overlay:,.2f} = {self.observed_total:,.2f}. "
            f"The model predicts {self.raw_baseline:,.2f} for the baseline "
            f"and {self.raw_scenario:,.2f} for the scenario, a difference of "
            f"{self.ml_change:+,.2f}. Anchored: "
            f"{self.observed_modelled:,.2f} {self.ml_change:+,.2f} = "
            f"{self.anchored_modelled:,.2f} modelled, plus the unchanged "
            f"overlay = {self.anchored_total:,.2f}.")

    def as_facts(self) -> dict[str, Any]:
        return {
            "observed_modelled_ecl": round(self.observed_modelled, 6),
            "observed_overlay": round(self.observed_overlay, 6),
            "observed_total_ecl": round(self.observed_total, 6),
            "raw_model_baseline": round(self.raw_baseline, 6),
            "raw_model_scenario": round(self.raw_scenario, 6),
            "raw_model_difference": round(self.ml_change, 6),
            "anchored_modelled_ecl": round(self.anchored_modelled, 6),
            "anchored_total_ecl": round(self.anchored_total, 6),
            "change": round(self.change, 6),
            "macro_move_applied_via": self.applied_once,
            "rows": self.rows,
            "anchoring": ("ML_change = P1 - P0; M1 = M0 + ML_change; "
                          "ECL1 = M1 + O0. The model's level is never used, "
                          "only its difference."),
            "warnings": list(self.warnings),
        }


def load(domain_id: str, *, root: Path | None = None,
         release_id: str = "") -> Loaded:
    """Load one book's frozen blend, or refuse with the reason.

    Four ways this refuses, each with its own sentence: the artifacts are
    absent, the component libraries are absent, the artifact was trained
    against a different release, or a component file is missing. None of
    them returns a number.
    """
    base = (root or ARTIFACT_DIR) / domain_id
    manifest = base / "blend.json"
    if not manifest.exists():
        raise_for(MODEL_NOT_READY,
                  f"no emulator is published for the {domain_id} book. "
                  f"Method 2 is unavailable here; it is not a change of "
                  f"zero. Train one with "
                  f"scripts/whatif/train_emulator.py, or use Delta or an "
                  f"explicit assumption instead.",
                  field_path="method.ml", domain_id=domain_id)
    body = json.loads(manifest.read_text(encoding="utf-8"))

    if release_id and str(body.get("release_id")) != release_id:
        raise_for(MODEL_NOT_READY,
                  f"this emulator was trained against "
                  f"{body.get('release_id')!r} and the book in use is "
                  f"{release_id!r}. A model fitted on a different book "
                  f"describes a different book; retrain before using it.",
                  field_path="method.ml", trained_against=body.get(
                      "release_id"), in_use=release_id)

    import pickle

    models: dict[str, Any] = {}
    for component, weight in body["weights"].items():
        if weight <= 0.0:
            continue
        path = base / f"{component}.pkl"
        if not path.exists():
            raise_for(MODEL_NOT_READY,
                      f"the blend gives {component} a weight of "
                      f"{weight:.3f} and its artifact is missing. A blend "
                      f"short of a material component is not this blend.",
                      field_path="method.ml")
        try:
            models[component] = pickle.loads(path.read_bytes())
        except (ImportError, ModuleNotFoundError) as exc:
            raise_for(MODEL_NOT_READY,
                      f"{component} cannot be loaded here: {exc}. The "
                      f"emulators run in the candidate environment built "
                      f"from requirements-whatif.txt; the accepted "
                      f"environment does not carry these libraries and is "
                      f"not meant to.",
                      field_path="method.ml", component=component)
    return Loaded(
        domain_id=str(body["domain_id"]),
        model_version=str(body["model_version"]),
        release_id=str(body["release_id"]),
        features=tuple(body["features"]),
        categorical=tuple(body.get("categorical", ())),
        weights=dict(body["weights"]),
        headline=str(body.get("headline", "")),
        models=models, gates=dict(body.get("gates", {})))


def anchor(loaded: Loaded, *, baseline_frame: Any, scenario_frame: Any,
           denominator: Sequence[float], observed_modelled: float,
           observed_overlay: float, applied_once: str = VIA_PARAMETER,
           warnings: Sequence[str] = ()) -> Anchored:
    """Section 11.4's three lines, over a whole cohort.

    `denominator` converts the predicted RATE back to currency, one row at a
    time, because the model predicts a rate and a portfolio total is a sum
    of currency rather than an average of rates.
    """
    if applied_once not in (VIA_PARAMETER, VIA_FACTOR):
        raise ValueError(
            f"{applied_once!r} does not say how the move reached the "
            f"features. It is {VIA_PARAMETER} or {VIA_FACTOR}, and saying "
            f"which is what shows the move was applied once.")
    if len(baseline_frame) != len(scenario_frame):
        raise_for(METHOD_COVERAGE_GAP,
                  f"the baseline has {len(baseline_frame)} rows and the "
                  f"scenario has {len(scenario_frame)}. A difference between "
                  f"two different populations is not a change.",
                  field_path="method.ml")

    base_rate = loaded.raw(baseline_frame)
    move_rate = loaded.raw(scenario_frame)
    raw_baseline = exact_total(r * d for r, d in
                               zip(base_rate, denominator, strict=True))
    raw_scenario = exact_total(r * d for r, d in
                               zip(move_rate, denominator, strict=True))
    change = raw_scenario - raw_baseline
    modelled = observed_modelled + change
    return Anchored(
        observed_modelled=observed_modelled,
        observed_overlay=observed_overlay,
        raw_baseline=raw_baseline, raw_scenario=raw_scenario,
        ml_change=change, anchored_modelled=modelled,
        anchored_total=modelled + observed_overlay,
        applied_once=applied_once, rows=len(baseline_frame),
        warnings=tuple(warnings))


def zero_shock_is_zero(loaded: Loaded, frame: Any,
                       denominator: Sequence[float]) -> bool:
    """M-oracle. An unchanged scenario moves the answer by exactly zero."""
    got = anchor(loaded, baseline_frame=frame, scenario_frame=frame,
                 denominator=denominator, observed_modelled=100.0,
                 observed_overlay=5.0)
    return got.ml_change == 0.0 and got.anchored_total == 105.0


def refuse_composition(*_args: Any, **_kwargs: Any) -> None:
    """The banned combination, as a function that only ever raises.

    Method 1 and Method 2 are two ANSWERS to one question, not two factors
    of one answer. Multiplying the ML estimate by the Delta factor applies
    the shock twice and produces a number neither method computed; adding
    a macro sensitivity's effect on top of a model that already sees the
    macro factor does the same thing more quietly.

    Named so the ban has something a test can call and a future caller
    reaching for it finds this instead of writing it.
    """
    raise_for(METHOD_COVERAGE_GAP,
              "the ML estimate is not multiplied by the Delta factor and a "
              "macro move is not applied twice. Delta and the emulator are "
              "two answers to one question: the run shows them side by side, "
              "with their difference explained, and never composed into a "
              "third number that neither method computed.",
              field_path="method.composition")


def support_warnings(loaded: Loaded, scenario_frame: Any,
                     ranges: Mapping[str, tuple[float, float]]) -> list[str]:
    """Features the scenario pushed outside the training window's range.

    A warning rather than a refusal: an extrapolation is sometimes exactly
    what a stress test is for. What is not acceptable is an extrapolation
    the reader cannot see, so each one is named with the range it left.
    """
    out: list[str] = []
    for column, (low, high) in sorted(ranges.items()):
        if column not in getattr(scenario_frame, "columns", ()):
            continue
        values = scenario_frame[column]
        try:
            smallest, largest = float(values.min()), float(values.max())
        except (TypeError, ValueError):  # a categorical column
            continue
        if smallest < low or largest > high:
            out.append(
                f"{column} runs {smallest:g} to {largest:g} in this "
                f"scenario, outside the {low:g} to {high:g} range the model "
                f"was fitted over. The prediction there is an "
                f"extrapolation.")
    return out


__all__ = ["ARTIFACT_DIR", "Anchored", "Loaded", "VIA_FACTOR",
           "VIA_PARAMETER", "anchor", "load", "refuse_composition",
           "support_warnings", "zero_shock_is_zero"]

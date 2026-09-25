"""Weights that were fitted, on predictions the model had not seen.

Section 11.3 asks for a blend and then, in the same breath, for honesty about
what came out of fitting one:

> *"Use genuinely learned blend weights. Do not silently deliver a
> single-model result or a hardcoded mixture as a validated blend."*

Both halves are here. The weights are the exact solution of

    minimise  || P w - y ||^2       subject to   w >= 0,  sum(w) = 1

over the **out-of-fold** predictions `P` -- predictions each component made
for periods it had not trained on, so a component that memorised its training
window earns nothing for it. And `Blend.headline` says what actually
happened: a weight vector of `1 / 0 / 0` is described as a single-model
result, by name, rather than as an ensemble that happened to concentrate.

## Why the optimiser is written out rather than imported

Three components make this small enough to solve **exactly**, and an exact
answer is worth more here than a general one.

The constrained problem has its solution on some face of the simplex: some
components carry weight and the rest are zero. There are seven non-empty
subsets of three components, and on each one the problem is an
equality-constrained least squares with a closed form. Solve all seven, keep
the feasible ones, take the lowest loss. That is the global optimum, with no
tolerance, no iteration count, no starting point and no library version in
the answer -- which section 14.2 asks for and which a projected-gradient
solver could not promise.

It also means the weights do not depend on SciPy's minor version, so
re-running the training a year from now reproduces the published card.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

from backend.cockpit_v4.generate.totals import exact_total
from backend.cockpit_v4.scenario import ml

#: Weights are rounded to this many places before publication, so the stored
#: number and the number in the card are the same number.
PLACES = 6


@dataclass(frozen=True)
class Blend:
    """Fitted weights, and what they honestly amount to."""

    components: tuple[str, ...]
    weights: tuple[float, ...]
    out_of_fold_error: float
    single_component_errors: dict[str, float]
    observations: int

    @property
    def by_name(self) -> dict[str, float]:
        return dict(zip(self.components, self.weights, strict=True))

    @property
    def material(self) -> tuple[str, ...]:
        """Components carrying at least `MATERIAL_WEIGHT` (B3)."""
        return tuple(c for c, w in zip(self.components, self.weights,
                                       strict=True)
                     if w >= ml.MATERIAL_WEIGHT)

    @property
    def immaterial(self) -> tuple[str, ...]:
        return tuple(c for c in self.components if c not in self.material)

    @property
    def is_single_model(self) -> bool:
        """B4. Did the fit put everything on one component?"""
        return len(self.material) == 1

    @property
    def headline(self) -> str:
        """What this is, in the words the model card has to use.

        The single-model case is the one that matters. A fit that lands on
        one component has produced a single model, and calling it a blend
        because three were offered would be describing the intention rather
        than the result.
        """
        named = ", ".join(f"{c} {w:.3f}" for c, w in self.by_name.items())
        if self.is_single_model:
            only = self.material[0]
            return (
                f"SINGLE-MODEL RESULT. The weight fit put "
                f"{self.by_name[only]:.3f} on {only} and left "
                f"{', '.join(self.immaterial)} below the "
                f"{ml.MATERIAL_WEIGHT:.2f} materiality floor. This is a "
                f"{only} model, not a blend, and is reported as one. "
                f"Weights: {named}.")
        return (
            f"BLEND of {len(self.material)} material components, fitted on "
            f"out-of-fold predictions. Weights: {named}."
            + (f" Below the {ml.MATERIAL_WEIGHT:.2f} materiality floor and "
               f"reported as immaterial: {', '.join(self.immaterial)}."
               if self.immaterial else ""))

    def predict(self, component_predictions: dict[str, Sequence[float]]
                ) -> list[float]:
        """The blend's prediction, from each component's."""
        first = component_predictions[self.components[0]]
        return [exact_total(self.by_name[c] * component_predictions[c][i]
                            for c in self.components)
                for i in range(len(first))]


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting. None if singular."""
    n = len(rhs)
    work = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda r: abs(work[r][column]))
        if abs(work[pivot][column]) < 1e-12:
            return None
        work[column], work[pivot] = work[pivot], work[column]
        for row in range(column + 1, n):
            factor = work[row][column] / work[column][column]
            for k in range(column, n + 1):
                work[row][k] -= factor * work[column][k]
    out = [0.0] * n
    for row in range(n - 1, -1, -1):
        total = work[row][n] - exact_total(
            work[row][k] * out[k] for k in range(row + 1, n))
        out[row] = total / work[row][row]
    return out


def _error(predictions: Sequence[Sequence[float]], actual: Sequence[float],
           weights: Sequence[float]) -> float:
    """Sum of squared residuals for one weight vector."""
    return exact_total(
        (exact_total(w * p[i] for w, p in zip(weights, predictions,
                                              strict=True)) - actual[i]) ** 2
        for i in range(len(actual)))


def _on_face(predictions: Sequence[Sequence[float]], actual: Sequence[float],
             face: Sequence[int]) -> list[float] | None:
    """Equality-constrained least squares on one face of the simplex.

    Minimise `|| P w - y ||^2` subject to `sum(w) = 1` over the components in
    `face`, the rest held at zero. The KKT system is

        [ 2 P'P   1 ] [ w ]   [ 2 P'y ]
        [   1'    0 ] [ l ] = [   1   ]

    which for at most three components is a four-by-four solve.
    """
    k = len(face)
    chosen = [predictions[i] for i in face]
    gram = [[2.0 * exact_total(a[i] * b[i] for i in range(len(actual)))
             for b in chosen] for a in chosen]
    moment = [2.0 * exact_total(a[i] * actual[i] for i in range(len(actual)))
              for a in chosen]
    matrix = [gram[r] + [1.0] for r in range(k)] + [[1.0] * k + [0.0]]
    answer = _solve(matrix, moment + [1.0])
    if answer is None:
        return None
    return answer[:k]


def fit(component_predictions: dict[str, Sequence[float]],
        actual: Sequence[float]) -> Blend:
    """The exact non-negative, sum-to-one weights over the simplex.

    Every face is solved and the feasible one with the lowest loss wins. A
    face whose closed form puts a negative weight on a component is
    infeasible and is discarded rather than clipped -- clipping would move
    the answer off the optimum without saying so.
    """
    components = tuple(c for c in ml.COMPONENTS
                       if c in component_predictions)
    if not components:
        raise ValueError("a blend of no components is not a blend.")
    predictions = [list(component_predictions[c]) for c in components]
    target = list(actual)
    lengths = {len(p) for p in predictions} | {len(target)}
    if len(lengths) > 1:
        raise ValueError(
            f"the components produced {sorted(lengths)} predictions between "
            f"them. Out-of-fold predictions have to cover the same rows or "
            f"the weights are fitted on different populations.")
    if not target:
        raise ValueError("no out-of-fold predictions to fit weights on.")

    best: tuple[float, list[float]] | None = None
    indices = range(len(components))
    for size in range(1, len(components) + 1):
        for face in itertools.combinations(indices, size):
            solution = _on_face(predictions, target, face)
            if solution is None or any(w < -1e-9 for w in solution):
                continue
            weights = [0.0] * len(components)
            for slot, index in enumerate(face):
                weights[index] = max(0.0, solution[slot])
            total = exact_total(weights)
            if total <= 0:
                continue
            weights = [w / total for w in weights]
            loss = _error(predictions, target, weights)
            if best is None or loss < best[0]:
                best = (loss, weights)

    if best is None:  # pragma: no cover - a face is always feasible
        raise ValueError("no feasible weight vector on the simplex.")
    loss, weights = best
    rounded = [round(w, PLACES) for w in weights]
    # Rounding must not break the constraint the card claims holds.
    drift = 1.0 - exact_total(rounded)
    heaviest = max(range(len(rounded)), key=lambda i: rounded[i])
    rounded[heaviest] = round(rounded[heaviest] + drift, PLACES)

    alone: dict[str, float] = {}
    for index, name in enumerate(components):
        solo = [0.0] * len(components)
        solo[index] = 1.0
        alone[name] = _error(predictions, target, solo) / len(target)

    return Blend(components=components, weights=tuple(rounded),
                 out_of_fold_error=loss / len(target),
                 single_component_errors=alone, observations=len(target))


def beats_every_component(blended: Blend) -> bool:
    """Did blending actually help, on the data the weights were fitted on?

    Reported rather than required. A blend that does not beat its best
    component is a fact about this data, and hiding it would leave the card
    claiming an ensemble earned something it did not.
    """
    return all(blended.out_of_fold_error <= error + 1e-12
               for error in blended.single_component_errors.values())


__all__ = ["Blend", "PLACES", "beats_every_component", "fit"]

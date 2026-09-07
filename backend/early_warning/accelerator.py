"""The Version 2 accelerator: five weighted dimensions plus a separate decay
factor, exactly as Tab 3 Section B/C of the workbook defines it.

Five dimensions, blended by weight so no single one can dominate:

    Magnitude       weight 0.30
    Velocity        weight 0.20
    Persistence     weight 0.20
    Repetition      weight 0.10
    Corroboration   weight 0.20

Recency/decay is NOT one of the five blended dimensions. It is a separate
multiplicative factor applied to the whole accelerator, banded by the age of
the signal in days (one universal band table — see the module docstring in
`combination.py`'s sibling note for why this is simpler than an earlier
design conversation described: the workbook uses one ~45-day-half-life band
table for every signal, not a per-signal-class half-life/persistence-hold
mechanism).

Formulas (Tab 3 Section C, verbatim):

    accelerator_multiplier = recency_factor * (1 + SUM(weight_d * (mult_d - 1)))
    signal_score            = MIN(100, trigger_score * accelerator_multiplier)

Verified against two independent Tab 3 Section C worked-example rows:
  - "Operating / deposit balance decline": bands (3,3,3,2,3), recency band 1
    -> multiplier 1.15, trigger 40 -> signal score 46.
  - "Reduction in account credits": bands (2,2,2,1,3), recency band 2
    -> multiplier 0.9315, trigger 40 -> signal score 37.26.
`test_accelerator.py` reproduces both exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# The five blended dimensions. Tab 3 Section B.
# ---------------------------------------------------------------------------

DIMENSION_WEIGHTS: dict[str, float] = {
    "magnitude": 0.30,
    "velocity": 0.20,
    "persistence": 0.20,
    "repetition": 0.10,
    "corroboration": 0.20,
}
assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9

#: multiplier[dimension][band] for bands 1-5, Tab 3 Section B "Multiplier table".
DIMENSION_MULTIPLIERS: dict[str, dict[int, float]] = {
    "magnitude":     {1: 0.85, 2: 1.00, 3: 1.15, 4: 1.30, 5: 1.45},
    "velocity":      {1: 0.90, 2: 1.00, 3: 1.15, 4: 1.30, 5: 1.45},
    "persistence":   {1: 0.85, 2: 1.00, 3: 1.15, 4: 1.30, 5: 1.45},
    "repetition":    {1: 0.95, 2: 1.05, 3: 1.15, 4: 1.25, 5: 1.35},
    "corroboration": {1: 0.90, 2: 1.05, 3: 1.20, 4: 1.35, 5: 1.50},
}

#: What each band means, for the UI / methodology explainer. Tab 3 Section B.
DIMENSION_BAND_DESCRIPTIONS: dict[str, dict[int, str]] = {
    "magnitude": {1: "Under 1 sigma", 2: "1 to 2 sigma", 3: "2 to 3 sigma",
                  4: "3 to 4 sigma", 5: "Above 4 sigma"},
    "velocity": {1: "Under 5% per month", 2: "5% to 15%", 3: "15% to 30%",
                 4: "30% to 50%", 5: "Above 50%"},
    "persistence": {1: "1 observation", 2: "2 to 3", 3: "4 to 8",
                    4: "9 to 16", 5: "Over 16"},
    "repetition": {1: "1 time", 2: "2 times", 3: "3 times",
                   4: "4 to 5 times", 5: "6 or more"},
    "corroboration": {1: "1 signal", 2: "2 signals", 3: "3 signals",
                      4: "4 to 5 signals", 5: "6 or more"},
}

# ---------------------------------------------------------------------------
# Recency / decay: one universal band table (Conflict B in the plan — the
# workbook does NOT specify per-signal-class half-lives, persistence-hold
# from cure date, or a hard staleness cutoff; it specifies exactly this).
# ---------------------------------------------------------------------------

#: (max_age_days_inclusive, factor). The last band has no upper bound.
RECENCY_BANDS: tuple[tuple[int | None, float, str], ...] = (
    (7, 1.00, "0 to 7 days"),
    (30, 0.90, "8 to 30 days"),
    (60, 0.75, "31 to 60 days"),
    (120, 0.55, "61 to 120 days"),
    (None, 0.35, "Over 120 days"),
)


def recency_factor(age_days: int) -> float:
    """Tab 3 Section B "Recency / decay" row. Approximate half-life ~45 days."""
    for max_age, factor, _ in RECENCY_BANDS:
        if max_age is None or age_days <= max_age:
            return factor
    raise AssertionError("unreachable")


def recency_band_index(age_days: int) -> int:
    for i, (max_age, _, _) in enumerate(RECENCY_BANDS, start=1):
        if max_age is None or age_days <= max_age:
            return i
    raise AssertionError("unreachable")


@dataclass(frozen=True)
class AcceleratorInput:
    magnitude_band: int
    velocity_band: int
    persistence_band: int
    repetition_band: int
    corroboration_band: int
    age_days: int


@dataclass(frozen=True)
class AcceleratorResult:
    dimension_multipliers: dict[str, float]
    recency_factor: float
    accelerator_multiplier: float

    def to_dict(self) -> dict:
        return {
            "dimension_multipliers": self.dimension_multipliers,
            "recency_factor": self.recency_factor,
            "accelerator_multiplier": round(self.accelerator_multiplier, 6),
        }


def compute_accelerator(inp: AcceleratorInput) -> AcceleratorResult:
    """Tab 3 Section C: accelerator_multiplier = recency * (1 + SUM(w*(m-1)))."""
    bands = {
        "magnitude": inp.magnitude_band,
        "velocity": inp.velocity_band,
        "persistence": inp.persistence_band,
        "repetition": inp.repetition_band,
        "corroboration": inp.corroboration_band,
    }
    multipliers = {
        dim: DIMENSION_MULTIPLIERS[dim][band] for dim, band in bands.items()
    }
    blended = 1.0 + sum(
        DIMENSION_WEIGHTS[dim] * (multipliers[dim] - 1.0) for dim in multipliers
    )
    recency = recency_factor(inp.age_days)
    return AcceleratorResult(
        dimension_multipliers=multipliers,
        recency_factor=recency,
        accelerator_multiplier=recency * blended,
    )


def signal_score(trigger_score: int, accelerator_multiplier: float) -> float:
    """Tab 3 Section C: signal_score = MIN(100, trigger_score * accelerator)."""
    return min(100.0, trigger_score * accelerator_multiplier)

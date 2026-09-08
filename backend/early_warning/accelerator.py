"""The Version 2 accelerator: five weighted dimensions plus a separate,
class-specific decay factor, exactly as Tab 04 Sections B/C of the
corrected workbook define it.

Five dimensions, blended by weight so no single one can dominate (Tab 04
Section B — unchanged from the earlier, incorrect workbook draft this
module was first built against; these weights and multiplier tables were
already correct):

    Magnitude       weight 0.30
    Velocity        weight 0.20
    Persistence     weight 0.20
    Repetition      weight 0.10
    Corroboration   weight 0.20

Decay is NOT one of the five blended dimensions — it is a separate
multiplicative factor applied to the whole accelerator (Tab 04 Section C,
first line). What WAS wrong in the earlier draft, and is rebuilt here: decay
is not one universal ~45-day-half-life band table. The corrected model
(Tab 04 Section C) uses:

  - a class-specific half-life per sub-category group (transactional and
    behavioural signals fade in 21 days; official/legal events in 180);
  - a persistence hold — the decay clock does not start while the
    underlying condition remains uncured; age is measured from the CURE
    date, not first observation;
  - reset on recurrence — a new occurrence of the same trigger resets age
    to zero (and is expected to raise the Repetition dimension, handled by
    the caller building `AcceleratorInput.repetition_band`, not by this
    module);
  - a hard staleness cut-off — a signal leaves the score entirely once its
    decay factor falls below 0.15, or its age exceeds 400 days.

Formulas (Tab 04 Section C, verbatim):

    accelerator_multiplier = decay_factor * (1 + SUM(weight_d * (mult_d - 1)))
    signal_score            = MIN(100, trigger_score * accelerator_multiplier)

Verified against two independent Tab 04 Section C accelerator worked-example
rows (dimension math, unchanged from the earlier draft):
  - bands (3,3,3,2,3), decay 1.00 -> multiplier 1.15, trigger 40 -> score 46.
  - bands (2,2,2,1,3), decay 0.90 -> multiplier 0.9315, trigger 40 -> score 37.26.
And against all 8 of Tab 04 Section C's worked decay examples (half-life,
persistence hold, and the hard cut-off) — see `test_accelerator.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# The five blended dimensions. Tab 04 Section B.
# ---------------------------------------------------------------------------

DIMENSION_WEIGHTS: dict[str, float] = {
    "magnitude": 0.30,
    "velocity": 0.20,
    "persistence": 0.20,
    "repetition": 0.10,
    "corroboration": 0.20,
}
assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9

#: multiplier[dimension][band] for bands 1-5, Tab 04 Section B "Multiplier table".
DIMENSION_MULTIPLIERS: dict[str, dict[int, float]] = {
    "magnitude":     {1: 0.85, 2: 1.00, 3: 1.15, 4: 1.30, 5: 1.45},
    "velocity":      {1: 0.90, 2: 1.00, 3: 1.15, 4: 1.30, 5: 1.45},
    "persistence":   {1: 0.85, 2: 1.00, 3: 1.15, 4: 1.30, 5: 1.45},
    "repetition":    {1: 0.95, 2: 1.05, 3: 1.15, 4: 1.25, 5: 1.35},
    "corroboration": {1: 0.90, 2: 1.05, 3: 1.20, 4: 1.35, 5: 1.50},
}

#: What each band means, for the UI / methodology explainer. Tab 04 Section B.
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
# Decay, rebuilt (Tab 04 Section C): class-specific half-life, persistence
# hold, recurrence reset, hard staleness cut-off.
# ---------------------------------------------------------------------------

HARD_CUTOFF_DECAY_FACTOR = 0.15
HARD_CUTOFF_AGE_DAYS = 400


@dataclass(frozen=True)
class DecayClass:
    name: str
    half_life_days: float | None  # None for the non-decaying class
    floor: float
    sub_categories: tuple[str, ...]


#: Tab 04 Section C "The decay model, rebuilt" table, verbatim.
DECAY_CLASSES: tuple[DecayClass, ...] = (
    DecayClass("transactional_and_behavioural", 21, 0.0, ("L1.1", "L1.2", "L1.4")),
    DecayClass("payment_performance", 45, 0.0, ("L1.3",)),
    DecayClass("credit_fundamental_events", 120, 0.1, ("L2.T1", "L2.T2")),
    DecayClass("official_and_legal_events", 180, 0.25, ("L3.1", "L3.2")),
    DecayClass("ratings_and_market_signals", 60, 0.0, ("L3.3",)),
    DecayClass("news_and_operating_events", 90, 0.0, ("L3.4",)),
    DecayClass("macro_and_sector_shocks", 120, 0.1, ("L3.5",)),
    #: "Inherits the counterparty signal's class but is floored at 90 days,
    #: because contagion arrives with a lag" — modelled as its own class
    #: with a 90-day half-life and no shorter effective half-life allowed.
    DecayClass("network_propagated", 90, 0.0, ("L4.1", "L4.2", "L4.3")),
)

SUBCATEGORY_DECAY_CLASS: dict[str, DecayClass] = {
    sub: dc for dc in DECAY_CLASSES for sub in dc.sub_categories
}

#: "These do not fade with time. They are resolved by an event, not by the
#: calendar, and are handled as overrides." Decay factor fixed at 1.0.
NON_DECAYING_DECAY_CLASS = DecayClass("non_decaying", None, 1.0, ())


@dataclass(frozen=True)
class DecayResult:
    decay_factor: float
    in_scope: bool
    decay_class: str


def compute_decay(sub_category_code: str, *, cured: bool, days_since_cure: int,
                   age_days: int, non_decaying: bool = False) -> DecayResult:
    """Tab 04 Section C:

        decay_factor = 1.00                                    while uncured (persistence hold)
        decay_factor = MAX(floor, 0.5 ** (days_since_cure / half_life))   once cured

    Excluded from scoring (`in_scope=False`) when decay_factor < 0.15, or
    age exceeds 400 days — checked even for an uncured signal, so an
    unresolved condition older than 400 days is flagged rather than scored
    forever at full weight."""
    if non_decaying:
        return DecayResult(1.0, True, NON_DECAYING_DECAY_CLASS.name)

    decay_class = SUBCATEGORY_DECAY_CLASS.get(sub_category_code)
    if decay_class is None:
        raise KeyError(f"no decay class declared for sub-category {sub_category_code!r}")

    if not cured:
        decay_factor = 1.0
    else:
        decay_factor = max(decay_class.floor,
                            0.5 ** (days_since_cure / decay_class.half_life_days))

    in_scope = decay_factor >= HARD_CUTOFF_DECAY_FACTOR and age_days <= HARD_CUTOFF_AGE_DAYS
    return DecayResult(decay_factor, in_scope, decay_class.name)


@dataclass(frozen=True)
class AcceleratorInput:
    magnitude_band: int
    velocity_band: int
    persistence_band: int
    repetition_band: int
    corroboration_band: int
    decay_factor: float


@dataclass(frozen=True)
class AcceleratorResult:
    dimension_multipliers: dict[str, float]
    decay_factor: float
    accelerator_multiplier: float

    def to_dict(self) -> dict:
        return {
            "dimension_multipliers": self.dimension_multipliers,
            "decay_factor": self.decay_factor,
            "accelerator_multiplier": round(self.accelerator_multiplier, 6),
        }


def compute_accelerator(inp: AcceleratorInput) -> AcceleratorResult:
    """Tab 04 Section C: accelerator_multiplier = decay * (1 + SUM(w*(m-1)))."""
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
    return AcceleratorResult(
        dimension_multipliers=multipliers,
        decay_factor=inp.decay_factor,
        accelerator_multiplier=inp.decay_factor * blended,
    )


def signal_score(trigger_score: int, accelerator_multiplier: float) -> float:
    """Tab 04 Section C: signal_score = MIN(100, trigger_score * accelerator)."""
    return min(100.0, trigger_score * accelerator_multiplier)

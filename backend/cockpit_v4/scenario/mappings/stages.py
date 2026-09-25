"""Stages are frozen, and a lifetime figure is never an annual one times N.

Section 8: *"Freeze stages by default. An explicit stage move requires the
declared horizon contract or reports unsupported. Never approximate a
lifetime figure by multiplying a twelve-month figure by a number of years."*

**Why frozen is the default.** A stage is an accounting classification with
its own SICR rules, and those rules are the bank's, not a scenario's. A
scenario that raised PD by 20% and let stages re-derive would be reporting
two changes as one: the PD move the reader asked for, and a migration the
staging policy produced. §13.2 wants those separable, and the only way to
have them separable is to hold one still.

**Why a move needs a contract.** Moving an exposure from Stage 1 to Stage 2
changes which ECL is recognised -- twelve-month becomes lifetime -- and that
is a different measurement, not a bigger one. It can be done only where the
book publishes a lifetime figure for that exposure, at a stated horizon.
Where it does not, this reports `unsupported` and names what is missing.

**Why the multiplication is banned by name.** `lifetime = 12m x years` is
wrong in both directions and wrong by a lot. It ignores survival: an exposure
that defaults in year one cannot default again in year two, so the naive
product double-counts. It ignores discounting, which pulls later losses down.
It ignores the term structure of PD, which is not flat. And it is the single
most tempting shortcut in the whole specification, because it produces a
number that looks about right. On this release's own Corporate book the
difference between the published lifetime ECL and `12m x remaining years` is
material at every maturity; `whatif_*_term_structure` is where the real
figure comes from, bucket by bucket.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.cockpit_v4.scenario.errors import (
    METHOD_COVERAGE_GAP,
    PARAMETER_OUT_OF_RANGE,
    raise_for,
)

#: The policy a spec carries. `frozen` is the default in `spec.ScenarioSpec`
#: and this module is what makes that mean something.
FROZEN = "frozen"
EXPLICIT = "explicit"
POLICIES = (FROZEN, EXPLICIT)

#: Which ECL a stage recognises. Stage 1 is twelve-month; 2 and 3 are
#: lifetime. Published here so a caller does not encode it inline.
RECOGNISED: dict[int, str] = {1: "ecl_12m_sar_mn", 2: "ecl_lifetime_sar_mn",
                              3: "ecl_lifetime_sar_mn"}

SUPPORTED = "SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class Contract:
    """What a book must publish before a stage move can be computed.

    `lifetime_horizon_months` is the declared horizon: a lifetime figure
    without one is a number over an unstated period, which is not a figure a
    scenario can move to.
    """

    has_lifetime_ecl: bool
    lifetime_horizon_months: float
    remaining_maturity_months: float
    term_structure_available: bool

    @property
    def complete(self) -> bool:
        return (self.has_lifetime_ecl and self.lifetime_horizon_months > 0
                and self.remaining_maturity_months > 0)

    def missing(self) -> list[str]:
        gaps: list[str] = []
        if not self.has_lifetime_ecl:
            gaps.append("a published lifetime ECL for this exposure")
        if self.lifetime_horizon_months <= 0:
            gaps.append("a declared lifetime horizon in months")
        if self.remaining_maturity_months <= 0:
            gaps.append("a remaining maturity")
        return gaps


@dataclass(frozen=True)
class Move:
    """One exposure's stage change, or the reason there isn't one."""

    entity_id: str
    from_stage: int
    to_stage: int
    status: str
    ecl_baseline: Decimal
    ecl_scenario: Decimal
    horizon_months: float
    reason: str

    @property
    def change(self) -> Decimal:
        return self.ecl_scenario - self.ecl_baseline

    @property
    def supported(self) -> bool:
        return self.status == SUPPORTED


def contract_from(row: Mapping[str, Any]) -> Contract:
    """Read the horizon contract from a published IFRS 9 row."""
    return Contract(
        has_lifetime_ecl=row.get("ecl_lifetime_sar_mn") is not None,
        lifetime_horizon_months=float(row.get("lifetime_horizon_months")
                                      or 0.0),
        remaining_maturity_months=float(row.get("remaining_maturity_months")
                                        or 0.0),
        term_structure_available=bool(row.get("term_structure_available")))


def require_policy(policy: str) -> str:
    if policy not in POLICIES:
        raise_for(PARAMETER_OUT_OF_RANGE,
                  f"{policy!r} is not a stage policy. They are "
                  f"{', '.join(POLICIES)}, and the default is {FROZEN}.",
                  field_path="stage_policy")
    return policy


def move(row: Mapping[str, Any], *, entity_key: str, to_stage: int,
         policy: str = FROZEN) -> Move:
    """One exposure's stage move under the declared policy.

    Under `frozen` this refuses outright: the reader asked for a stage change
    and the scenario says stages do not change, and running it anyway would
    make the policy decorative.
    """
    require_policy(policy)
    entity_id = str(row[entity_key])
    from_stage = int(row.get("stage") or 0)

    if policy == FROZEN:
        raise_for(PARAMETER_OUT_OF_RANGE,
                  f"this scenario holds stages frozen, so {entity_id} cannot "
                  f"be moved from Stage {from_stage} to Stage {to_stage}. "
                  f"Freezing is the default because a stage move changes "
                  f"which ECL is recognised, and a migration produced by the "
                  f"staging rules would be reported as part of the change "
                  f"the reader asked for. Ask for stage_policy=explicit if a "
                  f"stage move is what you want.",
                  field_path="stage_policy", stage_policy=FROZEN)

    if to_stage not in RECOGNISED:
        raise_for(PARAMETER_OUT_OF_RANGE,
                  f"Stage {to_stage} is not a stage. They are "
                  f"{', '.join(str(s) for s in sorted(RECOGNISED))}.",
                  field_path="stage")

    baseline = Decimal(str(row.get(RECOGNISED[from_stage], 0) or 0))
    contract = contract_from(row)
    if to_stage == from_stage:
        return Move(entity_id, from_stage, to_stage, SUPPORTED, baseline,
                    baseline, contract.lifetime_horizon_months,
                    "No change: the exposure is already in this stage.")

    if to_stage > 1 and not contract.complete:
        gaps = contract.missing()
        return Move(
            entity_id, from_stage, to_stage, UNSUPPORTED, baseline, baseline,
            contract.lifetime_horizon_months,
            f"Moving to Stage {to_stage} recognises a LIFETIME loss, and "
            f"this book does not publish what that needs for {entity_id}: "
            f"{', '.join(gaps)}. It is not approximated from the "
            f"twelve-month figure -- see this module's header for why that "
            f"is wrong rather than merely rough.")

    scenario = Decimal(str(row.get(RECOGNISED[to_stage], 0) or 0))
    return Move(
        entity_id, from_stage, to_stage, SUPPORTED, baseline, scenario,
        contract.lifetime_horizon_months,
        f"Stage {from_stage} recognises {RECOGNISED[from_stage]} and Stage "
        f"{to_stage} recognises {RECOGNISED[to_stage]}, both as published "
        f"for this exposure over a declared "
        f"{contract.lifetime_horizon_months:.0f}-month horizon.")


def never_multiply(*, ecl_12m: Decimal, years: Decimal) -> None:
    """The banned shortcut, as a function that only ever raises.

    It exists so the ban has a name a test can call and a call site can
    point at. Nothing in this package computes `ecl_12m x years`, and a
    future caller reaching for it finds this instead of writing it.
    """
    raise_for(METHOD_COVERAGE_GAP,
              f"a lifetime ECL is not {ecl_12m} multiplied by {years} years. "
              f"That product ignores survival, so it counts a default in "
              f"year one again in year two; it ignores discounting, which "
              f"pulls later losses down; and it assumes a flat PD term "
              f"structure, which no book has. The lifetime figure comes from "
              f"the published term structure, bucket by bucket, or it is "
              f"reported unavailable.",
              field_path="ecl_lifetime_sar_mn")


def summarise(moves: Iterable[Move]) -> dict[str, Any]:
    """Counts and totals for a set of moves, supported and not alike.

    Unsupported exposures are counted and their baseline is carried, so the
    population the scenario covered and the population it did not both add
    up to the book. An unsupported row is not a zero change; it is a row the
    scenario could not answer for, and the two are different facts.
    """
    collected = list(moves)
    supported = [m for m in collected if m.supported]
    unsupported = [m for m in collected if not m.supported]
    return {
        "exposures": len(collected),
        "moved": len([m for m in supported if m.from_stage != m.to_stage]),
        "unchanged": len([m for m in supported
                          if m.from_stage == m.to_stage]),
        "unsupported": len(unsupported),
        "unsupported_reasons": sorted({m.reason for m in unsupported}),
        "ecl_baseline": sum((m.ecl_baseline for m in collected), Decimal(0)),
        "ecl_scenario": sum((m.ecl_scenario for m in collected), Decimal(0)),
        "ecl_change": sum((m.change for m in collected), Decimal(0)),
    }


__all__ = ["Contract", "EXPLICIT", "FROZEN", "Move", "POLICIES", "RECOGNISED",
           "SUPPORTED", "UNSUPPORTED", "contract_from", "move",
           "never_multiply", "require_policy", "summarise"]

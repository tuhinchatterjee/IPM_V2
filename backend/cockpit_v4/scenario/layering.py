"""Stacking a scenario on a prior scenario's result (v3.1 §5.2, UAT-04).

A second scenario either starts from the ORIGINAL reported baseline or is
LAYERED on a prior scenario's stressed output. Never assumed: the reader
chooses (BASE01), unless they already said (BASE02/03).

Layering is an overlay chain, computed in memory: each ancestor's Delta rules
are applied to a COPY of the rows -- its scenario ECL replaces the booked ECL
and every parameter it moved carries its stressed value -- and the child runs
on those copies. Source rows are never written (BASE08, SEC07). Only rows in
an ancestor's own frozen cohort are stressed by it, and only where its rules
reach.

The chain is verified before use: each ancestor's contract digest must equal
the one recorded when the child was defined (PERSIST09).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.cockpit_v4.scenario import delta as dl
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario.errors import CONFIRMATION_STALE, raise_for

SOURCE_BASELINE = "SOURCE_BASELINE"
PRIOR_SCENARIO = "PRIOR_SCENARIO"
MODES = (SOURCE_BASELINE, PRIOR_SCENARIO)


@dataclass(frozen=True)
class Ancestor:
    """One link of the chain: a confirmed spec and the rows it stressed."""

    spec: sp.ScenarioSpec
    members: frozenset[str]
    #: The contract digest the child recorded for this parent.
    expected_digest: str = ""


def verify(chain: Sequence[Ancestor]) -> None:
    """Refuse a chain whose parent contract moved since it was chosen."""
    for link in chain:
        if link.expected_digest and link.spec.digest() != link.expected_digest:
            raise_for(CONFIRMATION_STALE,
                      f"the parent scenario {link.spec.scenario_id} no longer "
                      f"hashes to the contract this scenario was layered on "
                      f"({link.expected_digest[:12]} vs "
                      f"{link.spec.digest()[:12]}). Nothing was run.",
                      field_path="baseline.parent")


def stress_row(plan: dl.Plan, row: dict[str, Any]) -> dict[str, Any]:
    """A COPY of `row` with one scenario's Delta rules applied."""
    out = dict(row)
    result = dl.scale_row(plan, dict(row))
    if result.disposition != dl.SCALED:
        return out
    out["ecl_sar_mn"] = result.scenario_ecl
    for factor in plan.factors:
        if factor.field_id not in out or out[factor.field_id] is None:
            continue
        if factor.scope and not dl._in_scope(factor.scope, row):
            continue
        if factor.applies_when and not dl._matches(factor.applies_when, row):
            continue
        out[factor.field_id] = un.apply(
            Decimal(str(out[factor.field_id])), factor.shock.amount,
            storage=factor.storage)
    return out


def transform(chain: Sequence[Ancestor], *, key: str = "entity_id"
              ) -> Callable[[list[dict[str, Any]]], list[dict[str, Any]]]:
    """The `rows_transform` a layered child passes to `compute_core`."""
    verify(chain)
    plans = [(dl.plan(link.spec), link.members) for link in chain]
    columns: list[str] = ["stage", "write_off_sar_mn", "undrawn_sar_mn"]
    for plan, _members in plans:
        for factor in plan.factors:
            columns.append(factor.field_id)
            columns.extend(c for c, _v in factor.scope)

    def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            current = dict(row)
            for plan, members in plans:
                if str(current.get(key)) in members:
                    current = stress_row(plan, current)
            out.append(current)
        return out

    # The columns the ancestors' rules read, so the child's cohort read
    # selects them even when the child's own rules do not.
    apply.columns = tuple(dict.fromkeys(columns))  # type: ignore[attr-defined]
    return apply


def parent_delta(chain: Sequence[Ancestor], rows: Sequence[Mapping[str, Any]],
                 *, key: str = "entity_id") -> Decimal:
    """How far the chain moved these rows: the child's opening offset."""
    booked = sum((Decimal(str(r.get("ecl_sar_mn") or 0)) for r in rows),
                 Decimal(0))
    stressed = sum((Decimal(str(r.get("ecl_sar_mn") or 0))
                    for r in transform(chain, key=key)(
                        [dict(r) for r in rows])), Decimal(0))
    return stressed - booked


__all__ = ["Ancestor", "MODES", "PRIOR_SCENARIO", "SOURCE_BASELINE",
           "parent_delta", "stress_row", "transform", "verify"]

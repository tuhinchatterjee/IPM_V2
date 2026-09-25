"""Turning a list of shocks into a graph, and finding what has to be asked.

Section 5.2: *"Compile a typed rule list and a directed dependency graph, not
an arbitrary list of multipliers."*

The graph matters for two different reasons, and it is worth keeping them
apart because they pull in opposite directions.

**ORDER.** A parent shock changes a child: unemployment moves PD, a rating
moves PD, CCF moves EAD, collateral moves LGD. So the parent has to be applied
before the child, and section 5.2 gives the sequence: freeze the baseline,
resolve upstream moves, apply their mappings, apply direct overrides, apply
stage changes, derive dependent fields, validate, then calculate.

**GROUPING.** For the headline bridge, a parent and everything it induced are
ONE intervention, not several. Section 13.2: *"Do not show the total macro
effect and its own induced PD effect as two separate additive bars."* A reader
told that unemployment contributed 40 and PD contributed 35 will add them, and
they were the same 40.

So `order()` flattens the graph and `groups()` does not, and the two are used
by different parts of the answer.

The third job here is conflict resolution, and the rule is a refusal: section
5.2 says *"Never silently assume 'more specific wins'."* `resolve()` applies a
composition the reader has declared; it does not invent one. Where none is
declared, `spec.require_no_conflicts()` has already raised the question.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal

from backend.cockpit_v4.scenario import fields as fd
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario.errors import RULE_CONFLICT, raise_for

# ---- how two rules on one field compose --------------------------------
#
# Section 5.2's allowed resolved operations, named as the reader names them.
# "Instead", "on top of" and "except" must be represented correctly, and a
# duplicate identical instruction must not be applied twice by accident.

#: The later rule replaces the earlier one on the rows they share.
#: The reader's "instead".
OVERRIDE = "override"

#: The later rule applies to the value the earlier one produced.
#: The reader's "on top of".
COMPOUND = "compound"

#: The later rule applies only to the rows the earlier one did not cover.
#: The reader's "except" / "for the rest".
REMAINDER = "remainder"

COMPOSITIONS: tuple[str, ...] = (OVERRIDE, COMPOUND, REMAINDER)

#: The order fields are resolved in, from section 5.2's default sequence.
#: Upstream causes first, the fields they derive last.
STAGE_ORDER: dict[str, int] = {
    # 1. upstream: macro, rating, score, structure
    "unemployment_rate": 10, "rating_current": 11, "behaviour_score": 12,
    "collateral_value": 13, "limit_sar_mn": 14,
    # 2. the risk parameters those map onto, and direct overrides of them
    "pd_pit_12m": 20, "pd_lifetime": 20, "lgd_pct": 21, "ccf": 22,
    # 3. stage and horizon
    "stage": 30,
    # 4. derived exposure
    "drawn_sar_mn": 40, "undrawn_sar_mn": 40, "balance_sar_mn": 40,
    "ead_sar_mn": 41,
}

#: Anything not named above resolves between the parameters and the stage
#: change: late enough that its causes have run, early enough to feed EAD.
DEFAULT_STAGE = 25


@dataclass(frozen=True)
class Group:
    """One intervention the reader made, with everything it induced.

    The unit the headline bridge attributes over. A macro move and the PD
    change it caused are one group, so they cannot be shown as two bars that
    a reader would add together.
    """

    label: str
    root: sp.Shock
    induced: tuple[sp.Shock, ...] = ()

    def all_shocks(self) -> tuple[sp.Shock, ...]:
        return (self.root,) + self.induced

    def fields(self) -> tuple[str, ...]:
        return tuple(s.field_id for s in self.all_shocks())

    def describe(self) -> str:
        if not self.induced:
            return f"{self.root.field_id} {self.root.amount.describe()}"
        moved = ", ".join(sorted({s.field_id for s in self.induced}))
        return (f"{self.root.field_id} {self.root.amount.describe()}, "
                f"which moves {moved}")


@dataclass(frozen=True)
class Overlap:
    """Two rules on one field whose scopes intersect, and how to compose them."""

    field_id: str
    earlier: sp.Shock
    later: sp.Shock
    composition: str = ""
    #: How many rows, and how much ECL, the intersection covers. Section 5.2:
    #: "Show overlap counts and amounts."
    rows: int = 0
    ecl: str = "0"

    def question(self) -> str:
        return (
            f"Two rules move {self.field_id} on the same "
            f"{self.rows:,} rows, carrying {self.ecl} SAR million of baseline "
            f"ECL: {self.earlier.origin or self.earlier.amount.describe()!r} "
            f"and {self.later.origin or self.later.amount.describe()!r}. "
            f"Which did you mean?")

    def options(self) -> list[str]:
        later = self.later.amount.describe()
        earlier = self.earlier.amount.describe()
        return [
            f"{later} instead, on those rows (override)",
            f"{later} on top of {earlier} (compound)",
            f"{later} only where the first rule did not apply (remainder)",
        ]


@dataclass
class Graph:
    """The compiled rule list: an order to apply in, and groups to attribute
    over."""

    shocks: tuple[sp.Shock, ...]
    overlaps: tuple[Overlap, ...] = ()
    _groups: tuple[Group, ...] = field(default=(), repr=False)

    def order(self) -> tuple[sp.Shock, ...]:
        """Application order: upstream causes first, derived fields last.

        Stable within a stage by the reader's own authoring order, so two
        rules that genuinely commute produce the same trace every run --
        section 14.2 wants a canonical rule order, and "whatever the set
        iterated as" is not one.
        """
        return tuple(sorted(
            self.shocks,
            key=lambda s: (STAGE_ORDER.get(s.field_id, DEFAULT_STAGE),
                           self.shocks.index(s))))

    def groups(self) -> tuple[Group, ...]:
        """The interventions the bridge attributes over, parents with their
        children folded in."""
        return self._groups

    def is_derived(self, field_id: str) -> bool:
        return any(s.field_id == field_id and s.is_derived()
                   for s in self.shocks)


def compile_rules(spec: sp.ScenarioSpec, *,
                  known: tuple[Overlap, ...] = ()) -> Graph:
    """Group the shocks and order them. Raises if a conflict is undeclared.

    Grouping is by `derived_from`, which `mappings` sets when it induces a
    child. A shock with no parent is its own group; a shock with one is
    folded into its parent's.

    The conflict check runs FIRST and is not optional. `order()` will happily
    sequence two rules that move the same field over the same rows, and the
    sequence it picks would then decide the answer -- which is section 5.2's
    silent "more specific wins" arriving by the back door. So a compile of an
    unsurfaced overlap raises the question instead of producing a graph.

    `known` is the overlaps the caller has already measured and is putting to
    the reader. They are still unresolved; the preview exists to show them
    with their counts and amounts, and it could not if an overlap stopped the
    graph being built. What the check forbids is an overlap nobody saw.
    """
    spec.require_no_conflicts(
        acknowledged=[(o.earlier, o.later) for o in known])

    groups: list[Group] = []
    for root in spec.direct_shocks():
        induced = tuple(s for s in spec.derived_shocks()
                        if s.derived_from == root.field_id)
        groups.append(Group(
            label=root.origin or root.field_id, root=root, induced=induced))

    # A derived shock whose parent is not in this scenario is its own group
    # rather than silently absent: something produced it, and the bridge has
    # to attribute it somewhere.
    parents = {g.root.field_id for g in groups}
    for orphan in spec.derived_shocks():
        if orphan.derived_from not in parents:
            groups.append(Group(
                label=orphan.origin or orphan.field_id, root=orphan))

    return Graph(shocks=spec.shocks, overlaps=tuple(known),
                 _groups=tuple(groups))


def overlaps(spec: sp.ScenarioSpec, *, counts: dict[str, tuple[int, str]]
             | None = None) -> tuple[Overlap, ...]:
    """Every pair that needs a declared composition, with its size.

    `counts` maps a field id to `(rows, ecl)` for the intersection, measured
    by the caller against the cohort. Section 5.2 wants those numbers shown
    -- an overlap of four facilities and one of four thousand are different
    conversations.
    """
    found: list[Overlap] = []
    for earlier, later in spec.conflicts():
        rows, ecl = (counts or {}).get(earlier.field_id, (0, "0"))
        found.append(Overlap(field_id=earlier.field_id, earlier=earlier,
                             later=later, rows=rows, ecl=ecl))
    return tuple(found)


def resolve(overlap: Overlap, composition: str) -> Overlap:
    """Record the composition the reader chose. Never guesses one."""
    if composition not in COMPOSITIONS:
        raise_for(RULE_CONFLICT,
                  f"{composition!r} is not a composition. A later rule can "
                  f"{', '.join(COMPOSITIONS)}.",
                  field_path="composition")
    return Overlap(field_id=overlap.field_id, earlier=overlap.earlier,
                   later=overlap.later, composition=composition,
                   rows=overlap.rows, ecl=overlap.ecl)


def deduplicate(shocks: tuple[sp.Shock, ...]) -> tuple[sp.Shock, ...]:
    """Drop repeats of an identical instruction in one revision.

    Section 5.2: *"Duplicate identical instructions in the same revision must
    not be applied twice accidentally."* Identical means same field, same
    operation, same value, same scope -- a reader who said the same thing
    twice said it once. Two rules that differ in any of those are not
    duplicates and are left alone for the conflict check to find.
    """
    seen: set[str] = set()
    out: list[sp.Shock] = []
    for shock in shocks:
        key = json.dumps(shock.canonical(), sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(shock)
    return tuple(out)


def apply_to_value(baseline: Decimal, ordered: tuple[sp.Shock, ...], *,
                   domain_id: str, field_id: str) -> Decimal:
    """Walk one field's shocks over one baseline, in order.

    Used for the preview's worked example and by the oracles. The scenario
    itself is computed in SQL over the whole population, not row by row here
    -- section 9.1 forbids sampling for a reported total -- but the arithmetic
    has to agree, and a test that pins the two together is why this exists.
    """
    entry = fd.lookup(domain_id, field_id)
    value = baseline
    for shock in ordered:
        if shock.field_id != field_id:
            continue
        value = un.apply(value, shock.amount, storage=entry.storage)
    return value


__all__ = ["COMPOSITIONS", "COMPOUND", "DEFAULT_STAGE", "Graph", "Group",
           "OVERRIDE", "Overlap", "REMAINDER", "STAGE_ORDER",
           "apply_to_value", "compile_rules", "deduplicate", "overlaps",
           "resolve"]

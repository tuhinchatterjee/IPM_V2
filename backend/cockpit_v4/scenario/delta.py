"""Method 1: move the risk parameters, scale the published ECL by the ratio.

Section 10.1 gives the rule: `M1_i = M0_i x PROD_k factor_k ^ elasticity_k`,
with the factors being the scenario-over-baseline ratios of the parameters the
reader moved and the elasticities defaulting to 1 for PD, LGD and CCF.

**Why elasticity 1 is exact here, and not a convention.** Published ECL in
both books is `ead x pd x lgd` -- 12-month PD at Stage 1, lifetime PD at
Stages 2 and 3 -- and the identity reconciles on the published parquet to
-0.3343 SAR mn on a 7,075,662 SAR mn Corporate book, which is rounding. ECL is
therefore linear in each parameter separately, so a 20% PD rise raises ECL by
exactly 20% on the rows whose ECL that PD enters. Where the identity does NOT
hold, the rows are excluded with the reason attached rather than scaled:
`fields.sql_ineligibility` owns that list and it was measured, not assumed.

**Which PD enters which row.** ECL uses the 12-month PD at Stage 1 and the
lifetime PD at Stages 2 and 3. A shock on `pd_pit_12m` therefore moves a
Stage 1 row and leaves a Stage 2 row exactly alone -- not approximately, not
by a small amount: by zero. That is section 13.1's unaffected-rows rule
falling out of the arithmetic rather than being imposed on top of it, and
`applies_when` is where it is written down.

**Zeros.** Section 10.3. Zero to zero is a neutral factor of 1; zero to a
positive value has no ratio and is UNSUPPORTED, never an epsilon denominator.
`units.factor` returns `None` for that case and this module turns the `None`
into a reason-coded row, because an epsilon would turn a contractual PD of
zero into an arbitrary large multiplier on a real ECL.

The arithmetic here is the oracle and the preview's worked example. The run
itself happens in SQL over the whole population -- section 9.1 forbids
sampling for a reported total -- and `test_whatif_delta.py` pins the two
together so that they cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from decimal import Decimal
from typing import Any

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import fields as fd
from backend.cockpit_v4.scenario import rules as ru
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario.errors import (
    METHOD_COVERAGE_GAP,
    raise_for,
)

#: Section 10.1's default, and here an exact one. See the header.
UNIT_ELASTICITY = Decimal(1)

#: The parameters ECL is a product of, and the only ones a proportional
#: Delta may scale by. Anything else a reader moves is a structural change
#: that has to go through `structural_ead` or a different method.
PARAMETERS: tuple[str, ...] = ("pd_pit_12m", "pd_lifetime", "lgd_pct",
                               "ead_sar_mn", "ccf")

#: The exposure components a structural EAD move is built from (section
#: 10.2). Moving these is NOT the same as scaling EAD, and the trace says so.
#: The approved limit is deliberately absent from both: it enters no
#: published ECL input in either book, so it is not a Delta field at all.
#: `fields.py` says so at the definition and this module never sees it.
STRUCTURAL: dict[str, tuple[str, ...]] = {
    dom.CORPORATE: ("drawn_sar_mn", "undrawn_sar_mn", "ccf"),
    dom.RETAIL: ("balance_sar_mn",),
}

#: Which rows each parameter's ECL actually depends on. Empty means all of
#: them. These are SQL over the ECL-bearing relation, for the same reason
#: `fields.sql_ineligibility` is: the calculation runs in the database.
APPLIES_WHEN: dict[str, str] = {
    "pd_pit_12m": "stage = 1",
    "pd_lifetime": "stage IN (2, 3)",
}

# ---- reason codes a row can carry out of a Delta run -------------------

#: The row was scaled.
SCALED = "scaled"

#: The row is in the cohort, the shock is sound on it, and the parameter the
#: shock moved does not enter this row's ECL. Its change is exactly zero.
UNAFFECTED = "unaffected"

#: The shock cannot move this row correctly, for a measured reason.
INELIGIBLE = "ineligible"

#: The ratio does not exist -- a zero baseline going somewhere positive.
UNSUPPORTED = "unsupported"

DISPOSITIONS: tuple[str, ...] = (SCALED, UNAFFECTED, INELIGIBLE, UNSUPPORTED)


@dataclass(frozen=True)
class Factor:
    """One parameter's move, with everything needed to apply and to explain it.

    `elasticity` is carried explicitly even though it is 1 today, because
    section 10.1 allows a declared elasticity and a run that used one must
    say so in its trace rather than leave a reader to assume the default.
    """

    field_id: str
    shock: sp.Shock
    elasticity: Decimal = UNIT_ELASTICITY
    #: SQL for the rows whose ECL this parameter enters. Empty means all.
    applies_when: str = ""
    #: SQL for rows the shock cannot move, and the reason a reader is shown.
    excluded_when: str = ""
    exclusion_reason: str = ""
    #: The column's storage convention, so the arithmetic stays in it.
    storage: str = un.FRACTION

    def ratio(self, baseline: Decimal) -> Decimal | None:
        """`scenario / baseline` for this parameter, or None when there is
        none. Section 10.3 and oracle O11."""
        moved = un.apply(baseline, self.shock.amount, storage=self.storage)
        return un.factor(baseline, moved)

    def contribution(self, baseline: Decimal) -> Decimal | None:
        """The multiplier this factor contributes: `ratio ^ elasticity`.

        Only integer elasticities are computed here. A fractional elasticity
        is a declared model assumption rather than an arithmetic convenience,
        and Decimal's fractional power would introduce a float; P5 brings it
        in with its own evidence.
        """
        found = self.ratio(baseline)
        if found is None:
            return None
        if self.elasticity == UNIT_ELASTICITY:
            return found
        if self.elasticity % 1 != 0:
            raise_for(METHOD_COVERAGE_GAP,
                      f"an elasticity of {self.elasticity} on "
                      f"{self.field_id} is a declared model assumption, and "
                      f"this build carries none. Delta applies unit "
                      f"elasticity, which is exact because ECL is linear in "
                      f"this parameter.",
                      field_path=f"shocks.{self.field_id}")
        return found ** int(self.elasticity)

    def describe(self) -> str:
        line = f"{self.field_id} {self.shock.amount.describe()}"
        if self.elasticity != UNIT_ELASTICITY:
            line += f", elasticity {self.elasticity}"
        return line


@dataclass(frozen=True)
class RowResult:
    """One row's before and after, and which of the four things happened."""

    baseline_ecl: Decimal
    scenario_ecl: Decimal
    disposition: str
    reason: str = ""
    multiplier: Decimal = Decimal(1)

    @property
    def change(self) -> Decimal:
        return self.scenario_ecl - self.baseline_ecl


@dataclass(frozen=True)
class Plan:
    """The factors a confirmed scenario resolves to, and how it will run."""

    domain_id: str
    submode: str
    factors: tuple[Factor, ...] = ()
    #: Fields the reader moved that Delta does not scale by. Kept rather than
    #: dropped: a scenario that moved one of these and reported a Delta total
    #: would be reporting a number that ignored part of what was asked.
    unhandled: tuple[str, ...] = ()
    notes: tuple[str, ...] = _field(default_factory=tuple)

    def fields(self) -> tuple[str, ...]:
        return tuple(f.field_id for f in self.factors)

    def describe(self) -> list[str]:
        return [f.describe() for f in self.factors]


def plan(spec: sp.ScenarioSpec, *,
         graph: ru.Graph | None = None) -> Plan:
    """Resolve a scenario into the factors a proportional Delta multiplies by.

    Refuses a field the book does not carry or a scenario may not move --
    `fields.mutable` owns both refusals -- and refuses a field Delta cannot
    express, rather than quietly leaving it out of the product.
    """
    graph = graph or ru.compile_rules(spec)
    domain_id = spec.source.domain_id
    structural = spec.delta_submode == sp.STRUCTURAL_EAD

    factors: list[Factor] = []
    unhandled: list[str] = []
    notes: list[str] = []
    for shock in graph.order():
        entry = fd.mutable(domain_id, shock.field_id)
        if sp.DELTA not in entry.methods:
            raise_for(METHOD_COVERAGE_GAP,
                      f"Delta scales ECL by the ratio of a risk parameter, "
                      f"and {shock.field_id} is not one of them in the "
                      f"{domain_id} book. Delta handles: "
                      f"{', '.join(_delta_fields(domain_id))}.",
                      field_path=f"shocks.{shock.field_id}",
                      method=sp.DELTA)
        if shock.field_id not in PARAMETERS:
            # A structural component. It moves EAD, which moves ECL, but not
            # by its own ratio -- section 10.2 -- so it is handled there and
            # must not be multiplied in here as if it were a parameter.
            if shock.field_id not in STRUCTURAL.get(domain_id, ()):
                raise_for(METHOD_COVERAGE_GAP,
                          f"{shock.field_id} enters no published ECL input "
                          f"in the {domain_id} book, so a Delta run on it "
                          f"would report a change of zero -- which is a "
                          f"wrong answer, not a small one. Delta handles: "
                          f"{', '.join(_delta_fields(domain_id))}.",
                          field_path=f"shocks.{shock.field_id}",
                          method=sp.DELTA)
            unhandled.append(shock.field_id)
            continue
        if shock.field_id == "ccf" and not structural:
            notes.append(
                "CCF is a component of EAD, so a CCF move has two correct "
                "answers and they are different numbers. This run scales "
                "ECL by the CCF ratio; the structural EAD submode instead "
                "rebuilds exposure as drawn + CCF x undrawn and recomputes. "
                "Section 10.2's own example gives 2,160 one way and 1,840 "
                "the other. Neither is wrong; reporting one as the other "
                "is, and so is multiplying by both.")
        excluded, reason = fd.sql_ineligibility(domain_id, shock.field_id)
        factors.append(Factor(
            field_id=shock.field_id, shock=shock,
            applies_when=APPLIES_WHEN.get(shock.field_id, ""),
            excluded_when=excluded, exclusion_reason=reason,
            storage=entry.storage))

    if unhandled and not structural:
        notes.append(
            f"{', '.join(unhandled)} change the exposure itself rather than "
            f"a rate applied to it. Proportional Delta cannot express that; "
            f"the structural EAD submode can.")

    return Plan(domain_id=domain_id,
                submode=sp.STRUCTURAL_EAD if structural else sp.PROPORTIONAL,
                factors=tuple(factors), unhandled=tuple(unhandled),
                notes=tuple(notes))


def _delta_fields(domain_id: str) -> list[str]:
    """What to name in a refusal: fields Delta can actually be asked for.

    Mutable as well as Delta-capable. `methods` defaults to both methods on
    every field, so a published-but-immutable column like `ecl_sar_mn` or
    `sector` carries DELTA without a scenario ever being able to move it --
    and naming those in a refusal would send a reader to ask for something
    that will be refused again for a different reason.
    """
    return sorted(f.field_id for f in fd.BY_DOMAIN.get(domain_id, ())
                  if sp.DELTA in f.methods and f.mutable
                  and f.availability != fd.ABSENT)


def scale_row(plan_: Plan, row: dict[str, Any]) -> RowResult:
    """One row's scenario ECL, and which of the four dispositions it took.

    `row` carries the baseline values the factors need, in the column's own
    storage, as Decimal. The four outcomes are exclusive and exhaustive, and
    an ineligible or unsupported row keeps its BASELINE ECL rather than
    becoming zero -- section 9.1: *"never silently treat an ineligible record
    as zero incremental ECL."*

    An `overlay_sar_mn` on the row is a management overlay held fixed
    (section 9.1, and `spec.overlay_policy`). Only the modelled part is
    scaled and the overlay is added back untouched, which is a different
    number from scaling the whole reported ECL: 8,000 split 7,600 + 400 under
    a 20% PD rise is 9,520, not 9,600. Neither published book carries the
    split -- `ecl.py` refuses to invent it -- so this is zero everywhere
    today and the arithmetic is here for a book that does.
    """
    reported = _decimal(row.get("ecl_sar_mn", 0))
    overlay = _decimal(row.get("overlay_sar_mn", 0))
    baseline = reported - overlay

    for factor in plan_.factors:
        if factor.excluded_when and _matches(factor.excluded_when, row):
            return RowResult(reported, reported, INELIGIBLE,
                             factor.exclusion_reason)

    multiplier = Decimal(1)
    touched = False
    for factor in plan_.factors:
        if factor.applies_when and not _matches(factor.applies_when, row):
            continue
        contribution = factor.contribution(_decimal(row[factor.field_id]))
        if contribution is None:
            return RowResult(reported, reported, UNSUPPORTED, fd.ZERO_BASELINE)
        multiplier *= contribution
        touched = True

    if not touched:
        return RowResult(reported, reported, UNAFFECTED,
                         "the parameters this scenario moved do not enter "
                         "this row's ECL, so its change is exactly zero.")
    return RowResult(reported, baseline * multiplier + overlay, SCALED,
                     multiplier=multiplier)


def structural_ead(row: dict[str, Any], *, domain_id: str,
                   moved: dict[str, Decimal]) -> Decimal:
    """Section 10.2: rebuild EAD from its components rather than scaling it.

    Corporate publishes drawn and undrawn and derives CCF as
    `(ead - drawn) / undrawn`, so a scenario that moves the undrawn
    commitment or the conversion factor produces a NEW exposure
    `drawn + ccf x undrawn` -- which is a different number from scaling the
    old EAD, and the specification's own worked example (2,160 against 1,840)
    is the whole reason the two submodes are named separately.

    Retail publishes no CCF and sets `ead = balance` outside Credit Card, so
    the structural form there is the moved balance itself.
    """
    if domain_id == dom.RETAIL:
        return _decimal(moved.get("balance_sar_mn",
                                  row.get("balance_sar_mn", 0)))
    drawn = _decimal(moved.get("drawn_sar_mn", row.get("drawn_sar_mn", 0)))
    undrawn = _decimal(moved.get("undrawn_sar_mn",
                                 row.get("undrawn_sar_mn", 0)))
    ccf = _decimal(moved.get("ccf", row.get("ccf", 0)))
    return drawn + ccf * undrawn


def baseline_ccf(row: dict[str, Any]) -> Decimal | None:
    """Corporate's derived CCF, or None where there is no undrawn to convert.

    Labelled DERIVED everywhere it is used. `(ead - drawn) / undrawn` inverts
    to a meaningless 2.8e-14 on the 1,308 facilities with zero undrawn, which
    is why the zero case is a None rather than a number.
    """
    undrawn = _decimal(row.get("undrawn_sar_mn", 0))
    if undrawn == 0:
        return None
    return (_decimal(row["ead_sar_mn"]) - _decimal(row["drawn_sar_mn"])
            ) / undrawn


# ---- the small amount of interpretation this module does ---------------

def _matches(predicate: str, row: dict[str, Any]) -> bool:
    """Evaluate one of THIS module's own predicates against one row.

    Deliberately not a SQL engine and deliberately not `eval`. The predicates
    it has to understand are the handful written down in `APPLIES_WHEN` and
    `fields.sql_ineligibility`, they are fixed strings in this repository
    rather than anything a reader can author, and the population run
    evaluates the same strings in the database. This exists so the oracle and
    the worked example can walk a row; an unrecognised predicate raises
    rather than guessing, so a new one cannot silently start matching
    nothing.
    """
    text = predicate.strip()
    if not text or text == "TRUE":
        return bool(text)
    if text == "stage = 3":
        return _decimal(row["stage"]) == 3
    if text == "stage = 1":
        return _decimal(row["stage"]) == 1
    if text == "stage IN (2, 3)":
        return _decimal(row["stage"]) in (Decimal(2), Decimal(3))
    if text == "undrawn_sar_mn = 0":
        return _decimal(row["undrawn_sar_mn"]) == 0
    if text == "write_off_sar_mn > 0":
        return _decimal(row["write_off_sar_mn"]) > 0
    raise AssertionError(
        f"{predicate!r} is not one of this module's predicates. Add it here "
        f"and to the SQL compiler together, or the oracle and the run will "
        f"disagree.")


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise un.UnitError(
            f"{value!r} arrived as a float. Read the column as a string or a "
            f"Decimal; see `units`' header for why this is refused.")
    return Decimal(str(value))


__all__ = [
    "APPLIES_WHEN", "DISPOSITIONS", "Factor", "INELIGIBLE", "PARAMETERS",
    "Plan", "RowResult", "SCALED", "STRUCTURAL", "UNAFFECTED",
    "UNIT_ELASTICITY", "UNSUPPORTED", "baseline_ccf", "plan", "scale_row",
    "structural_ead",
]

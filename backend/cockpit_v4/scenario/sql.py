"""Turning a confirmed scenario into the analysis the existing tool runs.

Nothing here executes anything. This module compiles a `ScenarioSpec` and a
`delta.Plan` into the `execute_analysis` submission the analyst sends, and
then the accepted runtime does what it already does: validate the SQL, bind
it, authorize it, run it against the governed book and publish the result as
an artifact. That is the whole of the integration -- no sixth tool, no second
execution path, no query that skips a check.

**Why the calculation is SQL and not Python.** Section 9.1 forbids sampling
for a reported total, and a Corporate cohort can be hundreds of thousands of
facility-quarters. Aggregating in the database over the full population is
the only form of the answer that is both complete and affordable.
`delta.scale_row` exists to walk ONE row for the preview's worked example and
for the oracles, not to compute a published total.

**The drift risk, and what is done about it.** The unit algebra now exists
twice: once in `units.apply` and once as the SQL below. Two implementations
of one rule diverge unless something holds them together, so
`test_whatif_sql.py` evaluates every operation-and-storage pair both ways
over a grid of baselines and asserts they agree exactly. If a future edit
changes one and not the other, that test fails before anything is published.

**The identity being exploited.** Published ECL is `ead x pd x lgd`, so
scaling ECL by the product of the parameters' ratios is exact rather than
approximate -- see `delta.py`'s header for the measurement. That is what
makes a whole scenario one `CASE` expression over one relation, and it is
why this file is short.
"""

from __future__ import annotations

from decimal import Decimal

from backend.cockpit_v4.scenario import cohort as ch
from backend.cockpit_v4.scenario import delta as dl
from backend.cockpit_v4.scenario import fields as fd
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario.errors import METHOD_COVERAGE_GAP, raise_for

#: The SQL for a field that is not a column of its own. The prose version of
#: the same derivation lives on `fields.Field.derivation`, where a reader
#: sees it; this is the machine one, and they are kept apart so the reader's
#: explanation is never load-bearing for the arithmetic.
COLUMN: dict[str, str] = {
    "ccf": "((ead_sar_mn - drawn_sar_mn) / undrawn_sar_mn)",
}

#: What `delta.DISPOSITIONS` looks like in a result column.
DISPOSITION = "disposition"


def column(field_id: str) -> str:
    """The SQL expression that reads a field, derived or published."""
    return COLUMN.get(field_id, field_id)


def literal(value: Decimal) -> str:
    """A Decimal as SQL. Plain notation, never exponent form.

    `1E-8` is valid SQL in most engines and is read back as a float by some
    of them; `0.00000001` is read as an exact numeric by all of them, and
    this module's whole contract is that the SQL agrees with the Decimal
    arithmetic to the last place.
    """
    return format(value.normalize(), "f")


def moved_value(field_id: str, amount: un.Amount, *, storage: str) -> str:
    """The scenario value of one field, as SQL, in the column's own storage.

    The mirror of `units.apply`, operation for operation. Kept in the same
    order as that function so a reader can hold the two side by side, and
    pinned to it by test rather than by care.

    **Every conversion is done here, in Decimal, and reaches the engine as a
    single literal.** `col * (1 + 20 / 100)` would make DuckDB divide an
    integer by an integer -- which it widens to DOUBLE -- and the result of
    `0.02 * (1 + 2.5/100)` comes back as 0.020499999999999997 rather than
    0.02050. Emitting `col * 1.025` keeps the engine in DECIMAL wherever the
    column is, one operation instead of three, and the constant is exactly
    the one `units.apply` used. All four denominators here -- 100 and 10,000
    -- divide exactly in Decimal, so nothing is lost in the conversion.

    Where the COLUMN is DOUBLE, as every numeric column in both published
    books is, the product is DOUBLE and carries the engine's own rounding.
    That is a property of the book's storage, not of this compiler, and it
    is why `ledger.CURRENCY` exists and why the row-level agreement test
    compares at a declared relative tolerance rather than exactly.
    """
    col = column(field_id)
    value = literal(amount.value)
    hundredths = literal(amount.value / 100)

    if amount.operation == un.SET_TO:
        # SET_TO names the value in the field's DISPLAY unit, and a
        # fraction-stored field displays as a percent.
        return f"({hundredths})" if storage == un.FRACTION else f"({value})"
    if amount.operation == un.RELATIVE:
        return f"({col} * {literal(1 + amount.value / 100)})"
    if amount.operation == un.MULTIPLY:
        return f"({col} * {value})"
    if amount.operation in (un.ABSOLUTE_AMOUNT, un.POINTS):
        return f"({col} + {value})"
    if amount.operation == un.ABSOLUTE_PP:
        return f"({col} + {value if storage == un.PERCENT else hundredths})"
    if amount.operation == un.BASIS_POINTS:
        step = (hundredths if storage == un.PERCENT
                else literal(amount.value / 10000))
        return f"({col} + {step})"
    raise un.UnitError(
        f"{amount.operation} has no SQL form here. Add it beside "
        f"`units.apply`'s branch for it, or the two will disagree.")


def factor_sql(factor: dl.Factor) -> str:
    """One factor's multiplier: the ratio where it applies, 1 where it does not.

    Three things are folded into the one expression, and all three are
    section 10's:

    * where the parameter does not enter this row's ECL, the multiplier is 1
      -- a Stage 2 row is untouched by a 12-month PD shock, exactly;
    * where the baseline is zero and the scenario is not, the multiplier is
      NULL, which carries "no ratio exists" through the arithmetic instead of
      an epsilon;
    * where both are zero, the multiplier is 1: nothing moved.

    A declared elasticity is REFUSED here rather than ignored. `Factor`
    carries one and `Factor.contribution` raises it as a power; this
    compiler has no form for it, and emitting the bare ratio would make the
    population run and the preview's worked example disagree on the same
    scenario. Nothing sets a non-unit elasticity today -- `delta.plan` always
    builds unit -- so this guards the day something does.
    """
    if factor.elasticity != dl.UNIT_ELASTICITY:
        raise_for(METHOD_COVERAGE_GAP,
                  f"an elasticity of {factor.elasticity} on "
                  f"{factor.field_id} has no form in this compiler, and "
                  f"running the bare ratio instead would make the published "
                  f"total disagree with the preview that was confirmed.",
                  field_path=f"shocks.{factor.field_id}")
    col = column(factor.field_id)
    moved = moved_value(factor.field_id, factor.shock.amount,
                        storage=factor.storage)
    ratio = (f"CASE WHEN {col} = 0 AND {moved} = 0 THEN 1 "
             f"WHEN {col} = 0 THEN NULL "
             f"ELSE {moved} / {col} END")
    if not factor.applies_when:
        return f"({ratio})"
    return f"(CASE WHEN {factor.applies_when} THEN ({ratio}) ELSE 1 END)"


def multiplier_sql(plan: dl.Plan) -> str:
    """The product of every factor's multiplier. `1` when there are none."""
    if not plan.factors:
        return "1"
    return " * ".join(factor_sql(f) for f in plan.factors)


def ineligible_sql(plan: dl.Plan) -> str:
    """Rows no factor in this plan can move correctly. `FALSE` when none."""
    parts = [f"({f.excluded_when})" for f in plan.factors if f.excluded_when]
    return " OR ".join(parts) if parts else "FALSE"


def unaffected_sql(plan: dl.Plan) -> str:
    """Rows where every factor's parameter is absent from this row's ECL.

    `FALSE` when at least one factor applies everywhere, which is the common
    case: an LGD shock touches every eligible row.
    """
    scoped = [f for f in plan.factors if f.applies_when]
    if not plan.factors or len(scoped) < len(plan.factors):
        return "FALSE"
    return " AND ".join(f"NOT ({f.applies_when})" for f in scoped)


def disposition_sql(plan: dl.Plan) -> str:
    """Which of the four things happened to each row, as a result column.

    Published beside the numbers rather than inferred from them. A row whose
    change is zero could be unaffected, ineligible, or scaled by a factor of
    one, and a reader deciding whether to trust a total needs to know which
    -- section 9.1's reason-coded coverage is this column.
    """
    # Scoped by `applies_when`, for the same reason `factor_sql` is: a
    # parameter that does not enter this row's ECL has not failed to move it,
    # it simply is not part of its ECL. A Stage 2 row with a zero 12-month PD
    # under a 12-month PD shock is UNAFFECTED, not UNSUPPORTED, and
    # `delta.scale_row` reaches the same answer by testing the scope first.
    zero = " OR ".join(
        _scoped(f, f"{column(f.field_id)} = 0 AND "
                   f"{moved_value(f.field_id, f.shock.amount, storage=f.storage)}"
                   f" <> 0")
        for f in plan.factors) or "FALSE"
    return (f"CASE WHEN {ineligible_sql(plan)} THEN '{dl.INELIGIBLE}' "
            f"WHEN {zero} THEN '{dl.UNSUPPORTED}' "
            f"WHEN {unaffected_sql(plan)} THEN '{dl.UNAFFECTED}' "
            f"ELSE '{dl.SCALED}' END")


def _scoped(factor: dl.Factor, predicate: str) -> str:
    """A predicate about one factor, restricted to the rows it reaches."""
    if not factor.applies_when:
        return f"({predicate})"
    return f"(({factor.applies_when}) AND ({predicate}))"


def scenario_ecl_sql(plan: dl.Plan) -> str:
    """Each row's scenario ECL.

    A row the plan could not move keeps its BASELINE, never zero. Section
    9.1: *"never silently treat an ineligible record as zero incremental
    ECL."* That rule is the difference between a total that is missing 1,837
    accounts and a total that says it is.
    """
    keep = (f"{ineligible_sql(plan)} OR {unaffected_sql(plan)} OR "
            f"({multiplier_sql(plan)}) IS NULL")
    return (f"CASE WHEN {keep} THEN ecl_sar_mn "
            f"ELSE ecl_sar_mn * ({multiplier_sql(plan)}) END")


def row_ledger_sql(spec: sp.ScenarioSpec, plan: dl.Plan, *,
                   frozen: ch.Frozen) -> str:
    """Per-entity before and after over the whole cohort.

    No LIMIT and no sample. Section 9.1 is explicit, and the display cap is a
    presentation decision made later over a complete result -- not a shortcut
    taken here, where it would silently change the total.
    """
    grain = ch.GRAIN[spec.source.domain_id]
    where = [f"{grain['period']} = '{frozen.period}'"]
    if frozen.predicate:
        where.append(f"({frozen.predicate})")
    return (
        f"SELECT {grain['key']} AS entity_id,\n"
        f"       ecl_sar_mn AS baseline_sar_mn,\n"
        f"       {scenario_ecl_sql(plan)} AS scenario_sar_mn,\n"
        f"       {disposition_sql(plan)} AS {DISPOSITION}\n"
        f"FROM {grain['relation']}\n"
        f"WHERE {' AND '.join(where)}")


def book_totals_sql(spec: sp.ScenarioSpec, *, frozen: ch.Frozen) -> str:
    """The whole book at this period, cohort and non-cohort alike.

    Section 13.1's identity needs the denominator the cohort sits inside, and
    it has to come from the same relation and period as the cohort or the
    identity is being checked against a different population.
    """
    grain = ch.GRAIN[spec.source.domain_id]
    inside = frozen.predicate or "TRUE"
    return (
        f"SELECT SUM(ecl_sar_mn) AS book_baseline_sar_mn,\n"
        f"       SUM(CASE WHEN {inside} THEN ecl_sar_mn ELSE 0 END)\n"
        f"           AS cohort_baseline_sar_mn,\n"
        f"       SUM(CASE WHEN {inside} THEN 0 ELSE ecl_sar_mn END)\n"
        f"           AS outside_cohort_sar_mn,\n"
        f"       COUNT(*) AS book_rows\n"
        f"FROM {grain['relation']}\n"
        f"WHERE {grain['period']} = '{frozen.period}'")


def submission(spec: sp.ScenarioSpec, plan: dl.Plan, *,
               frozen: ch.Frozen) -> dict[str, object]:
    """The `execute_analysis` payload, ready for the analyst to send.

    A plain dict, built here and validated there: `contracts.parse_execution`
    remains the authority on what a submission is, and this module producing
    one that it rejects is a bug in this module. Nothing is bypassed.

    Two steps, deliberately independent. The ledger is the cohort's rows; the
    totals are the book's. Neither depends on the other, so a failure in one
    does not leave a half-computed result looking complete.
    """
    spec.require_confirmed()
    grain = ch.GRAIN[spec.source.domain_id]
    reads = sorted({column(f.field_id) for f in plan.factors} |
                   {"ecl_sar_mn", grain["key"], grain["period"]})
    return {
        "objective": (
            f"Scenario impact on ECL for {frozen.described_as or 'the cohort'}"
            f" at {frozen.period}: {'; '.join(plan.describe()) or 'no shock'}"),
        "subquestions": [
            "What is the baseline and scenario ECL for each entity?",
            "What does the whole book total, so the cohort's share is "
            "checkable?",
        ],
        "scope": {
            "domain_id": spec.source.domain_id,
            "release_id": spec.source.release_id,
            "reporting_period": frozen.period,
            "cohort_id": frozen.ref.cohort_id,
            "membership_hash": frozen.ref.membership_hash,
            "scenario_digest": spec.digest(),
        },
        "fields_required": reads,
        "expected_output_grain": "row",
        "expected_units": {
            "baseline_sar_mn": "SAR million",
            "scenario_sar_mn": "SAR million",
            DISPOSITION: "category",
        },
        "steps": [
            {"step_id": "scenario_ledger", "language": "sql",
             "purpose": ("Baseline and scenario ECL for every entity in the "
                         "frozen cohort, with the reason any row was not "
                         "moved. Full population, no sample."),
             "code": row_ledger_sql(spec, plan, frozen=frozen)},
            {"step_id": "book_totals", "language": "sql",
             "purpose": ("The book's total at this period, split into the "
                         "cohort and everything outside it, so the ledger's "
                         "identity can be checked against it."),
             "code": book_totals_sql(spec, frozen=frozen)},
        ],
    }


def reads_only_published(plan: dl.Plan, *, domain_id: str) -> bool:
    """True when no factor reads a DERIVED column.

    Not a refusal -- a derived CCF is legitimate and labelled. It exists so
    a preview can say which of its inputs were reconstructed rather than
    read, which section 3.3 requires and a reader deserves.
    """
    return all(fd.lookup(domain_id, f.field_id).availability == fd.PUBLISHED
               for f in plan.factors)


__all__ = ["COLUMN", "DISPOSITION", "book_totals_sql", "column",
           "disposition_sql", "factor_sql", "ineligible_sql", "literal",
           "moved_value", "multiplier_sql", "reads_only_published",
           "row_ledger_sql", "scenario_ecl_sql", "submission",
           "unaffected_sql"]

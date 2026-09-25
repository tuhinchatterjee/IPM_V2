"""What Delta can express, what it refuses, and what it will not pretend.

UNIT · NO MODEL. Arithmetic over a resolved scenario. No database, no
provider, not even a scripted one; the population run and its evidence live
in `test_whatif_sql.py`.

Section 10.1's rule is one line -- scale ECL by the product of the
parameters' ratios -- and almost everything here is about its edges:

* which rows a parameter's ECL actually depends on, so an unaffected row is
  unaffected by exactly zero rather than by a small amount;
* which rows it cannot move at all, with the measured reason attached;
* which fields it cannot express, refused by name rather than dropped
  quietly from the product;
* and the zero that has no ratio.

Covers the reachable parts of D06, D07, D08, E10, E11 and R02 of section 16.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import delta as dl
from backend.cockpit_v4.scenario import fields as fd
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario.errors import ScenarioError

D = Decimal


def shock(field_id: str, value: str, operation: str = un.RELATIVE,
          **over) -> sp.Shock:
    return sp.Shock(field_id=field_id,
                    amount=un.parse(value, operation,
                                    raw=f"{field_id} {value}"), **over)


def plan_for(*shocks: sp.Shock, domain_id: str = dom.CORPORATE,
             submode: str = sp.PROPORTIONAL) -> dl.Plan:
    spec = sp.ScenarioSpec(
        scenario_id="sc", version=1,
        source=sp.SourceRef(domain_id=domain_id, release_id="r",
                            release_fingerprint="0" * 16,
                            reporting_period="p"),
        cohort=sp.CohortRef(cohort_id="c", membership_hash="0" * 64,
                            grain="facility", entity_count=1),
        shocks=shocks, delta_submode=submode)
    return dl.plan(spec)


def corporate_row(**over) -> dict:
    body = {"ecl_sar_mn": D("100"), "pd_pit_12m": D("0.04"),
            "pd_lifetime": D("0.12"), "lgd_pct": D("45"),
            "ead_sar_mn": D("5000"), "drawn_sar_mn": D("4000"),
            "undrawn_sar_mn": D("2000"), "ccf": D("0.5"), "stage": D(1),
            "write_off_sar_mn": D("0")}
    body.update(over)
    return body


# ---- what a plan resolves to -------------------------------------------

def test_a_plan_carries_one_factor_per_parameter_the_reader_moved() -> None:
    plan = plan_for(shock("pd_pit_12m", "20"), shock("lgd_pct", "5"))
    assert plan.fields() == ("pd_pit_12m", "lgd_pct")
    assert plan.submode == sp.PROPORTIONAL


def test_a_factor_carries_the_column_s_own_storage() -> None:
    plan = plan_for(shock("pd_pit_12m", "20"), shock("lgd_pct", "5"))
    storages = {f.field_id: f.storage for f in plan.factors}
    assert storages["pd_pit_12m"] == un.FRACTION
    assert storages["lgd_pct"] == un.PERCENT


def test_the_elasticity_is_one_and_says_so() -> None:
    """Section 10.1's default, and exact rather than conventional: ECL is
    linear in each parameter, so the ratio IS the effect."""
    factor = plan_for(shock("pd_pit_12m", "20")).factors[0]
    assert factor.elasticity == dl.UNIT_ELASTICITY == D(1)
    assert "elasticity" not in factor.describe()


def test_a_declared_elasticity_appears_in_the_trace() -> None:
    """A run that used one must say so rather than leave a reader to assume
    the default."""
    base = plan_for(shock("pd_pit_12m", "20")).factors[0]
    declared = dl.Factor(field_id=base.field_id, shock=base.shock,
                         elasticity=D(2), storage=base.storage)
    assert "elasticity 2" in declared.describe()
    assert declared.contribution(D("0.04")) == D("1.2") ** 2


def test_a_fractional_elasticity_is_a_model_assumption_this_build_lacks(
) -> None:
    base = plan_for(shock("pd_pit_12m", "20")).factors[0]
    fractional = dl.Factor(field_id=base.field_id, shock=base.shock,
                           elasticity=D("1.4"), storage=base.storage)
    with pytest.raises(ScenarioError, match="declared model assumption"):
        fractional.contribution(D("0.04"))


# ---- what Delta refuses ------------------------------------------------

def test_a_field_the_book_does_not_carry_is_refused_by_name() -> None:
    with pytest.raises(ScenarioError, match="not in the retail book"):
        plan_for(shock("ccf", "20"), domain_id=dom.RETAIL)


def test_a_field_a_scenario_may_not_move_is_refused() -> None:
    with pytest.raises(ScenarioError, match="not something a scenario"):
        plan_for(shock("ecl_sar_mn", "20"))


def test_the_approved_limit_is_refused_rather_than_answered_with_zero(
) -> None:
    """It moves no published ECL input in either book, so a Delta run on it
    would report a change of zero -- a wrong answer, not a small one.

    The field dictionary is what refuses it, which is where that fact
    belongs: `limit_sar_mn` is not a Delta field in either book and the
    comment at its definition says why.
    """
    for domain_id in (dom.CORPORATE, dom.RETAIL):
        with pytest.raises(ScenarioError, match="not one of them"):
            plan_for(shock("limit_sar_mn", "-20"), domain_id=domain_id)


def test_a_refusal_names_only_fields_a_scenario_could_actually_ask_for(
) -> None:
    """`methods` defaults to both methods on every field, so a published but
    immutable column carries DELTA without a scenario ever being able to
    move it. Naming those in a refusal would send a reader to ask for
    something that will be refused again for a different reason.
    """
    with pytest.raises(ScenarioError) as caught:
        plan_for(shock("limit_sar_mn", "-20"))
    named = str(caught.value)
    for movable in ("pd_pit_12m", "lgd_pct", "ead_sar_mn", "ccf"):
        assert movable in named
    for immovable in ("ecl_sar_mn", "sector", "utilisation_pct",
                      "default_flag", "write_off_sar_mn"):
        assert immovable not in named, immovable


def test_a_delta_field_that_is_neither_parameter_nor_structural_is_caught(
) -> None:
    """A guard on the dictionary, not on the reader. Nothing reaches it
    today -- every mutable Delta field is a parameter or an exposure
    component -- and a future entry that is neither would otherwise be
    silently dropped from the product and reported as if it had applied.
    """
    for domain_id in (dom.CORPORATE, dom.RETAIL):
        movable = {f.field_id for f in fd.BY_DOMAIN[domain_id]
                   if f.mutable and sp.DELTA in f.methods
                   and f.availability != fd.ABSENT}
        handled = set(dl.PARAMETERS) | set(dl.STRUCTURAL[domain_id])
        assert movable <= handled, (
            f"{sorted(movable - handled)} are Delta fields in the "
            f"{domain_id} book that Delta has no way to apply")


def test_a_stage_move_is_not_a_delta_field() -> None:
    """Moving a facility between stages changes WHICH PD its ECL uses, which
    is not a ratio on the one it had. Method 3 can express it; Delta says
    so instead of scaling something."""
    assert sp.DELTA not in fd.lookup(dom.CORPORATE, "stage").methods
    with pytest.raises(ScenarioError, match="not one of them"):
        plan_for(shock("stage", "3", un.SET_TO))


def test_the_refusal_names_what_delta_does_handle() -> None:
    with pytest.raises(ScenarioError) as caught:
        plan_for(shock("stage", "3", un.SET_TO))
    for field_id in ("pd_pit_12m", "lgd_pct", "ead_sar_mn"):
        assert field_id in str(caught.value)


def test_a_structural_component_is_carried_not_multiplied_in() -> None:
    """Drawn and undrawn move EAD, and EAD moves ECL, but not by their own
    ratios. They are recorded as unhandled by the proportional mode rather
    than folded into the product as if they were parameters."""
    plan = plan_for(shock("undrawn_sar_mn", "20"))
    assert plan.factors == ()
    assert plan.unhandled == ("undrawn_sar_mn",)
    assert any("structural" in note for note in plan.notes)


# ---- the four dispositions ---------------------------------------------

def test_a_scaled_row_moves_by_the_ratio() -> None:
    got = dl.scale_row(plan_for(shock("pd_pit_12m", "20")), corporate_row())
    assert got.disposition == dl.SCALED
    assert got.multiplier == D("1.2")
    assert got.scenario_ecl == D("120")
    assert got.change == D("20")


def test_an_unaffected_row_moves_by_exactly_zero() -> None:
    """A Stage 2 facility under a 12-month PD shock. Its ECL uses the
    lifetime PD, so the shock does not reach it -- and the answer is zero,
    not nearly zero."""
    got = dl.scale_row(plan_for(shock("pd_pit_12m", "20")),
                       corporate_row(stage=D(2)))
    assert got.disposition == dl.UNAFFECTED
    assert got.change == D("0")
    assert got.scenario_ecl == got.baseline_ecl


def test_the_lifetime_pd_reaches_the_stages_that_use_it() -> None:
    plan = plan_for(shock("pd_lifetime", "20"))
    assert dl.scale_row(plan, corporate_row(stage=D(2))).disposition \
        == dl.SCALED
    assert dl.scale_row(plan, corporate_row(stage=D(1))).disposition \
        == dl.UNAFFECTED


def test_an_ineligible_row_keeps_its_baseline_and_carries_the_reason(
) -> None:
    got = dl.scale_row(plan_for(shock("pd_lifetime", "20")),
                       corporate_row(stage=D(3)))
    assert got.disposition == dl.INELIGIBLE
    assert got.scenario_ecl == got.baseline_ecl
    assert "exactly 1.0" in got.reason


def test_an_unsupported_row_keeps_its_baseline_too() -> None:
    got = dl.scale_row(plan_for(shock("pd_pit_12m", "5", un.SET_TO)),
                       corporate_row(pd_pit_12m=D("0"), ecl_sar_mn=D("0")))
    assert got.disposition == dl.UNSUPPORTED
    assert got.scenario_ecl == D("0")


@pytest.mark.parametrize("disposition", dl.DISPOSITIONS)
def test_every_disposition_is_reachable(disposition) -> None:
    """A vocabulary with an unreachable word in it is a vocabulary that has
    drifted from the code."""
    cases = {
        dl.SCALED: (shock("pd_pit_12m", "20"), corporate_row()),
        dl.UNAFFECTED: (shock("pd_pit_12m", "20"),
                        corporate_row(stage=D(2))),
        dl.INELIGIBLE: (shock("pd_lifetime", "20"),
                        corporate_row(stage=D(3))),
        dl.UNSUPPORTED: (shock("pd_pit_12m", "5", un.SET_TO),
                         corporate_row(pd_pit_12m=D("0"))),
    }
    move, row = cases[disposition]
    assert dl.scale_row(plan_for(move), row).disposition == disposition


def test_the_retail_write_off_floor_is_ineligible_with_its_reason() -> None:
    """On those accounts ECL is not a function of PD, LGD or EAD at all, so
    no proportional shock on any of the three is sound."""
    got = dl.scale_row(
        plan_for(shock("lgd_pct", "10"), domain_id=dom.RETAIL),
        {"ecl_sar_mn": D("50"), "lgd_pct": D("60"), "stage": D(3),
         "write_off_sar_mn": D("12")})
    assert got.disposition == dl.INELIGIBLE
    assert "written off" in got.reason


# ---- section 10.2, structural EAD --------------------------------------

def test_structural_ead_rebuilds_exposure_rather_than_scaling_it() -> None:
    row = corporate_row(drawn_sar_mn=D("80000"), undrawn_sar_mn=D("20000"),
                        ead_sar_mn=D("90000"))
    assert dl.structural_ead(row, domain_id=dom.CORPORATE,
                             moved={"ccf": D("0.6")}) == D("92000")


def test_structural_ead_on_retail_is_the_moved_balance() -> None:
    """Retail publishes no CCF and sets ead = balance outside Credit Card,
    whose 0.45 lives in the generator rather than in a column."""
    assert dl.structural_ead({"balance_sar_mn": D("300")},
                             domain_id=dom.RETAIL,
                             moved={"balance_sar_mn": D("330")}) == D("330")


def test_a_derived_ccf_is_undefined_where_there_is_nothing_to_convert(
) -> None:
    """`(ead - drawn) / undrawn` inverts EAD to 2.8e-14 on the 1,308
    facilities with zero undrawn, which is a number and not an answer."""
    assert dl.baseline_ccf(corporate_row(undrawn_sar_mn=D("0"))) is None
    assert dl.baseline_ccf(corporate_row(
        ead_sar_mn=D("5000"), drawn_sar_mn=D("4000"),
        undrawn_sar_mn=D("2000"))) == D("0.5")


def test_a_ccf_shock_excludes_the_facilities_with_no_undrawn() -> None:
    plan = plan_for(shock("ccf", "20"))
    got = dl.scale_row(plan, corporate_row(undrawn_sar_mn=D("0")))
    assert got.disposition == dl.INELIGIBLE
    assert "no undrawn commitment" in got.reason


# ---- guards ------------------------------------------------------------

def test_a_float_in_a_row_is_refused_rather_than_converted() -> None:
    """`Decimal(0.1)` is 0.1000000000000000055511151231257827, and a
    tolerance loose enough to absorb that is loose enough to absorb a real
    error."""
    with pytest.raises(un.UnitError, match="float"):
        dl.scale_row(plan_for(shock("pd_pit_12m", "20")),
                     corporate_row(pd_pit_12m=0.04))


def test_an_unknown_predicate_raises_rather_than_matching_nothing() -> None:
    """A predicate added to the SQL and not here would silently match no
    rows, and every row would look eligible."""
    factor = plan_for(shock("pd_pit_12m", "20")).factors[0]
    invented = dl.Factor(field_id=factor.field_id, shock=factor.shock,
                         excluded_when="region = 'Riyadh'",
                         storage=factor.storage)
    plan = dl.Plan(domain_id=dom.CORPORATE, submode=sp.PROPORTIONAL,
                   factors=(invented,))
    with pytest.raises(AssertionError, match="not one of this module"):
        dl.scale_row(plan, corporate_row())


def test_a_scenario_with_no_shocks_moves_nothing_and_says_unaffected(
) -> None:
    got = dl.scale_row(plan_for(), corporate_row())
    assert got.disposition == dl.UNAFFECTED
    assert got.change == D("0")


def test_two_factors_multiply_rather_than_add() -> None:
    got = dl.scale_row(plan_for(shock("pd_pit_12m", "20"),
                                shock("lgd_pct", "10")), corporate_row())
    assert got.multiplier == D("1.2") * D("1.1")
    assert got.scenario_ecl == D("132.00")
    assert got.scenario_ecl != D("130"), "first-order would be 130"

"""A rule list becomes an order and a set of groups, and the two differ.

UNIT throughout. No lake, no model, no provider call: everything here is
arithmetic over a `ScenarioSpec`, which is the point of keeping the compile
step separate from the SQL that runs it.

Section 5.2 asks for a typed rule list and a directed dependency graph, and
the graph is read two ways that pull opposite ways:

* `order()` flattens it, because a parent has to be applied before the child
  it moves;
* `groups()` does not, because section 13.2 forbids showing a macro move and
  the PD move it induced as two additive bars in one bridge.

The third thing tested here is the refusal. Section 5.2: *"Never silently
assume 'more specific wins'."* Two rules on one field over overlapping rows
produce a question with counts and amounts attached, not a resolution.

Covers the reachable parts of D03, D04, D05, C05, C06, C07 and E09, plus the
mutation the specification names by hand: a compound applied where an override
was meant.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import fields as fd
from backend.cockpit_v4.scenario import rules as ru
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario.errors import ScenarioError

# ---- fixtures ----------------------------------------------------------

def shock(field_id: str, value, operation: str = un.RELATIVE,
          **over) -> sp.Shock:
    body = {
        "field_id": field_id,
        "amount": un.parse(value, operation, raw=f"{field_id} {value}"),
        "origin": over.pop("origin", ""),
    }
    body.update(over)
    return sp.Shock(**body)


def spec_with(*shocks: sp.Shock, **over) -> sp.ScenarioSpec:
    body = {
        "scenario_id": "sc-1",
        "version": 1,
        "name": "Rule compilation",
        "source": sp.SourceRef(
            domain_id=dom.CORPORATE,
            release_id="v4-saudi-corporate-20q-v4",
            release_fingerprint="0" * 16,
            reporting_period="2026Q2"),
        "cohort": sp.CohortRef(
            cohort_id="co-1", membership_hash="a" * 64, grain="facility",
            entity_count=1370, baseline_ead="240000",
            baseline_ecl="19800"),
        "shocks": shocks,
    }
    body.update(over)
    return sp.ScenarioSpec(**body)


# ---- grouping: one intervention is one bar -----------------------------

def test_a_direct_shock_is_its_own_group() -> None:
    graph = ru.compile_rules(spec_with(shock("pd_pit_12m", "20")))
    assert len(graph.groups()) == 1
    assert graph.groups()[0].root.field_id == "pd_pit_12m"
    assert graph.groups()[0].induced == ()


def test_d03_a_parent_and_what_it_induced_are_one_group() -> None:
    """Section 13.2: *"Do not show the total macro effect and its own induced
    PD effect as two separate additive bars."*

    A reader told that unemployment contributed 40 and PD contributed 35 will
    add them to 75, and they were the same 40.
    """
    macro = shock("unemployment_rate", "2", un.ABSOLUTE_PP,
                  origin="unemployment up 2 points")
    induced = shock("pd_pit_12m", "18", derived_from="unemployment_rate",
                    mapping_version="mev-2026.1")
    graph = ru.compile_rules(spec_with(macro, induced))

    groups = graph.groups()
    assert len(groups) == 1, "a parent and its child are one intervention"
    assert groups[0].root is macro
    assert groups[0].induced == (induced,)
    assert groups[0].fields() == ("unemployment_rate", "pd_pit_12m")


def test_the_group_label_is_the_reader_s_own_clause() -> None:
    graph = ru.compile_rules(spec_with(
        shock("pd_pit_12m", "20", origin="raise PD by a fifth")))
    assert graph.groups()[0].label == "raise PD by a fifth"


def test_a_group_with_no_clause_falls_back_to_the_field() -> None:
    graph = ru.compile_rules(spec_with(shock("lgd_pct", "5")))
    assert graph.groups()[0].label == "lgd_pct"


def test_a_group_describes_what_it_moved_downstream() -> None:
    graph = ru.compile_rules(spec_with(
        shock("unemployment_rate", "2", un.ABSOLUTE_PP,
              origin="unemployment up 2 points"),
        shock("pd_pit_12m", "18", derived_from="unemployment_rate"),
        shock("lgd_pct", "3", un.ABSOLUTE_PP,
              derived_from="unemployment_rate")))
    said = graph.groups()[0].describe()
    assert "moves lgd_pct, pd_pit_12m" in said


def test_d04_an_orphan_derived_shock_is_attributed_not_dropped() -> None:
    """Something produced it, and the bridge has to put it somewhere.

    A derived shock whose parent is not in this scenario would otherwise
    vanish from the attribution while still moving the total -- which is a
    bridge that does not add up.
    """
    orphan = shock("pd_pit_12m", "10", derived_from="rating_current")
    graph = ru.compile_rules(spec_with(orphan))
    assert [g.root for g in graph.groups()] == [orphan]


def test_all_shocks_of_a_group_is_root_then_induced() -> None:
    root = shock("rating_current", "-1", un.NOTCHES)
    child = shock("pd_pit_12m", "12", derived_from="rating_current")
    group = ru.compile_rules(spec_with(root, child)).groups()[0]
    assert group.all_shocks() == (root, child)


def test_the_mutation_two_bars_for_one_cause_is_caught() -> None:
    """Mutation: flatten `groups()` so every shock is its own group.

    That is the double count section 13.2 names. This test fails under the
    mutation and passes on the correct code, which is the only thing that
    makes it a guard rather than a description.
    """
    graph = ru.compile_rules(spec_with(
        shock("unemployment_rate", "2", un.ABSOLUTE_PP),
        shock("pd_pit_12m", "18", derived_from="unemployment_rate")))
    assert len(graph.groups()) < len(graph.shocks)


# ---- ordering: causes before consequences ------------------------------

def test_d05_upstream_moves_are_applied_before_the_fields_they_move() -> None:
    graph = ru.compile_rules(spec_with(
        shock("ead_sar_mn", "5"),
        shock("pd_pit_12m", "20"),
        shock("rating_current", "-1", un.NOTCHES)))
    assert [s.field_id for s in graph.order()] == [
        "rating_current", "pd_pit_12m", "ead_sar_mn"]


def test_ccf_precedes_the_exposure_it_derives() -> None:
    graph = ru.compile_rules(spec_with(
        shock("ead_sar_mn", "1"), shock("ccf", "10")))
    assert [s.field_id for s in graph.order()] == ["ccf", "ead_sar_mn"]


def test_stage_changes_run_after_the_parameters_and_before_exposure() -> None:
    graph = ru.compile_rules(spec_with(
        shock("ead_sar_mn", "1"),
        shock("stage", "3", un.SET_TO),
        shock("lgd_pct", "2", un.ABSOLUTE_PP)))
    assert [s.field_id for s in graph.order()] == [
        "lgd_pct", "stage", "ead_sar_mn"]


def test_a_field_with_no_declared_stage_sits_between_parameters_and_stage(
) -> None:
    assert ru.STAGE_ORDER["lgd_pct"] < ru.DEFAULT_STAGE < ru.STAGE_ORDER[
        "stage"]
    graph = ru.compile_rules(spec_with(
        shock("stage", "2", un.SET_TO),
        shock("sector", "1", un.SET_TO),
        shock("lgd_pct", "1", un.ABSOLUTE_PP)))
    assert [s.field_id for s in graph.order()] == [
        "lgd_pct", "sector", "stage"]


def test_e09_the_order_is_canonical_not_whatever_the_set_iterated_as() -> None:
    """Section 14.2 wants a canonical rule order. Two rules in the same stage
    keep the reader's own authoring order, so a rerun traces identically."""
    first = shock("pd_pit_12m", "20", origin="first clause")
    second = shock("pd_lifetime", "20", origin="second clause")
    forwards = ru.compile_rules(spec_with(first, second)).order()
    backwards = ru.compile_rules(spec_with(second, first)).order()
    assert [s.origin for s in forwards] == ["first clause", "second clause"]
    assert [s.origin for s in backwards] == ["second clause", "first clause"]


def test_ordering_is_stable_under_repeated_compiles() -> None:
    spec = spec_with(shock("ead_sar_mn", "1"), shock("pd_pit_12m", "2"),
                     shock("rating_current", "-1", un.NOTCHES))
    once = [s.field_id for s in ru.compile_rules(spec).order()]
    for _ in range(5):
        assert [s.field_id for s in ru.compile_rules(spec).order()] == once


def test_the_graph_knows_which_fields_arrived_by_derivation() -> None:
    graph = ru.compile_rules(spec_with(
        shock("rating_current", "-1", un.NOTCHES),
        shock("pd_pit_12m", "12", derived_from="rating_current")))
    assert graph.is_derived("pd_pit_12m")
    assert not graph.is_derived("rating_current")


def test_the_ordering_table_is_not_a_back_door_into_absent_fields() -> None:
    """`STAGE_ORDER` names `unemployment_rate` because P5 will need it. That
    is an ordering hint and nothing else: the field dictionary still refuses
    a book that does not carry the column."""
    assert "unemployment_rate" in ru.STAGE_ORDER
    with pytest.raises(ScenarioError):
        fd.mutable(dom.CORPORATE, "unemployment_rate")


# ---- conflicts: a question, never a guess ------------------------------

def test_c05_compiling_an_unresolved_overlap_raises_the_question() -> None:
    """`order()` would happily sequence two rules on one field, and the
    sequence it picked would decide the answer. That is "more specific wins"
    arriving by the back door, so the compile refuses first."""
    with pytest.raises(ScenarioError, match="two rules move pd_pit_12m"):
        ru.compile_rules(spec_with(
            shock("pd_pit_12m", "20", origin="raise PD 20%"),
            shock("pd_pit_12m", "30", origin="raise PD 30%")))


def test_c05_an_overlap_the_reader_is_being_shown_does_not_block_the_graph(
) -> None:
    """A surfaced overlap is still unresolved -- the reader has not chosen a
    composition yet -- but the preview exists to put it to them with its
    counts and amounts, and it cannot do that if having one stops the graph
    being built. What the guard forbids is an overlap nobody saw."""
    spec = spec_with(shock("pd_pit_12m", "20", origin="raise PD 20%"),
                     shock("pd_pit_12m", "30", origin="raise PD 30%"))
    known = ru.overlaps(spec, counts={"pd_pit_12m": (412, "18,500.25")})
    graph = ru.compile_rules(spec, known=known)
    assert graph.overlaps == known
    assert graph.overlaps[0].composition == "", "surfaced, not resolved"


def test_acknowledging_one_overlap_does_not_excuse_another() -> None:
    spec = spec_with(
        shock("pd_pit_12m", "20"), shock("pd_pit_12m", "30"),
        shock("lgd_pct", "5", un.ABSOLUTE_PP),
        shock("lgd_pct", "9", un.ABSOLUTE_PP))
    pd_only = [o for o in ru.overlaps(spec) if o.field_id == "pd_pit_12m"]
    with pytest.raises(ScenarioError, match="two rules move lgd_pct"):
        ru.compile_rules(spec, known=tuple(pd_only))


def test_an_acknowledgement_survives_a_round_trip_through_json() -> None:
    """Matched by value, not by object identity, so a pair acknowledged
    before a spec was serialised is the same pair after it comes back."""
    spec = spec_with(shock("pd_pit_12m", "20", origin="raise PD 20%"),
                     shock("pd_pit_12m", "30", origin="raise PD 30%"))
    rebuilt = spec_with(*[
        shock(s.field_id, s.amount.value, s.amount.operation,
              origin=s.origin, where=dict(s.where))
        for s in spec.shocks])
    ru.compile_rules(rebuilt, known=ru.overlaps(spec))


def test_two_rules_on_different_fields_are_not_a_conflict() -> None:
    graph = ru.compile_rules(spec_with(
        shock("pd_pit_12m", "20"), shock("lgd_pct", "5", un.ABSOLUTE_PP)))
    assert len(graph.groups()) == 2


def test_a_derived_shock_does_not_conflict_with_the_rule_that_caused_it(
) -> None:
    ru.compile_rules(spec_with(
        shock("pd_pit_12m", "20", origin="raise PD 20%"),
        shock("pd_pit_12m", "5", derived_from="pd_pit_12m")))


def test_c06_an_overlap_carries_its_rows_and_its_baseline_ecl() -> None:
    """Section 5.2: *"Show overlap counts and amounts."* An overlap of four
    facilities and one of four thousand are different conversations."""
    spec = spec_with(shock("lgd_pct", "5", un.ABSOLUTE_PP,
                           origin="LGD up 5 points"),
                     shock("lgd_pct", "10", un.ABSOLUTE_PP,
                           origin="LGD up 10 points"))
    found = ru.overlaps(spec, counts={"lgd_pct": (412, "3,190.44")})
    assert len(found) == 1
    assert found[0].rows == 412
    assert "412" in found[0].question()
    assert "3,190.44 SAR million" in found[0].question()


def test_an_overlap_with_no_measurement_still_asks() -> None:
    spec = spec_with(shock("lgd_pct", "5", un.ABSOLUTE_PP),
                     shock("lgd_pct", "10", un.ABSOLUTE_PP))
    assert ru.overlaps(spec)[0].rows == 0
    assert ru.overlaps(spec)[0].question()


def test_c07_the_question_offers_exactly_the_three_compositions() -> None:
    spec = spec_with(shock("lgd_pct", "5", un.ABSOLUTE_PP),
                     shock("lgd_pct", "10", un.ABSOLUTE_PP))
    options = ru.overlaps(spec)[0].options()
    assert len(options) == 3
    assert "instead" in options[0] and "override" in options[0]
    assert "on top of" in options[1] and "compound" in options[1]
    assert "did not apply" in options[2] and "remainder" in options[2]


@pytest.mark.parametrize("composition", ru.COMPOSITIONS)
def test_a_declared_composition_is_recorded_as_declared(composition) -> None:
    spec = spec_with(shock("lgd_pct", "5", un.ABSOLUTE_PP),
                     shock("lgd_pct", "10", un.ABSOLUTE_PP))
    resolved = ru.resolve(ru.overlaps(spec)[0], composition)
    assert resolved.composition == composition
    assert resolved.field_id == "lgd_pct"


def test_more_specific_wins_is_not_a_composition_this_engine_has() -> None:
    spec = spec_with(shock("lgd_pct", "5", un.ABSOLUTE_PP),
                     shock("lgd_pct", "10", un.ABSOLUTE_PP))
    with pytest.raises(ScenarioError, match="is not a composition"):
        ru.resolve(ru.overlaps(spec)[0], "more_specific_wins")


def test_the_refusal_names_the_three_that_are() -> None:
    spec = spec_with(shock("lgd_pct", "5", un.ABSOLUTE_PP),
                     shock("lgd_pct", "10", un.ABSOLUTE_PP))
    with pytest.raises(ScenarioError) as caught:
        ru.resolve(ru.overlaps(spec)[0], "")
    for name in ru.COMPOSITIONS:
        assert name in str(caught.value)


def test_rules_scoped_to_different_values_of_one_key_do_not_overlap() -> None:
    spec = spec_with(
        shock("lgd_pct", "5", un.ABSOLUTE_PP, where={"sector": "Retail"}),
        shock("lgd_pct", "10", un.ABSOLUTE_PP,
              where={"sector": "Construction"}))
    assert ru.overlaps(spec) == ()
    assert len(ru.compile_rules(spec).groups()) == 2


# ---- duplicates: said twice, meant once --------------------------------

def test_d05_an_identical_instruction_repeated_is_applied_once() -> None:
    """Section 5.2: *"Duplicate identical instructions in the same revision
    must not be applied twice accidentally."* 20% twice is 1.20, not 1.44."""
    twice = (shock("pd_pit_12m", "20"), shock("pd_pit_12m", "20"))
    assert len(ru.deduplicate(twice)) == 1


def test_a_repeat_worded_differently_is_still_a_repeat() -> None:
    """The wording is audit material; only the arithmetic decides identity."""
    kept = ru.deduplicate((
        shock("pd_pit_12m", "20", origin="raise PD by 20%"),
        shock("pd_pit_12m", "20", origin="put PD up a fifth")))
    assert len(kept) == 1
    assert kept[0].origin == "raise PD by 20%", "the first wording survives"


def test_the_same_number_in_a_different_unit_is_not_a_duplicate() -> None:
    kept = ru.deduplicate((shock("lgd_pct", "20", un.RELATIVE),
                           shock("lgd_pct", "20", un.ABSOLUTE_PP)))
    assert len(kept) == 2


def test_the_same_rule_over_different_rows_is_not_a_duplicate() -> None:
    kept = ru.deduplicate((
        shock("lgd_pct", "5", un.ABSOLUTE_PP, where={"sector": "Retail"}),
        shock("lgd_pct", "5", un.ABSOLUTE_PP,
              where={"sector": "Construction"})))
    assert len(kept) == 2


def test_a_direct_shock_and_a_derived_one_that_match_are_both_kept() -> None:
    kept = ru.deduplicate((
        shock("pd_pit_12m", "20"),
        shock("pd_pit_12m", "20", derived_from="rating_current")))
    assert len(kept) == 2


def test_deduplication_keeps_the_reader_s_order() -> None:
    kept = ru.deduplicate((shock("lgd_pct", "5", un.ABSOLUTE_PP),
                           shock("pd_pit_12m", "20"),
                           shock("lgd_pct", "5", un.ABSOLUTE_PP)))
    assert [s.field_id for s in kept] == ["lgd_pct", "pd_pit_12m"]


# ---- walking one value -------------------------------------------------

def test_one_shock_over_one_baseline_is_the_unit_algebra() -> None:
    ordered = ru.compile_rules(spec_with(shock("pd_pit_12m", "20"))).order()
    moved = ru.apply_to_value(Decimal("0.04"), ordered,
                              domain_id=dom.CORPORATE, field_id="pd_pit_12m")
    assert moved == Decimal("0.048")


def test_a_percentage_point_move_lands_in_the_column_s_own_convention(
) -> None:
    """LGD is stored as a percent, PD as a fraction. `+5pp` has to mean five
    points of probability in both, which is 0.05 in one column and 5.0 in the
    other."""
    pd_ordered = ru.compile_rules(
        spec_with(shock("pd_pit_12m", "5", un.ABSOLUTE_PP))).order()
    lgd_ordered = ru.compile_rules(
        spec_with(shock("lgd_pct", "5", un.ABSOLUTE_PP))).order()
    assert ru.apply_to_value(Decimal("0.04"), pd_ordered,
                             domain_id=dom.CORPORATE,
                             field_id="pd_pit_12m") == Decimal("0.09")
    assert ru.apply_to_value(Decimal("45"), lgd_ordered,
                             domain_id=dom.CORPORATE,
                             field_id="lgd_pct") == Decimal("50")


def test_two_rules_on_one_field_compound_in_the_order_given() -> None:
    """Only reachable once a composition is declared -- `compile_rules`
    refuses the undeclared pair -- but the arithmetic is what `compound`
    means, and the oracles pin against it."""
    ordered = (shock("pd_pit_12m", "20"), shock("pd_pit_12m", "10"))
    assert ru.apply_to_value(Decimal("0.04"), ordered,
                             domain_id=dom.CORPORATE,
                             field_id="pd_pit_12m") == Decimal("0.0528")


def test_the_mutation_compound_where_override_was_meant_is_visible() -> None:
    """Override is the later rule alone: 0.04 -> 0.044. Compound is both:
    0.04 -> 0.0528. A run that reported the second for a reader who said
    "instead" would be 20% high, and these are different numbers."""
    both = (shock("pd_pit_12m", "20"), shock("pd_pit_12m", "10"))
    later_only = both[1:]
    compounded = ru.apply_to_value(Decimal("0.04"), both,
                                   domain_id=dom.CORPORATE,
                                   field_id="pd_pit_12m")
    overridden = ru.apply_to_value(Decimal("0.04"), later_only,
                                   domain_id=dom.CORPORATE,
                                   field_id="pd_pit_12m")
    assert overridden == Decimal("0.044")
    assert compounded != overridden


def test_shocks_on_other_fields_leave_this_one_alone() -> None:
    ordered = ru.compile_rules(spec_with(
        shock("pd_pit_12m", "20"),
        shock("lgd_pct", "10", un.ABSOLUTE_PP))).order()
    assert ru.apply_to_value(Decimal("0.04"), ordered,
                             domain_id=dom.CORPORATE,
                             field_id="pd_pit_12m") == Decimal("0.048")


def test_a_scenario_with_no_shocks_moves_nothing() -> None:
    graph = ru.compile_rules(spec_with())
    assert graph.order() == () and graph.groups() == ()
    assert ru.apply_to_value(Decimal("0.04"), graph.order(),
                             domain_id=dom.CORPORATE,
                             field_id="pd_pit_12m") == Decimal("0.04")


def test_rules_on_different_fields_commute() -> None:
    """A property, not an example: if two rules touch different columns, the
    order they were authored in cannot change either result."""
    forwards = ru.compile_rules(spec_with(
        shock("pd_pit_12m", "20"),
        shock("lgd_pct", "10", un.ABSOLUTE_PP))).order()
    backwards = ru.compile_rules(spec_with(
        shock("lgd_pct", "10", un.ABSOLUTE_PP),
        shock("pd_pit_12m", "20"))).order()
    for field_id, baseline in (("pd_pit_12m", Decimal("0.04")),
                               ("lgd_pct", Decimal("45"))):
        assert (ru.apply_to_value(baseline, forwards,
                                  domain_id=dom.CORPORATE, field_id=field_id)
                == ru.apply_to_value(baseline, backwards,
                                     domain_id=dom.CORPORATE,
                                     field_id=field_id))


def test_walking_a_field_the_book_does_not_carry_is_refused() -> None:
    ordered = (shock("unemployment_rate", "2", un.ABSOLUTE_PP),)
    with pytest.raises(ScenarioError):
        ru.apply_to_value(Decimal("6"), ordered, domain_id=dom.CORPORATE,
                          field_id="unemployment_rate")

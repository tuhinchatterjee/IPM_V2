"""
§13 — the canonical teaching cases.

    "Add at least 500 canonical complex teaching cases across the families
     above. Do not inflate counts with trivial one-word paraphrases."

The second sentence is what these tests are for. Producing five hundred rows
is easy; producing five hundred rows that each teach something a family could
not otherwise demonstrate is the work. So the tests check the count once and
then spend their time on the things that make a count worth having: no
duplicates, every family's obligation actually met, and — the one that matters
most — every blueprint recording what its question is usually got wrong.
"""

from __future__ import annotations

import pytest

from backend.teaching import families as fam
from backend.teaching import schema as sc
from backend.teaching import status as st
from intelligence_factory.teaching import canonical as cn
from intelligence_factory.teaching import migrate as mg


@pytest.fixture(scope="module")
def cases() -> list[sc.TeachingCase]:
    return cn.cases()


def _family(cases, family_id) -> list[sc.TeachingCase]:
    return [c for c in cases if c.family_id == family_id]


# ------------------------------------------------------------------ the bar


def test_the_corpus_reaches_section_13s_target(cases):
    assert len(cases) >= cn.TARGET


def test_every_case_validates(cases):
    broken = [(c.case_id, [str(p) for p in sc.validate(c)])
              for c in cases if sc.validate(c)]
    assert broken == []


def test_nothing_is_approved(cases):
    """Authoring is not review, however carefully the blueprint was written."""
    assert {sc.resolve_status(c) for c in cases} == {st.AUTO_VALIDATED}


def test_no_two_cases_teach_the_same_thing(cases):
    """A hash-based choice collides whenever a blueprint's combination space
    is smaller than the count asked for. Duplicates are exactly what §13 means
    by inflating the count, so the generator draws until it has distinct cases
    and reports a shortfall rather than padding."""
    fingerprints = [c.fingerprint for c in cases]
    assert len(fingerprints) == len(set(fingerprints))


def test_no_blueprint_falls_short_of_what_it_asked_for():
    """A family that cannot reach its target needs more shapes in its
    blueprint — a decision for a person, not a number to pad."""
    assert cn.report()["short_of_blueprint"] == {}


def test_the_corpus_is_the_same_on_every_run(cases):
    again = {c.case_id: c.fingerprint for c in cn.cases()}
    assert again == {c.case_id: c.fingerprint for c in cases}


# ------------------------------------------------------- what §13 counts by


def test_at_least_a_hundred_cases_are_multi_turn(cases):
    """§13's threshold, and the one migration could not meet: the Phase 0
    corpora hold nine multi-turn threads between them."""
    assert sum(1 for c in cases if c.turn_count() > 1) >= 100


def test_at_least_a_hundred_and_fifty_cases_are_demanding(cases):
    assert sum(1 for c in cases if c.difficulty in sc.DEMANDING) >= 150


def test_the_corpus_covers_the_families_migration_leaves_empty(cases):
    """The reason this module exists. Ten families had nothing at all after
    migration; another twenty had a handful."""
    covered = {c.family_id for c in cases}
    assert {"AS_OF_JOIN", "GRAIN_RECONCILIATION", "ROLL_RATE_AND_CURE",
            "VINTAGE_AND_COHORT", "RISK_APPETITE", "CONTRADICTORY_SIGNALS",
            "PREVIOUS_RESULT_REUSE", "AGENTIC_ORCHESTRATION",
            "CORPORATE_SCOPE", "RETAIL_SCOPE"} <= covered


def test_together_with_migration_every_available_family_has_cases():
    """The whole point of doing both. A family with no cases is a family whose
    obligation nothing in the library demonstrates."""
    covered = {c.family_id for c in [*mg.cases(), *cn.cases()]}
    missing = sorted(set(fam.AVAILABLE) - covered)
    assert missing == []


# ---------------------------------------------------------- the trap is the case


def test_every_case_records_what_its_question_is_usually_got_wrong(cases):
    """A case that only says what a right answer looks like cannot distinguish
    a right answer from a plausible substitute. A roll rate computed off two
    closing snapshots looks exactly like a roll rate."""
    for case in cases:
        forbidden = case.scope_contract.get("forbidden_behaviours") or []
        assert forbidden, case.case_id


def test_every_case_says_what_a_correct_answer_must_do(cases):
    for case in cases:
        assert case.conversation_turns
        assert all(t.expected_answer_behavior for t in case.conversation_turns)


def test_every_case_carries_more_than_one_objective_or_a_reason_not_to(cases):
    """A single-objective case cannot exercise coverage. The metadata families
    legitimately have one; everything else needs at least two."""
    single = {"DATA_DISCOVERY", "DATA_INSPECTION", "AMBIGUITY"}
    for case in cases:
        if case.family_id in single:
            continue
        assert len(case.objectives) >= 2, case.case_id


def test_no_case_carries_a_portfolio_figure(cases):
    """§8, enforced by the schema — but asserted here too, because a
    generator is exactly the thing that would introduce one everywhere at
    once."""
    assert all(c.data_sensitivity == st.PUBLIC for c in cases)
    assert all(not sc.validate(c) for c in cases)


# --------------------------------------------------- the families' obligations


def test_an_as_of_case_refuses_the_current_attribute(cases):
    """The failure the family exists for: joining today's rating onto last
    year's population, which returns a plausible table."""
    for case in _family(cases, "AS_OF_JOIN"):
        assert case.period_contract["as_of"] is True
        assert case.join_contracts[0]["kind"] == "as-of"
        assert "as_of_alignment" in case.invariants


def test_a_grain_case_aggregates_before_it_joins(cases):
    """Attaching a borrower attribute to facility rows and then summing
    multiplies the borrower's facilities into the total."""
    for case in _family(cases, "GRAIN_RECONCILIATION"):
        assert case.population_contract["aggregate_before_join"] is True
        assert "no_double_counting" in case.invariants
        assert "totals_tie" in case.invariants


def test_a_roll_rate_divides_by_the_opening_population(cases):
    """Dividing one closing bucket by another produces a number that looks
    like a roll rate and is not one."""
    for case in _family(cases, "ROLL_RATE_AND_CURE"):
        assert "opening population" in case.formula_contract["denominator"]
        assert "denominator_is_opening_population" in case.invariants


def test_a_vintage_case_fixes_its_cohort_at_origination(cases):
    """Re-forming the cohort each period measures the book, not the vintage."""
    for case in _family(cases, "VINTAGE_AND_COHORT"):
        assert case.population_contract["fixed_at_origination"] is True
        assert "cohort_membership_fixed" in case.invariants


def test_an_appetite_case_reports_the_limit_as_well_as_the_measure(cases):
    """Returning the measure without the limit answers a different
    question."""
    for case in _family(cases, "RISK_APPETITE"):
        assert "limit_stated" in case.invariants
        assert len(case.objectives) >= 3


def test_a_contradiction_case_reports_both_directions(cases):
    for case in _family(cases, "CONTRADICTORY_SIGNALS"):
        assert case.interpretation_contract["must_surface"] == \
            "both directions"
        assert "both_signals_reported" in case.invariants


def test_an_agentic_case_stops_at_its_approval_gate(cases):
    """The gate is the case. An agent that plans well and acts through a gate
    has failed in the way that matters."""
    for case in _family(cases, "AGENTIC_ORCHESTRATION"):
        assert case.forbidden_tools
        assert case.cost_budget > 0 and case.latency_budget > 0
        assert "approval_gate_respected" in case.invariants
        assert case.expected_officer_level == 4


def test_a_scope_case_speaks_its_own_vocabulary(cases):
    """A CORPORATE_SCOPE case that reports at account grain, or a RETAIL_SCOPE
    case that talks about covenants, teaches the substitution the family
    exists to prevent."""
    for case in _family(cases, "CORPORATE_SCOPE"):
        assert case.portfolio_scope == fam.CORPORATE
        assert case.grain == "obligor"
        assert case.industry_or_product_scope
    for case in _family(cases, "RETAIL_SCOPE"):
        assert case.portfolio_scope == fam.RETAIL
        assert case.grain == "account"
        assert "covenant" in str(case.scope_contract)


def test_a_reuse_case_does_not_recompute(cases):
    for case in _family(cases, "PREVIOUS_RESULT_REUSE"):
        assert case.turn_count() == 2
        second = case.conversation_turns[1]
        assert second.conversation_action == "ASSESS_PREVIOUS_RESULT"
        assert second.expected_plan_change["recompute"] is False


def test_a_presentation_case_changes_only_the_presentation(cases):
    for case in _family(cases, "PRESENTATION_MODIFICATION"):
        second = case.conversation_turns[1]
        assert second.conversation_action == "MODIFY_PRESENTATION"
        assert second.expected_presentation
        assert second.expected_plan_change["recompute"] is False


def test_a_multi_turn_case_records_what_the_second_turn_inherits(cases):
    """§9's `inherited_context` and `scope_delta`. Without them the case
    records that a follow-up happened but not what it was a follow-up to."""
    for case in _family(cases, "MULTI_TURN_REFERENTS"):
        second = case.conversation_turns[1]
        assert second.inherited_context
        assert second.scope_delta
        assert second.expected_referent_resolution


def test_the_multi_turn_blueprint_reaches_every_kind_of_follow_up(cases):
    """A conversation family whose forty cases all narrow teaches narrowing
    forty times."""
    actions = {c.conversation_turns[1].conversation_action
               for c in _family(cases, "MULTI_TURN_REFERENTS")}
    assert {"CONTINUE", "MODIFY_PREVIOUS", "WIDEN_SCOPE", "RESET_SCOPE"} <= \
        actions


def test_an_ambiguity_case_asks_one_question_and_computes_nothing(cases):
    for case in _family(cases, "AMBIGUITY"):
        assert case.expected_outcome == fam.CLARIFY
        assert case.clarification_contract["one_question_only"] is True
        assert "ANALYSIS" in case.scope_contract["forbidden_behaviours"]


def test_a_parameter_case_refuses_to_sum_a_parameter(cases):
    """The type error the ontology exists to refuse, as a case."""
    for case in _family(cases, "PD_LGD_EAD_ANALYSIS"):
        assert case.formula_contract["weighting"] == "exposure at default"
        assert "weighted_not_summed" in case.invariants
        assert "summing a parameter" in \
            case.scope_contract["forbidden_behaviours"]


# ------------------------------------------------------------- housekeeping


def test_every_case_names_a_dataset_the_lake_actually_holds(cases):
    """A case naming a dataset that does not exist teaches the planner to
    reach for it."""
    known = {cn.FACILITY, cn.IFRS9, cn.RATINGS, cn.TRANSITIONS,
             cn.DELINQUENCY, cn.PAYMENTS, cn.FINANCIALS, cn.COVENANTS,
             cn.COLLATERAL, cn.LIMITS, cn.APPETITE, cn.WATCHLIST,
             cn.RECOVERIES, cn.SCENARIOS, cn.GROUPS, cn.PROFITABILITY}
    for case in cases:
        assert set(case.required_datasets) <= known, case.case_id


def test_every_route_is_a_role_rather_than_a_provider_model(cases):
    """§23, at the point a corpus would embed a model ID across six hundred
    cases at once."""
    for case in cases:
        assert case.expected_model_route in sc.ROUTES


def test_difficulty_and_route_agree(cases):
    """A case marked EXPERT that routes to the routine model is describing a
    routing decision the product would not make."""
    for case in cases:
        expected = cn._ROUTE[case.difficulty]
        assert (case.expected_model_route, case.expected_effort) == expected


def test_case_ids_are_unique_and_readable(cases):
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids))
    assert all(c.case_id.startswith("can-") for c in cases)


def test_every_case_records_the_blueprint_it_came_from(cases):
    for case in cases:
        assert case.source_provenance.startswith("canonical:")
        assert case.tags[0] == "canonical"


def test_a_second_choice_is_never_the_first_one():
    """A cohort compared with itself is not a comparison."""
    for index in range(50):
        first = cn.pick(cn.SECTORS, f"s{index}", 1)
        assert cn._other(cn.SECTORS, first, f"s{index}", 2) != first

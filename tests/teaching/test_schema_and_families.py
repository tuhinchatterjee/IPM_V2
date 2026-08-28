"""
Part A §4-§11 — the governed TeachingCase, its families and its statuses.

What these tests are actually defending
---------------------------------------
Not that the dataclass has the right fields; that would be a spelling test. The
thing worth defending is that a case cannot look complete and teach nothing:
a SAME_TURN_COREFERENCE case with no antecedent, an AMBIGUITY case expected to
execute, a two-turn family with one turn, a structure-only case carrying last
quarter's ECL. Each of those parses. Each of them is a case somebody would
approve. Each of them makes the library worse than it was.
"""

from __future__ import annotations

import pytest

from backend.teaching import families as fam
from backend.teaching import schema as sc
from backend.teaching import status as st


def _case(**over) -> sc.TeachingCase:
    """A case that validates, so a test can break exactly one thing."""
    base = dict(
        case_id="tc-base", title="Total EAD by sector",
        family_id="SINGLE_DOMAIN_AGGREGATION",
        question="What is total EAD by sector in the latest quarter?",
        objectives=[sc.Objective(id="o1", text="total EAD by sector")],
        analytical_plan_contract={"group_by": ["sector"],
                                  "measure": "exposure_at_default"},
        concepts=["exposure at default"], operations=["SUM"],
    )
    base.update(over)
    return sc.TeachingCase(**base)


# --------------------------------------------------------------- the families


def test_every_family_section_7_names_is_declared():
    """§7 gives the list. A family missing from the module is a family no case
    can be filed under and no coverage report can show as empty."""
    required = {
        "DATA_DISCOVERY", "DATA_DICTIONARY", "DATA_RELATIONSHIPS",
        "DATA_INSPECTION", "SINGLE_DOMAIN_AGGREGATION",
        "FILTERING_AND_RANKING", "SAME_TURN_COREFERENCE",
        "MULTI_TURN_REFERENTS", "COMPOUND_OBJECTIVES", "COHORT_COMPARISON",
        "PERIOD_ALIGNMENT", "AS_OF_JOIN", "MULTI_DATASET_JOIN",
        "GRAIN_RECONCILIATION", "RATING_MIGRATION", "STAGE_MIGRATION",
        "DPD_MIGRATION", "ROLL_RATE_AND_CURE", "ECL_MOVEMENT",
        "ECL_CHANGE_DECOMPOSITION", "PD_LGD_EAD_ANALYSIS", "PORTFOLIO_MIX",
        "CONCENTRATION", "COVENANT_AND_COLLATERAL", "FINANCIAL_DETERIORATION",
        "EARLY_WARNING", "VINTAGE_AND_COHORT", "RISK_APPETITE",
        "STRESS_AND_SCENARIO", "BROAD_INVESTIGATION", "CONTRADICTORY_SIGNALS",
        "ASSOCIATION_NOT_CAUSATION", "PREVIOUS_RESULT_REUSE",
        "PRESENTATION_MODIFICATION", "VISUALIZATION_SELECTION", "AMBIGUITY",
        "UNSUPPORTED_DATA", "CONTROLLED_FAILURE", "AGENTIC_ORCHESTRATION",
        "TRACE_CONSISTENCY", "OBJECTIVE_COVERAGE", "CORPORATE_SCOPE",
        "RETAIL_SCOPE", "ARABIC_QUERY", "PROJECT_PLANNER_QUERY",
    }
    assert required <= set(fam.IDS)


def test_the_two_conditional_families_are_gated_rather_than_missing():
    """§7 names Arabic and Project Planner with conditions. Declaring them and
    marking them unavailable is the difference between 'we have not built it'
    and 'we forgot'."""
    assert set(fam.GATED) == {"ARABIC_QUERY", "PROJECT_PLANNER_QUERY"}
    for family_id in fam.GATED:
        assert fam.BY_ID[family_id].gated_on


def test_every_family_says_what_a_case_in_it_must_demonstrate():
    """A family whose description is its own name admits everything."""
    for family in fam.FAMILIES:
        assert len(family.teaches) > 30
        assert family.group in fam.GROUPS
        assert family.teaches.lower() != family.label.lower()


def test_every_legacy_curriculum_family_maps_somewhere():
    """§13 asks for the existing cases to be migrated, not rewritten. Every
    Phase 0 family needs a destination or the migration stalls on a judgment
    call repeated three hundred times."""
    for legacy, target in fam.LEGACY_FAMILIES.items():
        assert target in fam.BY_ID, f"{legacy} maps to an unknown family"
    assert fam.from_legacy("nothing like this") == ""


def test_the_legacy_map_still_matches_the_curriculum_it_maps_from():
    """The left-hand names are copied literals — the backend must not import
    the factory. A copy that silently drifts is worse than no copy."""
    from intelligence_factory import curriculum as cur

    assert set(cur.FAMILIES) == set(fam.LEGACY_FAMILIES)


# ---------------------------------------------------------------- the schema


def test_every_field_section_4_requires_exists_on_the_case():
    from dataclasses import fields as dataclass_fields

    declared = {f.name for f in dataclass_fields(sc.TeachingCase)}
    assert set(sc.REQUIRED_FIELDS) <= declared


def test_nothing_is_on_the_case_that_is_not_declared_somewhere():
    """The extensions are documented in EXTENSION_FIELDS with a reason. A field
    in neither list is one that arrived without anybody deciding to add it."""
    from dataclasses import fields as dataclass_fields

    declared = {f.name for f in dataclass_fields(sc.TeachingCase)}
    assert not (declared - set(sc.REQUIRED_FIELDS) - set(sc.EXTENSION_FIELDS))


def test_a_case_survives_a_round_trip_through_plain_data():
    """Storage is JSONB and the factory reads dictionaries. A case that cannot
    survive `to_dict` and back is one the library cannot hold."""
    case = _case(
        conversation_turns=[
            sc.Turn(turn_index=0, user_message="Show the five largest.",
                    conversation_action="NEW_REQUEST"),
            sc.Turn(turn_index=1, user_message="Only Contracting.",
                    conversation_action="MODIFY_PREVIOUS",
                    scope_delta={"narrowed": ["sector"]})],
        question="Show the five largest.",
        same_turn_discourse=sc.Discourse(cohorts={"c1": "the five largest"},
                                         referents={"them": "c1"}))
    again = sc.TeachingCase.from_dict(case.to_dict())
    assert again.to_dict() == case.to_dict()
    assert again.conversation_turns[1].scope_delta == {"narrowed": ["sector"]}
    assert again.same_turn_discourse.referents == {"them": "c1"}


def test_the_model_route_is_a_role_and_never_a_provider_model_id():
    """§23: the recommended models are configuration. A case naming
    'claude-opus-5' as its route would bake a provider ID into the library."""
    assert sc.validate(_case(expected_model_route="C_COMPLEX")) == []
    problems = sc.validate(_case(expected_model_route="claude-opus-5"))
    assert any(p.field == "expected_model_route" for p in problems)


def test_the_route_vocabulary_still_matches_the_router():
    from backend.orchestration import routing as rt

    assert set(sc.ROUTES) == set(rt.ROUTES)


# ------------------------------------------------------- the family's rules


def test_a_same_turn_case_with_no_antecedent_does_not_validate():
    """§10's whole point. Without a declared local cohort the case is an
    ordinary filter question wearing the family's name."""
    bare = _case(case_id="tc-st", family_id="SAME_TURN_COREFERENCE")
    assert any(p.field == "same_turn_discourse" for p in sc.validate(bare))

    bound = _case(case_id="tc-st", family_id="SAME_TURN_COREFERENCE",
                  same_turn_discourse=sc.Discourse(
                      cohorts={"matched": "customers matching all four "
                                          "conditions"},
                      referents={"them": "matched"}))
    assert sc.validate(bound) == []


def test_a_referent_pointing_at_an_undeclared_cohort_is_caught():
    loose = _case(same_turn_discourse=sc.Discourse(cohorts={"a": "x"},
                                                   referents={"them": "b"}))
    assert any(p.field == "same_turn_discourse" for p in sc.validate(loose))


@pytest.mark.parametrize("family_id", ["MULTI_TURN_REFERENTS",
                                       "PREVIOUS_RESULT_REUSE",
                                       "PRESENTATION_MODIFICATION"])
def test_a_conversation_family_needs_more_than_one_turn(family_id):
    """These three families are about what a second turn does with the first.
    One turn cannot demonstrate it."""
    one = _case(family_id=family_id)
    assert any(p.field == "conversation_turns" for p in sc.validate(one))


@pytest.mark.parametrize("family_id,outcome", [
    ("AMBIGUITY", fam.CLARIFY),
    ("UNSUPPORTED_DATA", fam.UNSUPPORTED),
    ("CONTROLLED_FAILURE", fam.FAIL),
])
def test_a_refusal_family_cannot_expect_to_execute(family_id, outcome):
    """An AMBIGUITY case expected to execute teaches the opposite of what the
    family exists for."""
    wrong = _case(family_id=family_id, expected_outcome=fam.EXECUTE)
    assert any(p.field == "expected_outcome" for p in sc.validate(wrong))


def test_a_scope_family_must_declare_its_scope():
    assert any(p.field == "portfolio_scope"
               for p in sc.validate(_case(family_id="CORPORATE_SCOPE")))
    ok = _case(family_id="CORPORATE_SCOPE", portfolio_scope=fam.CORPORATE)
    assert sc.validate(ok) == []


def test_a_clarifying_case_must_say_what_it_would_ask():
    """"Clarify" with no clarification recorded is an instruction to hesitate,
    not an example of how."""
    silent = _case(family_id="AMBIGUITY", expected_outcome=fam.CLARIFY)
    assert any(p.field == "clarification_contract" for p in sc.validate(silent))
    asked = _case(family_id="AMBIGUITY", expected_outcome=fam.CLARIFY,
                  clarification_contract={"ask": "Which exposure measure?"})
    assert sc.validate(asked) == []


def test_turn_indices_must_run_in_order():
    jumbled = _case(conversation_turns=[
        sc.Turn(turn_index=0, user_message="a"),
        sc.Turn(turn_index=5, user_message="b", conversation_action="CONTINUE")])
    assert any(p.field == "conversation_turns" for p in sc.validate(jumbled))


def test_a_later_turn_must_say_what_it_does_to_the_conversation():
    """§9's `conversation_action`. A follow-up with no action recorded is the
    case that teaches nothing about follow-ups."""
    silent = _case(conversation_turns=[
        sc.Turn(turn_index=0, user_message="a"),
        sc.Turn(turn_index=1, user_message="b")])
    assert any("conversation action" in p.detail for p in sc.validate(silent))


# --------------------------------------------- §8: structure, not last quarter


def test_a_structure_only_case_may_not_carry_a_portfolio_figure():
    """§8's own example: "Contracting ECL is 8,563." True for one quarter, and
    afterwards a model reciting a wrong number with confidence."""
    stale = _case(result_contract={"answer": "Contracting ECL is 8,563."})
    problems = sc.validate(stale)
    assert any(p.field == "result_contract" for p in problems)
    assert "8,563" in str(problems)


def test_a_diagnostic_case_may_carry_the_exact_value_it_validates():
    """§8's exception. A synthetic case proving a decomposition reconciles
    needs the figures, and they are reference data, not teaching material."""
    diagnostic = _case(data_sensitivity=st.DIAGNOSTIC,
                       result_contract={"answer": "total change 12,500"})
    assert sc.validate(diagnostic) == []


def test_a_year_is_a_period_and_not_a_portfolio_figure():
    """The check has to survive ordinary prose or authors will disable it."""
    prose = _case(description="Compares the latest quarter against 2024.")
    assert sc.validate(prose) == []


# ------------------------------------------------------------- fingerprints


def test_two_cases_teaching_the_same_thing_fingerprint_the_same():
    """§15's duplicate control. Different ids, different reviewers, different
    notes — the same lesson."""
    a = _case(case_id="tc-a", reviewer="Amal", notes="from the workshop",
              tags=["q3"])
    b = _case(case_id="tc-b", reviewer="Bilal", notes="", tags=[])
    assert sc.fingerprint(a) == sc.fingerprint(b)


def test_changing_what_a_case_teaches_changes_its_fingerprint():
    a = _case()
    b = _case(objectives=[sc.Objective(id="o1", text="average EAD by sector")])
    assert sc.fingerprint(a) != sc.fingerprint(b)


def test_a_declared_fingerprint_that_does_not_match_is_caught():
    """A fingerprint written by hand is a claim about content. An unchecked one
    lets a case be edited without its identity moving."""
    tampered = _case(fingerprint="0" * 32)
    assert any(p.field == "fingerprint" for p in sc.validate(tampered))


# ---------------------------------------------------------------- statuses


def test_only_approved_and_governed_system_validated_reach_a_live_prompt():
    for status in st.STATUSES:
        permitted = bool(st.retrievable(status))
        assert permitted == (status == st.APPROVED), status


def test_system_validated_is_off_until_somebody_governs_it_on():
    """§5 says "where explicitly governed". A default-on controlled status is
    not a controlled status."""
    assert not st.retrievable(st.SYSTEM_VALIDATED)
    assert st.retrievable(st.SYSTEM_VALIDATED, system_validated_enabled=True)


def test_client_data_is_never_retrievable_whatever_its_status():
    """§47. No approval redeems it, which is why the check runs before the
    status check rather than after it."""
    verdict = st.retrievable(st.APPROVED, sensitivity=st.CLIENT)
    assert not verdict and "client" in verdict.reason


def test_an_unknown_status_is_not_retrievable():
    """The same shape as the P0.16 assurance-ceiling defect: an unrecognised
    value must fail closed, not slip through the membership test."""
    assert not st.retrievable("VALIDATED")
    assert not st.retrievable("")


def test_a_validator_cannot_approve_anything():
    """§5: do not label LLM-generated cases human reviewed. AUTO_VALIDATED is
    a different word for a reason, and `resolve_status` can never return
    APPROVED however clean the case is."""
    assert sc.resolve_status(_case()) == st.AUTO_VALIDATED
    assert not st.may_approve(authoring_method=st.LLM_GENERATED,
                              reviewer="the validator",
                              reviewer_is_human=False)


def test_approval_needs_a_named_reviewer():
    assert not st.may_approve(authoring_method=st.HUMAN, reviewer="")
    assert st.may_approve(authoring_method=st.HUMAN, reviewer="Amal")


def test_retired_is_terminal():
    """Reviving a withdrawn case as a draft would let its history be rewritten
    under the same id. A new case costs nothing."""
    for status in st.STATUSES:
        assert not st.may_transition(st.RETIRED, status)


def test_an_approved_case_cannot_go_straight_back_to_draft():
    """Editing approved content in place is the thing versioning exists to
    prevent."""
    assert not st.may_transition(st.APPROVED, st.DRAFT)
    assert st.may_transition(st.APPROVED, st.SME_REVIEW_REQUIRED)


def test_a_stale_case_cannot_be_approved_without_being_revalidated():
    assert not st.may_transition(st.STALE, st.APPROVED)
    assert st.may_transition(st.STALE, st.AUTO_VALIDATED)


# ---------------------------------------------------------- §6 system-validated


def test_system_validation_requires_a_governed_source():
    assert not st.may_system_validate(source="a colleague told me",
                                      provenance="chat",
                                      deterministic_validation_passed=True)
    assert st.may_system_validate(source=st.CERTIFIED_METHOD,
                                  provenance="method:ecl_decomposition@1.2",
                                  deterministic_validation_passed=True)


def test_system_validation_cannot_rest_on_model_generated_gold():
    """§6: no hidden model-generated gold. The whole value of the status is
    that a deterministic contract, not a model, produced the expectation."""
    assert not st.may_system_validate(
        source=st.ENGINE_CONTRACT, provenance="engine:ecl@2",
        deterministic_validation_passed=True, model_generated_gold=True)


def test_a_holdout_source_can_never_be_system_validated():
    """The check that keeps the seal from becoming decoration: a case can name
    a legitimate source and still have been built from a sealed question."""
    verdict = st.may_system_validate(
        source=st.REVIEWED_TEST, provenance="tests/benchmark",
        deterministic_validation_passed=True, from_holdout=True)
    assert not verdict and "holdout" in verdict.reason


def test_the_exact_source_must_be_recorded():
    assert not st.may_system_validate(source=st.ENGINE_CONTRACT,
                                      provenance="",
                                      deterministic_validation_passed=True)


# ------------------------------------------------------------- staleness


def test_a_case_is_stale_on_every_axis_that_moved():
    case = _case(ontology_version="1.0.0", method_version="3.1")
    axes = st.stale_because(case.recorded_versions(),
                            {st.ONTOLOGY: "2.0.0", st.METHOD: "3.1"})
    assert axes == (st.ONTOLOGY,)


def test_a_version_the_case_never_recorded_counts_as_stale():
    """A blank is not evidence of agreement. The case with no recorded
    ontology version is precisely the one most likely to predate the ontology
    governing it now — the same failure shape as the assurance ceiling that
    ranked an unknown status as the weakest."""
    axes = st.stale_because(_case().recorded_versions(),
                            {st.ONTOLOGY: "2.0.0"})
    assert st.ONTOLOGY in axes


def test_an_axis_nobody_versions_yet_does_not_make_every_case_stale():
    """Declaring a new staleness axis must not retroactively invalidate the
    library."""
    assert st.stale_because(_case().recorded_versions(), {}) == ()


def test_the_staleness_axes_cover_what_section_5_names():
    assert set(st.STALENESS_AXES) == {
        "ontology", "method", "relationship", "dataset_contract",
        "planner_schema", "prompt_schema", "model_family"}


def test_every_recorded_version_maps_to_a_staleness_axis():
    """A version field with no axis is one nothing ever checks."""
    assert set(_case().recorded_versions()) == set(st.STALENESS_AXES)


# ------------------------------------------------------------ housekeeping


def test_a_variant_must_record_its_cluster():
    """§15: variants that cannot be clustered are variants that flood
    retrieval and straddle an evaluation split."""
    loose = _case(authoring_method=st.VARIANT)
    assert any(p.field == "cluster_id" for p in sc.validate(loose))


def test_a_dataset_cannot_be_required_and_forbidden_at_once():
    conflicted = _case(required_datasets=["ifrs9_staging"],
                       forbidden_datasets=["ifrs9_staging"])
    assert any(p.field == "forbidden_datasets" for p in sc.validate(conflicted))


def test_a_case_needs_a_question_or_a_thread():
    assert any(p.field == "question"
               for p in sc.validate(_case(question="")))


def test_the_question_must_match_the_first_turn():
    """Two records of what was asked drift, and the one retrieval reads is not
    always the one a reviewer read."""
    mismatched = _case(question="What is total EAD by sector?",
                       conversation_turns=[
                           sc.Turn(turn_index=0, user_message="Something "
                                                              "else.")])
    assert any(p.field == "question" for p in sc.validate(mismatched))


def test_an_unknown_family_does_not_validate():
    assert any(p.field == "family_id"
               for p in sc.validate(_case(family_id="MADE_UP")))


def test_an_executing_case_with_no_objectives_asks_for_review_not_rejection():
    """§14's rule generalised: a validator's doubt is a reason to ask
    somebody, not a reason to throw the case away."""
    thin = _case(objectives=[])
    problems = sc.validate(thin)
    assert problems and not any(p.fatal for p in problems)
    assert sc.resolve_status(thin) == st.SME_REVIEW_REQUIRED

"""
§13 — the existing corpus, in the governed schema.

Migration is the step where a large amount of reviewed work either arrives
intact or arrives subtly wrong in bulk. These tests are about the second: a
family assigned by the closest-sounding name, an outcome that contradicts the
family it was filed in, a refusal that lost the thing it was refusing.
"""

from __future__ import annotations

import pytest

from backend.teaching import families as fam
from backend.teaching import schema as sc
from backend.teaching import status as st
from intelligence_factory.teaching import migrate as mg


@pytest.fixture(scope="module")
def cases() -> list[sc.TeachingCase]:
    return mg.cases()


@pytest.fixture(scope="module")
def by_id(cases) -> dict[str, sc.TeachingCase]:
    return {c.case_id: c for c in cases}


# --------------------------------------------------------------- wholesale


def test_every_migrated_case_validates(cases):
    """The one that matters. A migration that lands a thousand cases in DRAFT
    has moved the work without moving it anywhere useful."""
    broken = [(c.case_id, [str(p) for p in sc.validate(c)])
              for c in cases if sc.validate(c)]
    assert broken == []


def test_migration_approves_nothing(cases):
    """§5. A review given for the Phase 0 curriculum is not a review of a
    teaching case; the schema, the family rules and the retrieval consequences
    are all different."""
    assert {sc.resolve_status(c) for c in cases} == {st.AUTO_VALIDATED}
    assert all(c.review_status == st.DRAFT for c in cases)
    assert all(not c.reviewer for c in cases)


def test_every_case_records_where_it_came_from(cases):
    """§6 and §47 both turn on provenance. A case with no source is one nobody
    can decide anything about later."""
    for case in cases:
        assert case.source_provenance
        assert case.source_provenance.split(":")[0] in mg.SOURCES
        assert case.tags and case.tags[0] in mg.SOURCES


def test_nothing_migrated_carries_client_data(cases):
    """Every source is synthetic or contractual. If this ever fails, the case
    is not the problem — the source is."""
    assert {c.data_sensitivity for c in cases} == {st.PUBLIC}


def test_every_case_is_filed_in_a_real_family(cases):
    for case in cases:
        family = fam.get(case.family_id)
        assert family is not None, case.case_id
        assert family.available, f"{case.case_id} filed in a gated family"


def test_case_ids_are_unique(cases):
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids))


def test_the_corpus_is_the_same_on_every_run(cases):
    """A corpus that reshuffles between runs produces scores that cannot be
    compared, which is the whole reason the generators are hash-seeded."""
    again = {c.case_id: c.fingerprint for c in mg.cases()}
    assert again == {c.case_id: c.fingerprint for c in cases}


def test_the_declared_fingerprint_matches_the_content(cases):
    for case in cases:
        assert case.fingerprint == sc.fingerprint(case)


# ---------------------------------------------------------------- families


def test_migration_reaches_most_of_the_governed_families(cases):
    """Not all of them — §13 asks for canonical authoring on top, and the
    families migration cannot reach are exactly the ones that authoring has to
    cover. The number is asserted so that gap stays visible."""
    touched = {c.family_id for c in cases}
    assert len(touched) >= 30
    assert {"SAME_TURN_COREFERENCE", "COMPOUND_OBJECTIVES",
            "ECL_CHANGE_DECOMPOSITION", "BROAD_INVESTIGATION",
            "UNSUPPORTED_DATA", "CONTROLLED_FAILURE"} <= touched


def test_an_executing_case_is_not_filed_under_ambiguity(by_id):
    """Phase 0's "ambiguity" family holds both halves of a pair. Only the half
    that clarifies is an AMBIGUITY case under §7; filing the other half there
    would put a case saying "do not compute this" in front of a model whose
    whole lesson is that it should be computed."""
    clarifies = by_id["mig-cur-cur-amb-1"]
    answers = by_id["mig-cur-cur-amb-2"]
    assert clarifies.family_id == "AMBIGUITY"
    assert clarifies.expected_outcome == fam.CLARIFY
    assert answers.family_id != "AMBIGUITY"
    assert answers.expected_outcome == fam.EXECUTE


def test_refiling_leaves_a_family_with_no_outcome_rule_alone():
    assert mg.refile("SINGLE_DOMAIN_AGGREGATION", outcome=fam.CLARIFY,
                     capability="ANALYSIS") == "SINGLE_DOMAIN_AGGREGATION"


def test_a_metadata_question_refiles_to_the_dictionary():
    assert mg.refile("AMBIGUITY", outcome=fam.EXECUTE,
                     capability="DATA_DICTIONARY") == "DATA_DICTIONARY"


# ------------------------------------------------------- the family's rules


def test_every_same_turn_case_carries_a_bound_antecedent(cases):
    """§10. These cases exist for local reference, and one without a declared
    cohort is an ordinary filter question wearing the family's name."""
    local = [c for c in cases if c.family_id == "SAME_TURN_COREFERENCE"]
    assert len(local) >= 150
    for case in local:
        assert case.same_turn_discourse.bound(), case.case_id


def test_every_decomposition_case_carries_section_11s_objectives(cases):
    """§11 lists eleven. A decomposition case that records one objective
    cannot fail the coverage validator, which makes it useless for the thing
    it is meant to teach."""
    decomposition = [c for c in cases
                     if c.family_id == "ECL_CHANGE_DECOMPOSITION"]
    assert decomposition
    for case in decomposition:
        assert len(case.objectives) >= 11, case.case_id
        assert "components_reconcile" in case.invariants
        assert case.method_contract["order_neutral"] is True


def test_every_multi_clause_case_records_more_than_one_objective(cases):
    """A compound case with one objective cannot fail the coverage validator,
    which is the only thing the family exists to exercise. Two is the floor —
    a genuinely two-clause question is a compound question — and the generated
    three-clause corpus is checked separately below."""
    compound = [c for c in cases if c.family_id == "COMPOUND_OBJECTIVES"]
    assert compound
    for case in compound:
        assert len(case.objectives) >= 2, case.case_id


def test_the_generated_multi_clause_corpus_records_all_three_clauses(cases):
    """Its template builds three: a total, a ranking, and the largest movers.
    Answering two of them and stopping is the exact failure §21 forbids."""
    generated = [c for c in cases
                 if c.family_id == "COMPOUND_OBJECTIVES"
                 and c.source_provenance.startswith("complex:")]
    assert len(generated) >= 150
    assert all(len(c.objectives) >= 3 for c in generated)


def test_a_controlled_failure_case_expects_to_fail(cases):
    failures = [c for c in cases if c.family_id == "CONTROLLED_FAILURE"]
    assert failures
    for case in failures:
        assert case.expected_outcome == fam.FAIL
        assert "reduced answer" in str(case.result_contract)


def test_an_unsupported_case_says_what_it_declines_and_why(cases):
    refusals = [c for c in cases if c.family_id == "UNSUPPORTED_DATA"]
    assert refusals
    for case in refusals:
        assert case.abstention_contract.get("declines")
        assert case.abstention_contract.get("because")


def test_a_thread_that_clarifies_then_executes_is_an_executing_thread(by_id):
    """The outcome of a thread is its last turn's. Taking the first turn's
    would file every repair case under CLARIFY and leave the family that is
    about repair empty."""
    repair = by_id["mig-cur-cur-inc-1"]
    assert repair.expected_outcome == fam.EXECUTE
    assert repair.turn_count() == 2


# ------------------------------------------------------------- the periods


def test_a_period_is_kept_as_a_phrase_rather_than_resolved(by_id):
    """§8's rule applied to periods: a resolved date range teaches a range
    that stops being 'latest' next quarter."""
    case = by_id["mig-cur-cur-simple-1"]
    assert case.conversation_turns[0].expected_reading["period"] == {
        "phrase": "latest", "basis": "as stated"}


# ------------------------------------------------- the certified methods


def test_only_certified_methods_are_derived():
    """§6 admits certified Analysis Studio methods as a system-validation
    source. A preconfigured method is a definition somebody wrote, and the
    difference is exactly what certification is."""
    from backend.studio import library as lib
    from backend.studio.model import Lifecycle

    certified = {m.id for m in lib.all_definitions()
                 if m.lifecycle == Lifecycle.CERTIFIED}
    derived = mg.from_certified_methods()
    assert derived
    for case in derived:
        method_id = case.source_provenance.split(":")[1].split("@")[0]
        assert method_id in certified


def test_a_derived_case_names_the_method_it_rests_on():
    for case in mg.from_certified_methods():
        assert case.authoring_method == st.DERIVED
        assert case.source_provenance.startswith("studio:")


def test_a_derived_case_could_be_system_validated():
    """The point of deriving them. Not that they ARE system validated —
    §6 needs a deterministic validation to have passed as well — but that
    nothing about the case blocks it."""
    case = mg.from_certified_methods()[0]
    assert st.may_system_validate(
        source=st.CERTIFIED_METHOD, provenance=case.source_provenance,
        deterministic_validation_passed=True,
        sensitivity=case.data_sensitivity)


def test_a_definition_case_forbids_running_an_analysis():
    """The metadata failure the dictionary family exists for: answering "what
    does LTV mean" with a number."""
    definitions = [c for c in mg.from_certified_methods()
                   if c.family_id == "DATA_DICTIONARY"]
    assert definitions
    for case in definitions:
        assert case.scope_contract["forbidden_behaviours"] == ["ANALYSIS"]
        assert case.expected_capability == "DATA_DICTIONARY"


@pytest.mark.parametrize("name,expected", [
    ("stage_migration_matrix", "STAGE_MIGRATION"),
    ("rating_migration_matrix", "RATING_MIGRATION"),
    ("dpd_bucket_migration", "DPD_MIGRATION"),
    ("roll_rate_30_to_60", "ROLL_RATE_AND_CURE"),
    ("ecl_change_decomposition", "ECL_CHANGE_DECOMPOSITION"),
    ("obligor_concentration", "CONCENTRATION"),
    ("vintage_loss_curve", "VINTAGE_AND_COHORT"),
    ("covenant_headroom", "COVENANT_AND_COLLATERAL"),
    ("stress_ecl_uplift", "STRESS_AND_SCENARIO"),
    ("total_ead", "SINGLE_DOMAIN_AGGREGATION"),
])
def test_a_method_is_filed_by_what_its_name_says_it_does(name, expected):
    """Filing by category alone puts "stage migration" under IFRS 9 and
    "rating migration" under Ratings, which are two names for one lesson."""

    class _Method:
        id = name
        category = "IFRS 9 / Impairment"

    _Method.name = name.replace("_", " ")
    assert mg.family_for_method(_Method()) == expected


# ------------------------------------------------------------- clustering


def test_variants_of_one_question_share_a_cluster():
    """§15. Word order and stop words must not split a cluster, or the
    duplicate control they exist for never fires."""
    from intelligence_factory.teaching.migrate import _cluster

    assert _cluster("What is total EAD by sector in Q1?") == \
        _cluster("By sector, what is the total EAD for Q1?")
    assert _cluster("What is total EAD by sector?") != \
        _cluster("What is average DSCR by sector?")


def test_the_corpus_is_not_one_giant_cluster(cases):
    """A clustering that puts everything together would silently cap retrieval
    at one case — §17 allows at most one case per cluster."""
    clusters = {c.cluster_id for c in cases}
    assert len(clusters) > len(cases) * 0.75


# --------------------------------------------------------------- reporting


def test_the_report_counts_by_family_rather_than_by_total():
    """§13: report quality by family, not merely total count."""
    found = mg.report()
    assert found["total"] > 1000
    assert found["by_source"].keys() <= set(mg.SOURCES)
    assert len(found["by_family"]) >= 30
    assert found["problems"] == {}

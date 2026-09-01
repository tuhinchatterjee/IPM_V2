"""The corpus has to hold its own contract before it can measure anything."""

from __future__ import annotations

import re

import pytest

from backend.brain import corpus, holdout, variants, vocabulary
from backend.brain.cases import (
    FAMILIES,
    MINIMUM_CANONICAL,
    MINIMUM_HOLDOUT,
    RETRIEVABLE,
    STATUSES,
    TUNABLE,
    validate,
)
from backend.data_access.catalog import get_catalog


@pytest.fixture(scope="module")
def canonical():
    return corpus.build()


@pytest.fixture(scope="module")
def generated(canonical):
    return variants.build(canonical)


@pytest.fixture(scope="module")
def sealed():
    return holdout.build()


# ------------------------------------------------------------- the vocabulary


def test_every_named_field_exists_in_the_governed_catalogue():
    catalogue = get_catalog()
    for measure in vocabulary.MEASURES:
        dataset = catalogue.dataset(measure.dataset)
        fields = dataset.fields
        names = (set(fields) if hasattr(fields, "keys")
                 else {f.name for f in fields})
        assert measure.field in names, (
            f"{measure.dataset}.{measure.field} is in the training "
            "vocabulary but not in the catalogue")


def test_every_dataset_can_carry_at_least_one_question():
    """A governed dataset the corpus cannot compose over is one it skips.

    An EVENT dataset is the one honest exception: a log of things that
    happened carries a category, a severity and a date and nothing to sum, so
    a question over it counts rows or filters them. That exemption is a named
    list rather than an inference — "this dataset has no measure" and
    "somebody forgot to register its measures" look identical from outside,
    and only one of them is acceptable.
    """
    for dataset in vocabulary.DATASETS:
        if dataset in vocabulary.EVENT_DATASETS:
            assert not vocabulary.measures_for(dataset), (
                f"{dataset} is listed as an event log but now carries a "
                "measure; take it off the exemption list")
            assert vocabulary.dimensions_for(dataset), (
                f"{dataset} has neither a measure nor a dimension, so no "
                "question at all can be composed over it")
            continue
        assert vocabulary.measures_for(dataset), (
            f"{dataset} has no measure, so no case can be composed over it "
            "and the corpus would silently skip a governed dataset")
        assert vocabulary.dimensions_for(dataset)


# ------------------------------------------------------------ the corpus size


def test_the_canonical_corpus_meets_every_family_floor(canonical):
    tally = {family: 0 for family in FAMILIES}
    for case in canonical:
        tally[case.case_family] += 1
    for family, floor in FAMILIES.items():
        assert tally[family] >= floor, (
            f"{family} has {tally[family]} canonical cases, floor {floor}")
    assert len(canonical) >= MINIMUM_CANONICAL


def test_no_variant_is_counted_toward_the_canonical_floor(canonical):
    assert all(case.canonical for case in canonical)
    assert all(not case.variant_of for case in canonical)


def test_no_two_canonical_cases_assert_the_same_thing(canonical):
    seen: dict[str, str] = {}
    for case in canonical:
        assert case.fingerprint not in seen, (
            f"{case.case_id} and {seen[case.fingerprint]} are the same case")
        seen[case.fingerprint] = case.case_id


def test_the_corpus_is_deterministic():
    first = [c.case_id for c in corpus.build()]
    second = [c.case_id for c in corpus.build()]
    assert first == second


# --------------------------------------------------------- what a case may say


def test_no_case_stores_a_portfolio_figure(canonical, sealed):
    money = re.compile(
        r"\d[\d,.]*\s*(million|billion|bn|mn|SAR|USD)\b", re.IGNORECASE)
    for case in [*canonical, *sealed]:
        for text in (case.expected_result_shape,
                     case.expected_answer_contract,
                     case.expected_population,
                     *case.objectives):
            assert not money.search(text or ""), (
                f"{case.case_id} stores a figure in its expectation; a "
                "stored number is right for one quarter and wrong after it")


def test_every_case_says_what_a_wrong_answer_would_look_like(
        canonical, sealed):
    for case in [*canonical, *sealed]:
        assert case.forbidden, (
            f"{case.case_id} has no forbidden behaviour, so it cannot tell "
            "a right answer from a convincing substitute")


def test_every_case_can_be_settled_without_asking_a_model(canonical, sealed):
    for case in [*canonical, *sealed]:
        assert case.reference.independent, (
            f"{case.case_id} has no independent reference spec")


def test_every_case_validates(canonical, sealed):
    for case in [*canonical, *sealed]:
        assert validate(case) == [], f"{case.case_id}: {validate(case)}"


# ------------------------------------------------- semantics of the questions


def test_a_rate_is_never_summed_across_rows(canonical):
    for case in canonical:
        if case.case_family != "SINGLE_DOMAIN":
            continue
        kind = case.expected_plan_properties.get("measure_kind")
        if kind in ("rate", "ratio"):
            assert "sum" not in case.expected_operations, (
                f"{case.case_id} sums {kind} {case.question!r}, which has "
                "no meaning added across rows")


def test_a_weighted_measure_names_what_it_is_weighted_by(canonical):
    for case in canonical:
        if "weighted_mean" not in case.expected_operations:
            continue
        weight = case.expected_plan_properties.get("weight_field")
        assert weight, f"{case.case_id} weights by nothing in particular"
        assert any("weighted by" in inv for inv in case.required_invariants)


def test_no_case_asks_a_dataset_without_a_period_how_it_moved(canonical):
    for case in canonical:
        if "over the last four quarters" not in case.question:
            continue
        for dataset in case.expected_datasets:
            assert dataset in vocabulary.PERIODIC, (
                f"{case.case_id} asks {dataset} for a history it does not "
                "have")


def test_a_fan_out_join_forbids_the_unaggregated_join(canonical):
    checked = 0
    for case in canonical:
        cardinality = case.expected_plan_properties.get("join_cardinality")
        if cardinality in ("many_to_one", "many_to_many", "one_to_many"):
            checked += 1
            assert any("without first aggregating" in f
                       for f in case.forbidden), (
                f"{case.case_id} traverses a {cardinality} edge without "
                "forbidding the join that multiplies the book")
    assert checked > 0


def test_a_clarification_and_an_abstention_are_never_both_expected(
        canonical, sealed):
    for case in [*canonical, *sealed]:
        assert not (case.expected_clarification and case.expected_abstention)


def test_every_security_case_is_critical_and_expects_a_refusal(canonical):
    security = [c for c in canonical if c.case_family == "SECURITY"]
    assert len(security) >= FAMILIES["SECURITY"]
    for case in security:
        assert case.criticality == "critical"
        assert case.expected_abstention


def test_every_expected_agent_is_registered(canonical, sealed):
    for case in [*canonical, *sealed]:
        for agent in case.expected_agents:
            assert agent in vocabulary.AGENTS, (
                f"{case.case_id} expects unregistered agent {agent!r}")


def test_every_expected_dataset_is_governed(canonical, sealed):
    for case in [*canonical, *sealed]:
        for dataset in case.expected_datasets:
            assert dataset in vocabulary.DATASETS


# ------------------------------------------------------------------- variants


def test_every_eligible_case_gets_between_three_and_six_variants(canonical):
    for case in canonical:
        made = variants.variants_for(case)
        if not variants.eligible(case):
            assert made == []
            continue
        assert variants.MIN_VARIANTS <= len(made) <= variants.MAX_VARIANTS


def test_a_variant_never_leaves_its_parents_cluster(canonical, generated):
    parents = {c.case_id: c for c in canonical}
    for variant in generated:
        assert variant.cluster == parents[variant.variant_of].cluster, (
            f"{variant.case_id} left its cluster, which is exactly how a "
            "variant leaks across the holdout boundary")


def test_a_variant_never_counts_as_canonical(generated):
    assert all(not v.canonical for v in generated)
    assert all(v.case_type == "variant" for v in generated)


def test_a_variant_never_changes_a_governed_term(canonical, generated):
    parents = {c.case_id: c for c in canonical}
    protected = re.compile(
        r"\b(IFRS|SICR|ECL|PD|LGD|EAD|DPD|RAROC|SAMA|BCBS|Basel|Stage|"
        r"Scope|FY\d\d|\d+)\b")
    for variant in generated:
        original = parents[variant.variant_of].question
        assert sorted(t.lower() for t in protected.findall(original)) == \
            sorted(t.lower() for t in protected.findall(variant.question)), (
            f"{variant.case_id} changed a governed term, so it is a "
            "different question wearing its parent's expectations")


def test_a_variant_inherits_every_expectation(canonical, generated):
    parents = {c.case_id: c for c in canonical}
    for variant in generated:
        parent = parents[variant.variant_of]
        assert variant.expected_capability == parent.expected_capability
        assert variant.expected_officer_level == parent.expected_officer_level
        assert variant.expected_datasets == parent.expected_datasets
        assert variant.forbidden == parent.forbidden


def test_variants_are_deterministic(canonical):
    case = canonical[0]
    assert ([v.question for v in variants.variants_for(case)]
            == [v.question for v in variants.variants_for(case)])


# -------------------------------------------------------------- the holdout


def test_the_holdout_meets_its_floor_and_covers_every_family(sealed):
    assert len(sealed) >= MINIMUM_HOLDOUT
    assert {c.case_family for c in sealed} == set(FAMILIES)


def test_every_holdout_case_is_sealed(sealed):
    for case in sealed:
        assert holdout.sealed(case)
        assert case.cluster.startswith(holdout.SEAL)


def test_the_holdout_is_isolated_from_everything_trainable(
        canonical, generated, sealed):
    holdout.assert_isolated([*canonical, *generated], sealed)


def test_no_holdout_cluster_is_a_training_cluster(canonical, sealed):
    training = {c.cluster for c in canonical}
    assert not training & {c.cluster for c in sealed}


def test_the_holdout_uses_shapes_the_training_corpus_does_not(
        canonical, sealed):
    """Disjoint fingerprints are the floor. A holdout that reused the
    training shapes would measure memorisation of those shapes."""
    trained = {c.question.strip().lower() for c in canonical}
    for case in sealed:
        assert case.question.strip().lower() not in trained


def test_a_holdout_case_is_never_claimed_to_be_human_approved(sealed):
    for case in sealed:
        assert case.status in STATUSES
        assert case.status != "HUMAN_APPROVED", (
            f"{case.case_id} claims a human review that did not happen")


# --------------------------------------------------------- status governance


def test_only_human_approved_is_freely_retrievable():
    freely = [s for s, policy in RETRIEVABLE.items() if policy == "yes"]
    assert freely == ["HUMAN_APPROVED"]


def test_system_reference_validated_is_retrievable_only_under_policy():
    policy = RETRIEVABLE["SYSTEM_REFERENCE_VALIDATED"]
    assert policy and "Administrator policy" in policy and "labelled" in policy


def test_an_unvalidated_case_may_never_tune_anything():
    assert "AUTO_GENERATED" not in TUNABLE
    assert "AUTO_VALIDATED" not in TUNABLE

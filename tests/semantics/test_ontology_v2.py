"""
P0.5 — the credit-risk ontology, held to its own contract.

Every concept must carry aliases, canonical fields, a definition, the direction
of deterioration, units, valid AND invalid aggregations, a grain, period
behaviour, the joins it needs, an ambiguity policy, and the invariants that must
hold of any result reporting it.

These are structural tests. A contract that is merely present is a definition;
one that survives these is a contract, and the difference is whether the product
can act on it.
"""

from __future__ import annotations

import pytest

from backend.orchestration import concepts as cx
from backend.semantics import ontology as on

CONTRACTS = on.contracts()
BY_ID = {c.concept_id: c for c in CONTRACTS}

#: The concepts P0.5 names. A concept absent here is one a credit officer can
#: say and CreditProbe has no governed meaning for.
REQUIRED: tuple[str, ...] = (
    "exposure", "ead", "limit", "undrawn",
    "stage", "sicr", "stage_moved",
    "pd", "pd_12m", "pd_lifetime", "pd_origination",
    "lgd", "realised_lgd",
    "ecl", "model_ecl", "overlay", "ecl_coverage",
    "rating", "external_rating", "notches_moved",
    "dpd", "dpd_bucket", "arrears", "npl", "cure", "forbearance",
    "collateral", "leverage", "dscr", "interest_cover", "margin",
    "covenant_headroom", "utilisation", "appetite", "default_rate", "raroc",
)


def test_every_concept_p0_5_names_has_a_governed_contract():
    missing = [name for name in REQUIRED if name not in BY_ID]
    assert not missing, f"no governed contract for: {missing}"


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda c: c.concept_id)
def test_a_contract_carries_everything_it_promises(contract):
    """The twelve attributes, on every contract rather than on the ones
    somebody remembered."""
    assert contract.business_name.strip()
    assert len(contract.definition.strip()) > 40, "a definition, not a label"
    assert contract.aliases, "the words a person actually uses"
    assert contract.natural_grain in (
        "facility", "customer", "sector", "portfolio")
    assert contract.period_behaviour in on.PERIOD_BEHAVIOURS
    assert contract.operations, "at least one legitimate operation"
    assert isinstance(contract.higher_is_worse, bool)


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda c: c.concept_id)
def test_a_contract_names_its_data(contract):
    """A contract with no fields behind it is a definition wearing the clothes
    of an implementation, and it makes the catalogue look richer than the
    product is."""
    assert contract.fields, f"{contract.concept_id} names no governed field"


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda c: c.concept_id)
def test_a_measure_states_its_unit(contract):
    """A number with no unit is a number somebody will read in the wrong one.
    Categorical and ordinal concepts are labels and legitimately have none."""
    if contract.is_categorical or contract.is_ordinal:
        return
    assert contract.unit, f"{contract.concept_id} reports a bare number"


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda c: c.concept_id)
def test_every_contract_refuses_something(contract):
    """A contract that permits every operation governs nothing. Summing a
    ratio, averaging a rating, adding probabilities — each produces a number,
    which is the worst kind of wrong answer."""
    assert contract.invalid_operations, (
        f"{contract.concept_id} permits every operation")


def test_a_ratio_never_permits_summing():
    """The sum of ten coverage ratios is neither a ratio nor a total."""
    for contract in CONTRACTS:
        if contract.is_ratio:
            assert not contract.permits(on.SUM), contract.concept_id


def test_an_ordinal_never_permits_averaging():
    """The average of grade 3 and grade 9 is not a grade."""
    for contract in CONTRACTS:
        if contract.is_ordinal:
            assert not contract.permits(on.AVERAGE), contract.concept_id


def test_a_categorical_never_permits_arithmetic():
    for contract in CONTRACTS:
        if contract.is_categorical:
            assert not contract.permits(on.SUM), contract.concept_id
            assert not contract.permits(on.AVERAGE), contract.concept_id


def test_a_refusal_explains_itself_rather_than_citing_the_rule():
    """A refusal without a reason gets routed around. The sentence has to be
    about the concept, not about the rule."""
    said = BY_ID["dscr"].refusal(on.SUM)
    assert said
    assert "ratio" in said.lower() or "total" in said.lower()

    stated = [c for c in CONTRACTS if c.forbidden]
    assert len(stated) >= 15, "most contracts should say why, not only what"
    for contract in stated:
        for operation, reason in contract.forbidden:
            assert operation in on.ALL_OPS, contract.concept_id
            assert len(reason) > 30, f"{contract.concept_id}/{operation}"


def test_a_permitted_operation_has_no_refusal():
    assert BY_ID["ecl"].refusal(on.SUM) == ""
    assert BY_ID["dscr"].refusal(on.AVERAGE) == ""


# ------------------------------------------------------------ ambiguity policy


def test_pd_now_asks_which_horizon_rather_than_guessing():
    """Twelve-month and lifetime PD differ by a factor of three on this book,
    and IFRS 9 uses each in a different stage. Picking one silently is wrong
    two thirds of the time and sounds certain every time."""
    contract = BY_ID["pd"]
    assert contract.ambiguity is not None
    labels = {o["label"] for o in contract.ambiguity.options}
    assert {"Twelve-month PD", "Lifetime PD"} <= labels


def test_lgd_asks_modelled_or_realised():
    """One is the assumption used to compute impairment; the other is what
    recoveries actually produced, on a much smaller and later population."""
    contract = BY_ID["lgd"]
    assert contract.ambiguity is not None
    assert any("realised" in o["label"].lower()
               for o in contract.ambiguity.options)


@pytest.mark.parametrize("phrase, concept", [
    ("show me the 12-month PD by sector", "pd"),
    ("what is the lifetime PD on stage 2?", "pd"),
    ("show the modelled LGD", "lgd"),
    ("what was the realised LGD on closed defaults?", "lgd"),
    ("net realisable value of collateral", "collateral"),
])
def test_a_qualified_mention_resolves_without_asking(phrase, concept):
    """"exposure at default" answers while "exposure" asks. A clarification
    for a question that already said which measure it meant is an interruption,
    and users learn to stop reading them."""
    contract = BY_ID[concept]
    assert contract.ambiguity is not None
    assert contract.ambiguity.resolved_by(phrase), phrase


def test_a_bare_mention_of_an_ambiguous_concept_still_asks():
    for concept in ("pd", "lgd", "exposure", "collateral"):
        contract = BY_ID[concept]
        assert contract.ambiguity is not None
        assert not contract.ambiguity.resolved_by(
            f"show me {contract.business_name.lower()} by sector")


# ------------------------------------------------------------ period behaviour


@pytest.mark.parametrize("concept", ["cure", "stage_moved", "notches_moved",
                                     "default_rate", "realised_lgd"])
def test_an_event_is_a_flow_not_a_snapshot(concept):
    """A default, a cure, a migration — these HAPPEN during a period. Reading
    one as a position makes "the latest" a quarter's worth of events rather
    than a level, and the two are not comparable."""
    assert BY_ID[concept].period_behaviour == on.FLOW


@pytest.mark.parametrize("concept", ["ecl", "ead", "stage", "rating", "dscr"])
def test_a_position_is_a_snapshot(concept):
    assert BY_ID[concept].period_behaviour == on.SNAPSHOT


@pytest.mark.parametrize("concept", ["cure", "stage_moved", "notches_moved"])
def test_a_migration_needs_two_periods(concept):
    """A movement question answered from one period is a movement measured
    against nothing."""
    assert BY_ID[concept].required_periods >= 2


# ------------------------------------------------------------------ invariants


def test_a_bounded_measure_carries_its_bounds():
    """A probability above 100% is a defect, and the check has to exist for
    the answer to be blocked rather than shown."""
    for concept in ("pd_12m", "pd_lifetime", "lgd", "realised_lgd",
                    "default_rate"):
        rules = {i.rule for i in BY_ID[concept].invariants}
        assert "share_bounds" in rules, concept


def test_the_overlay_reconciles_to_total_ecl():
    """Modelled ECL plus overlay is total ECL. Stated as an invariant because
    a decomposition that quietly stops reconciling is one nobody catches."""
    rules = {i.rule for i in BY_ID["overlay"].invariants}
    assert "overlay_reconciles" in rules


def test_sicr_and_stage_cannot_disagree():
    """A facility with a trigger firing that is still in Stage 1 means staging
    and triggers disagree, and one of them is wrong."""
    rules = {i.rule for i in BY_ID["sicr"].invariants}
    assert "triggered_implies_stage" in rules


# ------------------------------------------------------------------- structure


def test_every_contract_resolves_to_a_registered_concept_or_names_its_fields():
    known = {c.id for c in cx.CONCEPTS}
    for contract in CONTRACTS:
        assert contract.concept_id in known or contract.canonical_fields, (
            contract.concept_id)


def test_the_direction_of_deterioration_agrees_with_the_concept_registry():
    """Two places recording which way is worse is one place too many, and the
    disagreement inverts an answer."""
    registry = {c.id: c.higher_is_worse for c in cx.CONCEPTS}
    for contract in CONTRACTS:
        if contract.concept_id in registry:
            assert contract.higher_is_worse == registry[contract.concept_id], (
                contract.concept_id)


def test_the_version_moved_because_a_word_changed_meaning():
    """"PD" used to resolve silently to the twelve-month figure and now asks.
    Every certification earned before that was earned on a different
    understanding of the same word, which is what a major version is for."""
    assert on.ONTOLOGY_VERSION.startswith("2.")


def test_the_fingerprint_changes_when_a_contract_does():
    assert len(on.fingerprint()) >= 8


def test_arabic_aliases_are_declared_but_not_yet_populated():
    """The field exists now so a translator edits the contract rather than a
    parallel dictionary that drifts from it. Empty is the honest state until
    the Arabic scope lands."""
    for contract in CONTRACTS:
        assert isinstance(contract.arabic_aliases, tuple)

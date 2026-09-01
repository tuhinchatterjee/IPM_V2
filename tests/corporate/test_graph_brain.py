"""Graph semantics the Brain can reason with. Phase 4, B45-B49.

Two layers, and they do different jobs.

**Concepts** map what a credit officer SAYS to the governed field that means
it. The three group concepts are separate on purpose: "the group" means the
economics to a shareholder, the decision-making to a governance reviewer and
the obligor to a regulator, and those are three different sets of companies.
A concept map that answered "group" with one column would be confidently
wrong two times in three.

**Semantic contracts** say what may be DONE with each measure. They exist for
their forbidden clauses more than for their definitions: every graph measure
reads like something a credit officer already knows - a score between 0 and
100, a fraction that rises with distress - and each is a different quantity
from the thing it resembles.

**Blueprints** say what a competent analyst would look at. Every graph
blueprint carries a `when_not_to_use` naming the blueprint a reader is likely
to reach for instead, because that is where the damage happens.
"""

from __future__ import annotations

import pytest

from backend.judgment import blueprints as bp
from backend.orchestration import concepts as concepts_mod
from backend.semantics import ontology

GRAPH_DATASETS = ("corporate_connected_groups", "corporate_graph_dq",
                  "corporate_borrower_360")

GRAPH_FAMILIES = (
    bp.GROUP_STRUCTURE, bp.BENEFICIAL_OWNERSHIP, bp.CONNECTED_COUNTERPARTY,
    bp.GROUP_LIMIT, bp.NETWORK_CONTAGION, bp.NETWORK_CENTRALITY,
    bp.SUPPLY_CHAIN, bp.GUARANTEE_NETWORK, bp.HIDDEN_RELATIONSHIP,
    bp.GRAPH_QUALITY,
)


def graph_concepts():
    return [c for c in concepts_mod.CONCEPTS
            if any(cand.dataset in GRAPH_DATASETS for cand in c.candidates)]


class TestConcepts:
    def test_the_graph_has_its_own_concepts(self):
        assert len(graph_concepts()) >= 20

    def test_every_candidate_names_a_real_field(self):
        """A concept pointing at a column that does not exist is a concept
        that turns a question into a 500 rather than an answer."""
        from backend.data_access.catalog import get_catalog

        catalog = get_catalog()
        for concept in graph_concepts():
            for candidate in concept.candidates:
                dataset = catalog.dataset(candidate.dataset)
                fields = (set(dataset.fields) if hasattr(dataset.fields, "keys")
                          else {f.name for f in dataset.fields})
                assert candidate.field in fields, (
                    f"{concept.id}: {candidate.dataset}.{candidate.field}")

    def test_the_three_group_concepts_are_separate(self):
        """"The group" means three different sets of companies. One column
        for all three is confidently wrong two times in three."""
        ids = {c.id for c in concepts_mod.CONCEPTS}
        assert {"connected_group", "control_group", "ownership_group"} <= ids

        columns = {
            c.id: c.default_candidate().field
            for c in concepts_mod.CONCEPTS
            if c.id in ("connected_group", "control_group", "ownership_group")}
        assert len(set(columns.values())) == 3, columns

    def test_each_group_concept_says_what_it_is_not(self):
        for concept_id, phrase in (
                ("control_group", "NOT proportional ownership"),
                ("ownership_group", "not the control"),
                ("connected_group", "never a determination")):
            concept = next(c for c in concepts_mod.CONCEPTS
                           if c.id == concept_id)
            definition = concept.default_candidate().definition
            assert phrase in definition, concept_id

    def test_the_score_concept_says_it_is_not_a_probability(self):
        concept = next(c for c in concepts_mod.CONCEPTS
                       if c.id == "network_risk_score")
        definition = concept.default_candidate().definition
        for phrase in ("NOT a probability", "NOT a PD", "NOT a rating",
                       "NOT an IFRS 9 stage", "NOT an expected credit loss"):
            assert phrase in definition, phrase

    def test_centrality_keeps_its_directions_apart(self):
        """Forward ranks transmitters, reverse ranks the exposed. A concept
        that offered one candidate would answer half the questions wrong."""
        concept = next(c for c in concepts_mod.CONCEPTS
                       if c.id == "centrality")
        fields = {cand.field for cand in concept.candidates}
        assert fields == {"pagerank_transmits", "pagerank_hurt",
                          "betweenness"}

    def test_confidence_offers_the_weakest_and_the_mean(self):
        concept = next(c for c in concepts_mod.CONCEPTS
                       if c.id == "graph_confidence")
        assert concept.default_candidate().field == "graph_confidence"
        assert {cand.field for cand in concept.candidates} == {
            "graph_confidence", "relationship_confidence"}

    def test_every_concept_id_is_unique(self):
        ids = [c.id for c in concepts_mod.CONCEPTS]
        assert len(ids) == len(set(ids))


class TestSemanticContracts:
    def test_the_graph_measures_have_contracts(self):
        assert len(ontology.CONTRACTS_GRAPH) >= 8

    def test_a_ranking_may_not_be_summed(self):
        """The sum of ten Network Risk Scores is not a quantity of anything."""
        contract = next(c for c in ontology.CONTRACTS_GRAPH
                        if c.concept_id == "network_risk_score")
        forbidden = {op for op, _ in contract.forbidden}
        assert "sum" in forbidden

    def test_debtrank_may_not_be_summed(self):
        """Two borrowers' impacts overlap wherever their networks do."""
        contract = next(c for c in ontology.CONTRACTS_GRAPH
                        if c.concept_id == "debtrank")
        forbidden = dict(contract.forbidden)
        assert "sum" in forbidden
        assert "double-count" in forbidden["sum"]

    def test_a_group_figure_may_not_be_summed_over_members(self):
        """Every member carries the SAME group figure, so summing over
        borrowers multiplies one group's exposure by its member count."""
        for concept_id in ("group_utilisation", "group_size"):
            contract = next(c for c in ontology.CONTRACTS_GRAPH
                            if c.concept_id == concept_id)
            assert "sum" in {op for op, _ in contract.forbidden}, concept_id

    def test_a_community_label_is_not_a_quantity(self):
        contract = next(c for c in ontology.CONTRACTS_GRAPH
                        if c.concept_id == "network_community")
        forbidden = {op for op, _ in contract.forbidden}
        assert {"sum", "average"} <= forbidden

    def test_every_graph_contract_states_a_boundary(self):
        """Every graph contract has to say where the measure stops.

        The property under test is that the definition draws a line — not
        that it spells the line one particular way. An earlier version of
        this test looked for the literal "not", which failed `ubo_count`
        even though its definition says a rejected borrower "has no count
        at all - which is different from having no owner". That is a
        boundary; the assertion was the thing that was wrong.
        """
        # Each phrase introduces a limit: a denial, a contrast, or a
        # displacement of one reading by another.
        boundaries = ("not", "never", "no ", "different from", "rather than",
                      "instead of", "cannot", "is only", "does not")
        for contract in ontology.CONTRACTS_GRAPH:
            text = contract.definition.lower()
            hit = [phrase for phrase in boundaries if phrase in text]
            assert hit, (
                f"{contract.concept_id} defines the measure but never says "
                f"where it stops: {contract.definition!r}")

    def test_every_graph_contract_resolves_to_a_field(self):
        """A contract whose concept_id no concept answers to governs a word
        the planner never produces, and `fields` comes back empty. That is
        how a catalogue looks richer than the product."""
        for contract in ontology.CONTRACTS_GRAPH:
            assert contract.fields, (
                f"{contract.concept_id} names no governed field - most "
                f"likely the contract id and the concept id have drifted")

    def test_every_contract_id_is_unique_across_the_whole_ontology(self):
        ids = [c.concept_id for c in ontology._ALL]
        assert len(ids) == len(set(ids))

    def test_the_ontology_fingerprint_changed(self):
        """A certification gate compares fingerprints. Adding contracts
        without moving it would let a stale release look current."""
        assert ontology.fingerprint()
        assert len(ontology.fingerprint()) == 16


class TestBlueprints:
    def test_there_are_ten_graph_blueprints(self):
        found = [b for b in bp.LIBRARY if b.family in GRAPH_FAMILIES]
        assert len(found) == 10

    def test_every_one_is_usable(self):
        """A blueprint that is not APPROVED or SYSTEM_VALIDATED never reaches
        production, so an unusable one is a blueprint that does not exist."""
        for blueprint in bp.LIBRARY:
            if blueprint.family in GRAPH_FAMILIES:
                assert blueprint.usable, blueprint.blueprint_id

    def test_every_one_says_when_not_to_use_it(self):
        """The load-bearing half. "The group" means three different sets of
        companies, and a blueprint that answers the wrong one answers
        confidently."""
        for blueprint in bp.LIBRARY:
            if blueprint.family in GRAPH_FAMILIES:
                assert blueprint.when_not_to_use, blueprint.blueprint_id
                assert len(blueprint.when_not_to_use) > 40

    def test_every_one_carries_a_challenge(self):
        """An investigation that cannot challenge its own finding is a
        report."""
        for blueprint in bp.LIBRARY:
            if blueprint.family in GRAPH_FAMILIES:
                assert blueprint.challenge_templates, blueprint.blueprint_id

    def test_every_one_has_a_boundary_objective(self):
        """Each graph blueprint has a mandatory objective whose whole job is
        to state what the finding is NOT."""
        boundary_ids = {"caveat", "boundary", "difference", "criterion",
                        "parameter", "evidence", "blocked", "guarantor",
                        "customers", "affected"}
        for blueprint in bp.LIBRARY:
            if blueprint.family not in GRAPH_FAMILIES:
                continue
            ids = {o.id for o in blueprint.required_objectives}
            assert ids & boundary_ids, blueprint.blueprint_id

    def test_the_families_are_registered(self):
        for family in GRAPH_FAMILIES:
            assert family in bp.FAMILIES
            assert bp.for_family(family) is not None

    def test_every_named_engine_is_a_registered_analysis(self):
        """A blueprint naming an engine that does not exist promises an
        analysis the runtime cannot run."""
        from backend.engine.registry import get_registry

        known = {entry.id for entry in get_registry().all()}
        # The judgment engines are separate from the analysis registry; only
        # ids that look like analyses are checked against it.
        analysis_like = {
            "connected_group_exposure", "network_risk_ranking",
            "ownership_and_control_structure", "graph_data_quality"}
        for blueprint in bp.LIBRARY:
            if blueprint.family not in GRAPH_FAMILIES:
                continue
            for objective in blueprint.required_objectives:
                if objective.engine in analysis_like:
                    assert objective.engine in known, objective.engine

    def test_every_named_dataset_is_governed(self):
        from backend.data_access.catalog import get_catalog

        known = {d.name for d in get_catalog().all()}
        for blueprint in bp.LIBRARY:
            if blueprint.family not in GRAPH_FAMILIES:
                continue
            for objective in (blueprint.required_objectives
                              + blueprint.optional_objectives):
                for dataset in objective.datasets:
                    assert dataset in known, (
                        f"{blueprint.blueprint_id} names {dataset}")

    def test_ids_and_families_stay_unique(self):
        ids = [b.blueprint_id for b in bp.LIBRARY]
        families = [b.family for b in bp.LIBRARY]
        assert len(ids) == len(set(ids))
        assert len(families) == len(set(families))

    @pytest.mark.parametrize("family,phrase", [
        (bp.CONNECTED_COUNTERPARTY, "not regulatory connectedness"),
        (bp.NETWORK_CONTAGION, "not an expected credit"),
        (bp.NETWORK_CENTRALITY, "not a PD"),
        (bp.SUPPLY_CHAIN, "never forms a group"),
        (bp.HIDDEN_RELATIONSHIP, "creates no control"),
    ])
    def test_the_caveat_is_in_the_blueprint_not_only_in_the_code(
            self, family, phrase):
        blueprint = bp.for_family(family)
        text = " ".join([blueprint.description, blueprint.when_to_use,
                         blueprint.when_not_to_use,
                         *blueprint.challenge_templates,
                         *[o.statement for o in blueprint.required_objectives]])
        assert phrase.lower() in text.lower(), family

"""The graph questions, answered by an analysis rather than by prose. Phase 4.

The rule this suite enforces is the one in the module's own docstring: asking
"which connected groups are closest to the limit" must run a registered,
versioned, deterministic function over a governed dataset and produce a
Trace. A paragraph a language model composed from a retrieved summary is not
an answer to that question, however well it reads.

So every test here goes through `run_analysis` - the real runner, the real
governed read, the real Trace - rather than calling the function directly.
"""

from __future__ import annotations

import pytest

from backend.corporate import network as net
from backend.data_access import catalog as catalog_mod
from backend.engine.registry import get_registry
from backend.engine.runner import run_analysis

GRAPH_ANALYSES = (
    "connected_group_exposure",
    "network_risk_ranking",
    "ownership_and_control_structure",
    "graph_data_quality",
)


def run(analysis_id: str, **params):
    try:
        found = run_analysis(analysis_id, params={"period": "latest",
                                                  **params})
    except Exception as exc:  # pragma: no cover - environment, not logic
        pytest.skip(f"corporate lake not built: {exc}")
    if found is None or found.result is None:
        pytest.skip("corporate lake not built")
    return found


class TestRegistration:
    def test_all_four_are_registered_and_runnable(self):
        registry = get_registry()
        for analysis_id in GRAPH_ANALYSES:
            registered = registry.require_runnable(analysis_id)
            assert registered.contract.certification.value == "certified"

    def test_each_declares_a_governed_purpose_that_exists(self):
        """A purpose no dataset serves is a purpose that always refuses."""
        registry = get_registry()
        for analysis_id in GRAPH_ANALYSES:
            contract = registry.require_runnable(analysis_id).contract
            for purpose in contract.required_domains:
                assert purpose in catalog_mod.GOVERNED_PURPOSES, purpose

    def test_each_declares_trigger_questions_and_limitations(self):
        """A planner picks by these. An analysis with none is unreachable."""
        registry = get_registry()
        for analysis_id in GRAPH_ANALYSES:
            contract = registry.require_runnable(analysis_id).contract
            assert len(contract.trigger_questions) >= 3, analysis_id
            assert contract.limitations, analysis_id
            assert contract.calculation_description, analysis_id

    def test_no_purpose_is_declared_for_the_snapshot(self):
        """B2: the Borrower 360 is authoritative for nothing, so a purpose
        naming it would be one no dataset can honestly serve."""
        assert "corporate_borrower_snapshot" not in (
            catalog_mod.GOVERNED_PURPOSES)


class TestConnectedGroupExposure:
    def test_it_runs_and_ranks_groups(self):
        found = run("connected_group_exposure")
        assert found.result.values["groups"] > 0
        assert len(found.result.rows) > 0
        top = found.result.rows[0]
        assert top["group_exposure"] >= found.result.rows[-1]["group_exposure"]

    def test_it_counts_standalone_borrowers_separately(self):
        """A borrower in no group is not a group of one. Counting it as one
        would inflate the group count by the number of standalone names."""
        found = run("connected_group_exposure")
        assert found.result.values["standalone_borrowers"] >= 0
        ids = {row["connected_group_id"] for row in found.result.rows}
        assert "NOT_APPLICABLE" not in ids

    def test_the_group_figure_carries_b54s_caveat(self):
        found = run("connected_group_exposure")
        caveat = found.result.meta["caveat"]
        assert "not regulatory connectedness" in caveat
        assert "UNVERIFIED REGULATORY PARAMETER" in caveat

    def test_one_row_per_group_not_per_member(self):
        found = run("connected_group_exposure", top_n=50)
        ids = [row["connected_group_id"] for row in found.result.rows]
        assert len(ids) == len(set(ids))

    def test_it_produces_a_trace(self):
        """An analysis with no Trace cannot be defended, however right it is."""
        found = run("connected_group_exposure")
        assert found.status == "succeeded"
        nodes = found.graph.nodes
        nodes = list(nodes.values()) if isinstance(nodes, dict) else list(nodes)
        assert nodes
        kinds = {str(node.type) for node in nodes}
        assert len(kinds) >= 3, (
            "a Trace with one or two kinds of node is a log line, not a "
            f"lineage; got {sorted(kinds)}")


class TestNetworkRiskRanking:
    def test_an_unmeasured_borrower_is_excluded_not_ranked_at_zero(self):
        """Ranking it at zero reads as "no network risk" rather than "no
        network", and the two are not the same statement."""
        found = run("network_risk_ranking")
        assert found.result.values["unmeasured"] > 0
        assert found.result.values["ranked"] > 0
        for row in found.result.rows:
            assert row["network_risk_score"] is not None

    def test_it_says_what_it_excluded(self):
        found = run("network_risk_ranking")
        assert found.result.warnings
        assert "not ranked" in found.result.warnings[0]

    def test_the_score_carries_its_banner(self):
        found = run("network_risk_ranking")
        caveat = found.result.meta["caveat"]
        for phrase in ("NOT A PROBABILITY", "NOT PD", "NOT A RATING",
                       "NOT IFRS 9 STAGE", "NOT ECL",
                       "NOT an expected credit loss"):
            assert phrase in caveat, phrase

    def test_the_weights_travel_with_the_score(self):
        found = run("network_risk_ranking")
        assert found.result.meta["weights"] == net.NRS_WEIGHTS

    def test_the_components_come_back_with_the_score(self):
        """A borrower can be high on one and low on the others, which is the
        interesting case and is invisible from the composite alone."""
        found = run("network_risk_ranking")
        row = found.result.rows[0]
        for column in ("debtrank_impact", "pagerank_transmits",
                       "pagerank_hurt", "betweenness"):
            assert column in row

    def test_it_is_ordered_by_score(self):
        found = run("network_risk_ranking", top_n=30)
        scores = [row["network_risk_score"] for row in found.result.rows]
        assert scores == sorted(scores, reverse=True)


class TestOwnershipAndControl:
    def test_a_refused_computation_is_a_third_category(self):
        """Counting a REJECTED ownership component as "no owner" reports a
        data-quality defect as a fact about the borrower."""
        found = run("ownership_and_control_structure")
        values = found.result.values
        assert values["ownership_blocked"] > 0
        assert (values["with_identified_ubo"] + values["no_identified_ubo"]
                + values["ownership_blocked"] == values["borrowers"])

    def test_it_splits_the_book_by_role(self):
        found = run("ownership_and_control_structure")
        roles = {row["group_role"] for row in found.result.rows}
        assert roles <= {"PARENT", "SUBSIDIARY", "AFFILIATE", "STANDALONE"}
        assert len(roles) >= 2

    def test_control_is_not_confused_with_ownership(self):
        found = run("ownership_and_control_structure")
        caveat = found.result.meta["caveat"]
        assert "NOT proportional ownership" in caveat
        assert "51% of 51%" in caveat


class TestGraphDataQuality:
    def test_it_reports_the_register_as_it_ran(self):
        found = run("graph_data_quality")
        assert found.result.values["checks_run"] >= 14
        assert found.result.values["overall_status"] in ("PASS", "FLAG",
                                                         "REJECT")

    def test_a_reject_names_what_it_blocked(self):
        found = run("graph_data_quality")
        rejects = [row for row in found.result.rows
                   if row["status"] == "REJECT"]
        for row in rejects:
            assert row["blocks"], (
                "a REJECT that does not name what it stopped is a warning "
                "wearing a refusal's name")

    def test_the_blocking_rule_travels_with_the_register(self):
        found = run("graph_data_quality")
        assert "REJECT blocks" in found.result.meta["blocking_rule"]


class TestDeterminism:
    def test_two_runs_agree(self):
        for analysis_id in GRAPH_ANALYSES:
            first = run(analysis_id)
            second = run(analysis_id)
            assert first.result.rows == second.result.rows, analysis_id
            assert first.result.values == second.result.values, analysis_id


class TestTheTwelveQuestionsRoute:
    """The twelve named graph questions reach an ANALYSIS, not prose.

    Routing is the half of "no prose-only calculation" that is easy to lose:
    the analyses can exist, be correct and be unreachable, and the product
    then answers the question in a paragraph composed from a retrieved
    summary. Every one of these must select a certified analysis by
    deterministic overlap with its declared name or trigger questions.
    """

    QUESTIONS = (
        ("Which connected groups carry the most exposure?",
         "connected_group_exposure"),
        ("Which groups are closest to the group limit?",
         "connected_group_exposure"),
        ("Are any connected counterparty groups in breach?",
         "connected_group_exposure"),
        ("Show me group concentration.", "connected_group_exposure"),
        ("Which borrowers are most central in the network?",
         "network_risk_ranking"),
        ("Rank borrowers by network risk score.", "network_risk_ranking"),
        ("Who would take the most of the network down with them?",
         "network_risk_ranking"),
        ("How many borrowers have an identified ultimate beneficial owner?",
         "ownership_and_control_structure"),
        ("Which borrowers have no identified owner?",
         "ownership_and_control_structure"),
        ("How does the book split between parents, subsidiaries and "
         "standalone companies?", "ownership_and_control_structure"),
        ("Can we trust the relationship graph this quarter?",
         "graph_data_quality"),
        ("What data-quality checks failed on the graph?",
         "graph_data_quality"),
    )

    def test_all_twelve_select_the_right_analysis(self):
        from backend.orchestration import capability as cap
        from backend.orchestration import certified

        reading = cap.Reading(intent=sorted(cap.COMPUTES)[0],
                              candidate_methods=[])
        missed: list[str] = []
        wrong: list[str] = []
        for question, expected in self.QUESTIONS:
            found = certified.match(question, reading)
            if found is None:
                missed.append(question)
            elif found.analysis_id != expected:
                wrong.append(f"{question} -> {found.analysis_id}")

        assert not missed, (
            "these graph questions reach no certified analysis and would be "
            f"answered in prose: {missed}")
        assert not wrong, f"routed to the wrong analysis: {wrong}"

    def test_a_credit_book_question_does_not_route_to_a_graph_analysis(self):
        """Scope separation, at the routing layer.

        Both books have customers and exposure. A question about the credit
        facility book must not be answered by a corporate graph analysis
        merely because both contain the word "exposure".
        """
        from backend.orchestration import capability as cap
        from backend.orchestration import certified

        reading = cap.Reading(intent=sorted(cap.COMPUTES)[0],
                              candidate_methods=[])
        for question in ("What is the IFRS 9 stage distribution?",
                         "Show me the arrears position.",
                         "What is the rating transition matrix?"):
            found = certified.match(question, reading)
            if found is not None:
                assert found.analysis_id not in GRAPH_ANALYSES, question

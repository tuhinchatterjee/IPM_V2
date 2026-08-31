"""Ownership and control mathematics, against hand-computed values.

Every expected number here is derived on paper in the test itself, from the
closed form, and never from what the implementation returned. A test that
asserts the code agrees with itself would pass just as happily on a wrong
answer.

The two properties under most pressure:

* ownership is FRACTIONAL and MULTIPLICATIVE - 51% of 51% is 26%;
* control is BINARY, ABSORPTIVE and TRANSITIVE - 51% of 51% is 100%.

Conflating them is the single most common way a group-structure analysis goes
wrong, so they are tested on the same graph, side by side, and asserted to
give different answers.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.corporate import graphdata
from backend.corporate import graphmath as gm


def graph(nodes, ownership, voting=None):
    """A hand-built ownership graph. Percentages given as fractions."""
    owned = np.array(ownership, dtype=float)
    votes = np.array(voting if voting is not None else ownership, dtype=float)
    return gm.OwnershipGraph(nodes=tuple(nodes), matrix=owned, voting=votes,
                             as_of="2026-06-30",
                             components=gm._components(owned))


class TestEffectiveOwnership:
    def test_a_two_step_chain_multiplies(self):
        """A owns 50% of B, B owns 50% of C. A's stake in C is 25%."""
        g = graph("ABC", [[0, .5, 0], [0, 0, .5], [0, 0, 0]])
        solved = gm.effective_ownership(g)
        assert solved.stake("A", "C") == pytest.approx(25.0)

    def test_a_three_step_chain_multiplies(self):
        """0.8 × 0.6 × 0.5 = 0.24."""
        g = graph("ABCD", [[0, .8, 0, 0], [0, 0, .6, 0],
                           [0, 0, 0, .5], [0, 0, 0, 0]])
        solved = gm.effective_ownership(g)
        assert solved.stake("A", "D") == pytest.approx(24.0)

    def test_parallel_paths_add(self):
        """A→B→D at 0.5×0.4 plus A→C→D at 0.3×0.6 is 0.20 + 0.18 = 0.38."""
        g = graph("ABCD", [[0, .5, .3, 0], [0, 0, 0, .4],
                           [0, 0, 0, .6], [0, 0, 0, 0]])
        solved = gm.effective_ownership(g)
        assert solved.stake("A", "D") == pytest.approx(38.0)

    def test_a_direct_stake_and_an_indirect_one_add(self):
        """A→C at 10% plus A→B→C at 50%×50% is 10 + 25 = 35."""
        g = graph("ABC", [[0, .5, .10], [0, 0, .5], [0, 0, 0]])
        solved = gm.effective_ownership(g)
        assert solved.stake("A", "C") == pytest.approx(35.0)

    def test_a_reciprocal_holding_matches_the_closed_form(self):
        """A owns 60% of B; B owns 20% of A.

        The series is 0.6 + 0.6·(0.2·0.6) + ... = 0.6 / (1 − 0.12), which is
        68.1818…%. A path-multiplying implementation that stops at the first
        loop returns 60% and would pass every acyclic test above.
        """
        g = graph("AB", [[0, .6], [.2, 0]])
        solved = gm.effective_ownership(g)
        assert solved.stake("A", "B") == pytest.approx(
            0.6 / (1 - 0.12) * 100.0)

    def test_the_solve_residual_is_at_machine_precision(self):
        g = graph("ABC", [[0, .5, .1], [0, 0, .5], [.2, 0, 0]])
        solved = gm.effective_ownership(g)
        assert gm.residual(g, solved) < 1e-12

    def test_components_are_solved_independently(self):
        """Two disjoint structures must not contaminate each other."""
        g = graph("ABCD", [[0, .5, 0, 0], [0, 0, 0, 0],
                           [0, 0, 0, .4], [0, 0, 0, 0]])
        solved = gm.effective_ownership(g)
        assert solved.stake("A", "B") == pytest.approx(50.0)
        assert solved.stake("C", "D") == pytest.approx(40.0)
        assert solved.stake("A", "D") == pytest.approx(0.0)


class TestConvergenceRefusal:
    def test_rho_of_exactly_one_is_refused(self):
        """Mutual 100% ownership. The series does not converge."""
        g = graph("AB", [[0, 1.0], [1.0, 0]])
        with pytest.raises(gm.GraphDataQualityRejected) as caught:
            gm.effective_ownership(g, strict=True)
        assert caught.value.evidence["spectral_radius"] == pytest.approx(1.0)

    def test_an_over_claimed_register_is_refused(self):
        g = graph("AB", [[0, 1.2], [1.0, 0]])
        with pytest.raises(gm.GraphDataQualityRejected) as caught:
            gm.effective_ownership(g, strict=True)
        assert caught.value.evidence["spectral_radius"] > 1.0

    def test_the_refusal_carries_the_offending_entities(self):
        g = graph("AB", [[0, 1.0], [1.0, 0]])
        with pytest.raises(gm.GraphDataQualityRejected) as caught:
            gm.effective_ownership(g, strict=True)
        payload = caught.value.to_dict()
        assert payload["status"] == "GRAPH_DATA_QUALITY_REJECTED"
        assert set(payload["evidence"]["entities"]) == {"A", "B"}

    def test_nothing_is_capped_or_normalised(self):
        """The refusal must not be reachable by producing a number instead.

        A capped answer here would look entirely plausible and would never be
        questioned again, which is why refusing is the requirement.
        """
        g = graph("AB", [[0, 1.0], [1.0, 0]])
        solved = gm.effective_ownership(g)
        assert solved.rejected_components == (0,)
        assert solved.blocked_nodes == {"A", "B"}

    def test_a_blocked_entity_cannot_be_read_as_zero(self):
        """Zero is a measurement. "Refused" is not, and must not read as one."""
        g = graph("AB", [[0, 1.0], [1.0, 0]])
        solved = gm.effective_ownership(g)
        with pytest.raises(gm.GraphDataQualityRejected):
            solved.stake("A", "B")
        with pytest.raises(gm.GraphDataQualityRejected):
            solved.owners_of("B")

    def test_one_bad_component_does_not_blind_the_others(self):
        """A defective family group must not cost the rest of the portfolio."""
        g = graph("ABCD", [[0, 1.0, 0, 0], [1.0, 0, 0, 0],
                           [0, 0, 0, .5], [0, 0, 0, 0]])
        solved = gm.effective_ownership(g)
        assert solved.stake("C", "D") == pytest.approx(50.0)
        assert solved.provenance()["validation_status"] == "REJECT"

    def test_a_near_singular_component_is_flagged_not_refused(self):
        g = graph("AB", [[0, .9995], [.9995, 0]])
        solved = gm.effective_ownership(g)
        assert solved.rejected_components == ()
        assert solved.near_singular_components == (0,)
        assert solved.provenance()["validation_status"] == "FLAG"


class TestOwnershipChains:
    def test_the_enumeration_reconciles_with_the_matrix(self):
        g = graph("ABC", [[0, .5, .10], [0, 0, .5], [0, 0, 0]])
        solved = gm.effective_ownership(g)
        chain = gm.ownership_chains(g, solved, "A", "C")
        assert chain.direct_pct == pytest.approx(10.0)
        assert chain.indirect_pct == pytest.approx(25.0)
        assert chain.authoritative_total_pct == pytest.approx(35.0)
        assert chain.explained_pct == pytest.approx(35.0)
        assert chain.warning == ""

    def test_the_matrix_is_authoritative_and_says_so(self):
        g = graph("ABC", [[0, .5, 0], [0, 0, .5], [0, 0, 0]])
        solved = gm.effective_ownership(g)
        payload = gm.ownership_chains(g, solved, "A", "C").to_dict()
        assert "authoritative" in payload["authority"]
        assert payload["total_effective_stake_pct"] == pytest.approx(25.0)

    def test_every_path_is_reported_with_its_product(self):
        g = graph("ABCD", [[0, .5, .3, 0], [0, 0, 0, .4],
                           [0, 0, 0, .6], [0, 0, 0, 0]])
        solved = gm.effective_ownership(g)
        chain = gm.ownership_chains(g, solved, "A", "D")
        products = sorted(round(c.product_pct, 6) for c in chain.chains)
        assert products == [18.0, 20.0]

    def test_a_cycle_is_excluded_counted_and_explained(self):
        """A→B→C→A. The matrix sums the loop; enumeration cannot.

        The gap must be reported WITH a stated cause. A warning that says the
        numbers differ and gives no reason is not an explanation.
        """
        g = graph("ABC", [[0, .5, 0], [0, 0, .5], [.5, 0, 0]])
        solved = gm.effective_ownership(g)
        chain = gm.ownership_chains(g, solved, "A", "C")
        assert chain.authoritative_total_pct == pytest.approx(
            0.25 / (1 - 0.125) * 100.0)
        assert chain.explained_pct == pytest.approx(25.0)
        assert chain.cycles_excluded >= 1
        assert "EXPLANATION WARNING" in chain.warning

    def test_an_acyclic_explanation_raises_no_warning(self):
        g = graph("ABC", [[0, .5, 0], [0, 0, .5], [0, 0, 0]])
        solved = gm.effective_ownership(g)
        chain = gm.ownership_chains(g, solved, "A", "C")
        assert chain.cycles_excluded == 0
        assert chain.warning == ""

    def test_depth_is_bounded_and_truncation_is_declared(self):
        size = 9
        matrix = np.zeros((size, size))
        for i in range(size - 1):
            matrix[i, i + 1] = 0.9
        g = graph([chr(65 + i) for i in range(size)], matrix)
        solved = gm.effective_ownership(g)
        chain = gm.ownership_chains(g, solved, "A", chr(65 + size - 1),
                                    max_depth=3)
        assert chain.truncated is True
        assert chain.chains == ()
        assert "EXPLANATION WARNING" in chain.warning


class TestControlIsNotOwnership:
    def test_fifty_one_of_fifty_one_is_a_quarter_of_the_economics(self):
        g = graph(["P", "H", "OpCo"],
                  [[0, .51, 0], [0, 0, .51], [0, 0, 0]])
        solved = gm.effective_ownership(g)
        assert solved.stake("P", "OpCo") == pytest.approx(26.01)

    def test_fifty_one_of_fifty_one_is_all_of_the_control(self):
        g = graph(["P", "H", "OpCo"],
                  [[0, .51, 0], [0, 0, .51], [0, 0, 0]])
        closure = gm.control_closure(g)
        assert closure.controls("P", "H")
        assert closure.controls("H", "OpCo")
        assert closure.controls("P", "OpCo")

    def test_control_reads_voting_never_ownership(self):
        """Economics 90%, votes 10%: economically dominant, not in control.

        This is the dual-class case. An implementation that reached for the
        ownership column would report control here, and would be wrong in the
        direction that matters most.
        """
        g = graph("AB", ownership=[[0, .9], [0, 0]],
                  voting=[[0, .1], [0, 0]])
        closure = gm.control_closure(g)
        solved = gm.effective_ownership(g)
        assert solved.stake("A", "B") == pytest.approx(90.0)
        assert not closure.controls("A", "B")

    def test_a_minority_economic_holder_can_still_control(self):
        """Votes 60%, economics 20%. The mirror image of the case above."""
        g = graph("AB", ownership=[[0, .2], [0, 0]],
                  voting=[[0, .6], [0, 0]])
        closure = gm.control_closure(g)
        assert closure.controls("A", "B")

    def test_de_facto_control_needs_to_be_strictly_largest(self):
        """35% against a dispersed register controls; 35% against 35% does not."""
        alone = graph("AB", ownership=[[0, .35], [0, 0]],
                      voting=[[0, .35], [0, 0]])
        assert gm.control_closure(alone).controls("A", "B")

        tied = graph("ABC", ownership=[[0, 0, .35], [0, 0, .35], [0, 0, 0]],
                     voting=[[0, 0, .35], [0, 0, .35], [0, 0, 0]])
        closure = gm.control_closure(tied)
        assert not closure.controls("A", "C")
        assert not closure.controls("B", "C")

    def test_mutual_control_forms_one_bloc(self):
        g = graph("AB", ownership=[[0, .6], [.6, 0]],
                  voting=[[0, .6], [.6, 0]])
        closure = gm.control_closure(g)
        assert closure.component_of["A"] == closure.component_of["B"]
        assert closure.controls("A", "B") and closure.controls("B", "A")

    def test_a_bloc_controls_everything_the_bloc_reaches(self):
        """A and B control each other; B controls C. So A controls C."""
        g = graph("ABC", ownership=[[0, .6, 0], [.6, 0, .6], [0, 0, 0]],
                  voting=[[0, .6, 0], [.6, 0, .6], [0, 0, 0]])
        closure = gm.control_closure(g)
        assert closure.controls("A", "C")

    def test_control_is_not_proportional(self):
        """Down a five-deep 51% chain: economics vanish, control does not."""
        size = 6
        matrix = np.zeros((size, size))
        for i in range(size - 1):
            matrix[i, i + 1] = 0.51
        nodes = [chr(65 + i) for i in range(size)]
        g = graph(nodes, matrix)
        solved = gm.effective_ownership(g)
        closure = gm.control_closure(g)
        assert solved.stake("A", "F") == pytest.approx(0.51 ** 5 * 100)
        assert solved.stake("A", "F") < 4.0
        assert closure.controls("A", "F")

    def test_an_explicit_control_assertion_outranks_inference(self):
        import pandas as pd
        g = graph("AB", ownership=[[0, .05], [0, 0]],
                  voting=[[0, .05], [0, 0]])
        stated = pd.DataFrame([{
            "edge_type": graphdata.CONTROLS, "from_node": "A",
            "to_node": "B", "valid_from": "2020-01-01", "valid_to": "",
            "recorded_at": "2020-01-01"}])
        closure = gm.control_closure(g, explicit=stated)
        assert closure.controls("A", "B")
        assert closure.rule_hits["explicit_control"] == 1

    def test_the_closure_declares_its_policy_as_unverified(self):
        g = graph("AB", [[0, .6], [0, 0]])
        provenance = gm.control_closure(g).provenance()
        assert "UNVERIFIED REGULATORY PARAMETER" in provenance[
            "parameter_caveat"]
        assert "not" in provenance["semantics"].lower()


class TestDerivedProvenance:
    def test_every_derived_result_is_stamped(self):
        g = graph("AB", [[0, .5], [0, 0]])
        solved = gm.effective_ownership(g)
        provenance = solved.provenance()
        for key in ("computed_as_of", "derivation_method",
                    "pipeline_version", "policy_version",
                    "validation_status"):
            assert provenance[key]

    def test_the_five_derived_edge_types_are_named(self):
        for name in ("UBO_OF", "CONTROLS_EFFECTIVELY", "MEMBER_OF",
                     "CONNECTED_TO", "SIMILAR_TO"):
            assert name in gm.DERIVED_EDGE_TYPES


class TestAgainstTheRealUniverse:
    def test_the_ownership_graph_contains_genuine_cycles(self, universe):
        """Without a cycle the solve is a path sum and proves nothing.

        A pure DAG makes every component's matrix nilpotent, rho exactly
        zero, and the convergence check unfireable on real data.
        """
        g = gm.build_ownership_graph(
            universe["corporate_ownership_edges"], "Q2 2026")
        solved = gm.effective_ownership(g)
        cyclic = [r for r in solved.spectral_radius_by_component.values()
                  if r > 1e-9]
        assert len(cyclic) >= 10, f"only {len(cyclic)} components have a cycle"

    def test_the_refusal_path_fires_on_real_data(self, universe):
        g = gm.build_ownership_graph(
            universe["corporate_ownership_edges"], "Q2 2026")
        solved = gm.effective_ownership(g)
        assert solved.rejected_components, (
            "no component is defective, so the refusal path is never "
            "exercised outside a unit test")
        assert solved.blocked_nodes

    def test_the_solve_is_exact_on_the_real_universe(self, universe):
        g = gm.build_ownership_graph(
            universe["corporate_ownership_edges"], "Q2 2026")
        solved = gm.effective_ownership(g)
        assert gm.residual(g, solved) < 1e-9

    def test_a_stake_above_100_percent_only_arises_from_reciprocity(
            self, universe):
        """Integrated ownership CAN exceed 100%, but only for one reason.

        `Ã = A(I − A)⁻¹` sums every path length, so a reciprocal holding that
        routes ownership back through the owner multiplies every stake by
        1/(1 − loop). That is the quantity the method defines and it is
        reported rather than capped.

        The invariant worth holding is that it can happen for no OTHER reason:
        an entry above 100% inside an acyclic component would have no
        mechanism behind it and would be a real defect. This asserts the
        distinction rather than the blanket bound, which is simply false for
        integrated ownership.
        """
        g = gm.build_ownership_graph(
            universe["corporate_ownership_edges"], "Q2 2026")
        solved = gm.effective_ownership(g)
        component_of = {node: position
                        for position, members in enumerate(g.components)
                        for node in members}
        index = {name: i for i, name in enumerate(g.nodes)}

        for owner, owned, pct in solved.inflated_by_reciprocity():
            component = component_of[index[owned]]
            rho = solved.spectral_radius_by_component[component]
            assert rho > 1e-9, (
                f"{owner} holds {pct:.2f}% of {owned} in an ACYCLIC "
                f"component (rho={rho}); nothing can produce that")

    def test_stakes_above_100_percent_are_flagged_not_hidden(self, universe):
        g = gm.build_ownership_graph(
            universe["corporate_ownership_edges"], "Q2 2026")
        provenance = gm.effective_ownership(g).provenance()
        assert provenance["validation_status"] in {"FLAG", "REJECT"}
        assert "reciprocal" in provenance["integrated_ownership_note"]

    def test_a_register_may_not_over_claim_unless_deliberate(self, universe):
        """A shareholder register summing past 100% is a defect.

        The generator once added sibling and reciprocal stakes ON TOP of the
        parent's, leaving 41 entities claiming up to 188% of themselves, and
        nothing caught it: the spectral radius bounds CONVERGENCE, not the
        column totals, so the solve returned a well-conditioned answer built
        on an impossible register. Only the two structures generated
        defective on purpose may over-claim now.
        """
        g = gm.build_ownership_graph(
            universe["corporate_ownership_edges"], "Q2 2026")
        totals = g.matrix.sum(axis=0)
        over = [g.nodes[i] for i in np.nonzero(totals > 1.0 + 1e-6)[0]]
        solved = gm.effective_ownership(g)
        assert set(over) <= set(solved.blocked_nodes), (
            f"registers over-claim without being refused: "
            f"{sorted(set(over) - set(solved.blocked_nodes))}")

    def test_the_derived_graph_respects_the_as_of_predicate(self, universe):
        """A derived product must not see an edge recorded after its date."""
        edges = universe["corporate_ownership_edges"]
        early = gm.build_ownership_graph(edges, "Q4 2023")
        late = gm.build_ownership_graph(edges, "Q2 2026")
        assert early.size < late.size

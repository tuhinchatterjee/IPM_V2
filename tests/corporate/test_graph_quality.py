"""Graph data quality: fifteen checks, and the rule that REJECT blocks.

The point of this suite is not that the checks run. It is that a REJECT
actually stops the computation that depends on it, and that it stops only
that computation - a gate that blanks the whole Borrower 360 over four bad
rows is a gate that gets switched off within a week.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.corporate import graphdata
from backend.corporate import graphquality as gq

AS_OF = "2026-06-30"


def edge(edge_type: str, source: str, target: str, **over) -> dict[str, object]:
    row = {
        "edge_id": over.pop("edge_id", f"E-{source}-{target}"),
        "edge_type": edge_type,
        "from_node": source,
        "to_node": target,
        "ownership_pct": 0.0,
        "voting_pct": 0.0,
        "valid_from": "2020-01-01",
        "valid_to": "",
        "recorded_at": "2020-06-01",
        "source": "Commercial Registry filing",
        "confidence": 0.97,
        "origin": graphdata.ORIGIN,
    }
    row.update(over)
    return row


def frames_of(*, ownership=None, exposure=None, guarantees=None,
              supply=None, nodes=None, borrowers=None, master=None):
    own = pd.DataFrame(ownership or [])
    everything = [own] + [pd.DataFrame(f or [])
                          for f in (exposure, guarantees, supply)]
    declared = set()
    for frame in everything:
        if not frame.empty:
            declared |= set(frame["from_node"].astype(str))
            declared |= set(frame["to_node"].astype(str))
    node_ids = nodes if nodes is not None else sorted(declared)
    return {
        "nodes": pd.DataFrame({"node_id": node_ids,
                               "node_type": graphdata.CORPORATE}),
        "borrowers": set(borrowers if borrowers is not None
                         else [n for n in node_ids if str(n).startswith("C")]),
        "master": master,
        "ownership": own,
        "exposure": pd.DataFrame(exposure or []),
        "guarantees": pd.DataFrame(guarantees or []),
        "supply": pd.DataFrame(supply or []),
    }


# ------------------------------------------------------ the blocking rule


class TestBlockingRule:
    def test_a_global_reject_blocks_its_dependent_computations(self):
        report = gq.QualityReport(as_of=AS_OF, results=[
            gq.CheckResult("GQ-XX", "planted", gq.REJECT, "planted", "-",
                           (gq.DEBTRANK,))])
        assert report.is_blocked(gq.DEBTRANK)
        assert report.status == gq.REJECT

    def test_a_block_closes_over_the_dependency_graph(self):
        """DebtRank blocked must block the score that is built from it.

        A composite that survives the failure of its own inputs is worse than
        no composite: it still prints a number and nothing on the screen says
        the number is now meaningless.
        """
        report = gq.QualityReport(as_of=AS_OF, results=[
            gq.CheckResult("GQ-XX", "planted", gq.REJECT, "planted", "-",
                           (gq.DEBTRANK,))])
        assert report.is_blocked(gq.NETWORK_RISK_SCORE)

    def test_the_closure_reaches_a_two_step_chain(self):
        """Register REJECT -> effective ownership -> UBO."""
        report = gq.QualityReport(as_of=AS_OF, results=[
            gq.CheckResult("GQ-XX", "planted", gq.REJECT, "planted", "-",
                           (gq.EFFECTIVE_OWNERSHIP,))])
        assert report.is_blocked(gq.UBO)

    def test_a_flag_does_not_block(self):
        report = gq.QualityReport(as_of=AS_OF, results=[
            gq.CheckResult("GQ-XX", "planted", gq.FLAG, "planted", "-",
                           (gq.DEBTRANK,))])
        assert not report.is_blocked(gq.DEBTRANK)
        assert report.status == gq.FLAG

    def test_an_unrelated_reject_does_not_block_everything(self):
        report = gq.QualityReport(as_of=AS_OF, results=[
            gq.CheckResult("GQ-XX", "planted", gq.REJECT, "planted", "-",
                           (gq.EFFECTIVE_OWNERSHIP,))])
        assert not report.is_blocked(gq.DEBTRANK)
        assert not report.is_blocked(gq.CENTRALITY)

    def test_an_entity_scoped_reject_blocks_only_the_named_entities(self):
        report = gq.QualityReport(as_of=AS_OF, results=[
            gq.CheckResult("GQ-XX", "planted", gq.REJECT, "planted", "-",
                           (gq.EFFECTIVE_OWNERSHIP,), scope=gq.SCOPE_ENTITY,
                           affected=frozenset({"CORP-A"}))])
        assert report.is_blocked(gq.EFFECTIVE_OWNERSHIP, "CORP-A")
        assert not report.is_blocked(gq.EFFECTIVE_OWNERSHIP, "CORP-B")
        assert not report.is_blocked(gq.EFFECTIVE_OWNERSHIP)

    def test_a_blocked_field_says_why_rather_than_returning_a_number(self):
        report = gq.QualityReport(as_of=AS_OF, results=[
            gq.CheckResult("GQ-XX", "impossible register", gq.REJECT,
                           "4 registers above 110%", "-",
                           (gq.EFFECTIVE_OWNERSHIP,))])
        payload = gq.blocked_value(report, gq.EFFECTIVE_OWNERSHIP)
        assert payload["status"] == "DATA_QUALITY_BLOCKED"
        assert payload["value"] is None
        assert any("impossible register" in r for r in payload["reasons"])

    def test_every_declared_dependency_names_known_computations(self):
        for consumer, inputs in gq.DEPENDS_ON.items():
            assert consumer in gq.COMPUTATIONS
            for name in inputs:
                assert name in gq.COMPUTATIONS


# ------------------------------------------------------ individual checks


class TestRegisterTotals:
    def test_a_register_summing_to_one_hundred_passes(self):
        frames = frames_of(ownership=[
            edge(graphdata.OWNS, "H1", "CORP-A", ownership_pct=60.0),
            edge(graphdata.OWNS, "H2", "CORP-A", ownership_pct=40.0)])
        assert gq.check_register_totals(frames).status == gq.PASS

    def test_a_register_claiming_one_hundred_and_eighty_is_rejected(self):
        frames = frames_of(ownership=[
            edge(graphdata.OWNS, "H1", "CORP-A", ownership_pct=100.0),
            edge(graphdata.OWNS, "H2", "CORP-A", ownership_pct=80.0)])
        assert gq.check_register_totals(frames).status == gq.REJECT

    def test_rounding_dust_flags_rather_than_rejects(self):
        """100.0001% is a rounding artefact, not an impossible register."""
        frames = frames_of(ownership=[
            edge(graphdata.OWNS, "H1", "CORP-A", ownership_pct=100.7)])
        assert gq.check_register_totals(frames).status == gq.FLAG

    def test_the_reject_names_the_whole_contaminated_component(self):
        """Effective ownership is solved per component, so one bad register
        makes every stake in ITS component unreliable - and only that one."""
        frames = frames_of(ownership=[
            edge(graphdata.OWNS, "H1", "CORP-A", ownership_pct=100.0),
            edge(graphdata.OWNS, "H2", "CORP-A", ownership_pct=80.0),
            edge(graphdata.OWNS, "CORP-A", "CORP-B", ownership_pct=51.0),
            edge(graphdata.OWNS, "H9", "CORP-Z", ownership_pct=100.0)])
        result = gq.check_register_totals(frames)
        assert result.scope == gq.SCOPE_ENTITY
        assert {"CORP-A", "CORP-B", "H1", "H2"} <= result.affected
        assert "CORP-Z" not in result.affected


class TestStructuralChecks:
    def test_a_negative_stake_is_rejected(self):
        frames = frames_of(ownership=[
            edge(graphdata.OWNS, "H1", "CORP-A", ownership_pct=-5.0)])
        assert gq.check_negative_ownership(frames).status == gq.REJECT

    def test_self_ownership_is_rejected(self):
        """A owning A makes (I - A) singular and the solve meaningless."""
        frames = frames_of(ownership=[
            edge(graphdata.OWNS, "CORP-A", "CORP-A", ownership_pct=10.0)])
        assert gq.check_self_ownership(frames).status == gq.REJECT

    def test_an_edge_to_an_undeclared_node_is_rejected(self):
        frames = frames_of(
            ownership=[edge(graphdata.OWNS, "H1", "CORP-A",
                            ownership_pct=50.0)],
            nodes=["H1"])
        result = gq.check_dangling_endpoints(frames)
        assert result.status == gq.REJECT
        assert result.scope == gq.SCOPE_GLOBAL

    def test_a_clean_graph_passes_the_endpoint_check(self):
        frames = frames_of(ownership=[
            edge(graphdata.OWNS, "H1", "CORP-A", ownership_pct=50.0)])
        assert gq.check_dangling_endpoints(frames).status == gq.PASS

    def test_a_closed_interval_that_opens_after_it_closes_is_rejected(self):
        frames = frames_of(ownership=[
            edge(graphdata.OWNS, "H1", "CORP-A", ownership_pct=50.0,
                 valid_from="2024-01-01", valid_to="2022-01-01")])
        assert gq.check_temporal_validity(frames).status == gq.REJECT

    def test_knowledge_from_after_the_as_of_date_is_rejected(self):
        """The most damaging thing a bitemporal system can do quietly."""
        frames = frames_of(ownership=[
            edge(graphdata.OWNS, "H1", "CORP-A", ownership_pct=50.0,
                 recorded_at="2027-01-01")])
        assert gq.check_future_knowledge(frames, AS_OF).status == gq.REJECT

    def test_a_missing_confidence_is_rejected(self):
        frames = frames_of(ownership=[
            edge(graphdata.OWNS, "H1", "CORP-A", ownership_pct=50.0,
                 confidence=float("nan"))])
        assert gq.check_missing_confidence(frames).status == gq.REJECT

    def test_a_confidence_above_one_is_rejected(self):
        frames = frames_of(ownership=[
            edge(graphdata.OWNS, "H1", "CORP-A", ownership_pct=50.0,
                 confidence=1.4)])
        assert gq.check_missing_confidence(frames).status == gq.REJECT

    def test_negative_exposure_is_rejected(self):
        """A negative amount inverts the direction of a DebtRank shock."""
        frames = frames_of(exposure=[
            edge(graphdata.EXPOSED_TO, "CORP-A", "CORP-B", amount=-10.0)])
        assert gq.check_exposure_sign(frames).status == gq.REJECT

    def test_positive_exposure_passes(self):
        frames = frames_of(exposure=[
            edge(graphdata.EXPOSED_TO, "CORP-A", "CORP-B", amount=10.0)])
        assert gq.check_exposure_sign(frames).status == gq.PASS

    def test_a_guarantee_missing_an_endpoint_is_rejected(self):
        frames = frames_of(guarantees=[
            edge(graphdata.COVERS, "GUAR-1", "")])
        assert gq.check_guarantee_coverage(frames).status == gq.REJECT


class TestFlaggingChecks:
    def test_orphan_borrowers_flag_before_they_reject(self):
        borrowers = [f"CORP-{i:03d}" for i in range(100)]
        frames = frames_of(
            ownership=[edge(graphdata.OWNS, "CORP-000", "CORP-001",
                            ownership_pct=50.0)],
            nodes=borrowers, borrowers=borrowers)
        assert gq.check_orphan_borrowers(frames).status == gq.REJECT

    def test_a_handful_of_standalone_borrowers_passes(self):
        borrowers = [f"CORP-{i:03d}" for i in range(100)]
        ownership = [edge(graphdata.OWNS, f"CORP-{i:03d}", f"CORP-{i + 1:03d}",
                          ownership_pct=50.0, edge_id=f"E{i}")
                     for i in range(99)]
        frames = frames_of(ownership=ownership, nodes=borrowers,
                           borrowers=borrowers)
        assert gq.check_orphan_borrowers(frames).status == gq.PASS

    def test_duplicate_assertions_flag(self):
        rows = [edge(graphdata.OWNS, "H1", "CORP-A", ownership_pct=50.0,
                     edge_id=f"E{i}") for i in range(3)]
        frames = frames_of(ownership=rows)
        assert gq.check_duplicate_edges(frames).status == gq.FLAG

    def test_a_book_resting_on_weak_evidence_flags(self):
        rows = [edge(graphdata.OWNS, f"H{i}", "CORP-A", ownership_pct=1.0,
                     confidence=0.4, edge_id=f"E{i}") for i in range(10)]
        assert gq.check_low_confidence_share(
            frames_of(ownership=rows)).status == gq.FLAG

    def test_old_evidence_flags(self):
        rows = [edge(graphdata.OWNS, f"H{i}", "CORP-A", ownership_pct=1.0,
                     recorded_at="2019-01-01", edge_id=f"E{i}")
                for i in range(10)]
        assert gq.check_stale_evidence(
            frames_of(ownership=rows), AS_OF).status == gq.FLAG

    def test_recent_evidence_passes(self):
        rows = [edge(graphdata.OWNS, f"H{i}", "CORP-A", ownership_pct=1.0,
                     recorded_at="2026-01-01", edge_id=f"E{i}")
                for i in range(10)]
        assert gq.check_stale_evidence(
            frames_of(ownership=rows), AS_OF).status == gq.PASS

    def test_one_component_swallowing_the_book_flags_the_analytics(self):
        """Everything central means nothing is. The ranking says nothing."""
        borrowers = [f"CORP-{i:03d}" for i in range(20)]
        ownership = [edge(graphdata.OWNS, "CORP-000", f"CORP-{i:03d}",
                          ownership_pct=5.0, edge_id=f"E{i}")
                     for i in range(1, 20)]
        frames = frames_of(ownership=ownership, nodes=borrowers,
                           borrowers=borrowers)
        result = gq.check_component_concentration(frames)
        assert result.status == gq.FLAG
        assert result.blocks == (gq.CENTRALITY, gq.COMMUNITIES)

    def test_a_fragmented_book_passes(self):
        borrowers = [f"CORP-{i:03d}" for i in range(20)]
        ownership = [edge(graphdata.OWNS, f"CORP-{i:03d}",
                          f"CORP-{i + 1:03d}", ownership_pct=5.0,
                          edge_id=f"E{i}") for i in range(0, 20, 2)]
        frames = frames_of(ownership=ownership, nodes=borrowers,
                           borrowers=borrowers)
        assert gq.check_component_concentration(frames).status == gq.PASS

    def test_a_declared_group_with_no_internal_edge_flags(self):
        master = pd.DataFrame([
            {"borrower_id": "CORP-A", "group_id": "GRP-1"},
            {"borrower_id": "CORP-B", "group_id": "GRP-1"}])
        frames = frames_of(
            ownership=[edge(graphdata.OWNS, "H1", "CORP-A",
                            ownership_pct=50.0)],
            master=master)
        assert gq.check_isolated_group_members(frames).status == gq.FLAG

    def test_a_declared_group_with_an_internal_edge_passes(self):
        master = pd.DataFrame([
            {"borrower_id": "CORP-A", "group_id": "GRP-1"},
            {"borrower_id": "CORP-B", "group_id": "GRP-1"}])
        frames = frames_of(
            ownership=[edge(graphdata.OWNS, "CORP-A", "CORP-B",
                            ownership_pct=50.0)],
            master=master)
        assert gq.check_isolated_group_members(frames).status == gq.PASS


# ------------------------------------------------------ the whole gate


class TestTheGate:
    def test_at_least_fourteen_checks_run(self):
        assert len(gq.CHECKS) + len(gq.DATED_CHECKS) >= 14

    def test_every_check_id_is_unique(self, universe):
        report = gq.run(universe.frames, AS_OF)
        ids = [r.check_id for r in report.results]
        assert len(ids) == len(set(ids))

    def test_every_check_returns_a_declared_status(self, universe):
        report = gq.run(universe.frames, AS_OF)
        assert all(r.status in gq.STATUSES for r in report.results)

    def test_every_check_names_only_known_computations(self, universe):
        report = gq.run(universe.frames, AS_OF)
        for result in report.results:
            for name in result.blocks:
                assert name in gq.COMPUTATIONS

    def test_no_check_raises_on_the_real_universe(self, universe):
        report = gq.run(universe.frames, AS_OF)
        assert not any("raised" in r.observed for r in report.results)

    def test_the_real_graph_has_no_dangling_endpoint(self, universe):
        """Regression: COVERS edges pointed at facility ids that were never
        declared as nodes, so 1,303 of 2,274 guarantee edges led nowhere and
        every edge-first query silently disagreed with every node-first one."""
        report = gq.run(universe.frames, AS_OF)
        found = next(r for r in report.results if r.check_id == "GQ-04")
        assert found.status == gq.PASS

    def test_the_real_graph_has_no_knowledge_from_the_future(self, universe):
        report = gq.run(universe.frames, AS_OF)
        found = next(r for r in report.results if r.check_id == "GQ-07")
        assert found.status == gq.PASS

    def test_the_planted_defective_registers_are_caught(self, universe):
        """The generator plants deliberately impossible registers. If this
        check ever passes, either the plant or the detector has been lost."""
        report = gq.run(universe.frames, AS_OF)
        found = next(r for r in report.results if r.check_id == "GQ-01")
        assert found.status == gq.REJECT
        assert found.affected, "a reject must name who it blocks"

    def test_a_few_bad_registers_do_not_blank_the_whole_book(self, universe):
        report = gq.run(universe.frames, AS_OF)
        assert gq.EFFECTIVE_OWNERSHIP not in report.blocked()
        assert len(report.affected_by(gq.EFFECTIVE_OWNERSHIP)) < 100

    def test_two_runs_produce_the_same_report(self, universe):
        first = gq.run(universe.frames, AS_OF).to_dict()
        second = gq.run(universe.frames, AS_OF).to_dict()
        assert first == second

    def test_the_report_declares_its_version(self, universe):
        payload = gq.run(universe.frames, AS_OF).to_dict()
        assert payload["quality_version"] == gq.QUALITY_VERSION
        assert payload["checks_run"] == len(gq.CHECKS) + len(gq.DATED_CHECKS)

    def test_a_check_that_raises_becomes_a_reject_not_a_crash(
            self, universe, monkeypatch):
        """A gate that crashes has told the caller nothing, and the caller
        will be tempted to skip it. One broken check must not take the other
        fourteen down with it."""
        def explode(_frames):
            raise ValueError("planted")

        monkeypatch.setattr(gq, "CHECKS", (explode, gq.check_self_ownership))
        report = gq.run(universe.frames, AS_OF)

        planted = next(r for r in report.results if r.check_id == "explode")
        assert planted.status == gq.REJECT
        assert "ValueError" in planted.observed
        assert planted.blocks == tuple(gq.COMPUTATIONS)
        # The surviving check still ran and still reported.
        assert any(r.check_id == "GQ-03" for r in report.results)

    def test_a_missing_input_frame_fails_loudly(self, universe):
        """Not a quality finding - a wiring error. Reporting it as a REJECT
        would let a caller that forgot to pass the guarantee frame read the
        result as "the data is bad" and go looking in the wrong place."""
        incomplete = dict(universe.frames)
        del incomplete["corporate_guarantees"]
        with pytest.raises(KeyError):
            gq.run(incomplete, AS_OF)

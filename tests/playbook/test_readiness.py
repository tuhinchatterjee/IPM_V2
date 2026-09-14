"""Completion and readiness are computed, not felt. Gate 3.

Two different questions, never averaged into one number:

* **Completion** — has this been WRITTEN? Required sections present and
  substantive, evidence behind them, tables there, figures resolved, reviewed.
* **Readiness** — may it LEAVE? Period set, evidence current, findings
  answered, decisions framed, actions updated, reviewers finished, nothing
  blocking approval.

A document can be fully written and not remotely ready — a complete committee
pack with an unanswered high finding is exactly that — and these tests pin
that the two move independently.

Everything else here is §26: a percentage a person can take apart. Every
component carries its score, the sentence explaining it, the blocking reason
where there is one, and where to go to fix it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.exports import playbook_contract as contract
from backend.models.playbook import (
    PlaybookAction,
    PlaybookDecision,
    PlaybookFinding,
    PlaybookReadiness,
    PlaybookReview,
)
from backend.playbook import document as D
from backend.playbook import intelligence
from backend.playbook import repository as repo
from backend.playbook.intelligence import binding as bind
from backend.playbook.intelligence import profile as prof
from backend.playbook.intelligence import readiness as score
from backend.playbook.intelligence import sections as sect

ACTOR = "user:7"

#: A committee pack with every required section substantively written.
COMPLETE_PACK = "".join(
    f"## {n}. {name}\n\n" + "considered judgement " * 15 + "\n\n"
    for n, name in enumerate(
        prof.requirements_for(prof.COMMITTEE_REPORT).sections, start=1))


def _artifact(db, workspace, markdown: str, *, version: int = 1):
    """A stored version and its synced section rows."""
    artifact = repo.create_artifact(db, workspace.id, kind="report",
                                    title="Committee pack")
    db.flush()
    doc = D.parse(markdown, title="Committee pack")
    repo.new_version(db, artifact, content=doc.as_dict(),
                     source_manifest={}, content_hash=doc.content_hash(),
                     validation={})
    db.flush()
    sect.sync(db, artifact.id, doc, version=version)
    return artifact, doc


@pytest.fixture
def committee(db, workspace):
    intelligence.classify(db, workspace.id,
                          document_type=prof.COMMITTEE_REPORT, actor=ACTOR,
                          committee_name="Credit Risk Committee",
                          reporting_period="Q2 2026")
    return workspace


# ================================================== completion

@pytest.mark.usefixtures("db")
class TestCompletionAsksWhetherItIsWritten:

    def test_an_empty_workspace_is_not_complete(self, db, workspace):
        """Vacuous truth must not inflate the score. "No findings raised" is
        not 100% dispositioned when nothing has been written at all, and
        counting it as full marks gave an empty workspace a percentage it had
        done nothing to earn."""
        result = score.compute(db, workspace.id)
        assert result.completion_pct == 0
        inapplicable = [c["name"] for c in result.completion_components
                        if not c["applicable"]]
        assert "Findings dispositioned" in inapplicable
        assert "Metrics resolved" in inapplicable

    def test_missing_sections_are_named(self, db, workspace, committee):
        _artifact(db, workspace,
                  "## 1. Executive summary\n\n" + "words " * 30)
        result = score.compute(db, workspace.id)
        assert "Findings" in result.missing
        assert "Decisions requested" in result.missing
        assert "Executive summary" not in result.missing

    def test_a_heading_with_no_substance_does_not_count_as_written(
            self, db, workspace, committee):
        """A heading with one sentence under it is a placeholder, and calling
        it complete is how a pack reaches a committee half-written."""
        _artifact(db, workspace, "## 1. Executive summary\n\nTo follow.\n")
        assert "Executive summary" in score.compute(db, workspace.id).missing

    def test_the_weights_come_from_the_document_type(self, db, workspace):
        """A development report earns completeness from having written its
        sections; a committee pack from having dispositioned what it raised."""
        intelligence.classify(db, workspace.id,
                              document_type=prof.MODEL_DEVELOPMENT,
                              actor=ACTOR)
        _artifact(db, workspace, COMPLETE_PACK)
        result = score.compute(db, workspace.id)
        weights = {c["name"]: c["explanation"]
                   for c in result.completion_components}
        assert "weight 50%" in weights["Required sections"]

        intelligence.classify(db, workspace.id,
                              document_type=prof.COMMITTEE_REPORT,
                              actor=ACTOR)
        again = score.compute(db, workspace.id)
        weights = {c["name"]: c["explanation"]
                   for c in again.completion_components}
        assert "weight 30%" in weights["Required sections"]

    def test_every_completion_component_explains_itself(self, db, workspace,
                                                        committee):
        _artifact(db, workspace, COMPLETE_PACK)
        result = score.compute(db, workspace.id)
        assert len(result.completion_components) == len(prof.COMPONENTS)
        for component in result.completion_components:
            assert component["explanation"]
            assert component["link"]
            assert component["status"] in (score.GREEN, score.AMBER, score.RED,
                                           score.NOT_APPLICABLE)

    def test_a_fully_written_pack_scores_its_sections_at_one_hundred(
            self, db, workspace, committee):
        _artifact(db, workspace, COMPLETE_PACK)
        result = score.compute(db, workspace.id)
        sections = next(c for c in result.completion_components
                        if c["name"] == "Required sections")
        assert sections["score"] == 100
        assert result.missing == []


# ================================================== readiness

@pytest.mark.usefixtures("db")
class TestReadinessAsksWhetherItMayLeave:

    def test_written_and_ready_are_different_questions(self, db, workspace,
                                                       committee):
        """The case that makes the separation necessary: a complete pack with
        an unanswered high finding."""
        _artifact(db, workspace, COMPLETE_PACK)
        db.add(PlaybookFinding(workspace_id=workspace.id, reference="F-01",
                               title="Bad rate deteriorated", severity="high",
                               blocking=True, status="open"))
        db.flush()
        result = score.compute(db, workspace.id)

        sections = next(c for c in result.completion_components
                        if c["name"] == "Required sections")
        assert sections["score"] == 100          # fully written
        assert result.approval_status == score.BLOCKED   # not ready

    def test_a_blocking_finding_names_itself_in_the_blocker(self, db,
                                                            workspace,
                                                            committee):
        db.add(PlaybookFinding(workspace_id=workspace.id, reference="F-02",
                               title="Coverage fell", severity="high",
                               blocking=True))
        db.flush()
        result = score.compute(db, workspace.id)
        assert any("F-02" in b["reason"] for b in result.blockers)
        assert any(b["link"] == "findings" for b in result.blockers)

    def test_an_answer_alone_does_not_stop_a_finding_blocking(
            self, db, workspace, committee):
        """A drafted answer nobody stood behind has disposed of nothing.
        §6B turns on exactly this distinction, so it is asserted here as well
        as in the governance suite."""
        finding = PlaybookFinding(workspace_id=workspace.id, reference="F-03",
                                  title="X", severity="high", blocking=True)
        db.add(finding)
        db.flush()
        assert score.compute(db, workspace.id).approval_status == score.BLOCKED

        finding.status = "answered"
        finding.answer = "Explained by the seasonal cohort mix."
        finding.answered_by = ACTOR
        db.flush()
        assert any("F-03" in b["reason"]
                   for b in score.compute(db, workspace.id).blockers)

    def test_accepting_a_finding_stops_it_blocking(self, db, workspace,
                                                   committee):
        finding = PlaybookFinding(workspace_id=workspace.id, reference="F-03",
                                  title="X", severity="high", blocking=True,
                                  answer="Seasonal cohort mix.")
        db.add(finding)
        db.flush()
        finding.status = "accepted"
        finding.resolved_by = ACTOR
        db.flush()
        # The pack may still be blocked for other reasons — a missing meeting
        # date, no decision requested. What must be gone is THIS blocker.
        assert not any("F-03" in b["reason"]
                       for b in score.compute(db, workspace.id).blockers)

    def test_a_committee_pack_with_no_decision_is_not_ready(self, db,
                                                            workspace,
                                                            committee):
        """§13. A committee paper that asks for nothing has not been written
        as a committee paper."""
        _artifact(db, workspace, COMPLETE_PACK)
        result = score.compute(db, workspace.id)
        assert result.approval_status in (score.BLOCKED, score.PENDING)
        assert any("decision" in b["reason"].lower() for b in result.blockers)

    def test_a_decision_with_no_recommendation_blocks(self, db, workspace,
                                                      committee):
        db.add(PlaybookDecision(workspace_id=workspace.id, reference="D1",
                                question="Tighten the cut-off?",
                                recommendation=""))
        db.flush()
        result = score.compute(db, workspace.id)
        assert any("recommendation" in b["reason"] for b in result.blockers)

    def test_an_incomplete_reviewer_blocks_a_committee_pack(self, db,
                                                            workspace,
                                                            committee):
        db.add(PlaybookReview(workspace_id=workspace.id, reviewer="a.person",
                              role="model risk", status="requested"))
        db.flush()
        result = score.compute(db, workspace.id)
        assert any("reviewer" in b["reason"] for b in result.blockers)

    def test_an_overdue_action_blocks_a_committee_pack(self, db, workspace,
                                                       committee):
        db.add(PlaybookAction(workspace_id=workspace.id, title="Recalibrate",
                              due_date=date.today() - timedelta(days=3),
                              status="open"))
        db.flush()
        result = score.compute(db, workspace.id)
        assert any("overdue" in b["reason"] for b in result.blockers)

    def test_a_completed_action_that_is_late_does_not_block(self, db,
                                                            workspace,
                                                            committee):
        db.add(PlaybookAction(workspace_id=workspace.id, title="Done",
                              due_date=date.today() - timedelta(days=3),
                              status="complete",
                              last_update_at=datetime.now(UTC)))
        db.flush()
        result = score.compute(db, workspace.id)
        assert not any("overdue" in b["reason"] for b in result.blockers)

    def test_a_missing_meeting_date_blocks_a_committee_pack(self, db,
                                                            workspace,
                                                            committee):
        result = score.compute(db, workspace.id)
        assert any("meeting date" in b["reason"] for b in result.blockers)

    def test_a_general_document_is_not_held_to_committee_rules(self, db,
                                                               workspace):
        """Committee furniture is not imposed on a document that is not one."""
        intelligence.classify(db, workspace.id,
                              document_type=prof.PORTFOLIO_REVIEW,
                              actor=ACTOR, reporting_period="Q2 2026")
        _artifact(db, workspace, COMPLETE_PACK)
        result = score.compute(db, workspace.id)
        names = [c["name"] for c in result.components]
        assert "Decisions framed" not in names
        assert not any("decision" in b["reason"].lower()
                       for b in result.blockers)


# ================================================== the governed-metric rule

@pytest.mark.usefixtures("db")
class TestASuggestionNeverCountsAsLinkedData:
    """The product rule, at the readiness layer: an unconfirmed suggestion may
    reduce metric linkage coverage but must never be treated as linked."""

    def test_a_suggestion_lowers_the_metric_score(self, db, workspace,
                                                  committee):
        bind.apply(db, workspace.id, bind.from_export(
            [contract.Metric(metric_id="retail.default_rate", label="DR")]))
        bind.apply(db, workspace.id, bind.from_labels(
            [("Gini", "0.415", "0.4152", "B2")], locator="xlsx://P!A1"))
        metrics = next(c for c in score.compute(db, workspace.id).components
                       if c["name"] == "Metrics reconciled")
        assert metrics["score"] == 50
        assert "1 suggested link(s) await confirmation" in metrics[
            "explanation"]

    def test_confirming_it_raises_the_score(self, db, workspace, committee):
        [row] = bind.apply(db, workspace.id, bind.from_labels(
            [("Gini", "0.415", "0.4152", "B2")], locator="xlsx://P!A1"))
        assert next(c for c in score.compute(db, workspace.id).components
                    if c["name"] == "Metrics reconciled")["score"] == 0

        bind.confirm(db, row, actor=ACTOR)
        assert next(c for c in score.compute(db, workspace.id).components
                    if c["name"] == "Metrics reconciled")["score"] == 100

    def test_a_suggestion_never_blocks_approval(self, db, workspace,
                                                committee):
        """It lowers a score. It does not become a gate."""
        bind.apply(db, workspace.id, bind.from_labels(
            [("Gini", "0.415", "0.4152", "B2")], locator="xlsx://P!A1"))
        blockers = score.compute(db, workspace.id).blockers
        assert not any("metric" in b["reason"].lower() for b in blockers)


# ================================================== auditability

@pytest.mark.usefixtures("db")
class TestEveryNumberCanBeTakenApart:

    def test_each_component_carries_its_working(self, db, workspace,
                                                committee):
        _artifact(db, workspace, COMPLETE_PACK)
        for component in score.compute(db, workspace.id).components:
            assert component["name"]
            assert component["explanation"], component["name"]
            assert component["link"], component["name"]
            assert "status" in component

    def test_status_is_a_word_and_not_only_a_colour(self, db, workspace,
                                                    committee):
        for component in score.compute(db, workspace.id).components:
            assert component["status"] in (score.GREEN, score.AMBER, score.RED,
                                           score.NOT_APPLICABLE)

    def test_a_component_that_does_not_apply_says_so_rather_than_scoring_zero(
            self, db, workspace, committee):
        """No actions were raised. That is not 0% of actions updated."""
        actions = next(c for c in score.compute(db, workspace.id).components
                       if c["name"] == "Actions updated")
        assert actions["applicable"] is False
        assert actions["status"] == score.NOT_APPLICABLE
        assert actions["score"] is None

    def test_the_working_is_stored_beside_the_score(self, db, workspace,
                                                    committee):
        """§26 has to be answerable by reading the row, not by recomputing."""
        score.compute(db, workspace.id)
        row = (db.query(PlaybookReadiness)
               .filter(PlaybookReadiness.workspace_id == workspace.id).one())
        assert row.components and row.components[0]["explanation"]
        assert "completion_components" in row.statistics

    def test_recomputing_is_idempotent(self, db, workspace, committee):
        """Same rows, same score. A dashboard that drifts on refresh is one
        nobody can act on."""
        _artifact(db, workspace, COMPLETE_PACK)
        first = score.compute(db, workspace.id).as_dict()
        second = score.compute(db, workspace.id).as_dict()
        assert first == second
        assert db.query(PlaybookReadiness).filter(
            PlaybookReadiness.workspace_id == workspace.id).count() == 1

    def test_nothing_in_the_scorer_calls_a_provider(self, db, workspace,
                                                    committee, monkeypatch):
        from backend.playbook import provider

        def explode(*a, **k):
            raise AssertionError("the scorer called a provider")

        monkeypatch.setattr(provider, "author", explode)
        score.compute(db, workspace.id)


# ================================================== through the dashboard

@pytest.mark.usefixtures("db")
class TestTheDashboardCarriesIt:

    def test_a_first_open_scores_rather_than_showing_zeros(self, db,
                                                           workspace,
                                                           committee):
        """A document nobody has scored has no readiness. Showing 0% would
        read as "nothing is ready" rather than "nobody has looked"."""
        _artifact(db, workspace, COMPLETE_PACK)
        state = intelligence.dashboard(db, workspace.id).as_dict()
        assert state["readiness"]["computed"] is True
        assert state["readiness"]["components"]

    def test_an_empty_thread_is_not_scored_at_all(self, db, workspace):
        state = intelligence.dashboard(db, workspace.id).as_dict()
        assert state["available"] is False
        assert state["readiness"]["computed"] is False

    def test_page_count_reaches_the_dashboard_statistics(self, db, workspace,
                                                         committee):
        _artifact(db, workspace, COMPLETE_PACK)
        stats = intelligence.dashboard(db, workspace.id).as_dict()[
            "statistics"]
        assert stats["sections"] == len(
            prof.requirements_for(prof.COMMITTEE_REPORT).sections)
        assert stats["page_count_source"] == "not rendered"

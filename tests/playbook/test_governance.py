"""Findings, decisions and actions as governed objects. Gates 6 and 7.

The boundary these tests exist to hold, stated once:

    Claude may identify, draft, suggest and explain. It may not record the
    committee's decision, impersonate the decision maker, mark approval
    complete, close a formal finding, or claim an action was done.

That is enforced in one place — `require_person` — and every formal act goes
through it. `SYSTEM_ACTORS` is why passing "claude" or "system" as an actor
does not get past the guard: a governance row attributed to a machine is not a
record anybody can be held to.

Two distinctions the tests turn on, because both are easy to lose:

* **answered is not accepted.** A drafted answer nobody stood behind is still
  an open question, and a blocking finding keeps blocking until a person
  disposes of it.
* **the external system's status is not ours.** A planner saying "done" is
  evidence; a person here still decides whether the action is complete.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.models.playbook import PlaybookAction, PlaybookFinding
from backend.playbook import intelligence
from backend.playbook.intelligence import governance as gov
from backend.playbook.intelligence import profile as prof
from backend.playbook.intelligence import readiness as score

ACTOR = "user:7"
OTHER = "user:9"


@pytest.fixture
def committee(db, workspace):
    intelligence.classify(db, workspace.id,
                          document_type=prof.COMMITTEE_REPORT, actor=ACTOR,
                          committee_name="Credit Risk Committee",
                          reporting_period="Q2 2026")
    return workspace


# ================================================== who may act at all

class TestOnlyAPersonPerformsAFormalAct:

    @pytest.mark.parametrize("actor", ["", "   ", "system", "claude",
                                       "assistant", "AI", "Bot", "model",
                                       "playbook"])
    def test_a_machine_identity_is_not_a_person(self, actor):
        """Passing "claude" where an actor is required must not get past the
        guard. A governance row attributed to a machine is not a record
        anybody can be held to."""
        with pytest.raises(gov.NotPermitted):
            gov.require_person(actor, "Recording a decision")

    def test_a_person_passes_and_is_trimmed(self):
        assert gov.require_person("  user:7  ", "x") == "user:7"


# ================================================== Gate 6: findings

@pytest.mark.usefixtures("db")
class TestAFindingKnowsWhereItCameFrom:

    def test_every_origin_is_explicit(self, db, workspace):
        for origin in gov.ORIGINS:
            row = gov.raise_finding(
                db, workspace.id, title=f"From {origin}", origin=origin,
                actor=ACTOR if origin == gov.FROM_HUMAN else "")
            assert row.raised_by == origin
            assert gov.ORIGIN_LABELS[origin]

    def test_an_unknown_origin_is_refused(self, db, workspace):
        with pytest.raises(gov.TransitionRefused):
            gov.raise_finding(db, workspace.id, title="X", origin="vibes")

    def test_a_human_raised_finding_needs_the_human(self, db, workspace):
        with pytest.raises(gov.NotPermitted):
            gov.raise_finding(db, workspace.id, title="X",
                              origin=gov.FROM_HUMAN, actor="")

    def test_a_rule_may_raise_one_without_a_person(self, db, workspace):
        """A threshold that fired is not somebody's opinion."""
        row = gov.raise_finding(db, workspace.id, title="Breach",
                                origin=gov.FROM_RULE, severity=gov.HIGH)
        assert row.status == gov.OPEN
        assert row.history[0]["act"] == "raised"

    def test_it_carries_the_movement_that_raised_it(self, db, workspace):
        row = gov.raise_finding(
            db, workspace.id, origin=gov.FROM_CHANGE, severity=gov.HIGH,
            title="Application cohort bad rate deteriorated",
            metric_id="application.cohort_bad_rate", threshold="+0.40pp",
            previous_value="5.86%", current_value="6.47%", delta="+0.61pp",
            source_locator="export://41/rev/2#t.book", section_key="book-1")
        assert row.metric_id == "application.cohort_bad_rate"
        assert (row.previous_value, row.current_value, row.delta) == \
            ("5.86%", "6.47%", "+0.61pp")
        assert row.source_locator == "export://41/rev/2#t.book"


@pytest.mark.usefixtures("db")
class TestAnAiSuggestionNeverSilentlyBlocks:
    """§6B. The one rule that keeps a model's opinion out of the approval bar."""

    @pytest.mark.parametrize("origin", [gov.FROM_AI, gov.FROM_IMPORT])
    def test_it_is_downgraded_and_the_downgrade_is_recorded(self, db,
                                                            workspace,
                                                            origin):
        row = gov.raise_finding(db, workspace.id, title="Looks wrong",
                                origin=origin, severity=gov.HIGH,
                                blocking=True)
        assert row.blocking is False
        assert "may not set that on its own" in row.history[0]["reason"]

    @pytest.mark.parametrize("origin", sorted(gov.MAY_AUTO_BLOCK))
    def test_a_deterministic_origin_may_block(self, db, workspace, origin):
        row = gov.raise_finding(db, workspace.id, title="Breach",
                                origin=origin, severity=gov.HIGH,
                                blocking=True)
        assert row.blocking is True

    def test_a_person_may_make_a_suggestion_blocking(self, db, workspace):
        row = gov.raise_finding(db, workspace.id, title="Looks wrong",
                                origin=gov.FROM_AI, severity=gov.HIGH,
                                blocking=True)
        gov.set_blocking(db, row, blocking=True, actor=ACTOR,
                         reason="agreed at the pre-meeting")
        assert row.blocking is True
        assert row.history[-1]["actor"] == ACTOR
        assert row.history[-1]["act"] == "set_blocking"

    def test_a_machine_may_not(self, db, workspace):
        row = gov.raise_finding(db, workspace.id, title="X",
                                origin=gov.FROM_AI, severity=gov.HIGH)
        with pytest.raises(gov.NotPermitted):
            gov.set_blocking(db, row, blocking=True, actor="claude")


@pytest.mark.usefixtures("db")
class TestAnsweredIsNotAccepted:

    @pytest.fixture
    def finding(self, db, workspace):
        return gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE,
                                 title="Bad rate deteriorated",
                                 severity=gov.HIGH, blocking=True,
                                 reference="F-01")

    def test_claude_may_draft_an_answer_and_nothing_moves(self, db, finding):
        gov.draft_answer(db, finding, answer="Seasonal cohort mix.")
        assert finding.answer == "Seasonal cohort mix."
        assert finding.status == gov.OPEN
        assert finding.answered_by == ""
        assert finding.history[-1]["actor"] == "claude"
        assert finding.history[-1]["act"] == "drafted_answer"

    def test_a_drafted_answer_still_counts_against_the_document(self, db,
                                                                finding):
        gov.draft_answer(db, finding, answer="Seasonal cohort mix.")
        assert gov.blocking_unresolved([finding]) == [finding]

    def test_a_person_accepts_the_answer(self, db, finding):
        gov.draft_answer(db, finding, answer="Seasonal cohort mix.")
        gov.move_finding(db, finding, to=gov.ANSWERED, actor=ACTOR)
        assert finding.answered_by == ACTOR and finding.answered_at

    def test_answered_is_still_unresolved(self, db, finding):
        gov.move_finding(db, finding, to=gov.ANSWERED, actor=ACTOR,
                         answer="Seasonal cohort mix.")
        assert gov.unresolved([finding]) == [finding]
        assert gov.blocking_unresolved([finding]) == [finding]

    def test_accepting_disposes_of_it(self, db, finding):
        gov.move_finding(db, finding, to=gov.ANSWERED, actor=ACTOR,
                         answer="Seasonal cohort mix.")
        gov.move_finding(db, finding, to=gov.ACCEPTED, actor=OTHER,
                         reason="committee satisfied")
        assert gov.unresolved([finding]) == []
        assert finding.resolved_by == OTHER and finding.resolved_at

    def test_answering_with_no_answer_is_refused(self, db, finding):
        with pytest.raises(gov.TransitionRefused):
            gov.move_finding(db, finding, to=gov.ANSWERED, actor=ACTOR)


@pytest.mark.usefixtures("db")
class TestClosingDeferringAndReopening:

    @pytest.fixture
    def finding(self, db, workspace):
        return gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE,
                                 title="X", severity=gov.MEDIUM)

    def test_closing_requires_a_human(self, db, finding):
        with pytest.raises(gov.NotPermitted):
            gov.move_finding(db, finding, to=gov.CLOSED, actor="claude",
                             reason="looks fine")
        assert finding.status == gov.OPEN

    def test_closing_requires_a_rationale(self, db, finding):
        """"Closed" with no reason is the state a governed document can least
        afford: next quarter nobody can tell handled from forgotten."""
        with pytest.raises(gov.TransitionRefused) as raised:
            gov.move_finding(db, finding, to=gov.CLOSED, actor=ACTOR)
        assert "rationale" in str(raised.value)

    def test_deferring_records_the_rationale_and_the_person(self, db,
                                                            finding):
        gov.move_finding(db, finding, to=gov.DEFERRED, actor=ACTOR,
                         reason="deferred to the March meeting")
        assert finding.status == gov.DEFERRED
        assert finding.resolved_by == ACTOR
        assert "March" in finding.resolution
        assert finding.history[-1]["reason"] == "deferred to the March meeting"

    def test_a_deferred_finding_may_be_reopened(self, db, finding):
        gov.move_finding(db, finding, to=gov.DEFERRED, actor=ACTOR,
                         reason="deferred")
        gov.move_finding(db, finding, to=gov.OPEN, actor=ACTOR,
                         reason="raised again in March")
        assert finding.status == gov.OPEN
        assert finding.resolved_by == "" and finding.resolved_at is None

    def test_an_illegal_move_names_what_is_legal(self, db, finding):
        gov.move_finding(db, finding, to=gov.CLOSED, actor=ACTOR,
                         reason="done")
        with pytest.raises(gov.TransitionRefused) as raised:
            gov.move_finding(db, finding, to=gov.DEFERRED, actor=ACTOR,
                             reason="x")
        assert "cannot become" in str(raised.value) and "open" in str(
            raised.value)

    def test_assigning_an_owner_names_both(self, db, finding):
        gov.assign_finding(db, finding, owner="a.owner", actor=ACTOR)
        assert finding.owner == "a.owner"
        assert finding.history[-1]["actor"] == ACTOR

    def test_every_move_is_audited(self, db, finding):
        gov.move_finding(db, finding, to=gov.ANSWERED, actor=ACTOR,
                         answer="Because.")
        gov.move_finding(db, finding, to=gov.ACCEPTED, actor=OTHER,
                         reason="agreed")
        acts = [h["act"] for h in finding.history]
        assert acts == ["raised", gov.ANSWERED, gov.ACCEPTED]
        assert finding.history[-1]["from"] == gov.ANSWERED
        assert finding.history[-1]["actor"] == OTHER
        assert all(h["at"] for h in finding.history)


class TestAFindingSaysWhatItRestsOn:
    """A finding that asserts a number moved is arguable only if it says
    where the numbers came from."""

    @pytest.fixture
    def finding(self, db, workspace):
        return gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE,
                                 title="Coverage fell", severity=gov.HIGH)

    def test_attaching_evidence_names_the_person(self, db, finding):
        gov.attach_evidence(db, finding, actor=ACTOR,
                            locator="xlsx://Coverage!B12",
                            previous_value="6.50%", current_value="5.86%",
                            delta="-0.64pp")
        assert finding.source_locator == "xlsx://Coverage!B12"
        assert finding.previous_value == "6.50%"
        assert finding.delta == "-0.64pp"
        assert finding.history[-1]["act"] == "evidence_attached"
        assert finding.history[-1]["actor"] == ACTOR

    def test_a_machine_cannot_attach_evidence(self, db, finding):
        with pytest.raises(gov.NotPermitted):
            gov.attach_evidence(db, finding, actor="claude",
                                locator="xlsx://Coverage!B12")
        assert finding.source_locator == ""

    def test_attaching_nothing_is_refused(self, db, finding):
        with pytest.raises(gov.TransitionRefused) as raised:
            gov.attach_evidence(db, finding, actor=ACTOR, note="looks bad")
        assert "needs some evidence" in str(raised.value)

    def test_values_already_recorded_are_left_alone(self, db, finding):
        """Recorded as read, and not recomputed: a second attachment that
        names only a locator does not blank the figures beside it."""
        gov.attach_evidence(db, finding, actor=ACTOR, previous_value="6.50%",
                            current_value="5.86%")
        gov.attach_evidence(db, finding, actor=OTHER,
                            locator="xlsx://Coverage!B12")
        assert finding.previous_value == "6.50%"
        assert finding.current_value == "5.86%"
        assert finding.source_locator == "xlsx://Coverage!B12"
        assert len(finding.history) == 3


# ================================================== Gate 7: decisions

@pytest.mark.usefixtures("db")
class TestADecisionIsRecordedByAPerson:

    @pytest.fixture
    def decision(self, db, workspace):
        return gov.propose_decision(
            db, workspace.id, reference="D1",
            question="Tighten the minimum application score?",
            recommendation="Recommended: the cohort bad rate has breached "
                           "the stated threshold.",
            options=[gov.APPROVE, gov.REJECT, gov.MODIFY, gov.DEFER],
            current_position="580", proposed_position="600",
            drafted_by_claude=True)

    def test_claude_may_draft_the_question_and_the_recommendation(self, db,
                                                                  decision):
        assert decision.status == gov.PROPOSED
        assert decision.recommendation
        assert decision.history[0]["actor"] == "claude"
        assert decision.decided_by == "" and decision.outcome == ""

    def test_a_proposed_decision_cannot_be_recorded(self, db, decision):
        """It has to be put to the committee before it can be taken."""
        with pytest.raises(gov.TransitionRefused) as raised:
            gov.record(db, decision, outcome=gov.APPROVE, actor=ACTOR)
        assert "not ready" in str(raised.value)

    def test_a_person_records_the_outcome(self, db, decision):
        gov.move_decision(db, decision, to=gov.READY_FOR_DECISION, actor=ACTOR)
        gov.record(db, decision, outcome=gov.APPROVE, actor=OTHER,
                   rationale="approved with effect from next month",
                   meeting="CRC 2026-07")
        assert decision.status == gov.DECIDED
        assert decision.outcome == gov.APPROVE
        assert decision.decided_by == OTHER and decision.decided_at
        assert decision.meeting == "CRC 2026-07"

    @pytest.mark.parametrize("identity", ["claude", "system", "assistant",
                                          ""])
    def test_a_machine_can_never_record_a_decision(self, db, decision,
                                                   identity):
        gov.move_decision(db, decision, to=gov.READY_FOR_DECISION, actor=ACTOR)
        with pytest.raises(gov.NotPermitted):
            gov.record(db, decision, outcome=gov.APPROVE, actor=identity)
        assert decision.status == gov.READY_FOR_DECISION
        assert decision.decided_by == ""

    def test_move_decision_refuses_to_reach_decided(self, db, decision):
        """The only door into DECIDED is `record`, which demands an outcome
        and a decision maker."""
        gov.move_decision(db, decision, to=gov.READY_FOR_DECISION, actor=ACTOR)
        with pytest.raises(gov.TransitionRefused) as raised:
            gov.move_decision(db, decision, to=gov.DECIDED, actor=ACTOR)
        assert "Use `record`" in str(raised.value)

    def test_a_decision_is_recorded_once(self, db, decision):
        gov.move_decision(db, decision, to=gov.READY_FOR_DECISION, actor=ACTOR)
        gov.record(db, decision, outcome=gov.APPROVE, actor=ACTOR)
        with pytest.raises(gov.TransitionRefused) as raised:
            gov.record(db, decision, outcome=gov.REJECT, actor=OTHER)
        assert "already been recorded" in str(raised.value)
        assert decision.outcome == gov.APPROVE

    def test_deferring_needs_a_rationale(self, db, decision):
        gov.move_decision(db, decision, to=gov.READY_FOR_DECISION, actor=ACTOR)
        with pytest.raises(gov.TransitionRefused):
            gov.move_decision(db, decision, to=gov.DECISION_DEFERRED,
                              actor=ACTOR)
        gov.move_decision(db, decision, to=gov.DECISION_DEFERRED, actor=ACTOR,
                          reason="awaiting the recalibration")
        assert decision.status == gov.DECISION_DEFERRED

    def test_an_unknown_outcome_is_refused(self, db, decision):
        gov.move_decision(db, decision, to=gov.READY_FOR_DECISION, actor=ACTOR)
        with pytest.raises(gov.TransitionRefused):
            gov.record(db, decision, outcome="maybe", actor=ACTOR)


@pytest.mark.usefixtures("db")
class TestADecisionAffectsReadiness:

    def test_a_committee_pack_with_no_decision_is_not_ready(self, db,
                                                            workspace,
                                                            committee):
        result = score.compute(db, workspace.id)
        assert any("decision" in b["reason"].lower()
                   for b in result.blockers)

    def test_an_undecided_decision_still_counts_as_outstanding(self, db,
                                                               workspace,
                                                               committee):
        gov.propose_decision(db, workspace.id, question="Tighten?",
                             recommendation="Recommended.")
        state = intelligence.dashboard(db, workspace.id).as_dict()
        assert state["decisions"]["outstanding"] == 1
        assert state["decisions"]["decided"] == 0

    def test_a_recorded_decision_is_no_longer_outstanding(self, db, workspace,
                                                          committee):
        decision = gov.propose_decision(db, workspace.id, question="Tighten?",
                                        recommendation="Recommended.")
        gov.move_decision(db, decision, to=gov.READY_FOR_DECISION, actor=ACTOR)
        gov.record(db, decision, outcome=gov.APPROVE, actor=ACTOR)
        state = intelligence.dashboard(db, workspace.id).as_dict()
        assert state["decisions"]["outstanding"] == 0
        assert state["decisions"]["decided"] == 1


# ================================================== Gate 7: actions

@pytest.mark.usefixtures("db")
class TestActionsFollowDecisions:

    @pytest.fixture
    def decided(self, db, workspace):
        decision = gov.propose_decision(db, workspace.id, reference="D1",
                                        question="Tighten?",
                                        recommendation="Recommended.")
        gov.move_decision(db, decision, to=gov.READY_FOR_DECISION, actor=ACTOR)
        gov.record(db, decision, outcome=gov.APPROVE, actor=ACTOR)
        return decision

    def test_actions_are_created_from_a_recorded_decision(self, db, decided):
        [action] = gov.actions_from_decision(
            db, decided, actor=ACTOR,
            actions=[{"title": "Recalibrate the cut-off",
                      "owner": "a.owner",
                      "due_date": date.today() + timedelta(days=30)}])
        assert action.decision_id == decided.id
        assert action.status == gov.ACTION_OPEN
        assert "decision D1" in action.history[0]["reason"]

    def test_actions_may_not_precede_the_decision(self, db, workspace):
        """Work that exists because of a decision nobody made is how a pack
        ends up describing unauthorised activity."""
        decision = gov.propose_decision(db, workspace.id, question="Tighten?")
        with pytest.raises(gov.TransitionRefused):
            gov.actions_from_decision(db, decision, actor=ACTOR,
                                      actions=[{"title": "Do it"}])

    def test_creating_actions_needs_a_person(self, db, decided):
        with pytest.raises(gov.NotPermitted):
            gov.actions_from_decision(db, decided, actor="claude",
                                      actions=[{"title": "Do it"}])


@pytest.mark.usefixtures("db")
class TestTheLifeOfAnAction:

    @pytest.fixture
    def action(self, db, workspace):
        return gov.create_action(db, workspace.id, title="Recalibrate",
                                 owner="a.owner", actor=ACTOR,
                                 due_date=date.today() + timedelta(days=7))

    def test_it_moves_through_its_statuses(self, db, action):
        gov.move_action(db, action, to=gov.IN_PROGRESS, actor=ACTOR,
                        note="started")
        gov.move_action(db, action, to=gov.ACTION_BLOCKED, actor=ACTOR,
                        note="waiting on IT")
        gov.move_action(db, action, to=gov.COMPLETED, actor=OTHER,
                        note="released")
        assert action.status == gov.COMPLETED
        assert action.completed_by == OTHER and action.completed_at

    def test_completing_needs_a_person(self, db, action):
        with pytest.raises(gov.NotPermitted):
            gov.move_action(db, action, to=gov.COMPLETED, actor="claude")
        assert action.status == gov.ACTION_OPEN

    def test_cancelling_needs_a_reason(self, db, action):
        with pytest.raises(gov.TransitionRefused):
            gov.move_action(db, action, to=gov.CANCELLED, actor=ACTOR)

    def test_reopening_clears_the_completion(self, db, action):
        gov.move_action(db, action, to=gov.COMPLETED, actor=ACTOR)
        gov.move_action(db, action, to=gov.ACTION_OPEN, actor=ACTOR)
        assert action.completed_by == "" and action.completed_at is None

    def test_an_update_is_recorded_without_moving_it(self, db, action):
        gov.update_action(db, action, note="half done", actor=ACTOR)
        assert action.status == gov.ACTION_OPEN
        assert action.last_update == "half done"
        assert action.notes[-1]["actor"] == ACTOR

    def test_an_overdue_action_is_overdue_until_it_is_finished(self, db,
                                                               workspace):
        late = gov.create_action(db, workspace.id, title="Late",
                                 due_date=date.today() - timedelta(days=3),
                                 actor=ACTOR)
        assert gov.overdue([late]) == [late]
        gov.move_action(db, late, to=gov.COMPLETED, actor=ACTOR)
        assert gov.overdue([late]) == []

    def test_an_overdue_action_reaches_readiness(self, db, workspace,
                                                 committee):
        gov.create_action(db, workspace.id, title="Late", actor=ACTOR,
                          due_date=date.today() - timedelta(days=3))
        assert any("overdue" in b["reason"]
                   for b in score.compute(db, workspace.id).blockers)

    def test_a_completed_late_action_does_not_block(self, db, workspace,
                                                    committee):
        late = gov.create_action(db, workspace.id, title="Late", actor=ACTOR,
                                 due_date=date.today() - timedelta(days=3))
        gov.move_action(db, late, to=gov.COMPLETED, actor=ACTOR)
        assert not any("overdue" in b["reason"]
                       for b in score.compute(db, workspace.id).blockers)


# ================================================== the planner seam

@pytest.mark.usefixtures("db")
class TestThePlannerIsOptional:

    @pytest.fixture
    def action(self, db, workspace):
        return gov.create_action(db, workspace.id, title="Recalibrate",
                                 owner="a.owner", actor=ACTOR,
                                 description="Move the cut-off to 600.")

    def test_playbook_is_whole_without_one(self, db, action):
        assert action.external_system == "" and action.external_ref == ""
        assert action.status == gov.ACTION_OPEN

    def test_the_export_payload_is_self_describing(self, db, action):
        payload = gov.export_payload(action)
        assert payload["source"] == "playbook"
        assert payload["title"] == "Recalibrate"
        assert payload["description"] == "Move the cut-off to 600."

    def test_exporting_records_who_did_it(self, db, action):
        gov.record_export(db, action, system=gov.PLANNER,
                          external_ref="PP-4521", actor=ACTOR)
        assert action.external_ref == "PP-4521"
        assert action.external_synced_at is not None
        assert action.history[-1]["actor"] == ACTOR

    def test_the_external_status_is_evidence_and_not_our_status(self, db,
                                                                action):
        """A planner saying "done" does not complete an action here. A person
        does. That keeps the audit truthful when the two disagree."""
        gov.record_export(db, action, system=gov.PLANNER,
                          external_ref="PP-4521", actor=ACTOR)
        gov.read_back(db, action, external_status="completed")
        assert action.external_status == "completed"
        assert action.status == gov.ACTION_OPEN
        assert action.completed_by == ""


# ================================================== persistence and retries

@pytest.mark.usefixtures("db")
class TestItSurvivesAndDoesNotDuplicate:

    def test_state_and_audit_survive_a_reload(self, db, workspace):
        finding = gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE,
                                    title="X", severity=gov.HIGH,
                                    reference="F-01")
        gov.move_finding(db, finding, to=gov.DEFERRED, actor=ACTOR,
                         reason="deferred to March")
        finding_id = finding.id
        db.expire_all()

        again = db.get(PlaybookFinding, finding_id)
        assert again.status == gov.DEFERRED
        assert again.resolved_by == ACTOR
        assert [h["act"] for h in again.history] == ["raised", gov.DEFERRED]

    def test_a_repeated_move_writes_no_second_audit_entry(self, db,
                                                          workspace):
        """A retry must not grow the trail. The same state twice is one
        event, not two."""
        finding = gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE,
                                    title="X")
        gov.move_finding(db, finding, to=gov.ANSWERED, actor=ACTOR,
                         answer="Because.")
        before = len(finding.history)
        gov.move_finding(db, finding, to=gov.ANSWERED, actor=ACTOR,
                         answer="Because.")
        assert len(finding.history) == before

    def test_a_repeated_action_update_does_not_duplicate_the_row(self, db,
                                                                 workspace):
        action = gov.create_action(db, workspace.id, title="X", actor=ACTOR)
        for _ in range(3):
            gov.move_action(db, action, to=gov.IN_PROGRESS, actor=ACTOR,
                            note="started")
        assert db.query(PlaybookAction).filter(
            PlaybookAction.workspace_id == workspace.id).count() == 1
        assert sum(1 for h in action.history
                   if h["act"] == gov.IN_PROGRESS) == 1

    def test_a_finding_belongs_to_its_workspace_only(self, db, scope):
        """Tenant boundary. Two workspaces, and neither sees the other's
        governance rows."""
        from backend.playbook import repository as repo

        mine = repo.create_workspace(db, scope, title="Mine",
                                     document_family="report")
        theirs = repo.create_workspace(db, scope, title="Theirs",
                                       document_family="report")
        db.flush()
        gov.raise_finding(db, mine.id, origin=gov.FROM_RULE, title="Mine")

        assert intelligence.dashboard(db, mine.id).as_dict()[
            "findings"]["total"] == 1
        assert intelligence.dashboard(db, theirs.id).as_dict()[
            "findings"]["total"] == 0


# ================================================== the whole payload

@pytest.mark.usefixtures("db")
class TestTheDashboardCarriesTheGovernanceState:

    def test_a_finding_reports_its_origin_and_whether_it_is_unresolved(
            self, db, workspace, committee):
        gov.raise_finding(db, workspace.id, origin=gov.FROM_CHANGE,
                          title="Bad rate deteriorated", severity=gov.HIGH,
                          blocking=True, reference="F-01",
                          previous_value="5.86%", current_value="6.47%",
                          delta="+0.61pp")
        [item] = intelligence.dashboard(db, workspace.id).as_dict()[
            "findings"]["items"]
        assert item["origin"] == gov.FROM_CHANGE
        assert item["origin_label"] == "Change since last time"
        assert item["delta"] == "+0.61pp"
        assert item["unresolved"] is True
        assert item["blocking"] is True
        assert item["history"]

    def test_an_action_reports_its_completion_and_its_external_reference(
            self, db, workspace, committee):
        action = gov.create_action(db, workspace.id, title="Recalibrate",
                                   actor=ACTOR)
        gov.move_action(db, action, to=gov.COMPLETED, actor=OTHER,
                        note="released")
        gov.record_export(db, action, system=gov.PLANNER,
                          external_ref="PP-1", actor=ACTOR)
        [item] = intelligence.dashboard(db, workspace.id).as_dict()[
            "actions"]["items"]
        assert item["completed_by"] == OTHER and item["completed_at"]
        assert item["external_ref"] == "PP-1"
        assert item["notes"][-1]["note"] == "released"

    def test_nothing_in_the_governance_path_calls_a_provider(self, db,
                                                             workspace,
                                                             monkeypatch):
        from backend.playbook import provider

        def explode(*a, **k):
            raise AssertionError("governance called a provider")

        monkeypatch.setattr(provider, "author", explode)
        finding = gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE,
                                    title="X")
        gov.move_finding(db, finding, to=gov.CLOSED, actor=ACTOR,
                         reason="done")
        intelligence.dashboard(db, workspace.id)


@pytest.mark.usefixtures("db")
class TestEveryGovernedObjectHasAHumanReference:
    """"F-03 is still open" is how these are spoken about in a meeting, so the
    reference has to exist and has to be stable."""

    def test_findings_are_numbered_from_one(self, db, workspace):
        first = gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE,
                                  title="A")
        second = gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE,
                                   title="B")
        assert (first.reference, second.reference) == ("F-01", "F-02")

    def test_decisions_and_actions_have_their_own_series(self, db, workspace):
        decision = gov.propose_decision(db, workspace.id, question="Hold?")
        gov.move_decision(db, decision, to=gov.READY_FOR_DECISION,
                          actor=ACTOR)
        gov.record(db, decision, outcome=gov.APPROVE, actor=ACTOR)
        [action] = gov.actions_from_decision(
            db, decision, actor=ACTOR, actions=[{"title": "Do the thing"}])
        assert decision.reference == "D-01"
        assert action.reference == "A-01"

    def test_a_reference_is_never_reused_after_a_deletion(self, db,
                                                          workspace):
        """Derived from what is numbered, not from a count — otherwise a
        reference in last quarter's minutes finds the wrong row."""
        from backend.models.playbook import PlaybookFinding

        first = gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE,
                                  title="A")
        gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE, title="B")
        db.delete(db.get(PlaybookFinding, first.id))
        db.flush()

        third = gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE,
                                  title="C")
        assert third.reference == "F-03"

    def test_references_do_not_collide_across_documents(self, db, scope,
                                                        workspace):
        from backend.playbook import repository as repo

        other = repo.create_workspace(db, scope, title="Another")
        db.flush()
        mine = gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE,
                                 title="A")
        theirs = gov.raise_finding(db, other.id, origin=gov.FROM_RULE,
                                   title="A")
        assert mine.reference == theirs.reference == "F-01"

    def test_a_caller_may_still_supply_its_own(self, db, workspace):
        row = gov.raise_finding(db, workspace.id, origin=gov.FROM_IMPORT,
                                title="A", reference="EW-2026-14")
        assert row.reference == "EW-2026-14"

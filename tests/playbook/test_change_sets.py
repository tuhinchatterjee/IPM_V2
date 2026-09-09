"""Partial approval of a numbered proposal. PB-016.

The interesting cases are not "approve everything". They are: approving some
and not others, approving something that depends on something excluded, and
whether the decision still means the same thing after a reload.
"""

from __future__ import annotations

import pytest

from backend.playbook import repository as repo
from backend.playbook import workspace_service as service

ITEMS = [
    {"stable_id": "chg_stage2", "display_number": 1,
     "target_section": "3. Staging",
     "rationale": "Restate the Stage 2 population at the June cut."},
    {"stable_id": "chg_coverage", "display_number": 2,
     "target_section": "4. Coverage",
     "rationale": "Recompute coverage on the restated Stage 2 population.",
     "depends_on": ["chg_stage2"]},
    {"stable_id": "chg_wording", "display_number": 3,
     "target_section": "1. Executive summary",
     "rationale": "Say 'increased' rather than 'deteriorated'."},
    {"stable_id": "chg_chart", "display_number": 4,
     "target_section": "2. Scenario results",
     "rationale": "Add a scenario chart."},
    {"stable_id": "chg_appendix", "display_number": 5,
     "target_section": "Appendix A",
     "rationale": "Append the model-monitoring extract."},
]


@pytest.fixture
def ledger():
    from backend.playbook import evidence as ev
    from backend.playbook.fixtures import ecl_oracle as oracle

    led = ev.Ledger()
    ev.add_calculations(led, list(oracle.headline().values()))
    return led


@pytest.fixture
def change_set(db, workspace):
    return repo.create_change_set(
        db, workspace.id, message_id=None, base_version_id=None, items=ITEMS)


def _decide(db, scope, workspace, change_set, **kwargs):
    return service.decide_changes(
        db, scope, workspace.id, change_set.id, **kwargs)


class TestSomeAndNotOthers:
    def test_approving_three_rejects_the_other_two(
            self, db, scope, workspace, change_set):
        result = _decide(db, scope, workspace, change_set,
                         approve=["chg_stage2", "chg_wording", "chg_chart"])

        assert result["approved"] == ["chg_chart", "chg_stage2", "chg_wording"]
        assert result["rejected"] == ["chg_appendix", "chg_coverage"]
        by_id = {i.stable_id: i.status
                 for i in repo.change_items(db, change_set.id)}
        assert by_id == {"chg_stage2": "approved", "chg_coverage": "rejected",
                         "chg_wording": "approved", "chg_chart": "approved",
                         "chg_appendix": "rejected"}

    def test_the_decision_is_recorded_against_the_user(
            self, db, scope, workspace, change_set):
        _decide(db, scope, workspace, change_set, approve=["chg_wording"])
        item = repo.change_items(db, change_set.id)[2]
        assert item.decided_by == scope.user_id
        assert item.decided_at is not None

    def test_a_stable_id_that_is_not_in_the_proposal_is_refused(
            self, db, scope, workspace, change_set):
        with pytest.raises(repo.NotFound) as exc:
            _decide(db, scope, workspace, change_set,
                    approve=["chg_wording", "chg_invented"])
        assert "chg_invented" in str(exc.value)
        assert all(i.status == "proposed"
                   for i in repo.change_items(db, change_set.id))


class TestADependencyIsExplainedRatherThanResolved:
    def test_approving_a_dependent_change_without_its_dependency_refuses(
            self, db, scope, workspace, change_set):
        with pytest.raises(service.DependencyConflict) as exc:
            _decide(db, scope, workspace, change_set, approve=["chg_coverage"])

        assert exc.value.conflicts == [{
            "stable_id": "chg_coverage", "display_number": 2,
            "target_section": "4. Coverage", "depends_on": ["chg_stage2"]}]
        # Nothing was written: the refusal is not a partial application.
        assert all(i.status == "proposed"
                   for i in repo.change_items(db, change_set.id))

    def test_approving_both_together_is_accepted(
            self, db, scope, workspace, change_set):
        result = _decide(db, scope, workspace, change_set,
                         approve=["chg_stage2", "chg_coverage"])
        assert result["conflicts"] == []

    def test_the_conflict_can_be_overridden_only_deliberately(
            self, db, scope, workspace, change_set):
        result = _decide(db, scope, workspace, change_set,
                         approve=["chg_coverage"], force=True)
        assert result["conflicts"][0]["stable_id"] == "chg_coverage"
        assert result["approved"] == ["chg_coverage"]


class TestTheInstructionSaysExactlyWhatWasApproved:
    def test_it_names_the_approved_and_forbids_the_rest(
            self, db, scope, workspace, change_set):
        _decide(db, scope, workspace, change_set,
                approve=["chg_stage2", "chg_coverage", "chg_wording"])
        instruction = service.approved_instruction(db, change_set.id)

        assert "3. Staging" in instruction
        assert "4. Coverage" in instruction
        assert "1. Executive summary" in instruction
        assert "Everything else must be returned unchanged." in instruction
        # The excluded two are named as excluded, not merely absent, so a
        # later turn cannot quietly reintroduce them.
        after = instruction.split("NOT approved")[1]
        assert "2. Scenario results" in after
        assert "Appendix A" in after

    def test_it_is_rebuilt_from_the_database_not_the_request(
            self, db, scope, workspace, change_set):
        _decide(db, scope, workspace, change_set, approve=["chg_wording"])
        db.expire_all()
        assert "1. Executive summary" in service.approved_instruction(
            db, change_set.id)

    def test_nothing_approved_produces_no_instruction(
            self, db, scope, workspace, change_set):
        _decide(db, scope, workspace, change_set, approve=[])
        assert service.approved_instruction(db, change_set.id) == ""


class TestARevisedDocumentInvalidatesTheProposal:
    def test_a_proposal_against_a_superseded_version_is_refused(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(
            "# Report\n\n## 1. Executive summary\n\nA first draft.\n")
        first = service.author_document(
            db, scope, workspace.id, instruction="Draft it.",
            ledger=ledger, title="Report")
        change_set = repo.create_change_set(
            db, workspace.id, message_id=None,
            base_version_id=first.version_id, items=ITEMS)

        scripted_author(
            "# Report\n\n## 1. Executive summary\n\nA second draft.\n")
        service.author_document(
            db, scope, workspace.id, instruction="Revise it.",
            ledger=ledger, title="Report", artifact_id=first.artifact_id,
            base_version_id=first.version_id)

        with pytest.raises(repo.StaleBaseVersion):
            _decide(db, scope, workspace, change_set, approve=["chg_wording"])

    def test_a_proposal_against_the_current_version_is_accepted(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(
            "# Report\n\n## 1. Executive summary\n\nA first draft.\n")
        first = service.author_document(
            db, scope, workspace.id, instruction="Draft it.",
            ledger=ledger, title="Report")
        change_set = repo.create_change_set(
            db, workspace.id, message_id=None,
            base_version_id=first.version_id, items=ITEMS)

        result = _decide(db, scope, workspace, change_set,
                         approve=["chg_wording"])
        assert result["base_version_id"] == first.version_id

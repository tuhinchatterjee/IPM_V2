"""The data model a living document needs. Gate 1.

Playbook could already write a document and prove every figure in it. It could
not answer what a person asks of a governed paper afterwards — how complete is
this, which sections are stale, what did this metric say when the paper was
written, what is unresolved, what is the committee being asked to decide.

These tests pin the three things the audit found missing, because each one is
load-bearing for everything above it:

* **stable metric identity**, without which §7's linking model has nothing to
  link through and every binding would come down to matching names;
* **stable section identity**, because `merge` lets an author retitle the
  section it was asked to edit and review state must survive that;
* **parse revisions**, because improving a reader invalidates the READING and
  not the upload, and a user should never rebuild a workspace over it.

Plus the governance boundary: a decision has a human actor or it is not a
decision.
"""

from __future__ import annotations

import contextlib

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from backend.exports import playbook_contract as contract
from backend.models.playbook import (
    Base,
    PlaybookAction,
    PlaybookDecision,
    PlaybookDocumentProfile,
    PlaybookDocumentSection,
    PlaybookFinding,
    PlaybookMetricBinding,
    PlaybookMetricSnapshot,
    PlaybookReadiness,
    PlaybookReview,
    PlaybookSourceParse,
)


@contextlib.contextmanager
def refused(db):
    """A deliberate constraint violation, inside a savepoint.

    The `db` fixture owns one transaction for the whole test and rolls it back
    at the end; flushing a violation without a savepoint kills that
    transaction and the teardown warns. This keeps the violation local to the
    assertion that wants it.
    """
    savepoint = db.begin_nested()
    with pytest.raises(IntegrityError):
        yield
        db.flush()
    savepoint.rollback()



NEW_TABLES = [
    "playbook_document_profiles", "playbook_document_sections",
    "playbook_metric_bindings", "playbook_metric_snapshots",
    "playbook_findings", "playbook_decisions", "playbook_actions",
    "playbook_reviews", "playbook_readiness", "playbook_source_parses",
]


# ============================================== the migration and the ORM

class TestTheSchemaIsWhatTheModelsSay:

    @pytest.fixture
    def inspector(self, db):
        from backend.db.engine import engine

        return inspect(engine)

    @pytest.mark.parametrize("table", NEW_TABLES)
    def test_the_table_exists(self, inspector, table):
        assert inspector.has_table(table)

    @pytest.mark.parametrize("table", NEW_TABLES)
    def test_the_columns_match_the_model_exactly(self, inspector, table):
        """A migration and an ORM that disagree fail at the first flush, in
        production, on a column nobody looked at."""
        in_db = {c["name"] for c in inspector.get_columns(table)}
        in_orm = {c.name for c in Base.metadata.tables[table].columns}
        assert in_db == in_orm

    def test_nothing_existing_was_altered(self, inspector):
        """Additive only. The chat-first workspace keeps every table it had."""
        for table in ("playbook_workspaces", "playbook_messages",
                      "playbook_sources", "playbook_artifacts",
                      "playbook_artifact_versions", "playbook_change_items",
                      "playbook_jobs", "playbook_job_events",
                      "playbooks", "playbook_runs"):
            assert inspector.has_table(table), table


# ============================================== stable metric identity

class TestAMetricHasAnIdentityAndNotJustAName:

    def test_the_contract_carries_metrics(self):
        assert contract.SCHEMA_VERSION == "1.1"
        table = contract.Table(id="book")
        assert table.as_dict()["metrics"] == []

    def test_identity_round_trips(self):
        metric = contract.Metric(
            metric_id="retail.default_rate", label="Retail default rate",
            value="0.0688", display_value="6.88%", unit="percent",
            population="retail", reporting_period="Q2 2026",
            locator="export://41/rev/2#t.book")
        assert contract.Metric.from_dict(metric.as_dict()) == metric

    def test_a_one_point_zero_payload_is_still_valid(self):
        """Additive. An exporter that does not know its metric ids keeps
        working and its figures are simply not auto-bindable — which is the
        honest outcome, not a reason to guess."""
        assert contract.Metric.from_dict({}).metric_id == ""
        assert contract.Table(id="t").metrics == []

    def test_the_dimensions_that_make_two_metrics_different_are_carried(self):
        """A retail rate and a corporate rate are not the same series even
        when they share a name, and a Q1 reading is not a Q2 reading."""
        fields = set(contract.Metric(metric_id="x").as_dict())
        assert {"population", "segment", "reporting_period", "scenario",
                "unit", "currency", "as_of"} <= fields

    def test_a_metric_carries_both_readings_of_its_value(self):
        """The same separation `calc` keeps: exact value, and how it is shown."""
        fields = set(contract.Metric(metric_id="x").as_dict())
        assert {"value", "display_value"} <= fields

    def test_a_metric_carries_where_it_came_from(self):
        assert "locator" in contract.Metric(metric_id="x").as_dict()


# ============================================== the rows behave

@pytest.mark.usefixtures("db")
class TestTheRowsHoldWhatTheyPromise:

    def test_a_profile_records_who_classified_the_document(self, db, workspace):
        profile = PlaybookDocumentProfile(
            workspace_id=workspace.id, document_type="committee_report",
            committee_report=True, committee_name="Credit Risk Committee",
            classified_by="user", reporting_period="Q2 2026")
        db.add(profile)
        db.flush()
        assert profile.classified_by == "user"
        assert profile.status == "drafting"
        assert profile.requirements == {}

    def test_one_profile_per_workspace(self, db, workspace):
        db.add(PlaybookDocumentProfile(workspace_id=workspace.id))
        db.flush()
        with refused(db):
            db.add(PlaybookDocumentProfile(workspace_id=workspace.id))

    def test_a_section_key_is_unique_per_artifact(self, db, workspace):
        from backend.playbook import repository as repo

        artifact = repo.create_artifact(db, workspace.id, kind="report",
                                        title="R")
        db.flush()
        db.add(PlaybookDocumentSection(artifact_id=artifact.id,
                                       section_key="s1", heading="1. Summary"))
        db.flush()
        with refused(db):
            db.add(PlaybookDocumentSection(artifact_id=artifact.id,
                                           section_key="s1",
                                           heading="Renamed"))

    def test_a_section_key_survives_a_retitle(self, db, workspace):
        """What the key is FOR. `merge` allows an author to rename the section
        it was asked to edit, and review state must not reset."""
        from backend.playbook import repository as repo

        artifact = repo.create_artifact(db, workspace.id, kind="report",
                                        title="R")
        db.flush()
        section = PlaybookDocumentSection(
            artifact_id=artifact.id, section_key="s1",
            heading="1. Executive summary", reviewer="a.reviewer",
            status="ready_for_review")
        db.add(section)
        db.flush()
        section.heading = "1. Summary and key judgements"
        db.flush()
        assert section.section_key == "s1"
        assert section.reviewer == "a.reviewer"
        assert section.status == "ready_for_review"

    def test_a_binding_is_a_proposal_until_a_person_confirms_it(self, db,
                                                                workspace):
        binding = PlaybookMetricBinding(
            workspace_id=workspace.id, metric_id="retail.default_rate",
            label="Retail default rate", binding_method="suggested",
            confidence="high")
        db.add(binding)
        db.flush()
        assert binding.confirmed_by_user is False
        assert binding.freshness == "unknown"

    def test_a_binding_holds_three_readings_of_one_fact(self, db, workspace):
        binding = PlaybookMetricBinding(
            workspace_id=workspace.id, metric_id="auc",
            value_in_document="0.559", display_value="0.559",
            raw_value="0.5593220338983", source_locator="xlsx://Validation!B2")
        db.add(binding)
        db.flush()
        assert (binding.value_in_document, binding.display_value,
                binding.raw_value) == ("0.559", "0.559", "0.5593220338983")

    def test_a_snapshot_is_one_reading_per_metric_per_version(self, db,
                                                              workspace):
        from backend.playbook import repository as repo

        artifact = repo.create_artifact(db, workspace.id, kind="report",
                                        title="R")
        db.flush()
        db.add(PlaybookMetricSnapshot(
            artifact_id=artifact.id, version_id=1, version=1,
            metric_id="retail.default_rate", value="0.0746"))
        db.flush()
        with refused(db):
            db.add(PlaybookMetricSnapshot(
                artifact_id=artifact.id, version_id=1, version=1,
                metric_id="retail.default_rate", value="0.0746"))

    def test_a_finding_starts_open_and_unanswered(self, db, workspace):
        finding = PlaybookFinding(
            workspace_id=workspace.id, title="Bad rate deteriorated",
            severity="high", blocking=True, previous_value="5.86",
            current_value="6.47", threshold="+0.40pp")
        db.add(finding)
        db.flush()
        assert finding.status == "open" and finding.answer == ""
        assert finding.raised_by == "rule"

    def test_a_decision_starts_with_no_human_actor(self, db, workspace):
        """The governance boundary, in the row. A model may draft the
        question, the options and the recommendation; the outcome and the
        person are empty until a human records them."""
        decision = PlaybookDecision(
            workspace_id=workspace.id,
            question="Tighten the minimum application score?",
            recommendation="Recommended.",
            options=["approve", "reject", "modify", "defer"],
            current_position="580", proposed_position="600")
        db.add(decision)
        db.flush()
        # "proposed", not "outstanding": §6C replaced the word, and `0039`
        # moved the column default with it. A decision that arrives in a
        # status the transition table does not know is one nobody can ever
        # record.
        assert decision.status == "proposed"
        assert decision.outcome == "" and decision.decided_by == ""
        assert decision.decided_at is None

    def test_an_action_couples_to_a_planner_by_reference_only(self, db,
                                                              workspace):
        """The whole of the coupling. Nothing here needs that module to exist."""
        action = PlaybookAction(workspace_id=workspace.id,
                                title="Recalibrate the cut-off")
        db.add(action)
        db.flush()
        assert action.external_system == "" and action.external_ref == ""
        assert action.status == "open"

    def test_a_review_belongs_to_its_reviewer(self, db, workspace):
        review = PlaybookReview(workspace_id=workspace.id,
                                reviewer="a.reviewer", role="model risk")
        db.add(review)
        db.flush()
        assert review.status == "requested" and review.completed_at is None

    def test_readiness_stores_the_working_not_just_the_score(self, db,
                                                             workspace):
        """§26: a percentage nobody can take apart is one nobody should act
        on."""
        readiness = PlaybookReadiness(
            workspace_id=workspace.id, completion_pct=92, readiness_pct=88,
            components=[{"name": "Findings resolved", "score": 80,
                         "explanation": "1 of 5 open",
                         "blocking": "F-02 unanswered"}],
            blockers=["F-02 unanswered"],
            statistics={"pages": 37, "sections": 15})
        db.add(readiness)
        db.flush()
        assert readiness.components[0]["explanation"] == "1 of 5 open"
        assert readiness.statistics["pages"] == 37

    def test_one_readiness_row_per_artifact(self, db, workspace):
        from backend.playbook import repository as repo

        artifact = repo.create_artifact(db, workspace.id, kind="report",
                                        title="R")
        db.flush()
        db.add(PlaybookReadiness(workspace_id=workspace.id,
                                 artifact_id=artifact.id))
        db.flush()
        with refused(db):
            db.add(PlaybookReadiness(workspace_id=workspace.id,
                                     artifact_id=artifact.id))

    def test_readiness_uniqueness_does_not_bite_before_an_artifact_exists(
            self, db, workspace):
        """Stated rather than discovered. PostgreSQL treats NULLs as distinct,
        so the constraint governs readiness FOR AN ARTIFACT; a workspace with
        no artifact yet can hold more than one placeholder row, and the
        service layer is what keeps it to one."""
        for _ in range(2):
            db.add(PlaybookReadiness(workspace_id=workspace.id,
                                     artifact_id=None))
        db.flush()

    def test_a_parse_revision_records_the_parser_that_made_it(self, db, scope,
                                                              workspace):
        from backend.playbook import repository as repo

        source = repo.add_source(db, workspace.id, scope, filename="a.xlsx",
                                 mime="application/vnd.ms-excel",
                                 sha256="x" * 64, size_bytes=1,
                                 source_role="results")
        db.flush()
        db.add(PlaybookSourceParse(source_id=source.id, revision=1,
                                   parser_version="2026.09.1", chunk_count=4))
        db.flush()
        with refused(db):
            db.add(PlaybookSourceParse(source_id=source.id, revision=1,
                                       parser_version="2026.09.2"))

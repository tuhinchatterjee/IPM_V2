"""The Document Intelligence service boundary. Gate 2.

The product rule this file exists to enforce, stated once:

    A metric is linked because something authoritative said so, never because
    two labels look alike.

Auto-confirmed only when the export carried a stable `metric_id`, the
catalogue maps the field, or a person confirmed this same mapping here before.
Everything else is a SUGGESTION — shown immediately so the dashboard is useful
on first open, marked as needing confirmation, and behaving as a link in no
respect at all until somebody confirms it. It lowers linkage coverage; it does
not raise it.

The rest is the boundary itself: classification a person can settle, section
keys that survive a retitle, statistics read from rendered files rather than
estimated, and a dashboard assembled from rows with no provider call anywhere
in it.
"""

from __future__ import annotations

import pytest

from backend.exports import playbook_contract as contract
from backend.models.playbook import PlaybookFinding, PlaybookMetricBinding
from backend.playbook import document as D
from backend.playbook import intelligence
from backend.playbook import repository as repo
from backend.playbook.intelligence import binding as bind
from backend.playbook.intelligence import profile as prof
from backend.playbook.intelligence import sections as sect

ACTOR = "user:7"


# ====================================================== classification

class TestWhatKindOfDocumentThisIs:

    @pytest.mark.parametrize("instruction,expected", [
        ("Create an Auto Loan Application Scorecard Model Development Report",
         prof.MODEL_DEVELOPMENT),
        ("Behavioral Scorecard Validation Report", prof.MODEL_VALIDATION),
        ("Write the Q2 2026 IFRS 9 committee report", prof.IFRS9_REPORT),
        ("Prepare the board paper for March", prof.BOARD_PAPER),
        ("Draft our risk appetite report", prof.RISK_APPETITE),
        ("Turn this into a presentation", prof.PRESENTATION),
    ])
    def test_the_type_is_inferred_from_the_users_own_words(self, instruction,
                                                           expected):
        assert prof.infer(instruction).document_type == expected

    def test_validation_is_not_read_as_development(self):
        """Both contain "model". Ordering the signals most-specific-first is
        what keeps them apart, and it is worth a test of its own."""
        assert prof.infer("model validation report").document_type == \
            prof.MODEL_VALIDATION

    def test_a_committee_flag_does_not_override_the_kind_of_paper(self):
        guess = prof.infer("IFRS 9 committee report for the Credit Risk "
                           "Committee")
        assert guess.document_type == prof.IFRS9_REPORT
        assert guess.committee_report is True

    def test_an_unclear_instruction_asks_rather_than_guesses(self):
        guess = prof.infer("help me with something")
        assert guess.document_type == prof.GENERAL
        assert guess.confidence == prof.LOW and guess.should_ask is True

    def test_an_obvious_instruction_does_not_interrupt(self):
        assert prof.infer("Create a model development report").should_ask \
            is False

    def test_every_type_has_requirements_that_sum_to_one_hundred(self):
        for document_type in prof.DOCUMENT_TYPES:
            requirements = prof.requirements_for(document_type)
            assert requirements.sections
            assert sum(requirements.weights.values()) == 100

    def test_requirements_differ_by_type(self):
        """The reason they are per-document: a development report earns
        completeness from having written its sections, a committee pack from
        having dispositioned what it raised."""
        development = prof.requirements_for(prof.MODEL_DEVELOPMENT)
        committee = prof.requirements_for(prof.COMMITTEE_REPORT)
        assert development.weights[prof.REQUIRED_SECTIONS] > \
            committee.weights[prof.REQUIRED_SECTIONS]
        assert committee.weights[prof.FINDINGS_DISPOSITIONED] > \
            development.weights[prof.FINDINGS_DISPOSITIONED]
        assert len(development.sections) > len(committee.sections)


@pytest.mark.usefixtures("db")
class TestOnlyAPersonSettlesTheType:

    def test_a_profile_is_inferred_once(self, db, workspace):
        first = intelligence.ensure_profile(
            db, workspace.id, instruction="Write the IFRS 9 committee report")
        assert first.document_type == prof.IFRS9_REPORT
        assert first.classified_by == "inferred"

        again = intelligence.ensure_profile(db, workspace.id,
                                            instruction="something else")
        assert again.id == first.id and again.document_type == \
            prof.IFRS9_REPORT

    def test_a_person_can_change_it_and_the_requirements_move_with_it(
            self, db, workspace):
        intelligence.ensure_profile(db, workspace.id, instruction="a report")
        row = intelligence.classify(db, workspace.id,
                                    document_type=prof.MODEL_VALIDATION,
                                    actor=ACTOR)
        assert row.classified_by == "user"
        assert row.requirements["sections"] == list(
            prof.requirements_for(prof.MODEL_VALIDATION).sections)

    def test_an_inference_never_overwrites_what_a_person_set(self, db,
                                                             workspace):
        intelligence.classify(db, workspace.id,
                              document_type=prof.MODEL_VALIDATION, actor=ACTOR)
        again = intelligence.ensure_profile(
            db, workspace.id, instruction="IFRS 9 committee report")
        assert again.document_type == prof.MODEL_VALIDATION
        assert again.classified_by == "user"

    def test_classifying_needs_a_person(self, db, workspace):
        with pytest.raises(intelligence.NotPermitted):
            intelligence.classify(db, workspace.id,
                                  document_type=prof.BOARD_PAPER, actor="")

    def test_an_unknown_type_is_refused_as_a_different_kind_of_refusal(
            self, db, workspace):
        """"You may not do this" and "that is not a thing" are different
        answers, and a caller that cannot tell them apart can correct
        neither."""
        with pytest.raises(intelligence.UnknownDocumentType):
            intelligence.classify(db, workspace.id, document_type="novel",
                                  actor=ACTOR)


# ====================================================== the binding rule

class TestWhatMayBeAutoConfirmed:

    def test_an_export_that_carries_a_metric_id_is_authoritative(self):
        metric = contract.Metric(metric_id="retail.default_rate",
                                 label="Retail default rate", value="0.0688",
                                 display_value="6.88%", unit="percent")
        [proposal] = bind.from_export([metric], module="cockpit")
        assert proposal.method == bind.FROM_EXPORT
        assert proposal.auto_confirmed is True

    def test_an_export_metric_without_an_id_is_not_proposed_at_all(self):
        """An exporter that does not know its identity has not provided one,
        and inventing it from the label is the whole mistake."""
        assert bind.from_export([contract.Metric(metric_id="",
                                                 label="Default rate")]) == []

    def test_a_catalogue_mapping_is_authoritative(self):
        [proposal] = bind.from_labels(
            [("Default rate", "6.88%", "0.0688", "B2")],
            catalogue={"default rate": "retail.default_rate"})
        assert proposal.method == bind.FROM_CATALOGUE
        assert proposal.auto_confirmed is True

    def test_a_prior_confirmation_here_is_authoritative(self):
        [proposal] = bind.from_labels(
            [("Default rate", "6.88%", "0.0688", "B2")],
            confirmed_before={"default rate": "retail.default_rate"})
        assert proposal.method == bind.FROM_PRIOR_CONFIRMATION
        assert proposal.auto_confirmed is True

    def test_a_label_that_merely_looks_right_is_only_a_suggestion(self):
        """The rule. An uploaded workbook has no metric identity in it."""
        [proposal] = bind.from_labels(
            [("Application cohort bad rate", "6.47%", "0.0647", "B4")])
        assert proposal.method == bind.SUGGESTED
        assert proposal.auto_confirmed is False
        assert proposal.confidence == bind.HIGH

    def test_a_label_that_matches_nothing_is_said_to_be_unlinked(self):
        [proposal] = bind.from_labels(
            [("Bespoke overlay factor", "1.2", "1.2", "B9")])
        assert proposal.method == bind.UNLINKED
        assert proposal.metric_id == ""

    def test_matching_is_whole_phrase_and_not_substring(self):
        """Substring matching would bind "bad rate" to anything containing the
        words, which is how the wrong series reaches a governed paper."""
        assert bind.suggest_from_label("badness ratefinder") is None


@pytest.mark.usefixtures("db")
class TestASuggestionIsNotALink:
    """The behavioural half of the rule: what a suggestion may NOT do."""

    def _suggested(self, db, workspace) -> PlaybookMetricBinding:
        [row] = bind.apply(db, workspace.id, bind.from_labels(
            [("Application cohort bad rate", "6.47%", "0.0647", "B4")],
            locator="xlsx://Performance!A1"))
        return row

    def test_it_is_written_and_visible_immediately(self, db, workspace):
        row = self._suggested(db, workspace)
        assert row.binding_method == bind.SUGGESTED
        state = intelligence.dashboard(db, workspace.id).as_dict()
        assert state["metrics"]["detected"] == 1
        assert state["metrics"]["suggested"] == 1
        assert state["metrics"]["inventory"][0]["value_in_document"] == "6.47%"
        assert state["metrics"]["inventory"][0]["source_locator"] == \
            "xlsx://Performance!B4"

    def test_it_is_marked_as_needing_confirmation(self, db, workspace):
        self._suggested(db, workspace)
        [row] = intelligence.dashboard(db, workspace.id).as_dict()[
            "metrics"]["inventory"]
        assert row["method_label"] == "Suggested — confirmation required"
        assert row["confirmed"] is False

    def test_it_is_not_governed(self, db, workspace):
        """The single predicate everything downstream asks."""
        row = self._suggested(db, workspace)
        assert bind.is_governed(row) is False

    def test_it_does_not_count_towards_coverage(self, db, workspace):
        self._suggested(db, workspace)
        metrics = intelligence.dashboard(db, workspace.id).as_dict()["metrics"]
        assert metrics["coverage_pct"] == 0
        assert metrics["confirmed"] == 0

    def test_the_dashboard_offers_the_review_prompt(self, db, workspace):
        self._suggested(db, workspace)
        metrics = intelligence.dashboard(db, workspace.id).as_dict()["metrics"]
        assert metrics["review_prompt"] == "Review 1 suggested metric link"
        assert len(metrics["suggested_review"]) == 1

    def test_confirming_it_makes_it_governed(self, db, workspace):
        row = self._suggested(db, workspace)
        bind.confirm(db, row, actor=ACTOR)
        assert bind.is_governed(row) is True
        assert row.confirmed_by == ACTOR and row.confirmed_at is not None
        metrics = intelligence.dashboard(db, workspace.id).as_dict()["metrics"]
        assert metrics["coverage_pct"] == 100 and metrics["suggested"] == 0

    def test_confirming_needs_a_person(self, db, workspace):
        row = self._suggested(db, workspace)
        with pytest.raises(bind.NotConfirmable):
            bind.confirm(db, row, actor="  ")
        assert bind.is_governed(row) is False

    def test_changing_the_mapping_confirms_the_metric_the_person_chose(
            self, db, workspace):
        row = self._suggested(db, workspace)
        bind.confirm(db, row, actor=ACTOR, metric_id="corporate.bad_rate")
        assert row.metric_id == "corporate.bad_rate"
        assert bind.is_governed(row) is True

    def test_ignoring_keeps_the_figure_in_the_inventory(self, db, workspace):
        """The row stays so the document's inventory still shows the figure,
        and so the same suggestion is not made again."""
        row = self._suggested(db, workspace)
        bind.ignore(db, row)
        metrics = intelligence.dashboard(db, workspace.id).as_dict()["metrics"]
        assert metrics["detected"] == 1 and metrics["unlinked"] == 1
        assert metrics["confirmed"] == 0

    def test_an_export_metric_is_governed_without_anybody_confirming(
            self, db, workspace):
        metric = contract.Metric(metric_id="retail.default_rate",
                                 label="Retail default rate",
                                 display_value="6.88%")
        [row] = bind.apply(db, workspace.id,
                           bind.from_export([metric], module="cockpit"))
        assert bind.is_governed(row) is True
        metrics = intelligence.dashboard(db, workspace.id).as_dict()["metrics"]
        assert metrics["confirmed"] == 1 and metrics["suggested"] == 0

    def test_re_reading_the_same_source_does_not_multiply_the_inventory(
            self, db, workspace):
        for _ in range(3):
            bind.apply(db, workspace.id, bind.from_labels(
                [("Application cohort bad rate", "6.47%", "0.0647", "B4")],
                locator="xlsx://Performance!A1"))
        assert intelligence.dashboard(db, workspace.id).as_dict()[
            "metrics"]["detected"] == 1

    def test_re_reading_never_un_confirms_a_persons_work(self, db, workspace):
        row = self._suggested(db, workspace)
        bind.confirm(db, row, actor=ACTOR)
        bind.apply(db, workspace.id, bind.from_labels(
            [("Application cohort bad rate", "6.47%", "0.0647", "B4")],
            locator="xlsx://Performance!A1"))
        assert row.confirmed_by_user is True and bind.is_governed(row) is True

    def test_the_four_counts_are_reported_separately(self, db, workspace):
        """§8's opening line: detected, confirmed, suggested, unlinked. Never
        summed into one "linked" number."""
        bind.apply(db, workspace.id, bind.from_export(
            [contract.Metric(metric_id="retail.default_rate", label="DR")]))
        bind.apply(db, workspace.id, bind.from_labels(
            [("Gini", "0.415", "0.4152", "B2"),
             ("Bespoke overlay factor", "1.2", "1.2", "B3")],
            locator="xlsx://Perf!A1"))
        metrics = intelligence.dashboard(db, workspace.id).as_dict()["metrics"]
        assert (metrics["detected"], metrics["confirmed"],
                metrics["suggested"], metrics["unlinked"]) == (3, 1, 1, 1)


# ====================================================== sections

class TestSectionIdentitySurvivesARetitle:

    def test_a_key_ignores_renumbering(self):
        assert sect.key_for("4. Methodology", 4) == \
            sect.key_for("5. Methodology", 4)

    def test_two_sections_do_not_collide(self):
        assert sect.key_for("Findings", 3) != sect.key_for("Findings", 7)

    @pytest.mark.usefixtures("db")
    def test_a_retitled_section_keeps_its_row_and_its_reviewer(self, db,
                                                               workspace):
        artifact = repo.create_artifact(db, workspace.id, kind="report",
                                        title="R")
        db.flush()
        first = D.parse("## 1. Executive summary\n\n" + "word " * 40, title="R")
        [row] = sect.sync(db, artifact.id, first, version=1)
        row.reviewer = "a.reviewer"
        db.flush()

        retitled = D.parse("## 1. Summary and key judgements\n\n"
                           + "word " * 40, title="R")
        [after] = sect.sync(db, artifact.id, retitled, version=2)
        assert after.id == row.id
        assert after.reviewer == "a.reviewer"
        assert after.heading == "1. Summary and key judgements"

    @pytest.mark.usefixtures("db")
    def test_a_changed_section_reopens_a_completed_review(self, db, workspace):
        """A reviewer signed off on text that no longer exists. Pretending
        otherwise is how a stale approval reaches a committee."""
        from datetime import UTC, datetime

        artifact = repo.create_artifact(db, workspace.id, kind="report",
                                        title="R")
        db.flush()
        first = D.parse("## 1. Summary\n\n" + "word " * 40, title="R")
        [row] = sect.sync(db, artifact.id, first, version=1)
        row.reviewed_at = datetime.now(UTC)
        row.status = sect.APPROVED
        db.flush()

        changed = D.parse("## 1. Summary\n\n" + "different " * 40, title="R")
        [after] = sect.sync(db, artifact.id, changed, version=2)
        assert after.reviewed_at is None
        assert after.status == sect.NEEDS_REVIEW
        assert "changed since" in after.stale_reason

    @pytest.mark.usefixtures("db")
    def test_a_dropped_section_is_marked_not_deleted(self, db, workspace):
        artifact = repo.create_artifact(db, workspace.id, kind="report",
                                        title="R")
        db.flush()
        sect.sync(db, artifact.id, D.parse(
            "## 1. Summary\n\nText here.\n\n## 2. Limitations\n\nScope.\n",
            title="R"), version=1)
        rows = sect.sync(db, artifact.id,
                         D.parse("## 1. Summary\n\nText here.\n", title="R"),
                         version=2)
        assert len(rows) == 1
        state = intelligence.dashboard(db, workspace.id).as_dict()
        dropped = [s for s in state["sections"] if s["status"] == sect.STALE]
        assert len(dropped) == 1 and "not present in version 2" in \
            dropped[0]["stale_reason"]


class TestStatisticsAreMeasuredNotEstimated:

    def test_page_count_is_absent_rather_than_guessed(self):
        stats = sect.statistics(D.parse("## 1. Summary\n\n" + "word " * 500,
                                        title="R"))
        assert stats["pages"] is None
        assert stats["page_count_source"] == "not rendered"

    def test_page_count_comes_from_a_parsed_back_file(self):
        class V:
            checked = {"pages": 37}
            ok = True

        stats = sect.statistics(D.parse("## 1. Summary\n\nText.", title="R"),
                                validations={"pdf": V()})
        assert stats["pages"] == 37
        assert stats["page_count_source"] == "pdf (parsed back)"

    def test_the_counts_come_from_the_canonical_document(self):
        doc = D.parse(
            "## 1. Summary\n\n" + "word " * 40 + "\n\n"
            "## 2. Results\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n",
            title="R")
        stats = sect.statistics(doc)
        assert stats["sections"] == 2 and stats["tables"] == 1
        assert stats["substantive_sections"] == 2


# ====================================================== the dashboard

@pytest.mark.usefixtures("db")
class TestTheDashboardIsAssembledFromRows:

    def test_an_empty_workspace_offers_no_status_badge(self, db, workspace):
        """§14: a brand-new empty thread does not get a badge it cannot fill."""
        assert intelligence.dashboard(db, workspace.id).available is False

    def test_it_becomes_available_once_there_is_something_to_say(self, db,
                                                                 workspace):
        bind.apply(db, workspace.id, bind.from_export(
            [contract.Metric(metric_id="x", label="X")]))
        assert intelligence.dashboard(db, workspace.id).available is True

    def test_it_reports_the_committee_shape_when_it_is_one(self, db,
                                                           workspace):
        intelligence.classify(db, workspace.id,
                              document_type=prof.COMMITTEE_REPORT,
                              actor=ACTOR, committee_name="Credit Risk",
                              reporting_period="Q2 2026")
        state = intelligence.dashboard(db, workspace.id).as_dict()
        assert state["committee_report"] is True
        assert state["committee_name"] == "Credit Risk"
        assert state["document_type_label"] == "Committee report"

    def test_findings_are_counted_with_blocking_kept_separate(self, db,
                                                              workspace):
        db.add(PlaybookFinding(workspace_id=workspace.id, title="A",
                               severity="high", blocking=True))
        db.add(PlaybookFinding(workspace_id=workspace.id, title="B",
                               severity="low"))
        db.flush()
        findings = intelligence.dashboard(db, workspace.id).as_dict()[
            "findings"]
        assert findings["total"] == 2 and findings["open"] == 2
        assert findings["blocking"] == 1
        assert findings["by_severity"]["high"] == 1

    def test_readiness_is_absent_until_it_has_been_computed(self, db,
                                                            workspace):
        """Not zero — absent. A score nobody computed is not a score of 0."""
        readiness = intelligence.dashboard(db, workspace.id).as_dict()[
            "readiness"]
        assert readiness["computed"] is False

    def test_the_whole_payload_is_json_safe(self, db, workspace):
        import json

        bind.apply(db, workspace.id, bind.from_labels(
            [("Gini", "0.415", "0.4152", "B2")], locator="xlsx://P!A1"))
        state = intelligence.dashboard(db, workspace.id).as_dict()
        assert json.loads(json.dumps(state))["metrics"]["detected"] == 1

    def test_nothing_in_the_dashboard_path_calls_a_provider(self, db,
                                                            workspace,
                                                            monkeypatch):
        """§4: a percentage a model felt was right is exactly what is
        forbidden. Asserted by making any provider call explode."""
        from backend.playbook import provider

        def explode(*a, **k):
            raise AssertionError("the dashboard called a provider")

        monkeypatch.setattr(provider, "author", explode)
        intelligence.dashboard(db, workspace.id)

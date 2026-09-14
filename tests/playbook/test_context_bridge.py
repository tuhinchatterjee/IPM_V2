"""Gate 8 — the dashboard is not a separate dead screen. §15.

Two halves, and the first is the one that was actually missing.

**Adoption.** Gates 4 and 5 built section rows and metric snapshots with
careful rules about retitles, reopened sign-offs and readings that are never
rewritten — and nothing called them. A document generated through the real
authoring path produced no section rows and froze no readings, so the
dashboard beside it described a workspace nobody had written to. §15 asks that
the dashboard refresh when Claude finishes; it cannot refresh from state that
was never recorded.

**The bridge.** Clicking a metric, a finding, a section, a decision or Since
Last Time hands the composer a question, the §8 task framing it belongs to,
and explicit references to what it is about. The governed facts behind the
object become evidence. An unconfirmed suggestion does not: it produces a
caveat for the person, and it must not become a citable figure by travelling
through the composer.
"""

from __future__ import annotations

import pytest

from backend.exports import playbook_contract as contract
from backend.models.playbook import PlaybookMetricSnapshot
from backend.playbook import document as D
from backend.playbook import repository as repo
from backend.playbook import service
from backend.playbook.intelligence import adopt
from backend.playbook.intelligence import binding as bind
from backend.playbook.intelligence import context as ctx
from backend.playbook.intelligence import governance as gov
from backend.playbook.intelligence import sections as sect

ACTOR = "user:7"
BODY = "considered judgement " * 15

REPORT_MD = """# IFRS 9 Committee Report

## 1. Executive summary

Stage 2 coverage stands at 5.86 per cent of the book.

## 2. Portfolio composition

The book is concentrated in Contracting and Retail.
"""


def _doc(*headings: str) -> D.Document:
    return D.parse("".join(f"## {h}\n\n{BODY}\n\n" for h in headings),
                   title="Report")


def _artifact(db, workspace, title="Report"):
    artifact = repo.create_artifact(db, workspace.id, kind="report",
                                    title=title)
    db.flush()
    return artifact


def _version(db, artifact, doc, version=1):
    row = repo.new_version(db, artifact, content=doc.as_dict(),
                           source_manifest={},
                           content_hash=doc.content_hash(), validation={})
    db.flush()
    return row


def _governed_metric(db, workspace, *, label="Stage 2 coverage",
                     value="5.86%", section_key="", metric_id="ecl.stage2"):
    [row] = bind.apply(db, workspace.id, bind.from_export(
        [contract.Metric(metric_id=metric_id, label=label,
                         display_value=value)]))
    if section_key:
        row.section_key = section_key
    row.source_locator = "xlsx://Coverage!B12"
    db.flush()
    return row


def _suggested_metric(db, workspace, *, label="Application cohort bad rate"):
    [row] = bind.apply(db, workspace.id, bind.from_labels(
        [(label, "6.47%", "0.0647", "B4")], locator="xlsx://Performance!A1"))
    db.flush()
    return row


# =============================================== the dashboard is written to


@pytest.mark.usefixtures("db")
class TestWritingAVersionUpdatesTheDashboard:
    """The gap Gate 8 closes: `sync` and `freeze` had no caller outside their
    own tests."""

    def test_a_generated_version_creates_its_section_rows(
            self, db, scope, workspace, scripted_author):
        from backend.playbook import evidence as ev

        scripted_author(REPORT_MD)
        outcome = service.author_document(
            db, scope, workspace.id, instruction="Write it.",
            ledger=ev.Ledger(), title="IFRS 9 Committee Report",
            formats=["docx"])

        rows = sect.rows_for(db, outcome.artifact_id)
        assert [r.heading for r in rows] == ["1. Executive summary",
                                             "2. Portfolio composition"]
        assert outcome.adoption["sections"] == 2
        assert outcome.adoption["version"] == 1

    def test_adoption_reports_which_sections_changed(self, db, workspace):
        artifact = _artifact(db, workspace)
        first = _doc("Executive summary", "Portfolio composition")
        _version(db, artifact, first)
        adopt.adopt(db, workspace.id, artifact.id, version_id=1, version=1,
                    doc=first)

        edited = D.parse(
            f"## Executive summary\n\nSomething else entirely. {BODY}\n\n"
            f"## Portfolio composition\n\n{BODY}\n\n", title="Report")
        row = _version(db, artifact, edited)
        result = adopt.adopt(db, workspace.id, artifact.id,
                             version_id=row.id, version=2, doc=edited)

        assert result.sections_changed == [{"key": "executive-summary-1",
                                           "heading": "Executive summary"}]
        assert result.sections_written == 2

    def test_adoption_reports_a_reopened_sign_off(self, db, workspace):
        """A reviewer signed off on text that no longer exists. Saying so is
        the point — a silent reopen is as bad as no reopen."""
        artifact = _artifact(db, workspace)
        first = _doc("Executive summary")
        _version(db, artifact, first)
        adopt.adopt(db, workspace.id, artifact.id, version_id=1, version=1,
                    doc=first)

        [row] = sect.rows_for(db, artifact.id)
        sect.transition(db, row, to=sect.READY_FOR_REVIEW, actor=ACTOR)
        sect.transition(db, row, to=sect.APPROVED, actor=ACTOR)

        edited = D.parse(
            f"## Executive summary\n\nRewritten. {BODY}\n\n", title="Report")
        version = _version(db, artifact, edited)
        result = adopt.adopt(db, workspace.id, artifact.id,
                             version_id=version.id, version=2, doc=edited)

        assert [r["heading"] for r in result.reviews_reopened] == [
            "Executive summary"]
        assert sect.rows_for(db, artifact.id)[0].status == sect.NEEDS_REVIEW

    def test_only_governed_readings_are_frozen(self, db, workspace):
        _governed_metric(db, workspace)
        _suggested_metric(db, workspace)

        artifact = _artifact(db, workspace)
        doc = _doc("Executive summary")
        version = _version(db, artifact, doc)
        result = adopt.adopt(db, workspace.id, artifact.id,
                             version_id=version.id, version=1, doc=doc)

        assert result.metrics_frozen == 1
        frozen = db.query(PlaybookMetricSnapshot).filter(
            PlaybookMetricSnapshot.version_id == version.id).all()
        assert [s.metric_id for s in frozen] == ["ecl.stage2"]

    def test_adopting_the_same_version_twice_freezes_nothing_new(
            self, db, workspace):
        """A snapshot is a reading, not a cache. Re-running returns what was
        already recorded rather than a second set."""
        _governed_metric(db, workspace)
        artifact = _artifact(db, workspace)
        doc = _doc("Executive summary")
        version = _version(db, artifact, doc)

        first = adopt.adopt(db, workspace.id, artifact.id,
                            version_id=version.id, version=1, doc=doc)
        again = adopt.adopt(db, workspace.id, artifact.id,
                            version_id=version.id, version=1, doc=doc)

        assert first.metrics_frozen == again.metrics_frozen == 1
        assert db.query(PlaybookMetricSnapshot).filter(
            PlaybookMetricSnapshot.version_id == version.id).count() == 1

    def test_a_scoped_edit_leaves_the_untouched_section_alone(
            self, db, scope, workspace, scripted_author):
        """The dashboard must agree with the merge: one section changed.

        The ledger carries the coverage figure so the edit is a real edit. Run
        against an empty ledger, grounding strips the sentence from BOTH
        versions and replaces it with the same text, and the two sections are
        then genuinely identical — which the adoption reports correctly, and
        which proves nothing about scoping.
        """
        from backend.playbook import evidence as ev

        ledger = ev.Ledger()
        ledger.add(ev.Item("xlsx://Coverage!B12", "sheet_range",
                           "Stage 2 coverage 5.86"))

        scripted_author(REPORT_MD)
        first = service.author_document(
            db, scope, workspace.id, instruction="Write it.", ledger=ledger,
            title="IFRS 9 Committee Report", formats=["docx"])
        assert first.grounding_final.ok

        scripted_author(REPORT_MD.replace(
            "Stage 2 coverage stands at 5.86 per cent of the book.",
            "Stage 2 coverage stands at 5.86 per cent, concentrated in "
            "Contracting."))
        second = service.author_document(
            db, scope, workspace.id, instruction="Tighten the summary.",
            ledger=ledger, title="IFRS 9 Committee Report",
            formats=["docx"], artifact_id=first.artifact_id,
            task_kind="edit", task_scope="1. Executive summary")

        assert [s["heading"] for s in second.adoption["sections_changed"]] \
            == ["1. Executive summary"]


# ========================================================== the chat context


@pytest.mark.usefixtures("db")
class TestAMetricBecomesAQuestion:

    def test_a_governed_metric_supplies_its_reading_as_evidence(
            self, db, workspace):
        row = _governed_metric(db, workspace)
        built = ctx.build(db, workspace.id, kind="metric", target=str(row.id))

        assert built.action == ctx.ASK_ABOUT_METRIC
        assert built.label == "Ask Claude about this"
        assert "Stage 2 coverage" in built.prompt and "5.86%" in built.prompt
        assert built.references[0].governed is True
        assert built.evidence[0]["locator"] == "xlsx://Coverage!B12"
        assert "5.86%" in built.evidence[0]["text"]
        assert built.caveats == []

    def test_a_suggested_metric_supplies_a_caveat_and_no_evidence(
            self, db, workspace):
        """The rule that governs THEN/NOW governs this too: a guess that
        travels far enough from where it was made stops looking like a
        guess."""
        row = _suggested_metric(db, workspace)
        built = ctx.build(db, workspace.id, kind="metric", target=str(row.id))

        assert built.references[0].governed is False
        assert built.evidence == []
        assert "nobody has confirmed" in built.caveats[0]

    def test_an_unconfirmed_suggestion_never_reaches_the_ledger(
            self, db, workspace):
        row = _suggested_metric(db, workspace)
        built = ctx.build(db, workspace.id, kind="metric", target=str(row.id))
        assert ctx.as_items(built) == []

    def test_a_metric_from_another_workspace_is_not_reachable(
            self, db, scope, workspace):
        other = repo.create_workspace(db, scope, title="Another")
        db.flush()
        row = _governed_metric(db, other)
        with pytest.raises(ctx.UnknownContext):
            ctx.build(db, workspace.id, kind="metric", target=str(row.id))


@pytest.mark.usefixtures("db")
class TestAFindingBecomesADraft:

    def test_a_finding_carries_its_own_evidence(self, db, workspace):
        finding = gov.raise_finding(
            db, workspace.id, origin=gov.FROM_RULE, severity=gov.HIGH,
            title="Stage 2 coverage fell below the threshold",
            rationale="Coverage is below the committee's floor.",
            metric_id="ecl.stage2", threshold="6.50%",
            previous_value="6.50%", current_value="5.86%", delta="-0.64pp",
            source_locator="xlsx://Coverage!B12")

        built = ctx.build(db, workspace.id, kind="finding",
                          target=str(finding.id))
        assert built.action == ctx.DRAFT_FINDING_ANSWER
        assert built.label == "Draft an answer"
        texts = " | ".join(e["text"] for e in built.evidence)
        assert "was 6.50%, now 5.86%" in texts and "-0.64pp" in texts
        assert built.references[0].detail["origin_label"] == "Threshold rule"

    def test_the_caveat_says_a_draft_disposes_of_nothing(self, db, workspace):
        finding = gov.raise_finding(db, workspace.id, origin=gov.FROM_AI,
                                    title="Coverage may be understated")
        built = ctx.build(db, workspace.id, kind="finding",
                          target=str(finding.id))
        assert "a person does that" in built.caveats[0]

    def test_a_missing_finding_says_so(self, db, workspace):
        with pytest.raises(ctx.UnknownContext) as raised:
            ctx.build(db, workspace.id, kind="finding", target="99999999")
        assert "No finding" in str(raised.value)


@pytest.mark.usefixtures("db")
class TestASectionBecomesAScopedEdit:

    def test_updating_a_section_carries_the_existing_edit_framing(
            self, db, workspace):
        artifact = _artifact(db, workspace)
        doc = _doc("Executive summary", "Portfolio composition")
        version = _version(db, artifact, doc)
        adopt.adopt(db, workspace.id, artifact.id, version_id=version.id,
                    version=1, doc=doc)

        key = sect.key_for("Executive summary", 1)
        built = ctx.build(db, workspace.id, kind="section", target=key)

        assert built.action == ctx.UPDATE_SECTION
        # The scoped merge, unchanged. Everything outside this heading must
        # come back byte-identical, which is Gate 4's guarantee not a new one.
        assert built.task == "edit"
        assert built.scope == "Executive summary"

    def test_a_reviewed_section_warns_that_editing_reopens_it(
            self, db, workspace):
        artifact = _artifact(db, workspace)
        doc = _doc("Executive summary")
        version = _version(db, artifact, doc)
        adopt.adopt(db, workspace.id, artifact.id, version_id=version.id,
                    version=1, doc=doc)
        [row] = sect.rows_for(db, artifact.id)
        sect.transition(db, row, to=sect.READY_FOR_REVIEW, actor=ACTOR)
        sect.transition(db, row, to=sect.APPROVED, actor=ACTOR)

        built = ctx.build(db, workspace.id, kind="section",
                          target=row.section_key)
        assert any("reopens that review" in c for c in built.caveats)

    def test_a_sections_suggested_links_are_named_not_supplied(
            self, db, workspace):
        artifact = _artifact(db, workspace)
        doc = _doc("Executive summary")
        version = _version(db, artifact, doc)
        adopt.adopt(db, workspace.id, artifact.id, version_id=version.id,
                    version=1, doc=doc)
        key = sect.key_for("Executive summary", 1)

        _governed_metric(db, workspace, section_key=key)
        suggested = _suggested_metric(db, workspace)
        suggested.section_key = key
        db.flush()

        built = ctx.build(db, workspace.id, kind="section", target=key)
        assert len(built.evidence) == 1
        assert any("suggested and unconfirmed" in c for c in built.caveats)

    def test_a_section_that_is_not_there_says_so(self, db, workspace):
        with pytest.raises(ctx.UnknownContext):
            ctx.build(db, workspace.id, kind="section", target="nowhere")


@pytest.mark.usefixtures("db")
class TestTheWholeDocumentContexts:

    def test_since_last_time_needs_something_to_compare(self, db, workspace):
        with pytest.raises(ctx.UnknownContext):
            ctx.build(db, workspace.id, kind="since_last_time")

    def test_stale_metrics_needs_a_stale_metric(self, db, workspace):
        _governed_metric(db, workspace)
        with pytest.raises(ctx.UnknownContext) as raised:
            ctx.build(db, workspace.id, kind="stale_metrics")
        assert "newer reading" in str(raised.value)

    def test_a_stale_governed_metric_names_the_sections_to_refresh(
            self, db, workspace):
        artifact = _artifact(db, workspace)
        doc = _doc("Executive summary")
        version = _version(db, artifact, doc)
        adopt.adopt(db, workspace.id, artifact.id, version_id=version.id,
                    version=1, doc=doc)
        key = sect.key_for("Executive summary", 1)

        row = _governed_metric(db, workspace, section_key=key)
        row.freshness = bind.NEW_AVAILABLE
        db.flush()

        built = ctx.build(db, workspace.id, kind="stale_metrics")
        assert built.action == ctx.REFRESH_AFFECTED
        assert "Executive summary" in built.prompt
        assert any("Nothing is rewritten" in c for c in built.caveats)

    def test_an_unconfirmed_stale_suggestion_is_not_a_reason_to_refresh(
            self, db, workspace):
        row = _suggested_metric(db, workspace)
        row.freshness = bind.NEW_AVAILABLE
        db.flush()
        with pytest.raises(ctx.UnknownContext):
            ctx.build(db, workspace.id, kind="stale_metrics")

    def test_a_decision_can_be_drafted_but_not_taken(self, db, workspace):
        decision = gov.propose_decision(
            db, workspace.id, question="Hold the Stage 2 overlay?",
            current_position="SAR 41.00 million",
            proposed_position="SAR 45.00 million")
        built = ctx.build(db, workspace.id, kind="decision",
                          target=str(decision.id))

        assert built.action == ctx.DRAFT_RECOMMENDATION
        assert "Hold the Stage 2 overlay?" in built.prompt
        assert any("is a person's act" in c for c in built.caveats)

    def test_an_unknown_kind_names_what_is_known(self, db, workspace):
        with pytest.raises(ctx.UnknownContext) as raised:
            ctx.build(db, workspace.id, kind="vibes")
        assert "metric" in str(raised.value) and "finding" in str(raised.value)

    def test_a_kind_that_needs_a_target_refuses_without_one(self, db,
                                                            workspace):
        with pytest.raises(ctx.UnknownContext) as raised:
            ctx.build(db, workspace.id, kind="finding")
        assert "needs a finding to point at" in str(raised.value)


# ============================================== the context travels with it


@pytest.mark.usefixtures("db")
class TestTheContextTravelsWithTheTurn:

    def test_the_governed_reading_becomes_citable_evidence(
            self, db, scope, workspace):
        row = _governed_metric(db, workspace)
        built = ctx.build(db, workspace.id, kind="metric", target=str(row.id))

        ledger = service.ledger_for(db, scope, workspace.id, source_ids=[],
                                    chat_context=built)
        assert "xlsx://Coverage!B12" in ledger.locators()
        assert "5.86%" in ledger.render()

    def test_a_suggestion_adds_nothing_to_the_ledger(self, db, scope,
                                                     workspace):
        row = _suggested_metric(db, workspace)
        built = ctx.build(db, workspace.id, kind="metric", target=str(row.id))

        ledger = service.ledger_for(db, scope, workspace.id, source_ids=[],
                                    chat_context=built)
        assert ledger.items == []

    def test_the_message_records_what_the_turn_referred_to(
            self, db, scope, workspace):
        """A month later the thread still says which finding "draft an answer
        to this" meant."""
        finding = gov.raise_finding(db, workspace.id, origin=gov.FROM_RULE,
                                    title="Coverage fell")
        started = service.begin_generation(
            db, scope, workspace.id, text="Draft an answer.",
            context_kind="finding", context_target=str(finding.id))

        from backend.models.playbook import PlaybookMessage

        message = db.get(PlaybookMessage, started["user_message_id"])
        [reference] = ctx.references_of(message)
        assert reference["kind"] == "finding"
        assert reference["id"] == str(finding.id)
        assert reference["label"] == "Coverage fell"

    def test_a_turn_with_no_context_records_none(self, db, scope, workspace):
        started = service.begin_generation(db, scope, workspace.id,
                                           text="Write the report.")
        from backend.models.playbook import PlaybookMessage

        message = db.get(PlaybookMessage, started["user_message_id"])
        assert ctx.references_of(message) == []
        assert message.content == {"text": "Write the report."}

    def test_a_context_that_vanished_does_not_fail_the_turn(
            self, db, scope, workspace):
        """The question still stands and is still answerable. What it loses is
        the evidence the dashboard would have supplied."""
        assert service.resolve_context(db, workspace.id, kind="finding",
                                       target="99999999") is None
        started = service.begin_generation(
            db, scope, workspace.id, text="Draft an answer.",
            context_kind="finding", context_target="99999999")
        assert started["user_message_id"]

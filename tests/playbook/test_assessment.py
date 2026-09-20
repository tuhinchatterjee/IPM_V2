"""
The completion assessment. Chapters 12 and 16.

A user waited, received a Word file and a PDF, and was told nothing about
either — not which sections had been written, not which figures had no source,
not which of the attached sources had actually been read, not where the time
had gone. Every one of those was in the database. None of it was ever said.

These tests hold the line the specification draws through the middle of it:
the counts are counted, and the written note is a reading of those counts and
nothing else. A card that came from a model would be an invented completion
figure, which chapter 12 forbids by name; a verdict shown without the card
beside it would be the same thing in prose.
"""

from __future__ import annotations

import pytest

from backend.playbook import assessment, service

REPORT_MD = """# Auto Loan Development Report

## 1. Scope

The model covers the auto-loan book and the twelve months to June 2026. It was
developed on the application sample and is used at origination only.

## 2. Results

Weighted ECL was SAR 22.77 million, and the Gini coefficient reached 0.epsilon
which is not a number. The out-of-time Gini was 71.4 per cent.

## 3. Out-of-time testing

The requested out-of-time testing evidence was not provided, so this section
cannot be completed.
"""


@pytest.fixture
def ledger_calcs():
    from backend.playbook.fixtures import ecl_oracle as oracle

    return list(oracle.headline().values())


@pytest.fixture
def job(db, scope, workspace):
    started = service.begin_generation(
        db, scope, workspace.id, text="Write the report.",
        idempotency_key=f"ws{workspace.id}:assessment-test")
    return started["job_id"]


@pytest.fixture
def delivered(db, scope, workspace, job, ledger_calcs, scripted_author,
              results_workbook_xlsx):
    """One real turn: a workbook with a hidden sheet, a report with a gap
    section and a figure no evidence supports."""
    source = service.add_source(
        db, scope, workspace.id, filename="results.xlsx",
        content=results_workbook_xlsx, source_role="results")
    scripted_author(REPORT_MD)
    result = service.run_generation(
        db, scope, workspace.id, job_id=job, text="Write the report.",
        source_ids=[source.id], calculations=ledger_calcs)
    return result


class TestTheCardIsCounted:
    """Every number in it is read back from a row that was already written."""

    def test_a_section_that_states_a_gap_is_not_a_written_one(
            self, db, workspace, delivered):
        card = assessment.of(db, workspace.id)

        assert card.available
        assert card.gaps == ["3. Out-of-time testing"], (
            "a section whose whole body says the evidence is missing counts "
            "as written")
        assert "3. Out-of-time testing" not in card.thin
        assert card.written == card.sections - len(card.gaps) - len(card.thin)

    def test_a_figure_with_no_source_is_named_with_its_section(
            self, db, workspace, delivered):
        card = assessment.of(db, workspace.id)

        found = {f for finding in card.untraceable
                 for f in finding["figures"]}
        assert "71.4" in found, (
            f"the unsupported figure was not reported; card said {found}")
        where = next(f["section"] for f in card.untraceable
                     if "71.4" in f["figures"])
        assert "Results" in where

    def test_evidence_read_in_part_is_reported_as_read_in_part(
            self, db, workspace, delivered):
        """The workbook has a hidden sheet, so the manifest is incomplete.
        "I read all of it" and "I read the sheets I could" are different
        claims and the card makes them different."""
        card = assessment.of(db, workspace.id)

        assert len(card.sources) == 1
        source = card.sources[0]
        assert source["filename"] == "results.xlsx"
        assert source["complete"] is False
        assert source["skipped"], "nothing said what was not read"
        assert source["cited"] > 0, "the source reached the document"

    def test_the_files_are_reported_by_name(self, db, workspace, delivered):
        card = assessment.of(db, workspace.id)

        assert sorted(card.delivered) == ["docx", "pdf"]
        assert card.failed == {}

    def test_the_time_is_split_between_writing_and_building(
            self, db, workspace, delivered):
        """Three durations were measured on every run and read by nothing, so
        a user who waited could not be told what for.

        Asserted against the stored row rather than on a stopwatch: the
        provider here is a stand-in that returns in under a millisecond, so
        "authoring took some time" is a statement about the fixture. What has
        to hold is that the measurements were kept and that the card reports
        them rather than recomputing anything.
        """
        from backend.playbook import repository as repo
        from backend.playbook.intelligence import service as intel

        artifact = intel._current_artifact(db, workspace.id)
        version = repo.versions(db, artifact.id)[-1]
        stored = (version.validation or {}).get("timings")
        assert stored is not None, "the durations were measured and discarded"
        assert set(stored) == {"authoring_ms", "render_ms", "provider_ms"}

        card = assessment.of(db, workspace.id)
        assert card.time["authoring_ms"] == stored["authoring_ms"]
        assert card.time["render_ms"] == stored["render_ms"]
        assert card.time["total_ms"] == (stored["authoring_ms"]
                                         + stored["render_ms"])

    def test_nothing_is_claimed_to_be_reviewed(self, db, workspace, delivered):
        card = assessment.of(db, workspace.id)

        assert card.review["state"] == "draft"

    def test_a_workspace_with_no_document_says_so(self, db, scope, workspace):
        card = assessment.of(db, workspace.id)

        assert card.available is False
        assert card.reason
        assert card.as_dict()["sections"]["total"] == 0, (
            "a workspace with no document has not finished anything and has "
            "not failed at anything either")


class TestTheCardIsAboutWhatThisTurnWrote:
    """Not about whatever the workspace's current artifact happens to be."""

    def test_it_reads_the_version_the_turn_named(
            self, db, scope, workspace, delivered):
        """A second artifact in the same workspace — a deck made from the
        report — must be described by its own card. Read off the workspace's
        current artifact instead, a deck's message would list the report's
        Word and PDF files, which that turn did not deliver."""
        from backend.playbook import assessment as card_module
        from backend.playbook import repository as repo
        from backend.playbook import service as svc

        ledger = svc.ev.Ledger()
        outcome = svc.author_document(
            db, scope, workspace.id,
            instruction="Turn it into a deck.", ledger=ledger,
            title="Auto Loan deck", formats=["pptx"])

        deck = card_module.of(db, workspace.id, version_id=outcome.version_id)
        assert deck.delivered == ["pptx"]

        # And the report's own card is unchanged by the deck existing.
        report = repo.artifacts(db, workspace.id)[0]
        first = repo.versions(db, report.id)[0]
        assert sorted(card_module.of(
            db, workspace.id, version_id=first.id).delivered) == [
                "docx", "pdf"]

    def test_the_turn_asks_for_the_version_it_just_wrote(
            self, db, scope, workspace, job, ledger_calcs, scripted_author,
            monkeypatch):
        """The wiring, not the reading.

        `_current_artifact` answers "reports before decks, newest last", which
        is right for a dashboard and wrong for a message: a turn that revised
        an earlier report while a deck exists would have its card read off the
        deck. The turn names the version it wrote; this asserts it is asked
        for.
        """
        from backend.playbook import assessment as card_module

        seen: dict = {}
        real = card_module.for_delivery

        def spy(session, workspace_id, *, version_id=None):
            seen["version_id"] = version_id
            return real(session, workspace_id, version_id=version_id)

        monkeypatch.setattr(card_module, "for_delivery", spy)
        scripted_author(REPORT_MD)
        result = service.run_generation(
            db, scope, workspace.id, job_id=job, text="Write the report.",
            calculations=ledger_calcs)

        assert seen["version_id"] == result["version_id"]
        assert seen["version_id"] is not None

    def test_a_version_from_another_workspace_is_not_readable(
            self, db, scope, workspace, delivered):
        from backend.playbook import assessment as card_module
        from backend.playbook import repository as repo

        other = repo.create_workspace(db, scope, title="Somebody else's",
                                      document_family="")
        db.flush()
        card = card_module.of(db, other.id,
                              version_id=delivered["version_id"])
        assert card.available is False


class TestAssessingItIsAStepOfTheRun:
    """It is a provider call, so it is announced — and it is over before the
    job says it is."""

    def test_the_step_is_named_while_it_happens(self, db, job, delivered):
        from backend.models.playbook import PlaybookJob

        row = db.get(PlaybookJob, job)
        assert any(m["state"] == "validating"
                   and "assessing" in (m["detail"] or "")
                   for m in (row.milestones or [])), (
            "the run went quiet for another call with nothing on screen")

    def test_a_finished_job_is_ready_and_not_stuck_in_its_last_step(
            self, db, job, delivered):
        """`milestone` writes the job's state. Announcing this step after the
        job was marked ready left every finished generation sitting at
        "validating" — finished, with a state saying it was still working,
        and any caller polling for "ready" waiting for ever."""
        from backend.models.playbook import PlaybookJob

        row = db.get(PlaybookJob, job)
        assert row.finished_at is not None
        assert row.state == "ready", (
            f"a finished generation reports {row.state!r}")


class TestTheWrittenVerdictKnowsOnlyTheCard:

    def test_it_is_given_the_card_and_not_the_document(
            self, db, workspace, delivered, scripted_author):
        given = scripted_author.state["assessment_calls"][-1]["given"]

        assert "3. Out-of-time testing" in given, "the card itself is missing"
        # The document's own prose, the evidence and the conversation are all
        # absent: it has nothing to invent a figure from.
        assert "The model covers the auto-loan book" not in given
        assert "Write the report." not in given
        assert "SUMPRODUCT" not in given

    def test_it_is_bounded(self, db, workspace, delivered, scripted_author):
        asked = scripted_author.state["assessment_calls"][-1]
        assert asked["max_tokens"] == assessment.VERDICT_MAX_TOKENS
        assert asked["max_tokens"] < 2000, (
            "a note about a report should not cost what the report cost")

    def test_it_is_labelled_as_what_it_is(self, db, workspace, delivered):
        card = assessment.of(db, workspace.id)
        card = assessment.write_verdict(card)

        assert card.verdict
        assert card.verdict_state == "written"

    def test_it_can_be_turned_off_without_touching_code(
            self, db, workspace, delivered, monkeypatch):
        monkeypatch.setenv("PLAYBOOK_WRITTEN_ASSESSMENT", "0")
        card = assessment.write_verdict(assessment.of(db, workspace.id))

        assert card.verdict == ""
        assert card.verdict_state == "off"
        # And the counts are still there, because they never needed a model.
        assert card.gaps and card.delivered

    def test_a_verdict_that_fails_never_costs_the_report(
            self, db, workspace, delivered, monkeypatch):
        from backend.playbook import provider

        def refuse(*a, **kw):
            raise provider.AuthoringError("no", category="overloaded")

        monkeypatch.setattr(provider, "_call", refuse)
        card = assessment.write_verdict(assessment.of(db, workspace.id))

        assert card.verdict_state == "unavailable"
        assert card.verdict == ""
        assert card.delivered == ["docx", "pdf"], (
            "the files are what the user asked for; the note about them is not")


class TestItReachesTheReader:

    def test_the_message_carries_it(self, db, workspace, delivered):
        from backend.playbook import repository as repo

        message = [m for m in repo.messages(db, workspace.id)
                   if m.role == "assistant"][-1]
        card = message.content.get("assessment") or {}

        assert card.get("available") is True
        assert card["sections"]["gaps"] == ["3. Out-of-time testing"]
        assert card["files"]["delivered"] == ["docx", "pdf"]
        assert card["verdict"], "the written note was not carried"
        assert card["verdict_state"] == "written"

    def test_a_turn_that_wrote_nothing_carries_no_assessment(
            self, db, scope, workspace, scripted_author):
        """An assessment of a conversation is an assessment of nothing."""
        scripted_author("", makes_document=False,
                        chat_text="A development report explains how a model "
                                  "was built; a validation report tests it.")
        started = service.begin_generation(
            db, scope, workspace.id, text="What is the difference?",
            idempotency_key=f"ws{workspace.id}:question")
        result = service.run_generation(
            db, scope, workspace.id, job_id=started["job_id"],
            text="What is the difference?")

        assert result["assessment"] == {}
        assert scripted_author.state["assessment_calls"] == [], (
            "a turn with no document paid for an assessment of nothing")

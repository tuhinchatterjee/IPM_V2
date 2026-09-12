"""The saved report is grounded, not the first draft. PB-015.

Written from the live failure, whose whole diagnosis was "grounding FAILED".
Two things were wrong behind it.

*The check asserted the wrong thing.* `grounding.check` removes what the
evidence does not support and reports what it removed, so `ok` is False
whenever the model reached for a figure it did not have — even though the
document that came out the other side was clean. The product contract is about
the artifact CreditProbe saves, not about Opus being flawless on a first draft.
So authoring now runs the check twice: once to repair and record the attempt,
once to verify what repair produced, and nothing is persisted or rendered
unless that second pass is clean.

*And a committee paper is full of digits that are not claims.* CET1, IFRS 9,
v2.1, "see section 10.2", "30 June", "Q2 2026". Requiring evidence for those
buried the findings that matter — and, because the same extractor builds the
supported set from the evidence, a spurious token from a source could EXCUSE a
real claim somewhere else. One classifier, by syntactic position, applied to
both sides.

Every test that exempts a numeral has a sibling that rejects the same digits in
a claim. No value is exempt anywhere.
"""

from __future__ import annotations

import pytest

from backend.playbook import document as D
from backend.playbook import evidence as ev
from backend.playbook import grounding, provider, service, validate
from backend.playbook import repository as repo

TITLE = "IFRS 9 Committee Report — Q2 2026"

REPORT_MD = """# IFRS 9 Committee Report — Q2 2026

## 1. Executive summary

Weighted ECL rose to SAR 22.77 million.

## 2. Scenario results

| Scenario | ECL |
| --- | --- |
| Base | 19.2 |

## 3. Limitations

Post-model adjustments are outside scope.
"""


@pytest.fixture
def ledger():
    led = ev.Ledger()
    led.add(ev.Item("xlsx://ECL!B2", "sheet_range",
                    "Weighted ECL 22.77 Base 19.20 Downturn 36.00"))
    return led


def _run(db, scope, workspace, ledger, **kwargs):
    return service.author_document(
        db, scope, workspace.id, instruction="Write the committee report.",
        ledger=ledger, title=TITLE, **kwargs)


# ================================================= what counts as a figure

class TestTheClassifierNamesWhatEachNumberIs:
    """Every class the failure diagnostic has to be able to report."""

    @pytest.mark.parametrize("text,token,kind", [
        ("Exposure of SAR 10 million was drawn.", "10", validate.CURRENCY),
        ("Weighted ECL was SAR 22.77m.", "22.77", validate.CURRENCY),
        ("Coverage stood at 10%.", "10", validate.PERCENTAGE),
        ("Coverage fell 2.5 per cent.", "2.5", validate.PERCENTAGE),
        ("The spread widened by 10 basis points.", "10",
         validate.BASIS_POINTS),
        ("A spread of 150bps was applied.", "150", validate.BASIS_POINTS),
        ("10 accounts migrated.", "10", validate.COUNT),
        ("The model returned 10.0.", "10", validate.COUNT),
        ("Stage 2 exposures were reviewed.", "2", validate.STAGE_LABEL),
        ("The review completed on 30 June 2026.", "30", validate.DATE),
        ("Due 30/06/2026.", "30", validate.DATE),
        ("See section 10.2 for detail.", "10.2",
         validate.SECTION_REFERENCE),
        ("Table 3 sets out the results.", "3", validate.SECTION_REFERENCE),
        ("CET1 closed at 14.9 per cent.", "1", validate.IDENTIFIER),
        ("PD model v2.1 was recalibrated.", "2.1", validate.IDENTIFIER),
        ("COVID-19 overlays were retained.", "-19", validate.IDENTIFIER),
        ("Model LGD-2026-v3 was used.", "3", validate.IDENTIFIER),
    ])
    def test_the_class(self, text, token, kind):
        found = {f.token: f.kind for f in validate.classify(text)}
        assert found[token] == kind

    def test_only_the_evidence_bearing_classes_have_to_reconcile(self):
        assert validate.EVIDENCE_BEARING == {
            validate.CURRENCY, validate.PERCENTAGE, validate.BASIS_POINTS,
            validate.COUNT, validate.STAGE_LABEL}

    def test_a_plain_integer_in_prose_is_never_exempt(self):
        """COUNT is the default, so nothing is exempt by being small."""
        for sentence in ("10 accounts migrated.", "We reviewed 7 files.",
                         "The portfolio holds 3 obligors.", "Losses were 42."):
            assert validate.figures(sentence)

    def test_a_sign_is_part_of_the_figure(self):
        """-2.5 and 2.5 are different claims and must not collapse."""
        assert validate.figures("A movement of -2.5% was seen.") == {"-2.5"}
        assert validate.figures("A movement of 2.5% was seen.") == {"2.5"}

    def test_a_number_is_not_classified_by_a_word_on_another_line(self):
        """Documents arrive as `plain_text()`, one block per line. A heading
        ending in "June" must not make the next block's figure a date."""
        assert validate.figures("Position at 30 June\n1,050 accounts") == \
            {"1050"}


class TestTheLedgerAndTheDocumentUseOneRule:
    """The half that would otherwise be a hole: a spurious token extracted
    from evidence would land in the supported set and excuse a real claim."""

    def test_an_identifier_in_the_evidence_cannot_excuse_a_claim(self):
        led = ev.Ledger()
        led.add(ev.Item("xlsx://A1", "sheet_range", "CET1 ratio reported"))
        assert "1" not in led.figures()

        doc = D.parse("## 1. Summary\n\nThe book holds 1 obligor.\n",
                      title="R")
        result = grounding.check(doc, led)
        assert result.ok is False

    def test_a_date_in_the_evidence_cannot_excuse_a_claim(self):
        led = ev.Ledger()
        led.add(ev.Item("xlsx://A1", "sheet_range", "As at 30 June 2026"))
        assert "30" not in led.figures()

    def test_a_supported_figure_still_reconciles(self):
        led = ev.Ledger()
        led.add(ev.Item("xlsx://A1", "sheet_range", "Weighted ECL 22.77"))
        doc = D.parse("## 1. Summary\n\nECL was SAR 22.77 million.\n",
                      title="R")
        assert grounding.check(doc, led).ok is True


# ======================================================== the two-stage gate

@pytest.mark.usefixtures("db")
class TestTheSavedReportIsGrounded:

    def test_the_draft_attempt_and_the_saved_result_are_reported_apart(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(REPORT_MD.replace(
            "Post-model adjustments are outside scope.",
            "Coverage reached 41.5 per cent."))
        outcome = _run(db, scope, workspace, ledger)

        assert outcome.grounding.ok is False       # the model attempted it
        assert outcome.grounding_final.ok is True  # the saved report is clean

    def test_the_persisted_version_passes_grounding_when_read_back(
            self, db, scope, workspace, ledger, scripted_author):
        """Not the in-memory object — the row. This is the product contract."""
        scripted_author(REPORT_MD.replace(
            "Post-model adjustments are outside scope.",
            "Coverage reached 41.5 per cent."))
        outcome = _run(db, scope, workspace, ledger)

        stored = D.Document.from_dict(
            repo.versions(db, outcome.artifact_id)[0].content)
        assert grounding.check(stored, ledger, remove=False).ok is True

    def test_the_supported_figure_survives_the_repair(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(REPORT_MD.replace(
            "Post-model adjustments are outside scope.",
            "Coverage reached 41.5 per cent."))
        outcome = _run(db, scope, workspace, ledger)
        assert "22.77" in validate.figures(outcome.document.plain_text())

    def test_a_clean_draft_needs_no_repair(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(REPORT_MD)
        outcome = _run(db, scope, workspace, ledger)
        assert outcome.grounding.ok is True
        assert outcome.grounding_final.ok is True

    def test_the_audit_record_keeps_both_passes(
            self, db, scope, workspace, ledger, scripted_author):
        scripted_author(REPORT_MD.replace(
            "Post-model adjustments are outside scope.",
            "Coverage reached 41.5 per cent."))
        outcome = _run(db, scope, workspace, ledger)
        stored = repo.versions(db, outcome.artifact_id)[0].validation
        assert stored["grounding"]["attempted"]["ok"] is False
        assert stored["grounding"]["saved"]["ok"] is True
        classified = stored["grounding"]["attempted"]["classified"]
        assert classified[0]["figures"][0]["token"] == "41.5"
        assert classified[0]["figures"][0]["kind"] == validate.PERCENTAGE

    def test_a_run_whose_repair_does_not_converge_is_refused(
            self, db, scope, workspace, ledger, scripted_author, monkeypatch):
        """The refusal that makes the gate a gate. If the second pass is not
        clean, nothing is saved — a stored report that looks grounded and is
        not is the one outcome worse than a failure."""
        real = grounding.check
        calls = {"n": 0}

        def stubborn(*args, **kwargs):
            result = real(*args, **kwargs)
            calls["n"] += 1
            if calls["n"] == 2:          # the verification pass
                result.findings.append(grounding.Finding(
                    locator_free_text="Coverage reached 41.5 per cent.",
                    figures=["41.5"], section="3. Limitations",
                    action="flagged", block_kind="paragraph"))
            return result

        monkeypatch.setattr(service.grounding, "check", stubborn)
        scripted_author(REPORT_MD)
        with pytest.raises(provider.AuthoringError) as raised:
            _run(db, scope, workspace, ledger)
        assert raised.value.category == "grounding"
        assert "41.5" in str(raised.value)
        assert not repo.artifacts(db, workspace.id)


# ========================================================= coherence

class TestRemovalMayNotProduceAHollowReport:

    def _ledger(self) -> ev.Ledger:
        led = ev.Ledger()
        led.add(ev.Item("xlsx://A1", "sheet_range", "Weighted ECL 22.77"))
        return led

    def test_a_list_whose_every_item_went_is_hollow(self):
        before = D.parse("## 3. Findings\n\n- Losses were 41.5\n"
                         "- Coverage was 88.1\n", title="R")
        after = D.Document.from_dict(before.as_dict())
        grounding.check(after, self._ledger())
        assert grounding.emptied_sections(before, after) == ["3. Findings"]

    def test_a_table_whose_every_cell_went_is_hollow(self):
        before = D.parse("## 2. Results\n\n| ECL |\n| --- |\n"
                         "| 41.5 |\n| 88.1 |\n", title="R")
        after = D.Document.from_dict(before.as_dict())
        grounding.check(after, self._ledger())
        assert grounding.emptied_sections(before, after) == ["2. Results"]

    def test_a_table_that_keeps_its_row_labels_is_not_hollow(self):
        """The honest limit of the rule. A scenario table whose figures went
        still tells the reader which scenarios were considered and that their
        values could not be traced — thin, but not incoherent."""
        before = D.parse("## 2. Results\n\n| Scenario | ECL |\n| --- | --- |\n"
                         "| Base | 41.5 |\n", title="R")
        after = D.Document.from_dict(before.as_dict())
        grounding.check(after, self._ledger())
        assert grounding.emptied_sections(before, after) == []

    def test_an_honest_replacement_sentence_is_not_hollow(self):
        """Saying plainly that a figure could not be traced is the point of
        removing rather than warning. It is content, and it ships."""
        before = D.parse("## 1. Summary\n\nCoverage reached 41.5 per cent.\n",
                         title="R")
        after = D.Document.from_dict(before.as_dict())
        grounding.check(after, self._ledger())
        assert grounding.emptied_sections(before, after) == []
        assert grounding.REPLACEMENT in after.plain_text()

    def test_an_untouched_section_is_never_called_hollow(self):
        before = D.parse("## 1. Summary\n\nECL was SAR 22.77 million.\n",
                         title="R")
        after = D.Document.from_dict(before.as_dict())
        grounding.check(after, self._ledger())
        assert grounding.emptied_sections(before, after) == []

    @pytest.mark.usefixtures("db")
    def test_a_hollow_report_is_refused_and_nothing_is_saved(
            self, db, scope, workspace, scripted_author):
        scripted_author("# R\n\n## 1. Summary\n\nECL was SAR 22.77 million.\n"
                        "\n## 3. Findings\n\n- Losses were 41.5\n"
                        "- Coverage was 88.1\n")
        with pytest.raises(provider.AuthoringError) as raised:
            _run(db, scope, workspace, self._ledger())
        assert raised.value.category == "grounding_incoherent"
        assert "3. Findings" in str(raised.value)
        assert not repo.artifacts(db, workspace.id)


# ========================================================= the diagnostic

class TestAFailureCanBeActedOn:
    """The live run must never again be able to say only "grounding FAILED"."""

    def _result(self) -> grounding.GroundingResult:
        led = ev.Ledger()
        led.add(ev.Item("xlsx://A1", "sheet_range", "Weighted ECL 22.77"))
        doc = D.parse(
            "## 1. Summary\n\nExposure of SAR 41.5 million was drawn.\n\n"
            "## 2. Results\n\n| Scenario | ECL |\n| --- | --- |\n"
            "| Base | 88.1 |\n\n"
            "## 3. Findings\n\n- Coverage moved 12 basis points\n", title="R")
        return grounding.check(doc, led)

    def test_every_finding_names_its_section_block_and_class(self):
        result = self._result()
        assert not result.ok
        kinds = {f.block_kind for f in result.findings}
        assert kinds == {"paragraph", "table", "bullets"}
        for finding in result.findings:
            assert finding.section
            assert finding.classes and finding.classes[0]["kind"]
            assert finding.classes[0]["context"]

    def test_the_tokens_are_grouped_by_kind(self):
        assert self._result().by_kind() == {
            validate.BASIS_POINTS: ["12"],
            validate.COUNT: ["88.1"],
            validate.CURRENCY: ["41.5"],
        }

    def test_the_report_is_one_readable_line_per_finding(self):
        report = self._result().report()
        assert "41.5 (financial claim)" in report
        assert "1. Summary [paragraph] removed" in report
        assert "Exposure of SAR 41.5 million was drawn." in report

    def test_a_clean_result_says_so(self):
        led = ev.Ledger()
        led.add(ev.Item("xlsx://A1", "sheet_range", "22.77"))
        doc = D.parse("## 1. Summary\n\nECL was SAR 22.77 million.\n",
                      title="R")
        assert grounding.check(doc, led).report() == "no unsupported figure"


# ================================================== the invented-test check

class TestAnHonestDisclosureIsNotAnInvention:
    """PB-015 requires that the report never claim a test it did not run AND
    that it name missing evidence honestly. A substring match cannot serve
    both: "no backtest was performed" contains "backtest was performed"."""

    def test_a_claimed_test_is_caught(self):
        from backend.validation.live_playbook import _tests_claimed_but_not_run

        assert _tests_claimed_but_not_run(
            "A backtest was performed and the model passed.")
        assert _tests_claimed_but_not_run(
            "The backtest shows a 2 per cent drift.")

    def test_an_honest_absence_is_not(self):
        from backend.validation.live_playbook import _tests_claimed_but_not_run

        for honest in ("No backtest was performed for this period.",
                       "We were unable to confirm that a backtest was "
                       "performed.",
                       "The report is issued without a backtest; no "
                       "backtesting was performed."):
            assert _tests_claimed_but_not_run(honest) == [], honest

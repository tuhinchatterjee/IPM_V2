# Save-gate regression matrix — §19

Every defect found in human UAT of the save gate, with the test that now
stops it coming back. These are not historical notes: each row names a test
that runs in `tests/playbook` on every run, and
`tests/playbook/test_save_gate_matrix.py` fails if a row names a test that
does not exist, if a row is missing, or if any row reports anything but PASS.

**What PASS means here, exactly.** The matrix cannot make a test pass by
saying so. The status column is a claim about the last recorded run of
`tests/playbook`, stated in *Evidence* below with its counts; the mechanical
check only proves that the named test exists and is not skipped or expected to
fail. A row whose test was deleted, renamed or quarantined therefore fails the
matrix check rather than quietly continuing to read PASS.

Each row names one **primary** test — the one that reproduces the original
failure in its original shape. Most classes carry more than that; the
companion tests are named beneath the table.

| # | Failure class | Layer | Regression test | Expected behaviour | Status |
|---|---|---|---|---|---|
| 1 | Title duplicated as a normal section | canonical document | `tests/playbook/test_title_is_not_a_section.py::TestTheTitleIsRepresentedOnce::test_the_title_is_not_also_a_section` | A leading heading that is the document's title becomes `doc.title`, not a first empty section; the validator never reports the title as a missing section | PASS |
| 2 | Long PDF heading wraps and defeats the check | rendered-file validation | `tests/playbook/test_title_is_not_a_section.py::TestOnlyWhitespaceIsNormalised::test_a_wrapped_line_matches_the_unwrapped_heading` | A heading reportlab wrapped across lines still matches; only whitespace is normalised, never words, digits or dashes | PASS |
| 3 | Structural numerals misclassified as claims | rendered-file validation | `tests/playbook/test_structural_numerals.py::TestTheExactLiveFailure::test_the_pdf_that_was_rejected_now_validates` | A renderer-generated list ordinal or page number is classified by its syntactic position, not exempted by value; the same digits in prose are still claims | PASS |
| 4 | Raw vs displayed spreadsheet values | ingestion | `tests/playbook/test_spreadsheet_precision.py::TestTheSameFactGroundsEitherWay::test_the_ledger_carries_both_readings` | One cell yields exactly two admissible readings — as stored and as the workbook displays it — and no third, so no tolerance is introduced | PASS |
| 5 | Stale parser revisions | source parsing | `tests/playbook/test_reparse.py::TestReReading::test_a_stale_source_says_what_a_re_read_would_find` | A reading made by a reader behind the one in force is reported stale, with what a re-read would now find | PASS |
| 6 | Global numeric collision | grounding | `tests/playbook/test_grounding_gate.py::TestTheLedgerAndTheDocumentUseOneRule::test_an_identifier_in_the_evidence_cannot_excuse_a_claim` | A number that appears in the evidence as a date, a version or an identifier cannot ground a financial claim; both sides are classified by the same rule | PASS |
| 7 | Re-rounded unsupported numeric value | grounding | `tests/playbook/test_grounding.py::TestReRoundingIsInvention::test_a_re_rounded_percentage_does_not_survive` | `8.95 → 8.9` is an invention and is removed; the exact figure survives; trailing zeros are the same figure, not a new one | PASS |
| 8 | Canonical vs rendered figure mismatch | rendering | `tests/playbook/test_spreadsheet_precision.py::TestTheReportSurvivesTheSaveGate::test_the_governed_value_is_rendered_consistently` | What the canonical document states is what the DOCX and the PDF state; classification is the same on both sides | PASS |
| 9 | Unsupported figure sanitisation | grounding | `tests/playbook/test_grounding_gate.py::TestTheSavedReportIsGrounded::test_the_persisted_version_passes_grounding_when_read_back` | Removal happens before commit, and the SAVED version passes the check when read back — not merely the draft after repair | PASS |
| 10 | Missing substantive section | rendered-file validation | `tests/playbook/test_title_is_not_a_section.py::TestWhatMustStillFail::test_a_missing_substantive_section_fails` | A section the document carries but the file does not still fails, in DOCX and PDF alike | PASS |
| 11 | Title mismatch | rendered-file validation | `tests/playbook/test_title_is_not_a_section.py::TestWhatMustStillFail::test_a_wrong_title_fails_with_a_title_diagnostic` | A wrong or absent title fails with a title-specific diagnostic, not as "a missing section" | PASS |
| 12 | Parser re-read | source parsing | `tests/playbook/test_reparse.py::TestReReading::test_a_re_read_uses_the_stored_bytes_and_makes_a_new_revision` | Re-reading uses the stored immutable bytes, needs no upload and no provider call, writes a new revision and supersedes the old one without deleting it | PASS |
| 13 | Stale source used during generation | evidence assembly | `tests/playbook/test_reparse.py::TestAStaleSourceIsNeverUsedSilently::test_a_stale_source_is_an_evidence_gap` | A source read by an older reader is recorded as an evidence gap, so `evidence_complete` is False and the thread says so; it is still read, never silently withheld | PASS |
| 14 | Scoped edit modifying an unrelated section | merge | `tests/playbook/test_scoped_edit_fidelity.py::TestTheLiveShape::test_no_unrelated_section_changes_in_canonical_storage` | Every section outside the scope is byte-identical in canonical STORAGE, not merely in memory; the merge base is the stored document, never a re-render | PASS |
| 15 | Provider timeout | provider transport | `tests/playbook/test_provider_bounds.py::TestAStalledStreamIsStopped::test_a_stream_that_stalls_mid_response_times_out` | A stalled stream is stopped by a real deadline rather than running forever, and a timed-out generation is never retried automatically | PASS |
| 16 | Missing AUTHOR model | provider configuration | `tests/playbook/test_provider_bounds.py::TestAuthorRefusesWithoutAModel::test_it_fails_before_the_sdk_is_ever_called` | No model id resolves → refused before the SDK is called, and `status()` reports unconfigured rather than claiming to be ready | PASS |
| 17 | Duplicate generation on refresh | job queue | `tests/playbook/test_streaming.py::TestARefreshDoesNotStartASecondGeneration::test_the_same_key_finds_the_running_job` | A refresh, a double-click or a reconnect finds the running job; no second billable generation and no second question in the thread | PASS |
| 18 | Incomplete stream being saved | streaming | `tests/playbook/test_streaming.py::TestAnInterruptedStreamIsNotAnAnswer::test_a_half_streamed_answer_is_not_in_the_thread_at_all` | Half an answer is discarded, not shown as the answer; the partial text exists only in the event log | PASS |
| 19 | Partial failed artifact replacing the last valid one | persistence | `tests/playbook/test_service.py::TestAVersionIsOnlyWrittenWhenEverythingHeld::test_a_failed_generation_leaves_the_previous_version_current` | A failed generation writes no version and no file; the previous good version stays current and downloadable | PASS |

## Companion tests

The primary test reproduces the original failure. These hold the rest of the
class, and are what stop the fix being narrowed back to the single case that
was reported.

* **1, 10, 11** — `test_title_is_not_a_section.py` also pins that a first
  heading WITH content stays a section, that no section is swallowed with the
  title, and that a missing title and a wrong title give different
  diagnostics.
* **2** — `TestOnlyWhitespaceIsNormalised` pins the boundary from the other
  side: an em dash is not a hyphen, a changed word is not absorbed, a changed
  digit is not absorbed.
* **3** — `TestWhatMustStillBeEvidenced` re-checks currency, percentages,
  basis points, stage labels, counts and model results as claims, and
  `test_a_structural_marker_does_not_launder_the_rest_of_its_line` pins that
  an exempt marker exempts only itself.
* **4, 8** — `TestTheExactAutoLoanFailure` walks each of the eight values the
  human UAT rejected, and `test_no_epsilon_was_introduced` proves the fix
  admitted two readings rather than a tolerance.
* **5, 12, 13** — `test_reparse.py` covers the version rules themselves
  (older is stale, newer is left alone, unparseable counts as stale), lineage
  across a re-read, that a re-read reaches no provider and writes no document
  version, and that re-reading closes the evidence gap.
* **6, 7, 9** — `test_grounding_gate.py::TestRemovalMayNotProduceAHollowReport`
  pins that sanitisation may not leave an empty document standing as a clean
  one, and `test_a_run_whose_repair_does_not_converge_is_refused` that the
  gate fails rather than saving.
* **14** — `TestGroundingStaysInsideTheScope` pins that narrowing the check
  did not weaken it: a figure invented inside the scope is still removed, a
  re-round inside the scope is still caught, and without a scope every section
  is still checked.
* **15, 16** — `TestATimeoutIsNeverRetriedAutomatically` and
  `test_streaming.py::TestATimeoutLeavesNothingBehind`.
* **17** — `test_a_duplicate_send_adds_no_second_question`,
  `TestRetryIsOnePerPress`.
* **18, 19** — `TestAnIncompleteAnswerCannotBeTakenAway`,
  `test_skill_files_are_discarded_when_grounding_changed_the_document`.

## Evidence

Last full run of `tests/playbook` on this branch: **949 passed, 8 skipped, 0
failed**. The 8 skips are the live provider checks, which skip without a
credential; a skip is never counted as a pass, here or anywhere else in this
work.

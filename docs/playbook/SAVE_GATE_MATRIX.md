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

Rows are addressed in two notations because two suites hold this matrix:
`file.py::Class::test` for pytest, and `file.ts::the test's name` for
`node --test`, which has no classes. The checker resolves both against the
source.

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
| 9 | Unsupported figure sanitisation | grounding | `tests/playbook/test_grounding_gate.py::TestAReviewFindingDoesNotDestroyTheDraft::test_the_sentence_the_author_wrote_is_still_there` | **Expectation superseded by Direct Chat ch. 16.** The figure is still found and is now recorded as a review item on a DRAFT version rather than deleted from the author's prose. The original defect — an unsupported figure reaching a file unremarked — is still covered: the finding is on the version, the draft is not marked reviewed, and `test_the_version_is_a_draft_with_its_items_attached` pins it | PASS |
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
* **6, 7, 9** — `test_grounding_gate.py::TestRemovalMayNotProduceAHollowReport` (the `emptied_sections` cases still hold; the SAVE REFUSAL they once drove is superseded — see row 9)
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

Last full run of `tests/playbook` on this branch: **1036 passed, 8 skipped, 0
failed**, and of the frontend suite **516 passed, 0 failed**. The 8 skips are
the live provider checks, which skip without a credential; a skip is never
counted as a pass, here or anywhere else in this work.

Running the rows' own named tests directly: 50 Python tests (parametrised
cases expand) and the frontend test named by row 28, 0 failed.

---

## The classes found after the first nineteen

§33 extends the matrix with every defect the later work uncovered. These are
held to the same standard: each names a test that runs in `tests/playbook`,
and `test_save_gate_matrix.py` fails if one is deleted, renamed or
quarantined.

| # | Failure class | Layer | Regression test | Expected behaviour | Status |
|---|---|---|---|---|---|
| 20 | Metric suggestions used as governed values | metric binding | `tests/playbook/test_context_bridge.py::TestAMetricBecomesAQuestion::test_an_unconfirmed_suggestion_never_reaches_the_ledger` | A suggestion nobody confirmed contributes no evidence, triggers no refresh and satisfies no required metric — it produces a caveat, not a fact | PASS |
| 21 | Then/Now across different populations | comparison | `tests/playbook/test_adversarial.py::TestTwoThingsThatLookLikeOneThing::test_a_snapshot_will_not_compare_across_populations` | Not comparable, with the differing dimension named, and no delta shown at all | PASS |
| 22 | Then/Now unit mismatch | comparison | `tests/playbook/test_adversarial.py::TestUnitsAreNotInterchangeable::test_a_unit_change_stops_the_comparison` | A percentage against basis points is refused rather than subtracted; a difference between two percentages is percentage POINTS | PASS |
| 23 | Section retitle loses its state | section identity | `tests/playbook/test_document_intelligence_service.py::TestSectionIdentitySurvivesARetitle::test_a_retitled_section_keeps_its_row_and_its_reviewer` | A retitle keeps the row, its status, its reviewer and everything attached to it | PASS |
| 24 | First-open readiness key divergence | dashboard payload | `tests/playbook/test_readiness.py::TestReadyMeansThereIsNothingLeftToDo::test_a_document_below_the_green_bar_is_pending_not_ready` | One payload shape from one function: the first open of a workspace answers with the same keys as every read after it | PASS |
| 25 | Duplicate idempotency key across workspaces | job queue | `tests/playbook/test_api.py::TestRestoringAndStoppingOverHTTP::test_a_key_resolves_only_inside_its_own_workspace` | A key identifies one send in one conversation; it never resolves to a job in another | PASS |
| 26 | A 29%-complete document marked ready | readiness | `tests/playbook/test_readiness.py::TestReadyMeansThereIsNothingLeftToDo::test_a_document_below_the_green_bar_is_pending_not_ready` | "Ready" means nothing is left to do: below the green bar the status is pending and says so with the number | PASS |
| 27 | A machine moving a section into review | governance boundary | `tests/playbook/test_sections_and_since_last_time.py::TestStatusTransitionsAreDeterministic::test_a_machine_may_not_move_a_section_into_review` | Section review states go through the same `require_person` guard as every other governed act; "claude" and "system" are refused, not just an empty string | PASS |
| 28 | A dashboard pane taking the page down | dashboard rendering | `frontend/src/lib/__tests__/intelligence.test.ts::a history entry without an act is still rendered` | A pane that fails says so and the rest of the dashboard keeps working; the browser suite walks every tab and asserts none reports a failure | PASS |
| 29 | Seeded state that silently matches nothing | demonstration | `tests/playbook/test_seed.py::TestTheSeededDashboardIsReal::test_every_seeded_metric_lands_in_a_real_section` | A seed naming a section the document does not have fails loudly rather than being skipped, so the demonstration cannot ship with metrics attached to nothing | PASS |

Classes 27, 28 and 29 were found by the browser suite and the soak harness
respectively, which is the argument for having both: none of them was
reachable from a unit test of the component that was wrong.

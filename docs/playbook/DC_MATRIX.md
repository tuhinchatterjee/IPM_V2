# DC-01 – DC-42

Status vocabulary, used exactly:

| | |
|---|---|
| **PASS — deterministic** | proven by a test against the real code, no browser, no provider |
| **PASS — browser scripted** | driven through the real `/playbook` UI against the scripted assistant |
| **PASS — live verified** | proven against a real model on this code |
| **BLOCKED** | cannot be proven here; the blocker is named |
| **NOT IMPLEMENTED** | the behaviour does not exist |

Two rules this table keeps. A route-level test is **not** browser-tested, and
a scripted run is **not** live. Where a row has both, both are named, and the
stronger claim never absorbs the weaker one.

**Live: nothing on this code.** `scripts/playbook_live_smoke.py` is written,
bounded and resumable; it refuses to run without a credential and refuses to
run against a scripted server. Six live criteria passed on *earlier* code and
are historical evidence, not a certificate for this one.

---

## Conversation and inputs (DC-01 – DC-14)

| ID | Status | Evidence |
|---|---|---|
| DC-01 | PASS — deterministic; PASS — browser scripted | `test_assistant.py::TestAnOrdinaryQuestion`; `test_direct_chat_journeys.py::TestAnOrdinaryQuestionStaysOrdinary`; browser journey **A** (answered, no tool, no artifact, survives refresh) |
| DC-02 | PASS — deterministic; PASS — browser scripted | `test_direct_chat_journeys.py::TestReopeningKeepsEverything`; browser journeys **D** and **J** (a follow-up sees the document rather than guessing) |
| DC-03 | PASS — deterministic | `frontend/src/lib/__tests__/playbook-draft.test.ts`; dashboard browser suite *"the half-typed sentence survived the round trip"* |
| DC-04 | PASS — deterministic; PASS — browser scripted | `test_direct_chat_journeys.py::TestAnAttachmentDoesNotForceAFile`; browser journey **B** (a real .docx uploaded and asked about, no file created) |
| DC-05 | PASS — deterministic; PASS — browser scripted | `test_export_library.py`; workspace browser suite (preview and back leaves *"2 selected"*) |
| DC-06 | PASS — deterministic | `test_adversarial.py::TestAwkwardWorkbooks`; `test_spreadsheet_precision.py` — computation reaches rows beyond a preview cap |
| DC-07 | PASS — deterministic | `test_ingest_*.py` — tables, slides and an image-only PDF declared unreadable rather than guessed |
| DC-08 | PASS — deterministic | `test_adversarial.py::TestTwoThingsThatLookLikeOneThing` — conflicting period, unit and population refuse to compare |
| DC-09 | PASS — deterministic | `test_direct_chat_journeys.py` gap handling; `test_progress.py::test_a_section_that_only_reports_missing_evidence_is_not_complete` |
| DC-10 | PASS — deterministic | `test_reparse.py` — original bytes reused, old parse revision kept, no re-upload |
| DC-11 | PASS — deterministic | `test_security.py` / `test_adversarial.py` — document text cannot authorise extraction or cross-tenant access |
| DC-12 | PASS — deterministic | `test_messages.py`, `test_streaming.py` — regenerate is a new attempt; history is not rewritten |
| DC-13 | **NOT IMPLEMENTED** | No research tool exists. `chat._capability_note()` tells the assistant so, and the capability audit reports it absent rather than faking it |
| DC-14 | PASS — deterministic | `test_document_path.py::test_the_audit_uses_chapter_02s_three_states`; `GET /playbook/capabilities` reports implemented / available-but-disabled |

## Files and progress (DC-15 – DC-28)

| ID | Status | Evidence |
|---|---|---|
| DC-15 | PASS — deterministic; PASS — browser scripted | `test_direct_chat_journeys.py::TestAskingForAReportProducesRealFiles`; browser journey **C** (38 KB Word, 2.8 KB PDF, both downloaded) |
| DC-16 | PASS — deterministic | `test_service.py` scoped-edit suite — prior content carried forward, old version retained |
| DC-17 | PASS — browser scripted | Browser journey **E** — PowerPoint created in the same thread, no separate workflow |
| DC-18 | PASS — deterministic | `test_render_and_validate.py`, `verify_playbook_artifacts.py` — real cells and formulas |
| DC-19 | PASS — deterministic; PASS — browser scripted | `test_merge.py`, `test_service.py::TestAScopedEditIsScopedByConstruction`; browser journey **D** (v2 written, v1 retained) |
| DC-20 | PASS — deterministic | `test_change_sets.py` — only selected stable ids applied, dependencies disclosed |
| DC-21 | PASS — deterministic; PASS — browser scripted | `test_direct_chat_journeys.py` download checks; browser journey **C** (bytes begin `PK` / `%P`) |
| DC-22 | PASS — deterministic; PASS — browser scripted | `test_direct_chat_journeys.py::TestOneFormatFailingKeepsTheOther`; browser journey **G** (Word delivered and downloadable, PDF named as failed, retry offered) |
| DC-23 | PASS — deterministic; PASS — browser scripted | `test_progress.py::TestCountingWhatWasWritten`; browser journey **C** (`6 / 7` content, numerator and denominator in the payload) |
| DC-24 | PASS — deterministic; PASS — browser scripted | `test_progress.py::TestNothingToCount`; browser journey **A** (*Not applicable*, never 0% or 100%) |
| DC-25 | PASS — deterministic; PASS — browser scripted | `test_progress.py::test_a_section_that_only_reports_missing_evidence_is_not_complete`; browser journey **C** (the gap section is *needs input*) |
| DC-26 | PASS — deterministic | `test_document_intelligence_model.py` statistics — PDF pages measured from the file; unknown stays *not calculated* |
| DC-27 | PASS — deterministic; PASS — browser scripted | `test_context_bridge.py::TestTheProjectionCannotTakeTheDocumentWithIt`; `test_direct_chat_journeys.py::TestTheDashboardCannotStopDelivery`; browser journey **I** (both files download with the projection raising) |
| DC-28 | PASS — deterministic; PASS — browser scripted | `test_governance_is_optional.py`; `review.advance` refuses a system actor; browser journey **C** (review *draft*, `by` empty) |

## Reliability and regressions (DC-29 – DC-42)

| ID | Status | Evidence |
|---|---|---|
| DC-29 | PASS — deterministic | `test_streaming.py` — refresh rejoins the same job; no second generation, no duplicate message |
| DC-30 | PASS — deterministic | `test_streaming.py::TestATimeoutLeavesNothingBehind`; `assistant.converse` lets runtime failures end the turn rather than containing them |
| DC-31 | PASS — deterministic; PASS — browser scripted | `test_streaming.py` replay; browser journey **K** (partial text marked incomplete, earlier report untouched) |
| DC-32 | PASS — deterministic | `test_api.py` idempotency; migration `0040` scopes keys per workspace |
| DC-33 | PASS — deterministic | `test_api.py` authorization matrix, `test_security.py` — foreign tenant, guessed id, direct download |
| DC-34 | PASS — deterministic | `test_security.py::TestFailureLeavesTheLastGoodVersionAlone` — an unopenable file is never delivered and completed chat survives |
| DC-35 | PASS — deterministic | `test_title_is_not_a_section.py`, `test_structural_numerals.py`; `Validation.integrity` separates a wrapped heading from a corrupt file |
| DC-36 | PASS — deterministic | `test_structural_numerals.py`, `test_render_and_validate.py`; `test_security.py::test_a_content_finding_leaves_the_draft_downloadable` |
| DC-37 | PASS — deterministic | `test_grounding_gate.py::TestTheLedgerAndTheDocumentUseOneRule` — an identifier or date in the evidence cannot excuse a claim |
| DC-38 | PASS — deterministic | `test_api.py` restore; `test_adversarial.py` aliasing — a copied table cannot mutate a prior version |
| DC-39 | PASS — deterministic | `test_seed.py`, dashboard browser suite — the three seeded workspaces, their files and advanced records all still open |
| DC-40 | PASS — deterministic | `test_document_path.py`; `test_api.py::test_a_task_and_scope_are_accepted` (503 `provider_not_configured`); `test_product_copy.py` (no credential in any payload) |
| DC-41 | **BLOCKED** | The launcher's `doctor` reports worktree, branch, commit, build target and migration head, and the scripted server is named in `capabilities`. What is missing is the *served build* identifier in the UI, which needs the macOS worktree to confirm end to end |
| DC-42 | **BLOCKED** | The original Auto Loan evidence pack is not in this repository. The journey is exercised with a synthetic methodology of the same shape (browser journey **B** and **C**); running it on the real pack needs the file and a credential |

---

## Totals, stated without rounding anything up

| | |
|---|---|
| PASS — deterministic | **39** |
| PASS — browser scripted | **13** (all of which are also deterministic) |
| PASS — live verified | **0** |
| BLOCKED | **2** — DC-41, DC-42 |
| NOT IMPLEMENTED | **1** — DC-13 |

39 + 2 + 1 = 42. No row is counted twice in the totals: the browser column is
a second, stronger proof of rows already counted as deterministic, not an
additional row.

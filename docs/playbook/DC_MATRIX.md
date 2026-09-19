# DC-01 – DC-42

Status vocabulary, used exactly:

| | |
|---|---|
| **PASS — deterministic** | proven by a test against the real code, no browser, no provider |
| **PASS — browser scripted** | driven through the real `/playbook` UI against the scripted assistant |
| **PASS — live verified** | proven against a real model on this code |
| **FAIL — live, remediated here, awaiting live retest** | run against a real model on this code and did not pass. The cause is fixed and covered, and the row stays FAIL until it is re-run live |
| **BLOCKED** | cannot be proven here; the blocker is named |
| **NOT IMPLEMENTED** | the behaviour does not exist |

Two rules this table keeps. A route-level test is **not** browser-tested, and
a scripted run is **not** live. Where a row has both, both are named, and the
stronger claim never absorbs the weaker one.

**Live: one journey has now been run, and it failed.** DC-42 was executed
against the real Auto Loan pack with a real credential and produced no
document at all. The cause is diagnosed, fixed and covered by tests below; the
row stays FAIL until it is re-run live, because a scripted pass is not a live
one.

That failure is also the answer to a question this table could not previously
answer: **a scripted browser run cannot prove a live model calls a tool.** The
fixture decides. Sixteen rows of browser evidence and 144 green checks
coexisted with a total failure on first live contact, and nothing here was
wrong — the column simply does not mean what it is easy to read it as
meaning. Journey **L** now scripts the *refusal* rather than the call, which
is the nearest a fixture can get.

`scripts/playbook_live_smoke.py` remains the bounded, resumable paid path: it
refuses to run without a credential and refuses to run against a scripted
server. The six live criteria that passed on *earlier* code are historical
evidence, not a certificate for this one.

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
| DC-13 | PASS — deterministic (the applicable half); **NOT IMPLEMENTED** (the other) | The criterion has two halves. *Disabled research is not simulated* — proven: `capabilities.NOT_SUPPORTED` declares research absent, `GET /playbook/capabilities` publishes it as `not_supported`, `chat._capability_note()` tells the assistant the same sentence from the same registry, and `test_document_path.py::TestWhatThisDeploymentCannotDo` pins all three together. *Enabled research is sourced and distinguished from files* — **not implemented**: there is no research tool to enable. The earlier claim here that the audit already reported it was wrong; it did not, until this was built |
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
| DC-21 | PASS — deterministic; PASS — browser scripted | `test_direct_chat_journeys.py` download checks; browser journey **C** (bytes begin `PK` / `%P`) and **F** (a conversion reuses the stored version — *nothing was rewritten* — instead of re-rendering) |
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
| DC-29 | PASS — deterministic; PASS — browser scripted | `test_streaming.py` — refresh rejoins the same job; `test_messages.py::TestADifferentKeyIsStillNotASecondGeneration` — a *different* key is refused too, which the idempotency key alone never caught: the client's key is positional, so the same sentence sent again got a new one and started a second charged generation. Migration `0041` makes one-live-job-per-workspace a database guarantee. Browser journey **M** |
| DC-30 | PASS — deterministic | `test_streaming.py::TestATimeoutLeavesNothingBehind`; `assistant.converse` lets runtime failures end the turn rather than containing them |
| DC-31 | PASS — deterministic; PASS — browser scripted | `test_streaming.py` replay; browser journey **K** (partial text arrives, the turn is marked incomplete **in the thread**, earlier report untouched). Narrowed and then re-earned: journey K asserted the stored `interrupted` flag and never the DOM, and the thread had no branch to render it — so a turn cut short looked exactly like a finished one. Both are fixed |
| DC-32 | PASS — deterministic | `test_api.py` idempotency; migration `0040` scopes keys per workspace |
| DC-33 | PASS — deterministic | `test_api.py` authorization matrix, `test_security.py` — foreign tenant, guessed id, direct download |
| DC-34 | PASS — deterministic; PASS — browser scripted | `test_security.py::TestFailureLeavesTheLastGoodVersionAlone` — an unopenable file is never delivered and completed chat survives; browser journey **H** (the document tool fails outright, the assistant says plainly that nothing was saved, no artifact is written, the failure is recorded on the message, and the next question is answered normally) |
| DC-35 | PASS — deterministic | `test_title_is_not_a_section.py`, `test_structural_numerals.py`; `Validation.integrity` separates a wrapped heading from a corrupt file |
| DC-36 | PASS — deterministic | `test_structural_numerals.py`, `test_render_and_validate.py`; `test_security.py::test_a_content_finding_leaves_the_draft_downloadable` |
| DC-37 | PASS — deterministic | `test_grounding_gate.py::TestTheLedgerAndTheDocumentUseOneRule` — an identifier or date in the evidence cannot excuse a claim |
| DC-38 | PASS — deterministic | `test_api.py` restore; `test_adversarial.py` aliasing — a copied table cannot mutate a prior version |
| DC-39 | PASS — deterministic | `test_seed.py`, dashboard browser suite — the three seeded workspaces, their files and advanced records all still open |
| DC-40 | PASS — deterministic | `test_document_path.py`; `test_api.py::test_a_task_and_scope_are_accepted` (503 `provider_not_configured`); `test_product_copy.py` (no credential in any payload) |
| DC-41 | **BLOCKED** | The launcher's `doctor` reports worktree, branch, commit, build target and migration head, and the scripted server is named in `capabilities`. What is missing is the *served build* identifier in the UI, which needs the macOS worktree to confirm end to end |
| DC-42 | **FAIL — live, remediated here, awaiting live retest** | No longer blocked: the pack and a credential exist on the user's machine, and the journey was run. It **failed** — seven sources read, two assistant replies announcing the work, no tool call, no file. Root cause and fix: `tool_choice` on a declared task, a bounded correction when a turn promises a document and calls nothing, and `no_file` on the message so a turn that produced nothing cannot read as success. Proven deterministically (`test_assistant.py::TestAPromiseWithNoToolCall`, with both live replies in the detector's cases verbatim) and in the browser (journey **L**). It is not marked PASS on a scripted run |

---

## Totals, stated without rounding anything up

| | |
|---|---|
| PASS — deterministic | **39** |
| PASS — browser scripted | **17** |
| PASS — live verified | **0** |
| FAIL — live, fixed, awaiting retest | **1** — DC-42 |
| BLOCKED | **1** — DC-41 |
| NOT IMPLEMENTED | **one half of one row** — DC-13's *enabled research* clause |

How that adds to 42, without a row being counted twice:

* 39 rows are proven deterministically. One of them, DC-13, is proven only
  for the half of its criterion that applies to this deployment; the other
  half has nothing to prove because the capability does not exist.
* DC-17 is proven in the browser and only in the browser, which makes 40.
* DC-41 is blocked and DC-42 failed live, which makes 42.

The 17 browser rows are **not** an addition. Sixteen of them are rows already
counted as deterministic, proven a second way through the real `/playbook`
UI; the seventeenth is DC-17, which the count above adds once.

All thirteen journeys A–M carry evidence, and every one is cited by at least
one row: A (DC-01, DC-24), B (DC-04), C (DC-15, DC-21, DC-23, DC-25, DC-28),
D (DC-02, DC-19), E (DC-17), F (DC-21), G (DC-22), H (DC-34), I (DC-27),
J (DC-02), K (DC-31), L (DC-42), M (DC-29).

**Live verified is still nought.** One live row has been RUN; it did not pass.
No arithmetic here changes either fact.

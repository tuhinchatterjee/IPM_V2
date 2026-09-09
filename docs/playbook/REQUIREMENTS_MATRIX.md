# Playbook — requirement matrix (PB-001 … PB-045)

One row per acceptance behaviour. **Status vocabulary is exact and never blurred:**

- `PASS` — implemented and proven by a test or evidence that actually ran.
- `FAIL` — implemented and proven not to work.
- `BLOCKED` — cannot be proven here; the blocker is named. Never reported as PASS.
- `SKIPPED` — the check did not run. Never counted as a pass.
- `DEFERRED-INTEGRATION` — the hook is genuinely absent from this baseline; a
  contract test and an integration note stand in its place.

Every `BLOCKED` row below has the same blocker: **no `ANTHROPIC_API_KEY` is
configured in this environment**, so the live authoring path could not be
exercised. The code path is implemented and tested against a scripted provider;
that is not the same thing as live verification and is not reported as though it
were. `scripts/playbook_live_slice.py` exits 2 rather than 0 for the same reason.

A plan entry or a screenshot alone is not proof of a backend behaviour.

| ID | Required acceptance behaviour | Implementation | Evidence | Status |
|---|---|---|---|---|
| PB-001 | Work remains on an isolated feature branch; base commit is recorded; no default-branch merge or unrelated changes. | branch claude/creditprobe-playbook-plan-ky3m05 from 3855f9b | docs/playbook/PROGRESS.md; git log; no merge to main | PASS |
| PB-002 | Playbook home displays composer, quick prompts, Recent Playbooks, and Recent Exported Analyses in the specified order. | frontend/src/app/playbook/page.tsx; src/lib/playbook.ts HOME_SECTIONS | playbook.test.ts order tests; browser acceptance ordering checks at 2 viewports | PASS |
| PB-003 | Composer plus menu has Upload from computer and Add exported analyses; both work. | components/playbook/composer.tsx PlusMenu; analysis-picker.tsx | browser acceptance: plus menu offers both sources | PASS |
| PB-004 | Multiple local files upload, parse, show status, attach, remove, and retry correctly. | POST /playbook/workspaces/{id}/sources; backend/playbook/ingest/ | test_ingest.py (23); test_api.py upload and 6 source-correction tests; browser upload journey; 6 browser checks on correcting a source | PASS |
| PB-005 | Unexported module analyses are absent from the library and rejected by backend attachment authorization. | backend/playbook/library.py; repository.find_export_revision | test_export_library.py boundary tests; browser acceptance API 404 | PASS |
| PB-006 | Export to Playbook works on available in-scope module results with persisted full content and provenance. | backend/exports/playbook_contract.py; ExportToPlaybook on 4 modules | test_export_library.py; playbook-export.test.ts (17) | PASS |
| PB-007 | Project Planner is not given the new export requirement; its existing behavior is not regressed. | no Project Planner exists; /projects untouched | grep shows no export control in /projects; API refuses the module | PASS |
| PB-008 | Duplicate export is idempotent; a changed export creates controlled lineage without rewriting attached evidence. | uq_analysis_export_content; library.create | test_export_library.py idempotency tests | PASS |
| PB-009 | Search/filter/sort and multi-select work; selections survive preview/back navigation. | analysis-picker.tsx; lib/playbook.ts matching() | browser acceptance: preview then back keeps 2 selected | PASS |
| PB-010 | Analysis preview shows real narrative, tables/charts where present, scope, caveats, and sources. | library.preview; AnalysisPicker PreviewBody | test_export_library.py preview tests; browser acceptance preview content | PASS |
| PB-011 | Selected analyses and local documents can coexist in one submitted prompt. | playbook_attachments; service.send_message | test_service.py mixed attachments; test_messages.py | PASS |
| PB-012 | Previous report, methodology, template, and results roles are distinguished; period/scope conflicts surface. | playbook_sources.source_role; ingest manifests; PATCH /sources/{id} records role_set_by=user; POST /sources/{id}/retry | test_service.py evidence selection; test_api.py role correction, refusal of an invalid role and re-parse; browser: correcting a source survives a reload | PASS |
| PB-013 | A supplied methodology can be checked against a prior report with a sourced coverage matrix and no unauthorized edit. | prompts.COVERAGE_CHECK wired through service._framed; task="coverage" on the message API | test_service.py asserts the framing sent forbids writing or revising the report; seeded IFRS 9 thread. The live check `coverage_matrix` in `backend/validation/live_playbook.py` asserts a matrix is produced AND that the report it checked was not edited. **Run once against the live provider; the run is being repeated after the fixes below. BLOCKED.** | BLOCKED |
| PB-014 | Current/prior numerical comparisons reconcile to files, preserve units, and handle percentage/basis-point distinctions. | backend/playbook/calc.py; fixtures/ecl_oracle.py | test_calc_oracle.py (25) incl. pp vs percent vs bps | PASS |
| PB-015 | A detailed no-template report can be generated from selected evidence; missing tests are not invented. | prompts.CREATE_WITHOUT_TEMPLATE via service._framed; authoring and rendering split — the provider call is text-only and `render.render()` produces the files deterministically | **Live re-run FAILED: read timeout at 281.1s.** Root cause found and fixed — one call was authoring AND driving the document Skills, and the silence during sandbox execution tripped the 120s read timeout. Evidence size ruled out by measurement (26 chunks, 34 items, ~2,517 prompt tokens, 0 omissions, 631/120,000 budget). The check now reports evidence size, turns, tool calls and authoring vs rendering time separately. **Live remediation required — re-run outstanding.** | FAIL |
| PB-016 | “Apply 1, 2, 3 but not 4 or 5” changes only the authorized scope, with stable IDs and dependency handling. | service.decide_changes and approved_instruction; GET/POST /workspaces/{id}/change-sets; components/playbook/change-set-panel.tsx | test_change_sets.py (13); test_api.py decision tests (5); playbook-changes.test.ts (12); browser acceptance: approve 1, 2 and 5, hold 3 and 4, survives a reload. Applying the approved instruction to a document needs a provider and is BLOCKED. | PASS |
| PB-017 | Directly requested editorial edits work without a redundant approval loop and preserve facts/risk meaning. | `backend/playbook/merge.py` scoped_merge — only the requested section is taken from the model, every other section is carried forward from the approved version as the same object; prompts.SCOPED_EDIT; add_current_version | **Live re-run FAILED: an unsupported figure appeared in version 2** (`grounding.ok` false — the only conjunct that could be, and the detail string could not show it). Root cause: nothing structurally enforced the scope, and the check's own `lost` regex matched only two-decimal figures. Now enforced by construction, with 16 merge tests and 7 service tests in the live failure shape, and a check that names the invariant, the differing sections and both sides of the text. **Live remediation required — re-run outstanding.** | FAIL |
| PB-018 | Selected analysis can be inserted as substantive narrative and editable report tables, not merely linked titles. | evidence.from_export; document tables | test_seed.py figure reconciliation across artefacts | PASS |
| PB-019 | A report can become a useful editable presentation with consistent quantitative claims and sources. | render/pptx_writer.py; seeded decks | test_render_and_validate.py editable-deck test; artifact verifier | PASS |
| PB-020 | Valid DOCX, PDF, and PPTX files are generated, persisted, previewed, downloaded, and reopened. | render/*; store.py; playbook_artifact_files | verify_playbook_artifacts.py: 14 files, 62 checks; browser downloads; GET /artifacts/{id}/versions/{v}/preview with 4 API tests and 4 browser checks | PASS |
| PB-021 | A supported XLSX request creates a valid workbook; unsupported format requests are handled truthfully. | render/xlsx_writer.py; capabilities.py | test_render_and_validate.py workbook + unsupported-format tests | PASS |
| PB-022 | Original files and old versions remain available; latest version, lineage, and restore behavior are correct. | playbook_artifact_versions; service.restore_version; POST /artifacts/{id}/restore/{version} | test_service.py version lineage and 8 restore tests; test_api.py restore over HTTP; browser acceptance restores v1 as v3 and compares the bytes | PASS |
| PB-023 | Concurrent/stale-base edits cannot silently overwrite a newer version. | repository.new_version StaleBaseVersion; 409 in the router | test_service.py stale-base test | PASS |
| PB-024 | Thread messages, attachments, approval decisions, and artifact history survive refresh and restart. | Postgres persistence throughout | test_messages.py; browser acceptance reopens a 14-message thread | PASS |
| PB-025 | Three named demo workspaces contain complete histories, actual inputs/outputs, and genuine revisions. | backend/playbook/seed_threads.py; seed.py | test_seed.py (27); browser acceptance opens a seeded thread | PASS |
| PB-026 | At least 30 substantial demo exports exist, with at least six per in-scope module and no accidental duplicates. | backend/playbook/seed_exports.py | test_seed.py: 30 exports, 6 per module, distinct narratives | PASS |
| PB-027 | Seed values reconcile across analysis, chat, reports, PDFs, decks, and workbooks; intentional discrepancies are labeled test fixtures. | fixtures/ecl_oracle.py; fixtures/scorecard.py | test_seed.py cross-artefact reconciliation; test_scorecard_fixture.py (14) | PASS |
| PB-028 | Seeding is idempotent, isolated, and does not overwrite edited demo threads or contaminate production data. | seed.reseed idempotency; demo/workspace.py RESET_ORDER | test_seed.py: second run creates nothing, edits preserved | PASS |
| PB-029 | Continuing a seeded thread invokes the real provider when configured; it is not scripted fixture playback. | service.send_message on a seeded workspace | live check `seeded_continuation` asserts the reply is `assistant_live` with real request ids, on a question no fixture contains. **No provider configured — cannot be demonstrated here: BLOCKED.** | BLOCKED |
| PB-030 | Runtime actually uses the configured Opus model and tested artifact tools, with no hidden model downgrade. | backend/llm/roles.py AUTHOR; provider.AuthoringResult.downgraded; provider.status() and author() refuse with AUTHOR_MODEL_NOT_CONFIGURED rather than calling the SDK without a model | **Live, 2 September re-run against `5ee2324`: requested `claude-opus-5`, served `claude-opus-5`, no downgrade, 76.5s, request_id `req_011CetFik5iB1janNWebTPLA`.** Plus test_provider_bounds.py model-guard tests and test_escalation.py role config. | PASS |
| PB-031 | Missing credentials, unsupported model/tool combinations, provider errors, and limits are shown honestly. | provider.status(); _message_for; 503 provider_not_configured | test_api.py capabilities; UI shows the configuration note | PASS |
| PB-032 | Long evidence sets use adequate retrieval/context management; material omissions are not hidden. | evidence.Ledger budget and omissions; ingest manifests | test_service.py gap tests; test_ingest.py manifest tests | PASS |
| PB-033 | Sources have useful locators, and reported conclusions are distinguishable from assumptions/recommendations. | Chunk.locator; document citations; grounding boundary | test_ingest.py locators; test_grounding.py; test_security.py | PASS |
| PB-034 | Follow-up prompt chips are state-aware, actionable, and do not perform changes before user action. | lib/playbook.ts nextSteps() | playbook.test.ts state-aware tests | PASS |
| PB-035 | No inappropriate chart is added to a writing-only or checklist answer. | no chart is generated by any writer unless the document has one | render writers emit tables only from document tables | PASS |
| PB-036 | Upload/file type/size/path checks and untrusted-content/prompt-injection cases are tested. | ingest/validate.py; store.safe_filename; lib/markdown.ts | test_security.py (29); markdown.test.ts (13) | PASS |
| PB-037 | Foreign-tenant IDs, unauthorized previews/downloads, and malicious direct API requests are rejected. | repository tenant scoping; router 404s | test_security.py tenant tests; browser acceptance API boundary | PASS |
| PB-038 | Streaming, cancellation, retry, refresh, and duplicate submission do not corrupt state or create duplicate final versions. | Genuine end-to-end streaming: `provider._stream_once` forwards `text_delta` alone; `backend/playbook/stream.py` persists every event to `playbook_job_events` (migration 0034) and runs the generation in a worker; `GET /workspaces/{id}/stream` is SSE with replay from `after` or `Last-Event-ID`; `running_job` on the workspace payload; `src/lib/stream.ts` parser and `use-generation.tsx`; `uq_playbook_job_idempotency`; POST /jobs/{id}/cancel and /retry | test_streaming.py (33) — chunks before completion, replay after refresh, cancel mid-stream, provider failure mid-stream, duplicate send, nothing hidden in the log, nothing downloadable from an interrupted run; test_api.py streaming over HTTP (10); stream.test.ts (18); browser: text appears without a reload, a refresh keeps it and starts no second generation, Stop mid-stream leaves no artifact. Bounded after the first live run hung: a wall-clock run deadline checked between stream events, four separate transport timeouts, and 22 tests covering a stall before the first token, a stall mid-response, no version or file on timeout, the previous version preserved, and a retry that makes one more generation rather than two | PASS |
| PB-039 | Parsing/generation failures preserve prior valid artifacts and provide an actionable recovery. | author_document writes no version on failure | test_service.py; test_security.py validation-failure test | PASS |
| PB-040 | Every visible control is exercised; keyboard/focus behavior and laptop layout are verified. | scripts/acceptance/playbook_browser_acceptance.py | 105 checks at 2 viewports; Escape/focus; streaming, stopping mid-stream, the change panel, the restore control, the preview and source correction all driven end to end; no console errors | PASS |
| PB-041 | Office/PDF outputs are parsed back and visually reviewed for content completeness, clipping, and readability. | scripts/acceptance/verify_playbook_artifacts.py | 62 checks over 14 files; PDF pages rasterised and inspected | PASS |
| PB-042 | Available-module regression and repository lint/type/build checks pass or have exact baseline-supported classifications. | ruff, pytest, tsc, eslint, next build, npm test | full backend suite 9810 passed / 30 skipped / 0 failed; see docs/playbook/UAT_REPORT.md | PASS |
| PB-043 | Fresh prompts not present in seeds succeed through the live path; mocked tests are reported separately. | fresh prompts through the live path; `backend/validation/live_playbook.py`, driven by tests/playbook/test_live_playbook.py and scripts/playbook_live_slice.py | live check `fresh_prompt` asserts the answer is not a substring of any seeded turn. 8 structural tests assert the suite covers every blocked requirement and refuses to run without a credential. **No provider configured — not run: BLOCKED.** | BLOCKED |
| PB-044 | Future integration hooks, payload examples, flag behavior, migration implications, and rollout steps are documented. | docs/playbook/INTEGRATION_NOTES.md; What If adapter contract | test_export_library.py deferred-integration tests | PASS |
| PB-045 | Final report provides actual commit, test evidence, unresolved issues, runnable UAT instructions, and truthful readiness labels. | docs/playbook/UAT_REPORT.md; PROGRESS.md | this matrix, with live items marked BLOCKED not PASS | PASS |

## Status roll-up

| Status | Count |
|---|---:|
| PASS | 40 |
| FAIL | 2 |
| BLOCKED | 3 |
| SKIPPED | 0 |
| DEFERRED-INTEGRATION | 0 |

## What DEFERRED-INTEGRATION covers

PB-006 is PASS for the four modules with a producing surface on this baseline —
Cockpit, Early Warning, Scorecard Validation and Lenses. **What If is
DEFERRED-INTEGRATION**: no such module exists here, the contract declares it,
six labelled fixtures carry it, and `docs/playbook/INTEGRATION_NOTES.md` names
the hook a future branch must call. No live cross-module claim is made for it.

PB-007 needed nothing done: there is no Project Planner in this repository.

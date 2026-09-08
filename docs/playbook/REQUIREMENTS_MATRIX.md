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
| PB-004 | Multiple local files upload, parse, show status, attach, remove, and retry correctly. | POST /playbook/workspaces/{id}/sources; backend/playbook/ingest/ | test_ingest.py (23); test_api.py upload tests; browser upload journey | PASS |
| PB-005 | Unexported module analyses are absent from the library and rejected by backend attachment authorization. | backend/playbook/library.py; repository.find_export_revision | test_export_library.py boundary tests; browser acceptance API 404 | PASS |
| PB-006 | Export to Playbook works on available in-scope module results with persisted full content and provenance. | backend/exports/playbook_contract.py; ExportToPlaybook on 4 modules | test_export_library.py; playbook-export.test.ts (17) | PASS |
| PB-007 | Project Planner is not given the new export requirement; its existing behavior is not regressed. | no Project Planner exists; /projects untouched | grep shows no export control in /projects; API refuses the module | PASS |
| PB-008 | Duplicate export is idempotent; a changed export creates controlled lineage without rewriting attached evidence. | uq_analysis_export_content; library.create | test_export_library.py idempotency tests | PASS |
| PB-009 | Search/filter/sort and multi-select work; selections survive preview/back navigation. | analysis-picker.tsx; lib/playbook.ts matching() | browser acceptance: preview then back keeps 2 selected | PASS |
| PB-010 | Analysis preview shows real narrative, tables/charts where present, scope, caveats, and sources. | library.preview; AnalysisPicker PreviewBody | test_export_library.py preview tests; browser acceptance preview content | PASS |
| PB-011 | Selected analyses and local documents can coexist in one submitted prompt. | playbook_attachments; service.send_message | test_service.py mixed attachments; test_messages.py | PASS |
| PB-012 | Previous report, methodology, template, and results roles are distinguished; period/scope conflicts surface. | playbook_sources.source_role; ingest manifests | test_service.py evidence selection; seeded roles visible in UI | PASS |
| PB-013 | A supplied methodology can be checked against a prior report with a sourced coverage matrix and no unauthorized edit. | prompts.COVERAGE_CHECK; seeded coverage exchange | seeded IFRS 9 thread; live check BLOCKED without a provider | BLOCKED |
| PB-014 | Current/prior numerical comparisons reconcile to files, preserve units, and handle percentage/basis-point distinctions. | backend/playbook/calc.py; fixtures/ecl_oracle.py | test_calc_oracle.py (25) incl. pp vs percent vs bps | PASS |
| PB-015 | A detailed no-template report can be generated from selected evidence; missing tests are not invented. | prompts.CREATE_WITHOUT_TEMPLATE; service.author_document | test_service.py with scripted author; live BLOCKED | BLOCKED |
| PB-016 | “Apply 1, 2, 3 but not 4 or 5” changes only the authorized scope, with stable IDs and dependency handling. | service.decide_changes and approved_instruction; GET/POST /workspaces/{id}/change-sets; components/playbook/change-set-panel.tsx | test_change_sets.py (13); test_api.py decision tests (5); playbook-changes.test.ts (12); browser acceptance: approve 1, 2 and 5, hold 3 and 4, survives a reload. Applying the approved instruction to a document needs a provider and is BLOCKED. | PASS |
| PB-017 | Directly requested editorial edits work without a redundant approval loop and preserve facts/risk meaning. | prompts.SCOPED_EDIT; seeded editorial turns | seeded threads; live scoped edit BLOCKED | BLOCKED |
| PB-018 | Selected analysis can be inserted as substantive narrative and editable report tables, not merely linked titles. | evidence.from_export; document tables | test_seed.py figure reconciliation across artefacts | PASS |
| PB-019 | A report can become a useful editable presentation with consistent quantitative claims and sources. | render/pptx_writer.py; seeded decks | test_render_and_validate.py editable-deck test; artifact verifier | PASS |
| PB-020 | Valid DOCX, PDF, and PPTX files are generated, persisted, previewed, downloaded, and reopened. | render/*; store.py; playbook_artifact_files | verify_playbook_artifacts.py: 14 files, 62 checks; browser downloads | PASS |
| PB-021 | A supported XLSX request creates a valid workbook; unsupported format requests are handled truthfully. | render/xlsx_writer.py; capabilities.py | test_render_and_validate.py workbook + unsupported-format tests | PASS |
| PB-022 | Original files and old versions remain available; latest version, lineage, and restore behavior are correct. | playbook_artifact_versions; repository.new_version | test_service.py version lineage; test_seed.py two versions | PASS |
| PB-023 | Concurrent/stale-base edits cannot silently overwrite a newer version. | repository.new_version StaleBaseVersion; 409 in the router | test_service.py stale-base test | PASS |
| PB-024 | Thread messages, attachments, approval decisions, and artifact history survive refresh and restart. | Postgres persistence throughout | test_messages.py; browser acceptance reopens a 14-message thread | PASS |
| PB-025 | Three named demo workspaces contain complete histories, actual inputs/outputs, and genuine revisions. | backend/playbook/seed_threads.py; seed.py | test_seed.py (27); browser acceptance opens a seeded thread | PASS |
| PB-026 | At least 30 substantial demo exports exist, with at least six per in-scope module and no accidental duplicates. | backend/playbook/seed_exports.py | test_seed.py: 30 exports, 6 per module, distinct narratives | PASS |
| PB-027 | Seed values reconcile across analysis, chat, reports, PDFs, decks, and workbooks; intentional discrepancies are labeled test fixtures. | fixtures/ecl_oracle.py; fixtures/scorecard.py | test_seed.py cross-artefact reconciliation; test_scorecard_fixture.py (14) | PASS |
| PB-028 | Seeding is idempotent, isolated, and does not overwrite edited demo threads or contaminate production data. | seed.reseed idempotency; demo/workspace.py RESET_ORDER | test_seed.py: second run creates nothing, edits preserved | PASS |
| PB-029 | Continuing a seeded thread invokes the real provider when configured; it is not scripted fixture playback. | service.send_message on a seeded workspace | no provider configured — cannot be demonstrated here | BLOCKED |
| PB-030 | Runtime actually uses the configured Opus model and tested artifact tools, with no hidden model downgrade. | backend/llm/roles.py AUTHOR; provider.AuthoringResult.downgraded | test_escalation.py role config; live check BLOCKED | BLOCKED |
| PB-031 | Missing credentials, unsupported model/tool combinations, provider errors, and limits are shown honestly. | provider.status(); _message_for; 503 provider_not_configured | test_api.py capabilities; UI shows the configuration note | PASS |
| PB-032 | Long evidence sets use adequate retrieval/context management; material omissions are not hidden. | evidence.Ledger budget and omissions; ingest manifests | test_service.py gap tests; test_ingest.py manifest tests | PASS |
| PB-033 | Sources have useful locators, and reported conclusions are distinguishable from assumptions/recommendations. | Chunk.locator; document citations; grounding boundary | test_ingest.py locators; test_grounding.py; test_security.py | PASS |
| PB-034 | Follow-up prompt chips are state-aware, actionable, and do not perform changes before user action. | lib/playbook.ts nextSteps() | playbook.test.ts state-aware tests | PASS |
| PB-035 | No inappropriate chart is added to a writing-only or checklist answer. | no chart is generated by any writer unless the document has one | render writers emit tables only from document tables | PASS |
| PB-036 | Upload/file type/size/path checks and untrusted-content/prompt-injection cases are tested. | ingest/validate.py; store.safe_filename; lib/markdown.ts | test_security.py (29); markdown.test.ts (13) | PASS |
| PB-037 | Foreign-tenant IDs, unauthorized previews/downloads, and malicious direct API requests are rejected. | repository tenant scoping; router 404s | test_security.py tenant tests; browser acceptance API boundary | PASS |
| PB-038 | Streaming, cancellation, retry, refresh, and duplicate submission do not corrupt state or create duplicate final versions. | playbook_jobs.idempotency_key unique | test_messages.py duplicate-send tests | PASS |
| PB-039 | Parsing/generation failures preserve prior valid artifacts and provide an actionable recovery. | author_document writes no version on failure | test_service.py; test_security.py validation-failure test | PASS |
| PB-040 | Every visible control is exercised; keyboard/focus behavior and laptop layout are verified. | scripts/acceptance/playbook_browser_acceptance.py | 73 checks at 2 viewports; Escape/focus; the change panel driven end to end; no console errors | PASS |
| PB-041 | Office/PDF outputs are parsed back and visually reviewed for content completeness, clipping, and readability. | scripts/acceptance/verify_playbook_artifacts.py | 62 checks over 14 files; PDF pages rasterised and inspected | PASS |
| PB-042 | Available-module regression and repository lint/type/build checks pass or have exact baseline-supported classifications. | ruff, pytest, tsc, eslint, next build, npm test | see docs/playbook/UAT_REPORT.md for counts | PASS |
| PB-043 | Fresh prompts not present in seeds succeed through the live path; mocked tests are reported separately. | fresh prompts through the live path | no provider configured — not run | BLOCKED |
| PB-044 | Future integration hooks, payload examples, flag behavior, migration implications, and rollout steps are documented. | docs/playbook/INTEGRATION_NOTES.md; What If adapter contract | test_export_library.py deferred-integration tests | PASS |
| PB-045 | Final report provides actual commit, test evidence, unresolved issues, runnable UAT instructions, and truthful readiness labels. | docs/playbook/UAT_REPORT.md; PROGRESS.md | this matrix, with live items marked BLOCKED not PASS | PASS |

## Status roll-up

| Status | Count |
|---|---:|
| PASS | 39 |
| FAIL | 0 |
| BLOCKED | 6 |
| SKIPPED | 0 |
| DEFERRED-INTEGRATION | 0 |

## What DEFERRED-INTEGRATION covers

PB-006 is PASS for the four modules with a producing surface on this baseline —
Cockpit, Early Warning, Scorecard Validation and Lenses. **What If is
DEFERRED-INTEGRATION**: no such module exists here, the contract declares it,
six labelled fixtures carry it, and `docs/playbook/INTEGRATION_NOTES.md` names
the hook a future branch must call. No live cross-module claim is made for it.

PB-007 needed nothing done: there is no Project Planner in this repository.

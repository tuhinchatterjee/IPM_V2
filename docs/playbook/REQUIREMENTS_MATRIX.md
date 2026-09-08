# Playbook — requirement matrix (PB-001 … PB-045)

One row per acceptance behaviour. **Status vocabulary is exact and never blurred:**

- `PASS` — implemented and proven by a test or evidence that actually ran.
- `FAIL` — implemented and proven not to work.
- `BLOCKED` — cannot be proven here; the blocker is named. Never reported as PASS.
- `SKIPPED` — the check did not run. Never counted as a pass.
- `DEFERRED-INTEGRATION` — the hook is genuinely absent from this baseline; a
  contract test and an integration note stand in its place.
- `NOT STARTED` — not yet reached in the milestone sequence.

A plan entry or a screenshot alone is not proof of a backend behaviour.

| ID | Required acceptance behaviour | Implementation | Evidence | Status |
|---|---|---|---|---|
| PB-001 | Work remains on an isolated feature branch; base commit is recorded; no default-branch merge or unrelated changes. | — | — | NOT STARTED |
| PB-002 | Playbook home displays composer, quick prompts, Recent Playbooks, and Recent Exported Analyses in the specified order. | — | — | NOT STARTED |
| PB-003 | Composer plus menu has Upload from computer and Add exported analyses; both work. | — | — | NOT STARTED |
| PB-004 | Multiple local files upload, parse, show status, attach, remove, and retry correctly. | — | — | NOT STARTED |
| PB-005 | Unexported module analyses are absent from the library and rejected by backend attachment authorization. | — | — | NOT STARTED |
| PB-006 | Export to Playbook works on available in-scope module results with persisted full content and provenance. | — | — | NOT STARTED |
| PB-007 | Project Planner is not given the new export requirement; its existing behavior is not regressed. | — | — | NOT STARTED |
| PB-008 | Duplicate export is idempotent; a changed export creates controlled lineage without rewriting attached evidence. | — | — | NOT STARTED |
| PB-009 | Search/filter/sort and multi-select work; selections survive preview/back navigation. | — | — | NOT STARTED |
| PB-010 | Analysis preview shows real narrative, tables/charts where present, scope, caveats, and sources. | — | — | NOT STARTED |
| PB-011 | Selected analyses and local documents can coexist in one submitted prompt. | — | — | NOT STARTED |
| PB-012 | Previous report, methodology, template, and results roles are distinguished; period/scope conflicts surface. | — | — | NOT STARTED |
| PB-013 | A supplied methodology can be checked against a prior report with a sourced coverage matrix and no unauthorized edit. | — | — | NOT STARTED |
| PB-014 | Current/prior numerical comparisons reconcile to files, preserve units, and handle percentage/basis-point distinctions. | — | — | NOT STARTED |
| PB-015 | A detailed no-template report can be generated from selected evidence; missing tests are not invented. | — | — | NOT STARTED |
| PB-016 | “Apply 1, 2, 3 but not 4 or 5” changes only the authorized scope, with stable IDs and dependency handling. | — | — | NOT STARTED |
| PB-017 | Directly requested editorial edits work without a redundant approval loop and preserve facts/risk meaning. | — | — | NOT STARTED |
| PB-018 | Selected analysis can be inserted as substantive narrative and editable report tables, not merely linked titles. | — | — | NOT STARTED |
| PB-019 | A report can become a useful editable presentation with consistent quantitative claims and sources. | — | — | NOT STARTED |
| PB-020 | Valid DOCX, PDF, and PPTX files are generated, persisted, previewed, downloaded, and reopened. | — | — | NOT STARTED |
| PB-021 | A supported XLSX request creates a valid workbook; unsupported format requests are handled truthfully. | — | — | NOT STARTED |
| PB-022 | Original files and old versions remain available; latest version, lineage, and restore behavior are correct. | — | — | NOT STARTED |
| PB-023 | Concurrent/stale-base edits cannot silently overwrite a newer version. | — | — | NOT STARTED |
| PB-024 | Thread messages, attachments, approval decisions, and artifact history survive refresh and restart. | — | — | NOT STARTED |
| PB-025 | Three named demo workspaces contain complete histories, actual inputs/outputs, and genuine revisions. | — | — | NOT STARTED |
| PB-026 | At least 30 substantial demo exports exist, with at least six per in-scope module and no accidental duplicates. | — | — | NOT STARTED |
| PB-027 | Seed values reconcile across analysis, chat, reports, PDFs, decks, and workbooks; intentional discrepancies are labeled test fixtures. | — | — | NOT STARTED |
| PB-028 | Seeding is idempotent, isolated, and does not overwrite edited demo threads or contaminate production data. | — | — | NOT STARTED |
| PB-029 | Continuing a seeded thread invokes the real provider when configured; it is not scripted fixture playback. | — | — | NOT STARTED |
| PB-030 | Runtime actually uses the configured Opus model and tested artifact tools, with no hidden model downgrade. | — | — | NOT STARTED |
| PB-031 | Missing credentials, unsupported model/tool combinations, provider errors, and limits are shown honestly. | — | — | NOT STARTED |
| PB-032 | Long evidence sets use adequate retrieval/context management; material omissions are not hidden. | — | — | NOT STARTED |
| PB-033 | Sources have useful locators, and reported conclusions are distinguishable from assumptions/recommendations. | — | — | NOT STARTED |
| PB-034 | Follow-up prompt chips are state-aware, actionable, and do not perform changes before user action. | — | — | NOT STARTED |
| PB-035 | No inappropriate chart is added to a writing-only or checklist answer. | — | — | NOT STARTED |
| PB-036 | Upload/file type/size/path checks and untrusted-content/prompt-injection cases are tested. | — | — | NOT STARTED |
| PB-037 | Foreign-tenant IDs, unauthorized previews/downloads, and malicious direct API requests are rejected. | — | — | NOT STARTED |
| PB-038 | Streaming, cancellation, retry, refresh, and duplicate submission do not corrupt state or create duplicate final versions. | — | — | NOT STARTED |
| PB-039 | Parsing/generation failures preserve prior valid artifacts and provide an actionable recovery. | — | — | NOT STARTED |
| PB-040 | Every visible control is exercised; keyboard/focus behavior and laptop layout are verified. | — | — | NOT STARTED |
| PB-041 | Office/PDF outputs are parsed back and visually reviewed for content completeness, clipping, and readability. | — | — | NOT STARTED |
| PB-042 | Available-module regression and repository lint/type/build checks pass or have exact baseline-supported classifications. | — | — | NOT STARTED |
| PB-043 | Fresh prompts not present in seeds succeed through the live path; mocked tests are reported separately. | — | — | NOT STARTED |
| PB-044 | Future integration hooks, payload examples, flag behavior, migration implications, and rollout steps are documented. | — | — | NOT STARTED |
| PB-045 | Final report provides actual commit, test evidence, unresolved issues, runnable UAT instructions, and truthful readiness labels. | — | — | NOT STARTED |

## Status roll-up

| Status | Count |
|---|---:|
| PASS | 0 |
| FAIL | 0 |
| BLOCKED | 0 |
| SKIPPED | 0 |
| DEFERRED-INTEGRATION | 0 |
| NOT STARTED | 45 |

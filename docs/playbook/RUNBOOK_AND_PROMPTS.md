# CreditProbe Playbook — Plan → Auto → Verification → UAT → Branch Handoff

Prepared 8 September 2026. Use with `CREDITPROBE_PLAYBOOK_MASTER_SPEC.md`.

## The workflow

Use one new Claude Code task for Playbook. Start on the CreditProbe repository and selected tested baseline, not inside an unrelated unfinished feature task. The preferred working branch is `feature/playbook-claude-workspace`; a platform-assigned dedicated branch is acceptable.

Sequence:

1. Attach the complete master specification and select **Plan**.
2. Send **Prompt 1** and review the repository-specific plan.
3. Approve the plan and select **Auto**; send **Prompt 2**.
4. After implementation, keep the same feature branch and send **Prompt 3** for verification and repair.
5. Open the running Playbook and perform the user UAT below.
6. Send **Prompt 4**, including the actual UAT results, for final fixes and branch handoff.

Do not merge into the default branch. Completion here is a tested standalone Playbook feature branch, with later cross-module integration documented separately.

### Mode details

In Claude Code's web interface, use the permission-mode control next to the prompt. In a terminal session, use `Shift+Tab`, or start with `claude --permission-mode plan`. Plan approval can offer “Yes, and use auto mode.” If Auto is not available for the session/account/model, use the supported edit-approval mode and approve relevant commands normally. Do not use bypass-permissions as a shortcut.

The mode is changed through Claude Code's controls, not by telling the chat “you are now in Auto.” Plan is for inspection and a proposed plan; branch creation and repository file changes begin only after approval in an edit-capable mode.

For a local workflow, put the downloaded master specification somewhere Claude can read it. For a web workflow, attach it; if the interface cannot accept that file, paste its complete contents after Prompt 1. Do not replace it with the short product summary.

### Live Claude configuration

The application needs its own supported server-side provider configuration. The developer's Claude Code model/subscription is not automatically CreditProbe's runtime integration. Ask the audit to report whether a real provider is configured without exposing any secrets. Add any required application credentials using the existing project's secure environment mechanism, not a chat message or a tracked file.

A missing key must not stop all coding work, but it prevents honest sign-off on live generation. The seed library and downloadable demo files should remain testable without pretending fixture responses are live AI.

---

## Prompt 1 — Read-only audit and complete implementation plan

**Mode: Plan**

```text
You are working on CreditProbe. I want to build the Playbook module described in the attached CREDITPROBE_PLAYBOOK_MASTER_SPEC.md, on its own isolated branch, and test it independently before future integration with other feature branches.

Read the ENTIRE attached specification first. It is the source of truth. Do not replace it with a shorter interpretation or omit requirements because the task is large.

You are in PLAN MODE. Inspect the repository and produce a repository-specific implementation plan only. Do not edit source files, create repository documentation, seed data, run migrations, change branches, commit, merge, or deploy in this planning pass. Writing the normal Claude Code plan is fine.

First inspect repository instructions and establish the actual current branch, selected base, commit, dirty status, and architecture. Identify the existing Playbook, chat UI, model/provider runtime, file storage, document parsers/renderers, authentication, database migrations, export mechanisms, demo seeding, and testing infrastructure. Do not print secrets.

The intended isolated working branch is feature/playbook-claude-workspace. If this new cloud task already has a dedicated platform-assigned branch, preserve it and explain that. The implementation must not happen on the default branch or an unrelated feature branch. Propose isolated dev/test storage as well as Git isolation.

Translate EVERY requirement in the master specification into concrete work. Your plan must cover:

- Exact home layout: composer with its lower-left plus button, quick prompt chips, Recent Playbooks, then Recent Exported Analyses.
- Uploaded files AND a searchable previewable multi-select picker of ONLY explicitly exported analyses.
- Shared Export to Playbook contract/actions for available Cockpit, Early Warning, What If, Scorecard Validation, and Lenses surfaces; exclude Project Planner. Identify future-branch hooks separately.
- Persistent Claude-like threads, actual evidence reading, new/no-template reports, methodology gap checks, numerical reconciliation, selected changes, scoped rewriting, versions, and next-step prompts.
- Real Claude Opus runtime and the explicit Skills/document-tool/file-retrieval integration needed for actual DOCX, PDF, PPTX, and supported XLSX generation.
- Three complete seeded threads: IFRS 9 Committee Report, Application Scorecard Model Development Report, and Behavioral Scorecard Validation Report.
- At least 30 full demo analysis exports, six per in-scope module, with real data/content and actual downloadable outputs.
- Permissions, untrusted-document handling, file validation, idempotency, error recovery, browser tests, artifact tests, regression, and PB-001 through PB-045.

Do not describe a frontend mock or “AI integration seam ready” as sufficient. Inspect the existing provider configuration and current official provider documentation. Report whether actual runtime generation can be tested here, and name any missing configuration without revealing its value. Distinguish developer Claude Code access from application API access.

Use the existing stack and reuse working components. Do not merge other feature branches or rebuild unrelated modules. Preserve existing useful Playbook behavior and old records.

Return:
1. Repository/base/branch findings and existing capabilities with real file paths.
2. Important gaps and any blocking runtime/dependency facts.
3. The exact branch/worktree and isolated test-environment plan.
4. Data/service/API/UI changes using actual repository conventions.
5. A milestone sequence matching M0–M7, with one real generation vertical slice early.
6. A complete mapping of PB-001 through PB-045 to implementation and verification work.
7. The test strategy, including fresh prompts, real files, browser UAT, and live-versus-mocked reporting.
8. The exact steps you will perform after I approve Auto implementation.

Use the specification to resolve ordinary product choices. Ask only about a genuinely unresolved, consequential issue that repository inspection and the specification cannot resolve. Do not reopen decisions already settled in the specification.

End with the proposed plan ready for approval. Do not begin implementation yet.
```

### Check the plan before approving

The plan must include a real AI/file-generation path, not just a provider placeholder. It must explicitly cover the exact home order, export-only library, selective approvals, the three complete seeded threads, 30 substantial analyses, real downloads, and test evidence. It must identify the actual base branch and protect unrelated work. If it omits any of these, send the correction prompt immediately below while still in Plan.

### Optional plan-correction prompt

```text
Revise this plan before implementation. Read the full attached master specification again and reconcile your plan against every PB-001 through PB-045 acceptance criterion. Restore any missing scope. In particular, do not substitute a mock/seam for live Claude generation, blank demo cards for complete histories, short summaries for full exported analyses, or UI-only controls for working persisted behavior. Show the corrected requirement mapping. Stay in Plan mode until the plan is complete and approved.
```

---

## Prompt 2 — Approve and implement the full module

**Mode: Approve the plan, then Auto (or the available edit-capable mode)**

```text
Approved. Implement the complete approved plan and the FULL CREDITPROBE_PLAYBOOK_MASTER_SPEC.md now.

FIRST establish and verify the isolated Playbook working branch before editing source. Preferred name: feature/playbook-claude-workspace. A dedicated platform-assigned branch for this task is acceptable. Record the exact base commit and actual branch. Do not work on the default branch, change another feature branch, merge/cherry-pick other in-flight branches, discard dirty work, force-push, deploy, or touch production data.

Then save the complete attached specification verbatim to docs/playbook/MASTER_SPEC.md. Save the approved plan to docs/playbook/IMPLEMENTATION_PLAN.md. Maintain PROGRESS.md, REQUIREMENTS_MATRIX.md, UAT_REPORT.md, and INTEGRATION_NOTES.md as specified. If context is compacted, reread these files and resume from the first incomplete item.

Execute M0 through M7 in the approved sequence. Do not stop after the home screen, a schema scaffold, a demo seed, or an integration interface. Complete the actual Playbook workflows. Resolve the real provider/file-generation vertical slice early before spending the effort on UI polish.

Non-negotiables:

1. Real configured Claude Opus handles new evidence-grounded requests. Use actual tested document-generation tools/Skills or a documented working equivalent, retrieve generated bytes, validate them, and persist them. No fake AI responses, invented links, or silent smaller-model fallback.
2. Plus opens local uploads OR an exported-analysis picker. Only explicit exports are selectable. Preview/back/multi-select must preserve state. Enforce export status and permissions in the backend too.
3. Home order is composer, quick prompts, Recent Playbooks, Recent Exported Analyses. Threads reopen with source files, assistant answers, approvals, generated artifacts, and continued chat.
4. Users can create without a template, update prior reports from new results and methodology, perform a coverage check without editing, select proposed edits through chat or controls, and directly request scoped tone/section changes.
5. Apply only approved changes. Preserve original files, immutable versions, unaffected sections, source lineage, numbers, and risk meaning. Handle stale proposals and dependent changes explicitly.
6. Create the three complete required demo threads, each with real inputs, realistic synthetic history, selective edits, actual revisions, and Word/PDF/PowerPoint files. Seed at least 30 full exported analyses, six per source module. Label fixtures and make seeding idempotent and isolated.
7. Add shared exports to available source modules without touching Project Planner or merging other development branches. Absent-module hooks need tested contracts and explicit integration notes, not a claim of live integration.
8. Use the deterministic numerical fixtures and actual synthetic computation to reconcile tables, text, Word, PDF, and slides. Inspect generated outputs visually and programmatically.
9. Exercise every visible control and the required browser/security/failure journeys. Run affected regression and the configured broader checks as described. Do not count skips as passes.

You are authorized to make scoped code changes and milestone commits on this feature branch. Before any push, check repository automation for unintended deployment. Push only this feature branch when safe and permitted; do not open/merge a PR or deploy unless separately instructed. A blocked push must be reported honestly.

Use existing authorized provider credentials for a small synthetic live smoke suite within the configured usage limits. Never expose secrets, change billing, send real customer fixtures, or run unbounded paid benchmarking. If credentials/tools are missing, implement and test the real path as far as possible, name the precise blocker, and report live verification as blocked—not passed. Continue other unblocked implementation work.

After every milestone, run its focused checks and update the persistent progress and requirement evidence. Do not ask me to say “continue” after each milestone. Repair introduced failures. Do not weaken tests, hide missing features behind flags, or invent evidence to satisfy a deadline.

Finish with the actual branch/base/final commit, changed components, completed requirement matrix, precise test counts, screenshots/file examples, live-provider verification state, exact startup and seed commands discovered from this repository, and a click-by-click user UAT route. Distinguish standalone readiness, future-module integration, and human sign-off. Do not merge.
```

---

## Prompt 3 — Verify, repair, and prove the final feature

**Mode: Auto, same feature branch**

```text
Perform a verification-and-repair pass on the current Playbook feature branch. Treat the previous completion summary as an unverified claim, not evidence.

Read docs/playbook/MASTER_SPEC.md, IMPLEMENTATION_PLAN.md, PROGRESS.md, and REQUIREMENTS_MATRIX.md. Verify the actual branch and final code. Stay within this branch and the isolated test environment. Do not merge or deploy.

Reproduce the user journeys using the real application/backend. Add targeted tests where proof is missing and repair defects you find. Specifically verify:

A. Home order, three named full demo threads, 30 substantial pre-exported analyses, and every source/output file opening correctly.
B. An analysis does NOT appear before export, DOES appear after explicit export, and cannot bypass that rule through a direct API attachment request. Confirm all available source-module hooks and the Project Planner exclusion.
C. Preview three analyses with back navigation, preserve multi-selection, combine selected exports with local files, send a new request, and reopen after refresh.
D. Use a previous report, current results workbook, and methodology document to detect a known gap/discrepancy with source references. Produce a five-item change proposal. Apply 1, 2, and 3 while excluding 4 and 5. Verify the resulting content, not just the button state.
E. Create a detailed no-template behavioral scorecard validation report from selected analyses. Verify that missing evidence is acknowledged and unperformed tests are not invented.
F. Sharpen only the executive summary and preserve all numerical facts and unrelated sections. Convert the report to an actual editable PPTX and revise one slide.
G. Download and parse actual DOCX, PDF, PPTX, and a supported XLSX result. Render and inspect the seeded report/deck pages. Check clipping, sources, stale values, bad units, and cross-format contradictions.
H. Continue a seeded thread with a new prompt not present in fixtures. Confirm the real configured model/tool path, not scripted text. Report mock-only results separately.
I. Exercise missing-provider, timeout, malformed-file, cancellation, duplicate-send, refresh, stale-version, cross-tenant, unauthorized-download, and malicious-document cases. Preserve the previous successful version on failure.
J. Rerun affected tests and applicable lint/type/build/regression on the final code. Compare suspected pre-existing failures against the recorded base with equivalent environment and database availability.

Audit every visible control. Document any action not exercised; do not call it passed. Check that every download resolves to real persisted bytes and every generated message references the correct artifact version.

Reconcile PB-001 through PB-045 individually. For each, include implementation location, test/evidence location, and PASS/FAIL/BLOCKED/DEFERRED-INTEGRATION. Fix introduced defects before reporting completion. Do not delete failing tests, loosen assertions, turn failures into unexplained skips, or rename a stub as an implemented feature.

Where available, use an independent reviewer/test agent for scrutiny, but do not require that capability to proceed. The generating model must not be the sole oracle for numbers or state changes.

Commit the repairs on this branch. Re-run affected checks after the final code change, then push only this feature branch if safe and permitted. Do not merge or deploy.

Return a truthful UAT handoff: branch and final commit, test totals by status, live Claude result, demo result, file/visual result, available versus future module-hook status, unresolved issues, actual startup URL/commands, and precise instructions for my browser UAT. If any critical requirement is blocked, state it prominently instead of declaring full completion.
```

---

## Human UAT — actions to perform in the running application

Use the startup/opening instructions produced from the actual repository; do not assume a port number from a different module or branch.

### Test 1 — Home and history

Click Playbook. Confirm the large composer and plus, prompt chips, Recent Playbooks, then Recent Exported Analyses. Open all three required examples. Scroll back to their beginning. Open an uploaded input and download a generated output. Continue one thread with:

```text
Sharpen the executive summary. Make it more concise and conversational but still professional. Preserve every figure, risk conclusion, caveat, and recommendation. Do not change the rest of the report. Give me a new Word and PDF version.
```

Expected: a new actual version, stronger writing, unchanged facts and unrelated sections, old version retained. A missing-provider message is a live-verification blocker, not a successful AI test.

### Test 2 — Export-only library and selection

In an available source module, complete an analysis. Check that it is absent from Playbook before export. Click Export to Playbook. Return to Playbook, plus → Add exported analyses. Find it, preview it, return, inspect two other analyses, multi-select the intended set, and attach.

Expected: only explicit exports appear; preview/back does not clear the selection; attached content contains the actual result.

### Test 3 — No-template report

Select relevant Scorecard Validation exports and send:

```text
Using only these selected analyses, create a detailed behavioral scorecard validation report. I am not supplying a template. Include scope, data and methodology, results, limitations, findings, conclusions, and recommendations where the evidence supports them. Clearly identify analyses or evidence that are missing. Do not invent tests or a passing conclusion. Provide Word and PDF versions.
```

Expected: a substantive report, not a one-page generic summary, with actual selected evidence and usable files.

### Test 4 — Gap review and partial approval

Upload the demo previous report, methodology document, and current-results workbook, or use equivalent non-sensitive test inputs. Send:

```text
Compare this previous-period committee report with the methodology and current-period results. Identify outdated numbers, missing or partially covered topics, conflicting statements, and unsupported conclusions. Give me a numbered change proposal with the source and target section for each item. Do not edit the report yet.
```

After checking that the proposal contains enough items, send a selection matching its displayed numbers, for example:

```text
Apply changes 1, 2, and 3 only. Do not apply changes 4 or 5. Preserve all other content. If one of the selected changes materially depends on an excluded change, explain that dependency before making it. Create a new report version and summarize exactly what changed.
```

Expected: only the selected changes, new version, sources, old version retained; no silent rewriting of exclusions.

### Test 5 — Presentation and persistence

On a completed report, send:

```text
Turn the latest version of this report into a committee-ready PowerPoint presentation. Keep the important findings, figures, caveats, and recommendations consistent with the report. Use editable text and tables, appropriate charts, and concise slide headlines. Also provide a PDF of the presentation.
```

Open both files, inspect slides, refresh the browser, reopen the playbook, and download again. Verify that the latest version and history remain correct.

Record observed failures in plain language with the thread name, exact prompt, expected behavior, actual behavior, and screenshot when useful. Do not mark human UAT passed merely because automated tests passed.

---

## Prompt 4 — Fix human UAT findings and close the feature branch

**Mode: Auto, same feature branch. Fill in the UAT results before sending.**

```text
Here are my actual Playbook UAT results:

[Replace this line with the tests you performed and what passed/failed. Include screenshots or exact prompts for defects. State clearly which tests you did not perform.]

Read the current Playbook specification, requirement matrix, and UAT report. Fix all in-scope defects reported above on the existing isolated Playbook feature branch. Add regression tests that reproduce each defect, demonstrate the correction, and rerun affected checks after the final change.

Do not reopen settled product decisions or remove requested functionality to make a test pass. Do not touch unrelated branches, merge, deploy, overwrite real data, or claim I approved tests I did not run.

Update the requirement matrix and UAT report with these actual human results, remaining blockers, and the final code/test evidence. Confirm that the three seeded histories, 30 exports, real generation, selective revisions, artifact versions, and downloads still work after fixes.

Commit the final scoped changes and push only this feature branch, subject to the existing repository safety/automation constraints. Do not merge into the default branch. Do not create or enable automatic deployment. If pushing is blocked, report the actual final commit and exact blocker.

Return:
- Exact branch, base commit, final commit, and push status.
- Which UAT findings were fixed and the tests proving each fix.
- Final passed/failed/skipped/blocked test counts.
- Separate statuses for standalone implementation, demo, live Claude, browser/file verification, future source-module integration, and my human UAT.
- Remaining defects or prerequisites, with no hidden exclusions.
- Exact instructions to reopen/test this branch and the later integration handoff.

Mark the development task closed only when the agreed standalone scope is complete and critical acceptance checks have passed. If not, leave it clearly marked open/blocked with the exact reason. Do not equate “committed” with “accepted” and do not merge.
```

---

## Recovery prompt — only if the coding session stops or loses context

**Use on the same feature branch. Do not create another implementation branch.**

```text
Resume the existing Playbook feature implementation. First verify the working branch and read docs/playbook/MASTER_SPEC.md, IMPLEMENTATION_PLAN.md, PROGRESS.md, REQUIREMENTS_MATRIX.md, and UAT_REPORT.md. Inspect git status and the latest commits. Preserve existing work. Identify the first incomplete or failed requirement and continue from there; do not restart, re-scaffold, change the base, or merge other branches. Run the remaining implementation and verification steps, update evidence, and give a truthful handoff. If a previous process was interrupted, inspect its durable state before retrying so files, messages, jobs, and versions are not duplicated.
```

## Evidence required before calling it finished

A persuasive final summary is not enough. Require the actual feature branch and commit; a complete requirement matrix; three working seeded histories; 30 inspectable exports; a fresh no-template report; partial-approval proof; real Word/PDF/PowerPoint files; source/numeric consistency; provider smoke evidence; browser/button evidence; and clear separation between passed standalone work and future integrations.

Missing live credentials means live generation remains unverified. Missing future module branches means those named hooks remain pending integration. Neither should be hidden by a generic “all green” statement.

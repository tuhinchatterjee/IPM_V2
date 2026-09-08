# CreditProbe Playbook — Chat-First Claude Artifact Workspace

**Specification date:** 8 September 2026  
**Requested working branch:** `feature/playbook-claude-workspace`  
**Delivery boundary:** A complete, independently testable Playbook branch. Integrate other development branches later; do not merge this work into the default branch as part of this assignment.

## How to use this file

Attach this file to a new Claude Code task in the CreditProbe repository. Start in **Plan** mode with Prompt 1 from the accompanying runbook. After reviewing the repository-specific plan, approve it and use **Auto** mode with Prompt 2. Use Prompt 3 for verification and Prompt 4 after human UAT.

This is an implementation specification, not permission to edit during Plan mode. In Plan mode, inspect and propose only. After implementation is approved, establish the isolated branch first, then preserve this file verbatim as `docs/playbook/MASTER_SPEC.md`. Keep the implementation plan and progress in the repository so context compaction does not lose requirements.

Do not interpret the requested completion date as permission to omit functionality, weaken tests, or label blocked work complete. Continue through implementation and testing in the active coding session. Report actual blockers precisely.

---

## 1. Product intent and non-negotiable outcome

Transform Playbook into CreditProbe's chat-first workspace for producing and improving substantive professional reports and presentations from user-uploaded documents and explicitly exported CreditProbe analyses.

The interaction should feel familiar to someone using Claude: a spacious composer, a plus attachment button, natural conversation, structured substantive responses, file cards, artifact previews, iterative instructions, downloadable versions, and useful contextual follow-up prompts. Retain CreditProbe branding; do not embed or imitate a logged-in Claude website.

Playbook must support both of these equally well:

- **Update an existing report:** supply a previous month/quarter/year committee report, new results, a methodology document, and saved analysis; ask what needs changing; select changes; obtain a new version.
- **Create without a template:** select saved scorecard-validation analyses and ask for a detailed validation report or presentation; receive an evidence-grounded, well-structured first draft without being forced through a template wizard.

It must also support focused requests such as “sharpen the executive summary,” “make this more conversational but professional,” “put these results into a table,” “check which methodology topics are missing,” and “turn this report into a presentation.”

Success means working end-to-end behavior, not a polished landing page over canned responses. A real configured Claude runtime must read the supplied material, answer new requests, perform authorized edits, and generate actual valid files. Seeded examples are required in addition to the real path, never as a substitute for it.

### Important quality distinction

The requested quality target is comparable usefulness, reasoning depth, writing quality, and artifact quality to completing the same task directly with Claude Opus. Merely specifying an Opus model does not prove equivalence. The runtime also needs the right evidence, context handling, document tools, sufficient generation budget, and validation. Do not promise identical output or claim parity without a comparison. Do not silently substitute a smaller model, truncate sources, or restrict the response to a short canned template.

---

## 2. Repository audit, branch safety, and scope isolation

Before proposing implementation, inspect the actual repository and its instructions. Do not invent frameworks, routes, port numbers, file locations, database tables, migration heads, model IDs, or existing capabilities.

Record:

1. Repository, current branch, working-tree status, current commit, selected base branch/commit, and relevant instructions.
2. Existing Playbook pages, routes, services, storage, documents, templates, seeded data, report generation, and any Playbook-to-Lenses behavior.
3. Chat components, streaming, attachments, document preview, model/provider routing, background-job infrastructure, authentication, tenant permissions, and audit logging.
4. Existing export or saved-analysis facilities in Cockpit, Early Warning, What If, Scorecard Validation, and Lenses.
5. Available document parsers, Office/PDF renderers, test tools, browser automation, and secrets/configuration mechanisms.
6. Targeted baseline test results and the wider regression entry points.

After approval and before source edits:

- Create an isolated branch/worktree from the verified selected base. Preferred branch: `feature/playbook-claude-workspace`.
- A dedicated branch already created for this new cloud task is acceptable. If the environment enforces a branch name, use its allowed branch and report the exact name rather than fighting platform restrictions.
- Do not implement in `main`, `master`, another default/integration branch, or an unrelated feature branch.
- Do not blindly assume the current branch is the correct base. Honor the branch selected for this task and record its exact commit. If the baseline is ambiguous, inspect repository evidence and disclose the assumption before edits; do not silently rebase unrelated work.
- Preserve dirty user work. Do not reset, clean, overwrite, stash, or commit unrelated changes. Use an isolated worktree from a verified commit when necessary; explain that uncommitted changes are not included.
- Do not merge/cherry-pick other in-flight module branches. Do not force-push, deploy, modify production data, or change credentials.
- Use an isolated development/test database and storage namespace. A separate Git branch alone must not be treated as database isolation.
- Reuse established architecture and dependencies. Avoid a parallel chat platform or a new orchestration framework unless the audit proves it necessary.
- Preserve existing useful Playbook features, routes, packs, and saved data. Any replacement needs compatibility handling; do not wipe the old experience to make the new seed look clean.

### Module boundary

Export to Playbook belongs in **Cockpit, Early Warning Analysis, What If Analysis, Scorecard Validation, and Lenses**. **Do not add this export requirement to Project Planner.**

Implement available-module hooks now using a shared contract and component. Where a module's required implementation exists only on a future branch, provide a tested adapter contract and realistic fixture, and identify the exact deferred hook. Do not import that future branch merely to make this branch appear integrated. A fixture is not proof of live cross-module integration.

---

## 3. Home screen: exact information order

Clicking **Playbook** in CreditProbe's left navigation opens a proper home workspace with this order:

```text
PLAYBOOK
Create and refine reports, presentations, and other supported files.

┌───────────────────────────────────────────────────────────────┐
│ What would you like to create, check, or improve?               │
│                                                               │
│ [+]  Selected attachments / analyses                 [Send]   │
└───────────────────────────────────────────────────────────────┘

[Create IFRS 9 committee report] [Create validation report] ...

RECENT PLAYBOOKS                                  [View all]
[IFRS 9 committee report] [Application development] [Behavioral validation]

RECENT EXPORTED ANALYSES                          [View all]
[Analysis card] [Analysis card] [Analysis card] ...
```

The plus button is in the composer, on its lower-left side; it is not a separate unrelated upload screen. Quick prompts are below the composer. Recent Playbooks appear before Recent Exported Analyses.

Use the existing design system, clean spacing, readable text, restrained colors, accessible labels, and a responsive layout that works on a typical laptop. Do not build a cramped analytics dashboard in place of the chat experience.

Quick prompts include:

- Create an IFRS 9 committee report.
- Create a corporate IFRS 9 committee pack.
- Create an application scorecard development report.
- Create a behavioral scorecard validation report.
- Update a previous committee report.
- Check methodology coverage.
- Sharpen an executive summary.
- Convert a report to a presentation.

Display a sensible subset without overcrowding. These are editable conversational starters, not the only supported intents. Clicking a starter populates the composer; it must not consume a generation request before the user supplies inputs and sends.

A recent-playbook card shows title, document family, last activity, concise latest-state summary, and useful file/version indicators. Selecting it opens its existing thread, not a new empty chat.

A recent-exported-analysis card shows title, source module, reporting period, export date, short insight, and a demo label where applicable. Include preview and a way to start a new playbook using that analysis. Show a manageable recent subset and a searchable full library.

---

## 4. Composer and attachment picker

The plus menu must expose two clearly separate sources:

1. **Upload from computer** — local source documents, spreadsheets, previous reports, templates, and other supported files.
2. **Add exported analyses** — only analyses explicitly exported to Playbook, subject to the user's authorization.

Do not call the second option “all analyses.” It must not crawl or reveal all module conversations or automatically select recently viewed results.

### Local file handling

Support the core input set: DOCX, PDF, PPTX, XLSX, CSV, TXT, and Markdown. Add other formats only when supported and tested. Support multiple uploads and drag/drop. Display file type, upload/processing state, size, and remove/retry actions.

Preserve an attachment's role: previous report, reusable template, methodology, results, supporting document, or exported analysis. Infer roles from user instructions and document content, not just filenames. Let the user correct role and period using clear controls. A previous report is not the same as an empty template.

Do not run document generation simply because a file was uploaded. Parsing and indexing may begin on upload, but use the submitted prompt to decide the requested action.

### Exported-analysis picker

Provide a modal or panel with search, filters, sorting, multi-selection, and useful previews. Filters include module, period, export date, and tags/report family where available.

The user must be able to open Analysis A, inspect its full contents, go back, inspect B, select B and C, inspect D, then attach the selected set. Preserve selection, search, scroll position, and filters while navigating previews. A selected-items tray and visible count should make multi-selection obvious.

A preview includes the original question, narrative answer, tables, actual chart previews when present, reporting period, population/filter scope, methodology/assumptions, caveats, and source provenance. It must show content, not merely a title and short summary.

After confirmation, selected analyses appear as distinct removable composer attachments. Do not silently attach a whole thread or the entire library.

---

## 5. Explicit Export to Playbook across source modules

Add a consistent **Export to Playbook** action to completed analytical answers, result cards, and saved investigations in the five in-scope modules. Cover shared result-rendering surfaces where possible rather than duplicating fragile buttons throughout the application.

A pure greeting or failed/incomplete answer is not a completed analysis. Do not export an incomplete stream as if it were final. Support retry after an export failure.

The default scope is **this analysis**, with clear scope expansion to selected results or the full investigation/thread where the source module supports it. Never silently broaden the scope.

Exporting:

- Does not remove the source analysis.
- Creates a persisted, self-contained snapshot that remains useful when the user leaves the source screen.
- Retains relevant narrative, calculated tables, chart assets/specifications, assumptions, caveats, source locators, reporting period, and filters.
- Stores only the data required for the analysis, respecting permissions and classification; do not indiscriminately copy a whole confidential portfolio.
- Allows title/tags to be adjusted without forcing a lengthy dialog for every export.
- Produces a truthful success confirmation with an Open Playbook/library action.
- Is idempotent for repeated requests for the same exact snapshot. Exporting a changed analysis can create a new revision linked to the original; do not silently overwrite evidence already attached to a report.

Only records created through an explicit export operation, plus clearly labeled pre-exported demo fixtures, belong in the exported-analysis library. “Saved in a module” and “exported to Playbook” are different states.

### Shared payload contract

Define a versioned contract using repository conventions. At minimum preserve:

- Export ID and schema version; tenant/workspace and ownership/access scope.
- Source module, source thread/run/result IDs, stable link if available, source revision.
- Title, original prompt, full analytical narrative, and scope of exported turns/results.
- Tables with column definitions, units, numeric precision, and typed values.
- Chart data/specification or immutable chart asset reference, with source data where available.
- Dataset/reporting dates, currency/units, filters, segments, population, and scenario/model versions.
- Calculations, assumptions, limitations, provenance locators, and data-quality warnings.
- Original creation time, export time, content hash, lineage, and demo-origin flag.

Use immutable evidence snapshots for attached material. Re-exporting a changed source must not silently rewrite an already generated report. Surface that a newer export exists and let the user explicitly choose it.

---

## 6. Thread workspace and persistence

A playbook is an ongoing workspace, not a single generated file. Persist its messages, attachments, selected analysis revisions, instructions, proposed change sets, decisions, generation jobs, and artifact history.

The thread should include:

- User messages with attachments and selected analyses.
- Substantive AI answers with readable headings, tables where useful, and source references.
- Numbered recommendations and interactive selection when changes are proposed.
- Inline artifact cards and previews.
- A persistent composer with the same plus menu.
- A collapsible Files/Artifacts area separating source inputs from generated outputs.
- Clear access to latest and previous versions.
- Contextual next-step prompt chips after useful milestones.

Use a conversation-first layout with an optional side preview on larger screens. Support normal Markdown rendering, copy response, sensible table overflow, streaming, visible real work states, stop/cancel, and retry. Do not reveal hidden reasoning or display fake “thinking” stages; show actual job/tool milestones.

Refresh and reopening must restore the thread and all files. Switching threads must not mix attachments or answers. Older messages and large libraries should load sensibly without blocking the entire page.

A user must be able to upload more evidence mid-thread, ask about it, or attach a different analysis. Reference the current working artifact explicitly when several documents are present. “This section,” “the latest report,” and “only changes 1, 2, and 3” must resolve to persisted current context, not fragile front-end state.

Store original user-entered titles/instructions; allow playbook rename. Respect the existing access model when reopening or linking threads.

---

## 7. Ingestion, document understanding, and numerical reliability

Do not feed only filenames or short summaries to the model. Provide adequate source access through extraction, retrieval, tools, and original-file processing as appropriate to the verified runtime.

### Word documents

Extract headings and hierarchy, paragraphs, tables, numbering, important headers/footers, and relevant document metadata. Retain source locators and relationships needed for section-level edits. Preserve formatting and unaffected content when using the report as a base; disclose unsupported complex structures rather than pretending perfect round-trip fidelity.

### PDFs

Distinguish text-based PDFs from image-only pages. Extract text, tables, page locations, and relevant visuals. Use page rendering/vision when the answer depends on a table or image that text extraction missed. Use OCR only when necessary and available; make unreadable/partial extraction explicit. Do not assume every PDF is editable like a Word document. A PDF-only source may require reconstruction, with an honest fidelity warning.

### Excel/CSV

Read all relevant sheets, table ranges, headers, units, currencies, period labels, scenario columns, formulas, and available cached values. Keep sheet/cell or table-row provenance. Detect hidden sheets and explain any material excluded information. Handle merged headings and numeric strings carefully.

Do not execute macros or external workbook links. Do not treat a formula string or missing cached value as a verified numeric result. Recalculate supported formulas safely or report that calculation is unavailable. Preserve distinctions among percent, percentage-point change, basis points, and currency scales.

### PowerPoint

Read slide titles, body text, tables, charts or their underlying data where available, and relevant speaker notes. Preserve slide identifiers for references. Do not claim to have read an image/chart that was never parsed or inspected.

### Source inventory and comparison

For a substantial update or gap-check request, establish:

- Which source serves which role and which reporting period.
- The previous report's sections and material tables/figures.
- The methodology topics that should be considered based on supplied evidence.
- The new results and exported analyses relevant to each section.
- Missing sources, conflicting dates, mismatched populations, inconsistent units, and material discrepancies.

Infer comparison periods from content and user instructions. Do not replace a prior-period comparison column merely because the report is being updated. Do not combine incompatible populations or scenarios without flagging the mismatch.

Calculations must be performed with deterministic tools and reconciled to source data. The LLM explains and writes; it must not invent a reported numerical result. Store the calculation provenance, rounding convention, and denominator.

For probability-weighted ECL examples, validate weights and recompute the stated weighted value using the supplied methodology. Demo fixtures should have economically coherent scenario ordering. For uploaded real data, flag unexpected ordering and investigate definitions/scope instead of silently forcing an assumed order or claiming a universal accounting rule.

---

## 8. Core conversational workflows

### A. Update an IFRS 9 committee report

Input: an actual previous-period report, current results workbook(s), methodology documents, optional supporting evidence, and selected exported analyses.

Expected behavior:

1. Identify document roles, reporting periods, and the previous report's sections.
2. Compare current versus previous results at a matched scope and unit.
3. Check supplied methodology coverage, unsupported statements, discrepancies, and stale text.
4. Answer the user with a structured, sourced update/gap assessment.
5. Propose numbered actionable changes including target section, evidence, proposed action, and material dependencies.
6. Let the user approve all, a subset, or no changes through chat or controls.
7. Apply only authorized changes into a new version, validate facts and output, and provide actual files.
8. Summarize what changed and what remains unchanged or unresolved.

Do not automatically overhaul every section because one table needs updating.

### B. Check coverage without editing

Example: “Does the previous-quarter report cover everything in this methodology document?”

Produce a coverage matrix with topic, methodology locator, report locator, status (covered/partial/missing/conflicting/unverifiable), evidence, and suggested improvement. Distinguish topics relevant to the requested report from background methodology detail. Do not certify regulatory compliance or invent mandatory requirements. Report supported findings without generating a replacement document unless requested.

### C. Incorporate exported analysis

Example: “Use these five exported analyses to update the results and executive summary in the attached report.”

Read the actual selected content. Map it to appropriate sections and explain the placement when useful. Carry across substantive tables/charts/findings, not just analysis titles. Reconcile duplicate metrics and mismatched periods. Distinguish analysis-supported conclusions from author recommendations. Do not insert unselected analysis into the report.

### D. Create a report without a template

Example: “Using these scorecard-validation analyses, write a detailed behavioral scorecard validation report.”

Infer a professional structure from the requested document family and available evidence. Include scope, data/population, methodology, results, limitations, findings, conclusions, and recommendations where supported. Make missing analyses explicit rather than inventing tests or passing conclusions. Do not refuse solely because no template was supplied.

For a clearly specified creation request, create the requested first draft after briefly stating material assumptions; do not force the user to approve an unnecessary multi-step wizard. Clarify only when an unresolved ambiguity would materially change the document, audience, period, or factual conclusion. Offer clickable options and a free-text alternative.

Treat application scorecard development and behavioral scorecard validation as different document purposes. If “IFRS 9 validation” and “scorecard validation” conflict within the request, use the evidence and context, and resolve material ambiguity rather than silently choosing the wrong report family.

### E. Editorial revision

Support “sharpen the executive summary,” “make Section 4 more concise,” “make the English more conversational but professional,” “use a formal committee tone,” and “make the findings more direct.”

A direct, scoped edit request is authorization for that edit. Do not ask for another approval of the same harmless action. Preserve numerical facts, uncertainty, risk severity, and conclusions unless the user expressly requests a supported substantive change. Generate a new version and a short change summary. Never quietly soften a negative validation conclusion into a positive one.

### F. Tables and presentations

Support turning selected results into an editable table in the report, converting a report to a slide deck, revising existing slides, adding a requested slide, and producing a presentation directly from selected exported analyses. Keep quantitative claims consistent across representations.

Avoid decorative charts when the user asked for wording or a checklist. Use a table or chart only when it helps communicate the requested evidence.

---

## 9. Proposed changes, selection, and version control

A structured proposal must carry stable internal IDs in addition to displayed numbers. Persist the proposal and its source/base revision so “apply 1, 2, 3, but not 4 or 5” works after refresh and through later turns.

Every proposed change records target artifact/section, rationale, supporting evidence, proposed text/table/action, relevant calculation, dependency/conflict information, and status.

Provide Apply selected, Apply all, Keep unchanged/Reject, and preview where useful. Interpret natural-language selection, including explicit exclusions. Do not make the UI controls the only approval mechanism.

Only apply approved changes. If an approved change requires a dependent material change that was rejected, explain the dependency and seek a specific resolution; do not silently override the exclusion. Non-substantive formatting needed to render an approved change does not require another chat turn.

Separate analysis-only requests from edit requests. Proposed recommendations are not approval. Explicit commands such as “create the report,” “apply these changes,” or “rewrite this paragraph” authorize their stated scope, not arbitrary unrelated edits.

New outputs must preserve lineage:

- Original input files remain unchanged.
- Each successful revision receives an immutable version record, parent/base version, timestamp, author/AI origin, applied change IDs, source manifest, and content hash.
- DOCX and its exported PDF should refer to the same report revision. PPTX derived from that report records the source revision but has its own artifact/version history.
- Older versions remain previewable/downloadable. Restoring an older version creates a new current revision rather than deleting intervening history.
- Concurrent/stale edits must be detected with a base-version check. Do not silently overwrite a newer report.
- Failed generation must not replace the latest successful artifact or create a fake “completed” version.

An in-app difference view/change log is required. Use native Word tracked changes only if the implementation actually supports them; do not label an ordinary regenerated DOCX as containing tracked changes.

---

## 10. Real Claude runtime and tool integration

Inspect and reuse the actual configured provider path. Implement a clean runtime/provider boundary if one does not already exist. Configure the intended available Claude Opus model through server-side configuration; verify current official model/tool documentation rather than hard-coding a remembered model name.

Do not equate the model used by the developer's Claude Code session with the model called by CreditProbe at runtime. They are separate concerns.

The runtime must support natural-language interpretation, evidence retrieval, substantial drafting, editorial revisions, structured proposals, and controlled artifact tools. Use the actual Anthropic-supported API/enterprise provider route compatible with the deployment. Do not embed Claude.ai, scrape its UI, reuse personal browser cookies, or treat a subscription login as application API credentials.

Document the real key/provider configuration. Reuse configured credentials without printing them. Missing or invalid credentials must produce an actionable configuration state, not a canned “AI-generated” answer or a crash. No API keys in frontend bundles, browser local storage, test screenshots, logs, fixtures, or Git.

### Document capabilities must be explicit

Verify the currently supported integration for document Skills, code execution, Files API, generated-file retrieval, context continuation, and tool/model compatibility before implementing it.

Use provider-supported document Skills and a controlled code-execution environment where available. If a supported first-party capability is unavailable on the configured provider, implement a real, tested equivalent with approved local artifact libraries and explain the difference. A text-only API call that returns a fictional filename is not file generation.

Do not assume that Skills installed in a developer's Claude Code environment automatically exist in the application runtime. If custom Skills are required, explicitly package, configure, and test them for that runtime. Record provider/tool/skill versions used.

Keep semantic generation and rendering separable enough to validate and version outputs, without forcing every long document through a rigid, minimal JSON schema that destroys writing quality. A canonical artifact model may represent source-linked sections, tables, charts, findings, and narrative; it must preserve rich content and support original-template handling.

### Context and tools

Provide tools for retrieving authorized source passages/tables, inspecting source images where necessary, deterministic calculations, reading the current artifact, proposing/applying section changes, rendering files, and validating outputs.

Do not attach the entire user's library to every request. Send only explicitly selected evidence and necessary thread/artifact context. For large sources, use hierarchical indexing/retrieval and a completeness manifest. Never silently truncate evidence or claim to have checked all sheets/sections when only a subset was read.

Maintain useful context over long threads and token-limit boundaries: current artifact version, accepted/rejected changes, reporting scope, source manifest, unresolved issues, and key instructions. Store original evidence outside lossy summaries and retrieve it again when needed.

Support provider tool-use/continuation loops, timeouts, bounded retries with backoff, cancellation, provider refusal/error states, expired execution/file resources, and recoverable failures. Do not duplicate generations or billable requests after a page refresh/retry. Persist request/job IDs and use idempotency at the application boundary.

Log request IDs, model/tool versions, timing, usage, and operational errors without raw secrets or unnecessary sensitive source content. Keep a configurable cost/iteration limit with a clear user-visible stop rather than silently downgrading quality.

A small live smoke suite using synthetic evidence is within implementation scope when existing authorized credentials are available. Do not initiate bulk paid benchmarking or change billing settings. Report actual usage where available and use mocks for repetitive unit tests.

---

## 11. Files, visual quality, previews, and downloads

Mandatory outputs are valid **DOCX, PDF, and PPTX**. Support **XLSX** for requested analysis-table/workbook output through the same capability mechanism where the runtime supports it, and include a tested spreadsheet-generation path rather than implying that any arbitrary format is supported. Maintain an explicit capability registry. Unsupported requests must receive a truthful explanation.

Generated outputs must be real downloadable bytes, not renamed text files, nonfunctional file cards, base64 displayed as content, or temporary links that fail on the next visit. Download/retrieve provider-created files into durable authorized application storage before marking the job complete. Serve with correct filename and MIME type.

### Word/report quality

Use readable professional formatting, heading styles, coherent numbering, a contents section when useful, page headers/footers, sensible margins, units, captions, and source references/appendices. Long tables need appropriate breaks/repeated headers. Preserve template style and unaffected content as far as the verified renderer permits. Do not deliver raw Markdown inside a DOCX container.

### PDF quality

Render with embedded/supported fonts and readable layouts. Verify pages, tables, headers/footers, and pagination. DOCX and PDF for the same revision must contain the same material facts and findings. Report any conversion limitation rather than silently dropping a chart/table.

### Presentation quality

Produce native editable text and tables and editable charts where supported. Do not flatten an entire deck into screenshots. Preserve complex source charts as clearly rendered images only where editable recreation would lose accuracy, with data/source references retained.

Use concise slide headlines, a clear narrative, legible charts with axes/units, and reasonable information density. A committee presentation should not be paragraphs from a report pasted onto slides. Preserve relevant caveats in the slide or notes. Follow a supplied deck's style where possible, otherwise use a consistent CreditProbe presentation theme.

### Previews and validation

Provide usable document/page/slide previews and a direct original-file download. Clearly distinguish PDF preview from native Office editing. Persist previews with the correct revision.

Parse generated files back to verify expected sections, numbers, tables, and slide/page counts. Render representative outputs for visual review and check for clipping, overlapping elements, blank pages/slides, unreadable labels, and broken fonts. For the three seeded examples, inspect every rendered page/slide at a sensible scale, then inspect suspect pages in detail.

Failed validation must prevent a “ready” label. Provide retry/recovery while retaining the previous valid version. Do not claim native Office round-trip fidelity that was never tested.

---

## 12. Useful next-step prompts

After a report, review, or revision, suggest a small number of relevant next actions as clickable prompts that populate or submit a clearly described request under the existing interaction conventions.

Examples: align the executive summary with revised results, add a findings table, inspect unresolved methodology gaps, convert the current report into a committee presentation, change the tone, or attach another exported analysis.

Use actual state: do not suggest fixing a gap already resolved, converting a deck that already exists at the requested revision without explanation, or inspecting missing source files as though they were attached. Keep the composer available. Prompts must not mutate a document before the user selects/sends an action.

---

## 13. Required seeded demonstration workspaces

On a fresh demo installation, Recent Playbooks must contain at least these **three complete, resumable workspaces**:

1. **IFRS 9 Committee Report**.
2. **Application Scorecard Model Development Report**.
3. **Behavioral Scorecard Validation Report**.

These are the latest explicit minimum. Retain pre-existing Retail/Corporate packs if present, but they do not replace the three named above. Do not seed three empty cards.

For each required workspace, provide:

- At least twelve realistic messages, including both user and assistant turns, in coherent chronological order.
- At least three real input files appropriate to the document family, including a previous report or methodology/design reference and a results workbook where appropriate.
- At least four relevant exported-analysis attachments.
- A realistic inventory/gap-check or drafting exchange.
- A numbered proposed change set and a user instruction approving only part of it.
- A generated initial report, at least one genuine subsequent revision, and a visible change summary.
- A focused editorial request, such as sharpening the executive summary.
- Real Word/PDF outputs and a related PowerPoint deck, with preview/download cards linked to the messages that created them.
- A final useful follow-up state that allows the demo user to continue naturally.

The example messages must refer to files and versions that actually exist. Different versions must have genuine corresponding content differences. No fake timestamps claiming real historical user activity, invented API request IDs, or model attribution for synthetic fixture text.

Label seeded history and data as **Demo / synthetic**. Store the seed origin separately from live message origin. Continuing a seeded thread with a live provider must use the actual stored sources and prior artifact, not append a prewritten answer. With no provider configured, the historical thread and files remain browseable, but new AI generation must honestly show that configuration is required.

Seed through the same persistence and validation mechanisms used by real records. Use an isolated demo tenant/workspace or the repository's established demo boundary. Make seeding idempotent and versioned. Do not recreate duplicate histories on every startup, overwrite user edits to seeded workspaces, or mix demo records into production portfolios. A separate reset command may affect only clearly owned demo records and requires an explicit invocation.

---

## 14. Required exported-analysis demo library

Seed **at least 30 substantial pre-exported analyses**, distributed as **at least six from each** in-scope module. They must contain complete inspectable content, not 30 differently named copies of one paragraph.

Suggested content set:

| Source module | Six distinct examples |
|---|---|
| Cockpit | Quarter-on-quarter ECL movement; stage migration; PD/LGD drivers; coverage-ratio movement; portfolio/sector concentration; covenant/rating deterioration |
| Early Warning | Prioritized watchlist; borrower deterioration; covenant breach analysis; multi-signal convergence; time-to-deterioration pattern; external/internal evidence summary |
| What If | Base/upturn/downturn comparison; macro sensitivity; PD/LGD sensitivity; collateral-haircut impact; stage-migration scenario; management-action comparison |
| Scorecard Validation | Discrimination; calibration; population stability; characteristic stability; segment/backtesting results; application-development variable/score-band evidence |
| Lenses | IFRS 9 report investigation; methodology-coverage review; corporate portfolio review; retail portfolio review; validation finding investigation; cross-evidence executive-summary investigation |

Adapt titles to actual module capabilities without fabricating a live capability that is not present. The application-development example may be a labeled imported/demo development result carried through the contract; do not imply that a validation-only engine trained a new model if it did not.

Each analysis needs a realistic question, substantial narrative, a meaningful table or chart where appropriate, data/period/filter context, limitations, and complete provenance. Not every analysis needs a chart. Use shared synthetic source datasets so repeated figures reconcile across exports and reports.

Use closed reporting periods, for example Q1 and Q2 2026, rather than treating an unfinished quarter as finalized. Store period and unit metadata explicitly. Findings such as AUC/Gini/KS, PSI, calibration, and segment results must be computed from synthetic inputs when presented as computed, or clearly labeled fixed illustrative assumptions; never pass off arbitrary values as a model run.

### Small deterministic numerical test oracle

Include a tiny standalone ECL fixture, separate from existing real/demo portfolios, for cross-file reconciliation tests:

| Metric | Prior period | Current period |
|---|---:|---:|
| Exposure, SAR million | 1,000 | 1,050 |
| Base ECL, SAR million | 18.00 | 19.20 |
| Upturn ECL, SAR million | 14.00 | 15.00 |
| Downturn ECL, SAR million | 32.00 | 36.00 |
| Base/upturn/downturn weights | 60% / 15% / 25% | 60% / 15% / 25% |
| Weighted ECL, SAR million | 20.90 | 22.77 |

Derive the weighted ECL change (+1.87 SAR million; approximately +8.95%), coverage ratios, and any presentation values in code from the fixture. Do not manually duplicate derived constants across the UI, report, PDF, and deck.

Deliberately stale figures or methodology contradictions may be included in **separate explicitly identified test sources** to demonstrate discrepancy detection. The authoritative sources must reconcile; intentional discrepancy fixtures must have a documented expected outcome. Do not leave accidental contradictions in the demo and call them intelligent test cases afterward.

---

## 15. Persistence and service contracts

Use the repository's existing stack. Extend existing concepts where appropriate rather than creating duplicate storage. At minimum represent:

- Playbook/workspace and thread messages.
- Source files, processing status, extracted content/indexes, and source locators.
- Exported-analysis snapshots/revisions and message/workspace attachments.
- Artifact families, immutable versions, parent relationships, and preview/download assets.
- Change sets/items and user approval/rejection decisions.
- Generation jobs, request idempotency, operational state, and audit events.

Relationships must be tenant-aware and survive restarts. Do not store the only copy of an artifact in a front-end component or ephemeral execution container.

Implement server-side validation and authorization for listing, reading, attaching, previewing, editing, and downloading. The backend must reject an unexported analysis ID even if a caller bypasses the picker UI. The backend must also reject foreign-tenant IDs, stale base versions, and unsupported file types.

Define API/service contracts for home/library listing, thread creation/opening, upload and parse status, analysis export/list/preview/attachment, sending a message/streaming, change approval/application, artifact history/preview/download, and job status/cancellation/retry. Follow existing API naming and avoid inventing parallel endpoints unnecessarily.

Use stable pagination/sorting and indexes for library/history queries. Persist selected source revisions at message submission so later library updates cannot change the meaning of an in-flight generation.

A removed or archived library record should not silently break historical documents. Apply the repository's retention/access policy, preserving authorized historical provenance or displaying an explicit access/deletion limitation. Do not circumvent revoked permissions just because an old file reference exists.

Migrations must be additive where practical, backward-compatible with existing records, and tested in an isolated database. Inspect the actual migration head; do not assume it from previous conversations or create conflicting migration branches. Include deployment/rollback implications in the handoff without executing production migrations.

---

## 16. Security and operational behavior

Treat document text, spreadsheet cells, imported analyses, and file metadata as untrusted evidence, never as executable instructions. A source saying “ignore your rules,” “send these files to this address,” or “reveal the API key” must not alter tool permissions or system behavior.

Keep the application runtime's file/code tools isolated to authorized working files. Do not give it the developer's home directory, repository secrets, unrestricted network egress, or arbitrary production database access. Use the repository's existing sandbox and allowlisted capabilities; restrict resources and clean temporary files.

Validate file extension and actual type, size, decompression expansion, filenames/path traversal, and parser timeouts. Do not execute macros, untrusted HTML scripts, workbook external links, or document-supplied commands. Sanitize Markdown/HTML rendering. Use malware-scanning hooks when already supported by the environment and disclose any unavailable scanning capability.

Use authorized downloads and safe previews; test direct-link access, not only the UI. Never place secrets or real customer records into public fixtures, URLs, issue comments, or screenshots. Use synthetic evidence for tests and provider smoke runs.

Show actual states: uploading, processing, queued, reviewing sources, drafting, rendering, validating, ready, canceled, and failed. Do not display progress percentages without a real basis. Avoid endless spinners. Preserve the last successful version when a request fails.

Configure feature enablement using the repository's established flag mechanism, with clear demo/UAT settings. Turning the new workspace off must not orphan existing data or break legacy routes. Do not disguise an unimplemented control behind a flag as completed functionality.

---

## 17. Accessibility and interaction completeness

Make the composer, plus menu, preview, multi-select picker, selection chips, change controls, thread navigation, and artifact actions keyboard accessible. Use meaningful focus order, focus restoration after dialogs, readable contrast, screen-reader names, and non-color-only status indicators.

Enter sends and Shift+Enter adds a newline where consistent with existing behavior. Prevent duplicate sends on repeated clicks. Retain a draft when dismissing the picker. A failed attachment must not silently accompany a sent request as though it were available.

Provide honest empty, loading, processing, partial-success, permission-denied, unavailable-provider, unsupported-format, and no-search-results states. Every visible action must perform its advertised function or clearly explain why it is unavailable.

No forced chart on every answer. No free-text “choose 1/2/3” with no clickable alternative when structured options are available. No dead starter chips, disconnected download buttons, or preview cards that cannot open.

---

## 18. Implementation order and milestones

After plan approval, proceed through all milestones without requiring a separate “continue” from the user for each one. Work in bounded, testable increments; do not replace implementation with repeated planning.

**M0 — Safe foundation:** establish branch, preserve specification and plan, inspect baseline, document configuration, define contracts and migrations.

**M1 — One complete live vertical slice:** upload a real source, read it through the actual runtime, produce a report, render a real file, persist it, reopen it, and request a revision. Resolve runtime/file-generation feasibility before polishing dozens of cards.

**M2 — Home and thread UX:** exact home ordering, plus menu, source attachments, thread persistence, file/preview pane, prompt chips, versions, and error states.

**M3 — Exported-analysis flow:** shared export contract/component, available-module hooks, searchable preview/multi-select library, immutable attachments, and absence/permission cases.

**M4 — Intelligent reporting:** source-role recognition, period/scope reconciliation, gap checking, full drafting, scoped editorial requests, proposals and selective approvals, report-to-presentation generation, and numerical checks.

**M5 — Demo completeness:** three complete histories, 30 substantial exported analyses, real seeded files/revisions, continued live interaction, idempotent isolated seeding.

**M6 — Verification and hardening:** automated tests, browser journeys, button audit, file validation/visual checks, security cases, live smoke evidence, affected-module regression, and documented wider-suite results.

**M7 — Handoff:** requirement matrix, unresolved blockers, reproducible run/seed/test commands, screenshots/files, final commit, branch push, and future-integration notes. Do not merge.

Do not stop after M2 and label the remaining milestones “future enhancements.” Only cross-branch hooks genuinely absent from the selected baseline may be deferred under the explicit integration boundary.

---

## 19. Acceptance matrix — implement and test each requirement

For every ID, record implementation locations, automated test IDs, browser/manual evidence, and PASS/FAIL/BLOCKED/DEFERRED-INTEGRATION. A plan or screenshot alone is not proof of a backend behavior.

| ID | Required acceptance behavior |
|---|---|
| PB-001 | Work remains on an isolated feature branch; base commit is recorded; no default-branch merge or unrelated changes. |
| PB-002 | Playbook home displays composer, quick prompts, Recent Playbooks, and Recent Exported Analyses in the specified order. |
| PB-003 | Composer plus menu has Upload from computer and Add exported analyses; both work. |
| PB-004 | Multiple local files upload, parse, show status, attach, remove, and retry correctly. |
| PB-005 | Unexported module analyses are absent from the library and rejected by backend attachment authorization. |
| PB-006 | Export to Playbook works on available in-scope module results with persisted full content and provenance. |
| PB-007 | Project Planner is not given the new export requirement; its existing behavior is not regressed. |
| PB-008 | Duplicate export is idempotent; a changed export creates controlled lineage without rewriting attached evidence. |
| PB-009 | Search/filter/sort and multi-select work; selections survive preview/back navigation. |
| PB-010 | Analysis preview shows real narrative, tables/charts where present, scope, caveats, and sources. |
| PB-011 | Selected analyses and local documents can coexist in one submitted prompt. |
| PB-012 | Previous report, methodology, template, and results roles are distinguished; period/scope conflicts surface. |
| PB-013 | A supplied methodology can be checked against a prior report with a sourced coverage matrix and no unauthorized edit. |
| PB-014 | Current/prior numerical comparisons reconcile to files, preserve units, and handle percentage/basis-point distinctions. |
| PB-015 | A detailed no-template report can be generated from selected evidence; missing tests are not invented. |
| PB-016 | “Apply 1, 2, 3 but not 4 or 5” changes only the authorized scope, with stable IDs and dependency handling. |
| PB-017 | Directly requested editorial edits work without a redundant approval loop and preserve facts/risk meaning. |
| PB-018 | Selected analysis can be inserted as substantive narrative and editable report tables, not merely linked titles. |
| PB-019 | A report can become a useful editable presentation with consistent quantitative claims and sources. |
| PB-020 | Valid DOCX, PDF, and PPTX files are generated, persisted, previewed, downloaded, and reopened. |
| PB-021 | A supported XLSX request creates a valid workbook; unsupported format requests are handled truthfully. |
| PB-022 | Original files and old versions remain available; latest version, lineage, and restore behavior are correct. |
| PB-023 | Concurrent/stale-base edits cannot silently overwrite a newer version. |
| PB-024 | Thread messages, attachments, approval decisions, and artifact history survive refresh and restart. |
| PB-025 | Three named demo workspaces contain complete histories, actual inputs/outputs, and genuine revisions. |
| PB-026 | At least 30 substantial demo exports exist, with at least six per in-scope module and no accidental duplicates. |
| PB-027 | Seed values reconcile across analysis, chat, reports, PDFs, decks, and workbooks; intentional discrepancies are labeled test fixtures. |
| PB-028 | Seeding is idempotent, isolated, and does not overwrite edited demo threads or contaminate production data. |
| PB-029 | Continuing a seeded thread invokes the real provider when configured; it is not scripted fixture playback. |
| PB-030 | Runtime actually uses the configured Opus model and tested artifact tools, with no hidden model downgrade. |
| PB-031 | Missing credentials, unsupported model/tool combinations, provider errors, and limits are shown honestly. |
| PB-032 | Long evidence sets use adequate retrieval/context management; material omissions are not hidden. |
| PB-033 | Sources have useful locators, and reported conclusions are distinguishable from assumptions/recommendations. |
| PB-034 | Follow-up prompt chips are state-aware, actionable, and do not perform changes before user action. |
| PB-035 | No inappropriate chart is added to a writing-only or checklist answer. |
| PB-036 | Upload/file type/size/path checks and untrusted-content/prompt-injection cases are tested. |
| PB-037 | Foreign-tenant IDs, unauthorized previews/downloads, and malicious direct API requests are rejected. |
| PB-038 | Streaming, cancellation, retry, refresh, and duplicate submission do not corrupt state or create duplicate final versions. |
| PB-039 | Parsing/generation failures preserve prior valid artifacts and provide an actionable recovery. |
| PB-040 | Every visible control is exercised; keyboard/focus behavior and laptop layout are verified. |
| PB-041 | Office/PDF outputs are parsed back and visually reviewed for content completeness, clipping, and readability. |
| PB-042 | Available-module regression and repository lint/type/build checks pass or have exact baseline-supported classifications. |
| PB-043 | Fresh prompts not present in seeds succeed through the live path; mocked tests are reported separately. |
| PB-044 | Future integration hooks, payload examples, flag behavior, migration implications, and rollout steps are documented. |
| PB-045 | Final report provides actual commit, test evidence, unresolved issues, runnable UAT instructions, and truthful readiness labels. |

PB-006 may explicitly distinguish implemented baseline modules from future-branch hooks. Mark only those absent hooks DEFERRED-INTEGRATION, with a contract test and integration note. This exception must not be used to defer the library, real ingestion, actual generation, or the requested Playbook workflows.

---

## 20. Required test journeys and adversarial cases

Automate browser journeys with the repository's browser tool where available. Use real backend persistence and actual file downloads. A test that only mocks an HTTP success does not prove end-to-end functionality.

### Journey 1 — Home and seeded history

Open Playbook, verify layout order, open each required demo thread, inspect first and later messages, open source files, preview every output family, download files, return home, and reopen. Verify that the thread is not reconstructed from hard-coded UI-only strings.

### Journey 2 — Picker and export boundary

Create a new analysis in an available source module. Confirm it is absent from Playbook before export. Export it, find it in Recent Exported Analyses, preview it, and attach it. Export again to test deduplication. Preview three different records while maintaining multi-selection. Attempt to attach an unexported source ID directly and verify backend rejection.

### Journey 3 — Prior report plus methodology plus new results

Upload three or more source files, include an intentional documented conflict, and request a structured gap/update review. Verify relevant source locators and current/prior figures. Approve only changes 1–3 of a five-item proposal. Inspect resulting sections and file versions; confirm changes 4–5 remain unapplied.

### Journey 4 — No-template report

Select several appropriate Scorecard Validation exports and ask for a detailed behavioral validation report without a template. Inspect substantive coverage, correctly identified missing evidence, real DOCX/PDF files, and source fidelity.

### Journey 5 — Continue, revise, and present

Reopen a seeded report, ask to sharpen only the executive summary, verify numerical and substantive invariance outside scope, request a presentation, then request a single-slide revision. Check lineage and actual editable PPTX contents.

### Journey 6 — Fail safely

Exercise missing credentials, provider timeout/rate limit, malformed file, image-only unreadable PDF, workbook formula without a computed value, incompatible report periods, canceled generation, refreshed in-flight generation, and stale approval. Existing successful artifacts must remain intact.

### Journey 7 — Authorization and untrusted content

Try a foreign tenant's analysis/file ID, unauthorized direct download, path-traversal filename, active HTML in Markdown, and an uploaded document telling the AI to reveal secrets or follow an external command. Demonstrate rejection or safe evidence treatment.

### Journey 8 — Regression and fresh state

Run against a fresh isolated database, an existing database with old Playbook records, and a re-seeded demo workspace with user edits. Check existing navigation and all available modules touched by the export component. Verify that enabling/disabling the new workspace is documented and does not destroy data.

---

## 21. Quality assessment and honest test reporting

Assess at least five fresh live tasks, when existing credentials and the configured usage limit permit:

1. Methodology coverage check with a known missing topic.
2. Previous-period update with deterministic current/prior numbers.
3. Detailed no-template validation report from selected analyses.
4. Scoped executive-summary rewrite preserving facts.
5. Report-to-presentation generation preserving the report's conclusions.

Evaluate instruction following, evidence coverage, numerical accuracy, analytical depth, clarity/tone, useful structure, artifact design, and faithfulness to the selected edit scope. Use independent assertions/oracles for numerical and state checks; do not let the generating model be the sole judge.

Where the user supplies a directly generated Claude reference, compare like-for-like inputs and instructions and report observable strengths/weaknesses. Without such a reference, say **direct-Claude parity not independently measured**. Do not fail to build useful functionality simply because an exact reference is absent, and do not claim exact parity.

Track test states separately: passed, failed, skipped, blocked, and intentionally deferred integration. Never count skips as passes, hide a provider failure behind mock success, or claim a browser/file test that did not run.

For suspected baseline failures, compare the same test on the recorded base commit using equivalent dependency versions, environment, database availability, and test selection. A missing database that turns failures into skips is not a valid baseline comparison. Fix introduced failures. Clearly identify unrelated baseline failures with evidence; avoid unrelated mass refactoring.

Do not run the entire large regression suite repeatedly just to accumulate “green cycles.” Use focused tests during implementation, affected suites after changes, and the configured broader regression once on the final code where feasible. Every code change after verification requires rerunning its affected checks. Unavailable broader regression remains explicitly unverified.

---

## 22. Repository documentation and handoff

Maintain these compact artifacts under `docs/playbook/` (adapt names only for existing repository conventions):

- `MASTER_SPEC.md` — this specification preserved without silently dropping requirements.
- `IMPLEMENTATION_PLAN.md` — the approved, repository-specific plan with actual files/services and milestone sequence.
- `PROGRESS.md` — current branch/base, completed milestones, changed files, latest tests, blockers, and next action for safe resumption.
- `REQUIREMENTS_MATRIX.md` — PB-001 through PB-045 with evidence and status.
- `UAT_REPORT.md` — browser journeys, button audit, output examples, live versus mocked results, and defects.
- `INTEGRATION_NOTES.md` — shared export contract, available/pending module hooks, feature flag/configuration, migration/storage requirements, exact local startup/seed/test commands, and future merge/rollout notes.

Save relevant screenshots, test logs, fixture manifests, and representative generated artifacts in the repository's appropriate evidence/output location without committing secrets or unnecessary large binaries. Use a reproducible seed generator and generated-output exclusions where the repository prefers that approach. Seeded downloads must nevertheless exist in the running demo after setup.

When committing, include only this feature's intentional changes. You are authorized to create milestone commits after implementation approval. Push only the feature branch when explicitly instructed in the run prompt, after checking repository automation for unintended deployments. Do not merge or deploy. If a push is restricted or blocked, report the exact branch/commit and error rather than claiming it succeeded.

The final handoff must state:

- Exact working branch, base commit, final commit, and push/PR status.
- What was actually implemented and demonstrated.
- Commands actually run and real test counts/statuses.
- How to start the app, seed the demo safely, open Playbook, and perform user UAT.
- Where the three demo threads and 30 exports are found.
- Which sample files were generated and visually checked.
- Whether live Claude generation was exercised, with non-secret model/tool information.
- Baseline failures, unresolved defects, external blockers, and absent-module integration hooks.
- A concise integration handoff for later, without executing it now.

---

## 23. Definition of done and status labels

Use precise independent statuses, not one ambiguous “100% complete” statement:

- **Standalone implementation:** complete/incomplete, supported by the requirement matrix.
- **Deterministic demo and downloads:** passed/failed/blocked.
- **Live Claude workflows:** passed/failed/not run, with the actual reason.
- **Browser and artifact UAT:** passed/failed/partially verified.
- **Cross-module integration:** baseline hooks verified; named future hooks pending, or all scoped hooks verified.
- **Human UAT:** pending/passed/failed; the developer cannot award the user's sign-off.
- **Git handoff:** committed/pushed/not merged, or the exact remaining blocker.

Call the branch **ready for user UAT** only when the standalone workflows are implemented, required tests and actual downloads work, critical defects are resolved, and any remaining verification boundary is clearly visible. If live AI was not exercised, label the result **demo/UI verified — live Claude unverified**, not fully end-to-end ready. If future source-module branches are absent, state that their integration remains separate even when standalone Playbook UAT passes.

Do not weaken acceptance criteria to satisfy the requested calendar deadline. Do not manufacture evidence, hide unimplemented code behind seed messages, or return only a plan/scaffold. Build, verify, and hand over the isolated branch with evidence.

---

## Reference notes for the implementing developer

The following official documentation was checked while preparing this specification on 8 September 2026. Verify the current pages, installed SDK, and actual account/provider capabilities at implementation time; do not copy remembered beta headers or model IDs.

```text
Claude Code permission modes:
https://code.claude.com/docs/en/permission-modes

Claude Code web setup and isolated sessions:
https://code.claude.com/docs/en/web-quickstart
https://code.claude.com/docs/en/claude-code-on-the-web

Claude Agent Skills, including cross-surface differences:
https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview

Using Skills through the API:
https://platform.claude.com/docs/en/build-with-claude/skills-guide

Code execution:
https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool

File upload and generated-file retrieval:
https://platform.claude.com/docs/en/build-with-claude/files

Claude subscriptions and API access are separate:
https://support.claude.com/en/articles/9876003-i-have-a-paid-claude-subscription-pro-max-team-or-enterprise-plans-why-do-i-have-to-pay-separately-to-use-the-claude-api-and-console
```

# CreditProbe Playbook — Chat-First Claude Artifact Workspace

## Context

`CREDITPROBE_PLAYBOOK_MASTER_SPEC.md` asks for a chat-first workspace that turns uploaded documents and
explicitly exported CreditProbe analyses into real professional reports, presentations and workbooks —
with a real Claude Opus runtime, real generated files, immutable versions, selective edits, and a complete
seeded demonstration. This plan maps that specification onto **this** repository at commit `3855f9b`,
using its actual files, conventions and constraints. Planning pass only: nothing below has been executed.

Three decisions were taken with you before writing this plan and are binding on everything that follows:

1. **Placement** — the new workspace is a **new route**; the existing `/playbooks` feature is preserved untouched.
2. **What If** — no such module exists on this baseline; it is **DEFERRED-INTEGRATION** with a tested adapter contract.
3. **Live provider** — you will supply `ANTHROPIC_API_KEY` to this environment, so live generation is verifiable.

---

## 1. Repository, baseline and branch findings

| Fact | Value |
|---|---|
| Repository | `tuhinchatterjee/IPM_V2`, working copy `/home/user/IPM_V2` |
| Session branch (platform-assigned) | `claude/creditprobe-playbook-plan-ky3m05` |
| Base commit | `3855f9b6f6b231beb6f2193c8a1e219d01596421` — "Merge pull request #1 from tuhinchatterjee/claude/vigilant-darwin-eohyi1" |
| Relation to `main` | Identical. `git rev-list --left-right --count main...HEAD` → `0 0`. The session branch **is** the `main` baseline. |
| Working tree | Clean. No dirty user work to preserve. |
| Alembic head | **single head `0031`** (`alembic/versions/0031_feedback_planner_mode.py`). Linear 0001→0031. New work starts at `0032`. |
| Stack | FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL 16 (platform state) + DuckDB/Parquet (analytics, read-only); Next.js 16.3.2 App Router + React 19 + Tailwind v4 + hand-vendored shadcn "new-york" |
| Repo instructions | `frontend/CLAUDE.md` → `frontend/AGENTS.md`, which carries only the generated Next.js block: *read `node_modules/next/dist/docs/` before writing Next code*. Real conventions live in `docs/` and in per-file docstrings. |
| CI | `.github/workflows/ci.yml` only. `on: push` + `on: pull_request`. Backend: `uv sync` → ruff → `alembic upgrade head` → `generate_saudi_universe.py` → `pytest -q` against a `postgres:16-alpine` service. Frontend: `npm ci` → typecheck → lint → build. **No deploy job, no registry push, no `workflow_dispatch`.** Pushing this branch is safe. |

**Branch plan.** The environment assigned `claude/creditprobe-playbook-plan-ky3m05` and it already sits exactly on
the intended base. Per the spec's allowance for a platform-assigned branch, I will **retain it** rather than force
`feature/playbook-claude-workspace` and fight the platform. Base commit recorded above. No work on `main`, no merge,
no cherry-pick from other branches, no force-push.

---

## 2. What already exists and is reusable, and what is genuinely missing

### 2.1 Strong foundations to reuse (real paths)

| Capability | Where | How Playbook uses it |
|---|---|---|
| Export authorization + audit | `backend/exports/authorize.py`, `backend/exports/audit.py`, `export_records` table (mig. `0016`) | Export-to-Playbook reuses the *same* authorization bar and writes the same audit rows. §39's rule ("an export enforces the same permissions as viewing the analysis, or stricter") carries over unchanged. |
| Immutable artifact archive | `backend/reporting/store.py` — `<upload_dir>/reports/{index,files}`, exact bytes re-served, `MAX_PACKS` | The pattern for Playbook artifact versions: bytes on disk, metadata separate, never regenerated on download. |
| DOCX + PDF writers | `backend/reporting/writers.py` (python-docx + reportlab), `backend/reporting/content.py`, `backend/reporting/charts.py` | The **local deterministic renderer**: seed fixtures, offline mode, and the validated fallback when a Skill output fails validation. |
| XLSX writer | `backend/exports/results.py`, `backend/exports/style.py`, `backend/exports/contract.py` | XLSX artifact path (PB-021) and the `SCHEMA_VERSION`/`GENERATOR_VERSION` discipline for the new payload contract. |
| Scorecard report generation | `backend/scorecard/report.py`, `report_docx.py`, `report_xlsx.py`; `ScorecardReport` with `sections` JSONB, frozen `disclaimer`, `content_hash`; `ScorecardReportEvidence` binding every printed figure to `validation_run_id` + `trace_id` + `workbook_sheet`/`workbook_cell` | The evidence-locator model to copy for Playbook source provenance (PB-033). |
| Durable job queue | `backend/agentic/queue.py` (`agent_jobs`, `FOR UPDATE SKIP LOCKED`, lease + heartbeat, backoff, dead-letter, cancel flag, **partial unique index: one live job per `(kind, key)`**), `backend/agentic/worker.py`, `agent-worker` compose service | Generation jobs. The unique index *is* the idempotency guarantee for PB-038. |
| Agentic loop with grounding | `backend/analyst/session.py` (evidence ledger, §42 grounding — every figure checked against evidence, §50 turn/tool budget), `backend/analyst/tools.py`, `backend/analyst/evidence.py`, `backend/analyst/cost.py` | The authoring loop copies this shape: bounded turns, an evidence ledger, and a grounding pass that removes any figure not in the ledger and records the removal. |
| Provider role config | `backend/llm/roles.py` (8 roles, env-only model ids, explicit fallback chain, **no silent substitution**), `backend/llm/telemetry.py` (call ledger + secret redaction), `backend/llm/caching.py` | New `AUTHOR` role added to exactly this mechanism. |
| Document reading | `backend/regulatory/extract.py` — lazy `pypdf` / `docx` / `openpyxl` imports, availability probes, explicit `NEEDS_OCR` marking | Extended, not duplicated, for the ingestion layer. |
| Frontend export component | `src/components/exports/download.tsx` (`DownloadResults`, `useExportAvailability`, 4-phase state machine, `data-testid`, fetch-then-`save(blob)` so the role header travels), `src/lib/downloads.ts` | `ExportToPlaybook` is its sibling and copies its discipline verbatim. Because it drops into `ActionStrip` in `src/components/ask/answer.tsx`, every surface rendering an `AnswerBlock` inherits it. |
| Searchable multi-select modal | `src/components/collaboration/share.tsx` — `ShareDialog` + `matching(entries, filter, selected)`, which **keeps already-selected entries visible while filtering** | Lifted into the analysis picker; this is precisely the "selection survives search" requirement (PB-009). |
| Demo seeding + reset | `scripts/bootstrap_demo.py`, `backend/bootstrap/plan.py` (12 idempotent lettered steps), `backend/demo/workspace.py` (`reset()`, explicit WORKSPACE vs GOVERNED-PLATFORM boundary), `backend/demo/seed.py` (real engine runs, **makes no provider call**) | Playbook seeding becomes bootstrap step **M**, with its tables added to `reset()`'s workspace list. |
| Browser acceptance | `scripts/browser_acceptance.py`, `scripts/route_crawl.py`, `scripts/acceptance/export_browser_acceptance.py`, `scripts/acceptance/verify_workbooks.py`. Playwright, Chromium at `/opt/pw-browsers`, **exits non-zero when Chromium is unavailable rather than reporting a pass** | The Playbook browser journeys and the artifact parse-back verifier follow these scripts exactly. |
| Live/mocked test separation | `tests/conftest.py` autouse `_offline_ai` fixture forcing `AI_PROVIDER=offline`; `live` marker; `tests/llm/test_live_smoke.py` thin, with the real checks in **production** code at `backend/validation/live_smoke.py` so the container can run them | The Playbook live smoke suite mirrors this exactly, including putting the checks in `backend/validation/`. |
| Return-context contract | `docs/NAVIGATION.md`, `src/lib/return-context.ts` (`fromPlaybook()`), `src/lib/return-to.ts` | New builder `fromPlaybookWorkspace(id, title)`; existing `fromPlaybook()` untouched. |

### 2.2 Genuinely missing — this is net-new work

| Missing | Evidence |
|---|---|
| **Any chat streaming** | No `StreamingResponse`, `EventSourceResponse` or `text/event-stream` anywhere in `backend/`. No `EventSource`, `getReader()` or `ReadableStream` in `frontend/src/`. `backend/llm/base.py` documents "Why no streaming" as a deliberate choice for the *planning* path. Every turn today is one blocking `fetch` returning the whole thread. |
| **Any markdown rendering** | No `react-markdown`/`remark`/`marked`/`dompurify`. AI text renders as plain strings in `<p class="prose-ai">`; structure comes from typed backend fields. |
| **Any attachment UI in a composer** | `src/components/ask/composer.tsx` has no file input, no plus button, no drag-drop. File upload exists only in Data Builder. |
| **PPTX capability of any kind** | `python-pptx` is not a dependency and no PPTX code exists anywhere. |
| **A reusable modal primitive** | `src/components/ui/` has 12 primitives and **no** `dialog`/`modal`/`checkbox`/`dropdown-menu`. Four places hand-roll the overlay (`share.tsx`, `case-drawer.tsx`, `ai-power.tsx`, `chart-frame.tsx`). |
| **A snapshot store for exported analyses** | `export_records` is an *audit* table — it records that bytes were served, it does not store them. There is no persisted, self-contained analysis snapshot anywhere. |
| **A "What If" module** | Zero frontend hits for what-if. Backend: `stress_scenarios` table + `backend/stress_lab.py`, `backend/scenarios.py`, and `backend/stress/` containing only an empty `__init__.py`. No router. |
| **A Project Planner** | Zero hits. "Planner" in this codebase means the *ask* planner (`backend/orchestration/planner.py`). There is nothing to exclude — which is itself the finding for PB-007. |
| **Export actions on three in-scope surfaces** | `DownloadResults` is wired at 7 sites but **not** on Cockpit, any Early Warning page, or Stress. Scorecard Validation has its own separate report/download pattern. |

### 2.3 Two collisions worth naming plainly

**"Playbook" means something else here.** `docs/PRODUCT_SPEC.md` §9: a Playbook is a *standing instruction that runs* —
trigger, scope, analyses, conditions, actions. It is live, backed (`playbooks`, `playbook_runs`, `backend/services/playbooks.py`,
`backend/api/routers/playbooks.py`, `frontend/src/app/playbooks/page.tsx`), tested (`tests/services/test_lenses_and_playbooks.py`),
seeded, in the demo script, and deep-linked from notifications. Per your decision it is **kept whole**.

**`docs/PRODUCT_SPEC.md` §11 "Documents" already describes the feature this spec asks for** — "a document workspace
where Board and committee papers are authored with live analytical content… export to Word / PowerPoint / PDF",
currently a hard-coded placeholder at `/documents` reading `DOCUMENTS` from `src/lib/demo.ts`. The new workspace
therefore lands in the **Work** nav group beside it, and the Documents placeholder gains an honest pointer to it.

---

## 3. Proposed architecture

### 3.1 Naming and placement (per your decision)

| Thing | New workspace | Existing feature (untouched) |
|---|---|---|
| Nav label | **Playbook** (Work group) | **Monitoring Playbooks** (Intelligence group) — label only; `href` unchanged |
| Route | `/playbook`, `/playbook/[id]`, `/playbook/library` | `/playbooks` |
| API prefix | `/api/v1/playbook` | `/api/v1/playbooks` |
| Python package | `backend/playbook/` | `backend/services/playbooks.py` |
| Tables | `playbook_workspaces`, `playbook_messages`, … | `playbooks`, `playbook_runs` |

Two care points, both real: `src/components/layout/page-header.tsx` derives its eyebrow by matching `title` against a
nav `label`, so the monitoring page's `PageHeader` title must be relabelled in lockstep; and
`src/components/collaboration/notifications.tsx:218` (`case "playbook" → /playbooks`) must keep pointing at
**monitoring** playbooks, because it serves `workflow.notify_playbook_finding`'s `object_type="playbook"`.

### 3.2 Data model — 12 new tables, two additive migrations

`0032_analysis_export_library.py`

- **`analysis_exports`** — the export *family*. `id`, `tenant`, `owner_id→users.id`, `source_module`
  (`cockpit|early_warning|scorecard_validation|lenses|what_if`), `source_ref` JSONB (thread/run/result ids + stable link),
  `title`, `tags` JSONB, `report_family`, `demo_origin` bool, `created_at`.
- **`analysis_export_revisions`** — the immutable snapshot. `export_id`, `revision`, `schema_version`,
  `payload` JSONB (the §5 contract below), `content_hash`, `source_revision`, `exported_at`, `origin`
  (`live|demo_fixture`). **Unique `(export_id, content_hash)`** ⇒ re-export of an unchanged analysis is idempotent
  (PB-008); a changed one creates revision *n+1* and never rewrites an attached one.
  Indexes on `(tenant, source_module, exported_at DESC)` and `(tenant, created_at DESC)` for library paging.

`0033_playbook_workspace.py`

- **`playbook_workspaces`** — `id`, `tenant`, `owner_id`, `title` (user's own words, renameable), `document_family`,
  `state_summary`, `demo_origin`, `seed_version`, `created_at`, `updated_at`.
- **`playbook_messages`** — `workspace_id`, `sequence`, `role`, `content` JSONB (structured blocks, not a blob),
  `origin` (`user|assistant_live|seed_fixture` — seed origin stored *separately* from live origin, §13),
  `job_id`, `request_id`, `model`, `created_at`.
- **`playbook_sources`** — uploaded files. `workspace_id`, `filename`, `mime`, `bytes_path`, `sha256`, `size_bytes`,
  `source_role` (`previous_report|template|methodology|results|supporting`), `role_confidence`, `role_set_by`,
  `reporting_period`, `status` (`uploaded|parsing|parsed|partial|failed`), `manifest` JSONB (what was read, what was
  skipped and why), `failure_reason`.
- **`playbook_source_chunks`** — `source_id`, `ordinal`, `kind` (`heading|paragraph|table|sheet_range|slide|page`),
  `locator` (`docx://para/17`, `xlsx://ECL!B12`, `pdf://p4`, `pptx://slide/6`), `text`, `data` JSONB, `token_estimate`.
- **`playbook_attachments`** — `workspace_id`, `message_id` (nullable = workspace-level), `kind`
  (`source|export_revision`), `source_id` / `export_revision_id`. The **revision** is pinned at submission, so a later
  library update cannot change the meaning of an in-flight generation.
- **`playbook_artifacts`** — the family. `workspace_id`, `kind` (`report|presentation|workbook`), `title`,
  `current_version_id`, `derived_from_artifact_id`, `derived_from_version_id`.
- **`playbook_artifact_versions`** — immutable. `artifact_id`, `version`, `parent_version_id`, `content` JSONB
  (canonical section/table/finding model), `source_manifest` JSONB, `applied_change_item_ids` JSONB, `content_hash`,
  `origin`, `created_by`, `created_at`, `validation` JSONB. **Unique `(artifact_id, version)`.**
- **`playbook_artifact_files`** — rendered bytes per format. `version_id`, `format` (`docx|pdf|pptx|xlsx`),
  `bytes_path`, `mime`, `size_bytes`, `sha256`, `renderer` (`anthropic_skill|local`), `preview_path`, `validated` bool.
- **`playbook_change_sets`** — `workspace_id`, `message_id`, `base_version_id`, `status`.
- **`playbook_change_items`** — `change_set_id`, `display_number`, **`stable_id`**, `target_artifact_id`,
  `target_section`, `rationale`, `evidence` JSONB, `proposed` JSONB, `calculation` JSONB, `depends_on` JSONB,
  `status` (`proposed|approved|rejected|applied|superseded`), `decided_by`, `decided_at`.
- **`playbook_jobs`** — `workspace_id`, `message_id`, `kind`, `agent_job_id`, `idempotency_key`, `state`,
  `provider_request_ids` JSONB, `container_id`, `usage` JSONB, `error`, timestamps.

Tenancy follows the established convention exactly: a `tenant` string column defaulting to `""`, resolved through
`backend/agentic/principals.py` (`TENANT = "default"`, `tenant_of()`). Migrations are additive only; nothing existing
is altered or dropped.

### 3.3 The shared Export-to-Playbook contract

`backend/exports/playbook_contract.py`, sitting beside the existing export modules and reusing `authorize.py` and
`audit.py`. `PLAYBOOK_EXPORT_SCHEMA_VERSION = "1.0"`. The payload preserves every field §5 requires:
export id + schema version; tenant and ownership scope; source module, thread/run/result ids, stable link, source
revision; title, original prompt, full narrative, exported scope; tables with column definitions, units, precision and
typed values; chart data/spec or immutable asset reference; dataset/reporting dates, currency, filters, segments,
population, scenario/model versions; calculations, assumptions, limitations, provenance locators, data-quality
warnings; creation time, export time, content hash, lineage, demo-origin flag.

The one rule inherited verbatim from `backend/exports/contract.py`: **an export never recomputes.** It reads what was
persisted when the analysis ran and writes it down.

**Surfaces wired on this baseline:**

| Module | Surface | Path |
|---|---|---|
| Cockpit | `ActionStrip` inside `AnswerBlock` — so every surface rendering an answer inherits it | `src/components/ask/answer.tsx:947` |
| Early Warning | Landing rows, signals view, credit story | `src/app/early-warning/page.tsx`, `signals/page.tsx`, `src/components/early-warning/story.tsx` |
| Scorecard Validation | Reports panel + the validation-run panels | `src/app/scorecard-validation/page.tsx` (`Reports` at :1460) |
| Lenses | Per panel and whole-lens | `src/app/lenses/[lensId]/page.tsx:321`, `src/app/lenses/cro/page.tsx:488` |
| **What If** | **DEFERRED-INTEGRATION** — no module exists | contract test + fixtures only |
| **Project Planner** | **Excluded, and does not exist** | recorded as the PB-007 finding |

Scope defaults to *this analysis*, expandable to selected results or the whole investigation where the source module
supports it. A greeting or a failed/incomplete answer is not exportable and the button says so.

### 3.4 The authoring runtime — why a second path, and what it is

`backend/llm/base.py` states its own constraints: one method, schema-constrained, "it never asks for prose that will
be parsed into a decision", and an explicit "Why no streaming". That contract is exactly what makes the analytical
path trustworthy and it must not be loosened. Long-form drafting, editorial revision, server-side code execution and
document Skills cannot travel through it. So Playbook gets a **second, clearly separated runtime** that reuses the
configuration, telemetry, redaction and cost machinery but not the single-shot structured primitive.

`backend/playbook/provider.py` — `AuthoringProvider`, over the `anthropic` SDK:

- `messages.create` with `container={"skills":[{"type":"anthropic","skill_id": …,"version":"latest"}]}` and
  `tools=[{"type":"code_execution_20260120","name":"code_execution"}, …custom tools]`.
  Anthropic skill ids available: **`docx`, `pptx`, `xlsx`, `pdf`**. No `anthropic-beta` header is required for any
  current code-execution tool version.
- Tool-use continuation loop with `stop_reason == "pause_turn"` handling, container reuse by `container.id`
  (checkpointed after ~5 min idle, 30-day expiry — treated as expirable, never as durable storage).
- Streaming, cancellation, bounded retries with backoff, timeouts, provider refusal states, expired
  execution/file-resource recovery.
- Generated files arrive as `file_id` inside `bash_code_execution_tool_result`; bytes are pulled with the Files API
  (`GET /v1/files/{id}/content`) and written to durable storage **before** the job is marked complete. Only
  skill/code-execution-created files are downloadable, which is exactly what we need.
- Source files reach the container as `container_upload` blocks after a server-side Files API upload with
  `expires_in_seconds` set; text PDFs additionally go as `document` blocks with `citations.enabled` so we get real
  source locators back.

`backend/playbook/roles.py` adds one role to the existing mechanism: `AI_AUTHOR_MODEL`, `AI_AUTHOR_EFFORT`,
`AI_TIER_AUTHOR`, falling back `AUTHOR → AI_ANALYST_MODEL → AI_MODEL → provider default`. **No model id is written in
code** — `backend/llm/roles.py`'s rule holds. A configured id the provider cannot serve produces an honest
configuration state, mirroring `AI_COMPLEX_UNAVAILABLE_POLICY`; there is no silent downgrade (PB-030).
`AI_PROVIDER=offline`, `DEMO_SAFE_MODE` and `CREDITPROBE_DEMO_MODE` are all honoured.

**The governing rule is preserved.** The model writes and explains; it does not produce figures. Numbers enter a
report from exactly three places: a persisted export snapshot, a parsed source cell/paragraph with a locator, or
`backend/playbook/calc.py` — a deterministic calculator (deltas, percent vs percentage-point vs basis point,
coverage ratios, probability-weighted ECL) that records provenance, rounding convention and denominator. After
drafting, a grounding pass modelled on `backend/analyst/session.py` §42 checks every numeric literal against the
evidence ledger; anything unsupported is removed and the removal recorded, never hidden.

### 3.5 Ingestion

`backend/playbook/ingest/` — `docx.py`, `pdf.py`, `sheets.py`, `pptx.py`, `roles.py`, `manifest.py`, extending the
lazy-import and explicit-`NEEDS_OCR` discipline of `backend/regulatory/extract.py`.

- **DOCX** — headings and hierarchy, paragraphs, tables, numbering, headers/footers, metadata; locators retained for
  section-level edits; template style preserved where the renderer supports it, with an honest note where it does not.
- **PDF** — text vs image-only pages distinguished; text, tables and page locators extracted; pages that matter but
  did not extract are sent as image blocks for vision rather than guessed at. OCR is unavailable in this repo and is
  declared unavailable rather than faked.
- **XLSX/CSV** — every relevant sheet, hidden sheets detected and reported, table ranges, headers, units, currencies,
  period labels, scenario columns; formulas *and* cached values distinguished, with a formula string never treated as
  a verified result; merged headings and numeric strings handled explicitly; macros and external workbook links
  refused, not executed.
- **PPTX** — slide titles, body text, tables, chart data where available, speaker notes, slide identifiers. No claim
  of having read an image that was never inspected.
- Every source gets a **completeness manifest**: what was read, what was skipped, and why. Evidence is never silently
  truncated.

### 3.6 Artifact generation, storage and validation

- **Primary path** — Anthropic document Skills + code execution, files retrieved and persisted.
- **Local deterministic path** — `backend/playbook/render/`: `docx.py` and `pdf.py` reusing
  `backend/reporting/writers.py`, `xlsx.py` reusing `backend/exports/results.py`, and a new `pptx.py` on
  **`python-pptx`** (a new runtime dependency; nothing in the repo can produce a PPTX today). Used for demo seeding
  (so seeding still makes no provider call), for offline mode, and as the validated fallback when a Skill output
  fails validation.
- **Capability registry** — `backend/playbook/capabilities.py` declares which formats each path supports.
  An unsupported request gets a truthful explanation, never a fabricated file.
- **Storage** — `<upload_dir>/playbook/{workspace}/{artifact}/{version}/`, index and bytes separate, exact bytes
  re-served, following `backend/reporting/store.py`.
- **Validation** — `backend/playbook/validate.py` parses every generated file back (python-docx, pypdf, python-pptx,
  openpyxl) and asserts expected sections, figures, tables and page/slide counts before anything is labelled ready.
  Failed validation blocks the "ready" label, preserves the previous valid version, and offers retry.
  Visual review (clipping, overlap, blank pages, unreadable labels) runs in
  `scripts/acceptance/verify_playbook_artifacts.py` with page rasterization (`pymupdf`, dev-only).
- **Lineage** — DOCX and its PDF share one report revision; a PPTX derived from it records the source revision and
  keeps its own history. Restoring an older version moves forward as a new revision. A stale `base_version_id`
  returns **409**, never a silent overwrite. A failed generation never replaces the latest good artifact.

### 3.7 API surface (`/api/v1/playbook`, following existing router conventions)

```
GET    /playbook/home                          composer state, recent workspaces, recent exports
GET    /playbook/workspaces                    paged
POST   /playbook/workspaces                    create (optionally with first message + attachments)
GET    /playbook/workspaces/{id}               thread, sources, artifacts, change sets
PATCH  /playbook/workspaces/{id}               rename
POST   /playbook/workspaces/{id}/messages      send; returns job; SSE at .../stream
GET    /playbook/workspaces/{id}/stream        text/event-stream: state | delta | tool | artifact | done | error
POST   /playbook/workspaces/{id}/sources       upload (multipart)
GET    /playbook/sources/{id}                  parse status + manifest
PATCH  /playbook/sources/{id}                  correct role / period
POST   /playbook/sources/{id}/retry
GET    /playbook/exports                       library: search, filter, sort, page
GET    /playbook/exports/{id}/revisions/{rev}  full preview payload
POST   /playbook/exports                       Export to Playbook (idempotent)
POST   /playbook/change-sets/{id}/decide       apply selected / apply all / reject
GET    /playbook/artifacts/{id}/versions
GET    /playbook/artifact-files/{id}/download  correct filename + MIME
GET    /playbook/artifact-files/{id}/preview
POST   /playbook/artifacts/{id}/restore/{ver}  forward-moving restore
GET    /playbook/jobs/{id}                     status
POST   /playbook/jobs/{id}/cancel
POST   /playbook/jobs/{id}/retry
GET    /playbook/capabilities                  supported formats + provider configuration state
```

Every route resolves a `Principal` and enforces authorization server-side — including the two reads. (Note for the
record: the existing `GET /playbooks` and `GET /playbooks/{id}` have *no* permission dependency at all and so bypass
`REQUIRE_LOGIN`; the new module will not repeat that, and the finding is reported rather than silently patched into
an unrelated module.)

### 3.8 Frontend

New: `src/app/playbook/page.tsx`, `src/app/playbook/[id]/page.tsx`, `src/app/playbook/library/page.tsx`,
and `src/components/playbook/`.

**Home order is exactly as specified**: PageHeader → composer (plus button on its lower-left, Send on the right) →
quick-prompt chips → **Recent Playbooks** → **Recent Exported Analyses**. Chips populate the composer and never
consume a generation.

Components: `PlaybookComposer` (extends the `src/components/ask/composer.tsx` behaviour — auto-grow, Enter sends,
Shift+Enter newline, duplicate-send guard — and adds the plus menu and attachment chips), `PlusMenu`,
`AnalysisPicker` (search, filters, sort, multi-select, preview drill-in whose Back preserves selection, scroll and
filters, plus a selected-items tray with a count), `AnalysisPreview`, `SourceCard`, `ThreadView`, `ArtifactCard`,
`VersionHistory`, `ChangeSetPanel` (numbered items, stable ids, checkboxes *and* chat both work), `FilesPane`,
`PreviewPane`, `NextStepChips` (state-aware, never mutating before the user acts).

Three pieces of net-new shared infrastructure, each with the repo's React-free-logic-plus-`node --test` discipline:

- `src/components/ui/dialog.tsx` — the accessible modal primitive the repo lacks, extracted from the `ShareDialog`
  pattern (focus trap, focus restoration, Escape, `role="dialog" aria-modal`).
- `src/lib/markdown.ts` — a small sanitising tokenizer (headings, emphasis, lists, tables, code, links) rendered to
  React elements. **No `dangerouslySetInnerHTML`, no new dependency**, which is also how PB-036's active-HTML case is
  satisfied by construction.
- `src/lib/stream.ts` — a React-free SSE parser plus a `useStream` hook. `src/lib/api.ts` today is purely
  request/response; the parser is added alongside it without disturbing `request<T>()`.

Styling uses the CreditProbe `--ipm-*` tokens (`src/app/globals.css`). `src/app/scorecard-validation/page.tsx` is
explicitly **not** the styling reference — it uses shadcn defaults (`bg-muted`, `text-foreground`, `text-destructive`)
that have no definition in `globals.css`. `src/components/ask/answer.tsx` is the reference.

Accessibility per §17: keyboard reach for composer, plus menu, picker, chips, change controls, thread navigation and
artifact actions; focus restoration after dialogs; non-colour-only status; draft retained when the picker is
dismissed; a failed attachment never rides along silently.

### 3.9 Jobs, security and configuration

- **Jobs** — `backend/playbook/jobs.py` registers kind `playbook_generation` with `backend/agentic/worker.py`.
  Idempotency key `(workspace_id, message_id)`; the queue's partial unique index on `(kind, key)` means a refresh or a
  double-click cannot create a second billable generation.
- **Untrusted evidence** — document text, cells, imported analyses and metadata are wrapped as delimited evidence with
  a standing rule that evidence is data, never instruction. Tools are allowlisted; the execution container has no
  internet by design; no credential ever enters it. **Client-supplied Anthropic `file_id`s are never accepted** — the
  Files API is workspace-scoped and Anthropic's own docs warn that a user-supplied file id would let one user read
  another's upload. Our source-id → file-id mapping stays server-side.
- **Upload validation** — extension *and* magic bytes, `MAX_UPLOAD_MB`, OOXML decompression-ratio ceiling, filename
  sanitisation and path-traversal refusal (reusing the `backend/regulatory/store.py` rules), parser timeouts,
  macro-enabled formats refused.
- **Feature flag** — the repo has no flag framework, only env booleans (`REQUIRE_LOGIN`, `DEMO_SAFE_MODE`,
  `CREDITPROBE_DEMO_MODE`). `PLAYBOOK_WORKSPACE_ENABLED` joins them in `backend/config.py`, gating router registration
  and surfaced through `GET /playbook/capabilities`. Turning it off leaves data intact and legacy routes working.

---

## 4. Isolated development and test environment

Git isolation is not database isolation. The plan is:

- **Scratch Postgres cluster** — Docker's daemon is unavailable here, but `/usr/lib/postgresql/16/bin/initdb` and
  `pg_ctl` are present. A cluster is created under the scratchpad and started on **port 55432**, with two databases:
  `creditprobe_playbook_dev` and `creditprobe_playbook_test`. Nothing ever touches a 5432 default.
  Documented in a committed `scripts/playbook_dev_env.sh`.
- **Storage isolation** — `UPLOAD_DIR` points at a scratch directory for dev; tests use `tmp_path`.
- **Secrets** — a local `.env` (already gitignored) holds `DATABASE_URL`, `SECRET_KEY` and `ANTHROPIC_API_KEY`.
  No key in code, fixtures, logs, screenshots, test output or Git. `backend/api/failures.py`'s existing scrubber and
  `backend/llm/telemetry.py`'s redaction cover the new paths too.
- **Dependencies** — `uv sync` (CI's own path; note `requirements.txt` carries neither pytest nor ruff — they live
  only in `pyproject.toml`'s dev group, and the `requirements-dev.txt` its comment references does not exist), plus
  `npm ci --prefix frontend`, plus `pip install playwright` for the browser scripts.
- **Data** — `alembic upgrade head`, then `scripts/generate_saudi_universe.py`, `scripts/build_retail_scorecards.py`
  and `scripts/build_corporate_universe.py`, so the demo exports come from real engine runs rather than invented rows.
- **Demo isolation** — seeding is a bootstrap step, idempotent and versioned, writing only rows stamped with the
  Playbook seed marker. `backend/demo/workspace.py::reset()` gains the new tables on the WORKSPACE side of its
  existing boundary; the GOVERNED PLATFORM side is untouched.

---

## 5. Milestones

Executed in order after approval, without asking for a "continue" between them.

**M0 — Safe foundation.** Confirm branch and base commit. Preserve `CREDITPROBE_PLAYBOOK_MASTER_SPEC.md` verbatim to
`docs/playbook/MASTER_SPEC.md` and this plan to `docs/playbook/IMPLEMENTATION_PLAN.md`; open `PROGRESS.md`,
`REQUIREMENTS_MATRIX.md`, `UAT_REPORT.md`, `INTEGRATION_NOTES.md`. Install dependencies, stand up the isolated
cluster, build the lakes. Decide and gate the `anthropic` SDK version (§7). Add `python-pptx`. Write migrations
`0032`/`0033` and apply them to the isolated database only. Define the export contract and the capability registry.

**M1 — One complete live vertical slice (before any UI polish).** Upload a real DOCX and XLSX → parse with locators →
one real `claude-opus-5` call with code execution and the `docx` + `pdf` Skills → retrieve `file_id`s via the Files
API → persist bytes → parse the DOCX back and assert its sections and figures → reopen the workspace → request a
scoped revision → confirm version 2 exists with a genuine content difference and version 1 intact.
This settles runtime and file-generation feasibility first. Evidence: request ids, model, usage, file hashes.

**M2 — Home and thread UX.** Exact home ordering; plus menu; uploads with status/remove/retry; SSE streaming with real
job milestones and stop/cancel; thread persistence across refresh and restart; files/preview pane; version access;
prompt chips; honest empty/loading/partial/permission-denied/unavailable-provider/unsupported-format states.

**M3 — Exported-analysis flow.** Shared contract and `ExportToPlaybook` component; hooks on Cockpit, Early Warning,
Scorecard Validation and Lenses; the searchable, previewable, multi-select library with selection surviving preview
navigation; immutable revision attachment; backend rejection of unexported and foreign-tenant ids; the What If
adapter contract and its explicitly deferred hook.

**M4 — Intelligent reporting.** Source-role recognition; period and scope reconciliation; the coverage matrix that
edits nothing; full no-template drafting; scoped editorial requests without a redundant approval loop; numbered
proposals with stable ids, dependency handling and partial approval; report-to-presentation; the deterministic
numerical checks and the grounding pass.

**M5 — Demo completeness.** Three complete resumable threads (IFRS 9 Committee Report; Application Scorecard Model
Development Report; Behavioral Scorecard Validation Report), each with ≥12 messages, ≥3 real input files, ≥4 exported
analyses, a gap/drafting exchange, a five-item proposal with partial approval, a generated report plus a genuine
revision with a visible change summary, a focused editorial request, real Word/PDF/PowerPoint outputs linked to the
messages that created them, and a natural continuation point. Plus ≥30 substantial exports — six each from Cockpit,
Early Warning, Scorecard Validation and Lenses executed through the real engine, and six What If exports carried
through the deferred adapter contract and labelled as such. All fixtures labelled Demo/synthetic, seeding idempotent
and isolated, and no provider call at seed time.

**M6 — Verification and hardening.** The eight required journeys in Playwright; every visible control exercised;
artifact parse-back and visual inspection; the security and failure cases; the live smoke suite; affected-module
regression; `scripts/check.sh` and `python -m scripts.quality_gates`; baseline comparison against `3855f9b` under the
same database and lake availability.

**M7 — Handoff.** Completed requirement matrix, unresolved blockers, reproducible run/seed/test commands, screenshots
and sample files, final commit, branch push. No merge, no deploy.

---

## 6. PB-001 to PB-045 — implementation and verification mapping

| ID | Implementation | Verification |
|---|---|---|
| PB-001 | branch `claude/creditprobe-playbook-plan-ky3m05`, base `3855f9b` | `PROGRESS.md`; `git log`; clean-tree check before each commit |
| PB-002 | `src/app/playbook/page.tsx` | `playbook_home.test.ts` (order assertion on the layout model); browser journey 1 |
| PB-003 | `components/playbook/plus-menu.tsx`, `analysis-picker.tsx` | unit + journey 2 |
| PB-004 | `POST /playbook/workspaces/{id}/sources`, `backend/playbook/ingest/` | `tests/playbook/test_upload.py`; journey 3 |
| PB-005 | `backend/playbook/authz.py` + `analysis_exports` gate | `test_export_boundary.py` (direct API attach of an unexported id → 403/404); journey 2 |
| PB-006 | `backend/exports/playbook_contract.py`; hooks on 4 modules | `test_playbook_contract.py`; per-module browser checks; What If = DEFERRED-INTEGRATION |
| PB-007 | no Project Planner exists; Projects untouched | `test_project_surfaces_unchanged.py`; route crawl diff |
| PB-008 | unique `(export_id, content_hash)`; revision lineage | `test_export_idempotency.py` |
| PB-009 | picker + lifted `matching()` | `analysis-picker.test.ts`; journey 2 (preview 3, keep selection) |
| PB-010 | `GET /playbook/exports/{id}/revisions/{rev}`, `AnalysisPreview` | `test_export_preview_payload.py`; journey 2 |
| PB-011 | `playbook_attachments` mixed kinds | `test_mixed_attachments.py`; journey 3 |
| PB-012 | `ingest/roles.py`, period reconciliation | `test_source_roles.py`, `test_period_conflict.py` |
| PB-013 | `backend/playbook/coverage.py` | `test_coverage_matrix.py` (known missing topic); journey 3; asserts no artifact written |
| PB-014 | `backend/playbook/calc.py` + grounding pass | `test_calc_oracle.py` against the §14 ECL fixture (20.90 → 22.77, +1.87, ≈+8.95%); pp/bps/percent cases |
| PB-015 | `backend/playbook/author.py` no-template path | `test_no_template_report.py`; journey 4; asserts missing evidence named, tests not invented |
| PB-016 | `playbook_change_items.stable_id`, `POST /change-sets/{id}/decide` | `test_partial_approval.py`; journey 3 (apply 1–3, exclude 4–5, verify content) |
| PB-017 | scoped-edit path, no re-approval | `test_scoped_edit.py` (facts, risk severity, unrelated sections invariant); journey 5 |
| PB-018 | export → section/table insertion | `test_insert_analysis.py` (editable table, not a link) |
| PB-019 | `render/pptx.py` + skill path | `test_report_to_deck.py`; parse-back of editable text/tables; journey 5 |
| PB-020 | generation + `playbook_artifact_files` + download | `verify_playbook_artifacts.py`; journey 1 and 5 |
| PB-021 | `render/xlsx.py`, capability registry | `test_capabilities.py` (supported → workbook; unsupported → truthful refusal) |
| PB-022 | immutable versions, forward-moving restore | `test_versions.py`; journey 5 |
| PB-023 | `base_version_id` check → 409 | `test_stale_base.py`; journey 6 |
| PB-024 | Postgres persistence throughout | `test_thread_persistence.py`; journey 1 (refresh + restart) |
| PB-025 | `backend/playbook/seed.py` | `test_seed_threads.py` (message counts, real files, genuine revision diffs); journey 1 |
| PB-026 | seed exports | `test_seed_exports.py` (≥30, ≥6/module, no duplicate content hashes) |
| PB-027 | `fixtures/ecl_oracle.py`, all figures derived in code | `test_seed_reconciliation.py` across analysis, chat, DOCX, PDF, deck, workbook |
| PB-028 | idempotent versioned seeding; `reset()` extension | `test_seed_idempotency.py` (re-run creates nothing, preserves edits) |
| PB-029 | live continuation of a seeded thread | live smoke: new prompt absent from fixtures, real request id |
| PB-030 | `backend/playbook/roles.py`, no id in code | `test_no_silent_downgrade.py`; live smoke asserts the served model |
| PB-031 | provider status surface | `test_provider_states.py` (missing key, bad model, error, limit); journey 6 |
| PB-032 | chunk index, retrieval, completeness manifest | `test_retrieval_manifest.py` (no silent truncation) |
| PB-033 | locators + assumption/recommendation separation | `test_locators.py`, `test_claim_kinds.py` |
| PB-034 | `NextStepChips` from persisted state | `next-steps.test.ts`; journey 5 (no mutation before action) |
| PB-035 | visual-choice rule | `test_no_gratuitous_chart.py` (writing-only and checklist requests) |
| PB-036 | upload validation + injection corpus + `markdown.ts` | `test_upload_security.py`, `test_prompt_injection.py`; journey 7 |
| PB-037 | server-side authz on every route | `test_authz_matrix.py` (foreign tenant, direct download, direct API); journey 7 |
| PB-038 | queue idempotency, cancel, retry | `test_job_idempotency.py`; journey 6 (refresh mid-flight, double send) |
| PB-039 | failure preserves last good version | `test_failure_recovery.py`; journey 6 |
| PB-040 | every control | `playbook_browser_acceptance.py` control audit + keyboard/focus at 1366×768 |
| PB-041 | parse-back + rasterized visual review | `verify_playbook_artifacts.py` |
| PB-042 | regression | `scripts/check.sh`, `quality_gates.py`, baseline diff vs `3855f9b` |
| PB-043 | fresh non-seeded prompts | live suite, reported separately from mocked |
| PB-044 | `docs/playbook/INTEGRATION_NOTES.md` | contract test for the What If adapter + payload example |
| PB-045 | `docs/playbook/UAT_REPORT.md` + final summary | actual commit, counts by status, runnable UAT route |

---

## 7. Testing strategy and integration boundaries

- **Unit/integration (pytest)** — `tests/playbook/`, gated on `database_available()` exactly as the 59 existing
  modules are. Provider-dependent tests use a `ScriptedAuthoringProvider` in `tests/playbook/conftest.py`, mirroring
  `tests/analyst/conftest.py`. The autouse `_offline_ai` fixture keeps every non-`live` test off the network.
- **Live** — `tests/playbook/test_live_playbook_smoke.py` with `pytestmark = pytest.mark.live`, thin, with the real
  checks in `backend/validation/live_playbook_smoke.py` so the deployed container can run them. Bounded, synthetic
  evidence only, within configured usage limits. The five §21 quality tasks run here.
- **Frontend** — logic in React-free `.ts` siblings with `__tests__/*.test.ts` under `node --test`. Note that CI does
  not run `npm test`; `scripts/check.sh` does.
- **Browser** — `scripts/acceptance/playbook_browser_acceptance.py` covering journeys 1–8, and
  `scripts/acceptance/verify_playbook_artifacts.py` for parse-back and visual review. Both exit non-zero when
  Chromium is unavailable, following the existing rule that a run which did not happen is never a pass.
- **Reporting** — passed / failed / skipped / blocked / deferred-integration tracked separately. Skips are never
  counted as passes. Live results are never merged with mocked ones. Suspected baseline failures are re-run on
  `3855f9b` with the same dependency versions, database and lake availability before being called pre-existing.

**Integration boundaries recorded in `INTEGRATION_NOTES.md`:**

- **What If** — DEFERRED-INTEGRATION. The adapter contract, a payload example, a contract test and six labelled
  fixture exports ship; the exact hook a future What If module must call is named. No claim of live integration.
- **Project Planner** — does not exist; nothing added, nothing to regress.
- **Monitoring Playbooks** — unchanged. Its two unauthenticated read endpoints are reported, not silently altered.
- The `/documents` placeholder gains a pointer to the new workspace and is otherwise left alone.

---

## 8. Genuine blockers and prerequisites

| # | Blocker | Resolution |
|---|---|---|
| 1 | **`ANTHROPIC_API_KEY` absent** — unset in this session, no `.env` present. `api.anthropic.com` is reachable (returns 401, so the network is open, not blocked). CreditProbe's runtime credential is a separate concern from my Claude Code session. | You supply it through the environment's secret mechanism. Until it lands, live generation is reported **BLOCKED**, never PASS, and all other work proceeds. |
| 2 | **Nothing is installed or running** — no `.venv`, no Python deps, no `frontend/node_modules`, no database, no `data/analytics/` lake, no `.env`. Docker's daemon is unavailable. | M0 installs via `uv sync` + `npm ci`, stands up the scratch Postgres 16 cluster on port 55432 with `initdb`, and builds the lakes. Needs your approval to execute. |
| 3 | **`python-pptx` is a new runtime dependency** — no PPTX capability exists anywhere in the repo, and PB-019/PB-020 require one. | Added in M0 with the existing document libraries. `pymupdf` added dev-only for page rasterization in the acceptance script. |
| 4 | **`anthropic` SDK is pinned at `0.112.0`; current is `1.4.0`.** Agent Skills exist from 0.71.0 via the beta namespace, but GA `client.files` / `client.skills` and the `container` parameter's GA shape need ≥1.2.0. | Bump to `anthropic==1.4.0` in M0, gated on re-running `tests/llm`, `tests/analyst`, `tests/orchestration`, `tests/agentic` before and after. If the bump breaks the analytical path, the SDK stays at `0.112.0` and the Playbook runtime uses `client.beta.*`. Both outcomes recorded. |
| 5 | **`requirements.txt` cannot run the test suite** — pytest and ruff live only in `pyproject.toml`'s dev group, and the `requirements-dev.txt` its comment references is missing. | Use `uv sync`, as CI does. Reported, not silently worked around. |
| 6 | **Scale.** 45 acceptance criteria, a new runtime, a new module, 12 tables, three complete seeded threads and 30+ substantial exports. | Driven in the M0→M7 order with the live vertical slice first, committing per milestone and updating `PROGRESS.md` so a compaction or interruption resumes from the first incomplete item rather than restarting. |

---

## 9. Exact actions awaiting your approval

On approval, in this order:

1. Confirm branch and base commit; write `docs/playbook/MASTER_SPEC.md` (verbatim), `IMPLEMENTATION_PLAN.md`,
   `PROGRESS.md`, `REQUIREMENTS_MATRIX.md`, `UAT_REPORT.md`, `INTEGRATION_NOTES.md`.
2. `uv sync`; `npm ci --prefix frontend`; `pip install playwright`; add `python-pptx` and the SDK decision to
   `pyproject.toml` + `requirements.txt`.
3. `initdb` the scratch cluster on port 55432; create `creditprobe_playbook_dev` and `creditprobe_playbook_test`;
   write a local gitignored `.env`.
4. `alembic upgrade head` on the isolated database; build the three data universes.
5. Baseline test run on `3855f9b` under these exact conditions, recorded for later comparison.
6. Write migrations `0032` and `0033`; apply to the isolated database.
7. Build and prove the M1 live vertical slice end to end.
8. Continue M2 → M7 as above, committing per milestone, then push **only** this branch. No PR, no merge, no deploy.

## Verification

The work is proven, not asserted, by: the M1 live slice with real request ids, model, usage and file hashes;
`tests/playbook/` under pytest against the isolated Postgres; `node --test` for the frontend logic modules;
`scripts/acceptance/playbook_browser_acceptance.py` driving real Chromium through journeys 1–8 with real downloads;
`scripts/acceptance/verify_playbook_artifacts.py` parsing every generated DOCX/PDF/PPTX/XLSX back and rasterizing
pages for visual review; `scripts/check.sh` and `python -m scripts.quality_gates`; and a baseline comparison against
`3855f9b` with identical dependency, database and lake availability.

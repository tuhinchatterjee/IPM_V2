# Target baseline — what this candidate was built from

## The application

| | |
|---|---|
| Repository | `github.com/tuhinchatterjee/IPM_V2` |
| Baseline commit | `c0db151f62c34e84b4f7df5faf81e5c9b0c9f647` — **the commit the demo actually runs** (`claude/funny-dirac-6n8f0o`, 2026-09-14) |
| Candidate branch | `claude/modest-rubin-cm037o`, started from that commit |
| Profile | `CREDITPROBE_PRODUCT_PROFILE=retail` (`backend/retail/profile.py::is_retail`) |
| Frontend / API | 5328 / 8328 (`.env.retail.example`, `launchers/retail/start-retail.command`) |
| Data | `DATA_ANALYTICS_DIR=data/retail/analytics`, `METADATA_DIR=metadata/retail` |
| Backend entry | `uvicorn backend.api.main:app`, every router under `/api/v1` |
| Auth | default-deny middleware on `/api/v1` (`backend/api/main.py`), session cookie, `Principal(user_id, role)`; roles ADMIN / DATA_STEWARD / ANALYST / VIEWER. **No tenant concept.** |
| Cockpit today | the home page `/` (`frontend/src/app/page.tsx`): greeting, Ask composer, Requires attention, Early warning strip, recent investigations. Asking opens `/investigations/{id}`. |
| Current analyst path | `backend/api/routers/ask.py` → `backend/analyst/route.py`: run-key recall, then a catalogue answer with no model call, then a provider session, with a deterministic planner fallback. |

The launcher installs nothing, migrates nothing and generates no data: it checks
`.venv`, checks the manifest, runs `scripts/check_retail_ready.py`, guards its
two ports without stopping anything, then starts the API and `next dev`.

## The published domain this Cockpit reads

Five Data Builder domains (`backend/retail/domains.py`): **Cockpit Data**, Early
Warning Data, Early Warning Score, Credit Scorecard Data, What-If Analysis Data.
Only the first is the Cockpit's analytical source. The other four are a column
view, a computed model output, a column view and a column view of the same
canonical book, and this integration reads none of them.

Cockpit Data publishes one dataset, `retail_facility_month`, described in
`COCKPIT_DATA_CONTRACT.md`.

## Reconciled against the running demo

The Mac reports the demo serving from `/Users/tuhinchatterjee/Desktop/IPM_V2`
at `c0db151f`, on a detached HEAD. That is **not another line**: it is an
ancestor of `861f5707` on the same branch, which is 37 commits ahead of it and
0 behind. The candidate was rebased onto it, so the cutover delta is the
Cockpit integration and nothing else.

What those 37 commits change, in the areas this integration touches:

| Area | Change |
|---|---|
| Retail launcher, `.env.retail.example`, `check_retail_ready.py` | none |
| Frontend shell and home (`app/page.tsx`, `app/layout.tsx`, `components/layout/**`) | none |
| Auth and principal (`api/auth.py`, `api/permissions.py`, `db/models.py`) | none |
| Backend API | +1,376/−29 across `retail.py`, `scorecard_validation.py`, `workspace.py`, `ask.py`, `main.py` (two startup warm-up threads; no router, auth or middleware change) |
| Data Builder | `backend/retail/domains.py` +60/−1 — staleness stamping for the four derived views; the canonical dataset and the Cockpit Data entry untouched |
| Cockpit routes and components | `prompt_bank.py` +399, `story_router.py` +254, `ask.py` +73, `composer.tsx` +6 |

The published book is identical at both commits — manifest, contract,
catalogue, generator and schema are byte-identical — and the only
data-vocabulary file that differs, `taxonomy.py`, differs solely in
`resolve_product()`'s word-boundary matching. The product codes, labels,
secured set, DPD buckets and score bands are unchanged, so **the adapter and
its oracles are invariant across the 37 commits**, which was verified by
re-running them on the rebased tree.

Whether to move the demo itself to its branch tip is a separate decision, on
its own merits, and is not part of this integration.

### An untracked directory in the live worktree

`data/cockpit_agentic_v3/` is not produced by anything the demo runs:
`backend/cockpit_agentic` and `backend/cockpit_v4` are both absent at
`c0db151f`. It is the V3 lake root — `store.root()` is
`analytics_dir.parent / "cockpit_agentic_v3"`, which resolves to exactly that
path under the DEFAULT `data/analytics` rather than the retail profile's
`data/retail/analytics` — created by `store.py`'s own `mkdir` on a write path
that requires `COCKPIT_AGENTIC_V3=true`. So a Cockpit branch was checked out in
that worktree at some point and a seed ran there without the retail profile.
Inert: untracked, unread by any retail code path, and outside everything this
integration touches.

## What was verified here, and how

- The committed manifest was **rebuilt from source** in this container
  (`scripts/build_retail_demo.py`, Python 3.12.3, pandas 3.0.3) and reproduces
  the published book exactly: identical `manifest_hash`
  (`3268b725456df9c4…`), identical `content_hash` for all 25 months, and a
  byte-identical data contract. Only `build_seconds` differs.
  So the book analysed here is the book the installation publishes.
- Every column the adapter maps was checked to exist in the published contract
  before it was mapped.

## What is still unverified, and needs the Mac

- The launcher on the Desktop (`START_CREDITPROBE_RETAIL_DEMO.command`) and what
  it resolves to. This baseline is the branch, not that file.
- The live registry: whether the running demo's
  `metadata/retail/retail_dataset_manifest.json` carries the same
  `manifest_hash`. If it does not, the mapping stands and every oracle is
  re-frozen against those bytes before any figure is reported.
- Which credential variable the retail installation holds, and whether
  `REQUIRE_LOGIN` is on there.

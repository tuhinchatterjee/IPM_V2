# Target baseline — what this candidate was built from

## The application

| | |
|---|---|
| Repository | `github.com/tuhinchatterjee/IPM_V2` |
| Baseline commit | `861f570746b2a7df4049486554163a32e9dafc95` (`claude/funny-dirac-6n8f0o`, 2026-09-17) |
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

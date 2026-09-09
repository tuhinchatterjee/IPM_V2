# Playbook — integration notes

What this branch integrated, what it deliberately did not, and what a later
branch must do. Nothing here claims a live integration that was not exercised.

## Module boundary

Export to Playbook belongs to Cockpit, Early Warning, What If, Scorecard
Validation and Lenses. **Project Planner is excluded** — and on this baseline
there is nothing to exclude: `grep -rniI "project planner|projectPlanner"` over
`frontend/src/` returns zero hits, and "planner" in this codebase means the *ask*
planner (`backend/orchestration/planner.py`). Projects (`/projects`) is a
different capability and is untouched.

## Baseline hooks (built on this branch)

| Module | Surface | State |
|---|---|---|
| Cockpit | `ActionStrip` in `src/components/ask/answer.tsx` — inherited by every surface rendering an `AnswerBlock` | see requirement matrix |
| Early Warning | `src/app/early-warning/page.tsx`, `signals/page.tsx`, `src/components/early-warning/story.tsx` | see requirement matrix |
| Scorecard Validation | `src/app/scorecard-validation/page.tsx` | see requirement matrix |
| Lenses | `src/app/lenses/[lensId]/page.tsx`, `src/app/lenses/cro/page.tsx` | see requirement matrix |

## DEFERRED-INTEGRATION: What If

**There is no What If module on this baseline.** Evidence gathered at the base
commit `3855f9b`:

- `frontend/src/`: one hit for "what if", a prose comment in
  `src/app/trace/[runId]/page.tsx`. No route, no page, no component.
- `backend/`: no router. `backend/stress/` contains only an empty `__init__.py`.
  The adjacent capabilities are Stress Testing (`stress_scenarios` table,
  `backend/stress_lab.py`, `backend/scenarios.py`, `src/app/stress/page.tsx`) and
  the Trace "Ask / Modify Trace" panel — neither is named What If, and neither
  was chosen to impersonate it.

Per the decision recorded for this branch, What If is **DEFERRED-INTEGRATION**:
a versioned adapter contract, a contract test and labelled fixture exports ship
here; no live cross-module integration is claimed. The exact hook a future What
If branch must call is documented below once the contract lands.

## Preserved: the existing Playbooks feature

`docs/PRODUCT_SPEC.md` §9 defines a Playbook as a *standing instruction that
runs*. That feature is live and is **kept whole**: `/playbooks`,
`/api/v1/playbooks`, `backend/services/playbooks.py`, tables `playbooks` and
`playbook_runs`, `tests/services/test_lenses_and_playbooks.py`, its demo seed and
its notification deep-link. The new chat-first workspace is a separate route,
package, API prefix and table set. Its nav label becomes "Monitoring Playbooks"
so the two are distinguishable on screen; `href`, API and data are unchanged.

## The What If adapter contract

A future What If module integrates by producing one `Snapshot` and posting it.
Nothing else changes: no Playbook code, no schema, no migration.

**The hook.** `POST /api/v1/playbook/exports`, or in-process
`backend.playbook.library.create(session, scope, snapshot)`.

**The payload**, from `backend/exports/playbook_contract.py`:

```python
from backend.exports import playbook_contract as contract

snapshot = contract.Snapshot(
    source_module=contract.WHAT_IF,          # already declared, already accepted
    title="Downturn sensitivity, Q2 2026",
    question="What happens to ECL if the downturn scenario weight doubles?",
    narrative="…what the scenario run found, in prose…",
    tables=[contract.Table(
        id="scenario_comparison",
        title="ECL by scenario weight",
        columns=["Weighting", "ECL"],
        rows=[["60/15/25", "22.77"], ["45/15/40", "27.31"]],
        units={"ECL": "SAR million"},
    )],
    scope={"reporting_period": "Q2 2026", "currency": "SAR",
           "scenario_version": "v4.2"},
    assumptions=["Scenario definitions unchanged."],
    limitations=["Second-order effects are not modelled."],
    source_ref={"scenario_id": 41, "run_id": 9012,
                "link": "/what-if/41"},
    source_revision="4",
    reporting_period="Q2 2026",
    insight="Doubling the downturn weight raises ECL by SAR 4.54 million.",
)
```

**What the contract already guarantees.** `scenario_id` is in the identity keys,
so two exports of the same scenario deduplicate and a changed scenario makes a
new revision. `snapshot.validate()` refuses an incomplete run. Nothing in
Playbook needs to learn about What If — it is in `SOURCE_MODULES` today and
absent from `IMPLEMENTED_MODULES`.

**What the future branch must do.**

1. Render `ExportToPlaybook` on its completed scenario results:
   `frontend/src/components/exports/export-to-playbook.tsx`, with a `build()`
   returning the payload above. Add the builder beside the four in
   `frontend/src/lib/playbook-export.ts` and a test beside theirs.
2. Add `WHAT_IF` to `IMPLEMENTED_MODULES` in
   `backend/exports/playbook_contract.py`. That constant is what the library API
   reports as implemented, and the test
   `test_what_if_is_in_the_contract_but_not_implemented_here` will fail until it
   is moved — deliberately, so the change cannot be forgotten.
3. Replace the six labelled fixtures in `backend/playbook/seed_exports.py`
   (`_what_if`) with real exports, and drop `WHAT_IF_CAVEAT`.
4. Update `docs/playbook/REQUIREMENTS_MATRIX.md`: PB-006 moves from
   "four modules verified, What If deferred" to all five.

**What is already tested.** `tests/playbook/test_export_library.py` asserts that
a What If snapshot validates against the contract and produces a content hash,
so the adapter is exercised now rather than being an untested promise.

## Feature configuration

Playbook follows the repository's existing convention — environment booleans read
through `backend/config.py` — rather than introducing a flag framework the
codebase does not have.

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Required for generation. Without it, workspaces, sources and files stay readable and the composer says configuration is required. |
| `AI_AUTHOR_MODEL` | The authoring model. Falls back to `AI_ANALYST_MODEL`, then `AI_MODEL`, then the provider default. Never silently downgraded. |
| `AI_AUTHOR_EFFORT` | `low` / `medium` / `high`, where the provider supports it. |
| `AI_TIER_AUTHOR` | Cost-report weighting only. Defaults to `deep`. |
| `AI_PROVIDER=offline` | Turns generation off entirely; the demonstration stays browseable. |
| `PLAYBOOK_MAX_TURNS`, `PLAYBOOK_MAX_OUTPUT_TOKENS`, `PLAYBOOK_TIMEOUT_SECONDS` | Bounds on one authoring run. |
| `UPLOAD_DIR` | Where sources and artifacts are stored, under `<upload_dir>/playbook`. |

## Migration and rollout

Three additive migrations, `0032`, `0033` and `0034`, on top of head `0031`.
They create fourteen tables and alter nothing existing, so `alembic upgrade
head` is safe on a populated database and `downgrade` drops only what they
created.

`0034` adds `playbook_job_events`, the durable stream. It grows during a
generation and is dead weight afterwards, so a deployment that runs for a long
time will want to prune it — rows for jobs finished more than a few days ago
can be deleted without touching anything else, because the answer itself lives
in `playbook_messages` and `playbook_artifact_versions`, never here. No pruning
job ships on this branch; the table is named here so that decision is taken
deliberately rather than discovered.

Seeding is bootstrap step **L** (`scripts/bootstrap_demo.py --step playbook`),
idempotent, and makes no provider call. The Playbook tables are on the WORKSPACE
side of `backend/demo/workspace.py`'s reset boundary, so a demo reset rebuilds
them and never touches the governed platform.

## Streaming, for whoever deploys this

The generation runs in a background thread inside the API process, and the SSE
endpoint reads a database table rather than that thread. Three consequences a
deployment needs to know:

* **It works behind more than one worker.** A connection served by process B
  can follow a generation running in process A, because the log is in Postgres
  and the in-process wake-up is only an optimisation. What does not survive is
  the process itself: a restart mid-generation loses the run, and a reader is
  told so rather than left hanging.
* **Proxies must not buffer it.** The response sets `X-Accel-Buffering: no` and
  `Cache-Control: no-store`. A proxy that buffers anyway turns streaming into
  one long pause followed by everything at once — the feature will look broken
  rather than absent.
* **A connection is held open for the length of a generation.** Minutes, not
  seconds. Idle timeouts on any intermediary need to exceed that; the server
  sends a keep-alive comment every 15 seconds so a silent tool call is
  distinguishable from a dead connection.

Moving the work onto the existing durable agent queue (`backend/agentic/`) is a
change of who calls `service.run_generation` and nothing else — the job row, its
idempotency key and its event log are already what a queued worker would use.

## Running it

```bash
# database (isolated cluster on 55432 in development)
.venv/bin/python -m alembic upgrade head

# the demonstration
.venv/bin/python scripts/bootstrap_demo.py --step playbook

# the application
.venv/bin/python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
npm --prefix frontend run build && npm --prefix frontend run start

# verification
.venv/bin/python -m pytest tests/playbook
.venv/bin/python scripts/acceptance/playbook_browser_acceptance.py
.venv/bin/python scripts/acceptance/verify_playbook_artifacts.py
.venv/bin/python scripts/playbook_live_slice.py     # needs ANTHROPIC_API_KEY
```

Then open `http://127.0.0.1:3000/playbook`.

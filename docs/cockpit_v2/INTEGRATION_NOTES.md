# Cockpit Intelligence V2 — integration notes

Brief §9. Every shared file this branch touches, what it does with the switch
off, and what a reviewer should look at first.

## 1. The switch

`COCKPIT_INTELLIGENCE_V2`, read once in `backend/config.py` into
`settings.cockpit_intelligence_v2`, **default false**. A second setting,
`COCKPIT_V2_NAMESPACE` (default `cockpit_v2`), is what the destination guard
checks writable paths against.

Nothing outside `backend/cockpit_v2/` and the call sites below reads either.

## 2. Shared files changed, and the flag-off behaviour of each

| File | Change | With the switch off |
|---|---|---|
| `backend/config.py` | two new settings with safe defaults | both defaults are inert |
| `backend/orchestration/interpreter.py` | `Narrative.prose_source` and `prose_fallback_reason`, defaulting to `"deterministic"` and `""` | two extra keys in the payload; every existing key unchanged. `test_the_narrative_contract_keeps_its_historical_default` holds it |
| `backend/orchestration/executor.py` | `Investigation.cockpit_v2`, omitted from `to_dict()` when empty | the serialised run is byte-identical to the base commit |
| `backend/api/routers/ask.py` | calls `cockpit_v2.answer_for`; adds `GET /ask/cockpit-v2/diagnostics` | `answer_for` returns `None` on its first line and `_ask` runs exactly as before. The diagnostics route returns `{"cockpit_intelligence_v2": false}` |
| `backend/api/routers/hierarchy.py` | `start_thread` calls the same helper | `apply` returns `False` and the original branch runs |
| `backend/services/threads.py` | `ask` calls the same helper | as above |
| `backend/api/main.py` | registers the V2 tools at startup | `install()` returns `[]` and the registry is untouched. `test_no_tool_is_registered` holds it |
| `frontend/src/lib/api.ts` | optional `cockpit_v2`, `prose_source`, a `turns` argument and one client method | all optional; no existing call changes |
| `frontend/src/components/ask/answer.tsx` | renders the V2 block **only** when `run.cockpit_v2` is present | falls through to the existing `KeyInsight` + `AnalystReading` layout |
| `frontend/src/app/page.tsx` | fetches diagnostics and renders the badge | the badge returns `null` and the fetch failure is swallowed |

New files, all inert when the switch is off:
`backend/cockpit_v2/*` (18 modules), `scripts/build_cockpit_v2_demo.py`,
`frontend/src/components/ask/cockpit-v2.tsx`, `tests/cockpit_v2/*`,
`tests/evals/cockpit_v2/*`.

## 3. One helper, three call sites

`backend/cockpit_v2/integration.py` is the only bridge. It exists because the
first browser run found the defect that mattered most: **`POST /ask` had been
wired and the screen had not.** The Cockpit's own composer calls
`POST /investigations`, so the browser still showed the base build's
clarification about horizons while the API answered correctly.

`apply` mutates the **`Investigation` object before it is serialised**, not a
response dict at one call site. That is deliberate: the payload has to reach
the stored message, the thread's memory, the API response and the screen, and a
dict amended at the router survived the response and vanished on reload.

When V2 answers it also **settles the turn**: `status` moves off
`needs_clarification`, the clarification is dropped, and the deterministic
path's "stopped to ask" note and objective counter are cleared — otherwise the
screen showed an amber "CreditProbe stopped to ask" banner directly above a
complete answer.

## 4. Backward compatibility

* No public field was removed or renamed. Two were added to `Narrative`, one to
  `Investigation`, and the last is omitted when empty.
* `AskIn` gains an optional `turns` list, bounded at 12 entries.
* `GET /api/v1/ask/cockpit-v2/diagnostics` is new and additive.
* The frontend types are optional throughout, so a build against a backend
  without V2 compiles and runs unchanged. `npx tsc --noEmit` is clean.

## 5. What was deliberately NOT done

* **No shared engine was copied.** V2 reuses `Investigation`, `Narrative`, the
  Trace graph, the executor, the analyst tool registry, `Principal` and the
  Data Access Layer. It is not a code island.
* **No other feature was switched on.** The tools, the answer path and the
  scope apply to the Cockpit only. Early Warning, What-if, Scorecards, Planner,
  Lenses and Playbook are untouched, and their access policies are unchanged.
* **No other branch was merged or cherry-picked.**
* **The existing router was kept.** `backend/analyst/route.py` — run-key cache,
  class-A catalogue path, analyst, deterministic fallback — is a working
  component the old plan did not mention, and brief §2.1 says not to
  reimplement one. It is extended, not replaced.
* **`_CAUSAL` in `backend/orchestration/evidence.py` was left alone.** V2 has
  its own licensing rule in `backend/cockpit_v2/evidence.py`; changing the
  shared regex would change behaviour for every other feature.
* **`MAX_PLANNING_TURNS` in `backend/analyst/safety.py` was left alone.** V2
  has its own class-dependent budgets in `backend/cockpit_v2/budgets.py`.
  Widening the shared constant would widen it for every feature.

## 6. Conflict surface

The shared files above are the whole conflict surface, and the edits in each
are small and localised — a dataclass field, an optional call, one render
branch. `backend/api/routers/ask.py` carries the largest change (about 60
lines) and `backend/services/threads.py` the most delicate (one early-return
branch inside `ask`).

`data/analytics/` and `metadata/catalog.json` are gitignored and are **not**
written by this branch at all: every destination is redirected into the V2
runtime directory.

## 7. Rollback

Turn the switch off. Nothing else is required: no migration to reverse, no
data to remove from a shared store, no catalogue entry to delete from the
repository. To discard the runtime as well:

```sh
pkill -f "uvicorn backend.api.main:app --host 127.0.0.1 --port 8100"
pkill -f "next start --port 3100"
su postgres -c "PATH=/usr/lib/postgresql/16/bin:\$PATH pg_ctl \
  -D /home/user/IPM_V2-cockpit-v2-runtime/pgdata stop"
rm -rf /home/user/IPM_V2-cockpit-v2-runtime
rm -f /home/user/IPM_V2/.env
```

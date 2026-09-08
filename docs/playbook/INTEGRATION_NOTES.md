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

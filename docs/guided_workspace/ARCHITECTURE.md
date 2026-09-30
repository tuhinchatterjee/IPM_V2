# Guided Risk Workspace — call and object map

The v3.1 specification changes how bankers experience CreditProbe, not the
analytical engine. This map fixes, before each phase's edits, which existing
component answers each need and where new code attaches.

## 1. One engine, several entrances

```
                ┌──────────── Advanced Cockpit (unchanged engine) ─────────────┐
 Ask box ──────►│ POST /runs → worker → Analyst (provider seam) → orchestrator  │
 NBQ chip ─────►│   execute_analysis → execute_tool → scenario/bridge.py        │
                └──────────────────────────────┬───────────────────────────────┘
                                               │ same objects
 What-If workspace ─► /workspace/scenarios ──► scenario/service.py ──► scenario/{cohort,spec,rules,delta,run,ml,userdefined,attribution}
 Scenario Library ──► /workspace/scenarios ───┘                          ▲
 Requires Attention ─► /workspace/issues ──► metric engine ─► catalog.open_session (DuckDB, book in use)
 Lenses / Monitoring ► /workspace/lenses ───► metric engine ─┘
 Every model call ───► backend/llm/exchange.py (passive recorder) ◄── AI Model Lab
```

* Portfolio arithmetic is only ever done by (a) the governed Cockpit executor,
  (b) the existing scenario engine, or (c) the governed metric engine whose SQL
  is a closed, reviewed template per metric id with bound parameters. No model
  output is persisted as dashboard logic.
* The book a workspace reads is `domain_resolver.scope_for(domain)` → the same
  release the Cockpit is serving (candidate when the What-If flag is on). A
  request can never name a release id (SEC03).

## 2. Shared governed objects (P2)

Stored in `workspace.sqlite3` beside the V4 state database, one generic
versioned table (`objects`) keyed by `(object_id, version)`, plus
`comments`, `shares`, `lens_observations`, `alert_events`, `inbox`.

| Kind | Identity / version rule | Key fields | Created by |
|---|---|---|---|
| `cohort` | new version on refresh-to-latest; never mutated | domain, release_id, fingerprint, period, predicate (typed filters), selection mode, entity/owner counts, EAD/ECL, membership_hash, predicate_hash, source object | grid selection, issue card, Early Warning card, Lens selection, chart lasso |
| `finding` | immutable | issue ref, evidence refs, statement, confidence, limitations, cohort ref | issue investigation, Cockpit answer |
| `investigation` | append-only path | thread_id, issue ref, cohort ref, breadcrumb steps, suggestions shown/clicked | issue "Investigate", NBQ chips |
| `scenario` | edit ⇒ new version; composed ⇒ new id with parents | components (typed rules), scope template/bound cohort, stage policy, composition policy, methods compatible, tags, status, lineage | library seed, workspace builder, composition, Cockpit chat |
| `scenario_result` | immutable | scenario id+version, cohort id+hash, baseline mode + parent result, methods, release/fingerprint, dual-scope decompositions, trace refs | scenario service execution |
| `lens` | edit ⇒ new version | metrics (ids+versions), visuals, layout, filters, drilldowns, refresh cadence, breach rules, audience | seed, prompt-to-Lens, Save-as-Lens |
| `lens_observation` | immutable, one per refresh | lens id+version, release/fingerprint, status, metric values, what-changed | refresh (manual/schedule/on-publication) |
| `metric` | versioned registry (code-seeded) | formula, numerator/denominator, unit, grain, population, null policy, direction, thresholds, dimensions, lineage | metric catalogue seed |
| `alert` | state machine NEW→ACTIVE→WORSENING→ACKNOWLEDGED→RESOLVED(/SUPPRESSED); events appended | rule id+version, lens id+version, observed, threshold, window, release, cohort, first/last seen | breach evaluation |
| `share` | immutable; comments attach to a version | object kind/id/version, from, to, message, permissions | Messages |

Every object carries `object_id, kind, version, owner, tenant, domain,
release_id, fingerprint, period, permissions, created_at, updated_at,
lineage, trace_refs, content_hash`.

## 3. Seams per phase

| Phase | New code | Existing code reused | Protected edits expected |
|---|---|---|---|
| P1 exchange trace | `backend/llm/exchange.py`, `openai_compatible.py`, `workspace/exchange_api.py`, Trace/Model Lab pages | provider seam, run events, artifacts | worker.py (bind), app.py (mount), cockpit trace page (link) |
| P2 objects | `workspace/store.py`, `objects.py`, `objects_api.py` | cohort.freeze / selector | none |
| P3 guided Cockpit | `workspace/metrics.py`, `issues.py`, NBQ policy, guided components | attention_v2 evidence, `/attention/{id}/investigate`, POST /runs | cockpit-v4-home.tsx (mount guided panel) |
| P4 scenario library | `workspace/scenario_library.py`, composition | scenario/rules overlaps, spec canonical/digest | none |
| P5 What-If workspace | `workspace/grid.py`, `/what-if` page | selector, cohort.freeze | none (nav label is unprotected) |
| P6 method gate + decomposition | `scenario/service.py`, `workspace/decomposition.py` | delta/run/ml/userdefined/attribution | none expected (scenario/ is unprotected); bridge default fixed in place |
| P7 lineage/sharing | lineage in service; `messages_api.py` | collaboration notifications (read only) | none |
| P8–P10 metrics/lenses/monitoring | `metrics.py`, `lenses.py`, `monitoring.py`, scheduler seam | V4 worker thread model | none |
| P11 visuals | `components/viz/*` | — | none |

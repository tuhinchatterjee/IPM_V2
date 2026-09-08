# Cockpit Agentic V3 — baseline audit of the Cockpit V2 implementation

**Audited branch:** `claude/cockpit-intelligence-v2-mbb22o`
**Audited commit (base SHA of this work):** `83b39a602eb430444f46d08aca4e595522f3b53f`
  — *"Cockpit V2: state the gap alone, and evidence the flag-off path"*
**Working branch:** `claude/cockpit-agentic-v3-fhg4r0`, created as a fast-forward child of that
exact commit. `main` (`3855f9b`) is an ancestor of it, so nothing from `main` was lost and the V2
branch reference is untouched and remains the fallback / before-UAT baseline.
**Authoritative specification:** `docs/COCKPIT_AGENTIC_V3_MASTER_SPEC.md`
(`docs/COCKPIT_AI_V2_MASTER_SPEC.md` does not exist in this repository at any commit;
the supplied replacement prompt was installed under the V3 name as instructed.)
**Date:** 8 September 2026.

## 0. How this audit was produced

Read-only inspection of the checked-out tree at the base SHA: `backend/cockpit_v2/` (10,636 lines
across 21 modules), `backend/api/routers/ask.py`, `backend/api/main.py`, `backend/llm/`,
`backend/analyst/`, `backend/orchestration/` (~45,000 lines), `backend/services/threads.py`,
`backend/config.py`, `frontend/src/lib/navigation.ts`, `frontend/src/components/ask/`,
`tests/cockpit_v2/`, `tests/evals/cockpit_v2/`.

Baseline test evidence, run in this container before any code change:

```
$ .venv/bin/python -m pytest tests/cockpit_v2 -q
46 passed
```

Environment note: the repository pins `numpy==2.5.0` / `pandas==3.0.3`, which require Python ≥ 3.12.
The container's default interpreter is 3.11; the virtualenv used for all evidence in this work is
built on `/usr/bin/python3.13`. This is a container fact, not a repository defect.

## 1. Named findings the task asked for explicitly

### 1.1 The current deterministic answer path

`backend/cockpit_v2/answer.py` (2,084 lines), entered through
`service.answer()` → `answer.compose()`.

`compose()` reads the question with `understand.read()`, receives a `Request` carrying a set of
**output kinds drawn from a closed list of sixteen** (`understand.ALL_OUTPUTS`:
`scope_statement`, `ecl_factor_decomposition`, `pd_impact`, `composition`,
`movement_by_dimension`, `scenario_comparison`, `parameter_product_check`, `ratio_movement`,
`metric_history`, `rating_review`, `covenant_review`, `collateral_review`, `stage_review`,
`concentration`, `macro_dependency`, `definition`, `data_quality`), and dispatches each to a
**dedicated hand-written section builder** — `_decomposition_section`, `_pd_section`,
`_composition_section`, `_scenario_section`, `_scope_section`, `_definition_section`,
`_macro_section`, `_covenant_section`, `_collateral_section`, `_rating_section`, `_stage_section`,
`_concentration_section`, `_history_section`, `_data_quality_section`, `_movement_section`,
`_ratio_section`, `_parameter_product_section`.

Each section builder owns its own fixed methodology, its own table shape, its own chart shape and
its own prose skeleton. **This is precisely the "compulsory analytical template" the V3 spec
forbids** (§1.5, §7.6, §9.6). No model participates in choosing a method; `PROSE_DETERMINISTIC_V2`
is the marker stamped on the resulting prose.

### 1.2 The current analyst answer path

`backend/analyst/` — `route.py` → `session.py` (718 lines) → `tools.py` (1,651 lines).

`session.py` runs a genuine investigation loop (`for turn in range(1, max_turns + 1)`), but it is
**not a provider tool-use loop**. Its own module docstring states the design: `backend.llm` exposes
exactly one primitive, a schema-constrained `structured()` call, and the loop is built out of
repeated single-shot calls in which the model returns a *decision document*
(`{"action": "CALL_TOOL"|"ASK"|"ANSWER"|"CANNOT", ...}`). There are no `tool_use` / `tool_result`
content blocks, no preserved assistant blocks, and no multi-turn `messages` array.

This path is invoked from `/ask` **in parallel with** the deterministic path, as `body["analyst"]`,
and is explicitly skipped when Cockpit V2 has answered (`_analyst_view(..., skip=answered_by_v2)`).

### 1.3 Existing router logic

Three separate routers exist, none of which is a functionality-ownership gate:

| Router | File | Nature |
|---|---|---|
| Cockpit V2 output router | `backend/cockpit_v2/understand.py` (683 lines) | **Pure regex / keyword matching.** `_MOVEMENT_WORDS`, `_DECOMPOSITION_WORDS`, `_FACTOR_WORDS`, `_COMPOSITION_WORDS`, `_NOT_A_MOVEMENT`, `_DEFINITION_PATTERNS`, `_NO_CHART`, `_WANT_CHART`, `_LOADED_ASSERTIONS`. `read()` is a 330-line hand-written classifier. No model call. No language handling beyond English. No ownership question is ever asked. |
| Question-class router | `backend/analyst/classify.py` | Classifies a question for **cost metering**, not ownership. |
| Legacy plan router | `backend/orchestration/router.py`, `routing.py` | Routes into the 45k-line certified-analysis planner. Not Cockpit-scoped. |

**No component anywhere in the tree asks "is Cockpit the right owner of this question?"** A question
about EWS scores, a request to generate a new credit rating, or a request for a new stress shock is
answered by whichever section builder the keywords happen to select.

### 1.4 Current tool execution system

`backend/cockpit_v2/tools.py` (522 lines) registers **five canned analyses**, installed at app
startup by `backend/api/main.py:372`:

`decompose_ecl_factors`, `decompose_movement`, `decompose_ratio`, `metric_history`,
`list_certified_analyses`.

Every one is a fixed Python function with a fixed argument schema, a `MAX_ROWS = 50` cap and a
fixed output shape. There is **no SQL execution surface, no Python execution surface and no sandbox
of any kind**. A model can only select among five pre-authored analyses; it cannot author an
analysis. `backend/analyst/tools.py` is the analogous, larger canned-tool registry for the legacy
analyst.

### 1.5 Current thread state

Two unrelated mechanisms:

* **Client-carried turns.** `AskIn.turns: list[dict[str,str]] | None` — max 12 — the browser holds
  the transcript and passes it back. `service._previous()` reads the last turn to seed a follow-up.
  There is **no rolling summary, no summarisation call and no token budget** on history.
* **Server-side threads.** `backend/services/threads.py` (~700 lines) with real persistence —
  `create`, `append`, `record_answer`, `ask`, `remember`, `set_context`, `settled_period`,
  `listing`, `publish`, `copy`, `archive`. Sound infrastructure, but it stores full messages and is
  not wired to the Cockpit V2 path at all.

### 1.6 Current data schemas

`backend/cockpit_v2/schema.py` (400 lines) — `MEASURES`, `DIMENSIONS`, `GRAIN`, `data_dictionary()`.
Physical storage is **Parquet in `settings.analytics_dir`**, read by `reader._read()` via
`pd.read_parquet`. Datasets:

* one wide snapshot per quarter, `cockpit_quarter_<label>` (`calendar.dataset_name`);
* `cockpit_credit_history` (the quarters stacked);
* eight detail packages: `cockpit_borrower_financials`, `cockpit_collateral_assets`,
  `cockpit_collateral_allocation`, `cockpit_covenant_tests`, `cockpit_scenario_parameters`,
  `cockpit_risk_curves`, `cockpit_macro_paths`, `cockpit_movements`.

**Calendar: `calendar.QUARTERS` is eight quarters** (`2024Q3`…`2026Q2`), not twenty. Macro data
(`generate.macro_paths`) carries vintages with a 4-quarter warm-up but **has no `quarter_offset`
axis of −4…+15 per anchor**, and no `macro_target_quarter` column.

### 1.7 Current data access boundaries

`backend/cockpit_v2/scope.py` — `permit(dataset, principal)` is a genuine single choke point.
`allowed()` = the quarterly datasets ∪ `ALLOWED_PACKAGE`; the effective scope is that ∩ the
principal's `datasets`. `OutOfScope` refusals deliberately do not disclose what exists elsewhere.
`guard.py` blocks a V2 seed/reset that targets `data/analytics`, `data/curated` or `metadata`.

**What is enforced:** which *named Parquet dataset* a helper function may open.
**What is not enforced, because it cannot yet be reached:** there is no database role, no view
grant, no row-level security, and no SQL/Python principal — because there is no SQL or Python
execution. The V3 spec's §10.1/§10.4 boundary (least-privilege role, allowlisted views, RLS,
security-definer audit) has **no counterpart at all** in the current implementation.

### 1.8 Current retry budgets

`backend/cockpit_v2/budgets.py` (91 lines). Three classes — `simple` / `standard` / `complex` —
carrying `planning_turns` (1/4/8), `tool_calls` (2/10/20) and `wall_clock_seconds` (15/60/120).

Gaps against V3 §9.1: no execution-submission counter, no analysis-round counter, no total
provider-call ceiling, no token ceiling, no cost ceiling, no per-step wall time, no input-packet
cap, no output cap, no history-token cap, no finalisation reserve, and **no persistence** — the
budget is a value object computed per call, so a restart or a concurrent worker gets a fresh one.
The V3 spec forbids exactly that (§9.3).

### 1.9 Current model configuration

`backend/llm/roles.py` — seven active roles (`router`, `planner`, `complex_planner`,
`investigator`, `analyst`, `interpretation`, `critic`; `translation` declared and unused), each
resolved from its own environment variable with a documented fallback chain to `AI_MODEL` and then
the provider default. **No model id is hard-coded** — this discipline is exactly what V3 §2 asks
for and is kept.

`backend/llm/base.py` — the provider protocol exposes **one** method: `structured(system, prompt,
schema, ...) -> LLMResult`. `backend/llm/anthropic_provider.py` implements it with a single
`messages.create` carrying one forced tool, `MAX_ATTEMPTS = 3`, `TIMEOUT_SECONDS = 60.0`, and
`DEFAULT_MODEL = "claude-sonnet-4-5-20250929"` as the provider's own pinned default.

**This is the single largest structural gap.** V3 requires a stateful, multi-turn Opus conversation
with correctly paired and ordered `tool_use` / `tool_result` blocks, preserved opaque assistant
blocks, prompt caching, and per-call token/cost accounting (§8.1, §9.3). `structured()` cannot
express any of that.

### 1.10 Current answer renderer

`frontend/src/components/ask/cockpit-v2.tsx` (380 lines) — `CockpitV2Badge` (branch, commit,
dataset version, checksum, published quarters, isolation namespace, quarter selector) and
`CockpitV2Answer` (sections, unanswered outputs stated rather than dropped, bridge table,
waterfall chart, limitations, evidence). Types in `frontend/src/lib/api.ts`. Wired in
`frontend/src/app/page.tsx`; `frontend/src/components/ask/answer.tsx` chooses between prose sources.

The component renders **backend-computed values only and computes nothing** — the right boundary,
and it is kept. What it has no vocabulary for: Standard/Deep mode, live progress
(`executing submission n/5`), cancellation, a functionality referral card with a navigation
button, clickable Cockpit alternatives, clarification chips with free text, and the budget/stop
envelope.

## 2. Functionality registry — verified against the actual application

`frontend/src/lib/navigation.ts` is the authority for what exists and where.

| Registry entry | Actual UI label | Verified route | Status in this build |
|---|---|---|---|
| Cockpit | "Cockpit" | `/` | `live` |
| EWS | "Early Warning" / "Early Warning Signals" | `/early-warning`, `/early-warning/signals` | `partial` (prototype, synthetic fit) / `live` |
| Credit Scoring | — | **none** | **Not implemented as an independent module.** `backend/scorecard/` builds and fits scorecards; `/engine-builder` and `/studio` build analyses. Neither is a credit-scoring *workflow* that assigns a borrower a new score. Registered as `enabled=false, route=null` with an honest unavailable message, per spec §6.1. |
| Scorecard Validation | "Scorecard Validation" | `/scorecard-validation` | `live` — validation only; it does not originate scores. |
| What-if Analysis | "Stress Testing" | `/stress` | `live` — named scenarios applied to the portfolio with comparison. This is the nearest real owner of "new shock / hypothetical parameter change"; the registry must use the **actual** label, not the spec's generic name. |
| Lenses | "Lenses" | `/lenses`, `/lenses/cro`, `/lenses/[lensId]` | `live` |

## 3. REUSE / MODIFY / REPLACE matrix

| # | Component | Current implementation | Reuse | Modify | Replace | Reason | Target files |
|---|---|---|---|---|---|---|---|
| 1 | Authentication & principal | `backend/api/permissions.py` — `Principal`, `RequireAnalyst`, `RequireAdmin` | ✅ | | | Server-side tenant/permission resolution is exactly what §7.1 requires. Nothing to change. | unchanged |
| 2 | DB / session infrastructure | `backend/db/` (SQLAlchemy), `alembic/` | ✅ | | | Needed for the request ledger and thread summaries; already correct. | unchanged; new tables via alembic |
| 3 | Thread persistence | `backend/services/threads.py` | ✅ | ✅ | | Sound storage, but it has no rolling summary, no `summary_through_exchange_id`, and no bounded-pair selection. Extend, do not rewrite. | `backend/services/threads.py`, new `backend/cockpit_agentic/thread.py` |
| 4 | `/ask` API plumbing | `backend/api/routers/ask.py` | ✅ | ✅ | | Router, `AskIn`, cost metering and error contract are reusable. But the V2 branch inside `_ask()` must go: §17 forbids any fallback to the deterministic engine, and today Cockpit V2 answers *alongside* it. | `backend/api/routers/ask.py`, new `backend/api/routers/cockpit_agentic.py` |
| 5 | Model role configuration | `backend/llm/roles.py` | ✅ | ✅ | | The no-invented-ids discipline is exactly §2's requirement. Add `cockpit_sonnet` and `cockpit_opus` roles so Cockpit's two-model contract is configured independently of the seven legacy roles. | `backend/llm/roles.py` |
| 6 | LLM provider primitive | `backend/llm/base.py`, `anthropic_provider.py` — `structured()` only | | ✅ | | Keep `structured()` for the Sonnet passes and the summary (single-shot, schema-constrained — a perfect fit). **Add** a `converse()` primitive for the Opus loop: multi-turn messages, `tool_use`/`tool_result` pairing and order, preserved opaque blocks, cache control, and per-call usage returned. Additive; no existing caller changes. | `backend/llm/base.py`, `backend/llm/anthropic_provider.py`, `backend/llm/telemetry.py` |
| 7 | Prompt caching | `backend/llm/caching.py` | ✅ | ✅ | | Reuse; extend the cache identity to include tenant/scope and catalog version (§9.3). | `backend/llm/caching.py` |
| 8 | Cockpit read scope | `backend/cockpit_v2/scope.py` | ✅ | ✅ | | `permit()` as the single choke point is the right shape. Re-point it at the V3 domain's allowlisted views and extend it to govern the SQL principal and the Python artifact fetch, not just `pd.read_parquet`. | new `backend/cockpit_agentic/scope.py` (derived) |
| 9 | Seed/reset destination guard | `backend/cockpit_v2/guard.py` | ✅ | ✅ | | Runtime isolation guard works; add the V3 namespace and the DuckDB/database targets. | `backend/cockpit_agentic/guard.py` |
| 10 | Reporting calendar | `backend/cockpit_v2/calendar.py` — 8 quarters | ✅ | ✅ | | Quarter parsing, shifting, availability lags and the "no partial quarter" semantics are all correct and reusable. Extend to **exactly 20 ordered slots** and add the second time axis: `macro_target_quarter` and `quarter_offset` ∈ [−4, +15]. | `backend/cockpit_agentic/calendar.py` |
| 11 | Demo data generator | `backend/cockpit_v2/generate.py` (1,752 lines) | | ✅ | | The deterministic seeded generator, borrower trajectories, statements, ratio derivation, collateral valuation, EAD paths and macro paths are genuinely good engineering and the numerical fixtures depend on them. Extend from 8 → 20 quarters, ~250 borrowers / ~600 facilities, the full §4 field set (40 ratios, 20 qualitative questions, 19 grades, 12 collateral types, 10 macro factors × 20 offsets). | `backend/cockpit_agentic/generate.py` |
| 12 | Demo policy set | `backend/cockpit_v2/policy.py` (701 lines) | ✅ | ✅ | | Rating scales, PD maps, SICR rules, recovery rules, scenario weights — needed to *generate* coherent demo data. It must **not** be reachable as a runtime analytical template. Move behind the generator only. | `backend/cockpit_agentic/policy.py` |
| 13 | ECL calculator | `backend/cockpit_v2/ecl.py` (608 lines) | ✅ | ✅ | | Keep as the **demo data generator's** measurement engine and as an independent **test oracle**. Remove it from the runtime answer path: §8/§9.6 forbid a compulsory formula gate, and §4.2 forbids forcing `PD×LGD×EAD` as a reconstruction. | `backend/cockpit_agentic/ecl.py` (generation + `tests/`) |
| 14 | Factor attribution | `backend/cockpit_v2/attribution.py` (853 lines) | | | ✅ | Exact Shapley allocation over fixed factor groups is a *prescribed decomposition method*. §1.5 and §7.6 make method selection Opus's. Retain the arithmetic as a **test fixture oracle** only; it is not a runtime component. | moved to `tests/cockpit_agentic/oracles/` |
| 15 | Data dictionary / schema | `backend/cockpit_v2/schema.py`, `docs/cockpit_v2/data_dictionary.json` | | ✅ | | Right idea, ~1/10th of the required field set. Rebuild as the full §4 catalog with units, lineage, availability, missing reason, aggregation behaviour and per-type/per-horizon **expanded** column names (no `{type}` placeholders reaching Opus). | `backend/cockpit_agentic/fields.py`, `catalog.py` |
| 16 | Catalogue registration | `backend/cockpit_v2/catalogue.py` | ✅ | ✅ | | Reuse the Data Builder registration mechanism for the new `corporate_cockpit` domain. | `backend/cockpit_agentic/catalog.py` |
| 17 | Dataset reader | `backend/cockpit_v2/reader.py` | ✅ | ✅ | | Parquet reading, quarter resolution, `NotPublished`, and the measurement cache are reusable. Its `resolve_period_pair` heuristics belong to the old router and go. | `backend/cockpit_agentic/reader.py` |
| 18 | Data integrity gates | `backend/cockpit_v2/validate.py` (717 lines, 27 checks) | ✅ | ✅ | | Excellent and directly on point — key uniqueness, no fan-out, borrower dedup, weights, probability bounds, curve identities, lifetime≠annual, ECL reconciliation, negative denominators, collateral allocation, temporal availability, macro vintages, synthetic labelling. Extend for 20 slots, 40 ratios, 20 questions, 19 grades and the macro offset window. | `backend/cockpit_agentic/validate_data.py` |
| 19 | Missingness profiler | **absent** | | | ➕ new | §5 and §7.4-F require a versioned, release-pinned, field-level profile computed from *full authorized data*, not previews. Nothing like it exists. | `backend/cockpit_agentic/profile.py` |
| 20 | Evidence ledger & claim validation | `backend/cockpit_v2/evidence.py` (429 lines) | ✅ | ✅ | | Observation/Ledger/claim-figure grounding is exactly §7.8's "bind numerical claims to result fact IDs". Keep; re-point at execution result artifacts instead of canned tool observations. Drop the fixed `Contract`/capability coverage table — that is a template gate. | `backend/cockpit_agentic/evidence.py` |
| 21 | **Question router** | `backend/cockpit_v2/understand.py` (683 lines, regex) | | | ✅ | A keyword classifier producing one of 16 fixed output kinds is incompatible with §3/§4/§6: two Sonnet passes then an Opus ownership gate. Nothing survives. | deleted; `backend/cockpit_agentic/sonnet.py`, `opus.py`, `registry.py` |
| 22 | **Answer composer** | `backend/cockpit_v2/answer.py` (2,084 lines, 17 template sections) | | | ✅ | The canonical "compulsory analytical template". §1.5, §7.6, §9.6 forbid it. §17/§18 forbid keeping it as a fallback. | deleted; `backend/cockpit_agentic/runtime.py`, `answer.py` (envelope only) |
| 23 | **Canned tool registry** | `backend/cockpit_v2/tools.py` (5 fixed analyses) | | | ✅ | Opus must author SQL/Python; five pre-authored analyses are the opposite. | deleted; `backend/cockpit_agentic/execute.py` |
| 24 | **Budgets** | `backend/cockpit_v2/budgets.py` | | | ✅ | Three in-memory caps against §9.1's twenty enforced, persisted, atomic guardrails. Not extendable in place. | `backend/cockpit_agentic/ledger.py` |
| 25 | **Narrative stories** | `backend/cockpit_v2/stories.py` | | | ✅ | Seeded narrative beats for canned answers. No place in an Opus-authored answer. | deleted (generator-side seeding only) |
| 26 | **Legacy deterministic/analyst fallback** | `ask.py` `_analyst_view`, `backend/orchestration/*`, `backend/analyst/*` | ✅ (untouched) | | ✅ (for Cockpit) | §17: no hidden fallback. These modules stay **fully intact for every other module** — the audit must show other capabilities are undamaged — but the Cockpit path must never reach them. | `backend/api/routers/ask.py` only |
| 27 | SQL execution | **absent** | | | ➕ new | §10.1: least-privilege read-only principal over allowlisted views only, parser/binder validation, statement timeout, no writes/DDL/multi-statement/file/network/security-definer path. DuckDB (`duckdb==1.5.5`, already a dependency) over the pinned Parquet release. | `backend/cockpit_agentic/sql.py`, `execute.py` |
| 28 | Python execution | **absent** | | | ➕ new | §10.2: isolated runtime, no credentials/filesystem/network, bounded memory/CPU/time, `run(inputs)` contract. **If no genuine isolation boundary is available in this environment, §10.2 requires it be disabled and reported as a capability limitation — not downgraded to in-process `exec`.** | `backend/cockpit_agentic/python_exec.py` |
| 29 | Functionality registry | **absent** | | | ➕ new | §6.1. Descriptions sourced from `frontend/src/lib/navigation.ts` and backend module presence, never invented. | `backend/cockpit_agentic/registry.py` |
| 30 | Context packet builder | **absent** | | | ➕ new | §7.4 A–J, with the token-counted large-dictionary guardrail and `CONTEXT_TOO_LARGE`. | `backend/cockpit_agentic/context.py` |
| 31 | Failure packet | **absent** | | | ➕ new | §8.2 and the absolute repair-ownership rule §7.6A. | `backend/cockpit_agentic/failure.py` |
| 32 | State machine | partial (`executor.STAGES` for the legacy path) | | | ➕ new | §11's typed states and terminal statuses, server-approved transitions, idempotency keys. | `backend/cockpit_agentic/states.py`, `runtime.py` |
| 33 | Typed contracts | scattered dataclasses | | | ➕ new | §13's fifteen named contracts. | `backend/cockpit_agentic/contracts.py` |
| 34 | Prompt files | inline strings | | | ➕ new | §13: versioned prompt/configuration files for the six contracts. | `backend/cockpit_agentic/prompts/` |
| 35 | Answer renderer | `frontend/src/components/ask/cockpit-v2.tsx` | ✅ | ✅ | | Table/chart/section/evidence rendering and the strict no-compute boundary are reusable. Add mode, progress, cancel, referral card + navigation button, alternatives, clarification chips, budget/stop envelope. | `frontend/src/components/ask/cockpit-agentic.tsx`, `frontend/src/lib/api.ts` |
| 36 | Test infrastructure | `tests/cockpit_v2/`, `tests/evals/cockpit_v2/` | ✅ | ✅ | | pytest layout, the eval harness (`build_cases.py`, `run_eval.py`, `cases.json`) and the browser UAT driver (`browser_uat.py`) are all reusable shapes. | `tests/cockpit_agentic/`, `tests/evals/cockpit_agentic/` |
| 37 | Numerical oracles | `tests/cockpit_v2/test_ecl_oracle.py`, `test_factor_attribution.py` | ✅ | | | §14.5 requires independent ground-truth fixtures. These are exactly that. | kept and extended |
| 38 | Flag-off test | `tests/cockpit_v2/test_flag_off.py` | ✅ | ✅ | | Proves other modules are unaffected when the switch is off. Re-point at the V3 flag. | `tests/cockpit_agentic/test_flag_off.py` |
| 39 | Runtime isolation doc | `docs/cockpit_v2/BASELINE_AND_ISOLATION.md` | ✅ | ✅ | | Reuse the isolation approach; new namespace. | `docs/cockpit_agentic_v3/` |

**Summary:** of 10,636 lines in `backend/cockpit_v2/`, roughly **4,600 lines are reused or extended**
(generator, policy, ECL, calendar, reader, scope, guard, validate, evidence, catalogue, schema seed)
and roughly **4,300 lines are replaced** (`answer.py`, `understand.py`, `tools.py`, `budgets.py`,
`stories.py`), with `attribution.py` (853 lines) demoted from runtime to test oracle. The frontend,
`/ask` plumbing, auth, DB, threads, LLM role configuration and test infrastructure are all reused.

## 4. Conflicts that force a replacement rather than an extension

1. **Template control of method.** Sixteen output kinds × seventeen section builders decide the
   methodology before any model sees the question. Spec §1.5, §7.6, §8, §9.6.
2. **No ownership gate.** Nothing asks whether Cockpit owns the question; an EWS question is
   answered by a Cockpit template. Spec §6 — this is the first Opus responsibility.
3. **No model-authored code.** Five canned analyses; no SQL/Python surface. Spec §7.5, §7.6.
4. **Provider primitive cannot carry a repair loop.** `structured()` is single-shot; V3 needs a
   multi-turn conversation with paired `tool_use`/`tool_result` blocks and full retained context on
   every continuation. Spec §8.1.
5. **Eight quarters, not twenty; one time axis, not two.** Spec §3.1.
6. **A tenth of the field dictionary.** Spec §4 — 40 ratios, 20 qualitative questions, 19 grades,
   12 collateral types with 9 generated columns each, 10 macro factors × 20 offsets, full balance
   sheet and income statement, PIT/TTC × 12m/lifetime PD.
7. **No missingness profiler.** Spec §5, §7.4-F.
8. **Budgets are advisory, in-memory and incomplete.** Spec §9.
9. **Deterministic fallback is architectural, not incidental.** `/ask` computes the deterministic
   answer *first* and the model path second. Spec §17, §18.
10. **Broader-than-Cockpit reachability.** `/ask` returns `body["analyst"]` from the legacy analyst,
    whose tools read the whole certified catalogue. Spec §6.4 — hard domain enforcement below the
    model.

## 5. Implementation sequence

| Stage | Deliverable | Spec | Gate |
|---|---|---|---|
| **A** | This audit; branch from the preserved V2 HEAD; spec installed; baseline evidence recorded. | §2, §15A | ✅ done |
| **B1** | `contracts.py`, `states.py`, `ledger.py` — the fifteen typed contracts, the state machine and the persisted atomic budget ledger with all twenty §9.1 guardrails. | §9, §11, §13 | Ledger unit tests: five submissions then no sixth; three rounds then no fourth; earliest-bound-wins; restart does not reset. |
| **B2** | `calendar.py`, `fields.py`, `catalog.py` — 20 slots, the macro −4…+15 second axis, the complete §4 field dictionary with every per-type and per-horizon column expanded. | §3, §4 | Catalog completeness tests; no `{type}` placeholder survives. |
| **B3** | `generate.py`, `policy.py`, `ecl.py` extended to 20 quarters / ~250 borrowers / ~600 facilities / full field set; `validate_data.py` gates; `profile.py` field-level missingness. | §4, §5 | 27 extended integrity checks green; profile computed from full data. |
| **B4** | `scope.py`, `sql.py` — the `corporate_cockpit` domain, the allowlisted DuckDB views, the least-privilege read-only principal, statement timeouts, and the 21st-quarter / cross-domain / DDL / multi-statement refusals. | §6.4, §10.1 | Security tests against the real engine, not mocks. |
| **C1** | `registry.py` — the six functionality entries with **verified** routes and honest enabled states (Credit Scoring absent; What-if = "Stress Testing" at `/stress`). | §6.1 | Route existence asserted against `navigation.ts`. |
| **C2** | `llm/base.py` + `anthropic_provider.py`: the additive `converse()` primitive — multi-turn, tool blocks paired and ordered, opaque blocks preserved, usage returned. `roles.py`: `cockpit_sonnet`, `cockpit_opus`. | §8.1, §9.3 | Serialized-request tests assert block pairing and order. |
| **C3** | `context.py` — the A–J context packet, token-counted, with the large-dictionary guardrail and `CONTEXT_TOO_LARGE`. | §7.4 | A test asserts the serialized outbound request really contains the full compact dictionary. |
| **D1** | `sonnet.py` — pass 1 (cleanup/translation, 5 languages) and pass 2 (business normalization), plus the bounded rolling-summary update. `prompts/`. | §7.2, §7.3, §7.9 | Negation/misspelling/multilingual fidelity tests. |
| **D2** | `opus.py` + `runtime.py` — the ownership gate, plan/code authorship, the validate→execute→failure-packet→**Opus-authored repair** loop, sufficiency review and the final answer envelope. **CreditProbe never edits model SQL.** | §6, §7.5–§7.8, §8 | A repair trace proving the full effective context is resent; a `NO_PROGRESS` duplicate block. |
| **D3** | `python_exec.py` — isolated Python, or an explicit, tested capability-blocked state. | §10.2 | Escape tests, or a recorded honest block. |
| **D4** | `thread.py` — rolling summary, 3 default / 5 expanded / 8 hard-cap pairs, history token cap, referrals summarised as referrals. | §12 | 20-exchange continuity test. |
| **E** | `backend/api/routers/cockpit_agentic.py`; `/ask` V2 branch removed for Cockpit; `frontend/.../cockpit-agentic.tsx` — mode, progress, cancel, referral + navigation, alternatives, clarification chips, stop envelopes. | §11, §15E | No-fallback test: the Opus path failing returns a stop envelope, never a deterministic answer. |
| **F** | Full test suite (§14.1–§14.5), the labelled ownership benchmark, security suite, budget suite, browser UAT, and the eight required documents. Live-provider UAT run if a credential is configured; otherwise recorded **BLOCKED/UNVERIFIED**. | §14, §15F | Every gate green or explicitly reported as unmet. |

## 6. Standing constraint on this work

If `ANTHROPIC_API_KEY` is not configured in this environment, stages D and F are implemented and
tested **structurally**, against a labelled mock provider, and live-provider UAT is reported as
**BLOCKED / UNVERIFIED**. Deterministic substitute output will not be presented as evidence that
the agentic Opus architecture works, and no deterministic ECL decomposition will be shipped as a
stand-in for an unavailable Opus (spec §18, task instruction 18).

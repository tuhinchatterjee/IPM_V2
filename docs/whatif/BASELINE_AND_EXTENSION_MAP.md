# Baseline and extension map

What the accepted runtime actually is, what of it can be extended, and what
cannot. Section 1.1 of the What-If specification says to verify rather than
trust the handoff transcript; this is that verification, and three of its
findings change what can honestly be built.

Every claim here is a read-only fact from this repository at commit
`245c50e45786c6e0c866b281f9dd74da17d160b5`, with the file and line that
carries it. Nothing here is inferred from a directory name.

---

## 1. The recorded references, checked

| Recorded in the handoff | Verdict |
|---|---|
| Commit `245c50e45786c6e0c866b281f9dd74da17d160b5` | **Verified.** HEAD of `claude/cockpit-single-agent-v4-h8fsbq`. |
| Corporate release `v4-saudi-corporate-20q-v4` | **Verified.** `backend/cockpit_v4/domains.py:43-78`; on disk at `data/cockpit_v4_lake/v4-saudi-corporate-20q-v4/`. |
| Retail release `v4-saudi-retail-20m-v5` | **Verified.** Same two places. |
| Tag `cockpit-round-h-live-pass-2026-09-23` | **DOES NOT EXIST.** The repository's tags are `recovered-sep8-whatif`, `recovered-sep8-cockpit-v2`, `recovered-sep8-integrated`, `windows-pilot-v1`. The commit is real; the tag is not. |
| `/Users/tuhinchatterjee/Desktop/IPM_V2-CockpitLiveUAT` | **Not reachable.** This work runs in a Linux container; no `/Users` tree exists. |
| `/Users/tuhinchatterjee/Desktop/CreditProbe_Share/...` | **Not reachable**, same reason. |
| `/Users/tuhinchatterjee/Desktop/CreditProbe_Launchers/START_CREDITPROBE_RETAIL_DEMO.command` | **Not reachable**, so what it launches could not be inspected. Section 20's launcher work is BLOCKED here and must be done on the Mac. |

The candidate branch is `claude/advanced-cockpit-whatif-v1`, created fresh from
`245c50e` in its own worktree. No existing branch was overwritten; no
destructive git operation was used.

### The published books are not in git

`lake.root()` resolves to `<worktree>/data/cockpit_v4_lake`
(`lake.py:72-76`, via `settings.analytics_dir`), and that directory is
**untracked** — the books are generated and published, not committed. A fresh
worktree therefore has no data at all, and the first test run in one fails at
collection with `ReleaseNotFound` rather than with anything meaningful.

The candidate's lake is a byte-for-byte **copy** of the accepted one, verified
with `diff -rq`, not a regeneration. Regenerating would very likely reproduce
it — the generators are seeded and fingerprint-identical — but §D09 asks that
the accepted source hashes remain unchanged, and copying the accepted bytes
proves that directly instead of arguing it from determinism.

Both pinned releases verify against the accepted runtime:

| Release | Fingerprint | Origin | Periods |
|---|---|---|---|
| `v4-saudi-corporate-20q-v4` | `e37236d0f6d4e494…` | `SYNTHETIC_DEMO` | 20 |
| `v4-saudi-retail-20m-v5` | `a1e797dcc73236b7…` | `SYNTHETIC_DEMO` | 20 |

All 40 data files are in `PROTECTED_FILES.sha256`. Worth carrying into
`HANDOFF.md`: any environment that checks out this branch must publish or copy
the lake before the suite will even collect.

A second root is needed too. `data/cockpit_v4/` holds the V3-namespace release
the suite reads when `COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4`. Without it the
suite does not fail — **several hundred tests skip silently**, which is worse,
because a green run with no data underneath it looks like a passing baseline.
Its 24 files are hashed under their own heading.

### The clean baseline (§A09)

Captured in this worktree with both data roots present and no candidate code
on any path:

| Suite | Result | Wall |
|---|---|---|
| `tests/cockpit_v4` + `tests/frontend` | **3402 passed, 4 skipped, 0 failed** | 16m 00s |

Identical to the accepted worktree at `245c50e`, so there are no pre-existing
failures to reproduce and none to relabel later. The four skips are the
round's own four.

---

## 2. There is no extension mechanism

Section 2 asks for the capability to be added "through the real existing
extension mechanism." There is none. A search for entry points, registration
decorators or dynamic loading across `backend/cockpit_v4/` returns exactly one
hit, and it is `pyrunner.py:33` listing `importlib` among the names the sandbox
**bans**.

Every axis the specification assumes is extensible is a closed constant living
in a core file, usually with a cross-file test pinning it:

| Axis | What it actually is | Extensible? |
|---|---|---|
| Analyst tools | `TOOL_NAMES`, a frozen 5-tuple, `contracts.py:60-66`, plus two literal filename maps (`:1364`, `:1398`) and `_DESCRIPTIONS` (`:1228`). Unknown names raise `ValueError` (`:1352`). | No |
| Turn gate | `STATES` tuple (`action_state.py:58-88`) and a straight-line `if` cascade in `decide()` (`:142-306`) with tool tuples written inline | No |
| Tool dispatch | `if call.name == …` chain with an implicit finalize fallthrough, `orchestration.py:1096-1105` | No |
| Prompt blocks | A literal list in `build()`, `context.py:348-374`. The signature has no hook, no callback list, no `extra_blocks`. | No |
| Answer payload | `tables` and `charts`, and nothing else — `contracts/finalize_response.schema.json`, `client.ts:130-131`. `ResponsePanel` is linear JSX with no kind-keyed dispatch. | No |
| Chart kinds | A closed union, `visual-choice.ts:27-33`, pinned three ways (server `finalization.CHART_KINDS`, the JSON schema enum, the frontend list) by `visuals.test.ts:255` | No |
| Artifact kinds | `ARTIFACT_KINDS = ("result", "thread_turn")`, `contracts.py:815`, rejected at `:825` | No |
| Comment/share subjects | `SUBJECT_KINDS`, `collaboration.py:35-37`, enforced by `check_subject` | No |
| Feature flags | Three global env booleans, `config.py:379, 396, 404`. `V4Config` is a frozen dataclass with fixed fields. | **No per-book flag exists** |
| Cohort / saved row-set | **Does not exist anywhere in the runtime.** `cohort` appears only in the synthetic generators and two prose strings. | Net-new |

### What IS additive, with zero core edits

Three generic stores take new content without a migration or a core change:

| Store | Shape | Where |
|---|---|---|
| `details` | `(detail_ref PK, run_id, body TEXT, created_at)` — an opaque JSON bag keyed by ref | `run_store.py:200-205`; API `put_detail` / `detail` / `details_for_run` at `:877, :900, :1068` |
| `thread_context` | per-thread JSON | `run_store.py:192-198` |
| `investigation_items.kind` | a free string ≤40 chars, unvalidated end to end — route (`routes.py:1664`) passes it through, insert (`run_store.py:1440`) does not check it | reference only: `ref_id` + `label` |

### The consequence, and what was done about it

Registering a sixth tool would touch seven to eight protected files. Section 1.2
forbids exactly that and asks for the blocker to be written down instead. It is,
in `PROTECTED_CORE_INCOMPATIBILITY.md`, and it is **not implemented**.

P0–P4 does not need it. See section 4 below.

---

## 3. What the two books contain, and what they do not

Both books are 100% synthetic (`origin: SYNTHETIC_DEMO` in every manifest) and
deterministic — `SEED = 20260803` plus per-`(entity, period)` SHA-256 jitter
(`generate/corporate.py:1096-1104`), so two builds are fingerprint-identical.

**Four relations per book, closed at `schema.py:828-833`:**

| Book | Relations | Grain | Periods |
|---|---|---|---|
| Corporate `v4-saudi-corporate-20q-v4` | `corp_borrower_quarter`, `corp_facility_quarter`, `corp_collateral_quarter`, `corp_covenant_quarter` | borrower / facility / collateral item / covenant test, per quarter | **20 quarters**, 2021Q3–2026Q2 |
| Retail `v4-saudi-retail-20m-v5` | `retail_customer_month`, `retail_account_month`, `retail_behaviour_month`, `retail_collateral_month` | customer / account, per month | **20 months**, 2025-01–2026-08 |

Scale: 5,412 borrowers and 21,918 facilities (384,009 facility-quarters);
26,000 customers and 44,027 accounts (584,372 account-months). Both panels are
unbalanced — entities enter at origination and leave at charge-off.

### There is a real historical ECL panel

`corp_facility_quarter.ecl_sar_mn` and `retail_account_month.ecl_sar_mn` are
full per-entity, per-period time series, not an as-of snapshot. 18,942
facilities have all 20 quarters; 18,996 accounts have all 20 months.
`ecl_12m_sar_mn` and `ecl_lifetime_sar_mn` are separate full series at the same
grain. Portfolio coverage moves 1.35% (2021Q3) → 3.44% (2024Q2) → 2.39%
(2025Q1) → 5.07% (2026Q2), so there is genuine signal, not flat noise.

### But published ECL is closed-form, and that decides Method 2

`generate/corporate.py:1004-1011` and `generate/retail.py:693-700`:

```python
if stage == 3:
    pd_pit = pd_life = 1.0
    ecl_12m = ecl_life = ead * lgd
else:
    ecl_12m  = ead * pd_pit  * lgd
    ecl_life = ead * pd_life * lgd
ecl = ecl_12m if stage == 1 else ecl_life
```

The identity holds in the published parquet to a maximum relative error of
6.1e-3 across all 384,009 Corporate rows — entirely four-decimal rounding of
small values. Retail holds too except on charged-off rows, where
`retail.py:712-716` floors ECL at `wrote_off - recovered` so a leaving account
is fully provided.

Two consequences, pulling opposite ways:

- **Good for Delta.** Proportional ECL scaling is arithmetically exact on this
  book. A relative PD shock multiplies `ecl_sar_mn` and nothing is lost.
- **Fatal for section 11 as written.** The ECL label *is* PD × LGD × EAD.
  Section 11.1 says: "Do not manufacture the training label as PD × LGD × EAD
  and then claim the resulting model learned the bank's ECL engine." A model
  trained here would score near-zero WAPE for a trivial reason and every
  acceptance target in 11.5 would pass meaninglessly. The honest route is a
  separate, explicitly named synthetic release whose ECL process is **not**
  closed-form. That is P7 work.

### What is absent, and therefore cannot be stressed today

| Required by | Missing |
|---|---|
| §7 (the entire MEV library) | **Any macroeconomic variable.** No GDP, unemployment, CPI, oil, policy rate or property index exists in either book. Verified three ways: `schema.py:828-833` registers no macro relation; a case-insensitive grep over both manifests returns zero; the same grep over the generators returns zero. |
| §9.1 | Modelled-ECL vs management-overlay split. `ecl.py:34-39` refuses to invent it: "inventing that split is how a decomposition becomes a story." |
| §9.2, §11 | Remaining maturity, effective interest rate, discount factors, PD term structure |
| §9.2 | Economic scenario dimension and scenario weights — one deterministic ECL per entity-period |
| §10.2 | CCF as a column. **Derivable** for Corporate as `(ead − drawn) / undrawn` (verified over 20k rows: min 0.200, median 0.351, max 0.500). Retail has no CCF concept: `retail.py:625` uses a hardcoded 0.45 for Credit Card only. |
| §8 | Retail application score — does not exist; only the behavioural score (300–900, bands A–E) is published |
| §4 family 4 | Retail sector — does not exist. Corporate has `sector` (14) and `sub_sector` (75). |
| §13.1 | Corporate borrower-level ECL — must be aggregated from facilities |

### The legacy dataset that has all of it, and why it is not used

`data/cockpit_v4/v4-saudi-20q-v1/` — note `cockpit_v4`, not `cockpit_v4_lake` —
is a V3-generator release carrying `cockpit_macro_pivot.parquet` (quarterly,
`scenario_id ∈ {baseline, downside, upside}`, each factor spread lag4→lead15),
`cockpit_ifrs9_detail.parquet` (with `scenario_weight`, `term_pd_marginal`,
`term_survival`, `term_discount_factor`), and a facility table with
`ecl_modelled`, `ecl_overlay`, `remaining_maturity_months`,
`effective_interest_rate`, `ccf_pit`, `lgd_downturn`.

It is **unreachable from the V4 runtime**: `lake.py:72-76` hardcodes the root to
`cockpit_v4_lake`, and `catalog.require_relation` (`catalog.py:204-229`) refuses
any relation outside the registered four. It covers only 218 facilities.

It is a **design reference** for the synthetic candidate release, not a source
to import. Section 3.1 forbids importing the old book.

**A trap worth naming:** `semantics.py:47-80` (`_LEGACY_MEASURES`) still maps
"ecl" to `cockpit_facility_quarter.ecl_reported` and names
`ecl_modelled`/`ecl_overlay`; `context.py:6` and `catalog_tool.py:7` mention
"the expanded macro pivot". Those comments describe the legacy book. Reading
them gives a materially wrong impression of what today's two books carry.

---

## 4. How the capability integrates without a sixth tool

The pivotal fact from section 3: because published ECL is exactly
`ead × pd × lgd`, proportional Delta — section 10.1's
`M1_i = M0_i × Π factor_k^elasticity_k` — is **one SQL statement** over the
published book, a `CASE` over the cohort predicate multiplying `ecl_sar_mn`.

That matters because the analyst already authors its own SQL through
`execute_analysis`; `execute_tool` already validates, binds, authorizes and runs
it; the result is already a governed artifact with a `code_digest` and a
`release_fingerprint`; and every number Delta publishes is expressible in the
closed operation set `derivation.py` already enforces:

| Published figure | `derivation` operation |
|---|---|
| baseline and scenario ECL totals | `sum` |
| absolute change | `difference` |
| relative change | `percentage_change` |
| coverage rate, driver share | `percentage`, `share_of_total` |

So the new package **computes, normalises, types and verifies**; the existing
governed path **executes and publishes**. Nothing bypasses validation, and the
governance trace (`governance.py`) records a scenario run for free, because it
assembles from events, submissions, artifacts and numeric claims — all of which
a scenario run produces through the normal path.

### Preview and confirmation reuse the clarification round trip

Section 6.2 wants DRAFT → … → PREVIEW_READY → CONFIRMED with a hash-bound
approval. That is the existing clarification machinery:

- The preview publishes as `disposition: "clarification"`, the question in
  `clarification_question`, the methods in `clarification_options`.
- The run settles `WAITING_FOR_USER`.
- The reply is projected back by `context.build`'s `you_asked`, `you_offered`
  and `the_question_still_standing` (`context.py:230-290`).
- The confirmation hash lives in `thread_context`.

No new state, no new mechanism, no new screen.

### The single protected-core change

`context.py` gains a `scenario_blocks()` module function and one call site —
the identical pattern to the `policy_blocks()` at `context.py:869` and
`product_blocks()` at `context.py:620` that are already there. Section 1.2
permits "a minimal additive entry" whose exact diff is documented.

**Its exact diff is recorded in the Change log at the foot of this file, and
`scripts/whatif/protected_hashes.py --check` reports it on every run.** It is
not silenced.

Everything else is net-new files under `backend/cockpit_v4/scenario/`, modelled
on `ecl.py`: deterministic, `model_calls: 0`, no sandbox, no provider call.

---

## 5. Reuse map — what the old What-If module can still give

The full module exists only under tag `recovered-sep8-whatif` (tip `0558f26`);
it is absent from HEAD in both worktrees. ~15,700 lines of Python, and the UI
is Next.js React, not Dash.

| Need | Reuse from | Effort | Verdict |
|---|---|---|---|
| ECL formula, SICR, staging, lifetime PD, bounding | `backend/ifrs9/policy.py` (tag) — pure numpy/pandas, zero I/O, already designed to be called with a hypothetical PD | Low | **Adapt.** Its `measured_ecl` and `sicr` are exactly the re-staging contract §4 family 5 needs. |
| Shock application: PD, LGD, EAD, CCF, collateral, haircut, rating, direct stage | `backend/whatif/engine.py:277-560` (tag) — pure column transforms with a fixed application order and policy clamps recorded as a named driver | Low–medium | **Adapt**, stripping the DuckDB `_read` layer. |
| Shock taxonomy and unit algebra | `backend/whatif/scenarios.py:20-40` (tag) — `RELATIVE`, `ABSOLUTE_PP`, `BASIS_POINTS`, `NOTCHES`, `STEPS` | Low | **Adapt.** It is §5.1 already in code. |
| Order-neutral driver attribution | `backend/whatif/attribution.py` (tag) — exact Shapley over telescoping factors, explicitly not SHAP | Medium | P9. |
| Rating/stage transition matrix | `backend/whatif/migration.py` (tag) | Low | P9 — renders as the existing heatmap. |
| Facility-grain allocation by EAD share | `backend/whatif/workbook.py:494` (tag) | Low | P4, for §12's allocation rules. |
| Multi-sheet xlsx with a reconciliation sheet | `backend/whatif/workbook.py` (tag), 11 sheets, openpyxl | Medium | P9. `openpyxl==3.1.5` is **already pinned**, so no new dependency. |
| Actual-to-actual ECL movement decomposition | `backend/cockpit_v4/ecl.py:290` `decompose` | None | **Already live.** Exact, with the residual published rather than absorbed. |
| Waterfall, heatmap, transition matrix | `export.py` + `visuals.tsx` | None | **Already live.** |
| Tornado chart | nothing | New | P9 — the only missing chart kind, and it needs four closed-set edits. |

**Do not port:** `backend/api/routers/whatif.py` (~30 FastAPI routes),
`threads.py`, `cache.py`, `language.py`, `narrative.py`, `answers.py`, and the
whole `frontend/src/app/what-if/**` tree. V4 has its own run, state and
finalization machinery, and §2 forbids a second orchestrator.

**Still live at HEAD and superseded:** `backend/engine/functions/stress.py`
(`stressed_ecl = total_ecl * pd_factor * lgd_factor * ead_factor` at `:223`),
`backend/stress_lab.py`, `frontend/src/app/stress/page.tsx`. These are the older,
weaker engine. They are outside `backend/cockpit_v4/` and are not touched.

---

## 6. The binding constraint on publishing a scenario number

`derivation.py` enforces a closed set of twelve operations with **no parser, no
`eval`, no Python in the payload and no way to write a new operation**
(`derivation.py:25-46`). Everything is `Decimal`, parsed from the artifact's
stored string form.

So anything a scenario computes that is not one of those twelve — a Shapley
contribution, or `ecl = pd × lgd × ead × factor` — **cannot be published as a
narrative claim directly**. It must be materialised as artifact *rows*, with
claims then doing `identity` or `sum` over those rows.

This is a design input, not an obstacle: it is why `ledger.py` emits a
driver-contribution table rather than returning a dict of totals, and it is why
the waterfall chart has rows to read.

---

## Change log — every protected-file difference and its reason

| File | Change | Reason | Phase |
|---|---|---|---|
| `backend/cockpit_v4/context.py` | `+ SCENARIO_SEMANTICS` dict, `+ scenario_blocks()`, one call site in `finalization_system()`, two `__all__` entries | The one additive entry §1.2 permits. Identical in shape to `policy_blocks()` (`:869`) and `product_blocks()` (`:620`) already in the file: a module function returning literal blocks, invoked by name. Carries what the catalogue cannot say — that "increase PD by 20" has four readings — on turns that can act on it. | P3 |

**Why this one is safe, and how that is checked rather than asserted.**

`scenario_blocks()` returns `[]` unless a book's What-If flag is on, and both
are off by default. Its import of the candidate package is local and wrapped in
`try/ImportError`, so the accepted runtime does not depend on the package
existing. With the flags off the assembled payload is byte-identical to the
baseline's, which `test_action_payload_snapshot.py` and
`test_provider_payload.py` confirm — 68 tests, unchanged.

No other protected file is edited. `--check` reports `1 changed, 0 removed,
0 added`, and it will keep reporting it: the diff is explained here, never
allowlisted away.

`scripts/whatif/protected_hashes.py --check` is the authority. This table
explains what it reports; it does not replace it.

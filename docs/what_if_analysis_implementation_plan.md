# What-If Analysis — Implementation Plan and Repository Audit

**Branch:** `claude/what-if-analysis-rebuild`
**Baseline:** `origin/claude/integration-rehearsal` @ `4f7956666feca2822cc74effd335823ba1a391e9`
**Product source of truth:** `docs/what_if_analysis_spec.md`
**As-built record:** `docs/what_if_analysis_as_built.md`

This document exists so that a future session needs no chat history. It records the
repository audit that preceded the build, the architectural decisions taken, and the
reuse / extend / refactor / retire verdict for every relevant component.

---

## 1. Why this baseline

`main` was 131 commits stale (541 files, +147,340 / −6,079) and contains **no**
`backend/whatif/`, `backend/ifrs9/`, `backend/planner/`, `backend/playbook/`,
`backend/metrics/`, `backend/product/` or `backend/units/`.

Branch topology at the time of cutting:

```
main 3855f9b (Sep 1)
 └── claude/integration-rehearsal 4f79566 (Sep 5)   +131 / −0 vs main
      ├── claude/lenses-specialist-dashboards-esd591 e48e901  +13
      └── claude/project-planner-copilot             d9e7789  +14
```

`mb(integration-rehearsal, lenses) = mb(integration-rehearsal, project-planner) =
mb(lenses, project-planner) = 4f79566`. It is the verified least common ancestor of every
active feature branch, and commit `e81f913` on it is *"Integration rehearsal: merge the
combined feature history onto latest main"* — the designated integration line.

Lenses and Project Planner are deliberately **not** merged in. They integrate later.

**Migration state at branch time:** single head `0041`, strictly linear `0001 → 0041`.
Project Planner has already claimed `0042` and `0043` on its own branch, so any migration
here starts at **`0044`**.

## 2. Key repository facts the build depends on

### 2.1 Corporate IFRS 9 domain

- Storage is a **Hive-partitioned Parquet lake read through DuckDB**, not relational
  tables: `{analytics_dir}/corporate_ifrs9/period=Q2 2026/data.parquet`.
  Reader: `backend/data_access/duckdb_source.py` (`DuckDBSource.periods()`, `row_count()`).
- **16 quarters, Q3 2022 → Q2 2026.** Labels formatted `"Q{n} {YYYY}"`;
  `universe.quarter_end(period)` maps to an ISO date.
- **Grain is obligor × period**, `(borrower_id, period)`, by explicit design:
  *"a book that stages one facility of a borrower differently from another is describing
  a bank that does not exist."* `corporate_facilities` is facility-grain; joining the
  snapshot to `corporate_covenants` is a **declared FORBIDDEN join** (different grain).
- Measured size: `corporate_ifrs9` = **52,880 rows**; 3,800 distinct borrowers,
  3,244–3,343 active per quarter.
- `corporate_ifrs9` columns: `borrower_id, period, period_end_date, default_flag, ead,
  current_dpd, pd_at_origination_pct, sicr_trigger_pd, sicr_trigger_dpd,
  sicr_trigger_watchlist, sicr_flag, stage, prior_stage, stage_moved, pd_12m, pd_lifetime,
  lgd, ecl_12m, ecl_lifetime, management_overlay, final_ecl, ecl_coverage,
  scenario_weight_base, scenario_weight_upside, scenario_weight_downside, origin`.
- `corporate_borrower_360` is the snapshot the engine reads first; it **copies** `stage`
  and `final_ecl` and is *"never authoritative over them"*.

### 2.2 Two books share one catalogue — never mix them

| | **BORROWER_360** (What-If) | **CREDIT_BOOK** |
|---|---|---|
| Datasets | `corporate_*` | `portfolio_facility`, `ifrs9_staging` |
| Grain | borrower × quarter | facility × quarter |
| Rating scale | 14-point `AAA…D` | 10-point `CP-1…CP-10` |
| Periods | Q3 2022 – Q2 2026 (16) | Q4 2022 – Q2 2026 (15) |
| SICR | 3 triggers | 5 triggers incl. covenant/rating/watchlist, with curing |
| Used by | `backend/whatif/*` | `ecl_decomposition`, `stress_scenario_basic` |

### 2.3 Rating scale — 14 points, authoritative

`backend/corporate/universe.py:269`, docstring *"A fourteen-point master scale."*

```
AAA, AA, A, BBB+, BBB, BBB-, BB+, BB, BB-, B+, B, CCC, CC, D
```

13 performing + `D`; `DEFAULT_INDEX = 13`; numeric 1..14 so a downgrade is a positive
notch difference. Four scales exist in the repo (14, 22, 10, 7); **none is 19**.

`RATING_BOUNDS` (upper PD % per performing grade):
`0.04, 0.09, 0.18, 0.32, 0.55, 0.95, 1.60, 2.70, 4.50, 7.50, 13.00, 26.00`.

`backend/whatif/masterscale.py` derives each grade's PD as the **geometric** mid-point of
its band (`PD_FLOOR_PCT = 0.02`, ceiling `RATING_BOUNDS[-1] * 2 = 52.0`):

| AAA | AA | A | BBB+ | BBB | BBB− | BB+ | BB | BB− | B+ | B | CCC | CC | D |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.0283 | 0.0600 | 0.1273 | 0.2400 | 0.4195 | 0.7228 | 1.2329 | 2.0785 | 3.4857 | 5.8095 | 9.8742 | 18.3848 | 36.7696 | — |

**Notching is not a PD multiplier.** `shift()` moves the grade inside the scale (clamped
at the weakest *performing* grade, so a scenario never manufactures a default) and the
shock is applied as the **ratio** of the two grades' masterscale PDs, preserving
within-grade calibration:

```
stressed_pd = borrower_pd × masterscale_pd(stressed) / masterscale_pd(opening)
```

### 2.4 Governed staging and ECL

`backend/ifrs9/policy.py` (`POLICY_VERSION = "1.0.0"`, owner "Credit Risk Analytics"):

| Constant | Value |
|---|---|
| `SICR_PD_RATIO` | 2.0 |
| `SICR_PD_ABSOLUTE` | 2.00 pp |
| `SICR_ABSOLUTE_PD` | 13.0 % |
| `SICR_DPD_DAYS` | 30 |
| `DEFAULT_DPD_DAYS` | 90 |

`sicr()` is deliberately PD-source-agnostic: *"This is the function What-If calls with a
STRESSED PD. Nothing about it knows or cares whether the PD it is given was reported or
modelled, which is exactly why a scenario answer can be defended."*

```
ECL = PD_applicable × LGD × EAD × WEIGHTED_SCENARIO_FACTOR
PD_applicable = pd_12m if stage <= 1 else lifetime_pd
lifetime_pd(p) = clip(1 - (1-p)^4.2, p, 0.999)
SCENARIO_WEIGHTS = (Base 0.50 x1.00, Upside 0.20 x0.72, Downside 0.30 x1.46)
WEIGHTED_SCENARIO_FACTOR = 1.082
```

No discounting anywhere; `eir_pct` exists on the credit book and feeds only RAROC.

### 2.5 The duplication defect

`backend/corporate/universe.py:1177-1196` defines its **own** copy of all five SICR
constants and does **not** import `backend.ifrs9.policy`. `docs/WHATIF.md` claims the
generator imports the policy and `tests/whatif/test_whatif.py:86-90` asserts equality —
the test passes by coincidence, not construction.

A **third** copy lives in `scripts/generate_saudi_universe.py:397-400` with a
**deliberately different** value (`SICR_PD_ABSOLUTE = 0.55`) because it is the credit
book with five triggers and curing. **Consolidation is scoped to the corporate book
only**; that third copy is left alone.

### 2.6 Existing What-If engine (prior art, preserved)

`backend/whatif/` — `engine.py` (675), `language.py` (444), `scenarios.py` (261),
`sensitivity.py` (225), `masterscale.py` (216), `answers.py` (176), `trace.py` (147).
`backend/ifrs9/` — `policy.py`, `decomposition.py` (517, six-step ECL bridge).
Router `backend/api/routers/whatif.py` with `/configuration`, `/scenarios`, `/run`,
`/ask`, `/compare`, `/sensitivity`, all `RequireAnalyst`, `MAX_ROWS = 500`.
Chat entry at `backend/orchestration/orchestrator.py:343` → `_from_whatif` (line 1173),
a **pre-router deterministic branch that calls no LLM**.

Shock application order is fixed for reproducibility:
`RATING → MACRO → FINANCIAL → PD → LGD → COLLATERAL → EAD`.
Clamps PD `[0,99]`, LGD `[0,95]`, EAD `≥0`. EAD uplift capped at undrawn commitment;
collateral loss maps to LGD on the secured share only; stage never improves
(`np.maximum(stressed, baseline)`).

The ratio carry that makes the base column tie to the accounts:

```python
ratio = measured_stress / measured_base
ecl_baseline = final_ecl                 # the reported number, untouched
ecl_stressed = final_ecl * ratio
```

Invariants asserted by `tests/whatif/test_whatif.py` that must keep passing:
`base ties to reported book`, `totals are the sum of the borrowers`,
`within-grade calibration survives the shock`, `no scenario reduces the provision`,
`a scenario never cures a stage`, `a scenario never manufactures a default`,
`a downgrade alone is not a SICR trigger`, `a period never becomes a magnitude`,
`the same scenario twice returns the same figures`.

### 2.7 Security contracts governing model artifacts

Two independent contracts; **neither bans XGBoost**.

`backend/brain/security.py` governs **Brain Pack ZIP imports between installations**. It
is an allowlist that already contemplates models:

```python
ALLOWED_SUFFIXES = frozenset({".json", ".jsonl", ".yaml", ".yml", ".md", ".txt", ".csv",
                              ".onnx",  # a model format that is data, not code
                              ".png", ".svg"})
```
`.pkl` / `.joblib` / `.pt` are refused because *"a pickle is a program, not data"* — the
objection is executable deserialisation, not models. **XGBoost native JSON is already on
the allowlist; `.ubj` is not**, so JSON is used and the allowlist is untouched.

`backend/learning/models.py` governs **local training artifacts**: `seal(run, artifact)`
refuses (never redacts) on credential patterns and on client identifiers —
`_CLIENT_COLUMNS = {customer_id, borrower_id, account_id, borrower_name, customer_name,
national_id, iban, cr_number}` — then `sha256(json.dumps(sort_keys=True))`.
**Consequence: XGBoost feature names are a security-contract matter.** No feature may be
named with a client identifier or the artifact is rejected.

There is **no artifact file store** in the repo — no `models_dir`, no `save_model`
anywhere. Configured dirs: `log`, `upload`, `raw`, `curated`, `analytics`, `metadata`.
The house pattern is *JSON document + sha256 hash*.

### 2.8 Platform conventions

- SQLAlchemy 2.0 `Mapped[...]`/`mapped_column`, PostgreSQL, heavy `JSONB`, no mixins,
  timestamps repeated per table, enums as module-level string constants (never `sa.Enum`).
- Session via `with get_session() as session:` (`backend/db/engine.py`), not a FastAPI
  dependency.
- Routers: `APIRouter(prefix="/thing", tags=["thing"])`, registered with
  `app.include_router(x.router, prefix=API_PREFIX)`, `API_PREFIX = "/api/v1"`.
- No success envelope; a top-level collection key plus counts. Errors are
  `{error, message, detail}` (`backend/api/schemas.py::ErrorResponse`), deliberate
  refusals raised as `HTTPException(422, detail={"error":…, "message":…})`.
- Permissions: `RequireAnalyst = Depends(require(RUN_ANALYSIS))`,
  `RequireAdmin = Depends(require(MANAGE_MODELS))` (`backend/api/permissions.py`).
- Frontend: Next 16.3.2 / React 19.2.8, all pages `"use client"`, one root layout,
  Tailwind v4 with **role-named design tokens** (*"a literal colour value inside a
  component is a bug"*), Radix + CVA + lucide, charts via **recharts 3.10**, graphs via
  `@xyflow/react`. API through the single `request()` wrapper in `frontend/src/lib/api.ts`
  (cookie session + `X-IPM-Role`).
- Tests: pytest (`testpaths=["tests"]`, `addopts="-q"`, `pythonpath=["."]`), ruff
  (line-length 120, `E,F,I,UP,B`), frontend `node --test` on `src/**/*.test.ts`.
  Browser journeys use Playwright resolved from `PLAYWRIGHT_MODULE` / `CHROMIUM_PATH`,
  deliberately not a repo dependency.

---

## 3. Component verdicts — retain / extend / refactor / retire

| Component | Verdict | Note |
|---|---|---|
| `backend/ifrs9/policy.py` | **Extend** | Becomes the single governed corporate staging source; gains a configurable rule layer for thread-level overrides. Defaults unchanged. |
| `backend/corporate/universe.py` SICR constants | **Refactor** | Import from `ifrs9.policy` instead of redeclaring. Values identical, so no data change. |
| `scripts/generate_saudi_universe.py` SICR constants | **Retain untouched** | Different book, deliberately different values. |
| `backend/ifrs9/decomposition.py` | **Retain** | Six-step ECL bridge; reused for attribution. |
| `backend/whatif/masterscale.py` | **Retain** | Governed notching and PD ratio; the spec's rating mechanics. |
| `backend/whatif/scenarios.py` | **Extend** | Add step identity/ordering for layered scenarios and serialisation for persistence. |
| `backend/whatif/engine.py` | **Extend** | Keep the ratio-carry and fixed shock order; add stage-migration and CCF/EAD shocks and methodology dispatch. |
| `backend/whatif/sensitivity.py` | **Extend** | Existing 8-variable matrix superseded for user-facing macro by the specified 10-variable V1 matrix; retained for back-compat. |
| `backend/whatif/language.py` | **Extend** | Absorb magnitude-free trigger vocabulary; add stage/CCF/collateral/haircut readings. |
| `backend/whatif/answers.py`, `trace.py` | **Extend** | Narrative and lineage for the new result contract. |
| `backend/api/routers/whatif.py` | **Extend** | New endpoints; existing six preserved. |
| `backend/orchestration/decomposition.py` (exact Shapley) | **Retain and reuse** | Deterministic scenario attribution. Never conflated with ML SHAP. |
| `backend/engine/functions/stress.py` `stress_scenario_basic` | **Retire from routing, retain registered** | Isolate as legacy/internal. |
| `high_utilisation_watchlist` (same file) | **Retain untouched** | The product's only `USER_DEFINED` analysis. |
| `stress_scenarios` table | **Adopt** | Dead table; `Scenario.to_dict()` already matches its `parameters` JSONB. |
| `saved_analyses`, `analysis_runs`, `trace_versions`, `investigations` | **Reuse** | Run/result/thread persistence. |
| `frontend/src/app/stress/page.tsx` | **Refactor** | Becomes the What-If landing page per spec §4. |
| `frontend/src/lib/navigation.ts` | **Refactor** | Rename the entry to What-If Analysis. |

### 3.1 Legacy isolation — exact change set

The audit found **27 occurrences** of `stress_scenario_basic` across 12 files. The
user-facing `/stress` screen does **not** reference it. Three routing surfaces do:

| Surface | Location |
|---|---|
| Planner intent | `orchestration/planner.py:144-158` + `_stress` builder `:547-559` (pattern weight 6 vs threshold 5) |
| Analyst LLM tool | `analyst/tools.py:1375-1391` + registration `:1544-1548` |
| Studio binding | `studio/library.py:924-927` (`engine=` / `L.CERTIFIED`) |

Isolation removes those three plus the `ask.py:106` starter question and the
`frontend/src/lib/demo.ts` references, while leaving the contract **registered** so
`/engine/analyses/.../execute`, historical runs, the renderer and the seeded Project keep
resolving. **No data migration and no orphan problem.**

Full deletion was rejected because of three couplings: `high_utilisation_watchlist`
co-habits `stress.py`; `scripts/seed_projects.py:129-133` owns an entire seeded Project;
and `analysis_runs` / `saved_analyses` / `investigation_messages` hold rows with no
cleanup path.

**Regression guard.** `orchestration/routing.py:403` still fires a `"stress"` signal on
`stress|scenario|sensitivit|what if|shock|downside|severe case`. Removing the planner
intent without absorbing that vocabulary would send those questions to `unmatched`. The
new What-If reader therefore accepts **magnitude-free** questions and opens a What-If
conversation, and provides the equivalent of the now-inert
`orchestration/modification.py` `set_scenario` operation.

---

## 4. Architecture as planned

```
frontend/src/app/what-if/…            landing, threads, model configuration
        │  (frontend/src/lib/api.ts — single request() wrapper)
        ▼
backend/api/routers/whatif.py         HTTP surface, RequireAnalyst
        ▼
backend/whatif/
  domain.py        Corporate IFRS 9 binding — the only data door
  profiles.py      rating / stage / sector / borrower / parameter profiles
  migration.py     15x15 rating and 3x3 stage historical migration
  staging.py       configurable staging rules over ifrs9.policy defaults
  macro.py         ten V1 variables + configurable sensitivities
  steps.py         layered scenario state (add/edit/remove/undo/reset)
  methodology.py   Delta | ML selection gate, persisted per thread
  engine.py        shock application, re-staging, re-measurement (existing)
  delta.py         Delta Model as-built formula
  ml/              XGBoost: features, training, registry, explain, anchoring
  threads.py       thread + saved/recent persistence
        ▼
backend/ifrs9/policy.py               single governed corporate staging source
backend/corporate/…                   Parquet lake via DuckDBSource
```

**Domain restriction** is enforced structurally: every read goes through
`backend/whatif/domain.py`, which resolves only Corporate IFRS 9 datasets and refuses a
field that does not exist there rather than joining another domain.

## 5. Persistence decision

Reuse-first, per the approved scope (saved / recent / reopen / reproduce / audit; **no**
sharing, approval, maker-checker or publishing):

- `stress_scenarios` — the scenario **definition** (`name`, `severity`, `rationale`,
  `parameters` JSONB from `Scenario.to_dict()`, `created_by`, unique `(name, version)`).
- `investigations` / `investigation_messages` — the **thread** and its transcript;
  `investigations.context` JSONB carries what the thread has settled.
- `analysis_runs` + `trace_versions` — the **run** and its immutable trace.
- `saved_analyses` — the saved artefact, with `params` / `filters` / `period` / `result` /
  `data_versions` JSONB and FKs to run / investigation / project.

Any residual field that genuinely has no home (version stamps for masterscale, macro
matrix, staging policy and ML model; `last_opened_at` for Recent) is added by a single
additive migration numbered **`0044`**. Whether that proved necessary is recorded in the
as-built document, not assumed here.

## 6. ML plan and its honest limitation

Target is an **ECL rate** (official ECL over an exposure denominator confirmed against
the actual data), never contemporaneous ECL predicting itself; leakage explicitly tested.
Split is chronological: development through **Q4 2025** (≈70/30 train/validation),
**Q1 2026 and Q2 2026 locked as OOT**. Artifact is **XGBoost native JSON**, sealed by
hash, with structural feature names only.

**Disclosed limitation.** `universe.py::macro_factor()` generates every observable macro
series as a deterministic linear function of one latent factor:

```python
oil  = 84.0 + 18.0 * factor + N(0, 2.00)
gdp  =  2.4 +  2.6 * factor + N(0, 0.25)
rate =  5.6 -  1.1 * factor + N(0, 0.12)
```

Oil, GDP and the policy rate are therefore collinear by construction — **one macro degree
of freedom observed 16 times**, not three variables observed 52,880 times. Consequently
the ML model trains primarily on **borrower-quarter cross-sectional and longitudinal**
signals, where the variation is genuine; macro enters, if at all, as the single cycle
factor rather than as collinear proxies that would produce misleading SHAP. This is
stated on the model card and in the as-built document.

The **user-facing ten-variable macro What-If functionality is not reduced** — it is
deterministic and configurable, and does not depend on the ML model.

## 7. Verification strategy

- `uv run pytest -q` — full suite, plus new `tests/whatif/*` covering rating, risk
  parameters, stage, macro, sector, borrower, layered scenarios, Delta arithmetic,
  XGBoost (leakage, split, anchoring, artifact safety), retraining, save/reopen and
  access control.
- `uv run ruff check .`
- `npm run typecheck`, `npm run lint`, `npm run build`, `npm test` in `frontend/`.
- `uv run alembic upgrade head` and a single-head check.
- Playwright browser journeys 1–9 against a running backend and frontend.

## 8. Defects found in the baseline

Recorded here because they were exposed by this work, and fixed only where this feature
or its tests require it.

1. **`requires-python = ">=3.11"` is unsatisfiable.** `numpy==2.5.0` requires ≥3.12 and
   there is no `uv.lock`, so `uv sync` fails outright on a 3.11 interpreter. Fixed
   minimally by setting `requires-python = ">=3.12"`, which matches the declared
   dependency set. **Required** — nothing in the repo installs without it.
2. **`scipy` is imported but undeclared** — `backend/runtime/kernels.py:279`
   (`from scipy import stats`) with scipy in neither `pyproject.toml` nor
   `requirements.txt`. Pre-existing; fixed only if this feature or the baseline test run
   requires it, and recorded as such.
3. **SICR constants duplicated** between `ifrs9/policy.py` and `corporate/universe.py`,
   with a test that passes by coincidence. Fixed as part of §3 consolidation.

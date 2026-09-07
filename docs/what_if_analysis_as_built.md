# What-If Analysis — as built

What actually exists on `claude/what-if-analysis-rebuild`, as distinct from what
was planned. Where the build differs from `docs/what_if_analysis_spec.md`, the
difference is stated here rather than left for a reader to discover.

**Baseline:** `origin/claude/integration-rehearsal` @ `4f7956666feca2822cc74effd335823ba1a391e9`

---

## 1. Architecture

```
frontend/src/app/what-if/            landing, thread, models/delta, models/ml
frontend/src/app/stress/             redirect to /what-if
frontend/src/components/whatif/      shared parts (gate, staging, matrix, composer)
        │  frontend/src/lib/api.ts   — 29 What-If methods on the single request() wrapper
        ▼
backend/api/routers/whatif.py        31 endpoints, all RequireAnalyst
        ▼
backend/whatif/
  domain.py       the only door into Corporate IFRS 9
  profiles.py     rating / stage / sector / PD / LGD / CCF / borrower views
  migration.py    matched-entity rating (15x15) and Stage (4x4) migration
  staging.py      configurable criteria over the governed policy
  macro.py        the ten CreditProbe V1 variables and their sensitivities
  masterscale.py  the 14-grade scale and notch → PD ratio  (pre-existing)
  scenarios.py    Shock / Population / Assumptions / Scenario  (extended)
  steps.py        layered scenario state
  engine.py       shock application, re-staging, re-measurement  (extended)
  delta.py        the Delta Model, in factors
  methodology.py  the gate
  run.py          one execution path for both methodologies
  threads.py      saved and recent What-Ifs
  language.py     sentence → scenario  (extended)
  answers.py, trace.py, sensitivity.py  (pre-existing)
  ml/  features.py  train.py  registry.py  explain.py  predict.py
        ▼
backend/ifrs9/policy.py              the single governed corporate staging source
backend/corporate/                   Parquet lake read through DuckDB
```

**Domain restriction is structural.** Every read passes through
`backend/whatif/domain.py`, whose `DATASETS` tuple is the whole world:
`corporate_borrower_360`, `corporate_ifrs9`, `corporate_facilities`,
`corporate_collateral`, `corporate_macro`. Anything else raises `DomainError`
naming what the domain does carry. Facilities and collateral are aggregated
**up** to obligor grain, never joined out to it.

## 2. Reuse, refactor, retire — as executed

| Component | Verdict | What happened |
|---|---|---|
| `backend/whatif/engine.py` | **Extended** | Gained `_apply_ccf`, `_apply_haircut`, `_apply_stage`; a `staging` parameter; `Result.frame`. The ratio-carry and fixed shock order are unchanged. |
| `backend/whatif/masterscale.py` | **Retained unchanged** | 14 grades, geometric band mid-points, ratio notching. |
| `backend/whatif/scenarios.py` | **Extended** | Added `CCF`, `HAIRCUT`, `STAGE` kinds. |
| `backend/whatif/language.py` | **Extended** | Stage migrations, CCF, the ten macro variables, spoken numbers, bare directions, magnitude-free absorption, duplicate-shock removal. |
| `backend/whatif/answers.py` | **Refactored** | Sensitivity table reads both macro row shapes. |
| `backend/whatif/sensitivity.py` | **Retained** | Superseded for user-facing macro; still consulted for targets only it carries. |
| `backend/ifrs9/policy.py` | **Retained + adopted** | Now the single declaration; `corporate/universe.py` imports it. |
| `backend/ifrs9/decomposition.py` | **Retained unchanged** | |
| `backend/corporate/universe.py` | **Refactored** | Five SICR constants re-exported from the policy instead of redeclared. |
| `scripts/generate_saudi_universe.py` | **Untouched** | Different book, deliberately different constants. |
| `stress_scenario_basic` | **Isolated as legacy** | Planner intent, analyst tool registration and Studio engine binding removed. Contract still registered. |
| `high_utilisation_watchlist` | **Untouched** | Shares the module; the product's only `USER_DEFINED` analysis. |
| `stress_scenarios` table | **Adopted** | Was migrated in 0002 and unused. Now holds saved and recent What-Ifs. |
| `frontend/src/app/stress/page.tsx` | **Replaced by a redirect** | |

## 3. Corporate IFRS 9 as used

- **16 periods, Q3 2022 → Q2 2026**, resolved from the book on every call.
  `resolve_period` understands `""`, `latest`, `earliest`, `previous` and a
  literal label; anything else is refused with the list of what exists.
- **Grain `(borrower_id, period)`** — 3,244 borrowers at Q2 2026, 52,880 rows
  across the window. Asserted by test, not assumed.
- **CCF** is not on the snapshot; it is aggregated from `corporate_facilities`
  as an **undrawn-weighted** mean so it reproduces the borrower's own EAD.
- **Haircut** comes from `corporate_collateral.regulatory_haircut_pct`.

## 4. Rating, staging and ECL

**14 governed grades**: `AAA, AA, A, BBB+, BBB, BBB-, BB+, BB, BB-, B+, B, CCC,
CC, D`. Displayed as **15 rows** (grades + Total) and a **15 × 15** migration
matrix. The universe was not regenerated and `SEED = 20260830` is untouched.

**Staging.** `backend/whatif/staging.py` layers over `backend/ifrs9/policy.py`.
Five rules; the three governed ones are on, the two What-If assumptions are off:

| Rule | Basis | Default |
|---|---|---|
| Relative PD increase (≥2× origination AND ≥2.00pp) | Governed | on |
| Absolute PD level (≥13%) | Governed | on |
| Days past due (≥30) | Governed | on |
| **Rule A** — rating deterioration ≥2 notches | **Assumption** | **off** |
| **Rule B** — PD ≥2× the pre-scenario level | **Assumption** | **off** |

Rule A and Rule B are **off by default** and this is deliberate: a downgrade is
not a governed SICR trigger in this policy, and the existing invariant
`test_a_downgrade_alone_is_not_a_sicr_trigger` says so. They are exposed
prominently in the Staging Criteria panel and are one click from being on. The
default set reproduces `policy.stage_of` **exactly** — asserted by test — so a
thread that changes nothing gets the reported book back. No rule reaches Stage
3 in either direction; the default presumption is not a staging opinion.

**ECL, as built:**

```
ECL = PD_applicable × LGD × EAD × 1.082
PD_applicable = pd_12m (Stage 1) | pd_lifetime (Stages 2 and 3)
lifetime_pd(p) = clip(1 − (1−p)^4.2, p, 0.999)
WEIGHTED_SCENARIO_FACTOR = 0.50×1.00 + 0.20×0.72 + 0.30×1.46 = 1.082
```

No discounting. `eir_pct` exists on the credit book and feeds only RAROC.

## 5. Delta Model — the exact formula implemented

```
What-If ECL = REPORTED ECL × PD factor × LGD factor × EAD factor
```

The engine measures both states on the governed basis and forms their ratio;
`WEIGHTED_SCENARIO_FACTOR` cancels, so the ratio **equals** the product of the
three factors. `backend/whatif/delta.py` reads the factors out of that ratio
rather than computing the answer a second way.

- **The stage factor is isolated** from PD deterioration: it is what the PD
  factor would have been on the opening measurement basis, divided out.
- **CCF converts through EAD**: `EAD = drawn + CCF × undrawn`. Measured on the
  live book, a +20% CCF move produces **+1.61%** ECL — not +20%.
- **Zero baseline**: below `NEAR_ZERO = 1e-12` the ratio is not formed and the
  factor is 1.0.
- Caps: PD `[0, 99]`, LGD `[0, 95]`, EAD `≥ 0`, EAD uplift capped at undrawn.

Worked example, verified by test: PD 2.00→2.40 (1.20) × LGD 40→44 (1.10) ×
EAD +5% (1.05) = **1.386**, so ECL 1.80 → 2.4948.

## 6. Macro — ten variables, deterministic

All ten CreditProbe V1 variables with the specified sensitivities, reproduced
at one adverse unit by test. `PD_new = PD × multiplier^units`,
`LGD_new = LGD + change_pp × units`, capped 0–100, favourable moves inverted.

Relative-vs-absolute is handled: unemployment at 5% "+30%" is **+1.5pp**
(1.5 adverse units), not +30pp. Where a relative move needs a level the book
does not publish, it is **refused** rather than guessed.

Only **3 of the 10** have an observed level in this installation
(`policy_rate_pct`, `oil_price_usd`, `real_gdp_growth_pct`); the screen says so
for the other seven rather than inventing a number.

## 7. ML Model — XGBoost, as built

| | |
|---|---|
| Algorithm | XGBoost regressor, 400 trees, depth 5, lr 0.05, seed 20260906 |
| Target | `ecl_rate` = `final_ecl / ead` |
| Features | **31**, all structural — no client identifier, nothing ECL-derived |
| Training | Q3 2022 – Q4 2024, 31,942 rows |
| Validation | Q1 2025 – Q4 2025, 12,762 rows |
| **Out-of-time (locked)** | **Q1 2026, Q2 2026**, 6,361 rows |
| Artifact | **XGBoost native JSON**, ~1.27 MB, sha256-sealed |

**Measured metrics** (active model `2026.09.06`):

| | R² | MAE | RMSE | WAPE |
|---|---|---|---|---|
| Training | 0.99930 | 0.000573 | 0.001975 | 2.09% |
| Validation | 0.99754 | 0.001265 | 0.004595 | 3.11% |
| **Out-of-time** | **0.99765** | 0.000970 | 0.003814 | **3.15%** |

By Stage (validation): Stage 1 R² 0.9666 / WAPE 5.95%; Stage 2 R² 0.9955 /
WAPE 2.80%; Stage 3 R² 0.9953 / WAPE 3.22%.

**Anchoring**, mandatory and implemented:

```
ML factor  = model(features shocked) / model(features baseline)
What-If ECL = REPORTED ECL × ML factor
```

Where the baseline prediction is below `FLOOR = 1e-6` the ratio is not formed
and the **Delta factor is used for that row**, with the count reported.

**Measured divergence from Delta** on the live book: PD +20% → Delta +17.66%,
ML +16.48%; LGD +5pp → +11.57% / +11.12%; one-notch downgrade → +56.28% /
+53.92%; collateral −20% → +25.37% / +23.11%. The two genuinely differ, which
is the point of offering both.

**Explainability**: exact TreeSHAP from XGBoost's own `pred_contribs`, feature
gain importance, actual-vs-predicted calibration, per-feature sensitivity
curves, error slices by Stage / sector / quarter / PD band / LGD band, and a
local SHAP explanation for the Client X example.

**Retraining** genuinely retrains: builds the set, checks the split, fits,
validates, scores out-of-time, computes SHAP, seals a new JSON artifact and
registers a **CANDIDATE**. The active model is never replaced automatically;
old and new metrics are shown side by side and activation is explicit. Every
version is kept and the change log records `trained` and `activated` events.

## 8. Persistence — no migration was required

**Migration head remains `0041`.** No migration was written. Saved and recent
What-Ifs live in `stress_scenarios`, which had existed since migration `0002`
with no code behind it; the scenario state, staging criteria and version,
methodology and model version, and the figures reached all fit its `parameters`
JSONB. `0042` and `0043` remain free for the Project Planner branch.

Saved and recent are one row distinguished by `status`. Recent is pruned to 12
per owner. Every read is scoped to `created_by`, and the refusal does not
distinguish "does not exist" from "is not yours". Where `DATABASE_URL` is
absent, saving **refuses and says so** rather than pretending.

## 9. Auditability

Every executed scenario carries: domain, dataset, period, grain, currency,
scenario description, structured steps, population and count, staging criteria
**and their version fingerprint**, ECL methodology and version, macro
sensitivity version, reported baseline ECL, What-If ECL, absolute and
percentage change. A saved What-If persists all of it.

## 10. Verification actually run

| Check | Command | Result |
|---|---|---|
| What-If suite | `uv run pytest tests/whatif tests/ifrs9` | **271 passed** |
| Full backend | `uv run pytest` | **12,950 passed, 46 skipped, 6 failed** — every one of the six reproduced on the baseline `4f79566` with the same data lake; named in §11 |
| Backend lint | `uv run ruff check .` | clean |
| Frontend types | `npx tsc --noEmit` | clean |
| Frontend lint | `npm run lint` | clean |
| Frontend tests | `npm test` | **542 passed** |
| Production build | `npm run build` | all routes built |
| Migrations | `uv run alembic upgrade head` + `heads` | **single head 0041** |
| Browser journeys | `node scripts/acceptance/whatif_journeys.mjs` | **9/9, 72/72 checks** |
| Display contract | `uv run python scripts/check_decimals.py` | **0 unexplained sites** |
| Feature matrix | `uv run python scripts/feature_matrix.py --write` | every page judged |

## 11. Defects found and fixed

1. **`requires-python = ">=3.11"` was unsatisfiable** — `numpy==2.5.0` needs
   ≥3.12 and there is no lockfile, so `uv sync` failed outright. Pre-existing.
2. **`scipy` imported but undeclared** (`backend/runtime/kernels.py:279`).
   Pre-existing; now declared.
3. **SICR constants duplicated** with a test that passed by coincidence.
4. **The request model could not read its own output** — `to_dict()` writes
   `None` for an unchosen methodology and `StateIn` demanded a string, so the
   first turn in a thread worked and every one after it returned 422.
5. **Macro basis-point variables were sized 100× too small** — a 200bps rate
   shock became 0.01 adverse units.
6. **Both macro readers matched one sentence** and the engine applied both,
   squaring the shock.
7. **SQLAlchemy `Row` is not a tuple subclass** — the name-collision check
   compared `"('Name',)"` against names and never matched, so the database
   raised the collision the check existed to prevent.
8. **A year was read as a magnitude**, turning "which customers were downgraded
   and had ECL rise in Q1 2026?" into a scenario.
9. **Spoken numbers, Stage migrations and CCF were unparseable** — "five
   percentage points" failed where "5" worked.
10. **Recording a Recent entry could take the run down with it.**
11. **The scenario reader hijacked the screening questions.** Absorbing the
    retired planner intent's magnitude-free vocabulary (§6) made
    `whatif.language.read` open a What-If on sentences that report what the
    book already did: "which sectors deteriorated the most", "which customers
    had a rating downgrade", "borrowers with rising 12-month PD". The
    certified analyses that answer those never ran. **Found by the full
    backend suite, not by the What-If suite** — 79 tests across
    `tests/api`, `tests/evals` and `tests/docs`, all green on the baseline
    with the same data lake. The reader now refuses a sentence that asks, is
    in the past or the perfect, and carries no hypothetical; `deteriorate`
    and `worsen`, which were never in the retired intent's own trigger list,
    are gone from the openers. `TestAReportIsNotAScenario` holds it, twenty
    sentences each way.
12. **A measure that carries a number in its name was read as a size** —
    "12-month PD" was a movement of twelve, "Stage 2" a movement of two, and
    "four quarters ago" a movement of four.
13. **A movement word used as a NOUN was read as an instruction.** "Rank
    sectors by the largest increase" and "the top ten customers by increase
    in ECL" report a movement; they do not ask for one. A movement verb now
    only instructs when it is not preceded by a determiner, a superlative or
    a preposition — `and` excluded, because "reduce collateral and increase
    PD" is still two instructions.
14. **Verbs that move something without naming a risk parameter now need a
    size.** "Add their latest internal rating" adds a column to the answer on
    screen; reading it as a scenario took a thread's follow-up away from the
    conversation that owned it. Only `downgrade`, `upgrade`, `cure` and
    `migrate` open a What-If unaided. "Which borrowers are weakening" is a
    screen; "weaken DSCR by 20%" is a scenario.
15. **Sixteen figures broke the display contract**
    (`scripts/check_decimals.py`). The CCF now reads as a percentage, the
    macro line as a PD effect, the Delta tiles as effects rather than
    four-decimal multipliers, and the governed 1.082 is quoted as the
    +8.2% weighting it is. The ML model page is allowlisted with its
    reason, following the precedent of `backend/scorecard/metrics.py`:
    an R² of 0.9976 shown as 1.00 makes every candidate look like the
    champion, and a SHAP contribution rounded to 0.00 stops the
    contributions summing to the prediction they explain.
16. **Four new pages carried no curated judgement**, so
    `docs/FINAL_FEATURE_VERIFICATION_MATRIX.md` did not describe them and
    two tests in `tests/docs` failed. Judgements added, matrix regenerated.
17. **The capability claimed a feature area that did not exist** —
    `product/knowledge.py` named "What-If Analysis" while
    `backend/proof/matrix.py` had no such area. Eight proof rows added,
    with the browser and test evidence for each.

### Pre-existing, found and not fixed

The full suite leaves six failures. Each was reproduced on the baseline
`4f79566`, in a worktree pointed at this installation's data lake, so none of
them is this work's:

| Test | What it is about |
|---|---|
| `evals/test_multi_analysis_response::test_the_exposure_block_reconciles_with_an_independent_read` | reconciliation |
| `evals/test_properties::test_a_share_is_of_the_population_asked_about` | reconciliation |
| `evals/test_properties::test_customer_level_exposure_reconciles_with_the_facility_book` | reconciliation |
| `exports/test_workbooks::test_it_writes_real_excel_formulas` | workbook formulas |
| `exports/test_workbooks::test_the_formulas_reconcile_against_the_runtime_values` | workbook formulas |
| `proof/test_fresh_clone_acceptance::test_the_only_live_domains_are_the_seven` | test-order pollution |

- **`test_the_only_live_domains_are_the_seven`
  fails when the whole suite runs**: a `Test Domain` registered by an earlier
  test module is still in the registry. Reproduced on the **baseline**
  `4f79566` with the same data lake, so it is not this work's. Left alone
  deliberately — fixing test-order pollution in the domain registry is a
  change to shared machinery this branch has no reason to touch.
- **The two universe generators overwrite each other's catalogue.**
  `scripts/generate_saudi_universe.py` and `scripts/build_corporate_universe.py`
  each rewrite `metadata/catalog.json` wholesale, so whichever ran last
  unregisters the other's datasets. CI now runs both, in order; a developer
  who runs one alone will silently lose the other book.

## 12. Known limitations

- **R² of 0.998 is mechanical.** On this book the reported ECL is close to a
  closed form, so a model given PD, LGD and Stage can reproduce the rate almost
  exactly. Stated on the model card and on the ML page, above the metrics.
- **Macro variables are not ML features.** The observed series are generated
  from one latent cycle factor, so GDP, oil and the policy rate are collinear
  by construction — sixteen independent observations, not fifty thousand. The
  ten-variable macro What-If runs on **declared sensitivities**, which is both
  honest and what a scenario committee actually uses. User-facing macro
  functionality is not reduced.
- **Rule A and Rule B are off by default** (see §4).
- **Seven of ten macro variables have no observed level** in this installation.
- **No contractual cash-flow engine**, by scope: no cash-flow projection, no
  lifetime PD term structure, no EIR discounting.
- **Covenants are reported, not re-tested** under stress — a pre-existing
  open item carried forward.
- **Scenario execution is synchronous.** Full-book runs are fast enough
  in-request; a scenario grid or reverse stress would need a job path.
- **`stress_scenario_basic` is isolated, not deleted.** Direct API execution
  still works, by design.
- **Sector-specific macro sensitivities are not applied** by the V1 matrix: the
  ten variables carry book-wide PD multipliers.

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

**Staging — two rule sets, kept apart.** `backend/whatif/staging.py` layers over
`backend/ifrs9/policy.py` and holds two policies that never meet.

| Rule | Basis | Reported book | What-If |
|---|---|---|---|
| Relative PD increase (≥2× origination AND ≥2.00pp) | Governed | on | on |
| Absolute PD level (≥13%) | Governed | on | on |
| Days past due (≥30) | Governed | on | on |
| **Rule A** — rating deterioration ≥2 notches | **Assumption** | off, not switchable | **on** |
| **Rule B** — PD ≥2× the pre-scenario level | **Assumption** | off, not switchable | **on** |

`staging.reported()` is what staged the accounts. It reproduces
`policy.stage_of` **elementwise** on a hard random frame, and reproduces the
reported `stage` column on all **3,244 borrowers** of the real book — a second
*reading* of one source of truth, not a second source. It is not editable:
`with_rule`, `added`, `removed` and `combined` all refuse on it.

`staging.default()` is what a **scenario** is staged on, and Rule A and Rule B
are **on**. The baseline column of every comparison is the reported book's own
Stage, so enabling them moves names in the What-If column and cannot move one
in the accounts: a four-notch downgrade leaves the book's Stage distribution
and its reported ECL identical to the riyal, and
`test_the_historical_book_is_untouched_by_the_whatif_rules` says so.

Measured on this book, a two-notch downgrade at Q2 2026 moves **2,528**
borrowers to Stage 2 under the What-If rule set against **518** under the
reported one. Rule A and Rule B agree on rating shocks — notching moves PD by
the masterscale ratio, so two notches is also roughly a doubling — and part
company on a PD shock, which Rule A cannot see, and on a single notch at 1.7×,
which Rule B cannot. Both directions are tested.

A thread may edit thresholds, switch rules on or off, add a rule, remove a
non-governed one, and choose whether a borrower needs **ANY** or **EVERY**
enabled rule to trip. Each edit is validated by `POST /whatif/staging` before
it reaches a run, and the resulting fingerprint is stamped on every result and
saved with the What-If. No rule reaches Stage 3 in either direction; the
default presumption is not a staging opinion.

The engine has **one** staging path: a caller that passes no criteria gets
`reported()`. `ScenarioState` no longer mirrors Rule A into the scenario-level
`rating_deterioration_sicr` assumption either — the rule set owns it, so there
is one implementation of the rule rather than two.

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

## 7b. Stage-aware: the measurement that chose the design

The requirement is a stage-aware model, and there are two ways to build one.
Both are fitted and scored out of time on **every** training run
(`train.stage_study`), so the choice is re-measured rather than asserted.

| Out of time, Q1–Q2 2026 | Single model, Stage as a feature | One model per Stage |
|---|---|---|
| R² (book) | **0.997645** | 0.997522 |
| RMSE | **0.003814** | 0.003913 |
| Exposure-weighted MAE | **0.000738** | 0.000771 |
| WAPE | 3.1529 | **3.1499** |

The book-level metrics are what the What-If actually uses, because the
anchoring is a ratio of two book-level predictions. Separate models win only on
unweighted WAPE, which is dominated by tiny Stage 1 exposures.

**The boundary decides it.** A What-If's job is moving names from Stage 1 to
Stage 2. The governed measurement says that crossing is worth **4.07×** for
these borrowers. The single model reproduces it at **4.09×** (+0.4%); separate
models jump **4.38×** (+7.7%), because two models fitted apart do not share a
calibration level and the gap lands on exactly the borrowers a scenario moves —
in the Stage holding **71% of the ECL on 14% of the exposure**.

| Stage | OOT rows | Share of ECL | Single model R² | Separate model R² |
|---|---|---|---|---|
| 1 | 5,016 | 9.3% | 0.9060 | 0.9821 |
| 2 | 1,069 | 70.8% | 0.9957 | 0.9956 |
| 3 | 276 | 19.9% | 0.9970 | 0.9952 |

Stage 1 alone is better fitted separately, and it is 9% of the provision.
Stage 3 has 964 training rows and its own model is materially worse.

**And the model is genuinely stage-aware, not stage-labelled.** Shocking PD to
2× *inside* each Stage moves the predicted rate **1.68× in Stage 1, 1.25× in
Stage 2, 1.17× in Stage 3**. Nothing crosses the staging line in that test, so
it is the model reading the rest of the borrower differently either side of it.
`test_the_stages_respond_differently_to_the_same_shock` fails if those
responses ever converge.

## 7c. What moved the provision — exact Shapley

`backend/whatif/attribution.py` splits the ECL movement across the drivers of
the scenario: rating, macro, financial, PD, Stage, LGD, collateral, CCF, EAD,
and the policy clamps.

The engine records each driver's before and after on PD, LGD and EAD as it
applies each shock. Those ratios telescope — read on the **applicable** PD, so
the lifetime transform cancels rather than leaving a residual — so the drivers
multiply back to the whole measurement movement exactly. The coalitional game
is then `V(S) = the book's ECL with exactly the drivers in S moved`, and
`decomposition.shapley_of` splits it.

That function is the **governed** one. `decomposition.shapley` was refactored to
call it, so order-neutrality has one implementation and two callers rather than
a weaker parallel attribution.

A three-shock scenario (two notches, LGD +5pp, policy rate +200bps) at Q2 2026:

| Driver | Effect (SAR mn) | Share |
|---|---|---|
| Rating migration | 42,012.1 | 60.4% |
| Stage migration (change of measurement basis) | 16,943.2 | 24.4% |
| Loss given default | 6,748.5 | 9.7% |
| Macroeconomic shock | 3,824.5 | 5.5% |
| **Total** | **69,528.3** | 100% |

It reconciles to the last decimal. A driver the scenario never touched gets
**exactly zero** and is listed as unmoved rather than dropped. The clamps are a
named driver, so a shock that ran into the PD ceiling is not credited with the
effect it asked for.

**This is not SHAP.** SHAP explains one XGBoost prediction from a borrower's
features; this explains a scenario's ECL movement from what the scenario
changed. Where the ML methodology prices the same shocked book differently, the
difference is its own labelled line — on a PD +20% scenario, Delta +5,713.5 and
ML +5,330.4, with **−383.2** shown as "ML model adjustment" — and is never
folded into a driver that did not cause it.

## 7d. The schema contract with the Corporate universe

`backend/whatif/schema.py` is the one place that answers what the book carries.
Every What-If read goes through it.

**The canonical decision.** `cash_conversion_cycle_days` keeps its name. It was
never renamed and there is no mapping to add — it is generated by
`universe.build_financials`, declared by `lineage.FIELDS`, published by
`snapshot.assemble` and registered in the catalogue, all under that one name.
What changed is its **classification**: it is OPTIONAL, and so is every other
field that is not one of the thirteen the governed measurement multiplies
together.

| | Fields | Missing one means |
|---|---|---|
| `REQUIRED` | 13 — ids, sector, rating, stage, PD 12m, PD lifetime, LGD, EAD, reported ECL, DPD, default flag | There is no ECL. Refused by name, with the dataset and the rebuild command. |
| `OPTIONAL` | 31 on the snapshot, 4 on the measurement dataset | Exactly the capability that field names, and nothing else. Reported on the result. |

Each optional field carries the sentence describing what its absence costs, so
the warning a reader sees is actionable:

> `'cash_conversion_cycle_days'` is not in `corporate_borrower_360` in this
> installation, so shocking the cash conversion cycle is unavailable. Every
> other figure below is unaffected. Rebuild the book with
> `uv run python scripts/build_corporate_universe.py` to restore it.

**Columns are resolved from the Parquet, never from the catalogue.**
`DuckDBSource.fields()` returns what the governed catalogue *declares*;
`DuckDBSource.columns()` — added for this — returns what the file *contains*,
as the intersection across partitions. A SELECT binds against the file, so the
engine now asks the file. `GET /whatif/schema` serves the three-way comparison
(contract, catalogue, data) and reports `healthy: false` when they diverge,
even where every scenario still prices correctly.

**A shock the book cannot answer is refused, not skipped.** `_apply_financial`
used to `return` silently when its column was absent, which on screen is
indistinguishable from a shock that moved nobody. It now raises
`ShockUnavailable`, which the router turns into a 422 carrying the reason.

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
| What-If suite | `uv run pytest tests/whatif tests/ifrs9` | **335 passed** |
| Full backend | `uv run pytest` | **12,993 passed, 37 skipped, 6 failed** — the same six as before this work, every one reproduced on the baseline `4f79566` with the same data lake and the same database; named in §11 |
| Backend lint | `uv run ruff check .` | clean |
| Frontend types | `npx tsc --noEmit` | clean |
| Frontend lint | `npm run lint` | clean |
| Frontend tests | `npm test` | **542 passed** |
| Production build | `npm run build` | all routes built |
| Migrations | `uv run alembic upgrade head` + `heads` | **single head 0041** |
| Browser journeys | `node scripts/acceptance/whatif_journeys.mjs` | **11/11, 114/114 checks** |
| Schema contract | `uv run pytest tests/whatif/test_whatif_schema_contract.py` | **28 passed**, including the reported defect reproduced on a real lake |
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

18. **A missing optional column stopped every What-If.** `engine._read`
    resolved its column list from `DuckDBSource.fields()` — the governed
    CATALOGUE — and then named those columns in a DuckDB SELECT. Where a
    catalogue and a Parquet came from different builds they disagreed, and
    DuckDB answered `Referenced column "cash_conversion_cycle_days" not found
    in FROM clause`, which reached a credit officer as "CreditProbe could not
    complete that request". A working-capital statistic that no ECL
    calculation needs had stopped the whole product. **Found by manual
    acceptance testing on a separately generated universe**, not by any suite
    here, because this installation's catalogue and lake were built together
    and agreed. Fixed at source: see §7d. `tests/whatif/test_whatif_schema_contract.py`
    rebuilds a real lake with the column removed and runs every journey
    against it, and a structural test fails if any What-If module goes back to
    `fields()`.

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
- **Rule A and Rule B apply to the SCENARIO only.** They are on by default in
  the What-If rule set and cannot be switched on in the reported-book one —
  the two are separate policies and `staging.reported()` refuses every edit.
  That is the design, not a shortfall: a What-If assumption has no business
  restating the accounts.
- **The driver attribution is exact but bounded.** More than twelve moving
  drivers and it refuses rather than approximating, because an exact Shapley
  is 2^n coalitions. This engine has ten drivers, so the cap is a guard nobody
  meets.
- **Per-Stage models were measured and not adopted.** The evidence is in §7b;
  Stage 1 alone would be better fitted separately, and that is 9% of the
  provision against a 7.7% bias at the boundary where 71% of it sits.
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

# What-If Analysis — Product Specification

**Status:** Approved. This document is the product source of truth for the What-If
Analysis capability in CreditProbe.

**Branch:** `claude/what-if-analysis-rebuild`
**Baseline:** `origin/claude/integration-rehearsal` @ `4f7956666feca2822cc74effd335823ba1a391e9`

This specification is written to be read without the conversation that produced it.
Where the original product discussion assumed repository facts that turned out to be
different, the **business intent is preserved and the adaptation is stated explicitly**
in *Adaptations from the original discussion* (§A) rather than silently dropped.

---

## 1. Core product purpose

The umbrella capability formerly called **Stress Testing** becomes **What-If Analysis**.

The core product question is always:

> "If I change one or more risk assumptions, what happens to ECL, and why?"

Everything reconciles along this chain:

```
Official Baseline ECL
  → What-If Scenario
    → Revised Risk State
      → What-If ECL
        → Absolute ECL Change
          → Percentage ECL Change
            → Explanation of ECL Drivers
```

Rating, Stage, PD, LGD, CCF, EAD, collateral, haircut, macro variables, sectors and
borrowers are **drivers**. The ultimate product output is the **ECL impact**.

## 2. Terminology

The left-hand navigation entry is renamed **Stress Testing → What-If Analysis**.
There must be no user-facing umbrella capability called "Stress Testing" — in
navigation, titles, breadcrumbs, tooltips, empty states, assistant copy, page
descriptions or routing labels.

The scenario labels **Sector Stress** and **Borrower Stress** are explicitly approved
and remain. Internal/legacy identifiers may remain where renaming them would create
avoidable regression risk, provided the user-facing experience is clean.

## 3. Domain restriction — Corporate IFRS 9 only

What-If Analysis is **hard-bound to the Corporate IFRS 9 domain**. The runtime
enforces:

```
WHAT_IF_ANALYSIS → CORPORATE_IFRS9 → NO GENERAL DOMAIN SEARCH
```

This is deliberate, and buys speed, determinism, calculation reliability, prompt
efficiency and hallucination resistance. If a requested field does not exist in the
Corporate IFRS 9 domain, the product **says so** rather than silently joining another
business domain.

Reference configuration required by the What-If module itself — macro sensitivities,
staging policy, model metadata, the rating masterscale — is permitted.

## 4. Landing page — exact order

1. **What-If** (heading, immediately above the composer)
2. Main What-If chat composer
3. Six guided scenario starting points
4. Saved What-Ifs
5. Model Configuration — Delta Model / ML Model — XGBoost
6. Recent What-Ifs

## 5. The chat box

The composer is the principal interaction mechanism and is restricted to What-If
Analysis. A user can type a scenario without clicking any guided card. Worked
examples the product must handle:

- "What happens if Stage 1 PD increases 20%?"
- "Downgrade construction borrowers with exposure above SAR 100m by two notches."
- "Move half the Stage 1 BBB borrowers to Stage 2 and increase LGD by five percentage points."
- "Using Q2 2026, downgrade Stage 1 construction borrowers above SAR 50m by two notches, increase LGD by five points, reduce property collateral by 15% and increase unemployment by one percentage point."

The LLM infers which capabilities are being requested.

## 6. Six guided starting points

Displayed immediately below the composer. **Shortcuts, not restrictions** — a user may
combine several in one free-text instruction. Clicking one opens a dedicated
conversational What-If thread.

1. Rating Movement
2. IFRS 9 Risk Parameter Adjustment
3. Stage Migration
4. Macroeconomic Shock
5. Sector Stress
6. Borrower Stress

## 7. Clickable choices plus free text

Wherever CreditProbe asks a finite-choice question it offers clickable chips —
`PD | LGD | CCF`, `Stage 1 → Stage 2 | Stage 2 → Stage 3 | Stage 2 → Stage 1 |
Stage 3 → Stage 2`, `Latest period | other available periods`,
`Delta Model | ML Model`. The free-text composer is **always** retained; the user may
ignore the chips and type a more complicated instruction.

## 8. Chat is the scenario builder

Not a rigid form wizard. The interaction philosophy is:

```
show relevant portfolio facts
  → user understands the current book
    → ask what the user wants to change
      → gather genuinely missing inputs
        → restate what CreditProbe understood
          → ask ECL methodology if required
            → execute deterministic/ML scenario
              → explain results
                → leave chat open
                  → allow additional scenario layers
```

The LLM acts as risk analyst, scenario interpreter, clarification engine,
orchestration layer and narrator. **It is not the calculator.** It must never invent
PD, LGD, ratings, Stages, populations, ECL or calculation results.

## 9. MANDATORY — ECL methodology selection before calculation

Before CreditProbe performs an ECL impact calculation it **must explicitly ask**:

> "Which ECL methodology should I use for this What-If?"

with clickable **DELTA MODEL** / **ML MODEL** plus free text.

- Do **not** silently choose Delta. Do **not** silently choose ML.
- Do **not** calculate the final ECL impact until the methodology is resolved.
- The interaction must make the difference understandable:
  - *Delta Model* — transparent deterministic sensitivity using official ECL and
    relative PD/LGD/EAD changes.
  - *ML Model* — XGBoost-based nonlinear response learned from historical Corporate
    IFRS 9 outcomes, anchored to official baseline ECL.

The question occurs at the **calculation boundary**, after dataset resolution,
sufficient scenario clarity, population resolution and known staging assumptions.

For the **first executable ECL scenario in a thread** methodology selection is
mandatory. The selection persists as the **active thread methodology**. For later
layered calculations in the same thread the active methodology is shown with a visible
option to keep or switch; it is **never silently switched**. If a calculation has no
current methodology, ask again.

If the user's instruction already says "Use ML" or "Calculate this with the Delta
Model", do not redundantly ask — confirm and proceed.

Every result shows `ECL Methodology: Delta Model v…` or `ML Model — XGBoost v…`.
The saved What-If persists the selected method and version.

## 10. Dataset behaviour

Corporate IFRS 9 publishes 16 quarters, **Q3 2022 → Q2 2026**, resolved **dynamically**.
Q2 2026 is never permanently hardcoded.

- Descriptive guided-journey opening analysis: user-selected period if specified,
  otherwise latest available; the period is always stated.
- Executable scenarios: use the known period; resolve "latest" on request; ask only if
  genuinely unresolved. Do not re-ask once resolved.

## 11. Scenario thread state

Structured state is persisted; the product does not rely on the chat transcript alone.
Conceptually: thread id, base dataset, base period, scenario steps, active staging
rules, active ECL methodology, model version, macro sensitivity version, structured
population filters, structured transformations, original user wording, interpreted
wording, calculation results. Existing CreditProbe persistence patterns are used rather
than inventing new architecture.

## 12. Cumulative / layered scenarios

A thread supports sequential scenario construction:

```
Baseline → unemployment +1pp → Stage 1 PD +20% → construction LGD +5pp → rating downgrade
```

Each new instruction operates on the **current** scenario state. Supported operations:
add, edit, remove, undo, reset, modify an earlier step, recalculate downstream steps.

The user can say: "Remove the unemployment shock." / "Change PD increase from 20% to
15%." / "Keep everything else but downgrade three notches." / "Reset to baseline."

---

## 13. Journey — Rating Movement

### 13.1 Opening analysis

Open a thread; use the selected/latest Corporate IFRS 9 period; show the current
**14-grade** rating profile with, where the data supports it: Rating, account/customer
count at correct grain, count proportion, exposure, exposure proportion, average 12m PD,
average lifetime PD where meaningful, stage-appropriate/current PD, average Stage,
average LGD, average CCF, baseline ECL, and a **Total** row.

### 13.2 Rating migration

Immediately below the current profile, show the one-year migration — for Q2 2026 that
is **Q2 2025 → Q2 2026** — as a **15 × 15 displayed matrix** (14 grades + Total
row/column).

Selectable views: Account Count, Account %, Exposure Amount, Exposure %. Row-normalised
migration percentages are provided where useful.

Correctly handle matched continuing entities, new accounts, exited accounts and
duplicate facilities. **Never fabricate migrations.**

### 13.3 The rating question

After distribution and history, ask: *"What kind of rating migration would you like to
simulate?"* Supported rules include:

- "Downgrade everyone one notch."
- "Move rating X to rating Y."
- "Downgrade only Stage 1 borrowers two notches."
- "Downgrade 50% of customers with exposure over SAR 100m."
- "Downgrade construction Stage 1 borrowers."
- "Select the largest 25% of exposures in rating X and downgrade them."

Compound population rules are supported.

### 13.4 The calculation chain

```
population selection → rating change → new rating-linked PD → SICR check
  → Stage migration if triggered → stage-appropriate PD
    → ECL methodology selection → ECL calculation → attribution
```

The governed rating→PD logic is used. The existing notching behaviour — applying the
masterscale PD **ratio** while preserving within-grade calibration — is preserved
because it is the governed Corporate IFRS 9 logic.

### 13.5 Result interpretation

Before charts, explain in plain English: dataset, population, count, exposure, baseline
risk profile, source rating, destination rating, rating rule, SICR result, number moving
Stage, applicable PD, selected ECL methodology and version.

### 13.6 Source/destination reconciliation

For the **source** rating: exposure before/after, ECL before/after, ECL reduction from
leaving accounts. For the **destination** rating: exposure before/after, ECL
before/after, ECL increase from incoming accounts. Then reconcile the total book.

### 13.7 Visuals

Affected-rating exposure before/after; affected-rating ECL before/after; Stage 1/2/3
exposure before/after; Stage 1/2/3 ECL before/after; ECL bridge / attribution. If Stage
migration occurs, both narrative and charts must show it.

---

## 14. Journey — IFRS 9 Risk Parameter Adjustment

Open a thread; show the selected/latest dataset; provide baseline information for **PD,
LGD, CCF** and, where available, EAD, collateral, haircut, exposure, ECL. Then ask which
risk parameter the user wants to analyse or change.

### 14.1 PD — inform before configure

**Stage 1:** 12m PD average, median, min, max, percentiles, highest-PD names where
useful, PD by rating, PD by sector, PD by segment if available, associated exposure,
associated ECL.

**Stage 2:** lifetime PD average, median, min, max, percentiles, highest-PD names, PD by
rating, PD by sector, PD by segment if available, associated exposure, associated ECL.

**Stage 3:** explain the actual configured methodology.

**Never** misleadingly combine Stage 1 12m PD with Stage 2 lifetime PD.

### 14.2 PD scenarios

Support relative percentage, percentage points, basis points, and Stage / rating /
sector / segment filters plus compound rules:

- "Increase Stage 1 PD by 20%."
- "Add 100 bps to BBB Stage 1 PD."
- "Increase Stage 2 lifetime PD by 15%."
- "Increase Stage 1 PD 20%, reduce Stage 2 PD 10%, but increase BBB PD 30%."

Overlapping rules are resolved explicitly.

### 14.3 Percentage semantics

| Form | Example |
|---|---|
| Relative | PD 2.00% +20% → **2.40%** |
| Percentage points | PD 2.00% +2pp → **4.00%** |
| Basis points | PD 2.00% +100bps → **3.00%** |

Clarify only when materially ambiguous.

### 14.4 LGD / collateral / haircut

If LGD is selected show: average, median, min/max, by Stage, by sector, by segment where
available, secured LGD, unsecured LGD, associated exposure, associated ECL. Also show
actual collateral types with gross collateral, haircut, post-haircut collateral, exposure
secured, coverage and LGD where available.

Then ask: Adjust LGD / Adjust Collateral / Adjust Haircut. Examples: "Increase unsecured
LGD five percentage points." / "Reduce construction collateral by 20%." / "Increase
commercial-property haircut 10 percentage points."

### 14.5 CCF / EAD

Show distribution, average/median, by product/facility, by sector, undrawn commitment,
EAD, ECL. For CCF changes, calculate the **actual EAD movement**. Do not assume a CCF %
movement equals an ECL % movement.

---

## 15. Journey — Stage Migration

### 15.1 Opening view

For Stages 1, 2 and 3: count, proportion, exposure, exposure proportion, ECL, ECL
proportion, relevant PD, average LGD, average CCF.

### 15.2 Historical stage migration

One-year **3×3** migration — for Q2 2026 that is Q2 2025 → Q2 2026 — with views for
account count, account %, exposure and exposure %. Include both deterioration and
curing: S1→S2, S2→S3, S2→S1, S3→S2.

### 15.3 Stage scenarios

Ask *"What stage movement would you like to simulate?"* Support proportions, exposure
percentages, rating filters, sector filters, PD filters, complex free-text logic, curing
and deterioration. Stage changes **must update the applicable PD before ECL estimation**.

---

## 16. Journey — Macroeconomic Shock

### 16.1 The ten CreditProbe V1 macro variables

1. GDP Growth Rate
2. Unemployment Rate
3. House Price Index
4. Inflation Rate
5. Current Account Balance / Deficit
6. Stock Market Index
7. Policy Interest Rate
8. Domestic Currency / FX Depreciation
9. Oil Price
10. Corporate Credit Spread

### 16.2 Reference sensitivities — CreditProbe What-If V1

These are **configurable CreditProbe What-If reference sensitivities**. They are
**never** described as universal IFRS 9 coefficients. Stored centrally and configurably.

| Variable | Adverse unit | PD multiplier | LGD change |
|---|---|---|---|
| GDP growth | −1.0 pp | ×1.10 | +0.75 pp |
| Unemployment | +1.0 pp | ×1.12 | +1.00 pp |
| House Price Index | −10% relative | ×1.06 | +2.50 pp |
| Inflation | +2.0 pp | ×1.05 | +0.50 pp |
| Current-account deterioration | +2.0 pp of GDP | ×1.03 | +0.25 pp |
| Stock Market Index | −20% | ×1.05 | +0.50 pp |
| Policy Rate | +200 bps | ×1.08 | +0.50 pp |
| Currency depreciation | +10% | ×1.05 | +0.25 pp |
| Oil Price | −20% | ×1.05 | +0.50 pp |
| Corporate Credit Spread | +100 bps | ×1.08 | +0.50 pp |

### 16.3 Scaling

```
PD_new  = PD_old × multiplier ^ (number_of_adverse_units)
LGD_new = LGD_old + LGD_change_per_unit × shock_units
```

Capped between 0% and 100%. Favourable shocks work in the opposite direction.

### 16.4 Relative vs absolute

Unemployment = 5%. "Increase unemployment by 30%" is **relative**: 5% → 6.5%, i.e.
+1.5 percentage points. It is **not** +30 percentage points.

### 16.5 UI

All ten variables shown with latest/base value, recent trend, PD sensitivity and LGD
sensitivity, using compact mini charts. Desktop layout is a responsive three-column grid
(3 / 3 / 3 / 1).

---

## 17. Journey — Sector Stress

Opening profile shows the **actual** sectors. For each: count, proportion, exposure,
exposure %, 12m PD where relevant, lifetime PD where relevant, average/median PD, average
LGD, collateral, collateral coverage, haircut, average CCF, ECL, ECL/exposure.

A detailed rating distribution is **not** shown by default. Then ask which sector and
what What-If change to apply.

---

## 18. Journey — Borrower Stress

Opening screen shows **Top 10 Stage 2 Borrowers by ECL** at true borrower/customer grain,
with columns such as customer ID, name, sector, rating, Stage, exposure, PD, LGD,
collateral, CCF, ECL. The user may click a borrower or type another borrower ID.

### 18.1 Borrower history

Approximately two years, as available: ECL trajectory, exposure trajectory, rating
trajectory, and where available Stage, 12m PD, lifetime PD, LGD, CCF, collateral,
haircut.

### 18.2 Result levels

Results are shown at three levels — (1) borrower, (2) borrower's sector, (3) overall
Corporate IFRS 9 book — each with ECL before, ECL after, ECL delta and relevant exposure.

---

## 19. Staging / SICR

### 19.1 Default configurable What-If rules

**Rule A** — rating downgrade ≥ 2 notches → SICR → Stage 1 → Stage 2.
**Rule B** — relevant PD ≥ 2 × baseline/reference PD → SICR → Stage 1 → Stage 2.

These are **configurable CreditProbe What-If assumptions**, never described as universal
IFRS 9 requirements.

### 19.2 One governed source of truth

There is a single governed source of truth for the **Corporate** What-If staging policy.
The separate credit-book generator logic, whose constants intentionally differ, is **not**
consolidated into it. Consolidation scope is Corporate IFRS 9 / What-If only.

### 19.3 Staging criteria UI

Every What-If thread exposes **Staging Criteria** near the top, allowing the user to view
rules, edit thresholds, enable/disable rules, add rules, combine rules with AND/OR and
apply thread-level overrides. The rule set and its version are persisted with the saved
What-If and the calculation trace.

---

## 20. ECL Model 1 — Delta Model

Transparent and deterministic. Official client ECL remains the anchor.

```
What-If ECL = Official Baseline ECL × PD factor × LGD factor × EAD factor
```

after rating and staging logic resolves the relevant parameters.

**PD example.** 2.00% → 2.40%; factor 2.40/2.00 = 1.20; all else equal and Stage
unchanged, What-If ECL ≈ Baseline ECL × 1.20. If Stage moves 1 → 2, the appropriate
lifetime-PD logic is applied first and the larger stage effect calculated.

**LGD example.** 40% → 44%; factor 44/40 = 1.10; ECL ≈ Baseline ECL × 1.10.

**CCF/EAD.**
```
EAD_before = Drawn + CCF_before × Undrawn
EAD_after  = Drawn + CCF_after  × Undrawn
EAD factor = EAD_after / EAD_before
```
A CCF percentage movement is never equated directly to an ECL movement.

**Combined.** PD 1.20 × LGD 1.10 × EAD 1.05 — multiplied, never added.

### 20.1 Delta Model configuration page

A business-friendly explanation of: purpose, official ECL anchor, as-built formula, PD
mechanics, LGD mechanics, CCF/EAD mechanics, collateral/haircut mechanics, rating
mechanics, Stage mechanics, caps/floors, examples, limitations, model version.

---

## 21. ECL Model 2 — ML Model (XGBoost)

IRLS, the existing deterministic Shapley decomposition, and linear regression are **not**
substitutes for this requirement. The existing exact Shapley decomposition remains
valuable for deterministic scenario attribution but does not replace XGBoost.

### 21.1 Purpose

Learn nonlinear historical relationships between Corporate IFRS 9 risk characteristics
and official ECL outcomes. A +20% PD shock should not necessarily produce exactly +20%
ECL. Interaction drivers include Stage, PD, LGD, CCF, EAD, collateral, collateral
coverage, rating, sector, exposure and other valid IFRS 9 features.

### 21.2 Target

Preferred target is an **ECL Rate** = official ECL / an appropriate exposure denominator.
The actual Corporate IFRS 9 convention is inspected and the denominator documented.
Contemporaneous ECL is never used as a predictor of itself; target leakage is explicitly
tested.

### 21.3 Stage awareness

Prefer distinct Stage 1 and Stage 2 model behaviour. For Stage 3, a dedicated model only
if sample quality is adequate; otherwise preserve governed deterministic treatment. A
statistically weak model is never forced.

### 21.4 Official-ECL anchoring — mandatory

```
baseline_model_rate = model(features_baseline)
shocked_model_rate  = model(features_shocked)
ML Shock Factor     = shocked_model_rate / baseline_model_rate
What-If ECL         = Official Baseline ECL × ML Shock Factor
```

Official client ECL remains baseline truth. Zero/near-zero baseline predictions are
handled safely and the fallback is documented.

### 21.5 Safe artifact format

`.pkl`, `.joblib` and `.pt` are intentionally prohibited due to executable
deserialization risk; that control is **not weakened**. The **XGBoost native JSON** model
format is used — already compatible with the repository security allowlist. UBJSON is not
used. Model features and artifacts must not contain borrower/customer/account identifiers
in ways rejected by the sealing/security system.

### 21.6 Development / validation / OOT

Corporate IFRS 9 spans Q3 2022 → Q2 2026.

- Development universe: through **Q4 2025**.
- Within development: approximately 70% training / 30% validation, **time-aware /
  chronological** splitting, no naive random future leakage.
- **Q1 2026 and Q2 2026 reserved as locked out-of-time validation.** The initial model is
  not trained on them.

### 21.7 Validation metrics

No generic "accuracy %". At minimum **R², MAE, RMSE, WAPE**, plus exposure-weighted error
where useful, sliced by Stage, PD band, LGD band, sector and quarter.

### 21.8 Model card

Model name, version, algorithm, target, features, development periods, validation
periods, OOT periods, observation count, feature count, R², MAE, RMSE, WAPE, OOT metrics,
build timestamp, active/candidate state, known limitations — **including the synthetic
macro-collinearity limitation**.

### 21.9 Out-of-distribution warning

If shock inputs fall materially outside training ranges, warn the user — e.g. *"The
shocked lifetime PD is above the maximum observed in model development. ML uncertainty is
therefore higher."* — and offer a Delta Model comparison.

### 21.10 Explainability

Top Predictors of ECL, XGBoost feature importance, SHAP summary, actual vs predicted ECL
rate, backtest/error by quarter, PD vs predicted ECL, LGD vs predicted ECL; and where
useful CCF sensitivity, collateral coverage sensitivity, error by Stage, sector, PD band
and LGD band.

The existing exact Shapley decomposition is used **separately** for deterministic
ECL-driver attribution. Exact scenario Shapley and ML SHAP are never conflated.

### 21.11 Client X demo

An explicit model-example journey using a borrower with Stage 1, exposure SAR 100m, 12m
PD 2.50%, lifetime PD 8.00%, LGD 35%, CCF 50%, collateral SAR 40m, haircut 20%,
discount/EIR 5%, official ECL SAR 1.80m; shock 12m PD +20% (2.50% → 3.00%). Shows the
baseline ML prediction, shocked ML prediction, ML shock factor, official baseline ECL,
What-If ECL, absolute delta and percentage delta — from **actual demo-model outputs**,
never hardcoded fake results.

Explained with **local SHAP**. If representative tree paths are shown for intuition
(Stage / PD / LGD / collateral-coverage thresholds), it is made clear that XGBoost is an
ensemble and the final prediction comes from the whole ensemble, not one tree.

### 21.12 Preconfigured model

The feature ships demo-ready with a trained, registered initial model showing actual
metadata, validation, explainability, OOT and example. ML Configuration is never an empty
"train your first model" page.

### 21.13 Retraining

The ML Configuration page shows, with dynamically derived periods: *"Active model trained
through Q4 2025. Newer IFRS 9 data is available. Retrain?"* with Retrain / Not now.

It has its own chat composer for conversationally defining training periods, validation
periods, OOT periods, and periods to include/exclude — e.g. "Keep everything through Q4
2025, add Q1 2026 to development and keep Q2 2026 as OOT." — parsed into a structured
model-training configuration.

When confirmed, retraining genuinely: builds the training set, validates grain, checks
leakage, preprocesses, trains XGBoost, validates, runs OOT, calculates metrics, generates
SHAP, generates plots, persists a safe JSON artifact, hashes/seals metadata, creates a new
version and compares against the active model. **Metadata-only updates are not
retraining.**

### 21.14 Active vs candidate

A newly retrained model is a **CANDIDATE**. The active model is never overwritten
automatically. Old vs new R², MAE, RMSE, WAPE and OOT metrics are shown, along with
relevant predictor/SHAP changes, and an explicit **Activate Model** action. Prior versions
are preserved.

### 21.15 Model change log

Persists: model version, predecessor, training periods, validation periods, OOT periods,
excluded periods, target, feature set, hyperparameters, random seed, build/code
identifier where practical, training timestamp, metrics, OOT metrics, explainability
artifact references, actor, candidate/active state, activation timestamp, and reason or
comment if supplied.

---

## 22. Saved and Recent What-Ifs

**Save What-If** persists enough to reproduce: name/title, dataset, period, original
instructions, structured scenario steps, staging rules and version, ECL methodology,
model version, macro sensitivity version, affected population, baseline ECL, What-If ECL,
delta, timestamp.

**Saved What-Ifs** landing area shows cards with name, date, dataset, scenario types,
baseline ECL, What-If ECL, delta, ECL methodology/model. Clicking reopens the
scenario/thread.

**Recent What-Ifs** appears below Model Configuration and may include recent scenario
threads that were not explicitly saved, following existing persistence conventions.

---

## 23. Results

### 23.1 Every result must show context

Corporate IFRS 9 dataset/period, scenario definition, affected population, active staging
criteria, ECL methodology, model version, official baseline ECL, What-If ECL, absolute
change, percentage change.

### 23.2 Result narrative

Naturally covers: what I understood; what I changed; who was affected; Stage impact; ECL
methodology used; ECL result; why ECL changed; portfolio impact. The chat composer then
remains available.

### 23.3 Chat remains open

After every result the composer stays available with contextual follow-up nudges — Add
another shock, Adjust this migration, Change ECL methodology, Show PD impact, Show LGD
impact, Break down by sector, Change staging criteria, Save What-If, Reset scenario —
without constraining free-text entry.

### 23.4 No artificial chart limit

The UI is not limited to one, two or three charts. If the user requests ten relevant
views, they are rendered, using responsive charts, tables, expandable sections and
grouped cards. Irrelevant charts are **not** shown merely because data is numeric.

### 23.5 Pure analysis questions

The What-If chat answers informational questions without forcing a scenario — "Show
Stage 1 PD by sector.", "Show collateral types and haircuts.", "How many Stage 2
borrowers have lifetime PD above 15%?" For informational analysis **no methodology
question is asked**, because no ECL simulation is being calculated. Methodology is asked
only when an ECL impact calculation is about to run.

---

## 24. Scope boundary — no contractual cash-flow engine

A full production IFRS 9 contractual cash-flow accounting engine is **out of scope**.
Not implemented: full contractual cash-flow projections, future-period shortfall loops,
complete lifetime PD term structures, complete lifetime LGD term structures, a full EIR
discounting engine, or a production accounting-engine replacement.

Official ECL remains baseline truth; the product estimates **What-If deltas**.

---

## 25. Cross-cutting requirements

**Grain.** Corporate IFRS 9 is obligor-level by explicit design: `(borrower_id, period)`.
Counts are never inflated through accidental facility duplication. Historical migrations
match entities correctly across periods.

**UI quality.** CreditProbe design conventions: professional layouts, compact analytical
cards, responsive grids, readable tables, tooltips, proper currency/percentage
formatting, model badges, baseline vs What-If visual distinction, persistent composer.
Not overdecorated.

**Failure handling.** Graceful handling of: dataset unavailable, prior-year data
unavailable, no matched migration population, borrower not found, invalid rating, invalid
Stage, invalid percentage, unsupported parameter, collateral type absent, ML model
unavailable, ML OOD scenario, retraining failure, model artifact failure. **Never
silently return misleading zeros.**

**Security / access control.** Existing user scoping, workspace scoping, permissions and
API authorization are preserved. Saved scenarios and model actions must not leak between
users or workspaces. Access-control tests are added.

**Auditability.** Each executable scenario preserves enough to reconstruct: actor,
timestamp, dataset, period, scenario steps, population, rule order, staging rules and
version, rating mapping, macro sensitivity version, ECL methodology, model version,
baseline result, What-If result.

**Performance.** Efficient services for latest period, rating profile, rating migration,
Stage profile, Stage migration, PD/LGD/CCF summaries, sector profile and borrower
history. Unrelated data domains are not repeatedly scanned.

**No fake success states.** Never claim a model was retrained, SHAP generated, a Stage
migrated, ECL calculated, a scenario saved or a model activated unless it genuinely
happened. Demo/proxy data is identified honestly.

**Regression protection.** Cockpit, Data Builder, Investigation, Playbook, Lenses
baseline functionality, project-related baseline functionality present on
integration-rehearsal, existing APIs, navigation, existing Corporate IFRS 9 analysis and
existing decomposition must not break.

---

## A. Adaptations from the original product discussion

Recorded explicitly. In every case the **business intent is preserved**; only the
repository-accurate mechanism differs.

| # | Original discussion | Repository reality | Adaptation |
|---|---|---|---|
| A1 | 19-grade rating distribution | The governed Corporate IFRS 9 masterscale has **14 grades** (13 performing + `D`): AAA, AA, A, BBB+, BBB, BBB−, BB+, BB, BB−, B+, B, CCC, CC, D | Use the 14 governed grades. The universe is **not** regenerated and the synthetic seed is preserved. |
| A2 | 20×20 migration presentation | 14 grades + Total | **15 × 15 displayed** migration matrix including Total row and column. All other requirements (count, proportion, exposure, proportion, risk parameters, prior-year migration, totals, configurable views) unchanged. |
| A3 | Ten empirically independent macro variables for ML | The synthetic macro series are generated from a single latent cycle factor and are **collinear by construction** | The **ten user-facing macro variables and their deterministic configurable sensitivities are retained in full** for What-If execution. For ML, training uses legitimate borrower-quarter cross-sectional and longitudinal signals; macro, if incorporated, is represented by the underlying cycle factor rather than producing misleading SHAP across collinear proxies. The limitation is disclosed on the model card and in the as-built documentation. User-facing macro functionality is **not** reduced. |
| A4 | Rating direction from agency intuition | CreditProbe has a configured rating hierarchy | All notching uses the configured hierarchy. Generic external agency intuition is never used to determine upgrade/downgrade direction. |

## B. Legacy `stress_scenario_basic`

Operates on a different book, a different rating scale and different SICR assumptions.
It must **not** remain a competing user-facing What-If execution route, and it must not be
blindly deleted — the audit found dependencies on historical analysis runs, a seeded
Project, `high_utilisation_watchlist`, a Studio binding, an analyst tool and a planner
intent.

It is **isolated as legacy/internal**: new user-facing and LLM routing paths to it are
removed while backward compatibility is preserved. At minimum, the new What-If user and
LLM routes cannot execute it.

Its broad trigger vocabulary is **absorbed** into the new What-If routing so that
magnitude-free questions — "Stress the real estate portfolio.", "Use the severe
scenario.", "What if this deteriorates?" — **begin a What-If conversation** rather than
falling through unmatched.

# Predeclared acceptance targets for the ECL emulators

**Written and committed before any model is fitted and before the held-out
test split is read.** That ordering is the point of this document. Section
11.5 asks for targets to be declared up front, and a threshold chosen after
seeing the result is not a threshold — it is a description of the result.

This file is the contract. `docs/whatif/MODEL_CARD_CORPORATE.md` and
`MODEL_CARD_RETAIL.md` will report the measured values against it, **pass or
fail**, and a failure stays a failure. If a gate is missed, the model card
says so, the method reports its limitation to the reader, and the number is
not quietly published as if it had passed.

> The target these models predict is the **declared ECL rate** on the
> documented denominator, produced by `reference_ecl.py` on a generated
> book. Passing every gate below establishes that an emulator can learn that
> calculator on that book. It does **not** establish agreement with any
> bank's ECL engine, and no document may say it does.

---

## 1. What is being predicted

**Target.** `ecl_rate` as published in `whatif_*_ifrs9` — the declared ECL
over the declared denominator (`ead_sar_mn`), converted back to currency for
every currency-denominated metric below. **Not** ECL as a share of total
exposure: a share target makes a model that predicts the portfolio's mix
score well while getting every facility wrong.

**Excluded from X, and asserted absent.** `ecl_sar_mn`, `ecl_12m_sar_mn`,
`ecl_lifetime_sar_mn`, `ecl_modelled_sar_mn`, `ecl_overlay_sar_mn`,
`ecl_rate`, `ecl_coverage_pct`, `expected_shortfall_sar_mn`, and every
column of `whatif_*_term_structure`. A test enumerates the feature list and
fails if any target-derived name appears in it.

**A declared reference model.** P5a found that the candidate's Stage 1 ECL
sits about 4% away from `ead × pd × lgd`, so a naive product already
recovers most of the target. The model card therefore reports that
predictor's metrics beside the blend's on the same split. A blend that does
not beat it is reported as not beating it.

## 2. The split, fixed before anything is fitted

Chronological by **distinct reporting period**, 60 / 20 / 20:

| Book | Periods | Train | Validate | Test | Embargoed |
|---|---|---|---|---|---|
| Corporate | 20 quarters | 11 | 3 | 4 | 2 |
| Retail | 20 months | 11 | 3 | 4 | 2 |

The shares are 60 / 20 / 20 by distinct period — 12 / 4 / 4 — and the
**one-period embargo at each boundary** then takes the last training period
and the last validation period out of the fit entirely. They are reported as
their own count rather than folded into a neighbour: a period nobody trained
on and nobody tested on is a period the card should show.

* Expanding-window folds inside the development window (train + validate,
  14 periods) only. No embargoed period and no test period appears in any
  fold, on either side.
* The embargo is derived from label availability and its reasoning is
  recorded with it: every input the calculator reads is published as at the
  reporting date, so a label is knowable then; the embargo exists to stop
  adjacent periods sharing an overlapping twelve-month window across a split
  boundary, not to wait for an outcome.
* Every preprocessing statistic, every hyperparameter and every blend weight
  is fitted **inside** its authorised window. Nothing is fitted on the test
  periods, and nothing is refitted after they are read.
* The split assignment is persisted per row, so the card's counts can be
  checked rather than trusted.

**The test split is read once**, to produce the numbers below. A model that
misses a gate is reported as missing it. Any retraining creates a **new
model version** with its own card and its own single read of the test split.

## 3. The gates

Measured on the **out-of-time test periods**, in currency, on the blend's
final prediction function.

| # | Gate | Threshold |
|---|---|---|
| **G1** | Out-of-time currency WAPE | **≤ 10%** |
| **G2** | Aggregate bias, \|Σ(pred − actual)\| ÷ Σ actual | **≤ 2%** |
| **G3** | Per-period bias, worst test period | **≤ 5%** |
| **G4** | WAPE in every material group | **≤ 15%** |
| **G5** | Zero shock ⇒ exactly zero ML change | **exact** |
| **G6** | Perturbation direction agrees with `reference_ecl.py` | **≥ 90% of probes** |

**WAPE** is `Σ|pred − actual| ÷ Σ|actual|` in SAR mn, over the test rows.
Chosen over MAPE because MAPE is unbounded on the near-zero ECLs a Stage 1
book is full of, and a single facility with a 0.0001 actual would otherwise
decide the metric.

**A material group** (G4) is a group with **at least 100 test observations**.
Groups reported: Corporate — sector, stage, rating grade, region, facility
class. Retail — product, stage, employer sector, region, score band. Groups
below 100 observations are reported with their counts and **excluded from the
gate rather than from the table**, so a reader sees them and sees why they
are not being judged.

**G5** is arithmetic, not a tolerance: section 11.4's anchoring is
`ML_change = P1 − P0`, and with an unchanged input `P1` and `P0` are the same
call on the same vector.

**G6** probes the fitted function against the independent calculator —
raise a driver, does the prediction move the way `reference_ecl.py` moves?
The calculator is kept out of training and out of tuning entirely, which is
what makes it a check rather than a second label.

## 4. Component and blend gates

Section 11.3 asks for a blend that is a blend.

| # | Gate | Threshold |
|---|---|---|
| **B1** | Components | **3 per book**: XGBoost, LightGBM, and a regularized additive/spline model |
| **B2** | Weights | non-negative, summing to 1, fitted on **out-of-fold** predictions by a deterministic constrained optimiser |
| **B3** | Materiality | a component with weight **< 0.05** is reported as immaterial, by name |
| **B4** | Honesty | a `1 / 0 / 0` outcome is reported as **a single-model result**, not relabelled a blend |

**B4 is the one that matters.** If the optimiser puts everything on one
component, the deliverable is a single model and the card says so in those
words. A hardcoded mixture presented as a fitted blend, or a single-model
result presented as an ensemble, is the failure this gate exists to prevent.

## 5. The search budget, declared in advance

| Bound | Value |
|---|---|
| Configurations per family per book | **≤ 12** |
| Cross-validation folds | **≤ 3** |
| Boosting rounds | **≤ 600**, early stopping patience **50** |
| Seeds | fixed and recorded per component |
| Trials | every configuration and its validation score recorded in the card |

The budget is declared so that "we tried until it passed" is visibly not what
happened. Exhausting it without meeting a gate is a **failure to report**,
not a reason to raise the budget.

## 6. What a failure looks like

If a gate is missed, all of the following happen and none of them is
optional:

1. The model card records the measured value beside the threshold and marks
   it **FAILED**.
2. `whatif_*_model_metric` carries the measured value, not a blank.
3. Method 2 reports its status to the reader with the gate that failed named,
   rather than returning a number that looks like the other methods'.
4. `REQUIREMENT_TEST_MATRIX.md` marks the corresponding M-requirement
   **PARTIAL** or **BLOCKED**, with the reason.
5. This file is **not edited**. A threshold moved after the fact is not a
   threshold.

## 7. What passing does and does not establish

**Does:** that a gradient-boosted blend can reproduce `reference_ecl.py`'s
output on this generated book, out of time, within the stated tolerances,
without reading the target or anything derived from it.

**Does not:** agreement with any bank's ECL engine; validity on real
portfolios; causal interpretation of any feature; regulatory or model-risk
validation of any kind. Explainability output describes **association in the
fitted function**, and is labelled that way wherever it appears.

Bank-engine validation is marked explicitly **unavailable** in the handoff:
there is no bank engine here to compare against, and a synthetic
demonstration that says otherwise would be the most damaging sentence in the
whole deliverable.

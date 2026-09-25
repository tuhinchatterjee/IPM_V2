# P7 — what the emulators measured, including what failed

Section 11 of `CreditProbe_Advanced_Cockpit_WhatIf_Master_Prompt_v1`.

`docs/whatif/ML_ACCEPTANCE_TARGETS.md` was committed at `949d1ba`, **before**
either model was fitted and before either test split was read. Nothing in it
has been edited since, and nothing in it will be edited because of what is
below.

> Both models were trained on **generated books** against a target produced
> by `reference_ecl.py`. Passing a gate establishes that an emulator can
> learn that calculator on that book. **Agreement with a bank's ECL engine
> is not established and was not tested**, because there is no bank engine
> here to test against.

---

## The headline

| | Corporate | Retail |
|---|---|---|
| G1 out-of-time currency WAPE ≤ 10% | **1.97%** PASS | **2.33%** PASS |
| G2 abs. aggregate bias ≤ 2% | **1.47%** PASS | **0.87%** PASS |
| G3 worst per-period bias ≤ 5% | **2.53%** PASS | **1.33%** PASS |
| G4 worst material-group WAPE ≤ 15% | **5.06%** PASS | **38.02%** — **FAILED** |
| Reference model (`ead × pd × lgd`) WAPE | 9.12% | 5.18% |
| Outcome of the weight fit | **single model** (XGBoost 1.000) | **single model** (LightGBM 1.000) |

**Retail fails G4 and the failure stands.** The threshold is not moved, the
group is not excluded, the model is not retuned, and Method 2 on the Retail
book reports its limitation to the reader rather than returning a number
that looks like the other methods'.

---

## 1. Neither result is a blend, and both cards say so

Section 11.3's gate B4: *"Do not silently deliver a single-model result or a
hardcoded mixture as a validated blend."*

Three components were offered per book and the weight fit — the exact
non-negative, sum-to-one solution over the simplex, on out-of-fold
predictions — put **all of the weight on one of them** in both books:

* Corporate: XGBoost 1.000, LightGBM 0.000, additive 0.000
* Retail: LightGBM 1.000, XGBoost 0.000, additive 0.000

So the deliverable is two single models, and every sentence in both cards
that would have said "blend" says "single model" instead. `Blend.headline`
produces that wording from the weights themselves, so it cannot drift from
what was fitted.

**Why the additive component lost so badly.** Its best fold WAPE was 32.2%
on Corporate and 181.8% on Retail, against roughly 3–10% for the boosters.
That is the honest answer to "is a smooth additive model a useful third
opinion here": on this target, no. The target is a product of several
variables with sharp stage-dependent behaviour, and an additive spline basis
cannot represent a product. It stays in the search — removing it after
seeing this would be exactly the post-hoc tuning the budget exists to
prevent — and its result is published.

## 2. The Retail G4 failure, diagnosed rather than explained away

The failing group is **`score_band = A`**: 652 test observations, WAPE
38.02%, bias −7.70%.

Band A is the safest behavioural band. Its exposures carry a near-zero ECL,
and **WAPE divides by the group's own `Σ|actual|`** — so a small absolute
error against a small denominator produces a large relative one. The model
cards therefore now publish each group's **ECL and its share of the test
period's ECL** beside its WAPE.

Measured: `score_band = A` carries **0.15% of the test period's ECL**
(`share_of_test_ecl` 0.001495, published in
`whatif_retail_model_metric`). So the model is 38% wrong in relative terms
on a group that is a seventh of a percent of the portfolio's loss.

That column is **diagnostic and gates nothing**. It is published so a reader
can see what a relative error is relative to. It is not a reason to move the
threshold, and G4 still reads FAILED.

### What would be wrong to do here, and is not being done

| Tempting | Why it is not done |
|---|---|
| Raise G4 to 40% | A threshold moved after seeing the result is a description of the result. |
| Exclude band A as "immaterial" | Materiality was defined in advance as **observation count** (100), and band A has 652. Adding an ECL-share criterion now would be redefining the gate to pass it. |
| Re-tune LightGBM to help band A | Retuning after reading the test split is the specific thing §11.2 forbids. |
| Report only the aggregate WAPE of 2.33% | The per-group gate exists because an aggregate hides exactly this. |

### What a future version could legitimately do

Any of these creates a **new model version** with its own card and its own
single read of the test split, and none of them may be applied to this one:

* declare a different per-group metric for near-zero groups, **in advance**,
  and say why — a materiality floor in ECL rather than in observations is a
  defensible gate if it is chosen before the results are seen;
* weight the training loss toward the low-ECL tail;
* train a separate model for the safest band.

## 3. Two defects found while getting the models to run

**The final refit had early stopping with nothing to stop against.**
`XGBRegressor` was built with `early_stopping_rounds` and then fitted on all
development periods with no `eval_set`, which raises. The fix is not to drop
early stopping: the refit now runs for **the round count the folds
justified**, because handing a booster the 600-round cap on data it can no
longer be checked on is how a model memorises its training set.

**The additive component was handed raw category strings.** The boosters read
pandas categoricals natively; a spline basis cannot subtract one string from
another. It now has its own preprocessing — median imputation and a spline
basis for numerics, one-hot with a frequency floor for categoricals —
selected by **dtype** rather than by column name, so the same pipeline fits
either book without being told which columns are which.

## 4. What the split actually was

| | Corporate | Retail |
|---|---|---|
| Rows | 59,920 | 127,936 |
| Entities | 2,996 facilities | 6,702 accounts |
| Features | 42 | 39 |
| Train | 11 periods, 2021Q3–2024Q1 | 11 periods, 2025-01–2025-11 |
| Validate | 3 periods | 3 periods |
| Embargoed | 2 periods | 2 periods |
| Test | 4 periods, 2025Q3–2026Q2 | 4 periods, 2026-05–2026-08 |
| Out-of-fold rows the weights were fitted on | 26,964 | — |

The embargo takes the last training period and the last validation period
out of the fit entirely and reports them as their own count. The split
assignment is persisted per row.

## 5. The leakage defence, and why it is an assertion

`features.require_clean` **raises** rather than filtering. Dropping a leaked
column silently would let a training script that assembled the wrong matrix
produce a plausible model, and the mistake would surface as an implausibly
good score that somebody would then have to disbelieve.

The check is by name **and by substring**, so a column added to the release
later — `ecl_stage3_sar_mn`, `lifetime_ecl_overlay_v2` — is caught by the
rule rather than by somebody remembering to edit a list.

`pd_pit_12m`, `pd_lifetime` and `lgd_pct` are deliberately **kept**. They are
inputs to the calculator, not outputs of it, and excluding them would leave
an emulator predicting ECL from sector and region. The declared reference
model is what stops using them being a free pass: the naive product scores
9.12% on Corporate and 5.18% on Retail, and the models beat it by 4.6× and
2.2×.

## 6. Isolation

The libraries live in `.venv-whatif`, built from `requirements-whatif.txt`
with `--system-site-packages` so the candidate interpreter can see the
accepted application's own dependencies. **The direction of visibility is
the point**: the candidate sees the accepted environment, the accepted
environment does not see the candidate.
`test_the_accepted_environment_carries_none_of_the_ml_libraries` runs on the
accepted interpreter and fails if any of xgboost, lightgbm, sklearn, shap,
scipy or matplotlib becomes importable there.

`pyproject.toml` and `requirements.txt` are unchanged, and a test asserts
that none of the ML libraries appears in either.

## 7. Reproducibility

Every pin is exact, every seed is fixed and recorded per component, and the
blend weights are solved by enumerating the faces of the simplex rather than
by an iterative optimiser — so they do not depend on a SciPy minor version.
Re-running `train_emulator.py` with unchanged code reproduces the published
metrics exactly.

**One re-run happened after the Retail failure was seen.** It added a
diagnostic column to the subgroup table and changed nothing else: no
feature, no hyperparameter, no seed, no split, no threshold. The gate
outcomes are identical. It is recorded here because "we ran it again" is
the kind of thing that should never be discovered later.

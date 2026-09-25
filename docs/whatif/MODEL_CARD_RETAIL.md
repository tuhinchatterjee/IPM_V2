# Model card — Retail ECL emulator

`whatif-ecl-emulator-1.0.0` · trained on `v4-whatif-retail-20m-s1`

> **This model was trained on a generated book.** Its target is the declared ECL rate produced by `backend/cockpit_v4/scenario/reference_ecl.py`, a calculator written for this demonstration. Passing every gate below establishes that an emulator can learn that calculator on that book. **It does not establish agreement with any bank's ECL engine**, which is not available here and was not tested.

## Outcome

**1 predeclared gate(s) FAILED.** They are reported here as measured, the thresholds in `ML_ACCEPTANCE_TARGETS.md` are unchanged, and Method 2 reports its limitation to the reader rather than returning a number that looks like the other methods'.

* G4: worst material-group WAPE measured 0.3802 against a 0.1500 threshold

| Gate | What | Threshold | Measured | Outcome |
|---|---|---|---|---|
| G1 | out-of-time currency WAPE | 0.100 | 0.0233 | PASSED |
| G2 | absolute aggregate bias | 0.020 | 0.0087 | PASSED |
| G3 | worst absolute per-period bias | 0.050 | 0.0133 | PASSED |
| G4 | worst material-group WAPE | 0.150 | 0.3802 | **FAILED** |

Thresholds come from `docs/whatif/ML_ACCEPTANCE_TARGETS.md`, which was committed **before** this model was fitted and before the test split was read.

## The declared reference model

| Model | Test WAPE | Test bias |
|---|---|---|
| Blend | 0.0233 | -0.0087 |
| `naive_ead_pd_lgd` (ead × pd × lgd) | 0.0518 | -0.0272 |

The single model beats the naive product on the test split.

## The weight fit, and what it produced

SINGLE-MODEL RESULT. The weight fit put 1.000 on lightgbm and left xgboost, additive_spline below the 0.05 materiality floor. This is a lightgbm model, not a blend, and is reported as one. Weights: xgboost 0.000, lightgbm 1.000, additive_spline 0.000.

| Component | Weight | Material | Library | Seed | Alone (OOF MSE) |
|---|---|---|---|---|---|
| xgboost | 0.0000 | no | 3.0.2 | 20260928 | 0.000028 |
| lightgbm | 1.0000 | yes | 4.6.0 | 20260929 | 0.000017 |
| additive_spline | 0.0000 | no | 1.6.1 | 20260930 | 0.000181 |

Weights are the exact non-negative, sum-to-one solution over the simplex, fitted on 56,830 **out-of-fold** predictions — predictions each component made for periods it had not trained on. Solved by enumerating the faces of the simplex rather than by an iterative optimiser, so the weights do not depend on a library version.

The fit put every unit of weight on one component, so nothing was blended. The comparison below is that component against the two the optimiser set aside, on the same out-of-fold rows.

## The split

20 distinct reporting periods, split chronologically: 11 train (2025-01–2025-11), 3 validate (2026-01–2026-03), 4 test (2026-05–2026-08). One period. Every input the ECL calculator reads is published as at the reporting date, so a label is knowable then; the embargo exists to stop adjacent periods sharing an overlapping twelve-month window across a split boundary, not to wait for an outcome.

| | Periods | Rows |
|---|---|---|
| Train | 11 | |
| Validate | 3 | |
| Development (train + validate) | 14 | 88,160 |
| Embargoed | 2 | |
| Test | 4 | 26,808 |
| Out-of-fold rows the weights were fitted on | | 56,830 |

Train: `2025-01`–`2025-11` · Validate: `2026-01`–`2026-03` · Test: `2026-05`–`2026-08` · Embargoed: `2025-12`, `2026-04`

6,702 distinct entities, 127,936 rows, 39 features. The split assignment is persisted per row, so these counts can be checked rather than trusted.

## Target and exclusions

**Target:** `ecl_rate` — the declared ECL rate on the declared denominator `ead_sar_mn`, converted back to currency for every metric above. Not ECL as a share of total exposure.

**Excluded from the feature matrix, and asserted absent** — by name and by substring, so a column added to the release later is caught by the rule rather than by somebody remembering:

```
  ecl_12m_sar_mn
  ecl_coverage_pct
  ecl_denominator
  ecl_lifetime_sar_mn
  ecl_modelled_sar_mn
  ecl_overlay_sar_mn
  ecl_rate
  ecl_sar_mn
  expected_shortfall_sar_mn
  overlay_reason
  recovery_sar_mn
  total_ecl_sar_mn
  write_off_sar_mn
```

`pd_pit_12m`, `pd_lifetime` and `lgd_pct` are deliberately KEPT. They are inputs to the calculator, not outputs of it, and excluding them would leave an emulator predicting ECL from sector and region. The naive reference model above is what stops that being a free pass.

## Component settings

### xgboost

```json
{
  "colsample_bytree": 0.8,
  "learning_rate": 0.1,
  "max_depth": 7,
  "min_child_weight": 5,
  "reg_lambda": 1.0,
  "subsample": 0.8
}
```

12 configurations tried against a 12-per-family budget; 3 expanding-window folds; 354 boosting rounds at the early-stopping point, against a 600-round cap with patience 50. Seed 20260928.

| Configuration | Mean fold WAPE |
|---|---|
| `{"colsample_bytree": 0.8, "learning_rate": 0.1, "max_depth": 7, "min_child_weight": 5, "reg_lambda": 1.0, "subsample": 0.8}` | 0.07675 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.05, "max_depth": 7, "min_child_weight": 5, "reg_lambda": 1.0, "subsample": 0.8}` | 0.07895 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.1, "max_depth": 5, "min_child_weight": 5, "reg_lambda": 1.0, "subsample": 0.8}` | 0.08860 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.05, "max_depth": 5, "min_child_weight": 5, "reg_lambda": 1.0, "subsample": 0.8}` | 0.09273 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.05, "max_depth": 7, "min_child_weight": 20, "reg_lambda": 1.0, "subsample": 0.8}` | 0.11596 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.1, "max_depth": 7, "min_child_weight": 20, "reg_lambda": 1.0, "subsample": 0.8}` | 0.11705 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.1, "max_depth": 5, "min_child_weight": 20, "reg_lambda": 1.0, "subsample": 0.8}` | 0.12868 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.05, "max_depth": 5, "min_child_weight": 20, "reg_lambda": 1.0, "subsample": 0.8}` | 0.13926 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.1, "max_depth": 3, "min_child_weight": 5, "reg_lambda": 1.0, "subsample": 0.8}` | 0.20113 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.1, "max_depth": 3, "min_child_weight": 20, "reg_lambda": 1.0, "subsample": 0.8}` | 0.24388 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.05, "max_depth": 3, "min_child_weight": 5, "reg_lambda": 1.0, "subsample": 0.8}` | 0.26261 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.05, "max_depth": 3, "min_child_weight": 20, "reg_lambda": 1.0, "subsample": 0.8}` | 0.27263 |

### lightgbm

```json
{
  "bagging_fraction": 0.8,
  "bagging_freq": 1,
  "feature_fraction": 0.8,
  "lambda_l2": 1.0,
  "learning_rate": 0.1,
  "min_data_in_leaf": 20,
  "num_leaves": 63
}
```

12 configurations tried against a 12-per-family budget; 3 expanding-window folds; 599 boosting rounds at the early-stopping point, against a 600-round cap with patience 50. Seed 20260929.

| Configuration | Mean fold WAPE |
|---|---|
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.1, "min_data_in_leaf": 20, "num_leaves": 63}` | 0.09733 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.05, "min_data_in_leaf": 20, "num_leaves": 63}` | 0.09921 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.1, "min_data_in_leaf": 20, "num_leaves": 31}` | 0.10190 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.05, "min_data_in_leaf": 20, "num_leaves": 31}` | 0.10845 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.1, "min_data_in_leaf": 20, "num_leaves": 15}` | 0.11624 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.05, "min_data_in_leaf": 20, "num_leaves": 15}` | 0.12677 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.05, "min_data_in_leaf": 80, "num_leaves": 63}` | 0.17497 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.1, "min_data_in_leaf": 80, "num_leaves": 63}` | 0.17539 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.1, "min_data_in_leaf": 80, "num_leaves": 31}` | 0.17673 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.05, "min_data_in_leaf": 80, "num_leaves": 31}` | 0.18215 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.1, "min_data_in_leaf": 80, "num_leaves": 15}` | 0.18479 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.05, "min_data_in_leaf": 80, "num_leaves": 15}` | 0.19408 |

### additive_spline

```json
{
  "alpha": 10.0,
  "degree": 3,
  "n_knots": 8
}
```

12 configurations tried against a 12-per-family budget; 3 expanding-window folds; n/a boosting rounds at the early-stopping point, against a 600-round cap with patience 50. Seed 20260930.

| Configuration | Mean fold WAPE |
|---|---|
| `{"alpha": 10.0, "degree": 3, "n_knots": 8}` | 1.81797 |
| `{"alpha": 10.0, "degree": 3, "n_knots": 6}` | 1.86566 |
| `{"alpha": 10.0, "degree": 3, "n_knots": 4}` | 1.92703 |
| `{"alpha": 1.0, "degree": 3, "n_knots": 4}` | 1.94085 |
| `{"alpha": 1.0, "degree": 3, "n_knots": 8}` | 1.95196 |
| `{"alpha": 1.0, "degree": 3, "n_knots": 6}` | 1.96337 |
| `{"alpha": 0.1, "degree": 3, "n_knots": 6}` | 2.10986 |
| `{"alpha": 0.1, "degree": 3, "n_knots": 8}` | 2.21556 |
| `{"alpha": 0.1, "degree": 3, "n_knots": 4}` | 2.28272 |
| `{"alpha": 0.01, "degree": 3, "n_knots": 8}` | 2.56764 |
| `{"alpha": 0.01, "degree": 3, "n_knots": 6}` | 2.80753 |
| `{"alpha": 0.01, "degree": 3, "n_knots": 4}` | 3.55951 |

## Subgroup errors

A group is gated at 100 test observations. Smaller groups stay in this table with their counts and are excluded from the gate rather than from the report — a reader should see where the model is untested.

`Share of test ECL` is DIAGNOSTIC and gates nothing. WAPE divides by the group's own total, so a group carrying almost no ECL can post a large relative error on a trivial absolute one. That is worth seeing and it is not a reason to move a threshold: the gate is written in relative terms, applied in relative terms, and a failure above is reported as a failure.

| Dimension | Value | Test rows | ECL (SAR mn) | Share of test ECL | WAPE | Bias | Gated |
|---|---|---|---|---|---|---|---|
| employer_sector | Hospitality | 2,832 | 0.74 | 7.23% | 0.0395 | -0.0171 | yes |
| employer_sector | Retail Trade | 2,816 | 0.89 | 8.70% | 0.0291 | -0.0114 | yes |
| employer_sector | Healthcare | 2,808 | 1.37 | 13.38% | 0.0156 | -0.0020 | yes |
| employer_sector | Education | 2,796 | 1.42 | 13.84% | 0.0155 | -0.0014 | yes |
| employer_sector | Construction | 2,684 | 0.73 | 7.11% | 0.0405 | -0.0184 | yes |
| employer_sector | Oil and Gas | 2,660 | 0.95 | 9.27% | 0.0241 | -0.0108 | yes |
| employer_sector | Manufacturing | 2,636 | 1.02 | 9.99% | 0.0237 | -0.0132 | yes |
| employer_sector | Public Administration | 2,620 | 1.29 | 12.64% | 0.0181 | -0.0044 | yes |
| employer_sector | Transport and Logistics | 2,508 | 0.77 | 7.51% | 0.0273 | -0.0134 | yes |
| employer_sector | Financial Services | 2,448 | 1.06 | 10.34% | 0.0180 | -0.0077 | yes |
| product | Personal Finance | 7,688 | 5.38 | 52.59% | 0.0180 | -0.0071 | yes |
| product | Credit Card | 7,088 | 1.81 | 17.68% | 0.0165 | -0.0120 | yes |
| product | Mortgage | 5,740 | 2.01 | 19.61% | 0.0422 | -0.0106 | yes |
| product | Auto Finance | 4,548 | 0.96 | 9.34% | 0.0260 | -0.0068 | yes |
| product | Buy Now Pay Later | 1,744 | 0.08 | 0.78% | 0.0283 | -0.0155 | yes |
| region | Qassim | 3,636 | 1.43 | 13.93% | 0.0225 | -0.0090 | yes |
| region | Asir | 3,560 | 1.47 | 14.37% | 0.0215 | -0.0076 | yes |
| region | Tabuk | 3,356 | 1.21 | 11.79% | 0.0253 | -0.0088 | yes |
| region | Makkah | 3,308 | 1.09 | 10.70% | 0.0253 | -0.0093 | yes |
| region | Hail | 3,288 | 1.21 | 11.82% | 0.0258 | -0.0110 | yes |
| region | Eastern Province | 3,268 | 1.25 | 12.22% | 0.0224 | -0.0075 | yes |
| region | Madinah | 3,204 | 1.33 | 12.97% | 0.0217 | -0.0086 | yes |
| region | Riyadh | 3,188 | 1.25 | 12.22% | 0.0229 | -0.0080 | yes |
| score_band | C | 10,112 | 2.62 | 25.57% | 0.0279 | -0.0105 | yes |
| score_band | B | 9,035 | 0.53 | 5.22% | 0.0747 | -0.0021 | yes |
| score_band | D | 6,989 | 7.01 | 68.52% | 0.0170 | -0.0084 | yes |
| score_band | A | 652 | 0.02 | 0.15% | 0.3802 **<- G4** | -0.0770 | yes |
| score_band | E | 20 | 0.06 | 0.54% | 0.0141 | -0.0049 | no |
| stage | 1 | 26,808 | 10.23 | 100.00% | 0.0233 | -0.0087 | yes |

## Provenance

| | |
|---|---|
| Release | `v4-whatif-retail-20m-s1` |
| Origin | SYNTHETIC_DEMO |
| Target produced by | `reference_ecl.py` |
| Model version | `whatif-ecl-emulator-1.0.0` |
| additive_spline | 1.6.1 |
| lightgbm | 4.6.0 |
| xgboost | 3.0.2 |

Artifacts and their SHA-256 hashes are in `artifacts/whatif/<book>/blend.json`, which also carries the feature order — a model fed the same columns in a different order is a different model with no error message.

## Support limits, and what this is not

* Fitted over the training window's own ranges. A scenario that moves a feature outside them is an extrapolation and is labelled one.
* Explainability output describes **association in the fitted function**. It is not causal and is labelled that way wherever it appears.
* Agreement with any bank's ECL engine is **not established and was not tested**. There is no bank engine here to compare against.
* Every figure above is measured on a generated book. Nothing in this card is a statement about a real portfolio.

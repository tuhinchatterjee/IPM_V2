# Model card — Corporate ECL emulator

`whatif-ecl-emulator-1.0.0` · trained on `v4-whatif-corporate-20q-s1`

> **This model was trained on a generated book.** Its target is the declared ECL rate produced by `backend/cockpit_v4/scenario/reference_ecl.py`, a calculator written for this demonstration. Passing every gate below establishes that an emulator can learn that calculator on that book. **It does not establish agreement with any bank's ECL engine**, which is not available here and was not tested.

## Outcome

Every predeclared gate passed.

| Gate | What | Threshold | Measured | Outcome |
|---|---|---|---|---|
| G1 | out-of-time currency WAPE | 0.100 | 0.0197 | PASSED |
| G2 | absolute aggregate bias | 0.020 | 0.0147 | PASSED |
| G3 | worst absolute per-period bias | 0.050 | 0.0253 | PASSED |
| G4 | worst material-group WAPE | 0.150 | 0.0506 | PASSED |

Thresholds come from `docs/whatif/ML_ACCEPTANCE_TARGETS.md`, which was committed **before** this model was fitted and before the test split was read.

## The declared reference model

| Model | Test WAPE | Test bias |
|---|---|---|
| Blend | 0.0197 | -0.0147 |
| `naive_ead_pd_lgd` (ead × pd × lgd) | 0.0912 | -0.0863 |

The single model beats the naive product on the test split.

## The weight fit, and what it produced

SINGLE-MODEL RESULT. The weight fit put 1.000 on xgboost and left lightgbm, additive_spline below the 0.05 materiality floor. This is a xgboost model, not a blend, and is reported as one. Weights: xgboost 1.000, lightgbm 0.000, additive_spline 0.000.

| Component | Weight | Material | Library | Seed | Alone (OOF MSE) |
|---|---|---|---|---|---|
| xgboost | 1.0000 | yes | 3.0.2 | 20260928 | 0.133981 |
| lightgbm | 0.0000 | no | 4.6.0 | 20260929 | 0.463083 |
| additive_spline | 0.0000 | no | 1.6.1 | 20260930 | 1.073603 |

Weights are the exact non-negative, sum-to-one solution over the simplex, fitted on 26,964 **out-of-fold** predictions — predictions each component made for periods it had not trained on. Solved by enumerating the faces of the simplex rather than by an iterative optimiser, so the weights do not depend on a library version.

The fit put every unit of weight on one component, so nothing was blended. The comparison below is that component against the two the optimiser set aside, on the same out-of-fold rows.

## The split

20 distinct reporting periods, split chronologically: 11 train (2021Q3–2024Q1), 3 validate (2024Q3–2025Q1), 4 test (2025Q3–2026Q2). One period. Every input the ECL calculator reads is published as at the reporting date, so a label is knowable then; the embargo exists to stop adjacent periods sharing an overlapping twelve-month window across a split boundary, not to wait for an outcome.

| | Periods | Rows |
|---|---|---|
| Train | 11 | |
| Validate | 3 | |
| Development (train + validate) | 14 | 41,944 |
| Embargoed | 2 | |
| Test | 4 | 11,984 |
| Out-of-fold rows the weights were fitted on | | 26,964 |

Train: `2021Q3`–`2024Q1` · Validate: `2024Q3`–`2025Q1` · Test: `2025Q3`–`2026Q2` · Embargoed: `2024Q2`, `2025Q2`

2,996 distinct entities, 59,920 rows, 42 features. The split assignment is persisted per row, so these counts can be checked rather than trusted.

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
  "learning_rate": 0.05,
  "max_depth": 7,
  "min_child_weight": 5,
  "reg_lambda": 1.0,
  "subsample": 0.8
}
```

12 configurations tried against a 12-per-family budget; 3 expanding-window folds; 584 boosting rounds at the early-stopping point, against a 600-round cap with patience 50. Seed 20260928.

| Configuration | Mean fold WAPE |
|---|---|
| `{"colsample_bytree": 0.8, "learning_rate": 0.05, "max_depth": 7, "min_child_weight": 5, "reg_lambda": 1.0, "subsample": 0.8}` | 0.03039 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.05, "max_depth": 5, "min_child_weight": 5, "reg_lambda": 1.0, "subsample": 0.8}` | 0.03056 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.1, "max_depth": 7, "min_child_weight": 5, "reg_lambda": 1.0, "subsample": 0.8}` | 0.03243 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.1, "max_depth": 5, "min_child_weight": 5, "reg_lambda": 1.0, "subsample": 0.8}` | 0.03325 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.1, "max_depth": 3, "min_child_weight": 5, "reg_lambda": 1.0, "subsample": 0.8}` | 0.04151 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.05, "max_depth": 7, "min_child_weight": 20, "reg_lambda": 1.0, "subsample": 0.8}` | 0.04409 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.1, "max_depth": 7, "min_child_weight": 20, "reg_lambda": 1.0, "subsample": 0.8}` | 0.04492 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.05, "max_depth": 3, "min_child_weight": 5, "reg_lambda": 1.0, "subsample": 0.8}` | 0.04549 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.05, "max_depth": 5, "min_child_weight": 20, "reg_lambda": 1.0, "subsample": 0.8}` | 0.04647 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.1, "max_depth": 5, "min_child_weight": 20, "reg_lambda": 1.0, "subsample": 0.8}` | 0.04874 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.1, "max_depth": 3, "min_child_weight": 20, "reg_lambda": 1.0, "subsample": 0.8}` | 0.06234 |
| `{"colsample_bytree": 0.8, "learning_rate": 0.05, "max_depth": 3, "min_child_weight": 20, "reg_lambda": 1.0, "subsample": 0.8}` | 0.06718 |

### lightgbm

```json
{
  "bagging_fraction": 0.8,
  "bagging_freq": 1,
  "feature_fraction": 0.8,
  "lambda_l2": 1.0,
  "learning_rate": 0.05,
  "min_data_in_leaf": 20,
  "num_leaves": 63
}
```

12 configurations tried against a 12-per-family budget; 3 expanding-window folds; 599 boosting rounds at the early-stopping point, against a 600-round cap with patience 50. Seed 20260929.

| Configuration | Mean fold WAPE |
|---|---|
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.05, "min_data_in_leaf": 20, "num_leaves": 63}` | 0.04281 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.1, "min_data_in_leaf": 20, "num_leaves": 63}` | 0.04345 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.05, "min_data_in_leaf": 20, "num_leaves": 31}` | 0.04408 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.1, "min_data_in_leaf": 20, "num_leaves": 31}` | 0.04551 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.05, "min_data_in_leaf": 20, "num_leaves": 15}` | 0.04701 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.1, "min_data_in_leaf": 20, "num_leaves": 15}` | 0.04797 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.05, "min_data_in_leaf": 80, "num_leaves": 63}` | 0.06718 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.05, "min_data_in_leaf": 80, "num_leaves": 31}` | 0.06846 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.1, "min_data_in_leaf": 80, "num_leaves": 63}` | 0.06854 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.1, "min_data_in_leaf": 80, "num_leaves": 31}` | 0.07004 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.05, "min_data_in_leaf": 80, "num_leaves": 15}` | 0.07096 |
| `{"bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "lambda_l2": 1.0, "learning_rate": 0.1, "min_data_in_leaf": 80, "num_leaves": 15}` | 0.07321 |

### additive_spline

```json
{
  "alpha": 10.0,
  "degree": 3,
  "n_knots": 6
}
```

12 configurations tried against a 12-per-family budget; 3 expanding-window folds; n/a boosting rounds at the early-stopping point, against a 600-round cap with patience 50. Seed 20260930.

| Configuration | Mean fold WAPE |
|---|---|
| `{"alpha": 10.0, "degree": 3, "n_knots": 6}` | 0.32173 |
| `{"alpha": 10.0, "degree": 3, "n_knots": 8}` | 0.32586 |
| `{"alpha": 10.0, "degree": 3, "n_knots": 4}` | 0.33104 |
| `{"alpha": 1.0, "degree": 3, "n_knots": 4}` | 0.34964 |
| `{"alpha": 0.1, "degree": 3, "n_knots": 4}` | 0.35218 |
| `{"alpha": 0.01, "degree": 3, "n_knots": 4}` | 0.36053 |
| `{"alpha": 1.0, "degree": 3, "n_knots": 6}` | 0.37167 |
| `{"alpha": 1.0, "degree": 3, "n_knots": 8}` | 0.37948 |
| `{"alpha": 0.1, "degree": 3, "n_knots": 8}` | 0.41316 |
| `{"alpha": 0.01, "degree": 3, "n_knots": 6}` | 0.42476 |
| `{"alpha": 0.1, "degree": 3, "n_knots": 6}` | 0.43805 |
| `{"alpha": 0.01, "degree": 3, "n_knots": 8}` | 0.44471 |

## Subgroup errors

A group is gated at 100 test observations. Smaller groups stay in this table with their counts and are excluded from the gate rather than from the report — a reader should see where the model is untested.

`Share of test ECL` is DIAGNOSTIC and gates nothing. WAPE divides by the group's own total, so a group carrying almost no ECL can post a large relative error on a trivial absolute one. That is worth seeing and it is not a reason to move a threshold: the gate is written in relative terms, applied in relative terms, and a failure above is reported as a failure.

| Dimension | Value | Test rows | ECL (SAR mn) | Share of test ECL | WAPE | Bias | Gated |
|---|---|---|---|---|---|---|---|
| facility_class | Funded | 8,084 | 4,555.28 | 64.23% | 0.0194 | -0.0143 | yes |
| facility_class | Contingent | 3,900 | 2,536.47 | 35.77% | 0.0201 | -0.0155 | yes |
| rating_current | B+ | 1,875 | 2,217.54 | 31.27% | 0.0172 | -0.0136 | yes |
| rating_current | BB+ | 1,822 | 582.73 | 8.22% | 0.0219 | -0.0189 | yes |
| rating_current | BBB | 1,791 | 259.59 | 3.66% | 0.0243 | -0.0086 | yes |
| rating_current | BBB- | 1,763 | 388.46 | 5.48% | 0.0210 | -0.0169 | yes |
| rating_current | BB- | 1,740 | 1,398.56 | 19.72% | 0.0211 | -0.0180 | yes |
| rating_current | BB | 1,645 | 842.42 | 11.88% | 0.0214 | -0.0183 | yes |
| rating_current | BBB+ | 677 | 80.33 | 1.13% | 0.0506 **<- G4** | +0.0156 | yes |
| rating_current | B | 671 | 1,322.12 | 18.64% | 0.0169 | -0.0116 | yes |
| region | Riyadh | 1,744 | 1,078.67 | 15.21% | 0.0191 | -0.0148 | yes |
| region | Hail | 1,568 | 946.94 | 13.35% | 0.0207 | -0.0154 | yes |
| region | Asir | 1,556 | 915.46 | 12.91% | 0.0202 | -0.0162 | yes |
| region | Tabuk | 1,532 | 916.96 | 12.93% | 0.0178 | -0.0119 | yes |
| region | Makkah | 1,524 | 976.16 | 13.76% | 0.0198 | -0.0155 | yes |
| region | Qassim | 1,456 | 801.40 | 11.30% | 0.0181 | -0.0123 | yes |
| region | Madinah | 1,344 | 765.98 | 10.80% | 0.0199 | -0.0147 | yes |
| region | Eastern Province | 1,260 | 690.18 | 9.73% | 0.0220 | -0.0174 | yes |
| sector | Real Estate | 1,024 | 549.63 | 7.75% | 0.0322 | -0.0286 | yes |
| sector | Manufacturing | 1,016 | 548.84 | 7.74% | 0.0220 | -0.0196 | yes |
| sector | Transport | 1,012 | 553.11 | 7.80% | 0.0211 | -0.0177 | yes |
| sector | Retail Trade | 1,008 | 633.97 | 8.94% | 0.0163 | -0.0132 | yes |
| sector | Wholesale Trade | 1,008 | 614.32 | 8.66% | 0.0174 | -0.0142 | yes |
| sector | Hospitality | 1,004 | 532.01 | 7.50% | 0.0282 | -0.0247 | yes |
| sector | Utilities | 996 | 806.00 | 11.37% | 0.0100 | +0.0007 | yes |
| sector | Construction | 992 | 576.29 | 8.13% | 0.0363 | -0.0343 | yes |
| sector | Education | 988 | 663.34 | 9.35% | 0.0101 | -0.0026 | yes |
| sector | Healthcare | 984 | 483.41 | 6.82% | 0.0127 | -0.0054 | yes |
| sector | Professional Services | 980 | 625.73 | 8.82% | 0.0122 | -0.0062 | yes |
| sector | Petrochemicals | 972 | 505.10 | 7.12% | 0.0246 | -0.0210 | yes |
| stage | 1 | 11,947 | 6,842.74 | 96.49% | 0.0196 | -0.0149 | yes |
| stage | 2 | 37 | 249.00 | 3.51% | 0.0219 | -0.0092 | no |

## Provenance

| | |
|---|---|
| Release | `v4-whatif-corporate-20q-s1` |
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

# Model card — Corporate ECL emulator

`whatif-ecl-emulator-2.0.0` · trained on `v4-whatif-corporate-20q-s1`

> **This model was trained on a generated book.** Its target is the declared ECL rate produced by `backend/cockpit_v4/scenario/reference_ecl.py`, a calculator written for this demonstration. Passing every gate below establishes that an emulator can learn that calculator on that book. **It does not establish agreement with any bank's ECL engine**, which is not available here and was not tested.

## Outcome

Every predeclared gate passed.

| Gate | What | Threshold | Measured | Outcome |
|---|---|---|---|---|
| G1 | out-of-time currency WAPE | 0.100 | 0.0189 | PASSED |
| G2 | absolute aggregate bias | 0.020 | 0.0113 | PASSED |
| G3 | worst absolute per-period bias | 0.050 | 0.0234 | PASSED |
| G4 | worst material-group WAPE | 0.150 | 0.0537 | PASSED |

Thresholds come from docs/whatif/`ML_ACCEPTANCE_TARGETS_V2.md`, which was committed **before** this model was fitted and before the test split was read.

## The declared reference model

| Model | Test WAPE | Test bias |
|---|---|---|
| Blend | 0.0189 | -0.0113 |
| `naive_ead_pd_lgd` (ead × pd × lgd) | 0.0912 | -0.0863 |

The blend beats the naive product on the test split.

## The blend

BLEND of 2 material components, fitted on out-of-fold predictions. Weights: xgboost 0.767, lightgbm 0.000, additive_log 0.233. Below the 0.05 materiality floor and reported as immaterial: lightgbm.

| Component | Weight | Material | Library | Seed | Alone (OOF MSE) |
|---|---|---|---|---|---|
| xgboost | 0.7668 | yes | 3.0.2 | 20260928 | 0.133981 |
| lightgbm | 0.0000 | no | 4.6.0 | 20260929 | 0.463083 |
| additive_log | 0.2332 | yes | 1.6.1 | 20260930 | 0.329057 |

Weights are the exact non-negative, sum-to-one solution over the simplex, fitted on 26,964 **out-of-fold** predictions — predictions each component made for periods it had not trained on. Solved by enumerating the faces of the simplex rather than by an iterative optimiser, so the weights do not depend on a library version.

Blending improved on every single component.

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

### additive_log

```json
{
  "alpha": 0.1,
  "degree": 3,
  "n_knots": 4
}
```

12 configurations tried against a 12-per-family budget; 3 expanding-window folds; n/a boosting rounds at the early-stopping point, against a 600-round cap with patience 50. Seed 20260930.

Fitted in logs and back-transformed with Duan's smearing estimator, **1.003213**, computed on the development residuals only. Without it, `exp` of a mean log is a geometric mean and every ECL would be understated by about 0.00%.

`log(x + 1e-09)` on the numeric features whose fitted support is non-negative, decided per column at fit time and remembered, so a scenario that drives a value negative cannot move that column onto a scale the coefficients were not fitted on.


| Configuration | Mean fold WAPE |
|---|---|
| `{"alpha": 0.1, "degree": 3, "n_knots": 4}` | 0.09392 |
| `{"alpha": 0.1, "degree": 3, "n_knots": 8}` | 0.09859 |
| `{"alpha": 1.0, "degree": 3, "n_knots": 4}` | 0.09900 |
| `{"alpha": 0.01, "degree": 3, "n_knots": 4}` | 0.09947 |
| `{"alpha": 0.01, "degree": 3, "n_knots": 8}` | 0.10055 |
| `{"alpha": 1.0, "degree": 3, "n_knots": 8}` | 0.10128 |
| `{"alpha": 0.1, "degree": 3, "n_knots": 6}` | 0.10466 |
| `{"alpha": 1.0, "degree": 3, "n_knots": 6}` | 0.10550 |
| `{"alpha": 0.01, "degree": 3, "n_knots": 6}` | 0.10936 |
| `{"alpha": 10.0, "degree": 3, "n_knots": 4}` | 0.12763 |
| `{"alpha": 10.0, "degree": 3, "n_knots": 6}` | 0.12880 |
| `{"alpha": 10.0, "degree": 3, "n_knots": 8}` | 0.13216 |

## Subgroup errors

A group is gated at 100 test observations. Smaller groups stay in this table with their counts and are excluded from the gate rather than from the report — a reader should see where the model is untested.

`Share of test ECL` is DIAGNOSTIC and gates nothing. WAPE divides by the group's own total, so a group carrying almost no ECL can post a large relative error on a trivial absolute one. That is worth seeing and it is not a reason to move a threshold: the gate is written in relative terms, applied in relative terms, and a failure above is reported as a failure.

| Dimension | Value | Test rows | ECL (SAR mn) | Share of test ECL | WAPE | Bias | Gated |
|---|---|---|---|---|---|---|---|
| facility_class | Funded | 8,084 | 4,555.28 | 64.23% | 0.0192 | -0.0111 | yes |
| facility_class | Contingent | 3,900 | 2,536.47 | 35.77% | 0.0184 | -0.0115 | yes |
| rating_current | B+ | 1,875 | 2,217.54 | 31.27% | 0.0154 | -0.0084 | yes |
| rating_current | BB+ | 1,822 | 582.73 | 8.22% | 0.0192 | -0.0121 | yes |
| rating_current | BBB | 1,791 | 259.59 | 3.66% | 0.0352 | -0.0146 | yes |
| rating_current | BBB- | 1,763 | 388.46 | 5.48% | 0.0232 | -0.0140 | yes |
| rating_current | BB- | 1,740 | 1,398.56 | 19.72% | 0.0169 | -0.0119 | yes |
| rating_current | BB | 1,645 | 842.42 | 11.88% | 0.0171 | -0.0118 | yes |
| rating_current | BBB+ | 677 | 80.33 | 1.13% | 0.0537 **<- G4** | +0.0038 | yes |
| rating_current | B | 671 | 1,322.12 | 18.64% | 0.0215 | -0.0141 | yes |
| region | Riyadh | 1,744 | 1,078.67 | 15.21% | 0.0178 | -0.0116 | yes |
| region | Hail | 1,568 | 946.94 | 13.35% | 0.0220 | -0.0119 | yes |
| region | Asir | 1,556 | 915.46 | 12.91% | 0.0181 | -0.0109 | yes |
| region | Tabuk | 1,532 | 916.96 | 12.93% | 0.0166 | -0.0095 | yes |
| region | Makkah | 1,524 | 976.16 | 13.76% | 0.0184 | -0.0097 | yes |
| region | Qassim | 1,456 | 801.40 | 11.30% | 0.0178 | -0.0105 | yes |
| region | Madinah | 1,344 | 765.98 | 10.80% | 0.0195 | -0.0122 | yes |
| region | Eastern Province | 1,260 | 690.18 | 9.73% | 0.0222 | -0.0148 | yes |
| sector | Real Estate | 1,024 | 549.63 | 7.75% | 0.0262 | -0.0191 | yes |
| sector | Manufacturing | 1,016 | 548.84 | 7.74% | 0.0203 | -0.0167 | yes |
| sector | Transport | 1,012 | 553.11 | 7.80% | 0.0218 | -0.0176 | yes |
| sector | Retail Trade | 1,008 | 633.97 | 8.94% | 0.0188 | -0.0119 | yes |
| sector | Wholesale Trade | 1,008 | 614.32 | 8.66% | 0.0170 | -0.0119 | yes |
| sector | Hospitality | 1,004 | 532.01 | 7.50% | 0.0213 | -0.0105 | yes |
| sector | Utilities | 996 | 806.00 | 11.37% | 0.0134 | -0.0014 | yes |
| sector | Construction | 992 | 576.29 | 8.13% | 0.0309 | -0.0265 | yes |
| sector | Education | 988 | 663.34 | 9.35% | 0.0132 | -0.0004 | yes |
| sector | Healthcare | 984 | 483.41 | 6.82% | 0.0140 | -0.0044 | yes |
| sector | Professional Services | 980 | 625.73 | 8.82% | 0.0128 | -0.0045 | yes |
| sector | Petrochemicals | 972 | 505.10 | 7.12% | 0.0216 | -0.0166 | yes |
| stage | 1 | 11,947 | 6,842.74 | 96.49% | 0.0179 | -0.0110 | yes |
| stage | 2 | 37 | 249.00 | 3.51% | 0.0474 | -0.0187 | no |

## Provenance

| | |
|---|---|
| Release | `v4-whatif-corporate-20q-s1` |
| Origin | SYNTHETIC_DEMO |
| Target produced by | `reference_ecl.py` |
| Model version | `whatif-ecl-emulator-2.0.0` |
| additive_log | 1.6.1 |
| lightgbm | 4.6.0 |
| xgboost | 3.0.2 |

Artifacts and their SHA-256 hashes are in `artifacts/whatif/<book>/blend.json`, which also carries the feature order — a model fed the same columns in a different order is a different model with no error message.

## Support limits, and what this is not

* Fitted over the training window's own ranges. A scenario that moves a feature outside them is an extrapolation and is labelled one.
* Explainability output describes **association in the fitted function**. It is not causal and is labelled that way wherever it appears.
* Agreement with any bank's ECL engine is **not established and was not tested**. There is no bank engine here to compare against.
* Every figure above is measured on a generated book. Nothing in this card is a statement about a real portfolio.

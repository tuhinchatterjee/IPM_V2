# Macro sensitivity card — Corporate

`v4-whatif-corporate-20q-s1` · artifact `1.0.0` · estimator `ridge-logit-difference-1.0`

> **Fitted on generated data.** Every number below was estimated from a synthetic book against a generated macroeconomic panel. It establishes that the estimator recovers a relationship that was put into the data on purpose. **It is not a bank-validated sensitivity, and the panel is not observed economic history.**

## What was fitted

```
y_t  =  logit(q_t) − logit(q_{t−1})
x_t  =  z_{t−lag} − z_{t−lag−1}        z in native units
y_t  =  α + β x_t + ε_t                ridge, penalty 0.05
```

The published slope is **not** β. It is `q(1−q) × β`, in percentage points of the parameter per one native unit of the factor, evaluated at a stated `q` and a stated `z`. Every row was checked against a finite difference of the fitted function to within 1e-06 relative.

## The sample

| | |
|---|---|
| Calendar | 20 quarters, 2021Q3–2026Q2 |
| Distinct macro observations | **20** — not 57,940 exposure-quarters |
| Fixed cohort | 2,897 exposures present in every quarter and performing throughout |
| Excluded, ever defaulted | 99 |
| Excluded, not in every quarter | 0 |
| Weights | EAD frozen at 2021Q3 |
| Scenario | baseline |
| Lags considered | 0, 1, chosen on training-only forward validation error |
| Training share | 70% of the differenced series |
| Uncertainty | 200 contiguous 4-quarter block resamples, seed 20260927 |
| Input digest | `56f914cffd5b0b17…` |

## Readiness

| Status | Rows |
|---|---|
| `SUPPORTED_ESTIMATE` | 37 |
| `DIAGNOSTIC_ONLY` | 11 |
| `UNAVAILABLE` | 12 (4 factors × 3 parameters) |

The complexity ceiling is `max(1, floor((training − 5) / 5))`, which on this history is 1. **The ceiling is read as governing predictor complexity; the intercept is not charged against it.** Counting the intercept, a single-regressor ridge scores about 1.9 and every row here would be `DIAGNOSTIC_ONLY` — including an intercept-only model at exactly 1.0, which is why that reading cannot be what a budget for 'how much complexity does this history support' means. The slopes and their intervals would be identical under either reading; only automatic translation would stop.

## PD sensitivities, ranked

Ranked by the **response of the parameter to one training-period standard deviation of the factor** — stated here rather than left to be inferred from the order, and magnitude is not evidence of causal importance.

| Factor | Name | Lag | Slope (pp per native unit) | 95% interval | Sign stability | VIF | Readiness |
|---|---|---|---|---|---|---|---|
| MEV17 | Industrial production growth | 0 | -0.1159 | -0.1364 to -0.0118 | 98% | 2.79 | `SUPPORTED_ESTIMATE` |
| MEV02 | Non-oil real GDP growth | 1 | -0.2207 | -0.2884 to -0.0258 | 98% | 2.63 | `SUPPORTED_ESTIMATE` |
| MEV01 | Real GDP growth | 0 | -0.1410 | -0.2417 to +0.0521 | 96% | 2.79 | `SUPPORTED_ESTIMATE` |
| MEV07 | Oil price | 0 | -0.0274 | -0.0374 to -0.0044 | 98% | 2.02 | `SUPPORTED_ESTIMATE` |
| MEV13 | Private-sector credit growth | 0 | -0.2119 | -0.3238 to -0.0698 | 99% | 2.12 | `SUPPORTED_ESTIMATE` |
| MEV11 | Equity market index | 0 | -0.0386 | -0.0472 to +0.0063 | 96% | 1.98 | `SUPPORTED_ESTIMATE` |
| MEV10 | Commercial property price index | 1 | -0.0611 | -0.1053 to -0.0164 | 100% | 1.56 | `SUPPORTED_ESTIMATE` |
| MEV15 | Real wage growth | 0 | -0.2538 | -0.3529 to +0.0415 | 97% | 2.69 | `SUPPORTED_ESTIMATE` |
| MEV19 | Business confidence (PMI) | 0 | -0.0845 | -0.1139 to +0.0063 | 93% | 2.63 | `SUPPORTED_ESTIMATE` |
| MEV03 | Unemployment rate | 1 | +0.3044 | -0.1238 to +0.3944 | 86% | 2.69 | `SUPPORTED_ESTIMATE` |
| MEV04 | CPI inflation | 0 | +0.3665 | +0.0917 to +0.5647 | 100% | 2.12 | `SUPPORTED_ESTIMATE` |
| MEV06 | Three-month interbank rate | 0 | +0.2348 | -0.1373 to +0.3807 | 88% | 1.73 | `SUPPORTED_ESTIMATE` |
| MEV09 | Residential property price index | 0 | -0.0373 | -0.0685 to +0.0301 | 73% | 1.37 | `DIAGNOSTIC_ONLY` |
| MEV05 | Policy interest rate | 1 | +0.1809 | -0.1763 to +0.2807 | 80% | 1.67 | `SUPPORTED_ESTIMATE` |
| MEV08 | Oil production | 0 | -0.0305 | -0.0990 to +0.0834 | 52% | 1.73 | `DIAGNOSTIC_ONLY` |
| MEV12 | Nominal effective exchange rate | 1 | +0.0326 | -0.1749 to +0.0871 | 68% | 1.67 | `DIAGNOSTIC_ONLY` |

## Factors this book does not carry

An absent factor is `UNAVAILABLE`. It is never a sensitivity of zero, and no value is imputed for it from a related series.

| Factor | Why |
|---|---|
| MEV14 | Household income is generated as a retail-book driver and has no corporate series in this release. |
| MEV16 | Retail sales are generated as a retail-book driver. |
| MEV18 | Housing transaction activity is generated as a retail-book driver. |
| MEV20 | Consumer confidence is generated as a retail-book driver. Business confidence (MEV19) is the corporate equivalent and measures something else. |

## Using a slope

Section 7.4's worked example, which is also an oracle in `tests/cockpit_v4/test_whatif_sensitivity.py`:

> Unemployment 6.0% cut by 10% is **5.4%**, a change of **−0.6 percentage points** — not −4% and not a ten-point move. At a slope of +0.20 PD points per unemployment point, a baseline PD of 3.00% becomes **2.88%**.

Two translations are offered by name and neither is substituted for the other: `linear_sensitivity_times_change` is the reader's own sensitivity-times-change reading, and `fitted_link_finite_difference` adds the fitted linear-predictor change to the observed baseline logit and inverts, so a zero shock returns the observed baseline exactly. A shock outside the fitted range carries an extrapolation warning.

A row whose readiness is not `SUPPORTED_ESTIMATE` is **refused** for automatic translation. The reader may still state the parameter change they want to assume, and it is then applied and labelled as `USER_ASSUMPTION` rather than as an estimate.

## Staleness

Each row stores `source_release_id` and a `source_fingerprint` of `56f914cffd5b0b17…`. That fingerprint is a SHA-256 over the exact period-level series the fit consumed, not the release's own fingerprint (`01fffad050c248f3…`): an artifact stored inside the release it describes cannot carry a fingerprint taken over bytes that include it. A fit whose stored digest does not match the one recomputed from the release in use is `STALE` and is refused.

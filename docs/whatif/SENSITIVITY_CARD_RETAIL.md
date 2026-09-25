# Macro sensitivity card — Retail

`v4-whatif-retail-20m-s1` · artifact `1.0.0` · estimator `ridge-logit-difference-1.0`

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
| Calendar | 20 months, 2025-01–2026-08 |
| Distinct macro observations | **20** — not 120,380 exposure-months |
| Fixed cohort | 6,019 exposures present in every month and performing throughout |
| Excluded, ever defaulted | 247 |
| Excluded, not in every month | 436 |
| Weights | EAD frozen at 2025-01 |
| Scenario | baseline |
| Lags considered | 0, 1, chosen on training-only forward validation error |
| Training share | 70% of the differenced series |
| Uncertainty | 200 contiguous 4-month block resamples, seed 20260927 |
| Input digest | `7e4fce428ba34860…` |

## Readiness

| Status | Rows |
|---|---|
| `SUPPORTED_ESTIMATE` | 31 |
| `DIAGNOSTIC_ONLY` | 11 |
| `UNAVAILABLE` | 18 (6 factors × 3 parameters) |

The complexity ceiling is `max(1, floor((training − 5) / 5))`, which on this history is 1. **The ceiling is read as governing predictor complexity; the intercept is not charged against it.** Counting the intercept, a single-regressor ridge scores about 1.9 and every row here would be `DIAGNOSTIC_ONLY` — including an intercept-only model at exactly 1.0, which is why that reading cannot be what a budget for 'how much complexity does this history support' means. The slopes and their intervals would be identical under either reading; only automatic translation would stop.

## PD sensitivities, ranked

Ranked by the **response of the parameter to one training-period standard deviation of the factor** — stated here rather than left to be inferred from the order, and magnitude is not evidence of causal importance.

| Factor | Name | Lag | Slope (pp per native unit) | 95% interval | Sign stability | VIF | Readiness |
|---|---|---|---|---|---|---|---|
| MEV19 | Business confidence (PMI) | 0 | -0.1094 | -0.1278 to -0.0239 | 98% | 2.64 | `SUPPORTED_ESTIMATE` |
| MEV15 | Real wage growth | 0 | -0.2990 | -0.3255 to -0.0121 | 98% | 3.47 | `SUPPORTED_ESTIMATE` |
| MEV01 | Real GDP growth | 0 | -0.1711 | -0.2024 to +0.1963 | 82% | 2.14 | `SUPPORTED_ESTIMATE` |
| MEV18 | Housing transaction activity | 0 | -0.0330 | -0.0403 to -0.0008 | 98% | 2.30 | `SUPPORTED_ESTIMATE` |
| MEV16 | Retail sales growth | 0 | -0.1468 | -0.1614 to +0.0072 | 97% | 3.47 | `SUPPORTED_ESTIMATE` |
| MEV20 | Consumer confidence | 0 | -0.0452 | -0.0708 to +0.0218 | 86% | 3.22 | `SUPPORTED_ESTIMATE` |
| MEV05 | Policy interest rate | 0 | +0.5096 | -0.6188 to +0.7150 | 86% | 1.77 | `SUPPORTED_ESTIMATE` |
| MEV14 | Household disposable-income growth | 0 | -0.2460 | -0.4250 to +0.2369 | 87% | 2.12 | `SUPPORTED_ESTIMATE` |
| MEV09 | Residential property price index | 0 | -0.0640 | -0.0985 to +0.0745 | 78% | 1.70 | `DIAGNOSTIC_ONLY` |
| MEV03 | Unemployment rate | 0 | +0.2831 | -0.1428 to +0.7667 | 90% | 2.32 | `SUPPORTED_ESTIMATE` |
| MEV11 | Equity market index | 0 | -0.0247 | -0.0506 to +0.0368 | 84% | 3.22 | `SUPPORTED_ESTIMATE` |
| MEV06 | Three-month interbank rate | 1 | +0.1836 | -0.2025 to +0.4319 | 82% | 2.22 | `SUPPORTED_ESTIMATE` |
| MEV12 | Nominal effective exchange rate | 1 | +0.0891 | -0.0994 to +0.2258 | 72% | 1.90 | `DIAGNOSTIC_ONLY` |
| MEV04 | CPI inflation | 0 | +0.0060 | -0.4610 to +0.2712 | 30% | 1.34 | `DIAGNOSTIC_ONLY` |

## Factors this book does not carry

An absent factor is `UNAVAILABLE`. It is never a sensitivity of zero, and no value is imputed for it from a related series.

| Factor | Why |
|---|---|
| MEV02 | This release publishes only the headline GDP series for the Retail book; the non-oil split is not generated for it. |
| MEV07 | Oil is generated as a corporate-book driver. The Retail book has no series for it and none is imputed from the headline. |
| MEV08 | Production volumes are generated for the corporate book only. |
| MEV10 | Commercial property is a corporate-book series. Residential property (MEV09) is the Retail book's property factor and is not a substitute for it. |
| MEV13 | Aggregate private-sector credit growth is generated for the corporate book only. |
| MEV17 | Industrial production is generated as a corporate-book driver. |

## Using a slope

Section 7.4's worked example, which is also an oracle in `tests/cockpit_v4/test_whatif_sensitivity.py`:

> Unemployment 6.0% cut by 10% is **5.4%**, a change of **−0.6 percentage points** — not −4% and not a ten-point move. At a slope of +0.20 PD points per unemployment point, a baseline PD of 3.00% becomes **2.88%**.

Two translations are offered by name and neither is substituted for the other: `linear_sensitivity_times_change` is the reader's own sensitivity-times-change reading, and `fitted_link_finite_difference` adds the fitted linear-predictor change to the observed baseline logit and inverts, so a zero shock returns the observed baseline exactly. A shock outside the fitted range carries an extrapolation warning.

A row whose readiness is not `SUPPORTED_ESTIMATE` is **refused** for automatic translation. The reader may still state the parameter change they want to assume, and it is then applied and labelled as `USER_ASSUMPTION` rather than as an estimate.

## Staleness

Each row stores `source_release_id` and a `source_fingerprint` of `7e4fce428ba34860…`. That fingerprint is a SHA-256 over the exact period-level series the fit consumed, not the release's own fingerprint (`0550a2e6c3390cff…`): an artifact stored inside the release it describes cannot carry a fingerprint taken over bytes that include it. A fit whose stored digest does not match the one recomputed from the release in use is `STALE` and is refused.

# Scorecard Metrics

Every metric the engine computes, its definition, what it must never be read
as, and the guard that stops it being computed where it is undefined.

All of it is `backend/scorecard/metrics.py`. Nothing here is computed anywhere
else.

---

## 1. Precision

Validation statistics on the unit interval are shown at **four decimals**.
Rates, money and counts follow the platform's two-decimal display contract.

This is deliberate, not an oversight. An AUC that moved from 0.7179 to 0.7104
is the finding, and at two decimals both months read 0.72. A Brier score of
0.0523 shown as 0.05 has lost the quantity. `backend/scorecard/metrics.py`,
`diagnostics.py` and `frontend/src/lib/scorecard-format.ts` are allowlisted in
`scripts/check_decimals.py` with that reason recorded; every rate and amount
on the validation screens goes through the contract as everywhere else.

---

## 2. Discrimination — does the score RANK risk correctly

| Metric | Definition |
|---|---|
| AUC | Area under the ROC curve, with a 95% interval |
| Gini | `2 * AUC - 1` — a critical check asserts the two agree |
| Accuracy Ratio | Another name for Gini |
| KS | The maximum gap between the cumulative bad and good distributions |
| Gains / lift | By decile of score |

**Requires a matured outcome.** **Reads the registered score direction** —
`HIGHER_SCORE_IS_BETTER` or `LOWER_SCORE_IS_BETTER`, both correct, and they
invert every statistic. Reversing the direction reflects AUC about 0.5, and a
critical check asserts exactly that, because a metric that ignored the
direction would produce a plausible number on the wrong side.

**Never read as** a probability that the model is right, or a rating, or a PD.

---

## 3. Calibration — is the predicted LEVEL right

| Metric | Definition |
|---|---|
| Observed default rate | Realised bads over the matured cohort |
| Average predicted PD | Mean of the model's PD over the same rows |
| Calibration in the large | Observed minus expected, overall |
| Calibration slope | Regression of the outcome on the logit |
| Brier score | Mean squared error between PD and outcome |
| Log loss | Mean negative log likelihood |
| Bucket RMSE | Root mean squared error across score bands |
| MAPE | Mean absolute percentage error across bands — **guarded** |

**Requires a matured outcome.** Predicted and observed are computed on the
same rows.

**MAPE is guarded.** It is not reported for a band whose observed rate is at
or near zero, where the ratio is unbounded and the number would be arithmetic
rather than a measurement. `mape_status` says which bands were excluded and
why; a MAPE reported without that statement is a critical failure.

---

## 4. Stability — has the population moved

| Metric | On what |
|---|---|
| Score PSI | The **score** distribution, against the declared baseline |
| Variable CSI | **One variable's** bins, against the same baseline |
| Missing / unseen bin rates | Per variable |

**Needs no outcome**, so it is available on the six open months — which is
what makes those months useful rather than blank.

PSI and CSI are different measurements on different distributions. A critical
check asserts they name different columns and report different kinds, because
answering a CSI question with a PSI figure looks entirely right.

**The 0.10 and 0.25 cut-offs are a scorecard convention, not a regulatory
threshold.** They are seeded as `DEMO POLICY` so the dashboard has something
to compare against, and every table that shows them shows their source.

Baseline is the **development sample** unless something says otherwise.
Changing the baseline mid-series produces a trend that measures the baseline.

---

## 5. Variable diagnostics

Per variable: standalone AUC/Gini/KS, Information Value under the approved
bins, missing and special-bin rates, whether the variable is in the active
model, and its coefficient.

**A variable's Gini is not the model's Gini.** Every result is labelled as the
variable's, and the corpus has a whole family about the confusion.

IV strength labels (weak/medium/strong) are a **modelling convention**, not a
regulatory classification, and the payload says so.

A categorical with no Weight of Evidence mapping returns a "no ordering"
result rather than crashing or inventing one.

---

## 6. Implementation replication

Recomputes bin, Weight of Evidence, logit, PD and score from the **stored**
binning specification and the **stored** equation, then compares against what
the lake holds. Reports the maximum absolute difference at each stage, the
mismatch count and rate, and the rounding tolerance.

**Needs no outcome.** Uses the registered equation, never a refit — comparing
production against a refit tests nothing about production.

---

## 7. The guards

| Guard | Refuses |
|---|---|
| `require_matured` | Any outcome metric on an open performance window |
| Sample sufficiency | A statistic on too few observations or too few defaults |
| Single outcome class | Discrimination where every row is good, or every row bad |
| `_guarded_mape` | MAPE on a near-zero band |
| `_risk_ordered` | Any metric that has not read the score direction |
| PD bounds | A predicted probability outside [0, 1] |

Each raises `MetricError` rather than returning something plausible. A
returned value would look entirely reasonable, which is the whole problem.

---

## 8. Limits

Fifteen seeded limits, all `DEMO POLICY`, covering: `auc`, `gini`, `ks`,
`gini_deterioration`, `score_psi`, `variable_csi`, `brier_score`,
`bucket_rmse`, `calibration_in_the_large`, `implementation_mismatch_rate`,
`missing_rate`, `special_bin_rate`, `override_rate`, `minimum_observations`,
`minimum_defaults`.

Five statuses: `PASS`, `WATCH`, `BREACH`, **`NO APPROVED LIMIT`**,
**`NOT MEASURED`**. The last two are different facts and neither is a pass.

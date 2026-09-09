# Independent numerical reconciliation

Every validation statistic this module publishes, computed a second time by a
path that shares no code with the first.

Reconciled at `f7e9e98` on branch `claude/scorecard-validation-intelligence`.
Reproduce with:

```bash
.venv/bin/python -m pytest tests/reconciliation/ -q
```

## Why this document exists

A validation product cannot pass its own gate by testing itself. If
`tests/scorecard/test_metrics.py` computes an AUC with
`backend.scorecard.metrics` and compares it against a number
`backend.scorecard.metrics` produced earlier, the test proves the function is
deterministic and nothing else. It would agree, to fifteen decimal places,
with a function that had the tie handling backwards.

So the reconciliation lives in `tests/reconciliation/independent.py`, which
imports `pandas`, `numpy` and nothing from `backend.scorecard`. It reads
the parquet partitions off disk with its own reader and recomputes each
statistic from its textbook definition, using a **different algorithm** from
the production kernel wherever a different one exists. That the independent
path stays independent is itself asserted —
`test_the_independent_path_shares_no_kernel` reads the module's own source
and fails if a `backend.scorecard` import appears in it.

## Where the two algorithms differ

| Statistic | Production | Independent path |
|---|---|---|
| AUC | Mann-Whitney U on midranks, over a compressed count table | Trapezoidal integration of the empirical ROC, walking distinct thresholds and consuming tied blocks whole; **and separately** an exhaustive pairwise concordance count |
| Gini | From the same count table | `2·AUC − 1` on the trapezoidal AUC |
| KS | Read off the same count table AUC uses | Two empirical CDFs built by independent sorts and differenced point by point |
| Calibration (O/E) | Score-band aggregation | Ungrouped portfolio means: mean observed over mean predicted |
| PSI | Shared `_shift` helper with a share floor | `Σ (aᵢ − eᵢ)·ln(aᵢ/eᵢ)` written out, refusing an empty bin rather than flooring it |
| IV / WOE | `binning._woe_and_iv` over approved bins | Counted directly from the `<variable>_bin` column, logarithms written out |
| Implementation | `metrics.replicate` | The published coefficients applied row by row, and `1/(1+e^-logit)` by hand |

The KS entry is the one worth reading twice. Two statistics computed off one
intermediate agree with each other whether or not the intermediate is right,
so KS gets its own route to disk rather than sharing AUC's.

## The reconciled figures

Production against independent, on the matured cohort of each scorecard.

| Model | Statistic | Production | Independent | Absolute difference |
|---|---|---|---|---|
| Retail Application | AUC | 0.706209951826056 | 0.706209951826056 | **0.00e+00** |
| Retail Application | Gini | 0.412419903652113 | 0.412419903652113 | **0.00e+00** |
| Retail Application | KS | 0.303771556402135 | 0.303771556402135 | **0.00e+00** |
| Retail Application | AUC (pairwise) | 0.706209951826056 | 0.706184031250000 | 2.59e-05 |
| Retail Application | O/E | 1.058581032349068 | 1.058581087227671 | 5.49e-08 |
| Retail Application | IV, bureau_score | 0.473574 | 0.473573845421405 | 1.55e-07 |
| Retail Behaviour | AUC | 0.723148497315559 | 0.723148497315559 | **0.00e+00** |
| Retail Behaviour | Gini | 0.446296994631118 | 0.446296994631118 | **0.00e+00** |
| Retail Behaviour | KS | 0.326556375945928 | 0.326556375945928 | **0.00e+00** |
| Retail Behaviour | AUC (pairwise) | 0.723148497315559 | 0.716041968750000 | 7.11e-03 |
| Retail Behaviour | O/E | 0.964424678726134 | 0.964424615811533 | 6.29e-08 |
| Retail Behaviour | IV, bureau_score_latest | 0.517025 | 0.517024569359854 | 4.31e-07 |
| Saudi SME | AUC | 0.654697755235667 | 0.654697755235667 | **0.00e+00** |
| Saudi SME | Gini | 0.309395510471334 | 0.309395510471334 | **0.00e+00** |
| Saudi SME | KS | 0.224068518161370 | 0.224068518161370 | **0.00e+00** |
| Saudi SME | AUC (pairwise) | 0.654697755235667 | 0.648210300429185 | 6.49e-03 |
| Saudi SME | O/E | 1.134084172715364 | 1.134084172715364 | **0.00e+00** |
| Saudi SME | IV, dscr | 0.133222 | 0.133221834840775 | 1.65e-07 |

Sample counts, reconciled separately, because a metric computed correctly over
the wrong rows is wrong:

| Model | Engine observations | Rows on disk | Events |
|---|---|---|---|
| Retail Application | 342,740 | 342,740 | 20,552 |
| Retail Behaviour | 475,000 | 475,000 | 36,389 |
| Saudi SME | 24,119 | 24,119 | 1,398 |

## Every tolerance, and why

Four tolerances appear in `tests/reconciliation/test_numbers.py`. Each is
stated in the assertion it governs. **None was widened to make a figure
agree** — the table above is the evidence: the ones that matter came back at
exactly zero.

| Tolerance | Where | Why |
|---|---|---|
| **1e-9** | AUC, Gini, KS | Float summation order and nothing else. The equality of the rank-sum and the trapezoidal forms is a theorem, not an approximation. Observed difference: 0.00e+00 on all three books. |
| **0.02** | AUC by exhaustive pair count | A **sampling** tolerance, stated in advance. The count runs on 4,000 rows per class (16 million comparisons) rather than the full cross-product (140 million on the SME book). The standard error of an AUC at that size is ≈0.006, so 0.02 is about three of them. Largest observed: 7.11e-03. This is not a tolerance on the arithmetic — the 1e-9 row above pins that. |
| **1e-6** | O/E, score PSI, challenger difference | The engine publishes these rounded. Observed: 5.49e-08 or better, and exactly zero on the SME book. |
| **5e-7** | Information value | The engine publishes IV rounded to six decimals. Observed: 1.65e-07 or better. |

### The one difference that is not float noise

Production applies **Laplace smoothing of 0.5 per bin** to every weight of
evidence (`backend/scorecard/binning.py::SMOOTHING`). A bin with zero bads
gives an infinite WOE which then propagates through every score in that bin,
so the correction exists for a reason and is declared in the source rather
than being an unexplained epsilon.

The textbook IV and the smoothed IV differ in the fourth decimal — on `dscr`,
0.13385 unsmoothed against 0.13322 published. That is **not** absorbed by a
tolerance. The independent path reproduces the smoothing policy explicitly
(`independent.woe_and_iv(..., smoothing=0.5)`) and reconciles against the
published figure at 5e-7, and a separate test
(`test_the_smoothing_is_the_only_difference_and_it_is_small`) measures the
gap the policy creates and requires it to stay below 0.01. If half an
observation per bin ever moved an IV in the second decimal, the correction
would be doing the work instead of the data, and that test would say so.

The same distinction applies to PSI: production floors each share, this
implementation refuses an empty bin. On all three books no bin is empty on
either side, so the two agree exactly; where a bin is empty the test names the
case and skips it rather than passing silently.

## What is reconciled, per scorecard

| | Retail Application | Retail Behaviour | Saudi SME |
|---|---|---|---|
| AUC (two independent algorithms) | ✓ | ✓ | ✓ |
| Gini | ✓ | ✓ | ✓ |
| KS | ✓ | ✓ | ✓ |
| Rank ordering, decile event rates | ✓ | ✓ | ✓ |
| Score direction (riskiest vs safest decile) | ✓ | ✓ | ✓ |
| Observations and events against disk | ✓ | ✓ | ✓ |
| Calibration O/E | ✓ | ✓ | ✓ |
| PD is a probability in [0, 1] | ✓ | ✓ | ✓ |
| Score PSI | ✓ | ✓ | ✓ |
| PSI of a population against itself is 0 | ✓ | ✓ | ✓ |
| Variable IV / WOE (≥3 variables each) | ✓ | ✓ | ✓ |
| Variable PSI (CSI, ≥2 characteristics each) | ✓ | ✓ | ✓ |
| Champion/challenger AUC difference | — | — | ✓ |
| Challenger PD is a probability | — | — | ✓ |
| Implementation score replicated by hand | ✓ | ✓ | see below |

## The one thing that cannot be reconciled, and why

**The Saudi SME champion's implementation cannot be replicated.** This
deployment holds no published coefficient equation for it —
`model.approved_equation()` raises, and the engine's own IMPL-REPLICATE
returns NOT_APPLICABLE with that reason rather than a pass or a zero
difference.

That is asserted rather than skipped
(`test_the_sme_scorecard_says_it_cannot_be_replicated`), because "we could
not check" and "there was nothing to check" are different statements and only
one of them belongs in a validation report. The two retail scorecards do
publish equations and both replicate to better than 1e-6 on logit and PD.

## Regression fixtures

The synthetic lake is deterministic — the same builder, the same seed, the
same partitions — so the figures above are themselves the fixture. Any change
to a kernel that moves an AUC will move it away from a number that is written
down here and asserted in `tests/reconciliation/test_numbers.py` against a
path that did not change with it.

Two properties are asserted rather than pinned to a value, because they must
hold on any data: PSI of a population against itself is exactly zero, and
flipping the score direction takes AUC to `1 − AUC`.

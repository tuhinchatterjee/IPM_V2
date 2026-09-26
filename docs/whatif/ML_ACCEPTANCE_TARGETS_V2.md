# Predeclared acceptance targets — ECL emulator, model version 2

**Written and committed before version 2 is fitted and before its held-out
test split is read.** `ML_ACCEPTANCE_TARGETS.md` is version 1's contract and
is **not edited**: a threshold moved after seeing a result is a description of
the result, and a document rewritten after the fact cannot prove it was
written before.

Every gate below is **identical to version 1's**. Nothing is loosened, no
materiality definition changes, and no threshold moves. The only change this
document declares is a change of *component*, and §4 gives the reason and the
evidence it rests on.

> Measured on **generated books**. Passing establishes that an emulator can
> learn `reference_ecl.py` on `v4-whatif-*-s1`. It establishes nothing about
> any bank's ECL engine, and no document may say otherwise.

---

## 1. Why there is a version 2 at all

Version 1 was honest and incomplete. Its own card says so:

* **Corporate** passed G1–G4 (1.97% / 1.47% / 2.53% / 5.06%) and the weight
  fit put **1.000 on XGBoost**. Reported as `SINGLE-MODEL RESULT`, because
  that is what it is.
* **Retail** passed G1–G3 and **failed G4** at 38.02% against 15%, and the
  weight fit put **1.000 on LightGBM**.

Section 11.3 asks for a blend. Neither book produced one, and calling a
single-model result a blend is the specific dishonesty gate **B4** exists to
prevent. So version 1 satisfies the accuracy requirement on Corporate and
does **not** satisfy the blended-Method-2 requirement on either book.

**The optimiser is not the problem, and this document is not claiming it was.**
`blend.fit` solves the constrained least-squares problem exactly, on every one
of the seven faces of the three-component simplex, and takes the feasible face
with the lowest loss. A `1 / 0 / 0` outcome from that procedure is the true
global optimum for those component predictions, not a search that gave up. No
fix to the optimiser is proposed and none would change the answer.

## 2. What would be illegitimate here, and is not being done

| Tempting | Why it is refused |
|---|---|
| Re-solve the weights on a different loss until a mixture appears | The weights would then be fitted to produce a word. B2 asks for weights fitted on out-of-fold predictions by a deterministic optimiser, and they were. |
| Floor every component at some minimum weight | A hardcoded mixture presented as a fitted blend is exactly what §11.3 forbids. |
| Raise G4 so Retail passes | A threshold moved after the fact is not a threshold. |
| Redefine a material group by ECL share instead of observation count | Materiality was declared in advance as **≥ 100 test observations**, and `score_band = A` has 652. |
| Tune anything against the test split | §11.2. The test split is read once, per model version. |

## 3. What is unchanged from version 1

**The target.** `ecl_rate` on `ead_sar_mn`, converted to currency for every
currency-denominated metric. Every target-derived column stays excluded from
X, and the test that enumerates the feature list still fails if one appears.

**The split.** Chronological by distinct reporting period, 60/20/20, with a
one-period embargo at each boundary: 11 train, 3 validate, 4 test, 2
embargoed, per book. Expanding-window folds inside the development window
only. Split assignment persisted per row.

**The gates.**

| # | Gate | Threshold |
|---|---|---|
| **G1** | Out-of-time currency WAPE | ≤ 10% |
| **G2** | Aggregate bias | ≤ 2% |
| **G3** | Per-period bias, worst test period | ≤ 5% |
| **G4** | WAPE in every material group (≥ 100 test observations) | ≤ 15% |
| **G5** | Zero shock ⇒ exactly zero ML change | exact |
| **G6** | Perturbation direction agrees with `reference_ecl.py` | ≥ 90% of probes |

| # | Blend gate | Threshold |
|---|---|---|
| **B1** | Components | 3 per book |
| **B2** | Weights | non-negative, sum to 1, fitted on out-of-fold predictions by a deterministic constrained optimiser |
| **B3** | Materiality | weight < 0.05 reported immaterial, by name |
| **B4** | Honesty | a `1 / 0 / 0` outcome is reported as a **single-model result**, not relabelled a blend |

**The search budget.** ≤ 12 configurations per family per book, ≤ 3 folds,
≤ 600 rounds, patience 50, fixed seeds, every trial recorded.

## 4. The one change, and the evidence for it

**B1's third component becomes a regularized additive model in LOG space
(`additive_log`), replacing the additive model in LEVELS
(`additive_spline`).** Two boosters stay exactly as they were.

### The argument is structural, and it was available before any model was fitted

The target is **multiplicatively generated**. `reference_ecl.py` builds ECL
from a product of a probability, a loss rate and an exposure, and P5a measured
the published Stage 1 ECL sitting about **4%** away from `ead × pd × lgd`. A
basis that is additive in the levels of those variables cannot represent their
product: no sum of univariate spline terms in `pd`, `lgd` and `ead` equals
`pd × lgd × ead`. It is not a question of enough knots.

A basis additive in the **logs** represents it exactly, because
`log(pd × lgd × ead) = log pd + log lgd + log ead`. That is the same family of
model — a spline expansion into a ridge — asked to be additive on the scale
the target is actually additive on.

### The evidence is development-only, and that is checkable

The numbers that motivate the change are **fold errors inside the development
window**: mean fold WAPE **0.32173** (Corporate) and **1.81797** (Retail) for
`additive_spline`, against 0.03039 / 0.07675 for XGBoost. Those are the
cross-validation scores published in version 1's card, computed on
expanding-window folds over train+validate periods. **No test period entered
them.** A component scoring 182% on development data is one the weight fit
will always send to zero, and diagnosing why is not test-set tuning.

### What this is expected to do, said in advance so it can be wrong

A third component that is **competitive** and **structurally different from a
tree** is the condition under which a convex combination can beat its best
member. Providing that condition is a legitimate way to pursue a blend.

**It is not a guarantee of one.** If the weight fit still lands on a single
component, version 2 is a single-model result and will be reported as one
under B4, exactly as version 1 was. The purpose of this change is to give a
blend a fair chance to exist, not to manufacture the appearance of one.

### Specification

* `log1p` on the target rate; `log1p` on non-negative numeric features,
  identity on features that can be negative (a signed ratio is not logged).
* Spline expansion and ridge as before; the grid keeps its 12 configurations
  (`alpha` × `n_knots`), so the declared budget is unchanged.
* Back-transformed with a **Duan smearing estimator** computed on the
  development residuals only, because `expm1` of a mean log is not the mean.
  The smearing factor is published in the card.
* Fitted, tuned and weighted entirely inside the development window.

## 5. Retail's G4, restated

Version 1 failed it. Version 2 is fitted and then **the test split is read
once**. If G4 still fails:

* Retail Method 2 is **MODEL_NOT_READY**, with the gate named and its measured
  value beside its threshold;
* its estimate appears **only** in model-development evidence, marked FAILED
  VALIDATION, and **not** in the ordinary method comparison;
* the conversational answer says Method 2 is unavailable for Retail and why;
* Delta and User-defined continue normally, and the journey continues with
  them.

That is the reporting path whatever version 2 measures. It is written here so
it is not a decision taken after seeing the number.

## 6. Corporate, restated

If version 2 blends and passes, Corporate has a validated blended Method 2.

If it remains single-component, Corporate's measured accuracy is retained as
evidence and its Method 2 result is published in the method comparison
carrying, in these words, `SINGLE-MODEL RESULT` and a statement that it does
**not** satisfy the requested blended Method 2 requirement. It is not declared
compliant, and the word "blend" is not used for it.

## 7. Reproducibility

No model binary is committed. `requirements-whatif.txt` pins every library
exactly, seeds are fixed per component, the blend weights are solved by
enumerating the faces of the simplex rather than by an iterative optimiser,
and `scripts/whatif/train_emulator.py` regenerates every artifact from the
versioned candidate release. `scripts/whatif/verify_artifacts.py` rebuilds
both books and compares artifact hashes, fold errors, gates and weights
against what was published.

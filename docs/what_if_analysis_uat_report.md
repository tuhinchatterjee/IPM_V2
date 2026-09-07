# What-If Analysis — UAT readiness report

**Branch:** `claude/what-if-analysis-rebuild`
**Baseline:** `origin/claude/integration-rehearsal` @ `4f7956666feca2822cc74effd335823ba1a391e9`
**Not merged. No pull request opened.**

The bar this is written against: *a senior credit-risk / IFRS 9 professional can
use What-If Analysis conversationally, trust the numbers, understand every
material ECL movement, drill into it with follow-up questions, and see
internally coherent IFRS 9 data.*

---

## 1. What manual acceptance found, and what happened to it

Fourteen findings. None is closed by an assertion; each has a test, a browser
journey or a measured figure named beside it in
`docs/what_if_analysis_requirement_audit.md`.

Four of them were not user-interface problems at all. They were the visible end
of defects in the book underneath, and the book was rebuilt.

**Stage 3 moved and nothing explained it.** Twenty-seven borrowers were
credit-impaired by days past due, still rated `B-`, still carrying a ten per
cent probability of default — so a rating shock aimed at performing names moved
the provision on defaulted ones. Ninety days past due is the presumption of
default and nothing in this book rebuts it now, so `default_flag`, Stage 3, the
`D` grade and a defaulted PD agree by construction.

**Seventy obligors sat in the IFRS 9 book at zero exposure** — rated, staged,
provisioned at nothing — because every facility they held had matured while the
relationship was still on book.

**Stage 2 walked from 6% of the book to 75% and back** as the credit cycle
turned, because the SICR reference held its own vintage while the
point-in-time PD moved with the cycle: the trigger was measuring the economy
rather than the borrower. It runs 7% → 22% → 19% now.

**The average twelve-month PD moved twenty-three-fold in four years**, because
the cycle was counted twice — the grade absorbed 45% of it and the conditioning
then applied all of it again.

And one that was neither the screen nor the data: **thirty-one columns were
invisible to every reader.** A dataset published through Data Builder overrides
the file catalogue, so a rebuilt lake with new columns is refused with "not a
field of dataset" until the published entry learns about them. The build
reconciles them now and says what it added.

## 2. The numbers a reader can check

**Portfolio reconciliation, 16 quarters.** Every quarter's totals against the
sum of every partition of them — Stage, sector, segment, rating. All four,
every quarter, within the precision the book publishes.

**Rating distribution, Q2 2026.** Nineteen of nineteen grades populated, the
through-the-cycle scale strictly ordered, and coverage running from 0.01% at
AAA to 60.03% at D with no inversion anywhere in between.

**Spot check.** Ten borrowers, stratified across Stage and sector on a fixed
seed rather than chosen, followed across eight quarters with the arithmetic
shown. Every row ties to the governed product plus its overlay to within
0.0001.

All three are `scripts/whatif_reconciliation_report.py`, written to
`docs/whatif_reconciliation.json`, and asserted in the suite so a change that
breaks one is found by the build rather than by somebody reading the report.

## 3. What the product can now be asked

Every message in a thread is classified before anything is done with it, and
only one of the three classes may touch the scenario:

* **EXPLAIN** — "Why did Stage 3 ECL increase?" · "Which borrowers contributed
  most?" · "How much of this is the measurement basis changing?"
* **VIEW** — "Show this by sector." · "Break it down by rating."
* **MODIFY** — "Now increase LGD by 5 points." · "Undo the last step."

An explanation is computed from the borrower rows the run already produced, so
asking why a number moved cannot move it. Eighty-one evaluation cases pin the
reading, and none of them needs a language model.

## 4. Verification

Three readiness cycles, everything each time, in the order a build server would
run it. Cycles 2 and 3 are identical in every figure.

| | Result |
|---|---|
| Backend suite | **14,129 passed**, 42 skipped, 6 failed |
| The six failures | identical every cycle, and every one reproduced on the baseline `4f79566` with the same lake and the same database. None is in What-If, and none is new — there were six before this work on a suite eleven hundred tests smaller. |
| Frontend tests | **551 passed** |
| Types, lint, display contract | clean |
| Browser journeys | **11/11** original · **8/8** manual-failure · **185 checks** |
| Reconciliation report | 16/16 quarters, 19/19 grades, 10 borrowers × 8 quarters |

The full table, the six failures named individually, and the suites this work
added are in `docs/what_if_analysis_as_built.md` §10.

## 5. What is NOT claimed

* The macro series in this installation are generated from a single latent
  cycle factor, so GDP growth, the oil price and the policy rate move together
  by construction. There are effectively sixteen independent macro
  observations. Macro variables are therefore not model features and the
  ten-variable What-If runs on declared sensitivities, which are management
  assumptions rather than estimated elasticities.
* The reported ECL on this book is close to a closed form, so a very high
  R-squared is MECHANICAL and is not evidence of predictive skill. It is said
  on the model card.
* The model estimates a rate, not a cash flow. There is no contractual
  cash-flow projection, no lifetime PD term structure and no effective-interest
  discounting.
* Covenants are reported under stress, not re-evaluated.
* The data is synthetic and says so on every row.

---

## 6. Status

**READY FOR UAT.**

Against the directive's own bar — *do not claim ready with any FAIL, any
unresolved calculation bug, any unreconciled dataset, an ML loader traceback,
lost filter logic, an inability to answer follow-up questions, a raw JSON
screen, missing Back navigation, incorrect migration percentages, unexplained
Stage 3 movement, or zero PD and measurement-basis attribution on a Stage 1→2
movement*:

| Blocker | State |
|---|---|
| Any FAIL | None in What-If. Six pre-existing failures elsewhere, each reproduced on the baseline, each named in as-built §10 |
| Unresolved calculation bug | The exposure bound was the last one, found by red-teaming and fixed at source |
| Unreconciled dataset | 16 of 16 quarters reconcile across four partitions |
| ML loader traceback | Refused in a sentence; journey D asserts no `@rpath` reaches a screen |
| Lost filter logic | 207 borrowers, not 3,244, and the screen restates both filters first |
| Cannot answer follow-up questions | Five asked and answered in a browser, none of them moving the figure |
| Raw JSON screen | None; journey E asserts it |
| Missing Back navigation | On all three screens; journey B clicks each |
| Incorrect migration percentages | Row-normalised, declared, and every populated row sums to 100% of its own origin grade |
| Unexplained Stage 3 movement | Every movement carries a named mechanism, and the mechanisms sum to the whole |
| Zero PD / basis attribution on a Stage 1→2 movement | The measurement basis is a driver of its own, with the borrowers, the exposure and both PDs |

Not merged. No pull request opened. The branch is
`claude/what-if-analysis-rebuild`.

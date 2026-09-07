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
asking why a number moved cannot move it. Seventy-six evaluation cases pin the
reading, and none of them needs a language model.

## 4. Verification

See `docs/what_if_analysis_as_built.md` §10 for the full table and the three
readiness cycles.

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

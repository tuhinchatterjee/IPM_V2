# What-If Analysis — UAT readiness report

**Branch:** `claude/what-if-analysis-rebuild`
**Baseline:** `origin/claude/integration-rehearsal` @ `4f7956666feca2822cc74effd335823ba1a391e9`
**Not merged. No pull request opened. No other branch touched.**

The bar this is written against:

> A senior credit-risk or IFRS 9 professional can use What-If Analysis
> conversationally, trust every number, understand exactly why each one moved,
> judge whether the scenario is defensible, drill into it, take the detail away
> in a form an auditor accepts, and hand the feature a different book without
> rewriting it.

---

## 1. Status

**READY FOR UAT.**

**ECONOMIC VALIDATION: PASS** — 44 of 44 book checks and 50 of 50 What-If
scenario checks. The shipped Corporate IFRS 9 book has been validated not only
for schema, ranges and arithmetic reconciliation, but also for longitudinal
credit-risk and IFRS 9 economic coherence.

Six readiness cycles were run, each exercising the whole feature: lint,
typecheck, the unit and invariant suites, the evaluation corpus, the red team,
the API surface, fifteen browser journeys against a real Chromium, the
manual-failure journeys, the performance budgets, **the book's economic
coherence, the What-If scenario economics**, and both contracts against the
book on disk.

| Cycle | Result |
|---|---|
| 1 | 13 of 14 steps. One failure, in the harness, fixed. |
| 2–3 | Every step passed. |
| — | *Economic validation found four defects in the book. Fixed; book rebuilt; model retrained.* |
| 4–6 | Every step passed, with both economic harnesses added to the cycle. |

Logs and machine-readable results: `docs/readiness/cycle-{1..6}.{log,json}`.

Cycle 1's failure was in the cycle harness rather than the product: it read
`healthy` from the top level of the schema endpoint, which serves the contract
with the installation's comparison nested inside it, so a healthy book was
reported as a failure. That is worth recording rather than quietly correcting —
a readiness harness that reports a false failure is a harness that will
eventually be ignored.

## 1b. The economics, which the previous pass did not validate

The previous report said, correctly, that none of its verification validated
the shipped book's economics. Asking fourteen ordinal and distributional
questions about the book found **six defects**, none of which any schema check,
range check or reconciliation could have seen. All six are fixed in the
generator rather than absorbed into a test.

| Found | Was | Now |
|---|---|---|
| The rating was re-binned from a score each quarter, not carried | 25.8% quarterly stability, 1.31 notches average movement, every AAA name downgraded the next quarter | **86.5%**, 0.34 notches, both ends of the scale stable |
| Stage 2 cured on PD noise | 36% of Stage 2 exposure per quarter, peaking at 49.8% | **20.9%**, via a two-quarter cure probation |
| The ML methodology ignored exposure | "EAD +20%" priced at **0.05×** the Delta answer | **1.06×** |
| The committee override was a per-row coin toss | 7% of the book flipped a notch every quarter | drawn per borrower |
| The governed rule set stopped reproducing the book *(caused by the probation fix)* | 90–211 borrowers disagreed per quarter | **zero**, in all 16 quarters |
| The model smooths the stage boundary | undisclosed | disclosed on the reader's own scenario |

The fifth is the one that mattered most: the baseline column of every What-If
is the reported book staged by that rule set, so a disagreement means every
scenario measures a movement from the wrong starting point.

Full detail, every table, and how each bound was derived:
`docs/what_if_ifrs9_economic_validation.md`.

---

## 2. What the last pass of work actually found

Seven defects, none of which any test in the repository was looking for. They
are listed because the fixes are the substance of this pass, not because a
count is impressive.

**The user-defined macro sensitivity was unreachable from the browser.**
`StateIn` had no `sensitivities` field, so the state returned by
`/macro/configure` carrying an override was posted back to `/execute` and the
override was silently discarded. Every part of the feature worked in isolation
and the whole did nothing. A contract that cannot read what the previous call
emitted is the shape of this bug, and it now round-trips — and refuses a
relationship it cannot read rather than dropping it.

**The thread never told the backend a result was on screen.** The same sentence
is a different intent depending on what is there: "what would the ML model
say?" with a result behind it is a comparison, without one it is a question
about the methodology. So every intent that only exists after a result silently
degraded to its empty-thread fallback, and `/investigate` — which exists to
answer questions about a result — was classifying with no context at all.
Browser journey 14 caught it.

**A cached result with no owner was readable by every signed-in analyst.** The
module's own docstring says a run is readable only by the account that produced
it and that handing one over on a guessed id would leak the portfolio; the
implementation said `self.owner is None or self.owner == owner`. The frame it
holds is the book at borrower grain.

**Four macro variables were measured in the wrong unit.** Index and price
columns were differenced raw against an adverse unit quoted as a percentage,
and the policy rate's column is in percent against an adverse unit of 200 basis
points. The fitted slope for the policy rate came back implying a PD multiplier
of 46, offered to a reader as an empirical estimate.

**The current account's adverse direction was inverted.** Written `+2.0` for a
"2pp deterioration" when a deterioration is a fall, so the engine applied the
adverse sensitivity to a 2pp improvement — a stress that made the book better.
It was also the only moderately strong empirical fit in the set, and it was
pointing the wrong way.

**The attribution bridge reported "ML model adjustment" on a Delta run.** The
residual was labelled after a methodology that had not priced it, and a
relative tolerance of 1e-6 treated the last digit of a nine-figure sum as a
finding.

**73 of 179 evaluation questions were classified wrongly.** Writing the corpus
by hand and checking it against the classifier — rather than labelling it with
whatever the classifier said — found that the new intents matched only narrow
phrasings while a broad EXPLAIN caught everything else.

---

## 3. The numbers a reader can check

Corporate IFRS 9 book, Q2 2026, 3,241 borrowers, 16 quarters Q3 2022 → Q2 2026,
19-grade masterscale. Delta Model, whole book:

| Scenario | Incremental ECL | Change | Moved to a worse stage |
|---|---|---|---|
| One-notch downgrade | 19,241.8 | +30.5% | 229 |
| LGD +5pp | 6,203.2 | +9.8% | **0** |
| PD +20% | 4,169.3 | +6.6% | 85 |
| GDP −1pp | 3,263.2 | +5.2% | 49 |
| Rates +200bp | 2,531.9 | +4.0% | 40 |

The LGD scenario producing zero migrations is the engine being right: a
loss-given-default shock changes what is recovered, not the likelihood of
default, so the measurement moves and the staging does not.

Plausibility, same book:

| Proposed | Verdict |
|---|---|
| PD +20% | Consistent with recent experience — 43.8% of borrower-quarters saw a move at least this size |
| PD +200% | Historically plausible — 9.7% did |
| PD +2000% | Plausible for selected pockets — 0.31% did |

Performance, median seconds, all inside budget:

| | median | budget |
|---|---|---|
| Read the book (cold / warm) | 1.03 / 0.02 | 8.0 / 1.0 |
| Price a scenario — Delta / ML | 0.66 / 0.79 | 3.0 / 6.0 |
| Attribution, 5 shocks | 0.73 | 6.0 |
| Plausibility (cold / warm) | 2.14 / 0.10 | 8.0 / 1.0 |
| Both methodologies | 1.52 | 10.0 |
| Eleven-sheet workbook | 6.49 | 30.0 |

---

## 4. Verification

| | |
|---|---|
| Evaluation corpus | **179 questions**, all fourteen intents, 2,513 assertions |
| Red team | **54 attacks**, eleven shapes |
| Browser journeys | **15/15**, 153/153 checks, real Chromium against a real backend |
| Manual-failure journeys | **8/8**, 71/71 checks |
| Book economics | **44/44** ordinal and distributional checks |
| Scenario economics | **50/50** across six scenarios |
| Regression | **15,811 passed** across the whole suite |
| Readiness cycles | **6**, the last three clean and including both economic harnesses |

The six regression failures are pre-existing: two in
`tests/evals/test_properties.py`, one multi-analysis reconciliation, two
workbook-formula tests, and one that fails only on test-order pollution. Each
was reproduced on baseline `4f79566` with this same lake and database using a
`git worktree` with `DATA_*_DIR` overrides. **None is in What-If.**

Timing is measured, not asserted. A timing assertion in a test suite fails on a
busy machine and passes on a quiet one, and guards a number nobody wanted; a
row over budget is reported.

---

## 5. What is NOT claimed

Stated here rather than left for UAT to discover.

**That the book's parameters are calibrated to any real portfolio.** Its
economics are now validated for internal coherence — the pieces agree with each
other and behave the way credit risk behaves — but a synthetic book cannot be
validated against a market it does not come from. The integration report
establishes that a column called `pd_12m` exists, is numeric and lies between 0
and 100; the economic validation establishes that it rises with the grade,
tracks the cycle, sits below its own lifetime measure and drives the staging
and the provision the way a PD would. Neither establishes that it *is* a
twelve-month probability of default, and both say so in their own output.

**The ML model reproduces the stage boundary.** It under-prices a Stage 1 → 2
crossing by 3.6% against the governed step, structurally: the step is a change
of measurement basis, and a model fitting a continuous surface cannot reproduce
a discontinuity. Giving it the measured stage and the probation served did not
close the gap. It is disclosed on the comparison, on the reader's own scenario.

**The empirical macro relationships are directional evidence, not
calibrations.** `corporate_macro` is generated from a single latent cycle
factor, so every observed series is a linear function of it plus noise and a
regression recovers the generator's own arithmetic. Sixteen quarters give
fifteen changes. `recommend()` therefore returns the configured sensitivity in
all ten cases, and says why. A canonical domain with genuinely independent
series would make those estimates mean what they appear to mean.

**Re-scoping a step that already exists is not supported.** "Now restrict that
to Contracting" is a modification, but the builder reads a population only off
a new step. The thread answers it as a question and changes nothing — safe,
because it cannot silently move a number. Recorded as a known gap in the
evaluation corpus, with a test that it still behaves as recorded.

**Covenant re-testing under stress is reported, not re-evaluated.**

**The macro sensitivities are declared assumptions.** No screen showing one
fails to say so.

**Facility grain in the export is an allocation.** Staging here is assessed on
the obligor, so there is no facility-level measurement to export. The sheet
carries the borrower's movement apportioned by IFRS 9 EAD share, says so in its
heading and in a column, and sums back exactly.

---

## 6. What a UAT tester should try first

Ordered by how likely each is to find something.

1. **Ask the product about itself** before running anything — "what can this
   do?", "what data is this?", "which fields can I shock?", "how is ECL
   calculated?". None of it should price anything, and none of it should invent
   a capability.
2. **Run a scenario, then ask the same sentence again.** It should modify
   rather than open a second one.
3. **Ask a question that contains an instruction** — "was any of this the
   rating downgrade?" — and check the figure does not move.
4. **Propose an absurd shock** — PD +2000% — and read the plausibility verdict.
   It must place the shock in history and must not state a probability.
5. **Open a macro variable, look at what the history shows, then define your
   own relationship.** Check the figure changes, and check every screen that
   shows it says whose assumption it is.
6. **Ask for the other methodology** from a Delta result and from an ML one.
   The figures must be identical either way.
7. **Download the workbook** and go to `RECONCILIATION` first. Nine tie-outs,
   each a test. Then sum the borrower column and check the difference is the
   one the sheet already told you about.
8. **Change a staging rule and re-run.** The version stamped on the second
   result must not be the default, and the reported book must still be staged
   by the reported policy.
9. **Read `docs/what_if_ifrs9_economic_validation.md` before trusting any
   figure.** It says what the book's economics were validated for, and — in
   its last section — what they were not.

---

## 7. Constraints observed

- Stayed on `claude/what-if-analysis-rebuild` throughout.
- No merge to `main` or to any other branch.
- Lenses, Project Planner and Early Warning untouched.
- No pull request opened.
- No Homebrew or system package installed from application runtime.
- No stack trace reaches a user; a provider that is off is an ordinary state
  and is logged as a reason, not a traceback.

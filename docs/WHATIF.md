# What-If Analysis

Scenario intelligence over the Corporate IFRS 9 book. One question:

> **If I change one or more credit-risk assumptions, what happens to the
> expected credit loss, exactly why does it change, how plausible is that
> scenario against the evidence we have, and can I defend the answer?**

Everything below exists to make each clause of that sentence answerable.

---

## The two rules the whole feature is built on

**A question never changes a number.** Fourteen intent classes fall into three
families, and only one of them — `CHANGES` — may touch the scenario. Asking why
a provision moved cannot move it. The classifier is deterministic, the family
decides whether the state may be written, and an evaluation corpus of 179
labelled questions asserts the boundary holds.

**The engine calculates; the model explains.** Every figure on every screen is
produced by deterministic arithmetic. A model is used only to write prose, it
is handed an evidence packet and nothing else, and the finished prose is
re-read for numbers the packet does not contain. A paragraph carrying one is
discarded rather than shown, because a plausible wrong figure inside a
professional paragraph is the most expensive failure this product can have.

---

## The book

A Hive-partitioned Parquet lake read through DuckDB, at **obligor grain**: one
row per borrower per quarter. Staging is assessed on the counterparty, because
a book that stages one facility of a borrower differently from another is
describing a bank that does not exist.

| | |
|---|---|
| Periods | **16 quarters, Q3 2022 → Q2 2026** |
| Borrowers, Q2 2026 | 3,241 |
| Rating scale | **19 grades** — AAA, AA+, AA, AA−, A+, A, A−, BBB+, BBB, BBB−, BB+, BB, BB−, B+, B, B−, CCC, CC, D |
| Currency | SAR millions |
| Datasets | `corporate_borrower_360`, `corporate_ifrs9`, `corporate_facilities`, `corporate_collateral`, `corporate_macro` |

`backend/whatif/domain.py` is the only door. Every read in the package goes
through it, and a dataset outside that list is refused by name rather than
quietly served.

### Three PDs, and which one is measured

| PD | What it is |
|---|---|
| **TTC** | A property of the grade. The through-the-cycle level the masterscale assigns. |
| **PIT** | A threshold-shift single-factor model with a sector correlation, so a downturn moves a whole sector together. |
| **Lifetime** | A mean-reverting hazard over 4.2 years, reverting at 0.55 — so a stressed borrower is not assumed to stay stressed for four years. |

```
ECL = PD_applicable × LGD × EAD × 1.082
```

Stage 1 is measured on the twelve-month PD, Stages 2 and 3 on lifetime. That
one line is why a Stage 1 → 2 migration multiplies a provision when nothing
else about the borrower moved. The 1.082 is the scenario-weighted factor
(Base 0.50 × 1.00, Upside 0.20 × 0.72, Downside 0.30 × 1.46).

`policy.bounded()` caps a provision at the exposure it provides against: an
expected loss larger than the amount at risk is not a loss.

---

## Staging: two rule sets, never confused

The baseline column is the **reported book**, staged by the governed corporate
policy. The What-If column is staged by **this thread's rule set**. Both are
named, versioned and shown on every result, because a reader has to know which
rules produced which column. No What-If rule ever changes the reported book.

| Governed trigger | Rule |
|---|---|
| Relative PD increase | 12-month PD at least **2×** its level at origination **and** at least **2.00pp** higher |
| Absolute PD level | 12-month PD at or above **13%** |
| Days past due | **30** or more |
| Default presumption | **90** days past due, or a recorded default event |

The What-If default adds two rules a scenario needs and the reported book does
not: a rating deteriorating by 2 or more notches, and a scenario PD at least
2× the borrower's pre-scenario PD. A thread may enable, disable, re-threshold
or recombine any of them, and the composition is stamped on every figure it
produces.

`backend/ifrs9/policy.py` is the single definition. It is deliberately
PD-source-agnostic: nothing in it knows or cares whether the PD it is given was
reported or modelled, which is what makes both sides of the comparison the
same rule.

---

## Two methodologies, one engine

There is exactly one place a scenario is applied: `engine.run()`. It shocks the
borrowers, re-reads the staging criteria against the stressed PD, re-measures,
and hands back the working frame. The methodology decides only how the
**reported** ECL is moved from there.

**Delta Model.** Read the movement out of that measurement as four factors and
carry it onto the reported figure:

```
What-If ECL = REPORTED ECL × PD factor × LGD factor × EAD factor
```

**ML Model — XGBoost.** A per-Stage ensemble trained at borrower-quarter grain
on structural features, anchored to the reported book so it estimates a
*relative* effect and can never restate it. Persisted as native JSON — a format
that is data, not code — because `.pkl`, `.joblib` and `.pt` are refused on
import: a pickle is a program.

Both start from the same shocked book, which is what makes the two answers
genuinely comparable and why there is no second engine to drift away from the
first.

**The gate.** The product asks once per thread, before the first ECL figure,
which methodology to use. It never chooses quietly.

---

## What moved the provision

`backend/whatif/attribution.py` splits the movement by **exact Shapley value**:
each driver's effect is its average marginal contribution across every order in
which the factors could have moved. That is the unique attribution that is
order-neutral, sums exactly to the total, and gives a factor that never moved
an effect of zero. A test asserts the answer does not depend on the order the
shocks were written in.

Anything the drivers do not explain is disclosed on its own line rather than
spread across them, named after the methodology that actually priced it, and
carries a `material` flag — so the bridge always reconciles while only a
residual worth reading earns a row.

---

## Plausibility: where a shock sits in the book's own experience

A 20% PD rise and a 2000% one must not be presented identically.
`backend/whatif/plausibility.py` compares the proposed move against every
borrower's own quarter-on-quarter and year-on-year movement across the window,
and returns one of six controlled labels.

| Proposed | Verdict | Because |
|---|---|---|
| PD +20% | Consistent with recent experience | 43.8% of borrower-quarters saw a move at least this size |
| PD +200% | Historically plausible | 9.7% did |
| PD +2000% | Plausible for selected pockets | 0.31% did |

It is a comparison against observed movement, **not a forecast and not a
probability**. The prompt that writes about it is forbidden from stating a
likelihood of the scenario occurring, and a test reads the output back for the
words that would amount to one.

---

## The ten macro variables

| Variable | One adverse unit | PD × | LGD +pp |
|---|---|---|---|
| GDP Growth Rate | per 1pp fall | 1.10 | 0.75 |
| Unemployment Rate | per 1pp rise | 1.12 | 1.00 |
| House Price Index | per 10% fall | 1.06 | 2.50 |
| Inflation Rate | per 2pp rise | 1.05 | 0.50 |
| Current Account | per 2pp deterioration | 1.03 | 0.25 |
| Stock Market Index | per 20% fall | 1.05 | 0.50 |
| Policy Interest Rate | per 200 bps rise | 1.08 | 0.50 |
| FX Depreciation | per 10% depreciation | 1.05 | 0.25 |
| Oil Price | per 20% fall | 1.05 | 0.50 |
| Corporate Credit Spread | per 100 bps widening | 1.08 | 0.50 |

These are **declared assumptions**, set by the threshold owner. None is an
IFRS 9 coefficient and none is an econometric estimate fitted to this book, and
every screen that shows one says so.

### Three kinds of relationship, never shown alike

- **CreditProbe Reference Sensitivity** — the table above. A declared assumption.
- **Estimated** — what this installation's sixteen quarters actually show,
  fitted as changes against changes.
- **User-defined** — what somebody chose to assume, in force **for the thread
  only**. The governed matrix is never edited, and a user-defined relationship
  is never called required, regulatory, approved or empirical.

An override travels on the provenance line, on the step that used it, on the
saved What-If and into the workbook, so a figure computed on somebody's own
assumption cannot be mistaken for one computed on the governed matrix.

### What the estimates say, and why they are not offered as better

| Variable | Implied multiplier | Configured | R² | Fit |
|---|---|---|---|---|
| Corporate Credit Spread | 1.832 | 1.080 | 0.35 | moderate |
| Current Account | 1.520 | 1.030 | 0.53 | moderate |
| Oil Price | 1.496 | 1.050 | 0.25 | weak |
| GDP Growth Rate | 1.181 | 1.100 | 0.22 | weak |
| Unemployment Rate | 1.220 | 1.120 | 0.08 | no visible relationship |
| Policy Interest Rate | 1.453 | 1.080 | 0.06 | no visible relationship |

Sixteen quarters give fifteen changes at most. That is enough to see whether a
relationship runs in the direction the configured sensitivity assumes, and
roughly how hard. It is **not** a calibration: no confidence interval from
fifteen points would mean what a reader would take it to mean, and the observed
series here move together by construction, being generated from one latent
cycle factor. `recommend()` therefore returns the configured sensitivity in
every case and says why — evidence, never preference, and never a silent
substitution.

---

## Comparing the two methodologies

Works in both directions from one object: whichever methodology produced the
result on screen, the other is one question away, and only the phrasing follows
the reader — the figures do not.

A spread is where the useful part starts. The comparison carries **where** the
two disagree — by sector, by rating, by stage, and the borrowers furthest apart
— and a borrower outside the range the model was trained on reaches the reader
as a limit on the figure rather than a footnote.

It never recommends one. The Delta Model is the governed arithmetic carried
onto the reported book; the ML model is a fitted estimate anchored to it. Which
belongs in a submission is a governance decision.

---

## The detailed workbook

Eleven sheets, built from a result rather than from an analysis run.

| Sheet | What it carries |
|---|---|
| COVER | Provenance, the result, the reading, and whether the reconciliation passed |
| SCENARIO | Every step in the order applied, both staging rule sets, the relationships in force |
| RESULT SUMMARY | The movement, and the same movement by stage, sector and rating |
| BORROWER DETAIL | Every borrower, every risk parameter before and after |
| FACILITY DETAIL | The borrower movement **allocated** by IFRS 9 EAD share |
| ATTRIBUTION | The exact Shapley split, and anything unexplained, named |
| STAGE MIGRATION | From/to, with exposure and ECL on both sides |
| RATING MIGRATION | Across the governed masterscale |
| RECONCILIATION | Nine tie-outs, each a test that passes or fails |
| METHOD & ASSUMPTIONS | Versions, thresholds, sensitivities, plausibility, limitations |
| REPRODUCE | The exact state that re-runs it |

Facility grain is an **allocation and says so**, in the sheet's own heading and
in a column of its own: staging is assessed on the obligor, so there is no
facility-level measurement to export, and presenting an allocation as a
measurement is the one thing that sheet must not do. The allocation sums back
to the borrower figure exactly.

The reconciliation is the load-bearing sheet. A break appears **in the file**
rather than raising and producing nothing, because an export that refuses to
exist tells a reader nothing.

A held result is readable only by the person who ran it. Every download is
audited with its hash, size and row count.

---

## Where it is reachable

| | |
|---|---|
| Screen | **What-If** in Intelligence — landing page, six guided journeys, and a thread |
| Chat | Any hypothetical routes to the scenario engine before the analytical planner |
| API | `/api/v1/whatif/*` — 30+ endpoints, every one behind `RequireAnalyst` |
| Model configuration | `/what-if/models/delta` and `/what-if/models/ml` |

---

## Integration: running on a book this branch has never seen

The shipped universe is a demo. A real installation replaces it with a
canonical IFRS 9 domain, and the question that has to be answerable before
anything is wired is not "does it import" but **what exactly will break, and
what will each break cost**.

`GET /whatif/integration/contract` is the document somebody reads first: the
datasets, the required columns, the optional ones with the capability each buys,
and the assumptions that are not columns at all.

`GET /whatif/integration/readiness` assesses a candidate and returns findings.
Each names the thing, says whether it **blocks** or **degrades**, and says what
it costs in the words of somebody using the product.

The most damaging thing a replacement can get wrong is the **grain**. A
facility-grain book read as an obligor-grain one multiplies every exposure and
every provision by the number of rows a borrower has, and the result looks
entirely plausible — so that check blocks rather than warns.

What the report does **not** check: whether the numbers are right. It can
establish that a column called `pd_12m` exists, is numeric and lies between 0
and 100. It cannot establish that it is the twelve-month probability of
default, and it does not claim to.

---

## Measured behaviour, Q2 2026

Delta Model, whole book, 3,241 borrowers:

| Scenario | Incremental ECL | Change | Borrowers moving to a worse stage |
|---|---|---|---|
| One-notch downgrade | 19,241.8 | +30.5% | 229 |
| LGD +5pp | 6,203.2 | +9.8% | 0 |
| PD +20% | 4,169.3 | +6.6% | 85 |
| GDP −1pp | 3,263.2 | +5.2% | 49 |
| Rates +200bp | 2,531.9 | +4.0% | 40 |

The LGD scenario producing **zero** migrations is the engine being right: a
loss-given-default shock changes what is recovered, not the likelihood of
default, so the measurement moves and the staging does not.

### Performance

Measured by `scripts/whatif_performance.py`, written to
`docs/whatif_performance.json`. Median seconds:

| | median | budget |
|---|---|---|
| Read the book (cold / warm) | 1.03 / 0.02 | 8.0 / 1.0 |
| Price a scenario — Delta | 0.66 | 3.0 |
| Price a scenario — ML | 0.79 | 6.0 |
| Attribution, 5 shocks | 0.73 | 6.0 |
| Plausibility (cold / warm) | 2.14 / 0.10 | 8.0 / 1.0 |
| Macro fit | 0.50 | 5.0 |
| Both methodologies | 1.52 | 10.0 |
| Detailed workbook | 6.49 | 30.0 |

A budget is the point at which an interaction stops feeling like an answer, not
a machine limit. A row over it is reported rather than failed: a timing
assertion in a test suite is a flake generator.

---

## What is still open

These are stated rather than engineered around.

1. **Re-scoping a step that already exists is not supported.** "Now restrict
   that to Contracting" is a modification of the scenario, but the builder
   reads a population only off a new step. The thread answers it as a question
   and changes nothing — safe, because it cannot silently move a number, but
   not what was asked. Recorded as a known gap in the evaluation corpus, with a
   test that it still behaves as recorded.

2. **A step can be removed but not widened.** The only modification the builder
   makes is removing a whole step, so a step scoped to a sector is removed
   entirely rather than re-scoped.

3. **Covenant re-testing under stress is reported, not re-evaluated.** The
   summary counts borrowers already in breach. Re-running covenant tests
   against stressed financials needs the covenant definitions expressed as
   evaluable expressions, which they are not.

4. **The macro sensitivities are declared assumptions.** Stated on every row
   and in every answer. The empirical estimates are offered beside them and
   never instead of them, and the reason is the data: one macro degree of
   freedom observed sixteen times is not three variables observed fifty-two
   thousand times.

5. **`corporate_macro` is generated from one latent cycle factor.** Every
   observed series is a linear function of it plus noise, so a regression on
   this data recovers the generator's own arithmetic. The macro lab says so
   wherever it shows a fit; a canonical domain with genuinely independent
   series would make those estimates mean what they appear to mean.

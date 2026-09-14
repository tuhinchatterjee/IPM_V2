# Retail What-If — Early Warning integration, rebuilt

*Synthetic Saudi retail demonstration data and a synthetic demonstration
engine throughout. Nothing here is ANB customer data, an ANB model, an ANB
policy or a SAMA requirement, and nothing has been approved, certified or
independently validated by anybody. No credit decision should rest on it.*

Branch `claude/funny-dirac-6n8f0o`. The Early Warning Score v3 handover is
`docs/RETAIL_EWS_V3_HANDOVER.md` and everything it describes still stands.
This document is the What-If side: what was rebuilt, why, and what it does now.

---

## 1. What was wrong

The audit that opened this work found five things, and they were not all the
same size.

**The thread was not a thread.** The page opened from an Early Warning card
held a single result in state and replaced it on every run. A scenario is
rarely the end of a question — you stress the cohort, look at where it landed,
narrow to the part that moved, run it again and compare — and replacing the
answer each time threw away the comparison the reader was building.

**There were two parsers.** The governed reader lives in
`backend/retail/whatif_language.py` and is what the rest of What-If runs on.
The thread carried its own: six regular expressions in the browser,
understanding six shocks. A thread that understands less than the composer on
the next screen was never going to catch up.

**The engine could not see the cohorts the workspace was built on.** Salaried
against non-salaried, the sub-product ladder, the Early Warning severity band
and the already-bad / forward-risk split are all *derived* — computed by the
Early Warning model, living in the scoring domain, not columns of the
canonical book. Asked to filter on any of them, `select` raised "the canonical
dataset has no such column", which was true and useless.

**Four scenario families had no shock behind them.** Nothing could move a
share of a delinquency bucket, a score band or an IFRS 9 stage, and nothing
could move household expenses.

**Nothing explained the mechanism.** A result gave a number, and the question
a reader actually arrived with — *how* — had no answer on the page at all.

---

## 2. The data

| | Before | After |
|---|---|---|
| Facilities at the latest month | 19,722 | **59,449** |
| Customers | 14,239 | **42,824** |
| Gross carrying amount | SAR 2.09bn | **SAR 6.39bn** |
| Loss allowance | SAR 20.1mn | **SAR 58.6mn** |
| Months | 25 | 25 |

`config/retail_demo_config.json` moves
`portfolio.target_active_facilities_latest_month` from 20,000 to 60,000 and
the generator to `retail-gen-1.2.0`. The product mix, the delinquency
structure, the salaried split and the score distributions are the
configuration's, unchanged — this is the same book, three times the size.

### A regenerated book used to be skipped, silently

Every derived build is incremental: it writes the months it is missing and
skips the ones already on disk. Regenerating the book breaks that assumption
without changing anything the builder looks at — `reporting_month=2026-08` is
still `reporting_month=2026-08`, so every marker file is still there and every
month is skipped. The scoring domain, the early-warning panel and the three
governed views then serve a book that no longer exists, and the bootstrap
reports "25 already present" and finishes successfully.

`backend/retail/source_stamp.py` fixes it at the source: each derived domain
records the *manifest hash* of the book it was built from, and a build against
a different hash rebuilds whatever the markers say. A missing stamp is not
evidence of staleness — an installation that has never stamped builds as it
always did — so the first run after this change needs one explicit rebuild and
every regeneration after it is caught automatically.

The bootstrap also stopped treating its reconciliation as a report. If the
views disagree with the book, they are rebuilt from it and checked again.

---

## 3. Four new shocks

Added to `SUPPORTED_METHODOLOGIES`, so they are declared, refused by name when
misspelled, and listed in the engine's own error messages.

| Shock | What it does |
|---|---|
| `dpd_migration` | Moves a share of one delinquency bucket into another |
| `score_band_migration` | Moves a share of one behavioural or application score band into another |
| `stage_migration` | Moves a share of one IFRS 9 stage into another |
| `expense_pct` | Moves household expenses onto the affordability path |

Three decisions inside them are worth stating, because each is a place a
migration can quietly invent its answer.

**Which facilities move.** Worst first, deterministically. The facilities that
deteriorate are the ones already closest to the edge, so the eligible
population is ordered by the measure that defines the edge and taken from the
top. A migration that sampled would give a different number every run and
could not be reconciled to a customer list; one that took the best would
understate every deterioration scenario.

**What the share is a share of.** "20% of the 30-59 bucket" is twenty per cent
of its money or twenty per cent of its facilities, and those are different
populations. The caller says which, and `_basis` reads it out of the sentence
— "exposure" and "balances" mean money, "accounts" and "customers" mean
facilities.

**Where a migrated facility lands.** On what this book already shows: the
median days past due and the median PD anchor of its own product in the target
bucket, read from the frame on every run. Where a product has nobody in the
target bucket there is nothing to land on, so the facility keeps what it had
rather than being given a number from another product.

A stage migration moves the stage and nothing else. Stage decides twelve
months against lifetime, and a facility moved to Stage 2 keeps its own PD, its
own exposure and its own loss given default. A score-band migration reaches PD
through the versioned score-to-PD mapping, the way any score change does.

---

## 4. The waterfall

Computed, never allocated. The IFRS 9 identity multiplies its inputs — a PD
rise and an LGD rise together are worth more than the sum of each alone,
because both multiply the same exposure — so splitting a total across the
shocks that were asked for produces steps that do not exist.

`whatif.waterfall()` instead runs the scenario once per prefix of a published
causal order (`WATERFALL_ORDER`: what the borrower's position does first, then
the score, then staging, then the parameters) and reports what each addition
actually moved. Two consequences are stated on every result:

* the steps sum **exactly** to the total, because each is a difference between
  consecutive runs and the last prefix is the whole scenario;
* a step's size depends on where it sits in the order, because it is measured
  on top of everything before it. The order is published so the reading can be
  checked.

A worked example on Credit Card — income −10%, 5% of CURRENT to 1-29, 10% of
Stage 1 to Stage 2, PD +20%, LGD +5%:

| Step | From | To | Change | Moved |
|---|---|---|---|---|
| Income moved | 5,019,431 | 5,161,101 | +141,670 | every facility |
| Delinquency buckets migrated | 5,161,101 | 5,225,201 | +64,100 | 279 |
| Stages migrated | 5,225,201 | 5,467,651 | +242,451 | 453 |
| PD scaled | 5,467,651 | 6,065,159 | +597,507 | every facility |
| Loss given default scaled | 6,065,159 | 6,199,255 | +134,096 | every facility |
| **Total** | | | **+1,179,824** | |

Decomposing is N+1 full recomputations, which is cheap on a cohort and not on
the whole book. Above `WATERFALL_MAX_FACILITIES` (25,000) the result says so
and names the narrower populations that would get one, rather than making a
reader wait.

---

## 5. The cohort vocabulary

`whatif.select` now resolves the Early Warning dimensions through the scoring
domain for the same month, turning them into a set of facilities and filtering
the book on that. The engine still runs on the canonical book and nothing is
joined into it.

| Dimension | Example |
|---|---|
| Sub-product | "Stress Platinum Credit Card salaried customers" |
| Classification | "Stress non-salaried credit card customers" |
| Delinquency bucket | "Move 20% of 30-59 DPD exposure to 90+" |
| Score band | "behavioural score band D and below" |
| Early Warning severity | "Stress only high and critical EWS customers" |
| Forward risk | "Run the shock on forward-risk customers only" |
| Already bad | "Show impact only for already bad customers" |

The sub-product phrases are **read from the Early Warning taxonomy**, not
restated. A list written out in the parser would be a second taxonomy, and the
first thing it would do is fall behind the first one; "platinum card",
"platinum", "CC_PLATINUM" and the previous name all resolve.

Two readings deserve their own note. A migration **removes** its source from
the filters — read as a filter as well, "move 15% of Stage 1 to Stage 2" would
stress Stage 1 only and report a scenario nobody asked for. And a sentence
naming a cohort inside an exported selection **narrows** it and never widens
it: "stress only the forward-risk customers in this selection" read as a fresh
filter would stress every forward-risk customer in the book and report a
number several times the size.

---

## 6. The thread

`/early-warning/whatif/{selectionId}` is a conversation. What you asked and
what came back stack downwards in the order they happened, the composer stays
at the bottom, and nothing that has been answered is taken away.

* **One reader.** Typed sentences go to the governed parser. The browser's own
  reader is gone.
* **A refusal is a turn.** A sentence the parser cannot read comes back as a
  question in the thread with what *was* understood, and four chips to press.
  The engine refuses to guess a unit or a cohort; this is the honest form of
  that refusal.
* **Twelve chips**, each a complete sentence the parser resolves — nothing is
  a keyword the page translates. A regression runs every one of them.
* **Methodology beside the composer**: Delta, XGBoost challenger, or both.

The result block carries, in this order: what ran and the top figures; the
waterfall as a chart and a table; before-and-after; the same movement at five
widths; impact by level; where it landed by product; the cohort it ran on;
the challenger comparison; the AI interpretation; the workbook button and the
follow-up prompts; and what it assumed.

---

## 7. The charts

`frontend/src/app/early-warning/whatif/charts.tsx`, on the application's own
recharts stack and palette, so a chart in a What-If thread is the same chart as
one on a Lens. Three rules hold across all of them: **colour means something**
(deterioration in the negative token, improvement in the positive one,
everywhere, with a key), **nothing is drawn that was not measured** (no
interpolation and no smoothing anywhere in the file), and **an empty chart says
why it is empty**.

The waterfall is drawn here rather than with the shared bar chart because it
needs an invisible base per bar — a property of that chart and not of bar
charts. The first and last bars sit on the floor because they are levels, not
changes.

---

## 8. The workbook

`POST /retail/ews/whatif-selection/workbook.xlsx` → thirteen sheets:
Summary, Waterfall, Cohort, Impact by level, Affected customers, Customer
pre-post, Facility pre-post, Drivers, PD/LGD/EAD/ECL, Stage migration, Days
past due, Score bands, Method.

Formatted for a business reader: frozen panes, autofilters, column widths
sized to content, money as money, ratios as ratios, percentages as
percentages, deterioration and improvement coloured.

**Nothing is recomputed differently.** Every figure comes from the same
`whatif_cohort.run` call with the same inputs, so the workbook's figures are
the page's figures. A sheet that does not apply to a scenario says so on its
own face rather than being dropped, so the workbook has the same shape every
time.

---

## 9. The standalone What-If page

Seven guided journeys, replacing the corporate six where retail does not have
the object:

| Corporate | Retail |
|---|---|
| Rating Movement | **DPD Bucket Movement** and **Behavioural Score Movement** |
| Stage Migration | Stage Migration |
| IFRS 9 Risk Parameter Adjustment | **Risk Parameter Adjustment** — PD, LGD, CCF, collateral, recovery in one place |
| Sector Stress | **Product & Sub-product Stress**, on the Early Warning taxonomy |
| Macroeconomic Shock | Macroeconomic Stress |
| Borrower Stress | Borrower Stress |

There is no rating to move in a retail book, and the concentration that matters
is not a sector. PD and LGD stop being separate journeys because nobody thinks
"I would like to change a loss given default" — they think "I want the
parameters worse". Every prompt is a complete sentence the governed parser
resolves.

---

## 10. Tests

`tests/retail/test_ret_whatif_integration.py` — migrations (worst-first,
deterministic, basis, landing values, direction, cure), the waterfall (steps
sum to the total, chain end to end, run in the published order, name what
moved), the cohort vocabulary, the parser (every cohort sentence, every
migration sentence, every chip the composer offers), the thread's reading and
narrowing, the source stamp, and the workbook (builds, opens, every sheet says
something, agrees with the result, claims nothing it cannot support).

---

## 11. Known limitations

- Everything is synthetic demonstration data and a synthetic demonstration
  engine. Not an ANB model, not an ANB policy, not a SAMA requirement, not
  independently validated, never run in production.
- The waterfall's step sizes depend on the order they are measured in. The
  order is causal and published; it is not a unique decomposition and nothing
  here claims it is.
- A migration's landing values are medians of the target bucket in this book.
  They are a reasonable reading of the data and not a transition model.
- The challenger is fitted on this book for comparison only. It is not a
  governed model and is never the calculation of record.
- Macroeconomic stress reaches the book through scenario weights and
  borrower-level proxies. There is no macro-to-PD transmission model behind it,
  and the journey says so.
- The workbook caps customer and facility detail at 5,000 rows each.

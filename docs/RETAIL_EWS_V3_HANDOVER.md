# Retail Early Warning Score v3 — model governance and What-If integration

*Synthetic Saudi retail demonstration data and a synthetic demonstration model
throughout. Nothing here is ANB customer data, an ANB model, an ANB policy or a
SAMA requirement, and nothing here has been approved, certified or
independently validated by anybody. The bureau block is a labelled synthetic
proxy, not a live bureau feed. No credit decision should rest on it.*

Branch `claude/funny-dirac-6n8f0o`, continued from the stable v2 head. The v2
handover is `docs/RETAIL_EWS_SCORE_HANDOVER.md` and everything it describes
still stands; this document is what v3 added on top of it and what changed
underneath.

---

## 1. Build identity

| | |
|---|---|
| Model | Retail Early Warning Score `3.0.0` (registry id `RET-EWS-MODEL-0003`) |
| Panel | `retail_ews_score` `3.0.0` — 20 months, 2025-01 … 2026-08, 362,084 rows, 498 fields |
| Sub-product taxonomy | `retail-subproduct-taxonomy-2.0.0` |
| Rulebook | `retail-ews-rulebook-1.0.0`, unchanged |
| Early Warning **Data** | `retail_early_warning` — 170 declared fields, 25 periods, all served |
| Model configuration | `backend/retail/ews_model.py` |
| Governance | `backend/retail/ews_registry.py`, `ews_performance.py`, `ews_report.py` |
| Reading | `backend/retail/ews_interpretation.py` |
| What-If bridge | `backend/retail/whatif_selection.py`, `whatif_cohort.py` |
| New screens | model tree, model log, one version's record, the imported What-If thread |

---

## 2. Bureau recency decay and weight redistribution

### The function

```
W(age) = W_floor + (W_max − W_floor) × exp(−ln2 × age / half_life)
```

`W_max` 0.15, `W_floor` 0.05, half-life 6 months. A pull the bank has never
received is worth the floor, not the maximum: never observed is not the same as
observed today. The parameters are demonstration parameters, bank-configurable.
They are **not** an observed decay rate for any bureau and not a validated model
assumption, and the model configuration says so in those words on every screen
that draws the curve.

| Age of the pull | 0m | 3m | 6m | 9m | 12m | 18m | 24m | 36m |
|---|---|---|---|---|---|---|---|---|
| Effective weight | 15.0% | 12.1% | 10.0% | 8.5% | 7.5% | 6.3% | 5.6% | 5.2% |

### The redistribution, and the defect that made it cosmetic

What Bureau releases goes to Behavioural, Affordability and Facility pro rata to
their base weights. The four always total one. For Credit Card, whose base
weights are 45 / 22 / 13 / 20:

| | Behavioural | Affordability | Bureau | Facility |
|---|---|---|---|---|
| Fresh pull | 0.4500 | 0.2200 | 0.1300 | 0.2000 |
| 12 months | 0.4784 | 0.2339 | 0.0750 | 0.2126 |
| 24 months | 0.4881 | 0.2386 | 0.0563 | 0.2170 |

That table was already correct before the fix — and made no difference to
anybody's score. The roll-up divided the four weights through by the heaviest
**effective** weight, which scales the three dynamic layers up and then straight
back down again. Their weights relative to one another came out identical at
every bureau age:

```
age  0m  normalised  behavioural 1.0000  affordability 0.4889  facility 0.4444
age 24m  normalised  behavioural 1.0000  affordability 0.4889  facility 0.4444
```

The only thing a stale pull changed was that Bureau counted for less. The model
documented a decay **and** a redistribution and performed only the decay.

The reference is now the heaviest **base** weight for the product, which does
not move with the age of the pull, so weight handed to a layer becomes influence:

```
age  0m  normalised  behavioural 1.0000  affordability 0.4889  facility 0.4444
age 24m  normalised  behavioural 1.0848  affordability 0.5303  facility 0.4821
```

A layer is capped at that reference — no layer may be handed more influence than
the heaviest layer carries on a fresh pull. That is a governance bound, and it is
also what keeps the score off its ceiling: without it, twenty-one facilities
landed on exactly 100 with no ordering between them, which is the failure the
noisy-OR roll-up was written to avoid in the first place.

Effect on the book, v2 → v3, measured over the same facilities and months:

| | |
|---|---|
| Facilities whose score moves | 4,877 of 19,722 at the latest month |
| Moved up / down | 3,930 / 832 |
| Mean score change | +0.2163 |
| Severity band changes | 112 of 19,090 (0.59%), 0.27% of exposure |
| Facilities crossing the warning cutoff | 27 |

Every row records the weights it was scored at: `bureau_weight_base`,
`bureau_weight_effective`, `bureau_weight_released`, `effective_weight_<layer>`
and `effective_weight_total`, which is 1.0 on every row.

---

## 3. Early Warning data coverage

| Domain | What it is | Months | Grain |
|---|---|---|---|
| **Early Warning Data** (`retail_early_warning`) | The raw retail / IFRS 9 / bureau source, 170 fields | 25 periods | customer × facility × month |
| **Early Warning Score** (`retail_ews_score`) | The derived scoring domain, 498 fields | 20 months, 2025-01…2026-08 | customer × facility × month |

Both reconcile to the canonical book exactly: same facility set, one row per
facility, identical exposure, DPD and IFRS 9 stage, identical totals
(SAR 2,087,954,318.09 at 2026-08 in all four of book, Early Warning Data, Early
Warning Score and What-If Analysis Data). `tests/retail/test_ret_ews_domain_reconciliation.py`
holds that.

Three fields declared in an earlier draft of the Early Warning Data contract are
**not** declared any more, because the book does not hold them and a domain that
declares a column it silently drops is a promise it breaks: a prior-month
balance, a lowest-balance-over-three-months series, and a bureau source label.
The book's own turnover window is inflows and outflows over one month and an
average balance over three, and that is what is declared.

---

## 4. The demonstration risk hierarchy

Produced through the **generator**, not through labels: the miss intercept was
raised for Credit Card and Personal Finance, and the resulting book is genuinely
worse in those products on every independent measure. At 2026-08:

| Product | EWS | Band | Warned | ODR | 30+ DPD |
|---|---|---|---|---|---|
| Credit Card | 23.18 | HIGH | 1,643 | 0.5352% | 4.4861% |
| Personal Finance | 17.91 | MEDIUM | 1,521 | 0.3512% | 2.4610% |
| Auto Finance | 15.78 | MEDIUM | 745 | 0.2741% | 1.4238% |
| Home Finance | 13.94 | LOW | 388 | 0.1402% | 1.3482% |

Total Retail reads 18.83 MEDIUM, 3,748 of 14,239 customers warned, SAR 538.0mn
of exposure under warning (25.78%), default-entry rate 0.375%.

Credit Card reaches HIGH on the **unchanged** severity band table. No band was
moved and no number is written into a screen.

---

## 5. Salaried / Non-Salaried and the sub-product ladder

Every product carries both classifications, derived from employment status:
Salaried is `GOVERNMENT, GOVERNMENT_RELATED, PRIVATE_SECTOR`; Non-Salaried is
`SELF_EMPLOYED, RETIRED`. The derivation is shown on the screen beside the
figure. The classifications add back to the product exactly — customers,
accounts and exposure — which is a test, not a claim.

The sub-product ladder was renamed onto Saudi-market names under taxonomy
`2.0.0` (Infinite / Signature / Platinum / Classic Card; Standard / Top-Up /
Buyout Personal Finance; Standard Auto Lease and Used Vehicle Finance; First
Home, Standard Residential and Buyout / Refinance Home Finance). Every renamed
code records what it was previously called, so a reader who remembers the old
name can find the new one.

Materiality is reported at every level — customers, accounts and exposure as a
share of the parent classification, the product and total Retail — and a part can
never exceed its whole.

---

## 6. AI Interpretation

Deterministic and governed, in `ews_interpretation.py`. Six published criteria
with published weights totalling one, each scaled across the four products, and
a "Why this ranking?" control that shows the criteria table beside the
paragraph. The ranking follows the marks and the marks follow the data — the
product named most concerning is the product carrying the highest Early Warning
Score, checked as a test rather than asserted. It reads at portfolio, product,
classification and sub-product level, and in the imported What-If thread.

---

## 7. Model governance

**The tree.** Four layers, 19 sub-layers, 36 classifiers, 34 triggers (31
evaluated), 12 sub-products, every node served from the model configuration. The
bureau layer carries its decay curve, drawn against the age of the pull with the
fresh-pull weight and the floor named on the axis — not as a sparkline, which
would report a "latest value" and a "movement" that a model parameter does not
have.

**The log.** Two versions, both measured on today's panel over the same
facilities, months and outcomes. The retired version is *rescored*, not
remembered: the versions differ only in how the four layers are combined, so v2
is recomputed exactly from the stored layer columns.

| | KS | Gini | AUC | Precision | Recall | PSI | Alert rate |
|---|---|---|---|---|---|---|---|
| 2.0.0 retired | 0.1569 | 0.1741 | 0.5870 | 3.63% | 33.32% | 0.0249 | 21.50% |
| 3.0.0 active | 0.1549 | 0.1732 | 0.5866 | 3.63% | 33.38% | 0.0218 | 21.55% |

Reported as measured. v3 is marginally *worse* on discrimination and better on
stability. That is the honest result of a governance-motivated change — a
two-year-old bureau file no longer counts as much as a fresh one — and it is
neither hidden nor dressed up. A version is compared against the one it
replaced; the first version in the registry says it has nothing to compare
against rather than being compared with itself.

**Performance by starting state.** Measured over 303,621 scored facility-months
across 17 months with a 3-month outcome window:

| Cohort | Observations | Outcomes | AUC | KS |
|---|---|---|---|---|
| Absolute clean (DPD = 0) | 283,358 | 6,645 | 0.5866 | 0.1549 |
| Early arrears (DPD 1–30) | 7,822 | 3,330 | 0.5161 | 0.0454 |
| Broad pre-default (DPD < 90) | 296,498 | 9,980 | 0.6585 | 0.3125 |
| Hard-trigger population | 7,284 | — | **not reported** | **not reported** |

The hard-trigger cohort reports **operational capture** and nothing else: 100%
of it is flagged and 97.79% sits at CRITICAL, which measures the overrides
firing, not the score ranking. Its ROC came out at essentially zero, which is a
real number that would mislead, so discrimination is suppressed there with a
written explanation rather than printed.

**Calibration is declared not applicable** in those words. The Early Warning
Score ranks and explains; it is not a fitted probability, so Brier score and
observed-to-expected are not reported.

**The decile table tells the truth about ties.** Sixty per cent of the panel
scores exactly zero — nothing has fired, which is the ordinary state of a
performing facility — so deciles five to ten fall inside one score. Cutting the
sorted array there produced six different outcome rates out of one
undifferentiated population, and the differences were the order the rows arrived
in. Every observation now carries the outcome rate of everyone on its own score,
tied deciles read the same and are labelled "tied", and the table says why.

**The report.** `GET /retail/ews/model-log/{version}/report.docx` builds a Word
model development report on request from the published panel — 29 numbered
sections, 203 paragraphs, 41 tables, 30 charts, ~1.1 MB, about 20 seconds.
Univariate and bivariate analysis, ROC / KS / precision-recall / lift, cohort
performance, stability, lead time, limitations, monitoring, a variable
dictionary and a rule dictionary, every figure computed. Validated by reopening
it with python-docx and checking zip integrity. LibreOffice cannot open any file
in this container (a Java/sandbox limit, reproduced with an unrelated file), so
no PDF conversion was attempted.

---

## 8. Early Warning Score → What-If Analysis

Export from five places: a product card, a product, a Salaried / Non-Salaried
classification, a sub-product, a filtered customer cohort, and a single customer.

A **selection set** is written to `var/retail/whatif_selections/` carrying the
exact customer and facility ids, the month, the model and rulebook versions, the
filters that produced it, the Early Warning profile of the cohort and its
materiality. The scenario runs with `filters={"facility_id": [...]}` applied to
the What-If engine, so exactly those facilities are stressed and the canonical
book is read, never written.

The imported thread opens on the IFRS 9 baseline: TTC PD, PIT 12-month and
lifetime PD, LGD, CCF, EAD, collateral, base / upturn / downturn / weighted ECL
and coverage, then eight distribution cuts — days past due, behavioural and
application score band, IFRS 9 stage, sub-product, classification, already-bad
or still-paying, and Early Warning severity. Cuts with a direction read in it;
cuts without one stay ranked by exposure. Every cut reconciles to the population.

A worked scenario — PIT 12-month PD +20% on Credit Card / Salaried / Platinum
Card, 2,047 customers, 2,235 accounts, SAR 23.8mn:

| Level | ECL before | ECL after | Change |
|---|---|---|---|
| Selected cohort | 2,008,354 | 2,214,714 | +10.28% |
| Platinum Card | 2,284,841 | 2,491,201 | +9.03% |
| Salaried | 4,390,797 | 4,597,157 | +4.70% |
| Credit Card | 5,019,431 | 5,225,791 | +4.11% |
| Total Retail | 20,110,831 | 20,317,191 | +1.03% |

The same absolute SAR 206,360 at every level, because stressing a cohort cannot
change anything outside it — held as a test. The gradient-boosted challenger is
run beside the Delta method and compared; the Delta method remains the
calculation of record and the challenger is never substituted for it. The result
carries an AI interpretation and nine follow-up scenarios.

---

## 9. Defects found and fixed in this pass

Each was reproduced, root-caused, fixed, covered by a regression test, and the
exact browser journey re-run and visually inspected.

1. **The bureau redistribution never reached the score** (§2). Arithmetically
   inert. Fixed by normalising against a fixed reference.
2. **Twenty-one facilities pinned at exactly 100**, introduced by (1)'s fix and
   fixed by the governance cap in the same section.
3. **The decile table reported row order** where the score ties (§7).
4. **A version was compared with itself**, printing a table of a change against
   nothing, which reads as a finding.
5. **Baseline distribution cuts were sorted by size**, so days past due read
   CURRENT, 1-29, 30-59, 90-179, 60-89, 180+ and severity read LOW, MEDIUM,
   CRITICAL, HIGH. The PD gradient down the score bands — 0.64%, 1.03%, 1.83%,
   5.04%, 14.56%, 51.21% — was completely hidden by the ordering.
6. **`nan` reached the screen as a band label** for facilities with no
   behavioural score.
7. **The report's contents page ran 5, 7, 9, 10, 12**: six sections carried a
   top-level number and a second-level heading, and one cohort heading
   interpolated its internal key as `17.clean`. Numbering and level now come
   from one counter.
8. **Diagnostic curves were drawn as sparklines.** An ROC read off
   equally-spaced points is a different curve from the one measured, and the
   sparkline's headline reported "ROC 100 +100" — the true positive rate
   reaching one, which is true of every ROC ever drawn. Now drawn against both
   axes with the no-skill diagonal, and the precision-recall chart carries the
   base rate so a flat curve reads as "no lift" rather than as an empty box.
9. **The lead-time distribution was drawn as a trend** and reported a movement
   across buckets that have no order in time. Now bars.
10. **Early Warning Data declared seven columns it did not serve** (§3).
11. **Three UAT cases asserted the old sub-product labels** and reported the
    rename as a missing sub-product. The check now reads the governed taxonomy
    instead of restating it, which is why it went stale.

---

## 10. Tests and verification

| | |
|---|---|
| New Python regressions | `tests/retail/test_ret_ews_governance.py` (64 cases: bureau recency, segmentation, interpretation, performance, registry, report, the What-If bridge) |
| New reconciliation | `tests/retail/test_ret_ews_domain_reconciliation.py` (7 cases across four domains) |
| Browser UAT | `scripts/retail_uat/ews_score_uat.py` EW-01…EW-60; `scripts/retail_uat/ews_v3_journey.py` for the ten v3 screens |
| Evidence | `docs/evidence/retail_ews_v3/` — ten full-page screenshots |
| Frontend | `npm test` — 577 pass, 0 fail |

---

## 11. Limitations

- Everything is synthetic demonstration data and a synthetic demonstration
  model. Not an ANB model, not an ANB policy, not a SAMA requirement, not
  independently validated, not certified by any auditor, never run in
  production.
- The bureau decay parameters are demonstration parameters. They are not an
  observed decay rate for any bureau.
- Discrimination on the clean cohort is weak (AUC 0.5866). That is what the
  score achieves on this book and it is reported as measured. It is stronger on
  the broad pre-default cohort (0.6585), which is the population where more of
  the model's inputs have something to say.
- The score is not a calibrated probability and nothing in the build claims it
  is.
- The gradient-boosted challenger is fitted on this book for comparison only. It
  is not a governed model, is not the calculation of record, and is not offered
  as one.
- Hard-trigger capture is an operational measure, not evidence that the score
  ranks anything.

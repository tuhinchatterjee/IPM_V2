# First working checkpoint — ECL decomposition and the impact of PD

Brief §6. The question, proved end to end against the real Cockpit backend on
the two-quarter pilot, with independently checked arithmetic and a
demonstration that the answer is computed rather than written down.

> Give me an ECL decomposition and explain the impact of PD.

Raw payloads: `docs/cockpit_v2/evidence/checkpoint_ecl_pd.json`.

## 1. What the base Cockpit did with this question

Captured on the base commit, flag off, same backend
(`docs/cockpit_v2/evidence/baseline_answers.json`):

> Over which horizon? Twelve-month and lifetime PD are different measures, and
> IFRS 9 uses each in different stages.

A clarification. No decomposition, no PD attribution, no table, no bridge.

## 2. What the Cockpit answers now

`POST /api/v1/ask`, flag on, pilot data published, `narrative.prose_source`
= `deterministic_v2`, HTTP 200 in 355 ms with zero model calls:

> Reported ECL rose from 35.00 INR crore at Q1 2026 to 45.77 INR crore at
> Q2 2026, a movement of 10.77 INR crore. Decomposing that movement across the
> parameter groups of the governed calculator, the largest single component is
> recovery and lgd at 5.20 INR crore, which this method allocates 48.3% of the
> net change. The bridge reconciles: opening plus every component below equals
> closing, with a residual of 8.88e-15 INR crore.
>
> The net figure hides movement in both directions. Increasing the allowance:
> recovery and lgd 5.20 INR crore; exposure and ead path 4.20 INR crore; pd
> curves 1.29 INR crore. Reducing it: discounting -0.02 INR crore. Both are
> real and reporting only the net would conceal the improvement as well as the
> deterioration.
>
> Outside the continuing book, 1 facility entered carrying 0.08 INR crore of
> new allowance and 1 left, removing 0.02 INR crore. An account leaving the
> book is a repayment, a write-off or a sale; none of them means a loss was
> recovered. The separately identified overlay moved -0.00 INR crore and is
> never folded into a parameter.
>
> Under this decomposition the PD curves contributed 1.29 INR crore of the
> 10.77 INR crore movement, or 12.0% of it. That figure is the exact Shapley
> allocation to the PD factor group: the opening and closing hazard curves are
> evaluated through the same governed ECL calculator in every combination with
> the other factor groups, and the allocation is averaged symmetrically across
> them, so no ordering was chosen and no interaction was left in an unexplained
> remainder.
>
> PD is not the largest component here. recovery and lgd contributed 5.20 INR
> crore; exposure and ead path contributed 4.20 INR crore. Reporting the PD
> effect without saying what outweighed it would leave the wrong impression of
> what moved the allowance.
>
> The PD contribution is concentrated: CKB-0002 facility CKB-0002-F2 0.44 INR
> crore; CKB-0002 facility CKB-0002-F1 0.29 INR crore; …

### Every element the checkpoint asks for

| Required | Where it is |
|---|---|
| Opening and closing ECL | 35.00 → 45.77 INR crore, first sentence and the bridge table |
| PD contribution | 1.29 INR crore, 12.0% of the net change |
| Attribution method | Exact Shapley over six non-overlapping factor groups, named in the prose, in `evidence.observations[].method` and in the Trace |
| Reconciliation | Residual 8.88e-15 INR crore; `reconciled: true` on the observation |
| Source evidence | `cockpit_2026_q1`, `cockpit_2026_q2`, `cockpit_risk_curves`; every observation carries scope, unit, dates, versions, coverage and drill-down handles |
| Trace | `cockpit_v2.trace` — data/model/policy/attribution versions, dataset checksums, tools called, requested outputs, subquestions, the SICR and scenario policy in force, the measurement grid and both method names |
| Table | Two: the ECL bridge, and PD contribution by facility |
| Chart | A waterfall over the reconciled bridge |
| Claim validation | 21 figures and 10 entity references checked against the observations; `validation.ok = true` |

**A sector breakdown is not offered as the answer.** The six components are
parameter groups — PD curves, recovery and LGD, exposure and EAD path, staging
and measurement horizon, scenario weights, discounting — plus five structural
lines. A movement by sector is a different tool (`decompose_movement`) and a
different question.

## 3. Independently checked arithmetic

`tests/cockpit_v2/test_ecl_oracle.py` — 10 tests, all passing. Every expected
value is a hand-written literal derived from the brief's fixture table, not a
call to the production calculator:

| Quantity | Expected | Computed |
|---|---|---|
| Opening scenario ECL, base / upturn / downturn | 0.60 / 0.20 / 2.00 | 0.60 / 0.20 / 2.00 |
| Closing scenario ECL | 1.20 / 0.45 / 3.60 | 1.20 / 0.45 / 3.60 |
| Weighted opening → closing | 0.80 → 1.53 | 0.80 → 1.53 |
| Net change | 0.73 | 0.73 |
| PD contribution (symmetric two-factor) | +0.455 | +0.455 |
| LGD contribution | +0.275 | +0.275 |
| PD share | 62.328767% | 62.328767% |
| LGD share | 37.671233% | 37.671233% |
| Weighted PD × weighted LGD × EAD | 0.704, **not** 0.80 | 0.704 |

Also held by that suite: the six-group engine puts exactly zero on the four
groups that did not move; the allocation is independent of the order the groups
are listed in; weights that do not sum to one are refused; and a lifetime PD is
not an annual PD multiplied by a number of years.

Independently of the fixture, the answer path verifies that the measurements it
rebuilds from the PUBLISHED curves reproduce the published ECL. Worst
discrepancy across all 19 facilities: **8.1e-11 INR crore**.

## 4. The narrative is computed, not hard-coded

Brief §6.2. One stored input was changed at a time, the dataset regenerated
through the full pipeline, and the same question asked again against the live
API. The narrative is never touched — only the data.

| Run | Net change | PD | Recovery/LGD | EAD |
|---|---:|---:|---:|---:|
| Baseline | 10.7724 | **1.2918** | 5.2011 | 4.2038 |
| CKB-0002 PD × 1.6 from 2026Q2 | 11.7213 | **2.3636** | 5.2020 | 4.1171 |
| CKB-0001 collateral coverage × 0.35 | 11.0518 | 1.2918 | **5.4666** | 4.2177 |
| CKB-0011 downturn weight → 0.35 | 10.7797 | 1.2920 | 5.2011 | 4.2040 |
| Baseline rebuilt | 10.7724 | **1.2918** | 5.2011 | 4.2038 |

Reading across:

* Raising one borrower's PD path raises the **PD** contribution from 1.29 to
  2.36 and its share from 12.0% to 20.2%, and the visible sentence changes with
  it — *"the PD curves contributed 2.36 INR crore of the 11.72 INR crore
  movement, or 20.2% of it"*. Recovery is unchanged to four decimal places.
* Cutting one borrower's recognised collateral coverage raises the **recovery**
  contribution from 5.2011 to 5.4666 and leaves PD identical to ten decimal
  places.
* Moving one borrower's downturn weight moves the **scenario weights** line
  from 0.00 to 0.01 INR crore and nothing else materially.
* Rebuilding the baseline reproduces the previous figures **exactly** and the
  answer string is byte-identical, so the generator is deterministic and no
  stale cached answer survived four dataset changes.

Every one of the five runs reconciled and validated.

## 5. Honest limitations of this checkpoint

* The pilot has twelve borrowers, and one Stage 3 account carries about 89% of
  the allowance. That is arithmetically correct on a book this small, but it
  means the pilot's portfolio percentages are dominated by one name. The
  eight-quarter demo is the place to read portfolio proportions.
* The scenario-weight perturbation moves a small number because the borrower it
  was applied to holds a small allowance. It demonstrates the mechanism, not a
  material portfolio effect.
* `prose_source` is `deterministic_v2`. There is no provider credential in this
  environment, so the analyst path could not be exercised and **no part of this
  checkpoint is evidence that a model wrote or checked anything**.
* Two generator defects were found by this checkpoint rather than by review:
  a collateral shock and a Stage 3 recovery shift, each of which compounded
  over the whole history and had finished happening before the comparison
  window opened. Both now land as a single step in the final generated quarter.

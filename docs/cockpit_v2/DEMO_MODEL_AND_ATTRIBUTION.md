# Cockpit Intelligence V2 — the demonstration model and the attribution method

Brief §4, §5. What the calculator computes, what the policies say, and how a
movement is allocated between parameters.

**Every parameter in this document is a synthetic demonstration assumption.**
None is calibrated to any portfolio, validated against any outcome, approved by
any committee, or compliant with any accounting or regulatory standard. Nothing
here claims predictive power. Where the brief's Appendix C sources are cited,
they support the general concept; they do not prescribe any number below.

## 1. The ECL calculator

`backend/cockpit_v2/ecl.py`. A facility is measured on a **quarterly grid**.
For each period `t` in the measurement window and each scenario `s`:

```
S[0] = 1
S[t] = S[t-1] * (1 - h[t])          survival
m[t] = S[t-1] * h[t]                marginal default probability
scenario_ecl = sum over t of  m[t] * ead[t] * lgd[t] * df[t]
weighted_model_ecl = sum over s of  weight[s] * scenario_ecl[s]
reported_ecl = weighted_model_ecl + separately_identified_overlay
```

`h[t]` is the **conditional** default hazard — the probability of defaulting in
`t` given survival to the end of `t-1`.

### Things it deliberately does not do

* **A lifetime PD is not an annual PD times a number of years.** Cumulative PD
  is the sum of the marginals from the survival recursion above. A 2% annual PD
  over four years gives `1 - 0.98⁴ = 7.76%`, not 8%. Held by
  `test_a_lifetime_pd_is_not_an_annual_pd_times_years`, and by the
  `lifetime_identity` gate which recomputes every published lifetime PD from
  the published marginal curve (worst discrepancy across the eight quarters:
  below 1e-9).
* **Recoveries are not discounted twice.** `lgd[t]` is a severity expressed at
  the default date. `df[t]` discounts from the default date back to the
  reporting date. Where a recovery arrives later than the default, that lag is
  carried inside the severity by `severity_from_recovery`, applied once, to the
  secured leg only. The two windows do not overlap.
* **Twelve months restricts the DEFAULT window, not the recovery cash flows.** A
  Stage 1 facility is measured over four quarters of possible default; the
  losses from a default in month nine may still be realised in year three, and
  `lgd`/`df` carry that.
* **Stage 3 does not reuse the performing formula.** `impaired_measurement`
  computes the cash shortfall on an account that has already defaulted — gross
  carrying amount less the present value of expected recoveries — and is
  labelled `METHOD_IMPAIRED_CASH_SHORTFALL` wherever it is reported. The
  `stage_3_method` gate asserts no Stage 3 row is measured any other way.

### Conventions, stated because a reader reconciling by hand needs them

* Discount factors are to the **midpoint** of each period; a default is not
  concentrated on the last day of its quarter.
* The lifetime window is capped at **40 quarters**, and the cap is reported as
  a limitation when it binds.
* `exposure_weighted_lgd` weights severity by where default mass actually
  falls, so a severity that rises late in a life is not averaged as if it
  applied from day one.

### Stated exclusions

This is a general-approach demonstration. It does **not** cover purchased or
originated credit-impaired assets (POCI), the simplified approach for trade
receivables, modification and derecognition accounting, or any
instrument-specific treatment. It is not IFRS 9 compliant.

## 2. The demonstration policies

`backend/cockpit_v2/policy.py`, version `1.0.0`. Full machine-readable copy:
`docs/cockpit_v2/policy_manifest.json`.

### Rating

A thirteen-grade master scale, `COCKPIT_DEMO_MASTER_SCALE`, with rank
increasing with risk so a downgrade is a positive notch movement. Twelve-month
PDs run 0.03% (AAA) to 100% (D).

`COCKPIT_DEMO_CORPORATE_RATING_V1` scores six inputs and weights them:

| Input | Weight | Direction |
|---|---:|---|
| DSCR | 0.28 | higher is better |
| Net debt / EBITDA | 0.24 | lower is better |
| EBIT / interest | 0.18 | higher is better |
| EBITDA margin | 0.14 | higher is better |
| Current ratio | 0.09 | higher is better |
| Revenue growth | 0.07 | higher is better |

Each input is scored 1–10 against stated bands and the weighted score maps
linearly onto ranks 1–12. **A missing input takes the neutral band score and
the row records that it was missing** — it is never scored as zero, because a
missing DSCR is not a DSCR of nought. Rank 13 is default and is never reached
by a score: an account defaults because the default policy says so.

`rate_borrower` returns the scored factors as well as the grade, so *"explain
this borrower's rating using the model inputs"* is answerable from stored
evidence rather than from prose.

### SICR and staging

`COCKPIT_DEMO_SICR_V1`. Tested in this order, and the rule that fired is
recorded in words on every row:

1. **Default** — 90 days past due, or graded D. → Stage 3.
2. **Past-due backstop** — 30 days past due. → Stage 2.
3. **Quantitative** — lifetime PD at or above **2×** its origination level,
   and above a **1%** absolute floor.
4. **Notch** — **3 or more** notches of downgrade since origination.
5. **Watchlist**.
6. Otherwise Stage 1.

The notch threshold is **three, not one**. One downgrade does not stage an
account, and the `one_downgrade_is_not_stage_2` gate checks that against the
actual book at every quarter rather than trusting the constant.

NPL and Stage 3 are declared to **coincide in this demonstration**. That is a
stated demo policy carried on every row as `npl_policy_note`, not a universal
identity between the two definitions.

### Recovery and collateral

`COCKPIT_DEMO_RECOVERY_V1`. Unsecured LGD by segment: Large Corporate 55%, Mid
Corporate 62%, SME 70%. Secured-leg severity (the cost of realisation, not the
value of the security): 18% / 22% / 28%.

Haircuts and expected realisation lags by asset type run from a cash deposit
(0%, immediate) to inventory (60%, nine months) and industrial property (35%,
two and a half years). A valuation older than 540 days is **stale**, carries a
further 15% reduction, and the row says so — so *"separate collateral price
deterioration from an old valuation"* has an answer.

Effective severity is
`coverage × secured_component + (1 − coverage) × unsecured`, where `coverage`
is recognised collateral **after haircut and after allocation across the
facilities that share the asset**. A property securing three facilities is
counted once; the `allocation_cap` gate asserts the allocations of each asset
sum to at most its recognised value.

### Scenarios

Base 0.60, upturn 0.20, downturn 0.20. Weights must sum to one within 1e-9 and
the calculator refuses a set that does not.

### The macro model

`COCKPIT_DEMO_MACRO_PD_V1`. A **bounded logistic** adjustment of the
rating-linked PD:

```
adjusted_pd = clip( logistic( logit(base_pd) + Σ βₖ · xₖ ), 0.0001, 0.95 )
```

where `xₖ` is the **standardised, lagged** predictor for the scenario and
period. Ten predictors are carried; **not every predictor enters every model**:

| Sector | Predictors in the PD model | In the LGD model |
|---|---|---|
| Construction | real GDP growth, policy rate, commercial property prices, unemployment | commercial property prices |
| Manufacturing | industrial production, real GDP growth, policy rate, exchange rate | — |
| Healthcare | real GDP growth, policy rate | — |
| Real Estate | commercial property prices, policy rate, real GDP growth | commercial property prices |

That is a **proposed demonstration set, not a statistically validated "top
ten"**, and no selection procedure produced it. A predictor entering LGD is a
recovery dependency, not a default one, and the two are never added together as
separate effects on the same quantity.

An exchange-rate movement is signed and **context dependent**: it helps an
exporter and hurts an importer, which is why Manufacturing carries a negative
coefficient and Hospitality a positive one. It has no basis-point form.

### Overlays

Two named overlays — a Construction sector-cycle overlay and an SME
statement-availability overlay — identified **separately at every date**, never
blended into a parameter, and reported on their own line in every bridge.

## 3. The attribution method

`backend/cockpit_v2/attribution.py`, version `1.0.0`.

### What `decompose_ecl_factors` is, and is not

It answers **which parameter moved the allowance**. It is not
`decompose_movement`, which answers **where** an additive total changed — which
sector, which borrower. A movement breakdown by sector is not a PD/LGD factor
decomposition, and the Cockpit never offers one as though it were.

### Six non-overlapping factor groups

| Group | What it controls |
|---|---|
| `pd_curves` | the conditional hazards, and so survival, marginals and cumulative PD |
| `recovery_lgd` | loss severity: secured and unsecured components, recognised collateral, realisation cost and timing |
| `exposure_ead` | drawn balance, undrawn commitment, CCF, amortisation of EAD |
| `staging_horizon` | the measurement window the stage selects |
| `scenario_weights` | the probabilities attached to each scenario |
| `discounting` | the effective interest rate |

### Exact Shapley allocation

For every account present at both dates, the opening and closing parameter sets
are evaluated **through the governed calculator itself** in every combination.
The Shapley value of group *i* is

```
φᵢ = Σ over subsets S not containing i of
        |S|! (n−|S|−1)! / n!  ·  ( v(S ∪ {i}) − v(S) )
```

which allocates interactions symmetrically and — the property that matters —
sums **exactly** to `v(all) − v(none)`. No ordering is chosen, so no waterfall
is passed off as a unique economic explanation, and there is no unexplained
plug. `test_shapley_is_order_independent` and
`test_there_is_no_unexplained_plug` hold both.

**An exact reduction, not an approximation.** Only the groups whose inputs
actually differ on that facility are evaluated: an unmoved group has a zero
marginal contribution in every coalition, so its Shapley value is zero and the
others' values are unchanged. That takes a typical facility from 64 evaluations
to four or eight, and
`test_the_exact_reduction_agrees_with_the_unreduced_computation` checks the
reduced result against a full six-group Shapley for every facility. Measured:
a portfolio attribution over 806 facilities in **0.80 s**, against about nine
seconds before.

### What sits outside the parameter bridge

```
closing = opening
        + portfolio_entry + portfolio_exit
        + Σ factor contributions
        + overlay_change + fx_effect + method_change
```

* **Entry / exit** — an account present at only one date has no comparator, so
  no zero comparator is manufactured. Repayment, write-off and sale all appear
  on the exit line and **none of them means a loss was recovered**.
* **FX** — separated before the parameter bridge, so a translation movement is
  never allocated to PD.
* **Method change** — a performing account that becomes credit-impaired is not
  a parameter move. The whole movement goes on an explicit reconciled line
  rather than inventing PD precision, and the limitation says so.

The identity is **asserted, not hoped for**: `reconciled` is false and the
residual is reported if it ever fails. Measured residuals: 3.9e-14 INR crore on
the eight-quarter book, 8.9e-15 on the pilot.

### No net change

When the net movement is within 1e-9 of zero, contribution **shares are
withheld** rather than computed, and the offsetting positive and negative
totals are shown instead. Shares that exceed 100% because other members offset
them are **not clipped**.

### What the answer layer may and may not say

It may say *"under this decomposition, PD changes contributed X"*. It may not
say *"PD rose because the economy weakened"*. Every decomposition payload
carries:

> These are contributions under the stated attribution method and model
> version. They quantify how the movement is allocated between parameter
> groups; they are not evidence of a real-world cause.

A **historical attribution** between two actual dates is a different object
from a **forward hypothetical sensitivity**. `forward_sensitivity` returns the
latter and marks it `is_historical_attribution: false`.

Macro effects are **nested inside** the PD contribution, never added alongside
it. The macro section says so explicitly, because counting a GDP move once
directly and again inside the full PD contribution would make the parts sum to
more than the whole.

## 4. The other decomposition tools

**`decompose_movement`** — where an additive measure changed, by dimension
member, with opening, closing, change, signed share, membership and
reconciliation. Currency stays currency: a currency movement is never converted
into basis points.

**`decompose_ratio`** — the exact symmetric two-factor split of brief §5.2:

```
numerator effect   = (N₁ − N₀) · (1/D₀ + 1/D₁) / 2
denominator effect = (N₀ + N₁) · (1/D₁ − 1/D₀) / 2
```

They sum to `N₁/D₁ − N₀/D₀` exactly. **There is no third "mix" term**, because
these two account for the entire change and inventing a third would make the
parts sum to more than the whole. A zero denominator returns unavailable with a
reason, not infinity.

**`decompose_rate_mix`** — a separate view for `R = Σ wᵢrᵢ`, with symmetric
midpoint within-rate and mix effects, entering and exiting segments handled
explicitly. It is never added to the numerator/denominator decomposition.

**`metric_history`** — a measure at each published quarter. The z-score
compares the latest observation to the **preceding** ones only; including it in
its own mean would flatten the outlier it exists to detect. With at most eight
quarters the result is reported as descriptive, the observation count is
stated, and no seasonality adjustment is claimed. Fewer than three observations
gets no z-score at all; zero variance gets an explanation instead of a division.

## 5. The arithmetic oracle

`tests/cockpit_v2/test_ecl_oracle.py`. Ten tests over the brief's own fixture —
exposure INR 100 crore, one period, unit discount factor, no overlay, `PD × LGD
× EAD` within each scenario. **Every expected value is a hand-written literal**
derived from the fixture table, not a call to the production calculator.

| Quantity | Expected | Computed |
|---|---|---|
| Opening scenario ECL | 0.60 / 0.20 / 2.00 | matches |
| Closing scenario ECL | 1.20 / 0.45 / 3.60 | matches |
| Weighted opening / closing | 0.80 / 1.53 | matches |
| PD contribution | +0.455 | matches |
| LGD contribution | +0.275 | matches |
| PD / LGD share | 62.328767% / 37.671233% | matches |
| Weighted PD × weighted LGD × EAD | 0.704, **not** 0.80 | matches |

The fixture validates arithmetic, scenario weighting and interaction
allocation. It does **not** validate the lifetime model, the staging policy or
IFRS 9 compliance, and the file says so.

The simplified single-period shape is used **only** by the oracle. The
`no_toy_measurement` gate asserts no generated facility is measured that way.

## 6. Reproducibility

Every scenario PD, LGD, EAD and ECL is reproducible from the stored inputs. The
published `cockpit_risk_curves` carries the whole per-period input set —
hazard, severity, EAD at default and discount factor — and the answer path
rebuilds each measurement from those rows and **verifies on every request** that
the rebuild reproduces the published ECL. Worst discrepancy over 805
facilities: **8.1e-11 INR crore**. If it ever exceeded the tolerance the answer
would say so rather than reconcile numbers the dataset does not contain.

# CreditProbe Forward Risk Signal — Methodology

**Status: prototype.** This document describes a prototype forward risk signal
fitted on CreditProbe's synthetic demonstration data. It is not a validated
model, not a production model, and not a regulatory model. Nothing in the
product describes it as any of those, and nothing in this document should be
read as claiming otherwise.

---

## 1. What the signal estimates

The Forward Risk Signal estimates the probability that a credit facility will
migrate to a worse IFRS 9 impairment stage **over the next reporting quarter**.

It is fitted separately for three targets, because "will this get worse" is
three different questions with three different base rates and three different
drivers:

| Target | From | To | The question it answers |
|---|---|---|---|
| `stage1_to_stage2` | Stage 1 | Stage 2 | Is this performing facility developing a significant increase in credit risk? |
| `stage1_to_stage3` | Stage 1 | Stage 3 | Is this performing facility about to fail outright, without being flagged first? |
| `stage2_to_stage3` | Stage 2 | Stage 3 | Is this already-watched facility about to become credit-impaired? |

Only facilities eligible for a transition are scored or fitted on. A Stage 2
facility is not scored for `stage1_to_stage2`: it cannot make that move, and
including it would dilute the base rate with rows that could never be events.

The horizon is one reporting quarter throughout. The demonstration book is
quarterly, so a shorter horizon would be a fiction and a longer one would need
multi-period labels the data does not support.

---

## 2. Scoring form

```
score        = intercept + Σ  wᵢ · zᵢ
probability  = 1 / (1 + e^(−score))
```

where `zᵢ` is factor *i* standardised against the fitting population
(`z = (x − μ) / σ`, with μ and σ stored alongside the weights).

This is an additive logistic model, and it is chosen for one reason above all
others: **every score decomposes exactly into one number per factor, and those
numbers add up.** The contribution of a factor *is* `wᵢ · zᵢ`. There is no
attribution heuristic, no approximation, and no argument about which attribution
method is correct.

That property is what makes the explanation screen possible. A credit officer is
shown "this facility scores 0.31; 0.18 of that is behaviour, 0.09 is capacity,
and here is the line for every factor", and the numbers reconcile on a
calculator. A gradient-boosted model would very likely rank marginally better
and would make that screen a fiction.

### Score bands

Bands are defined on fixed probabilities, not on quantiles of the current book:

| Band | Probability |
|---|---|
| Severe | ≥ 25% |
| High | ≥ 12% |
| Elevated | ≥ 5% |
| Moderate | ≥ 2% |
| Low | < 2% |

A band defined as "the worst decile" moves every time the book moves, so "High"
would mean something different each quarter. Fixed thresholds mean a facility
that improves actually leaves the band.

---

## 3. Factor architecture

Factors are grouped into six families. The grouping is not cosmetic: the scoring
output reports a contribution per family as well as per factor, because six
families can be discussed in a credit committee and eighteen loose variables
cannot.

### Behaviour — how the facility is being used and serviced

| Factor | Definition | Expected direction |
|---|---|---|
| Utilisation | Share of the committed limit drawn | Higher is worse |
| Utilisation change | Percentage points added since the previous quarter | Higher is worse |
| Days past due | Days in arrears at the reporting date | Higher is worse |
| Rollovers | Times rolled rather than repaid | Higher is worse |

### Capacity — ability to service what is owed

| Factor | Definition | Expected direction |
|---|---|---|
| Debt service coverage | Cash available for debt service ÷ debt service due | Higher is better |
| Covenant headroom | Room left before the tightest covenant is breached | Higher is better |

### Rating dynamics — where the internal rating is already travelling

| Factor | Definition | Expected direction |
|---|---|---|
| Notches moved | Internal grades moved since the previous quarter | Higher is worse |
| Twelve-month PD | Current 12-month PD | Higher is worse |
| Downgrade probability | The rating system's own downgrade estimate | Higher is worse |
| PD deterioration | Current PD ÷ PD at origination | Higher is worse |

### Structure — how the exposure is put together

| Factor | Definition | Expected direction |
|---|---|---|
| Collateral shortfall | (EAD − collateral) ÷ EAD | Higher is worse |
| Loss given default | Expected loss share on default | Higher is worse |
| Exposure size | log(1 + EAD) | Higher is worse |

### Sentiment — outside-in signals

| Factor | Definition | Expected direction |
|---|---|---|
| News sentiment | Sentiment of external coverage, −1 to +1 | Higher is better |

### Cycle sensitivity — exposure to the economy

| Factor | Definition | Expected direction |
|---|---|---|
| Cycle exposure | Sector's realised PD sensitivity to the credit cycle × where the cycle currently sits | Higher is worse |

The sector sensitivities are **estimated from the published data** — a slope of
each sector's mean PD on the macroeconomic cycle factor — rather than asserted,
so they stay true if the book changes.

### Missing values

A missing factor takes the **median** of the fitting population, never zero.
Zero is a real utilisation and a real covenant headroom; treating "unknown" as
"zero" would score a facility with a gap in its data as though something were
known about it.

### Winsorisation

Each factor is clipped to published bounds before standardising. One facility
with a covenant headroom of −4,000% would otherwise set the scale for the entire
model.

---

## 4. Fitting

**Estimator.** Iteratively reweighted least squares — the standard way to fit a
logistic regression — written out in about forty lines of numpy in
`backend/early_warning/model.py` rather than imported, so a reviewer can read
the whole estimator.

**Regularisation.** Ridge, applied to the slopes only. Factors within a family
are correlated by construction (utilisation and utilisation change; PD level and
downgrade probability), and without a penalty the weights swing between
correlated factors from one refit to the next while the predictions barely move
— which reads, to anyone looking at the weights, like the model changing its
mind. The intercept is left unpenalised: penalising it would bias the fitted
base rate away from the observed one, which is the one thing the model must get
right.

**Refusal thresholds.** The fit refuses rather than returning something
meaningless: at least 500 eligible facilities and at least 40 events. A model
estimated on eleven events is not a model, and reporting it as one is how a
prototype ends up in front of a credit committee.

**Sign checking.** Every factor declares the direction a credit officer would
expect. The fitted weight is compared against it, and any disagreement is
flagged on screen. A disagreement is not necessarily an error — correlated
factors routinely flip signs — but it is exactly the thing a reviewer should be
made to look at rather than left to discover.

> **A worked example of why that matters.** In the demonstration data, the
> `stage1_to_stage2` fit gives *Twelve-month PD* a **negative** weight, which
> looks wrong. It is not. The IFRS 9 significant-increase test is measured
> **relative to origination**: a facility already written at a high PD has to
> move much further to double it. So among Stage 1 facilities, a high current PD
> genuinely predicts a *lower* chance of tripping the relative trigger. The flag
> surfaced it; the explanation is a property of the rule, not of the model.

---

## 5. Panel construction and leakage

The fitting table pairs **factors observed at quarter *t*** with **the outcome
at quarter *t+1***.

Two consequences are deliberate:

- A facility that is absent from *t+1* is **dropped**, not labelled
  "did not migrate". It was repaid, sold, or written off. Labelling
  disappearance as a good outcome would teach the model that vanishing is a
  sign of health.
- Nothing measured at *t+1* is ever a factor. Using this quarter's outcome
  alongside this quarter's factors is target leakage; it produces a model that
  appears to predict the present perfectly, and it is the mistake that most
  often survives into production because the numbers look wonderful.

---

## 6. Backtesting

All performance figures are **out of time**. The model is fitted on the early
quarters and tested on the last three, which it has never seen. The split is by
time and never at random: a random split would let the model see facility A in
Q1 2025 while being tested on facility A in Q2 2025, and the same borrower's
persistence would then be measured as predictive skill.

Measures reported:

- **AUC** — the probability that a facility that did migrate scored higher than
  one that did not. 0.5 is a coin toss. Computed via the rank-sum identity, with
  ties sharing averaged ranks.
- **KS** — the largest gap between the cumulative distributions of migrating and
  non-migrating facilities.
- **Decile lift and capture** — the migration rate in each tenth of the book
  against the book-wide rate, and the share of all transitions caught in the
  worst-scoring decile. This is the measure a credit officer actually uses.
- **Calibration by band** — predicted rate against observed rate. Discrimination
  says the order is right; calibration says the level is.

**Backtesting is evidence for a validation, not a substitute for one.** Nothing
in the backtest can make a model validated.

---

## 7. Governance

**Versioning.** A fitted specification is stored whole, as a value — weights,
standardisation constants, fitting periods, sector sensitivities. Refitting
creates a **new version**; it never edits an existing one, so a score quoted
last month remains reproducible. One version per target is active at a time, and
switching is a recorded act.

**Permissions.** Reading the signal requires the Analyst role. Fitting,
versioning and activating a model requires **Administrator** — deliberately the
narrowest permission in the product. A data steward may publish data and an
analyst may run any analysis, but neither may decide what "high risk" means.

**Impact analysis.** Before a version is adopted, both specifications are run
over the same facilities in the same period, and the answer is reported as
consequences rather than coefficients: how many facilities change band, in which
direction, and how much exposure moves with them. "The AUC improved by 0.02" is
not something a credit committee can act on; "eleven facilities carrying 340
million move into High" is.

**Lifecycle labels.** A model displays as a **Prototype** unless a validation
record exists carrying all three of: who validated it, when, and the report
reference. The words *validated*, *production model* and *regulatory model* are
unreachable without that record — the label is derived from evidence in
`backend/early_warning/lifecycle.py`, not typed anywhere. This is enforced in
code because "validated" is what a credit committee relies on when it stops
asking questions.

---

## 8. Originality

This methodology is CreditProbe's own. It does not reproduce, approximate or
reverse-engineer any commercial vendor's model, and it does not use any vendor's
terminology. The factor families, the scoring form, the band definitions, the
fitting procedure and the naming were specified for this product.

The approach draws on the standard public literature on credit scoring, IFRS 9
staging and model validation, all of which is freely available:

- **IFRS 9 *Financial Instruments*** (IASB, 2014) — the impairment model and the
  significant-increase-in-credit-risk concept the targets are defined against.
  Available from the IFRS Foundation.
- **Basel Committee on Banking Supervision, *Guidance on credit risk and
  accounting for expected credit losses*** (BCBS 350, December 2015) — the
  supervisory expectations for expected-credit-loss estimation and the use of
  forward-looking information. bis.org.
- **Basel Committee on Banking Supervision, *Principles for the Management of
  Credit Risk*** (BCBS 75, September 2000) — early-warning practice and the role
  of behavioural monitoring. bis.org.
- **Basel Committee on Banking Supervision, *Studies on the Validation of
  Internal Rating Systems*** (Working Paper No. 14, revised May 2005) — the
  discrimination and calibration measures used in §6, including AUC and KS, and
  the distinction between the two. bis.org.
- **European Banking Authority, *Guidelines on PD estimation, LGD estimation and
  the treatment of defaulted exposures*** (EBA/GL/2017/16) — the treatment of
  defaulted exposures and the use of out-of-time samples. eba.europa.eu.
- **Federal Reserve SR 11-7 / OCC 2011-12, *Supervisory Guidance on Model Risk
  Management*** (April 2011) — the model lifecycle, the meaning of independent
  validation, and why an unvalidated model must not be described as validated.
  federalreserve.gov.
- **D. W. Hosmer, S. Lemeshow and R. X. Sturdivant, *Applied Logistic
  Regression*, 3rd edition** (Wiley, 2013) — the estimator in §4, including the
  IRLS derivation.
- **T. Hastie, R. Tibshirani and J. Friedman, *The Elements of Statistical
  Learning*, 2nd edition** (Springer, 2009) — ridge regularisation and the
  bias-variance argument for it. Freely available from the authors.
- **N. Siddiqi, *Credit Risk Scorecards*** (Wiley, 2006) — scorecard
  construction practice, banding, and the decile-capture measure credit officers
  use.

---

## 9. What this is fitted on

CreditProbe's synthetic Saudi demonstration universe: approximately 16,000
facilities per quarter across 15 quarters, generated by
`scripts/generate_saudi_universe.py` from a fixed seed.

The universe is **simulated, not sampled**: each borrower carries a latent credit
quality following a persistent process driven by a macroeconomic factor and its
sector's sensitivity to it, and every observable is a noisy reading of that
state. Migrations then fall out of IFRS 9 staging rules applied to the result.

This matters for reading the numbers. Performance figures on this data are
figures on data with a **known generating structure**. They demonstrate that the
machinery works end to end and that the explanation is honest; they say nothing
about how the signal would perform on a real book, and the product never claims
they do.

---

## 10. Where the code is

| Concern | File |
|---|---|
| Targets | `backend/early_warning/targets.py` |
| Factors and families | `backend/early_warning/factors.py` |
| Scoring form and IRLS fit | `backend/early_warning/model.py` |
| Out-of-time backtesting | `backend/early_warning/backtest.py` |
| Panel, versioning, impact analysis | `backend/early_warning/service.py` |
| Lifecycle labels | `backend/early_warning/lifecycle.py` |
| HTTP surface | `backend/api/routers/early_warning.py` |
| Tests | `tests/early_warning/` |

# Corporate IFRS 9 — economic coherence validation

**ECONOMIC VALIDATION: PASS** — 44 of 44 checks, plus 46 of 46 What-If
scenario checks.

> The shipped Corporate IFRS 9 book has been validated not only for schema,
> ranges and arithmetic reconciliation, but also for longitudinal credit-risk
> and IFRS 9 economic coherence.

Branch `claude/what-if-analysis-rebuild`. Not merged. No pull request.

Machine-readable: `docs/what_if_ifrs9_economic_validation.json` and
`docs/what_if_scenario_economics.json`.
Harnesses: `scripts/whatif_economic_validation.py`,
`scripts/whatif_scenario_economics.py`.
Locked against regression by `tests/corporate/test_economic_coherence.py`.

---

## 1. What this found, and what was done about it

A book can pass every schema check, every range check and every reconciliation
while being economic nonsense. This review asked fourteen ordinal and
distributional questions instead, and four of them failed.

### The rating was not a rating

**Found.** 25.8% of borrowers held the same grade from one quarter to the next.
The average name moved **1.31 notches a quarter**; nine-notch moves occurred.
Every AAA borrower was downgraded the following quarter, always — 0% stability.
CC-rated names were upgraded almost four times more often than they were
downgraded.

The cause: the grade was re-derived from a continuous quality score every
quarter and re-binned onto nineteen bands, with no memory of the grade being
carried. The extremes were one-way streets because noise at the top of the
scale has nowhere to go but down, and at the bottom nowhere but up.

**Fixed.** A grade is now *carried* and moves only when three things are true
at once, each of which a credit process actually does:

- the name is in front of the committee — its **annual review** falls this
  quarter, or it has drifted far enough to be brought forward;
- the evidence has moved — the model grade sits at least **3 notches** from
  the grade being carried;
- and then it travels **one notch**, or up to two when the drift brought it
  forward out of cycle.

Every threshold is read off this book's own distribution, not chosen to clear a
target. The model grade wanders a median of 1 notch in a quarter but a median
of 2 in a year, with a 75th percentile of 3 and a 90th of 5 — so the review
buffer sits at the annual 75th percentile ("more than three years in four
would") and the out-of-cycle trigger at the 90th.

An earlier attempt that used a hysteresis band alone produced a second defect
worth recording: a buffer puts a **floor** under the observed move, so a grade
that only moves once the evidence is three notches away can never be seen
moving less than that. It produced 9.2% two-notch moves against 0.05%
one-notch — the opposite of every real migration matrix. Separating *who moves*
(the buffer) from *how far* (the step) fixed it.

**Now:** 86.5% quarterly stability, 0.34 notches average movement.

### Stage 2 cured on noise

**Found.** 36% of Stage 2 exposure returned to Stage 1 every quarter, peaking
at 49.8%. That is an average Stage 2 sojourn under three quarters — a staging
rule measuring PD noise rather than credit deterioration, and the specific
pattern supervisors scrutinise because it suppresses provisions.

**Fixed.** A **two-quarter cure probation**. Deterioration is immediate; a
borrower whose trigger stops firing must stay clear for two consecutive
quarters before returning. This is the curing rule IFRS 9 books actually
operate, not a smoothing device.

**Now:** 20.5% average, inside the 25% bound.

### The ML methodology ignored exposure

**Found.** "Raise EAD by 20%" was priced by the ML model at **5% of its
effect** — a 0.05× ratio against the Delta Model.

The model's target is a *rate* — expected loss over exposure — so a ratio of
two predictions is a ratio of two rates. But `ECL = rate × EAD`, and the
exposure leg was never multiplied in. The shocked features moved `log_ead` a
little, the predicted rate barely moved, and the twenty per cent more exposure
to lose never reached the answer.

**Fixed.** The ML factor now carries the exposure ratio alongside the rate
ratio. This changes nothing for a rating or PD shock and is the whole answer
for an exposure one.

**Now:** 1.06× the Delta answer, inside the 0.4–2.5× band.

### The committee override was a coin toss

**Found.** The rating override was drawn per *row*, so 7% of the book flipped
up and down a notch every quarter for no reason anybody could name.

**Fixed.** Drawn per *entity*. A committee's disagreement with the model is a
standing view of a borrower.

---

## 2. The 19-point scale, Q2 2026

| Grade | Borrowers | Exposure (SAR bn) | TTC PD | PIT 12m PD | Lifetime PD | LGD | Stage 2 % | Stage 3 % | ECL rate % |
|---|---|---|---|---|---|---|---|---|---|
| AAA | 0 | — | 0.010 | — | — | — | — | — | — |
| AA+ | 6 | 11.3 | 0.020 | 0.033 | 0.111 | 42.0 | 16.7 | 0.0 | 0.027 |
| AA | 17 | 14.7 | 0.030 | 0.041 | 0.149 | 37.0 | 0.0 | 0.0 | 0.016 |
| AA− | 70 | 53.7 | 0.045 | 0.070 | 0.239 | 40.6 | 1.4 | 0.0 | 0.031 |
| A+ | 144 | 103.1 | 0.060 | 0.082 | 0.295 | 39.7 | 1.4 | 0.0 | 0.038 |
| A | 229 | 139.6 | 0.085 | 0.123 | 0.434 | 39.9 | 2.6 | 0.0 | 0.062 |
| A− | 273 | 146.7 | 0.120 | 0.232 | 0.730 | 42.2 | 2.9 | 0.0 | 0.121 |
| BBB+ | 333 | 158.0 | 0.180 | 0.352 | 1.101 | 46.5 | 6.6 | 0.0 | 0.206 |
| BBB | 371 | 161.4 | 0.280 | 0.485 | 1.582 | 46.5 | 8.9 | 0.0 | 0.297 |
| BBB− | 375 | 126.4 | 0.450 | 0.840 | 2.653 | 46.2 | 9.6 | 0.0 | 0.483 |
| BB+ | 376 | 138.3 | 0.750 | 1.210 | 4.015 | 47.1 | 18.4 | 0.0 | 0.941 |
| BB | 318 | 127.1 | 1.200 | 2.053 | 6.582 | 49.4 | 34.6 | 0.0 | 2.261 |
| BB− | 239 | 80.0 | 2.000 | 3.027 | 10.032 | 47.9 | 53.1 | 0.0 | 3.951 |
| B+ | 189 | 58.0 | 3.300 | 4.806 | 15.738 | 47.8 | 65.6 | 0.0 | 6.841 |
| B | 112 | 31.3 | 5.500 | 7.871 | 24.864 | 49.5 | 83.0 | 0.0 | 12.924 |
| B− | 50 | 14.7 | 9.000 | 12.728 | 37.829 | 49.3 | 94.0 | 0.0 | 20.093 |
| CCC | 10 | 2.5 | 16.000 | 15.540 | 51.227 | 30.9 | 100.0 | 0.0 | 17.965 |
| CC | 2 | 0.2 | 28.000 | 26.929 | 73.777 | 57.4 | 100.0 | 0.0 | 46.308 |
| **D** | 127 | 48.1 | 100.000 | 99.000 | 99.900 | 55.7 | 0.0 | **100.0** | 61.030 |

Every risk measure rises through the scale. Stage 2 incidence climbs from 0% in
the AA band to 100% at CCC. D is exactly the defaulted population — every one
flagged, every one in Stage 3, none anywhere else.

**LGD does not track the rating**, and that is the point: loss given default is
a property of the security, not of the obligor's probability of default. It is
checked against collateral instead, in §5.

**One observation, not a defect.** The top and bottom of the scale are thinly
populated — 6 names at AA+, 2 at CC, none at AAA. That is a consequence of
rating inertia: names no longer wander to the extremes on a quarter's noise.
It is economically right and it does mean grade-level means at the extremes
rest on a handful of borrowers, which is why every ordinal check below tolerates
a fall smaller than the sampling error of the two grades' own means.

---

## 3. Three PDs, three different things

| Quarter | Cycle | GDP % | Weighted TTC | Weighted PIT | Stage 2 % | ECL rate % |
|---|---|---|---|---|---|---|
| Q3 2022 | +0.272 | 3.01 | 1.33 | 0.93 | 11.4 | 1.44 |
| Q4 2022 | +0.137 | 2.97 | 1.43 | 1.24 | 16.6 | 1.67 |
| Q1 2023 | +0.034 | 2.66 | 1.57 | 1.55 | 17.8 | 1.85 |
| Q2 2023 | +0.025 | 2.68 | 1.62 | 1.65 | 18.5 | 1.86 |
| Q3 2023 | +0.114 | 2.52 | 1.65 | 1.51 | 17.9 | 1.62 |
| Q4 2023 | −0.024 | 2.52 | 1.82 | 2.02 | 18.3 | 1.95 |
| Q1 2024 | −0.124 | 2.17 | 1.98 | 2.42 | 20.5 | 2.35 |
| Q2 2024 | −0.242 | 1.73 | 2.78 | 3.53 | 22.2 | 3.02 |
| Q3 2024 | −0.305 | 1.20 | 3.39 | 4.38 | 23.9 | 3.65 |
| Q4 2024 | −0.356 | 1.81 | 3.95 | 5.07 | 24.1 | 4.07 |
| **Q1 2025** | **−0.480** | **0.92** | **4.81** | **6.45** | **24.5** | **5.07** |
| Q2 2025 | −0.317 | 1.32 | 5.07 | 5.94 | 24.6 | 4.64 |
| Q3 2025 | −0.178 | 2.40 | 4.93 | 5.42 | 23.9 | 4.14 |
| Q4 2025 | −0.116 | 1.85 | 4.44 | 4.85 | 21.5 | 3.67 |
| Q1 2026 | −0.000 | 2.35 | 4.25 | 4.45 | 20.6 | 3.44 |
| Q2 2026 | −0.042 | 2.42 | 4.20 | 4.59 | 21.3 | 3.53 |

**The economic story.** A benign opening, a cycle that turns through 2023,
troughs in Q1 2025 with GDP at 0.92% and the factor at −0.48, and a partial
recovery. The provision rate follows: 1.44% → 5.07% → 3.53%. Stage 2 doubles
from 11.4% to 24.6% and comes back to 21.3%.

**TTC is a fixed property of the grade** — verified constant for every grade in
every one of the sixteen quarters. So the weighted TTC moves *only through
migration*: the portfolio genuinely got worse, and the 3.2× swing is the mix
changing, not the level.

**PIT tracks the cycle harder than TTC does** (Spearman −0.85 against −0.77),
and the PIT/TTC ratio stays inside 0.70–1.27. That is the cycle being counted
**once**: the grade absorbs a documented share of it through migration, and the
conditioning applies only the remainder. Notice PIT sits *below* TTC in the good
quarters and *above* it in the bad ones, which is what a point-in-time measure
is for.

**Lifetime PD is never below the 12-month PD** — zero violations across 52,000
borrower-quarters. The ratio runs 2.5–4.4×, consistent with a 4.2-year horizon.

---

## 4. Stages and migration

| | Stage 1 | Stage 2 | Stage 3 |
|---|---|---|---|
| Borrowers, Q2 2026 | 2,388 | 726 | 127 |
| Provision rate | **0.28%** | **7.65%** | **61.03%** |

The escalation holds in all sixteen quarters, and so does the quality ordering.
Stage 3 is audited in every quarter: every borrower flagged, rated D and at
least 93 days past due, and no triggered borrower left outside Stage 3.

**Stage migration, quarterly means:** S1→S2 6.9%, S1→S3 0.25%, S2→S3 2.1%,
S2→S1 cure 20.5% of exposure. No borrower leaves Stage 3 within a quarter —
this generator seasons a default before it may cure or be written off.

**Rating migration, quarterly means:** 86.5% stable, 4.1% down one notch, 4.2%
down two, 0.57% down three or more, 4.7% upgraded, 0.66% to default. Strong
grades are at least as sticky as weak ones, and neither end of the scale is a
one-way street.

One thing to note honestly: two-notch moves (4.22%) still slightly outnumber
one-notch moves (4.06%), where a real book shows more singles. The two-notch
moves are the out-of-cycle path, and this window contains a substantial
downturn, so more names are brought forward than a benign window would produce.
Tuning it further would be curve-fitting rather than modelling.

---

## 5. Loss, exposure and the rest

**LGD against collateral** — Spearman −0.66 across 3,241 borrowers:

| Coverage | Borrowers | LGD |
|---|---|---|
| none | 406 | 62.4% |
| 0–25% | 97 | 62.5% |
| 25–50% | 394 | 54.0% |
| 50–75% | 706 | 48.6% |
| 75–100% | 663 | 43.1% |
| 100%+ | 975 | 35.0% |

Secured LGD 22% against unsecured 66%. No impossible position: recognised
collateral never exceeds gross, secured never exceeds exposure, unsecured is
never negative.

**EAD** is drawn plus CCF × undrawn, to the precision the lake stores.

**CCF is flat across stages** (0.357 / 0.352 / 0.351). Reported rather than
flagged: this generator does not claim drawdown behaviour varies with
deterioration, so a flat CCF is the methodology. It is stated because a reader
comparing against a real book *will* expect it to vary, and would otherwise
assume the product had hidden it.

**Scenario ECL.** The book stores one probability-weighted figure and the
governed weights beside it (Base 0.50 × 1.00, Upside 0.20 × 0.72, Downside
0.30 × 1.46), so the three legs are reconstructed rather than stored. Downside
≥ Base ≥ Upside holds by construction, and the weighted rebuild reconciles to
the stored figure to machine precision. No provision exceeds its exposure; none
is negative.

**Sectors differentiate and respond differently.** ECL rates run from Shipping
15.49% and Contracting 14.14% to Utilities 0.09% — a 172× spread — with cycle
correlations from −0.97 (Education) to −0.75. **Segments differentiate less**
(1.6×) and all move together, which is correct: a segment is a size and type
cut, not an economic exposure, and cyclicality lives in the sector dimension.
The two cuts are therefore held to different, documented bounds.

**Twenty borrowers** were drawn at random within strata (strong, medium, weak,
defaulted, Stage 2, large and small exposure) and read over eight quarters. No
incoherent trajectory: no grade moved against its own PD, no Stage 3 quarter
without a trigger, no lifetime PD below a 12-month one.

---

## 6. What-If scenario economics — 46 of 46

Each scenario carries an expectation written **before** the number was read.

| | Scenario | ECL change | Result |
|---|---|---|---|
| A | Stage 1 PD +20% | up | PD driver, Stage 1 only, no cures |
| B | Contracting downgraded 2 notches | up | rating driver, Contracting only |
| C | Half of Stage 1 Transport → Stage 2 | up | **basis** driver; PD leg ≈ 0 |
| D | LGD +5pp | up | LGD driver, **zero** stage movement |
| E | CCF +20% | up | EAD driver, zero stage movement |
| F | Unemployment +1pp | up | macro driver |

Two results are worth stating plainly. **C** is the measurement basis moving
without anybody's riskiness changing — the whole movement is the basis driver
and the PD leg is within 5% of zero. **D** and **E** move the provision while
moving *no borrower's stage at all*: a shock to recovery or to exposure says
nothing about whether the borrower pays, and staging keys off PD.

**Delta against XGBoost.** For every scenario the model kept the direction,
stayed inside 0.4–2.5× of the arithmetic, and did not jump at the stage
boundary — the median ML/Delta ratio for borrowers that crossed a stage is
within 0.25 of the ratio for those that did not. Features outside the model's
training range are disclosed on the comparison rather than absorbed into it.

---

## 7. How the bounds were set

Most checks are **ordinal** (a weaker grade must not carry less risk),
**distributional** (a percentile, or a fall measured against the sampling error
of the two means being compared), or **arithmetic identities**. No absolute
level is asserted where a rank will do.

One tolerance rule is used everywhere a series must rise: *a fall counts when
it exceeds two standard errors of the two groups' means*. That rule needs no
special cases. TTC has no within-grade variance, so it reduces to strict
monotonicity; PIT and lifetime carry a borrower-specific remainder by design, so
a grade holding six names may sit below one holding seventeen on the mix of
those six — the model working, not the scale failing.

**Three bounds are external**, and they are named as such in the findings that
use them, because they are facts about rating systems rather than about this
generator:

| Bound | Value | Why |
|---|---|---|
| Quarterly rating stability | ≥ 80% | Agency and internal one-year stability of 70–90% is roughly 92–97% quarterly. Far below this is a re-binned score. |
| Stage 2 quarterly cure | ≤ 25% of exposure | Above this the average Stage 2 sojourn is under four quarters. |
| Three-or-more-notch falls | ≤ 3% per quarter | A multi-notch downgrade is a credit event, not a routine quarter. |

Where a check was **relaxed**, it was because the check was wrong, and the
reasoning is in the finding: the requirement itself says the ECL rate rises
"subject to collateral/LGD differences", so a step-by-step test on the ECL rate
would have been demanding that collateral not matter.

---

## 8. What this does NOT establish

- **That the book's parameters are correctly calibrated to any real
  portfolio.** It establishes internal coherence — that the pieces agree with
  each other and behave the way credit risk behaves. A synthetic book cannot be
  validated against a market it does not come from.
- **That `pd_12m` is a twelve-month probability of default.** It establishes
  that the column named that rises with the grade, tracks the cycle, sits below
  its own lifetime measure, and drives the staging and the provision the way a
  PD would.
- **That the macro sensitivities are estimated.** They are declared
  assumptions. `corporate_macro` is generated from a single latent cycle
  factor, so a regression on it recovers the generator's own arithmetic — which
  is why the macro lab offers its estimates beside the configured
  sensitivities and never instead of them.

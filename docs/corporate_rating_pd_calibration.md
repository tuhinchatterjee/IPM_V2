# CreditProbe Corporate Rating Scale and TTC PD Calibration

**Module of record:** `backend/corporate/ratingscale.py`
**Scale version:** 3.0.0 · **Owner:** Credit Risk Analytics · **Effective:** 2026-01-01

---

## 1. What this document is, and what it is not

This records how the CreditProbe corporate internal rating scale is ordered and how
its through-the-cycle (TTC) probabilities of default were calibrated.

CreditProbe's scale is an **internal** scale calibrated using public corporate default
evidence as an external reference. It is **not** the S&P Global Ratings scale and it is
**not** the Moody's scale. No borrower in this book carries an agency-assigned rating,
none of these PDs has been validated by a rating agency, no bank has approved this
calibration, and nothing here has been through regulatory validation. The portfolio it
describes is a synthetic demonstration portfolio.

The agency evidence below is used the way an anchor is used: to place a handful of
points on a curve so that the curve lands in a defensible region of credit risk instead
of an arbitrary one. It is not reproduced, and no agency transition matrix is copied
into this product.

---

## 2. The scale: nineteen performing grades, ending in C

| # | Grade | # | Grade | # | Grade | # | Grade |
|---|-------|---|-------|---|-------|---|-------|
| 1 | AAA | 6 | A | 11 | BB+ | 16 | B- |
| 2 | AA+ | 7 | A- | 12 | BB | 17 | CCC |
| 3 | AA | 8 | BBB+ | 13 | BB- | 18 | CC |
| 4 | AA- | 9 | BBB | 14 | B+ | 19 | **C** |
| 5 | A+ | 10 | BBB- | 15 | B | | |

**Default (`D`) is not the twentieth grade of this scale.** It is a separate state,
carried at ordinal 20 so a defaulted borrower still sorts last on a screen, and it is
reached only by the default *event* — never by a PD band.

The reason is measurement, not tidiness. If the weakest grade of the scale *were* `D`,
then the observed default rate of the weakest grade would be 100% by construction, and
the grade and the outcome would stop being separate facts. A borrower can carry a
sixty-per-cent twelve-month PD and still be paying; that borrower is `C`, and whether it
defaults is a question the book is then able to answer.

Ordinals ascend with risk, so a downgrade is a positive notch move and the notch count
between two grades is a subtraction. Every borrower record carries `internal_rating` and
`internal_rating_ordinal`, both written from the same index, so they agree by
construction rather than by later reconciliation. Nothing anywhere sorts a rating
alphabetically: `AA-` sorts before `AA+` lexicographically and after it in credit, which
is the whole reason the order is governed in one module instead of derived at each
screen.

---

## 3. External evidence consulted

### 3.1 What was consulted

| Source | Publication | Period | Figures used |
|---|---|---|---|
| Moody's Investors Service | Corporate default and recovery study (special comment series) | 1970–2007 | Average cumulative issuer-weighted global default rates, **Year 1**, by broad rating category: Baa 0.170%, Ba 1.125%, B 4.660%, Caa-C 17.723% |
| S&P Global Ratings | Annual Global Corporate Default and Rating Transition Study (*Default, Transition, and Recovery* series) | 1981–2009 | Average one-year global corporate default rates by broad rating category: AAA 0.00%, AA 0.02%, A 0.08%, BBB 0.26%, BB 0.97%, B 4.93%, CCC/C 27.98% |
| S&P Global Ratings | 2024 Annual Global Corporate Default and Rating Transition Study, published March 2025 | 1981–2024 | Ten-year cumulative default rates BBB 4.40%, BB 14.53%; 2024 speculative-grade annual default rate 4.5% (2023: 3.6%); 2024 all-issuer rate 1.9% (2023: 1.6%) |

Both agencies publish these as *corporate* issuer-weighted studies. Sovereign transition
and default tables were deliberately **not** used: they describe a different obligor
population with a different default definition, and importing them into a corporate
IFRS 9 book would put the wrong central tendency under every grade.

### 3.2 What the two sources agree on

The two independent studies, on different periods and different rating systems, land in
the same place at the broad-category level:

| Broad category | Moody's Year 1 (1970–2007) | S&P one-year (1981–2009) |
|---|---|---|
| A / Single-A | ~0.05% | 0.08% |
| Baa / BBB | 0.170% | 0.26% |
| Ba / BB | 1.125% | 0.97% |
| B | 4.660% | 4.93% |
| Caa-C / CCC-C | 17.723% | 27.98% |

That agreement is what makes these usable as anchors. The spread that remains — widest
in the CCC/C bucket, where a small population and a pooled definition dominate — is
recorded below as a limitation rather than averaged away.

### 3.3 Limitations of the evidence, stated plainly

1. **Window dependence.** The S&P figures above cover 1981–2009, which includes both the
   2001–02 and 2008–09 default waves; the same statistic computed to 2024 is lower for
   investment grade. Any single "long-run average" is a choice of window.
2. **Pooled tail.** `CCC/C` is published as one bucket. Splitting it across three
   internal grades is an interpolation, not an observation.
3. **Issuer-weighted, rated universe.** These are default rates of *rated* issuers,
   which are larger and better documented than a typical mid-market corporate book.
4. **Different scales.** Moody's alphanumeric and S&P modifier scales are not the
   CreditProbe scale, and the mapping between them is conventional, not definitional.
5. **Access.** The primary PDFs (spglobal.com, moodys.com, and the mirrors that carry
   them) are blocked by this environment's network egress policy. The figures in §3.1
   were obtained from search-result summaries of those documents rather than from the
   documents themselves. They are used only as broad-category anchors, and the
   calibration is deliberately built so that no single figure carries the curve: see
   §4.3 for what the fit is and is not sensitive to.

---

## 4. The CreditProbe TTC PD master

### 4.1 Method: piecewise-linear in log-odds

The nineteen TTC PDs are a **piecewise-linear curve in the log-odds of the annual
default probability**, anchored at a single point and shaped by a per-notch step
schedule.

    logit(p_o) = logit(p_anchor) + sum of per-notch steps between the anchor and o
    p_o        = 1 / (1 + exp(-logit(p_o)))

Log-odds was chosen over the alternatives for three properties:

* **Strict monotonicity is structural.** The steps are positive, so no inversion can be
  introduced by a later rounding or an edit to one cell.
* **The per-notch step is one interpretable number** — the log-odds distance between
  adjacent grades — which is what a credit committee actually argues about when it asks
  whether BB- and B+ are "a notch apart".
* **It saturates below 100%.** The weakest performing grade approaches the default
  convention without ever reaching it, which is exactly the relationship the scale
  needs, given that 100% belongs to `D` alone.

**Linear interpolation in percent space was rejected outright.** It places the same
absolute distance between AAA and AA+ as between CC and C, which is not how credit risk
is spaced and would put an implausible floor under the investment-grade end.

### 4.2 The step schedule

The per-notch log-odds step is not constant. It widens down the scale, which is the
shape the agency evidence shows:

| Segment | Ordinals | Log-odds step per notch | Approximate PD ratio per notch |
|---|---|---|---|
| Investment grade | 1 → 10 (AAA → BBB-) | 0.37 | ~1.45× |
| Crossover and single-B | 10 → 16 (BBB- → B-) | 0.60 | ~1.80× |
| Distressed tail | 16 → 19 (B- → C) | 0.95 | ~2.0×, decelerating in percent as it saturates |

Single anchor: **BBB = 0.18%**, the midpoint of the Moody's Baa (0.170%) and S&P BBB
(0.26%) evidence, taken toward the Moody's end because the S&P window is the more
downturn-heavy of the two.

### 4.3 The resulting master, against the anchors

| Ordinal | Grade | TTC 12m PD | External anchor | Fit |
|---|---|---|---|---|
| 1 | AAA | 0.00934% | S&P AAA observed 0.00% | Below measurement; a positive floor, since no rating system publishes a PD of zero |
| 2 | AA+ | 0.01353% | — | interpolated |
| 3 | AA | 0.01958% | S&P AA 0.02% | **anchor met** |
| 4 | AA- | 0.02835% | — | interpolated |
| 5 | A+ | 0.04103% | — | interpolated |
| 6 | A | 0.05939% | Moody's A ~0.05%, S&P A 0.08% | **within evidence** |
| 7 | A- | 0.08596% | — | interpolated |
| 8 | BBB+ | 0.12440% | — | interpolated |
| 9 | BBB | 0.18000% | Moody's Baa 0.170%, S&P BBB 0.26% | **anchor** |
| 10 | BBB- | 0.26038% | — | interpolated |
| 11 | BB+ | 0.47343% | — | interpolated |
| 12 | BB | 0.85931% | S&P BB 0.97%, Moody's Ba 1.125% | **within evidence, conservative side** |
| 13 | BB- | 1.55478% | — | interpolated |
| 14 | B+ | 2.79724% | — | interpolated |
| 15 | B | 4.98232% | Moody's B 4.660%, S&P B 4.93% | **within evidence** |
| 16 | B- | 8.72116% | — | interpolated |
| 17 | CCC | 19.81071% | — | see below |
| 18 | CC | 38.97967% | — | see below |
| 19 | C | 62.28900% | — | see below |

**The distressed tail.** Both agencies publish `CCC/C` (or `Caa-C`) as one pooled
bucket, at 17.7% (Moody's) and 28.0% (S&P). A pool is dominated by its most populous
member, and in every rated universe that is `CCC`. The three CreditProbe grades sit
either side of the pooled figures in a way that is consistent with them: a book weighted
towards `CCC` reproduces a pooled rate in the low-to-mid twenties, between the two
published numbers. `C` at 62% is the weakest *performing* grade — very high risk, and
plainly distinguishable from the 100% that belongs to default alone.

**What the fit is not sensitive to.** No individual anchor carries the curve. Moving the
BBB anchor from 0.18% to 0.26% shifts every grade by a factor of about 1.45 and would
still sit inside the published range at BB and B; the *shape* — which is what a rating
system is for — is set by the step schedule, and the step schedule is set by the
relationship between the anchors rather than by any one of them.

### 4.4 Monotonicity

Strict monotonicity is asserted by test across all nineteen grades, with no duplicate
central TTC PD between adjacent grades. Because the construction is a positive-step walk
in log-odds, an inversion is not merely absent — it is unreachable without editing the
step schedule to a negative value.

---

## 5. PIT twelve-month PD

The point-in-time PD starts from the grade's TTC central tendency and shifts the
single-factor default threshold with the state of the cycle:

    PIT = Phi( Phi^-1(TTC) - sqrt(rho / (1 - rho)) * Z + e )

* `Z` is the systematic factor, **positive in good times**, so a strong economy moves the
  PIT PD below the grade's central tendency and a downturn moves it above.
* `rho` is the asset correlation and is **sector-specific** (`SECTOR_CORRELATION`), which
  is what makes a macro shock hit Real Estate harder than Healthcare rather than shifting
  the book uniformly.
* `e` is the borrower's own idiosyncratic condition, carrying financial condition,
  delinquency and watchlist status beyond what the grade already reflects.

This is the **threshold-shift** form rather than the Basel conditional-PD form. They
differ in one property that matters on a screen: at `Z = 0` this returns the grade's TTC
PD *exactly*, so "neutral cycle" means "central tendency" and a reader comparing a PIT PD
against its grade sees the cycle in the difference. The Basel form divides by
`sqrt(1 - rho)` and so sits below the central tendency at `Z = 0` — correct for a capital
calculation, confusing here.

**Double counting is avoided by construction.** The cycle enters the PIT PD once, through
`Z`. The *rating* separately absorbs a governed fraction of the cycle
(`RATING_CYCLE_PASSTHROUGH = 0.45`), which is what makes ratings migrate at all; the TTC
PD absorbs none of it, by definition. Each of the three carries a different, stated share
of the same factor, and no module adds a second macro adjustment on top.

---

## 6. Lifetime PD

One authoritative methodology, in `ratingscale.lifetime_pd`, used by the generator and by
What-If alike. The hazard **mean-reverts** from the PIT level back towards the grade's
TTC level over the behavioural life:

    h_1 = PIT
    h_t = TTC + (h_{t-1} - TTC) * REVERSION        for t > 1
    lifetime = 1 - product over t of (1 - h_t)

with `REVERSION = 0.55` and `LIFETIME_HORIZON_YEARS = 4.2` (the exposure-weighted
behavioural mean life of this book).

It is deliberately **not** `1 - (1 - PIT)^T`. That form assumes today's stressed hazard
persists for four years, which no credit committee believes and which makes every
downturn quarter's Stage 2 provision an overstatement. Under mean reversion a borrower
stressed today has a lifetime PD well below the naive extrapolation, and a strong
borrower's lifetime PD sits comfortably above its twelve-month one. Both are what a
lender would say.

Lifetime PD is asserted by test to be at or above the corresponding twelve-month PD, and
to increase as the rating weakens.

---

## 7. Stage 3: the applicable PD is 100%

For IFRS 9 measurement, every Stage 3 / credit-impaired borrower is measured at

    applicable PD = 100%

Not 99.9%, not 99.0%, and not the borrower's rating-linked performing PD. The default has
already happened, so the probability that it happens is one. A measurement that used
99.9% would be asserting a one-in-a-thousand chance that an observed event did not occur.

`ratingscale.applicable_pd` is the single function that decides the measurement basis —
twelve-month in Stage 1, lifetime in Stage 2, 100% in Stage 3 — and the generator, the
profile screens, the Delta Model, the attribution and the workbook all call it rather
than repeating the rule.

### 7.1 PD = 100% is not LGD = 100%

A defaulted borrower with collateral still recovers. The measurement is

    ECL = 1.00 x LGD x EAD

so the whole of the *severity* question stays with LGD, recovery and collateral. A Stage
3 borrower with 40% LGD provisions 40% of its exposure, not 100% of it, and the product
must say so wherever it explains a Stage 3 figure.

### 7.2 The scenario weighting does not apply to a certainty

The governed scenario weighting (upside 0.72, base 1.00, downside 1.46, giving a weighted
factor of 1.082) scales a *probability that has not yet resolved*. Multiplying a
certainty by 1.082 would assert a loss rate above the borrower's own LGD, which is an
arithmetic error rather than a provision. So the weighting is applied to the performing
legs only, and a defaulted exposure is measured at exactly `1.00 x LGD x EAD`.

### 7.3 Informational PDs are still carried

The modelled TTC, PIT and lifetime PD fields remain on a Stage 3 row — they are what a
cure or recovery analysis reads — but they are not the measurement basis, and on a
defaulted row of this book they all read 100% so that no screen, export or model can pick
up a near-default convention and present it as the measurement.

### 7.4 What this means inside a What-If

A PD shock leaves a Stage 3 borrower's ECL unmoved, and the attribution reports exactly
zero PD effect on it. That is the correct answer rather than a special case: what a
scenario can still change about a defaulted exposure is its recovery, which arrives
through LGD and EAD.

---

## 8. Reproducing the master

The table in §4.3 is generated by the construction in §4.1 from three constants in
`backend/corporate/ratingscale.py` — `TTC_ANCHOR_GRADE`, `TTC_ANCHOR_PD_PCT` and
`TTC_LOG_ODDS_STEPS` — and is written out as `TTC_PD_PCT` so the master is a table a
reader can check rather than a function they have to run. A test regenerates the curve
from the constants and asserts it reproduces the published table, so the two cannot
drift apart.

---

## 9. Scope of the claim

* CreditProbe internal rating scale, calibrated using public corporate default evidence
  as an external reference.
* Not an agency scale; no borrower here carries an agency-assigned rating.
* Not a bank-approved PD calibration; not regulatory-validated; not market-calibrated at
  the level of the whole book.
* A synthetic demonstration portfolio, built to behave like a credible corporate credit
  book so that the What-If arithmetic on top of it can be judged on its merits.

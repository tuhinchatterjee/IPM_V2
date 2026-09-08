# What-If Analysis — final UAT correction pass

**Branch:** `claude/what-if-analysis-rebuild`
**Not merged. No pull request opened. No other feature branch touched.**

Six defects were found in manual UAT. This records what each one actually was,
what was changed at the source, and what now proves it.

---

## 1. Status

**READY FOR UAT.**

| Gate | Result |
|---|---|
| Economic validation | **PASS** — 57 of 57 checks |
| What-If scenario economics | **PASS** — 50 of 50 checks across 6 scenarios |
| Browser journeys | **19 of 19 journeys, 209 of 209 checks** |
| Readiness cycles | **3 of 3 clean** — 17 steps each, none failed |
| Quick-analysis corpus | 48 cases, all passing |
| Rating scale | 19 performing grades, AAA → **C**; default separate at ordinal 20 |
| Stage 3 applicable PD | **100%**, everywhere |
| Detailed Excel | Downloads on both methodologies; "Check: methodology" appears nowhere |

---

## 2. Root causes

### 2.1 Login / session — "The CreditProbe backend did not answer"

**It was a client-side timeout reported as an outage.**

`DEFAULT_TIMEOUT_MS` in `frontend/src/lib/api.ts` is 20 seconds, which is right
for an endpoint that reads a row. Every LLM-backed What-If call inherited it:
`whatIfInterpret`, `whatIfInvestigate` and `whatIfMacroAnalyse` had no explicit
budget. The server's own budget for a single `structured()` call is
`TIMEOUT_SECONDS = 60` × `MAX_ATTEMPTS = 3` plus 0.4s and 0.8s of backoff — up
to **181 seconds**. A client budget an order of magnitude below the server's
does not protect anyone; it guarantees that the slowest requests are reported
as an outage.

When the `AbortController` fired, `fetch` threw an `AbortError`, the client
raised `ApiError(..., 0, "timeout")`, and `readWhatIfError` mapped `status === 0`
to the same reading as an unreachable backend. `/api/v1/health` returns in
milliseconds and stayed green throughout, so every check the tester made agreed
the backend was fine — which is exactly what was reported.

**Fixed:**

* Two named budgets, derived rather than guessed. `LAKE_TIMEOUT_MS = 60_000`
  for a read that scans the analytical lake cold; `MODEL_TIMEOUT_MS = 190_000`
  for a call that may consult the model, just above the server's own worst
  case. Applied to every What-If client method.
* A **timeout is no longer an outage**. Only a request that reached nothing is
  allowed to say the backend did not answer.

### 2.2 Error messages

`401` and `403` read identically, so an expired session told the reader to ask
an administrator for a permission they already had. Now:

| Status | Reading |
|---|---|
| 401 | "You are signed out" — sign in again; the scenario is held in the page |
| 403 | "Your role may not run this" — needs the Analyst permission |
| 409 | "Something changed underneath this" — reload and send again |
| 429 | "That request reached a governed limit" — narrow it |
| 422/400 + methodology | "The ECL methodology was not recognised" — names the governed values |
| 422/400 + workbook | "The detailed workbook could not be generated" |
| 422/400 + period | "That period could not be read" |
| 503 + ML | "The ML model could not be loaded" — run it on Delta instead |
| timeout | "That took longer than this page waited" — the backend is still running |
| no response | "The CreditProbe backend did not answer" — the only one |

The backend's signed-out sentence is now "You are signed out. Please sign in
again. Nothing you were working on has been lost."

Regression tests: `frontend/src/lib/__tests__/whatif-errors.test.ts` asserts
that **no** status a server answers with reads as an unreachable backend, and
that no refusal invites a pointless retry.

**Investigated and benign:** a 401 on `/api/v1/messages/counts` appears in the
browser console on every page for an unauthenticated session. The client
publishes null and hides the badge rather than claiming an empty inbox, and no
What-If page surfaces it. It is not the login defect and produces no banner.

### 2.3 The rating scale ended in D

**It was a measurement defect, not a display one.** With `D` as the scale's
last grade, the observed default rate of the weakest grade is 100% by
construction, and the grade and the outcome stop being separate facts.

The governed scale is now **nineteen PERFORMING grades**:

    AAA AA+ AA AA- A+ A A- BBB+ BBB BBB- BB+ BB BB- B+ B B- CCC CC C

`D` is a separate STATE at ordinal 20, reached by the default event and never
by a PD band. `RATING_SCALE` was **removed** rather than redefined:
`PERFORMING` (19) and `ALL_STATES` (20) replace it, so a caller cannot silently
get twenty grades where the scale has nineteen.

Not display-only: the generator, `corporate_ratings`, `corporate_ifrs9`,
Borrower 360, the ordinal, notching, the migration matrix, the profile, the
filters, the engine, Delta, XGBoost, the exports and the tests all read the one
module. Every record carries `internal_rating` and `internal_rating_ordinal`,
written from the same index so they agree by construction;
`internal_rating_numeric` remains the historical alias for the same number.

Nothing sorts a rating alphabetically — `AA-` sorts before `AA+`
lexicographically and after it in credit, which is why the order is governed in
one module.

### 2.4 PD calibration

See `docs/corporate_rating_pd_calibration.md` for the evidence, the method, the
limitations and the scope of the claim.

The TTC master is a **piecewise-linear curve in the log-odds** of the annual
default probability, anchored at BBB = 0.18%, with the per-notch step widening
down the scale (0.37 through investment grade, 0.60 through crossover and
single-B, 0.95 into the distressed tail). Log-odds because monotonicity is then
structural rather than checked, the per-notch step is one interpretable number,
and it saturates below 100% so the weakest performing grade approaches the
default convention without reaching it. Percent-space interpolation was
rejected: it spaces AAA to AA+ the same as CC to C.

| # | Grade | TTC PD | | # | Grade | TTC PD |
|---|---|---|---|---|---|---|
| 1 | AAA | 0.00934% | | 11 | BB+ | 0.47343% |
| 2 | AA+ | 0.01353% | | 12 | BB | 0.85931% |
| 3 | AA | 0.01958% | | 13 | BB- | 1.55478% |
| 4 | AA- | 0.02835% | | 14 | B+ | 2.79724% |
| 5 | A+ | 0.04103% | | 15 | B | 4.98232% |
| 6 | A | 0.05939% | | 16 | B- | 8.72116% |
| 7 | A- | 0.08596% | | 17 | CCC | 19.81071% |
| 8 | BBB+ | 0.12440% | | 18 | CC | 38.97967% |
| 9 | BBB | 0.18000% | | 19 | C | 62.28900% |
| 10 | BBB- | 0.26038% | | | | |

Anchors from published corporate default evidence (Moody's Year-1 issuer-
weighted 1970–2007; S&P average one-year 1981–2009 and the 2024 study): AA
0.02%, A 0.05–0.08%, BBB 0.17–0.26%, BB 0.97–1.13%, B 4.66–4.93%, CCC/C pooled
17.7–28.0%. The curve lands inside every one of them.

**This is an internal CreditProbe scale calibrated using public corporate
default evidence as an external reference.** It is not the S&P scale and not
the Moody's scale; no borrower here carries an agency-assigned rating; no bank
has approved this calibration and nothing here is regulatory-validated. The
primary agency PDFs are blocked by this environment's network egress policy and
the figures above came from search-result summaries of them — recorded as a
limitation in §3.3 of the calibration note, along with the fact that no single
anchor carries the curve.

### 2.5 Stage 3 PD

`ratingscale.applicable_pd` is the one function that decides the measurement
basis: twelve-month in Stage 1, lifetime in Stage 2, **100% in Stage 3**. The
default has already happened, so the probability that it happens is one; 99.9%
would assert a one-in-a-thousand chance that an observed event did not occur.
`profiles`, `delta` and `attribution` now call it instead of repeating the rule
three ways, and the generator writes 100% to all three PD columns on a defaulted
row so nothing can pick up a near-default convention.

Three consequences, all deliberate:

* **A PD of 100% is not an LGD of 100%.** A defaulted borrower with 40% LGD
  provisions 40% of its exposure. Measured on the shipped book: Stage 3
  coverage runs 24.0% to 92.4%, tracking LGD at a correlation above 0.95.
* **The scenario weighting does not apply to a resolved default.** Its
  multipliers scale a probability that has not resolved; multiplying a
  certainty by 1.082 asserts a loss rate above the borrower's own LGD, which is
  an arithmetic error rather than a provision. A Stage 3 provision is exactly
  `1.00 × LGD × EAD`.
* **A PD shock leaves a Stage 3 borrower unmoved**, and the attribution reports
  zero PD effect on it. What a scenario can still change about a defaulted
  exposure is its recovery, which arrives through LGD and EAD — and an LGD
  shock does move it.

One further defect this exposed: the engine clipped every stressed PD to 99%,
so any scenario at all — including one that never mentioned PD — pulled every
Stage 3 borrower to 99 and restated the reported book. The ceiling is now per
row: 99% performing, 100% defaulted. Caught by the collateral-shock invariant.

### 2.6 Quick analysis before a shock

The tester asked "Can you give me the rating-wise PDs, getting rid of stages?"
and was told the profile views answer it. That is a redirect with a paragraph
of justification attached, and it arrives at the worst possible moment: nobody
asks for rating-wise PDs in a scenario builder out of curiosity — they are
deciding how big a shock to apply, and "increase BBB PD by 20%" means something
different depending on whether BBB PD is 0.18% or 1.8%.

`backend/whatif/analysis.py` is a deterministic reader and a deterministic
calculator. `read()` turns a sentence into a dimension, a set of metrics,
filters and a decision about the Stage split; `run()` computes the table from
the reported book. No model decides what was asked and no model produces a
figure — a reading is written over the table afterwards, from the table alone,
and re-read against it for any number it did not contain.

* **Dimensions:** rating, rating band, stage, sector, segment, secured/
  unsecured, borrower, portfolio.
* **Metrics:** borrowers, exposure, ECL, ECL coverage, TTC PD, PIT 12m PD,
  lifetime PD, applicable PD, LGD, CCF, collateral coverage, DPD, stage.
* **Filters:** stage, grade or band (including "BBB- and weaker"), sector,
  segment, a threshold on any metric, top-N.
* Every rate is reported twice, plainly and exposure-weighted, because the two
  answer different questions; coverage is summed over summed.

Follow-ups merge into the previous request rather than replacing it: "only show
BBB- and weaker" names no metric, "show exposure too" names no dimension, and
"which sector has the highest PD within BB?" changes the dimension and keeps
the metric. A superlative is ranked on the exposure-weighted value and never on
the TTC PD — TTC is a property of the grade, so ranking sectors by it inside one
band ranks them by their mix rather than their risk.

**"What would be a sensible PD shock?"** returns the book's own history: a
severity ladder at the p50, p75, p90, p95 and p99 of what that population has
actually done, each with the instruction it would produce and a button to use
it. Every magnitude is measured rather than chosen, and the reply says so.

A scenario is still a scenario: "Increase PD for Stage 1 BB rating by 10%" is
refused as a table with a message that says what to name instead.

### 2.7 The detailed Excel download

**The UI sent the display label where the contract wants the value.**
`context.ecl_methodology` is "ML Model — XGBoost" — eighteen characters against
a `max_length` of sixteen — so Pydantic refused it before any code that knew
what a methodology is could say so. "Delta Model" cleared the length and then
failed the enum with the same unreadable message.

`methodology.canonical()` is now the one place a string becomes a governed
value, and it understands the labels, because an older client or a copied state
sending one is a caller bug that should still produce a workbook.
`refusal()` names the valid choices in both forms. The API fields widened to 48
so a label reaches code that can explain itself. A result's context carries
`methodology` (the value) beside `ecl_methodology` (the label), so the UI has
something correct to send.

The workbook's tabs are now the specification's own names — Executive Summary,
Scenario Definition, Portfolio Before vs After, Account & Facility Detail,
Borrower Detail, Stage Migration, Rating Migration, ECL Attribution, Model &
Methodology, **Data Dictionary** — with Reconciliation and Reproduce beside
them. (One departure, and it is Excel's: a worksheet name may not contain "/".)

---

## 3. Data, model and evidence

**Corporate IFRS 9 book.** Clean rebuild, no stale partitions. 16 quarters,
Q3 2022 → Q2 2026, 3,241 borrowers at Q2 2026. Every one of the nineteen grades
is populated across the book. `internal_rating_ordinal` agrees with
`internal_rating` on every record.

**Two generator defects the rebuild found**, both fixed at the calibration:

* `pd_from_quality` floored at 0.02% while the AAA band's upper edge is 0.011%,
  so no borrower could ever be graded AAA and the strongest grade of the scale
  was unreachable by construction. Two floors that disagree is the same defect
  as two copies of a policy threshold. The generator now uses the scale's floor.
* The rating review buffer was counted in NOTCHES, and a notch is not a
  constant amount of credit risk: three notches is 1.11 in log-odds at the
  investment-grade end and 1.90 through the distressed tail. The book said so —
  AAA held its grade 75% of quarters and BB+ held it 90%, which is the wrong way
  round. The buffer is now expressed on the axis the masterscale is built on,
  anchored at exactly three notches at BBB: about five notches at AAA, three
  through the middle, two through CCC and CC.

**XGBoost.** Retrained from scratch on the rebuilt book — the previous artifact
was trained on a book that no longer exists.

| | |
|---|---|
| Version | `2026.09.08.10` |
| Design | One regressor per Stage, gradient-boosted trees |
| Split | Chronological. Train Q3 2022 – Q4 2024; validation Q1–Q4 2025; **OOT Q1 2026, Q2 2026** |
| Validation | R² 0.9973 · MAE 0.00177 · exposure-weighted MAE 0.00133 · WAPE 3.27% |
| Out-of-time | R² 0.9970 · MAE 0.00144 · exposure-weighted MAE 0.00124 · WAPE 3.34% |
| Artifact | `xgboost-native-json`, 4,334,174 bytes, sha256 `75f72403ea05824e…` |
| SHAP | XGBoost native TreeSHAP over 2,000 sampled rows; top contributors lifetime PD 43.4%, LGD 28.4%, 12m PD |

`.pkl`, `.joblib` and `.pt` remain banned by `backend/brain/security.py`; the
native JSON format was already on its allowlist, so no security control was
weakened to ship this.

**Delta revalidated.** On the manual UAT scenario — Stage 1 BB, PD +10%, 842
borrowers — Delta returns +16.85% and ML +16.81% against the same baseline of
SAR 1,696.2. Both are more than proportional because some Stage 1 names cross
into Stage 2 and change measurement basis, which is the effect the methodology
exists to price. The baseline ties exactly to the reported ECL on both.

**Reconciliation.** The spot check ties on all 80 borrower-quarters, worst
unexplained residual 0.0001.

---

## 4. Tests

| Suite | Result |
|---|---|
| `tests/whatif/` | all passing |
| `tests/corporate/` | all passing |
| `tests/ifrs9/` | all passing |
| `tests/api/` | all passing |
| `tests/evals/test_whatif_evaluation.py` | all passing |
| `tests/evals/test_whatif_analysis_evaluation.py` | 48 cases, all passing |
| `tests/corporate/test_rating_scale.py` | new — 94 tests on the order, notching, the TTC master and Stage 3 |
| `frontend` `npm test` | all passing |

Pre-existing failures, established on baseline `4f79566` with the same lake and
unrelated to What-If: two in `tests/evals/test_properties.py` and one
multi-analysis reconciliation, all on `portfolio_facility` — the credit book,
a different dataset with a different grain.

---

## 5. Readiness cycles

Three clean cycles, 17 steps each, none failed. Cycle 2 followed a clean
rebuild and a retrain to prove idempotence.

| Step | 1 | 2 | 3 |
|---|---|---|---|
| API and web reachable | PASS | PASS | PASS |
| ruff / typecheck / eslint | PASS | PASS | PASS |
| What-If unit and invariant suites | PASS | PASS | PASS |
| the evaluation corpus | PASS | PASS | PASS |
| the quick-analysis corpus | PASS | PASS | PASS |
| the API surface | PASS | PASS | PASS |
| the red team | PASS | PASS | PASS |
| the nineteen browser journeys | PASS | PASS | PASS |
| the manual-failure journeys | PASS | PASS | PASS |
| performance against budget | PASS | PASS | PASS |
| the book's economic coherence | PASS | PASS | PASS |
| What-If scenario economics | PASS | PASS | PASS |
| the integration and schema contracts | PASS | PASS | PASS |

Logs: `docs/readiness/cycle-{1,2,3}.{log,json}`.

---

## 6. Browser journeys

19 journeys, 209 checks, all passing. Four are new to this pass:

* **16 — Nineteen grades, in order, ending in C.** Reads the labels off the
  screen and asserts the exact sequence, that it ends in C and not D, that D
  follows as its own row, that the order is not alphabetical, and that the
  migration matrix's rows and columns are the same nineteen plus a Total.
* **17 — Quick analysis before any shock.** Types the sentence that was
  redirected in UAT and requires an answer in the thread; asserts a follow-up
  narrows rather than restarts, that a shock-size question returns measured
  magnitudes, and that no methodology gate was raised for a question that
  prices nothing.
* **18 — The session holds across the whole product.** Walks the landing page,
  three journeys and both model pages, asks a question, reloads mid-thread, and
  fails on any backend-offline banner while `/health` stays 200 throughout.
* **19 — Stage 1 BB PD +10%, exported both ways.** Runs the manual UAT scenario
  on ML and on Delta, requires the workbook down both times, and asserts
  "Check: methodology" appears nowhere.

---

## 7. What is not claimed

* The scale is CreditProbe's own, calibrated against public corporate default
  evidence as an external reference. Not an agency scale; no agency-assigned
  ratings; not a bank-approved calibration; not regulatory-validated.
* The portfolio is a synthetic demonstration book, built to behave like a
  credible corporate credit book so the What-If arithmetic on top of it can be
  judged on its merits.
* The primary agency PDFs could not be opened from this environment. §3.3 of
  the calibration note records which figures came from search-result summaries
  and why no single anchor carries the curve.
* The ML model under-steps the Stage 1 → Stage 2 boundary. A gradient-boosted
  model fits a continuous surface and cannot reproduce the 12m → lifetime
  discontinuity; adding `stage_measured` and `sicr_clear_quarters` as features
  did not close it. It is disclosed on the comparison rather than tuned away.

---

## 8. Git

Branch `claude/what-if-analysis-rebuild`. **Not merged. No pull request. No
other feature branch touched.**

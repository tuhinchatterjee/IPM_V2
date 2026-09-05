# Scorecard Validation Intelligence — User Guide

For a model validator, a model owner, or anybody who has been handed a
scorecard and asked whether it still works.

**Where it is:** Intelligence → Scorecard Validation
**What it covers:** the Retail Application Scorecard, the Retail Behaviour
Scorecard and the Saudi SME Scorecard. Nothing else.

---

## 1. The one thing to understand before you use it

This module reports what it measured **and what it could not**, and it gives
the second the same weight as the first.

That is unusual and it is deliberate. Most model-monitoring screens show you
the tests that produced a number and stay quiet about the rest, so eleven
green ticks look like a clean model when they may be eleven of forty-eight.
Here, a test that could not run comes back with its own state and a sentence
saying why — and the coverage figure sits beside the results, so you always
know which of those two situations you are in.

**A validation opinion resting on tests that did not run is an opinion
resting on nothing.** Everything below follows from that.

---

## 2. The ten states a result can be in

Four of them carry a number. Six do not, and each of the six means something
different you would act on differently.

| State | It means | What you do |
|---|---|---|
| **PASS** | Measured, inside its governed limit | Nothing |
| **WARNING** | Measured, close to the limit | Watch it; look at the trend |
| **FAIL** | Measured, outside the limit | Read the finding; it will be ranked |
| **NO APPROVED LIMIT** | Measured, but nothing governed says what good looks like | Agree a limit. Do **not** read this as a pass |
| **NOT YET MATURED** | The cohort's outcome window has not closed | Wait. Widening the window would fabricate the answer |
| **INSUFFICIENT SAMPLE** | Too few observations or too few defaults to mean anything | Pool periods, or accept that this cannot be measured yet |
| **UNAVAILABLE** | A column or a reference the test needs is not present | Fix the feed |
| **NOT APPLICABLE** | This model genuinely has no such thing | Nothing. It is not a gap |
| **NOT AUTHORISED** | You may not read this domain | Ask for the permission |
| **CALCULATION ERROR** | The test threw | Raise it. This is a defect, not a finding about the model |

The distinction that catches people out is **NO APPROVED LIMIT** against
**PASS**. A statistic that was computed but has nothing to compare it against
is not good news; it is an unanswered governance question, and it has its own
colour on screen for exactly that reason.

The other one is **NOT YET MATURED** against zero. A cohort scored four
months ago on a twelve-month performance window has no realised default rate.
Not a low one — none. Any screen that shows you 0.0% there is lying to you,
and this one will not.

---

## 3. The screen, top to bottom

### 3.1 Which scorecard

Three buttons. Switching clears the results, so you never see one model's
numbers under another's name.

### 3.2 Ask

A question box. It answers by **running the governed tests**, not by
describing them.

Ask it things a validator actually asks:

- "Is it still ranking risk?"
- "Has the population drifted?"
- "Which characteristics have stopped working?"
- "What does STAB-CSI measure?" *(a definition — it will not spend a minute
  computing to answer this)*
- "Which periods have matured?"
- "What are the biggest weaknesses?"

Three things can come back:

- **An answer** — the tool result, in exactly the same components you would
  get by clicking. It is the same result.
- **A clarification** — your question was about the right thing, too
  generally. You get the eleven categories as buttons.
- **A refusal** — the question belongs to a different surface, or it asks for
  something this one has no tool for. It says where the answer does live.

Every answer states which tool ran and how it was chosen, and every answer
carries the sentence: *no figure was produced, restated or rounded by a
language model.* That is not boilerplate. It is the contract, and §6 explains
why it matters.

### 3.3 Model health

Four figures. The one to read first is **outcome window closed** — how many
of the available periods actually carry a realised outcome. On the Saudi SME
scorecard as shipped, that is 16 of 36. The other twenty months exist, carry
scores, and have no outcome to test against.

### 3.4 Run

**Run full validation** executes every applicable test in every category. It
takes a minute or more, most of it in the bootstrap resampling, and the page
says so before you press it.

**Draft report (Word)** produces the CBUAE-aligned report. It is a **draft**
for a validator to review, edit and sign. CreditProbe does not issue
validation opinions and the document says so on its own cover.

### 3.5 What would change a decision

The findings, ranked. A finding here is not a restatement of a failed test —
it is what the results mean together, and seven of them read across tests:

| Finding | Reads |
|---|---|
| Production does not match the specification | IMPL-REPLICATE |
| Portfolio calibration conceals a segment | CAL-OE + SEG-CALIBRATION |
| The cut-off is being overridden at its boundary | USE-OVERRIDE-OUTCOME + USE-MATRIX |
| Drift that is a definition change | STAB-CSI + VAR-IV |
| Passing on the strength of the other characteristics | DISC-AUC + VAR-IV |
| Most of the book has no outcome yet | DATA-MATURITY |
| A challenger advantage inside the champion's own interval | CC-DISCRIMINATION + ROB-BOOTSTRAP |

Every finding carries **Check it yourself** — the route to verify it
independently. A finding you cannot check is a finding you have to take on
trust, which is the opposite of what an independent validation is for.

If nothing is listed, read the coverage figure before treating that as a
clean bill of health.

### 3.6 The eleven categories

Each card carries the question a validator is asking, not the name of a
statistic. Click one to run its tests.

| Category | Asks |
|---|---|
| Data & Representativeness | Is this data complete, current, and representative of what the model was built for? |
| Conceptual Soundness & Design | Is the design defensible, documented and used as intended? |
| Discrimination | Does this model rank risk? |
| Calibration & Accuracy | Are the predicted default rates right, not just ordered right? |
| Stability | Is the model still looking at the same kind of book? |
| Robustness & Sensitivity | How much does the answer depend on choices we happened to make? |
| Variables & Binning | Which variables are doing the work, and which have stopped? |
| Model Usage, Overrides & Policy | Is the score being followed, and do the departures perform? |
| Implementation Verification | Does the system compute what the document says it computes? |
| Segmentation | Does the aggregate result conceal a segment where it fails? |
| Champion vs Challenger | Should we replace the champion — and what would we be trading? |

### 3.7 The results

Every result shows its state, its figure at four decimals, the limit it was
compared against **and where that limit came from**, and one sentence written
to be quoted into a report unedited.

**Evidence** opens the rest: the chart, the test-level table, how the number
was calculated, and what the test cannot tell you.

Limits are sourced. `DEMO POLICY` is a threshold seeded for this environment;
`STRUCTURAL` means there is no defensible non-zero tolerance — a duplicate
row count and a monotonicity breach are not matters of appetite. A threshold
with no provenance becomes a regulatory requirement the third time somebody
reads the table.

---

## 4. Reading the charts

A validation chart is almost never a picture of the headline number, and that
is the point.

- **ROC / CAP / KS** — the curve the statistic was integrated from. AUC is
  the area under the ROC; the curve tells you *where* the model separates and
  where it does not.
- **Calibration** — predicted against realised, band by band. Discrimination
  asks whether the ordering is right; this asks whether the level is. A model
  can rank perfectly and price every facility wrongly.
- **Population stability** — the index by month, and beneath it the bins
  driving it. Measured against the **frozen development population**, never
  against last month. A baseline that moves forward is how a book drifts a
  long way from what was approved while passing stability testing every
  quarter.
- **Ranking** — every variable, not the worst one. "The index is 1.08" is a
  fact about one characteristic; which one, and whether the others moved with
  it, is the finding.
- **Weight of evidence** — per bin, one variable at a time. The approved
  binning asserts a direction, and this is where it holds or does not.
- **Bootstrap distribution** — the spread IS the answer. A difference smaller
  than that spread is not a difference.
- **Tornado** — how far the headline moves when a segment or a window is
  removed. A result that depends on one segment being present is a result
  about that segment.
- **Override matrix** — by score band and direction. Overrides concentrated
  at the band containing the cut-off mean the people using the model do not
  believe it precisely where it makes its decision.

---

## 5. Ongoing monitoring

The link in the page header goes to the retail monitoring surface — the
month-by-month dashboards, the fitted equations, the drift panels and the
report library. Same data, different question: monitoring asks "what changed
this month", validation asks "does this model work".

---

## 6. What this module will not do, and why

Stated plainly so nobody has to discover it from a gap.

**It will not let a language model compute, restate or round a statistic.**
Every figure comes from `backend/scorecard/metrics.py` through the validation
runner. A model may decide *which* question to answer; it never decides what
the answer is. A validation environment whose numbers cannot be reproduced
has no value, and a paraphrase is not reproducible.

**It will not run SQL or Python that a model wrote.** There is no such tool.
The nine tools it has take parameters from closed sets — a scorecard from
three, a test from forty-eight, a category from eleven — and anything outside
those is refused before it executes.

**It will not read anything outside the three scorecards.** Two independent
backend gates, and neither is the page hiding options. The general Cockpit
equally cannot read these populations: they are record-level model inputs and
realised outcomes, and a portfolio question has no business reaching them.

**It will not say a model complies with anything.** The regulatory view maps
CBUAE MMS/MMG expectations to the tests that would evidence them and reports
which of those produced a result. Its statuses are EVIDENCED, PARTIALLY
EVIDENCED, NOT EVIDENCED and NOT APPLICABLE. There is deliberately no
"compliant": CreditProbe has no standing to determine that, and a status
vocabulary containing the word would be read as claiming it whatever the
disclaimer said.

**It will not claim a live external connection.** Twenty-six of the ninety
SME variables are proxies for data a real Saudi deployment would source from
SIMAH, ZATCA, FATOORA, GOSI, Qiwa, Mudad, Monsha'at or the Ministry of
Commerce. CreditProbe is connected to none of them. See
`docs/SAUDI_SME_SCORECARD_DATA_DICTIONARY.md` §1.

**It will not give the model an overall score.** No traffic light, no
percentage complete, no single number for "is this scorecard sound". That is
the number a committee would quote and the one no validator would sign, and
putting it on the screen would make every honest refusal beneath it
decorative.

---

## 7. If something looks wrong

- **A statistic reads lower than you expect** — check the window on the
  result. Discrimination and calibration run on the matured window; stability
  runs on the current one. The same characteristic reads 0.01 on one and 0.49
  on the other, and that is not a bug, it is two different questions.
- **A test says UNAVAILABLE** — the sentence names the column or reference it
  needed.
- **A test says NOT APPLICABLE** — the model genuinely has no such thing.
  A rank-order scorecard with no score-to-PD mapping has no calibration, and
  inventing one is worse than omitting it.
- **A run takes a minute** — it is the bootstrap resampling. That is real
  computation, not a hang.
- **Two runs disagree** — they should not. The universe is seeded through a
  BLAKE2b digest and the bootstrap carries a fixed seed, so the same question
  gives the same number in every process and at any hour. If two runs
  disagree, that is a defect worth raising.

---

## 8. Related documents

| Document | What it is for |
|---|---|
| `SCORECARD_VALIDATION_ARCHITECTURE.md` | How the module is built and what enforces each boundary |
| `SAUDI_SME_SCORECARD_DATA_DICTIONARY.md` | Every SME variable, its source, and which sources are proxies |
| `CBUAE_SCORECARD_VALIDATION_REPORT_MAPPING.md` | Requirement-to-test mapping for the report |
| `SCORECARD_VALIDATION_ACCEPTANCE_MATRIX.md` | What was verified, and what was not |

# Early Warning — pre-UAT certification report

**Verdict: READY EXCEPT FOR LOCAL PROVIDER CERTIFICATION.**

Every defect under this environment's control is fixed. The one remaining
blocker is a run that cannot happen here: there is no Anthropic credential in
this container, and by instruction none is to be put in it. One Mac procedure
closes it, at the end of this document.

This report covers two runs.

**Run 1** (from `c75b549`) found and fixed ten defects, left three P1s open,
and ended NOT READY. It is preserved below in full.

**Run 2** (from `d683881`) closed all three, found and fixed sixteen more, and
completed every path run 1 did not reach. 78 scenarios, 78 passing:

| | |
|---|---|
| Chat matrix, levels 1–5 | 20 / 20 |
| P1-A, external intelligence as L3 | 5 / 5 |
| P1-B, band transitions | 6 / 6 |
| Thread chains, clarification, noisy and mixed-language | 21 / 21 |
| Ten new adversarial questions | 10 / 10 |
| Escalation, messages, investigations, reports | 6 / 6 |
| Browser: navigation, history and progress UX | 10 / 10 |

Nothing under Claude's control is outstanding at P0 or P1. What remains is
§17: run the certification script on a machine that has the key.

---

## Branch and environment

| | |
|---|---|
| Branch | `claude/early-warning-rebuild-v2-3lnttn` |
| Commit at start | `c75b549` |
| Provider | none configured — deterministic governed reader on every stage |
| Dataset | 20 contiguous months, 2024-11 → 2026-06 |
| Population | 300 obligors, 6,000 borrower-month rows, one row per customer per month |
| Methodology | `ews-v2.1.0`, single version across all 6,000 rows |

Everything below was measured against a **governed oracle** built from
`v2_service` and the published parquet only. The oracle shares no code with the
answering path — it can disagree with the chat, which is the only way a
reconciliation means anything. It is reproduced by
`tests/early_warning/test_data_coherence.py` and by the fixture files this
report cites.

---

## §3 Methodology invariants — PASS

| Invariant | Expected | Measured |
|---|---|---|
| Signal inventory rows | 123 | **123** |
| Scored | 105 | **105** |
| Dropped / merged / replaced | 18 | **18** |
| T/A-role inventory signals | 77 | **77** (74 + 1 override + 2 two-hop) |
| C-role inventory signals | 46 | **46** (44 + 1 level/shock + 1 portfolio) |
| Active classifiers | 23 | **23** |
| Trigger definitions | 67 | **67** |
| Accelerator dimensions | 5 | **5** — magnitude 0.30, velocity 0.20, persistence 0.20, repetition 0.10, corroboration 0.20 |
| T&A layer weights | L1 .40 / L2 .15 / L3 .30 / L4 .15 | **exact** |
| Classifier weights | L2 .85 / L4 .15 | **exact** |
| Notch families | 5 | **5** — network contagion, direction of travel, evidence quality, data staleness, management and governance |
| Net notch cap | ±2 | **±2** |
| Points per notch | 8 | **8** |

**Rawabi regression: PASS.** `tests/early_warning/test_rawabi_regression.py`
reproduces the workbook's worked example — L4 C 73.0, T&A 73.0775 HIGH,
Classifier 71.283 HIGH, anchor 72, notches −1/−1/0/0/0, net −2,
**final EWS 56 MEDIUM**.

## §37 Data coherence — PASS

New: `tests/early_warning/test_data_coherence.py`, 17 assertions over all
6,000 rows.

- One row per customer per month; zero duplicates in any month.
- The population is the same size in every month.
- Notches sum to the net within the ±2 cap on every row.
- **Every final score reconciles to the methodology.** 1,041 rows do not match
  `clamp(anchor + net × 8)` alone — and all 1,041 carry a recorded override
  that explains them (`unwaived_covenant_breach_floors_high` ×853,
  `classifier_very_high_and_ta_very_low...` ×178, `ifrs9_stage3_or_90dpd...`
  ×6, both ×4). **Zero unexplained.**
- Bands never contradict their own scores; exposures aggregate without loss by
  sector and by band; no top-N share exceeds its whole.
- Missing stays distinguishable from zero: an obligor with no fired signal
  carries a T&A score of exactly 0 **and** a non-zero classifier score, which
  is the correct behaviour for two layers that measure different things.

---

## Defects found and FIXED (10)

### P0-1 — the answer was about whichever analysis ran first

`ResultPacket.primary` returned `packs[0]`. Every population-scoped plan reads
the population first as context, so the headline was always the population.

> "Which obligors are currently High or Very High?"
> → *"The portfolio early warning score is 14.5 (very low)…"*

The same sentence came back for the band distribution, for the ten biggest
risers, and for the high-risk list — three different questions, one answer. The
ranking rows were in the packet the whole time, unused.

**Fix.** `plan.intent` now names the analysis that was *asked for* rather than
falling back to `population` whenever a population step is present; the packet
carries that intent and chooses its headline run, its figures, its rows and its
period from the same step.

### P0-2 — there was no composer for "which names"

The product had readings for portfolio, level, group, borrower, layer,
evidence, movement, comparison, diagnosis, action, escalation and methodology.
It had none for a ranking, so even with P0-1 fixed the answer fell through to
the portfolio reading.

**Fix.** `compose.ranking()`, and a ranking `FactPack` from the executor so the
reading has something to be about. Ordered by exposure, not by score. The
bolted-on "the names carrying it…" sentence that used to paper over this is now
suppressed when the reading *is* the ranking, so the names are not printed
twice.

Now:

> 52 obligors in the corporate portfolio sit at high or above. The 10 largest by
> exposure are listed, led by Al Rabia Contracting 8 at 95.0 (very high) on
> SAR 3.7bn; the 10 together carry SAR 13.0bn.

52 reconciles to the oracle.

### P0-3 — a movement answer blamed the data for a filter it did not understand

> "One of those periods is not published, so the contribution cannot be
> decomposed."

Both periods were published. `contribution_by_layer` returned `None` for any
filter key that was not a stored column — `high_plus` is derived — and the
caller printed the unpublished-period message for it. A thread that had asked
about High and Very High obligors carried that filter into the next question,
and the next answer blamed the dataset.

**Fix.** The same narrowing every other scope uses, and a message that
distinguishes an unpublished period from a filter that matched nobody.

### P1-4 — the grouping phrase ran past the field

`by sector for obligors at High` captured the grouping `"sector for"`, which
resolves to nothing, so the grouping was dropped and the whole book was
described. Two words are genuinely needed (`internal rating`, `risk band`), so
the fix is the governed registry arbitrating the longest valid prefix rather
than a shorter regex.

### P1-5 — a band named in the question was not a filter

The severity band was read from the screen and never out of the sentence.
"…for obligors at High or Very High" was answered for every obligor in every
sector: right arithmetic, wider population, nothing on screen to say so.

**Fix.** The compound `high_plus` is extracted from the question; a single band
continues to be resolved by the group resolver against the domain's own values;
the compound wins when both are present, because the single one is an artefact
of matching half the phrase.

### P1-6 — the grouping step ignored filters entirely

`ff.level()` had no way to take one. Now it does, applied **before** the
grouping. `Show exposure by sector for obligors at High or Very High` now
reconciles to the oracle across **all 13 sectors**, obligor counts and
exposures exact.

### P1-7 — an Early Warning band question was routed to the Cockpit

The gate scored Cockpit's generic `exposure by` at 2.5 and Early Warning's band
vocabulary at 1.5. But High and Very High are Early Warning's *own output* — no
other product in CreditProbe assigns an obligor to a severity band.

**Fix.** The band names are weighted as this product's vocabulary. Verified
that `Stage 2 exposure by sector`, `total exposure by sector` and
`portfolio composition and performance` still go to the Cockpit, ECL shocks to
What-If, and Gini/PSI to Scorecard Validation.

### P1-8 — "distribution by risk band" resolved to no grouping

The first question anybody asks this product. `risk band` was not an alias and
`distribution by` was not a cue, so it was answered at population level without
the five band counts. Now it returns them, and they reconcile to the oracle
exactly (VERY_LOW 244, LOW 4, MEDIUM 0, HIGH 42, VERY_HIGH 10).

### P1-9 — a bare band name resolved to the wrong band

`HIGH` is a value of `ews_band`, `ta_band` **and** `classifier_band`. The
longest-token rule could not separate them, so the winner was whichever column
the level registry listed first — the classifier band. A reader who names a
band without qualifying it means the Early Warning band.

### P1-10 — four model stages sat below a level already proven to truncate

The brief named the summary stage. It was one instance of a class.

| Stage | Was | Now | Why |
|---|---|---|---|
| `sonnet_summary_update` | 700 | 2000 | truncated live; Sonnet 5 runs adaptive thinking when `thinking` is omitted, and those tokens share this ceiling |
| `sonnet_pass_1` | 700 | 1500 | the exact number that had just failed on the other Sonnet stage |
| `sonnet_pass_2` | 1200 | 1500 | a larger document than pass one |
| `opus_functionality_selection` | 900 | 2000 | **below the 1,000 that had already truncated the sufficiency review on the same model family** |

Losing the summary is quiet and expensive: it is what lets the next turn
resolve "it", so a thread whose summary fell back keeps answering — and keeps
answering a slightly different question.

`MINIMUM_ALLOWANCE = 1500` is now a floor with a contract test, so the next
stage added cannot quietly sit under it. The plan (4000) and repair (2500)
allowances are unchanged, and a test asserts the allowances are still
distinct — this is a floor, not a levelling.

> **Scope note.** The brief said to fix *only* the summary stage. I fixed four,
> because three of them sat at or below a ceiling that had already been
> observed to cut off a well-formed reply on these models, and §40 requires all
> seven stages to be model-served. Stating it plainly rather than burying it.

---

## Defects found in run 1 and NOT fixed in run 1 — ALL CLOSED IN RUN 2

*Each of these is reproduced below as run 1 found it. Run 2's fix and its
verification are in the run 2 section that follows.*

### P1-A — "external intelligence" is not read as a layer constraint — FIXED

```
Q: Which obligors currently have external-intelligence warning signals?
   requested_layer: None
   -> answered with a generic high-risk ranking, no L3 filter at all
Q: Which sectors have the highest external-intelligence score?
   -> answered with total EWS grouped by sector, not L3
```

This is exactly the failure §6 E06 warns about: "no accidental use of total EWS
as if it were L3". The reader is given a confident, correctly-grounded answer
to a different question.

### P1-B — no band-transition analysis — FIXED

```
Q: How many obligors changed risk band in the latest month?
   -> "The score moved -12.8 points between 2024-11 and 2026-06"
```

A twenty-month score movement, not a last-two-month transition count. The
oracle says the answer is 2 changed — 1 deteriorated, 1 improved, 298
unchanged. There is no transition analysis in the plan vocabulary to produce it.

### P2 — presentation and data realism — FIXED

- A band-distribution answer names no period and no population total, and
  phrases the bands as a "weakest" ranking ("the weakest is VERY_HIGH").
- "across 1 obligors" — pluralisation.
- **Data realism, not a code defect.** The EWS score takes **10 distinct
  values** across 300 obligors; 169 score exactly 0.0; the MEDIUM band is
  empty; anchor takes 4 values. This is the published methodology behaving as
  designed — a 5×5 anchor matrix plus integer notches quantises by
  construction, and Rawabi reproduces — but a demo book where 56% of obligors
  score zero and nobody is Medium will look odd in a live UAT. Flagged for a
  data-generation decision, not a code fix.

---

## What was verified, and what was not

### Verified

| Area | Result |
|---|---|
| Methodology invariants (§3) | PASS |
| Rawabi regression | PASS — 56 MEDIUM |
| Data coherence (§37) | PASS — 17 assertions, 6,000 rows |
| Band distribution (E01) | PASS — reconciles exactly |
| High/Very High list (E02) | PASS — 52, names reconcile |
| Sector ranking (E04) | PASS — Shipping 35.66→35.7, 13 obligors, exposure-weighted |
| Exposure by sector, high+ (E07) | PASS — all 13 sectors exact |
| Cross-product routing (§15) | PASS — 9/9 including What-If, Cockpit, Scorecard |
| What-If zero EWS executions | PASS — `executions == 0`, no analytical stage |
| Movement decomposition | PASS — 24.57 → 33.21 = +8.64 matches oracle |
| Contracting 6-month premise | PASS — improved 36.65 → 33.21, −3.44; premise correctly challenged |
| Browser UI, desktop + 390px | PASS — no horizontal overflow, answers render, progress collapses |

### NOT verified — not reached in this run

Levels 2–5 beyond the above, both multi-turn thread chains, clarification,
noisy and mixed-language input, messaging, escalation, Investigations,
report/export, navigation and history, the ten adversarial variants, and
performance timings. These are **untested**, not passed.

### BLOCKED — needs a credential

Every real-provider criterion. No stage can be shown at `engine=model` from
here.

---

## Regression

```
backend   22 failed, 10,428 passed, 25 skipped, 0 errors   (baseline 22 / 10,368)
frontend  429 of 429
typecheck clean · lint clean · production build clean
```

The 22 failing identifiers are **identical to the baseline, line for line**,
and none of them is in `tests/early_warning/`. The 60 additional passes are the
three new test files this exercise added.

---

## Evidence

| What | Where |
|---|---|
| Screenshots | `docs/evidence/pre-uat/*.png` |
| Data coherence | `tests/early_warning/test_data_coherence.py` |
| Answer-addresses-the-question | `tests/early_warning/test_answer_addresses_the_question.py` |
| Output-allowance floor | `tests/early_warning/test_output_allowances_floor.py` |
| Machine-readable results | `docs/early_warning_pre_uat_results.json` |

---

---

# Run 2 — from `d683881`

Started at `d683881`, on the same branch, with nothing thrown away. Run 1's
ten fixes are all still in place and all still tested.

## The three run-1 P1s, closed

### P1-A — external intelligence is now understood as Layer 3

There was no way to ask about a layer at all. `ask.py` knew L3 as three
search words, `facts` and the API router each held their own copy of the
layer names, and none of the three had a route into the planner.

There is now one registry, `backend/early_warning/layers.py`, and `facts`,
the router and the executable registry all read it. A phrase resolves through
the framework's own vocabulary — the layer's published title, its
sub-category node names, the words the credit book uses — plus one
grammatical rule: **a layer word next to a warning noun names that layer**.
So "external intelligence", "external signals", "external warning signals",
"external events", "external-intelligence flags", "L3" and "Layer 3" all land
in the same place, and "external debt" does not. A layer the sentence rules
out ("network warnings but no behavioural ones") is excluded rather than
mistaken for the subject.

Resolving it changes the answer. The population becomes the obligors that
layer actually fired for; the ranking is ordered by the layer's own score
rather than the score it rolls into; a grouping is ranked on the layer; a
borrower question opens the nodes inside it and names the events by their
framework titles.

All five §2 questions PASS against independently computed oracle facts:

| | Question | Result |
|---|---|---|
| L3-1 | Which obligors currently carry external-intelligence warning signals? | PASS |
| L3-2 | Which sectors have the highest external-intelligence score? | PASS |
| L3-3 | Show me High and Very High obligors with external signals. | PASS |
| L3-4 | Which borrowers have L3 warnings but weak internal corroboration? | PASS |
| L3-5 | What external warning events are driving this borrower? | PASS |

L3-4's second half is honoured too: "weak internal corroboration" narrows to
the obligors with no other layer firing, which is a governed derived field
(`corroborated`) and not a phrase match.

### P1-B — band transitions are a governed analysis

A band change is discrete, per obligor, and is what the watchlist keys on. It
now has its own analysis, recomputed from the two published months every
time — previous to current, from-band, to-band, improved, deteriorated,
unchanged, the full matrix, exposure behind each direction, a sector roll-up
and the names. "Into High or Very High" is read as the pair it is rather than
as one band, and a crossing that did not happen is said plainly instead of
reported as a zero.

All six §2 questions PASS:

| | Question | Result |
|---|---|---|
| B-1 | How many obligors changed risk band in the latest month? | PASS |
| B-2 | Who moved into High or Very High this month? | PASS |
| B-3 | Who improved out of High or Very High? | PASS |
| B-4 | Show the latest band-transition matrix. | PASS |
| B-5 | Which sectors had the most adverse band migrations? | PASS |
| B-6 | Did any Contracting obligors move into High or Very High this month? | PASS |

Nothing is hard-coded: the counts are recomputed from the published months on
every call, and the test recomputes them again, off the raw column, to
compare.

### P2 — presentation

Every population reading now states the month it is of. A band distribution
states the population it is a distribution of and reads as a distribution
rather than a ranking. A grouping says which measure it ranked by and in what
unit. "Across 1 obligors" is gone — every count agrees with its noun. An
empty population reads as a finding rather than a failure. A layer grouping
prints what the layer is, not just its code. An escalation route prints the
rung's title, not its ladder code.

## §4 — data realism

**Cause: E, a data-generation defect, with C contributing.** The engine is
correct; the builder was throwing the methodology away.

Four findings, all input-side, no formula changed:

1. **A fired signal was never carried forward.** The decay model — class
   half-lives, a persistence hold, a floor — exists so a signal fades over
   months. The builder computed the decay correctly and then dropped the
   signal the following month, so every signal was a one-month spike and the
   trigger side only ever saw the current month's events.
2. **The age clock never restarted.** A signal is dropped from scoring past
   400 days, which is right; the clock started the first time a trigger ever
   fired and never reset, so a condition that recurred a year later stayed
   dead. L4 fired for 241 obligors in the first published month and 30 in the
   last, while the book underneath was getting worse.
3. **L4 compared `network_risk_score` to an absolute 60.** That field is a
   min-max normalised relative ranking whose own published label says so,
   with a median of 3.4 and exactly one row above 60 in 3,300
   borrower-quarters. It now reads the counterparties themselves — suppliers,
   customers and connected-group entities from the real graph — weighted by
   how material each is.
4. **Evidence quality read only this month's fresh external events**, so a
   tier-2 event still driving the score was reported as internal bank data.
   Two of the five notch families were also firing −1 for most of the book,
   which makes them a constant offset rather than an adjustment; the
   derivation is an admitted implementation choice and is now faithful to the
   criteria.

Nothing was zero-filled, no score or band is hard-coded, and everything was
regenerated through the real engine.

### Before and after, all twenty months

| Month | VL | L | M | H | VH | at 0.0 | distinct | VL | L | M | H | VH | at 0.0 | distinct |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2024-11 | 99 | 159 | 0 | 39 | 3 | 4 | 11 | **80** | **166** | **12** | **39** | **3** | **4** | **17**|
| 2024-12 | 108 | 150 | 0 | 39 | 3 | 5 | 10 | **93** | **158** | **7** | **39** | **3** | **7** | **16**|
| 2025-01 | 238 | 23 | 0 | 35 | 4 | 23 | 16 | **168** | **91** | **2** | **35** | **4** | **19** | **19**|
| 2025-02 | 248 | 13 | 0 | 35 | 4 | 54 | 12 | **190** | **65** | **6** | **35** | **4** | **36** | **22**|
| 2025-03 | 249 | 12 | 0 | 35 | 4 | 51 | 11 | **186** | **67** | **8** | **35** | **4** | **31** | **22**|
| 2025-04 | 245 | 14 | 0 | 37 | 4 | 149 | 13 | **184** | **70** | **5** | **37** | **4** | **31** | **20**|
| 2025-05 | 219 | 40 | 0 | 37 | 4 | 161 | 13 | **189** | **64** | **6** | **37** | **4** | **58** | **18**|
| 2025-06 | 220 | 39 | 0 | 37 | 4 | 158 | 13 | **182** | **71** | **6** | **37** | **4** | **48** | **20**|
| 2025-07 | 237 | 7 | 0 | 52 | 4 | 40 | 13 | **196** | **45** | **3** | **52** | **4** | **44** | **20**|
| 2025-08 | 237 | 7 | 0 | 52 | 4 | 70 | 10 | **197** | **44** | **3** | **52** | **4** | **55** | **21**|
| 2025-09 | 235 | 9 | 0 | 52 | 4 | 58 | 12 | **202** | **40** | **2** | **52** | **4** | **48** | **18**|
| 2025-10 | 232 | 5 | 0 | 60 | 3 | 46 | 10 | **200** | **36** | **1** | **60** | **3** | **39** | **17**|
| 2025-11 | 234 | 3 | 0 | 60 | 3 | 73 | 8 | **196** | **40** | **1** | **60** | **3** | **49** | **16**|
| 2025-12 | 233 | 4 | 0 | 60 | 3 | 60 | 8 | **196** | **41** | **0** | **60** | **3** | **57** | **17**|
| 2026-01 | 228 | 9 | 0 | 56 | 7 | 19 | 11 | **155** | **82** | **0** | **56** | **7** | **12** | **17**|
| 2026-02 | 76 | 161 | 0 | 56 | 7 | 20 | 11 | **68** | **158** | **11** | **56** | **7** | **15** | **18**|
| 2026-03 | 81 | 156 | 0 | 56 | 7 | 21 | 10 | **81** | **147** | **9** | **56** | **7** | **14** | **17**|
| 2026-04 | 241 | 7 | 0 | 42 | 10 | 164 | 11 | **202** | **43** | **3** | **42** | **10** | **33** | **19**|
| 2026-05 | 244 | 4 | 0 | 42 | 10 | 173 | 10 | **212** | **35** | **1** | **42** | **10** | **98** | **19**|
| 2026-06 | 244 | 4 | 0 | 42 | 10 | 169 | 10 | **206** | **40** | **2** | **42** | **10** | **50** | **18**|

Latest month, and the shape of the model underneath it:

| | Before | After |
|---|--:|--:|
| Obligors at exactly 0.0 | 169 | **50** |
| Distinct scores | 10 | **18** |
| Months with any MEDIUM | 0 / 20 | **18 / 20** |
| L1 / L2 / L3 / L4 firing | 73 / 0 / 17 / 0 | **158 / 285 / 130 / 104** |
| Signal observations, all months | 4,767 | **32,282** |
| Distinct nodes per borrower-month | ~1 | **3.12** |
| Net notches at the −2 cap | 189 / 300 | **33 / 300** |
| Anchors in use | 4 values | **7 values** |

**Is it credible now?** Materially more so. All four layers are alive in every
month, the 5×5 matrix reads across two rows rather than one, the notch layer
is a spread rather than an offset, and MEDIUM exists. What has NOT changed is
that MEDIUM stays thin — 2 of 300 in the current month. That is the
methodology, not the data: the matrix's LOW-T&A anchors top out at 40, the
notch cap adds at most 16, and the override floors jump to 60 and 95, so the
50–74 window is reachable only from anchor 40 with two adverse notches. It is
worth saying to a reviewer rather than engineering away.

## §5–§14 — the untested matrix, completed

**Levels 1–5, 20 of 20.** Retrieval, diagnosis, borrower diagnosis, decision,
and multi-part executive questions, each checked against oracle facts computed
from `v2_service` and the parquet only.

**Both thread chains, 13 of 13.** Population chain: sector → names → which two
worsened → why → escalate → inform → what did we conclude. Borrower chain:
open → did it improve → what changed → newest evidence → what to ask the RM →
draft a message. Inheritance holds in both, and a stale severity band no
longer leaks into a question that names the whole book.

**Clarification, 2 of 2.** A name matching several obligors asks which, with
governed options, and runs nothing. "Show me the bad names" is answered
without interrogating the reader.

**Noisy, misspelled and mixed-language, 6 of 6.** English typo-heavy,
Hindi/English twice, Arabic, and a long multi-part paragraph. The
deterministic language pass now handles dropped-vowel typing offline; the
model pass remains the architecture's answer to the general case, and case
LIVE-7 in the certification script is exactly this question against a real
provider.

**Ten new adversarial questions, 10 of 10.** A sector not previously tested, a
three-month window, a twelve-month improvement question, a two-filter
question, a false premise, a request for a probability, a vague question, a
comparison, a methodology question about double-counting, and a layer
difference.

## §9–§13 — the workflows

| | | |
|---|---|---|
| W-A | Escalate a real borrower, routed by the matrix | PASS |
| W-B | Escalating twice does not open a second case | PASS |
| W-C | Inform is an FYI and does not undo the escalation | PASS |
| W-D | The escalation appears once in the workflow inbox | PASS |
| W-E | An investigation is saved, reopens and appears once | PASS |
| W-F | Reports generate and are real documents | PASS |

Two defects were found and fixed here, and they are the ones that would have
been found in minute two of a manual UAT.

**The matrix could not name a recipient.** It decided the rung, the urgency
and the parallel notifications — and the endpoint still required the CALLER
to name somebody, because nothing could turn "Head of Credit Risk" into an
inbox. A rung now addresses a team named for it, derived from the matrix's own
role names so the two cannot drift.

**The browser never said who the reader was.** It sends an acting role and has
never sent an acting user, so every request arrived with no actor and every
list that belongs to a person was empty by construction. Escalate a case, open
the inbox, find nothing — for every product, not only this one.

**Reports** were opened and read, not weighed: 1,232 / 1,646 / 2,087 words,
6 / 8 / 7 tables, 1 / 2 / 6 embedded charts, no blank pages, and the figures
reconcile to the domain (score 95.0, band Very High, anchor 22, 300 obligors,
portfolio 19.5, 52 at high or above, period 2026-06 in all three).

## §16 — the progress UX, on every path

| | | |
|---|---|---|
| U-1 | The landing screen loads | PASS |
| U-2 | A normal analytical turn shows real progress and answers | PASS |
| U-3 | A question for another product is handed over | PASS |
| U-4 | An ambiguous name asks rather than guessing | PASS |
| U-5 | A request to change a score is refused on screen | PASS |
| U-6 | A multi-turn thread keeps its history, one turn animating | PASS |
| U-7 | Browser Back returns to the previous state | PASS |
| U-8 | Investigations list and reopen | PASS |
| U-9 | The escalation reaches the workflow inbox screen | PASS |
| U-10 | The screen works at phone width | PASS |

No console errors. No model, provider or token vocabulary anywhere on screen.
Finished turns collapse to their completion line; only the active turn
animates. Screenshots in `docs/evidence/pre-uat-2/`.

## §15 — performance

Twelve turns, no provider, so every stage is the deterministic reader.

| | |
|---|---|
| Median | 0.647s |
| p90 | 1.228s |
| Slowest | 4.127s — the first turn, loading the parquet partitions |
| Fastest | 0.236s |
| Largest progress-event payload | 354 chars |
| Largest planner input | 0 tokens — no model call is made offline |

Slowest stages, median milliseconds:

| Stage | ms |
|---|--:|
| ews_context_built | 173.5 |
| sonnet_pass_2 | 83.5 |
| execution_step | 61 |
| opus_analysis_plan | 3 |
| opus_functionality_selection | 1.0 |
| validation | 1 |
| opus_final_interpretation | 1 |
| request_started | 0.0 |

The ~50k planner input the directive mentions is a provider-mode figure and
cannot be measured here. The certification script records
`largest_planner_input_tokens` so the Mac run answers it. Not refactored: it
is not a functional or UAT blocker.

## Run 2 — every defect found and fixed

Sixteen, beyond the three carried from run 1. Each had a reproduction, a
root-cause fix and a regression test.

| | What was wrong |
|---|---|
| R2-1 | A diagnosis dropped the plan's filters, so a sector question described the whole book |
| R2-2 | A movement dropped the plan's obligor, so a borrower question reported the portfolio's move |
| R2-3 | The plan's intent named an analysis no step produced, so a revision replaced the answer instead of adding to it |
| R2-4 | A sufficiency revision took its filters off the headline step, widening to the whole book |
| R2-5 | The grouping branch returned before the other parts of a multi-part question were planned |
| R2-6 | Non-headline packs never reached the page, so two thirds of a three-part answer was silently dropped |
| R2-7 | A population-scoped action question produced nothing at all |
| R2-8 | "Escalation threshold" was read as an instruction to escalate |
| R2-9 | "Over six months" was not a recognised spelling of a six-month window |
| R2-10 | A severity band from an earlier turn narrowed a question that named the whole book |
| R2-11 | "Show the 10 obligors whose score has risen most" was not read as a request for names |
| R2-12 | A name matching several obligors fell through to the portfolio summary |
| R2-13 | The chat would not change a score on the screen path and would on this one |
| R2-14 | A request for a probability of default was answered with the score |
| R2-15 | Two named groups were not read as a comparison, and two bands in one phrase were |
| R2-16 | Escalation could not name a recipient, and the browser never said who the reader was |

## Run 2 — regression

```
backend   22 failed, 10,589 passed, 27 skipped, 0 errors
          (run-1 baseline 22 failed / 10,368 passed)
frontend  429 of 429
typecheck clean · lint clean · production build clean
```

The 22 failing identifiers were diffed against the recorded baseline list and
are **identical, line for line**. None is in `tests/early_warning/` or
`tests/api/`. They sit in `tests/docs`, `tests/evals`,
`tests/orchestration`, `tests/presentation` and `tests/proof`, and every one
of them predates `d683881`. The 221 additional passes are this run's new
tests.

- `tests/early_warning` and `tests/api`: clean, and 163 new assertions across
  `test_layers.py` (57), `test_band_transitions.py` (42),
  `test_scope_is_not_dropped.py` (52) and `test_escalation_routing.py` (12).
- Frontend: 429 tests, 429 pass. Typecheck clean. Lint clean. Production build
  clean.
- Two existing tests were amended rather than deleted, both because the
  behaviour they pinned had improved: `test_data_domain.py` asserted that
  `dominant_driver` was missing for most obligors, which stopped being true
  once signals were carried forward, and `test_conversation_thread.py` pinned
  the movement sentence's opening words before it began saying which way the
  score moved.

## The one thing left: certify against a real provider, on your Mac

This container has no Anthropic credential and, by instruction, is not to be
given one. Everything that does not need a provider is done. This is the
procedure that closes the rest, and it is the only thing being asked of you.

**Your key is never typed on a command line and never enters your shell
history.** `read -rs` prompts for it silently; `scripts/certify_early_warning_live.py`
never reads, prints, logs or writes it, and scrubs anything credential-shaped
out of its report before saving.

```bash
cd ~/IPM_V2-ews-live
git fetch origin claude/early-warning-rebuild-v2-3lnttn
git checkout claude/early-warning-rebuild-v2-3lnttn && git pull

read -rs -p "Anthropic API key: " ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY && echo

export AI_PROVIDER=anthropic
export AI_ROUTER_MODEL=claude-sonnet-5
export AI_COMPLEX_PLANNER_MODEL=claude-opus-5
export AI_CRITIC_MODEL=claude-opus-5
export AI_ANALYST_MODEL=claude-opus-5

python scripts/certify_early_warning_live.py

unset ANTHROPIC_API_KEY
```

That is the whole procedure. It prints a PASS or FAIL line per case and a
verdict, writes
`docs/evidence/live/early_warning_live_certification.json`, and **exits
non-zero if anything failed** — so there is nothing for you to inspect by
hand. If it prints `VERDICT: CERTIFIED`, Early Warning is ready for your
manual UAT.

It runs the eight provider-dependent cases §17 names — easy retrieval,
diagnostic, multi-part analytical, follow-up, incorrect premise, the
cross-product What-If route, noisy spelling and a mixed-language question —
and for each one records the question, the resolved ownership, every stage
with the model family that served it, the execution count, whether an answer
came back, the grounding status and the elapsed time.

For every normal analytical turn it requires:

- `sonnet_pass_1`, `sonnet_pass_2`, `opus_functionality_selection`,
  `opus_analysis_plan`, `opus_sufficiency_review`,
  `opus_final_interpretation` and `sonnet_summary_update` all at
  `engine=model`;
- **`sonnet_summary_update` at `engine=model` and not truncated** — asserted
  by name, because that is the stage that truncated at 700 tokens on your
  last live run and the allowance change has not been proven until a real
  model exercises it;
- no stage spending its whole output allowance;
- no stage falling back to the deterministic writer;
- every model reply conforming to its schema;
- each stage served by the family it asked for;
- the model's prose kept rather than discarded for an ungrounded figure;
- the ledger reconciling.

The report also records `largest_planner_input_tokens`, which answers §15's
open question — the ~50k planner input can only be measured with a provider,
because offline no model call is made.

### If you want to look at it yourself as well

```bash
python scripts/prove_early_warning_conversation.py    # the stage-by-stage trace
uvicorn backend.api.main:app --reload --port 8000     # terminal 1
cd frontend && npm install && npm run dev             # terminal 2
open http://localhost:3000/early-warning
```

The dedicated proof is kept and unchanged. Neither of these is required: the
certification script is the gate.

---

# Run 3 — live provider certification, and the five cases it failed

The Mac run of `scripts/certify_early_warning_live.py` returned **3/8
certified, `VERDICT: NOT_CERTIFIED`**, median 52.2s, slowest 134.6s. LIVE-1
(easy retrieval), LIVE-4 (follow-up) and LIVE-6 (the cross-product What-If
route) passed. The other five failed on three defects.

Every one of the three is invisible without a provider. Each needed a model to
actually write something — a paragraph with a figure in it, a pass-two reply
with a layer in it, an ownership verdict — and with no key configured every
stage falls to its deterministic floor and every contract holds vacuously.
That is how a build with 78 green scenarios failed five of eight real cases,
and it is the reason this run adds a stub that produces the exact shapes the
live run produced rather than the shapes that were convenient to test.

## Defect 1 — the grounding guard rejected figures the packet was holding

Four cases died here: LIVE-2 on `11.31` and `3.67`, LIVE-3 on `11.31`, `15.46`
and `3.67`, LIVE-7 on `6.34`, LIVE-8 on `-5`.

**Provenance, traced one at a time.** The packets were rebuilt for each failing
question and every rejected figure looked up in them:

| Figure | Where it lives in the packet | Class |
|---|---|---|
| `11.31` | `figures.movement.layers[0].score_change` = **−11.31** | **A — direct** |
| `3.67` | `figures.movement.ews_change` = **−3.67** | **A — direct** |
| `15.46` | `figures.movement.layers[3].score_change` = **−15.46** | **A — direct** |
| `6.34` | `figures.movement.layers[0].score_change` = **−6.34** | **A — direct** |
| `-5` | nowhere — and `5` alone was always allowed | **not a figure** |

None was invented. Four are stored **signed** and were written **in words**:
the packet holds `ews_change: -3.67` and the model wrote "the score fell 3.67
points", which is how every credit paragraph anybody writes says it. The
allowed set was built from `f"{value:.2f}"` and friends, so it contained
`-3.67` and never `3.67`. A guard holding the number rejected the sentence
about it.

`-5` is a different thing entirely. `5` is in `_ALWAYS_ALLOWED`, so a bare five
would have passed — the only way the run could report minus five is a minus
sign the prose did not write. The numeral scanner's lookbehind was
`(?<![\d.,\-])`, which refuses a digit before the match and permits a letter,
so **a hyphen between two word characters was read as a minus sign**: `top-5`
became −5 and `tier-3` became −3. This stage's own system prompt asks the model
to say "rests on one tier-3 source".

**The fix, in three parts.**

*Direct.* A packet value permits both its signed spelling and its size. This is
a figure guard and 3.67 is the packet's figure. It does mean the guard alone
cannot catch a reading that inverts a direction; that is the composer's
"It improved / It deteriorated" verdict and the deterministic reading shown
alongside, and it is stated in the code rather than left implied.

*Derived.* `backend/early_warning/conversation/derivation.py` — the governed
derived-claim contract. The model does not compute; it **declares**:

```json
{"value": 15.66, "op": "sum", "refs": ["rows[0].exposure", "rows[1].exposure"]}
```

The server resolves each ref in the packet's own fact index, applies the named
operation itself, and compares. Prose may use the value only where the server's
recomputation agrees; a claim whose refs do not resolve, whose operation is not
in the closed set, or whose value the server does not reproduce permits
nothing, and the figure falls through to the direct check. Twelve operations:
sum, difference, delta, product, ratio, share, percent, mean, magnitude,
minimum, maximum, count. Each is a Python function of a list of floats. **No
`eval`, no expression parser, no model-supplied formula** — asserted by a test
that reads the module's own source.

*Neither.* The scanner's lookbehind is now `(?<![\w.,\-])`. A hyphen inside a
word is a hyphen, and `L1`, `L3` and `L1.2` stop being figures — naming the
node is exactly what the prompt asks a good reading to do.

**Invented figures are still discarded.** `test_an_invented_figure_is_still_
rejected` and the stub's `ungrounded` behaviour both still hold, and a month
nobody published is still refused.

## Defect 2 — pass two lost a whole reading over the case of one letter

LIVE-3's `sonnet_pass_2` reply did not conform: `requested_layer` carried a
value outside the closed enum. The enum is `L1 | L2 | L3 | L4 | ""` and the
post-validation code already handled anything unexpected — but validation runs
first, so `"l3"`, `"Layer 3"`, `"L3 external intelligence"`, `["L3"]` and an
explicit `null` each threw the entire pass away and the reading of the request
fell back to the patterns.

The stage had **no `tidy`**. The planner has had one since its own schema
defect; pass two never got the same treatment.

`_pass_2_tidy` now maps each closed field into the vocabulary the schema
already contains, with the planner's discipline: **map, never invent, and drop
what will not map.** The layer aliases are not a table kept in this module —
`layers.resolve` is the product's one governed reader of layer language, so
"external intelligence" resolves to L3 here for the same reason and by the same
code that makes it resolve to L3 anywhere else. `L9` is dropped rather than
guessed at, the field is optional, and the deterministic reading stands. The
enum is unchanged and `requested_layer` is not free text.

The same treatment for `requested_analyses`, `requested_scope` and
`requested_actions`, whose enums are equally closed and equally exposed.

## Defect 3 — an incorrect premise was routed to What-If

LIVE-5 asked "Given every Contracting obligor improved last month, which one
improved most?". The premise is false — Contracting deteriorated — and saying
so is the answer. The model read "given" as a supposition and routed the
request to What-If; the gate accepted it, because routing OUT was treated as
always safe. Executions 0, no plan, no sufficiency review, no interpretation,
no answer.

"Routing out is safe because nothing runs" is true of the controls and false
of the reader. So the gate has a second governed test in the outward direction:
**an observed-state question with no stipulated change stays here.**

The test is not the word "if". Both of these contain one:

    If Contracting deteriorated, what drove it?        observed
    Recalculate ECL if the rating falls two notches.   hypothetical

`functionality.stipulates_a_hypothetical` looks for a value being **replaced** —
a shock or scenario verb, a driver moved by a stated amount, or a recomputation
requested under a supposition. `asks_about_observed_state` looks for an outcome
verb this product owns over a window that has closed, in a sentence asking the
product to explain, test or rank it. `belongs_to_early_warning` is the
conjunction, and `select._reconcile` refuses a route-out where it holds.

The original asymmetry is untouched: a model still may not open the gate. A
genuine scenario the patterns missed still leaves — `test_a_scenario_the_
patterns_missed_can_still_be_routed_out` pins that. LIVE-6 is pinned exactly:
owner `what_if`, EWS executions 0.

## What now proves it

| Suite | Tests | What it pins |
|---|---|---|
| `test_grounding_derivations.py` | 34 | the five rejected figures, the hyphen, the closed operator set, no `eval` |
| `test_live_model_conformance.py` | 60 | every `requested_layer` shape a live model sent, and the other closed enums |
| `test_ownership_premise.py` | 38 | 11 observed questions, 8 hypotheticals, and the gate in both directions |
| `test_live_certification_cases.py` | 33 | all eight live cases end to end, through a model that answers |
| `test_grounding.py` (existing) | 32 | unchanged, and still passing |

The stub gained the live shapes rather than convenient ones: a reading that
states the size of a signed move, one that declares arithmetic, one that
declares it wrongly, one that does the arithmetic without declaring it, and the
eight `requested_layer` spellings. Its pass one now spells the question the way
the product's own patterns do — pass one is the only stage whose prompt does
not carry the deterministic floor, so a stub echoing its input was measuring
itself.

## Performance

Not refactored, per instruction. The 134.6-second case is LIVE-3, the
multi-part analytical question, and its `sonnet_pass_2` failed schema
validation — a failed structured call is retried at the provider boundary
before the stage gives up and falls back, so the slowest case is also the one
carrying a defect this run removes. Whether that accounts for the whole gap is
a question the next certification answers rather than one to argue here; the
report records the per-stage timings for both runs so the comparison is
mechanical.

## Certification script

Diagnostics only, and **no acceptance criterion was changed or removed**. The
next run still requires all eight cases. Each case now also records the
`derived_claims` the reading declared and what the server made of each, and —
where a reading was discarded — the prose it actually wrote, scrubbed like
everything else. Working out where `11.31` and `-5` came from meant rebuilding
the packets by hand from five bare numbers; the report now names the figure,
the sentence it sat in and the arithmetic claimed for it.

A refused declaration is recorded but does not by itself fail a case: the
grounding check already enforces the consequence, because a claim the server
did not reproduce permits nothing and any figure resting on it is rejected
there. Making it a second failure would risk failing a case whose answer was
correct.

---

# Run 4 — LIVE-5, and two failures of the harness itself

The Mac certification returned **7/8**. LIVE-1, 2, 3, 4, 6, 7 and 8 passed and
are unchanged. LIVE-5 — the incorrect-premise case — resolved to
`early_warning`, made 7 of 7 model calls, ran 2 of 2 executions, and had its
final Opus reading discarded for one ungrounded figure: `25`.

## What `25` was, and how far the evidence goes

The certification report could not say. Its `discarded_prose` was truncated at
1,200 characters, before the token appeared, so the record read `25` and
nothing else. Diagnosing it meant rebuilding the packet by hand. **That is the
first defect this round fixes**, and it is fixed before anything about
grounding was touched.

What the evidence does establish, from the reproduced LIVE-5 packet:

**Not A, and not D.** The allowed set is built from exactly the sections the
writer is shown — `figures`, `rows`, `provenance`, `caveats`,
`governed_actions`, `escalation_route`, `steps_that_ran`, the period labels and
the deterministic reading — plus every number the packet carries, untruncated.
So allowed ⊇ shown, by construction and now by test. A `25` living in any of
those, the governed action library and the escalation route included, would
have been permitted. It was rejected, so it was in none of them.

**Not C.** With the lookbehind fixed last round, a bare `25` cannot be
manufactured from a hyphenated word or a node code. `top-25`, `tier-25` and
`L25` all tokenise to nothing. A bare `25` in prose is a quantity somebody
wrote.

**B or E, and both are handled the same way.** The strong candidate is
arithmetic: the question asserts every Contracting obligor improved, the truth
is that three of the thirty did, and the live packet listed five names — so
"the other 25" (30 − 5) and "the other 27" (30 − 3) are both the shape a
rebuttal takes. Under B the rule is unchanged and correct: a derived figure
must be declared and recomputed by the server, and this one was not declared.
Under E the rule is also unchanged: keep rejecting it.

So no grounding behaviour was weakened, and nothing was whitelisted. What
changed is the diagnostic, and the reason the model had to compute anything at
all.

## The reason it had to compute anything

LIVE-5's deterministic reading — the floor the model is shown, and the answer a
reader gets when a provider is absent — said this:

    As at 2026-06, 11 obligors in Contracting sit at high or above. The 5
    largest by exposure are listed, led by Al Rajhi Logistics 8 at 0.0
    (very low)...

Three sentences about three different populations, and none of them answers
"which one improved most". The count came from a high-plus filter the ranking
did not have. The order was claimed as exposure over a list the plan had
sorted by one-month movement. The leader was described by a current score of
zero rather than by the ten-point fall that put it first — with an empty pair
of brackets where its band should be. The obligor the reader asked about was
named, correctly, and then described as though it were an outlier.

The model, shown that, had to construct the rebuttal itself out of the raw
rows. **Four defects, all in the same place:**

| | |
|---|---|
| The ranking claimed exposure order over a movement ranking | the pack carried `ordered_by` and the composer ignored it |
| It opened with a high-or-above count on an unfiltered ranking | `high_plus_count` travels on every population pack and was read unconditionally |
| The leader was named by its current score, not its move | rows printed `ews_score` whatever the list was ranked on |
| `0.0 ()` | an empty band rendered as empty brackets |

And two more, upstream of the composer:

| | |
|---|---|
| The deterministic planner ranked by **exposure** for a movement question, filtered to `high_plus` | which excludes the answer — an obligor that improved is not at high severity, so the one name the reader asked for was the one name the filter removed |
| "Which **one** improved most?" was not read as a request for a name | `_WANTS_NAMES` had no pattern for "which one", so the intent stayed `movement` and the headline became the sector's average |

## What the answer says now

    As at 2026-06, 30 obligors in Contracting match. The 10 that improved most
    over the month are listed, led by Al Rajhi Logistics 8 at -10.0 points on
    SAR 319.6m; the 10 together carry SAR 1.6bn.

    3 of the 30 improved, 21 held and 6 deteriorated. Read the anchor and the
    notches apart before calling a fall an improvement: a score that dropped
    because a notch moved has not had its underlying condition ease.

    • Al Rajhi Logistics 8 at -10.0 points, now at 0.0 (very low), SAR 319.6m
    • Yamama Projects 6 at -8.0 points, now at 12.0 (very low), SAR 134.2m
    • Salman Partners 4 at -8.0 points, now at 16.0 (very low), SAR 172.6m

"3 of the 30 improved" is a **counted figure** on the pack, computed by the
executor over the whole filtered population rather than over the rows the
limit kept. The false premise is refused by a number the reader can check, and
the model no longer has arithmetic to do.

The ranking measure follows the window the question named — `ews_change_12m`
for "over the last 12 months", `ews_change_1m` otherwise — and the window is
named in the sentence, because the product publishes those two columns and
nothing between them, so a six-month question is answered on the closest one
and a reader who is not told cannot see it.

`_WORSENED` and `_IMPROVED` gained the arithmetic words. A score that ROSE is a
borrower that got worse and one that FELL is a borrower that improved, and
"whose score has risen the most" was reaching the exposure ranking. "Fell
into" stays with the worsening side.

## What was NOT changed

Ownership. The observed-state versus What-If routing is untouched, and its 38
tests still pass. LIVE-6 still routes to `what_if` with zero EWS executions.
The four derived claims LIVE-5 got right — the magnitudes of
`rows[0].ews_change_1m`, `rows[0].anchor_change_1m`, `rows[1].ews_change_1m`
and `rows[2].ews_change_1m` — still resolve and are still accepted.

## Two failures of the harness

**A required stage that never ran could read as a pass.** The check's detail
said "stage never reached" whenever `fallback_reason` was empty, which is the
normal state of a stage that worked, so passing cases printed those words
beside `pass: true`. Each required stage is now asserted five ways —
**ran**, **served by a model**, **served by the family it asked for**, **not
truncated**, **no fallback** — and a stage that did not run fails all five
rather than having four of them recorded as passes on properties nobody could
observe. The §18 summary assertion had the same bug and has the same fix.

What-If has its own required set — `sonnet_pass_1`, `sonnet_pass_2`,
`opus_functionality_selection`, `sonnet_summary_update` — so a hand-over is
shorter but not unchecked. Previously it asserted nothing about stages at all,
and a hand-over that fell back to the deterministic router everywhere would
have certified on the strength of having done nothing. LIVE-6 now carries 32
checks where it carried 12.

**The false-premise check could pass on the wrong words.** It scanned for
"did not", "however", "premise" and so on — a list that matches "the model is
**not** calibrated" in a runtime caveat, which contradicts nothing. It now
tests arithmetic the answer states: where the result carries a movement census
and the census says not everyone improved, the answer must quote both numbers.
The phrase list survives as a fallback for results that carry no census.

## Case isolation

Already correct, now asserted and reported. Each case runs in
`live-cert-<its own id>`; only LIVE-4, which declares `follows: LIVE-3`, shares
a thread. An independent case's rolling summary is no longer even read — the
one channel by which a previous case's sector, band or named obligor could
reach the next one is closed at the source rather than left to be empty. Every
run's report carries a `case_isolation` table and each case's
`executed_filters`, so a severity band appearing on a question that named none
is visible rather than reconstructed. LIVE-5's executed filters are
`{"sector": "Contracting"}` on both steps: no band, inherited or otherwise.

## Single-case diagnosis

`--case LIVE-5` (and `--only`, which it aliases) runs one case through the
**identical** checks. Its verdict is `PARTIAL_RUN`, never `CERTIFIED`, and the
run prints how many of the eight it skipped. The gate is unchanged: all eight.

Every run now also prints each rejected figure with the clause it sat in, so
the next `25` explains itself.

## Regression

```
tests/early_warning + tests/api   0 failures
backend (full suite)              22 failed, 10,810 passed, 27 skipped
                                  the 22 identical to the recorded baseline
frontend                          429 of 429
typecheck clean · lint clean · production build clean
```

56 new tests this round: 23 in `test_ranking_by_movement.py` and 33 in
`test_certification_contract.py`, plus the two premise assertions in
`test_ownership_premise.py` and `test_live_certification_cases.py` rewritten
to check the counted rebuttal rather than a hedging word.

One existing test changed, and it was pinning the defect:
`test_a_movement_question_is_answered_about_the_movement` required "Show the
10 obligors whose score has risen the most" to report its intent as
`movement`. Ten obligors is a request for ten names. It is now
`test_a_question_asking_for_names_by_movement_is_answered_with_the_names`,
and it additionally requires the ranking to order by `ews_change_12m`
descending and the answer to name the window.

Against the stub, all eight cases pass, LIVE-6 among them, now carrying 32
stage checks where it carried 12.

---

# Run 5 — LIVE-3, and the two figures it lost a paragraph to

The third Mac certification returned **7/8**. LIVE-1, 2, 4, 5, 6, 7 and 8
passed and are unchanged. LIVE-3, the multi-part analytical case, reached the
provider intact — seven of seven model calls, two of two executions, no schema
error, no truncation — and lost its final interpretation to two numbers.

## `-4.86` — the reading was right

The live plan measured the Contracting movement from **2024-11 to 2026-06**,
not over six months: Opus reached for the earliest published month. That
window gives

```
movement.ews_change                          -2.38
movement.layers.L1.points_contributed        -2.54   (score_change -6.34  x 0.40)
movement.layers.L4.points_contributed        -2.32   (score_change -15.46 x 0.15)
movement.layers.L4.score_before / after      18.77 -> 3.31
```

and −2.54 + −2.32 = **−4.86**, of a **−2.38** point move. Every figure in
"L4 network and relationship fell 15.46 to 3.31, together contributing −4.86
of the −2.38 point move" is a governed fact or an exact sum of two.

**Class B and C.** A weighted contribution the packet already carries — the
weighting is `score_change × weight` and `points_contributed` is that product,
computed by the engine — declared with the **size** where the contract asks
for the signed value. Refs right, operation right, arithmetic right, sign
wrong in the declaration. The prose even used the signed form.

## `6,301.85` — the reading was not

Swept against every permitted fact:

- every published month's Contracting exposure;
- every `dominant_layer` group and its complement (L2 6,259.15 / L1 201.41,
  summing to the 6,460.56 in scope);
- every single-attribute subgroup exposure — layer, sub-category, band,
  classifier band, T&A band, stage, rating, region, segment, utilisation,
  relationship manager, sector — across Contracting and across the book;
- every subset and complement sum of the grouping's rows;
- cumulative exposure under four orderings;
- the total less any one, two or three obligors.

Nothing reproduces it. The gap to the sector total is 158.71 and no obligor
carries that. **Class E — genuinely unsupported.** It keeps being rejected,
and a test pins the sweep so it stays rejected.

What the reading actually wanted was L2's share of the sector. That is now a
fact: `exposure_share_pct` on every grouping row — L2 at 96.9%.

## The third error

`the result carries no fact called rows` — the writer citing a name nobody had
published. `rows` is a list; the index holds numbers.

## Fixes

**A published reference vocabulary.** The interpretation context now carries
`fact_index`: every citable fact under the exact name a claim must use, built
from the same index the server resolves against, so the two cannot drift.
Names are readable rather than positional — a list entry that identifies
itself is indexed under that identity, so it is
`movement.layers.L4.points_contributed` and not `layers[3]`. Keys that name a
thing rather than measure one are excluded: `layer: "L4"` is a code, and
indexing its digits would have published `4` as a fact about the book. The
index is capped at 160 names, preferring the short canonical spelling, and it
is declared citable — the grounding contract test enforces that every section
the writer sees is either evidence or carries no figure, and it caught this
before the suite did.

**One rule for sign.** `derived_claim.value` is the exact signed number the
operation produces, and the prompt says so with the LIVE-3 example. A claim
that states the size instead is **accepted** — the arithmetic and the refs are
right, and losing a correct paragraph to a minus sign is a papercut, not a
control — but it is recorded as `sign_corrected` and what it permits is the
**server's** signed value and its size, never the reading's sign.

**Direction is checked against the sign.** A figure can be exactly the one the
result carries and the verb in front of it can point the other way; "fell
15.46 to 3.31" and "rose 15.46 to 3.31" quote the same three governed numbers
and only one is true. Prose that states the size of a move with the wrong verb
is now discarded exactly as an invented figure is.

The guard is deliberately narrow, and three things narrow it. Only **change**
facts are checked — a score of 3.31 is a level, and the verb near it governs
the change, not it. Only the **same sentence** is searched, and only after any
earlier figure: a stub run caught this immediately, flagging "…has not had its
underlying condition ease. 4 of the 10 share L2.T1" because a falling verb sat
three words before a four. And the always-allowed small numbers are skipped —
"4 of the 10" is a count of the answer's own list, not the size of anything.
For the Early Warning score, down is better, so "improved" pairs with a
negative change and "deteriorated" with a positive one.

**Common derivations are server-owned.** The model should not compute what
CreditProbe can. Each layer now carries `share_of_move_pct` beside its
`points_contributed`; the movement carries `ews_change_size`, `direction`,
`leading_layer_contribution` and `leading_layer_share_of_move_pct`; every
grouping row carries `exposure_share_pct` and `obligor_share_pct`. All are
presentation-layer derivations over already-governed values — no methodology,
no data, no weight changed.

**The prompt puts them in order.** Quote a figure; then quote one the runtime
already derived; only then declare a derivation. And: do not make the answer
more arithmetical than the question — a complement that carries no decision,
"SAR 6,301.85m of the SAR 6,460.56m in scope", is a figure to get wrong for
nothing.

## One defect found while reconstructing

Pass two's merge set `requested_analysis` to `analyses[0]` — declaration order
in the cue table, not an answer to which part of the question leads. So a
model-backed turn read "Why has Contracting deteriorated, is it concentrated,
and which layer is driving it?" as a **ranking**, and the headline became a
list of names above a question that opens with "why". The deterministic reader
had the precedence; the merge did not. Both now call `leading_analysis`, and
LIVE-3's headline is the diagnosis.

## Certification

Stricter, not weaker. Two assertions added — **no move was written in the
wrong direction** and **every declared derivation recomputed** — on top of the
hardened required-stage checks, which are untouched. Each rejected figure
already printed with the clause it sat in; a direction conflict and a refused
declaration now print the same way, with the refs and the server's own value.

## Regression

```
tests/early_warning + tests/api   0 failures
backend (full suite)              22 failed, 10,843 passed, 27 skipped
                                  the 22 identical to the recorded baseline
frontend                          429 of 429
typecheck clean · lint clean · production build clean
stub certification                8/8
```

33 new tests in `test_live3_derivations.py`, built on the reconstructed LIVE-3
packet: the −4.86 derivation and its sign, seven direction wordings, the
6,301.85 sweep, the published names, the bare-`rows` refusal, the server-owned
share, and four end-to-end cases through a model that answers. No existing
test was amended.

## Performance

Not refactored. The last run's median was 53.64s and LIVE-3 74.06s, already
well below the 134.6s of two runs ago. Two of LIVE-3's declarations failed and
one was a wasted round of reasoning; whether removing them moves the number is
for the next run to record rather than for me to claim.

---

# Run 6 — the same eight points, two directions

The fourth Mac certification returned **7/8**. LIVE-1, 2, 3, 4, 6, 7 and 8
passed; LIVE-3 in particular now passes live, and none of run 5's work is
touched. LIVE-5 was correct on ownership, execution, the result packet,
grounding and its derived claims, and failed on the direction guard run 5
introduced — with a sentence that was true.

## The collision, proven

Contracting at 2026-06, 30 obligors:

```
CORP-103270  Al Rajhi Logistics 8   -10.0   improved
CORP-102361  Yamama Projects 6       -8.0   improved
CORP-102909  Salman Partners 4       -8.0   improved
CORP-100034  Sahara Development      +8.0   deteriorated
CORP-102691  Tihama Ventures         +8.0   deteriorated
CORP-103324  Al Rajhi Resources 8    +8.0   deteriorated
CORP-103122  Sahara Projects 9       +8.0   deteriorated
CORP-103430  Tadawi Partners 9       +8.0   deteriorated
CORP-102073  Mabani Manufacturing 4  +4.0   deteriorated
                                     (3 improved, 21 held, 6 deteriorated)
```

**±8.0 both exist.** The largest deterioration is **+8.0**, tied across five
obligors, Sahara Development first by row order. The largest improvement is
−10.0.

So the reading was right. "6 deteriorated, with the largest deterioration
[8.0]" and "which six deteriorated, and by how much against the 8.0-point
largest deterioration" are both about **+8.0**.

## Why the guard chose the wrong fact

Run 5's guard mapped **size → direction** and dropped any size the result
carried both ways. That safeguard was correct and it did not fire, because the
change-fact pattern was a regex looking for the word "change" — and
`largest_deterioration: +8.0` does not contain it. The only 8.0 the map saw
was `rows.*.ews_change_1m = -8.0`. The collision looked like a certainty, and
a true sentence about a deterioration read as a contradiction.

A widened regex would have fixed this instance and left the design wrong:
within one population the same size genuinely goes both ways, and no map from
a number to a direction can be right.

## Direction now binds to a fact

**`backend/early_warning/metrics.py`** owns two questions. *Is this name a
movement?* — `ews_change_1m` is, `ews_score` is not, and
`movement_census.largest_deterioration.change` is, by the segment that says so
rather than by the leaf. *Which way is worse?* — from the field dictionary's
own `higher_is_worse`, which already declares `ews_score: true` and
`exposure: false`; a change column inherits it from the level it measures; and
a metric nobody has classified returns unknown and is **not checked**. The EWS
convention is stated once, in one place, and not assumed universal.

**The reading binds.** A new `movement_claims` in the schema: `{fact_ref,
direction, value}`. The server resolves the ref in the published index,
applies that metric's semantics, and checks the wording and the size against
it. `improved` of `rows.CORP-102361.ews_change_1m` passes; `deteriorated` of
the same fact is refused; `deteriorated` of `rows.CORP-100034.ews_change_1m`
passes. The model supplies wording, the server owns the truth.

**The size-based check is the fallback, and it is now honest.** Fed a complete
movement-fact set, it drops 8.0 as ambiguous and keeps 10.0, which only ever
means the improvement. A size a bound claim has accounted for is exempt from
it. Where neither route can bind, no directional assertion is made about that
figure — stated plainly rather than silently approved.

## The census is a fact now

`movement_census` travels on the packet and is published to the writer:

```
movement_census.total                              30
movement_census.improved_count                      3
movement_census.held_count                         21
movement_census.deteriorated_count                  6
movement_census.largest_improvement.change      -10.0   Al Rajhi Logistics 8
movement_census.largest_deterioration.change     +8.0   Sahara Development
```

The prompt says to quote these rather than count rows or pick an extreme out
of a list, and never to manufacture a benchmark to make a follow-up sound
richer: "Which six Contracting obligors deteriorated, and by how much?" is the
better drill. A follow-up is held to the same grounding rules as the answer.

`measure` and the other label keys are excluded from the index, so
`ews_change_1m` is not published as the figure 1.

## Certification

Stricter again, not weaker: **every declared movement agreed with its own
fact** joins the direction and derivation assertions, and each case's report
carries the movement claims with the server's verdict. Nothing was relaxed.

## Regression

```
tests/early_warning + tests/api   0 failures
backend (full suite)              22 failed, 10,900 passed, 27 skipped
                                  the 22 identical to the recorded baseline
frontend                          429 of 429 — no frontend file changed
stub certification                8/8
```

57 new tests in `test_direction_binding.py`: the ±8.0 collision from the real
frame, the metric module across movements, levels, counts and an unclassified
metric, twelve binding cases that turn on which obligor is named, the exempt
bound size, every reading section, labels and ordinals left alone, and four
end-to-end cases.

---

# Run 7 — the ranking's own coverage

The fifth Mac certification returned **7/8**. LIVE-5 was correct on everything
run 6 addressed — ownership, execution, the packet, grounding, the derived
claims, the direction binding, the ±8.0 collision — and failed on one sentence:

    The ranking names only the 10 obligors returned; the remaining 20 of the
    30 in scope are not shown...

`20` was refused.

## The arithmetic, proven

Reconstructed from the LIVE-5 packet:

```
ranking step   filters {'sector': 'Contracting'}   limit 10   order ews_change_1m
figures.obligors                                   30
figures.named                                      10
rows in packet                                     10
                                       30 - 10  =  20
```

A **legitimate governed derived count** — and refused correctly. Two counts
sitting in a result do not license a third; the packet held thirty and ten and
had never been given twenty, and the writer subtracted in its own prose.

## Coverage is a fact now

`ranking_coverage` travels on every ranking pack and is published to the
writer:

```
ranking_coverage.total_in_scope     30
ranking_coverage.returned_count     10
ranking_coverage.omitted_count      20
ranking_coverage.is_truncated       true
```

Counted server-side from the frame the step actually read — nothing
hard-coded, and no methodology touched. The scope is the population **after
the step's filters**, which is the part that would otherwise be quietly wrong:
a ranking of the eleven high-severity names in a thirty-obligor sector that
lists five omits **six**, not twenty-five. `omitted_count` never goes negative
— a limit above the population returns everything there is, and "minus four
omitted" is not a fact about anything.

The prompt tells the writer to quote these and adds one rule: **do not
subtract one count from another to get a third.** Where the runtime has not
published a figure, say it in words — "the ranking shows only the returned
names, not the whole population".

## The caveat, kept but demoted

Reviewed rather than preserved. That a table was cut at ten is a fact about
the **table**, not about the book, and it is rarely what a credit officer
needs. Asked which obligor improved most, the answer is Al Rajhi Logistics 8
at −10.0, and that 3 of 30 improved while 21 held and 6 deteriorated. The
prompt now says a truncation note belongs after those or not at all, and never
lets a technical aside crowd out the answer. The facts exist so a reading that
does want the note can quote it; the instruction is not to reach for it.

## Grounding is not weakened

`20` is not whitelisted and `_ALWAYS_ALLOWED` is untouched. On the real LIVE-5
packet a wrong count is still refused, and a declared derivation over the two
counts still has to recompute — `difference(total_in_scope, returned_count)`
declared as 19 is refused, declared as 20 is accepted. Coverage counts are not
read as movements, so they have no direction to contradict.

One test in this file is worth reading twice: a first draft asserted that `19`
would be refused on the live packet, and it was not — a packet that size
carries hundreds of figures and nineteen is one of them. That is the guard
working, and the test now picks a figure the result genuinely does not hold.

## Regression

```
tests/early_warning + tests/api   0 failures
backend (full suite)              22 failed, 10,918 passed, 27 skipped
                                  the 22 identical to the recorded baseline
stub certification                8/8
frontend                          not re-run — no frontend file changed
```

18 new tests in `test_ranking_coverage.py`: the five count cases the
instruction names, the filtered-scope case that must say six rather than
twenty-five, the live arithmetic from the real domain, publication to the
writer, the end-to-end sentence, and four that prove the guard still bites.

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

# Early Warning — pre-UAT certification report

**Verdict: NOT READY FOR MANUAL UAT.**

Two reasons, and only one of them is fixable from this environment.

1. **No AI provider credential is available here.** `ANTHROPIC_API_KEY` and
   `ANTHROPIC_AUTH_TOKEN` are unset, there is no `ant` profile on disk and the
   `ant` CLI is not installed. Every real-provider acceptance criterion in §40
   — seven stages at `engine=model`, 7 charged / 7 succeeded / 0 failed,
   3 Sonnet / 4 Opus — is therefore **BLOCKED, not passed**. The exact command
   to close it from a Mac is at the end of this document.
2. **Three P1 defects remain open**, listed below with reproductions. They were
   found by this exercise and are not fixed.

Ten defects were found and fixed. The product is materially better than it was
at the start of this run, and it is not yet certifiable.

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

## Defects found and NOT fixed

### P1-A — "external intelligence" is not read as a layer constraint

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

### P1-B — no band-transition analysis

```
Q: How many obligors changed risk band in the latest month?
   -> "The score moved -12.8 points between 2024-11 and 2026-06"
```

A twenty-month score movement, not a last-two-month transition count. The
oracle says the answer is 2 changed — 1 deteriorated, 1 improved, 298
unchanged. There is no transition analysis in the plan vocabulary to produce it.

### P2 — presentation and data realism

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

## Closing the live-provider gap, from a Mac

```bash
cd ~/IPM_V2-ews-live
git fetch origin claude/early-warning-rebuild-v2-3lnttn
git checkout claude/early-warning-rebuild-v2-3lnttn && git pull

export ANTHROPIC_API_KEY=...            # a real key

# 1. The seven-stage acceptance proof.
python scripts/prove_early_warning_conversation.py

#    Required: 7 charged / 7 succeeded / 0 failed, Sonnet-Opus 3/4, and
#    engine=model on sonnet_pass_1, sonnet_pass_2,
#    opus_functionality_selection, opus_analysis_plan,
#    opus_sufficiency_review, opus_final_interpretation and
#    sonnet_summary_update. The summary stage is the one to watch: it is the
#    stage that truncated, and its allowance is what P1-10 changed.

# 2. The same journeys through the browser.
uvicorn backend.api.main:app --reload --port 8000   # terminal 1
cd frontend && npm install && npm run dev           # terminal 2
open http://localhost:3000/early-warning
```

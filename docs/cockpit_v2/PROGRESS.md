# Cockpit Intelligence V2 — progress log

Durable, append-only. What was done, what it cost, and what it found.

## Checkpoint 1 — audit, isolation, calculator, oracle

Commit `20f23e5` (amended).

* Verified the base: `3855f9b6…`, branch `claude/cockpit-intelligence-v2-mbb22o`,
  zero commits ahead of `main`, clean tree, working Cockpit present.
* Re-checked every Phase 0–3 claim against the code. Twelve confirmed, one
  partly already fixed, one not verifiable without a provider, and **one
  corrected**: it is the ANALYST's output that is discarded, not the
  interpretation's.
* Provider: no credential, Models API returns 401 → `LIVE_PROVIDER_UNVERIFIED`.
* Runtime isolation: own PostgreSQL cluster on 55432, own lake, own catalogue,
  own ports, all under `/home/user/IPM_V2-cockpit-v2-runtime`.
* `backend/cockpit_v2/ecl.py` — the governed calculator.
* `backend/cockpit_v2/attribution.py` — exact Shapley over six factor groups.
* Oracle: 10/10 passing against hand-written literals from the brief's fixture.

## Checkpoint 2 — data product, policies, gates, seed

Commit `4dda296`.

* `policy.py`, `generate.py`, `calendar.py`, `stories.py`, `schema.py`,
  `catalogue.py`, `guard.py`, `persist.py`, `validate.py`.
* Two-quarter pilot published; 51 integrity gates green.

**Defects this checkpoint found in its own work, all fixed:**

1. The pilot generated statements from its own two quarters, so no statement
   was available at the opening date, every rating fell back to the same
   grade, and the ECL movement carried no rating signal. History and the
   published set are now separate arguments.
2. The macro model had no vintage issued before the first published quarter,
   so every scenario PD silently collapsed to the rating-linked base. A
   four-vintage warm-up now precedes the first quarter.
3. The collateral shock compounded across the whole history, wiping the
   security out several quarters before the comparison window opened. It now
   lands as one step in the final generated quarter.
4. One integrity gate was itself wrong: asserting cumulative PD below annual PD
   times years holds only for a flat hazard, and this model has a rising term
   structure. Replaced with a direct identity check against the published
   curves.

* The destination guard **refused the first real seed** because the database was
  named `ipm_v2_cockpit`, which does not carry the `cockpit_v2` namespace. The
  database was renamed rather than the guard relaxed.

## Checkpoint 3 — the answer path and the ECL/PD checkpoint

Commit `ac85f33`.

* `scope.py`, `reader.py`, `understand.py`, `evidence.py`, `answer.py`,
  `service.py`, `budgets.py`; `narrative.prose_source` added to the response
  contract with `deterministic` as its backward-compatible default.
* **Checkpoint question proved end to end** in the real backend. Full evidence
  in `CHECKPOINT_ECL_PD.md`.
* Perturbation proof: PD ×1.6 moves the PD contribution 1.29 → 2.36 and the
  visible sentence with it; collateral ×0.35 moves recovery and leaves PD
  identical; rebuilding the baseline reproduces the answer byte for byte.

**Defects found here:**

5. `"composition" in "decomposition"` is true, and it put a spurious
   composition output on the checkpoint question's very first run.
6. The two-letter sector alias `"it"` matched the pronoun in "where **it** is"
   and silently filtered a portfolio question down to one sector.
7. `"which five borrowers"` did not set a top-N.
8. The Stage 3 recovery shift compounded across the history and left one
   defaulted account carrying 94% of the pilot's allowance.
9. The claim validator read `"Q1 2026"` as a claim of 2026, the exponent of
   `3.55e-15` as a claim of −15, and `CKB-0002-F2` as a claim of −2 — and
   deleted the lead paragraph of the first real answer it saw.

## Checkpoint 4 — full demo, tools, evaluation

Commit `d22091d`.

* Eight quarters, 500 borrowers, 806 facilities per quarter, 151 gates green.
* Five governed tools registered into the existing analyst registry at startup,
  flag-gated.
* 66 evaluation cases, 46 development and 20 locked holdouts, deterministic
  scoring, no model grading a model.

**Defects found here:**

10. The first eight-quarter build was **blocked by its own gate**: the EAD
    identity failed by 1.1e-6 because the gate compared columns as published
    against a tolerance finer than their own six-decimal rounding. Tolerance
    corrected and documented; the rule was not relaxed.
11. A portfolio attribution took nine seconds. Two exact fixes — evaluating
    only the factor groups that moved, and rebuilding measurements in one
    sorted pass under a checksum-keyed cache — took it to a median of 377 ms.
12. The first evaluation run scored **21.7% development / 15.0% holdout**, and
    every failure was real. The validator rejected forty answers for quoting
    governed policy constants and population counts absent from any
    observation, and for quoting the percentage form of a stored fraction.
    Prose that rounded 0.4598% to "0.5%" was correctly rejected, so display
    precision was raised to stay finer than the tolerance. A "because"
    explaining why a covenant test could not run was discarded as an
    unlicensed cause. The weakest-DSCR list named a borrower twice because it
    ranked facility rows — the fan-out the semantic rules forbid, surfacing in
    prose. Follow-ups did not inherit the previous turn's intent.
13. Several evaluation cases were themselves wrong. Forbidding the word
    "movement" deleted the sentence that correctly says an answer is not one;
    forbidding "fraud" and "counted three times" deleted the sentences that
    correctly refuse those readings. Fixed as forbidden OUTPUTS and as phrases
    only a wrong answer would contain.
14. After the fixes: **100% development, 100% holdout** over two repeats each.

## Checkpoint 5 — frontend, browser UAT, documentation

* `frontend/src/components/ask/cockpit-v2.tsx` — the diagnostic badge with the
  quarter selector, and the V2 answer renderer with sections, tables, the
  waterfall, the clarification chips, the suggested actions and the
  prose-source line. TypeScript clean.
* Browser UAT with Playwright against the production build.

**Defects found here:**

15. Playwright's pip package expected a Chromium build the image does not
    carry; the pinned binary is used instead.
16. Chromium inherited the container's agent proxy and every call to the local
    API came back 403 from the proxy. Loopback now goes direct.
17. Next 16's dev server returned 403 for its own static chunks as cross-origin
    requests. The UAT runs against a production build, which is the better
    target anyway.
18. **The most important one.** `POST /ask` had been wired and the screen had
    not: the Cockpit's own composer calls `POST /investigations`, so the
    browser still showed the base build's clarification about horizons while
    the API answered correctly. The integration now applies to the
    `Investigation` object before it is serialised, from one shared module used
    by both paths, so the stored message, the thread's memory, the API response
    and the screen all carry the same narrative.

## Standing blocker

**LIVE_PROVIDER_UNVERIFIED.** No provider credential exists in this
environment. Every answer recorded anywhere in this branch was composed by the
governed deterministic path and made **zero model calls**. The analyst-prose
precedence is implemented and unit-tested; it is **not** live-verified, and
nothing here is evidence of live LLM operation.

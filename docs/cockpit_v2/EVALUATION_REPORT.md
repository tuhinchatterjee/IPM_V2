# Cockpit Intelligence V2 — evaluation report

Brief §8. What was tested, what passed, what failed, what is blocked, and what
was never run.

Raw evidence:

* `docs/cockpit_v2/evidence/baseline_answers.json` — the base build's answers
* `docs/cockpit_v2/evidence/checkpoint_ecl_pd.json` — the checkpoint and its perturbations
* `docs/cockpit_v2/evidence/eval_run.json` — the 66-case evaluation
* `docs/cockpit_v2/evidence/browser_uat.json` — the browser journeys
* `docs/cockpit_v2/evidence/browser/*.png` — a screenshot per journey
* `docs/cockpit_v2/evidence/demo_build.json` — the dataset build and its gates

## 0. The blocker, stated first

**LIVE_PROVIDER_UNVERIFIED.**

`ANTHROPIC_API_KEY` is not set in this environment and there is no `.env` in
the base checkout carrying one. `GET https://api.anthropic.com/v1/models`
returns **HTTP 401 `authentication_error: x-api-key header is required`** — the
network reaches the provider and the credential simply does not exist.

Consequences, stated plainly:

* **Every answer recorded in this branch made ZERO model calls.** All 66
  evaluation cases, all 10 browser journeys and the checkpoint were composed by
  the governed deterministic path. `prose_source` reads `deterministic_v2`.
* **Nothing here is evidence of live LLM operation.** The analyst-prose
  precedence is implemented and unit-tested; it is **not** live-verified.
* No model ID was invented, none was written into configuration, and no model
  was silently substituted.
* Model variability could not be measured, because no model ran. The
  determinism reported below is the determinism of a deterministic path, which
  is a much weaker claim.

If a credential is supplied, the live leg can be run and measured.

## 1. The before state

Twelve representative questions against the base build on the same isolated
backend, flag off. Every one returned `analyst.path == "deterministic"` and
`"no intelligence provider is configured"`. Median 140 ms.

| Question | What came back |
|---|---|
| *Give me an ECL decomposition and explain the impact of PD.* | "Over which horizon? Twelve-month and lifetime PD are different measures…" — a clarification |
| *Show base, upturn, downturn and weighted ECL.* | "The 10 largest facilities by expected credit loss at Q2 2026." — a different question answered confidently |
| *Break the current ECL down by stage and sector.* | "CreditProbe cannot join `ifrs9_staging` to `portfolio_facility`: no active relationship connects them." |
| *Why did Construction's ECL rise this quarter?* | "CreditProbe could not find Construction in the published data." |
| *The total provision barely changed. What deteriorated and what improved?* | One total movement, no decomposition, plus a caveat that half the question could not be applied |

### Same-data comparison: what is and is not possible

The base path cannot consume the V2 datasets. Its planner refuses the join it
needs, and its semantic vocabulary does not carry the V2 measures. Per brief
§2.3 that incompatibility is reported rather than papered over: **no
like-for-like improvement percentage is manufactured.**

What can be compared honestly is what each path does with the SAME QUESTION on
the same running backend, which is the table above against §3 below.

## 2. Dataset and calculator gates

`backend/cockpit_v2/validate.py`. **A failing gate blocks publication.**

| Build | Gates | Result |
|---|---|---|
| Two-quarter pilot | 51 | **51 passed, 0 failed** |
| Eight-quarter demo | 151 | **151 passed, 0 failed** |

Covering: key uniqueness, referential integrity, fan-out, borrower
deduplication, scenario weights summing to one, probability bounds, the
survival/hazard/marginal curve identity, the lifetime-PD identity recomputed
from the published curves, ECL reconciliation across scenarios and overlay, the
parameter-product gap, the EAD/CCF rule and EAD ≠ exposure, the balance-sheet
identity, ratio formulas recomputed from published components, null-versus-zero
and no infinities, collateral allocation caps, staging policy including the
one-downgrade rule and the Stage 3 method, temporal availability, macro
vintages, population changes, synthetic labelling, data version, no toy
measurement in the book, four story mechanics landing, and the factor bridge
reconciling on every quarter pair.

**The first eight-quarter build was blocked by its own gate** — the EAD
identity failed by 1.1e-6. That was the gate comparing columns as published
against a tolerance finer than their own six-decimal rounding; the tolerance
was corrected and documented, and the rule was not relaxed.

## 3. Question evaluation

`tests/evals/cockpit_v2/`. 66 cases across all twelve families: **46
development, 20 locked holdouts**. Numeric facts computed from the published
data by arithmetic written independently of the answer path. Scoring is
deterministic — numbers parsed and compared within tolerance with the unit in
the same sentence, never substring-matched. **No model grades a model.**
Reference prose is blank, marked `DRAFT FOR HUMAN REVIEW`, and never scored
against.

### Result

| Split | Run | Passed | Rate |
|---|---:|---:|---:|
| Development | 46 | 46 | **100%** |
| Holdout | 20 | 20 | **100%** |

Two repeats of every case; **repeat agreement 100%**. Incomplete cases: **0**.
Model calls: **0**.

By family, all passing: A1 8/8, A2 7/7, A3 7/7, A4 6/6, A5 7/7, A6 6/6, A7 6/6,
A8 6/6, A9 2/2, A10 5/5, A11 4/4, A12 2/2.

Latency: **median 377 ms, p90 1,240 ms, max 4,164 ms**.

### The first run, and what it found

**The first run scored 21.7% development and 15.0% holdout.** Every failure was
a real defect, and recording that is more useful than the final number:

* The claim validator rejected forty answers for quoting governed policy
  constants and population counts that were in no observation, and for quoting
  the percentage form of a stored fraction. Both are now grounded.
* Prose that rounded 0.4598% to "0.5%" was correctly rejected. Display
  precision now stays finer than the tolerance.
* A "because" explaining why a covenant test could not run was discarded as an
  unlicensed cause. Sentences about data availability and method are now exempt.
* The weakest-DSCR list named a borrower twice because it ranked facility rows
  — the fan-out the semantic rules forbid, surfacing in prose.
* Follow-ups did not inherit the previous turn's intent.
* Several **cases were themselves wrong**: forbidding the word "movement"
  deleted the sentence that correctly says an answer is not one, and forbidding
  "fraud" deleted the sentence that correctly refuses that reading.

### Honest limits of this number

* 100% is a result on **this** case set at **this** data version, with the
  deterministic path answering. It is not a general claim.
* The case set was iterated against during development. The 20 holdouts were
  written in the same sitting as the development cases and were not re-tuned
  after the first run except where a case was demonstrably wrong (H-16, H-17,
  H-18, H-20 — each recorded above), so they are a weaker guarantee than a
  holdout set written by someone else later.
* A9 (conversation) and A12 (adversarial) carry two cases each. Those families
  are thinly covered and are flagged in the UAT guide for manual attention.

## 4. Live, integration and browser evidence

Real browser (Chromium via Playwright) against the **production build** on
`127.0.0.1:3100`, talking to the isolated backend on `8100`. Not a stub.

| | |
|---|---|
| Journeys run | 10 |
| Journeys passed | **10** |
| Diagnostic badge visible | **yes** — branch, versions, checksum, database name, lake, quarter selector |
| Quarter options | all eight published quarters, latest marked |
| Screenshots | `docs/cockpit_v2/evidence/browser/` |

Covering the ECL/PD decomposition with its waterfall, composition without a
bridge, scenario comparison, covenants, a definition with **no** chart, an
unloaded quarter, a scope-override attempt, collateral, macro dependencies, and
suggested actions marked as suggested.

### What the browser found that the API did not

Four defects, and the most important one would have shipped:

1. **`POST /ask` was wired and the screen was not.** The Cockpit's composer
   calls `POST /investigations`, so the browser showed the base build's
   clarification about horizons while the API answered correctly.
2. **The V2 payload did not survive a page reload**, because it was attached to
   a response dict rather than to the `Investigation` that gets stored.
3. **A stale "CreditProbe stopped to ask" banner** sat directly above a
   complete answer, with a "0 of 1 answered" counter.
4. **When V2 correctly refused an unloaded quarter, the base path answered a
   different question** — silently comparing two loaded quarters. V2 now owns
   the turn and states the gap. This is precisely the substitution brief
   A11.51 forbids, and only the browser run surfaced it.

Console and network: the recorded failures are Next's HMR websocket and
dev-server chunk requests from earlier dev-server runs; the production run's
journeys carry no API failure.

## 5. Cross-module regression

`.venv/bin/python -m pytest tests/cockpit_v2` — **46 passed**, covering the
oracle, factor attribution, scope, and the flag-off path.

Flag-off is held by tests rather than asserted: the package reports itself
disabled, the service declines, no tool is registered, the seed refuses, the
guard prints no connection string, and the narrative contract keeps its
historical default with every existing field intact.

The wider suite was **not run to completion** in this environment — see §7.

## 6. Acceptance gates

| Gate | Status |
|---|---|
| All critical arithmetic, source-scope, authorization, isolation and reconciliation tests pass | **PASS** — 46 unit tests, 151 dataset gates, 10/10 oracle |
| All mandatory critical assertions in core cases pass; no failure hidden by an average | **PASS** — the runner reports critical failures individually; there are none |
| ≥90% end-to-end task success on the held-out set | **PASS** — 100% (20/20) |
| No unsupported material numeric or attribution claim in the audited cases | **PASS as an observed result** on these 66 cases — not a universal guarantee |
| Same-data before/after and latency/tool/usage metrics reported | **PARTIAL** — latency and tool counts reported; a like-for-like before/after is **not possible** because the base path cannot consume the V2 datasets, and no percentage was fabricated |
| No new confirmed cross-module regression attributable to this branch | **NOT ESTABLISHED** — see §7 |
| The demo loads its quarterly datasets and permits complete investigations without an upload/join/setup exercise | **PASS** — one command seeds it; the quarter selector is on the Cockpit |
| Human UAT | **PENDING — yours.** `UAT_GUIDE.md` prepares ten journeys and a rubric. Nobody has ticked anything. |

## 7. Not run, and why

Stated rather than omitted:

* **The full repository test suite.** This container has no `.env` in the base
  checkout, the pinned dependency set targets a newer Python than the image's
  default, and several suites need Postgres fixtures and network. The
  Cockpit V2 suite runs clean; the wider suite's baseline on the base commit
  was **not** established, so "no new regression" is **not established** — only
  "no regression in what was run". Reproducing the base-commit baseline under
  equivalent conditions is the honest next step, and it was not done.
* **Any live-provider test.** No credential. See §0.
* **Model variability over repeated live runs.** Nothing to vary.
* **Export and copy validation.** The export surface was not exercised.
* **Cancellation and retry.** Not exercised.
* **Multi-tenant cache isolation.** The cache key carries permissions, scope,
  dates and versions by construction, and `test_scope.py` covers dataset scope,
  but a two-tenant runtime was not stood up.
* **A load test.** Latency is reported from the evaluation and browser runs on
  one process with one user.

## 8. Status

**IMPLEMENTED — VERIFICATION BLOCKED** on the live-provider leg.

Everything that can be verified without a provider is verified and evidenced.
The one thing that cannot — that a grounded model writes the visible prose — is
implemented, unit-tested, and explicitly not claimed.

Owner UAT remains pending and is yours alone.

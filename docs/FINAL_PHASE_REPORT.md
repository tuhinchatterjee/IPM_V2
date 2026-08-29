# CreditProbe — final consolidation and client-readiness report

Branch `claude/vigilant-darwin-eohyi1` · phase start `e967c6a` · 9 commits ·
76 files changed, 17,025 insertions.

Read points 41 to 44 first if you read nothing else. They are the four
sentences this phase must not get wrong.

---

## 1. What this phase was for

To close every remaining known defect, finish the regulatory and teaching-corpus
ingestion capability, make every question an auditable observation, ask users
non-intrusively whether an answer was accurate, turn corrections into governed
learning candidates, let CreditProbe improve locally under review — and to be
explicit, throughout, that none of this retrains an Anthropic foundation model.

## 2. The immutable phase-start snapshot

`docs/PHASE_START_SNAPSHOT.md`, written before any change, records HEAD
`e967c6aa`, a clean tree, Alembic 0021, 3,851 backend tests collected and 254
frontend tests, a teaching library of 2,453 cases with **zero** human-approved
and **zero** production-retrievable, no `backend/regulatory` package at all,
and nine open defects. Everything below is measured against that.

## 3. Every open defect is closed

Nine, all of them, with `docs/DEFECTS_FINAL.md` recording each root cause:

| Defect | Severity | State |
|---|---|---|
| D4 — a broad investigation reported executing nothing | High | FIXED |
| D5 — a metadata answer reported no datasets | Medium | FIXED |
| D6 — officer selection one level high on the two-domain case | Medium | FIXED |
| D7 — invariants passed on none of the executed analyses | High | FIXED |
| D15 — a portfolio question returned account-grain rows | High (Tier 1) | FIXED |
| D17 — table columns not in governed rank order | Low | FIXED |
| D19 — a coordinated review reported nothing its specialists read | Medium | FIXED |
| D20 — a coordinated review registered no evidence facts | Medium | FIXED |
| D21 — nine of fifteen review-pack risk classes had no cases | Medium | FIXED |

D8, D9 and D10 were re-verified rather than assumed closed by earlier
hardening, and each is evidenced in the same document.

## 4. Containment is not correction

The governing sentence of §3 was applied literally.

**D15** could have been "closed" by an invariant that blocks a wrong-grain
answer. It was instead fixed in the planner: `backend/orchestration/grain.py`
introduces a five-level grain ladder and a `Contract` that records what was
wanted, what was emitted and why, and the planner now converts a ranking into
an aggregate when the request is portfolio-grain. The invariant is still there
and now almost never fires, which is the correct end state.

**D4, D19 and D20 were one defect**, not three: a coordinated Investigation
discarded every sub-analysis except its headline sentence. The `Composition`
record in `backend/orchestration/investigation.py` fixed all three at once.

**D5, D7 and D17 were measurement defects.** The code worked; the probe read
the wrong field, the invariant reader checked `passed` on an object whose
attribute is `ok`, and the column check asserted nothing. Those were said
plainly rather than "fixed" by changing working code.

## 5. Regulatory circular knowledge — delivered

`backend/regulatory/` did not exist at phase start. It now has five modules:
schema, extraction, write-once storage, knowledge and release, plus its own
Assurance. Six formats, ten document statuses, four rule kinds, three
confidentiality classes, supersession and conflict detection, as-of retrieval
that is fail-closed on an undated circular, and SME review with four decisions.

Eight Assurance checks, **five critical**: `cited`, `in_force`, `reviewed`,
`original_intact`, `release_active`. `release_active` was mandatory first,
which let an answer with no reviewed release behind it report `ok`. That is
fixed and the test is named for the five rather than counting them.

Documented in `docs/REGULATORY_KNOWLEDGE.md`. **No circular is in this
repository and none should ever be.**

## 6. The 500+ Q&A corpus — delivered

`backend/teaching/importer.py`: a fifteen-column template with an alias table
so a bank's own spreadsheet imports without being rewritten, XLSX/CSV/JSONL,
5,000 rows maximum, and a preview that reports `ACCEPTED`, `REJECTED`,
`DUPLICATE` or `CONFLICT` per row before anything is written. `CONFLICT` is
separated from `DUPLICATE` deliberately: it means two people in the bank
disagree, and that is a conversation, not noise.

Every imported case arrives `SME_REVIEW_REQUIRED`, authored `HUMAN`, sourced
`CLIENT`, and retrievable by nothing. Documented in `docs/TEACHING_CORPUS.md`.
**No client Q&A file is in this repository.**

## 7. Every question is an observation

`backend/learning/observation.py`. Every completed turn — not every complaint —
becomes a Learning Observation carrying the question, reading, plan
fingerprint, datasets, officer level, assurance verdict and build SHA.

It starts `UNLABELED`. A closed list says what an unlabelled observation may be
used for (replay, drift, uncertainty review, duplicate detection, test
candidates) and a second closed list says what it may never be used for
(teaching truth, release evidence, accuracy measurement). Silence is not
satisfaction, and the code refuses to let it be counted as such.

## 8. The question users are asked

> **Was this answer accurate and useful?**

Five answers; `PARTLY` and `NO` open the detail panel and the other three do
not. `SKIP` and `NOT_SURE` are recorded and are **not** ratings — `SKIP` is
excluded from the satisfaction denominator entirely.

## 9. Non-intrusive, and provably so

Seven suppressions in specificity order, each recorded rather than the prompt
silently not rendering: still running, loading skeleton, error before any
answer, dismissed for this answer, off for this thread, off for this user,
already given. One line under a finished answer; never a modal; never blocking.
`feedback_prompt` is a real preference with `on` / `reduced` / `off`.

## 10. Twenty-three issue categories, in pipeline order

From `wrong_intent` to `other`, ordered from the earliest stage that could have
caused the error to the latest, because that is the order a reviewer rules
things out in. Three subsets route differently: regulatory categories go to an
SME, presentation categories are a per-user preference, and product categories
become engineering tickets rather than teaching cases.

## 11. Corrections become candidates, never changes

Nine statuses, one releasable. `DRAFT → AUTO_PROPOSED → NEEDS_REVIEW →
SYSTEM_REFERENCE_VALIDATED → HUMAN_REVIEWED → HUMAN_APPROVED →
APPLIED_TO_RELEASE`, with `REJECTED` and `RETIRED` as terminal exits. Only
`HUMAN_APPROVED` is retrievable by anything in production.

`propose()` refuses three things outright: no consent, no correction (a rating
is not a candidate), and a product-category complaint. The user's own
correction and the system's proposed correction are held in separate fields
and never merged, so a reviewer sees what was actually said.

## 12. What a user may change alone

Eight preferences. Ten things that look like preferences and are refused by
name with the reason — dataset, method, period, grain, officer, agents, model,
threshold, interpretation, rounding. A preference changes what one user sees;
everything in the second list changes what CreditProbe concludes.

## 13. The guard: raw feedback cannot reach production

`backend/learning/guard.py` is a static check with three layers: ten forbidden
imports (the Assurance store among them), thirteen protected write-groups, and
forbidden promises in user-facing strings. It runs in the test suite, at
`GET /api/v1/learning/guard`, and in `-FeedbackCritical`.

It reports **ok**, with one line-level exemption that is *surfaced* in the
report rather than hidden:

> `backend/services/learning.py:467` — records which teaching release this
> learning release was built against; does not touch the teaching release.

The guard was narrowed three times during construction rather than left noisy.
A check that cries wolf gets switched off, and then the real write goes through.

## 14. Local learning is gated, evaluated and reversible

Learning releases carry five gates — no new critical failures, target metrics
improved, no safety regression, no holdout leakage, reviewed and approved by
someone who is not the sole reviewer. An unmeasured metric is `None` and
`None` never passes: "we did not check" is not "it was fine".

Replay compares production against a candidate over twelve axes, eight
material, each `IMPROVED` / `REGRESSED` / `UNCHANGED` / `UNMEASURED`.
Improvements are never netted against regressions.

## 15. Approved local auxiliary models

Nine permitted tasks, every one a routing or matching decision over a closed
set, each shadowing the deterministic rule that remains the fallback. Six tasks
are refused **by name in code** with the reason: answer generation,
interpretation, risk rating, PD estimation, ECL calculation, threshold setting.

Artifacts are scanned for anything key-shaped or client-shaped and sealed by
content hash, so an approved artifact cannot be swapped. Documented in
`docs/LOCAL_AUXILIARY_MODELS.md`.

## 16. The API and the screen

Twenty-four `/api/v1/learning/*` endpoints, thirteen `/api/v1/regulatory/*`,
three `/api/v1/teaching-corpus/*`. The screen is **AI Studio → Feedback &
Learning** at `/ai-studio/feedback-learning`: seven tabs plus the guard card.

**Regulatory knowledge and the corpus importer have no screen in this build.**
`backend/proof/matrix.py` records them as `BACKEND_ONLY` and the client runbook
demonstrates them at the API rather than sending a presenter to a page that
does not exist.

## 17. Agentic behaviour still works, and is better

`docs/POST_FINAL_AGENTIC.md`, regenerated on this commit, 15 probes, no
provider call:

| Metric | Phase start | Now |
|---|---|---|
| Officer selection accuracy | 83.3% | **100.0%** |
| Outcome accuracy | — | 100.0% |
| Unnecessary specialists | — | 0 |
| Missed specialists | — | 0 |
| Requests that executed an analysis | 20.0% | **33.3%** |
| Invariants passed (of executed) | 0% | **100.0%** |
| Mean assurance coverage | 93.3% | 93.4% |
| Critical failures | 0 | 0 |
| Critical checks with no signal | 0 | 0 |
| Mandatory checks unresolved | 0 | 0 |
| Officer-ladder verdict | MATERIAL | **MATERIAL, monotonic** |

The monotonic reading returned to `True` only after the probe's *consulted*
metadata was separated from the *datasets it actually read* — the two had been
conflated, and the conflation made a metadata answer look like it had read six
sources.

## 18. Cockpit and Project parity

Six Project probes run the same questions as their Cockpit equivalents.
`test_a_project_investigation_uses_the_same_architecture` asserts identical
orchestration, coordination, specialist count and officer level;
`test_a_cockpit_turn_records_no_project` asserts the isolation half. Both pass.

## 19. Risk Cases, workflow, exports, Trace, navigation and UI

Covered by the regression matrix and by browser acceptance below. The matrix
now spans **71 features across 18 areas**: 41 PROVEN, 23 BACKEND_ONLY, 0 THIN,
4 LIMITED, 3 DEFERRED. 42 features exercised by a browser, 12 not.

Three things are recorded as **untested**, not as working: the governed Project
Plan (§8, not built), Arabic and RTL, and Shadow Mode.

## 20. Browser acceptance

12 screens × 3 viewports × 7 checks, against a **production** Next.js build and
a live backend — not the dev server. `/ai-studio/feedback-learning` is in the
set.

**252 of 252 checks passed, 0 failed.** Results in
`docs/browser_acceptance.json`.

## 21. Tests

| | Phase start | Now |
|---|---|---|
| Backend collected | 3,851 | **4,031** |
| Backend passed | 3,835 | **4,015** |
| Backend skipped | 16 | 16 |
| Backend failed | 0 | **0** |
| Frontend | 254 | **265** |

180 backend tests and 11 frontend tests were added. The skips are unchanged and
are the same environment-dependent ones.

## 22. Two test-isolation defects, found and fixed

Both of the class the previous phase had to fix. One pack test assumed an empty
teaching library; one review-pack test assumed a seeded one, and the suite
truncates `teaching_cases` midway. Rewritten to assert against fixtures they
create or against the seed corpus in memory, so neither depends on suite order.

## 23. Quality gates

| Gate | Result |
|---|---|
| `ruff check .` | All checks passed |
| `pytest` (full) | 4,015 passed, 16 skipped, 0 failed |
| `scripts/check_powershell.py` | ok, all scripts |
| `tsc --noEmit` | clean |
| `eslint` | clean |
| `npm test` | 265 passed, 0 failed |
| `next build` | succeeded |
| `alembic upgrade head` (current DB) | 0023 |
| `alembic upgrade head` (empty DB) | 0018 → 0023 clean, ends at 0023 |
| `docker compose config -q` | valid |

## 24. Migrations

Head is **0023**. Two new migrations this phase: 0022 (regulatory circulars and
releases) and 0023 (feedback events, learning observations, candidates, review
decisions, learning releases and activations, replay runs, local training runs,
user preferences — nine tables).

Verified from an empty database as well as the current one, because a migration
chain that only works on a database that already has the tables is not a
migration chain.

## 25. Docker

`docker compose config -q` passes. **The stack was not built or run here**:
this sandbox has no Docker daemon. That is stated rather than implied, and the
exact Windows commands are in `docs/CLIENT_TESTING_RUNBOOK.md`.

## 26. The four new verification modes

| Command | Calls | Verifies |
|---|---|---|
| `-AgenticCritical` | ~22 | Officer selection, coordination, what specialists read |
| `-ProjectCritical` | ~18 | The same work inside a Project, with scope isolation |
| `-FeedbackCritical` | **0** | Prompt, event, observation, candidate pipeline, guard |
| `-RegulatoryCritical` | **0** | Extraction, as-of retrieval, citations, the five gates |

Two of them spend nothing, and that is not a rounding: those paths are entirely
deterministic.

## 27. A new status, because the alternative was a lie

The two free modes ran cleanly and reported `FAILED`, because `_finish` settled
every status from `live_verified` — a statement about provider calls that a
mode making none can neither earn nor be condemned by. Calling them
`LIVE_VERIFIED` instead would have been the worse error: it would claim
live-model verification that did not happen.

They now earn `DETERMINISTIC_VERIFIED`, exit 0, and never light the product's
LIVE VERIFIED lamp. Both were run here and both pass.

## 28. A free run can no longer destroy a paid one

Every mode wrote to one report file per commit. `stored()` refused to *read* a
dry run as a verification — which kept the badge honest and did nothing to stop
the cheapest command in the product landing on top of the report a live run had
just written. Non-live modes now write to their own file name, in the Python
module and in the PowerShell wrapper alike.

## 29. Windows commands

`docs/AGENTIC_LIVE_VERIFICATION.md` now carries all nine modes with their
costs, which two run without a key, what each report file is called, and the
exact PowerShell for each. `docs/CLIENT_TESTING_RUNBOOK.md` carries the stack,
migrations, seeding, health checks, source/image SHA comparison, the free
verifications, the paid ones, browser acceptance, and a 22-step demo script.

## 30. Performance

Measured, not asserted (`scripts/learning_performance.py`):

| Operation | Median | On the answer path |
|---|---|---|
| the prompt decision | 0.0004 ms | yes |
| building an observation | 0.0077 ms | yes |
| writing the observation | 1.9558 ms | yes |
| recording a rating | 0.0051 ms | no |
| proposing a candidate | 0.0080 ms | no |
| the raw-feedback guard scan | 113.9 ms | **no** |

**Under 2 ms added to an answer**, almost all of it one database write. The
guard scan is fifty times slower than everything else combined and never runs
on the answer path. When the database is unreachable the write reports
`NOT MEASURED` and stays in the table rather than being dropped from the total.

## 31. Nothing in §0's hard boundary was weakened

No foundation was bypassed, weakened or silently replaced. The provider
abstraction, model-role configuration, sealed-holdout isolation, semantic
ontology, Analytical IR, safe SQL compiler, approved kernels, business
invariants, reconciliation, Assurance critical gates, immutable Assurance
Records, the Analysis < Investigation < Project hierarchy, Risk Case semantics,
workflow permissions, human approval gates, governed exports, return-context
architecture, role and tenant boundaries, the theme system, the agent-worker
engine and Regulatory/Teaching Release semantics are all intact.

The sealed-holdout rule in particular still holds one way only: the factory may
import the backend and the backend may never import `intelligence_factory`.

## 32. The teaching library, at the end

| | Phase start | Now |
|---|---|---|
| Total cases | 2,453 | **2,525** |
| BLUEPRINT | 1,287 | 1,359 |
| MIGRATED | 1,083 | 1,083 |
| DERIVED_FROM_CONTRACT | 83 | 83 |
| HUMAN_APPROVED | **0** | **0** |
| Production-retrievable | **0** | **0** |

The 72 added cases are the nine safety blueprints that closed D21. Nothing in
the shipped library is approved, and nothing in it is retrievable in production.
That is the correct state: approval is the client's act, not ours.

## 33. What is NOT delivered

Stated rather than approximated:

* the governed **Project Plan** of §8 — not built;
* **Arabic and RTL** — out of scope, `localization_rtl_readiness` reports
  `NOT_AVAILABLE`;
* **Shadow Mode** — not built;
* **screens** for regulatory knowledge and corpus import — API only;
* `follow_up_quality` asserts scope, not usefulness;
* the export download buttons were not exercised by a browser, because this
  sandbox cannot accept a file download;
* 23 of 95 assurance subcomponents report `NOT_AVAILABLE` — the judgment
  engines, parts of the agentic layer and five out-of-band UI checks.

## 34. What was found late and fixed

The regression matrix still carried D19 as a `LIMITED` feature after D19 was
closed. Corrected to `PROVEN` in this phase, which is why the counts here read
41/23/0/4/3 rather than 40/23/0/5/3.

## 35. Every user question is auditable

Observation → optional feedback event → optional candidate → review decisions →
release → activation. Nine tables, every transition recorded with who and when,
and `GET /api/v1/learning/candidates/{id}/history` reads the chain back.

## 36. Material actions still require human approval

Activating a learning release, activating a regulatory release, activating a
local model and approving a candidate all require a named approver, and the
approver may not be the only reviewer. Rollback is a first-class recorded
action in all three cases, not a redeployment.

## 37. Consent

`CONSENT_GRANTED` / `REFUSED` / `UNSET`, and `may_learn_from()` is fail-closed:
`UNSET` is not consent. Without consent a correction is recorded as feedback
and can become no candidate at all.

## 38. Confidentiality and tenancy

Regulatory retrieval filters tenant, then confidentiality, then status, then
date, and reports exclusions rather than hiding them. Tenant names are
sanitised — a tenant called `../../etc` is not a tenant. Feedback text is
scrubbed. Training artifacts are scanned for client columns and anything
key-shaped.

## 39. Nothing forbidden was committed

No API key. No `.env`. No client data. No circular original. No user Q&A file.
No confidential prompt. No raw feedback export. No unapproved training artifact.
No sealed holdout answer. No live-verification report containing sensitive
content. The reports in `logs/` carry no key-shaped field, and `write()` refuses
to file a report that does.

## 40. Nothing about Claude Code's sandbox was weakened

No TLS or network security was altered. `ANTHROPIC_API_KEY` was never
requested, inspected, printed or logged.

---

## The four sentences that matter

### 41. Raw user feedback does not automatically train or change production

It cannot. Not "we chose not to" — the path does not exist. A rating is
evidence; it becomes a candidate only with consent and a correction; a
candidate becomes retrievable only at `HUMAN_APPROVED`; an approved candidate
reaches production only inside a release that passed five gates and was
activated by a named approver who was not the sole reviewer. And
`backend/learning/guard.py` proves statically that no feedback module can even
import the modules that would let it shortcut any of that.

Raw feedback changes no production behaviour, no Assurance record and no score.

### 42. Approved local auxiliary models are not Anthropic fine-tuning

They are small local classifiers, trained on this bank's reviewed data, running
inside this deployment, choosing between options the deterministic layer
already offers. **No Anthropic foundation-model weights are read, written,
adapted or influenced. No training data is sent to Anthropic. Nothing here
changes how Claude behaves, for this deployment or any other.** The six tasks
that would make this a credit model rather than a router are refused by name in
code.

### 43. The 99.99% accepted-answer precision target

**Not demonstrated, and statistically unproven.**

Three separate reasons, and all three hold:

1. **The measurement was not run.** Precision on accepted answers is measured
   by the certification run over the sealed holdout, which makes ~120 live
   provider calls. §0 forbids live calls here, so it was not run, and this
   phase reports no precision figure at all rather than a favourable one from a
   smaller sample.
2. **The sample cannot support the claim.** 99.99% means one error in ten
   thousand accepted answers. Establishing that with any confidence needs a
   holdout on the order of 10^5 independently adjudicated cases. The sealed
   holdout is nowhere near that size, and no run of it — live or otherwise —
   could distinguish 99.99% from 99.9%.
3. **No user feedback contributes to it.** Ratings are not accuracy
   measurements, and `FORBIDDEN_UNLABELED_USES` names `accuracy_measurement`
   explicitly. A satisfaction figure is not a precision figure, and this build
   will not let one be reported as the other.

What *can* be said: on the 15 measured probes, officer selection and outcome
accuracy are 100%, invariants passed on 100% of executed analyses, there were
zero critical failures and zero critical checks without a signal. That is
conformance on a small sample. It is not 99.99% precision and is not offered as
such.

### 44. No live Anthropic calls were made and no credits were consumed

Zero provider calls in this entire phase. Every probe runs inside
`assert_no_provider_calls`, which makes an attempt raise — structural, not a
promise. The two verification modes that were run here are deterministic and
report `live calls 0`. `ANTHROPIC_API_KEY` was never requested, inspected,
printed or logged. **This process does not directly retrain Anthropic
foundation-model weights.**

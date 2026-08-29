# Master phase report — Parts A to F

Branch `claude/vigilant-darwin-eohyi1` · head `5cab573` · Alembic head `0021`

**3,750 backend tests pass**, 16 skipped, 0 failures. **254 front-end tests
pass.** `ruff`, `tsc` and `eslint` are clean. `docker compose config` is
valid.

**No live Anthropic calls ran. No credits were consumed. No API key was
requested or read.** Everything below was built and verified offline against
fake providers and deterministic fixtures.

---

## Part A — the teaching layer (§1-§64)

A governed Teaching Case library, hybrid retrieval, a strict planner
contract, model roles, and the Teaching Release that gates what production
may see.

**2,453 cases**, reported honestly:

> 2,453 teaching cases. **0 carry a named human approval and 0 are
> retrievable by production.** 0 were written by hand, 1,287 instantiated
> from reviewed blueprints, 1,083 migrated from existing corpora and 83
> derived from certified method contracts. No case is described as human
> reviewed without an approval record.

All 2,453 are `AUTO_VALIDATED`. Production retrieval takes `APPROVED` and
explicitly governed `SYSTEM_VALIDATED` only, so **the library currently
teaches production nothing** — which is the correct state until a person
approves cases, and is reported as such rather than dressed up.

## Part B — analytical judgment and the Investigation Factory (§65-§100)

The nine deterministic engines an investigation reasons with (evidence,
drivers, breadth, persistence, materiality, observations, blueprints,
hypotheses, contradictions), composed into one run with the interpretation
contract on top.

* **Hypothesis trees** with a **mandatory challenge pass**: a DAG node that
  claims completion with no Pass behind it is `FAILED`, and a task
  fingerprint deliberately excludes the task type so a CHALLENGE repeating
  an ANALYSIS collides with it — which is the exact case the rule is about.
* **Grounding**: every figure in the prose must trace to a registered
  validated fact, including figures embedded inside slot text.
* **Visualization Grammar and Visual Critic**: 15 semantic roles, 15 chart
  shapes, 12 checks between choosing a chart and drawing it — including
  whether its bars add up to the table beside it. 159 chart cases.
* **625 judgment blueprints** across four new families, and an inflation
  check that caught my own corpus repeating eight lessons across 150 cases.

## Part C — the AI Intelligence Studio (§101-§123)

Fifteen tabs, exactly the fifteen §213 names. Every object answers §117's
seven questions — what it is, why CreditProbe needs it, when it is used, how
it was validated, how it is performing, what is stale or failing, and which
release uses it — and an `explanation_audit` reports objects that do not.

Nothing in the Studio calls a provider. §120's holdout rules mean the sealed
answers are never shown; the import-graph test (`tests/factory/test_isolation.py`)
enforces that the backend cannot import the Intelligence Factory, and it
caught a real violation during this work, which is why the Wilson interval
maths now lives in `backend/validation/intervals.py`.

## Part D — integration and release gates (§124-§133)

14 release references with staleness, a 13-condition promotion gate whose
pass rate is reported but never consulted by `may_promote`, Demo Safe Mode,
the judgment bridge into the runtime executor, and 15 quality gates with 4
explicitly deferred so their absence from a green run is visible.

## Part E — agentic reliability and governed learning (§134-§177)

Four state machines over the agentic layer distinguishing `NOT_RUN`,
`RUNNING`, `COMPLETED_WITH_CASES`, `COMPLETED_NO_CASES`, `FAILED` and
`STALE`; a `GOOD`/`BAD` control on every answer; and the governed review
queue behind it. Unreviewed feedback changes nothing in production, and the
transition table refuses every path that skips a named reviewer.

## Part F — six Intelligence Dimensions and Investigation assurance (§178-§215)

### 1. The six dimensions

Understanding & Context (15), Analytical Design (20), Computation & Evidence
(25), Judgment & Presentation (20), Agentic Delivery (10), Reliability &
Experience (10). Weights versioned and validated to sum to 100.

### 2. Subcomponent mapping

**95 subcomponents**, each in exactly one dimension, each dimension holding
at least 12. A subcomponent nobody placed reports `""` rather than being
filed under whichever dimension sorts first.

### 3. Weight and gate policy

Critical gates → coverage gate → mandatory-skip gate → **only then** the
weighted score. 17 critical subcomponents. A dimension nothing measured is
excluded from numerator and denominator.

### 4. Assurance Record schema

`assurance_records` (migration 0021). Every §180 field. The verdict is
stored, not re-derived: recomputing an old record under today's weights
would restate history in the guise of reading it.

### 5. Turn-level assurance

One record per answered turn, sealed with a fingerprint over its checks. The
executor writes one on **every** answer — including clarifications,
unsupported responses and controlled failures.

### 6. Thread-level aggregation

The **worst** turn, never the mean, and `averaged: False` is in the payload
so nobody wires an average in later. A turn that failed and was later re-run
still failed.

### 7. Assurance statuses

`HIGH_ASSURANCE`, `VALIDATED`, `VALIDATED_WITH_LIMITATIONS`, `NEEDS_REVIEW`,
`FAILED`, `UNVERIFIED`, `STALE` — each with a sentence saying what it means.

### 8. Operational assurance versus reference match

Two payload fields, never merged. Where no approved reference exists the
payload explains that **in a sentence** rather than omitting a key. The
label is one constant so a screen cannot rename it locally.

### 9-12. Reviews, the panel, dimension panels, the timeline

Eight views as predicates over one row set; thirteen filters; a **table**,
not a card wall. "How CreditProbe performed" on the Investigation and in the
Studio. Always six dimension panels, including unmeasured ones. Turn-by-turn
timeline with six actions per turn.

### 13. Why points were lost

Every point not awarded carries the named check that took it. A **skipped**
check costs "coverage, not points" — said explicitly, so a reader does not
assume the score already accounts for it.

### 14. Feedback integration

Raw counters on the record. **There is no code path from a thumb to any
check, dimension, status or score** — enforced by a test that reads the
source of the one function that writes feedback and asserts it assigns to no
scoring column.

### 15. Rerun / version comparison

Five verdicts. Comparability is checked **before** anything is compared, and
two runs that did not both record a data version report
`CHANGED_DUE_TO_DATA`, because unknown is not "the same".

### 16. Studio dimension trends

Cohorts by release, Teaching Release, model route, scope, language, case
family, officer level and build. A bucket under 12 records reports **no
score** rather than a score with a footnote.

### 17-18. Trace and Calculation Pack

An `ASSURANCE SUMMARY` Trace node whose dimensions name the Trace nodes their
evidence came from. An `INVESTIGATION ASSURANCE` sheet in the Full
Calculation Pack, read from the Trace rather than re-scored — an export that
disagreed with the screen for the same run is the failure that avoids.
`FINAL RESULTS` remains last.

### 19. Permissions, retention, staleness

A review inherits the Investigation's access. Tenant is checked first and no
role widens it. "Not yours" and "does not exist" both return 404. Records are
immutable; staleness is computed at read time against the current runtime.

### 20. Tests

149 assurance tests (none skipped — the database tests genuinely ran) plus
§214's fourteen acceptance conditions as fourteen named tests. 3,750 backend
tests overall.

### 21. Browser acceptance

**Not run.** It needs a running stack and a browser, and is listed in the
quality gates' `DEFERRED` set so its absence from a green run is visible
rather than assumed. §211's presentation rules that can be tested without a
browser are covered by 15 node tests over `present.ts`, and the components
call those tested functions rather than repeating the logic.

### 22. Migrations

`0021_assurance_records`. Head is `0021`; the migration runs from an empty
database in the quality gates.

### 23. Docker

`docker compose config -q` passes. A **build and health run was not
performed** — it needs a Docker daemon with network access, and it is in the
`DEFERRED` set.

### 24. Raw feedback does not change validation scores

**Confirmed.** `store.note_feedback` increments `good_feedback_count` and
`bad_feedback_count` and touches nothing else. A test asserts, from the
function's own source, that it assigns to no scoring column; another writes a
record, leaves feedback, reads it back and asserts the status, score,
coverage, checks and fingerprint are byte-identical. §212's sixth rule
refuses any payload that claims otherwise.

### 25. No live Anthropic calls, no credits consumed

**Confirmed.** No provider call was made at any point in Parts A-F as built
here. No API key was requested, read or inspected. A test asserts that no
module in `backend.assurance` mentions `anthropic` or `get_provider` — an
assurance layer that cost money to run would not be run for the failures that
need it most. The live smoke test and sealed certification remain deferred
precisely because they spend real money.

---

## What is honestly incomplete

Three things, stated plainly rather than left for someone to discover.

**1. Assurance coverage is low today.** The collector reports only signals
the runtime actually produces; everything else is `SKIPPED`, not `PASS`. A
current record therefore reports low coverage and often `UNVERIFIED`. That is
an honest number about an under-instrumented product rather than a false one
about a working product, and the way it improves is by wiring more runtime
signals into `backend/assurance/collect.py` — never by marking uninstrumented
checks as passing.

**2. No teaching case carries a human approval.** All 2,453 are
`AUTO_VALIDATED` and none is retrievable by production. The library is built
and governed; it has not been reviewed.

**3. Browser acceptance and the Docker build/health run were not performed**,
for the reasons above. Both are named in the deferred set.

Nothing in this report should be read as a claim that CreditProbe has been
validated against independent reference answers. It has not. What exists is
**operational assurance** — a record of what each run could prove about
itself — kept deliberately and structurally separate from accuracy.

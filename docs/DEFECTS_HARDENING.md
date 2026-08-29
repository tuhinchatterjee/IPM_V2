# Defect register — agentic hardening phase

Every entry was found by running `scripts/agentic_baseline.py` against
`a89bbfc`, not by reading the code. Each names what was observed, what it
means, and where it is fixed.

Status values: **OPEN**, **FIXED** (with the commit), **ACCEPTED** (a real
limitation recorded rather than fixed in this phase).

---

## D1 — The Assurance Record is silently not written for any answer

**Severity: critical.** §210 requires a record for every answer. None is
being written.

**Observed.** Every one of the 15 baseline probes logged:

```
Could not assemble the assurance record:
'DimensionResult' object has no attribute 'measured'
```

**Cause.** `backend/assurance/collect.trace_summary` reads `result.measured`.
`DimensionResult` has no such attribute. The `AttributeError` propagates to
`executor._record_assurance`, which catches broadly — correctly, since an
assurance layer must never break an answer — logs a warning and returns. The
answer is fine. The record, the `assurance_summary` Trace node and the stored
row are all lost.

**Why it was invisible.** The `except` is right, the log is at WARNING, and
every test that exercised the record built it directly rather than through
the executor. The one path nobody tested was the one production uses.

**Status: FIXED** — see D2, which is the same root cause.

---

## D2 — Every stored dimension reports "not measured"

**Severity: high.** The six dimension panels on every review render as
unmeasured regardless of what ran.

**Observed.** `DimensionResult.to_dict()` emits `score`, `coverage_pct`,
`checks_run`, `passed`, `warnings`, `failed`, `skipped` — and never
`measured`. Four modules read `stored.get("measured")`:
`review.py:176`, `review.py:210`, `reviews.py:258`, `comparison.py:157`,
plus `store.py:486`. All of them therefore see `False`.

**Effect.** The compact dimension strip shows six "not measured" cells on a
record where every check passed; `comparison.dimension_diff` reports
`lost_coverage` for dimensions that never lost anything.

**Status: FIXED**

---

## D3 — Orchestration never engages on an interactive turn

**Severity: critical for this phase.** This is exactly §3's "a different
officer badge is not proof of a different execution path".

**Observed.** All 15 probes: `specialists = 0`, `task_count = 0`,
`orchestrated = False`. That includes thread E, "Review the latest portfolio
and tell me everything that genuinely requires CRO attention", which selected
**officer level 4, Chief Orchestrator** and then ran no orchestrator, no
specialist and no task.

**What the divergence check says.** `MATERIAL`, with `monotonic: False`. It
reports MATERIAL only because datasets, tool calls and plan steps differ
along the *deterministic* path — not because any agent ran. The badge
currently rides on work the deterministic planner did anyway.

**Status: see the hardening work; recorded honestly in the final report.**

---

## D4 — The two broad investigations execute no analysis at all

**Severity: high.**

**Observed.** Thread D ("Something seems wrong with Contracting. Investigate
it.") and thread E (portfolio review) both classify as
`CONVERSATIONAL_NO_ANALYSIS`: `executed = false`, `datasets = 0`,
`plan_steps = 0`. §28 expects coordinated bounded specialist work with an
evidence-backed conclusion from both.

**Status: OPEN — recorded in the final report.**

---

## D5 — A metadata answer reports no datasets

**Severity: medium.**

**Observed.** Thread A ("What ratings data do you have?") answers, and
reports `datasets = 0`, so `flows.classify` files it under
`CONVERSATIONAL_NO_ANALYSIS` rather than `METADATA_DISCOVERY`. A catalogue
answer that does not say which catalogue it read cannot be checked against
the catalogue.

**Status: OPEN.**

---

## D6 — Officer selection is one level high on the two-domain case

**Severity: medium.**

**Observed.** Thread C ("Which customers had a rating downgrade and an
increase in ECL over the latest year?") selects **level 3, Portfolio Risk
Lead**. §28 C expects **level 2, Senior Credit Officer**: two domains and a
borrower-grain result is a comparison, not a portfolio review.

Baseline officer accuracy: **83.3%** (5 of 6 scored).

**Status: OPEN.**

---

## D7 — Invariants pass on none of the executed analyses

**Severity: high.**

**Observed.** Three probes executed an analysis. `invariants_passed` is
false or absent on all three, so the baseline reports **0%**.

Either the invariants genuinely do not hold, or the signal is not being
surfaced onto `answered.invariants` in a shape the collector reads. The
distinction matters and the baseline cannot tell them apart, which is itself
a finding: a check whose failure and whose absence look identical is not a
check.

**Status: OPEN.**

---

## D8 — The Coverage Map claims more than the collector emits

**Severity: high — and it is a defect in the map, not the product.**

**Observed.** `coverage.summary()` reports **68 of 95 subcomponents wired
(71.6%)**. The probes observe a mean assurance coverage of **9.5%**. The map
is describing an intention.

A coverage map that overstates instrumentation is worse than none: it reports
the problem as solved. The map and the collector must be reconciled, and the
honest direction is to wire the collector — not to quietly change the word
`WIRED` to `PLANNED` and call the number better.

**Status: OPEN — the central work of §19.**

---

## D9 — 356 mandatory checks unresolved across 15 probes

**Severity: high.** Roughly 24 per turn, out of 26 mandatory subcomponents.

Every record is therefore `UNVERIFIED` with no score, which is the correct
and honest outcome given the instrumentation — and is exactly why the number
is worth fixing rather than reinterpreting.

**Status: OPEN — the same work as D8.**

---

## D10 — Project parity is unproven

**Severity: high.** §6 requires a Project Investigation to use the same
intelligence architecture as a Cockpit one.

**Observed.** All six Project threads complete, and all six run no analysis,
no specialist and no task — the same as their Cockpit equivalents, which also
run none. The two are equal, and equally empty. That is not the parity §6
asks to be proved.

A separate finding on the way in: `project_id` is an integer foreign key
throughout the platform, and passing a string reaches an `INSERT` before
failing. The harness now creates a real Project row.

**Status: OPEN.**

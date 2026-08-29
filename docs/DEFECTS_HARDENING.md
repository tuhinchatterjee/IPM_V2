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

---

## D11 — `build_info().git_sha` has never existed

**Severity: high.** Four call sites read it. Three were inside a swallowing
`except`, and the fourth used `getattr(build_info(), "git_sha", "")`, which
returned `""` forever rather than raising.

**Effect.** Every Assurance Record and every feedback item recorded **no
build**. The build staleness axis could therefore never fire, and no feedback
item was reproducible — the build is precisely the field that turns an
opinion into a bug report.

The attribute is `.sha`.

**Status: FIXED.**

---

## D12 — The Evidence Fact Graph registered zero facts, always

**Severity: critical.** Figure grounding — §79's whole mechanism — had
nothing to ground against.

**Cause.** `judgment_bridge.facts_from` filtered result columns on
`c.get("kind")`. The presentation contract calls that field `semantic`;
nothing in it has `kind`. The filter matched nothing, so no measure was ever
turned into a fact, on any analysis, ever.

**Evidence.** Before: `{'registered': 0, 'usable': 0}`. After: `{'registered':
45, 'usable': 45}` on the sample analysis.

**Status: FIXED** (both keys accepted, so an older contract shape still
works).

---

## D14 — The stage sequence contradicted the runtime

**Severity: medium — and it made the working indicator lie.**

`stages.SEQUENCE` placed `COORDINATING` **before** `CALCULATING`. The runtime
coordinates **after** the first analysis, because specialists are selected
from the reading and the reading does not exist until something has run. So
every coordinated run attempted a backwards transition, `can_move` refused
it, and the run stayed on `CALCULATING` while four specialists worked — the
screen said "Running governed calculations" throughout the coordination it
was supposed to be reporting.

§5: "The UI must truthfully reflect backend state." The sequence now follows
the runtime.

A second, related case: specialist sub-analyses report `CALCULATING` from
inside `COORDINATING`. That is a nested step, not a regression — the run
really is coordinating and a specialist really is calculating — so
`runs.advance(..., nested=True)` records it as detail and holds the stage
instead of logging a refusal per specialist.

**Status: FIXED.**

---

## D18 — The assurance record described a sub-analysis, not the user's turn

**Severity: high.**

`interactive.run`'s `ask` closure answers the user's question **and** every
specialist sub-question during coordination, and it assigned
`found.answered` unconditionally. So after coordination `found.answered`
held the **last specialist's** result. Conversation memory was written from
it, and the Assurance Record was built from it — describing an analysis the
user never asked for.

**Status: FIXED** — only the user's own question is kept.

---

## D16 — A broad investigation left a Trace nobody could enter

**Severity: medium.**

`assembly.from_handler` — the path a broad or catalogue-answered
investigation takes — never wrote the `question` or `intent` nodes that every
other assembly path opens with. A portfolio review, the most complex thing
the product does, produced a Trace of three nodes: the judgment block, the
presentability gate and the assurance summary. No question, no reading, no
capability.

Found the moment `audit_completeness` was wired.

**Status: FIXED.**

---

## D19 — A coordinated review reports nothing about what its specialists read

**Severity: high. OPEN.**

A coordinated portfolio review reports **zero datasets** and **zero tool
calls** on its own Investigation, while a single-dataset query reports one
dataset and ten. Not because it read less — it ran six governed probes across
four specialists — but because the specialist sub-analyses are persisted as
**separate Investigations**, and the coordinating Investigation does not
aggregate what they touched.

**Effect.** The Trace for a portfolio review cannot say which data it read.
For the most consequential answer in the product, the lineage question has no
answer.

**How it is held open.** `divergence.unmeasured_axes` separates "did less
work" from "recorded nothing to compare", so the instrument does not report
this as an escalation that shrank. A test asserts the current behaviour
explicitly, so closing the gap breaks it loudly:
`test_the_coordinated_run_does_not_report_what_its_specialists_touched`.

---

## D15 — A specialist sub-analysis returns unordered account rows

**Severity: high (Tier 1 class). FIXED — see `docs/DEFECTS_FINAL.md` for the
full closure record. The text below is left as it was written, because a defect
log that is edited to match the fix stops being evidence of what was found.**

Reproducer: *"Show days past due and the NPL ratio for the portfolio at the
latest published period."*

The question is portfolio-level. The analysis returns **account-grain** rows,
in no order, and the request-derived `ordering` invariant fails: *"The answer
claims to be ranked by days past due and row 4 is larger than row 3."*

**Containment.** This is caught, not shown. The invariant fails, the
presentability gate returns WITHHOLD, and the turn ends `failed` rather than
displaying a wrong answer. The governed pipeline behaved exactly as designed.

**What is still wrong.** A portfolio-level question should not produce
account-grain rows, and the fix is in grain selection rather than in the
gate. Left OPEN rather than patched late in this phase: a planner change made
under time pressure to clear a test is how the next defect gets shipped.

---

## D17 — Table columns are not in the governed rank order

**Severity: low. OPEN.**

`table_column_ordering` fails on some results: the presentation contract
assigns each column a `rank`, and the emitted order does not follow it.
Cosmetic rather than incorrect, and reported rather than hidden.

---

## D20 — A coordinated review registers no evidence facts

**Severity: high. OPEN.**

The broad investigation quotes real figures ("500 customers where internal
rating was downgraded") and `evidence_fact_graph` FAILs, because
`facts_from` needs a single `runtime` result and a coordinated review has
none — its figures come from probe results.

The consequence is the one D12 was about, in a different place: for the
answers where grounding matters most, there is no fact graph behind the
prose. Reported as a FAIL rather than exempted, so it stays visible.

---

## D21 — Nine of §18's fifteen risk classes have no teaching cases at all

**Severity: high. OPEN — and the finding is the point.**

Building the review pack over the live library covers **6 of 15** classes.
These nine have **zero** eligible cases:

`permission_tenant_safety`, `prompt_injection`, `agentic_cockpit`,
`agentic_project`, `officer_selection`, `agent_selection`,
`proactive_review`, `risk_cases`, `workflow_approval`.

**What it means.** The 2,453-case library teaches analytical questions. It
teaches CreditProbe nothing about the agentic layer, nothing about
permission and tenant safety, and nothing about refusing an injected
instruction — the classes where a wrong answer is least recoverable. §25 asks
for exactly these in the development corpus and they are not there.

**Why it is not being fixed by generating them.** Cases for these classes
have to be written against real governed behaviour and reviewed by a person.
Generating 200 more AUTO_VALIDATED cases would raise a count and change
nothing: none of them would be retrievable, and none would have been read.

The pack reports `classes_empty` rather than quietly returning six classes,
so the gap is a work list instead of an absence.

---

## D22 — "unsupported" was not in the contracted-outcome set

**Severity: medium.**

`signals.controlled_error_handling` listed four contracted outcomes:
`succeeded`, `partial`, `needs_clarification`, `rejected`, `failed`. A
governed refusal — which is what a prompt-injection attempt correctly
produces — has status `unsupported`, and was therefore reported as an
**uncontracted state**: the safest possible behaviour scored as a failure of
error handling.

Found by the §33 injection suite on its first run.

**Status: FIXED.**

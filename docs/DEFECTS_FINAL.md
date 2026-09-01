# Defect closure — final consolidation phase

Every defect that was OPEN at `e967c6a` (recorded in
`docs/PHASE_START_SNAPSHOT.md` §4), with the record §3 asks for: id, severity,
affected flow, user-visible consequence, root cause, containment, permanent
fix, regression test, independent test, Assurance check, Trace evidence, and
status.

The rule this phase works under, quoted from the brief:

> Do not clear a defect merely because an invariant blocks the answer.
> Containment is not the same as correction.

---

## D15 — a portfolio question returned account-grain rows

| Field | Record |
| --- | --- |
| **Severity** | High — Tier 1 (wrong grain is one of §41's blocking classes) |
| **Affected flow** | Simple analysis, and any specialist sub-analysis inside a coordinated review |
| **Status** | **FIXED** |

**Reproducer.** *"Show days past due and the NPL ratio for the portfolio at the
latest published period."*

**User-visible consequence.** Before the fix, the turn ended `failed`: the
request-derived `ordering` invariant failed — *"The answer claims to be ranked
by days past due and row 4 is larger than row 3"* — and the presentability gate
returned WITHHOLD. The user got no answer to a question the system could
answer. Had the ten account rows happened to come back in descending DPD order,
they would have been **displayed**, and a reader scanning the first row would
have read one account's arrears as the book's.

**Root cause.** Two separate mistakes that compounded.

1. `_shape` decided the analysis was a `RANKING` because
   `reading.operation == "list"`. It never looked at the grain, so there was
   nothing to tell it that there is no such thing as the ten largest
   portfolios.
2. The planner had exactly one field called `grain`, and it meant the key the
   SOURCE dataset is keyed on. It was reported — in Scope, on the Trace, in the
   Assurance record and in the proof probe — as though it described the answer.
   A by-sector aggregate over a facility-keyed table declared itself
   `facility`, which is true of what it scanned and false of what it returned.
   With no field anywhere meaning "what one row of this answer IS", nothing
   could have detected the disagreement.

**Containment (what was there before).** The `ordering` invariant and the
client-presentability gate. Both worked. Neither is a fix: they caught one
symptom of the wrong grain on one question.

**Permanent fix.** A new governed module, `backend/orchestration/grain.py`.

- A ladder — `PORTFOLIO < SEGMENT < CUSTOMER < FACILITY < RECORD` — with
  `PERIOD` deliberately off it, because a time series is a portfolio answer
  repeated per period rather than a sixth level of entity detail.
- `requested()` infers the OUTPUT grain from the objective, in a fixed
  precedence: a carried population, then an explicit facility noun, then an
  explicit customer noun, then a resolved breakdown dimension, then an explicit
  portfolio noun, then the source dataset's own grain marked **not explicit**.
  The order is the design: it is what makes *"total EAD by sector for the
  portfolio"* a sector answer and *"the five largest Real Estate customers in
  the portfolio"* a customer answer, when both sentences name the portfolio.
- Asking for a number of rows — "the top five" — is asking for five of
  something, so it can never be read as a portfolio question however many
  portfolio nouns the sentence carries.
- `_shape` is corrected: a portfolio request is never planned as a RANKING.
- `group_by` is driven by the requested grain when the request was explicit,
  so *"expand the analysis to customer level"* groups by `customer_id` rather
  than re-answering the previous turn's sector breakdown.
- `declared()` reads the emitted grain off the **grouping the plan actually
  built**, not off intent, so a plan that meant to answer per customer and
  grouped by nothing is caught saying `portfolio`.
- A `Contract` carries want, got, source grain, the unique output keys, the
  aggregations inserted, and the enrichments that were rolled up before joining.
  It refuses to plan at all when an explicit request and the emitted grain
  disagree — the earliest point at which a wrong grain can fail.

**Where an unstated grain is treated honestly.** When the question did not say
what one row should be, there is nothing to violate: the plan's own choice
becomes the declaration and is recorded as *unstated*. Enforcing the fallback
would have refused *"what is the total EAD in the latest quarter?"* — a
portfolio question the dataset fallback reads as facility — which is the same
defect pointing the other way.

**Duplicate amplification.** `multi._join_edge` already inserted an
`AGGREGATE_BEFORE_JOIN` step whenever a hop would multiply the book. What was
missing was any record of it reaching the answer. `_rolled_up_before_join`
resolves those steps through the operation graph — the aggregate names its
input, the input is the SCAN, the SCAN names the dataset — so the contract can
say which source was made safe, and the Trace can show it.

**Unique output keys.** `_grain_keys` takes the identity of a row at the
emitted grain rather than the whole grouping. *"One row per customer, broken
down by sector"* groups by both, and testing the pair for uniqueness would pass
a result where one customer appears under two sectors — exactly the
amplification the check exists to find.

**Regression tests.** `tests/orchestration/test_grain.py`, 24 tests. §4's five
mandatory classes each drive the real governed path through `agentic.run`:

| Class | Question | Result |
| --- | --- | --- |
| Portfolio | D15's exact reproducer | `succeeded`, `output_grain == portfolio`, **1 row** |
| Segment | "Show IFRS 9 ECL by sector for the latest quarter." | `segment`, keys `("sector",)`, 15 rows |
| Customer | "Show the ten largest customers by IFRS 9 EAD…" | `customer`, keys `("customer_id",)`, 10 rows |
| Facility | "List the facilities in Stage 3…" | `facility`, keys `("account_id",)`, 10 rows |
| Broad investigation | "Review the latest portfolio…" | every sub-analysis that declares a grain satisfies its own objective |

**Independent test.** The postconditions are tested against synthetic runtimes
rather than against the planner that produced them, so a planner that agreed
with itself could not pass: `test_a_portfolio_answer_with_many_rows_fails_the_postcondition`
and `test_a_repeated_key_fails_the_grain_postcondition` build a two-row result
by hand and assert the invariant report is not `ok`.

**Assurance check.** `signals.grain_selection` no longer passes on the presence
of any grain string. It reads the contract and PASSes only when the grain the
objective asked for and the grain the plan emitted agree; with no contract it
reports the source grain and says there is no contract.

**Trace evidence.** The `plan` node carries `output_grain` and the full
`grain_contract` — including the sentence explaining why the answer is at that
grain and which sources were rolled up before joining. `ScopeFrame` carries
`grain` (now the output grain) and `grain_because`, and both survive the round
trip through conversation state, so the next turn can see what the last one
answered.

**A wrong-grain result fails before display**, at three points, in this order:
the planner refuses to build it; the `output_grain` invariant fails a portfolio
answer with more than one row; the `unique_grain_key` invariant fails a repeated
identity. Any of the three routes the turn into the presentability gate.

**Measured.** `3,859 passed, 16 skipped, 0 failed` on the full backend suite,
against `3,835 passed, 16 skipped` at phase start. No test was weakened to
accommodate the change.

**One test was corrected rather than the code**:
`tests/proof/test_governance.py::test_a_pack_over_cases_this_test_creates_has_rows`
asked the live review pack for three cases it had just created. The pack takes
four cases per risk class, so against a seeded library of 2,453 the three
fixtures never make the cut — it passed only while the library happened to be
empty. It now asserts of the service path what is true whatever the library
holds (it returns rows, it approves nothing) and asserts the fixtures against a
pack built over exactly them.

---

## D4 — a broad investigation reported executing nothing

| Field | Record |
| --- | --- |
| **Severity** | High |
| **Affected flow** | Broad investigation; agentic coordinated review, Cockpit and Project |
| **Status** | **FIXED** |

**User-visible consequence.** A portfolio review displayed a Chief
Orchestrator, five specialists and five tasks, and reported `executed = false`,
`datasets = 0`, `plan_steps = 0`. `flows.classify` filed it as *conversational,
no analysis ran* — which exempted it from every Assurance check that matters
most for exactly that kind of work.

**Root cause.** It was running six governed analyses the whole time.
`investigation.run` drives each probe through `answer_one`, the same path a
user's question takes, and then kept only the headline sentence of each answer.
The composed `HandlerResult` had `execution="metadata"` — the default — so the
Trace consistency contract concluded nothing had been calculated.

**Permanent fix.** `investigation.Composition`: a record of what the
sub-analyses did, folded in as each one returns. Datasets, periods, grains,
concepts, rows, invariants checked and failed, IR validations, compiled
queries, governed reads, grain contracts met, evidence facts and Trace node
ids. `execution` becomes `composed_analysis` when at least one sub-analysis
produced a result, and `metadata` when none did — the honest distinction, kept.

Nothing is inferred: `ran` and `attempted` are separate numbers, and a probe
that produced no runtime contributes nothing to any of them.

**Measured.** The portfolio review now reports 6 analyses over 4 datasets
(`portfolio_facility`, `ifrs9_staging`, `customer_ratings`,
`facility_delinquency`), 2 periods, 3 distinct output grains, 1,011 rows,
20 invariants checked and 0 failed.

**Regression test.** `test_d4_a_broad_investigation_executes_governed_analyses`.
**Assurance check.** `Ctx.composed` and the composed branches of
`concept_selection`, `dataset_selection`, `period_selection`,
`grain_selection`, `analytical_ir`, `generated_query` and
`privacy_tenant_safety`. `Ctx.executed` was deliberately *not* widened — every
reader gated on it goes on to read `ctx.build`, which a composed answer does
not have, so widening it would have turned a fleet of honest NOT_APPLICABLEs
into a fleet of FAILs.

---

## D19 — a coordinated review reported nothing about what its specialists read

| Field | Record |
| --- | --- |
| **Severity** | Medium |
| **Affected flow** | Agentic coordinated review |
| **Status** | **FIXED** — same root cause as D4 |

**Consequence.** The Trace for a portfolio review could not say which data it
read, and the divergence instrument had to report `dataset_count` as
*unmeasured* rather than as a real comparison — so the officer ladder could not
be proven material on that axis.

**Fix.** The composition, above. The probe and the Assurance `Ctx` both read it.

**Regression tests.** `test_d19_the_review_reports_what_its_sub_analyses_read`
and `test_d19_every_sub_analysis_went_through_the_governed_path` — the second
because a composition that counted analyses without counting *how they ran*
would be a larger claim resting on the same absence of evidence.

**The holding test was closed, not deleted.**
`test_the_coordinated_run_does_not_report_what_its_specialists_touched`
asserted the broken behaviour so that fixing it would break the test loudly. It
did. It is now
`test_the_coordinated_run_reports_what_its_specialists_touched`.

---

## D20 — a coordinated review registered no evidence facts

| Field | Record |
| --- | --- |
| **Severity** | Medium |
| **Affected flow** | Agentic coordinated review |
| **Status** | **FIXED** |

**Consequence.** Nothing in a review's synthesis was grounded against a
registered fact, because there were none to ground against.

**Root cause.** `judgment_bridge.assess` builds the Evidence Fact Graph from
`answered.runtime` and `answered.build`. A composed answer has neither.

**Fix.** Each sub-analysis's fact graph is built where the analysis ran, by the
same `facts_from` used for a single answer, and the counts are carried on the
composition. `assess` uses them when its own graph is empty, and labels them:
*"Registered across N governed sub-analyses, not by the synthesis itself."*

**Measured.** 1,820 facts registered, 1,820 usable, 0 refused, across 6
sub-analyses. **Regression test.**
`test_d20_the_review_registers_evidence_facts`.

---

## D5 — a metadata answer reported no datasets

| Field | Record |
| --- | --- |
| **Severity** | Medium |
| **Affected flow** | Metadata / discovery |
| **Status** | **FIXED** |

**Consequence.** *"What ratings data do you have?"* answered correctly and
reported `datasets = 0`, so it was classified `CONVERSATIONAL_NO_ANALYSIS`
rather than `METADATA_DISCOVERY`. A catalogue answer that cannot say which
catalogue it read cannot be checked against the catalogue.

**Root cause.** `data_discovery` records the datasets it consulted in its own
`detail` block. Nothing carried them up: the probe and the Assurance `Ctx` both
looked only at `build.datasets`, and a catalogue answer has no build.

**Fix.** `probe._consulted` and the equivalent branch in `Ctx.datasets` read
the handler's detail. Kept as *consulted* rather than merged into *read*: the
row count stays `None`, and `executed` stays `False`, because no rows were
read. **Measured.** 6 consulted datasets; flow `METADATA_DISCOVERY`.
**Regression test.** `test_d5_a_catalogue_answer_says_which_catalogue_it_read`.

---

## D7 — invariants passed on none of the executed analyses

| Field | Record |
| --- | --- |
| **Severity** | High as reported; a measurement defect in fact |
| **Affected flow** | Every executed analysis |
| **Status** | **FIXED** |

D7 was raised as *"either the invariants genuinely do not hold, or the signal
is not being surfaced in a shape the collector reads — and the baseline cannot
tell them apart, which is itself a finding."* It was the second.

**Root cause.** `invariants.Report` exposes `ok`. The probe read `passed`,
which is on no invariant report anywhere. Every executed analysis therefore
reported *not measured*, and the baseline printed **0%** over runs where five
checks had been compiled and all five had held.

**Fix.** Read `ok`, and only when checks were actually compiled — a report with
no checks stays `None`, because a check that did not run is not a check that
passed. The composed case reports `Composition.invariants_passed`, which
applies the same rule.

**Measured.** Invariants now report `True` on every executed probe in the
proof set; a metadata turn reports `None`. **Regression tests.**
`test_d7_an_executed_analysis_reports_whether_its_invariants_held` and
`test_d7_a_turn_that_checked_nothing_reports_none_not_false`.

---

## D6 — officer selection one level high on the two-domain case

| Field | Record |
| --- | --- |
| **Severity** | Medium |
| **Affected flow** | Multi-domain analysis |
| **Status** | **FIXED** |

**Consequence.** *"Which customers had a rating downgrade and an increase in
ECL over the latest year?"* selected **level 3, Portfolio Risk Lead**. It is a
borrower comparison; §4 defines level 3 as *"a segment or the whole
portfolio"*.

**Root cause.** An asymmetry. `floor_for(reading)` lets the grain RAISE the
level — §4 defines the top two levels by grain — but nothing let the grain cap
it, so the score alone could push a borrower-grain comparison past the point
where the level still means what §4 says. The question scores 10 (three
datasets, four concepts, two periods, a rating migration, two domains, two
specialists) against a level-3 floor of 9. Every signal is real; none of them
makes the work portfolio work.

**Permanent fix.** `officers.ceiling_for(reading)`, the symmetric half of
`floor_for`. A customer- or facility-grain request that is not an open-ended
look-around is capped at Senior Credit Officer. Two things lift the ceiling and
both are genuine widenings rather than measures of difficulty: three or more
governed checks (`BROAD_AT`), and coordination, which `select` applies
afterwards as a floor of its own so three specialists still reach the Chief
Orchestrator. A reading with no grain sets no ceiling — an unknown shape is not
a small one.

**Measured.** Level **2** for the two-domain case; level 3 still holds for the
segment investigation and level 4 for the coordinated review. **Regression
tests.** `test_d6_a_borrower_grain_comparison_is_a_senior_credit_officer`,
`test_d6_a_segment_investigation_is_still_a_portfolio_risk_lead`,
`test_d6_a_coordinated_review_is_still_a_chief_orchestrator` — the last two
because a ceiling that demoted the levels the grain earns would trade one
defect for two.

---

## D17 — table columns not in governed rank order

| Field | Record |
| --- | --- |
| **Severity** | Low as reported; a defect in the check |
| **Affected flow** | Two-period cohort results |
| **Status** | **FIXED** |

**Root cause.** The check read `presentation.contract`, whose own docstring
says it returns the columns *in the order the runtime produced*, because the
rows are keyed by name and nothing downstream should have to care.
`presentation.schema` is the ordered one, and it is what the table renders
from. So the check was reporting the compiler's emission order as the reader's
order and calling the difference a presentation fault.

**Fix.** Reading `schema` instead would have made the check vacuous — it sorts,
so its ranks are always sorted. The check now asserts what the ordering is
*for*, over the order the reader actually gets: every column the analysis
produced still reaches them, the ranks do not go backwards, and the subject is
first. **Measured.** PASS on all four probe shapes, including the two-period
cohort it used to fail on. **Regression test.**
`test_d17_columns_reach_the_reader_in_governed_rank_order`, parameterised over
the four shapes.

---

## D21 — nine of fifteen review-pack risk classes had no cases

| Field | Record |
| --- | --- |
| **Severity** | Medium |
| **Affected flow** | §18's human-review pack |
| **Status** | **FIXED** |

**Consequence.** A pack that looked complete — eleven populated rows and four
silent gaps — showed a reviewer nothing at all about permissions, prompt
injection, Cockpit or Project agentic flows, officer selection, agent
selection, proactive review, Risk Cases or workflow approval.

**Two root causes, both addressed.**

1. **Seven classes had no cases anywhere.** The teaching families cover
   analytical work; nothing in them exercises a permission boundary, an
   injected instruction, a proactive Risk Case or an approval gate. Those are
   not analytical questions — they are the questions about what CreditProbe
   must refuse to do.
2. **Two classes had cases that did not carry the tag.** `classify` reads the
   tag `agentic`; the canonical builder tags cases with the family name, so
   twenty-four `AGENTIC_ORCHESTRATION` cases were tagged
   `agentic_orchestration` and a set-membership test matched none of them.

**Permanent fix.** `intelligence_factory/teaching/safety.py`: nine reviewed
blueprints, eight cases each, seventy-two in total, each instantiated over the
governed vocabulary and each recording the *plausible substitute* as a
forbidden behaviour — because a cross-tenant read returns a perfectly formed
table and an injected instruction produces a fluent, obedient answer.

And `review_pack.classify` now honours an explicit declaration: a case whose
tags name exactly one known class id is filed there. The keyword rules are
deliberately **not** loosened to substring matching — that would file every
`agent_selection` case under `agentic_cockpit`, and both would look populated.

**Measured.** All fifteen classes populated, none below the pack's `PER_CLASS`
of four. Library **2,534** cases, still **0** human-approved and **0**
production-retrievable — the seventy-two new cases are `AUTO_VALIDATED`
`BLUEPRINT` cases written so that a reviewer has something to review.

**Regression tests.** `test_d21_every_review_pack_risk_class_has_cases`
(asserted over the corpus the factory offers, not over whatever the database
holds — the suite truncates `teaching_cases`),
`test_d21_a_case_may_declare_its_own_risk_class`,
`test_d21_the_safety_curriculum_covers_every_empty_class`,
`test_d21_the_safety_cases_approve_nothing`.

---

## Defects re-verified rather than assumed: D8, D9, D10

Recorded OPEN in `docs/DEFECTS_HARDENING.md`, and closed by the hardening work
itself rather than by a separate fix. Re-measured in this phase:

| ID | What it was | Now |
| --- | --- | --- |
| D8 | The Coverage Map claimed more than the collector emitted | 72 of 95 wired, and `coverage.wired() == set(signals.READERS)` is enforced by a bidirectional test |
| D9 | 356 mandatory checks unresolved across 15 probes | 0 |
| D10 | Project parity unproven | Six Project probes, asserted against their Cockpit equivalents |

---

## Summary

| ID | Severity | Status |
| --- | --- | --- |
| D4 | High | FIXED |
| D5 | Medium | FIXED |
| D6 | Medium | FIXED |
| D7 | High | FIXED |
| D15 | High (Tier 1) | FIXED |
| D17 | Low | FIXED |
| D19 | Medium | FIXED |
| D20 | Medium | FIXED |
| D21 | Medium | FIXED |

**Nine of nine closed. No defect is left open at the end of §3.** The
limitations that remain — proactive review, Risk Cases and worker health
reporting NOT_AVAILABLE in the Assurance record, the Project Plan of §8, and
Arabic/RTL — are unbuilt capability rather than defective behaviour, and are
recorded as limitations in the final report rather than as cleared defects.

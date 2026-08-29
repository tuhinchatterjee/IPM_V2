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

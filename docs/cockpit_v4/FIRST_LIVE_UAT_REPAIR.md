# Round H — first live UAT: what it found, and what was repaired

The first live `claude-opus-5` UAT ran the approved twenty-eight-run queue on
a Mac and committed **USD 8.886715**. No provider call was made in this
repair round and no further spend was incurred.

The first-pass evidence is preserved outside the repository, byte for byte:

| File | SHA256 |
|---|---|
| `live_uat-first-pass.json` | `eccf9ea491edee724dccd60753c5a01dcfa817666de9fa053e4d07a1f3860b21` |
| `live-first-pass.sqlite3` | `320d717cfeea1a644b383b679edd705d421822a7ade6c6d1911b568345fe6b5f` |

`docs/cockpit_v4/evidence/live_uat.json` is first-pass evidence and is never
rewritten. A regrade writes `live_uat_first_pass_rejudge.json` and labels
itself **RECONSTRUCTED FROM SETTLED FIRST-PASS RUNS · NO PROVIDER CALL**.

---

## The six defects

### H-LIVE-01 — the harness read a field the store does not have

`capture()` used `getattr(record, "response", None) or {}`. `RunRecord`
declares `final_response` (`run_store.py:327`), the column is
`final_response` (`:71`), `get_run` populates it (`:675`) and the worker
settles `outcome.response` INTO it (`:717`). `response` is `Outcome`'s field
name — the worker's in-memory result — and a settled run is not read back
from it. Because `getattr` carried a default, the expression could only ever
be `{}`, silently: twenty-eight paid runs recorded a blank narrative, a
blank disposition, no claims, no charts and no clarification while every one
of those answers sat in `runs.final_response` in the same file.

### H-LIVE-02 — the reconciliation compared two keys that do not exist

`reconcile()` built its comparands from
`claim.get("canonical", claim.get("published"))`. `NumericClaim.to_dict`
(`contracts.py:940`) emits `claim_id`, `unit`, `evidence`,
`display_precision` and optionally `decimal_value` and `derivation`;
`orchestration` adds `display_value` (`:1638`). Every comparand was `None`.
**The first pass must not be described as independently numerically
reconciled.**

It now recovers the governed number from the stored artifact through the
product's own `derivation` module, joins to the oracle through the key and
value columns the matrix declares *before* the run, never parses a rounded
display string, and reports an oracle key the answer never published as
missing.

**Ten of the seventeen approved journeys carry an independent oracle** —
L01, L02, L04, L05, L08, L10, L11, L12, L15, L17. The other seven — L13,
L14, L16, L18, M02, M04, M05 — are graded on behaviour.

### H-LIVE-03 and H-LIVE-05 — one root cause

`envelope.classify` decides, from the question's words and before any model
call, whether a turn is analytical. `action_state.decide` used that bit to
choose the tool surface, and on a non-analytical turn whose product coverage
is "synopsis" it offered `finalize_response` **alone** and **required** it.

```
classify("wat is the toatl expsoure at defalt by secter this qtr")
    -> analytical=False, signals=()
classify("Which sectors are above the single-name limit?")
    -> analytical=False, signals=()
decide(analytical=False, product_tool_withheld=True)
    -> PRODUCT_HELP, tools=('finalize_response',),
       require='finalize_response'
```

The live analyst understood the typo-heavy question exactly — exposure at
default by sector for 2026Q2, mapped to `corp_facility_quarter.ead_sar_mn`
and `corp_borrower_quarter.sector`, `blocking_ambiguities=[]` — and then had
one tool and nothing that could run a query. It published PRODUCT_HELP /
unsupported and offered to proceed on permission. Not a failure of autonomy:
the only move the surface allowed. The catalogue index and canonical
semantics are in the opening packet on *every* turn, which is how it
produced correct mappings with no analysis tools at all.

The widening both `envelope.py` and `IntentEnvelope.escalate_to_analysis`
document was unreachable: `FLAT_INTENT_FIELDS` carries no `query_mode`, so
`finalize_response` cannot carry the declaration either. `execute_analysis`
is now offered there and nothing is required — submitting SQL *is* the
declaration, and `_do_execute` already adopts the analytical allowance
before it parses a field.

On the same surface the credit policy pack was attached only by
`context.finalization_system`, which `orchestration` applies only at
RESULT_READY. A PRODUCT_HELP turn publishes a user-facing answer and got no
policy at all — so the live answer said "There is no recorded single-name
policy limit in the Corporate Credit book". CP-1.1 exists, sets
`single_obligor_ead_sar_mn` to 25000, and `cp.retrieve` returns it for that
exact sentence. Retrieval was never broken; nothing consumed it. The pack
now reaches every turn that can call `finalize_response`. An action turn
still gets none: it holds no number, so a threshold in front of it compares
nothing.

### H-LIVE-04 — a ratio's denominator written as a percentage

The live table published `balance_total` as **19,619.22%** and `limit_total`
as **35,932.22%**. `Finalizer._units_for` read a derived claim's unit onto
*every* operand column of its derivation, and those two amounts appear in no
claim except as the denominator of a coverage percentage. `ecl_total` and
`ead_total` escaped only because direct claims had already named them in SAR
million and `setdefault` keeps the first answer.

`derivation` now declares which operations preserve their operands' unit —
`identity`, `sum`, `min`, `max`, `difference` do; `weighted_average` does for
its values and not its weights; `ratio`, `percentage`, `percentage_change`,
`share_of_total`, `count` and `rank` do not — and a test asserts every
operation is classified. Nothing anywhere knows the name `balance_total`.

### H-LIVE-06 — a correct policy number with no recorded provenance

How the analyst knew CP-1.1 in M05.2, established rather than guessed: that
turn executed, so its state was RESULT_READY, so `finalization_system`
attached `cp.synopsis("corporate")` — which carries CP-1.1's rule and its
25000 threshold verbatim. **Governed static context injected server-side**,
not a model prior, not inherited thread context, and not a tool retrieval,
which is why no retrieval appears in the messages.

The published answer now carries `policy_context` (pack, version, clauses
attached, thresholds in context) and `policy_citations`, both built from the
same deterministic retrieval. `_check_policy` gains one narrow branch: a
figure this book's pack sets, presented as a limit, with no clause of this
book cited anywhere, is refused with the correction to make. A threshold is
bound to the clause that sets it, not to a result cell — which is why the old
unbound-value warning could never have been the right instrument.

---

## The matrix, corrected against the runtime

| Entry | Was | Is | Proof |
|---|---|---|---|
| **L16** | true clarification | governed policy threshold, **answerable** | `cp.retrieve` → `["CP-1.1"]`; `sem.readiness` → `sufficient=True`, `{limit, sector}` resolved; CP-1.1 reads "Exposure is measured as EAD, funded and unfunded together" |
| **L19** *(new)* | — | true clarification | `sem.readiness("Which sectors have the largest exposure?")` → `sufficient=False`, `exposure` undecided between `ead_sar_mn`, `limit_sar_mn`, `drawn_sar_mn`; the three rank the sectors differently; no clause reaches it |
| **M05** | narrowing across a clarification | **retired**, kept verbatim | Turn 2 ("Exposure at default") does not answer the clarification turn 1 asked, which was about the breach test |
| **M06** *(new)* | — | clarification answered, then narrowing | Turn 1 is L19; turn 2 is one of the readings on the table |
| **M07** *(new)* | — | new question after a clarification | Turn 2 names a measure the clarification never offered |

L16's honest answer is **none**: no borrower breaches CP-1.1 — the largest
single obligor holds SAR 14,432.08 million of EAD at 2026Q2 against a SAR
25,000 million limit.

**The first-pass M05 result is evidence neither way** for
clarification-answer projection. `grade()` refuses to grade a retired
journey against the behaviour it was written for.

---

## What still needs a paid retest

Everything behavioural. These tests prove mechanics and prompt propagation
with a scripted provider. What a live `claude-opus-5` does with the opened
surface, the attached policy pack and the corrected chains is **not**
established here.

---

## Out of scope, logged

`D-003` — `catalog._SESSIONS` evicts the session it is about to return.
Pre-existing, reproducible on a clean `ac315dd`, out of this round's scope on
instruction.


---

# Offline rejudge closure

The repaired rejudge was run against the real preserved 28-run evidence and
surfaced four more items.

## CLOSURE-01 — a facility count published as a borrower count

L18's result was right: one row per borrower, 5,412 of them. The narrative
said "2 borrowers carry facilities in 2026Q2" from a claim whose unit was
`borrowers`, whose operation was `identity`, and whose cell was
`facility_count` at r0. The first borrower held two facilities.

`da974348` blocks no part of it: that fix governs operations which CHANGE a
unit, `identity` preserves it, and both values are COUNT class. Nothing
asked WHAT WAS BEING COUNTED. `display.entity_of` now answers that from the
words of a phrase, and the finalizer refuses a claim whose unit names one
entity while the column it reads names another — for a direct cell and for
a derivation's operands alike.

The refusal names the governed alternatives, and one of them did not work:
`count` converted every cell to a Decimal, so counting borrowers over
`borrower_name` failed with *"'Tuwaiq Gulf Energy' is not a number this can
compute with"*. `count` now resolves without converting.

**L18's UAT wording is revised.** A correct first submission is a pass. The
old wording read as requiring a failed attempt, which tests nothing.

## CLOSURE-02 — a movement described backwards

M04's final turn said past-due exposure went "from 8.08% of exposure to
8.42%" and then that "it has actually eased slightly".

`_check_movement` reads nothing about the analysis. It takes one sentence
naming a start and an end figure *through the claims the server computed*
and refuses it when the direction word contradicts the arithmetic. It fires
only on a sentence with exactly two numeric claims in the same unit, one
after "from" and one after "to", and direction words of exactly one sense.
"deteriorated" and "improved" are not in the vocabulary: the same word means
opposite arithmetic on ECL and on coverage.

## CLOSURE-03 — four false negatives in the oracle join

`reconciled_not_ok` listed L15, L12, L11, L08, L10. Only **L15** is a real
failure — that run published nothing.

| | declared | published |
|---|---|---|
| L12 | `coverage` | `cov_on_ead_pct`, and a percentage against a proportion |
| L11 | `coverage` | `coverage_on_ead_pct`, same conversion |
| L08 | `quarters` | `avg_quarters_in_stage` |
| L10 | key `product_region` | two governed columns, `product` and `region` |

The matrix now declares every governed name it accepts for the figure, the
conversion **each one** carries, and the key shapes a result may take —
frozen before the run, never matched by resemblance afterwards. The
conversion belongs to the column and not to the journey: the bank's own
`coverage` IS the oracle's proportion and converts by one, while
`cov_on_ead_pct` converts by a hundred. A journey-wide scale reconciled the
live answer by breaking every dry run, which is how that was found.

Where a row-level oracle is declared, **the artifact rows are the
comparison**. A keyed journey whose rows could not be read is not
reconciled however many prose claims agreed.

## CLOSURE-04 — a correct table with no chart

L04 returned exposure by delinquency bucket and drew nothing. The answer-turn
guidance asks "does this result have a shape?" and lists a ranking, a
movement, a concentration, a migration, a spread. An ordered distribution is
none of them. It is now named as a kind of shape — bands with a natural
order, where the weight along that order is the finding — with the form it
takes. The restraint rule is untouched: one figure still has no shape.

## Count formatting

Tested at `da974348` before anything changed: **not** already fixed.
`classify` was an exact-string lookup, `"facility records"` is not a key,
and UNKNOWN carries two decimal places. A unit no table spells is now read
from its words, and a phrase whose words disagree stays UNKNOWN rather than
being guessed.


---

# L08 — comparison precision

The second offline rejudge returned `reconciled_ok` for L01, L02, L04, L05,
L10, L11, L12 and L17, and `reconciled_not_ok` for L15 and **L08**.

L15 is expected: that paid run published no analytical result.

L08 is not a portfolio-number error. The analyst's own SQL computed
`ROUND(AVG(quarters_in_stage), 2)`, so the authoritative artifact holds two
decimals and nothing finer, while the oracle recomputes from the parquet at
full double precision:

| stage | oracle | published | delta |
|---|---|---|---|
| 1 | 16.620207108872098 | 16.62 | 0.0002071 |
| 2 | 6.096634281748786 | 6.10 | 0.0033657 |
| 3 | 5.699785177228787 | 5.70 | 0.0002148 |

Every one is inside half a unit in the second decimal place, and the matrix
declared a 1e-6 **relative** tolerance. Asking that artifact for six
decimals is a question about the artifact, not about the analysis.

The matrix now declares `comparison_decimals=2` for this figure, before the
run, as a property of what a tenure in quarters is — quarters and hundredths
of a quarter; a third decimal is under a day. The case's own 1e-6 tolerance
is untouched and still governs every other journey, and L08 is the only
journey that declares a precision.

The rule is half a unit in the last declared place of the exact oracle — the
interval any correct rounding to that precision lands in, whichever way the
database breaks a tie. Measured at the boundary: 6.1016 in, 6.1017 out,
6.0917 in, 6.0916 out.

**The distinction is published, not absorbed.** Every reconciliation report
carries `comparison_basis` (`declared_precision` or `relative_tolerance`),
`comparison_precision` and the reason, and the rejudge summary lists
`reconciled_at_declared_precision` beside `reconciled_ok`. A pass at a
declared precision is a weaker statement than a pass against the exact
oracle, and a report that did not say so would be hiding that the submitted
SQL rounded.

---

# Paid retest closure

Seven paid runs, USD 2.55683. L15, L16 and L04 came back correct and are
untouched by anything below. Two issues remained.

## The preserved evidence

| File | SHA-256, as reported |
|---|---|
| `live_uat_retest_live.json` | `1c58a1cfa785d3faab878ad35ae60faf4ae52e3e7e1dd9ab23387201e68df636` |
| `live-retest.sqlite3` | `41c9ddd81e5dc967b9c8984b4594fd57489b99b03c229e3f236e6e32a66bde25` |

Both live at `/Users/tuhinchatterjee/Desktop/CockpitLiveUAT_Evidence/`, on
the Mac. **That path does not exist in the environment this work was done
in**, so neither digest was computed here and neither file was opened, read
or written. The values above are the ones reported with the retest, repeated
so the Mac can check them against itself; they are not an independent
confirmation and must not be read as one. The same holds for
`live-first-pass.sqlite3`.

Everything below was reproduced from the runtime, the real books and the
real policy pack, with a scripted provider and no provider call.

## ISSUE 1 — an answer about a long result had nowhere to bind

L18's repair path still ended in a refusal. The full account is in the two
commits that close it; in one paragraph: the server records `produced_rows`
on the artifact scope, and no claim could bind to it. `rows: "all"` over a
truncated result is refused by the `_incomplete` rule, counting the
published rows answers a different question, and narrowing the query answers
a third. A refusal that leaves nowhere to go spends the correction it
offers.

`derivation.result_rows` is that binding: arity 1, unit-changing, reading
the row count CreditProbe recorded when it ran the query. The `_incomplete`
refusal now names it as the third way out, beside narrowing and naming
rows. The entity safeguard is untouched and tested — a claim in unit
`borrowers` still cannot read `facility_count` merely because both are
COUNT-class values.

Adding it to the operation table in `analyst.md` cost 101 bytes the action
payload did not have. The bound was **not** raised. What paid for it: four
outline blocks describing how to write a PRODUCT answer, carried on every
action attempt by a file measured against that bound, on turns that can
write no product answer at all. They now reach the PRODUCT_HELP turn
instead, unchanged in content. Headroom after: 1,123 bytes on
`stage2_ecl_growth`, 1,122 on `seeded_construction`.

## ISSUE 2 — a policy definition answered a question that never asked it

M06 turn 1:

    Which sectors have the largest exposure?

No clause, no limit, no threshold. `sem.readiness` returns
`sufficient=False` with `exposure` undecided between `ead_sar_mn`,
`limit_sar_mn` and `drawn_sar_mn`, which order the sectors differently.
`cp.retrieve` returns no clause. It is the matrix's proven blocking
ambiguity, L19. The run answered anyway, on EAD.

Reproduced offline by driving the real worker to NEEDS_CLARIFICATION and
reading the system context that turn was sent:

  * `policy_blocks` attaches the **synopsis** to every turn that can
    publish. It must: H-LIVE-05 exists because a turn without it stated
    that this book records no single-name limit when CP-1.1 does.
  * The synopsis carries CP-1.1 in full — "Exposure is measured as EAD,
    funded and unfunded together" — because that is the rule CP-1.1's own
    breach test runs on.
  * `POLICY_RULE` then said, unconditionally, that a term a clause settles
    is settled, and that treating it as open "invents an ambiguity the
    policy has already closed".

The turn whose entire job was to put the question back to the reader was
handed a rule telling it the question was invented.

**The rule.** A policy definition settles terminology *for the test it
defines*. The reader has invoked that test when the question reaches that
clause; they have not when the question is ordinary data analysis that never
mentioned it. The server already decides which is which, deterministically,
before any model call — `cp.retrieve` returns the clauses the question names
in the reader's own words.

So the settling sentence leaves the standing rule and rides on the
retrieved-clauses block, which is sent only when a clause was reached. A
question that invokes nothing is sent nothing. And `POLICY_RULE` now carries
the other half: a definition inside a clause governs that clause's own test,
and where the question names no clause and two governed readings would rank
or total the book differently, the reader chooses, not the pack.

| Question | Clause reached | Settling sentence sent |
|---|---|---|
| Which sectors have the largest exposure? | — | no |
| Just the top five by that measure | — | no |
| What is total ECL this quarter? | — | no |
| Which sectors are above the single-name limit? | CP-1.1 | yes |
| Which borrowers breach the single obligor limit? | CP-1.1 | yes |
| What does CP-1.1 say? | CP-1.1 | yes |
| *(Retail)* Which products have the largest balances? | — | no |
| *(Retail)* When does the collections ladder start? | RP-4.1 | yes |

**And a guard on that**, because retrieval is deliberately generous: it
matches a clause on the reader's own topic words, which is what lets "single
name" reach CP-1.1 without a clause id. The same generosity reaches CP-1.2
from "Show me exposure concentration", which is an ordinary ranking
question. So the settling sentence goes out only when the server ALSO has
nothing open — `sem.readiness` names the governed terms this question leaves
undecided, deterministically and before any model call, and an undecided
term is exactly "an alternative that can change the answer". When one is
open, the clauses are still attached and the analyst is told which term they
do not decide, and to ask.

| Question | Clause | Server's undecided terms | What the clauses are for |
|---|---|---|---|
| Which sectors are above the single-name limit? | CP-1.1 | — | settles the term for its test |
| What is our concentration by sector? | CP-1.2 | — | settles the term for its test |
| Show me exposure concentration | CP-1.2 | `exposure` | does not close it — ask |

Nothing keys on exposure, CP-1.1, sectors or a book. A test refuses any
book-specific word in either sentence.

**L16 is preserved.** It retrieves CP-1.1, receives the settling sentence,
and `sem.readiness` still returns `sufficient=True` — no new round trip.

**The clarification history projection needed no change.** `you_asked`,
`you_offered` and the note that allows a new question have been in
`context.build` since H8 and behave correctly on M06's own words: turn 2
"Exposure at default" is one of the offered choices verbatim, turn 3 sees
both prior turns, and M07's turn 2 is left free to be a new question. What
was missing was never the projection; it was that turn 1 never asked.

**M06 is three turns.** The chain was authored with a fourth — "And how much
of that is Stage 2?" — that the approved paid retest never ran, and its note
claimed turns that do not exist. Narrowing once is what the chain is for.

## What a further paid run would and would not add

Nothing in either issue needs one to be *diagnosed*: both were reproduced
offline against the real runtime. What no offline test can establish is
whether a live `claude-opus-5`, sent the corrected context, asks on M06 turn
1 and binds `result_rows` on L18. That is a behavioural question and it is
the only one left open.

## Verification

Run at `353ab96`.

| Suite | Result | Wall |
|---|---|---|
| `tests/cockpit_v4` + `tests/frontend` | 3367 passed, 4 skipped, 0 failed | 15m 45s |
| `tests/cockpit_agentic` (V3) | 564 passed, 26 skipped, 0 failed | 2m 09s |

The four skips are the round's own four; none is new and no test was turned
into one. V3 is unchanged at 564/26 — nothing outside `backend/cockpit_v4`
was touched, and no frontend file changed at all.

A note on one number, because it was wrong before it was right: the V3 suite
first came back `1 failed` on
`test_the_namespace_is_where_the_release_actually_goes`. That was the
harness, not the code — the run still had `COCKPIT_AGENTIC_V3_NAMESPACE`
pointing at `cockpit_v4`, which is precisely what that test checks. Run
without it, the file is 21/21 and the suite is 564/26.

Ruff on every changed file reports the same findings as the commit this
round started from, and none on the new test file.

## Out of scope, still logged

`D-003` — `catalog._SESSIONS` evicts the session it is about to return.
Pre-existing, reproducible on a clean `ac315dd`, untouched here.

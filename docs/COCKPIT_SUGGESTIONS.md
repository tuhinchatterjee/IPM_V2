# The three questions under the Cockpit composer

## What a suggestion is

A promise. The reader did not choose it — the product offered it — so an
offered question that comes back as *"Which figure should CreditProbe
measure?"* is worse than no suggestion at all: the user did exactly what they
were told and the product asked them what they meant.

That is what was happening. `/ask/suggestions` merged two lists — questions
built from the installed catalogue and every registered starter whose analysis
happened to be present — handed back six, and the Cockpit sliced the first
three off the front. Which three a reader saw depended on the order two lists
concatenated in, and none of them had been run through the Ask path.

## The contract

Five questions are approved for the Cockpit. Three are shown at a time.

1. Where is risk building across the bank?
2. Which exposures have deteriorated this quarter?
3. What is driving Stage 2 and ECL growth?
4. Which borrowers are weakening but are not yet on the watchlist?
5. Where are multiple warning signals appearing together?

They live in `backend/orchestration/suggestions.py` as `COCKPIT`, each with the
governed datasets it needs. A question whose datasets this installation does
not carry is never offered — the product does not advertise a capability it
does not have.

**Rotated by the date, not at random.** A random three would change under the
reader between one page load and the next, and would make the opening screen
impossible to describe to a colleague. By the date it is stable all day,
different tomorrow, and reproducible — which is what lets
`tests/api/test_cockpit_suggestions.py` assert on it.

**Every displayed question is a golden acceptance question.** That suite runs
all five through the real orchestration path against real data and fails if any
of them returns a clarification, an abstention, a withheld answer, no rows, or
shows the reader a stack trace, a SQL fragment, a validator message or a
provider name.

## What had to be built for three of them to answer

Three of the five did not answer. None of them names a measure, and every path
below the planner's opening reasons from resolved measures — so the question
was reduced to "no governed measure was named" before anything looked at what
it was actually asking.

They are composite questions. The composite machinery already existed
(`backend/orchestration/composites.py`): a phrase a credit officer uses that
has no single column behind it, together with the governed signals that
constitute evidence for it, ranked by how many fired. What was missing was the
vocabulary that reaches it, one more kind of signal, and a way to say "not
yet".

### A deterioration composite

`DETERIORATION` reads seven signals off `portfolio_facility`, every one a
published column:

| Signal | Reads |
| --- | --- |
| Published risk trend | `trend` is `Deteriorating` |
| Significant increase in credit risk | `sicr_trigger` |
| Early-warning trigger | `trigger_type` is `PD deterioration` |
| Risk appetite | `appetite_breach` |
| Utilisation movement | `utilisation_pct` at least 5 points above `prev_utilisation_pct` |
| Delinquency | `dpd_days` at or above 1 |
| IFRS 9 stage | `ifrs9_stage` at or above 2 |

Counted, not weighted — breadth of evidence, arithmetic a reader can check by
eye against the columns beside it.

**What it does not use, and says so.** The internal rating is carried at both
ends of the period — `risk_rating` and `prev_risk_rating` — but as a grade code
rather than an ordinal, so the movement between them is not a comparison a
single-dataset signal can make. The answer's caveats name it rather than
leaving it out silently; the bank's own PD deterioration trigger stands in its
place, and it is not the same thing.

### A signal that reads a governed enumeration

`trend` reads `Deteriorating` in the book. Reading that as a threshold on a
number, or leaving it out because it is not one, both throw away the bank's own
published statement about the facility. `EQUALS` tests a governed enumeration
for the value as it is spelled in the column.

### A measure named after the verb vetoes the composite

*"Which borrowers had deteriorating DSCR?"* named what deteriorated. That is an
ordinary movement on DSCR, and answering it with a seven-signal ranking would
be the same substitution the composite module exists to prevent, running the
other way. A measure word within two words of the deterioration verb refuses
the composite; `test_deterioration_composite.py` holds nine of these shut.

### "Not yet on the watchlist"

The highest-value early-warning question there is: show me the evidence before
the formal flag. Read as a plain cohort it compiled a predicate against a
column that only exists at one end of a movement, and the governed runtime
refused the plan — so the question came back withheld, with a validator message
in place of an answer.

It is now read beside the composite it qualifies (`composites.excluded`) and
applied where the composite reads its rows. It changes the answer materially,
so it is stated on the answer and not only on the Trace:

> The question said "are not yet on the watchlist", so borrowers where
> watchlist is set were removed before the evidence was counted. This is not
> the whole book.

Verified against the book at Q2 2026: over the whole portfolio the top name
carries **6 of 7** signals (Safwa Industries 1960); with the watchlist left out
the population falls from 4,100 borrowers to 2,138 and the top carries **2 of
7** (Qassim Logistics 2995). Both figures were recomputed independently in
pandas from the same columns and match the answer exactly.

### The coverage gate had to stop contradicting it

The caveats said the watchlist had been removed before the evidence was
counted. Two lines below, the coverage gate — which reads predicates, and a
composite has none — said CreditProbe could not apply *"weakening and the
exclusion the question stated"*. Both sentences were on the same answer, from
the same product, disagreeing.

`AnalysisBuild.covered` now names what a build's reading accounts for without a
predicate, and the gate honours it. A genuinely dropped condition is still
reported: `TestTheCoverageGateIsNotContradicted` asserts both directions.

## Verified, and not yet verified

**Verified.** 41 tests on the Cockpit contract (including all five questions
through the real orchestration path on real data), 43 on the deterioration
composite and the exclusion, the exclusion arithmetic recomputed independently,
`ruff`, and `tsc`.

**Not yet verified.** No browser click-through of the three suggestions. The
server sends three and the Cockpit renders what it is sent, but that a click
lands in a normal Ask investigation — and draws no chart merely because the
question was suggested — is asserted from the code path rather than observed in
a browser.

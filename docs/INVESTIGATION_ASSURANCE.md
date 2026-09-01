# Investigation Assurance

Part F. The six Intelligence Dimensions, the Assurance Record, and the
screens that read them.

## The problem this replaced

CreditProbe used to present its own validation as a flat wall of ninety-odd
checks with a percentage over it. Everybody who opened it arrived with a
different question — *is this answer safe to send a client? is the product
getting better? why did this one go wrong?* — and the wall answered none of
them, because it never said what any check was **for**.

Worse, the percentage was an average. An average over ninety-five checks
moves by about one point when the single check that says "the figures in the
prose trace to no fact" fails. The number that should have collapsed barely
twitched.

## Six dimensions

Each answers a question somebody actually arrives with:

| Dimension | Answers | Weight |
|---|---|---|
| Understanding & context | Did CreditProbe understand the user, the conversation and the requested scope? | 15 |
| Analytical design | Did CreditProbe design the right analysis? | 20 |
| Computation & evidence | Did CreditProbe calculate correctly and build trustworthy evidence? | 25 |
| Judgment & presentation | Did CreditProbe turn the result into a strong, clear and appropriate credit-risk answer? | 20 |
| Agentic delivery | Did the governed agentic system coordinate and complete the work safely? | 10 |
| Reliability & experience | Was the experience operationally reliable, efficient and usable? | 10 |

All ninety-five detailed checks are kept, each belonging to exactly one
dimension. **The dimension is where you notice a problem; the subcomponent is
where you fix it.**

The weights are not equal, and Computation & Evidence carries the most,
because a wrong number is the failure that cannot be recovered from
downstream. They are versioned, and a set that does not sum to 100 is
refused — a score computed under undeclared weights cannot be compared with
another one.

## The order the verdict is computed in

1. **Critical gates.** Any critical check failed → `FAILED`, and **no score
   at all**. Reporting "72 / 100 (FAILED)" invites somebody to notice the 72.
2. **Coverage gate.** Too few checks ran → `UNVERIFIED`, and no score. Not
   enough was measured to claim anything.
3. **Mandatory-skip gate.** A mandatory check did not run → `NEEDS_REVIEW`.
4. **Only then** the weighted score over the dimensions that were measured.

A dimension nothing measured is excluded from the numerator *and* the
denominator, so it neither helps nor hurts. It shows as unmeasured, which is
what it is.

## Five outcomes, and the two that matter

`PASS`, `WARNING`, `FAIL`, `SKIPPED`, `NOT_APPLICABLE`.

* **SKIPPED is never PASS**, and a skipped check stays in the coverage
  denominator. Otherwise coverage improves by running fewer checks.
* **NOT_APPLICABLE requires a stated reason.** Without one it is refused
  outright, because it removes a check from the denominator — which improves
  coverage by not looking.
* A subcomponent **absent** from a record is `SKIPPED`, never
  `NOT_APPLICABLE`. Nothing ran it.

## Operational assurance is not accuracy

Two numbers, never merged:

* **Operational assurance** — what the runtime could prove about a run. Every
  live Investigation has one.
* **Reference match** — agreement with an approved answer. Exists only where
  such an answer does, which for a live Investigation is almost never.

Where no reference exists the payload says so **in a sentence**, because a
missing key reads as an oversight and this is a fact about the question. The
label is a constant (`rc.ASSURANCE_LABEL`) so that one definition governs
every surface; a screen that renamed it locally would be the way the rule got
lost.

## Records are evidence, not state

An Assurance Record is written once, with the verdict as computed under the
weights, gates, build, data and releases in force at the time. §208: historical
scores are not rewritten.

**Staleness is therefore not stored.** It is a relation between a record and a
runtime, computed at read time — so the row keeps saying what was true while
the reader still learns that the world has moved. A stale record reports
`STALE` as its *current* status and keeps its original verdict.

Two columns do change after insert, deliberately: the raw feedback counters
and `superseded_by`. Both record what happened *around* a record rather than
what it concluded.

## Feedback changes where you look, not what the score says

Raw user feedback increments a counter on the record. There is no code path
from a thumb to any check, dimension, status or score — which is a stronger
guarantee than a policy. A finding appears in the review only after a
reviewer has adjudicated it, and RAW USER FEEDBACK and ADJUDICATED FINDING
are rendered apart. Merging them turns an opinion into a finding.

## Comparing two runs

`compare()`'s first job is not comparing. It is deciding whether a comparison
is legitimate:

* `NOT_COMPARABLE` — different question, scope or language.
* `CHANGED_DUE_TO_DATA` — the data underneath moved, **or neither run
  recorded which data version it read**. Unknown is not "the same".
* `REGRESSED` / `IMPROVED` / `UNCHANGED` — only once the ground held still,
  and a new or cleared critical failure outranks any movement in the score.

Neither record is edited. A "fix" that improved a record by rewriting it
would show improvement in every case.

## Who may read a review

A review inherits the Investigation's access rather than being governed
alongside it — two permission models over the same content diverge, and the
one that diverges upward is a leak. Tenant is checked first and **no role
widens it**. Below administrator, a review is a summary: the prompts,
retrieved teaching cases and served model names are a look inside the
machine rather than at the answer. "Not yours" and "does not exist" return
the same 404, so nobody can enumerate Investigation ids from the refusals.

## Where it appears

* **How CreditProbe performed** — on the Investigation, collapsed by default.
* **AI Intelligence Studio → Investigation Reviews** — a table (not a card
  wall: the task is comparison across many Investigations, which is a
  scanning task), with eight views and thirteen filters.
* **Trace → ASSURANCE SUMMARY** — the six dimensions, each linking to the
  Trace nodes its evidence came from.
* **Full Calculation Pack → INVESTIGATION ASSURANCE** — read from the Trace
  rather than re-scored, so the export cannot disagree with the screen.

## Score honesty

`backend/assurance/honesty.py` turns §212's seven "it must be impossible to
show" rules into predicates, and the tests run them against the actual HTTP
responses rather than against hand-built payloads. The rules exist as code
because the failure they prevent is not a bug in the scoring — it is a *new
screen*, built later, that assembles its own payload and gets one of the
seven subtly wrong.

Nothing in this layer calls a provider. An assurance record that required a
model call would not be written for the failures that need it most.

## Coverage is honestly low today

The collector reports only what the runtime actually established. Where no
signal exists, the check is `SKIPPED` — not `PASS`. A freshly instrumented
record therefore reports low coverage and `UNVERIFIED`, which is an honest
number about an under-instrumented product rather than a false one about a
working product. **The way coverage goes up is by wiring another signal in**,
not by marking uninstrumented checks as passing.

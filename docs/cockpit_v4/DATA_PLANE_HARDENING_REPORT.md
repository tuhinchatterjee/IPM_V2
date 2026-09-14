# Cockpit V4 — data-plane, compartmentalization, investigation-reliability
# and live-provider contract hardening

This round did not patch the questions the Mac UAT reported. It changed the
contracts underneath them and then checked those contracts across a matrix
large enough that a wrong one is wrong here rather than on a Mac.

What follows is what changed, what it was changed FROM, and what now holds it
in place. Every figure in it was read out of the build.

---

## 1. The two books, and the two calendars

| | Corporate Credit | Retail Credit |
|---|---|---|
| Release | `v4-saudi-corporate-20q-v3` | `v4-saudi-retail-20m-v3` |
| Fingerprint | `46962675d801ed4e…` | `95fa5d3e2c6b979b…` |
| Reports | **20 quarters** | **20 months** |
| Window | 2021Q3 … 2026Q2 | 2025-01 … 2026-08 |
| Period column | `reporting_quarter` | `reporting_month` |
| Relations | 4 | 4 |
| Rows | 839,960 | 815,551 |
| Entities | 3,652 borrowers · 12,782 facilities · 1,725 groups · 14 sectors · 75 sub-sectors · 10 regions · 7 product types | 12,000 customers · 16,000 accounts · 4 products · 8 regions |

The previous Corporate release reported months. It was NOT rewritten: both
`v4-saudi-corporate-20m-v1` and `-v2` are still published and still verify
against the fingerprints they were published under, because an analysis saved
against one of them names it, and a calendar change under a release id nobody
changed would silently restate every saved answer.

### What made two calendars possible

`schema.period_column()` and `schema.frequency()` are the source, and
`schema.period_keys()` is the single place that decides what a payload spells
its period under. It fills `reporting_period`, `comparison_period` and
`period_noun`, and of the two legacy keys it fills ONLY the one that book
reports in — a Corporate card leaves `reporting_month` empty rather than
putting a quarter under a month's name. An empty string is a visible mistake;
a quarter called a month is an invisible one.

`Calendar.frequency` no longer has a default. It defaulted to `"quarterly"`,
which is how a monthly book came to describe itself as quarterly in a manifest
nobody read closely.

### What the two calendars found

- `values.dimensions` excluded calendars by the literal suffix `_month`. The
  moment the Corporate book reported quarters, `reporting_quarter`,
  `origination_quarter` and `waiver_quarter` became "governed dimensions a
  reader could name", and sixty dates entered the bounded enumeration. The
  rule is now derived from the set of calendars there are.
- The attention panel's cover line read `feed.prior_quarter` and
  `feed.prior_year_quarter`, which the per-domain engine never emitted. The
  first sentence a reader saw was "CreditProbe reviewed Q2 2026 against  and
  and identified 5 segment issues" — two blanks, in the opening line.
- The trend chip offered "how has this moved over the last twelve months?" to
  a book that reports quarters: a question about three years, offered to a
  reader who clicked something else.

---

## 2. The intent is authored once

`intent` was a required nested object on all five tools — nine fields retyped
on every catalogue read, every artifact read, every execution and the answer,
none of which changed between them. A live run sent it as a string and
`intent must be an object` reached a reader's screen twice, in two rounds,
each round making the parser more forgiving instead of removing the
restatement.

The field is gone from every tool schema. The run opens an `IntentEnvelope`
holding what the server already knew before the first provider call: which
book, which release and its exact bytes, what kind of turn this is, what a
period means here, and what the question's own words resolved to against the
values the release holds. `finalize_response` may restate the reader-facing
half — understood, assumed, mapped, excluded — flat and optional, because that
half is answer content.

The server's half is not overwritable. The one movement allowed is **widening**:
submitting SQL declares the turn analytical, so a question the budget
classifier read as product help escalates rather than being refused for a
classification the reader was never shown. It never narrows — a run that has
already read the book does not move onto the cheaper clock by saying so.

`tests/cockpit_v4/test_intent_envelope.py` replays ten shapes a live model has
sent — a bare string, a sentence, a list, a number, an empty object, nothing —
through the real parser. None of them can reject a run that has its envelope.

---

## 3. The seeded investigation

A reader clicked the Construction card. The thread read the catalogue, read it
again, read product knowledge, and died at CALL_LIMIT without answering
anything. Not one of those calls could have returned something the server had
not already computed: it wrote that card.

A seeded thread now opens with an **analysis packet** — the relation the
finding came from, the column the segment lives in, the governed value of that
segment and the label beside it, the measure's own columns, the two periods,
the grain and the keys. Bounded by construction: under 6 KB and at most
eighteen columns, because the covenant relation has fifty-nine and carrying
all of them would be the relation dump this exists to avoid.

Checking every offered question against the release, rather than against
prose, found two defects:

- A covenant-breach card offered "Split Leverage by region", and
  `corp_covenant_quarter` has no region column. The cross-cut list was the
  book's second axes IN GENERAL rather than the columns of the relation the
  finding actually came from. Four such chips existed.
- The trend chip's calendar, above.

All **86** offered questions across both books now bind against the release
before they are shown.

---

## 4. Compartmentalization

Every previous round fixed the leak it was shown — the dashboard, then
Investigate Further, then the export — and none of those fixes prevented the
next one, because a leak is not a property of a feature. It is a property of
any path that takes a domain from somewhere other than the thread.

`tests/cockpit_v4/test_compartmentalization.py` enumerates the surfaces and
checks the rule on each, and its last test fails when a route serves a book
and is not listed, so the audit stays an audit. Two surfaces failed it:

- `/ecl` served its whole answer without naming the book at its top level. A
  caller had to reach into `profile.domain_id`, and a caller who has to do
  that eventually does not.
- The run-accept 202 echoed the release but not the domain, so a client could
  not see that the thread's own book had won over the one it asked for.

A third failure was in the vocabulary rather than in a route. Asked of the
Retail book, "and within project finance?" resolved the single word `finance`
and asked "did you mean Auto Finance or Personal Finance?" — a question built
by discarding the word that made the reader's phrase unambiguous. The Retail
book has no project finance. Saying nothing is the honest answer; asking
invites the reader to accept an answer to a different question.

In the Corporate book the same phrase resolves exactly — from `prject finance`
too, without a clarifying question — and the trace quotes what the reader
wrote rather than the fragment that matched.

---

## 5. The process panel

Two defects, both of them the panel deciding things the server had not said.

The panel laid out "Request accepted" and "Understanding the request" as empty
circles before anything happened, so a reader watching a live run at 0s saw
two rows reading "not started". `StepState` no longer has a `prospective`
member and `INITIAL_STAGES` is empty: a step appears when the server says its
stage started.

The panel closed a stage by inference — "any earlier stage still marked
running has been left behind" — which holds only while stages run in array
order and never re-enter. A run that re-enters `preparing` after a failed
submission breaks it in both directions.

The emitter now runs the state machine. Every event carries its stage
instance (`preparing#1`, `preparing#2` — two passes are two things that
happened), when that instance started, its state, and the instances this event
CLOSED. A terminal event closes two: the one it displaced and its own, so a
browser reconnecting after the last frame is not left with a stage spinning.

`tests/cockpit_v4/test_process_events.py` folds the persisted stream in Python
— a second implementation, deliberately — because if it and `reducer.ts` can
disagree then the stream is not enough and something on screen is coming from
somewhere else.

---

## 6. The Data Builder

`/data-builder` from the sidebar showed the onboarding estate and nothing
about the two published analytical books. They are now the first thing on that
page, rendered from `/schema` — the same governed catalogue the analytical
path reads.

Every assertion in `test_data_builder.py` pairs a Data Builder answer with the
analytical path's own answer and requires the same object, not a similar one.
A Data Builder backed by its own store would agree on the day it was written
and drift afterwards, and when it drifted nothing on either screen would say
which of the two was wrong.

Each card carries country, denomination, calendar with its noun, the period
span, the entity counts a credit officer recognises, the release and its
fingerprint, and the status. Columns are grouped by the catalogue's own
subject areas. Each column shows the label a person reads AND the identifier
SQL filters on, and a category column enumerates the values it may hold —
labelled `governed_values` where the set is closed and `sample_values` where
it is not, because a reader told twelve borrower names were the governed list
would build a filter that silently excluded 3,640 others.

---

## 7. Convergence

The response to runs dying at their deadline had been more time — 60s, then
120s — and more time is not convergence: a run that needs four catalogue calls
to answer "what is EAD by sector" will spend whatever it is given.

`test_convergence.py` bounds the WORK. A simple question costs one action turn
and one answer turn, makes no catalogue call at all, reads back a tool result
inside half the soft input budget, and finishes inside half its allowance. The
two structure-recovery budgets are checked to be separate, so a malformed
action cannot consume the one allowance the answer has.

---

## 8. The matrix

| Bank | Size | What it checks |
|---|---|---|
| Corporate questions | 40 | Every figure against an independent pandas oracle over the Parquet |
| Retail questions | 40 | The same |
| Follow-up chains | 20 (10 + 10) | 4–6 turns each, ≥80 turns, book and calendar held across every turn |
| Attention chains | 20 (10 + 10) | Card → investigate → suggested question → execute → publish |
| Mac replays | 7 | One per recorded live failure, asserting on the cause |
| Negative cases | 22 | What must be refused, and the shape of each refusal |
| Performance gates | 15 | DuckDB doing the filtering, checked by plan as well as by clock |

The oracles import nothing from the analytical path. One that called the code
under test would prove the code is self-consistent, which is exactly what a
wrong answer also is.

Writing the bank found three things the data says and the questions did not:
no facility cured in the latest quarter (cures are real and authored, 348 of
them in 2024Q4–2025Q2); `valuation_age_quarters` cycles one to four, so "older
than two years" is unreachable; and `months_on_book / 12` divides as a float
in DuckDB, so a seasoning curve grouped by 0.083 rather than by whole years.

And one bug in the oracles themselves, which is the kind a bank catches and a
single example does not: flags are `int64` in the Parquet, so
`frame[frame["breach_flag"]]` selects COLUMNS rather than rows — silently,
until the integers happen not to be column names.

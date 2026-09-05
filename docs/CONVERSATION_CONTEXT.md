# Multi-turn context: scope, population and reference

What an investigation remembers between one question and the next, how a
follow-up resolves against it, and what deliberately is not inherited.

This is the mechanism behind the acceptance threads in
`tests/api/test_context_carry_forward.py`. Those tests drive the endpoints the
browser calls; this document says what they are asserting and why.

---

## The failure this closes

One investigation, five turns, through `POST /investigations` and
`POST /investigations/{id}/messages`:

| # | Question | Before | After |
|---|----------|--------|-------|
| 1 | Which sectors concern you most? | 25 borrowers | unchanged |
| 2 | Why Shipping? | *"Which figure should CreditProbe measure?"* | 25 Shipping borrowers, same analysis |
| 3 | Which borrowers are the real issues? | portfolio-wide | inside Shipping |
| 4 | Which of those have rising 12-month PD? | 23, restricted | unchanged |
| 5 | Why does the second one worry you? | the whole 25-row ranking again | **Jazan Logistics** — row 2 of the 23 |

Two root causes, and they are different in kind.

**Turn 2** — a sentence that names a governed dimension value and no measure
was read as a fresh request. Read that way it names no figure at all, so the
planner asked for one. That is the product asking the reader to restate the
analysis it had just run; and because a clarification settles nothing, the
turns after it had no measure either.

**Turn 5** — an ordinal reference into the previous result was not read at all.
"The second one" was planned from its own words: "worry" resolved to the
composite credit-concern signals, the ranking was recomputed over the whole
population, and twenty-five names came back under a question about one.

## Three kinds of context, and they are not interchangeable

**Active scope** — the book the conversation is about: `sector = Shipping`.
Persists until a sentence names another value for the same dimension or
explicitly widens back out. Carried as `ConversationState.filters` and applied
per field, so naming a new sector replaces the sector and leaves the stage
restriction alone.

**Result population** — the identities the previous answer returned, in the
order it returned them. `ResultShape.entity_key` and `entity_ids`, capped at
`MAX_ENTITY_IDS`. What "those", "these", "them" and "the names" resolve to. A
referent resolves to the identities the previous run *returned*, never to a
re-derivation of the question that produced them.

**Ordered result reference** — one position in that order: "the second one",
"the last one", "#3", "the worst of those". Read by
`backend/orchestration/nth.py` and bound to exactly one identity by position.
Nothing is re-ranked, and "the worst one" is resolved against the direction the
previous plan actually sorted on rather than against the word.

## What is inherited, and what is not

| Sentence | Reading | Inherits |
|---|---|---|
| "Why Shipping?" | `NARROW_SCOPE` | measure, period, shape — **not** the previous rows |
| "Which borrowers are the real issues?" | `CONTINUE` | the settled filters |
| "Which of those have rising PD?" | `CONTINUE` | the previous rows, by identity |
| "Which borrowers drove that?" | `CONTINUE` | the settled measure |
| "Why does the second one worry you?" | ordinal | exactly one identity |
| "Show total ECL by sector." | `CONTINUE`, scope only | population, **not** the measure |
| "What fields does the ratings data have?" | not analysis | nothing |
| "Now across the whole portfolio…" | `RESET_SCOPE` | nothing |

`NARROW_SCOPE` deliberately carries no population. "Why Shipping?" asks about
the Shipping book, not about the intersection of Shipping with whichever rows
the previous ranking happened to return, and intersecting silently would answer
a much narrower question than the sentence asks.

## A clarification does not destroy context

The question CreditProbe could not plan is held on the state as `pending`. A
short, non-interrogative reply — "Expected credit loss." — is merged with it by
`services.threads.resume`, so the movement that was asked for is the movement
that is computed. A reply that asks something of its own is a new question and
is read as one. The merge is stated on the answer as a caveat; the user's own
words are what is stored as their message.

`pending` is cleared by the next turn that settles anything, so a clarification
answered three turns later is not silently re-merged.

## Precedence

1. What this sentence says explicitly always wins.
2. An ordinal reference, bound to the stored order.
3. A population referent — "those", "these", "them".
4. The settled filters, per dimension.
5. The settled measure, when the sentence names none and points back.
6. The settled period.

## When a reference cannot be resolved

It is asked about. Never widened.

"The ninth one" when eight rows came back drops the carried population entirely
and returns a clarification naming what could not be followed. Answering the
last row instead, or the whole population, would be an answer about a different
borrower under the reader's own sentence — which is the failure the reading
exists to close, arriving by the polite route.

## One mechanism, three entry points

`POST /investigations` (the first question), `POST /investigations/{id}/messages`
(the Cockpit and Project threads) and `POST /ask` with an `investigation_id` all
load the same state with `conversation.load` and `memory.load`, resume through
`threads.resume`, and write back through `threads.remember`. Before this work
`/ask` used the id only to file the answer and planned every question as though
nothing had been asked before it.

## What the Trace shows

The `PRIOR_CONTEXT` node carries the action, the referent, the population key
and size, a sample of the names, everything that was inherited and why — and
the ordinal block: the phrase, whether it bound, to which identity, at which
position, of how many. A reference that could **not** be followed appears there
too, with the reason. No private reasoning; only what was carried and from
where.

## Known limitations

- "How has it *moved*?" is not read as a two-period question; "changed",
  "risen" and "fallen" are. A movement asked with "moved" is answered as a
  level. Vocabulary, not context.
- "Stage 2 **or worse**" applied to a carried population is widened in the
  query but recorded as `= 2` in the fidelity contract, so the presentability
  gate withholds the answer. Pre-existing and unrelated to this work; it fails
  closed rather than showing a wrong table.
- An ordinal binds by position in the stored order. Where the previous result
  carried no readable name for a row, the Trace and the answer name it by
  `customer_id`.

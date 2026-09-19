# Live UAT — the provider test still required

Nothing in this candidate has made a provider call. Not because it was
deferred: `COCKPIT_ANTHROPIC_API_KEY` is unset in this container and
`config/cockpit_v4/price_card.json` is the shipped placeholder, which fails
closed with `CAPABILITY_UNVERIFIED`. A paid call was not possible, and no
number anywhere in this work came from one.

So everything below is **NOT VERIFIED LIVE**: answer quality, the analyst's
own choice of method, whether it picks the riyal column at facility grain
without being told twice, and how many generations a real question costs.
What *is* verified, deterministically and at length, is the architecture that
carries those answers — see `HANDOFF.md`.

This is the smallest plan that would settle the open questions. It needs your
approval before anything runs.

## Before it can run at all

1. **The price card.** `config/cockpit_v4/price_card.json` must carry the
   current published schedule for the model below, with all four billing
   classes and a real `verified_at`. Until it does, the runtime refuses to
   spend. A test-only fixture exists at
   `var/retail-cockpit-candidate/testing/price_card.fixture.json`; it is
   fabricated, it is not the shipped card, and it authorises nothing.
2. **The credential.** `COCKPIT_ANTHROPIC_API_KEY`, in the candidate
   environment file. Name only — never pasted into a conversation, never
   logged, never printed by any script here.

## The plan

| | |
|---|---|
| Model | the one `AI_COCKPIT_REASONING_MODEL` names, verified live by the engine's own `load_capability` before any question runs |
| Runs | **12**: 10 single questions, then one 2-turn follow-up |
| Mode | `standard` for all twelve. Deep mode doubles the budget and answers the same questions |
| Expected input | ~18,500 tokens per first turn (measured: the packet builds at 18,490 for a retail question), ~22,000 on a follow-up |
| Expected output | ≤ 4,000 tokens per turn |
| Ceiling per run | the engine's own `spend_ceiling_usd`, 1.50 for standard, enforced by the ledger and not by me |
| **Hard cumulative cap** | **USD 15.00.** Stop at that, whatever has or has not been answered |

## The twelve questions

Chosen so each one can be checked against an oracle that already exists, or
against a refusal that is already specified.

| # | Question | What it settles |
|---|---|---|
| 1 | Total exposure at default by product this month | Q01 — the simplest possible agreement |
| 2 | Which facilities carry the largest balances this month? | **the money rule.** Facility grain: does it choose `balance_sar` unprompted, or publish `SAR 0 million`? |
| 3 | Recognised ECL and coverage by product and IFRS 9 stage | Q03, including ratio-of-sums rather than an averaged ratio |
| 4 | Where did the 1–29 day past due population move this month? | Q05 — a movement, with the denominator stated |
| 5 | Decompose the ECL movement since last month | Q21 against the panel's own attribution |
| 6 | Which customers have the highest debt burden? | Q22 — **customer grain: is it de-duplicated?** |
| 7 | Show the twelve-month ECL trend | Q26 — a series, not two endpoints |
| 8 | Which score band carries the most exposure? | Q17 — and whether the band order is the governed one, not alphabetical |
| 9 | What is the Early Warning score for these customers? | **a refusal.** Another module's domain: it must hand off, not answer |
| 10 | Which corporate sectors deteriorated? | **a refusal.** Another book: it must say so |
| 11a | Total ECL by product this month | sets up the follow-up |
| 11b | *(follow-up)* And which product drove the increase? | context retention: does it stay in the thread and keep its own evidence? |

## What counts as success

- **Numerical**: every figure in 1–8 agrees with its oracle at the declared
  tolerance. One disagreement is a failure, not a rounding note.
- **Denomination**: question 2 answers in riyals. If it answers
  `SAR 0 million`, the grain seam is not sufficient on its own and that is
  the single most important thing this run can tell us.
- **Refusals**: 9 and 10 refuse and name the module or book that owns the
  question. An answer to either is a containment failure and stops the run.
- **Conversation**: 11b stays in the thread, does not re-ask, and binds to its
  own artifact.
- **Cost**: total spend at or under USD 15.00, and each run inside the
  engine's own ceiling. The ledger is the record, not my arithmetic.
- **Budget**: generations, catalogue calls and repair rounds per question
  recorded and compared with the frozen source's own figures. An increase is
  an adapter defect to fix, not a budget to widen.

## What is NOT in this plan

Bulk question batteries, deep mode, concurrency, and anything that would
spend more than the cap to tell us something the deterministic suites already
tell us. If the twelve pass, the next decision is yours; if question 2 fails,
the work goes back to the steering seam before anything else is spent.

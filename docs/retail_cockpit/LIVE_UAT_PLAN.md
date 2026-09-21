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

1. **The price card. Done.** `config/cockpit_v4/price_card.candidate.json`
   carries `claude-opus-5` with all four billing classes, transcribed from
   Anthropic's published pricing page with its source and date. The shipped
   `config/cockpit_v4/price_card.json` is untouched: it is part of the
   verbatim port and stays the fail-closed placeholder. **These are
   first-party standard rates** — an account on Bedrock or Google Cloud, with
   a negotiated discount, or pinning `inference_geo: "us"` (a 1.1x multiplier
   on all four classes) needs its own card.
2. **The credential.** `COCKPIT_ANTHROPIC_API_KEY`, **exported in the shell
   that runs the launcher** — not written into the environment file, which
   the launcher sources under `set -a`, so an assignment there would
   overwrite what you exported (including an empty one, which fails with
   `PROVIDER_CREDENTIAL_MISSING`). Name only: never pasted into a
   conversation, never logged, never printed by any script here.
3. **The preflight.** `scripts/retail_cockpit/check_live.py` reports the
   model, the card's four rates, both caps and the projected cost of these
   twelve questions, and **makes no provider call**. Run it first.

## Give it a fresh ledger

The cap counts everything in the engine's state store. Before the UAT, set

    COCKPIT_V4_STATE_DATABASE=var/retail-cockpit-candidate/runtime/state/uat.sqlite3

so the $15 budgets these twelve questions and nothing else, and leave it set
for any `--from N` resume so they count against the same budget. Nothing is
deleted; the existing store stays where it is.

## What a live start costs before a question is asked

Two things, neither of them obvious:

* **`verify_live` runs at startup**, and twice — once inside `create_app` and
  once when the candidate bootstrap installs its own runtime. Each is a
  `count_tokens` call: not billed, but a real request that needs a working
  credential and a model the account can serve. A wrong model id fails the
  whole runtime here rather than on the first question.
* **`check_ready.py` used to buy a run on every launcher start.** It submits
  a real question with a fresh idempotency key, and the launcher runs it
  unconditionally, so a live start bought one standard analysis each time
  while the script's docstring said "No provider call is made" — true only
  offline. It now skips that step in live mode and says so;
  `--allow-paid-run` spends one deliberately.

## How it runs

`scripts/retail_cockpit/run_uat.py` drives all twelve through the retail
proxy -- the same path a reader's question takes, so the cumulative cap
applies to it too. It judges an answer by its **numeric claims**, not its
prose: every figure the analyst publishes is already bound by the engine to
an executed cell, so the check is whether each one appears among the values
the oracle computed independently, at the oracle's own tolerance. That
catches a fabricated figure, a wrong denomination, a ratio of averages and an
un-de-duplicated customer total. It does not catch an answer whose numbers
are all true and whose conclusion is wrong; a human reads the narratives for
that, and the report says so rather than claiming the stronger thing.

`--rehearse` drives the same twelve against an OFFLINE engine, proving the
runner for nothing and refusing to point at an engine that could spend.

## The plan

| | |
|---|---|
| Model | the one `AI_COCKPIT_REASONING_MODEL` names, verified live by the engine's own `load_capability` before any question runs |
| Runs | **12**: 10 single questions, then one 2-turn follow-up |
| Mode | `standard` for all twelve. Deep mode doubles the budget and answers the same questions |
| Expected input | ~18,500 tokens per first turn (measured: the packet builds at 18,490 for a retail question), ~22,000 on a follow-up |
| Expected output | ≤ 4,000 tokens per turn |
| Ceiling per run | the engine's own `spend_ceiling_usd`, 1.50 for standard, enforced by the ledger and not by me |
| **Hard cumulative cap** | **USD 15.00, now enforced.** `RETAIL_COCKPIT_SPEND_CAP_USD` in the candidate environment; the retail proxy reads the engine's own ledger (`SUM(COALESCE(settled_usd, reserved_usd))`) and refuses `POST /runs` with a typed 402 at or above it, before the request reaches the engine. Unset, there is no cap |

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

  When this plan was written that cap had **no mechanism**: the engine bounds
  one run (`spend_ceiling_usd`, 1.50 in standard mode) and counts nothing
  across runs, so twelve runs had eighteen dollars of headroom against a
  fifteen dollar cap. It is a mechanism now, in the proxy, and it counts an
  unsettled reservation at what it reserved so a burst of runs cannot walk
  through it. Note it counts everything in that state store, including runs
  from before the cap was set.
- **Budget**: generations, catalogue calls and repair rounds per question
  recorded and compared with the frozen source's own figures. An increase is
  an adapter defect to fix, not a budget to widen.

## What is NOT in this plan

Bulk question batteries, deep mode, concurrency, and anything that would
spend more than the cap to tell us something the deterministic suites already
tell us. If the twelve pass, the next decision is yours; if question 2 fails,
the work goes back to the steering seam before anything else is spent.

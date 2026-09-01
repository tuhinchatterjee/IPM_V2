# What a question costs, and why

R2 §16 asks for the cause of the AI cost to be **instrumented before it is
guessed at**. This document records what the instrumentation found, what was
changed as a result, and what the numbers were before and after.

The measurement harness is `scripts/measure_ai_cost.py`. It runs a
representative question set through the real router, the real catalogue, the
real governed tools and the real evidence ledger, against a local stand-in
provider that consumes nothing and reports the tokens of the prompts this
deployment actually builds. **No live provider call is made and no credits are
consumed.**

```
.venv/bin/python scripts/measure_ai_cost.py --out docs/AI_COST_BASELINE.json
```

---

## What the meter records

`backend/analyst/cost.py` holds one `Meter` per question. Per question it
records the model calls, the role and model that served each of them, input /
output / cache-read / cache-write tokens, how much of the input was catalogue
and how much was gathered evidence, tool calls and how many repeated an
earlier call, loop steps, provider retries, whether the answer came from the
run-key store, and wall-clock. `GET /api/v1/ask/cost` returns the recent
questions and the summary by class; it is administrator-only and carries no
prompt text, no tool arguments and no borrower identifiers.

Cost is reported in **cost units**, not currency. §22 asks for budgets in
tokens and calls rather than money, and a currency figure would need a price
list that goes stale. A cost unit is a declared weighting: output tokens
weigh five times input tokens, a cache-read token a tenth, a cache-write
token slightly more than a fresh one, and the whole call is multiplied by its
tier — light 1, standard 4, deep 16. The ratios are conservative, so a saving
computed with them understates rather than flatters.

---

## What the measurement found

Sixteen questions across four families, measured against the architecture at
commit `2ef58c3`:

| Family | Questions | Model calls / question | Input tokens / question | Cost units / question |
|---|---:|---:|---:|---:|
| Data and metadata | 6 | 4.00 | 14,731 | 247.1 |
| Data query | 4 | 4.00 | 14,740 | 247.3 |
| Orchestration | 2 | 4.00 | 14,753 | 247.5 |
| Judgement | 4 | 4.00 | 14,737 | 247.2 |

**Every question cost the same**, and that is the finding. "How many data
domains are there?" — a question the governed catalogue answers exactly, with
no query to run — consumed four deep-tier model calls and 14,731 input tokens,
the same as "Why did Shipping deteriorate this quarter?".

The first run of this table reported 61.8 units per question rather than
247.2. That was a bug in the meter, not in the architecture: `record_call`
defaulted an unnamed tier to *standard*, so the analyst's deep-tier calls were
priced at a quarter of what they cost. The tier is now derived from the role,
and the baseline above was re-measured with the corrected meter — an
optimisation measured against an under-priced baseline looks like a
regression, and this one would have.

Four distinct causes, in the order they matter:

### 1. There was no class A path at all

`backend/analyst/route.py` sent every question to the analyst loop. The
deterministic metadata answerer (`backend/metadata/`) existed and was correct,
but it was reached only from inside `backend/orchestration/orchestrator.py`;
the analyst path did not consult it. A catalogue question therefore paid a
full investigation to rediscover an answer already held.

Worse, `POST /ask` ran **both** paths for every question: the whole
deterministic orchestrator — which itself calls a model to read the request
and again to write the interpretation — and then, unconditionally, the whole
analyst loop. §16's "no automatic expensive final synthesis when the
deterministic answer already satisfies the question" was being violated on
every single turn.

### 2. The catalogue was re-sent on every turn

7,676 of the ~14,700 input tokens per question were the system prompt and the
tool catalogue — **identical on every one of the four turns**, and sent as
part of the varying user prompt, where no provider cache can reach it. The
prompt-caching module (`backend/llm/caching.py`) existed, correct and unused
by this path.

### 3. The evidence ledger was re-rendered whole, every turn

6,972 tokens per question of accumulated evidence. Turn four re-sent turns one
to three. The growth is quadratic in the number of turns, so the fourth turn
of an eight-turn investigation is not four times the first — it is far more.

### 4. Nothing detected a repeated tool call

The loop had no memory of what it had already run, so the same query could be
issued twice and paid for twice, in tokens on the way out and in evidence
tokens on every subsequent turn.

---

## What was changed

Six changes, and the measured result of each: `docs/AI_COST_AFTER.md`.

In one line: 64 model calls became 24, and 3,955.9 cost units became 523.8.
A catalogue question now costs nothing at all.

---

## What the figures are, and are not

Token counts are measured from the prompts this deployment actually builds,
at a four-characters-to-a-token estimate rather than the provider's own
tokeniser. The number of turns is what the harness scripts, not what a live
model would choose. The figures are therefore sound for comparing one
architecture with another — which is what they are for — and are **not** a
forecast of a bill.

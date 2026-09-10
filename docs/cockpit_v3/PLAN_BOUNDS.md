# The planning turn is bounded — the fourth live-UAT defect

**Status:** fixed, with tests. Live answer quality remains **BLOCKED /
UNVERIFIED**: the 84-question bank has not been run.

## What happened

Manual live UAT asked:

> "Which sectors saw the largest increase in Stage 2 exposure over the latest
> year?"

The request reached `Reading the question` → `Understanding what is being
asked` → `Gathering the Cockpit data catalogue` → `Checking this is a Cockpit
question` → `Planning the analysis`, and stopped:

> The model's response was cut off at its 4096-token output limit so the
> opus_plan is incomplete.

One aggregation and one ranking had produced a 4,096-token planning response.

## The root cause

Two things, one on top of the other.

**The contract asked for a credit memo.** `opus_plan.md` asked, at the moment
the model was supposed to be writing executable instructions, for "your
assumptions, how you will handle missing data, ... a short statement of the
method you chose and why, an alternative if the inputs turn out to be
insufficient, and how the results will answer each subquestion" — with no
bound on any of it, and nothing saying what did *not* belong. Nothing in the
schema said how long a field could be or how many entries a list could have.
So the planning reply carried narrative reasoning, per-field justification, a
discussion of alternatives, and prose about what the numbers would mean.

None of that is wrong. It is in the wrong turn. Interpretation belongs in the
turn that has the results in front of it, and that turn has its own allowance.

**Field definitions were being copied back out.** The catalogue is INPUT: 751
field definitions go to Opus in the stage-B packet. When the plan writes
`"ead_reported — the exposure at default recorded for the facility position,
in INR crore"` instead of `"ead_reported"`, it is spending output tokens
restating what it was just given.

**And there was no defined behaviour for a truncated reply.** The truncation
surfaced as `OpusUnavailable` → `PROVIDER_ERROR`, which blames the provider for
doing exactly what it was told. Worse, the partial turn had already been
appended to the conversation, so the next request would have carried an
assistant `tool_use` with no matching `tool_result`.

## What changed

### The contract

`opus_plan.md` now opens with "Be concise. This is an execution plan, not the
final answer," and says in terms what does not belong: narrative reasoning,
business explanation, field definitions, restatement of the catalogue,
justification of each field, discussion of alternatives not taken, and any part
of the final answer. Brevity applies to the *description* of the method, never
to the method, and never to the SQL.

The turn's own user message shrank from about 1,500 characters to about 730.
That is not cosmetic: the brief is appended to `messages` and is carried for
the rest of the request, so every sentence in it is paid for again on every
repair and review turn. General guidance belongs in the contract, which sits in
the system blocks and is replaced each turn.

### The bounds

`contracts.PlanBounds`, stated in the schema so the model is told and enforced
in `contracts.bound_plan` / `bound_steps` so a model that ignores the schema
still produces something the runtime can hold.

| Field | Bound |
|---|---:|
| `subquestions` | 5 |
| `fields_required` | 30 |
| `joins_required` | 10 |
| `assumptions` | 8 |
| `steps` | 6 Standard, 8 Deep |
| `method_summary` | ~600 characters |
| `alternative_method` | ~400 characters, optional |
| `missingness_handling` | ~400 characters |
| each assumption | ~200 characters |
| each plan step line | ~200 characters |
| each subquestion | ~200 characters |
| step `purpose` | ~300 characters |
| a field name | 80 characters |
| **step `code` (the SQL)** | **not bounded** |

The step count is read from `Limits.steps_per_submission` rather than being
written down twice, so the plan contract and the execution ledger cannot drift
apart.

These are **orchestration controls**. Nothing here is shown to a user, nothing
here is a claim about what a good analysis looks like, and none of it
constrains the SQL — a query is exactly as long as correctness requires, and a
query trimmed to fit an allowance is a query that returns the wrong thing.

Everything the bounds trim is **reported** in `outcome.planning.bounds_applied`.
Nothing is quietly shortened and then allowed to read as what the model wrote.

### Canonical field names

`contracts.canonical_field_name` takes `"sector_name - the economic sector of
the borrower"` down to `"sector_name"`. It does not invent a name and does not
correct one; it drops the commentary attached to a reference, which loses
nothing, because the SQL is what executes and `fields_required` is the
reference list beside it. `cockpit_facility_quarter.ead_reported` is left
alone.

### Truncation, and the one retry

`opus.OutputTruncated` is now its own type, carrying the purpose and the limit.
When a planning reply is truncated:

1. the partial turn is **rolled out of the conversation** — no dangling
   `tool_use`, and the retry's allowance is not spent re-reading the prose that
   overran;
2. the progress line reads **"Refining the analysis plan"**;
3. **Opus** is asked once, over the same context, with the `opus_plan_compact`
   contract and an explicit notice that the previous response exceeded the
   allowance and was discarded unread;
4. that plan executes.

A second truncation raises `opus.PlanTruncated` and the request stops as
`STOPPED_OUTPUT_LIMIT` with `stop_reason = PLAN_OUTPUT_TRUNCATED`. There is no
third attempt.

The stop does not push the question back at the user. What overran was the
model's own plan, not anything that was asked for, so it says exactly that:
"Nothing is wrong with the question and rewording it is unlikely to help." It
names the response allowance and says Deep allows a longer one; it does not
show `max_tokens`, a stop reason, a schema or a tool name.

**CreditProbe writes no part of the plan.** There is no branch in `opus.py` or
`runtime.py` that composes one, shortens the model's prose into one, or reuses
the partial response. A test asserts the executed plan is field-for-field what
the model returned and that the retry brief carries no SQL.

### How the retry counts

| | |
|---|---|
| Another provider/model request | **yes** |
| Charged against tokens, cost and the deadline | **yes** |
| Consumes an execution submission | **no** — none had been submitted |
| Increments the analysis round | **no** — the round was opened when PLANNING was entered |
| Resets any budget | **no** |

### The new terminal state

`STOPPED_OUTPUT_LIMIT` is the mirror of `CONTEXT_TOO_LARGE`: one is the model's
REPLY not fitting its allowance, the other is the PACKET not fitting the input
cap. Opposite ends of the same call, and an operator sent to the wrong one
looks at something that was never the problem. It is in
`states.STOPPED_BY_GUARDRAIL`, reachable from every working state, and
documented in `FINAL_AGENTIC_ARCHITECTURE.md`.

## Measured

Planning output for the two regression questions, from
`test_plan_bounds.py` and `test_live_uat_regression.py`:

| Question | Planning output |
|---|---:|
| "Which sectors saw the largest increase in Stage 2 exposure over the latest year?" | **~227 tokens** |
| "What is total exposure at default by sector in the latest quarter?" | **~227 tokens** |
| The same question, before | reached the 4,096-token allowance and was cut off |

Against the §11 target of "well below 2,000 and preferably below 1,000", a
compact plan for one aggregation and one ranking is a few hundred tokens.

These are the sizes of a compact plan as this application accepts it, produced
by the labelled mock. **How verbose a real model chooses to be is a live
measurement and has not been taken**; the bounds are what stop it mattering,
and the retry is what recovers when it does.

## What was NOT changed

- The 4,096 / 6,144 output allowances. Raising them was the one solution ruled
  out, and a test asserts both.
- The 64,000 / 96,000 input caps, the 250,000 / 500,000 cumulative ceilings,
  the 60 s / 120 s deadlines, five submissions, three rounds, 12/16 model
  requests, $1.00 / $2.00.
- The final-answer contract. Planning got smaller; the answer did not, and a
  test asserts the review-and-answer contract is not told to be terse.
- Opus's ownership of the method, the plan, the SQL, the repair and the
  sufficiency review.

## A margin worth watching

The stage-B analysis conversation runs close to Standard's per-call cap: with
the dictionary pinned, a plan, a repair and a review turn measure about 54,600,
57,300 and 59,600 tokens against a 59,904-token working ceiling. That is
roughly 300 tokens of headroom on the third turn. It is why the planning brief
was moved into the contract rather than left in the message history, and it is
the same finding `CONTEXT_SIZING.md` records: Standard holds the gate, the plan
and about two further turns, and Deep holds the full five-submission path.

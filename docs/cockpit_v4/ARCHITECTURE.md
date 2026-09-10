# Cockpit V4 architecture

One Opus analyst. Four governed tools. A trace made of facts that happened.

## The shape

```
user question
  → POST /runs           persist run + outbox in ONE transaction, return 202
  → worker claims a lease
  → assemble small authorized context
  → ┌ generation ─────────────────────────────────────────┐
    │ the analyst chooses ONE action:                     │
    │   inspect_catalog   selected metadata               │
    │   execute_analysis  its own exact SQL/Python        │
    │   read_artifact     exact stored evidence           │
    │   finalize_response the terminal answer             │
    └─────────────────────────────────────────────────────┘
  → validate · authorize · execute · persist artifacts
  → tool_result back to the analyst, in order
  → (repeat until finalize, or until a bound stops it)
  → validate the answer against the evidence
  → PERSIST the answer, THEN publish answer.ready
  → optional memory maintenance, separately bounded
```

Ordinary help finishes in **one** generation. A simple analysis finishes in
**two** when the starting context already carries enough schema, or three when
one metadata lookup is needed. Those are architectural minimums, not promises
about a particular model's behaviour or elapsed time.

## Who is allowed to do what

| Component | May | Must not |
|---|---|---|
| The analyst (Opus) | understand the original wording, choose mode and owner, choose fields and method, write and repair code, assess evidence, write the answer | grant itself permissions or budget; treat dataset text as instructions |
| `context.py` | return exact authorized catalog/product/thread facts, paginate, redact | infer a business answer, invent a field, choose a method |
| `contracts.py` + `execute_tool.py` | validate schema, permissions, safety, grain, limits | rewrite a query, trim a step, substitute a field, compute a substitute answer |
| `execute_tool.py` runner | execute exactly the approved code in isolation | reach another domain, a credential, the shell, the network or host files |
| `orchestration.py` | carry messages, match tool ids, persist state, enforce counters and deadlines | repair the plan, the code or the answer; fall back to V3 |
| the UI | render persisted answers and events, collect clarification, cancel, reconnect | guess progress; claim a call succeeded without an event |
| `memory.py` | summarize completed history with turn-id citations | block delivery, invent facts, overwrite newer memory |

The one thing that is *not* authorship: deterministic formatting of a value
already bound to executed evidence. Rendering `5231.577413502459` as
`5,231.58 INR crore` at the declared precision is presentation. Changing which
column it came from is substance, and no code here can do it.

## Modules

```
backend/cockpit_v4/
  __init__.py        domain constant and schema versions
  config.py          the V4 settings contract; fails closed on what matters
  contracts.py       typed intent/tool/answer contracts; rejects, never repairs
  contracts/*.json   the application JSON Schemas from the master spec
  states.py          states, terminal outcomes, error codes, transition registry
  events.py          the persisted event sequence and its SSE frames
  run_store.py       SQLite/WAL: runs, events, messages, artifacts, leases,
                     idempotency, reservations, threads, turns, summaries
  budgets.py         counters, cost reservations, the run deadline
  capability.py      the verified model capability record and price card
  provider.py        one explicit model, native tool loop, real deadlines
  context.py         the small starting context
  catalog_tool.py    inspect_catalog: selective, complete, receipted
  execute_tool.py    execute_analysis: validate whole batch, run exactly
  artifacts.py       read_artifact: exact stored values, tenant-checked
  finalization.py    evidence binding and numeric-claim rendering
  orchestration.py   the single analyst loop
  worker.py          lease claimant and dispatch
  supervisor.py      independent deadlines and abandoned-run recovery
  memory.py          optional post-answer compaction
  routes.py          the additive V4 API
  app.py             the standalone ASGI app
  pyrunner.py        the Python capability, or an honest UNAVAILABLE
  prompts/analyst.md the runtime instruction (short, versioned)

frontend/src/components/cockpit-v4/
  client.ts          start/status/events/cancel/artifacts, bounded reconnect
  reducer.ts         run-id and sequence fenced UI state
  process-panel.tsx  the hideable live trace
  response-panel.tsx answer/referral/clarification/stop
  cockpit-v4.tsx     the ask surface

scripts/cockpit_v4/
  start.py status.py stop.py  + three .command wrappers
  seed_release.py             isolated synthetic release
  live_path_evidence.py       real socket/SSE evidence capture
```

## Three properties that were built, not asserted

**Boundedness.** Every path back to the model consumes a generation attempt,
an execution submission, a round, a format allowance, a correction allowance
or elapsed time — none of which is replenished. `states.TRANSITIONS` records
what each cycle-closing edge spends, and a test fails the build if an edge
closes a cycle without naming one. The same bounds are also exercised against
the live loop, because a graph labelled with counters is not evidence that the
implementation increments them.

**Evidence.** A portfolio number reaches the user through a `numeric_claim`
bound to an artifact *this run* produced, carrying the exact stored value. The
narrative references it as `{{claim.id}}` and the renderer substitutes it at
the declared unit and precision. A claim that restates a figure rounded is
refused. A full answer that reports nothing bound to the evidence is refused.
A *partial* answer that states plainly what it could not establish is accepted
— that is the honest outcome, not an invalid one.

**Durability.** The run, its events, its submitted code, its artifacts and its
cost reservations are committed before the next side effect. `202` means
durable and claimable, not answered. The answer is persisted before
`answer.ready` is published. A worker that stops heartbeating is settled by an
independent supervisor as `INTERRUPTED`, and nothing paid is replayed on a
guess.

## The analysis-round rule

The first `execute_analysis` submission opens round 1. A failed or partly
failed batch may be repaired **within** that round. Only after a batch
completes successfully and its results reach the analyst does the next batch
open a new round. Metadata reads, artifact reads and finalization open no
round.

This avoids asking the orchestrator to judge whether two methods are
"substantively different" — a judgement it has no business making. A failed
batch may change method inside its repair; the five-submission, call, cost and
time limits still bound it.

## What V4 deliberately does not have

- No mandatory Sonnet preprocessing, and no `AI_COCKPIT_PREPROCESS_MODEL` on
  the answer path.
- No separate ownership round trip: intent is declared with the first action.
- No full catalogue in any prompt.
- No planning essay, no functionality-scoring essay, no summary-before-answer.
- No fallback to V3, to another model, or to a deterministic calculator.
- No multi-agent framework, vector database or hosted workflow platform.

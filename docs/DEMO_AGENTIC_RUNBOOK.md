# Demonstration runbook — the agentic layer

Everything below runs with **no ANTHROPIC_API_KEY**. The proactive review needs
no model at all: the screening is DuckDB arithmetic and the specialists go
through the governed runtime, which answers most questions deterministically.

Sign in as `alex.rahman` (ADMIN) or `sara.qahtani` (DATA_STEWARD); password
`creditprobe-demo`.

---

## 1. Start the worker

```bash
docker compose up -d agent-worker
docker compose ps agent-worker          # expect: healthy
```

Or, without Docker:

```bash
PYTHONPATH=. .venv/bin/python -m backend.agentic.worker
```

**Check it:** Agent Operations → RUNS. The worker health panel shows workers
alive, and the queue depth.

---

## 2. Watch an officer work

Cockpit → ask **"Show EAD by sector."**

Expect, under the question:

```
▁▂▇▃▁  Credit Analyst is working
       Understanding your question.
```

then, under the answer:

```
Completed by Credit Analyst — 1 dataset · 1 calculation · all checks passed
VALIDATED
```

Now ask **"Something seems wrong with Contracting. Investigate it."** — expect
**Portfolio Risk Lead**, and an escalation line if the level moved.

Then **"Review the latest portfolio period and tell me what requires
attention."** — expect **Chief Orchestrator**.

**Reduced motion:** turn on the operating system's "reduce motion" setting and
ask again. The pulse becomes a still dot in the same position; nothing else
changes and the layout does not shift.

---

## 3. Trigger a proactive review

Either from the API:

```bash
curl -X POST localhost:8000/api/v1/agentic/review \
     -H 'Content-Type: application/json' \
     -d '{"period": "Q2 2026", "background": true}'
```

or run it inline (blocks for a few seconds, returns the cases):

```bash
curl -X POST localhost:8000/api/v1/agentic/review \
     -H 'Content-Type: application/json' \
     -d '{"period": "Q2 2026", "background": false}'
```

**What should happen** on the demonstration book at Q2 2026:

- ~32,700 rows screened in about a second, no model calls;
- one material segment (Financial Services — Stage 2 share +22.5%);
- four borrower cases, the top contributors to it;
- a notification for every analyst, data steward and administrator.

---

## 4. Inspect the cases

Cockpit → **Requires attention**.

- The sentence above the filters names counts that come from the same grouped
  query as the badges, so they cannot disagree.
- Filter **SEGMENTS**, then **BORROWERS**. Counts change; rows stay one line.
- Click a case. The drawer shows the bottom line, why it matters, the signals,
  the timeline, the evidence with links to each governed analysis, the owner and
  workflow state, comments, and the next actions.
- Click **"How the medium severity was calculated"** — the nine components,
  their weights and their contributions.

---

## 5. Prove replay does not duplicate

Run the review again for the same period.

```bash
curl -X POST localhost:8000/api/v1/agentic/review \
     -H 'Content-Type: application/json' \
     -d '{"period": "Q2 2026", "background": false}'
```

Expect `cases_created: []` and `cases_refreshed: [ …five ids… ]`. The counts in
Requires Attention are unchanged. Anything a person did to a case — triaged it,
assigned it, commented on it — is untouched.

---

## 6. Open an Investigation from a case

In the drawer, press **Investigate**.

An Investigation opens seeded with the case's scope, period and signals, and its
first message reads:

> CreditProbe has opened this Investigation from Risk Case rc_…

The case moves to UNDER_INVESTIGATION and now links to the thread. Ask a
follow-up — it is answered against the case's population, not a fresh reading of
a sentence nobody typed.

---

## 7. Stop a run

Agent Operations → RUNS → the square button on a running row.

The run stops at its next checkpoint and keeps what it completed. It does **not**
disappear: the stage it reached, the tasks that finished and the findings they
produced are all on the run.

To cancel a queued job before it starts, the same button marks it cancelled
outright.

---

## 8. Prove no autonomous material action occurred

This is the check worth doing in front of somebody.

**a) The approvals queue.** Agent Operations → APPROVALS. Anything material an
agent proposed is here, pending. If it is empty, nothing material was proposed —
not "something happened unrecorded", because the gate row is written *before* the
action.

**b) The tool registry.** Agent Operations → AGENTS. No agent's tool list
contains `publish_data`, `certify_method`, `approve_workflow`, `send_workflow`,
`change_limits`, `close_case`, `modify_client_data`, `execute_sql`,
`execute_python`, `fetch_url` or `read_file` — because none of those is a tool.

Verify from a shell:

```bash
PYTHONPATH=. .venv/bin/python -c "
from backend.agentic import tools
print([a for a in tools.NO_TOOL_EXISTS if tools.tool(a) is not None] or
      'none of the material actions has a callable tool')"
```

**c) Every case is a draft.** In the database, no case reached RESOLVED or
DISMISSED without a `risk_case_events` row naming a user:

```sql
SELECT c.case_key, c.status, e.actor_id, e.actor_agent
  FROM risk_cases c
  JOIN risk_case_events e ON e.case_id = c.id
 WHERE c.status IN ('RESOLVED', 'DISMISSED');
```

`actor_id` is always a person. `cases.transition` refuses an agent actor for
those two statuses outright.

**d) The evaluation corpus.** Agent Operations → EVALUATIONS → Certification.
Expect **CERTIFIED — 56 of 56 cases passed, with no safety failure**, and the
eleven APPROVAL cases green.

---

## 9. Stop everything

```bash
docker compose stop agent-worker
```

The worker drains: it finishes its current job and exits. A job still running
after 60 seconds is recovered by the next worker that starts, because the lease
expires and the stale sweep re-queues it.

```bash
docker compose down          # stop the stack, keep the data
docker compose down -v       # stop it and erase the database
```

# Agent Operations

The administrator's view of the governed agentic layer, at `/agent-operations`.

Visible to **ADMIN** and **DATA_STEWARD**. The sidebar hides the link for anyone
else, the page says so plainly if they arrive by URL, and every endpoint behind
it refuses them. Three layers, and only the third is security — the other two
are manners.

Changing a policy or a schedule is narrower still: **ADMIN** only. Seeing what
the autonomy policy is and being able to widen it are different privileges.

---

## AGENTS

The twelve job descriptions. For each: purpose, owner, allowed tools, data
domains, autonomy level, preferred model *role*, maximum steps, timeout,
certification state, evaluation score, and when it last ran.

The parts worth opening are `when_not_to_use` and `escalation_rules`. Every
agent registry ever written says what its agents are for; what makes one
auditable is that each also says what it must **not** do and what it does when
it cannot proceed.

There is no code editor here, deliberately. An agent's permissions live in
`backend/agentic/registry.py`, which is reviewed like any other code. A screen
that let an administrator widen a tool list in a text box would make every
permission in that file decorative.

---

## RUNS

Every run: trigger, officer, specialists, scope, status, start, duration, task
count, usage, and links to the result and the Trace.

Above the table, **worker health** — because the first question when a review
has not appeared is "is anything actually running", and a queue depth with no
worker beside it cannot answer it. If work is queued and no worker is alive, the
panel says so and tells you the jobs are durable.

### Cancel

Sets a flag. The worker notices at its next checkpoint and stops cleanly, so a
cancelled run still shows what it completed. Nothing is killed mid-write.

### Retry

Re-enqueues a **proactive** run only. Re-running somebody's question on their
behalf would put an answer they did not ask for into a thread they are reading.

---

## SCHEDULES

| Schedule | Trigger | Ships |
|---|---|---|
| New period portfolio review | On dataset published | **Enabled** |
| Quarterly portfolio review | Quarterly | Disabled |
| Daily unresolved case review | Daily | Disabled |
| Weekly watchlist review | Weekly | Disabled |

One enabled, because it is the demonstration's own flow. A product whose first
act is to start running daily jobs nobody asked for is one its operator learns to
distrust.

A schedule carries its trigger, scope, agents, methods, data requirement,
approval policy, notification recipients, budget and enabled state. `Run now`
queues it immediately; the scheduler never runs a review inline, because a tick
that held the queue for minutes would starve every user's question behind it.

A schedule whose required datasets are not published at the current period is
**skipped with a reason**, not run against missing data.

---

## POLICIES

| Key | Governs |
|---|---|
| `autonomy` | What agents may do without asking. Ships with nothing pre-approved. |
| `budgets` | The interactive and proactive ceilings |
| `screening` | What counts as a material movement |
| `severity` | The nine weights and the four bands |
| `notification` | Who is told, and at what severity |
| `retention` | How long agentic records are kept |

**Versioned by row, never edited.** Writing a new version and deactivating the
old one costs one row and makes "what was the threshold when this case was
raised" answerable off the screen. A row updated in place cannot answer it.

---

## APPROVALS

Gates waiting for a person, filtered to what **this** role can actually decide —
a queue full of items somebody cannot act on trains them to ignore the queue.

Each shows §22's full record: the proposed action, its consequence in plain
words, the reason, the evidence, the agent, the scope, the objects affected, the
risk, the reversibility and the approver role.

Three decisions: **APPROVE**, **REJECT**, **REQUEST CHANGE**. The last two need
a note. A decision cannot be taken twice — an approval that could be flipped
afterwards leaves no record of which decision the action was taken under.

---

## EVALUATIONS

Two tiers.

**Quick check** — a sample, one case per area. A health check, and the result
says it is not a certification.

**Certification** — all 56 cases. The verdict comes first, then the sixteen §59
areas scored separately, then the failures. Not one percentage: "87% accurate"
does not answer "can it be trusted not to close a case on its own".

Safety areas — data permissions, human approval, loop prevention, budget
adherence, workflow safety — are marked, and **a single failure in one fails the
run** whatever the accuracy.

The whole corpus is deterministic and calls no model, which is what makes running
it on demand from a browser reasonable.

---

## Running the worker

```bash
# In Docker, with the rest of the stack
docker compose up -d agent-worker

# Directly, for development
python -m backend.agentic.worker
```

The worker claims jobs, works, heartbeats, and stops cleanly on SIGTERM: it
finishes the job it is in the middle of and exits. A job that outlives the
60-second grace period is recovered by the next worker's stale-lease sweep, so
nothing is lost either way.

Its health check is not a port probe. A worker serves nothing, and a process
that is running but has stopped claiming jobs is not healthy — so the check asks
whether this host's row in `agent_workers` is beating.

---

## When something goes wrong

| Symptom | Look at | Likely cause |
|---|---|---|
| A review never appeared | RUNS → worker health | No worker alive; jobs are queued and durable |
| A run says `dead_letter` | RUNS → the run's failure | Attempts exhausted. The reason is on the row. |
| A run stopped early | The run's `budgets` | A meter ran out. It says which, and what remained. |
| A schedule did not fire | SCHEDULES → last run | Disabled, or its required data is not published |
| An action did not happen | APPROVALS | It is waiting for a person. That is the design. |
| Cases did not update | The event log (`/agentic/events`) | The event was `ignored`, with a reason |

## Budgets

| Meter | Interactive | Proactive |
|---|---|---|
| Orchestration passes | 2 | 3 |
| Delegated tasks | 12 | 24 |
| Repair attempts | 1 | 2 |
| Model calls | 8 | 16 |
| Analytical scans | 20 | 60 |
| Rows read | 8,000,000 | 40,000,000 |
| Output characters | 24,000 | 60,000 |
| Runtime | 180s | 1,200s |

A limit of **zero** means none allowed. Unlimited is a negative limit, which
nothing in the shipped policy uses.

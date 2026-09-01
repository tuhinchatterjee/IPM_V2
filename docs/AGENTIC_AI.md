# The governed agentic layer

CreditProbe operates as a team of credit-risk specialists rather than a
question-answering assistant. The principle the whole layer is built to hold:

> **Agents may propose, coordinate and interpret.
> CreditProbe's governed runtime must calculate and prove.
> Humans must approve material side effects.**

Nothing in `backend/agentic/` computes a credit figure. Every number an agent
reports came out of the deterministic Analytical Runtime through the Tool
Registry, carries a plan fingerprint, and reconciles exactly as it would have if
a person had asked for it directly. What the agents add is *coordination*.

---

## Architecture

```
EVENT OR USER QUESTION
        ↓
    ROUTER                    routing.py — structural signals, counted, no model
        ↓
  OFFICER LEVEL               officers.py — four levels from those signals
        ↓
CHIEF ORCHESTRATOR            orchestrator.py — decompose, delegate, reconcile
  or ONE SPECIALIST
        ↓
 STRUCTURED PLAN → TASK DAG   dag.py — validated before anything runs
        ↓
SPECIALIST AGENTS             registry.py — twelve, each with a job description
        ↓
 GOVERNED TOOLS               tools.py — 22 approved, nothing general
        ↓
DETERMINISTIC RESULTS         run_investigation — the same path a user takes
        ↓
VALIDATION & ASSURANCE        assurance.py — computed, never self-reported
        ↓
    SYNTHESIS                 quoted findings, never paraphrase
        ↓
RESULT / RISK CASE / DRAFT    cases.py, workflow
        ↓
   TRACE / AUDIT              runs.py — every stage, tool call and version
```

### Modules

| Module | What it owns |
|---|---|
| `officers.py` | Which of the four officer levels a request gets, and why |
| `registry.py` | The twelve specialists and the 24-field agent contract |
| `tools.py` | The 22 approved tools and the permission gate |
| `dag.py` | The task graph, its layers, and refusing a plan that cannot terminate |
| `orchestrator.py` | Decomposition, delegation, reconciliation, synthesis |
| `interactive.py` | The officer record around a user's own question |
| `review.py` | The proactive new-period review, §35's eleven steps |
| `screening.py` | Deterministic pre-screening — the funnel, with no model |
| `severity.py` | The versioned severity formula |
| `cases.py` | Risk Cases and their lifecycle |
| `budgets.py` | Loop and cost safety |
| `autonomy.py` | The five autonomy levels and the approval gates |
| `approvals.py` | Gates, persisted before the action they gate |
| `handoff.py` | Structured handoffs and evidence-settled disagreement |
| `assurance.py` | Answer Assurance from what the run observed |
| `memory.py` | Scope-checked agentic working memory |
| `queue.py` | The durable Postgres task queue |
| `worker.py` | The agent worker loop |
| `runs.py` | Run persistence and the Trace story |
| `events.py` | Governed events, recorded once |
| `principals.py` | Who a run acts as, and what it may read |
| `notifications.py` | Who is told, and — mostly — when not to tell them |
| `schedules.py` | Governed schedules and versioned policies |
| `evaluation.py` | The 56-case corpus and the certification bar |

---

## Agent roles and model roles

These are different things, and conflating them is the mistake §3 exists to
prevent.

**A MODEL ROLE** — `router`, `planner`, `interpretation`, `critic` — is
configuration. Which model serves each is set in `backend/llm/roles.py` and
changes.

**An AGENT ROLE** is a business specialist: Data Steward, IFRS 9, Portfolio
Risk. It has a purpose, a tool list, data domains, a budget and an autonomy
level. It *prefers* a model role; it is never a model.

A Chief Orchestrator is a job, not a model ID. A user who learns to read the
title as a model name learns something that becomes false the next time the
configuration changes.

## The twelve specialists

| Agent | Owns | Autonomy |
|---|---|---|
| Data Steward | Catalogue, fields, periods, readiness | 0 Observe |
| Credit Analyst | Bounded descriptive analysis | 1 Recommend |
| Ratings & Financials | Rating migration, financial deterioration | 1 |
| IFRS 9 | Stage, SICR, ECL, coverage | 1 |
| Delinquency & Collections | DPD, roll rates, cures | 1 |
| Covenant & Collateral | Headroom, breach proximity, coverage | 1 |
| Portfolio Risk | Portfolio and segment trends, concentration | 1 |
| Early Warning | Deterioration and forward signals | 1 |
| Stress & Scenario | Governed scenarios and sensitivities | 1 |
| Validation & Assurance | Invariants, reconciliation, challenge | 0 Observe |
| Workflow Coordinator | Draft assignments and follow-ups | 2 Draft |
| Chief Orchestrator | Decompose, delegate, reconcile, synthesise | 2 Draft |

`backend/agentic/registry.py` is the source. Definitions are mirrored into
`agent_definitions` so an administrator can see versions, evaluation scores and
history — but the permissions live in the file, because a security posture that
can be edited in a form without review is not one.

---

## Officer levels

Four levels are shown to the user. They come from the complexity and risk
signals `backend/orchestration/routing.py` already counts, plus domain breadth,
analytical grain and the number of specialists the work actually needs.

| Level | Title | For |
|---|---|---|
| 1 | Credit Analyst | Metadata, one dataset, one figure, a presentation change |
| 2 | Senior Credit Officer | Several steps, two domains, a period comparison, a join |
| 3 | Portfolio Risk Lead | A segment or the portfolio; Early Warning; scenarios |
| 4 | Chief Orchestrator | Broad, multi-domain, coordinated specialist work |

### Not from phrases

§5 forbids phrase-specific rules, and the reason is practical: "look at
Contracting" and "investigate Contracting" are the same work, and a product
where the second gets a more senior officer has made the level a property of
vocabulary.

Three things decide it, and none of them is a word:

1. **The score.** Routing's structural signals — datasets, concepts, periods,
   referents, breadth — plus this layer's own: governed domain count, grain,
   operations, specialist count, materiality, proactive initiative.
2. **The grain floor.** §4 defines levels 3 and 4 by grain rather than by
   difficulty. A borrower-grain two-domain question and a sector-wide
   investigation score identically and are different jobs; the grain says so.
3. **The coordination floor.** Three specialists whose findings have to be
   reconciled is the Chief Orchestrator's job, whatever it scored.

### Chosen twice

The first selection sees only the sentence, so the indicator appears the instant
Ask is pressed. The second sees what the analysis actually read. The difference
is an **escalation** (§9) — the request grew — and it is one-directional:
discovering half-way through that the work was simpler does not demote the
officer in front of the user.

Persisted on every run: `officer_level`, `officer_title`, `selection_reason`,
`complexity_score`, `risk_score`, `agent_count`, `planned_task_count`.

---

## The task engine

A Postgres-backed queue (`agent_jobs`), not Redis. An agentic job's state is
already in Postgres and has to be transactional with it: a job acknowledged in
Redis and lost in Postgres is a run that silently vanished, and the reverse is a
run that silently happened twice.

- **Claim** — `SELECT … FOR UPDATE SKIP LOCKED`. Two workers racing take two
  different rows.
- **Lease** — 120 seconds, extended by a heartbeat thread while work runs.
- **Recovery** — an expired lease returns the job to `queued` and counts the
  lost attempt, so a job that kills every worker dead-letters rather than
  looping.
- **Retry** — exponential backoff from 5s, capped at 300s.
- **Dead letter** — attempts exhausted. The job stops costing money and leaves a
  row saying why.
- **Cancellation** — a flag, not a kill. The worker stops at its next
  checkpoint, so a cancelled run is a *recorded* run showing what it completed.
- **Idempotency** — a partial unique index allows one live job per
  `(kind, key)`.

### Swapping it out

§17 asks for an abstraction so Temporal or Celery could replace it. That
abstraction is the module surface — `enqueue`, `claim`, `heartbeat`, `complete`,
`fail`, `cancel`, `recover_stale`. Nothing outside `queue.py` writes
`agent_jobs`, and nothing inside the agents knows a queue exists.

---

## Autonomy and approval

| Level | Name | Means |
|---|---|---|
| 0 | Observe | Read governed state and summarise it |
| 1 | Recommend | Propose an analysis or an action |
| 2 | Draft | Create a draft case, investigation, workflow item or link |
| 3 | Execute pre-approved | Only where an administrator policy allows |
| 4 | Material side effect | **Never without a named person** |

Level 4 has **no path**. There is no autonomy setting that grants it, no policy
that unlocks it, and — the part that matters — no tool in the registry that
performs one. An agent cannot publish data, certify a method, approve a workflow
item, change a limit, close a case, send an external message or modify client
data, because the function does not exist for it to call.

That is the difference between a permission check and an architecture: a check
can be wrong, and a missing function cannot be called.

What an agent *can* do is propose one, which opens an **Approval Gate**. The
gate row exists BEFORE the action; approving it is what causes the action, not a
receipt for one that already happened. It carries the proposed action, the
reason, the evidence, the agent, the scope, the objects affected, the risk, the
reversibility and the approver role — because an approver asked to trust a
one-line summary is an approver rubber-stamping.

---

## Loop and cost safety

Eight meters, each closing a specific way a run can consume without bound:
iterations, tasks, repairs, model calls, scans, rows, output size, runtime.

Every meter is charged **before** the thing it pays for. A budget checked
afterwards has already been exceeded, and the model call it was meant to prevent
has already been billed.

Exhaustion is a first-class outcome, not an error: the run stops, states what it
completed, states what remains, and asks. §20's word is *silently*.

A limit of **zero** means none allowed, not unlimited. (This was a real defect,
found by the evaluation corpus: `if limit and …` treated them as the same thing,
so an administrator switching something off by setting its budget to 0 would have
granted it without a ceiling.)

---

## The proactive review

§35's eleven steps, with §36's funnel:

```
the whole book                        32,692 rows
  → deterministic screening           DuckDB aggregates, ~1s, no model
  → material segments                 governed thresholds, not judgement
  → material borrowers                top contributors to those segments
  → specialist analysis               agents, on a bounded population
  → LLM synthesis                     only on validated findings
```

Measured on the demonstration book at Q2 2026: **32,692 rows screened down to
four borrowers — 0.0122% of the book reached a specialist**, with zero model
calls in the screen itself.

A review that asked a model about each borrower would cost hundreds of calls to
reach the same four names, could not be reproduced, and would turn "the model
said Contracting deteriorated" into an assertion nobody could check. Doing the
arithmetic first turns it into "Stage 2 share in Financial Services rose from
5.22% to 6.39%".

### No duplicates on replay

Two constraints, both in the database:

- `uq_agent_event_once` on `(kind, idempotency_key)` — a publication delivered
  twice produces one event, therefore one run.
- `uq_risk_case_dedupe` on `dedupe_key` — a replayed review UPDATES the case it
  already made. Verified: a second run of the same period creates 0 new cases
  and refreshes 5.

A refresh recomputes the severity and the evidence and leaves the **human**
state alone — owner, status, comments, due date. A review that reset a triaged
case to NEW every time it ran would undo somebody's work on a schedule.

---

## Risk Cases

A Risk Case is **not** an Investigation. An Investigation is a conversation
somebody is having; a Risk Case is a finding with a lifecycle, an owner and a due
date, which may *cause* an Investigation.

Four levels — PORTFOLIO, SEGMENT, BORROWER, DATA_QUALITY — and nine statuses:
NEW, TRIAGED, UNDER_REVIEW, UNDER_INVESTIGATION, ACTION_PENDING, MONITORING,
RESOLVED, DISMISSED, SNOOZED.

RESOLVED and DISMISSED are **human-only**. `cases.transition` refuses an agent
actor outright: the requirement is not "an agent with enough autonomy may close
a case", it is that a person must.

### Severity is arithmetic

Nine components with published weights, a version, and the whole calculation
stored on the case and shown in the drawer:

| Component | Weight |
|---|---|
| Exposure at stake | 0.22 |
| Size of the movement | 0.22 |
| Adverse signals | 0.12 |
| Risk appetite | 0.12 |
| How long it has been moving | 0.10 |
| Concentration | 0.08 |
| Data and relationship confidence | 0.05 |
| Method and invariant validation | 0.05 |
| Evidence completeness | 0.04 |

Bands: 0.75+ critical, 0.55+ high, 0.35+ medium, below low.

A severity decides which case a credit officer opens first on a Monday morning.
An ordering produced by a language model changes between two runs over identical
data and cannot be argued with — and "why is this case above that one" is a
question somebody eventually asks in a room where the answer matters. The LLM
may *explain* the score; it may not produce it.

---

## Answer Assurance

> "Do not show LLM self-confidence as the answer confidence."

A model's stated confidence is a prediction about its own output made by the
thing that produced it, and it is uncorrelated with whether the ECL figure on
screen reconciles. Assurance is computed from what happened: data completeness,
relationship validation, method certification, plan validation, business
invariants, reconciliation, evidence grounding, model agreement, known
limitations.

Four statuses — HIGH ASSURANCE, VALIDATED, LIMITED EVIDENCE, NEEDS REVIEW — and
the status is the **weakest link, not an average**. A result that fails its
invariants is not "mostly assured" because seven other checks passed.

---

## Permissions and tenancy

Every specialist inherits the requesting principal's permissions. A user must not
gain access to data through an agent they could not reach directly, and the
guarantee is the intersection: an agent whose definition allows every domain
still cannot read one the calling user cannot, and a user with every permission
still cannot make an agent read outside its definition.

A proactive run acts as a named service identity, `creditprobe.review`, with the
DATA_STEWARD role — wide enough to read the published book, narrow enough that it
cannot manage models or approve anything. A background process holding the widest
role in the product is how a convenience becomes an escalation path.

Results are filtered on **read**, not on write, because one case is read by many
people with different permissions.

### Tenancy — a release requirement

The product is currently single-tenant: one bank's data in one deployment, and
no table carries a tenant id. §58 asks that where tenancy is not implemented the
boundary is preserved and documented, and `principals.TENANT` /
`principals.tenant_of()` are that boundary. Every agentic object is scoped
through them, so making the product multi-tenant means giving `tenant_of()` a
real implementation rather than auditing every query that forgot.

**This is a release requirement before any multi-tenant deployment.**

---

## Trace

§26's layers are on every agentic run: trigger, officer selection, orchestration
plan, delegation, task, tool call, data and method, result, handoff, challenge,
validation, approval, synthesis, action, final answer.

§27's Story reads them without clicking a node: TRIGGERED, ORCHESTRATED,
INVESTIGATED, VALIDATED, DECIDED, ACTIONED.

No hidden chain-of-thought appears anywhere. Every string rendered is a
structured field the run recorded — a purpose, a finding, a validation state, a
tool id. There is no code path from a prompt to the Trace.

---

## Evaluation

`backend/agentic/evaluation.py` — 56 deterministic cases across §59's sixteen
areas. No model calls; every case exercises a permission check, a plan
validation, budget arithmetic or an approval rule, which are the parts that can
be wrong in ways nobody notices.

**Quick check** (§61) — one case per area, for a health check. Not a
certification, and the result says so.

**Certification** (§62) — the whole corpus. The bar: **zero safety failures**,
then 90% accuracy over at least 20 cases. Safety is not averaged — a run that
correctly refused nineteen material actions and performed the twentieth has
failed, not scored 95%.

The corpus earned its keep on the first run by failing two real defects: the
zero-budget bug above, and an inverted evidence component that made thin evidence
*raise* a case's severity — which would have sent officers to the least
established finding first.

---

## Safety summary

| Property | How it holds |
|---|---|
| No arbitrary SQL, Python, network or filesystem | Not in the Tool Registry. There is nothing to call. |
| No material action without a person | §21 Level 4 actions have no tool, and no autonomy grants them |
| No agent closes a Risk Case | `cases.HUMAN_ONLY` checks the ACTOR, not a permission |
| No unbounded spend | Eight meters, charged before the work, zero means zero |
| No infinite delegation | The plan is validated before it runs; the orchestrator is not on its own delegation list |
| No duplicate cases on replay | Two unique constraints in the database |
| No access widening through an agent | Permissions intersect; a service identity is not an administrator |
| No self-reported confidence | Assurance is computed from observations |
| No invented severity | A published, versioned formula with its arithmetic on screen |
| No hidden reasoning surfaced | Only structured stages and recorded fields are rendered |

---

## Verifying it

Four commands, in this order. None of them calls a model or spends a credit.

```bash
# The layer's own tests: officers, registry, queue, orchestration, cases,
# approvals, the review, the worker.
PYTHONPATH=. pytest tests/agentic tests/api/test_agentic_api.py -q

# The frontend's pure modules: the indicator's rules and the case ordering.
cd frontend && npm test

# §77 — the browser acceptance, against a running stack. Cockpit idle and
# working, a stage transition, the completion line, all five attention
# filters, the case drawer, Agent Operations, the agentic Trace, the approval
# queue, reduced motion, four themes and three viewports.
python scripts/acceptance/agentic_browser_acceptance.py http://127.0.0.1:3000

# §78 — the cost of every step a screen waits on, with the funnel's own
# figures at the end.
python scripts/acceptance/agentic_performance.py
```

### What §78 measures, and why the funnel is the headline

| Step | Measured | Budget |
|---|---|---|
| Officer selection (no I/O) | 0.0 ms | 10 ms |
| Agent registry | 0.3 ms | 50 ms |
| Evaluation corpus, 56 cases | 2.6 ms | 2 s |
| Officer preview endpoint | 8 ms | 500 ms |
| Risk case listing | 13 ms | 500 ms |
| Agentic runs listing | 18 ms | 500 ms |
| Deterministic pre-screen, whole book | 133 ms | 30 s |

The last row is the one that matters. Screening the whole book at Q2 2026 reads
**32,692 rows**, reduces them to **one material segment and four borrowers**, and
makes **zero model calls** — 0.0122% of the book reaches a specialist. That is
what §36 means by refusing "unrestricted model calls over the entire raw book":
the expensive half of a proactive review only ever sees what deterministic
arithmetic has already established is worth looking at.

The officer number matters for a different reason. It runs on every question a
user asks, before anything else, so it has to be free — and it is, because it
reads structure the router already produced rather than doing any work of its
own.

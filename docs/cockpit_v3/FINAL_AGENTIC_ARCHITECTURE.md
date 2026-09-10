# Cockpit Agentic V3 — the frozen architecture

The architecture as implemented at the freeze, not as intended. The state
tables here are generated from the code and checked by tests, so a document
that says something the code does not do is a test failure rather than a
discrepancy someone finds later.

**Not merged. Not live-validated.** This describes what the application does,
and says nothing about how a model behaves inside it.

## 1. The responsibility split

| | Owns |
|---|---|
| **Sonnet** (`AI_COCKPIT_PREPROCESS_MODEL`) | Language detection · spelling and transcription cleanup · faithful translation into English · business-request normalization · the final rolling thread-summary update |
| **Opus** (`AI_COCKPIT_REASONING_MODEL`) | Query-mode classification · functionality ownership · analytical reasoning and methodology · the analysis plan · SQL generation · Python generation · SQL repair · Python repair · sufficiency review · final interpretation · presentation choice · the one final prose repair |
| **CreditProbe** | Authentication · authorization · request state · context construction · the Cockpit domain restriction · schema and catalogue · data grain · validation · safe deterministic execution · diagnostics · request counters · time, token, cost and resource guardrails · provenance · result storage · thread storage · final-answer evidence validation · the response envelope |

```
OPUS REASONS.  OPUS WRITES.  OPUS REPAIRS.
CREDITPROBE VALIDATES.  EXECUTES.  DIAGNOSES.  ENFORCES.
```

**CreditProbe has no runtime path that rewrites Opus SQL or Python.** Proved
by reading the source rather than by asserting it: no assignment back into a
step's code anywhere in the package; no string outside `sql.py` naming a
Cockpit relation after `FROM` or `JOIN`, so the two metadata queries `sql.py`
needs are the only SQL this application composes; nothing in `failure.py` that
tells Opus which field to use; no call in `runtime.py` named for a fallback, a
template or a decomposition; and no assignment to `narrative` in
`answer_check.py`. See `test_repair_ownership.py` and
`test_answer_validation.py`.

## 2. The data boundary

Cockpit reads `corporate_cockpit` and nothing else: 991 addressable columns
across 11 relations over 20 reporting quarters, holding identifiers and
exposure, IFRS 9 (PIT and TTC PD at 12-month and lifetime, LGD and EAD
variants, stage, ECL, stored scenarios, overlays, SICR, default), collateral
with types, values, valuations, haircuts and allocations, covenants with
thresholds, headroom, breaches, waivers and cures, the 19-grade AAA-to-C
scale, 40 ratios, 20 qualitative assessments, balance sheet, income statement,
the cash-flow and debt-service inputs, and 10 macro factors over offsets
−4…+15 with forecast vintage preserved.

It cannot read Early Warning, Credit Scoring, Scorecard Validation, What-if,
Lenses, Playbook or Planner data. The enforcement is the DuckDB session, which
materializes only the allowlisted relations and then disables external access
and locks the configuration; `test_sql_security.py` proves it against a real
engine, including a case that bypasses the validator entirely.

Generic model knowledge and the controlled product registry are not analytical
data domains and are not restricted by this.

## 3. The query modes

Decided by Opus, semantically, **on every turn**. Never inherited from the
previous turn, never a keyword match.

| Mode | Runs SQL/Python | Consumes | Ends at |
|---|---|---|---|
| `PRODUCT_HELP` | no | nothing | `COMPLETED` |
| `THEORY_CONCEPT` | no | nothing | `COMPLETED` |
| `DATA_ANALYSIS` | yes, when the owner is COCKPIT | submissions and rounds | `COMPLETED` / `PARTIAL` / a stop |
| `OTHER_FUNCTIONALITY` | no | nothing | `REDIRECTED` |
| `CLARIFICATION_REQUIRED` | no | nothing | `WAITING_FOR_USER` |
| `UNSUPPORTED` | no | nothing | `UNSUPPORTED` |

Owners: `COCKPIT`, `EWS`, `CREDIT_SCORING`, `SCORECARD_VALIDATION`,
`WHAT_IF`, `LENSES`, `GENERAL_CREDITPROBE_HELP`, `NONE`.

**Only `DATA_ANALYSIS` + `COCKPIT` executes.** `FunctionalityDecision.may_execute`
is the single predicate, and the dataclass refuses a decision whose mode and
decision contradict each other rather than leaving the runtime to resolve it
later.

### Product help and theory

Answered from knowledge in the gate turn — one Opus call, no second. Zero SQL,
zero Python, zero execution submissions, zero analysis rounds, and the machine
never enters `VALIDATING` or `EXECUTING`. That is structural: the branch
returns before reaching the loop that consumes them.

A statement about **CreditProbe specifically** must be grounded in the product
registry. Generic credit and accounting theory is allowed; "how does
CreditProbe determine SICR" is not, unless the registry documents it, and the
honest answer where it does not is that it cannot be verified from the
configured product information. `answer_check` catches an invented mechanism.

### Mixed theory and data

"Explain PIT PD and show how it moved" is `DATA_ANALYSIS`, not
`THEORY_CONCEPT`. Both halves are owed an answer and the second needs the book.

### Current external information

Closed explicitly. Nothing configured here holds current external facts, so
such a question is `UNSUPPORTED` and is never answered from model memory.

## 4. Ownership, decided by the server

Opus assesses; two numbers decide, in `FunctionalityDecision.ownership_test`:

* the Cockpit scores **≥ 70**, and
* the Cockpit is the highest, and
* the Cockpit leads the next functionality by **≥ 10**.

Otherwise `CLARIFICATION_REQUIRED`. A near-tie is a question for the user, not
a coin toss resolved in the Cockpit's favour, and a confident explanation is
not evidence: the scores are read by the server rather than taken from the
decision field.

Hard responsibility boundaries override scores. Historical observed ECL
movement is the Cockpit's; increasing PD 20% and recalculating is What-if; why
an EWS score rose is Early Warning; generating a score is Credit Scoring;
discrimination and calibration are Scorecard Validation.

## 5. Guardrails

| | Standard | Deep |
|---|---:|---:|
| Execution submissions | **5** | **5** |
| Analysis rounds | **3** | **3** |
| Deadline | 60 s | 120 s |
| Opus input packet | 64,000 | 96,000 |
| Cumulative input | 250,000 | 500,000 |
| Model calls | 12 | 16 |
| Charts | 2 | 3 |
| Spend ceiling | $1.00 | $2.00 |

Thread context: 3 complete Q&A pairs by default, 5 where useful, **8
absolute**. The earliest guardrail reached wins. No automatic Standard → Deep
escalation. The model is told the remaining budgets and cannot change them:
`execution_submissions` and `analysis_rounds` have no override at any level.

A submission is consumed when Opus SUBMITS, before validation — so a rejected
candidate costs one, which is what closes the unlimited pre-execution
generation loop. A duplicate (code + parameters + release, hashed) costs one
and is **not run again**; Opus may still write something different with what
remains, and only exhaustion ends the request.

## 6. Repair

Every failed validation or execution returns a packet to Opus containing the
original question, both Sonnet outputs, the thread, the pinned scope, the
complete catalogue with grains, coverage and missingness, the ownership
decision, the current plan, the successful intermediate results, the exact
failed code, its bound parameters, the exact diagnostic and its category, the
authorized alternatives, the prior failed approaches, and every remaining
budget.

**Sixteen items, verified on the actual assembled request immediately before
dispatch.** A missing one stops the request rather than sending Opus a repair
task it cannot do. `failure.OUTBOUND_ITEMS`.

Join and grain safety is part of validation: `sql.MULTIPLYING_JOINS` names the
relation pairs that repeat rows and `multiplication_risk` reports
`JOIN_MULTIPLICITY_RISK` with both grains, the multiplicity and the measure at
risk — and stops there, because which de-duplication is right depends on the
question and choosing one would be choosing the analysis.

## 7. The final answer

Opus returns narrative, `findings[]`, `fact_ids[]`, `tables[]`, `charts[]`,
`limitations[]`, `suggested_questions[]`.

Before anyone sees it, CreditProbe checks it:

| Outcome | What happens |
|---|---|
| `VALID` | render |
| `UNSUPPORTED_NUMERIC_CLAIM` | back to Opus, once |
| `INVALID_EVIDENCE_REFERENCE` | back to Opus, once |
| `DOMAIN_LEAK` | back to Opus, once |
| `INVALID_PRODUCT_CLAIM` | back to Opus, once |
| `RESPONSE_CONTRACT_INVALID` | back to Opus, once |
| `INVALID_CHART` | **the chart is dropped**, and nothing is re-analysed |
| a suggestion naming a field or quarter this domain lacks | **it is dropped**; if all fail, none are shown |

Every figure in the prose must appear in the executed results, or in a
difference, percentage change, sum, mean or count between them. Rounding is
accepted; 42 for 52 is not. Years, quarter labels and bare ordinals are not
treated as measurements, because a check that fires on those is one a reader
learns to ignore.

**The rewrite is one.** It cannot execute, cannot open an analysis round and
cannot reset a counter — and has no means to: `REWRITE_SCHEMA` carries no plan
and no steps. A second failure renders only what is supported, with a
limitation saying what was removed. There is no third attempt and no loop.

CreditProbe does not write the replacement prose. `rewrite_request` reports
what failed, attaches the answer exactly as written, and hands it back.

## 8. The thread

The summary is written **after** the answer already exists, so a failure there
cannot erase it: the last valid summary is retained and the turn is marked
unsummarized. No retry loop.

Factual hierarchy: **exact stored result > exact recent turn > rolling
summary.** The summary is never the source of truth over evidence.

A thread's identity is tenant + data release + catalogue version + thread id,
not the thread id alone — so identical question text from another tenant
shares nothing. A prior result may be READ as context whatever its scope, and
REUSED as a number only when the scope matches; where it does not, the fact
ids are stripped and the turn is labelled as prose only.

## 9. The state machine

`backend/cockpit_agentic/states.py`. Every edge carries its event, condition,
side effect and what it consumes.

### Working states, and the two context stages

The context is assembled in two stages, and the second one is built on exactly
one edge. `BUILDING_CONTEXT` assembles the LIGHT gate packet — the question,
the thread, the functionality registry and the domain in outline. Only
`FUNCTIONALITY_ASSESSMENT → PLANNING`, taken when `query_mode = DATA_ANALYSIS`
and `owner = COCKPIT` and the score test passes, assembles the FULL analytical
packet with the complete field dictionary. Product help, theory, a referral, a
clarification and an unsupported request leave the gate without it ever
existing.

```
RECEIVED → NORMALIZING_1 → NORMALIZING_2 → BUILDING_CONTEXT
                                             │ stage A: the gate packet
                                             ▼
                                    FUNCTIONALITY_ASSESSMENT
         ├─ PLANNING → VALIDATING → EXECUTING → REVIEWING → ANSWERING
         │    ▲ stage B: the full analytical packet is built here, and only here
         └─ (no-execution modes and referrals leave here, with no stage B)
         → ANSWER_VALIDATION → SUMMARIZING → terminal
```

The two stages are two Opus conversations, each with its own cached prefix, so
neither prefix ever changes under itself. Sizes and the measurement behind them
are in `docs/cockpit_agentic_v3/CONTEXT_SIZING.md`; the defect that led to the
split is in `docs/cockpit_v3/LIVE_UAT_REMEDIATION.md`.

### The transitions

| State | Event | Condition | Next | Side effect | Terminal |
|---|---|---|---|---|---|
| `RECEIVED` | request accepted | authenticated and authorized | `NORMALIZING_1` | ledger opened; scope, release and deadline pinned | no |
| `RECEIVED` | authorization refused | principal may not read this scope | `STOPPED_SECURITY` | nothing is read; the refusal is recorded | **yes** |
| `NORMALIZING_1` | pass 1 returned | the question was cleaned | `NORMALIZING_2` | — | no |
| `NORMALIZING_1` | pass 1 failed | the call raised or returned nothing | `NORMALIZING_2` | proceeds on the preserved raw text with the failure flagged; intent is never silently rewritten | no |
| `NORMALIZING_1` | cannot clean safely | meaning would change to proceed | `WAITING_FOR_USER` | a targeted clarification; this request closes | **yes** |
| `NORMALIZING_2` | pass 2 returned | a business request was produced | `BUILDING_CONTEXT` | — | no |
| `NORMALIZING_2` | cannot understand safely | the request is ambiguous | `WAITING_FOR_USER` | a targeted clarification; this request closes | **yes** |
| `BUILDING_CONTEXT` | gate packet assembled | the light stage-A packet fits the input cap | `FUNCTIONALITY_ASSESSMENT` | the question, the thread, the functionality registry and the domain in OUTLINE; no field dictionary, no coverage table, no sample rows and no execution contract | no |
| `FUNCTIONALITY_ASSESSMENT` | gate returned | query_mode=DATA_ANALYSIS and owner=COCKPIT and the score test passes | `PLANNING` | the full stage-B analytical packet is built -- this is the ONLY edge that builds it -- and the first analysis round is consumed | no |
| `FUNCTIONALITY_ASSESSMENT` | gate returned | query_mode is PRODUCT_HELP or THEORY_CONCEPT | `ANSWER_VALIDATION` | Opus answered in the gate turn, from the gate packet; zero submissions, zero rounds, and the field dictionary was never assembled | no |
| `FUNCTIONALITY_ASSESSMENT` | gate returned | owner is another functionality | `REDIRECTED` | a referral with a configured destination; zero execution | **yes** |
| `FUNCTIONALITY_ASSESSMENT` | gate returned | query_mode=CLARIFICATION_REQUIRED, or the score test fails | `WAITING_FOR_USER` | a targeted question; this request closes | **yes** |
| `FUNCTIONALITY_ASSESSMENT` | gate returned | query_mode=UNSUPPORTED, including current external information | `UNSUPPORTED` | the boundary is explained; nothing is fabricated | **yes** |
| `PLANNING` | Opus submitted candidate code | submissions remain | `VALIDATING` | one execution submission is consumed | no |
| `PLANNING` | Opus chose to answer without executing | the plan needs no data | `ANSWER_VALIDATION` | — | no |
| `PLANNING` | Opus asked for clarification | the request is ambiguous | `WAITING_FOR_USER` | this request closes | **yes** |
| `PLANNING` | Opus explained and stopped | the data cannot answer it | `INSUFFICIENT_DATA` | — | **yes** |
| `PLANNING` | the repair could not be dispatched | the effective context could not be assembled, or the failure is not repairable | `EXECUTION_FAILED` | an application defect is reported as one; no repair request is sent that Opus could not act on | **yes** |
| `PLANNING` | submissions exhausted | five have been consumed | `STOPPED_EXECUTION_LIMIT` | Opus explains what was tried | **yes** |
| `PLANNING` | rounds exhausted | three have been consumed | `STOPPED_ANALYSIS_LIMIT` | what was established is reported | **yes** |
| `VALIDATING` | validation passed | the candidate is safe and resolvable | `EXECUTING` | — | no |
| `VALIDATING` | validation failed, repairable | the diagnostic goes back to Opus and submissions remain | `PLANNING` | CreditProbe authors nothing; Opus writes the next candidate | no |
| `VALIDATING` | validation failed, not repairable | out of scope or permission denied | `EXECUTION_FAILED` | fails closed; looking for a workaround would spend attempts on nothing | **yes** |
| `VALIDATING` | duplicate candidate | the code, parameters and release hash to a prior failure | `PLANNING` | the submission is consumed and the code is NOT run again | no |
| `VALIDATING` | forbidden operation | the candidate reaches outside the authorized domain | `STOPPED_SECURITY` | — | **yes** |
| `VALIDATING` | submissions exhausted | five have been consumed | `STOPPED_EXECUTION_LIMIT` | — | **yes** |
| `EXECUTING` | execution succeeded | results were produced | `REVIEWING` | — | no |
| `EXECUTING` | execution failed, repairable | the runtime diagnostic goes back to Opus and submissions remain | `PLANNING` | CreditProbe authors nothing | no |
| `EXECUTING` | execution failed, not repairable | no attempts remain or the failure is closed | `EXECUTION_FAILED` | — | **yes** |
| `EXECUTING` | sandbox refused the code | the isolation boundary was reached | `STOPPED_SECURITY` | — | **yes** |
| `REVIEWING` | SUFFICIENT | every subquestion is answered | `ANSWERING` | — | no |
| `REVIEWING` | NEEDS_FURTHER_ANALYSIS | the method must materially change and rounds remain | `PLANNING` | one analysis round is consumed | no |
| `REVIEWING` | NEEDS_FURTHER_ANALYSIS | no rounds remain | `STOPPED_ANALYSIS_LIMIT` | what was established is reported | **yes** |
| `REVIEWING` | NEEDS_USER_CLARIFICATION | the answer depends on a choice only the user can make | `WAITING_FOR_USER` | — | **yes** |
| `REVIEWING` | MISSING_DATA | the domain does not hold it | `INSUFFICIENT_DATA` | — | **yes** |
| `REVIEWING` | MISSING_DATA | partial findings are supported | `PARTIAL` | — | **yes** |
| `REVIEWING` | OUT_OF_SCOPE | another functionality owns it | `REDIRECTED` | — | **yes** |
| `REVIEWING` | BUDGET_STOP | a guardrail was reached | `STOPPED_EXECUTION_LIMIT` | — | **yes** |
| `ANSWERING` | Opus returned the final answer | always | `ANSWER_VALIDATION` | — | no |
| `ANSWER_VALIDATION` | validation passed | every claim traces to evidence and the envelope is well formed | `SUMMARIZING` | — | no |
| `ANSWER_VALIDATION` | validation failed | no rewrite has been used yet | `ANSWERING` | the ONE permitted answer-only rewrite; it cannot execute, cannot open a round and cannot reset a counter | no |
| `ANSWER_VALIDATION` | validation failed again | the rewrite has been used | `PARTIAL` | only the safely supported content is rendered, with a limitation saying what was removed | **yes** |
| `ANSWER_VALIDATION` | domain leak detected | the answer names data outside the authorized domain | `STOPPED_SECURITY` | — | **yes** |
| `SUMMARIZING` | summary updated | the call succeeded | `COMPLETED` | — | **yes** |
| `SUMMARIZING` | summary failed | the call raised | `COMPLETED` | the delivered answer stands; the turn is marked unsummarized and the last valid summary is retained. No retry loop | **yes** |
| `SUMMARIZING` | partial answer summarized | the answer was partial | `PARTIAL` | — | **yes** |
| `SUMMARIZING` | referral summarized | the turn was a referral | `REDIRECTED` | — | **yes** |
| `SUMMARIZING` | clarification summarized | the turn asked a question | `WAITING_FOR_USER` | — | **yes** |
| `SUMMARIZING` | stop summarized | the turn stopped | `UNSUPPORTED` | — | **yes** |
| `SUMMARIZING` | stop summarized | the data did not support it | `INSUFFICIENT_DATA` | — | **yes** |
| `SUMMARIZING` | stop summarized | execution failed | `EXECUTION_FAILED` | — | **yes** |

### Reachable from every working state except SUMMARIZING

A guardrail reached while saving a summary must not take a delivered answer
away, which is why `SUMMARIZING` is excluded.

| Event | Condition | Next | Side effect |
|---|---|---|---|
| deadline reached | clock past the request deadline | `STOPPED_TIME_LIMIT` | the stop names the deadline |
| user cancelled | cancel flag set on the ledger | `CANCELLED` | in-flight work is stopped; usage is retained |
| token ceiling reached | cumulative input would exceed it | `STOPPED_TOKEN_LIMIT` | the stop names the ceiling |
| spend ceiling reached | the next call would exceed it | `STOPPED_COST_LIMIT` | the stop names the ceiling |
| model call ceiling reached | no provider calls remain | `STOPPED_EXECUTION_LIMIT` | the stop names what was tried |
| provider failed | the provider raised | `PROVIDER_ERROR` | no deterministic substitute is produced |
| model roles unconfigured | either role is unset | `MODEL_CONFIGURATION_MISSING` | the stop names the variable |
| no Cockpit provider credential | COCKPIT_ANTHROPIC_API_KEY is unset or empty | `PROVIDER_CREDENTIAL_MISSING` | the stop names the variable and never the value; no fallback to ANTHROPIC_API_KEY or any other credential |
| model refused by provider | the provider will not serve it | `MODEL_UNAVAILABLE` | the stop names the id |
| packet will not fit | measured above the input cap | `CONTEXT_TOO_LARGE` | nothing is sent |
| the reply would not fit twice | the model's response reached the output allowance, and the one permitted compact regeneration did too | `STOPPED_OUTPUT_LIMIT` | the partial response is discarded, not executed; no execution submission is consumed and this application writes no replacement |
| pinned release unavailable | the release cannot be read | `DATA_UNAVAILABLE` | no silent switch to another release |
| forbidden operation attempted | the engine or sandbox refused a boundary violation | `STOPPED_SECURITY` | the attempt is recorded; nothing runs |
| unexpected application failure | an unhandled exception | `INTERNAL_ERROR` | stage and error id recorded; no secrets, no stack trace, no fallback |

### Terminal states

| State |
|---|
| `COMPLETED` |
| `PARTIAL` |
| `REDIRECTED` |
| `UNSUPPORTED` |
| `WAITING_FOR_USER` |
| `STOPPED_EXECUTION_LIMIT` |
| `STOPPED_ANALYSIS_LIMIT` |
| `STOPPED_TOKEN_LIMIT` |
| `STOPPED_COST_LIMIT` |
| `STOPPED_TIME_LIMIT` |
| `STOPPED_SECURITY` |
| `STOPPED_OUTPUT_LIMIT` |
| `MODEL_CONFIGURATION_MISSING` |
| `MODEL_UNAVAILABLE` |
| `PROVIDER_CREDENTIAL_MISSING` |
| `PROVIDER_ERROR` |
| `DATA_UNAVAILABLE` |
| `CONTEXT_TOO_LARGE` |
| `INSUFFICIENT_DATA` |
| `EXECUTION_FAILED` |
| `CANCELLED` |
| `INTERNAL_ERROR` |

`INSUFFICIENT_DATA`, `EXECUTION_FAILED`, `PROVIDER_ERROR`,
`PROVIDER_CREDENTIAL_MISSING` and `STOPPED_OUTPUT_LIMIT` are this
implementation's additions to the specification's list. Each is distinct from
its nearest neighbour:
`INSUFFICIENT_DATA` is a readable domain that does not hold the answer, where
`DATA_UNAVAILABLE` is an unreadable release; `EXECUTION_FAILED` is every
attempt failing for a reason inside the analysis, where
`STOPPED_EXECUTION_LIMIT` is running out of attempts; `PROVIDER_ERROR` is the
provider not answering, where `MODEL_UNAVAILABLE` is a model that does not
exist here and `INTERNAL_ERROR` is this application's own defect; and
`PROVIDER_CREDENTIAL_MISSING` is nobody having configured the Cockpit's own
credential, where `MODEL_CONFIGURATION_MISSING` is nobody having said which
model answers — one sends an operator to `COCKPIT_ANTHROPIC_API_KEY` and the
other to the two model-role variables. `STOPPED_OUTPUT_LIMIT` is the model's
REPLY not fitting its allowance twice, where `CONTEXT_TOO_LARGE` is the packet
not fitting the input cap — opposite ends of the same call, and an operator
sent to the wrong one looks at something that was never the problem.

### Why no request can run forever

Cycles are found by search rather than assumed, and each contains an edge that
spends something finite and never replenished:

| Cycle | Costs | Cap |
|---|---|---:|
| `PLANNING` → `VALIDATING` → `PLANNING` | an execution submission | 5 |
| `PLANNING` → `VALIDATING` → `EXECUTING` → `PLANNING` | an execution submission | 5 |
| `PLANNING` → … → `REVIEWING` → `PLANNING` | an analysis round | 3 |
| `ANSWERING` → `ANSWER_VALIDATION` → `ANSWERING` | the answer rewrite | 1 |

`test_state_machine.py` enumerates the simple cycles and fails if any can be
traversed for free, so a fourth loop cannot be added silently.

## 10. Security boundaries

**SQL** — one SELECT, against materialized allowlisted relations, in a session
with external access disabled and configuration locked.

**Python** — a separate process in fresh mount, network, PID, IPC and UTS
namespaces, chrooted into a tmpfs jail holding the standard library and
`numpy`/`pandas` only. No `/usr/bin` at all, so there is no shell. No network,
no `/etc`, no repository, no credential. Address space, CPU, file size and
process count bounded; privileges dropped before the code runs; workspace
removed afterwards; cancellation kills the whole PID namespace. Availability
is established by running a job that tries to escape, and where the probe does
not pass, Python is reported unavailable rather than downgraded.

**Prompt injection** — dataset text travels as a JSON string value inside a
data section, under the untrusted-data note, and never in a system block. The
hierarchy is system policy > product configuration > user request > data
content, which is the block order.

**Models** — `AI_COCKPIT_PREPROCESS_MODEL` and `AI_COCKPIT_REASONING_MODEL`
fail closed. No fallback to `AI_MODEL`, to another role, or to the SDK's
default. Missing → `MODEL_CONFIGURATION_MISSING`; refused by the provider →
`MODEL_UNAVAILABLE`. Neither is answered from a deterministic substitute.

**The credential** — the Cockpit reads `COCKPIT_ANTHROPIC_API_KEY` and nothing
else. Not `ANTHROPIC_API_KEY`, which in this deployment is also the Claude Code
agent's own; not the SDK's implicit discovery; not the legacy application
setting. Missing → `PROVIDER_CREDENTIAL_MISSING`, before the first provider
request. The rest of CreditProbe keeps its existing provider configuration,
which is correct for it: this isolation is the Cockpit's requirement, not a
change of convention for the product.

The value is read from the environment on demand and never stored — no module
global, no dataclass field, no settings attribute. Diagnostics report
`PRESENT` or `MISSING` and nothing else: no prefix, no suffix, no length, no
hash, no masked form. `backend/cockpit_agentic/credential.py` is the only
place it is read, and a test reads that module's own source to confirm it
reaches the environment exactly once.

## 11. Data release and macro vintage

Every execution uses the request's pinned `data_release_id`. If it becomes
unreadable the request ends `DATA_UNAVAILABLE`; there is no switch to the
latest, because another release is a different book and answering from one
while the question named the other is wrong in a way nobody can see.

Macro rows carry observation quarter, target quarter, forecast vintage and
scenario. A later revised forecast is never presented as though it were known
at the historical reporting date; `check_macro_vintages` and
`check_no_future_actuals` are release gates.

## 12. Example journeys

**"What can I do in Cockpit?"** — Sonnet ×2 → gate returns `PRODUCT_HELP` with
its answer → evidence check (no numeric claims to trace) → summary →
`COMPLETED`. One Opus call. Zero submissions, zero rounds.

**"What is SICR?"** — as above, `THEORY_CONCEPT`. Generic theory answered; had
it asked how CreditProbe determines SICR, the answer would say that cannot be
verified from the configured product information.

**"How did ECL move last quarter?"** — Sonnet ×2 → gate returns
`DATA_ANALYSIS`/`COCKPIT` with a plan and SQL (round 1) → validate → execute →
review `SUFFICIENT` → answer → evidence check → summary → `COMPLETED`. One
submission, one round.

**"Show me PD."** — gate returns `CLARIFICATION_REQUIRED` with four options
(PIT/TTC × 12-month/lifetime) → `WAITING_FOR_USER`. Nothing executed; the
reply is a new request in the same thread.

**"Increase ABC's PD by 20% and recalculate ECL."** — gate returns
`OTHER_FUNCTIONALITY`/`WHAT_IF` → `REDIRECTED` with the configured route.
Zero execution, and the other functionality is not invoked.

**A column that does not exist** — submission 1 fails binding →
`UNRESOLVED_FIELD` naming the four real PD fields with their meanings and
units and an explicit instruction not to substitute one silently → Opus writes
submission 2 → executes. Two submissions, one round.

**A figure that is not in the results** — the answer says 52 where the table
says 42 → `UNSUPPORTED_NUMERIC_CLAIM` → the one rewrite → validates → renders.
No submission, no round.

## 13. What this document does not claim

That any of it produces good answers. Every automated test behind it uses the
labelled mock provider and proves an application property. Model behaviour is
`BLOCKED`/`UNVERIFIED` until a credential is configured and
`scripts/cockpit_v3_live_validation.py` has run.

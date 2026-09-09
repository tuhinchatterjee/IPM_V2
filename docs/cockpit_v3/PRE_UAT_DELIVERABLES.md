# Cockpit Agentic V3 — pre-UAT deliverables

**DO NOT MERGE.** Not production ready. Nothing below that was produced by a
mock is described as live validation.

## A. Branch and HEAD

| | |
|---|---|
| Branch | `claude/cockpit-agentic-v3-fhg4r0` |
| HEAD | `312fad86ec9ea03da85a172651f9778bacef7d86` |
| Parent | `claude/cockpit-intelligence-v2-mbb22o` at `83b39a6`, untouched |
| Merged into main | **No** |

## B. Field-family audit and totals

Three counts, all correct. Quoting one without saying which had already misled
a reader of this project's own documents before the audit existed:

| Count | What it counts | Value |
|---|---|---:|
| Field definitions | `fields.ALL_FIELDS` — the 24 common keys defined once | 751 |
| Distinct canonical names | Unique column names anywhere in the domain | 763 |
| **Addressable columns** | Every `relation.column` a query author faces | **991** |

751 definitions + 24 common keys × 10 relations = 991. The macro
pivot is a generated view and takes no common keys.

| Family | Addressable columns |
|---|---:|
| A — identifiers and exposure | 20 |
| B — ifrs9 | 59 |
| C — collateral | 35 |
| C — collateral summary | 115 |
| D — covenants | 35 |
| E — rating | 17 |
| F — ratios | 129 |
| G — qualitative | 9 |
| H — balance sheet | 60 |
| I — income statement | 32 |
| I — ratio inputs | 19 |
| J — macro | 16 |
| J — macro pivot | 200 |
| K — reporting calendar | 5 |
| Z — keys and provenance | 240 |
| **Total** | **991** |

Groups A–K all present, named field by named field: 40 ratios,
20 qualitative questions, the exact 19-grade scale AAA…C,
10 macro factors over offsets −4…+15 with forecast vintage preserved,
20 reporting quarters. Per-field detail — definition, source, type, unit,
grain, quarter applicability, aggregation, measured missing rate,
availability — in `docs/cockpit_v3/COCKPIT_FIELD_AUDIT.md`.

## C. Cockpit-only isolation

| Check | Result |
|---|---|
| No declared field belongs to another module | PASS |
| No **published Parquet column** belongs to another module | PASS |
| No readable relation belongs to another module | PASS |
| No published column is undeclared | PASS |

Searched across Early Warning, Credit Scoring, Scorecard Validation, What-if,
Lenses and Playbook markers, against the physical columns rather than the
declaration. A test feeds the search eleven names drawn from those modules and
requires it to catch all eleven, because a search that finds nothing proves
nothing.

The one family of exceptions is the eight `scenario_*` IFRS 9 fields, each
listed with its justification: scenario outputs the source system already
computed and stored. Reading a stored scenario is not running a new one — the
boundary is the ACTION — and a test pins the exception set so a ninth cannot
be added silently.

**Isolation is enforced by the engine, not by this audit.** The DuckDB session
materializes only the allowlisted relations, then disables external access and
locks the configuration. `test_sql_security.py` proves it against a real
engine, including a case that bypasses the validator entirely.

## D. Context-packet token measurements

| Section | Tokens |
|---|---:|
| D/E — the complete field dictionary, grains, joins, enumerations | 22,079 |
| F — measured coverage | 6,152 |
| H — functionality registry | 2,330 |
| G — sample rows | 922 |
| I — execution capabilities, SQL and the Python sandbox | 729 |
| B — server-confirmed scope | 620 |
| A, C, J — question, thread, budget | 443 |
| **Whole packet** | **33,388** |
| **Required core**, what the guardrail forbids reducing | **26,114** |
| Floor, every reduction spent | 28,105 |

| Budget | Standard | Deep |
|---|---:|---:|
| Per-call input | 64,000 | 96,000 |
| Cumulative | 250,000 | 500,000 |

Estimated locally at 3.4 characters per token, deliberately conservative.
Under a live credential this is replaced by the provider's own count against
the exact model that will serve the request, and every result records which
method produced it. **An estimate is never reported as a measurement.**

**What binds first is spend, not tokens.** At $5/MTok input a 28,000-token
call costs about $0.14; the $1.00 ceiling is reached between the fifth and
sixth call while barely 170,000 of the 250,000 tokens are used. Per the
instruction the ceilings stay and live usage will be measured against them.
Standard affords **6** full-context Opus calls and Deep **10**, so the §9.1
call ceilings of 12 and 16 are unreachable with this catalogue — reported
because "12 calls permitted" would mislead.

Unmoved, as required: 5 execution submissions, 3 analysis rounds, the 60 and
120-second deadlines, no automatic Standard→Deep escalation, earliest bound
wins.

## E. Prompt-cache design

One breakpoint, at the end of the invariant prefix. Four system blocks:

| # | Block | Cached |
|---|---|---|
| 1 | Architecture instructions, the division of labour, the domain boundary | yes |
| 2 | Domain id, release id, currency, scale, **the full compact catalogue**, grains, relationships, functionality definitions, the execution contract | yes — the breakpoint sits here |
| 3 | The per-turn contract | no |
| 4 | The untrusted-data note | no |

Everything volatile is in the conversation, after the prefix: the question,
the Sonnet outputs, the filters, the thread, the plan, the exact previous
results, the failed code, the latest diagnostic, the remaining budgets.

A test asserts the prefix is **byte-identical across all three turns of one
request** — which is what caught the first attempt, where the per-turn
contract sat before the breakpoint and every turn was a cache miss. Other
tests assert the catalogue is inside the prefix, that volatile values are not,
and that the catalogue is still logically present in every request.
**Caching is an optimization only**: the ledger counts cached reads toward the
token ceiling either way, and no request is sent with a hash standing in for
the catalogue.

## F. Python executor status

**AVAILABLE on this host**, strategy `privileged_namespaces`, established by running a
job in a real jail whose code tries to escape.

| Guarantee | Evidence from this host |
|---|---|
| `network_denied` | connect() raised OSError |
| `host_filesystem_hidden` | /etc/passwd raised FileNotFoundError; root holds ['dev', 'lib', 'lib64', 'proc', 'site', 'tmp', 'usr', 'work'] |
| `host_files_read_only` | writing the bound /usr/lib raised OSError |
| `jail_skeleton_read_only` | /usr raised PermissionError; /site raised PermissionError |
| `repository_hidden` | /home/user/IPM_V2 not present |
| `inputs_read_only` | appending to the input raised PermissionError |
| `environment_scrubbed` | no credential-shaped variables |
| `no_shell` | /bin/sh raised FileNotFoundError; no binary directory exists |
| `dependency_surface` | approved: ['2.5.0', '3.0.3']; unapproved importable: none |
| `privileges_dropped` | uid 65534 |
| `separate_process` | a child process, never the API process |

Separate process; fresh mount, network, PID, IPC and UTS namespaces; chroot
into a tmpfs jail holding the standard library and `numpy`/`pandas` only; no
`/usr/bin` at all, so "no shell" is a fact about the filesystem rather than a
policy; address space, CPU, file size and process count bounded; privileges
dropped before the code runs. Where the probe does not pass, Python is
reported unavailable — no in-process fallback, no restricted `eval`, no AST
allowlist, and a test reads the source and fails if any appears.

A hardened production container will not grant these namespace privileges.
`docs/cockpit_v3/PYTHON_EXECUTION_BOUNDARY.md` names the separate-service
mechanism such a deployment needs and where the seam already is.

## G. Actual model ids

**Not available — no credential is configured.**

| Role | Environment variable | Configured id in this container |
|---|---|---|
| `cockpit_preprocess` | `AI_COCKPIT_PREPROCESS_MODEL` | **not set** |
| `cockpit_reasoning` | `AI_COCKPIT_REASONING_MODEL` | **not set** |

**These two now fail closed.** Neither inherits from another role, from
`AI_MODEL`, or from the provider SDK's default. Unset, blank or malformed
stops the request with `MODEL_CONFIGURATION_MISSING`; configured but rejected
by the provider stops it with `MODEL_UNAVAILABLE`. Neither is ever answered
from a deterministic substitute.

Before this correction both roles would have fallen through to the SDK's own
pinned default, and a commissioning run would have measured a model nobody
chose. `docs/cockpit_v3/MODEL_CONFIGURATION.md` records what changed and the
tests that hold it.

What a live provider would actually serve is **UNVERIFIED**.
`scripts/cockpit_v3_live_validation.py` reports the ids and the provider's own
token counts against them the moment a credential exists.

## H. Cockpit V3 test results

**397 tests, all passing.** Every one uses the labelled mock provider or no
provider at all. They prove application properties — the gate runs first, a
referral executes nothing, five submissions is five, the repair request
carries the effective context, the sandbox boundary holds, CreditProbe authors
no SQL. **They prove nothing about model behaviour.**

```
COCKPIT_AGENTIC_V3=true .venv/bin/python -m pytest tests/cockpit_agentic -q
```

## I. Regression classification

| | Failing tests |
|---|---:|
| This branch | 413 |
| Preserved V2 base `83b39a6`, same container | 413 |
| **Regressions** | **0** |
| Identical sets, id for id | yes |

| Root cause | Tests |
|---|---:|
| downstream of the empty catalogue or the absent database | 251 |
| the governed data lake has not been built | 71 |
| no PostgreSQL is running | 34 |
| the synthetic corporate universe has not been built | 22 |
| the planner finds no measures, because the catalogue is empty | 13 |
| no scorecard months exist, because nothing was built | 11 |
| the governance check has nothing to govern | 9 |
| there are no reporting periods, because nothing was built | 2 |

All of it resolves to two absent things: the governed data lake was never
built in this container, and PostgreSQL is not running. Nothing is filed as a
pre-existing PRODUCT failure, because nothing observed distinguishes a broken
product from an unfed one — the document says so rather than choosing the
flattering reading.

**The set comparison was not enough.** Failure messages were compared too, and
found one test failing WORSE here than on the base: the decimal contract, six
unallowed high-precision sites against the base's three. Three were mine. Two
were correct and are now allowlisted with the reason written down; the third
printed model spend to four decimals in a stop message and was wrong — it now
reports how much of the ceiling is left, in cents. Detail in
`docs/cockpit_v3/REGRESSION_CLASSIFICATION.md`.

## J. Remaining blockers, exactly

0. **Neither Cockpit model role has an id configured.** Nothing runs until
   both are set — that is now enforced rather than warned about. Set
   `AI_COCKPIT_PREPROCESS_MODEL=claude-sonnet-5` and
   `AI_COCKPIT_REASONING_MODEL=claude-opus-5`.
1. **No provider credential.** Everything that depends on a model is
   BLOCKED/UNVERIFIED: routing accuracy, translation fidelity, plan quality,
   repair quality, answer quality, latency, and real token and cost figures.
2. **No real data.** Every field in the release is `demo_only`. Nothing is
   ingested from a real source and `COCKPIT_DATA_DOMAIN_MAPPING.md` says so.
3. **No built data lake and no PostgreSQL in this container**, which is why
   413 tests outside the Cockpit fail here — and fail
   identically on the base.
4. **Thread state is in memory.** `backend/services/threads.py` is the seam;
   nothing binds it, so a restart loses thread continuity.
5. **The spend ceiling is inert until prices are configured**, and the ledger
   reports `spend: UNKNOWN` rather than implying a control it does not have.
6. **The Python sandbox needs namespace privileges** this container grants and
   a hardened production container will not.
7. **The question bank is ungraded.** 84 questions and 10 controlled cases are
   written; none has been run against a model.

## K. Manual browser UAT — exact commands

```sh
# 1. Build the release (refuses to publish if any of the 72 gates fails)
COCKPIT_AGENTIC_V3=true .venv/bin/python scripts/build_cockpit_agentic_v3.py --overwrite

# 2. Backend, with the flag on
COCKPIT_AGENTIC_V3=true .venv/bin/python -m uvicorn backend.api.main:app \
    --host 127.0.0.1 --port 8000

# 3. Frontend, in a second terminal
cd frontend && npm run dev          # http://localhost:3000

# 4. Open http://localhost:3000 -- localhost, NOT 127.0.0.1. The API's CORS
#    allowlist names localhost, and a 127.0.0.1 origin is refused by the
#    browser before the request is ever sent.

# 5. What to look at on the screen
#    - the Cockpit badge names the branch, the release and the mode
#    - any raised limit is disclosed on the badge, not only in the logs
#    - the progress states advance: normalizing, assessing, planning,
#      validating, executing, reviewing, answering
#    - with no credential the result is an honest stop saying the model is
#      unavailable -- NOT a deterministic narrative
#    - cancel mid-request and confirm the envelope says it was cancelled

# 6. The scripted browser pass over the same screen
COCKPIT_AGENTIC_V3=true .venv/bin/python tests/cockpit_agentic/browser_uat.py

# 7. Diagnostics, including the measured Python sandbox status
curl -s localhost:8000/api/v1/cockpit/diagnostics | python -m json.tool

# 8. When a credential exists -- from the environment, never on a command line
#    that lands in shell history, never in a file that gets committed
ANTHROPIC_API_KEY=... COCKPIT_AGENTIC_V3=true \
    .venv/bin/python scripts/cockpit_v3_live_validation.py
```

Then work `docs/cockpit_v3/QUESTION_BANK.md` against this branch and against
the preserved V2 branch, side by side, with a credit person reading both. That
review is a person's, not a script's.

## Do not

Merge to main. Declare production ready. Call a mock run live validation.

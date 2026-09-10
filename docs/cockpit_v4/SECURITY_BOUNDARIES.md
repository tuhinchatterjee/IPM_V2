# Security boundaries

## What is actually enforced, and by what

| Boundary | Enforced by | Not enforced by |
|---|---|---|
| Which relations are readable | the DuckDB session materializes **only** the authorized relations, then file access is disabled and the configuration locked before any submitted SQL is admitted (`cockpit_agentic/sql.open_session`) | the SQL text check, which is an early, precise refusal — not the boundary |
| Which tenant's rows | server-derived scope from the authenticated principal (`scope.for_principal`); artifacts are tenant-checked on read | anything the model can say |
| Which domain | there is exactly one: `corporate_cockpit`. EWS, scoring, scorecard validation, What-if, Lenses, Playbook and Planner stores are not in the session at all | a keyword list |
| Python execution | a bounded subprocess jail, or **UNAVAILABLE**. There is no in-process `exec` path | the AST/import allowlist, which is supplementary |
| The credential | `COCKPIT_ANTHROPIC_API_KEY` only. No fallback to `ANTHROPIC_API_KEY`, an SDK default, or another module's key | — |
| Cross-tenant API access | every run, event stream, cancel, artifact and thread is tenant-checked; a mismatch returns 404, never "not permitted" | — |

## The honest limit

Isolation prevents the analyst from **reading** another domain. It does not
mathematically prove that an arbitrary program never **encodes** a
calculation that belongs elsewhere — a sufficiently determined SQL statement
over authorized columns can compute something a What-if user would recognise.

Intent declaration, the ownership check on the execution path, and adversarial
tests strengthen that boundary. None of them proves semantic safety for
arbitrary programs, and this document does not claim otherwise.

## Ownership gate on execution

`execute_analysis` runs only when the intent declared *in that same
submission* is `DATA_ANALYSIS` **and** `COCKPIT` **and** carries no unresolved
ambiguity. A previous turn's owner authorizes nothing: the check is recomputed
from the current declaration (`contracts.Intent.may_execute`,
`execute_tool.validate_batch`).

Tested for `THEORY_CONCEPT + COCKPIT`, `DATA_ANALYSIS + WHAT_IF`,
`PRODUCT_HELP + COCKPIT` and for a data analysis carrying an unresolved
ambiguity — all refused with `SECURITY_DENIED`.

## SQL isolation

Refused in `tests/cockpit_v4/test_ownership_and_security.py`, each against a
real session:

- a relation outside the domain (`ews_alerts`)
- `read_csv_auto('/etc/passwd')` — host file read
- `ATTACH` — another database
- `INSTALL httpfs` — an extension
- `COPY … TO` — writing out
- a stacked statement after a semicolon

Grain checks are separate from safety checks. `multiplication_risk` refuses a
demonstrable repetition trap (a borrower balance sheet summed once per
facility, a shared collateral asset counted whole per allocation) and warns
where static analysis cannot prove correctness — it never silently removes a
join.

## Python

`pyrunner.probe()` reports the capability honestly and runs an escape
self-test before certifying it: network, filesystem, subprocess and
environment access are each attempted in the jail, and if **any** succeeds the
capability is reported UNAVAILABLE with the reason.

In this environment the self-test found network access was not blocked, so
Python analysis is `available: false`. A Python step therefore fails with
`PYTHON_UNAVAILABLE` and is explicitly **not** rewritten as SQL. A UAT that
reports "Python passed" while the analyst only ever wrote SQL is not evidence
of a Python capability, and `ready_for_python_analysis` is a separate
diagnostic flag for exactly that reason.

## Secrets in traces

`orchestration._redact` runs on the way **in**, before an operator detail is
persisted, so a downloadable trace cannot leak what was never stored. It
redacts any key whose name contains `api_key`, `apikey`, `authorization`,
`cookie`, `token`, `secret`, `password` or `credential`, recursively, plus any
string beginning `sk-` or `Bearer `.

Diagnostics report the credential as `PRESENT`/`MISSING` and never its value.
The launcher reads the key from the environment or the macOS Keychain, or
prompts with `getpass` — it is never echoed, never written into the
repository, never placed in a command line, and never requested in a chat
window.

Private reasoning is not exposed. Event `public_message` fields are business
language; operator details carry model ids, request ids, sizes, checks and the
submitted code — not model thinking.

## Untrusted content

Catalog descriptions, qualitative answers, covenant text, database error
strings, stored thread records and result rows are **data**. The analyst
prompt says so explicitly, and more importantly tool authorization does not
consult the model's opinion: an injected instruction cannot widen scope,
because scope is derived server-side from the principal and pinned for the
run.

No guarantee is offered that prompting alone defeats every injection. The
guarantee is that following an injected instruction cannot grant access.

## Local demo auth

`COCKPIT_V4_LOCAL_DEMO_AUTH` issues a server-controlled demo principal, and:

- only for loopback clients (`127.0.0.1`, `::1`);
- scoped to the pinned synthetic release's own tenant, resolved server-side;
- off by default;
- unable to authorize real-data access, another module, public binding or
  production mode.

It does not touch V3's or the product's authentication. `REQUIRE_LOGIN` is not
set globally by anything in this build.

## Real-data egress

Published real data may not be sent to a provider without the deployment's
approval. Permission to use the synthetic demo release is not permission to
send bank data. Nothing in V4 asserts a regulatory certification or a
bank-approved credit policy.

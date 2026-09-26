# Protected-core incompatibility: the capability has no tool to arrive through

Section 1.2 of the What-If specification: *"If the existing architecture has no
compatible hook, write PROTECTED_CORE_INCOMPATIBILITY.md: exact file/symbol,
required behavior, why existing hooks cannot supply it, smallest proposed
change, and consequences. Do not implement that core change, monkey-patch it,
wrap it with a new orchestrator, or quietly weaken a validator."*

This is that document. **Nothing described here has been implemented.** The
P0–P4 work delivered alongside it routes around the blocker entirely; this
records what would be needed if a later phase cannot.

---

## 1. The required behaviour

Section 2 lists eight logical domain operations and says to "map them to actual
repository interfaces." Five of them — discover capabilities, resolve/freeze
cohort, read sensitivity/model cards, draft/revise scenario, preview — are
read-and-assemble operations that a deterministic server-side module can do and
that P0–P4 does do.

The sixth is different:

> **Execute selected methods** — Deterministic results for the confirmed
> version only

and section 19 makes the requirement explicit:

> *"Execute only through registered deterministic methods after confirmation."*

For the analyst to *invoke* a registered deterministic scenario method, that
method has to be reachable from the analyst's turn. Today it cannot be.

---

## 2. Exact files and symbols

The analyst's callable surface is a frozen five-tuple with four independent
copies of its membership, each in a protected file.

| # | File:line | Symbol | What it is |
|---|---|---|---|
| 1 | `backend/cockpit_v4/contracts.py:60-66` | `TOOL_INSPECT`, `TOOL_PRODUCT`, `TOOL_EXECUTE`, `TOOL_READ`, `TOOL_FINALIZE`, `TOOL_NAMES` | The tuple itself |
| 2 | `backend/cockpit_v4/contracts.py:71-73` | `BATCHABLE` | Second closed set |
| 3 | `backend/cockpit_v4/contracts.py:1228` | `_DESCRIPTIONS` | Literal name → description dict |
| 4 | `backend/cockpit_v4/contracts.py:1363-1381` | `tool_schemas` | Literal name → schema-filename map; unknown name raises `ValueError` at `:1352` |
| 5 | `backend/cockpit_v4/contracts.py:1397-1405` | `application_schema` | A **second** copy of the same filename map |
| 6 | `backend/cockpit_v4/contracts/*.schema.json` | 9 JSON files | A directory nothing scans; indexed only by 4 and 5 |
| 7 | `backend/cockpit_v4/action_state.py:58-88` | `STATES` | The turn-gate state set |
| 8 | `backend/cockpit_v4/action_state.py:142-306` | `decide()` | Straight-line `if` cascade with tool tuples written inline |
| 9 | `backend/cockpit_v4/action_state.py:313-315` | `COMPANIONS` | Dict keyed by state, module literal |
| 10 | `backend/cockpit_v4/action_state.py:318-326` | `offered()` | A **fourth** hardcoded copy of the tool order |
| 11 | `backend/cockpit_v4/orchestration.py:1096-1105` | `_handle_call` | `if call.name == …` chain, implicit finalize fallthrough |
| 12 | `backend/cockpit_v4/orchestration.py:1028-1044` | `_handle_turn` | Validates against `TOOL_NAMES` and `BATCHABLE` |
| 13 | `backend/cockpit_v4/orchestration.py:1941-1952` | trace maps | Two more literal name → stage/label maps |

A sixth tool needs a new `parse_<tool>` and dataclass in `contracts.py`, a new
`_do_<tool>` handler on the orchestrator, and an edit to every row above.
**Minimum seven protected files.**

---

## 3. Why no existing hook supplies it

Four candidates were examined. Each fails for a different reason, and the
reasons matter because three of them are deliberate design decisions this
document is not asking to reverse.

### 3.1 There is no plugin or registry mechanism

A search across `backend/cockpit_v4/` for entry points, registration
decorators, `importlib` discovery or dynamic module loading returns **one** hit:
`pyrunner.py:33`, which lists `importlib` among the names the sandbox **bans**.

`catalog_tool.CatalogService` and `execute_tool.ExecutionService` look like
plugin points but are service classes instantiated and called by name from
`orchestration._do_catalog` and `_do_execute`. They register nothing.

### 3.2 `execute_analysis` can carry the calculation but not the registration

This is the near miss, and it is what P0–P4 uses.

The analyst authors its own SQL through `execute_analysis`; `execute_tool`
validates, binds, authorizes and runs it; the result is a governed artifact.
Because published ECL is exactly `ead × pd × lgd` (see
`BASELINE_AND_EXTENSION_MAP.md` §3), proportional Delta is one SQL statement, so
the *arithmetic* needs no new tool.

What it cannot carry is section 19's word **registered**. A submission is code
the analyst wrote; the server validates its shape, its bindings, its grain and
its authorization, but it does not and must not assert that the code implements
a named method. A run that claims "Delta" is a run whose SQL the server compiled
from a confirmed `ScenarioSpec` — and P0–P4 gets that by having `scenario/sql.py`
compile the statement and a test prove the submitted bytes match the compiler's
output. That is a strong guarantee, but it is a *test-time* guarantee, not a
runtime gate: nothing stops a future turn submitting different SQL and calling
it Delta.

For P0–P4 the distinction is acceptable and is recorded in `KNOWN_LIMITATIONS`.
For a phase that must refuse an unregistered method at runtime, it is not.

### 3.3 The Python sandbox is the wrong instrument, deliberately

`pyrunner.py` is a real subprocess jail, and its own header explains why it will
not help here:

> *"This module deliberately has no in-process fallback. `exec` in the worker
> process would have the provider credential, the state database and the whole
> filesystem in reach."* (`pyrunner.py:3-8`)

Four blockers, any one sufficient: it is **off by default**
(`COCKPIT_V4_PYTHON_RUNNER`, and a `self_test()` that must prove the jail
blocks network, filesystem, subprocess and environment access); `-I -S` means
**no site-packages**, so no numpy or pandas; `getattr` is in
`_FORBIDDEN_NAMES`, which most array idioms need; and only `parameters` and
`inputs` cross the boundary, so a borrower-grain book would have to be
serialised through `RLIMIT_AS`.

Deterministic scenario maths belongs in native backend code beside `ecl.py`,
which is exactly where P0–P4 puts it.

### 3.4 The answer payload has nowhere to put a scenario card

`contracts/finalize_response.schema.json` gives a response `tables` and
`charts` and nothing else; `client.ts:130-131` mirrors it; `ResponsePanel`
(`response-panel.tsx:131-305`) is linear JSX with no kind-keyed dispatch.
`CHART_KINDS` is a closed union pinned three ways — server, JSON schema,
frontend — by `visuals.test.ts:255`.

P0–P4 needs no new payload slot: a scenario result is a table and a waterfall,
both of which already exist. A later phase wanting an interactive inline
scenario card would need nine files, including that pinning test.

---

## 4. The smallest change that would supply it

Not implemented. Recorded so the decision can be made on evidence.

**Option A — one new tool, `run_scenario`.** ~7 protected files as listed in §2,
plus `contracts/run_scenario.schema.json`. The state machine gains no state:
the tool is offered in `RESULT_READY` and in a new companion position, and
`decide()` gains one branch. Smallest diff that satisfies section 19's
"registered deterministic methods" at runtime.

**Option B — a tool registry.** Replace the four copies of the tool tuple with
one table and have `decide()` consult it. Larger diff, and it weakens a gate
that round §65 tightened on purpose ("expose only the legal tool and force
it"). **Not recommended**: the closed tuple is load-bearing, and four
independent copies pinned by tests is a deliberate belt-and-braces, not an
oversight.

**Option C — leave it.** Ship the compile-and-verify guarantee of §3.2, record
the gap, and revisit if a later phase genuinely needs a runtime refusal. **This
is what P0–P4 does.**

---

## 5. Consequences of not changing the core

| Consequence | Severity in P0–P4 |
|---|---|
| "Registered method" is a test-time guarantee, not a runtime gate | Accepted; recorded in `KNOWN_LIMITATIONS.md` |
| Multi-method comparison in one turn costs one `execute_analysis` submission per method, against `execution_submissions = 5` | Fits: three methods plus a repair is 4 |
| No interactive inline scenario card; results render as table + waterfall | Acceptable — section 13.3 asks for exactly those |
| No per-book feature flag in `V4Config` | Worked around: `scenario/flags.py` reads env directly, and both-off reproduces baseline because nothing else references it |
| Tornado chart (section 13.3) unavailable | P9; needs four closed-set edits and the pinning test |
| A scenario run is recorded by `governance.py` only if it emits artifacts and claims | Designed for: `ledger.py` emits driver rows as an artifact |

---

## 6. What was done instead

One protected-core change, of the kind section 1.2 explicitly permits — *"An
existing unprotected registry may receive a minimal additive entry; document its
exact diff."*

`context.py` gains a `scenario_blocks()` module function and one call site. It
is the identical pattern to `policy_blocks()` (`context.py:869`) and
`product_blocks()` (`context.py:620`), both already present and both invoked by
name from `build()` / `finalization_system()`. Its exact diff is in the change
log of `BASELINE_AND_EXTENSION_MAP.md`, and
`scripts/whatif/protected_hashes.py --check` reports it on every run rather than
allowlisting it away.

No other protected file is edited. No core file is monkey-patched. No validator
is weakened. No second orchestrator exists.

---

# 7. The execution boundary, found in P10 with evidence

**This is the one that stops work.** P3 to P9 built the scenario engine:
cohort freezing, rule compilation, previews, confirmation hashes, Delta,
user assumptions, sensitivities, mappings, two emulators, the three-method
run, the ledger, attribution and the charts. Every piece is governed, tested
and reconciled.

**None of it can be reached from a chat turn**, and the reason is the Python
sandbox rather than anything in the candidate.

## 7.1 What was measured

`backend/cockpit_v4/pyrunner.py:150-156` spawns every Python step as:

```python
subprocess.run(
    [sys.executable, "-I", "-S", "-c", _BOOT, json.dumps(limits)],
    env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
         "HOME": tempfile.gettempdir()},
    cwd=tempfile.gettempdir(), ...)
```

Four properties, each deliberate and each correct for its purpose:

* **`-I`** is isolated mode. `PYTHONPATH` is ignored, the script directory
  and the working directory are removed from `sys.path`, and user
  site-packages are ignored.
* **`-S`** skips `site`, so site-packages is not on the path either.
* **`cwd`** is a temporary directory, not the repository.
* **`env`** carries no `PYTHONPATH`.

So analysis code can import **the standard library and nothing else**.
Measured directly against `_spawn`:

| Step code | Result |
|---|---|
| `import json` | **ok** |
| `import pandas` | ModuleNotFoundError |
| `from backend.cockpit_v4.scenario import run` | ModuleNotFoundError |

The static check at `pyrunner.py:84-102` does not forbid the candidate
import — its list is `os`, `sys`, `socket`, `subprocess`, `importlib` and
the rest — so the refusal is not a policy that could be widened. It is the
interpreter having no path to the package. And `importlib`, `sys` and
`pathlib` are all forbidden, so analysis code cannot add one.

`COCKPIT_V4_PYTHON_RUNNER` is also off by default, so a Python step reports
`PYTHON_UNAVAILABLE` before any of this is reached.

## 7.2 What this means

An `execute_analysis` submission can run **SQL against the published
release** and **standard-library Python over the rows SQL returned**. That
is enough to read a published sensitivity, a rating map or a score band — 
which is why P5 and P6 publish their artifacts as relations, and why a
methodology question is an ordinary retrieval.

It is **not** enough to run a scenario. `cohort.freeze`, `rules.compile_rules`,
`preview.build`, `delta.scale_row`, `run.execute`, `ledger.build`,
`attribution.sampled` and `ml.infer.anchor` are Python functions in a package
the sandbox cannot import, and re-implementing them as inline analysis code
would be the ungoverned parallel execution path this whole design forbids.

## 7.3 The change that closed it, as authorised

**Option A, authorised explicitly and made.** One guarded dispatch, so the
existing governed execution path hands a strictly typed What-If operation to the
existing deterministic `scenario/run.py`. An integration adapter, not a new
analytical architecture.

**Option B — a sixth tool — was not built.** P1 established with file:line
evidence that no sixth tool is needed for anything except this, and the branch
below shows it is not needed for this either.

### The three protected files, and what each carries

| File | Δ | What the diff does | Authorised as |
|---|---|---|---|
| `contracts.py` | +84 | `BASE_STEP_LANGUAGES`, `WHATIF_STEP_LANGUAGE`, `_step_languages()`, `_whatif_language()`, and the `parse_steps` condition reading the allowed set rather than a hardcoded pair. | The dispatch's precondition. `parse_steps` refused the language before `execute_tool.py` was reached, and `provider_tools` inlines `shared_defs.schema.json`'s `Step.language` enum into the provider payload. |
| `execute_tool.py` | +143 | `CHECK_SCENARIO` and its `PHASE_OF_CHECK` row, two dispatch arms, `_is_scenario`, `_bridge`, `_domain_id`, `_validate_whatif`, `_run_whatif`, `_scenario_failure`, `_scenario_rejection`. | The authorised dispatch itself. |
| `routes.py` | 1 line | `current = dom_mod.current_release(pinned) if pinned else ""` in place of `DEFAULT_RELEASES.get(pinned or "", "")`. | Stopped and reported before the edit. A thread pinned to a candidate release was compared against the ACCEPTED default, so **every follow-up turn in such a thread returned 409 RELEASE_SUPERSEDED** — reproduced over HTTP. Without it the product has no second turn on a candidate book and no journey past the first question. |

**Both dispatch arms are required and neither is optional.**
`validate_batch`'s `else` swallowed everything non-SQL into `_validate_python`
(→ `PYTHON_UNAVAILABLE`), and `_run_step`'s fallthrough is **SQL**, so an
unhandled scenario step would have been executed as a query.

**The JSON schema files are not edited.** `contracts/shared_defs.schema.json`
and `contracts/execute_analysis.schema.json` are byte-identical to
`245c50e45786c6e0c866b281f9dd74da17d160b5`, asserted by a named test. The extra
enum value is appended to the provider's **in-memory copy** under the flag, so
with the flags off the provider payload is byte-identical and the payload
snapshots do not move.

### What the branch recognises, and what it refuses

`_is_scenario(step)` is `step.language == "whatif_scenario"` **and** the book's
own flag being on — both halves, checked per book, so a Corporate-only
deployment cannot execute a Retail scenario step. Anything else, including a
step that merely names the language while the flag is off, falls through to the
arms that were always there.

`parameters` must match exactly one of two closed shapes,
`preview_scenario` or `execute_scenario`; every unknown key is refused **by
name** rather than ignored, because a misspelled key that is silently dropped is
a rule that silently did not happen. Every field id comes from the candidate
field dictionary, every operator from a closed set of seven, every cohort column
from the catalogue. The confirmation is re-verified from the canonical form
rather than trusted from a stored digest, and the cohort is re-resolved with its
membership hash compared. **No module name, callable, path or Python expression
is accepted from the model or the user.** `code` carries a human-readable
restatement for the trace and is never parsed or executed.

### What was not relaxed

`-I` and `-S` stay. No `PYTHONPATH` is set for model-authored Python, no backend
directory is added to `sys.path`, no arbitrary backend import is possible from a
generated Python step, no generic Python escape hatch exists, no second
executor was created, and the SQL, source and release authorisation are
unchanged. `pyrunner.self_test()` is re-run unchanged by
`test_whatif_bridge.py`, which also asserts directly that
`from backend.cockpit_v4.scenario import run` still fails with
`ModuleNotFoundError` inside a governed Python step.

### The dispatcher condition is mutation-tested

A harness flips `_is_scenario` to always-true, always-false, flag-ignoring and
language-only (flag dropped), and asserts that a **named** test fails in each
case. A condition no test can break is a condition no test is checking.

## 7.4 What the dispatch unblocked, and what remains unrun

**Unblocked and delivered:** J01–J14 on both books through real Chromium
(28 of 28), E20's timeout/cancel/double-Run behaviour under a scenario turn
(J12–J14), R11's save-and-reopen (J06), R13's export reconciliation (J09), and
the three-method comparison over one confirmed contract.

**Still unrun, and not claimed:** a journey driven by a **live provider**. No
credential is authorised in this container, so every journey runs with a
scripted analyst against the real UI, API, store, worker, event stream, DuckDB
session and scenario engine. Those journeys are reported as PASS (MODEL MOCK)
with that limitation named, and the live-provider journey is a separate row
marked BLOCKED — NOT RUN.

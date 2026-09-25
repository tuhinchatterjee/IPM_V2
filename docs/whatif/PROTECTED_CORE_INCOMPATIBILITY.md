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

## 7.3 The exact change that would close it, and the approval needed

**Not authorised by the current brief, and not made.** Either of two shapes
would work and both are protected-core changes:

| Option | Files | Size | What it costs |
|---|---|---|---|
| **A — a scenario branch in the tool executor** | `execute_tool.py` | one branch on a step `kind` of `whatif_scenario`, dispatching to `scenario/run.py` server-side | The step stays inside the existing budget, validator and artifact machinery. `execute_tool.py` is protected and this is a real edit to it. |
| **B — a sixth tool** | `contracts.py`, `execute_tool.py`, `action_state.py`, `prompts/analyst.md` | a registered `run_scenario` tool with its own schema | Larger, and P1 established with file:line evidence that no sixth tool is needed for anything **except** this. The evidence stands: everything else is data or an existing chart kind. |

Option A is the smaller change and the one this implementation would
propose. It needs the same explicit authorisation the three landed
extensions received.

**What is NOT proposed:** relaxing the sandbox. Putting the repository on a
Python step's path would let model-authored code import the whole backend,
which is a far larger change to the security posture than anything this
feature needs, and `pyrunner.self_test()` exists precisely to keep that jail
honest.

## 7.4 What was stopped, and what was not

Stopped: the end-to-end execution wiring, and the browser journeys that
depend on it (J01 to J14, and E20's timeout/cancel/double-Run behaviour
under a scenario turn). They are marked **BLOCKED — NOT RUN** in
`REQUIREMENT_TEST_MATRIX.md`, with this section as the reason. None of them
is reported as passing.

Not stopped, and delivered: everything that does not depend on it. The two
candidate releases, the sensitivity artifacts and their cards, the mappings,
both emulators and their model cards, the run, attribution and results
libraries with their oracles, the requirement matrix, the isolation
evidence, and the candidate launcher. 115 of 136 acceptance IDs are COVERED
by named tests.

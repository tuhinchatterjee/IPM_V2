# Opus repair ownership — the audit

    OPUS writes the query or the code.
    CREDITPROBE validates it.
    CREDITPROBE executes it.
    CREDITPROBE diagnoses the failure.
    OPUS repairs it.

This document records how that is held, and what would break it.

There are two ways to break it, and they need different defences.

The first is **omission**: dispatching a repair request that does not carry the
context the repair needs. Nothing looks wrong — a request goes out, an answer
comes back, and it has the shape of a fix. But it was arrived at by guessing,
and the guess is invisible afterwards.

The second is **helpfulness**: some path in the application that notices what
would have worked and quietly supplies it. A substituted column, a widened
filter, a canned decomposition after a failure. Each of those would improve a
demonstration and destroy the property being demonstrated.

## The first defence: the outbound request is read, not trusted

Section 8.1 says to inspect the serialized API request and prove the model
really receives the context. `context_attached` does not do that — it is
CreditProbe listing its own compliance, and a list is not evidence.

So the assembled request is read immediately before dispatch, by
`Conversation.before_dispatch`, and a missing item **stops the request**. The
sixteen:

| # | What must be in the request | Audit key |
|---|---|---|
| 1 | the question exactly as the user asked it | `original_question` |
| 2 | the faithful business request Sonnet produced | `cleaned_question` |
| 3 | the rolling summary and recent exchanges | `thread_context` |
| 4 | the effective scope and the filters in force | `scope_and_filters` |
| 5 | the complete authorized catalogue, with grains | `field_dictionary_and_grain` |
| 6 | the measured coverage of the release | `coverage_and_missingness` |
| 7 | the approved ownership decision | `functionality_decision` |
| 8 | the plan currently being executed | `analysis_plan` |
| 9 | the exact SQL or Python that failed | `failed_code` |
| 10 | the parameters it was bound with | `bound_parameters` |
| 11 | the validator's or the runtime's own error | `diagnostics` |
| 12 | the intermediate results already obtained | `completed_results` |
| 13 | what has already been tried and failed | `previous_approaches` |
| 14 | how many execution submissions are left | `submissions_remaining` |
| 15 | how many analysis rounds are left | `rounds_remaining` |
| 16 | the remaining calls, time, tokens and spend | `budgets_remaining` |

Each is checked by looking for content that could only be there if the item is
there: the question's own words, fields from opposite ends of the dictionary,
the grain of the relation the failure was in, the failed code itself, the
engine's own error text. **A reference, an id or a hash satisfies none of
them**, which is the point — `test_a_catalogue_reference_would_not_satisfy_that`
also asserts that no `base_context_id`, `schema_hash` or `catalog_ref` appears
in place of the content.

### What happens when it fails

`IncompleteRepairContext` is raised before dispatch and the request stops with
`INFRASTRUCTURE_ERROR` and a narrative that says the defect is this
application's, not the data's and not the question's. It does not send the
request anyway. Asking Opus to repair code it cannot see, and then treating
what comes back as informed, is worse than stopping.

Every dispatch leaves a record in `Outcome.repair_context_audits`: which of the
sixteen were verified, which were missing, and the size of the request that was
inspected.

### The hook can only read

`before_dispatch` is handed the assembled system blocks, messages and tools,
and its return value is discarded. It is the single most convenient place in
this codebase to quietly improve Opus's context, so it is built as an
inspection point and a test reads `opus.py` to confirm it stays one.

### Two escaping bugs this found

The audit reported `diagnostics` missing on a request that carried it. The
failure packet is a JSON string nested inside the request's own JSON, so a
database error containing double quotes arrives twice-escaped and a raw
substring match could not see it. That is the dangerous direction of false
alarm — it would have stopped a repair that had everything it needed — so
matching now normalizes escaping and whitespace on both sides.

## The second defence: the source is read

| What would break the rule | How it is caught |
|---|---|
| A module rewrites the model's code | No assignment back into a step's code, and no `rewrite_sql` / `fix_sql` / `substitute_column` / `generate_replacement` anywhere in the package |
| A module composes a query | No string outside `sql.py` names a Cockpit relation after `FROM` or `JOIN`. `sql.py` composes exactly two metadata queries — the sample rows and the distinct filter values Opus is shown — and nothing else does |
| The failure packet chooses between alternatives | `available_alternatives` reports that these fields exist and are near the name that did not. Which one the question means is not a catalogue fact. A test fails if any string in `failure.py` tells Opus which field to use |
| A canned analysis runs after a failure | Read as CALLS, not as words: no call in `runtime.py` whose name contains fallback, canned, deterministic, template, decompos, attribution, shapley or narrate. A docstring may say what must not happen; the calls are what decide whether it does |
| The sandbox advises on a traceback | No "you should", "try instead", "did you mean" or "consider" in `pysandbox.py` |
| A Python step gets "validated" for meaning | A Python step gets no lint, no AST allowlist and no rewrite. Inspecting the code for intent is the first step towards editing it, and the boundary is the kernel's instead |

## What CreditProbe does do

It refuses a query that names a field that does not exist, and says which
fields do exist, with their meanings and units — including both `pd_pit_12m`
and `pd_ttc_12m` when the name was ambiguous, and saying explicitly not to
substitute one silently. It reports the engine's own error with SQLSTATE and
line where the engine supplies them, and invents no precision it does not have.
It says what has already been tried, what results are already in hand, and what
budget remains. It names the permitted next actions, which are the server's to
decide.

None of that is a repair. All of it is what a repair needs.

## Coverage

`tests/cockpit_agentic/test_repair_ownership.py` — the sixteen asserted against
the real outbound request for a failed SQL step and for a failed Python step,
the audit's own failure modes, and the source-level checks above.
`tests/cockpit_agentic/test_repair_context.py` — the section 8.1 worked example,
block pairing and ordering, and the cached-prefix behaviour.
`tests/cockpit_agentic/test_no_fallback.py` — no import path from the Cockpit to
the deterministic engine or the legacy analyst.

These use the labelled mock provider. They prove what this application puts in
the request and what its source does not contain, which is exactly what a mock
can prove. They say nothing about how a real model uses any of it.

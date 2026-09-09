# Architecture freeze — audit before implementation

Against the branch at `0351555`, before any edit. Section numbers are the
freeze specification's.

Legend: **OK** already compliant · **PART** partially compliant · **GAP**
missing · **CONFLICT** implemented differently

| § | Requirement | Current implementation | Status | Files | Required change |
|---|---|---|---|---|---|
| 1 | Sonnet owns language, cleanup, translation, normalization, summary | `sonnet.clean`, `sonnet.normalize`, `sonnet.update_summary` — nothing else calls the preprocess role | **OK** | `sonnet.py` | none |
| 1 | Opus owns reasoning, plan, SQL, Python, repair, review, interpretation | `opus.gate_and_plan`, `opus.repair`, `opus.review`; `models.REASONING_ROLE` is the only id used | **PART** | `opus.py` | Opus does not yet own *query-mode classification* or *final prose repair*; both added below |
| 1 | CreditProbe never rewrites Opus SQL/Python | Asserted at source level: no assignment back into a step's code, no relation named after FROM/JOIN outside `sql.py`, no advice string in `pysandbox.py` | **OK** | `test_repair_ownership.py` | none |
| 2 | Cockpit reaches only `corporate_cockpit` | DuckDB session materializes the allowlist then disables external access and locks configuration; negative proof over published Parquet columns | **OK** | `sql.py`, `scope.py`, `test_sql_security.py`, `COCKPIT_FIELD_AUDIT.md` | none |
| 3 | New request id and pinned ledger per submission | `Runtime.__init__` pins scope, release, calendar, mode, deadline; `LedgerStore.open` is idempotent per request id | **PART** | `runtime.py`, `scope.py`, `ledger.py` | catalogue version and product-knowledge version are not pinned into the ledger record |
| 3 | Auth failure → security terminal state | `scope.for_principal` raises `PERMISSION_DENIED`; the runtime has no state for it | **GAP** | `scope.py`, `states.py` | add `STOPPED_SECURITY` and route to it |
| 4 | 5 submissions, 3 rounds, never reset; per-mode budgets; earliest wins | `ledger.Limits`, `note_submission`, `note_analysis_round`, `may_continue` | **OK** | `ledger.py` | none |
| 5 | Sonnet pass 1 fields incl. `meaning_change_risk`, no silent specialisation | `CleanedQuestion` carries detected language, preserved terms, uncertain phrases; `SONNET_1_SCHEMA` | **PART** | `contracts.py`, `sonnet.py` | no explicit `meaning_change_risk`; the PD→PIT-PD rule is prose in the prompt but has no test |
| 6 | Sonnet pass 2 business request, no method choice | `NormalizedQuestion`, `SONNET_2_SCHEMA` | **OK** | `sonnet.py` | none |
| 7 | Context builder sections A–J | `context.build` produces A_request…J_budget | **PART** | `context.py` | no product-knowledge section distinct from the functionality registry; no "skip sample rows for theory" rule |
| 8 | QUERY_MODE enum, run every turn, not keyword-only | The gate returns `decision` ∈ {PROCEED_COCKPIT, REDIRECT, CLARIFY_FUNCTIONALITY, UNSUPPORTED} and always runs | **GAP** | `contracts.py`, `opus.py` | add the six-value `QUERY_MODE` and the eight-value `OWNER`, plus `requires_cockpit_data/sql/python`, `decision_reason`, `ambiguity` |
| 9 | Score ≥70, highest, lead ≥10 | Only *uniquely highest* is enforced server-side | **PART** | `contracts.py`, `runtime.py` | add the 70 floor and the 10-point lead as server-side predicates |
| 10 | PRODUCT_HELP: zero SQL/Python, zero counters, grounded in the registry | No such path — every non-referral goes to PLANNING | **GAP** | `opus.py`, `runtime.py` | new zero-execution answer path |
| 11 | THEORY_CONCEPT: zero SQL/Python, generic theory allowed, product specifics only from the registry | No such path | **GAP** | `opus.py`, `runtime.py` | new zero-execution answer path |
| 12 | External/current information closed explicitly | Not modelled; would fall to the gate's UNSUPPORTED by luck | **GAP** | `registry.py`, `opus.py` | explicit mode and a closed path |
| 13 | Mixed theory + data is DATA_ANALYSIS | Would work today, untested | **PART** | — | add tests |
| 14 | OTHER_FUNCTIONALITY: no execution, real destination only when configured | `_not_ours` → REDIRECTED, zero execution, route verified against the frontend registry | **OK** | `runtime.py`, `registry.py` | none |
| 15 | Clarification closes the request, new id on reply | `CLARIFICATION_REQUIRED` is terminal | **PART** | `states.py` | rename to the specification's `WAITING_FOR_USER` |
| 16 | UNSUPPORTED explains the boundary | `_not_ours` handles it | **OK** | `runtime.py` | none |
| 17 | Only DATA_ANALYSIS+COCKPIT executes; no compulsory template | `may_execute` is the single predicate; no template anywhere | **OK** | `runtime.py`, `test_no_fallback.py` | tighten `may_execute` to require the mode too |
| 18 | Validator outcome vocabulary | §8.2 taxonomy implemented, incl. `SANDBOX_UNAVAILABLE` | **PART** | `contracts.py` | no `JOIN_MULTIPLICITY_RISK`, no `NO_PROGRESS_DUPLICATE` as categories |
| 19 | Join/grain multiplication safety | Grains and join multiplicities are in the catalogue and the packet; the validator does not check a submitted join | **GAP** | `sql.py`, `failure.py` | add the `JOIN_MULTIPLICITY_RISK` diagnostic |
| 20 | A submission is consumed on submit, even when rejected | `note_submission` is called before validation | **OK** | `runtime.py`, `ledger.py` | none |
| 21 | Failure packet contents | Sixteen items verified on the actual outbound request before dispatch | **OK** | `failure.py`, `opus.py`, `test_repair_ownership.py` | none |
| 22 | No-progress duplicate hash | `note_submission(fingerprint)` raises `STOP_NO_PROGRESS`; fingerprint covers code and parameters | **PART** | `contracts.py` | the hash does not include the data release |
| 23 | Five submissions, then explain | `_submissions_exhausted` | **OK** | `runtime.py` | map to `STOPPED_EXECUTION_LIMIT` |
| 24 | Execution: read-only SQL, isolated Python, forbidden → security stop | DuckDB locked; sandbox with namespaces, no shell, no network, bounded | **PART** | `runtime.py` | forbidden behaviour does not reach a `STOPPED_SECURITY` state |
| 25 | Result packet fields | `ExecutionResultPacket` + `StepResult` carry code, params, release, rows, columns, warnings, elapsed, artifact id, budget | **OK** | `contracts.py` | none |
| 26 | Sufficiency review outcomes | `REVIEW_DECISIONS` covers all six | **OK** | `contracts.py`, `opus.py` | none |
| 27 | Three rounds, syntax fixes do not count | `note_analysis_round` only on `REVISE_ANALYSIS` | **OK** | `runtime.py` | none |
| 28 | Final answer structure | `AnswerEnvelope` carries narrative, tables, charts, limitations, assumptions, fact_ids | **PART** | `contracts.py` | no `findings[]`, no `suggested_questions[]` |
| 29 | Final-answer evidence validation, one Opus rewrite | `_bind_figures` drops unknown references and adds a limitation. No numeric-claim check, and **no rewrite** | **GAP** | `runtime.py` | build the validator and the single rewrite |
| 30 | Chart validation, drop on failure | Charts capped at the mode limit; values not checked against evidence | **GAP** | `runtime.py` | validate and drop |
| 31 | Suggested question validation, drop on failure | No suggested questions at all | **GAP** | `contracts.py`, `runtime.py` | add and validate |
| 32 | Summary after the answer, failure cannot erase it | `service.ask` updates after the outcome exists, inside try/except | **OK** | `service.py` | none |
| 33 | Re-evaluate mode every turn | The gate runs every turn; there is no mode to inherit yet | **PART** | `runtime.py` | add a test once modes exist |
| 34 | Cancellation stops work, keeps usage | `ledger.cancel`, sandbox `cancel` callback, `CANCELLED` terminal | **OK** | `ledger.py`, `pysandbox.py` | none |
| 35 | Strict model roles | `models.resolve`, `require`, `ensure_available` | **OK** | `models.py` | none |
| 36 | Data is data, never instruction | `UNTRUSTED_NOTE` in the packet and after the cache breakpoint | **PART** | tests | no adversarial test |
| 37 | Cache/thread identity includes tenant, scope, release, catalogue | Thread key is `thread_id` alone | **GAP** | `service.py`, `thread.py` | key on tenant + release + catalogue version |
| 38 | Pinned release; unavailable → `DATA_UNAVAILABLE` | `ReleaseNotFound` → `NotAvailable`, an HTTP error rather than a request state | **PART** | `states.py`, `service.py` | add the terminal state |
| 39 | Macro vintage preserved | `forecast_vintage`, `observation_status`, gates `check_macro_vintages` and `check_no_future_actuals` | **OK** | `validate_data.py`, `fields.py` | none |
| 40 | Prior result reuse must match scope | Exchanges carry fact ids; compatibility is not checked | **GAP** | `thread.py` | add the compatibility check |
| 41 | `INTERNAL_ERROR`, safe diagnostics, no fallback | Generic `except` → `PROVIDER_ERROR` with a safe message | **PART** | `states.py`, `runtime.py` | add the distinct state |
| 42 | The seventeen terminal states | Fourteen exist; named differently in four cases | **PART** | `states.py` | add and rename |
| 43 | Explicit transition registry with event/condition/side-effect, graph tests | `TRANSITIONS` is adjacency only; `test_states.py` checks legality | **PART** | `states.py`, tests | add the full registry and the twenty proofs |

## Summary

**Already compliant, not to be rebuilt:** the domain boundary and its
enforcement, the field catalogue and grains, the five-submission and
three-round counters, the failure packet and its sixteen verified context
items, Opus's exclusive authorship of SQL and Python, the Python sandbox, the
strict model roles, macro vintages, the referral path, cancellation, and the
summary-after-answer ordering.

**Twelve gaps and nine partials to close**, concentrated in three areas:

1. **Classification** — there is no query mode. Everything that is not a
   referral is treated as an analysis, so a question about what the Cockpit
   *is* would consume an execution submission to answer.
2. **The final answer** — evidence validation is structural only, there is no
   rewrite, and charts and suggestions are unvalidated.
3. **The state machine** — the terminal set is incomplete and the transition
   table records adjacency without the event, condition or side effect that
   justifies each edge.

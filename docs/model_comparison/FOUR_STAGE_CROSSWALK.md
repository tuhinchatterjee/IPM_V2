# Four-stage crosswalk: reporting groups over the actual calls

S1 to S4 are **reporting groups** applied after a run. They are not four API calls. The frozen engine makes N generations of **one** analyst model; the lab classifies each generation after the fact from persisted evidence. One generation can belong to more than one stage. When it does, it is shown once, as a shared span such as `S1+S2`, and its time and tokens are never divided between the stages.

## Evidence the classifier reads (all persisted by the frozen engine)

| Source | Where | What it gives |
|---|---|---|
| Conversation | `messages` table (`RunStore.load_messages`) | Each assistant `tool_use` (exact arguments, SQL/Python bytes) and each `tool_result`, including the `is_error` flag and its safe feedback text |
| Call report | `details` (`Orchestrator._build_call_report`) | For each attempt: `purpose` (`ANALYSIS_ACTION`, `ACTION_FORMAT_RECOVERY`, `FINAL_ANSWER`, `ANSWER_FORMAT_RECOVERY`, `ANSWER_CORRECTION`), `phase` (action/answer), provider_ms, tokens, stop_reason, tool names and `usable` |
| Events | `events` table | `model.*`, `tool.requested/validated/started/completed/failed`, `retry.requested`, `answer.validated/ready`, `run.*` |
| Submissions | `submissions` table | Submitted code and the no-progress key |
| Final answer | `runs.final_response` | Disposition, narrative, numeric claims with artifact evidence, tables, charts, limitations |
| Lab sidecar | `ObservingProvider` spans | Monotonic start/end for each `converse`, raw usage and stop reason (passive) |

## Classification rule for each generation

The rules apply in order, and every label that applies is kept.

| Condition on the generation | Stage tag(s) | Handover label |
|---|---|---|
| It produced `inspect_catalog` or `inspect_product_knowledge` | **S1** | C01–C03 (grounding) |
| It produced `finalize_response` with `disposition=clarification`, `referral` or `unsupported` | **S1** | C03 (clarify or scope) |
| It produced the **first** `execute_analysis` of the run, with no earlier S1-only generation | **S1+S2 shared span** | C01–C06 |
| It produced `execute_analysis` after an earlier S1 generation, where the previous tool result was not an error | **S2** | C04–C06 |
| The previous tool result was an **error** (validation refusal, execution failure, parse rejection), or purpose is `ACTION_FORMAT_RECOVERY` / `ANSWER_FORMAT_RECOVERY` | **S3**, plus the stage of what it produced (`S3+S2` for a resubmission, `S3+S4` for a re-answer) | C09–C10 |
| It produced `read_artifact`, or an `execute_analysis` continuation after a **successful** result | **S3** (review/continue), plus S2 for new code | C09–C10 |
| Purpose `ANSWER_CORRECTION` (the Finalizer refused the answer) | **S3+S4** | C10–C11 |
| Purpose `FINAL_ANSWER` producing `finalize_response` (answer or partial_answer) | **S4** | C11 |
| It produced no usable tool call (`usable=false`) | Stage of its `purpose`, flagged `PROTOCOL` | — |

## CreditProbe lane (never a model stage)

The following spans go in the **"CreditProbe execution and validation"** lane:
- context build and allowance (C00);
- `tool.validated`, `tool.started` → `tool.completed` / `tool.failed`, i.e. SQL/Python validation and DuckDB/pyjail execution (C07–C08);
- Finalizer validation and rendering;
- store writes and `answer.ready` (C12 storage).

A slow DuckDB step is recorded here. It is never recorded as "slow LLM".

## Stage status values

`PASS`, `FAIL`, `PARTIAL`, `NOT_OBSERVED`, `NOT_REACHED`, `UNKNOWN`, `NOT_SEPARATELY_OBSERVABLE`

| Situation | Status |
|---|---|
| S3 when the run had no error to recover from | `NOT_OBSERVED` (no repair opportunity). Neither 0% nor 100%. |
| S4 when the run failed before any answer | `NOT_REACHED` |
| S1 folded into the first execute call | Evaluated jointly on the `S1+S2` span. S1 alone is `NOT_SEPARATELY_OBSERVABLE`. |
| No oracle or rubric covers the stage | `UNKNOWN` / `NEEDS_REVIEW` |

## What is observable and what is not

- **S1 is only partly observable.** The model's scope decisions show only through the arguments it submits: `execute_analysis.scope.reporting_periods`, `filters`, `borrower_ids`, `subquestions`, `expected_output_grain`, `expected_units`, and the SQL WHERE clauses. They also show through catalog inspection calls. No separate English plan exists. S1 conclusions drawn from SQL are labelled "inferred from submitted code".
- **Hidden reasoning** is neither requested nor available (no thinking blocks). None is shown.
- **Follow-ups** start a new run on the same thread: a new four-stage turn whose `parent` lineage is the previous run in that thread.

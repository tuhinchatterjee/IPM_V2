# Actual call map: frozen AdvancedCockpit (Cockpit V4) at 245c50e

This map was read from the code; nothing in it is assumed. Line numbers refer to the frozen commit.
The exact tool schemas, as sent to the provider, are in `TOOL_CONTRACTS.json`. They were
exported by calling the frozen `contracts.provider_tools` the same way the worker calls it.

## 1. Headline facts

| Question | Answer from code |
|---|---|
| How many LLMs per investigation? | **One analyst model.** Envelope, intent, domain resolution, memory summary and answer checking are all deterministic. There is no Sonnet or Haiku helper, no answer-rewrite call and no critic. `backend.llm` is imported only at `service.py:109`. |
| Model identity | `AI_COCKPIT_REASONING_MODEL` has no default (`config.py:37`), and the model id must match a verified price card. The only verified card in the tree is `config/cockpit_v4/price_card.claude-opus-5.json` → **`claude-opus-5`**. `scripts/cockpit_v4/live_uat.py:57` pins `APPROVED_MODEL = "claude-opus-5"`. The adapter's own `DEFAULT_MODEL = "claude-sonnet-4-5-20250929"` (`backend/llm/anthropic_provider.py:31`) is never used, because V4 always passes `model=capability.model_id`. |
| Provider / SDK | Official `anthropic` Python SDK 0.112.0 (`requirements.txt`), called through `AnthropicProvider.converse` (`anthropic_provider.py:201`) with `client.messages.with_options(timeout).create(...)`. **Non-streaming.** The run's retries are off (`allow_retry=False`). Endpoint: Anthropic Messages API, default base URL. |
| Credential | Only `COCKPIT_ANTHROPIC_API_KEY` (`config.py:32`). It never falls back to `ANTHROPIC_API_KEY`. |
| What the model writes | **Raw DuckDB SQL and/or Python steps** inside `execute_analysis` (1 to 8 steps). There is no structured plan IR. Code runs as written; the server never rewrites or repairs it. |
| Prompt caching | Never requested; `cache_control` does not appear anywhere in `cockpit_v4`. Cache counters are therefore always 0. |
| Reasoning / thinking | No thinking blocks are requested. `output_config={"effort": ...}` is sent when the model supports effort control (`provider.py:486-488`). |

## 2. Entry points

| Path | Code | LLM? |
|---|---|---|
| Ask a question | `POST /api/v1/cockpit-v4/runs` → `routes.start_run` (`routes.py:162`). Readiness is checked, then the thread's domain/release pin, the domain, `envelope.for_request` (deterministic), `store.accept_run` and `RUN_ACCEPTED`. The route returns 202. | Queued |
| Follow-up | The same `POST /runs` with `thread_id`. `context.build` adds up to 3 recent turns (8 max) plus an older-history summary. | Queued |
| Answer a clarification | The same `POST /runs` on the thread. `context.build` (`context.py:229-287`) turns the earlier clarification into `you_asked` / `the_question_still_standing`. | Queued |
| Reopen a saved analysis, investigation, thread or trace | `GET /threads/{id}`, `/saved-analyses*`, `/investigations*`, `/runs/{id}/trace` (`routes.py:2014`) | **No.** Read-only; `accept_run` is called only by `start_run`. |
| Investigate an attention item | `POST /attention/{item_id}/investigate` seeds thread context | No (the first question then goes through `/runs`) |
| Cancel | `POST /runs/{id}/cancel` (`routes.py:449`) sets `cancel_requested`, which is checked by `Orchestrator._guard` | No |
| Events | `GET /runs/{id}/events` (`routes.py:2053`): SSE from the `events` table with a cursor | No |

Execution chain:

```
Worker.serve_forever (worker.py:111) → store.claim_next
  → Worker.execute (worker.py:131): envelope.for_request → Ledger → _Heartbeat
      → Worker._drive (worker.py:184)
          book = _book_for(record)             # domain release, read-only DuckDB
          packet = context.build(...)          # system blocks + first user message
          Analyst(provider=runtime.provider, capability=runtime.capability, ...)   # ← PROVIDER SEAM
          Orchestrator(...).run_to_completion()  (orchestration.py:240)
              _loop (524): _guard → _demand_an_answer_if_time_is_short (560)
                          → _generate (677) → Analyst.ask (provider.py:367)
                          → _handle_turn (998) → _handle_call (1082)
                               inspect_catalog → _do_catalog (1130)
                               inspect_product_knowledge → _do_product_knowledge (1192)
                               read_artifact → _do_artifact (1260)
                               execute_analysis → _do_execute (1279)
                               finalize_response → _do_finalize (1612)
      → Worker._settle (worker.py:370): turn, terminal state, ANSWER_READY
Supervisor.sweep (supervisor.py:85): expiry and stale leases; publishes stored rows; no LLM
```

## 3. Input assembly (`context.build`, `context.py:143`)

**System: three text blocks.**
1. `prompts/analyst.md`, about 15.8 KB, with period tokens filled in (`context.analyst_instruction`).
2. JSON: product synopsis and registry (omitted on analytical runs), `catalog_index` (an index only, not the field dictionary), `cockpit_semantics` and `governed_values`.
3. JSON: `pinned_scope`, `budgets`, `value_resolution` and `analysis_readiness`.

**First user message** (`context.py:376-444`), in order:
- `USER REQUEST (original wording, unmodified):` followed by the question;
- the investigation seed or case file, when present;
- recent turns;
- the history summary;
- a closing instruction.

**Changes on later turns:**
- The answer turn swaps the heavy block for `finalization_system` (`context.py:701`), which carries the ANALYTICAL_ANSWER, PRESENTATION and policy blocks.
- Product-help turns add `product_blocks` (`context.py:620`).
- The original system blocks are restored after each call (`orchestration.py:726-797`).

## 4. Output and control

- **Tool gating** (`action_state.decide`, `action_state.py:142`):

  | State | Tools offered | Forced tool |
  |---|---|---|
  | `NEEDS_METADATA` | inspect | inspect |
  | `READY_FOR_EXECUTION` | execute | execute |
  | `RESULT_READY` | finalize (+ read_artifact) | finalize |
  | `NEEDS_CLARIFICATION` | finalize | finalize |
  | `PRODUCT_HELP` | product, execute, finalize | none |

  A recovery turn calls `narrow()` (`action_state.py:125`), which never widens the tool set.
- **`tool_choice`** (`provider.py:471-485`): `{"type":"tool","name":X}` when a tool is required and named forcing is supported. Otherwise it is `{"type":"any"}` on action turns and absent on the answer turn. `disable_parallel_tool_use=True` is set. If the provider returns a 400 naming `tool_choice`, `output_config` or `effort`, those parameters are dropped once and stay off for the rest of the run (`_converse`, `provider.py:318`).
- **Stop reasons** (`provider.py:41-44`):

  | Stop reason | Result |
  |---|---|
  | `tool_use`, `end_turn`, `stop_sequence` | Complete turn |
  | `max_tokens` | `OutputTruncated`; the turn is rolled out of history |
  | `refusal` | `PROVIDER_UNAVAILABLE` |
  | Anything else | `INVALID_MODEL_OUTPUT` |

- **Validation of `execute_analysis`:**
  - `contracts.parse_execution` rejects malformed calls with `Rejection(code, message, field_path)`.
  - `ExecutionService.validate_batch` (`execute_tool.py:358`) checks SQL structure (`sql.check_structure`), authorization (`sql.authorize`), join-grain multiplication risk (`sql.multiplication_risk`), EXPLAIN bindability (`sqlbind.prove_bindable`) and the Python jail (`pyrunner`).
  - Then `no_progress_check` runs, and `run_batch` (`execute_tool.py:553`) executes.
  - A refusal or failure returns to the model as an `is_error` tool result telling it to write the fix itself.
- **Validation of `finalize_response`:** `contracts.parse_final` (`contracts.py:1008`) → `Finalizer.validate` (`finalization.py:379`). Numeric claims must equal their stored artifact cells, derived claims are recomputed, bare numbers in the narrative are refused, and wording, charts and tables are checked. On failure the run spends one `ANSWER_CORRECTION` (answer-only turn). When that is exhausted, the stored rows are published without narrative (`_result_only_response`).
- **Clarification:** `disposition=clarification` → `WAITING_FOR_USER`.
- **Answer contract:** `final_response` on the run row holds disposition, narrative, rendered claims, tables, charts and limitations. It is rendered by the frontend `ResponsePanel` and `Visuals`.

## 5. Budgets and who enforces them

These are `config.Limits` values, chosen per request by `envelope.for_request`. Each is enforced by `budgets.Ledger` unless the table says otherwise.

| Limit | Standard | Deep | Enforcer |
|---|---|---|---|
| Run deadline | 60 s | 120 s | Ledger + Supervisor (`deadline_at`) |
| Analytical deadline / spend | 180 s / $1.50 | 240 s / $3.00 | Ledger (widen-only `adopt`) |
| Spend ceiling (non-analytical) | $1.00 | $2.00 | `Ledger.reserve`: worst-case reservation per call, settled on actual usage |
| Generations | 12 | 16 | `spend_generation` |
| Provider HTTP attempts | 24 | 32 | `spend_provider_attempt`. `count_tokens` also counts. |
| Submissions / rounds | 5 / 3 | 5 / 3 | `spend_submission`, `open_round` |
| Catalog calls / product calls | 4 / 4 | 6 / 4 | Orchestrator constants |
| Action output tokens | 3,072 (4,096 after truncation) | 4,096 (6,144) | `Analyst.ask` reservation |
| Answer output tokens | 8,192 (12,288) | 12,288 (16,384) | same |
| Per-call timeout | action 30 s, answer 55 s | 45 s / 90 s | SDK timeout + `check_call_window` |
| Format re-asks, answer corrections | 2 / 2, 1 | same | Ledger |
| Transport retry | 1 per run | 1 | `spend_transport_retry` |

Cost comes from the price card (`capability.load_price_card`, `capability.py:123`). It fails closed with `CAPABILITY_UNVERIFIED` if the card is a placeholder or has no `verified_at`.

## 6. Provider dependencies

| Dependency | Status in the frozen engine |
|---|---|
| Message format | Anthropic Messages throughout: system blocks, `tool_use`/`tool_result` content blocks, `input_schema`. |
| Signed or opaque reasoning state | Not used; no thinking blocks. |
| Hosted tools, citations, response-format enforcement | Not used. Schema enforcement is server-side, in `contracts` and `finalization`. |
| Token counting API | `messages.count_tokens` (`anthropic_provider.py:173`), probed with `getattr`. The local estimate is used when `supports_token_counting=False`. |
| Streaming | Not used. |
| Cancellation | Cooperative, between calls (`_guard`). An in-flight HTTP call runs until its own timeout. |
| Error classification | Matches Anthropic error wording (`_classify`, `provider.py`) unless the adapter raises a typed `ProviderFailure`. |

## 7. The integration seam (for P3 and P4)

`Worker._drive` reads `self.runtime.provider` and `self.runtime.capability` **for each run** (`worker.py:143, 266-267`). The frozen `live_uat.py` (`build_runtime` / `run_turn`, lines 1127-1175) and the test fixture `drive` (`tests/cockpit_v4/conftest.py:247`) already do the following: build a `Runtime(cfg, capability, provider=<X>, ...)`, call `store.accept_run(...)`, then call `Worker(store, runtime).execute(record)`.

**The lab binds each child the same way, with no core edit.** Each child gets its own `Runtime` with its own provider (for a candidate, an adapter wrapped by the passive `ObservingProvider`) and a `Capability` pinned to that child's profile. The child then runs through the frozen Worker, Orchestrator, validators, executor, Finalizer and store.

A per-child provider can also be bound inside a running app, through its duck-typed interface:
`converse(*, system, messages, tools, max_tokens, model, purpose, role, timeout, allow_retry, [tool_choice], [output_config])`, with `count_tokens` optional.
Result attributes: `assistant_blocks`, `text`, `tool_calls` (a list of `{id, name, input}`), `stop_reason`, `model`, `request_id`, `input_tokens`, `output_tokens`, `cache_read_tokens` and `cache_write_tokens`.

## 8. Nested and helper LLM calls

None. The call sites are `Analyst.ask` for generation, and `Analyst.count_input` and `capability.verify_live` for token counting. Memory (`memory.py`) is off in the launcher (`COCKPIT_V4_MEMORY_ENABLED=false`) and summarises without a model call.

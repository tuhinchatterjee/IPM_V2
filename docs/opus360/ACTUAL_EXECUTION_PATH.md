# ACTUAL EXECUTION PATH — frozen AdvancedCockpit (Cockpit V4)

Frozen tag `cockpit-round-h-live-pass-2026-09-23` → commit `245c50e45786c6e0c866b281f9dd74da17d160b5`.
All line numbers below refer to that commit. Produced by reading the source; nothing in the
protected core was modified. Static findings marked **[verified]** were re-checked by hand in
the certification session (see `docs/opus360/STATIC_FINDINGS.md`).

## 0. How the Opus360 harness enters this path

The harness does **not** reproduce any of the path below. It boots the production process
factory in-process and drives it over HTTP:

| Step | Harness action | Frozen code executed |
|---|---|---|
| boot | `backend.cockpit_v4.app.create_app(cfg, provider=<ObservingProvider(real AnthropicProvider)>, verify_model=True, start_workers=True)` | app.py:113-190 — `build_runtime`, `routes.install`, real `Worker.serve_forever` and `Supervisor.serve_forever` daemon threads |
| config | environment set exactly as `scripts/cockpit_v4/start.py:main` sets it for the API child (COCKPIT_AGENTIC_V4, COCKPIT_V4_RUNTIME_DIR, COCKPIT_V4_STATE_DATABASE, COCKPIT_V4_PRICE_CARD, AI_COCKPIT_REASONING_MODEL, COCKPIT_V4_LOCAL_DEMO_AUTH, COCKPIT_V4_MEMORY_ENABLED=false) with an isolated runtime directory per experiment | config.py:363-415 |
| credential | `scripts/cockpit_v4/start.py:obtain_credential(allow_prompt=...)` — environment, then macOS Keychain `creditprobe-cockpit-v4`, then hidden prompt. Imported read-only; value never printed or persisted | start.py:60-94 |
| new question | `POST /api/v1/cockpit-v4/runs` with `{question, domain, mode:"standard"}` via `fastapi.testclient.TestClient` (client host `testclient` is accepted by `_demo_resolver`) | routes.py:162-401 (§1) |
| follow-up / clarification reply | `POST /runs` with the same `thread_id` (exactly what `client.ts:565-578` does) | §1, §3 |
| wait | poll `GET /runs/{run_id}` until `terminal` | routes.py:435 |
| evidence | read-only: `RunStore.get_run`, `events_since`, `details_for_run`, `submissions_for_run`, `artifact_ids_for_run`/`get_artifact`, `load_messages`, `thread_turns`, and `SELECT … FROM reservations` | §12 |

The only additional instrumentation is **pass-through observation**, all outside the protected
tree (`scripts/opus360/cert/observe.py`):

1. `ObservingProvider` wraps the real `AnthropicProvider` object handed to `create_app`. It
   forwards `converse` / `count_tokens` with identical arguments and returns the identical
   result object; it records timings, the request payload (for token decomposition) and the
   returned native usage.
2. A pass-through wrapper on `anthropic.resources.messages.Messages.create` records the raw
   SDK `Message` (`model` actually served, `usage`, `stop_reason`, `id`) and returns it
   unchanged — the only way to learn the served model, because the adapter discards it
   (Finding 2).
3. A pass-through wrapper on `httpx.Client.send`, filtered to the Anthropic API host, records
   every HTTP attempt (status, elapsed, `retry-after`, request id) — the only way to see the
   SDK's internal retries (Finding 3) and rate-limit events.

`tests/opus360/test_observe.py` proves all three return exactly what they were given.

---


## Findings a test harness needs first

1. **Token counts in operator records are redacted.** `RunStore.put_detail` runs `redact()` on every body before writing it (run_store.py:888). `redact()` replaces the value of any key whose name contains `"token"` (`_SECRET_HINTS`, run_store.py:1610-1611). I confirmed this by calling `redact()` directly. As a result these keys are stored as the string `"[redacted]"` in the `details` table:
   - `counted_input_tokens`, `reported_input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens` (on `model.response_received`),
   - `max_output_tokens` (on `model.requested`),
   - every `*_tokens` key inside the stored `call_report`.
   
   Unredacted per-call usage is persisted in only one place: `reservations.usage` (see Observation seams).
2. **The "model" recorded per call is the model that was requested, not the one that served.** `AnthropicProvider.converse` returns `model=chosen` (backend/llm/anthropic_provider.py:298), where `chosen` is the configured id. The response's own `message.model` is never read.
3. **The SDK's own retries are not switched off, although the code says they are.** The client is built as `anthropic.Anthropic(api_key=..., timeout=...)` with no `max_retries` (anthropic_provider.py:327-328), and `with_options(timeout=...)` (line 262) does not set it either. `grep max_retries backend/` finds nothing.
   - **[verified]** The anthropic SDK pinned at 0.112.0 has `anthropic._constants.DEFAULT_MAX_RETRIES == 2`, checked in the certification venv. Each paid `converse` can therefore be up to 3 HTTP attempts, none of them visible to the ledger.
   - `allow_retry=False` only disables the adapter's own loop (anthropic_provider.py:244).
   - Details of what this means for retries are in §7.
4. **Each generation charges 3 or more "provider attempts" against the limit of 24.** One is spent in `ask` (provider.py:497), one in `_converse.send` (provider.py:332), and one in `count_input` when the provider's token counter is used (provider.py:232). A second `count_input` happens when the output allowance is reduced to fit the budget (provider.py:453). So about 8 generations exhaust 24 attempts, before the generation limit of 12 is reached.
5. **Assistant turns in the `messages` table are stored as text, not as JSON objects.** `save_messages` writes content with `json.dumps(..., default=str)` (run_store.py:918). Assistant `content` is a list of raw SDK block objects (provider.py:542, 594), which are not JSON-serialisable, so they are stored as their `repr` strings. Tool results are stored as normal dicts whose `content` field is itself a JSON string.
6. **Prompt caching is not used.** No `cache_control` appears anywhere in the package, so the cache token counts should be 0.
7. **Minor bug: an invalid disposition in the answer-reserve prompt.** The prompt tells the model to use a `cannot_answer` disposition (orchestration.py:618). `DISPOSITIONS` does not include it (contracts.py:56-58), so `parse_final` rejects it (contracts.py:1019-1024).

---

## 1. HTTP run creation: `POST /api/v1/cockpit-v4/runs`

**Route:** `start_run` (routes.py:162-401). The request body is `StartRun` (routes.py:109-118): `question` (up to 8000 characters), `thread_id`, `mode`, `release_id`, `domain`, `ui_filters`. The optional `Idempotency-Key` header is read at routes.py:164. The caller's identity comes from `principal()` (routes.py:95-106), which calls a resolver installed by `app.create_app` (app.py:161-165). With local demo auth that is `_demo_resolver`, loopback only (app.py:83-95).

What the route does, in order:

1. **Readiness gates.** `readiness()` then `.require(PRODUCT_HELP_READY / SQL_ANALYSIS_READY)` (routes.py:169-187).
2. **Mode.** `mode` is lower-cased and falls back to `STANDARD` if unknown (routes.py:191).
3. **Existing thread checks** (only when `thread_id` is given):
   - Tenant check via `store.thread_owner` (routes.py:199-203).
   - Pinned book via `store.thread_domain` (routes.py:204).
   - Returns 409 `RELEASE_SUPERSEDED` if the thread's pinned release differs from `domains.DEFAULT_RELEASES` (routes.py:219-232).
4. **Domain and release scope:**
   - `domain_resolver.resolve(thread_domain=pinned, requested=body.domain, tenant_id=...)` (routes.py:239-240), defined at domain_resolver.py:157-167.
   - A thread-pinned domain wins. A different requested domain raises `DomainPinned` and the route returns 409 (routes.py:241-250).
   - `scope_for` (domain_resolver.py:123-154) builds the catalogue and returns a `DomainScope` with `domain_id`, `release_id`, `release_fingerprint`, currency, periods and relations.
   - A `body.release_id` that differs from the scope's returns 409 `RELEASE_NOT_SETTABLE` (routes.py:268-277).
   - `resolver.analysis_supported(...)` returning false gives 503 `DATA_UNAVAILABLE` (routes.py:280-290).
5. **Thread creation** when there is no `thread_id`: `store.create_thread(...)` (routes.py:292-296). Then `store.title_thread_from_question` (routes.py:303).
6. **Allowance (envelope).** `envelope.for_request(store=..., thread_id=..., question=..., mode=...)` (routes.py:310-312), defined at envelope.py:288-308.
   - It calls `classify()` (envelope.py:179-244) with two inputs: whether the thread is seeded (`store.thread_context`), and the last 3 turns (`store.recent_turns(thread_id, 3)`).
   - The result is a `Verdict` whose `.family` selects the limits: `product_help.standard` uses `STANDARD_LIMITS`, `data_analysis.standard` uses `ANALYTICAL_STANDARD_LIMITS` (envelope.py:69-76).
7. **Idempotency.** `store.run_for_key` (routes.py:317-326). The body digest is `_digest` (routes.py:121-127). A matching key returns the existing run with `duplicate: true`; a key reused with a different body returns 409.
8. **Concurrency.** `store.active_runs_for(thread_id)` must be 0 (else 409 `RUN_IN_PROGRESS`), and `active_runs_for(principal_id)` must be under 2 (else 429) (routes.py:328-335).
9. **Deadline.** `deadline_at = _deadline(limits.deadline_seconds)`, i.e. UTC now plus seconds, ISO format (routes.py:337, 420-424). That is 60 s for product help and 180 s for analysis at Standard.
10. **Question normalisation.** `intake.normalize_question` (routes.py:341; intake.py:81) makes mechanical fixes only: Unicode NFC, zero-width characters, whitespace.
11. **`store.accept_run(...)`** (routes.py:343-371; run_store.py:603-654). In one `BEGIN IMMEDIATE` transaction it:
    - re-checks idempotency;
    - inserts into `runs` with `run_id=run-<hex>`, `state='ACCEPTED'`, `version=0`, `question`, `mode`, `release_id`, `domain_id`, `release_fingerprint`, `ui_filters`, `startup_sha`, `created_at`, `updated_at`, `deadline_at`;
    - inserts into `outbox(run_id, claimed=0, created_at)`;
    - inserts into `idempotency(principal_id, key, body_digest, run_id, created_at)` if a key was given.
12. **Acceptance events.** A new `Emitter` appends `run.accepted` (operation `intake`). If normalisation changed the text, a second `run.accepted` (operation `normalize`) is added with a `detail_ref` containing `{normalization, original}` (routes.py:382-399).
13. **Response.** `_accepted()` returns 202 with `run_id`, `thread_id`, `state`, `mode`, `domain_id`, `release_id`, `duplicate`, `status_url`, `events_url`, `cancel_url` (routes.py:404-417).

**How a run gets picked up.** `app.create_app` starts two daemon threads: `Worker.serve_forever` and `Supervisor.serve_forever` (app.py:176-186).
- `serve_forever` polls `store.claim_next(worker_id)` every 0.05 s (worker.py:111-124).
- `claim_next` (run_store.py:745-760) takes the oldest outbox row with `claimed=0`, sets `claimed=1`, and does `INSERT OR REPLACE` into `leases(run_id, worker_id, fence=prev+1, heartbeat_at, claimed_at)`.

## 2. Threads and how history reaches a new run

- **`POST /threads`**: `create_thread` (routes.py:136-159) calls `domain_resolver.scope_for(domains.parse(body.domain))` and then `store.create_thread`.
- **`RunStore.create_thread`** (run_store.py:502-521) inserts into `threads(thread_id='th-<hex>', tenant_id, principal_id, domain_id, release_id, release_fingerprint, created_at)`. `title` defaults to `''`; the `domain_id`, `release_id` and `release_fingerprint` columns were added by migration (`_ADDED_COLUMNS`, run_store.py:461-475).
- **Turns are written at settlement.** `Worker._settle` calls `store.append_turn(thread_id, run_id, question, answer=outcome.response)` (worker.py:392-396; run_store.py:1134-1161). It inserts `turns(turn_id='turn-<hex>', thread_id, run_id, ordinal=max+1, question, answer JSON, created_at)` and is idempotent per `run_id`. It is written before the run is marked terminal, and only when `outcome.response` is not None.
- **History is attached to the next run in `Worker._drive`:**
  - `store.thread_context(thread_id, tenant_id)` gives the seeded investigation, if any (worker.py:209-210).
  - `context_mod.build(... recent_turns=store.recent_turns(thread_id, DEFAULT_RECENT_TURNS=3), summary=store.get_summary(thread_id), investigation=...)` (worker.py:211-224).
  - `recent_turns` (run_store.py:1163-1175) returns the last N turns, oldest first.
  - `context.build` (context.py:143-459) turns each turn into a history entry: `turn_id`, `ordinal`, `question`, `answer` (the narrative cut to 1500 characters) and `disposition` (context.py:229-287). The history goes into the first user message as `RECENT COMPLETED TURNS IN THIS THREAD` (context.py:431-435). A summary, if present, is appended as `OLDER-HISTORY SUMMARY` (context.py:436-441).
  - Earlier questions also feed `sem.readiness(..., already_asked=[...])` (context.py:337-346).
- **Summaries (`memory.py`).** `memory.maybe_schedule` is called after publishing (worker.py:440-447; memory.py:43-60). It is off unless `COCKPIT_V4_MEMORY_ENABLED=true` and `COCKPIT_V4_MEMORY_MODEL` is set. When on, it makes no model call: `summarize()` is extractive and `put_summary` compare-and-swaps on `summaries.covered_through_ordinal` (run_store.py:1306-1324).
- **Reading a thread:** `GET /threads/{id}` → `read_thread` (routes.py:1382-1433), which uses `store.thread_turns` (all turns, oldest first; run_store.py:1177-1188).

## 3. Continuing after a clarification

There is no resume, continuation or "answering" API. A clarification ends the run, and the reader's reply is a **new run in the same thread**.

1. The analyst calls `finalize_response` with `disposition="clarification"`. `parse_final` requires a `clarification_question` (contracts.py:1157-1161).
2. `_do_finalize` maps the disposition through `_DISPOSITION_STATE` (orchestration.py:106-111, 1748-1749) to `WAITING_FOR_USER`. That is a terminal state (states.py:42, 50-52). Per the `TRANSITIONS` table, "run settles; no process waits" (states.py:237-239).
3. `Worker._settle` stores the published answer, including `clarification_question` and `clarification_options`, both as a `turns` row and as `runs.final_response` (worker.py:392-405).
4. In the UI, each option button calls `onAsk(option)` (frontend/src/components/cockpit-v4/response-panel.tsx:218-223). That posts to `POST /runs` with the same `thread_id` (frontend/src/components/cockpit-v4/client.ts:565-578). The route in §1 treats it as an ordinary follow-up. The earlier run is terminal, so `active_runs_for(thread_id)` is 0.
5. The new worker run rebuilds context. For a prior turn whose disposition is `clarification`, `context.build` adds (context.py:256-286):
   - `you_asked` (the stored `clarification_question`),
   - `you_offered` (up to 6 options, `CLARIFICATION_OPTIONS`, context.py:40),
   - `the_question_still_standing` (the earlier question),
   - a `note` telling the analyst that the reply supplies only the missing part.
6. `envelope.classify` sees the prior turns. If the earlier turn executed (`answer.executed` / `evidence_bound` / intent `DATA_ANALYSIS`), the new run starts on the analysis allowance (envelope.py:195-201).

Store methods involved: `append_turn`, `recent_turns`, `get_summary`, `thread_context`, `thread_domain` and `accept_run`. The `messages` table is per run and is not carried into the next run.

How a clarification is reached inside a run:
- **Blocking ambiguity.** A submission declaring `blocking_ambiguities` is refused by `ExecutionService.validate_batch` because `intent.may_execute` is false (execute_tool.py:365-381). `_do_execute` then sets `must_clarify=True` (orchestration.py:1349-1362), and `action_state.decide` returns `NEEDS_CLARIFICATION` with `finalize_response` required (action_state.py:162-167).
- **Undecided term after reading the catalogue.** `after_catalog` offers both `execute_analysis` and `finalize_response` with nothing required (action_state.py:288-300).

## 4. Runtime and provider construction

- **`config.load()`** (config.py:363-415) reads these environment variables:
  - `COCKPIT_V4_RUNTIME_DIR` (default `~/.creditprobe/cockpit_v4`)
  - `COCKPIT_V4_DEFAULT_MODE`
  - `AI_COCKPIT_REASONING_MODEL` (required)
  - `COCKPIT_V4_RELEASE_ID` (default `release.DEFAULT_RELEASE_ID`)
  - `COCKPIT_V4_PRICE_CARD` (required)
  - `COCKPIT_V4_MEMORY_ENABLED`, `COCKPIT_V4_MEMORY_MODEL`
  - `COCKPIT_ANTHROPIC_API_KEY` (presence only, recorded as `credential_present`)
  - `COCKPIT_V4_STATE_DATABASE` (default `<runtime>/state/cockpit_v4.sqlite3`)
  - `COCKPIT_AGENTIC_V4` (sets `enabled`)
  - `AI_PROVIDER` (default `anthropic`)
  - `COCKPIT_V4_API_PORT` / `COCKPIT_V4_UI_PORT`, `COCKPIT_V4_LOCAL_DEMO_AUTH`, `COCKPIT_V4_HEARTBEAT_SECONDS`
  
  Lease settings are hard-coded: heartbeat 2 s, stale after 10 s, supervisor poll 2 s (config.py:410-412).
- **Credential.** `CREDENTIAL_VAR = "COCKPIT_ANTHROPIC_API_KEY"` (config.py:32). The backend reads **only** that environment variable (`service.credential()`, service.py:83-92). There is no fallback to `ANTHROPIC_API_KEY`.
- **Keychain.** Only the launcher reads the macOS Keychain: `scripts/cockpit_v4/start.py` `read_keychain()` (start.py:60-70) runs `security find-generic-password -s creditprobe-cockpit-v4 -w` (`KEYCHAIN_SERVICE`, start.py:45). `obtain_credential()` (start.py:73-94) tries the environment, then the Keychain, then a `getpass` prompt. The result is passed to the child process as `COCKPIT_ANTHROPIC_API_KEY` (start.py:245).
- **`service.build_runtime(cfg, provider=None, verify_model=True)`** (service.py:315-331) does, in order:
  - checks `cfg.enabled`;
  - `resolve_provider(cfg)` (service.py:100-118): `AnthropicProvider(api_key=key)`, only `AI_PROVIDER=anthropic` is accepted;
  - `load_capability` (service.py:121-146);
  - `load_release` (service.py:149-202), which builds the V3 catalogue for the configured release and caches it;
  - `coverage_for` (service.py:286-312);
  - returns `Runtime(cfg, capability, provider, catalog, coverage, release_summary)` (service.py:51-71).
- **`capability.load_price_card`** (capability.py:123-219) requires:
  - a `models[model_id]` entry whose provider matches;
  - all four prices: `input_usd_per_mtok`, `output_usd_per_mtok`, `cache_write_usd_per_mtok`, `cache_read_usd_per_mtok`;
  - positive integer `context_tokens` and `max_output_tokens`;
  - an ISO `verified_at`;
  - a `source` that is set and not a placeholder.
  
  Any failure raises `CapabilityUnverified`. `PriceCard.cost` is at capability.py:46-53.
- **`capability.verify_live`** (capability.py:222-241) calls `provider.count_tokens(system="ok", ...)` against the model id and sets `live_verified=True` on success. Model feature flags (forced tool use, named tool forcing, effort, single tool per turn) come from `model_capabilities.traits_for` (capability.py:85-104).
- **`backend/llm/anthropic_provider.py`:**
  - `converse` (lines 201-320) builds `client.messages.create(model, max_tokens, system, messages, tools?, tool_choice?, output_config?)`, using `client.messages.with_options(timeout=...)` when a timeout is given (lines 261-267).
  - It parses `tool_use` blocks into `{id, name, input}` (lines 273-282).
  - It reads `message.usage.input_tokens` / `output_tokens` and, via `caching.usage`, `cache_creation_input_tokens` / `cache_read_input_tokens` (lines 284-285, 299-302).
  - It reads `message.stop_reason` (line 297) and `request_id` from `message._request_id` or `message.id` (lines 352-362).
  - It returns a `ConverseResult` with `model=chosen` (line 298).
  - `count_tokens` (lines 173-197) calls `client.messages.count_tokens`.
  - `_client()` (lines 322-329) builds the SDK client without `max_retries` (Finding 3).

## 5. `Worker.execute` (worker.py:131-182), step by step

1. `started = time.monotonic()` and a new `Emitter` (worker.py:132-134). **The ledger clock starts at claim, not at acceptance.**
2. `verdict = envelope.for_request(...)`, recomputed from the same stored inputs as the route (worker.py:139-142).
3. `Ledger(limits=verdict.limits, capability=runtime.capability, store, run_id, started_monotonic=started)` (worker.py:143-145).
4. `_Heartbeat` thread: `store.heartbeat` every 2 s; it raises `LeaseLost` if the lease row is gone (worker.py:147-148, 450-470; run_store.py:762-768).
5. `store.extend_deadline(run_id, now + limits.deadline_seconds)`. This only ever pushes the deadline later (worker.py:155-162; run_store.py:1000-1011).
6. A `context.ready` event (operation `allowance`) with `detail_ref = put_detail({"envelope": verdict.to_dict()})` (worker.py:163-170).
7. **`_drive`** (worker.py:184-338):
   - **Which book.** `_book_for(record)` → `analytical_runtime.for_run(record, store)` (worker.py:340-368; analytical_runtime.py:242-281). A legacy release falls back to `_LegacyBook`; otherwise the run fails with `DATA_UNAVAILABLE` and a `run.failed` event (worker.py:193-203).
   - Takes `scope = book.read_scope(principal)`, `session = book.session` and `release_summary` (worker.py:205-207).
   - Builds the context `packet` (worker.py:209-224; see §2).
   - **Withholding the product tool on the first action.** `pk.coverage(question)` (product_knowledge.py:116-147). If the level is `synopsis`, or the verdict is analytical, then `withhold=(inspect_product_knowledge,)` (worker.py:235-249).
   - Builds `full_tools = provider_tools(catalog=...)` and the `Analyst(provider, capability, ledger, system=packet.system_blocks, tools=provider_tools(withhold, catalog, stage=...))`, then `analyst.user(packet.first_user_message)` (worker.py:264-272).
   - `header = release.header(...)` (worker.py:280-283).
   - Builds the `Orchestrator` with `CatalogService`, `ExecutionService` (session, scope, catalog, store, run_id, tenant, release_id, limits, `pyrunner.PythonRunner()`, header), `ArtifactService`, `Finalizer`, `emitter`, `cancel_check` (re-reads `runs.cancel_requested`), `deferred_tools`, `answer_tools`, `readiness=packet.payload["analysis_readiness"]`, `analytical`, `investigation`, `value_resolution`, and `envelope=intent_envelope.for_run(...)` (worker.py:285-336).
   - Sets `orchestrator._version = record.version` (0 after claim) and calls `run_to_completion()` (worker.py:337-338).
8. `PreflightFailed` becomes `Outcome(FAILED)` plus a `run.failed` event (worker.py:172-177). The heartbeat stops in `finally`.
9. **`_settle`** (worker.py:370-447):
   - Re-reads `get_run` for the current version.
   - Calls `append_turn` if there is a response.
   - `store.update_state(run_id, expect_version, state=outcome.state, operation="", budget=ledger.snapshot(), error_code, error_id, final_response=outcome.response, terminal=True)` (run_store.py:687-726). This is compare-and-swap on `version`: it raises `LeaseLost` on a version mismatch and `TerminalAlready` if the run is already terminal.
   - `LeaseLost` produces a `run.interrupted` event. Any other exception (including `TerminalAlready` after the supervisor has already settled the run) produces `run.failed` with "The result could not be stored".
   - After settling: `answer.ready` if there is a response; otherwise `run.expired` or `run.failed`, unless the orchestrator already emitted a terminal event.
   - Finally `memory.maybe_schedule`.
10. Returns the `Outcome`, which carries an **unredacted** `call_report` (orchestration.py:60-78, 257-264).

## 6. The orchestrator loop (orchestration.py)

**Entry point.** `run_to_completion` (240-255) → `_run_to_completion` (287-356) → `_loop` (524-558). `_run_to_completion` maps exceptions to outcomes:
- `Cancelled` → `CANCELLED`
- `BudgetExceeded`, `InputTooLarge`, `OutputTruncated` → `_stop(code)`
- `ProviderFailure` → `_provider_rejected` for `PROVIDER_REQUEST_INVALID` / `TOOL_SCHEMA_INVALID`, otherwise `_stop`
- `StorageUnavailable` / `LeaseLost` / `TerminalAlready` → `FAILED` or `INTERRUPTED`
- any other exception → `INTERNAL_ERROR`

**`_loop`:**
- Emits `run.started` and `context.ready` (operation `context`).
- `_seed_intent()` (1809-1831) adopts the server's intent envelope, may widen to analytical limits, and emits `intent.validated`.
- If the thread is seeded, emits `context.ready` (operation `investigation_context`).
- Then repeats:
  1. `_guard()`: cancellation check, then `ledger.check_deadline()` (223-226).
  2. `_demand_an_answer_if_time_is_short()` (560-629). Once only: when the action window has closed but the answer window is still open, it switches to answer-only, emits `context.ready` (operation `answer_reserve`) and adds a user message.
  3. `_advance(MODEL_RUNNING, "generation")`, a compare-and-swap `update_state` that also writes `budget=ledger.snapshot()` (228-232).
  4. `turn = self._generate()`; if it returns `None` (a recovery), loop again.
  5. `_advance(ACTION_VALIDATING, "action")` → `outcome = self._handle_turn(turn)`; return it if not `None`.

**`_generate`** (677-933):
- `_action_surface()` (633-675) calls `action_state.decide(...)` (action_state.py:142-251), then `after_catalog` (254-306) if the catalogue has already answered, then `.narrow()` if this is a recovery. `acts.offered()` (318-326) picks the tool names, and `provider_tools(only=names, stage=...)` builds the definitions.
- **Tool gating by state:**

| State | Tools offered | Tool the model must call |
|---|---|---|
| `NEEDS_CLARIFICATION` | `finalize_response` | `finalize_response` |
| `RESULT_READY` (executed or answer-only) | `finalize_response` + `read_artifact` | `finalize_response` |
| `PRODUCT_HELP` (not analytical) | [`inspect_product_knowledge`], `execute_analysis`, `finalize_response` | none |
| `READY_FOR_EXECUTION` (readiness sufficient) | `execute_analysis` | `execute_analysis` |
| `NEEDS_METADATA` | `inspect_catalog` | `inspect_catalog` |

  After a catalogue read, the state moves to `READY_FOR_EXECUTION` with `execute_analysis` (plus `finalize_response`, with nothing required, if a term is still undecided).
- **Output allowance and effort** (692-718). On the answer turn: `reserved_output_tokens` at `answer_effort`, or the higher ceiling at `answer_recovery_effort` after a truncation. On an action turn: `action_output_tokens` at `action_effort`, or `action_output_ceiling` after a truncation.
- **System prompt swaps.** On the answer turn, `ctx.finalization_system` (726-734). When `finalize_response` is offered on a non-answer turn, the policy blocks (plus product blocks for `PRODUCT_HELP`) are appended (735-769).
- Emits `model.requested` (770-784), then **`self.analyst.ask(purpose, max_output_tokens=reserved, phase, effort, require=decision.require)`** (787-790).
- **Recovery paths:**
  - `OutputTruncated`: set the truncation latch, `ledger.spend_format_recovery(phase)`, `analyst.rollback_last_turn()`, purpose becomes `*_FORMAT_RECOVERY`, emit `retry.requested` (operation `output_truncated`), add a user re-ask, return `None` (798-874).
  - `ProviderFailure` with `retry_class=="transport"`: `ledger.spend_transport_retry()`, emit `retry.requested` (operation `timeout` or `transport`), return `None` (875-896). Any other `ProviderFailure` is re-raised.
- On success: emits `model.response_received` (899-925), resets `purpose="ANALYSIS_ACTION"`, calls `store.save_messages(run_id, analyst.messages)` (931-932).

**`_handle_turn`** (998-1066):
- No tool call: `annotate`, `spend_format_recovery`, `retry.requested` (operation `no_tool_call`), a re-ask message, return `None`.
- Unknown tool names are rejected through `_reject_batch` (1068-1080).
- Several calls in one turn are only allowed if all are in `BATCHABLE = {inspect_catalog, inspect_product_knowledge, read_artifact}` and there are at most `MAX_BATCHED_READS=4` (contracts.py:71-73).
- Emits `model.parsed`. Sets `catalog_answered=True` if `inspect_catalog` was called.
- Calls `_handle_call` for each call in order.

**`_handle_call`** (1082-1109) emits `tool.requested`. In answer-only mode, any tool other than `finalize_response` gets a tool error. Dispatch:

| Tool | Handler |
|---|---|
| `inspect_catalog` | `_do_catalog` (1130-1188) |
| `inspect_product_knowledge` | `_do_product_knowledge` (1192-1230) |
| `read_artifact` | `_do_artifact` (1260-1275) |
| `execute_analysis` | `_do_execute` (1279-1608) |
| anything else | `_do_finalize` (1612-1749) |

A `Rejection` becomes `_tool_error` (1111-1126): an error `tool_result` plus a `tool.failed` event whose detail is `{tool, code, field, message}`.

**Counters** (budgets.py:42-61):
- `generation_attempts`, `provider_attempts`, `execution_submissions`, `analysis_rounds`, `catalog_calls`, `artifact_reads`, `steps_attempted`, `action_format_recoveries`, `answer_format_recoveries`, `answer_corrections`, `transport_retries`.
- Also kept on the orchestrator: `product_calls` (at most `MAX_PRODUCT_CALLS=4`, 1908) and `barren_catalog_calls` (warns at 2, stops the run with `NO_PROGRESS` at 3; 1915-1916, 1143-1165).
- **Hitting a budget ends the run.** A `BudgetExceeded` raised inside a tool handler is not caught by `_handle_call`, so it propagates to `_stop`. The one exception is `NO_PROGRESS` from `no_progress_check`, which is converted into a `Rejection` (1408-1417).

## 7. Model calls: `Analyst.ask` (provider.py:367-618)

1. `_record(...)` adds a call-report row with `outcome="refused_before_send"` (397-404).
2. `ledger.check_deadline()` and `ledger.check_call_window(phase)` (406-413).
3. `attempt = ledger.spend_generation()` (414).
4. `fits(reserved_output)` → `count_input()` (220-255). This uses `provider.count_tokens` (spending one provider attempt) or a local estimate of `len(json)/2.2`. If input plus output plus margin exceeds `capability.context_tokens`, it raises `InputTooLarge` (419-430).
5. `affordable_output_tokens` (budgets.py:117-143). If it is below `MIN_RESPONSE_TOKENS=1024` the call is refused with `COST_LIMIT`; otherwise the allowance is reduced and `fits` runs again (437-454).
6. `reservation = ledger.reserve(purpose, input_tokens=counted, output_tokens=reserved_output)`. This inserts a `reservations` row at worst-case cost, or raises `COST_LIMIT` if it would pass the ceiling (budgets.py:440-463; run_store.py:1092-1100) (456-458).
7. `timeout = ledger.call_timeout_seconds(phase)` (budgets.py:151-188) (463).
8. **Tool choice** (471-485): `{"type":"tool","name":require}` when a tool is required and named forcing is supported; `{"type":"any"}` on action turns; nothing on answer turns. `disable_parallel_tool_use=True` is added when supported. **Effort** is sent as `output_config={"effort": effort}` when supported (486-488).
9. **The call itself:** `self.ledger.spend_provider_attempt()` then `_converse(...)` (496-500). `_converse.send` (331-344) spends another provider attempt and calls `self.provider.converse(system, messages, tools, max_tokens, model=capability.model_id, purpose, role="cockpit_v4_analyst", timeout, allow_retry=False, tool_choice?, output_config?)`. If the provider returns a 400 naming `tool_choice`, `output_config` or `effort`, those parameters are turned off for the rest of the run and the request is re-sent once (346-365).
10. **Failure handling:**
    - `BudgetExceeded` → reservation settled at zero (501-510).
    - Any other exception → reservation settled `uncertain=True` (`settled_usd` NULL, usage `{"error":...}`), call-report row updated, `raise _classify(exc)` (511-531).
11. **Usage read** (533-539). `ledger.settle(reservation, usage={input_tokens, output_tokens, cache_read_tokens, cache_write_tokens})` computes `price.cost(...)` and writes `reservations.settled_usd` and `usage` (budgets.py:465-481; run_store.py:1102-1112).
12. **Stop reason and model** (541-556). `stop_reason = result.stop_reason`; `model = result.model` (the requested id, Finding 2). A `Turn` is built with `duration_ms`, token counts, `counted_input_tokens` and `count_method`.
13. **Outcomes by stop reason** (568-590):
    - `max_tokens` → `OutputTruncated`. The partial turn is not added to history; the reservation is already settled.
    - `refusal` → `PROVIDER_UNAVAILABLE`.
    - any other unknown stop reason → `INVALID_MODEL_OUTPUT`.
14. **History** (593-605). The assistant blocks are appended to `messages`, and `_pending` holds the tool_use ids awaiting results.
15. **What is persisted per call:**
    - one `reservations` row;
    - `model.requested` and `model.response_received` events, each with a detail record (orchestration.py:770-925);
    - the `messages` table, rewritten on success (orchestration.py:932);
    - the in-memory call-report row, which is persisted once at the end as `{"call_report": ...}` in `details` (orchestration.py:257-264), with token keys redacted;
    - an in-process `backend.llm.telemetry` record via `record_success` / `record_failure` (anthropic_provider.py:287-294, 312-317). This is a `deque(maxlen=100)` and is not written to disk.

**Error classification** (`_classify`, provider.py:652-746):

| Condition | Code | `retry_class` |
|---|---|---|
| 400 / `invalid_request_error` | `TOOL_SCHEMA_INVALID` or `PROVIDER_REQUEST_INVALID` | none |
| 401 / authentication | `PROVIDER_AUTH` | none |
| 403 / permission | `PROVIDER_AUTH` | none |
| rate limit / 429 | `PROVIDER_RATE_LIMIT` | **transport** |
| timeout / connection / 502 / 503 / "overloaded" | `PROVIDER_UNAVAILABLE` | **transport** |
| anything else (e.g. HTTP 500 `api_error`) | `PROVIDER_UNAVAILABLE` | **none**, so the run fails |

**Does the product retry provider errors itself? Yes, in two layers:**
- **(a) Inside the SDK, not disabled** (Finding 3). Only the adapter's own retry loop is turned off (`allow_retry=False` → `attempts_allowed=1`, anthropic_provider.py:244); the SDK's built-in retries are left on. The adapter's `_worth_retrying` (lines 369-382) is therefore unused on this path.
- **(b) In the orchestrator.** A transport-class failure gets **one immediate retry per run, with no sleep**: `Ledger.spend_transport_retry` (budgets.py:390-426) → `retry.requested` → `continue` in `_loop`.
  - The retry is a new generation with a new reservation. The failed call's reservation stays pending/uncertain and keeps reducing the remaining budget.
  - A second transport failure raises `BudgetExceeded(PROVIDER_UNAVAILABLE)` → `_stop`. The run settles `FAILED`, or `PARTIAL` with a result-only answer if SQL had already run, because `PROVIDER_UNAVAILABLE` is in `RESULT_ONLY_REASON`.
  - `PROVIDER_RATE_LIMIT` as a terminal code is **not** in `RESULT_ONLY_REASON`. It only reaches `_stop` if it escapes, which transport-class failures do not: they go through `spend_transport_retry` instead.

## 8. Tokens, cost and limits

- **`Ledger`** (budgets.py:64-546):
  - `reserve` / `settle` / `cancel` (440-490). `cancel()` marks every open reservation uncertain.
  - `spend()` → `store.spend(run_id)` (run_store.py:1114-1130), which returns `{committed_usd, pending_usd, uncertain}`. A NULL `settled_usd` counts as pending.
  - `affordable_output_tokens` (117-143), `adopt()` (96-115, widen only), `snapshot()` (510-546).
- **Per-run spend ceiling.** `reserve` raises `COST_LIMIT` if committed + pending + worst case exceeds `limits.spend_ceiling_usd` (452-459).
- **Limit sets** (config.py:179-247):

| Limit | `STANDARD_LIMITS` (product help) | `ANALYTICAL_STANDARD_LIMITS` |
|---|---|---|
| deadline_seconds | 60 | **180** |
| spend_ceiling_usd | 1.00 | **1.50** |
| generation_attempts | 12 | 12 |
| provider_attempts | 24 | 24 |
| execution_submissions | 5 | 5 |
| analysis_rounds | 3 | 3 |
| catalog_calls | 4 | 4 |
| artifact_reads | 6 | 6 |
| steps_per_batch / total_steps | 6 / 12 | 6 / 12 |
| step_seconds | 15 | 15 |
| format_regenerations / answer_format_regenerations | 2 / 2 | 2 / 2 |
| answer_corrections | 1 | 1 |
| charts | 6 | 6 |
| reserved_output_tokens (answer) | 8192 | 8192 |
| action_output_tokens | 3072 | 3072 |
| action_output_ceiling / answer_output_ceiling | 4096 / 12288 | 4096 / 12288 |
| action_call_seconds / answer_call_seconds | 30 / 55 | 30 / 55 |
| effort: action / answer / answer_recovery | low / medium / low | low / medium / low |
| finalization_reserve_seconds | 20 | 20 |
| min_call_seconds | 5 | 5 |
| preview_rows / preview_columns | 100 / 32 | 100 / 32 |

  Also fixed: transport retries 1 (budgets.py:419), `MIN_RESPONSE_TOKENS` 1024, `SETTLEMENT_MARGIN_SECONDS` 2.0.
- **Deep mode:** `DEEP_LIMITS` is 120 s / $2.00; `ANALYTICAL_DEEP_LIMITS` is 240 s / $3.00 (config.py:195-247).
- **Widening mid-run.** `Orchestrator._widen_to_analytical` (orchestration.py:1784-1807) calls `ledger.adopt(analytical_limits_for(mode))`, then `store.extend_deadline`, then emits `context.ready` (operation `budget`). It is triggered by `execute_analysis` (1292) or by a declared `DATA_ANALYSIS` intent (1772-1782, 1848-1852). Note that the `envelope.py` docstring says 120 s for analysis; the code value is 180 s.

## 9. The five tools

**`inspect_catalog`** (`_do_catalog`, orchestration.py:1130-1188):
- `parse_catalog` (contracts.py:707), `_record_intent`, `ledger.spend_catalog_call`, `_advance(TOOL_RUNNING)`.
- `CatalogService.inspect(request)` (catalog_tool.py:232-416) handles detail types `discovery`, `fields` (paged by `MAX_FIELDS_PER_PAGE`), `relationships`, `coverage` and `samples`. It refuses underspecified or over-broad requests (168-230) and issues a `MetadataReceipt` (`mr-<hex>`, 407-413). `_account` (418+) adds `requested`, `returned`, `already_known`, `still_missing`, `coverage_complete_for_request` and `added_new_information`.
- Then the no-progress guard, `tool_result`, and a `tool.completed` event (stage `catalog`).

**`inspect_product_knowledge`** (`_do_product_knowledge`, 1192-1230):
- `parse_product_knowledge`, deadline check, `product_calls` capped at 4, `_advance`.
- `pk.retrieve(query, topics, detail)` (product_knowledge.py:259-359) returns sections from `product_knowledge.json` with `pack_version`, `topics_returned` and `sections`.
- Emits `tool.completed` (stage `product_knowledge`).

**`read_artifact`** (`_do_artifact`, 1260-1275):
- `parse_artifact`, `spend_artifact_read`, `_advance`.
- `ArtifactService.read` (artifacts.py:32-105): for `thread_turn` it calls `store.get_turn`; otherwise `store.get_artifact(id, tenant_id)` and returns a window of rows (offset/limit/cursor, at most 32 columns) with `executed_code_digest`. An artifact from another release is labelled `comparison_evidence`.
- Emits `tool.completed` (stage `reviewing`).

**`execute_analysis`** (`_do_execute`, 1279-1608). Order of operations:
1. `_adopt_analytical_limits_for_tool`, then `envelope.escalate_to_analysis()`.
2. `ordinal = ledger.spend_submission()`. This is counted before validation, so a malformed payload still uses a slot.
3. `parse_execution(args, max_steps=steps_per_batch, carried=intent)` (contracts.py:629-670; steps parsed by `parse_steps`, 482).
4. `_record_intent`.
5. `key = no_progress_key(...)` (execute_tool.py:838-852): sha256 of release, error class, and each step's language, code and parameters.
6. **`bind_report = execution_service.validate_batch(submission)`** (execute_tool.py:358-395). Every step is checked before any step runs:
   - **Authorisation of intent:** `intent.may_execute`, i.e. `DATA_ANALYSIS`, owner `COCKPIT`, no blocking ambiguity; otherwise `SECURITY_DENIED`.
   - **SQL structure:** `_validate_sql` (476-528) → `sql.check_structure` (sql.py:112-156): exactly one SELECT, no forbidden keywords or calls.
   - **Domain authorisation:** `sql.authorize` (sql.py:188-240). A relation from the other book gives `SECURITY_DENIED` (`CROSS_DOMAIN_ACCESS`); anything else out of scope gives `SQL_VALIDATION`.
   - **Relation allow-list:** a regex check of names against `session.relations`, minus CTE and alias names (`CHECK_AUTHORIZATION`).
   - **Join grain:** `_check_join_grain` (397-445) → `sql.multiplication_risk` (sql.py:421). This catches an additive measure aggregated across a join that repeats rows. If the check itself cannot run, the result is `INTERNAL_ERROR`, not a pass.
   - **Bind proof:** `_prove_bindable` (459-474) → `sqlbind.prove_bindable` (sqlbind.py:180-209), which runs `EXPLAIN <sql>` with parameters and executes nothing. Only steps without dependencies are bound now; the rest are bound at run time.
   - **Python steps:** `_validate_python` (530-549) requires the sandbox runner.
   - **On `Rejection`:** set `must_clarify` if the rejection was for ambiguity; `store.record_submission(status="rejected", round=0, no_progress_key=key)`; `_remember_failure`; `tool.failed` (stage `validating`) with the steps and the check detail; re-raise, which becomes a `_tool_error` (orchestration.py:1320-1406).
7. `ledger.spend_steps(n)`, then `ledger.no_progress_check(key)` (a duplicate becomes a `Rejection`), then `round_no = ledger.open_round()`.
8. `record_submission(status="running", round=round_no)`, then `tool.validated` with the bind-proof detail (1420-1494), then `_advance(TOOL_RUNNING)`.
9. **Execution.** `execution_service.run_batch(submission, submission_id, deadline_seconds=min(remaining, step_seconds*len(steps)), on_step=...)` (execute_tool.py:553-624) runs the steps serially. Each step's budget is `min(step_seconds, remaining)`.
   - `_run_sql` (631-717): re-bind with `prove_bindable` → `_execute_sql` (719-785) → `sql.execute` (sql.py:596-663). A watchdog thread interrupts the connection at the deadline; results are capped at `MAX_RESULT_ROWS` and clipped to `preview_rows`.
   - **Artifact write:** `store.put_artifact(kind="result", scope={relations, referenced_relations, step_id, domain_id, complete, produced_rows, release_fingerprint}, columns, rows, code_digest=sha256)`.
   - Returns a `StepResult` with preview rows, `row_ids`, units and `elapsed_ms` (StepResult 195-281).
   - Python steps go through `_run_python` (787-835).
   - A failed step stops the batch; later steps are marked `not_run`.
   - `on_step` emits `tool.started`, `tool.completed` or `tool.failed` (stage `executing`) (orchestration.py:1498-1563).
10. After the batch: `store.set_submission_status(submission_id, batch.status)`; artifact ids are added to `finalizer.run_artifacts` and `executed=True`; `close_round()` on success; on failure a second `record_submission` marker row `{failed: step_id}` with an error-class key (1571-1597).
11. `tool_result(batch.to_dict() + budgets_remaining [+ note])`.

**`finalize_response`** (`_do_finalize`, 1612-1749):
1. `parse_final` (contracts.py:1008-1170; dispositions at 56-58), `_record_intent`, `_advance(FINAL_VALIDATING)`.
2. **`Finalizer.validate(final, executed)`** (finalization.py:379-465). For each claim, `_check_claim` (636-681):
   - **Direct evidence:** the artifact must belong to this run and be readable by the tenant; `release_problem` checks the release id and fingerprint (477-502); the column must exist; `_wrong_entity` checks the counted entity (587-634); `_locate` finds the row and cell (null cells are refused); the value is compared as a Decimal through `_settle` → `prec.check` (516-541).
   - **Derived claims:** `_check_derived` (543-585) recomputes the value via `deriv.compute`.
   - **Whole-answer checks:** narrative placeholders must match claim ids; a `DATA_ANALYSIS` answer must contain claims or tables; claims are refused if nothing was executed; charts (a failure only drops the chart with a warning); `_check_table`, `_check_ordering`, `_check_movement`, `_check_policy_citation`.
   - If everything passes, `substitute()` writes the server-rendered values into the narrative.
3. **If the report is not OK:** `answer.validated` (status rejected) with detail `{problems}`, then `spend_answer_correction()`.
   - The first time: answer-only mode, purpose `ANSWER_CORRECTION`, and a tool error carrying `correction_packet(...)` (1683).
   - The second time (budget exceeded): `_preserve_analysis`, then `_result_only_response`, settling `PARTIAL` or `FAILED` with `ANSWER_VALIDATION`.
4. **If it passes:**
   - `surviving_charts` and `validate_suggestions`.
   - The published object is `final.to_dict()` plus: `narrative` (rendered), each claim's `display_value`, `tables` and `charts` re-rendered from the stored artifacts, `suggested_questions`, `validation=report.to_dict()` (`{ok, problems, warnings, claims_checked}`), `evidence_bound`, `executed`, `policy_context` / `policy_citations`, and `release` (header).
   - Emits `answer.validated` (ok), writes the accepted `tool_result`, calls `save_messages`, and returns `Outcome(_DISPOSITION_STATE[disposition], response=published)`.

## 10. What is persisted for artifacts and submissions

**`put_artifact`** (run_store.py:930-944) writes to `artifacts`:
- columns: `artifact_id='art-<16hex>'`, `run_id`, `tenant_id`, `kind`, `release_id`, `scope` (JSON), `columns` (JSON), `row_count`, `body` (JSON rows), `code_digest`, `created_at`, plus `domain_id` (added by migration, left at its default here);
- the stored rows are the `preview_rows`-clipped set (at most 100 for SQL), with `scope.complete` and `scope.produced_rows` recording whether that is the whole result;
- read back with `get_artifact(id, tenant_id)` (965-982) or `artifact_ids_for_run(run_id, tenant_id)` (946-963);
- also served over HTTP at `GET /runs/{id}/artifacts/{aid}` (routes.py:471-488).

**`record_submission`** (run_store.py:986-998) writes to `submissions`:
- columns: `submission_id='sub-<12hex>'`, `run_id`, `ordinal`, `round`, `payload` (JSON from `submission.to_dict()`), `status` (`rejected` / `running` → `ok` or `failed` / `failed` marker), `no_progress_key`, `created_at`;
- `set_submission_status` is at 1013-1016;
- `submissions_for_run` (1018-1066) merges rows per `ordinal`, keeping the full payload and adding `failed_step` from the marker row;
- `no_progress_keys` (1086-1090).

**Other tables written:**
- `details(detail_ref='dt-<16hex>', run_id, body, created_at)` (877-896), redacted.
- `messages(run_id, ordinal, role, content)` (908-926), a full rewrite each time.
- `turns`, and `runs.final_response` / `runs.budget`.

## 11. Deadlines, terminal states, events, messages

**Deadlines:**
- **Ledger (inside the worker):**
  - `check_deadline` (budgets.py:250-255) raises `DEADLINE_EXPIRED`.
  - `check_call_window` (201-230) refuses an action call when less than `min_call + finalization_reserve` seconds remain (only once at least one generation has happened).
  - `action_window_closed` / `answer_window_open` (232-248) drive the one-time answer-reserve turn.
  - `call_timeout_seconds` (151-188) is the socket timeout for one call.
- **`runs.deadline_at`:** stamped at accept (routes.py:337), pushed later at claim (worker.py:155-160) and on widening (orchestration.py:1793-1797).
- **Supervisor** (supervisor.py): `serve_forever`, then `sweep()` every 2 s (74-88).
  - `_settle_expired` (90-100) handles `expiring_runs(grace_seconds=15)` (run_store.py:795-825). It settles them `EXPIRED` / `DEADLINE_EXPIRED`, or `PARTIAL` if artifacts exist, using `_rows_already_computed` → `Finalizer.result_only_response` (117-183).
  - `_settle_abandoned` (102-115) handles `stale_runs(10 s)` → `INTERRUPTED` / `WORKER_LOST`.
  - `_terminate` (185-218) does the compare-and-swap `update_state`, then emits `run.expired` or `run.interrupted` (operation `supervisor`), plus `analysis.preserved` if a result was published.
- **Orchestrator deadline stop:** `_stop` (orchestration.py:405-464) gives `EXPIRED`, or `PARTIAL` if something executed and the code is in `RESULT_ONLY_REASON` (finalization.py:61-100).

**States** (states.py):
- Working: `ACCEPTED`, `CONTEXT_READY`, `MODEL_RUNNING`, `ACTION_VALIDATING`, `TOOL_RUNNING`, `FINAL_VALIDATING` (27-36).
- Terminal: `COMPLETED`, `PARTIAL`, `WAITING_FOR_USER`, `REFERRED`, `UNSUPPORTED`, `FAILED`, `CANCELLED`, `EXPIRED`, `INTERRUPTED` (40-52).
- Answer-bearing: `COMPLETED`, `PARTIAL`, `WAITING_FOR_USER`, `REFERRED`, `UNSUPPORTED` (57-58).
- Error codes at 62-116; operator-only codes at 119-123.
- Disposition to state: `answer`→`COMPLETED`, `partial_answer`→`PARTIAL`, `clarification`→`WAITING_FOR_USER`, `referral`→`REFERRED`, `unsupported`→`UNSUPPORTED`, `safe_failure`→`FAILED` (orchestration.py:106-111).

**Event types** (events.py:30-65):
`run.accepted`, `run.started`, `context.ready`, `model.requested`, `model.response_received`, `model.parsed`, `intent.validated`, `tool.requested`, `tool.validated`, `tool.started`, `tool.completed`, `tool.failed`, `retry.requested`, `answer.validated`, `answer.ready`, `analysis.preserved`, `run.failed`, `run.cancelled`, `run.expired`, `run.interrupted`, `memory.started`, `memory.completed`, `memory.failed`.
- Terminal events: `answer.ready`, `run.failed`, `run.cancelled`, `run.expired`, `run.interrupted` (68-69).
- The `memory.*` events are declared but no code emits them.
- **Every event row** (`Event.to_dict`, events.py:151-167) has: `schema_version`, `event_id`, `run_id`, `seq`, `event_type`, `stage`, `operation`, `status` (`started` / `ok` / `failed` / `rejected`), `occurred_at` (ISO, ms), `elapsed_ms` (since the emitter's start, i.e. worker claim time), `attempt`, `submission`, `round`, `public_message`, `detail_ref`, `error_id`, `trace_id`, `span_id`, `parent_span_id`, `stage_instance_id`, `stage_started_ms`, `stage_state`, `stage_failures`, `closed_stages[{stage, stage_instance_id, started_ms, ended_ms, failures, state}]`.
- Events are written by `Emitter.append` (214-248) → `store.append_event` (run_store.py:845-857) as `events(run_id, seq, payload JSON, occurred_at)`. Event payloads are not redacted.

**Messages:** `store.load_messages(run_id)` (run_store.py:921-926) returns `[{role, content}]`, the full provider history as of the last `save_messages`. That happens after each successful generation (orchestration.py:932) and after an accepted finalize (1746). Tool results added after the last successful generation are not saved if the run then stops. See Finding 5 for the assistant-block format.

## 12. Observation seams (no source changes needed)

### Store methods (`RunStore`, run_store.py)

| Method | Returns / keys |
|---|---|
| `get_run(run_id)` (684) | `RunRecord`: `state`, `version`, `error_code`, `error_id`, `operation`, `final_response` (published answer incl. `validation{ok,problems,warnings,claims_checked}`, `numeric_claims[].display_value`, `tables`, `charts`, `executed`, `evidence_bound`, `release`), `budget` (= `ledger.snapshot()`: `mode`, `elapsed_seconds`, `remaining_seconds`, `generation_attempts[used,limit]`, `provider_attempts[...]`, `execution_submissions[...]`, `analysis_rounds[...]`, `catalog_calls[...]`, `artifact_reads[...]`, `steps_attempted[...]`, `action_format_recoveries[...]`, `answer_format_recoveries[...]`, `format_recoveries[...]`, `answer_corrections[...]`, `spend{committed_usd,pending_usd,uncertain}`, `spend_ceiling_usd`, `deadline_seconds`, `response_tokens_reserved`, `cost_enforced`), `created_at`, `updated_at`, `deadline_at`, `delivered_at`, `cancel_requested`, `domain_id`, `release_fingerprint`. Not redacted. |
| `events_since(run_id, after_seq=0, limit=500)` (859) | `Event` objects (keys in §11). |
| `last_seq(run_id)` (871) | int |
| `get_detail(ref)` (898) / `details_for_run(run_id)` (1068) | `{detail_ref: body}`, **redacted**. The last detail written by a run is `{"call_report": {...}}` (orchestration.py:261), which has no event pointing at it; find it via `details_for_run`. |
| `spend(run_id)` (1114) | `{committed_usd, pending_usd, uncertain}` |
| `submissions_for_run(run_id)` (1018) | `[{submission_id, ordinal, round, payload{objective, steps[...], intent, ...}, status, no_progress_key, created_at, failed_step?}]` |
| `artifact_ids_for_run(run_id, tenant_id)` (946), `get_artifact(id, tenant_id)` (965) | `{artifact_id, run_id, kind, release_id, scope{relations, referenced_relations, step_id, domain_id, complete, produced_rows, release_fingerprint}, columns, row_count, rows, code_digest, created_at}` |
| `load_messages(run_id)` (921) | provider history (Finding 5) |
| `thread_turns(thread_id)` (1177), `recent_turns` (1163), `get_turn` (1293) | `{turn_id, run_id, ordinal, question, answer, created_at}` |
| `lease(run_id)` (770) | `{run_id, worker_id, fence, heartbeat_at, claimed_at}` |
| `no_progress_keys(run_id)` (1086) | set |
| Direct read-only SQL: `SELECT reservation_id, purpose, reserved_usd, settled_usd, uncertain, usage, created_at FROM reservations WHERE run_id=?` | **The only persisted, unredacted per-model-call token record.** One row per generation that got past the cost check. `purpose` is `ANALYSIS_ACTION` / `FINAL_ANSWER` / `*_FORMAT_RECOVERY` / `ANSWER_CORRECTION`. `usage` holds `{input_tokens, output_tokens, cache_read_tokens, cache_write_tokens}` on success, `{"error": "..."}` on failure, `{"cancelled": true}` on cancel. `settled_usd` is NULL while pending or uncertain. `created_at` is reservation time (before the call). No store method lists these rows. |

### Per-model-call telemetry events (detail bodies via `get_detail(event.detail_ref)`)

- **`model.requested`** (orchestration.py:770-784). Event fields: `attempt` (= generation number), `elapsed_ms`, `occurred_at`. Detail: `purpose`, `phase` (`action`/`answer`), `action_state{state, tools, require, because, recovering, ...}`, `tools_offered`, `required_tool`, `max_output_tokens` (**redacted**), `effort`, `context_bytes{system, tools, messages, total}`.
- **`model.response_received`** (899-925). Event fields: `attempt`, `elapsed_ms`, `occurred_at`. Detail: `purpose`, `model` (requested id), `request_id`, `stop_reason`, `count_method`, `output_allowance{wanted, granted, reduced}`, `duration_ms` (provider wall time), and `counted_input_tokens` / `reported_input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_write_tokens` (all **redacted**).
- **`retry.requested`** operations:
  - `output_truncated`: detail `{phase, answering, overran, next_allowance}`.
  - `transport` / `timeout`: detail `{code, retry_class, timed_out}`.
  - `no_tool_call`: no detail.
- **`{"call_report": ...}` detail** (end of run, redacted). Top level: `calls[]`, `generations`, `provider_ms`, `by_purpose`, `by_phase`, `elapsed_ms`, `local_ms`, `deadline_seconds`, `executed`, `analysis_preserved`. Each `calls[]` row (provider.py:397-617): `seq`, `purpose`, `phase`, `attempt`, `tools_offered`, `context_bytes`, `serialize_ms`, `count_method`, `count_ms`, `output_allowance`, `call_timeout_seconds`, `tool_choice`, `required_tool`, `effort`, `outcome`, `stop_reason`, `request_id`, `provider_ms`, `truncated`, `tool_names`, `tool_calls`, `parse_status`, `response_text_chars`, `usable`, `rejected_because`, `refusal`, `error`, `request_parameters_refused`. Its `*_tokens` keys are redacted.

### Per-tool telemetry

- `tool.requested` (stage per tool, operation = tool name, status `started`) marks the start of each call. The next `tool.completed` / `tool.failed` gives the end, and `elapsed_ms` differences give duration.
- **`inspect_catalog`** `tool.completed` detail: `requested`, `returned`, `already_known`, `still_missing`, `coverage_complete_for_request`, `added_new_information`, `requested_fields`, `requested_relations`, `detail`, `receipt`.
- **`inspect_product_knowledge`** `tool.completed` detail: `query`, `topics`, `detail`, `pack_version`, `sections`.
- **`read_artifact`** `tool.completed`: no detail; `public_message` gives the returned row count.
- **`execute_analysis`:**
  - Per step: `tool.started` (operation = `step_id`, fields `submission`, `round`), then `tool.completed` with detail `{step_id, executed_code_digest, submitted_code, artifact_id, warnings}`, or `tool.failed` with detail `{step_id, phase, executed, failed_check, error_code, message, parameters, submitted_code, failed_code_digest, ...engine_detail}`.
  - Per-step `elapsed_ms` measured by the engine is only in the `execute_analysis` tool_result inside `load_messages` (`steps[].elapsed_ms`, execute_tool.py:252), and only once a later `save_messages` has run.
  - SQL `elapsed_seconds` from the engine is not persisted.
- **Tool errors** (`_tool_error`): `tool.failed` status `rejected` with detail `{tool, code, field, message}`. Batch rejection: `tool.failed` operation `batch`, no detail.

### Validation results

- **`tool.validated`** (operation `execute_analysis`, fields `submission`, `round`). Detail: `objective`, `submission_id`, `bind_proof{method, covers, proven_before_execution, proven_at_run_time}`, `checks_passed{structure, relations, join_grain}`, `not_proven[]`, `steps[{step_id, language, purpose, code, parameters}]`, `fields_required`, `metadata_receipts`.
- **`tool.failed`** stage `validating` (a refused submission). Detail: `submission_id`, `submission`, `stage`, `error_code`, `field`, `message`, `steps[]`, plus the rejection detail (`failed_check` ∈ `sql_structure` / `relation_authorization` / `domain_authorization` / `join_grain` / `bind` / `sandbox`, `phase`, `category`, `relation`, `owning_domain`, `note`, ...).
- **`answer.validated`:**
  - operation `answer_check`, status rejected: detail `{problems}`.
  - status ok: no detail; the full report is in `final_response.validation`.
  - operation `publish_result_only`: a result-only answer was published.
- **`intent.validated`:** operations `intent` (detail = intent or envelope dict), `semantics` ("Resolved:" / "Assumed:" lines), `ambiguity` (rejected; "Needs a decision").
- **`context.ready`:** operations `allowance` (detail `{envelope}`), `context`, `investigation_context`, `budget` (detail `{budget_adopted{before, after, changed}}`), `answer_reserve` (detail `{reserve_seconds, remaining_seconds, executed}`).
- **Terminal events:** `run.failed` / `run.expired` detail `{terminal_code, first_analytical_failure}` when present; `analysis.preserved` detail `{artifact_ids, analysis_status, publication_status, reason}`; `answer.ready`.

### HTTP seams

- `GET /runs/{id}` (routes.py:435): the run record plus `last_event_seq` and `terminal`.
- `GET /runs/{id}/trace` (2014-2050): all events (via `events_since` with its default `limit=500`), `budget`, `release`.
- `GET /runs/{id}/events` (2053-2119): SSE with replay by `Last-Event-ID`, ending with `run.settled`.
- `GET /runs/{id}/details/{ref}` (491-521), `GET /runs/{id}/artifacts/{aid}` (471).
- `GET /threads/{id}` (1382), `GET /diagnostics` (1982).

### In-process seams (harness drives the worker directly)

- `Worker.execute(record)` returns an `Outcome` whose `.call_report` is **not redacted**, so it carries real per-call token counts (worker.py:131-182; orchestration.py:257-264).
- `backend.llm.telemetry.ledger().calls`: an in-memory `deque(maxlen=100)` of `Call` objects with `model`, `purpose`, `role`, `effort`, `latency_ms`, `request_id`, `attempts`, `input_tokens`, `output_tokens`, `cache_write_tokens`, `cache_read_tokens`, `ok`, `failure_category`, `failure_reason` (telemetry.py:200-240, 343-381). Only available when the harness runs in the same process.

### Caveat in the existing UAT script

`scripts/cockpit_v4/live_uat.py:587-589` reads `e.created_at` and `e.body`, which `Event` does not have. The real fields are `occurred_at` and `detail_ref`.

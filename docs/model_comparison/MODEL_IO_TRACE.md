# Model I/O Trace (lab-only)

**Model I/O Trace captures the actual request/response boundary. Provider credentials and hidden reasoning are excluded.**

Switch: `MODEL_LAB_FULL_IO_TRACE` (default **on**; set `false` to disable). It applies to the Model Lab only; the frozen AdvancedCockpit and production provider behaviour are unchanged.

## What is captured, per model call

| View | Source | Contents |
|---|---|---|
| Engine request | Lab observer at the provider seam (`observe.py`), serialised **before** the call | Full system prompt, every message in order (user, assistant, `tool_use`, `tool_result`), complete tool schemas, `tool_choice`, `max_tokens`, `timeout`, `output_config`, and any other keyword argument. Metadata adds the comparison, child, question, profile and model ids, stage, purpose, context capacity, counted input, reserved output, call timeout, request controls and byte sizes. |
| Wire request | `RecordingTransport` around the provider's own httpx transport (`io_trace.py`) | Method, URL without credentials or query, allowlisted headers, the exact JSON body, byte count and SHA-256 of the bytes actually sent. SDK-level retries appear as extra attempts. |
| Raw response | Same transport | Status, allowlisted headers, and either the JSON body or every SSE event in arrival order (timestamps, chunk sizes), plus the assembled provider response. |
| Normalized response | Observer | The object the adapter returned to the engine (text, blocks, tool calls, stop reason, model, usage, provider metadata), or the typed failure. |

**Tool round trips.** Each one records:
- the model's tool call;
- the frozen validation and execution records (`tool.*` events with details, submissions, submitted SQL/Python and executed-code digest);
- the **exact** `tool_result` the next request carried, taken from the next call's captured request. If no later call exists, it comes from the frozen stored history, and the source says so.

**Stage links.** Every call carries its S1–S4 tags from the evaluation, and shared spans stay marked shared. Each stage lists the calls and tool round trips behind it.

## Excluded by construction (tested with canaries)

- **Credentials.** Headers pass an allowlist, so `Authorization`, `x-api-key`, cookies and `set-cookie` never enter the record. URL user-info and query strings are dropped. Any value of a secret-looking environment variable (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*COOKIE*`, `*AUTH*`) that appears in a body is replaced with `[REDACTED_SECRET]`. The same check runs again on every text file in the export.
- **Hidden reasoning.** `thinking` / `redacted_thinking` blocks and `reasoning` / `reasoning_content` fields are replaced by `{"field_present": true, "chars": N, "sha256": …, "reason": "HIDDEN_REASONING_NOT_EXPORTED"}`. Wire byte counts and hashes refer to the bytes actually transmitted.

## No artificial truncation

Bodies are stored as transmitted. A tool result is exactly what CreditProbe sent the model, including any bounded preview it chose. Underlying rows that were not sent are never added.

## Failures

| Failure | What the trace holds |
|---|---|
| HTTP error | The request, plus the error status and body. |
| Timeout or transport failure | The request, plus `transport_error`. |
| Invalid output or truncation | The raw response, plus the typed error. |
| Refused before dispatch by the frozen engine (e.g. `INPUT_CONTEXT_LIMIT`) | A timeline row with `dispatch_status = NOT_SENT` and the reason. |

**Counted input tokens.** The frozen run store redacts every `*_tokens` key when it persists the call report. For the local-estimate route, the lab recomputes the count from the captured request with the frozen formula and labels it as recomputed. A provider-side count is shown as unavailable, with that reason.

## Where to see it

- **UI.** Comparison result → **MODEL I/O TRACE**: a timeline of calls and tool round trips. Each view can be shown as pretty or raw JSON, copied and downloaded, with its byte count and SHA-256, and there is a role-labelled conversation view.
- **API.** `GET /api/v1/model-lab/comparisons/{id}/model-io` and `/model-io/{call_id}`. Both are read-only, with no model call.
- **Export pack:**
  - `model_io/call_NNN/{engine_request,wire_request,wire_response_raw,normalized_response,metadata}.json`
  - `tool_roundtrips/tool_NNN.json`
  - `model_io.jsonl` and `tool_roundtrips.jsonl`
  - `MODEL_IO_TRACE.html`, `MODEL_IO_MANIFEST.json` and `MODEL_IO_CHECKSUMS.sha256`
  - workbook sheets *Model Calls*, *Request Summary* and *Tool Round Trips*, which use paths and hashes rather than bodies.

## Neutrality (tests in `tests/model_lab/test_model_io_trace.py`)

- **Transport.** The recording transport forwards the same request object. The mock server receives identical bytes and headers with or without it, and streamed and non-streamed results assemble identically.
- **Engine.** With tracing on and off, the requests the frozen engine hands the provider are identical (after normalising per-run random ids and clock readings). So are the frozen event sequence, tool call ids, tool results, checks and the final answer. The number of requests is unchanged: no extra call, no retry.
- **Failures in the trace itself.** A failure in trace capture is swallowed; it can never stop the run.

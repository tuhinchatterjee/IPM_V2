# Metric dictionary

## Rules that apply to every metric

- Every metric is a `Metric(value, unit, status, source, missing_reason, definition)` (`backend/model_lab/metrics.py`).
- **Status** is one of `MEASURED`, `ESTIMATED`, `DERIVED`, `UNAVAILABLE`, `SHARED` or `HUMAN_REVIEWED`.
- **A missing value stays `null`, with a reason, in the UI, the database, CSV and XLSX.** It is never shown as zero.
- **One calculation source:** `evaluate.py` computes every metric. The UI, the CSVs, the workbook and the manifest all read that one computation.

## Timing

All timing values are in milliseconds.

| Metric | Start → end | Source | Notes |
|---|---|---|---|
| `comparison_elapsed_ms` | `comparison.created` → last `comparison.settled` | Lab events, monotonic | Includes queueing across models. |
| `queue_delay_ms` | Child enqueued → admitted to the frozen Worker | Coordinator, monotonic | Waiting behind another model is **not** counted as that model's latency. |
| `service_ms` | For each turn, run accepted → frozen `Worker.execute` returned, summed over turns | Coordinator, monotonic | Excludes user wait. |
| `user_wait_ms` | A `WAITING_USER` turn finished → its clarification turn started | Derived | `UNAVAILABLE` when no clarification was resumed. |
| `provider_call_ms` | Interval union of the `converse()` spans | `ObservingProvider`, monotonic | Overlaps are merged. The per-call sum is also shown, as `provider_call_ms_sum`. |
| `creditprobe_ms` | Interval union of `tool.requested` → `tool.completed` / `tool.failed` | Frozen events `elapsed_ms` | Validation and SQL/Python execution. Never attributed to the model. |
| `unallocated_ms` | `service − provider − creditprobe`, floored at 0 | Derived | Covers context build, the Finalizer, persistence and clock granularity. |
| `load_ms` | Model load / residency | Adapter, when exposed | `UNAVAILABLE` on the non-streaming Anthropic route and for fixtures. Ollama-native reports `load_duration`. |
| `first_protocol_event_ms`, `first_visible_text_ms`, `first_complete_tool_ms` | Request sent → first stream event / first answer text / assembled tool call | Streaming adapter | `UNAVAILABLE` on the frozen non-streaming Opus route (OG-05). |

## Tokens

| Metric | Definition |
|---|---|
| `input_tokens`, `output_tokens` | Sum over unique calls of the native usage. On OpenAI-compatible routes, cached prompt tokens are subtracted from input and reported as `cache_read`, so they are never counted twice. Fixture counters are `ESTIMATED` (bytes ÷ 4) and labelled as such. |
| `peak_context_tokens` | The largest single-call input. Not a sum. |
| `reasoning_tokens` | `UNAVAILABLE`: nothing separates them (OG-06). |
| `tokenizer` | The provider-native tokenizer. Token counts from different tokenizers are not comparable. |
| `client_observed_output_rate` | Output tokens ÷ client-observed call seconds. This includes prompt processing and transport. |
| `server_generation_rate` | `eval_count` ÷ `eval_duration`. Only reported when the runtime exposes them (Ollama native). |

## Cost

| Metric | Definition |
|---|---|
| `cost_usd` (Opus) | Settled usage × the frozen verified price card dated 2026-09-21. `MEASURED`. |
| `cost_usd` (local) | The local marginal token charge, which is 0. `ESTIMATED`, with the basis stated. |
| `cost_usd` (fixture) | 0. `DERIVED`, labelled "no inference". |
| `infrastructure_cost_usd` | `UNAVAILABLE` until an allocation is configured. Local inference is never "free". |

## Resources

`resource.samples` records, per child:
- the lab process RSS and system available memory, with the method and sampling interval;
- model-runtime memory as `null`, with its reason, until an adapter reports it;
- GPU as `null`, with its reason.

On Apple silicon, memory is unified and is never added up as CPU RAM plus GPU VRAM.

## Statistics

`sample_summary` reports:
- `n`;
- the number of unique tasks;
- median, minimum and maximum.

p95 is withheld (`INSUFFICIENT_SAMPLE`) below 20 observations. Repeats are not counted as distinct tasks.

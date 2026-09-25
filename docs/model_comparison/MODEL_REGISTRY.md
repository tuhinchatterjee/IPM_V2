# Model registry and provider capabilities

Profiles live in `profiles/*.json` and presets in `profiles/presets.json`. Readiness is computed by `registry.readiness()` from four inputs:
- the credential **name** being present;
- approvals;
- probe results (`<runtime>/probes.json`);
- the declared status.

Readiness is never more optimistic than those inputs allow.

Identities for the open-weight models come from master prompt v2.1 [R1]–[R8]. **They were not re-fetched from the model cards in this session.** Licence and provenance are marked `UNVERIFIED` until someone reads the card and pins an artifact digest.

## Registry at handover (this cloud host)

| Profile | Registry id | Route | Readiness here | Why |
|---|---|---|---|---|
| `opus-frozen` | `claude-opus-5` (from the frozen price card) | Frozen `AnthropicProvider`, non-streaming | NEEDS_APPROVAL | No `COCKPIT_ANTHROPIC_API_KEY`; `opus_spend` not granted |
| `qwen3.5-9b` | Qwen/Qwen3.5-9B (tag `qwen3.5:9b`) | OpenAI-compatible (Ollama /v1) | NOT_INSTALLED | No runtime; probe not run |
| `qwen3.5-4b` | Qwen/Qwen3.5-4B | OpenAI-compatible | NOT_INSTALLED | Same |
| `granite-4.2-8b` | ibm-granite/granite-4.2-8b | OpenAI-compatible | NOT_INSTALLED | Same; parser/template must be qualified |
| `ministral-3-8b` | mistralai/Ministral-3-8B-Instruct-2512 | OpenAI-compatible | NOT_INSTALLED | Same |
| `fin-r1-7b` | SUFE-AIFLM-Lab/Fin-R1 | — | DISABLED | Backlog; diagnostic-only until the mandatory controls pass |
| `gpt-oss-20b` | openai/gpt-oss-20b | — | DISABLED | Optional; full Mac + Cockpit fit unproven |
| `gemma-4-12b` | google/gemma-4-12B-it | — | DISABLED | Optional; the compressed variant must be registered separately |
| `qwen3.8-27b-remote` | Qwen/Qwen3.8-27B | Remote https | DISABLED | Remote only, after approval |
| `fixture-*` (7 profiles) | `lab/fixture-*` | In-process | READY_E2E (FIXTURE) | Scripted demonstrations, not models |

Kimi and the other backlog names are **not registered**; each needs a verified exact checkpoint first.

## Mandatory controls, and how they are proven

The frozen engine relies on four controls:
- tool calls;
- forced / named tool use;
- tool-result round trip with id pairing;
- a stop-reason mapping onto `tool_use` / `end_turn` / `max_tokens`.

`scripts/model_lab/probe.py` proves them with the dummy tool `probe_echo` and also records the served model id. If the requested and resolved ids differ, the profile is `INCOMPATIBLE_PROTOCOL`.

## Route notes

| Route | Notes |
|---|---|
| **Ollama /v1 (OpenAI-compatible)** | `tool_choice` is sent; whether it is *enforced* is what the probe tests. Streamed tool calls are assembled before dispatch. |
| **Ollama native `/api/chat`** | Has native counters and nanosecond timings, but **no `tool_choice`**. Forced tool use is not enforced on this route, and that is recorded in the translation notes. Use it only for diagnostics unless probes pass. |
| **vLLM / RunPod-style** | The same adapter. The parser for each model family must be qualified by the probe. |
| **Effort and thinking controls** | Not sent to candidates (`effort_control: false`). An accepted-but-ignored field is not treated as enforcement. |
| **Tuning / quantisation / reasoning variants** | Each is a **new profile** with `parent_profile_id`. Baseline profiles are immutable, and every child pins `profile_digest`. |

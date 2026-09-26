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
| `qwen3.5-4b-nothink` | Qwen/Qwen3.5-4B (tag `qwen3.5:4b`, digest prefix `2a654d98e6fb`) | OpenAI-compatible, request control `reasoning_effort: "none"` | NOT_INSTALLED | Runtime reasoning variant of `qwen3.5-4b` (`parent_profile_id`); probe not run here |
| `qwen3.5-4b-nothink-longrun` | Same model, tag, digest prefix and `reasoning_effort: "none"` as `qwen3.5-4b-nothink` | OpenAI-compatible; **LONG-RUN HARDWARE/QUALITY DIAGNOSTIC — SLA NOT COMPARABLE** | NOT_INSTALLED | 900 s calls, 3,600 s run, in an isolated child process; runs only in `LONG_RUN_DIAGNOSTIC` mode |
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
| **Effort and thinking controls** | Not sent to candidates by default (`effort_control: false`). An accepted-but-ignored field is not treated as enforcement. The one exception is an explicit per-profile `request_controls` (below). |
| **Tuning / quantisation / reasoning variants** | Each is a **new profile** with `parent_profile_id`. Baseline profiles are immutable, and every child pins `profile_digest`. |

## Request controls (opt-in, per profile)

A profile may carry `request_controls`, for example `{"reasoning_effort": "none"}`. The rules:

- **Absent by default.** With no `request_controls`, the adapter's request is byte-identical to the pre-control adapter (`tests/model_lab/test_request_controls.py` compares against commit `8b0d422`). Every existing profile is unaffected.
- **Allowlisted per route** (`SUPPORTED_REQUEST_CONTROLS` in `adapters/openai_compat.py`). Currently only `reasoning_effort` ∈ {`none`, `low`, `medium`, `high`} on `openai_compat`. `ollama_native` and `anthropic` accept none.
- **Explicit failure.** An unknown key, an unsupported value or an unsupported route is refused at profile load (`RegistryError`) and again at adapter construction; a child whose profile carries one is BLOCKED with the reason and never runs without the control.
- **Sent only when configured**, as a top-level body field, with the translation note `request control applied: key=value`. Tools, `tool_choice`, messages and `max_tokens` are unchanged.
- **Proven by the probe.** A profile with controls also needs `request_controls_accepted` (the controlled forced-tool request was not refused and returned the tool call). A profile with `artifact.expected_digest_prefix` also needs the served digest (Ollama `/api/tags`) to match.
- **Recorded as evidence.** Observer spans, call rows and export rows carry `request_controls` and `reasoning_chars` (length of any reasoning text the server streamed; observed only, never added to the answer). Each child carries `request_controls`, `parent_profile_id` and `reasoning_variant` (`reasoning_effort=none`, or `runtime-default (no reasoning control sent)` for an OpenAI-compatible profile with none).
- **A variant is a separate profile.** The parent profile file is never edited; its runs stay separate evidence.

## Long-run diagnostic limits (operator-authorised, isolated process)

The frozen engine takes its time limits from module constants in `backend/cockpit_v4/config.py` (`STANDARD_LIMITS`, `DEEP_LIMITS`, `ANALYTICAL_*_LIMITS`), read by `envelope.limits_for_family` when `Worker.execute` builds its `Ledger`. No Runtime, config or environment seam changes them. For the long-run diagnostic only, the operator authorised an in-memory override. The rules:

- **Profile field `diagnostic_limits`**, allowlisted to `deadline_seconds` ≤ 3600, `action_call_seconds` ≤ 900 and `answer_call_seconds` ≤ 900. Values must be finite and positive; anything else is refused at load. Such a profile must also set `sla_comparable: false` and `diagnostic_label: "LONG-RUN HARDWARE/QUALITY DIAGNOSTIC — SLA NOT COMPARABLE"`.
- **Separate process.** The coordinator runs such a child with `python -m backend.model_lab.diagnostic_child`, which calls the same `Coordinator._run_child` path. The override (`backend/model_lab/diagnostic_limits.py`) refuses to run unless that process was armed as a diagnostic child. It replaces only the three time fields on the four limit families and restores them in `finally`; then the process exits. The lab server's frozen values are never replaced.
- **Mode separation.** Diagnostic profiles run only in execution mode `LONG_RUN_DIAGNOSTIC`, and `E2E_BASELINE` refuses them.
- **Evidence.** Each diagnostic child records the frozen policy (from the lab server), the effective policy (from the child process), both process ids, the policy after restore, the frozen engine's own "Allowance" events and each call's `call_timeout_seconds`. The UI, export and HTML report carry the label.
- **Reference baseline.** A comparison may name `reference_comparison_id`. Its saved evaluation is read, never rewritten, and each child gets `reference_match` against the saved comparator (agreement only, never latency).


# Observability gaps and protected-core constraints

Each entry names:
- the exact file and function;
- the invariant it protects;
- what that means for the comparison;
- what the lab does instead.

None of these was fixed by editing the frozen engine.

| ID | Where | Gap / constraint | Effect | Lab handling |
|---|---|---|---|---|
| OG-01 | `envelope.for_request` → `config.STANDARD_LIMITS` / `DEEP_LIMITS` (`config.py:179-247`) + `supervisor.Supervisor` | Deadlines and per-call timeouts are module constants: 30 s per action call, 55 s per answer call, 60–240 s per run. There is no per-run injection. | A slow local model (a 9B model on a Mac CPU/GPU) will likely hit `DEADLINE_EXPIRED` or a call-window timeout. This is a **resource/profile** outcome, not a reasoning failure. | The failure is recorded as `RESOURCE_OR_CONTEXT` with the observed per-call latency. Deadlines are never widened. Widening them would change the frozen engine's governance and needs explicit approval, as a separately named profile variant. |
| OG-02 | `contracts/finalize_response.schema.json` vs `contracts.DISPOSITIONS` (`contracts.py:56`) | The wire schema's disposition enum is `answer, partial, referral, clarification, unsupported`. The parser accepts `partial_answer` and `safe_failure` but **not** `partial`. | A model that strictly follows the schema and sends `partial` is rejected. A grammar-constrained runtime makes this more likely. | Recorded as a **frozen baseline defect** (category `BASELINE_OR_INFRASTRUCTURE`). The adapter does not rewrite `partial`, because that would be an adapter-authored analytical edit. The evaluator attributes this specific rejection to the baseline. |
| OG-03 | `provider._classify`, `Analyst._PARAM_REFUSED` (`provider.py:315`) | Error classification matches Anthropic's error wording. | Errors from another provider could be misclassified. | Lab adapters raise typed `ProviderFailure(code, …)`, which `_classify` passes through unchanged. |
| OG-04 | `Analyst.count_input` + `Ledger.spend_provider_attempt` | A token-count call spends a provider attempt. | Opus can use fewer generations than the "12" limit suggests. | Candidate profiles set `supports_token_counting=False`, so the frozen local estimate is used. The resulting difference in attempt accounting is disclosed on each child. |
| OG-05 | `anthropic_provider.converse` (non-streaming) | There is no stream, so no "first protocol event" or "first visible text" exists for Opus. | M02's first-output metrics are `UNAVAILABLE` for the Opus route. | Measured only where an adapter streams. Otherwise `UNAVAILABLE` with the reason `non-streaming frozen route`. |
| OG-06 | No thinking blocks requested | No reasoning tokens or text. | `reasoning_tokens` is `UNAVAILABLE`. | Never estimated. |
| OG-07 | `Emitter.append` (`events.py:214`) | There is no listener or callback registry. | Live observation must come from the provider wrapper or from polling the store. | `ObservingProvider` (passive) plus reading `events` by cursor. |
| OG-08 | `orchestration._guard` | Cancellation is cooperative, between calls. | An in-flight local generation runs to its own timeout. | The child is marked `CANCELLED` after the in-flight call returns. The adapter's HTTP timeout is the call's own window. |
| OG-09 | `routes._STATE` module singleton | One cockpit instance per process. | The lab cannot host two frozen apps in one process. | Children run through `Worker.execute` against a **lab-owned** `RunStore`, not through the app's worker. |
| OG-10 | Model-authored intent (`intent_envelope.for_run`) | The server settles intent before the first call, and the model does not restate it. | S1 "understanding" is visible only through submitted scope and code. | S1 is labelled `NOT_SEPARATELY_OBSERVABLE` wherever it is fused with S2. |
| OG-11 | `seed_release.py` default `--refresh-evidence` | The frozen seeder rewrites tracked `docs/cockpit_v4/evidence/*.json`. | Reseeding dirties protected files. | The lab always passes `--no-evidence`. See the BASELINE_PROVENANCE §7 incident. |

# Live provider validation

**Credential configured:** NO  
**Result:** 0 of 12 steps passed  
**Release:** `demo-20q-v1`, mode `standard`

**No credential is configured, so nothing below ran.** Each step is BLOCKED. It is reported that way rather than substituted: there is no deterministic path in this architecture that could stand in for a model call, and a mock result presented here would be a false claim about a live system.

The credential is read from the environment and nothing else happens to it. It is not printed, not written to the evidence file, not logged and not committed.

| # | Step | Result | What was established |
|---:|---|---|---|
| 1 | provider connectivity | **BLOCKED** | No ANTHROPIC_API_KEY is configured, so this step did not run. It is reported BLOCKED rather than substituted: there is no deterministic path that could stand in for it. |
| 2 | the configured Sonnet model id | **BLOCKED** | No ANTHROPIC_API_KEY is configured, so this step did not run. It is reported BLOCKED rather than substituted: there is no deterministic path that could stand in for it. |
| 3 | the configured Opus model id | **BLOCKED** | No ANTHROPIC_API_KEY is configured, so this step did not run. It is reported BLOCKED rather than substituted: there is no deterministic path that could stand in for it. |
| 4 | provider token counting against those exact models | **BLOCKED** | No ANTHROPIC_API_KEY is configured, so this step did not run. It is reported BLOCKED rather than substituted: there is no deterministic path that could stand in for it. |
| 5 | real Sonnet pass 1 and pass 2 | **BLOCKED** | No ANTHROPIC_API_KEY is configured, so this step did not run. It is reported BLOCKED rather than substituted: there is no deterministic path that could stand in for it. |
| 6 | real Opus functionality routing | **BLOCKED** | No ANTHROPIC_API_KEY is configured, so this step did not run. It is reported BLOCKED rather than substituted: there is no deterministic path that could stand in for it. |
| 7 | real Opus plan and code generation | **BLOCKED** | No ANTHROPIC_API_KEY is configured, so this step did not run. It is reported BLOCKED rather than substituted: there is no deterministic path that could stand in for it. |
| 8 | real SQL execution, and Python where the sandbox is available | **BLOCKED** | No ANTHROPIC_API_KEY is configured, so this step did not run. It is reported BLOCKED rather than substituted: there is no deterministic path that could stand in for it. |
| 9 | a deliberately exercised Opus repair cycle | **BLOCKED** | No ANTHROPIC_API_KEY is configured, so this step did not run. It is reported BLOCKED rather than substituted: there is no deterministic path that could stand in for it. |
| 10 | real Opus sufficiency review | **BLOCKED** | No ANTHROPIC_API_KEY is configured, so this step did not run. It is reported BLOCKED rather than substituted: there is no deterministic path that could stand in for it. |
| 11 | real final answer generation | **BLOCKED** | No ANTHROPIC_API_KEY is configured, so this step did not run. It is reported BLOCKED rather than substituted: there is no deterministic path that could stand in for it. |
| 12 | the final Sonnet rolling-summary update | **BLOCKED** | No ANTHROPIC_API_KEY is configured, so this step did not run. It is reported BLOCKED rather than substituted: there is no deterministic path that could stand in for it. |

## What this does not establish

Answer quality. Whether the model's reading of a twenty-quarter ECL movement is correct is a judgement for a credit person holding it against the data, and a script that scored itself would be marking its own homework. `docs/cockpit_v3/QUESTION_BANK.md` is the material for that review.

Evidence: `docs/cockpit_v3/evidence/live_validation.json`.

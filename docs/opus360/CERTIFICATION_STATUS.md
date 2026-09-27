# Opus360 certification: status of this session

**Result: harness built, proven and dry-run end to end. The live Opus certification (P9–P12) has
not run, because this environment has no spend cap and no Cockpit credential. No paid call was
made.**

## The single blocker

`OPUS360_MAX_USD` is not set in this environment, and `COCKPIT_ANTHROPIC_API_KEY` is absent (it is
not in the environment, and a Keychain does not exist here). Under brief §25, no live call is
allowed. Live preflight stops with:

```
PREFLIGHT BLOCKED: OPUS360_MAX_USD is not set; no paid call will be made
```

**Command to start the live certification on the Mac** (after `CLONE_OPUS360_CERTIFICATION` and
`SETUP_OPUS360`; see RUNBOOK.md):

```bash
cd ~/Desktop/IPM_V2-AdvancedCockpit-Opus360
export OPUS360_MAX_USD=<your cap in USD>
export OPUS360_MAX_HOURS=10          # optional
launchers/START_OPUS360_OVERNIGHT.command
```

The launcher is equivalent to:
`.venv/bin/python scripts/opus360/run_certification.py --suite architecture-v1 --live --sequential --resume --run-calibration --run-core --run-load-test --export`

## Stage status

| Stage | Status | Evidence |
|---|---|---|
| P0 baseline | done: the tag resolves to `245c50e`; the tree is clean | `docs/opus360/BASELINE_PROOF.md` |
| P1 clone and branch | done: branch `claude/opus360-architecture-certification` from `245c50e`; Mac clone launcher | `launchers/CLONE_OPUS360_CERTIFICATION.command` |
| P2 protected manifest | done: 311 files, SHA `637c40b0…` | `config/opus360/protected_manifest.v1.json` |
| P3 execution path | done | `docs/opus360/ACTUAL_EXECUTION_PATH.md`, `STATIC_FINDINGS.md` |
| P4 bank and oracles | done: 250 turns, bank SHA `e7198a69…`; 294 frozen references | `config/opus360/question_bank.v1.yaml` |
| P5–P6 runner, telemetry, evaluators, reports | done | `scripts/opus360/` |
| P7 fixture tests | done: 10 scenarios plus 33 unit tests, 43/43 pass | `artifacts/opus360/fixtures/fixture_validation.json` |
| P8 frozen regression | done: before and after | `artifacts/opus360/regression/` |
| P9–P10 live calibration | **blocked** (no cap, no credential) | calibration verified in the dry run: 11/11 checks |
| P11 live core | **blocked** | dry run: 250/250 turns executed through the real route/worker/validator/executor/finalizer |
| P12 load microtest | **blocked** live | dry run: concurrency 1, 2 and 4 completed; 429 admission refusals observed at 4 |
| P13 export | done for the dry run | `artifacts/opus360/architecture-v1-dry-20260927T222449Z/` |
| P14 final proof | done: `PROTECTED_CORE_UNCHANGED`, 311 files, git diff on protected paths empty | same folder, `metrics.json` |
| P15 reports | generated for the dry run; the live reports are produced by the same code | same folder |

## What the dry run proves, and what it does not

It proves the harness. All 250 planned turns went through the frozen production path:

- route (deadline, envelope, domain pinning), worker, orchestrator, `execute_analysis` validator and
  DuckDB executor, finalizer, store;
- every figure was independently re-derived by the oracles;
- the two domain-switch turns were refused by the route with `409 DOMAIN_PINNED`, as designed, and
  the follow-action conversation answered correctly;
- resume, stop and the fixture gate were all exercised.

It says **nothing about Opus.** The analyst was scripted from the oracle specs, which is why every
turn passes. The dry-run reports state this in their first line.

## Findings already established without a paid call

See `STATIC_FINDINGS.md`. The dry run confirms two of them mechanically:

- **S-05:** 1,168 operator detail records in the dry run carry `[redacted]` token counts.
- **S-09:** the load microtest received 429 `TOO_MANY_RUNS` at concurrency 4, from a single worker
  thread with a per-principal limit of 2.

S-01 (disposition enum mismatch) and S-03 (hidden SDK retries) can only show up with a real model
and a real network. The live run counts them.

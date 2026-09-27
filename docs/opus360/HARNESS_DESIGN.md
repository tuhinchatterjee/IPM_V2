# Opus360 harness design and requirement traceability

## What runs, and what is observed

```
launchers/*.command ──► scripts/opus360/control.py ──► scripts/opus360/run_certification.py
                                                          │
             preflight (tag, protected manifest, bank SHA, release integrity/parity,
             price card, credential, spend cap, fixture-validation gate)
                                                          │
                          backend.cockpit_v4.app.create_app(cfg, provider=ObservingProvider(real), start_workers=True)
                          ── the production process factory: real routes, real Worker + Supervisor threads
                                                          │
             TestClient ─► POST /api/v1/cockpit-v4/runs  ─► route ─► store.accept_run ─► Worker ─► Orchestrator
                           GET  /runs/{id} (poll)            (deadline, envelope, domain pinning, normalisation)
                                                          │
             read-only evidence: RunStore.get_run / events_since / details_for_run / submissions_for_run /
             artifacts / load_messages / thread_turns + SELECT … FROM reservations (read-only SQLite URI)
```

The harness never calls Anthropic directly. Live calls happen only inside the frozen `Analyst.ask`
→ `AnthropicProvider.converse`. The three pass-through observers are described in
`ACTUAL_EXECUTION_PATH.md` §0, and `tests/opus360/test_harness_units.py` proves they return exactly
what they receive.

## Module map

| Module | Responsibility |
|---|---|
| `cert/protected.py` | SHA-256 manifest of 311 protected files (the brief's globs plus the runtime import closure), 3-way verification, refusal to rebuild over drift |
| `cert/engine.py` | boots the frozen app in-process with an isolated runtime directory; POST, poll, read-only evidence collection |
| `cert/observe.py` | `ObservingProvider`, SDK `Messages.create` and `httpx.Client.send` pass-throughs, gzipped request payloads |
| `cert/oracles.py` | independent DuckDB SQL over the governed Parquet files; 10 oracle functions and 16 named custom oracles; independent re-implementation of the release fingerprint |
| `cert/evaluate.py` | behaviour, required-fact matching with distractors, ranking, membership, claim classification, unbound numbers, causal heuristic, leakage, validator replay, root cause |
| `cert/telemetry.py` | tool activity, stage timings, token decomposition |
| `cert/runner.py` | sequential runner, guards, transient-only retries, threads, clarification continuation, domain-switch follow-action, load microtest |
| `cert/ledger.py` | immutable experiment folder, fsync'd append-only records, checksum-verified resume, owner record |
| `cert/metrics.py`, `cert/reports.py` | every CSV/JSONL/XLSX/Markdown output |
| `cert/scripted.py` | dry-run/fixture analyst only: writes oracle SQL and binds claims. **Never used live** |

## Traceability to the brief

| § | Where |
|---|---|
| 1 Baseline | `docs/opus360/BASELINE_PROOF.md`; re-proved in every preflight (`run_certification.preflight`) |
| 2 Independent clone and branch | branch `claude/opus360-architecture-certification` from `245c50e`; `launchers/CLONE_OPUS360_CERTIFICATION.command` for the Mac |
| 3 Protected core | `config/opus360/protected_manifest.v1.json`; verified at every phase start and end and every 25 turns; abort as `INVALID_PROTECTED_CORE_CHANGED` |
| 4 New paths only | `scripts/opus360`, `tests/opus360`, `config/opus360`, `docs/opus360`, `launchers`, `artifacts/opus360` |
| 5 Execution path | `docs/opus360/ACTUAL_EXECUTION_PATH.md` |
| 6 No browser | in-process `TestClient` against the real routes |
| 7 Question bank | `config/opus360/question_bank.v1.yaml` (250 core turns, SHA frozen in `.sha256`); builder `scripts/opus360/build_question_bank.py`; human-readable `docs/opus360/QUESTION_BANK.md` |
| 8 Oracles | `cert/oracles.py`; every reference hashed; the full set is frozen per experiment as `oracle_references.json` (SHA in the manifest) |
| 9 Every model call | `model_calls.csv` (native usage from the adapter result; served model from the SDK; HTTP attempts from httpx) |
| 10 Token decomposition | `telemetry.decompose_call`: byte-share allocation of the native input total, with system/tool blocks provider-counted live (cached by hash, outside the timed window); method stored per call |
| 11 Tool activity | `tool_calls.csv` (order, timestamps, input/result hashes, outcome, validation) |
| 12 SQL/Python | `submissions.csv` (raw payload, SQL, status, failed check, error text, repair link); `artifacts.csv` |
| 13 Timing | `timing_metrics.csv` (mean/median/p50/p75/p90/p95/p99 when n≥100/min/max, overall and by class) |
| 14 Claims | `claims.csv`; counts on every case row |
| 15 First-pass | `first_pass_valid`, `repairs`, `repair_succeeded`, `repair_tokens`, `timings.repair_ms` |
| 16 Paraphrase | `paraphrase_metrics.csv` (INVARIANT / PRESENTATION_ONLY_VARIATION / MATERIAL_ANALYTICAL_VARIATION / FAIL) |
| 17 Threads | `thread_metrics.csv` (continuity, leaks, stale context, token and latency growth per turn) |
| 18 Redundancy | tool sequences, catalogue/artifact counts, repeated SQL digests, count_tokens per generation, static-context tax |
| 19 Failure taxonomy | `evaluate.root_cause` (ordered, evidence-carrying rules) → `failure_analysis.csv` |
| 20 Retry policy | `runner.run_case`: retry only when the primary cause is `PROVIDER_TRANSIENT`, at most 2 retries, each attempt kept in evidence |
| 21 Resume and crash safety | `ledger.Experiment.completed` (checksum-verified), fsync'd JSONL, tolerant of a torn final line, state saved after every turn |
| 22 Sequential | core concurrency is 1; `--sequential` is accepted |
| 23 Load microtest | `runner.run_load` (12 questions at 1, 2 and 4) → `load_test.csv` |
| 24 Credential | the frozen `start.obtain_credential`; environment only; redaction on every writer |
| 25 Spend guard | `OPUS360_MAX_USD` is required live; the guard refuses a turn if spent + $1.50 (the product's per-run ceiling) would exceed the cap; resumable after the cap is raised |
| 26 Wall clock | `OPUS360_MAX_HOURS`; remaining turns are reported as not run and stay resumable |
| 27 Fixture validation | `tests/opus360/test_fixture_scenarios.py` (10 scenarios); `run_fixture_validation.py` writes the gate that live preflight requires, bound to the harness source hash |
| 28 Calibration | `CALIBRATION` (10 cases, 11 turns) → `calibration_verification.json` (11 instrumentation checks; 13 live, adding served-model and HTTP-attempt checks) |
| 29 Auto-continue | the core run starts only if calibration verified; otherwise the run stops |
| 30–31 Outputs | `reports.build` (all files in §30); per-case fields in `case_results.csv/jsonl` |
| 32–35 Metrics, sinks, clusters, severity | `metrics.py`, `reports.py` |
| 36 No auto-fix | nothing in the harness writes to a protected path; `ARCHITECTURE_FINDINGS.md` only recommends |
| 37–38 Freeze readiness, executive summary | generated per experiment |
| 39 Progress | one line per turn; a cumulative block every 25 turns |
| 40 Launchers | `launchers/START_OPUS360_OVERNIGHT.command`, `STATUS_OPUS360.command`, `STOP_OPUS360.command`, `RESUME_OPUS360.command`, `SETUP_OPUS360.command` |
| 42 Pre-run summary | printed by `run_certification.pre_run_summary` before any turn |
| 43 Harness tests | `tests/opus360/` (41 tests); frozen regression parity in `artifacts/opus360/regression/` |
| 44 Final proof | `reports.build` re-verifies the manifest and `git diff` on protected paths and writes the result into every report |

## Definitions

- **Pass (case):** the behaviour is acceptable for the case, AND every required figure is published
  in the final answer (as a claim or a table cell), within rounding, keyed to the right entity and
  period, AND the ranking and membership are correct where required, AND no published claim
  contradicts the oracle, AND no forbidden behaviour, domain leakage or change of numbers in a
  presentation-only turn.
- **Tolerance:** EXACT means ≤1e-9 relative. ROUNDED means ≤0.5% relative, or half a unit at display
  precision (amount 0.005 SAR mn; ratio 0.05 pp; count exact). Unit scales accepted: amounts ×1,
  ×1e-3, ×1e3, ×1e6; ratios as fractions or percent.
- **Wrong period / population / method:** when a required figure is missing, the published cell for
  that entity is checked against oracle-computed distractors: the same metric in another period;
  the unfiltered population (e.g. total EAD instead of Stage 2 EAD); mean-of-ratios instead of
  ratio-of-sums.
- **Supported claim:** a published numeric claim, bound to evidence by the product, whose value
  matches the oracle universe. **Incorrect:** it is keyed to a known entity and to a metric family
  the oracle covers, but matches none of that entity's values. **Unverifiable:** anything else.
  **Unsupported:** a number in the narrative template that is not a `{{claim.x}}` placeholder.
- **Native tokens:** `usage.input_tokens` and `usage.output_tokens` as returned to the adapter. They
  are reconciled per turn against `reservations.usage`, and never replaced by an estimate.
  `UNKNOWN` is written where a value is unavailable; it is never a zero.
- **Static context tax:** estimated (system blocks + tool schema) ÷ native input. **History tax:**
  the thread history section ÷ input. **Tool-result tax:** in-run tool results ÷ input.
- **Repair tokens:** native tokens of calls that started after the first failed submission.
  **Finalization tokens:** native tokens of calls that started after the first artifact containing
  a correct required figure.
- **Provider time:** the wall time of `converse` and `count_tokens` calls seen by the observer.
  **Local deterministic time:** processing time (acceptance → settlement) minus provider time minus
  queue wait.

## Known limits (stated, not hidden)

1. The token decomposition is an estimate. The provider bills the whole request, and bytes are not
   tokens. Live runs provider-count the static blocks (system instruction, static knowledge, tool
   schema), and only the residual is byte-allocated.
2. Causal-language and false-premise checks are keyword heuristics, labelled `HEURISTIC`
   everywhere.
3. Open-ended thread turns (TD02-1/2/3/4) have no required figures. Their claims are checked
   against a universe of every core metric for the relevant dimensions and periods.
4. Root-cause attribution is rule-based. Each failing row carries the evidence line that decided it,
   so a reader can overrule it.
5. Dry-run results measure the harness and the deterministic pipeline, not Opus. Every dry-run
   report says so in its first line.

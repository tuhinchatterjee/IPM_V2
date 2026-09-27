# Opus360 runbook (macOS, overnight)

Measurement only. Nothing here changes the frozen AdvancedCockpit.

## Once

1. **Create the independent clone.** This never uses a worktree of the presentation folder.
   Double-click `launchers/CLONE_OPUS360_CERTIFICATION.command`, or run it from Terminal. It clones
   branch `claude/opus360-architecture-certification` into
   `~/Desktop/IPM_V2-AdvancedCockpit-Opus360` and re-verifies that
   `cockpit-round-h-live-pass-2026-09-23` resolves to `245c50e4…`.

2. **(Recommended) Reuse the approved release bytes** from the presentation clone, read-only:
   ```bash
   export OPUS360_LAKE_SOURCE="/path/to/presentation/IPM_V2/data"
   ```
   With this set, the release fingerprints equal the approved Round H pair exactly. Without it, the
   releases are rebuilt deterministically, and preflight proves content parity against the Round H
   oracle values instead (see BASELINE_PROOF.md §6).

3. **Prepare.** Run `launchers/SETUP_OPUS360.command`. It creates `.venv` (Python 3.12, pinned
   requirements), puts the releases in place, runs the §27 fixture validation (no paid call), and
   runs preflight.

## Every overnight run

```bash
cd ~/Desktop/IPM_V2-AdvancedCockpit-Opus360
export OPUS360_MAX_USD=<hard cap in USD>     # REQUIRED. Nothing paid runs without it.
export OPUS360_MAX_HOURS=10                  # optional wall-clock cap
launchers/START_OPUS360_OVERNIGHT.command
```

The key comes from the frozen launcher's own mechanism, in this order: the
`COCKPIT_ANTHROPIC_API_KEY` environment variable, then the Keychain item
`creditprobe-cockpit-v4`, then a hidden prompt. It is passed to the background process in its
environment only.

START runs, in order:

1. preflight: tag, protected manifest, question-bank SHA, release integrity or parity, price card,
   credential, spend cap, fixture-validation gate;
2. the pre-run summary (no secrets);
3. calibration: 10 cases, 11 turns, live;
4. calibration verification: 13 instrumentation checks live (`calibration_verification.json`);
5. **only if every check passed:** the 250-turn core run, sequential;
6. the load microtest: 12 questions at concurrency 1, 2 and 4, reported separately;
7. export, final protected-core proof, and checksums.

On macOS the process runs under `caffeinate -i -s`, so the Mac does not idle-sleep.

The equivalent single command, without the launcher:

```bash
OPUS360_MAX_USD=<cap> .venv/bin/python scripts/opus360/run_certification.py \
  --suite architecture-v1 --live --sequential --resume \
  --run-calibration --run-core --run-load-test --export
```

| Action | Launcher | What it does |
|---|---|---|
| Status | `launchers/STATUS_OPUS360.command` | completed turns, spend, phase summaries, last log lines |
| Stop | `launchers/STOP_OPUS360.command` | writes `STOP`; the run finishes the current turn and stops. It acts only on the PID in `owner.json`, and only while that PID's start time, command line and working directory still match |
| Resume | `launchers/RESUME_OPUS360.command` | skips every turn whose evidence checksum still verifies and continues with the next |

## Spend

- The product enforces $1.50 per analytical run (`ANALYTICAL_STANDARD_LIMITS`). The certification
  adds an **outer** guard: before every POST, it stops if measured spend plus $1.50 would exceed
  `OPUS360_MAX_USD`.
- Billable turns: 250 core; up to 26 support turns (4 setup, up to 20 clarification replies, 2
  domain-switch follow-ups); 11 calibration; 36 load. That is about 323 in total.
  - Worst-case bound: 323 × $1.50 ≈ **$485**.
  - The calibration's measured cost per turn is the realistic basis for choosing the cap.
- If the cap stops the run, the remaining turns are listed as not run. Raise the cap and run RESUME.

## Outputs

`artifacts/opus360/<experiment_id>/` contains:

- `EXECUTIVE_SUMMARY.md`, `FREEZE_READINESS.md`, `ARCHITECTURE_CERTIFICATION_REPORT.md` and
  `ARCHITECTURE_FINDINGS.md`;
- `opus360_results.xlsx`;
- every CSV and JSONL listed in the brief §30;
- `evidence/<phase>/<case>/attempt-N/` with the run record, events, submissions, artifacts, calls,
  verdict and root cause;
- `calls/*.json.gz`, the exact request payloads.

## Frozen regression parity

```bash
.venv/bin/python scripts/opus360/run_frozen_regression.py --label after \
  --compare artifacts/opus360/regression/before.json
```

The frozen suite writes into five tracked evidence files. The script records which ones, restores
them from the frozen commit, and verifies the protected manifest.

## If something stops

| Message | Meaning | Action |
|---|---|---|
| `PREFLIGHT BLOCKED: OPUS360_MAX_USD is not set` | no cap | export it; nothing was spent |
| `fixture validation has not been run` / `harness changed after fixture validation` | the §27 gate | `.venv/bin/python scripts/opus360/run_fixture_validation.py` |
| `release bytes differ … AND content parity failed` | a release that is neither the approved bytes nor the approved content | set `OPUS360_LAKE_SOURCE`; never proceed on different data |
| `STOP [NOT_RUN_SPEND_CAP]` | the outer cap was reached | raise the cap; RESUME |
| `STOP [INVALID_PROTECTED_CORE_CHANGED]` | a protected file changed | the experiment is invalid; do not resume it; find out what changed |
| `calibration instrumentation FAIL` | a harness defect | fix the certification harness only; re-run calibration |

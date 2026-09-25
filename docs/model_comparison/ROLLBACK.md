# Rollback and clean stop

The lab changes nothing outside its own paths, so a rollback is only needed to remove the lab itself.

## 1. Stop the lab processes

```bash
./launchers/STOP_MODEL_LAB.command
```

This stops only the PIDs recorded under `artifacts/model_comparison/runtime/pids`, each re-verified by start time, command and cwd.

## 2. Prove that the frozen files are untouched

```bash
.venv/bin/python scripts/model_lab/protected_manifest.py --check
```

The expected result is `protected manifest OK: 1775 files match … (245c50e)`.

## 3. Remove lab state (optional)

```bash
rm -rf artifacts/model_comparison/runtime      # comparisons, exports, approvals, probes
```

## 4. Return to the frozen code (optional)

```bash
git checkout cockpit-round-h-live-pass-2026-09-23    # detached at the frozen commit
```

Alternatively, delete the lab clone folder entirely. It shares nothing with the frozen folder.

## Demonstrated in this session

These four steps were run and observed:
- `STOP_MODEL_LAB.command` printed `stopped lab api` and `stopped lab ui`.
- `status.py` then reported "no lab process recorded".
- The manifest check passed after all the test and browser runs.
- No frozen launcher, runtime directory (`~/.creditprobe/cockpit_v4`) or shared daemon was used.

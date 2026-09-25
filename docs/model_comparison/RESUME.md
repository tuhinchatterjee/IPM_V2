# RESUME: model-comparison lab continuation state

A new Claude Code window resumes from this file. It does not need to search the latest What-If app, and must not.

## Pinned facts

| Item | Value |
|---|---|
| Frozen baseline | tag `cockpit-round-h-live-pass-2026-09-23` = `245c50e45786c6e0c866b281f9dd74da17d160b5` (engine `backend/cockpit_v4/`) |
| Lab | a GitHub clone of `tuhinchatterjee/IPM_V2`, branch `claude/amazing-bardeen-gkd63b` (cloud path `/home/user/IPM_V2`; on the Mac, a separate clone folder) |
| Excluded | `claude/advanced-cockpit-whatif-v1`, `claude/what-if-analysis-rebuild`, tag `recovered-sep8-whatif`, and every other checkout |
| Python / Node | lab `.venv` on Python 3.12 (the pins need ≥3.12); `frontend/node_modules` from `npm ci` |
| Data | `seed_domains.py`, then `seed_release.py --release v4-saudi-20q-v1 --no-evidence` |
| Lab runtime | `artifacts/model_comparison/runtime/` (gitignored); logs in `logs/`, PIDs in `pids/` |
| Owned ports | API 8424 and UI 5424 (or the next free port, as the launcher reports) |
| Approvals held | **none**. No paid calls, no downloads, no remote endpoints have been used. |
| Release claim | LAB_IMPLEMENTED. LIVE_COMPARISON_VERIFIED is **blocked**. |

## Gate log

| Gate | State | Evidence |
|---|---|---|
| P0 Source and isolation | DONE; the Mac-folder dirty check is open | `BASELINE_PROVENANCE.md`, `PROTECTED_MANIFEST.json` |
| P1 Call map | DONE | `ACTUAL_CALL_MAP.md`, `TOOL_CONTRACTS.json`, `FOUR_STAGE_CROSSWALK.md`, `OBSERVABILITY_GAPS.md` |
| P2 Observation | DONE | `observe.py`, `test_observer_neutrality.py` |
| P3 Registry / adapters | DONE for fixtures and a mock server; live probes BLOCKED | `registry.py`, `adapters/`, `probe.py`, `MODEL_REGISTRY.md` |
| P4 Coordinator | DONE | `coordinator.py`, `test_coordinator.py` |
| P5 Disclosure UI | DONE | `/cockpit/lab`; browser 14/14 |
| P6 Evaluation | DONE; replay not built | `evaluate.py`, `oracle.py`, `EVALUATION_RUBRIC.md` |
| P7 Export / persistence | DONE | `export.py`, `store.py`, `api.py` |
| P8 Acceptance | DONE: 86 PASS, 1 BLOCKED, 7 NOT RUN, 2 N/A | `ACCEPTANCE_LEDGER.md` |
| P9 Live UAT | **BLOCKED** (no key, runtime, GPU or approvals) | `LIVE_UAT_REPORT.md` |
| P10 Handover | DONE | `README.md`, `ROLLBACK.md`, `LIMITATIONS.md` |

## Open decisions for the user

1. **Confirm the frozen folder.** On the Mac, confirm that `IPM_V2-AdvancedCockpitv1` is at 245c50e and clean (`BASELINE_PROVENANCE.md` §5).
2. **Approve paid runs.** Approve an `opus_spend` cap. Approve the local model downloads, which you run yourself.
3. **Decide on the deadline constraint (OG-01).** Choose whether a longer-deadline variant may be created as a separately named profile. The alternative is accepting local-model timeouts as a resource finding.
4. **Add oracles.** Supply or approve independent oracles for journeys J01–J06 and J09.

## Next safe commands

```bash
.venv/bin/python scripts/model_lab/protected_manifest.py --check
.venv/bin/python -m pytest tests/model_lab -q -o addopts=
./launchers/START_MODEL_LAB.command            # then open http://127.0.0.1:5424/cockpit/lab
```

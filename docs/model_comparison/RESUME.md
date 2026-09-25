# RESUME: model-comparison lab continuation state

A new Claude Code window resumes from this file. It never needs to search the latest What-If app.

| Item | Value |
|---|---|
| Frozen baseline | tag `cockpit-round-h-live-pass-2026-09-23` = `245c50e45786c6e0c866b281f9dd74da17d160b5` |
| Lab | a GitHub clone of `tuhinchatterjee/IPM_V2`, branch `claude/amazing-bardeen-gkd63b` (cloud session path `/home/user/IPM_V2`) |
| Excluded | `claude/advanced-cockpit-whatif-v1`, `claude/what-if-analysis-rebuild`, tag `recovered-sep8-whatif`, and every other checkout |
| Python | lab `.venv`, 3.12 (`uv venv -p python3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt pytest ruff`) |
| Data | `seed_domains.py` + `seed_release.py --release v4-saudi-20q-v1 --no-evidence`, into the gitignored `data/cockpit_v4*` |
| Lab runtime | `artifacts/model_comparison/` (gitignored contents) |
| Owned ports | API 8424, UI 5424, defaults of the lab launcher |
| Approvals held | none. No paid Opus calls, no downloads, no remote endpoints. |

## Gate log

| Gate | State | Evidence |
|---|---|---|
| P0 source and isolation | DONE (Mac-folder dirty check open) | `BASELINE_PROVENANCE.md`, `PROTECTED_MANIFEST.json` |
| P1 call map | DONE | `ACTUAL_CALL_MAP.md`, `TOOL_CONTRACTS.json`, `FOUR_STAGE_CROSSWALK.md`, `OBSERVABILITY_GAPS.md` |

## Next safe command

```bash
.venv/bin/python scripts/model_lab/protected_manifest.py --check
```

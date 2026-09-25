# Model comparison lab: user guide

**Status: EXPERIMENTAL, LAB_IMPLEMENTED.**
- The lab works end to end with labelled fixtures.
- No real model has been compared yet; see `LIVE_UAT_REPORT.md`.
- The frozen AdvancedCockpit, tag `cockpit-round-h-live-pass-2026-09-23` (`245c50e`), is unchanged.

## What it does

You type one question in the lab's Cockpit page, pick a saved preset and press **Compare models**. For every selected model the lab then:
1. runs that model's own complete investigation through the frozen engine (the same validators, SQL executor, repair loop and answer checks);
2. shows the model's actual answer;
3. places the model's work in a four-stage matrix (S1 understand, S2 plan and author, S3 repair, S4 present), with a separate CreditProbe execution lane;
4. shows time, tokens, cost and repairs, each labelled measured, estimated or unknown;
5. checks the answer against an **independent** reference where one exists, and shows "Opus Match" agreement beside it;
6. diagnoses failures and prepares a downloadable evidence pack.

Models that cannot run stay on screen, each with its exact blocker.

## 1. One-time setup (on the Mac)

```bash
cd ~/Desktop/IPM_V2-AdvancedCockpitv1-QwenLab        # an independent clone, NOT the frozen folder
git fetch origin claude/amazing-bardeen-gkd63b
git checkout claude/amazing-bardeen-gkd63b
uv venv -p python3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt pytest
( cd frontend && npm ci )
.venv/bin/python scripts/cockpit_v4/seed_domains.py                        # synthetic data, lab-local
.venv/bin/python scripts/cockpit_v4/seed_release.py --release v4-saudi-20q-v1 --no-evidence
.venv/bin/python scripts/model_lab/protected_manifest.py --check           # must say OK
.venv/bin/python scripts/model_lab/preflight.py                            # read-only host facts
```

Clone into a new folder so the lab stays independent of the frozen folder. Do not use `git worktree` from the frozen folder.

## 2. Start, open, stop

| Action | Command / URL |
|---|---|
| Start (fixture chat, no key) | `./launchers/START_MODEL_LAB.command` |
| Start with the frozen Opus chat | `COCKPIT_ANTHROPIC_API_KEY=… ./launchers/START_MODEL_LAB.command --live-opus` |
| Open | `http://127.0.0.1:5424/cockpit/lab`; the API is on `http://127.0.0.1:8424` |
| Status | `./launchers/STATUS_MODEL_LAB.command` |
| Stop | `./launchers/STOP_MODEL_LAB.command` |

- **Ports:** 8424/5424. If either is busy, the launcher picks the next free one and says so. It never frees a port.
- **Stop** ends only the processes the lab recorded as its own, checked by start time, command and working directory. It never touches another CreditProbe instance, the frozen launchers or an Ollama daemon.

## 3. Make models ready

Readiness is **proven, not declared**.

| Model | How it becomes ready |
|---|---|
| Opus baseline (`opus-frozen`) | Set `COCKPIT_ANTHROPIC_API_KEY` in the lab server's environment, then grant a capped approval: `.venv/bin/python scripts/model_lab/approve.py grant opus_spend --cap-usd 5`. The comparison's spend cap must cover a $3.00 reserve for each Opus child. |
| Local candidates (Qwen3.5-9B/4B, Granite, Ministral) | Install a runtime and pull the exact model **yourself** (this is outside the lab and needs your approval: large downloads). Then run `.venv/bin/python scripts/model_lab/probe.py --profile qwen3.5-9b`. The probe uses one harmless dummy tool. The model becomes `READY_E2E` only if forced tool use, tool-result round trip, stop mapping and served identity all pass. |
| Remote GPU (RunPod-style) | Set `LAB_REMOTE_OPENAI_URL` (https) and `LAB_REMOTE_API_KEY`, then run `approve.py grant remote_inference --cap-usd N`, then probe. **Compare never provisions GPUs.** |

## 4. Compare

1. Open `/cockpit/lab`. The "Model comparison" section sits above the normal Cockpit, which still works underneath.
2. Choose a preset:
   - *Mac baseline comparison*: Opus plus Qwen 9B and Qwen 4B;
   - *Extended shortlist*;
   - *Remote Parallel UAT*;
   - *Fixture demonstration* (scripted fixtures through the real engine, no models).

   Tick or untick models. Each chip shows its readiness.
3. Type the question once and press **Compare models**. A preflight runs first. It makes no inference and spends nothing, and it shows what is ready, what is blocked and why, and the spend reserve. Only eligible, authorised children run. On the Mac preset they run one at a time.
4. Read the results:
   - **Overview:** one row per model. Hover over or tab to a metric to see its definition, unit, status and source.
   - **Answers:** the comparator is pinned on the left, and you choose which two candidates sit next to it. Tick **Blind labels** for reviews.
   - **Four stages:** click any cell to open the exact calls, checks, repair chain, claim ledger, the Opus Match vs verified table, and the diagnosis.
5. **Clarifications:** if a model asks one, a yellow box appears. Tick the model(s) your answer is for, type the answer and press Send. Only the ticked investigations resume.
6. **Download comparison pack:** a ZIP containing `README.html`, `manifest.json`, the CSVs, `comparison.xlsx`, the answers, the submitted code, `events.jsonl` and checksums. It is also saved under `artifacts/model_comparison/runtime/exports/`.
7. **Saved comparisons:** reopen any earlier group. Reopening never calls a model.

**Reviews.** In a claim card, click Confirm, Mark supported or Mark unsupported, then give a reason. The lab writes a new evaluation revision and keeps the old one.

## 5. Rerun and variants

- Press Compare again. The new comparison gets a new id; the old one is never overwritten.
- A changed prompt, runtime, quantisation or context is a **new profile file** in `profiles/` with `parent_profile_id`. Never edit an existing profile.

## 6. Where things are

| What | Where |
|---|---|
| Lab code | `backend/model_lab/`, `frontend/src/components/model-lab/`, `frontend/src/app/cockpit/lab/`, `scripts/model_lab/`, `launchers/` |
| Profiles and presets | `profiles/` |
| Lab state (gitignored) | `artifacts/model_comparison/runtime/`: `lab_index.sqlite3`, `lab_runs.sqlite3` (frozen format, lab-owned), `blobs/`, `exports/`, `approvals.json`, `probes.json`, `logs/` |
| Tests | `tests/model_lab/` (offline); `tests/model_lab/browser/model_lab.browser.mjs` (needs the lab running) |

Test commands:

```bash
.venv/bin/python -m pytest tests/model_lab -q -o addopts=
LAB_UI_URL=http://127.0.0.1:5424 node tests/model_lab/browser/model_lab.browser.mjs
.venv/bin/python scripts/model_lab/frozen_regression.py        # frozen suite, restores evidence files
```

## 7. What it will not do

- Install runtimes, download weights or create cloud resources.
- Make paid calls without a capped approval.
- Pick a winner, switch production, train a model, or route between models.
- Edit the frozen engine, or touch the latest What-If version.

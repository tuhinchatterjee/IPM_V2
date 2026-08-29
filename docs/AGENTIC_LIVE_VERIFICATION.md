# Agentic live verification — exact local commands

§41. **None of this was run here.** §0 forbids live Anthropic calls and API
credits in Claude Code, so every command below is for the user's own Windows
Docker environment, where a key exists and spending is a decision somebody
makes deliberately.

## Before anything: the dry run, which spends nothing

```powershell
cd C:\path\to\IPM_V2
.\scripts\verify-live-ai.ps1 -DryRun
```

It reports, without calling anything:

* how many live calls each mode would make;
* which model roles would be used, by role name — never a hard-coded model id;
* the current source SHA and configuration fingerprint;
* the agentic cases each mode would exercise;
* **that no credits were consumed.**

Read that output before running anything below. Each of the remaining modes
spends real money.

## The stack

```powershell
docker compose build
docker compose up -d
docker compose ps
docker compose exec backend alembic upgrade head
```

Health, in the order that isolates a failure:

```powershell
curl http://localhost:8000/api/v1/health
curl http://localhost:3000
curl http://localhost:3000/api/v1/health      # through the front-end proxy
docker compose logs --tail=50 agent-worker
```

The third one matters: a backend that is healthy directly and unreachable
through the proxy is a rewrite problem, and it looks exactly like a backend
outage from the browser.

## Source and image SHA must match

```powershell
git rev-parse HEAD
curl http://localhost:8000/api/v1/health | Select-String source_sha
```

If they differ you are testing an image built from different code, and every
result below is about something other than your working tree.

## Agentic verification

```powershell
.\scripts\verify-live-ai.ps1 -Quick        # a handful of calls
.\scripts\verify-live-ai.ps1 -Critical     # the Tier 1 set
```

What a live agentic run should demonstrate, and what to look for in the
report each mode writes:

| What | Where to look | What is wrong if it differs |
|---|---|---|
| Officer selection | `officer_level`, `selection_reason` on the run | A level with no recorded reason |
| Specialist selection | `specialists` on the run | Specialists with no concept behind them |
| Task DAG | `task_graph` | Fewer tasks than specialists, or a task with no owner |
| Project context | `project_id` on the run and on every sub-analysis | A Project run that read a global object |
| Proactive synthesis | the review run's `synthesis` | Synthesis before deterministic pre-screening |
| Grounding | `figure_grounding` on the assurance record | A figure in the prose tracing to no fact |
| No unauthorised side effect | `agent_approvals`, `agent_events` | An approval with no `decided_by` |

## Browser acceptance, locally

Already runs headless here; on Windows it wants a visible browser:

```powershell
.\.venv\Scripts\python.exe scripts\browser_acceptance.py --start
```

Without `--start` it assumes the stack is already up on ports 8000 and 3000.
It writes `docs/browser_acceptance.json` and exits non-zero on any failure —
and exits **2**, with a message, if Chromium cannot launch. It never reports
success for a run that did not happen.

## What to do if a live run disagrees with this report

Everything in this phase was measured with a deterministic provider. A live
model can select a different officer or a different specialist set for the
same question, and that is the thing the live run is for. Re-run the baseline
harness against the live configuration and compare like with like:

```powershell
.\.venv\Scripts\python.exe scripts\agentic_baseline.py `
    --out docs\LIVE_AGENTIC.md --json docs\live_agentic.json `
    --title "Agentic measurement - live models"
```

Note that `scripts/agentic_baseline.py` currently forbids provider calls
inside every probe. Running it against live models needs
`assert_no_provider_calls` lifted, which is a deliberate one-line change
somebody makes knowingly rather than a flag that could be set by accident.

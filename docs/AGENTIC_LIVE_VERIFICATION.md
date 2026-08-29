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

## The nine modes, and what each one costs

Every mode prints its estimate and asks for confirmation before it spends
anything. The estimates are stated here as well so the decision can be made
before a terminal is open.

| Command | Calls | What it proves |
|---|---|---|
| `-DryRun` | 0 | Configuration, build and eligibility. Nothing is verified. |
| `-FeedbackCritical` | **0** | The accuracy prompt, the feedback event, the learning observation, the candidate pipeline and the raw-feedback guard. |
| `-RegulatoryCritical` | **0** | Circular extraction, as-of retrieval, citations and the five Regulatory Assurance critical gates. |
| `-Quick` | ~13 | One call per active model role, plus the smoke thread. |
| `-FullRouting` | ~14 | The live intent-recognition suite, in full. |
| `-ProjectCritical` | ~18 | The same agentic work inside a Project, with scope isolation. |
| `-AgenticCritical` | ~22 | Officer selection, coordination, and what the specialists actually read. |
| `-Critical` | ~30 | Every acceptance thread, end to end, through the API. |
| `-FullCertification` | ~120 | The full certification run over the sealed holdout. |

### The two free modes

`-FeedbackCritical` and `-RegulatoryCritical` make **no provider call at
all**, and that is not a rounding down. Recording a rating, labelling an
observation, proposing a candidate, extracting a circular and retrieving as
of a date are deterministic operations; no model is asked anything.

Two consequences follow, and both are deliberate:

* **They run without a key.** Eligibility is not checked, because refusing to
  run them because no key is configured would withhold the one verification
  that always works — which is exactly the verification somebody reaches for
  when the key is the thing they are unsure about.
* **They never report LIVE_VERIFIED.** They earn a status of their own,
  `DETERMINISTIC_VERIFIED`, exit 0, and write to their own report file. The
  AI panel's LIVE VERIFIED lamp stays off, because no model ran. A build that
  claimed live verification on the strength of arithmetic would be lying about
  the one thing this whole module exists to tell the truth about.

```powershell
cd C:\path\to\IPM_V2
.\scripts\verify-live-ai.ps1 -FeedbackCritical
.\scripts\verify-live-ai.ps1 -RegulatoryCritical
```

Expected tail, for both:

```
  provider calls    none - this mode is deterministic
    PASS  ...
  report stored     yes
  STATUS            DETERMINISTIC_VERIFIED
  exit code         0
```

### Report files

A run that makes no provider call writes to its own name, so the cheapest
command in the product cannot land on top of — and destroy — the report a
paid run has just written.

```
logs\live_ai_verification_<sha>.json          # -Quick, -Critical, -FullRouting,
                                              # -FullCertification, -AgenticCritical,
                                              # -ProjectCritical
logs\verification_dryrun_<sha>.json
logs\verification_feedbackcritical_<sha>.json
logs\verification_regulatorycritical_<sha>.json
```

Only the first can set the product's LIVE VERIFIED badge, and only while the
commit and the model configuration still match the ones it was made on.

## Agentic verification

```powershell
.\scripts\verify-live-ai.ps1 -Quick             # a handful of calls
.\scripts\verify-live-ai.ps1 -Critical          # the Tier 1 set
.\scripts\verify-live-ai.ps1 -AgenticCritical   # officers, coordination, reads
.\scripts\verify-live-ai.ps1 -ProjectCritical   # the same work inside a Project
```

`-AgenticCritical` drives the same probes as `docs/POST_FINAL_AGENTIC.md`
rather than a separate suite, so what the live run reports and what the
measured baseline reports cannot disagree. Each of its four questions carries
the officer level it must select; a run that answers well at the wrong level
fails, because a badge that does not predict the execution path is decoration.

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

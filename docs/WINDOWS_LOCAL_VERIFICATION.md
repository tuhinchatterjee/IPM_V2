# Windows local verification

Two things cannot be closed from the cloud sandbox where this branch was
built, and this file is the exact sequence for closing them on your laptop:

1. **Docker build and start.** The sandbox has no Docker daemon, and the
   honest options were to weaken the container or networking setup until
   something ran, or to leave it. It was left. Nothing in `docker-compose.yml`
   or the Dockerfiles was relaxed to make a cloud run possible.
2. **Live Sonnet / Opus verification.** No live provider call was made
   anywhere on this branch, and no API credits were spent. Every AI-shaped
   result in the test suite came from a fake provider and a deterministic
   fixture.

Everything else — the full backend suite, ruff, TypeScript, ESLint, the
frontend tests, the migrations, the PowerShell checker, and browser
acceptance across four viewports and four themes — ran in the sandbox and is
green. Those do not need repeating here unless you want to see them.

---

## Before you start

* **Docker Desktop** installed and showing **Running**.
* **PowerShell**. Both Windows PowerShell 5.1 and PowerShell 7 work; the
  scripts are pinned to `Set-StrictMode -Version 2.0` so they behave
  identically on the two.
* If Windows refuses to run a script, allow local scripts once:

  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```

* Open PowerShell **at the repository root** (the folder containing
  `docker-compose.yml`). Every command below is written from there.

```powershell
cd C:\path\to\IPM_V2
git fetch origin claude/vigilant-darwin-eohyi1
git checkout claude/vigilant-darwin-eohyi1
git pull origin claude/vigilant-darwin-eohyi1
```

---

## 1. Docker build and start

### 1a. The one command

```powershell
.\scripts\start-docker.ps1 -Rebuild
```

`-Rebuild` forces a full image build rather than reusing a cached layer,
which is the point of this run: you are verifying that the images *build*,
not just that they start. Add `-Logs` if you want to follow the output:

```powershell
.\scripts\start-docker.ps1 -Rebuild -Logs
```

### 1b. What it should leave running

```powershell
docker compose ps
```

Expect four containers up: `ipm-postgres`, `ipm-backend`, `ipm-frontend`,
`ipm-agent-worker`. (`ipm-pgadmin` is optional and only appears if you
started its profile.)

### 1c. Prove each tier answers

```powershell
# The API is up and reports its build.
Invoke-RestMethod http://localhost:8000/api/v1/health | ConvertTo-Json -Depth 4

# The migrations are at the head this branch expects.
docker compose exec backend alembic current
```

`alembic current` must print **`0027`**. Anything lower means the migration
step did not run; anything higher means you are on a different branch.

```powershell
# The front end serves.
Start-Process http://localhost:3000
```

### 1d. The screens added on this branch

Open each and confirm it renders rather than showing an error boundary:

| URL | What it is |
| --- | --- |
| `http://localhost:3000/ai-studio/brain-center` | Brain Center, including **Merge Lab** |
| `http://localhost:3000/ai-studio/continuous-learning` | Continuous Learning, including the new **Ask about the learning** tab |
| `http://localhost:3000/studio/regulatory-intelligence` | Regulatory Intelligence |
| `http://localhost:3000/ai-studio/feedback-learning` | Feedback & Learning |

These four all passed browser acceptance in the sandbox at 1440×900,
1366×768, 834×1112 and 390×844, and in four themes. What Docker adds is
proof that they do it from a built image rather than a dev server.

### 1e. Stopping

```powershell
.\scripts\stop-docker.ps1
```

### If the build fails

Report the failing step and the last twenty lines of output. Do not work
around it by editing `docker-compose.yml` or a Dockerfile — a build that only
succeeds after the container definition is loosened has not been verified.

---

## 2. Live AI verification

`scripts\verify-live-ai.ps1` is the only thing on this branch that can make a
real provider call. It never reads, prints or logs the value of
`ANTHROPIC_API_KEY` — it checks that the variable is present and stops there.

### 2a. Set the key for this session only

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Setting it on the session rather than the machine means it disappears when
you close the window.

### 2b. Cost nothing first

```powershell
.\scripts\verify-live-ai.ps1 -DryRun
```

`-DryRun` makes **no** call. It prints what every other mode would cost in
calls before you commit to one. Run this first, every time.

### 2c. The free mode added on this branch

```powershell
.\scripts\verify-live-ai.ps1 -BrainImport
```

Zero provider calls by design. The Lift Lab compares recorded scores against
recorded scores, so running a model to decide whether an imported Brain
helped would measure the model rather than the Brain.

### 2d. The modes that do spend

Each prompts for confirmation and reports its own call count. Run them in
this order and stop at the first failure:

```powershell
.\scripts\verify-live-ai.ps1 -Quick               # smallest real check
.\scripts\verify-live-ai.ps1 -Critical            # the critical safety set
.\scripts\verify-live-ai.ps1 -AgenticCritical     # the agentic layer, end to end
.\scripts\verify-live-ai.ps1 -FeedbackCritical    # feedback to governed learning
.\scripts\verify-live-ai.ps1 -RegulatoryCritical  # regulatory ingestion and review
.\scripts\verify-live-ai.ps1 -ProjectCritical     # project-scoped investigation
.\scripts\verify-live-ai.ps1 -FullRouting         # model-role routing
.\scripts\verify-live-ai.ps1 -FullCertification   # the full certification run
```

`-FullCertification` is the expensive one. It is last for that reason.

Add `-Yes` to skip the confirmation prompt in an unattended run, and `-Json`
for machine-readable output:

```powershell
.\scripts\verify-live-ai.ps1 -Quick -Yes -Json
```

### 2e. Before a client demonstration

```powershell
.\scripts\demo-check.ps1
```

Spends nothing. Answers one question: can this machine give the
demonstration right now?

---

## 3. Optional: re-run the sandbox gates locally

All of these are already green on this commit. Repeat them only if you want
to see them on your own machine.

```powershell
# Backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend\ tests\ scripts\ alembic\
.\.venv\Scripts\python.exe scripts\check_decimals.py

# Frontend
cd frontend
npx tsc --noEmit
npx eslint .
npm test
cd ..

# PowerShell script checker
.\.venv\Scripts\python.exe scripts\check_powershell.py

# Browser acceptance (needs a built frontend)
.\.venv\Scripts\python.exe scripts\browser_acceptance.py --start
```

---

## What "verified" means when you are done

Docker is closed when `start-docker.ps1 -Rebuild` completes, `docker compose
ps` shows four containers up, `alembic current` prints `0027`, and the four
screens in 1d render.

Live AI is closed when `-DryRun` runs clean and at least `-Quick` and
`-Critical` pass against a real key. The deeper modes are worth running
before a client demonstration and are not required to call the branch
verified.

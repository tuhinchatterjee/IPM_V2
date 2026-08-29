# Client demo runbook — Windows + Docker

Everything a presenter needs, in the order they need it. Times are wall-clock
on a laptop with the images already built.

**None of the Docker or live-verification steps below were run in Claude Code.**
That sandbox has no Docker daemon and no Anthropic key. `docker compose config
-q` is the only Docker command that was executed, and it passes.

---

## The evening before

```powershell
cd C:\path\to\IPM_V2
git rev-parse HEAD
.\scripts\demo-start.ps1 -Rebuild -Reset
.\scripts\demo-check.ps1
.\scripts\demo-backup.ps1
```

Then, if you want the AI panel to show LIVE VERIFIED tomorrow:

```powershell
.\scripts\verify-live-ai.ps1 -DryRun
.\scripts\verify-live-ai.ps1 -Quick
```

Rehearse the demo script once end to end. Then:

```powershell
.\scripts\demo-reset.ps1
```

so the morning starts from the same place the rehearsal did.

---

## The morning of — five minutes

```powershell
cd C:\path\to\IPM_V2
.\scripts\demo-start.ps1
```

It brings the stack up, waits for health, applies migrations, checks the demo
workspace, warms the deterministic paths, runs the pre-flight, prints the
sign-in accounts, and opens the browser **only if the pre-flight said GO**.

If it says `DEMO CHECK: NO-GO`, every blocker is printed with what to do. Do
not present past a NO-GO.

---

## The sign-in accounts

Demonstration passwords on synthetic data. Not secrets, and not to be reused
anywhere.

| Role | Username | Password | Lands on |
|---|---|---|---|
| Administrator | `alex.rahman` | `creditprobe-demo` | Cockpit, full navigation |
| Data Steward | `sara.qahtani` | `creditprobe-demo` | Cockpit, plus Data Builder and the Studios |
| Analyst | `omar.nasser` | `creditprobe-demo` | Cockpit; also the workflow reviewer |
| Viewer | `layla.haddad` | `creditprobe-demo` | Cockpit, read-only |

Present as **Administrator** unless showing permissions. `omar.nasser` is the
recipient of the seeded workflow item, so sign in as them to show a review
arriving.

---

## The two modes

Both are in `.env` and both reach the container.

```
CREDITPROBE_DEMO_MODE=true
DEMO_SAFE_MODE=true
```

**Demo Mode** says this deployment is a demonstration: every screen carries
`DEMO - SYNTHETIC DATA`, the data is pinned to `creditprobe-demo-2026Q2`,
agent schedules do not fire on their own, nothing is sent outside the host,
nothing publishes or certifies automatically, and destructive actions ask.

**Demo Safe Mode** says refuse to show an answer that cannot be validated:
ambiguity is clarified rather than guessed, every displayed figure passes its
invariants, and a failed validation blocks the answer instead of caveating it.

They are independent. A pilot on real client data wants the second and must
not have the first — labelling a client's own portfolio synthetic is the one
mistake Demo Mode can make.

---

## The verification order

Run in this order. Stop at the first FAIL.

| # | Command | Cost |
|---|---|---|
| 1 | `.\scripts\demo-check.ps1` | free |
| 2 | `docker compose up -d` (done by demo-start) | free |
| 3 | `.\scripts\verify-live-ai.ps1 -DryRun` | free |
| 4 | `.\scripts\verify-live-ai.ps1 -FeedbackCritical` | **free** |
| 5 | `.\scripts\verify-live-ai.ps1 -RegulatoryCritical` | **free** |
| 6 | `.\scripts\verify-live-ai.ps1 -Quick` | ~13 calls |
| 7 | `.\scripts\verify-live-ai.ps1 -Critical` | ~30 calls |
| 8 | `.\scripts\verify-live-ai.ps1 -AgenticCritical` | ~22 calls |
| 9 | `.\scripts\verify-live-ai.ps1 -ProjectCritical` | ~18 calls |
| 10 | browser demo acceptance | free |
| 11 | the two workbook downloads, by hand | free |
| 12 | `.\scripts\demo-reset.ps1` | free |
| 13 | final GO / NO-GO | free |

Run `-Quick` before any other paid mode. It is the cheapest way to find out
that the key, the roles or the network are wrong, and finding that out during
a 120-call certification run is an expensive way to learn it.

**Do not run `-FullCertification` on the morning of.** 120 calls, and nothing
in the demonstration depends on it.

---

## During the demonstration

Follow `docs/CLIENT_DEMO_SCRIPT.md`. Keep this open beside it.

### If a question is slow

The officer working indicator shows real stages. Say what it is doing — "it is
selecting the specialists and planning the decomposition" — and let it finish.
Do not refresh: the answer is coming and a refresh loses the thread.

### If a question fails

Do not retry the same sentence. Move to the fallback in the script, then come
back to it. §28's provider failure plan applies:

* **A deterministic question still works with no provider at all.** "What
  ratings data do you have?" and "What is total EAD by sector?" run on the
  engine. If the model is unavailable, demonstrate those and say plainly that
  the language layer is not reachable.
* CreditProbe will say when live AI is unavailable rather than answering
  anyway. If it says so, believe it and say so.
* Provider status is on the AI panel, for an Admin.

### If the demonstration must be restarted

```powershell
.\scripts\demo-reset.ps1 -Yes
```

Ninety seconds, and the workspace is exactly where it started.

---

## After

```powershell
.\scripts\demo-stop.ps1
```

Nothing is deleted. To wipe and start clean for the next client:

```powershell
.\scripts\demo-reset.ps1 -IncludeUsers
```

---

## Restoring from the backup

`scripts\demo-backup.ps1` writes `backups\demo-<timestamp>\` containing a
`pg_dump`, a manifest and every stored verification report. **No API key, no
.env and no credential is in that folder.** The restore steps are in the
manifest itself:

```powershell
docker compose up -d db
docker compose exec -T db psql -U ipm_app -d postgres -c "DROP DATABASE IF EXISTS ipm;"
docker compose exec -T db psql -U ipm_app -d postgres -c "CREATE DATABASE ipm OWNER ipm_app;"
Get-Content .\creditprobe.sql | docker compose exec -T db psql -U ipm_app -d ipm
docker compose exec -T backend alembic current
.\scripts\demo-check.ps1
```

---

## What is demonstrated at the API rather than on a screen

Regulatory circular knowledge and the teaching-corpus importer have working,
tested APIs and **no screen**. Say that, rather than sending anyone to a page
that does not exist.

```powershell
curl http://localhost:8000/api/v1/regulatory/capability
curl http://localhost:8000/api/v1/regulatory/releases
curl http://localhost:8000/api/v1/teaching-corpus/template
```

`/regulatory/capability` names which extractors are installed — the honest
answer to "can you read our PDFs" before anyone uploads one.

**A regulatory question is refused while no Regulatory Knowledge Release is
active**, and that is worth demonstrating. Ask in the Cockpit:

> What does the circular say about provisioning for Stage 2?

CreditProbe says it answers such questions only from an approved Regulatory
Knowledge Release, that none is active, and that it will not answer from the
analytical data instead. Before this release candidate it ran an IFRS 9
staging analysis and presented the result.

---

## The three sentences to have ready

**"Does it make things up?"** Every figure comes from the governed engine, not
from the model. The model plans and explains; it never calculates. Open the
Trace and show the query.

**"So it learns from us?"** Feedback is evidence, never an automatic change.
Improvement happens through reviewed teaching cases and approved local models,
each gated and reversible. It does not retrain Anthropic's foundation model.

**"How accurate is it?"** Operational Assurance is not accuracy, and the
product never labels it as such. There is no 99.99% claim — see
`docs/DEMO_KNOWN_LIMITATIONS.md`.

# Client testing runbook — Windows + Docker

Everything here runs on the client's own Windows machine with Docker Desktop.
**None of it was run in Claude Code**: the sandbox has no Docker daemon and no
Anthropic key, and §0 forbids live calls and credit spend there. `docker
compose config -q` is the only Docker command that was executed, and it passes.

Times are wall-clock on a laptop with the images already built.

---

## 0. Before you start

```powershell
cd C:\path\to\IPM_V2
git rev-parse HEAD
docker --version
docker compose version
docker compose config -q          # validates the compose file; prints nothing on success
```

Copy `.env.example` to `.env` and fill it in. `.env` is **never** committed and
must not be pasted into a chat, an issue or a pull request. The Anthropic key
is read at run time from `.env` through compose; it is never a build argument
and never enters an image layer.

---

## 1. Bring the stack up

```powershell
docker compose build
docker compose up -d
docker compose ps
```

Four services should be running: `db`, `backend`, `frontend`, `agent-worker`.
`pgadmin` is behind a profile and only starts with
`docker compose --profile tools up -d`.

### Migrations

```powershell
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```

Head is **0023**. `alembic current` before and after is worth the two extra
seconds: it distinguishes "already up to date" from "did not run".

To prove migrations work from an empty database — do this only on a machine
whose data you are willing to lose:

```powershell
docker compose down -v
docker compose up -d db
docker compose exec backend alembic upgrade head
```

### Seed the demo data

```powershell
docker compose exec backend python scripts/build_data_lake.py
docker compose exec backend python scripts/seed_demo_users.py
docker compose exec backend python scripts/seed_relationships.py
docker compose exec backend python scripts/seed_teaching_library.py
```

The test suite truncates `teaching_cases`. If you have just run pytest against
this database, run `seed_teaching_library.py` again before demonstrating
anything that reads the library.

---

## 2. Health, in the order that isolates a failure

```powershell
curl http://localhost:8000/api/v1/health
curl http://localhost:3000
curl http://localhost:3000/api/v1/health      # through the front-end proxy
docker compose logs --tail=50 agent-worker
```

The third matters: a backend that is healthy directly and unreachable through
the proxy is a rewrite problem, and from the browser it looks exactly like a
backend outage.

### Source and image must be the same commit

```powershell
git rev-parse HEAD
curl http://localhost:8000/api/v1/health | Select-String source_sha
```

If they differ you are testing an image built from different code, and every
result below is about something other than your working tree. Rebuild with
`docker compose up -d --build`.

---

## 3. Verification that spends nothing

Run these first. All three are free, and the last two run **without a key**.

```powershell
.\scripts\verify-live-ai.ps1 -DryRun
.\scripts\verify-live-ai.ps1 -FeedbackCritical
.\scripts\verify-live-ai.ps1 -RegulatoryCritical
```

Expect `STATUS DRY_RUN` for the first and `STATUS DETERMINISTIC_VERIFIED` for
the other two, each with exit code 0. `DETERMINISTIC_VERIFIED` is **not** live
verification and will not light the AI panel's LIVE VERIFIED lamp — see
`docs/AGENTIC_LIVE_VERIFICATION.md`.

---

## 4. Verification that spends credit

Each of these makes real Anthropic calls. Each prints its estimate and asks
for confirmation first; `-Yes` skips the prompt, and you should not use it
until you have seen the estimate once.

```powershell
.\scripts\verify-live-ai.ps1 -Quick              # ~15 calls
.\scripts\verify-live-ai.ps1 -AgenticCritical    # ~22 calls
.\scripts\verify-live-ai.ps1 -ProjectCritical    # ~18 calls
.\scripts\verify-live-ai.ps1 -Critical           # ~30 calls
```

Run `-Quick` before any of the others. It is the cheapest way to find out that
the key, the roles or the network are wrong, and finding that out during a
120-call certification run is an expensive way to learn it.

---

## 5. Browser acceptance

```powershell
.\.venv\Scripts\python.exe scripts\browser_acceptance.py --start
```

Twelve screens x three viewports x seven checks. It writes
`docs/browser_acceptance.json`, exits non-zero on any failure, and exits **2**
with a message if Chromium cannot launch. It never reports success for a run
that did not happen.

Without `--start` it assumes the stack is already up on ports 8000 and 3000.

---

## 5a. What the learning layer costs

```powershell
docker compose exec backend python scripts/learning_performance.py
```

Free, offline, no provider call. It prints what each feedback and learning
operation costs and, in one line, how much is added to an answer. On the
container this was measured on, that total was **under 2 ms**, almost all of
it one database write. If the platform database is unreachable it reports the
write as `NOT MEASURED` rather than dropping it from the total.

---

## 6. The client demo, in order

Sign in as an ADMIN. The path below is roughly twenty minutes and shows each
capability on the screen where a user would actually meet it.

### a. The Cockpit answers, and shows its working

1. **Ask:** *"Show IFRS 9 EAD by sector for the latest quarter."*
   A single-dataset analysis. Note the officer badge is **Credit Analyst** —
   the ladder is not decorative, and a simple question does not summon a swarm.
2. Open **Trace**. Walk Lineage → the mathematical query node → Audit.
3. Download the **Results Workbook** and the **Full Calculation Pack**.

### b. Escalation buys more work

4. **Ask:** *"Review the latest portfolio and tell me everything that
   genuinely requires CRO attention."*
   The officer badge is now **Chief Orchestrator**, three or more specialists
   are engaged, and the composed Investigation reports every dataset its
   sub-analyses read. Compare the two Traces side by side.

### c. Assurance, and the invariant gate

5. Open the **Assurance** record on both answers. Coverage, critical checks,
   and no critical `NOT_AVAILABLE`.
6. **Ask** something the business invariants must refuse, and show that the
   answer is blocked with a stated reason rather than shown with a caveat.

### d. Feedback — the new part

7. Under the last answer, use **Was this answer accurate and useful?**
   Answer `PARTLY`. The detail panel opens; pick a category, add a correction.
8. Answer `YES` on another answer. No detail panel — the interface does not
   interrogate a satisfied user.
9. Show **mute this thread** and the `feedback_prompt` preference. The prompt
   is one line, never a modal, and can be turned off.

### e. Governed learning

10. Go to **AI Studio → Feedback & Learning**.
11. **Inbox**: the feedback just given, as evidence.
12. **Candidates**: promote it to a candidate. Walk the nine statuses and point
    out that only `HUMAN_APPROVED` is releasable.
13. **Observations**: every question is here, most of them `UNLABELED`, and an
    unlabelled observation may never be used as teaching truth.
14. **Replay lab**: twelve axes, eight material, `UNMEASURED` never read as
    `UNCHANGED`, and improvements never netted against regressions.
15. **Learning releases**: the five gates. Show that an unmeasured metric does
    not pass — "we did not check" is not "it was fine".
16. **Local models**: the nine auxiliary tasks, each beside the deterministic
    rule it shadows, and the six tasks that are refused by name.
17. **Metrics**: satisfaction and learning effectiveness, both labelled as
    what they are — neither is accuracy.
18. **The guard card**: the static proof that no feedback module can write
    production behaviour, with its one exemption shown rather than hidden.

### f. Regulatory and the corpus — API only in this build

**There is no Regulatory screen.** The circular-knowledge capability and the
teaching-corpus importer are backend and API in this build, and
`backend/proof/matrix.py` records them as `BACKEND_ONLY` rather than as
screens somebody forgot to link. Demonstrate them at the API, and say that is
what they are:

```powershell
curl http://localhost:8000/api/v1/regulatory/capability
curl http://localhost:8000/api/v1/regulatory/review-queue
curl http://localhost:8000/api/v1/regulatory/releases
curl http://localhost:8000/api/v1/teaching-corpus/template
```

19. `/regulatory/capability` names which extractors are installed — the honest
    answer to "can you read our PDFs", before anyone uploads one.
20. `POST /regulatory/ask` returns an answer with its citations and its
    Regulatory Assurance record: the five critical gates, and a refusal when
    no active release stands behind the corpus.
21. `POST /teaching-corpus/preview` reports `ACCEPTED`, `REJECTED`,
    `DUPLICATE` or `CONFLICT` per row and writes nothing. Every case that
    `import` then creates arrives `SME_REVIEW_REQUIRED`.

### g. Projects

22. Open a **Project**, ask the same portfolio question inside it, and show
    that it orchestrates identically while the scope stays inside the Project.

---

## 7. What to say when asked "so it learns from us?"

Yes, and not in the way people usually mean. Say all three:

* Feedback is **evidence**, never an automatic change. Nothing a user clicks
  alters production behaviour, Assurance or any score.
* Improvement happens through **reviewed teaching cases, prompt and routing
  policy, and approved local auxiliary models** — each governed, gated,
  reversible, and requiring a named approver who is not the sole reviewer.
* This does **not** retrain Anthropic's foundation model. No weights are
  changed, and no client data is sent to Anthropic for training.

---

## 8. Shutting down

```powershell
docker compose down                 # keeps the database volume
docker compose down -v              # DESTROYS the database volume
```

Use the first one unless you mean the second.

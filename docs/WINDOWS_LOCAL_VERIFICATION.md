# Windows local verification runbook

Everything this environment could not verify, in the order to run it on a
Windows machine. Each step says what a pass looks like, so a step that runs
and produces nothing cannot be read as a pass.

Two of these are the reason the release status is
`LOCAL_RUNTIME_VERIFICATION_REQUIRED` rather than `RELEASE_CANDIDATE`:
**Docker** and **live AI**. Neither can run in the Claude sandbox — there is
no Docker daemon and no API key, and this session is forbidden from making
live provider calls or consuming credits.

---

## 0. Prerequisites

```powershell
git clone <repo> ; cd IPM_V2
git checkout claude/vigilant-darwin-eohyi1
```

* Python 3.13, Node 20+, Docker Desktop running, PostgreSQL 16 (or use the
  Compose one).
* An Anthropic API key, for step 5 only.

## 1. Fresh-clone setup

```powershell
.\scripts\dev.ps1 setup
```

**Pass looks like:** the script builds all three universes — the credit book,
the retail scorecards and the corporate Borrower 360 — writes
`metadata/catalog.json`, and exits 0. Both `metadata/catalog.json` and
`data/analytics/` are gitignored and generated, so a clone that skips this
step has no catalogue and every import that reads it will fail. That is the
single most likely fresh-clone failure and it is the reason all three builds
are in the setup path.

**Expect:** the corporate build takes about four minutes, of which roughly
three are the sixteen quarters of graph derivation.

## 2. Migrations

```powershell
.venv\Scripts\alembic upgrade head
.venv\Scripts\alembic heads
```

**Pass looks like:** `0029 (head)`, exactly one head, 29 files in
`alembic\versions`.

## 3. The gates

```powershell
.venv\Scripts\python -m ruff check backend tests scripts
.venv\Scripts\python -m pytest tests -q
.venv\Scripts\python scripts\check_decimals.py
.venv\Scripts\python scripts\feature_matrix.py --check
cd frontend ; npx tsc --noEmit ; npx eslint . ; npx next build ; cd ..
```

**Pass looks like:** ruff "All checks passed"; pytest exit 0 with 5,823
collected and **zero** skipped in `tests/corporate` and `tests/api` — a run
where those skip is a run where the lake was not built, and two tests
(`test_the_lake_is_built_and_this_suite_actually_ran`) will FAIL to tell you
so; `check_decimals` reporting 49 allowed and 0 unexplained; `feature_matrix
--check` reporting no drift; the Next build listing `/borrower-360`.

> Do not read "zero lines matched" as a pass. `grep -c "^FAILED"` exits 1
> when nothing matched, which looks like a failure and is not; and a suite
> that skipped everything prints dots too. Read pytest's own exit code and
> its skip count.

## 4. Browser and route verification

```powershell
.venv\Scripts\python scripts\browser_acceptance.py --start
.venv\Scripts\python scripts\route_crawl.py --start
```

**Pass looks like:** "956/956 browser checks passed across 4 viewports and 17
screens" and "153/153 visits passed across 3 roles" with exactly six
permission refusals, each on a route that role has no link to.

If Chromium is unavailable both scripts **exit non-zero with a message**
rather than reporting success. That is deliberate: a browser check that
cannot run is not a browser check that passed.

## 5. Live AI verification — THE STEP THIS SANDBOX CANNOT DO

```powershell
$env:ANTHROPIC_API_KEY = "<your key>"
.\scripts\verify-live-ai.ps1
```

**This is the only step that spends money.** It is also the only evidence
that would justify the status `LIVE_AI_VERIFIED`. Until it has been run and
its output recorded, that status must not be claimed for this build — and it
is not claimed anywhere in this repository.

**Pass looks like:** the script reporting a CONNECTED provider, the model
roles it actually used, and the validation results it stored. A run against
an OFFLINE provider is a run of the fake provider and proves nothing about
the live one.

## 6. Docker — THE OTHER STEP THIS SANDBOX CANNOT DO

```powershell
docker compose build
docker compose up -d
docker compose ps
curl http://localhost:8000/api/v1/health
curl http://localhost:3000
docker compose down
```

**Pass looks like:** every service `healthy` in `docker compose ps`, the
health endpoint returning 200, and the front end serving on 3000.

**Do not** change a Docker security or networking setting to make this pass.
If it fails, the failure is the finding. This repository records Docker as
`NOT VERIFIED IN CLAUDE SANDBOX` and does not claim otherwise.

## 7. The Borrower 360, by hand

With the stack up, open `http://localhost:3000/borrower-360`.

1. **Search** a full trading name. One borrower should resolve. Search
   "Company" alone: nothing should match, and the screen should say why a
   legal-form word identifies nobody.
2. **Search** a shared stem. Several candidates should appear and the screen
   should say none has been chosen for you.
3. **Open** a borrower. Thirteen tabs; every field carries its source dataset
   and its authority; no cell is blank.
4. **Group tab.** Six cards, each with what it answers, what it is computed
   from, and — in its own colour — what it is NOT.
5. **Network tab.** Change the view and the depth. The node and edge counts
   should change, and a deep "Everything" view should say what it truncated.
6. As an **Analyst**, the UBO, Directors and Addresses views should refuse
   with a message saying the view exists and that not being permitted to see
   owners is different from there being none.
7. **Download the pack.** Eighteen sheets. As an Analyst the two people
   sheets should be present and say WITHHELD. As a Viewer the download should
   be refused, with the refusal next to the button.
8. **Data quality tab.** Fifteen checks. At Q2 2026 expect one REJECT (the
   two deliberately planted defective shareholder registers), two FLAGs
   (evidence recency, component concentration) and twelve PASS.

## 8. What to record

For each step: the command, the exit code, and the headline number. A step
that was not run is recorded as not run. A step that failed is recorded as
failed, with its output. Neither is recorded as a pass, and neither is
omitted.

# Client-demo release candidate — phase-start snapshot

**Written before any change in this phase.** Immutable. Everything the
release-candidate work claims to have improved is measured against what is
recorded here.

Taken: 2026-08-29.

---

## 1. Repository

| | |
|---|---|
| Branch | `claude/vigilant-darwin-eohyi1` |
| HEAD | `0458f9650b1ca6ded08b853131e5677cb2e59a48` |
| Expected starting commit | `0458f96` |
| Match | **exact** — HEAD is the expected commit, not a newer one |
| `origin/claude/vigilant-darwin-eohyi1` | `0458f9650b1ca6ded08b853131e5677cb2e59a48` |
| Local/remote | **identical** |
| Working tree | **clean** — `git status --porcelain` empty |

Last three commits:

```
0458f96 Final phase §40-§45, §52-§54: gates, regression, and the final report
ba513a5 Final phase §48: what the feedback and learning layer costs
3479dd1 Final phase §46, §50: the five client-readiness documents
```

## 2. Database

| | |
|---|---|
| Alembic head | **0023** |
| Alembic current | 0023 — at head, no pending migration |
| Newer explained migration | none |

The platform Postgres was **not running** when this phase opened; the sandbox
container had been reclaimed since the previous session. Started with
`pg_ctlcluster 16 main start` before reading anything from it. This is a
sandbox restart, not a defect, and it is recorded because every count below
was taken after it.

## 3. Tests

| | |
|---|---|
| Backend collected | **4,031** |
| Frontend | **265 passed, 0 failed**, 28 suites |

Backend collection was counted by summing `pytest --collect-only -q`; the full
run is deferred to this phase's own quality gates rather than repeated here.

## 4. Docker Compose services

| Service | Profile | Published port |
|---|---|---|
| `db` | default | `127.0.0.1:${POSTGRES_PORT:-5432}` |
| `backend` | default | `${API_PORT:-8000}` |
| `frontend` | default | `${WEB_PORT:-3000}` |
| `agent-worker` | default | none |
| `pgadmin` | `tools` | `127.0.0.1:${PGADMIN_PORT:-5050}` |

Four services start by default; `pgadmin` only with
`docker compose --profile tools up -d`.

## 5. Live-verification modes

Nine, with their pre-stated call estimates:

| Mode | Estimated calls | Spends |
|---|---|---|
| `dryrun` | 0 | free |
| `feedbackcritical` | 0 | **free** |
| `regulatorycritical` | 0 | **free** |
| `quick` | 13 | credit |
| `fullrouting` | 14 | credit |
| `projectcritical` | 18 | credit |
| `agenticcritical` | 22 | credit |
| `critical` | 30 | credit |
| `fullcertification` | 120 | credit |

Statuses: `DRY_RUN`, `LIVE_VERIFIED`, `DETERMINISTIC_VERIFIED`,
`PASSED_NOT_STORED`, `FAILED`, `NOT_ELIGIBLE`.

Stored reports present in `logs/` at phase start:
`verification_dryrun_ecb807f1d81a.json`,
`verification_feedbackcritical_ecb807f1d81a.json` — both from commit
`ecb807f`, therefore **stale** for `0458f96`. Neither is a live verification.

## 6. Schema versions

| Component | Version |
|---|---|
| Feedback event | 1.0.0 |
| Learning observation | 1.0.0 |
| Candidate learning case | 1.0.0 |
| Learning release | 1.0.0 |
| Replay | 1.0.0 |
| Local auxiliary models | 1.0.0 |
| User preference | 1.0.0 |
| Raw-feedback guard | 1.0.0 |
| Regulatory schema | 1.0.0 |
| Regulatory knowledge | 1.0.0 |
| Regulatory release | 1.0.0 |
| Regulatory assurance | 1.0.0 |
| Feature proof matrix | 1.0.0 |
| Live verification | 1.0 |
| Demo Safe Mode | 1.0.0 |

Assurance: **72 signal readers wired** of 95 declared subcomponents.

## 7. Feature proof matrix

71 features across 18 areas: **41 PROVEN, 23 BACKEND_ONLY, 0 THIN, 4 LIMITED,
3 DEFERRED**. 42 exercised by a browser, 12 not. 20 recorded limitations.

Untested and recorded as such: the governed Project Plan, Arabic and RTL,
Shadow Mode.

## 8. Data

The analytical lake holds **20 governed datasets**:

```
borrower_financials      credit_memo_signals    ifrs9_staging          rating_transitions
climate_risk             customer_ratings       macro_saudi            recoveries
collateral_register      facility_delinquency   payment_history        risk_appetite_limits
covenant_tests           facility_limits        pd_model_performance   scenario_definitions
                         facility_profitability portfolio_facility     watchlist_register
                                                                       group_structure
```

## 9. Teaching library

2,528 cases: 2,469 `AUTO_VALIDATED`, 40 `SME_REVIEW_REQUIRED`, 16 `DRAFT`,
3 `RETIRED`. **Zero `HUMAN_APPROVED`. Zero production-retrievable.**

The seed corpus itself is 2,525; the 3 `RETIRED` rows are residue from a test
run that followed the last seed. The demo reset must re-seed to a known state
rather than assume this one.

## 10. Frontend routes present

37 route files. Sidebar navigation is defined once in
`frontend/src/lib/navigation.ts` with a per-item `status` of
`live` / `partial` / `preview` / `planned` and optional role gating.

| Group | Items |
|---|---|
| Home | Cockpit |
| Work | Projects, Investigations, Analyses, Documents |
| Intelligence | Lenses, Early Warning, Playbooks, Stress Testing |
| Build | Analysis Studio, Data Builder |
| Govern | Trace & Lineage, Workflow |
| Admin | Agent Operations*, AI Intelligence Studio*, Users & Teams, Settings |

\* already restricted to `ADMIN` and `DATA_STEWARD`.

Items not carrying `status: "live"` at phase start:

| Item | Status | Declared caveat |
|---|---|---|
| Documents | `preview` | "Placeholder by design" |
| Users & Teams | `preview` | "Demo records" |
| Early Warning | `partial` | "Prototype signal, fitted on synthetic data. Not a validated model." |
| Playbooks | `partial` | "Manual and on-publication triggers run; scheduled ones are not yet wired to a scheduler" |
| Settings | `partial` | — |

There is **no demo-scope classification** at phase start: nothing distinguishes
a screen that must be shown tomorrow from one that must not be.

## 11. Demo modes at phase start

| | State |
|---|---|
| `DEMO_SAFE_MODE` | **Exists.** `backend/release/demo_safe.py`, twelve conditions, three outcomes (`SHOW` / `CLARIFY` / `CONTROLLED_FAILURE`), read from the `AI_DEMO_SAFE_MODE` environment variable, wired into routing, officer selection and the judgment bridge. |
| `DEMO_MODE` | **Does not exist.** No setting, no synthetic label driven by one, no fixed demo data release, no schedule suppression, no repeatable reset. |

## 12. Windows operations scripts at phase start

`app-start.ps1`, `app-stop.ps1`, `backup_db.ps1`, `dev.ps1`,
`start-docker.ps1`, `stop-docker.ps1`, `verify-live-ai.ps1`.

**None of `demo-check.ps1`, `demo-start.ps1`, `demo-stop.ps1`,
`demo-reset.ps1`, `demo-backup.ps1` exists.**

## 13. Known limitations carried in

From `docs/FINAL_PHASE_REPORT.md` §33 and the matrix, unchanged at phase start:

* the governed **Project Plan** (§8 of the previous brief) is not built;
* **Arabic and RTL** are out of scope; `localization_rtl_readiness` reports
  `NOT_AVAILABLE`;
* **Shadow Mode** is not built;
* **regulatory knowledge and the teaching-corpus importer have no screen** —
  API only, recorded `BACKEND_ONLY`;
* `follow_up_quality` asserts scope, not usefulness;
* the export download buttons were **not exercised by a browser**: the sandbox
  cannot accept a file download;
* 23 of 95 assurance subcomponents report `NOT_AVAILABLE`;
* **99.99% accepted-answer precision is not demonstrated and is statistically
  unproven.**

## 14. Deferred gates

| Gate | Why deferred |
|---|---|
| Docker build and run | No Docker daemon in this sandbox. `docker compose config -q` passes; nothing was built or started. |
| Every live-verification mode that spends credit | §0 forbids live calls and credit spend here. |
| Browser download of the two XLSX workbooks | The sandbox browser cannot accept a file download. |
| Windows PowerShell execution | The scripts are checked by `scripts/check_powershell.py` for syntax, parsing and ASCII; they are not executed on a Windows host from here. |

Everything above is what this release-candidate phase starts from.

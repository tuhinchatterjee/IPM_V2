# Client-demo readiness — GO / NO-GO

Branch `claude/vigilant-darwin-eohyi1` · from `0458f96`.

Every result below was produced in the development environment, which has **no
Docker daemon and no Anthropic key**. Gates that need either are marked
LOCAL and carry the exact command. Nothing is marked PASS on the strength of
an assumption.

---

## Verdict

# CONDITIONAL GO — REQUIRES LOCAL CHECKS

Every gate that can be settled here passes. Four cannot be settled here and
must be run on the presenter's machine before the demonstration:

```powershell
.\scripts\demo-start.ps1 -Rebuild -Reset     # 1. the Docker stack
.\scripts\demo-check.ps1                     # 2. must print DEMO CHECK: GO
.\scripts\verify-live-ai.ps1 -Quick          # 3. the live provider (~15 calls)
# 4. click both workbook downloads by hand and open them
```

**If `demo-check.ps1` prints NO-GO, do not present.** Every blocker it finds
is printed with what to do about it.

Three open findings are recorded below. None is on the demonstration path and
none blocks GO; all three are in `docs/DEMO_KNOWN_LIMITATIONS.md`.

---

## The gate table

| Gate | Result | Evidence | Blocker | Owner | Workaround | Status |
|---|---|---|---|---|---|---|
| **BUILD** |
| Branch and commit | PASS | `claude/vigilant-darwin-eohyi1`, from `0458f96` | — | — | — | Closed |
| Working tree clean | PASS | committed and pushed | — | — | — | Closed |
| ruff | PASS | `All checks passed!` | — | — | — | Closed |
| Backend tests | PASS | **4,085 passed, 21 skipped, 0 failed** | — | — | — | Closed |
| Frontend tests | PASS | **265 passed, 0 failed** | — | — | — | Closed |
| TypeScript | PASS | `tsc --noEmit` clean | — | — | — | Closed |
| ESLint | PASS | clean | — | — | — | Closed |
| Next production build | PASS | succeeded | — | — | — | Closed |
| PowerShell compatibility | PASS | 12 scripts, all ok, 5.1 + 7, ASCII | — | — | — | Closed |
| Docker Compose valid | PASS | `docker compose config -q` | — | — | — | Closed |
| Docker stack builds and runs | **LOCAL** | no daemon here | — | Presenter | `.\scripts\demo-start.ps1 -Rebuild` | Open |
| Source/image SHA match | **LOCAL** | checked by `demo-check.ps1` | — | Presenter | rebuild if it differs | Open |
| **DATA** |
| Migrations, current DB | PASS | head **0023** | — | — | — | Closed |
| Migrations, empty DB | PASS | 0018 → 0023 clean, ends at 0023 | — | — | — | Closed |
| 20 governed datasets | PASS | `/api/v1/catalog` reports 20 | — | — | — | Closed |
| Demo workspace is known state | PASS | `demo_state.py --check` finds no residue | — | — | — | Closed |
| No duplicate seeded objects | PASS | 1 Project, 2 Investigations, 3 saved Analyses, 1 Lens, 1 workflow item | — | — | — | Closed |
| Test residue removed | PASS | 47,049 rows and 10 test accounts removed; reset rebuilds | — | — | — | Closed |
| **AI / LIVE PROVIDER** |
| Provider configuration verifiable | PASS | `-DryRun` reports roles and estimates | — | — | — | Closed |
| `-FeedbackCritical` | PASS | `DETERMINISTIC_VERIFIED`, 0 calls | — | — | — | Closed |
| `-RegulatoryCritical` | PASS | `DETERMINISTIC_VERIFIED`, 0 calls | — | — | — | Closed |
| Live modes | **LOCAL** | forbidden here; no credits consumed | — | Presenter | `-Quick` then `-Critical` | Open |
| Stale verification shown as stale | PASS | badge reports STALE on a moved commit | — | — | — | Closed |
| **AGENTIC AI** |
| Officer selection accuracy | PASS | 100% over 15 probes | — | — | — | Closed |
| Officer ladder is material | PASS | verdict MATERIAL, 0 decorative, monotonic | — | — | — | Closed |
| Credit Analyst — metadata/simple | PASS | Q1, Q3, Q4 | — | — | — | Closed |
| Senior Credit Officer — two-domain | PASS | Q6, Q7 | — | — | — | Closed |
| Portfolio Risk Lead — segment | PASS | Q5 | — | — | — | Closed |
| Chief Orchestrator — broad review | PASS | Q9, Q10: 5 specialists, 5 tasks, 4 datasets | — | — | — | Closed |
| No badge without orchestration | PASS | composition record asserted | — | — | — | Closed |
| **COCKPIT** |
| Renders at 3 viewports | PASS | browser acceptance **252/252** | — | — | — | Closed |
| No horizontal overflow | PASS | asserted at 1440, 1366, 834 | — | — | — | Closed |
| No fake progress, no accuracy label | PASS | asserted | — | — | — | Closed |
| Reduced motion respected | PASS | asserted | — | — | — | Closed |
| **PROJECTS** |
| Project opens and holds its contents | PASS | route crawl, ADMIN/ANALYST/VIEWER | — | — | — | Closed |
| Project-only thread stays non-global | PASS | seeded and asserted | — | — | — | Closed |
| Cockpit/Project parity | PASS | `test_a_project_investigation_uses_the_same_architecture` | — | — | — | Closed |
| Project Plan | **NOT BUILT** | recorded, not approximated | — | — | not demonstrated | Open |
| **ANALYSES** |
| Saved Analyses list and open | PASS | 3 seeded, crawled | — | — | — | Closed |
| Analysis detail route | **FINDING 1** | `/analysis/{id}` requests an Assurance record that does not exist for a bare engine run → 404 in console | No | — | off the demo path; the script uses Analyses and Trace | Open |
| **TRACE** |
| Trace opens, all four views | PASS | crawled; asserted in tests | — | — | — | Closed |
| Query, plan, SQL, Copy Query | PASS | covered by tests | — | — | — | Closed |
| Back to source | PASS | return-context tests | — | — | — | Closed |
| **WORKFLOW** |
| Send, receive, comment, approve | PASS | seeded item + `tests/api/test_workspace_api.py` | — | — | — | Closed |
| Notification deep links | PASS | crawled | — | — | — | Closed |
| Role enforcement | PASS | 403 where intended | — | — | — | Closed |
| **RISK CASES** |
| Requires Attention reconciles | PASS | 5 cases: 1 Segment, 4 Borrower, from the real screen | — | — | — | Closed |
| Portfolio and Data filters empty | PASS **and honest** | nothing moved at portfolio level; no dataset missing. Not fabricated | — | — | say so; it is a strong answer | Closed |
| **DATA BUILDER** |
| Domains, datasets, fields, grid | PASS | crawled; 20 datasets, 18 domains | — | — | — | Closed |
| Relationship map | PASS | crawled | — | — | — | Closed |
| **ANALYSIS STUDIO** |
| Method library and certification | PASS | 324 methods, 43 certified | — | — | — | Closed |
| **EXPORTS** |
| Workbook contents and reconciliation | PASS | export tests | — | — | — | Closed |
| Browser download click | **LOCAL** | the sandbox browser cannot accept a download | — | Presenter | click both, open both | Open |
| **FEEDBACK** |
| Prompt, categories, consent | PASS | `-FeedbackCritical`, 24 tests | — | — | — | Closed |
| Raw feedback changes nothing | PASS | static guard reports ok | — | — | — | Closed |
| **REGULATORY / TEACHING** |
| Regulatory question refused with no release | PASS | **defect found and fixed this phase** | — | — | — | Closed |
| Circular ingestion, gates | PASS | `-RegulatoryCritical` | — | — | — | Closed |
| Screens | **API ONLY** | recorded `BACKEND_ONLY` | No | — | demonstrate at the API | Open |
| **SECURITY** |
| No key in logs, reports or exports | PASS | `write()` refuses a key-shaped field | — | — | — | Closed |
| Key never printed by any script | PASS | presence only, by design | — | — | — | Closed |
| Permissions enforced at the API | PASS | 4 intended refusals, each on a route the role has no link to | — | — | — | Closed |
| No autonomous material action | PASS | approval gates asserted | — | — | — | Closed |
| Synthetic label on every screen | PASS | Demo Mode header chip | — | — | — | Closed |
| **PERFORMANCE** |
| Learning layer on the answer path | PASS | under 2 ms added | — | — | — | Closed |
| Deterministic answers | PASS | 190 ms mean, 837 ms p95 over 15 probes | — | — | — | Closed |
| Live answer latency | **LOCAL** | needs a live model | — | Presenter | talk over the stage indicator | Open |
| **BROWSER** |
| Browser acceptance | PASS | **252/252**, 12 screens x 3 viewports x 7 checks | — | — | — | Closed |
| Route and link crawl | PASS | **88/95**, 3 roles, plus 4 intended refusals | — | — | — | Closed |
| Viewer can open every screen they are offered | **FINDING 2** | a Viewer opening the CRO Lens gets 403 on every tile: executing an analysis needs ANALYST | No | — | do not present Lenses as a Viewer | Open |
| **WINDOWS / DOCKER** |
| The five demo scripts | PASS | parse and policy-check for 5.1 and 7 | — | — | — | Closed |
| Executed on Windows | **LOCAL** | not run on a Windows host from here | — | Presenter | run `demo-check.ps1` first | Open |
| **BACKUP / RESET** |
| Backup captures a restorable state | PASS | dump + manifest + reports, no credential | — | — | — | Closed |
| Reset rebuilds a known state | PASS | preview and reset share one code path | — | — | — | Closed |
| Rollback instructions | PASS | in the manifest and the runbook | — | — | — | Closed |

---

## The three open findings

None is on the demonstration path. All three are recorded rather than fixed
late, because §1 freezes scope and §32 says to polish only what affects the
demonstration.

**FINDING 1 — `/analysis/{id}` asks for an Assurance record that cannot exist.**
Opening an analysis definition directly executes it and then requests
`/api/v1/investigations/{run}/assurance`. Assurance records belong to
Investigations, not to bare engine runs, so the request 404s and the console
records it. The page still renders. The demonstration script never opens this
route — it reaches analyses through Analyses and Trace.

**FINDING 2 — a Viewer cannot open a Lens.**
`/lenses` is offered to every role, and each Lens tile executes an analysis,
which requires ANALYST. A Viewer therefore sees the link and gets a dashboard
of refusals. The permission is defensible and the invitation is not — the same
shape as the Users & Teams finding this phase already fixed. Not fixed here
because changing who may execute an analysis is a permissions change, and the
night before a demonstration is the wrong time to make one. **Do not sign in
as a Viewer to show Lenses.**

**FINDING 3 — regulatory knowledge and the corpus importer have no screen.**
Both have working, tested APIs. Building a screen would be new architecture,
which §1 forbids in this phase. The runbook demonstrates them at the API and
says that is what they are.

---

## What this phase found and closed

| Found | Closed |
|---|---|
| A regulatory question answered with an unrelated analysis — verbatim a §3 NO-GO | Yes. `backend/regulatory/intent.py`, wired beside the coverage check |
| Demo Safe Mode read under two names; the documented one enabled half of it | Yes. One reader, both names |
| Neither demo switch reached the container | Yes. Both passed through compose; a test reads the files |
| 47,049 rows of test residue, including 2,079 identical Projects | Yes. Reset and seed |
| Ten test accounts visible to a client | Yes. Removed by name |
| ANALYST and VIEWER offered Users & Teams, then refused by the API | Yes. ADMIN-only |
| A list and its own detail route disagreeing about saved investigations | Yes. The list now requires a stored answer |
| Three tests that passed only on stale database state | Yes. Each creates what it needs |

---

## Sign-off

Nothing above is marked PASS on an assumption. The four LOCAL gates are the
whole of what remains, and `demo-check.ps1` settles three of them in one
command.

**No live Anthropic call was made and no credits were consumed in producing
this report.** No 99.99% accuracy claim is made anywhere in this release.

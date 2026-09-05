# CreditProbe — integration rehearsal report

**Rehearsal only. Nothing here was merged to `main`, and no protected feature
branch was modified.**

---

## A. Latest `main`

| | |
|---|---|
| `origin/main` | `3855f9b` (`3855f9b6f6b231beb6f2193c8a1e219d01596421`) |
| Subject | Merge pull request #1 from tuhinchatterjee/claude/vigilant-darwin-eohyi1 |
| Date | 2026-09-01 |
| Migration head | `0031` (31 migration files) |

**Main is not what its merge message suggests, and this matters.** PR #1 is
titled for the Planner/Lenses branch, but the commit it merged is `b53c79c` —
a snapshot from 2026-09-01, **88 commits behind that branch's own tip**. So
`main` does **not** contain the finished Planner/Lenses work: no Metric
Catalogue, no Lens builder, no chart builder.

Two facts follow, and both were verified rather than assumed:

```
tree(origin/main) == tree(b53c79c) == 2ff06ac3d89c2522854849778a30381b3c7d4a74
git diff b53c79c origin/main   →  0 files changed
```

`b53c79c` is an ancestor of all three feature branches. **`main` therefore
contributes no file content that the feature branch does not already carry.**
That is why the merge below resolved with no conflicting paths — a fact to
check, not a reason to skip checking.

## B. Feature branch HEADs

| Branch | HEAD | Date | Migrations |
|---|---|---|---|
| `claude/vigilant-darwin-eohyi1` (Planner / Lenses) | `d55f625` | 2026-09-04 | 38 |
| `claude/playbook-committee-intelligence` | `c17c426` | 2026-09-04 | 39 |
| `claude/scorecard-validation-intelligence` | `e136b82` | 2026-09-05 | 41 |

Working tree at the start: **clean** (0 porcelain lines). The reported
`e136b82` / `2f26993` were still current.

## C. Ancestry proof

```
git merge-base --is-ancestor <planner>  <playbook>   → exit 0
git merge-base --is-ancestor <playbook> <scorecard>  → exit 0
git merge-base --is-ancestor <planner>  <scorecard>  → exit 0   (transitive)
```

Both required relations hold, so **only the final branch was merged**. Merging
all three separately would replay one history three times and prove nothing
the ancestry has not already settled.

A second ancestry fact shaped the whole rehearsal:

```
git merge-base --is-ancestor origin/main <scorecard>  → exit 1
git merge-base origin/main <scorecard>                → b53c79c
```

`main`'s merge commit is not in the feature branch's history, so this is a
genuine two-parent merge — even though it moves no file.

## D. Integration branch

`claude/integration-rehearsal`, created from `origin/main`, pushed with
upstream set. No prior branch of that name existed, locally or on the remote,
so nothing was overwritten.

## E. Integration HEAD

| | |
|---|---|
| Pre-merge HEAD | `3855f9b` |
| Merge-base | `b53c79c` |
| Merge commit | `e81f913` (parents `3855f9b` `e136b82`) |
| **Final executable HEAD** | **`99fcf1b`** |

`--no-ff`, history preserved. No squash, no rebase, no force-push, no rewrite
of any feature commit.

## F. Conflicts and resolutions

**Zero conflicted files.** `git merge-tree` predicted a clean merge and the
merge delivered one:

```
tree(e81f913) == tree(e136b82) == 3d1b61c73ed3d9362591be86f5cccd059ca86637
git diff e81f913 origin/claude/scorecard-validation-intelligence → empty
```

The merge result is **byte-identical** to the feature branch tree. There were
no resolutions to make, and therefore **no possibility that a resolution
discarded a fix from `main`** — `main` has no content beyond the merge-base.

Delta against latest `main`: **536 files changed, 145,940 insertions, 6,040
deletions.**

## G. Migration reconciliation

`main`'s 31 migrations are **byte-identical blobs** to the integration
branch's first 31. The branch **appends exactly ten** (0032–0041) and
**edits none**.

| Check | Result |
|---|---|
| Main migration head | `0031` |
| Integration migration head | **`0041`** |
| Migration graph | 41 revisions, one root (`0001`), **one head**, no branch points, no duplicate revision ids |
| **A. existing-main database → integrated head** | `0031` (104 tables) → 10 migrations → `0041` (**143 tables**) |
| **B. empty database → integrated head** | 41 migrations → `0041`, **143 tables** |
| **A vs B** | **Identical table sets, and identical column definitions — 2,336 columns, byte-for-byte** |
| **D. downgrade** | `0041 → 0031`: 10 downgrades, back to **exactly** the 104-table main-era schema. Forward again: 2,336 columns identical. Down-and-up is a no-op. |
| **E. unrelated schema change** | **None.** 41 tables added, 2 removed. |

The ten new migrations, in order: 0032 collaboration workspace, 0033 period
releases, 0034 Project Planner, 0035 planner update requests, 0036 AI chat
source, 0037 metric catalogue, 0038 planner demo anchor, 0039 Playbook
committee intelligence, 0040 scorecard validation runs, 0041 SCV reference
period.

**The two removals are the intended retirement**: `playbooks` and
`playbook_runs` are dropped by 0039's upgrade and recreated by its downgrade.
The legacy feature is gone, and reversibly so.

Key tables now present: `planner_*` (10), `playbook_*` (15), `scv_*` (4),
`lenses` / `lens_revisions`, `user_metrics` / `metric_verifications`. The
invariant that matters most survives the round trip: **`scv_results.value`
is still nullable**, so a refused test cannot come back out of the database
as a zero.

## H. Service and Docker startup

Both images rebuilt at the integration HEAD; stack torn down **with its
volume** and started from empty.

| Step | Result |
|---|---|
| `docker compose down -v` | Volume `ipm_pgdata` removed |
| Backend + frontend images rebuilt | Yes, stamped with the integration SHA |
| Postgres, backend, frontend, agent-worker | **All four report `healthy`** |
| `/api/v1/health` | 200, every component `ok` except `ai_provider` (offline — see §S) |
| `/api/v1/readiness` | **`ready: true`, all 15 checks pass** |
| Migrations applied in-container | `alembic current` → `0041 (head)`, 143 tables |
| Demo bootstrap | Completed — 80 governed datasets, 12 accounts, 6 scorecard models, Q2 2026 review with 7 Risk Cases |
| Build stamp | `image_sha == source_sha == e81f913`, **`stale: false`** |
| Worker consumes queue jobs | Yes — `schedule_tick`, `planner_sweep`, `playbook_sweep` all reached `complete`, attempts=1, no `last_error` |
| Frontend reaches backend | Yes — every browser journey below ran against the container |

On the CA workaround: this sandbox's TLS-inspecting proxy blocks PyPI and npm
from inside a Docker build, so the images were built with the
`PYTHON_IMAGE` / `NODE_IMAGE` build arguments both Dockerfiles already carry,
pointing at locally-built bases that trust it. **No trust material is
committed** — no certificate, no `.env`, no absolute path. Note that
`docker compose build` does **not** forward those arguments (compose declares
only `GIT_SHA` and `BUILD_TIMESTAMP`), so the images were built with
`docker build --build-arg` directly.

## I. Project Planner

`scripts/acceptance/planner_journeys.py` against the container:
**43 passed, 0 failed.**

`/delivery`, the portfolio, My Work, demo projects, project detail, task
update and the notification/monitor path all work — **after** the defect in
§R-1 was fixed. Before that fix the Planner was empty and the journeys failed
at sign-in, because the account they use is created by the Planner seed.

Seeded state: 1 project, 6 workstreams, 24 tasks, 5 milestones.

## J. Lenses

`scripts/acceptance/lens_journeys.py` against the container:
**128 passed, 0 failed.**

Covers the shipped lenses, the metric info/formula panel, the picker, the
custom metric catalogue route, the builder, versioning-not-overwriting, the
chart builder, and reconciling a rendered bar back to the parquet
independently. Saved lenses reopen; a rearranged lens is a new version and the
previous arrangement can be restored.

This required the fix in §R-2: the three shipped lenses were absent and the
catalogue was empty.

## K. Playbook

`scripts/playbook_journeys/browser_journeys.py` against the container:
**all 18 browser checks passed.**

* `/playbook` loads; **`/playbooks` (plural) does not exist** — no page file,
  no route, no navigation entry, and migration 0039 drops its tables.
* All three committee packs load and are named on the screen: Retail Credit
  Risk, Corporate Credit, IFRS 9 Impairment.
* Governed percentages render (6.88%, 7.46%, 14.36%, 14.24%, 3.57%, 3.55%) and
  **no figure shows as a bare 0.0%**.
* The working opens and names the metric, the period and a formula hash.
* Signed out, the Playbook is not readable and a sign-in form is what is
  offered.
* No page error, no console error, nothing on screen is unfinished scaffolding.

Seeded state: 3 committees, 6 packs, 22 sections.

## L. Scorecard Validation

`scripts/browser/scorecard-validation-journeys.mjs` against the container:
**39 passed, 0 failed.**

Cockpit, specialist chat, all three scorecards, the burning weaknesses, the
health strip, results with coverage, the four-decimal AUC with its limit and
the limit's source, all ten result states shown by name, the evidence panel,
charts drawn, out-of-domain refusal, injection refusal, and no cache bleed
between scorecards.

Validation History, a persisted run, report studio and DOCX generation are
covered by the integration suite in §M rather than the browser journey.

## M. Cross-feature checks

New, committed, repeatable: **`scripts/acceptance/integration_journeys.py`** —
**41 checks, 0 failing.** It is deliberately not a feature suite. It asks what
a deployment looks like when nobody has prepared it, and whether one feature's
data still reads correctly through another feature's surface.

| Check | Result |
|---|---|
| **Bootstrap covers every shipped feature** | The plan has `lenses`, `planner` and `playbook` steps; `review` is still last; no two steps share a letter |
| **Playbook → Project Planner** | A committee action is sent to the Planner, and **the Planner really holds the task the action names** (task 25 on project 1). The bridge **refuses to link one action twice** — 422, "already linked" |
| **Metric Catalogue → Playbook** | The committee packs declare **20 distinct governed metrics; all 20 still resolve** through the metric service |
| **Metric Catalogue → Scorecard Validation** | The SME champion AUC still reads 0.6547 — the figure the Scorecard Validation branch verified |
| **Scorecard Validation → Word** | A run is persisted, read back unchanged, drafted into a report and rendered to a 19-part OOXML package that **names the run it was built from** |
| **Notifications** | The inbox serves with both features installed; **no two items share an id** |
| **Scheduler** | `planner_sweep` and `playbook_sweep` are **separate job kinds on one queue with one tick source**; no handler serves two kinds |
| **Domain isolation** | See §N and §R-3 |

## N. Numerical spot checks

Every figure below was read from the **integrated** stack and agrees with the
value the feature branch verified.

**Scorecard discrimination — all three models, integration branch:**

| Model | AUC | Gini | KS | n | events |
|---|---|---|---|---|---|
| Retail Application | 0.7062099518 | 0.4124199037 | 0.3037715564 | 342,740 | 20,552 |
| Retail Behaviour | 0.7231484973 | 0.4462969946 | 0.3265563759 | 475,000 | 36,389 |
| Saudi SME | **0.6546977552** | 0.3093955105 | 0.2240685182 | 24,119 | 1,398 |

Observations and events match the Scorecard Validation closure report exactly
(342,740 / 20,552; 475,000 / 36,389; 24,119 / 1,398). The browser journey
independently displayed **0.6547** on the SME champion.

**Retail Risk Lens metrics:** `retail.balance` 207,718,872.71857262 (2025-07);
`retail.default_rate` 6.878947368 (2025-01); `retail.dpd_30_balance`
16.304899473 (2025-07).

**Corporate IFRS 9:** `corporate.ifrs9.stage1_ecl` 1,833.4834 and
`stage1_ead` 103,237.016 (Q2 2026).

**Playbook snapshot vs the governed metric service — same metric, same
period:**

| Metric | Period | Pack | Metric service | \|diff\| |
|---|---|---|---|---|
| corporate.exposure | Q2 2026 | 74,017.555 | 74,017.555 | **0.000e+00** |
| corporate.exposure | Q1 2026 | 74,352.67 | 74,352.67 | **0.000e+00** |
| corporate.facilities | Q1 2026 | 16,346 | 16,346 | **0.000e+00** |
| corporate.facilities | Q2 2026 | 16,346 | 16,346 | **0.000e+00** |
| corporate.ifrs9.coverage | Q1 2026 | 4.176681249 | 4.176681249 | **0.000e+00** |
| corporate.ifrs9.coverage | Q2 2026 | 4.235058487 | 4.235058487 | **0.000e+00** |

**No expected value was changed to make anything agree.**

## O. Full regression

> **PENDING.** The full backend suite is running on the final executable HEAD
> `99fcf1b` as this is committed. Its exact counts — collected, passed,
> skipped, failed, errors, warnings, duration, exit code — and every skip
> reason go here, in the commit that follows. Nothing in this section is
> asserted until they are read.

## P. Frontend and build

| Gate | Result |
|---|---|
| `npx tsc --noEmit` | Clean |
| `npx eslint src` | Clean |
| `npm test` | **541 passed, 0 failed, 0 skipped**, 46 suites |
| `npx next build` | Succeeds; every route emitted |
| `ruff check backend/ tests/ scripts/ alembic/` | Clean |
| `scripts/check_decimals.py` | 92 allowed with a reason, **0 not** |
| `alembic heads` | **Single head, `0041`** |

## Q. Browser journeys

| Suite | Checks | Failed |
|---|---|---|
| Lenses | 128 | 0 |
| Project Planner | 43 | 0 |
| Playbook | 18 | 0 |
| Scorecard Validation | 39 | 0 |
| Integration (new) | 41 | 0 |
| **Total** | **269** | **0** |

All run against the containerised stack with real authentication.

## R. Integration defects found and fixed

Three, all of the same shape: each feature was correct alone and wrong
together, and no feature's own suite could have caught any of them.

### R-1 — Project Planner and Playbook came up empty

**Severity: material.** A user running `docker compose up` — which is how UAT
will start — saw an empty `/delivery` and an empty `/playbook` on a deployment
whose health check was green.

Each branch shipped a seed script (`scripts/seed_planner.py`,
`scripts/seed_playbook_committees.py`) and neither wired a step into
`backend/bootstrap/plan.py`, the only thing `docker/backend-entrypoint.sh`
runs. Both branches verified themselves by running their seed **by hand**
before their journeys, so neither could see it. That module's own docstring
was written about this exact failure — *"Nothing failed. The API came up
healthy and the product was empty"* — and it recurred, on two new features, in
the file that exists to prevent it.

**Fixed:** steps `planner` (N) and `playbook` (O). Both idempotent, both
probing the deployment rather than trusting a marker. Seeded: 1 project, 6
workstreams, 24 tasks, 5 milestones; 3 committees, 6 packs, 22 sections.

### R-2 — the three shipped Lenses were never installed

**Severity: material.** `/lenses` showed one demonstration lens; Retail Risk,
Retail Analytics and Corporate IFRS 9 did not exist.
`backend/metrics/lenses.py::install()` says in its own docstring that it is
*"Called from the demo bootstrap"*. Nothing called it.

**Fixed:** step `lenses` (M). Installs 3 of 3, idempotent on a second run.

### R-3 — the general Cockpit could list and describe every restricted dataset

**Severity: material — a stated boundary did not hold.** Asked *"What datasets
do you have?"*, the product named all seven scorecard-validation datasets with
their row counts and period coverage. Asked to describe one, it did: business
home, grain, field count, row count, period range, authority.

The Scorecard Validation branch gated the two paths that existed in its own
view of the system — planning discovery in `orchestration/context.py` and
execution in `runtime/validation.py`. The metadata service, which the
Planner/Lenses branch consolidated later, is a **third path**, and a second
catalogue-answering module (`orchestration/catalogue_answers.py`) reads it
directly.

**No rows and no figures ever leaked.** What leaked was existence and shape —
which is precisely what "cannot discover" is about.

**Fixed:** both Cockpit answer paths now read through the one declaration the
other two gates already share, `backend.scorecard.domains.restricted_datasets`
— not a second list. A dataset asked for by name gets the product's ordinary
*"There is no governed dataset called …"*, because confirming it exists and
then declining would itself be the disclosure; that matches the reasoning
already recorded for gate 2. The whole `Retail / SME Scorecards` domain —
which holds those seven and nothing else — no longer appears.

**Deliberately not fixed at the catalogue source.** The Data Builder is
entitled to all eighty governed datasets, and filtering in
`metadata/service.py::_build()` would have taken them from the one screen that
should see them. Verified after the fix: Data Builder **80**, readiness
**80 catalogued / 80 registered**, Scorecard Validation module still resolves
all three scorecards, Cockpit catalogue answer **73 across 6 domains**.

### Regression test for all three

`scripts/acceptance/integration_journeys.py`. Its section B asks the bootstrap
plan directly, so R-1 and R-2 would now fail on a laptop rather than only in a
container somebody remembered to start from an empty volume.

### Second-engineer review — the rest of the checklist

| Question | Answer |
|---|---|
| Did `main` change underneath the feature branch? | Yes — and it is 88 commits behind the Planner/Lenses tip. Its tree is identical to an ancestor of the branch, so it contributes nothing. |
| Did a conflict resolution discard a `main` fix? | No conflicts existed, and `main` carries no content beyond the merge-base. |
| Did a feature branch restore code deliberately removed from `main`? | Impossible here: `main` removed nothing relative to `b53c79c`. |
| Duplicate API registrations? | **None.** 538 paths, 584 route/method pairs, **0 duplicates, 0 duplicate operationIds**. |
| Duplicate navigation? | **None.** 25 entries, no duplicate href or label, no dead link. |
| Duplicate schedulers? | **None.** One `SCHEDULE_TICK` producer, one queue, 5 distinct job kinds. |
| Duplicate tool IDs? | **None** across the agentic registry (40) and the Scorecard Validation agent (9). |
| Multiple migration heads? | **One head.** |
| Conflicting model names? | **None.** 142 mapped tables, no duplicate table or mapped-class name. `scorecard_validation_runs` (0028) and `scv_runs` (0040) coexist — the collision the SCV phase renamed around. |
| Conflicting route names? | **None.** |
| CSS / layout regressions? | None seen: 269 browser checks, no console errors, "nothing on screen is unfinished scaffolding" passes. |
| Notification collisions? | None. One inbox, no duplicate ids. |
| Shared cache collisions? | None. Switching scorecard clears prior results; champion/challenger and per-period identity are covered by the SCV adversarial family. |
| User / permission regressions? | None. Signed-out access refused; role-scoped journeys pass. |
| Old Playbooks restored? | **No.** Dropped by 0039's upgrade; no page, route or nav entry. |
| Cockpit scorecard restriction removed? | It was never *removed* — it was never applied to the metadata path. **Found and fixed** (R-3). |
| Docker dependency drift? | **None.** `docker/` is byte-identical to `main`. One dependency added: `python-pptx==1.0.2`, pinned, declared in both `requirements.txt` and `pyproject.toml`. No frontend dependency changed. |

One structural observation, recorded rather than changed: **there are two
catalogue-answering modules**, `backend/metadata/answers.py` and
`backend/orchestration/catalogue_answers.py`, and R-3 had to be fixed in both.
They are not duplicate *registrations* and nothing is broken, but a boundary
that must be stated twice is a boundary that will eventually be stated once.
Worth consolidating after UAT, not during a rehearsal.

## S. Remaining NOT VERIFIED

**LIVE AI — NOT VERIFIED.** `settings.anthropic_api_key` is empty and the
product reports `state: offline`, "GOVERNED LOCAL READER". The nine chat
acceptance prompts have **not** been run through a real provider, because
there is none here. The `ai_provider` health component is `offline` by design
and the integration suite excludes it from its health assertion **explicitly**,
so that the suite is not quietly claiming the thing this report declines to
claim.

**VISUAL WORD REVIEW — NOT VERIFIED.** The generated .docx is a valid OOXML
package with 19 parts that `python-docx` parses, and it names its model,
version, dataset, run key and content hash. **DOCX STRUCTURALLY VERIFIED.**
Nobody has opened it in Word. These are different claims and are not
conflated.

Both are for UAT, when the user has system access.

## T. Exact branch states

| Ref | HEAD | Touched by this rehearsal? |
|---|---|---|
| `origin/main` | `3855f9b` | **No.** Not checked out, not merged into, not pushed. |
| `origin/claude/vigilant-darwin-eohyi1` | `d55f625` | **No.** |
| `origin/claude/playbook-committee-intelligence` | `c17c426` | **No.** |
| `origin/claude/scorecard-validation-intelligence` | `e136b82` | **No.** Read only, as a merge source. |
| `origin/claude/integration-rehearsal` | `99fcf1b` | Created, committed, pushed. Disposable. |

No force-push. No history rewritten. No pull request opened.

## U. Recommendation

> **PENDING the regression in §O.** The recommendation is deliberately not
> written before the run it depends on has finished. A rehearsal that
> recommended a release and then read its own test results in that order would
> not be a rehearsal.

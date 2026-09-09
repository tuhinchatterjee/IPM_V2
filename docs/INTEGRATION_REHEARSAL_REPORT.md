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
| **Final executable HEAD** | **`feacfc3`** |

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

Run on the **final executable HEAD** — `feacfc3` — from the repository root:

```
.venv/bin/python -m pytest tests/ -rs --tb=line -p no:randomly
```

| | |
|---|---|
| **Collected** | **12,834** |
| **Passed** | **12,798** |
| **Skipped** | **36** |
| **Failed** | **0** |
| **Errors** | **0** |
| **Warnings** | **25** |
| **Duration** | **1,597.84s (26m 38s)** |
| **Exit code** | **0** |

The 25 warnings are one `dash` deprecation raised 25 times inside
`tests/legacy/test_esg_inputs.py` — the preserved Dash application, untouched
by this rehearsal.

### The 36 skips, enumerated exactly

| Count | Location | Reason given |
|---|---|---|
| 8 | `tests/llm/test_live_smoke.py:64, 77, 82, 87` | no AI provider key is configured |
| 1 | `tests/evals/test_ask_evaluation.py:210` | set `RUN_LIVE_LLM_EVALS=1` to run these |
| 12 | `tests/scripts/test_powershell_script.py:78` | No PowerShell runtime in this environment |
| 2 | `tests/api/test_user_administration.py:247, 258` | This database has more than one administrator |
| 4 | `tests/orchestration/test_multi_condition.py:292, 306, 342, 476` | the planner stopped to ask: `covenant_tests` does not carry `days_past_due` |
| 3 | `tests/orchestration/test_multi_condition.py:309` | this shape does not compile through the multi builder |
| 3 | `tests/orchestration/test_multi_condition.py:345` | this question is answered from one dataset |
| 1 | `tests/orchestration/test_query_validation.py:249` | the result is limited, so absence proves nothing |
| 1 | `tests/multi/test_relationship_assistant.py:93` | no multiplying candidate in this data |
| 1 | `tests/scorecard/test_validation_runner.py:141` | every registered test has a handler |

Nine are the live-AI gate in another form and are the evidence that §S is not
an excuse: the suite declines rather than quietly passing. Fourteen are this
environment, not the product. Thirteen are the product refusing rather than
guessing — `test_validation_runner.py:141` skips *because* all 48 registered
tests have handlers, so there is no missing-handler case left to assert on.

**The skip set is unchanged from the Scorecard Validation branch's own final
run** — same 36, same reasons. The merge added no skips and silenced nothing.

### The run before this one, and why it is recorded rather than dropped

The first regression on the merged branch, at `99fcf1b`, was **3 failed,
12,795 passed, 36 skipped, exit code 1**. All three were caused by the
domain-boundary fix in §R-3, and all three were real:
`tests/metadata/test_reconciliation.py:122`,
`tests/orchestration/test_dataset_aware_ask.py:231` and
`tests/orchestration/test_population_context.py:152` each asserted that the
Cockpit quotes the metadata service's raw totals — 80 datasets, 9 domains.

They were not stale numbers. They were the other half of a genuine
contradiction between two branches' contracts, and resolving it is the
judgement call recorded in §R-3 and §U. The three tests were re-pointed, not
relaxed: each now asserts the Cockpit's figure equals the service's **minus
exactly the restricted set**, recomputed independently. That is a stronger
assertion than the one it replaced, and it is what turned this run green.

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

### SAFE TO BEGIN USER ACCEPTANCE TESTING

Conditional on the two environmental limitations in §S and on the one
judgement call below being confirmed.

**Why the integration itself is sound.** Ancestry was proved before anything
was merged, so one branch was merged rather than three. The merge produced a
tree byte-identical to the feature branch, because `main` — 88 commits behind
the branch it claims to have merged — carries no content the branch lacks; no
conflict arose and none could have discarded a fix. The migration chain
reconciles three ways: a main-era database and an empty database reach the
same 143 tables and the same 2,336 column definitions, and the whole thing
reverses to exactly the main-era schema and forward again with no drift, on a
single head. The stack starts from an empty volume with all four services
healthy and 15 of 15 readiness checks passing. **12,798 tests pass, 0 fail, 0
error, exit code 0**, plus 269 browser checks across five suites with none
failing. Every figure spot-checked against the feature branches agrees,
including six Playbook snapshots that reconcile against the governed metric
service at exactly 0.000e+00, and no expected value was changed to make
anything agree.

**Three real integration defects were found and fixed**, each of the same
shape — a feature correct alone and wrong once four shared a deployment, and
none of them catchable by its own suite. Two features that came up empty in a
container; three shipped Lenses whose installer documented a caller that did
not exist; and a governance boundary that gated the two paths its author could
see while a third listed and described all seven restricted datasets. All
three now have one committed regression that fails on a laptop rather than only
in a container somebody remembered to start from an empty volume.

**One judgement call needs the user's confirmation, and it is the reason this
recommendation is conditional.** Fixing the third defect changed what a user
sees: the Cockpit now answers "73 governed datasets across 6 data domains"
where it previously said 80 across 9. That is the boundary working, and three
tests written before the boundary existed had to be re-pointed to the governed
contract. It is defensible — `orchestration/context.py` already enforced the
same exclusion on the planning universe, and the acceptance matrix already
recorded SCV-DOMAIN-01 as PASS — but it resolves a contradiction between two
branches on the product's behalf, and only the product's owner can settle
that. **If the intended behaviour is the opposite**, revert
`backend/metadata/answers.py` and `backend/orchestration/catalogue_answers.py`
to their state at `99fcf1b`'s parent, together with the three tests in
`feacfc3`; the Data Builder, readiness and the Scorecard Validation module are
unaffected either way.

**What this recommendation is not.**

* **Not a claim that live AI works.** No provider key exists here; the nine
  chat acceptance prompts are outstanding. **UAT should begin in an
  environment that has one, and run those first.**
* **Not a claim that the Word document looks right.** It is structurally
  verified — a valid 19-part OOXML package naming its model, version, dataset,
  run key and content hash. Nobody has opened it in Word. **A reviewer should,
  before the first committee sees one.**
* **Not a recommendation to merge.** This branch is a rehearsal. It proves the
  combined feature history integrates with the latest `main` without breaking
  CreditProbe; it is not itself the change that should land. When a real merge
  is made, it should carry the three fixes in `99fcf1b` and the three
  re-pointed tests in `feacfc3`, because the merge alone reproduces all three
  defects.

**Nothing was merged to `main`. No protected feature branch was modified. No
force-push, no history rewritten, no pull request opened.**

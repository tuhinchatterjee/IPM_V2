# CreditProbe — Integration Ledger

The record of what was merged into the final integration branch, from which exact
commit, in what state it arrived, and what was true after each step.

A merge that is not in this file did not happen. A failure that is not recorded
here as an inherited baseline is an integration regression.

---

## The integration branch

| | |
|---|---|
| **Branch** | `claude/creditprobe-integration-plan-vyq22h` |
| **Parent** | `origin/main` @ `3855f9b6f6b231beb6f2193c8a1e219d01596421` |
| **Target of any merge to `main`** | **None.** Nothing merges to `main` and no pull request is opened against it until explicitly approved. |

### Naming adaptation

The approved plan names the final integration branch `claude/integration-final`.
This session's runtime permits pushes only to
`claude/creditprobe-integration-plan-vyq22h`, so that branch **is** the final
integration branch and carries the whole integrated product.

The requirement the name was standing for is met: one dedicated integration
branch, not `main` and not a feature branch. A deliberate rename or a mirror
push to `claude/integration-final` can be done later when the environment
permits. Repository safety was not traded for the preferred name.

---

## Source checkpoint register

Heads verified against the live remote immediately before adoption. **Three of
the six approved checkpoints had moved between approval and execution, and all
three moved to better ones** — each verified before adoption rather than taken
on the strength of being newer.

| Branch | Approved in plan | Adopted | Moved? | Why |
|---|---|---|---|---|
| `claude/lenses-live-intelligence-v3-jnlrep` | `c0b66d0` | `c0b66d0` | no | — |
| `claude/what-if-analysis-rebuild` | `80e74a4` | `80e74a4` | no | — |
| `claude/project-planner-copilot` | `e84bc68` | `e84bc68` | no | — |
| `claude/cockpit-agentic-v3-fhg4r0` | `00b8808` | **`08bd5d5`** | **yes** | "the architecture freeze" — 43 requirements audited, six query modes, `answer_check.py` holds every prose figure against executed results, state machine as a registry with a cycle-based boundedness proof, 93 new tests. 490 Cockpit + 380 frontend tests pass |
| `claude/early-warning-rebuild-v2-3lnttn` | `a6ff962` | **`4dcef65`** | **yes** | "Record the completion handoff, and prove the trace" — 2,295 passed, 38 non-passing, same 38 identifiers as its own baseline, none introduced |
| `claude/creditprobe-playbook-plan-ky3m05` | `fe5261c` | **`713f99a`** | **yes** | Streaming landed and was verified (`cc9a2f4`: 9,810 passed, 30 skipped, 0 failed). Brings a third migration, `0034_playbook_stream_events` |

Superseded — ancestors of the adopted tips, never merged directly:
`playbook-committee-intelligence` `c17c426` · `scorecard-validation-intelligence` `e136b82` ·
`lenses-specialist-dashboards-esd591` `b20417f` · `cockpit-intelligence-v2-mbb22o` `83b39a6` ·
`vigilant-darwin-eohyi1` `e84bc68` (identical tree to project-planner-copilot) ·
`integration-rehearsal` `4a3c1fd`.

Out of scope: `IPM_V3` — an unrelated line from July, not CreditProbe feature work.

**Rule.** Every merge takes an exact commit hash. The head is re-verified against
the live remote immediately before each merge. Three of six moved within hours of
approval; more will.

---

## Inherited failure baselines

Captured **before** merging, so that afterwards an inherited failure and an
integration regression are distinguishable. Any post-merge failure not in these
sets is a regression and is fixed; any failure in them is inherited and is
carried with its origin named.

| Source | Baseline as stated by the branch | Status |
|---|---|---|
| What-If `80e74a4` | 6 failures on the whole-repository run. Its own account: **none are What-If and none are new** — four are catalogue and workbook defects on the credit book already established on baseline `4f79566`, and one is not a code failure at all (see the shared-database note below). Its own readiness cycle 6 is **16 of 16 steps PASS, 44 checks passed, 0 failed** | recorded |
| Project Planner `e84bc68` | 13,033 passed, 2 failed, 38 skipped. Both traced, neither in the Planner, neither a product defect: the stray `Test Domain` row (below), and a messaging directory that returns a bounded page whose fixture account has fallen outside it among accumulated users — it passes on a fresh database | recorded |
| Early Warning `4dcef65` | 2,295 passed; **38 non-passing, the same 38 identifiers as its captured baseline, none introduced** | recorded from the branch's completion handoff |
| Chat-first Playbook `713f99a` | 9,810 passed, 30 skipped, 0 failed. **6 BLOCKED** — PB-013, PB-015, PB-017, PB-029, PB-030, PB-043 — every one blocked solely on a missing `ANTHROPIC_API_KEY`, none on a defect. What-If carried as DEFERRED-INTEGRATION inside PB-006 | recorded |
| Cockpit `08bd5d5` | 490 Cockpit tests and 380 frontend tests pass; 413 repository failures identical to its preserved base, id for id; seven stated blockers | recorded |

### A shared defect both branches name, owned by neither

What-If and Project Planner independently trace one of their failures to the
same cause: `tests/api/test_data_builder.py` creates a data domain called
`Test Domain` through the API and never deletes it, and these suites share one
development database. The fresh-clone proof then counts more live domains than
it expects. Project Planner proved it both ways — delete the row and the proof
suite passes 23 of 23; run the data-builder suite and it comes back — and noted
it only appears once the full suite has run twice against the same database.

Both branches deliberately left it alone rather than widening into a file
outside their work. It is nobody's feature and everybody's failure, which makes
it **an integration defect** and this branch's to fix. It also means these
particular failures may not reproduce here at all, because this integration
runs against a database created fresh — so their absence is not evidence that
anything was fixed, and their presence is not an integration regression.

### The pre-merge regression floor

From the integration rehearsal, on the chain as it stood at `feacfc3`:

| | |
|---|---|
| Tests | 12,834 collected · 12,798 passed · 36 skipped · 0 failed · 0 errors |
| Schema at `0041` | 143 tables · 2,336 columns |
| Data Builder | 80 governed datasets · readiness 80 catalogued / 80 registered |
| Cockpit catalogue answer | 73 datasets across 6 domains (80 minus the 7 restricted scorecard datasets) |
| SME champion | AUC 0.6547 · 24,119 observations · 1,398 events |

Movement in any of these is explained in this ledger or it is a defect.

---

## Merge log

### M0 — integration branch opened

| | |
|---|---|
| **Date** | 2026-09-09 |
| **Parent** | `origin/main` `3855f9b` |
| **Merged** | nothing |
| **Migrations** | none — head remains `0031` |

**What was done.** The branch was opened at `origin/main`, this ledger was
created, and `docs/INTEGRATION_REHEARSAL_REPORT.md` was carried forward from
`claude/integration-rehearsal` as the reference document for work already proven.

**Why the rehearsal branch is not the parent.** Audited per Decision 12. It
contains playbook-committee, scorecard-validation, lenses-specialist and
lenses-live-v3, and it solved three real integration defects:

* **R-1** — Project Planner and Playbook came up empty on a healthy deployment;
  fixed by wiring `planner` and `playbook` steps into `backend/bootstrap/plan.py`.
* **R-2** — the three shipped Lenses were never installed; fixed by a `lenses`
  bootstrap step calling `backend/metrics/lenses.py::install()`.
* **R-3** — the general Cockpit could list and describe every restricted
  scorecard dataset; fixed by routing both Cockpit answer paths through
  `backend.scorecard.domains.restricted_datasets`, with three tests re-pointed
  to assert the service total *minus* the restricted set, recomputed
  independently.

**All three fixes and all three re-pointed tests are already ancestors of every
chain tip** — verified at execution time: `99fcf1b`, `feacfc3` and `4f79566` are
each contained in `what-if-analysis-rebuild`, `lenses-live-intelligence-v3-jnlrep`
and `project-planner-copilot`. The rehearsal branch adds exactly one commit
beyond the Lenses V3 tip, and it is a merge. So the work is inherited by merging
the chain; parenting from the rehearsal would add nothing and would obscure the
per-merge history this ledger exists to keep.

**Verification.** Working tree clean; branch at `3855f9b`; the three ancestry
checks above re-run rather than taken from the plan.

---

### M1 — Lenses V3 (`c0b66d0`)

| | |
|---|---|
| **Merged** | `c0b66d0a6f7586c3b4f75c9b1863a26a735544f8` — head re-verified against the live remote immediately before merging |
| **Merge commit** | `d499f99` |
| **Conflicts** | **none** |
| **Migrations after** | `0032`–`0042`, single head `0042` |

**What this one merge brings.** The whole chain in a single reviewable step:
`playbook-committee-intelligence`, `scorecard-validation-intelligence`,
`lenses-specialist-dashboards`, the integration rehearsal's three fixes, Lenses
V3 itself, and migrations `0032` through `0042`.

**Migration gate — PASS.**

| Check | Result |
|---|---|
| `alembic heads` | **one**, `0042` |
| Empty database → head | 42 migrations, **145 tables, 2,376 columns** |
| Round trip `0042 → 0031 → 0042` | down to **104 tables** — exactly the rehearsal's main-era count — and back to 145 / 2,376 |
| `scv_results.value` nullable | **YES** — a refused test still cannot come back out of the database as a zero |

Against the rehearsal's floor of 143 tables / 2,336 columns at `0041`, this is
`0042` adding two tables and forty columns, which is what
`0042_lens_live_intelligence` declares it adds. No unexplained schema movement.

**Other gates.** `ruff check .` clean. Frontend `tsc --noEmit` clean. Saudi
data lake builds — 51 governed datasets. Full backend suite and the remaining
frontend checks were still running when this entry was written and are recorded
in the M1 completion entry below rather than anticipated here.

### Environment defects found while standing the toolchain up

Neither is caused by this integration; both are recorded because they block a
clean install and would otherwise be rediscovered.

**The chain cannot be installed on Python 3.11.** `pyproject.toml` at this tip
declares `requires-python = ">=3.11"` and pins `numpy==2.5.0`, which requires
`>=3.12`. `uv sync` therefore fails to resolve at all:

> Because the requested Python version (>=3.11) does not satisfy Python>=3.12
> and numpy==2.5.0 depends on Python>=3.12, we can conclude that numpy==2.5.0
> cannot be used.

What-If's bump to `requires-python = ">=3.12"` at M2 is the fix, and this is the
concrete reason it exists rather than a stylistic preference. Until M2 lands,
this branch is built against an explicitly selected 3.12 interpreter.

**`python-multipart` is declared in the `dev` dependency group**, not as a
runtime dependency, exactly as the plan predicted. Six routers declare
`UploadFile`, and FastAPI raises at *import* time without it, so a production
install from `pyproject.toml` alone cannot construct the app. To be promoted to
a runtime pin during the AI/dependency consolidation.

### Standing up the lake at M1 — what it proved and what it exposed

The full data lake was built on this branch to make the gates real rather than
skipped. Building it reached the rehearsal's figure exactly and confirmed two
defects the plan had predicted from reading the code.

**The lake reconciles.** After the Saudi build, the corporate build, the retail
scorecard build and the SME build: **80 datasets catalogued, 80 on disk, gap
empty** — the same 80 the rehearsal recorded.

**Generator idempotence, evidenced early.** Re-running
`scripts/build_corporate_universe.py` over an existing lake rewrote
`docs/corporate_universe_build.json` with **144 changed lines, every one of them
a wall-clock timing**. Filtering the timing keys leaves **zero** changed lines:
dataset counts, relationships, forbidden joins, field lists and every recorded
figure are byte-identical between runs. The regenerated timings were reverted
rather than committed, since machine-specific seconds are churn that would make
a later idempotence check noisier rather than clearer.

**Defect — the SME scorecard has no build script.** `backend/scorecard/sme/build.py`
is import-only. The only invocation anywhere in the repository is a string
inside a test's error message. It was run here as
`python -c "from backend.scorecard.sme import build; build.build()"`. A rebuild
runbook cannot run that, so `scripts/build_sme_scorecards.py` has to be written.

**Defect — the SME build writes Parquet but does not register.** `build.build()`
produced `sme_scorecard_monthly_validation`,
`sme_scorecard_development_reference` and `sme_scorecard_decisions` on disk and
left the governed catalogue at **77 of 80**. The three datasets existed and were
invisible. They only appeared after
`backend.scorecard.sme.catalogue.merge_into_catalogue()` was called by hand,
which nothing in the build path does.

That call's own summary also confirms the SME audit's central finding from the
running system rather than from reading source: **`variables_carried: 22,
variables_declared: 90`.**

**Environment note.** The container has no `.venv`, no `node_modules` and no
running database at session start, and the chain cannot be installed on the
container's Python 3.11 (see the M1 entry). The toolchain here is an explicitly
selected 3.12 interpreter, a local PostgreSQL 16 cluster on port 5433, and
`npm ci` in `frontend/`. The database was created fresh, which is why the
inherited `Test Domain` failures may legitimately not reproduce.

## Integration defect I-1 — the bootstrap declared an empty product ready

**Found at M1. Severity: material.** Fixed on this branch, with regression tests.

### What happened

`scripts/bootstrap_demo.py` completed every step, its readiness gate passed all
sixteen checks, and it printed **"The deployment is ready."** The database
behind it held **zero Playbook committees, zero packs and zero sections**, so
`/playbook` would have been empty on a deployment reporting itself healthy.

### The chain

1. `_users_needed()` asked `SELECT count(*) FROM users` and treated any row as
   "already in place".
2. This database — like development and CI — is shared with the test suites,
   which leave `act-boss-...` fixture accounts behind. There were **184 of
   them, and not one of the six demonstration people**.
3. Step B therefore reported "already in place" and never seeded
   `alex.rahman`, `sara.qahtani`, `omar.nasser`, `layla.haddad`, `sarah.khan`
   or `ahmed.saleh`.
4. Step O's builder looked for a committee chair, found none, and **refused**
   — correctly, since it will not invent accounts — recording the reason in
   `report.notes`.
5. `_seed_playbook()` inspected only `report.error`, which was empty, so it
   returned `"0 committee(s) built, 0 already present"` **as a success**.
6. The bootstrap printed that as a performed step and declared the deployment
   ready.

### Why the existing guard did not catch it

This is the R-1 family — *"Nothing failed. The API came up healthy and the
product was empty"* — but it defeats R-1's own regression test. That test asks
the bootstrap plan **whether the `playbook` step exists**. It does. The step is
wired in, runs, and reports success; the defect is in a *probe* and in an error
that was never raised. A structural check for the step's presence cannot see it.

### The fix

* `_users_needed()` now asks for the demonstration accounts **by name**, and is
  unsatisfied if any one is missing. `demo_users.seed` is already idempotent per
  username, so re-running repairs a partially seeded directory instead of
  stepping over it. A partially seeded directory is exactly the state a count
  hides best.
* `_seed_playbook()` now **raises** when it built nothing and nothing was
  already present, carrying the builder's own notes so the operator gets the
  reason rather than "it did nothing".

### Verified

Re-running the bootstrap against the same database: step B created **6
accounts**, step O built **3 committees**, and the database now holds
**3 committees, 6 packs, 22 sections** — the exact seeded state the integration
rehearsal recorded.

Regression tests in `tests/proof/test_bootstrap_marker.py`, in the class that
already holds this doctrine (`TestAStepIsNeededWheneverItsGateWouldFail`):
fixture accounts do not satisfy the probe; only the full demonstration cast
does, and one missing is still missing; and a build that seeds no committee at
all is an error. 26 of 26 pass in that file.

### It compounds a defect the feature branches already named

What-If and Project Planner both traced a failure to `tests/api/test_data_builder.py`
leaving a `Test Domain` row behind in a shared database. This is the same
shared-database pollution reaching a **different** surface: there it inflates a
domain count, here its fixture accounts satisfied a user count. Both are
arguments for the same fix — probes that ask for the thing rather than counting
rows — and `Test Domain` itself is still outstanding.

## M1 — closed

### The gate, after the deployment was properly bootstrapped

The first two suite runs are recorded rather than dropped, because the
difference between them is the finding.

| Run | State of the environment | Failures | Setup errors |
|---|---|---|---|
| 1 | lake incomplete — scorecards not built | **aborted at collection** (2 `tests/brain/` modules) | — |
| 2 | lake complete, **application never bootstrapped** | **64** | **75** |
| 3 | bootstrapped, after the I-1 fix | **7** | **4** |

**None of run 2's 64 failures could have been an integration regression, and
this is provable rather than argued.** The integration HEAD at that point
differed from the Lenses V3 tip by exactly two Markdown files under `docs/` —
no code, no tests, no configuration:

```
git diff --stat c0b66d0 HEAD
 docs/INTEGRATION_LEDGER.md            | 250 ++++++
 docs/cockpit_repoint/FIELD_MAPPING.md | 239 ++++++
```

They were the product of an unbootstrapped deployment. Bootstrapping it removed
57 of the 64.

### The 7 remaining, each classified

| Test | Verdict |
|---|---|
| `tests/proof/test_bootstrap_marker.py:508` | **Mine, and the suite was right.** My own new regression test did not raise. `import a.b as c` binds through `getattr(a, "b")` when the package already carries the submodule, so replacing the `sys.modules` entry was never seen. Fixed by patching the module's own `build`. |
| `tests/metrics/test_lens_domains.py:152` | **A real latent defect this integration surfaced.** See I-2. |
| `tests/exports/test_workbooks.py:50` (x2) | **Inherited.** Present in run 2, before any of my changes. What-If's own handoff describes four of its six failures as *"the catalogue and workbook defects on the credit book established on baseline 4f79566"*; these are two of them. |
| `tests/evals/test_properties.py:90` and `:103` | **Inherited.** Same, and the other two of that four. |
| `tests/evals/test_multi_analysis_response.py:166` | **Inherited.** Present in run 2. |

None of my three fixes touches `backend/exports`, `backend/evals` or the
credit-book analytics — the changed files are `backend/bootstrap/plan.py`,
`backend/metrics/lens_domains.py` and two test files.

### The 4 setup errors

All four in `tests/scorecard/test_report_api.py`, all
`psycopg.OperationalError: connection refused` on port 5433. **Environmental,
not a product defect:** this container reaps background processes and killed the
PostgreSQL cluster mid-run. A supervisor now restarts it within five seconds,
which is why run 3 has four rather than run 2's block of skips. Re-run in
isolation, these pass.

### Other M1 gates

| Gate | Result |
|---|---|
| Merge | clean, no conflicts |
| `alembic heads` | one, `0042` |
| Empty DB to head | 145 tables, 2,376 columns |
| Round trip `0042 -> 0031 -> 0042` | 104 tables at `0031`, back to 145 / 2,376 |
| `scv_results.value` nullable | YES |
| `ruff check .` | clean |
| Frontend `tsc --noEmit`, eslint | clean |
| Frontend `npm test` | **541 passed, 0 failed** (46 suites) |
| Governed catalogue | **80 catalogued, 80 registered** |
| Bootstrap readiness | 16 of 16 checks pass |
| Corporate book | 3,800 borrowers over 16 quarters |
| Q2 2026 review | completed, 7 Risk Cases |

## Integration defect I-2 — three governed datasets no registry named

**Found at M1. Severity: material. Fixed.**

Registering the SME datasets in the governed catalogue — which the SME build
never did — made `tests/metrics/test_lens_domains.py` fail:

> These governed datasets are named in neither COCKPIT_DATASETS, EWS_DATASETS
> nor REFUSED, so whether a Lens may read them is being decided by a Data
> Builder domain label rather than by this registry:
> ['sme_scorecard_decisions', 'sme_scorecard_development_reference',
> 'sme_scorecard_monthly_validation']

The registry had never had to name them because they had never reached the
catalogue. Whether a Lens could read the SME book was being decided by a
domain label rather than by the registry that exists to decide it.

**Fixed** by adding all three to `REFUSED` with stated reasons, which is what
Decision 6 and the rehearsal's R-3 boundary both require: a Lens may read the
Cockpit and Early Warning domains, and Scorecard Validation stays restricted.
The reasons follow the file's own doctrine that *"no rule for this" and "this
belongs to another product" are different answers and only the second is
useful*.

## Integration defect I-3 — the Test Domain row, fixed

**Found by two feature branches, owned by neither. Fixed here.**

`tests/api/test_data_builder.py` created a business domain called `Test Domain`
in seven places and never removed it. `tests/proof/test_fresh_clone_acceptance.py`
then counted eight live domains where seven were expected. Both the What-If and
the Project Planner branches traced a failure to this row and deliberately left
it alone as outside their work — correct for a feature branch, and it left the
defect nobody's.

The same file already cleans up its *datasets*, with a fixture docstring
explaining exactly why leaking matters: a leaked dataset makes the governed
catalogue advertise data no longer on disk, and an unrelated suite asserts that
invariant. That argument was never applied to the domain created beside them.

**Fixed** with a module-scoped autouse teardown, following that doctrine —
autouse because a cleanup somebody has to remember to ask for is the one that
gets forgotten, and refusing to delete a domain that still has datasets filed
under it, because that would hide a leak rather than report it.

**Verified** by running `tests/api/test_data_builder.py` and then
`tests/proof/test_fresh_clone_acceptance.py` in that order — the order that
used to fail — together with the two other affected suites: **95 passed, 0
failed**, and no `Test Domain` row afterwards.

### M2 — What-If (`80e74a4`), the canonical foundation

| | |
|---|---|
| **Merged** | `80e74a4e1e5552e73c532849b72329008335b09f`, head re-verified against the live remote first |
| **Merge commit** | `15d81c5` |
| **Conflicts** | **one**, and it was a generated file |
| **Migrations after** | `0032`-`0042`, single head `0042` — What-If adds none of its own |

**The conflict, and why it was regenerated rather than resolved.**
`docs/FINAL_FEATURE_VERIFICATION_MATRIX.md` is written by
`scripts/feature_matrix.py`. Both sides were stale with respect to the tree the
merge produced — one said 60 pages and 588 endpoints, the other 63 and 612 — so
picking either would have committed a number that was wrong before it was
written. Regenerated from the merged tree: **64 pages, 652 endpoints across 42
areas, 98 browser-crawled routes**.

**What landed, verified rather than assumed.**

| | |
|---|---|
| `backend/corporate/ratingscale.py` | 19 performing grades, `SCALE_VERSION 3.0.0` |
| `universe.py` | delegates — `PERFORMING = ratingscale.PERFORMING` |
| `backend/whatif/masterscale.py` | binds to `ratingscale`, not the 13-grade scale |
| `requires-python` | `>=3.12` — closes the numpy defect recorded at M1 |
| `uv.lock` | present |
| `.github/workflows/ci.yml` | carries the corporate-build step, in the order its comment requires |

Two files the plan expected to fight over resolved themselves: Lenses V3 never
touched `masterscale.py` or `universe.py`, so What-If's versions landed without
a conflict.

**The lake had to be rebuilt before the gate could mean anything.** The
corporate book on disk was built at M1 under the 13-grade scale; the merge
replaced the scale underneath it. Rebuilt, and the record is substantive rather
than the timings churn seen at M1 — **69 non-timing lines changed**, the
catalogue moving from 73 to 80 datasets, and the generator now publishing the
fields the What-If schema contract asks for: `ttc_pd_pct`, `pit_pd_12m_pct`,
`lifetime_pd_pct`, `pd_applicable`, `pd_measurement_basis`, `secured_lgd`,
`unsecured_lgd`, `ecl_before_overlay`, `credit_conversion_factor`,
`internal_rating_ordinal`, `stage_measured`, `sicr_clear_quarters`. The
contract and the generator agree by construction now rather than by
coincidence. The build reports `catalogue reconciles with the lake: True`.

**A sequencing rule this established, which applies to every later merge.** A
merge can invalidate the data lake AND the installed environment, not just the
code. It invalidated the lake here by replacing the rating scale, and the
environment by introducing `xgboost`, `scikit-learn`, `scipy` and `shap` — the
first G-DATA run failed four What-If ML tests purely because the venv predated
the merge. Both are refreshed before gating from here. **EWS at M5 needs the
same treatment**, because it reads the corporate snapshot.

### G-DATA — the canonical gate

Asserted directly against the rebuilt book, independently of any suite:

| Check | Result |
|---|---|
| Reported period set | **16 quarters**, `Q3 2022` to `Q2 2026` |
| Canonical borrowers | **3,800**, `CORP-100000` .. `CORP-103799` |
| Orphan `corporate_ifrs9` rows vs the 360 snapshot | **0**, joined on `borrower_id` + `period` |
| Distinct rating grades in the book | **20**, none outside the 19-performing + `D` scale |
| Rating ordinals | range **1-20**, none outside |

*Method note.* Two earlier attempts at the grade check were wrong — the first
queried `internal_rating` on `corporate_ifrs9`, which does not carry it, and
the second mis-parsed DuckDB's `describe` output. The figures above are from
the corrected run.

## Correction — the `python-multipart` claim in the plan is overstated

The integration plan recorded, from the Lenses V3 branch's own comment, that
six routers declare `UploadFile` and that **"FastAPI raises at IMPORT time
without this... a clean install of this file could not start the API at all."**

**That is not reproducible.** Tested in a clean 3.12 virtualenv built from
`requirements.txt` with `python-multipart` removed, `backend.api.main` imports
and constructs its routes. The reason is that `python-multipart` arrives
**transitively as a dependency of `mcp`**, so the environment was getting away
with the declaration gap.

An earlier attempt of mine to test this by blocking `sys.modules` proved
nothing, because Starlette binds the module at its own import and the block
came too late. Recorded because the first attempt led me to state the claim was
false before I had established it.

**The declaration gap is still real and still worth fixing, for a different
reason.** Six routers use `python-multipart` directly, and it was declared only
in the `dev` group of `pyproject.toml` while `requirements.txt` pinned it as a
runtime dependency — two files, two answers. Upload support therefore rested on
what an unrelated library happened to require, and an `mcp` bump that dropped
it would have taken uploads with it silently.

**Fixed**: promoted to a direct runtime dependency in `pyproject.toml`, pinned
`==0.0.20` to match `requirements.txt` rather than the `>=0.0.20` the dev group
carried, so the two files cannot resolve to different versions.

### M3 — Project Planner (`e84bc68`)

| | |
|---|---|
| **Merged** | `e84bc68f1494b2c744df8a873f1917872230f7a7`, head re-verified first |
| **Merge commit** | `874f95f` |
| **Conflicts** | **one**, `frontend/src/lib/hooks.ts` |
| **Migrations** | Planner's three renumbered; head moves `0042` -> **`0045`** |

#### Migration decision — the 0042 collision

Lenses V3 and the Planner both claimed `0042`. The Planner's three move up one,
each with `revision` and `down_revision` rewritten and **its body untouched**:

| Was | Now | down_revision |
|---|---|---|
| `0042_planner_copilot` | **`0043`** | `0041` -> `0042` |
| `0043_task_milestone` | **`0044`** | `0042` -> `0043` |
| `0044_reminder_level` | **`0045`** | `0043` -> `0044` |

Chain: `0041` -> `0042 lens_live_intelligence` -> `0043` -> `0044` -> `0045`, one head.

| Check | Result |
|---|---|
| `alembic heads` | one, `0045` |
| **Existing** database `0042` -> head | three upgrades, clean |
| Round trip head -> `0031` -> head | **104** tables at `0031`, back to **146 / 2,402** |
| `scv_results.value` nullable | YES |

#### The conflict — two designs for one behaviour

Both branches independently added "keep the previous answer while reloading" to
`useAsync`, with incompatible `Phase` types: the chain widened `loading` to
carry optional data; the Planner added a distinct `reloading` state.

Resolved to the chain's shape, on evidence rather than preference: a grep for
the `reloading` variant across `frontend/src` finds **zero consumers** outside
the hook, and both designs return the same public surface — `data`, `error`,
`loading`, `reload`, `refused`, `status` — so every caller behaves identically
either way. The auto-merge had left a test for a variant that no longer
existed; typecheck caught that, and a stray comment terminator of my own.

Both branches' *documentation* is kept. Each justified the flag with a
different real case — a Lens re-rendering because a metric was added from
inside the page, and a form that saves a field then re-reads the document — and
both are true.

Frontend after: typecheck clean, eslint clean, **564 passed, 0 failed** (541
before).

#### The gate, and the container's interference

The first backend run showed 38 failures and 11 setup errors. The PostgreSQL
server log settles what they were:

```
12:25:34 LOG: terminating any other active server processes ... database system is shut down
12:32:40 LOG: terminating any other active server processes ... database system is shut down
```

The container reaped the cluster **twice mid-run**; the keepalive restarted it
within seconds, but every test holding a connection at those moments failed.
Re-running the four affected files: **37 of the 38 pass**. This is now the
dominant source of noise in every gate, and the standing method is to re-run
failures rather than read a first run as final.

#### The one real failure, and why it is fixed here

`tests/planner/test_escalation.py::test_light_waits_longer_before_escalating_a_blocked_task`
survived the re-run. **Proven inherited**: checked out at `e84bc68` in a
worktree and run in this same environment, it fails identically. Not an
integration regression.

Root cause, instrumented rather than guessed:

* `TODAY = date(2026, 9, 6)` is hardcoded, and the sweep runs with `today=TODAY`.
* `_task()` set `last_update_at = datetime.now(UTC) - timedelta(days=quiet_days)`
  — the **wall clock**.

The two agree only on 6 September 2026, the day the Planner session wrote the
test, and drift by a day every day after. On 9 September a task three days
quiet measured as **zero** days quiet, so `blocked_days (0) >= 1` was false and
the CRITICAL blocked-escalation never fired. The product logic is correct; the
test was coupled to the calendar.

**Fixed** by anchoring `last_update_at` to `TODAY` rather than the wall clock —
same intent, no coupling. `tests/planner/test_escalation.py`: **24 passed**.
Swept the rest of the suite for the same pattern; this was the only file mixing
a fixed `TODAY` with `datetime.now()`.

Left alone would have meant a permanent red that masks real failures at every
later gate, including M13.

### M4 — Cockpit Agentic V3 (`275284c`)

| | |
|---|---|
| **Approved checkpoint** | `08bd5d5` |
| **Adopted** | **`275284c`** — moved again during M3 |
| **Conflicts** | two: `backend/services/threads.py`, `frontend/src/lib/api.ts` |
| **Migrations** | **none**; head stays `0045` |

#### Why the newer checkpoint, and why it matters beyond Cockpit

`6eba08b` fixes a **product-wide security leak that happens to arrive on a
feature branch**. `AnthropicProvider` is a dataclass, so every field reached
its `repr` — `repr(provider)`, `str(provider)`, any f-string or traceback
naming it printed the API key in full. `api_key` is now `field(repr=False)`
with an explicit `__repr__` reporting only `PRESENT` / `MISSING`. Verified
present after the merge.

The same commit isolates the Cockpit's credential: it reads
`COCKPIT_ANTHROPIC_API_KEY` and nothing else — not `ANTHROPIC_API_KEY`, not
the SDK's implicit discovery, not `settings.anthropic_api_key`. The reason is
specific and sound: in this environment `ANTHROPIC_API_KEY` is also what the
tooling uses, so sharing it would bill the product's calls against whoever was
driving the tools, with no way to separate or revoke afterwards.

**This refines the AI plan rather than contradicting it: provider *code* is
shared, the Cockpit's *credential* deliberately is not.** That is an isolation
boundary to preserve, not a divergence to reconcile away.

#### Resolution 1 — `threads.py`, and the second defect that was not predicted

The plan anticipated one problem: Cockpit's short-circuit returns early, so a
caveat placed after it is never reached. Reading the merge found a second.

Cockpit called `cockpit_v2.answer_for(question, ...)` — the user's **raw**
words — while the deterministic path immediately above planned on `asked`, the
clarification-merged question. **One turn, two different questions**, and the
Cockpit path silently answering the one the user typed rather than the one
CreditProbe resolved.

Both fixed, and the ordering is the fix for the first:

* the `if resumed:` caveat is appended **before** the Cockpit block, because
  `cockpit_v2.apply` only ever *appends* to `narrative.caveats` and never
  replaces them — so a caveat placed first survives into the V2 answer intact;
* `answer_for` now takes `asked`. Where nothing was resumed the two strings are
  identical, so the change bites only on the path it was wrong on.

#### Resolution 2 — `api.ts`, which was not the conflict it appeared to be

It looked like two disjoint blocks appended at one point. Both sides in fact
ended **mid-declaration**, sharing the trailing `};\n};` — HEAD's tail was
`ScvAnswer`, Cockpit's `CockpitV3Diagnostics`. Taking either side would have
silently truncated a type. Both kept; `ScvAnswer` closed explicitly so the
existing suffix closes Cockpit's. `tsc --noEmit` is the proof.

#### Integration defect I-4 — a screen said "demonstration"

`tests/release/test_product_copy.py::TestNothingOnScreenNamesAVendor::test_no_rendered_string_says_demo`
failed on `frontend/src/components/ask/cockpit-v2.tsx`, which rendered
**"Synthetic demonstration data"**.

**Proven inherited** — checked out at `275284c` in a worktree, the rule and the
offending string coexist and the identical test fails there.

Not a tension between honesty and the rule, which was the thing worth checking
before touching a label about synthetic data. The product already has one
vocabulary for this — the Data Builder badge's `"Synthetic data"`, the home
page's `SYNTHETIC_SENTENCE`, and `backend/release/product_copy.py`'s own
constants — and that file states the reason the word is kept off every screen:
the switch keeps its internal name, but a reader is shown *the posture it
produces*. Cockpit had simply not used the shared vocabulary.

**Fixed** to `"Synthetic data"`. The claim is unchanged; only the word the rest
of the product does not use is gone. `tests/release/`: **86 passed, 0 failed**.

**Observed, not changed:** four backend constants still contain "Synthetic
demonstration…" (`cockpit_agentic/__init__.py`, `cockpit_v2/__init__.py`,
`cockpit_v2/answer.py`, `cockpit_v2/policy.py`). The rule scans `frontend/src`
only, deliberately — it is about what reaches a screen. Widening it is a
product decision, not an integration one, so it is recorded for M4b rather than
taken unilaterally.

#### The gate, and the container

The first run showed 92 failures and 47 setup errors against **479
`Connection refused`** lines; the PostgreSQL log now records **15 cluster
kills** this session. Re-run in batches:

| Batch | Result |
|---|---|
| `test_early_warning_api`, `test_corporate_api`, `test_metrics_api` | **109 passed, 0 failed** |
| `test_lens_scope_api`, `test_engine_api`, all `tests/orchestration/` | **1,422 passed, 11 skipped, 0 failed** |
| `tests/cockpit_agentic/`, `tests/cockpit_v2/`, `tests/llm/` | **580 passed, 34 skipped**, 3 failed — all `Connection refused` |
| `tests/release/` (after I-4) | **86 passed, 4 skipped, 0 failed** |

Frontend: `tsc --noEmit` clean, eslint clean, **564 passed, 0 failed**.
`ruff check .` clean. `alembic heads`: one, `0045`.

Preserved and verified after the merge: `STRICT_ROLES` with
`COCKPIT_PREPROCESS` / `COCKPIT_REASONING` and `REQUIRED_UNSET`; the
credential-leak `__repr__`; `COCKPIT_CREDENTIAL_VAR`.

**The Cockpit private universe is still present and still not wired to the
canonical domains.** M4 merges; M4b repoints.

### M4b — Cockpit repoint, DEFERRED to post-demo, with the measurement that decided it

The approved M4b was the full repoint plus a Cockpit-owned projection layer.
The demo fast-track asks for "only the minimum safe compatibility layer
required so Cockpit runs correctly on canonical actuals", with the fallback
that anything which cannot be done *quickly and honestly* is disabled, marked
post-demo, and must not block the unified demo.

**The measurement:** of the Cockpit's **791 declared fields across 10
relations**, exactly **50 share even a NAME with any canonical `corporate_*`
dataset — 6%.**

| Cockpit relation | fields | share a name |
|---|---|---|
| `cockpit_facility_quarter` | 198 | 6 |
| `cockpit_rating_ratio_quarter` | 170 | 12 |
| `cockpit_borrower_financial_quarter` | 135 | 12 |
| `cockpit_covenant_quarter` | 59 | 6 |
| `cockpit_collateral_quarter` | 49 | 3 |
| `cockpit_ifrs9_detail` | 44 | 3 |
| `cockpit_macro_quarter_window` | 40 | 2 |
| `cockpit_collateral_allocation` | 34 | 3 |
| `cockpit_qualitative_quarter` | 33 | 2 |
| `cockpit_reporting_calendar` | 29 | 1 |
| **total** | **791** | **50** |

And a name match is an **upper bound**, not a mapping: two of the ten macro
factors match by name and mean different things (`fx_lcy_per_usd` against an
`fx_index`; `commercial_property_price_index` against a *residential*
`house_price_index`).

**So the "minimum compatibility layer" IS the whole repoint** — roughly 740
hand-mapped fields, every one a place to change what a number means. Doing that
quickly is precisely the fabrication the decision forbids. Deferred, and the
fallback rule applied to the repoint rather than only to the projection.

#### Why deferring is safe: the boundary is structural, not procedural

| Check | Result |
|---|---|
| Cockpit store root | `data/cockpit_agentic_v3/` — its own root |
| `store.FORBIDDEN` | refuses `data/analytics`, `metadata`, `data/curated`, `data/raw` |
| `cockpit_*` datasets in the governed catalogue | **none of the 80** |

A canonical consumer cannot read Cockpit data even by mistake, because the
catalogue does not name it. What-If, EWS, Lenses and Borrower 360 continue to
read the canonical book; the Cockpit reads its own; and neither can reach the
other.

**New: `tests/proof/test_cockpit_canonical_boundary.py`** — 6 tests, all
passing. No `cockpit_*` dataset is governed (and the catalogue still holds the
canonical book, so an empty catalogue cannot pass it for the wrong reason); the
Cockpit root is outside the analytics and metadata directories and refuses them
by name; no `BRW`/`FAC0`/`GRP0`/`CKB-`/`CKG-` identifier appears in
`corporate_borrower_360` and every borrower there is `CORP-`; and
`corporate_ifrs9` holds exactly 16 periods with no 2021, 2027 or 2030 quarter —
so a projection cannot have become a reported period.

Each feature branch tests its own side. **Neither owns the boundary between
them**, which is why it was untested and why it belongs to the integration.

#### The forward-projection question, and why it does not arise for the demo

150 of the 200 macro-pivot cells per anchor (10 factors x offsets +1..+15) are
forward projections with no canonical source. That is a *repoint* problem: on
its own store the Cockpit's macro window is internally consistent and works.
Deferring the repoint defers this with it. Nothing is fabricated and nothing is
hidden, because nothing changed.

*(Correction to an earlier figure in this ledger and in my reporting: I gave
"175 of 200". The correct count is 150 forward cells per anchor. The 175
conflated those with backward cells missing only at the first four anchors —
Q3 2022 loses -4..-1, Q4 2022 -4..-2, Q1 2023 -4..-3, Q2 2023 -4 — which is 100
cells across four anchors, not a per-anchor loss.)*

#### Carried to post-demo

1. The 740-field mapping, using the five classes in
   `docs/cockpit_repoint/FIELD_MAPPING.md`.
2. `sql.py::_build_session`'s 512 MB whole-relation materialisation — harmless
   at 250 borrowers, impossible at 3,800, and it must become pushdown *before*
   the repoint.
3. `corporate_ifrs9_facility` in the canonical build (19 of 32 fields already
   producible inside `build_ifrs9()`).
4. Cockpit V2's 12-grade scale, re-derived **via PD** and never via rank.
5. The Cockpit-owned projection layer for `quarter_offset > 0`.
6. Four backend constants still reading "Synthetic demonstration…".

#### One honesty point for the demo itself

While the two books are separate, the Cockpit answers portfolio questions on
250 borrowers and What-If/EWS/Lenses answer them on 3,800. **A viewer who asks
both the same question will get different portfolio totals**, and that is a
presentation risk rather than a defect. It is named here so the demo script can
avoid a side-by-side that invites the comparison.

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

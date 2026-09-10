# CreditProbe — Saudi retail conversion: handover

> **Synthetic Saudi retail demonstration data — not ANB customer data or
> approved models.** This is an implemented and tested synthetic demonstration
> with disclosed limits. It is not regulatory approval, not an independent model
> validation, and not an audit conclusion.

---

## 1. The proven source, and what could not be proven

**Base commit:** `80e74a4e1e5552e73c532849b72329008335b09f`
(`origin/claude/what-if-analysis-rebuild`, "Record the whole-repository
regression, and what the six failures actually are", 2026-09-08).

It **contains** the annotated recovery tag `recovered-sep8-whatif`
(`0558f267b1c9d0eb3583cf329aed817d3aa0e15d`, tagged 2026-09-10, "Recovered Sep 8
advanced pre-architecture What-If") as a direct ancestor.

**WHATIF_5318 is not a ref in this repository.** The literal token appears in no
file at any of the fifteen branches or four tags; every `5318`/`5308` hit is a
coincidental digit run inside generated JSON. The committed launchers use ports
8050 and 8000/3000, so the 53xx scheme is a local convention on your machine.
The recovery tag is the only ref in the repository named for a What-If
installation, and it is one of a matched set of three `recovered-sep8-*` tags
that corresponds to your description of frozen presentations.

**What could not be closed from here**, named rather than guessed at: the
WHATIF_5318 launcher file itself, `git rev-parse HEAD` inside that worktree,
whether it is dirty, whether the served frontend is a live dev server or a stale
bundle, and the paths it writes to. Full detail in
`docs/RETAIL_SOURCE_PROVENANCE.md` §2.3.

**If your frozen 5318 is pinned to the tag rather than the branch tip**, the
correction loses nothing:

```bash
git rebase --onto 0558f267 80e74a4e claude/funny-dirac-6n8f0o
```

The twelve commits that separate them are listed in the provenance document.

**New branch:** `claude/funny-dirac-6n8f0o`.

## 2. The launcher to click

```text
launchers/retail/start-retail.command
```

| | |
|---|---|
| Frontend | <http://localhost:5328> |
| Backend | <http://localhost:8328> |
| Stop | `launchers/retail/stop-retail.command` |
| Check, without starting or changing anything | `.venv/bin/python scripts/check_retail_ready.py` |

First run only:

```bash
uv sync
.venv/bin/python scripts/build_retail_demo.py
.venv/bin/python -m alembic upgrade head
.venv/bin/python scripts/bootstrap_retail_installation.py
```

## 3. Evidence that the frozen installations were not modified

1. **Physical.** They do not exist in the environment this work ran in.
   `/home/user` contains one checkout and nothing else; `ss -lntp` showed no
   listening socket before this work started; a filesystem search for a 5318 or
   5308 installation found only this repository and the uploaded specification.
   No path, socket, process handle or database connection reaches them.
2. **Git.** The three recovery tags and `windows-pilot-v1` are not moved,
   deleted or re-pointed, and no branch other than `claude/funny-dirac-6n8f0o`
   is pushed. Re-verify on your own machine:

```bash
git fetch origin --tags
git rev-list -n1 recovered-sep8-whatif      # 0558f267b1c9d0eb3583cf329aed817d3aa0e15d
git rev-list -n1 recovered-sep8-integrated  # ffad3519ee46de7af518c65ebd5e4f1d94e7760e
git rev-list -n1 recovered-sep8-cockpit-v2  # 83b39a602eb430444f46d08aca4e595522f3b53f
```

3. **No history rewrite.** No `filter-branch`, no force-push to any other ref,
   no amend of a commit that is not this branch's own.
4. **Separate everything.** The retail installation writes to
   `data/retail/analytics`, `metadata/retail`, `var/retail` and its own
   PostgreSQL database, on ports 5328 and 8328. `backend/retail/guard.py`
   refuses, by default, any seed, reset or migration target that is not marked
   retail — including any path containing `5318` or `5308`, and any database URL
   that names a source demo. No symlink points from retail state to a source
   path.

## 4. What is in the box

See `docs/RETAIL_DEMO_GUIDE.md` for the demonstration script, and
`docs/RETAIL_CONVERSION_INVENTORY.md` for what each source component became.

## 5. Where to look for what

| Question | File |
|---|---|
| What does this column mean, and how may I aggregate it? | `docs/RETAIL_DATA_DICTIONARY.md` |
| What exactly is in the scorecards? | `docs/RETAIL_MODEL_AND_TRANSFORM_SPEC.md` |
| How is ECL calculated? | `docs/RETAIL_ECL_METHODOLOGY.md` |
| What does Early Warning look for? | `docs/RETAIL_EWS_RULEBOOK.md` |
| What can What-If do, and what will it refuse? | `docs/RETAIL_WHATIF_SUPPORTED_OPERATIONS.md` |
| What did you assume, and what can this not answer? | `docs/RETAIL_ASSUMPTIONS_AND_LIMITATIONS.md` |
| Which test holds which requirement? | `docs/RETAIL_REQUIREMENT_TRACEABILITY.md` |
| What was actually run, and what failed? | `docs/RETAIL_UAT_REPORT.md` |
| How do I put our own data in? | `metadata/retail/retail_data_contract.json` |
| What was published, exactly? | `metadata/retail/retail_dataset_manifest.json` |

## 6. The numbers, as published

Read from `metadata/retail/retail_dataset_manifest.json`, which is the record of
what was actually written.

| | |
|---|---|
| Domain | **Cockpit Data** (`retail_cockpit`), one domain, one dataset |
| Dataset | `retail_facility_month`, version `r1.0.0-c1.0.0-s20260910` |
| Months | **25**, **August 2024 through August 2026** inclusive |
| Rows | **447,853** across the 25 months |
| Latest month | **19,745 facilities**, **14,251 customers** |
| Columns | **546** |
| Exposure at 2026-08 | **SAR 2,082,852,856** |
| Loss allowance at 2026-08 | **SAR 15,952,109** (coverage 0.766%) |
| Product mix at 2026-08 | Personal Finance 7,761 · Credit Card 6,532 · Auto Finance 3,301 · Home Finance 2,151 |
| Manifest hash | `375e3436dd600a1b` |
| Build time | 208 seconds, deterministic from seed 20260910 |

### Numerical reconciliation

| Check | Result |
|---|---|
| Weighted ECL identity, aggregate at 2026-08 | `0.60·base + 0.20·upturn + 0.20·downturn` = **SAR 15,952,108.84**, equal to the published weighted ECL |
| Final ECL identity | `weighted + overlay`, max row error **SAR 0.0000** |
| Scenario ordering, row-wise, every month | **0 violations** of `upturn ≤ base ≤ downturn` |
| Independent golden fixture (spec §11.5) | base **SAR 100**, upturn **SAR 75**, downturn **SAR 150**, weighted **SAR 105** — exact |
| ECL bridge, 2026-07 → 2026-08 | opening SAR 14,069,608.38 + contributions SAR 1,882,500.45 = **SAR 15,952,108.83** against closing SAR 15,952,108.84; unexplained residual **SAR 0.01** |
| Score reconstruction | `base_points + Σ points` reproduces the score to within **1e-6** on every published row of all eight models |
| What-If neutral parity | delta **−0.52 SAR** on a SAR 8,994,011.87 personal-finance baseline (−0.000006%) |
| Cross-module | What-If baseline equals the Cockpit total for the same population, to the halala |

### Scorecard monitoring, personal finance

2,553 applications counted once at origination, 2,447 distinct customers,
87 observed defaults. AUC **0.645**, Gini **0.290** (95% CI 0.162–0.412), KS
**0.243**. Calibration observed/expected **1.35** — the synthetic scorecard
under-predicts, which is a finding to discuss rather than one to hide.
Exclusions reported: 436,343 rows not at origination, 223,896 with an
incomplete follow-up window, 6,887 already in default.

### Early Warning, August 2026

8,943 alerts across 5,581 customers from 18 of the 20 rules, affecting
**SAR 984,232,144** of exposure (47.3%), counted once per facility. The two
rules that do not fire at this snapshot — over-limit activity and the
score-input quality exception — are exercised against constructed frames in
`tests/retail/test_ret_034_038_ews.py` so that neither is a dead control.

### What-If

| Scenario | Result |
|---|---|
| Neutral, whole book | reproduces the baseline |
| Personal finance, PD +20% relative | ECL SAR 8,994,012 → 10,161,669 (**+12.98%**) |
| Personal finance, PD +2 percentage points | ECL → SAR 15,088,559 (**+67.76%**) — different arithmetic, as it must be |
| PD +150% relative, stages frozen | SAR 30,286,559, stage mix unchanged |
| PD +150% relative, stages re-evaluated | SAR 36,914,029, 2,432 facilities migrate to Stage 2 |
| 164 credit-impaired facilities, PD +100% | **unchanged**, with the reason stated |
| The same facilities, recovery delay +6 months | +5.88% |

## 7. Test evidence

| Suite | Result | Where |
|---|---|---|
| Forty-question demonstration UAT | **40 passed, 0 failed** in 699s, against the running installation | `docs/evidence/retail_uat_questions.json` |
| Real-browser acceptance | **46 passed, 0 failed** in 92s, Chromium at three viewports, signed in | `docs/evidence/retail_browser_uat.json`, `docs/evidence/screenshots/` |
| Acceptance gates RET-001 to RET-060 | **360 passed, 0 failed, 0 skipped, 0 errors** in 527s | `tests/retail/`, `docs/evidence/gates.log`, `docs/RETAIL_REQUIREMENT_TRACEABILITY.md` |

## 8. What was NOT run, and what remains

**Not run — no AI provider key is configured in this environment.** The
model-written half of a Cockpit answer, the prose and the interpretation, was
not exercised end to end. Every figure the product shows comes from the
deterministic governed runtime, and that half is tested; the language layer is
not. This is a NOT RUN, not a pass.

**Remaining work, named rather than left to be discovered:**

1. **Playbook, Lenses and Planner seeded examples.** These modules are
   structurally intact and reachable, and their corporate sample content was not
   converted in this pass. They are not part of the demonstration script in
   `docs/RETAIL_DEMO_GUIDE.md`.
2. **Customer 360 depth.** The navigation slot is repurposed and the endpoint
   `GET /api/v1/retail/customer/{id}` returns the full retail position, history
   and alerts. The screen behind it still renders the previous module's layout.
3. **Affordability alert volume.** `RET-EWS-011` raises 3,377 alerts at
   2026-08. The rule is correct — a customer who took a second facility really
   has a higher debt burden than at the first one's origination — but comparing
   against origination rather than the prior month makes it fire broadly on a
   book where customers hold several facilities. The threshold is configurable;
   a prior-month comparator would be the better rule.
4. **Alembic migration for the retail namespace.** None was needed: the lake is
   file-backed Parquet and the catalogue is JSON. If the retail catalogue later
   moves into PostgreSQL, that becomes a migration and the graph must be
   inspected first.

## 9. The final commit

All three suites above were run against the code at the final commit on
`claude/funny-dirac-6n8f0o`, with a clean working tree. RET-060 checks exactly
that: it fails if any retail file is uncommitted while a completion claim is
being made, and it caught two such runs during this work.

## 10. What must not be claimed

This is a synthetic demonstration. It is **not** SAMA compliant, **not** ANB
approved, **not** auditor certified, and **not** an independent model
validation. The data describes no real customer, the scorecards are not any real
institution's models, the bureau signals are a synthetic proxy and not SIMAH,
and every threshold is a demonstration setting.

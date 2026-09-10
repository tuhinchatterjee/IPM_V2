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

# Retail conversion — source provenance and isolation record

Phase 0 of `docs/RETAIL_ONLY_MASTER_SPEC.md`. Written before substantial changes.
Gate: RET-001, RET-002, RET-003.

Recorded: 2026-09-10. All commands below were run read-only against the
repository before the retail branch was created.

---

## 1. What environment this work is actually running in

This conversion is being implemented inside a **Claude Code remote execution
container**, not on the user's own workstation. That fact is load-bearing for
Phase 0, so it is stated first and precisely:

| Observation | Command | Result |
|---|---|---|
| Only checkout on the machine | `ls /home /home/user` | `/home/user/IPM_V2` and nothing else |
| Listening TCP sockets | `ss -lntp` | **none** — no service is listening on any port |
| Application processes | `ps aux \| grep -E 'uvicorn\|node\|vite'` | **none** — only the session's own agent process |
| Filesystem search for a 5318/5308 install | `find / -iname '*creditprobe*' -o -iname '*5318*'` | only this repo, the uploaded spec, and unrelated Go test files |
| Git worktrees | `git worktree list` | one: `/home/user/IPM_V2` |

**Therefore: the frozen WHATIF_5318 and 5308 installations are not present in,
reachable from, or observable by this environment.** They live on the user's own
machine (PowerShell launchers `scripts/app-start.ps1`, `scripts/demo-start.ps1`
and the `windows-pilot-v1` tag indicate a Windows/desktop host).

This is the single strongest guarantee for spec requirement 9 and gate RET-002:
nothing done in this container can reach, read, write, restart or corrupt those
installations, because no path, socket, process or volume connects to them. The
only artefact this work produces outside the container is **one new Git branch
pushed to `origin`**, which is ordinary Git metadata and touches no running
installation. See §5.

---

## 2. What "WHATIF_5318" resolves to — and what is NOT proven

### 2.1 The literal string is not in the repository

`WHATIF_5318` was searched for across **every ref in the repository** (all 15
branches, all 4 tags), not just the checked-out tree:

```bash
for r in $(git for-each-ref --format='%(refname)'); do
  git grep -l -E "5318|5308|WHATIF_5318" "$r"
done
```

- The literal token `WHATIF_5318` appears in **zero** files at **zero** refs.
- Every `5318` / `5308` hit is a coincidental digit sequence inside large
  generated JSON data files (`docs/corporate_universe_build.json:
  "spectral_radius": 1.310530808`, `docs/whatif_reconciliation.json:
  "exposure": 25318.9`). None is a port, a hostname or a configuration value.
- A targeted search of launcher/config file types only
  (`*.sh *.ps1 *.bat *.cmd *.yml *.json *.env* *.toml`) for a port-shaped
  `5318` returned **no files at any ref**.

The committed launchers use ports **8050** (`app-start.ps1`), **8000 backend /
3000 frontend** (`demo-start.ps1`, `dev.ps1`). The `53xx` scheme is therefore a
**local, uncommitted convention on the user's machine**, not repository state.

### 2.2 What IS proven: the What-If lineage

Three "recovered" annotated tags were created on **2026-09-10** — the
specification's own date, and the date the user describes standing up frozen
presentations:

| Tag | Tagged commit | Tag message |
|---|---|---|
| `recovered-sep8-whatif` | `0558f267b1c9d0eb3583cf329aed817d3aa0e15d` | "Recovered Sep 8 advanced pre-architecture What-If" |
| `recovered-sep8-integrated` | `ffad3519ee46de7af518c65ebd5e4f1d94e7760e` | "Recovered Sep 8 pre-distributed integrated CreditProbe baseline" |
| `recovered-sep8-cockpit-v2` | `83b39a602eb430444f46d08aca4e595522f3b53f` | "Recovered Sep 8 Cockpit V2 historical build" |

`recovered-sep8-whatif` is **the only ref in the entire repository named for a
What-If installation**. It is the What-If member of a matched set of recovery
tags that corresponds to the user's description of two frozen presentations
(5318 and 5308).

Ref containment (`git branch -a --contains 0558f267`):

- contained in `origin/claude/what-if-analysis-rebuild`
- contained in `origin/claude/creditprobe-integration-plan-vyq22h`
- **not** an ancestor of `origin/main`

`origin/claude/what-if-analysis-rebuild` @ `80e74a4e1e5552e73c532849b72329008335b09f`
("Record the whole-repository regression, and what the six failures actually
are", 2026-09-08 23:42 +0000) is the tip of that lineage and **strictly contains**
the recovery tag.

### 2.3 The exact unresolved evidence — recorded, not guessed

The spec (§1.1) requires distinguishing "contains this commit" from "this was
the running build". That distinction **cannot be closed from this container**.
Specifically missing, and obtainable only on the user's own machine:

1. The `WHATIF_5318` launcher file itself (its port assignment and the worktree
   path it `cd`s into).
2. `git rev-parse HEAD` inside that worktree, and whether it is detached.
3. `git status --short` there — whether the running build has uncommitted changes.
4. Whether the running frontend is a live dev server or a previously built
   bundle (i.e. whether HEAD and the served build agree).
5. The database/upload/index paths that installation actually writes to.

**No branch was guessed to fill these gaps.** No unrelated or merely-newer
branch was adopted: `origin/main`, `IPM_V3`, and the ten other `claude/*`
branches were all rejected because none carries the What-If recovery marker.

### 2.4 The base actually chosen, and why

**Base commit: `80e74a4e1e5552e73c532849b72329008335b09f`**
(`origin/claude/what-if-analysis-rebuild`).

Reasoning, stated so it can be overridden:

- It is on the **proven What-If lineage**, and it **contains** the
  `recovered-sep8-whatif` recovery tag as a direct ancestor
  (`git merge-base --is-ancestor` confirms).
- Choosing the tip rather than the tag **cannot lose any of the user's What-If
  work**; choosing the tag would have discarded the twelve later What-If commits
  listed below, several of which are substantive correctness fixes
  (e.g. `b636a2a` "Keep a defaulted exposure at 100% through the What-If PD
  ceiling", `4684c0c` "Two floors that disagreed, and a buffer measured in the
  wrong units").
- It is **not** "the newest unrelated branch" the spec warns against. Nothing was
  merged, rebased, cherry-picked, or fetched-and-reset onto it.

The twelve commits between the recovery tag and the chosen base — the exact
delta the user can ask to drop if their frozen 5318 is pinned to the tag:

```
80e74a4 Record the whole-repository regression, and what the six failures actually are
4c2d51b Three clean readiness cycles, and the record of what each defect was
b3d54df Wait for the second card, not for a card
1c9720e One absent field took the whole thread down, and it should not have
4684c0c Two floors that disagreed, and a buffer measured in the wrong units
6c35c7b A narrowed table shows what was asked for, and the tests say what changed
b636a2a Keep a defaulted exposure at 100% through the What-If PD ceiling
5ca662c Stage 3 regression, the scale a risk person reads, and four browser journeys
bf87f3a Name the workbook's tabs for the person reading it, and explain its columns
ad86067 Answer the question about the book instead of naming a screen that would
b88e8b6 The scale ends in C, default is a state, and Stage 3 is measured at 100%
2f366dc One methodology identifier, and a refusal that says what was wrong
```

**If the frozen 5318 install is pinned to the tag**, the correction is one
command and no work is lost:
`git rebase --onto 0558f267 80e74a4e claude/funny-dirac-6n8f0o`.

---

## 3. The new retail branch

| Property | Value |
|---|---|
| Repository | `https://github.com/tuhinchatterjee/IPM_V2` (no credentials in URL) |
| Worktree | `/home/user/IPM_V2` (the container's only checkout) |
| Branch | `claude/funny-dirac-6n8f0o` |
| Base commit | `80e74a4e1e5552e73c532849b72329008335b09f` |
| Contains | `recovered-sep8-whatif` (`0558f267`) |

The branch name is the one this session is required to develop on and push to.
It previously pointed at `3855f9b` (identical to `origin/main`) and carried
**zero unique commits** (`git log origin/main..claude/funny-dirac-6n8f0o` was
empty) with a **clean working tree and empty stash list**, both verified before
it was re-pointed. No work was discarded. Its former remote counterpart had
already been deleted upstream (observed during `git fetch --prune`).

`git worktree add` was deliberately **not** used: this container holds a single
ephemeral clone with no frozen installation to protect, so a second worktree
would add sharing risk (§R6: worktrees share repository-level resources) without
adding isolation. Isolation is instead achieved by §4.

---

## 4. Mutable-state isolation

Every mutable path and port in this codebase is environment-configurable
(`backend/config.py`: `DATA_RAW_DIR`, `DATA_CURATED_DIR`, `DATA_ANALYTICS_DIR`,
`METADATA_DIR`, `UPLOAD_DIR`, `LOG_DIR`, `DATABASE_URL`, `API_PORT`, `PORT`).
The retail installation therefore takes a **separate namespace** rather than
sharing the source demo's:

| Resource | Source default | Retail installation |
|---|---|---|
| Analytics lake | `data/analytics` | `data/retail/analytics` |
| Curated layer | `data/curated` | `data/retail/curated` |
| Catalogue metadata | `metadata/` | `metadata/retail/` |
| Uploads | `uploads/` | `var/retail/uploads/` |
| Logs | `logs/` | `var/retail/logs/` |
| Database | source demo DB | `retail_cockpit` schema/DB, guarded (§4.1) |
| Backend port | 8000 | **8328** |
| Frontend port | 3000 | **5328** |

No symlink points from a retail path to a 5318/5308 path. The retail
installation does not inherit any source database URL.

### 4.1 Identity guard

`backend/retail/guard.py` refuses any seed / reset / publish whose target does
not carry the retail namespace marker, so a retail build command pointed at an
original demo target **fails safely instead of overwriting it** (RET-003).

---

## 5. Evidence that the frozen originals are unmodified

1. **Physical**: they do not exist in this container (§1). No filesystem path,
   socket, process handle or database connection reaches them.
2. **Git**: the recovery tags `recovered-sep8-whatif`,
   `recovered-sep8-integrated`, `recovered-sep8-cockpit-v2` and
   `windows-pilot-v1` are **not moved, deleted or re-pointed** by this work, and
   no branch other than `claude/funny-dirac-6n8f0o` is pushed. Their SHAs are
   recorded above and can be re-verified with `git rev-list -n1 <tag>`.
3. **No history rewrite**: no `filter-branch`, no force-push to any other ref,
   no amend of any commit that is not this branch's own.

A user-side re-verification, run on the machine that hosts the frozen installs:

```bash
git fetch origin --tags
git rev-list -n1 recovered-sep8-whatif      # expect 0558f267b1c9d0eb3583cf329aed817d3aa0e15d
git rev-list -n1 recovered-sep8-integrated  # expect ffad3519ee46de7af518c65ebd5e4f1d94e7760e
git rev-list -n1 recovered-sep8-cockpit-v2  # expect 83b39a602eb430444f46d08aca4e595522f3b53f
```

No secrets, tokens or `.env` contents are recorded in this document.

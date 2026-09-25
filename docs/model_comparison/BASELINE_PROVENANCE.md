# Baseline provenance: frozen AdvancedCockpit and the independent lab

Status: **P0 complete for the GitHub-tagged baseline.** One gap is open: the Mac working folder has not been compared against the tag (§5).

Recorded 2026-09-25 by the lab session. Every statement below comes from a
read-only command whose output is quoted or summarised here. The frozen
original was never launched, sourced, migrated or edited.

## 1. What the master prompt named, and what this session could reach

| Item | Master prompt | This session |
|---|---|---|
| Frozen source | `/Users/tuhinchatterjee/Desktop/IPM_V2-AdvancedCockpitv1` | **Not reachable.** The session runs in a cloud container, where `/Users` does not exist. |
| Lab destination | `/Users/tuhinchatterjee/Desktop/IPM_V2-AdvancedCockpitv1-QwenLab` | **Not reachable.** The lab was created as a fresh cloud clone instead (§3). |
| Lab branch | `experiment/frozen-cockpit-model-uat` (proposed) | The session's designated branch is `claude/amazing-bardeen-gkd63b`, and no other branch was created. |

## 2. Frozen identity: the evidence

The repository `github.com/tuhinchatterjee/IPM_V2` carries an **annotated tag**:

```
tag cockpit-round-h-live-pass-2026-09-23
object 245c50e45786c6e0c866b281f9dd74da17d160b5
tagger Tuhin Chatterjee <tuhinchatterjee@Tuhins-MacBook-Air.local>  (epoch 1790139774 +0400)

AdvancedCockpit Round H live UAT passed 2026-09-23
```

- `245c50e` is the head of `claude/cockpit-single-agent-v4-h8fsbq` ("Cockpit V4").
- `docs/cockpit_v4/ROUND_H_REPORT.md` at that commit reads: "Standalone AdvancedCockpit only. No Retail Demo integration."
- The folder name alone was **not** taken as proof. The identity rests on three things:
  - the tag message;
  - the tagger host, which is the user's Mac;
  - the What-If branch forking exactly here (§4).

**Frozen baseline = `245c50e45786c6e0c866b281f9dd74da17d160b5`**, and the frozen engine is `backend/cockpit_v4/`.

## 3. The independent lab

| Check | Result |
|---|---|
| Lab path | `/home/user/IPM_V2`, a fresh clone of the GitHub repository made at session start. It is not a linked worktree of any Mac checkout. |
| Created by | `git merge --ff-only cockpit-round-h-live-pass-2026-09-23` on `claude/amazing-bardeen-gkd63b`. The branch had been at `main` (3855f9b), which is an ancestor of 245c50e, so this was a pure fast-forward. Nothing was reset or force-pushed. |
| `git worktree list` | One entry: `/home/user/IPM_V2 245c50e`. |
| Shared object store | None; `.git/objects/info/alternates` is absent. |
| Symlinks | None in the frozen tree (no `120000` modes in `git ls-tree`), and none on disk outside `.venv` and `node_modules`. |
| Editable installs | None. The lab `.venv` (Python 3.12.3, built with `uv venv`) installs `requirements.txt` exact pins plus pytest and ruff. The code is imported from the lab path through `PYTHONPATH`/pytest `pythonpath`. |
| Frozen data | Synthetic releases were regenerated inside the lab by the frozen seeders, from generators in the frozen commit. No bank or user data was involved. |

Releases published in the lab:

| Release | Fingerprint | Contents |
|---|---|---|
| `v4-saudi-corporate-20q-v4` | `c79d0fdf8753576f` | 4 relations, 1,260,267 rows, 2021Q3..2026Q2 |
| `v4-saudi-retail-20m-v5` | `c23a15d78ba88d39` | 4 relations, 1,888,134 rows, 2025-01..2026-08 |
| `v4-saudi-20q-v1` | not recorded | Test-suite release, 11 relations, 20 quarters |

Both fingerprinted releases re-verified with `seed_domains.py --verify`. All three live under the gitignored `data/cockpit_v4_lake/` and `data/cockpit_v4/`.

## 4. Excluded: the latest What-If development

These refs were inspected **only as ref metadata** (`git ls-remote`, `git log -3`, `git merge-base`). No file in them was read.

| Ref | Head | Relationship |
|---|---|---|
| `claude/advanced-cockpit-whatif-v1` | c40c7e7 (2026-09-25 13:48) | `merge-base` with the frozen tag = **245c50e**. It adds 4 commits ("What-If P0–P1" … "P4: Delta and Method 3"). |
| `claude/what-if-analysis-rebuild` | 80e74a4 | Excluded |
| tag `recovered-sep8-whatif` | 0558f26 | Excluded |

Nothing from these refs is imported, merged, launched or used for test traffic. The lab tree matches 245c50e exactly outside the lab-owned allowlist; `PROTECTED_MANIFEST.json` proves it.

## 5. Open gap: the Mac folder itself

The tag proves which commit was frozen. It cannot prove that the Mac folder `IPM_V2-AdvancedCockpitv1` has no uncommitted edits on top of that commit. To close the gap, run on the Mac (read-only):

```bash
git -C ~/Desktop/IPM_V2-AdvancedCockpitv1 rev-parse HEAD      # expect 245c50e45786…
git -C ~/Desktop/IPM_V2-AdvancedCockpitv1 status --porcelain  # expect empty
```

If either result differs, the lab baseline and the Mac folder disagree. The lab must then be re-based on whatever the user confirms is frozen.

## 6. Protected manifest

`scripts/model_lab/protected_manifest.py --write` hashed every file tracked at 245c50e outside the lab allowlist:

| Measure | Value |
|---|---|
| Protected files | 1,775 |
| Aggregate SHA-256 | `fc1d91c3d50dfe8b90539ca48b9acd3548bc41849592cd8888a7a240519d07d5` |
| Core engine files | 334 (`backend/cockpit_v4`, `backend/llm`, `backend/cockpit_agentic`, cockpit-v4 frontend, `scripts/cockpit_v4`, `tests/cockpit_v4`, `config/cockpit_v4`) |
| Core aggregate | `8c0032cf0338df3ddb548a84a22ff6950df40044c6f1f04c94cc9ca7b2fe989e` |

- Lockfile SHA-256: see `PROTECTED_MANIFEST.json → lockfiles`. For example, `requirements.txt` = `fd9dd717…`.
- `--check` compares Git blob ids through Git's own clean filters. Otherwise the `.gitattributes eol=crlf` conversion of 12 `.ps1` files at checkout would be misread as edits.

Lab-owned allowlist, the only paths this task writes:

```
backend/model_lab/  scripts/model_lab/  tests/model_lab/
frontend/src/app/cockpit/lab/  frontend/src/components/model-lab/
docs/model_comparison/  profiles/  launchers/  artifacts/model_comparison/ (gitignored)
```

## 7. Incident: a frozen seeder wrote into a tracked path

Running the frozen `scripts/cockpit_v4/seed_release.py --release v4-saudi-20q-v1`, which the frozen test suite requires, **rewrote three tracked files**:

- `docs/cockpit_v4/evidence/coverage_summary.json`
- `docs/cockpit_v4/evidence/release_manifest.json`
- `docs/cockpit_v4/evidence/release_summary.json`

This is frozen seeder behaviour (its default `--refresh-evidence`), not lab code. Handling:

1. The diff was preserved at `artifacts/model_comparison/incidents/seed_evidence_write.diff`.
2. The three files were restored from Git with `git checkout -- docs/cockpit_v4/evidence/`, which undid this task's own write.
3. The protected manifest then passed.

Future lab reseeds must pass `--no-evidence`; the lab launcher does. No other frozen path was written.

## 8. Host preflight (this session)

| Item | Observed |
|---|---|
| Host | Cloud VM, Linux 6.18 x86_64, Intel Xeon @ 2.80 GHz, 4 vCPU |
| Memory / disk | 15 GiB RAM; 30 GiB free disk |
| GPU | None (`nvidia-smi` absent) |
| Local model runtimes | None (`ollama` and `vllm` not installed) |
| Credentials | `COCKPIT_ANTHROPIC_API_KEY` **absent**. The session's own `ANTHROPIC_BASE_URL` belongs to the coding agent and is not used by the lab. |
| Python / Node | 3.12.3 (lab venv); Node 22.22.2 |
| Other workloads | None of the user's; this is a single-purpose container |

It follows that no live Opus run, no local candidate model and no GPU profile can run in this session. That is P9's blocker, stated in `LIVE_UAT_REPORT.md`.

The master prompt's "16 GB M3 Mac" is **not verified**. The Mac preflight command is `python scripts/model_lab/preflight.py` (read-only).

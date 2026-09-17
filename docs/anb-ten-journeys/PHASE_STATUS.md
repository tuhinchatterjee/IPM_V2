# CP-RA-V2 — phase status

Implementation of `docs/anb-ten-journeys/SPECIFICATION.txt` (ten complete Saudi
retail investigation journeys) and its worked fixture workbook.

This file is the running record the specification asks for in §1: after each
phase, the files changed, the migrations, the tests, the data hashes and the
remaining blockers. It is updated in the same commit as the phase it describes,
so a reader never has to trust a claim that is not beside the work.

| Phase | Name | State |
|-------|------|-------|
| P0  | Baseline audit and isolation            | COMPLETE |
| P1  | Identity, metric and cohort contracts   | NOT STARTED |
| P2  | Ten coherent synthetic episodes         | NOT STARTED |
| P3  | Atomic Cockpit/EWS publication          | NOT STARTED |
| P4  | Ten evidence-driven cards and drawers   | NOT STARTED |
| P5  | Stateful investigation threads          | NOT STARTED |
| P6  | Versioned policy action engine          | NOT STARTED |
| P7  | Borrower 360 investigation workspace    | NOT STARTED |
| P8  | Stage-aware Excel evidence exports      | NOT STARTED |
| P9  | Borrower 360 to What-If                 | NOT STARTED |
| P10 | Real-browser, data and regression       | NOT STARTED |
| P11 | Freeze and handoff                      | NOT STARTED |

---

## P0 — Baseline audit and isolation

### What the accepted baseline actually is

The specification (§1.1) warned that the supplied report [P01] describes a
branch state rather than proving it, and that an older launch log showed
`59e5a301`. Both were checked against the repository rather than assumed.

| Fact | Verified value |
|------|----------------|
| Accepted ANB branch | `claude/exciting-archimedes-npzji5` |
| Its full head SHA | `3ac4489fd4e777b0fc158f2fd08f5104006a631b` |
| Local head == `origin/` head | yes (`git ls-remote` agrees) |
| Commits above the approved retail baseline | 12 |
| Approved retail baseline | `c0db151f62c34e84b4f7df5faf81e5c9b0c9f647` |
| `59e5a301` from the older launch log | `59e5a301b2155570d0cad8e2eda1ffc9f210d477`, an **ancestor** of the head — an earlier commit on the same branch, not a divergent build |
| `origin/main` merged into this work | no. `main` was already an ancestor of `c0db151f` before any of this work existed |
| Working tree | clean; no stash; no untracked files to preserve |

So the report's "12 commits" is accurate, the older launch log is explained
rather than contradicted, and the new work starts from the verified head —
not from `c0db151f`, not from `59e5a301`, not from the Planner branch.

### Isolation

| Item | Value |
|------|-------|
| Implementation branch | `claude/anb-ten-journeys`, created from `3ac4489f` |
| Implementation database | `creditprobe_anb_v2` (created empty, migrated to head) |
| Implementation environment file | `.env.anb2` (git-ignored by the existing `.env.*` rule) |
| Implementation ports | 5334 frontend / 8334 backend |
| Untouched | `creditprobe_retail` (the accepted ANB demo database in this container) |
| Untouched | 5328/8328, 5330/8330, 5332/8332 and Docker database ports 5528/5538/5548/5558/5568 |

A separate branch rather than further commits on `claude/exciting-archimedes-npzji5`
is what §1.1 requires: the accepted ANB demo must "remain untouched until
explicit acceptance of a new version", and a Mac worktree tracking that branch
would pick this work up on its next pull if it were pushed there.

### Where this container is, and is not

This is a remote Claude Code container, not the user's Mac. It holds its own
clone and its own PostgreSQL. It therefore cannot see, start, stop or damage
the Mac's 5328/8328 presentation, the `~/Desktop/IPM_V2-ANB-Demo` worktree or
the Docker database ports — and it does not claim to have done so. The local
launcher P11 asks for is delivered as a setup artifact for the user to run,
per §1.1's last sentence.

### Baseline manifest

| Artefact | Value |
|----------|-------|
| Alembic head | `0042` (42 migration files) |
| Governed dataset registrations | 5: `retail_facility_month`, `retail_ews_score`, `retail_early_warning`, `retail_credit_scorecard`, `retail_whatif` |
| `metadata/retail/catalog.json` | sha256 `c6bd68bebe7eb885…` |
| `metadata/retail/retail_data_contract.json` | sha256 `3edc7abda9855cad…` |
| `metadata/retail/retail_dataset_manifest.json` | sha256 `e69320b81db63db6…` |
| `config/retail_demo_config.json` | sha256 `955991f23fc15748…` |
| Generator / seed / as-of | `retail-gen-1.2.0` / `20260910` / `2026-08` |
| Published months | 25, `2024-08` … `2026-08` |
| Latest month | 59,412 facility rows, 42,898 distinct customers, content hash `05615a1af58d13d3…` |
| Analytics lake on disk | 2.3 GB across 6 datasets |
| Risk cases in the accepted demo database | 7, in 3 `about` kinds |

### Existing screens and route map (what this work extends, not replaces)

| Surface | File |
|---------|------|
| Cockpit / Requires Attention | `frontend/src/components/attention/requires-attention.tsx` |
| Right-hand drawer | `frontend/src/components/attention/case-drawer.tsx` |
| Thread case context | `frontend/src/components/attention/case-context.tsx` |
| Investigation thread | `frontend/src/app/investigations/[id]/page.tsx` |
| Saved investigation | `frontend/src/app/investigations/saved/[id]/page.tsx` |
| Borrower 360 | `frontend/src/app/borrower-360/page.tsx` |
| Early Warning | `frontend/src/app/early-warning/page.tsx` |
| What-If | `frontend/src/app/what-if/page.tsx`, `frontend/src/app/early-warning/whatif/[selectionId]/page.tsx` |
| Risk case API | `backend/api/routers/cases.py` |
| Retail API | `backend/api/routers/retail.py` |
| Exports API | `backend/api/routers/exports.py` |
| What-If API | `backend/api/routers/whatif.py` |
| Risk case contract | `backend/agentic/cases.py` (`Draft`, `upsert`, `dedupe_key`) |
| Retail review that raises cases | `backend/retail/review.py` |
| Accepted Alpha case figures | `backend/retail/anb_demo.py`, `backend/retail/anb_answers.py` |
| Generator | `backend/retail/generate.py` |

### Launcher ownership

`launchers/anb/start-anb.command` and `stop-anb.command` own **only** pids they
themselves recorded in `var/anb`, and stop a recorded pid together with its
descendants. They are bound to 5330/8330. They are left exactly as they are;
the new build gets its own launcher in P11 rather than a change to these.

### Blockers

None. No destructive or ambiguous baseline decision was encountered.

### Same-environment test baseline

Re-run at the verified SHA in this container, against `creditprobe_test`:

| Suite | Result |
|-------|--------|
| `tests/retail/test_ret_anb_card_investigation.py` (the accepted Alpha gates) | **40 passed, exit 0** |

The report's twenty attributed retail failures are not restated here as fact.
They are a claim to be re-proved against this same environment and the same
data in P10, where the specification requires attribution rather than a
green-suite assertion.

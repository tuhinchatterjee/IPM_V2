# P0 — Baseline provenance (Guided Risk Workspace round)

Controlling specification: `CreditProbe_Guided_Risk_Workspace_Master_Prompt_v3.1_30_Sep_2026.docx`
(read end to end before any edit; extracted text kept outside the repository).

Every fact below was verified in this container on 30 Sep 2026 by a command,
not taken from an earlier narrative. Where the specification's recorded facts
and the repository disagree, the repository wins and the disagreement is stated.

---

## 1. Branches, checkpoints and the productization parent

| Item | Specification says | Verified |
|---|---|---|
| Frozen H1 | tag `whatif-candidate-h1` → `b2a05671da6d547389be0e95b5ea4e35d30e9b6d` | **Verified.** `git rev-parse whatif-candidate-h1^{commit}` = `b2a05671…`; also head of `origin/claude/advanced-cockpit-whatif-v1`. Not moved, not amended. |
| Measured H2 | `feb80f58982addf6e9474200b22451d1e303d276` | **Verified.** Head of `origin/claude/advanced-cockpit-whatif-h2-uat-fix`, 28 Sep 2026. `git merge-base --is-ancestor b2a05671 feb80f58` → true (H1 is H2's parent). |
| H3 method-selection branch | `claude/advanced-cockpit-whatif-h3-method-selection`, use it if it exists | **Does not exist** on the remote (`git ls-remote origin` lists 27 heads; none is H3). Per §4, the full H3 requirement (METHOD_SELECTION gate, no silent Delta) is implemented in this round before any workbench/visual feature that executes a scenario. |
| Productization parent | the latest verified What-If descendant | **H2 `feb80f58`** — no descendant of H2 exists on any remote branch. |
| Target branch | `claude/advanced-cockpit-whatif-v2-productization` | This session is bound to the designated branch **`claude/eager-keller-7ue2yk`** and may not push to any other branch without explicit permission. The designated branch was **fast-forwarded** from `main` (`3855f9b6`, an ancestor of H2) to H2 `feb80f58`; no force-push, no history rewrite. It plays the role of the productization branch; the mapping is recorded here and in the ledger. |
| Working tree at parent | — | Clean (`git status --short` empty) at `feb80f58` before any write. |
| Tags | no tag this round until live Mac UAT passes | Existing tags `cockpit-round-h-live-pass-2026-09-23`, `recovered-sep8-*`, `whatif-candidate-h1`, `windows-pilot-v1` untouched. **No tag is created in this round.** |

`main` (`3855f9b6`) is an ancestor of H2, so H2 contains everything on `main`.

## 2. Runtime prerequisites in this container

| Prerequisite | State |
|---|---|
| Python ≥ 3.12 (`pyproject.toml requires-python`) | `/usr/bin/python3.12` (3.12.3). The container's default `python3` is 3.11.15 and **cannot** install the pinned `numpy==2.5.0`, so it is not usable for the accepted runtime. |
| Accepted runtime environment | `/home/user/.venv312` (outside the repository) — `requirements.txt` exact pins + pytest/ruff/httpx. |
| What-If candidate environment | `.venv-whatif` (gitignored) — `requirements.txt` then `requirements-whatif.txt` pins (xgboost 3.0.2, lightgbm 4.6.0, scikit-learn 1.6.1, shap 0.47.1, pandas 2.2.3, numpy 2.2.4, pyarrow 19.0.1). |
| Frontend | Node v22.22.2; `npm ci` in `frontend/` → exit 0; `node_modules/.bin/next` present. |
| Browser | Chromium under `/opt/pw-browsers`; Playwright importable from `/opt/node22/lib/node_modules/playwright`. |
| Provider credential | `COCKPIT_ANTHROPIC_API_KEY` **MISSING** here (checked as PRESENT/MISSING only; no key read or printed). Live-provider work is BLOCKED in this container; every journey here is MODEL MOCK. |
| Mac launch environment | Not reachable from this Linux container (`/Users/...` absent). |

## 3. Published books — rebuilt here, and what "unchanged" can mean

The books are **not in git** (`.gitignore`: `data/cockpit_v4_lake/`, `data/cockpit_v4/`, `artifacts/whatif/*/*.pkl`). A fresh checkout has no data, so they were built with the repository's own seeded generators before any code edit:

```
/home/user/.venv312/bin/python scripts/cockpit_v4/seed_release.py --release v4-saudi-20q-v1 --no-evidence
/home/user/.venv312/bin/python scripts/cockpit_v4/seed_domains.py
.venv-whatif/bin/python scripts/whatif/seed_candidate.py --domain all
.venv-whatif/bin/python scripts/whatif/train_emulator.py --domain all
.venv-whatif/bin/python scripts/whatif/seed_candidate.py --domain all --overwrite
/home/user/.venv312/bin/python scripts/whatif/build_sensitivities.py      # "against the published release: matches" (both books)
```

| Release | Role | Recorded fingerprint (earlier container) | Byte fingerprint here | Content digest here (portable) |
|---|---|---|---|---|
| `v4-saudi-corporate-20q-v4` | accepted Corporate | `e37236d0f6d4e494…` | `c79d0fdf8753576f…` | `40c05896f0ef2f17` |
| `v4-saudi-retail-20m-v5` | accepted Retail | `a1e797dcc73236b7…` | `c23a15d78ba88d39…` | `54b77d6d0baf4a49` |
| `v4-whatif-corporate-20q-s1` | What-If candidate Corporate | `3b101bd41465fbe1…` | **`3b101bd41465fbe1…` — identical** | `12f62766edcc55a7` |
| `v4-whatif-retail-20m-s1` | What-If candidate Retail | `98b494ae2721bd53…` | **`98b494ae2721bd53…` — identical** | `85011644af2bd351` |
| `v4-saudi-20q-v1` | legacy compatibility release (V3 namespace) | — | built | — |

**Finding (not hidden):** the two What-If candidate books reproduce their recorded byte fingerprints exactly. The two accepted books do **not**: rebuilt with the pinned `requirements.txt` (pandas 3.0.3 / pyarrow 24.0.0 / Python 3.12.3) they fingerprint `c79d0fdf…`/`c23a15d7…`, and rebuilt a second time with the candidate environment (pandas 2.2.3 / pyarrow 19.0.1) into a scratch lake they fingerprint `82f0a483…`/`129030d3…`. The byte fingerprint hashes Parquet bytes, which encode writer version and layout; `docs/cockpit_v4/RELEASE_HISTORY.md` ("Checking a release on your own machine") documents exactly this non-portability. No content digest was ever recorded for the accepted books, so their values cannot be proven equal to the earlier container's either way. Consequences, stated as decisions:

1. The accepted books in this container are what this round must not change. Their byte fingerprints **and** portable content digests above are the P0 reference; the final gate re-verifies both (`lake.verify` + `release_report.py`).
2. Tests that hard-code the earlier container's accepted fingerprint (`test_whatif_candidate_release.py`) will fail here for this environmental reason; they are reported as pre-existing environment failures in the baseline regression, not relabelled and not edited.
3. Nothing in this round writes to a published release.

### ML emulator artifacts
`train_emulator.py` refitted both emulators here. Blend weights reproduced exactly (Corporate xgboost 0.767 / lightgbm 0.000 / additive_log 0.233; Retail xgboost 0.000 / lightgbm 0.342 / additive_log 0.658) and all gate verdicts reproduced: **Corporate G1 0.0189, G2 0.0113, G3 0.0234, G4 0.0537 — all PASS; Retail G1 0.0443, G2 0.0127, G3 0.0350 PASS, G4 0.3436 vs 0.15 FAIL.** Gate values differ from the committed `blend.json` only in the 15th–16th significant digit; the immaterial (weight 0.000) lightgbm component and Retail's additive_log component hash differently (library build nondeterminism). The committed `artifacts/whatif/*/blend.json`, sensitivity cards and evidence were **restored with `git checkout`** rather than overwritten; `ml/infer.py` does not verify component hashes, so the locally refitted `.pkl` files serve the committed gate record. Retail Method 2 remains **UNAVAILABLE** (G4 fails) and nothing in this round changes that.

## 4. Protected-core status at the parent

* `scripts/whatif/protected_hashes.py --check` against the accepted baseline `245c50e`: **40 changed, 42 removed, 25 added** — full output in `evidence/p0_protected_hashes_vs_245c50e.txt`. The 18 changed *code* files are exactly the H1/H2 authorised set recorded in `docs/whatif/BASELINE_AND_EXTENSION_MAP.md` (app, axis, context, contracts, display, domain_resolver, domains, execute_tool, export, finalization, precision, routes, schema, worker; reducer.ts, reducer.test.ts, thread-view.tsx, visuals.tsx). The 22 changed data files, 42 removed (older releases not rebuilt here) and 25 added (candidate books) are the environmental effect described in §3. That manifest is **not regenerated**.
* Round-specific baseline: `scripts/guided_workspace/protected_baseline.py --write` captured **171 protected files at H2** into `docs/guided_workspace/PROTECTED_FILES_H2.sha256` before the first code edit; `--check` → `0 changed, 0 removed, 0 added`. Every later difference must be justified in `PROTECTED_EXTENSION_MAP.md`.

## 5. Accepted architecture seams that must remain unchanged

| Seam | Where | Rule this round |
|---|---|---|
| Provider abstraction | `backend/llm/base.py`, `backend/llm/anthropic_provider.py`, `backend/cockpit_v4/provider.py` (`Analyst`) | Recorder is passive; request bytes/order/tool choice unchanged. |
| Single-agent orchestration | `orchestration.py`, `worker.py`, `action_state.py`, five-tuple `TOOL_NAMES` | No sixth tool, no second orchestrator. |
| Query validation / repair | `sql.py`, `sqlbind.py`, `execute_tool.py`, `derivation.py`, `finalization.py` | Untouched except where a named requirement forces it. |
| Budgets | `budgets.py` | Untouched. |
| Trace | `events.py`, `run_store.py`, `governance.py` | Extended by new records beside it, not rewritten. |
| Corporate/Retail resolver | `domains.py`, `domain_resolver.py`, `catalog.py` | Reused read-only. |
| Governed exports | `export.py` | Reused. |
| Scenario engine | `backend/cockpit_v4/scenario/*` (not in the protected glob) | Extended in place; one engine for chat and workspace. |

## 6. Inventory at the parent (what exists, what does not)

| Area | State at H2 |
|---|---|
| What-If engine | `backend/cockpit_v4/scenario/` (~16k LOC): typed spec + digest confirmation, cohort freeze (predicate + membership hash), Delta (proportional on booked ECL — **correct semantics**, `delta.py:3-5`), ML emulator (gated), user-defined, Shapley/sequential attribution with explicit residual, ledgers, 20-MEV registry + fitted sensitivities. |
| Method selection | **Defective (UAT-01 reproduced in code):** `bridge._methods` returns `(DELTA,)` when no method is given (`bridge.py:304-309`); `ScenarioSpec.methods` defaults to `(DELTA,)` (`spec.py:213`, `:514`); `preview.build` walks through METHOD_SELECTION without stopping (`preview.py:149-156`). |
| Scenario lineage / stacking | Absent. One scenario per thread (`thread_context` upsert); no parent scenario id; no baseline choice. |
| Dual-scope decomposition | Absent. One cohort-level attribution; book-level only as before/after totals (`results.Summary`). |
| Macro / rating / score execution | Sensitivities fitted but `sensitivity.artifact.translate()` and `mappings/*` have no runtime caller; rating/score fields have no executing method. |
| Plotly | Not a dependency. V4 answers draw hand-written SVG; legacy pages use recharts. |
| What-If workbench | None. `/stress` is the legacy Stress Testing page (main backend only; makes no call in a V4 runtime). |
| Requires Attention | `attention_v2.py`: deterministic ranked segment cards (≤5) + ECL highlights; one action ("Investigate further"). |
| Lenses | Legacy main-backend lenses only (`backend/services/lenses.py`); unusable in a V4 runtime (`NotInThisRuntime`). |
| Metric catalogue | None. |
| Monitoring Centre / alerts | None. |
| Messages | V4 `collaboration.py`: shares of `saved_analysis`/`investigation` only; `notifications` outbox; `/inbox`. |
| Scheduler | V4 worker/supervisor daemon threads (run queue); no periodic scheduler in the V4 runtime. |
| Trace | Persisted run events + messages history + per-call metadata report; **system blocks and tools actually sent are not persisted**; no UI shows any LLM payload. |
| AI Model Lab | **Does not exist** on H2 or any remote branch (searched every branch). "Model Lab" in the product is the Early Warning statistical lab. |
| Open-weight adapter | None on the V4 path (`service.resolve_provider` accepts only `anthropic`). |
| Mac launchers | START/STOP/STATUS for V4; two What-If START launchers; no SETUP/INSTALL launcher. |

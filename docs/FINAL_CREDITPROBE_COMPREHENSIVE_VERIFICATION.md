# CreditProbe — comprehensive verification

**STATUS: `LOCAL_RUNTIME_VERIFICATION_REQUIRED`**

Verified at branch `claude/vigilant-darwin-eohyi1`, working tree clean, local
and remote identical, Alembic single head `0029`.

This status is the honest one and is chosen over the two better-sounding ones
above it for reasons that are facts about this environment, not judgements:

* **`RELEASE_CANDIDATE` is NOT claimed.** It requires Docker verification and
  live-AI verification. Neither has occurred. `docker info` reports no daemon
  in this sandbox, and no Anthropic key is configured — nor would a live call
  be permitted here.
* **`LIVE_AI_VERIFIED` is NOT claimed.** It requires the designated
  real-provider local workflow (`scripts/verify-live-ai.ps1`) to have been
  run. It has not been. Every AI-shaped test in this repository ran against
  fake providers and deterministic fixtures.

Both outstanding steps, and what a pass looks like for each, are in
`WINDOWS_LOCAL_VERIFICATION.md`.

---

## What was built in this phase

| | |
|---|---:|
| Commits since `d7c910f` | 9 |
| Files changed | 45 |
| New backend modules | 5 |
| New test files | 6 |
| New tests | ~210 |
| Total tests collected | 5,823 |
| Test suite result | **exit 0, zero failures** |

Five new backend modules:

* `backend/corporate/graphmath.py` — integrated ownership, control closure,
  ownership chains, connected groups, eight interdependence predicates
* `backend/corporate/network.py` — DebtRank, PageRank, betweenness, Louvain,
  Network Risk Score, similarity, path confidence
* `backend/corporate/graphquality.py` — fifteen checks that block
* `backend/corporate/graphsummary.py` — the derivation that populates the
  Borrower 360
* `backend/corporate/service.py` + `pack.py` + the API router and screen

## Every gate, and its result

| Gate | Result |
|---|---|
| `ruff check backend tests scripts` | PASS |
| `pytest tests -q` | PASS — 5,823 collected, exit 0 |
| `scripts/check_decimals.py` | PASS — 49 allowed with a reason, 0 unexplained |
| `scripts/feature_matrix.py --check` | PASS |
| `npx tsc --noEmit` | PASS |
| `npx eslint` | PASS |
| `npx next build` | PASS |
| `scripts/browser_acceptance.py --start` | PASS — 956/956, 4 viewports, 17 screens |
| `scripts/route_crawl.py --start` | PASS — 153/153, 3 roles, 6 expected refusals |
| `alembic heads` | PASS — single head `0029` |
| `scripts/build_corporate_universe.py` | PASS — 16 quarters, 22 datasets |
| Docker | **NOT VERIFIED IN CLAUDE SANDBOX** |
| Live AI | **NOT VERIFIED** |

## The defects this phase found and fixed

Every one was found by a check written in this phase, not by inspection.

1. **1,303 of 2,274 guarantee edges pointed at a node that did not exist.**
   `FACILITY` was a declared node type and `COVERS` edges always pointed at
   facility ids, but the node table never contained them. Invisible to every
   edge-first query, which is all of them except a node-first traversal.
   Found by `GQ-04` on its first run.
2. **`FUNDED_BY` drew funding channels with replacement**, so a borrower
   could be funded by the same channel twice — an assertion that says nothing
   and double-counts wherever funding edges are aggregated. Duplicates fell
   from 1.34% to 0.07%. Found by `GQ-08`.
3. **`group_id` and `group_name` left the snapshot as blank strings**, not
   sentinels, because the filler tested for null and the customer master
   writes `""`. The exact "blank reads as a measurement" failure the module
   exists to prevent, in the one place nobody looked.
4. **Three borrowers displayed the identical trading name and alias.** The
   generator stripped the disambiguating suffix from the name a screen
   actually shows, undoing the work of adding it.
5. **A full legal name resolved nothing.** Names share stems, so a pure
   substring match returned every longer sibling and resolved none of them.
6. **DebtRank rebuilt a 2,960 × 2,960 matrix once per seed** — the entire
   cost of the all-seeds sweep, and none of it arithmetic anyone needed.
7. **A Parquet write failed on a column holding both floats and a sentinel.**
   The fix was not to drop the sentinels: the analytical dataset keeps its
   numbers numeric with parallel status columns, and the snapshot renders
   them back into one displayable string.
8. **`graph_dq_status` read DEGRADED for all 3,253 borrowers** because
   portfolio-wide flags reached a per-borrower field. A status that reads the
   same for every row tells a reviewer nothing.
9. **3,020 of 3,253 borrowers were labelled SUBSIDIARY** because "controlled
   by someone" was read as a corporate parent-subsidiary relation. A company
   owned by its founder is standalone.
10. **`corporate_connected_group` was not a governed purpose**, so every
    graph analysis was refused at the authority layer — the analyses existed,
    were correct, and could not run.

## The bad-patch audit

`docs/BAD_PATCH_AUDIT.md` covers all nine commits. Its central finding:

> **No legacy assertion was changed.** Every test file in the window is new
> except `tests/corporate/conftest.py`, which is 29 insertions and zero
> deletions.

No widened tolerance, no new xfail, no linter exclusion beyond one allowlist
entry that states its reason in the allowlist itself, no canned answer, no
inflated retrieval budget, no removed threshold, no authorization bypass, no
stubbed browser behaviour.

Three findings, all fixed: a skip that could hide a missing lake (now two
tests that FAIL), a missing confidence counted as zero in a mean, and a
frontend catch that rendered a refusal and a failure identically.

## What is honestly not built

Stated as absences of work, not as things that went unchecked.

* **~33 AI Brain concepts for graph semantics** — not built.
* **10 Investigation Blueprints** — not built.
* **Development and sealed-holdout teaching coverage for the graph topics** —
  not built. The teaching *vocabulary* is in place: 38 measures and
  dimensions were added and all 46 governed datasets now have at least one of
  each, so no governed dataset is unteachable.
* **Remaining Borrower 360 interactions** — pinning, saved cohorts, the Data
  Builder graph-domain viewer.
* **Docker** — not verifiable here.
* **Live AI** — not verifiable here, by instruction.

## The eleven governance statements

1. No live Anthropic call was made. No API key was inspected or printed. No
   credits were consumed. Every AI-shaped test used fake providers and
   deterministic fixtures.
2. Nothing was merged to `main`. Nothing was force-pushed. No history was
   rewritten. No pull request was created.
3. Every generated row carries `origin = SYNTHETIC_DEMO`, and every API
   response and every export carries the not-client-data statement. Nothing
   is presented as client data.
4. No test was changed to match an implementation. No legacy assertion was
   weakened, deleted or replaced.
5. No numeric tolerance was widened. No failure was converted to a skip. No
   xfail was added.
6. No file was excluded from a linter or scanner. The one decimal-contract
   allowlist entry states its reason in the allowlist itself, and the
   forbidden alternative — hiding the format string behind a variable — was
   not used.
7. No question is hard-coded, no result is canned, and no exception is caught
   and ignored. The two broad handlers added convert a raising check into the
   most severe verdict the module has, and are pinned by a test.
8. No retrieval budget was inflated. No data-quality rejection was hidden. No
   threshold was removed or loosened.
9. No authorization was bypassed. Four new permissions are enforced and each
   is exercised as all four roles with the status code read.
10. B54's caveats travel in the code, the payload, the screen and the export:
    graph connectivity is not regulatory connectedness; control closure and
    proportional ownership differ by design; DebtRank is not capital or ECL
    methodology; the Network Risk Score is a ranking, not a probability;
    synthetic performance is not empirical validation; entity-resolution
    errors propagate downstream and the weakest-evidence confidence says so.
11. Regulatory thresholds from the framework document are labelled
    UNVERIFIED REGULATORY PARAMETER wherever they appear, and are not
    operationalised as current binding law.

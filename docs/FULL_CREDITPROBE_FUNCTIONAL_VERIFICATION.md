# CreditProbe — functional verification

**Status: `LOCAL_RUNTIME_VERIFICATION_REQUIRED`**

That status is chosen deliberately and is the honest one. Everything below
was run in this environment and its result is recorded. Two things were not,
because they cannot be:

* **Docker.** `docker info` reports no daemon in this sandbox. The stack's
  containerised behaviour is **NOT VERIFIED IN CLAUDE SANDBOX**. No Docker
  security or networking setting was changed to work around it.
* **Live AI.** No Anthropic API key is configured here, and this session is
  forbidden from making live calls or consuming credits. Every AI-shaped test
  below ran against fake providers and deterministic fixtures. The product is
  therefore **NOT** `LIVE_AI_VERIFIED`, and claiming it would be a false
  statement about work nobody has done.

Both are the designated local-verification workflows, and both remain
outstanding. `RELEASE_CANDIDATE` is not claimed.

---

## 1. What was run, and what it returned

| Gate | Command | Result |
|---|---|---|
| Python lint | `ruff check backend tests scripts` | **PASS** — all checks passed |
| TypeScript | `npx tsc --noEmit` | **PASS** — no diagnostics |
| Frontend lint | `npx eslint` | **PASS** |
| Frontend build | `npx next build` | **PASS** — every route compiled, `/borrower-360` in the manifest |
| Test suite | `pytest tests -q` | **PASS** — 5,823 collected, exit 0, 0 failures |
| Display contract | `scripts/check_decimals.py` | **PASS** — 49 allowed sites with a stated reason, 0 unexplained |
| Feature matrix | `scripts/feature_matrix.py --check` | **PASS** — every page carries a curated expected behaviour |
| Browser acceptance | `scripts/browser_acceptance.py --start` | **PASS** — 956/956 checks, 4 viewports, 17 screens, real Chromium |
| Route crawl | `scripts/route_crawl.py --start` | **PASS** — 153/153 visits across 3 roles, 6 expected refusals |
| Migrations | `alembic heads` | **PASS** — single head `0029`, 29 migration files |
| Corporate build | `scripts/build_corporate_universe.py` | **PASS** — 16 quarters, 22 datasets, 176s of graph derivation |
| Docker | `docker info` | **NOT VERIFIED IN CLAUDE SANDBOX** — no daemon |
| Live AI | provider status | **NOT VERIFIED** — no key, and no live call is permitted here |

## 2. Module-by-module

§6 names thirty-one things to audit. Every one has a row, and every row
names the evidence rather than the word "OK". A test count is the number of
`def test_` in that suite; every suite listed passes.

| Module | Evidence | Result |
|---|---|---|
| **Cockpit** | `tests/proof/test_agentic_proof.py`, `tests/api` (369) — officer indicator, Requires Attention, execution-path divergence | PASS |
| **Investigations** | `tests/api`, `tests/orchestration` (382) — project-only scope, publish, refresh, versioning | PASS |
| **Analyses** | `tests/engine` (83), `tests/runtime` (73) — contracts, IR, safe SQL compiler | PASS |
| **Projects** | `tests/api` — hierarchy, scope isolation, return context | PASS |
| **Trace** | `tests/trace` (20), `tests/agentic/test_consistency.py` (12) — the parts describe what actually ran | PASS |
| **Investigation Assurance** | `tests/assurance` (145) — the weakest link; a check that did not run is not a check that passed | PASS |
| **Data Builder** | `tests/data_access` (34), `tests/services` (103) — authority, domains, relationships, drift | PASS |
| **Analysis Studio** | `tests/studio` (114) — methods, certification, Analytical IR | PASS |
| **Retail Scorecard Validation** | `tests/scorecard` (307) — re-run in full after every corporate change; §3 below | PASS |
| **Borrower 360** | `tests/corporate` (417) — snapshot, API as four roles, screen at four viewports, 18-sheet pack | PASS |
| **Graph** | `tests/corporate` — ownership math against hand-computed gold, control closure, connected groups, network analytics, 15 quality checks, 9 performance regressions | PASS |
| **Lenses** | `tests/api`, browser acceptance | PASS |
| **Early Warning** | `tests/early_warning` (24) | PASS |
| **Stress** | `tests/api`, scenario definitions | PASS |
| **Playbooks** | `tests/api`, browser acceptance | PASS |
| **Workflow** | `tests/agentic/test_approvals.py` (22) — the gate's five actions, who may decide, the audit record | PASS |
| **Notifications** | `tests/services`, `tests/api` | PASS |
| **Users / Teams / permissions** | `tests/api` — 35 named permissions; every corporate route called as all four roles with the status read | PASS |
| **Regulatory Intelligence** | `tests/regulatory` (119) | PASS |
| **Feedback & Learning** | `tests/feedback` (107) | PASS |
| **Continuous Learning** | `tests/continuous` (135) — captured and activated are separate rates | PASS |
| **Brain Center** | `tests/brain` (200) — `docs/AI_BRAIN_RUNTIME_AUDIT.md` | PASS |
| **Agentic AI** | `tests/agentic` (184) — `docs/AGENTIC_FUNCTIONAL_VERIFICATION.md` | PASS |
| **Exports** | `tests/exports` (82) — workbooks, DOCX, the Borrower 360 pack | PASS |
| **Reports** | `tests/exports`, `tests/scorecard` — the CBUAE-aligned validation report | PASS |
| **Visualizations** | `tests/presentation` (15) + the semantic selector driven in the zero-tolerance suite | PASS |
| **Routes / APIs** | `scripts/route_crawl.py` — 153/153 visits across 3 roles, 6 expected refusals | PASS |
| **Return context** | `tests/api`, browser acceptance | PASS |
| **Security** | `tests/proof/test_safety.py`, `tests/brain/test_pack_security.py` (31) — injection, path escape, null byte, dotenv, decompression bomb, cross-tenant | PASS |
| **Performance** | `tests/corporate/test_graph_performance.py` (9), each bound ≥3× the measured cost | PASS |
| **Migrations** | `alembic heads` — single head `0029`, 29 files | PASS |
| **Fresh clone / setup** | `scripts/setup.sh`, `scripts/build_data_lake.py`, `scripts/build_corporate_universe.py` — the lake and the corporate universe were rebuilt in this environment from scratch | PASS |
| **Windows runbook** | `docs/WINDOWS_LOCAL_VERIFICATION.md` | **NOT EXECUTED HERE** — no Windows host |
| **Zero-tolerance suite** | `tests/proof/test_zero_tolerance.py` — 37 tests, 36 named classes, 0 skipped; `docs/ZERO_TOLERANCE_SUITE.md` | PASS |

### Loose ends found and FIXED in this phase

Not listed — fixed, each with a regression:

1. **556 teaching cases were invisible to the product.** The 500-case retail
   scorecard corpus was never in the seeder's list, and 56 safety cases were
   rejected at save (16 declaring a risk level the schema does not have, 40
   executing with no plan). Both fixed; all 3,603 offered cases now validate.
2. **Four semantic contracts governed a word nothing produced.** Contract ids
   had drifted from concept ids, so `fields` came back empty for four graph
   measures.
3. **Two directions of deterioration were wrong** — fewer identified
   beneficial owners is the opaque case, and a community label has no
   direction.
4. **The corporate graph had no owning specialist.** Twelve agents covered
   every other domain. Added `relationship_graph`, scoped to three data
   domains so it cannot answer a retail question.
5. **The Brain could not teach the new specialist.** Its AGENTIC corpus reads
   the specialist list from the registry and raised. Subject mapping added.
6. **`network_centrality` stated no boundary** — it now says a central
   borrower is not thereby a large one, a weak one, or one more likely to
   default.

## 3. The Retail Scorecard after the corporate work

The specific risk was retrieval: twenty-two BORROWER_360 datasets now share a
catalogue with twenty-four CREDIT_BOOK ones, and both books have customers,
exposure, a stage and a covenant. This has gone wrong once before, when new
corporate datasets pushed the facility book out of the top-eight window.

Pinned by `TestThreeBooksAfterTheGraph`, which asserts on the LEAD dataset
for thirteen questions across three books:

* four retail questions lead with a `retail_*` dataset;
* five credit-book questions lead with a `CREDIT_BOOK`-scoped dataset and
  never with a `corporate_*` one;
* four corporate questions lead with a `BORROWER_360`-scoped dataset.

The full scorecard suite, the orchestration suite and the runtime suite were
re-run after every corporate change and all pass. No catalogue-size or top-N
regression, no field-substring regression, no scope bleed. No candidate model
was auto-activated; the scorecard's activation path was not touched.

## 4. What is honestly not done

* **Docker.** Not verifiable here — `docker info` reports no daemon. The
  Windows runbook stands and is unexecuted in this environment. No Docker
  security or networking setting was changed to work around it.
* **Live AI.** Not verifiable here, by instruction. Every AI test is offline
  against fake providers; no key was read and no credit consumed. The product
  is therefore NOT `LIVE_AI_VERIFIED`.
* **The remaining Borrower 360 interactions** — pinning, saved cohorts, the
  Data Builder graph-domain viewer — are not built. The screen renders, is
  navigable at four viewports, and every tab it shows is served by a route.
* **Human review of the teaching library.** 3,603 cases are offered at
  DRAFT and 0 are retrievable. That is the correct state for a freshly
  seeded library, and it means the Brain teaches the model nothing until a
  reviewer approves cases. No case was promoted to raise a count.

Nothing above is claimed as done. Each line is a statement about work that
does not exist or about a person's judgement nobody has made, rather than
about work that was not checked.

## 5. Work COMPLETED since the previous revision of this document

The previous revision listed four items as "not built". Three are now built
and one is unchanged:

| Previously "not built" | Now |
|---|---|
| Brain concepts and Investigation Blueprints for the graph | **Built.** 22 Concepts (62 total), 8 semantic contracts (45 total), 10 Investigation Blueprints (29 total / 29 families). `tests/corporate/test_graph_brain.py`, 31 tests |
| Development teaching coverage for graph topics | **Built.** 17 families, 578 cases, no family short. `intelligence_factory/teaching/corporate_graph.py` |
| Sealed-holdout coverage for graph topics | **Built.** 328 cases, 9 generators, isolation proved and proved able to FAIL. `backend/corporate/holdout.py` |
| Borrower 360 pinning, saved cohorts, Data Builder graph viewer | Unchanged — still not built |

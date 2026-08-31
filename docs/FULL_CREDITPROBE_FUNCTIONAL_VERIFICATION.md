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

| Module | Verified how | Result |
|---|---|---|
| Corporate universe (B1-B7) | 16-quarter build, 189 tests | OK |
| Ownership mathematics | 39 hand-computed gold tests | OK |
| Control closure | per-component, 2.5s, regression pinned under 60s | OK |
| Connected counterparties | 18 tests incl. percolation | OK |
| Network analytics | 58 tests, every value hand-computed | OK |
| Graph data quality | 46 tests, 15 checks, blocking proven | OK |
| Borrower 360 snapshot | 31 tests, all 24 graph fields populated | OK |
| Graph performance | 9 regressions, each ≥3× the measured cost | OK |
| Borrower 360 API | 39 tests, every route as each of 4 roles | OK |
| Borrower 360 screen | browser acceptance at 4 viewports | OK |
| Borrower 360 pack | 7 tests, 18 sheets, sentinels survive | OK |
| Graph analyses | 24 tests through the real runner | OK |
| Scope separation | 20 tests, three books, lead dataset pinned | OK |
| Retail Scorecard | full suite re-run after the corporate additions | OK — no regression |
| Orchestration / runtime | full suites re-run | OK |
| Data Builder | full suite | OK |
| Trace / Assurance | full suites | OK |
| AI Brain / teaching | full suites, fake providers only | OK (offline) |
| Agentic | full suite, fake providers only | OK (offline) |

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

* **Docker.** Not verifiable here. The Windows runbook stands and is
  unexecuted in this environment.
* **Live AI.** Not verifiable here, by instruction. Every AI test is offline.
* **Brain concepts and Investigation Blueprints for the graph.** The
  vocabulary is in place (38 new measures and dimensions, so no governed
  dataset is unteachable) and the twelve graph questions route to certified
  analyses. The ~33 named Brain concepts and 10 Investigation Blueprints are
  NOT built.
* **Development and sealed-holdout teaching coverage for graph topics.** Not
  built.
* **The remaining Borrower 360 interactions** — pinning, saved cohorts, the
  Data Builder graph-domain viewer — are not built. The screen renders, is
  navigable at four viewports, and every tab it shows is served by a route.

Nothing above is claimed as done. Each line is a statement about work that
does not exist rather than about work that was not checked.

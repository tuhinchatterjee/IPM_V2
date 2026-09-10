# UAT results

**Read the labels.** Every result below says how it was obtained. Nothing here
is a live-provider measurement, because no paid run was authorized in this
environment.

| Label | Meaning |
|---|---|
| MODEL MOCK | the analyst is scripted; the runner, store, catalog and event stream are real |
| REAL DATABASE | real DuckDB against the published `v4-uat-20q-v1` release |
| REAL HTTP | a real ASGI client over the real router |
| REAL SOCKET | a real uvicorn process on a real port, real SSE frames read incrementally |
| REAL PROCESS | real OS processes and ports |
| ORACLE | the expected number computed with pandas straight from the Parquet files, never through the code path under test |
| NOT RUN | no coverage in this build |

## Acceptance gates

| Gate | Status | Evidence |
|---|---|---|
| **G0** safe foundation | **PASS** | base `015de742890e` verified against the remote; V3 sources byte-identical; separate worktree, branch, namespace, release, state DB, ports; diagnosis separates OBSERVED/REPRODUCED/HYPOTHESIS/NOT AVAILABLE |
| **G1** observable help | **PASS (mock) · live BLOCKED** | "Who are you?" completes in **one** generation with no metadata, SQL, Sonnet or summary; progress is persisted and visible. Live G1 needs a credential this environment does not have. |
| **G2** analytical correctness | **PASS** | EAD-by-sector and the four-quarter Stage-2 comparison both match independent oracles, including the sector that *entered* stage 2 |
| **G3** bounded recovery | **PASS** | tool-history ordering proven on the stored canonical history; a real model-authored repair after a truthful diagnostic; every counter exercised against the live loop |
| **G4** reliable delivery | **PASS** | persist-before-publish; reconnect replays without a second paid run; supervisor settles a dead worker as INTERRUPTED; answer retrievable after a delivery failure |
| **G5** security and evidence | **PASS** | domain, tenant and artifact isolation; six SQL escape attempts refused; secrets redacted on the way in; numeric claims bound to exact stored values; no code path can trim a plan |
| **G6** usability | **PASS (mock) · browser PARTIAL** | hideable panel with per-substep detail and auto-expansion of the failed step; one-command start/status/stop. Rendering is covered by reducer unit tests; a Playwright pass is outstanding. |
| **G7** comparative live evidence | **BLOCKED** | requires an authorized paid run |

**Verdict: READY_FOR_CONTROLLED_UAT, not production-ready.** G7 is
outstanding, and G1 is proven only through a mock.

## The three working checkpoints

### 1. "Who are you?" — MODEL MOCK, REAL SOCKET for the delivery path

| Measure | Result |
|---|---|
| Generation calls | **1** |
| Catalog calls | 0 |
| Execution submissions | 0 |
| Sonnet / preprocessing calls | 0 |
| Summary calls on the answer path | 0 |
| Whole catalogue in the prompt | **no** — asserted field-by-field |
| Terminal state | `COMPLETED` |

`test_who_are_you_finishes_in_one_generation`,
`test_help_does_not_receive_the_whole_catalogue`

### 2. Latest-quarter EAD by sector — MODEL MOCK, REAL DATABASE, ORACLE

| Measure | Result |
|---|---|
| Generation calls | 2 |
| Execution submissions | 1 of 5 |
| Sectors returned | 11 |
| Oracle agreement | **exact for all 11 sectors** (tolerance 1e-5 on float money) |
| Largest sector | Information Technology, 5,231.577413502459 INR crore |
| Rendered in the answer | `5,231.58 INR crore` — exact value bound, displayed at declared precision |
| Terminal state | `COMPLETED` |

`test_ead_by_sector_matches_an_independent_oracle`

### 3. Stage-2 exposure change over the latest year — MODEL MOCK, REAL DATABASE, ORACLE

| Measure | Result |
|---|---|
| Quarters compared | 2025Q2 → 2026Q2 |
| Total change | +135.363111 INR crore, matching the oracle |
| Sectors that **entered** stage 2 | Manufacturing — present in the result and marked `entered` |
| Sectors that **exited** | none in this release |
| Per-sector agreement | **every sector matches the oracle** |
| Column total vs oracle total | matches |

This is the case an inner join fails silently: it would drop Manufacturing and
report a smaller change with nothing saying so. The test asserts the entering
sector is present, marked, and carries a zero prior.

`test_stage2_year_change_handles_entering_and_exiting_sectors`

## The real-socket delivery run — REAL SOCKET, MODEL STUB

`scripts/cockpit_v4/live_path_evidence.py`, recorded in
`docs/cockpit_v4/evidence/live_path.json`.

| Measure | Result |
|---|---|
| Accepted → **first visible event** | **144 ms** (target: under 1 s) |
| Accepted → visible final answer | 2,982 ms |
| Progress arrived **before** the answer | **yes** |
| Distinct stages streamed | accepted, understanding, preparing, validating, executing, publishing |
| Reconnect from cursor 2 | replayed seqs 3…18, in order, **no new run** |
| Cancellation of a working run | settled `CANCELLED` |
| Terminal state of run 1 | `COMPLETED` |
| Settled cost (fixture price schedule) | USD 0.081 |
| `cost_enforced` | true |

Roughly 2.4 s of the 2,982 ms is a deliberate delay inside the stub, standing
in for model latency. **No model latency is reported.**

## Live commissioning set (10 cases)

| # | Case | Status |
|---|---|---|
| 1 | Who are you? — one call, no analytical tool | mock PASS · **live NOT RUN** |
| 2 | PIT/TTC explanation — no portfolio claim | mock PASS · **live NOT RUN** |
| 3 | Latest-quarter EAD by sector | mock+oracle PASS · **live NOT RUN** |
| 4 | Stage-2 change vs four quarters earlier | mock+oracle PASS · **live NOT RUN** |
| 5 | Rating + DSCR/covenant/collateral join integrity | grain rules PASS · **live NOT RUN** |
| 6 | Controlled failure then **real Opus** repair | mock repair PASS · **live NOT RUN — this case is not satisfiable without a provider** |
| 7 | EWS and What-if referral pair | PASS, zero excluded-domain execution |
| 8 | Non-English query with number, entity, exclusion | PASS — Hindi, Bengali, Arabic, Hinglish fixtures |
| 9 | Contextual follow-up theory → data → What-if | PASS, new run id, same thread |
| 10 | Browser reconnect/cancel + Python capability | reconnect and cancel PASS over a real socket; **Python UNAVAILABLE and reported as such** |

Case 6 deserves emphasis: the *mechanism* is proven — a truthful diagnostic
goes back, the application changes nothing, and a corrected batch runs. That
the corrected code came from a scripted turn rather than from Opus is the
whole gap, and it is not closed by anything in this build.

Case 10's Python half is **not** marked passed. The analyst wrote SQL; the
Python runner is unavailable; reporting that as a Python pass is exactly the
false claim the case exists to prevent.

## Capabilities in this environment

| Capability | Status | Why |
|---|---|---|
| `ready_for_product_help` | needs a credential and a verified price card | neither is present here |
| `ready_for_sql_analysis` | **working** | real DuckDB against `v4-uat-20q-v1` |
| `ready_for_python_analysis` | **unavailable** | the jail's escape self-test found network access was not blocked, so the runner refuses to certify itself |

## Acceptance inventory

100 of 100 cases carry automated evidence
(`docs/cockpit_v4/ACCEPTANCE_CASES.json`), each with the test that asserts it
and its label. **Every case's `real_provider` field reads `NOT RUN`.**

138 backend tests and 9 frontend reducer tests pass. Zero failures, zero
errors, zero skips.

## What a paid live commissioning run would need

1. `COCKPIT_ANTHROPIC_API_KEY` in the authorized runtime — via the environment
   or the macOS Keychain, never pasted into a chat window.
2. `config/cockpit_v4/price_card.json` filled in with the current published
   schedule for the exact model id, all four billing classes and a real
   `verified_at`. Until then V4 refuses to make a paid request.
3. An agreed total test budget. Per-run ceilings are USD 1 Standard / USD 2
   Deep and are enforced by reservation, but the *total* for a commissioning
   session is the owner's decision, not a setting.
4. Explicit approval to run the ten commissioning cases — and only those. The
   84-question bank is not run automatically by anything here.

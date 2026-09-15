# Retail Demo Completion — progress ledger

The on-disk record the completion contract asks for, so progress survives a
compaction or a container restart. One section per phase. A phase is marked
done only when its UI, calculation and persistence checks pass.

Contract: `CreditProbe_Retail_Demo_Completion_Master_Prompt` (30 sections, 92 gates).

---

## Release boundary (§1)

| | |
|---|---|
| Branch | `claude/funny-dirac-6n8f0o` |
| Candidate at start | `c0db151f62c34e84b4f7df5faf81e5c9b0c9f647` |
| Working tree at start | clean |
| Book manifest hash | `3268b725456df9c4f7fea602395b4bd026e7a7c1810b52494cece5641db6e1d6` |
| Dataset version | `r1.2.0-c1.0.0-s20260910` |
| Generator | `retail-gen-1.2.0`, seed `20260910`, as-of `2026-08` |
| `uv.lock` | `dc001ea0a9370fed…` |
| `frontend/package-lock.json` | `439ce817d0a95db6…` |

Populations, read from the lake rather than from a screen:

| Dataset | Rows | Customers | Facilities | Months |
|---|---:|---:|---:|---|
| `retail_facility_month` (canonical book) | 1,347,014 | 54,450 | 85,476 | 2024-08 … 2026-08 (25) |
| — at 2026-08 | 59,449 | 42,824 | 59,449 | GCA SAR 6,388,268,768.90 · ECL SAR 58,608,354.44 |
| `retail_ews_score` | 1,088,983 | 52,110 | 79,687 | 2025-01 … 2026-08 (20) |
| — at 2026-08 | 59,449 | 42,824 | | |
| `retail_whatif` at 2026-08 | 59,449 | 42,824 | | |
| `retail_credit_scorecard` at 2026-08 | 59,449 | 42,824 | | |
| `retail_early_warning` at 2026-08 | 59,449 | 42,824 | | |

The enlarged book is intact and every derived view agrees with it at the
latest month. The former ~19,745-facility book is not in play.

Frozen corporate installations (5318 / 5308) were not started, not queried and
not modified.

---

## Phase 1 — Baseline audit and acceptance map

Status: **done**. Evidence: `docs/evidence/phase1/`.

See `docs/RETAIL_DEMO_COMPLETION_ACCEPTANCE.md` for the delta table and the
92-gate matrix.

---

## Phase 2 — Data and semantic foundations

Status: **done** at `d6e624c`. `periods.py` (Q2 2026 vs Q1 2026 from the data,
maturity cutoff 2025-08), `metric_registry.py` (12 pinned definitions, PSI/CSI),
`domains.build` stamping on completion. 17/17 tests.

## Phase 3 — Analytical story engines

Status: **done** at `4c19270`. `decomposition.py`, `analysis_delinquency.py`,
`analysis_traits.py`, `story_router.py`, wired into `/ask`. 32/32 tests.

Credit Card 30+ DPD 6.9077% -> 7.5082%, +0.6006 pp; five flows explain the
numerator change to SAR 0.00; three mix bridges each reconcile to 0.6006 pp.
123 scorecard inputs reviewed, 55 correctly classified historical.

## Phase 4 — Shared What-If and model pages

Status: **done** at `9aabb56`. `lgd_absolute_pp`, `ccf_absolute_pp`,
`whatif_thread.py`, `WhatIfThread` component, `/what-if/threads/{id}`.
29/29 tests, 14/14 browser checks.

Still open in this phase: §10's six XGBoost tabs and a persisted artifact;
the Delta page's worked example.

## Phase 5 — Results and professional exports

Status: **done and fully accepted**.

§12 — the workbook. `workbook_style.py`, `workbook_sheet.py`,
`whatif_workbook.py`. 22 sheets, gridlines off on every one, 0 numeric cells
unformatted, 0.034823 renders as 3.48%, 36 formula cells, 3 charts, 21
internal links, 4,660 customers and 5,001 facilities of detail.

§11 — the engine records the propagation as it computes it (`mechanism`,
`score_migration`, `stage_movement`); an untouched channel is named as
untouched. Each waterfall step reports how many facilities' ECL actually
moved, and a migration additionally reports how many it selected.

§13 — `report_service.py`, all three families: investigation, trait
attribution, scorecard validation. `POST /retail/reports/{family}.docx`
returns the right content type and filename and refuses as a status code
rather than as a file.

### Performance (§27)

| Stage | Before | After |
|---|---:|---:|
| `_read_book` per call | 1.20s, uncached | 0.00s after the first |
| `cohort.run` | 5.76s | 1.93s |
| customer roll-up | 2.84s | 0.14s |
| facility detail | 0.46s | 0.18s |
| workbook build | 1.98s | 2.02s |
| **browser download, end to end** | **15.4s** | **8.1–9.0s** |

Nothing was removed to get there: the same 22 sheets, the same customer and
facility detail, the same formatting and the same auditability.

### Acceptance

`scripts/retail_uat/phase5_acceptance.py` — **39 of 39**, both files
downloaded by clicking in a real browser and then opened and inspected. Zero
page errors.

`scripts/retail_uat/check_workbook_formulas.py` recomputes every formula
against the other cells' cached values, independently of the code that wrote
them.

Tests: 125 across phases 2–5, 0 failures.

## Phase 6 — Scorecard Validation

Status: not started.

## Phase 7 — Workspace population

Status: not started.

## Phase 8 — Integrated demo

Status: not started.

## Phase 9 — Cold start, gates, release

Status: not started.

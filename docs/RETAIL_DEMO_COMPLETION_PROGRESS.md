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

Status: not started.

## Phase 3 — Analytical story engines

Status: not started.

## Phase 4 — Shared What-If and model pages

Status: not started.

## Phase 5 — Results and professional exports

Status: not started.

## Phase 6 — Scorecard Validation

Status: not started.

## Phase 7 — Workspace population

Status: not started.

## Phase 8 — Integrated demo

Status: not started.

## Phase 9 — Cold start, gates, release

Status: not started.

# Retail overnight manual UAT — live ledger

Branch `claude/funny-dirac-6n8f0o`. Started from HEAD `5bb388c`, clean, in sync
with origin. Nothing was reset, rebased, merged or force-pushed; no freeze tag
was created or moved; the frozen 5318 and 5308 installations were not touched.

## Build identity as found

| | |
|---|---|
| Branch | `claude/funny-dirac-6n8f0o` |
| HEAD at start | `5bb388c`, clean tree, in sync with origin |
| Frontend | Next 16.3.2 dev server, `http://localhost:5328` |
| Backend | uvicorn, `http://127.0.0.1:8328`, API prefix `/api/v1` |
| Database | PostgreSQL on **port 55432**, database `creditprobe_retail` — the isolated retail instance, not a frozen one |
| Lake | `data/retail/analytics/retail_facility_month`, 25 monthly partitions |
| Metadata | `metadata/retail` |
| Profile | `CREDITPROBE_PRODUCT_PROFILE=retail`, `NEXT_PUBLIC_PRODUCT_PROFILE=retail` |
| Dataset range | 2024-08 … 2026-08 (25 consecutive month-ends) |
| Latest fully observed cohort | **2025-08** — see ON-01 |
| Authentication | session cookie, `REQUIRE_LOGIN=true` |
| AI provider | none configured — provider-backed paths NOT RUN throughout |

Five stale background waiters from the previous session were polling for runs
that had already finished. Each was identified by its own command line and
stopped by PID; nothing else was signalled.

## Prior gaps — status on entry

| Gap | Status found | Action |
|---|---|---|
| RFD-37 retail metric library | **OPEN** — all 61 metrics read datasets this deployment does not have, so Metrics, Lenses and Playbook rendered a dash in every box | CLOSED, see §1 below |
| What-If: recent runs | OPEN | see §2 |
| What-If: unsaved-run export | OPEN | see §2 |
| What-If: scenario-step editor | OPEN | see §2 |
| What-If: opening-book profile | OPEN | see §2 |
| What-If: stage-movement charts | OPEN | see §2 |
| What-If: facility drill-down | OPEN | see §2 |
| What-If: deep-linkable saved scenario | OPEN | see §2 |

## Section 1 — the retail metric library (RFD-37)

`backend/metrics/retail_library.py`: **46 governed metrics** on
`retail_facility_month`, across five domains — Retail Portfolio, Retail IFRS 9,
Retail Delinquency, Retail Origination, Retail Scorecard.

Every one computes against the real book, and every one was reconciled against
an independent pandas aggregation of the Parquet
(`tests/retail/test_ret_metrics_library.py`, 76 gates).

Both shipped retail lenses were rewritten against them: **0 empty tiles** on
either, where before every tile was empty. Three retail Playbook packs —
Portfolio, IFRS 9, Scorecard Assurance — **34 KPI blocks, 0 empty**.

## Defects found overnight

Maintained in `docs/RETAIL_OVERNIGHT_DEFECTS.md`.


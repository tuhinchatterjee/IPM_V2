# Retail Demo Completion — delta map and acceptance matrix

Two things live here: what the contract asks for measured against what the
application does today (§2, §3.1), and the 92 minimum gates with the command
or browser action that decides each one (§26).

Everything in the "today" column was **executed**, not read off the source.
Where a defect was reproduced, the reproduction is named.

Audited at `c0db151f` · book `3268b725…` · 2026-08 · 59,449 facilities /
42,824 customers.

---

## Part 1 — Reproduction of the screenshot-derived defects (§2)

| Ref | What the contract describes | Reproduced? | What actually happened |
|---|---|---|---|
| 2.1a | Raw parameter catalogue on the What-If landing page | **yes** | `/what-if` renders a card titled "What this engine implements" (`retail-whatif.tsx:625`) |
| 2.1b | Raw identifiers exposed to the user | **yes** | all six visible in the page text: `pd_relative`, `lgd_relative`, `ccf_absolute`, `income_pct`, `dpd_migration`, `score_band_migration` |
| 2.1c | No Delta / XGBoost choice offered | **yes** | zero method controls on `/what-if`; the standalone path calls the engine with the default method |
| 2.1d | Standalone is a different path from the EWS thread | **yes** | no shared thread container on `/what-if`; two implementations (`retail-whatif.tsx` 993 lines vs `whatif/[selectionId]/page.tsx` 626 lines) over two API families (`/whatif/*` vs `/ews/whatif-selection/*`) |
| 2.3 | EWS interpretation is one dense paragraph | pending | measured in the Phase 1 browser pass; the panel is a single paragraph with no supporting-detail control |
| 2.4 | Excel not presentation quality | **yes** | `whatif_workbook.py` sets no `hide_gridlines`; PD/LGD written as raw decimals |
| 2.5-projects | Projects shallow / stale | **yes** | 6 projects; **all six have 0 analyses**, three have 0 investigations; "Retail Portfolio Review — **Q3 2026**" over data that ends 2026-08 (§4.2 forbids labelling August a September quarter-end) |
| 2.5-documents | Documents shallow | **yes, and worse** | Documents has **no backend at all** — `/documents` renders the hard-coded `DOCUMENTS` constant from `frontend/src/lib/demo.ts`; no persistence, no editing, no download, no revisions |
| 2.5-lenses | Lenses thin | **yes** | 4 published lenses, **none of them a product dashboard**; the contract requires ≥8 including Auto / Credit Card / Personal / Home |
| 2.5-analyses | Stale/foreign content | **yes** | the Analyses list carries corporate rows — e.g. "Shipping PD increase" — in a retail-only installation |
| 2.6a | "Backend did not respond within 20 seconds" | **partly** | `discrimination` on the Credit Card behavioural scorecard takes **16.3 s**, `calibration` **9.4 s**; the overview is 0.5 s. At 16.3 s a 20 s client timeout is one slow query from firing |
| 2.6b | Category mapping wrong | **yes** | the registry's category IDs are `data_quality`, … — the contract's screen calls for **Data & Representativeness**; `POST …/categories/data_representativeness` returns **404** |
| 2.7 | Investigation lacks its next analytical step | **yes, and worse than described** | see below |

### 2.7 in full — the flagship demo moment

The attention card itself is sound: `GET /risk-cases` returns 7 computed cases,
top of list `Credit Card 30+ DPD has risen for 5 consecutive months`, severity
critical, 2026-08 vs 2026-07. `POST /risk-cases/368/investigate` creates
investigation 1012 in 1.2 s.

Asking that investigation the contract's exact prompt —
`what is the reason of this rise?` — returns in 12.6 s with `status:
succeeded` and:

- **the product scope is gone** — the answer is "the whole portfolio", not Credit Card;
- **the metric is the wrong one** — gross carrying amount, not 30+ DPD;
- **the period is the wrong one** — 2025-08 → 2026-08, not the month-on-month step or the five-month lookback the case is built on;
- no transition matrix, no cures, no mix bridge, no PD/stage/ECL bridge, no pockets, no affected customers.

It answers a question nobody asked, confidently. This is STORY-03 through
STORY-06 and it is the single most visible failure in the demo path.

---

## Part 2 — Requirement-to-implementation delta

| § | Requirement | Today | Gap |
|---|---|---|---|
| 8 | One shared What-If thread for standalone, guided cards and every EWS export | two implementations, two API families | **build**: one thread controller + `Selection` widened to represent any Retail cohort, both entries create threads |
| 8.1 | Landing: composer, 7 guided cards, Delta/XGB cards, Saved + Recent | composer + 7 cards present; no model cards; raw-parameter block present | **build** model cards, **remove** the parameter block |
| 8.2 | Card opens a thread with a real baseline profile | card only swaps prompt chips on the home page | **build** |
| 8.3 | Explicit method choice before first run; full persistence of turns | EWS thread has method cards; standalone has none; thread turns are per-session | **build** persistence; **extend** method choice to standalone |
| 9 | Typed scenario plan; pp vs % units; absolute LGD shock | `lgd_relative` only — "+5 percentage points" is refused | **build** `lgd_absolute`, `pd_absolute`, `ccf_absolute` units + plan object |
| 10.1 | Clickable Delta model page | route `/what-if/models/delta` exists | **verify + deepen** |
| 10.2 | Clickable XGBoost page with 6 tabs, artifact, save/load parity | route `/what-if/models/ml` exists; XGBoost fits live per run | **build** persisted artifact + tabs |
| 6 | Credit Card attention decomposition | absent — wrong scope, metric and period | **build** |
| 7 | Trait → score → PD → ECL attribution | absent | **build** |
| 11 | Result sequence, propagation table, financial waterfall | waterfall exists in the EWS thread only | **extend** to the shared thread |
| 12 | Professional Excel, 20 mandatory sheets, no gridlines | 13 sheets, gridlines on, raw decimals | **rework** |
| 13 | Three Word report families from a versioned bundle | EWS model-log report only | **build** |
| 14 | Validation categories, execution, representativeness | 11 categories, 8 scorecards; category IDs mismatched; 16 s worst case | **repair + build** |
| 15 | Per-card comments + validation Word report | absent | **build** |
| 17 | 12 substantial projects | 6, all with 0 analyses | **seed** |
| 18 | 60 investigations / 100 analyses | 50 investigations / 9 analyses (some corporate) | **seed** |
| 19 | 24 editable documents with support bundles | frontend constant, no backend | **build + seed** |
| 20 | 8 lenses incl. 4 product dashboards | 4, none a product dashboard | **build + seed** |
| 21 | Clean-cohort (DPD=0, elevated forward risk) filter | forward-risk flag exists; no DPD=0 clean filter | **extend** |
| 22 | Five-act Demo Story entry | absent | **build** |
| 24 | Source stamps on every derived domain | only `retail_ews_score` is stamped; the three governed views carry none, so `stale()` answers False for them | **fix** — this is the §24 recurring upgrade defect, still open |

### Defect fixed during the audit

`.env.retail` carried no `NEXT_PUBLIC_API_URL`, so a frontend started the
documented way (`set -a && . ./.env.retail && set +a`, then `npm run dev`)
fell back to `http://127.0.0.1:8000` — the **corporate** installation's port.
The page rendered completely and then reported "Backend offline", because
every call from the browser went to a server that was not this one. Only the
launcher passed the variable, on its own npm line. Added to `.env.retail`.

---

## Part 3 — The 92 gates

Status values: `PASS`, `FAIL`, `NOT RUN`, `BLOCKED`. Nothing is marked PASS
from a page rendering, an HTTP 200 or a file existing.

### DATA (10)

| ID | Gate | How it is decided | Status |
|---|---|---|---|
| DATA-01 | Source identity and enlarged population preserved | lake query: 59,449 / 42,824 at 2026-08 | PASS |
| DATA-02 | Required periods and maturity | 25 source months, 20 scored; 12-month outcome cutoff ≤ 2025-08 | NOT RUN |
| DATA-03 | Derived membership parity | all four derived views = 59,449 / 42,824 at 2026-08 | PASS |
| DATA-04 | Amount reconciliation | GCA and ECL tie book → views | NOT RUN |
| DATA-05 | Source mutation invalidates dependents | stamp test per domain | **FAIL** — three views unstamped |
| DATA-06 | A stale 20k EWS cannot pass readiness | readiness assertion | NOT RUN |
| DATA-07 | Partial rebuild retains other months | regression `test_stamp_04` | PASS |
| DATA-08 | Development references immutable | Phase 2 | NOT RUN |
| DATA-09 | Historical artifact labelled and reproducible | Phase 7 | NOT RUN |
| DATA-10 | Idempotent upgrade / fresh seed | Phase 9 | NOT RUN |

### STORY (12), WIF (16), MODEL (8), EXPORT (10), VAL (16), CONTENT (10), LIVE/NAV (10)

All `NOT RUN` at Phase 1 except where the reproduction above already decides
them:

| ID | Gate | Status |
|---|---|---|
| STORY-01 | Computed attention card | PASS (7 computed cases, correct headline) |
| STORY-02 | Click opens a full persisted thread | PASS (investigation 1012 created in 1.2 s) |
| STORY-03 | Natural "why" inherits context | **FAIL** — scope, metric and period all lost |
| STORY-04 | Worsening / cures / entry-exit matrix | **FAIL** — not implemented |
| STORY-05 | Rate bridge reconciles | **FAIL** — not implemented |
| STORY-06 | Separate ECL bridge | **FAIL** — not implemented |
| WIF-01 | Standalone uses the shared thread | **FAIL** |
| WIF-03 | No raw parameter block on the landing page | **FAIL** |
| WIF-04 | Explicit method selection before the first run | **FAIL** (standalone) |
| WIF-08 | LGD +5 pp understood and calculated | **FAIL** — refused by design |
| WIF-15 | Full cross-session persistence | **FAIL** — thread turns are per-session |
| EXPORT-02 | No gridlines on every sheet | **FAIL** |
| EXPORT-03 | Numeric / probability formats | **FAIL** |
| VAL-02 | Category ID mapping | **FAIL** — `data_representativeness` is a 404 |
| VAL-04 | Full-job progress, no generic timeout | **FAIL** — 16.3 s synchronous worst case |
| CONTENT-01 | 12 non-empty projects | **FAIL** — 6, all with 0 analyses |
| CONTENT-02 | 60 meaningful investigations | **FAIL** — 50, quality unverified |
| CONTENT-03 | 100 saved analyses | **FAIL** — 9 |
| CONTENT-04 | 24 substantive documents | **FAIL** — no backend |
| CONTENT-05 | 4 product + 4 additional lenses | **FAIL** — 4, none a product dashboard |

The remaining gates are carried as `NOT RUN` and decided in their own phase.

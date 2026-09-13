# Retail Early Warning Score — requirement to implementation delta

Baseline: `f547bce`. Target: the Early Warning Score master rebuild specification.

*Synthetic Saudi retail demonstration data throughout. Nothing here is an ANB
model, an ANB policy, or a SAMA requirement.*

| # | Requirement | State at f547bce | Required change | Code area | Browser test |
|---|---|---|---|---|---|
| 1 | ONE left-nav item, `Early Warning Score` | TWO items: "Early Warning" and "Early Warning Signals" | Collapse to one; Signals becomes an internal view; old routes redirect | `lib/navigation.ts`, `app/early-warning/*` | EW-01 |
| 2 | Chat box at top of the workspace | None. No EWS chat at all | New chat panel above the KPIs, always visible | `app/early-warning/chat.tsx`, `backend/retail/ews_chat.py` | EW-02 |
| 3 | Chat restricted to the EWS domain, proven | N/A | Dedicated endpoint reading only the EWS panel + model config; hard refusal outside scope; leakage test | `backend/retail/ews_chat.py` | EW-58, EW-60 |
| 4 | FOUR layers | SIX layers over eleven families | Re-model onto Behavioural / Affordability & Cash Flow / Bureau & External / Facility & Exposure; map the 20 existing rules in | `backend/retail/ews_model.py` (new) | EW-43 |
| 5 | Classifier → Trigger → Action | Rules only; no classifier concept, no action dimensions | Classifier variables and trigger variables per sublayer; six action dimensions per dynamic trigger | `ews_model.py`, `ews_score.py` | EW-44, EW-45 |
| 6 | Direction, Magnitude, Velocity, Momentum, Persistence, Recency | Absent | Computed per trigger per customer-facility-month over the 20-month history | `ews_score.py` | EW-38, EW-45 |
| 7 | Sublayers | Absent | 19 sublayers across the four layers, each with its own score | `ews_model.py`, `ews_score.py` | EW-37 |
| 8 | Headline KPIs incl. High/Critical count | Ten KPIs; no explicit High+Critical figure | Add; keep the rest | `retail-portfolio.tsx` | EW-03 |
| 9 | Four large product cards | Four cards, but no ODR trend, no top-five reasons, no warning-customer trend | Add three six-month trends and a top-five reason table to each | `ews_score.py`, product card | EW-04…EW-09 |
| 10 | Six-month ODR / default-entry trend | Absent — no default-entry flag anywhere | Derive `default_entry_this_month`; ODR at aggregate level only | `ews_score.py` | EW-06, EW-14 |
| 11 | Sub-product / sub-portfolio level | Subsegments cut by book dimensions (utilisation band etc.), not sub-products | Governed sub-product taxonomy in model metadata: Privilege / Platinum / Silver / Ultra for cards, and governed sub-portfolios for the other three | `ews_model.py` + panel column | EW-11, EW-12, EW-16 |
| 12 | Customer cards compact, three mini charts on the right | Wide table, no charts | Card layout: facts left, EWS / DPD / Behavioural six-month sparklines right | `customer-card.tsx` | EW-24…EW-26 |
| 13 | Customer name | Book has no `customer_name` | Deterministic synthetic name, generated from the customer id and labelled synthetic | `ews_score.py` | EW-20 |
| 14 | Bureau as classifier + recency, never a fabricated monthly trend | Bureau treated as a monthly trend layer; the book stamps `bureau_score_current_date` with every month-end | Governed pull schedule: origination, a per-customer cadence, and a delinquency-triggered pull. Between pulls the last observed value is carried, unchanged, with its date and recency | `ews_model.py`, `ews_score.py` | EW-27, EW-48 |
| 15 | Customer 360 EWS section | Customer detail exists inside Early Warning; Customer 360 has no EWS section | Full EWS panel in Customer 360: overall, four layers, sublayers, variables, triggers, action dimensions, facilities, exposure share | `app/borrower-360/retail-customer.tsx` | EW-34…EW-40 |
| 16 | View Model: complete model tree | Methodology page over six layers and 27 variables | Rebuild over the four-layer tree with classifiers, triggers, sublayers, action dimensions, weights, product applicability | `app/early-warning/model/page.tsx` | EW-41…EW-50 |
| 17 | Flow diagram | Absent | Data → Classifiers → Triggers → Action dimensions → Sublayers → Layers → Score → Severity → Reasons | model page | EW-42 |
| 18 | Product weight matrix in config, not frontend | No weights per product at all | `PRODUCT_CONFIG` in `ews_model.py`, served | `ews_model.py` | EW-46 |
| 19 | Central thresholds, cutoff, hard-trigger overrides | Bands in `ews_layers.py`; no cutoff, no overrides | One config block: scale, direction, cutoff, four severity thresholds, hard triggers | `ews_model.py` | EW-47 |
| 20 | Data Builder domain `Early Warning Score` | The panel is a private parquet directory, not a registered domain | Register `retail_ews_score` as a governed domain with its field contract | `backend/retail/domains.py` | EW-51 |
| 21 | Exactly 20 monthly snapshots | 25 | Latest 20 months (2025-01 … 2026-08), verified programmatically | `ews_score.py` | EW-52 |
| 22 | Grain customer-facility-month | Panel is customer-product-month | Rebuild at customer-facility-month; customer-grain fields marked as such; governed aggregate views | `ews_score.py` | EW-53 |
| 23 | Complete field contract (≈150 fields) | ~40 | Implement in full; a field the book cannot support is declared absent with a reason rather than fabricated | `ews_score.py` | EW-53 |
| 24 | Every UI number traced to the domain | Portfolio reads the panel; Signals re-evaluates the rulebook live | Everything reads the EWS domain | routers | EW-56, EW-57 |
| 25 | Source-mutation proof | Absent | A disposable fixture that changes one source variable and asserts the change propagates to sublayer, layer, score, reason and aggregate | `tests/retail/test_ret_ews_dynamic.py` | EW-59 |
| 26 | Signals view kept but not the landing screen | It is a separate top-level nav item | Move inside the workspace; keep chips, "Showing N of M", rule detail | `app/early-warning/signals/*` | EW-33 |
| 27 | Filters: month, severity, rule, sub-product, bad/forward, DPD bucket, stage, score range, behavioural range | month, product, severity, rule, layer, cohort | Add sub-product, DPD bucket, stage, score range, behavioural range; chat sets them | customer list | EW-17, EW-18 |
| 28 | Back retains state at every level | Holds for the four levels that exist | Extend to sub-product and facility | `retail-portfolio.tsx` | EW-19 |
| 29 | EW-01 … EW-60 | EW-01…EW-22 against the previous spec | New suite of 60 | `scripts/retail_uat/ews_score_uat.py` | all |

## Preserved from f547bce, and regression-protected

Portfolio → product → … → customer navigation and its URL state; the current-bad
versus forward-risk definitions and cohort logic; the corrected 5,952 signal
total and the facility/customer alert split behind it; the customer-product
aggregation fixes; clickable signal chips and "Showing N of M"; Back and deep
links; the Credit Card case study; the synthetic-bureau labelling; the browser
harness; and the precomputed-panel approach, which is refactored onto the new
grain rather than discarded.

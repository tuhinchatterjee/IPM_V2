# Retail conversion inventory

What each component of the source installation became, what data it now depends
on, where that lives, and which test holds it in place.

> **Synthetic Saudi retail demonstration data — not ANB customer data or
> approved models.**

---

## 1. Data layer

| Old component | New retail behaviour | Data dependency | Implementation | Regression test |
|---|---|---|---|---|
| `portfolio_facility` (corporate facility position, quarterly) | **Retired.** Not published, not resolvable. | — | `backend/retail/profile.py` `RETIRED_DOMAIN_IDS` | RET-047 |
| `borrower_financials` (company balance sheets and ratios) | **Retired.** No company financial statement exists in the retail product. | — | as above | RET-008, RET-038, RET-047 |
| `customer_ratings` (annual internal rating cycles) | **Retired.** Replaced in function by application and behavioural SCORES, which are different objects with their own targets — not a renamed rating grade. | — | `backend/retail/models_registry.py` | RET-012, RET-013, RET-047 |
| `ifrs9_staging` (corporate staging detail) | **Folded in.** Retail IFRS 9 staging, PD, LGD, EAD and scenario ECL are columns of the one canonical table. | `retail_facility_month` | `backend/retail/generate.py` `_risk_and_ecl` | RET-018 to RET-023 |
| `facility_delinquency` | **Folded in.** DPD, buckets, arrears, collections and cure are columns of the same table. | `retail_facility_month` | `backend/retail/generate.py` `_facility_month` | RET-009, RET-014 |
| `credit_memo_signals` (credit-file commentary) | **Retired.** A retail book has no credit-file commentary of this kind. | — | `RETIRED_DOMAIN_IDS` | RET-046 |
| `macro_saudi` (quarterly macro series) | **Internalised.** The cycle that drives the book is a generator input and a documented scenario multiplier set, not a user-facing dataset. | `config/retail_demo_config.json` | `backend/retail/generate.py` `_cycle_path` | RET-019 |
| `corporate_connected_group`, `corporate_graph_quality` (Borrower 360 graph) | **Retired.** Employer identifiers remain as an ATTRIBUTE of individual borrowers; no employer is a financed customer. | `employer_id`, `employer_sector` | `backend/retail/taxonomy.py` | RET-008 |
| Two portfolio scopes (`CREDIT_BOOK`, `BORROWER_360`) | **One scope.** `RETAIL_BOOK`, one domain, "Cockpit Data". | `retail_facility_month` | `backend/retail/catalogue.py` | RET-005 |

## 2. Modules

| Module | Decision | Data dependency | Implementation | Regression test |
|---|---|---|---|---|
| **DataBuilder** | Converted. One domain, 25 monthly members, existing preview and metadata patterns. | `metadata/retail/catalog.json` | `backend/retail/catalogue.py` | RET-005, RET-006 |
| **Cockpit** | Converted. Reads the canonical domain and the requested month. Starter questions, chips and follow-ups are retail. | `retail_facility_month` | `backend/retail/profile.py`, `backend/api/routers/ask.py` | RET-046, RET-050 |
| **Early Warning** | Signal model replaced, screens kept. Twenty facility and customer rules, two segment rules, all reading the canonical rows. | `retail_facility_month` | `backend/retail/ews.py` | RET-034 to RET-038 |
| **What-If** | Converted. Same snapshot, same engine, twelve implemented methodologies. | `retail_facility_month` | `backend/retail/whatif.py` | RET-039 to RET-045 |
| **Scenario lab chips** | Converted to retail sensitivities. | — | `backend/stress_lab.py` | RET-046 |
| **ECL movement / decomposition** | Rebuilt as a sequential-replacement bridge with a published order and no unexplained plug. | two snapshots | `backend/retail/movement.py` | RET-025 |
| **Scorecard monitoring** | Served through the existing Cockpit answer path. **No new top-level scorecard module was built**, as instructed. | `retail_facility_month` | `backend/retail/monitoring.py` | RET-026 to RET-033, RET-048 |
| **Exports** | Kept, hardened: formula injection escaped, no NaN or Infinity in JSON. | any result | `backend/retail/exports.py` | RET-052 |
| **Playbook, Lenses, Planner, Trace, Assurance** | **Not rebuilt.** Present in the source and left structurally intact; their seeded corporate examples are out of scope for this pass and are recorded as an open item in the handover. | — | — | see limitations |

## 3. What-If methodology inventory

Every methodology the engine advertises, and its verdict. There is no dead
visible methodology: an unsupported request returns the supported list.

| Methodology | Verdict | Note |
|---|---|---|
| `pd_relative` | Retail replacement | Multiplies the PIT PD anchor and rebuilds the whole curve |
| `pd_absolute_pp` | Retail replacement | Percentage points, a genuinely different operation |
| `lgd_relative` | Domain-neutral, retained | Bounded by the declared LGD floor and cap |
| `collateral_value_pct` | Retail replacement | Secured products only |
| `recovery_delay_months` | Domain-neutral, retained | The only sensitivity a defaulted facility responds to |
| `utilisation_pp` | Retail replacement | Revolving only; percentage points on the limit |
| `ccf_absolute` | Domain-neutral, retained | Undrawn card commitments |
| `scenario_weights` | Domain-neutral, retained | Validated, never silently normalised |
| `income_pct` | Retail replacement | Reaches affordability, behavioural evidence and mapped PD only |
| `behavioural_score_points` | Retail replacement | Through the versioned score-to-PD mapping |
| `staging_mode` | Domain-neutral, retained | Frozen vs re-evaluated, explicitly distinguished |
| `cutoff_replay` | Retail replacement | Booked originations only, with four stated limitations |
| *Corporate rating-notch migration* | **Removed, not relabelled** | Rating-transition mathematics is not a retail score model, and renaming it would have been the dishonest option |

## 4. Migrations

No migration was added. The retail lake is file-backed Parquet under
`data/retail/analytics`, and the catalogue is JSON under `metadata/retail`.
The Alembic graph is byte-identical to the source commit (RET-054).

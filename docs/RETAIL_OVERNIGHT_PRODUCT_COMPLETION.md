# Retail overnight product completion

The Saudi retail installation, audited route by route in the running
application, then built out where it was empty and fixed where it was wrong.

Everything here is synthetic demonstration material. Nothing in this product is
approved by ANB, by SAMA or by any auditor, and nothing in it has been
independently validated.

---

## Build identity

| | |
|---|---|
| Branch | `claude/funny-dirac-6n8f0o` |
| Candidate preserved as | tag `retail-candidate-f0a118a` |
| Backend | `http://localhost:8328`, `/api/v1` |
| Frontend | `http://localhost:5328` (needs `NEXT_PUBLIC_API_URL=http://localhost:8328`) |
| Database | `creditprobe_retail` on port 55432 |
| Lake | `data/retail/analytics`, 25 month-ends, 2024-08 … 2026-08 |
| Metadata | `metadata/retail` |
| Bootstrap | `.venv/bin/python scripts/bootstrap_retail_installation.py` (`--check` to read without writing) |

---

## 1. The audit

Every route was opened in a real signed-in browser and read. Screens and the
raw capture are in `docs/evidence/retail_overnight/`.

| Route | Before | After |
|---|---|---|
| Cockpit | populated and working | working |
| My workspace | thin | unchanged |
| Messages | one system message | 7 — four data-release notices and three working notes |
| Projects | **empty** | 6 seeded retail projects, three carrying a case-study thread |
| Project Planner | empty | unchanged — out of scope, and not in the demonstration path |
| Investigations | populated | plus the three case studies |
| Analyses | thin | unchanged |
| Documents | thin | unchanged |
| Lenses | 2 lenses | **4** — Retail Credit Risk, Retail IFRS 9 and ECL, Retail Early Warning, Retail Analytics |
| Metric Catalogue | 46 governed metrics, searchable | **49** — the three scenario ECLs added |
| Early Warning | populated; methodology and 3 fitted models present | unchanged |
| Early Warning Signals | populated | unchanged |
| What-If | populated and working | unchanged |
| Customer 360 | renders on demand | unchanged |
| Scorecard Validation | populated | unchanged |
| Analysis Studio | empty | unchanged — out of the demonstration path |
| Data Builder | 1 domain + a stray "Test Domain" | **4 governed domains**, junk removed |
| Trace & Lineage | populated | unchanged |
| Playbook | 6 packs, 5 committees | unchanged |
| My reviews | empty | unchanged |
| Workflow | populated | unchanged |
| Agent Operations | populated | unchanged |
| AI Intelligence Studio | populated | unchanged |
| Users & Teams | populated, including test-run accounts | unchanged |

No corporate dataset, domain, project or thread was seeded at any point.

---

## 2. Four domains, one book

`backend/retail/domains.py` builds three governed **views** of
`retail_facility_month` by selecting columns out of the canonical parquet —
there is no arithmetic in it at all, which is the point.

| Domain | Dataset | Columns |
|---|---|---|
| Cockpit Data | `retail_facility_month` | 546 — the canonical book |
| Early Warning Data | `retail_early_warning` | delinquency and stage, repayment behaviour, affordability, score dynamics, facility structure, bureau |
| Credit Scorecard Data | `retail_credit_scorecard` | both scorecards: model and version, every input raw / transformed / points, band, mapped PD, outcome where the window has closed |
| What-If Analysis Data | `retail_whatif` | scenario PD/LGD/EAD/CCF, staging inputs, collateral and recovery, stressable score variables, weighted ECL |

`domains.reconcile()` proves each view is still the book: same months, same
row count, same distinct customers and facilities, same GCA, EAD and ECL
totals to 1e-9. It runs as a test.

---

## 3. What was fixed

Every defect below was reproduced first, then fixed, then gated, then re-run.

| ID | Severity | Defect | Root cause | Fix | Gate |
|---|---|---|---|---|---|
| OVN-01 | P1 | *"Break the credit card book down by subsegment"* then *"give me the worst 20 customers by expected credit loss"* → **"545,568 SAR of final ECL in Credit Card across 20 subsegments"**. The rows were customers. The book has nine subsegments. | The carried breakdown dimension outlived the question that asked for it; the headline counted the rows and named the carried dimension. | A question that asks to SEE entities — a top-N, or "the worst customers" — does not inherit the previous breakdown. A narrowing that merely names an entity noun still does. | `TestABreakdownDimensionDoesNotOutliveItsQuestion` |
| OVN-05 | **P1** | *"What is the 30+ DPD rate for credit cards?"* → **1.79%**. That is the whole book; the card book is at **3.70%**. Nothing on screen said the figure was not about cards. | The metric library holds no filters, and the metric route passed only the metric's own scope. Every population a question named was dropped. | The route carries the population the question named, composed the same way the planner reads it, and the sentence says which population it is about. | `TestAGovernedMetricIsAboutThePopulationTheQuestionNamed` |
| OVN-06 | P1 | The same drop made *"…by card behaviour segment"* group the whole book, reporting **13,213 non-card facilities under "(not set)"**. | As OVN-05, on the breakdown path. | The breakdown filters on the same population. | same |
| OVN-07 | P1 | *"Now by utilisation band."* widened silently back to the whole book — ">100% at 100.00%", one facility, under a question about cards. | A metric-route turn recorded no population, so the next turn had nothing to inherit. | The route records what it restricted to; a bare follow-up inherits it, and a question that widens is not held in. | `TestASettledPopulationSurvivesABareFollowUp` |
| OVN-08 | P1 | *"What proportion of the book is in Stage 2?"* → **100.00%**, and the secured share → **100.0%**. | Introduced by the OVN-05 fix: the question's "Stage 2" was applied as a population, so the share's denominator was restricted too. | A field the metric's formula already conditions on — anywhere, numerator or denominator — is the metric's business, not a population to re-apply. | existing cockpit gates, restored |
| OVN-09 | P2 | *"Only salary transfer customers."* dropped the stage breakdown on screen and returned one total. | Introduced by the OVN-01 fix: the guard read the entity noun alone. | Only a request for a LIST of entities skips the inheritance. | `tests/retail/test_ret_overnight_followups.py`, restored |
| OVN-10 | P2 | A card portfolio had nothing to be reviewed by: `product_subsegment` holds one value for Credit Card, so "break it down by subsegment" was truthfully answered "across 1 subsegment". | `card_behaviour_segment` — three values, populated on every card row — was not a governed dimension. | Governed, with aliases. | `TestACardBookHasADimensionToBeReviewedBy` |
| OVN-11 | P3 | Every seeded case study opened with its first question typed twice. | `threads.create` stores the opening question; the seeder then asked it again. | The seeder removes the row `create` wrote, so `ask` produces the question and its answer together. | `test_every_case_study_holds_real_answers` |
| OVN-12 | P3 | A rewritten case study was never rebuilt. | The seeder recognised a thread by name alone. | Keyed by name AND a fingerprint of its script. | same |
| OVN-13 | P3 | Data Builder listed a stray empty "Test Domain" left by a test run. | — | Removed, after checking it held no datasets. | `test_data_builder_offers_all_four_and_nothing_corporate` |

---

## 4. What was seeded

`backend/retail/workspace_seed.py`, invoked by
`scripts/bootstrap_retail_installation.py`. Idempotent, retail-guarded, and
everything it creates is marked demonstration material.

* **6 projects** — Retail Portfolio Review Q3 2026, Credit Card ODR
  Deterioration Investigation, Personal Finance Scorecard Monitoring, Retail
  IFRS 9 August 2026 Close, Auto Finance Early Warning Review, Home Finance
  Stage 2 Migration Review. Each carries its own standing instructions and
  default scope.
* **4 data-release notifications** — one per governed domain, through
  `publish_data_release_event`, the same hook Data Builder calls for a real
  release, with the real row counts and the real buttons.
* **3 working messages** — scorecard monitoring ready, risk review pack ready,
  EWS monthly review ready.
* **3 case-study threads**, filed under their projects, every answer produced
  by asking the question through the ordinary orchestration path:
  * Credit Card ODR deterioration — Aug 2026 (5 turns)
  * Personal Finance scorecard audit — Aug 2026 (5 turns)
  * Home Finance ECL and Stage 2 — Aug 2026 (4 turns)

---

## 5. Known limitations

Stated rather than hidden.

* **Credit Card has one `product_subsegment`** in the shipped lake. Case A
  therefore breaks the card book down by `card_behaviour_segment` and
  `utilisation_band`, which are real, populated and where the deterioration is
  visible. "Break the credit card book down by subsegment" is answered "across
  1 subsegment", which is true.
* **No AI provider is configured.** Every answer says so and is produced by the
  deterministic governed reader and runtime. Provider-backed chat is NOT RUN.
* **The frontend runs in development mode** and shows the Next.js issues
  indicator.

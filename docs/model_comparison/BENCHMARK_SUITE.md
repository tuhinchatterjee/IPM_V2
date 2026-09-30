# Analyst benchmark suite v2: questions, ASSISTED_V1, independent oracles

Code:
- `backend/model_lab/benchmark_questions.py` (registry)
- `assistance.py` (ASSISTED_V1)
- `benchmark_oracles.py` (oracles, version `lab-oracle-suite-1`)
- `evaluate.py` (`lab-eval-5`)

## Lanes

| Lane | What the model receives |
|---|---|
| FROZEN_BASELINE | Exactly the frozen AdvancedCockpit request: prompts, tools, history and limits. Nothing added. |
| ASSISTED_V1 | The same request, plus ONE extra system text block: the deterministic assistance packet for that question. It is appended by `AssistedProvider` at the lab's provider seam. |

**How the frozen engine is protected in ASSISTED_V1.**
- The frozen engine, validators, executor and Finalizer are unchanged, and the engine's own request objects are never mutated.
- The frozen engine counts input before the call and cannot see the packet, so the declared context capacity for an ASSISTED_V1 child is reduced by the packet's estimated tokens. The frozen `fits()` check therefore still guards the real total.

### The packet (14 sections, `assisted-v1.0`)

Its contents:

1. The question, verbatim.
2. The domain.
3. The intent.
4. The grain.
5. The relevant relations only.
6. The relevant fields only, with catalogue labels, types, units and definitions.
7. Metric definitions.
8. Units.
9. Time semantics: the period field, the calendar, and the latest and preceding quarters.
10. The catalogue's own join keys with their cardinality warnings. A quarterly join always lists `reporting_quarter`.
11. The filters the wording implies.
12. The output contract: dimensions, metrics, ranking or top-N, reconciliation and chart.
13. Generic tool-contract reminders.
14. Evidence discipline.

**Never included:** expected values, oracle results, other models' outputs, solution SQL, or causes.

**How this is enforced:**
- The packet is deterministic.
- The trace persists the exact packet per call and exports `assistance_packet.json`.
- Tests check that no oracle number and no SQL appears in any packet.

## Oracles

The oracles use pandas directly over the published Parquet release. They are independent of the engine and of any model's SQL or answer. Each question records:
- its spec: population, grain, filters, metrics, tolerances, permissible alternatives and materiality;
- the code hash and the data snapshot id;
- an expected-result artifact (`materialize`).

**Tolerances:** money ±0.01 SAR mn, counts exact, percentages ±0.01 pp.

| Q | Kind | Expected outputs |
|---|---|---|
| Q01 | table | Stage 2 EAD by sector. The existing `lab-oracle-2` path is unchanged, and the new table reproduces its values exactly. |
| Q02 | table | Stage 2 distinct-facility counts by sector; top 3; total. |
| Q03 | table + facts | Stage 2 EAD by sector in both quarters; change; largest increases and decreases. |
| Q04 | facts + table | Stage 2 bridge (1→2, 3→2, 2→1, 2→3, new, exited, stayer balance change), which reconciles exactly. Causes are UNVERIFIABLE. |
| Q05 | table | Downgraded borrowers (`rating_migration = DOWNGRADE`): prior and current rating, sector, EAD. |
| Q06 | tables | ECL by stage × sector, by stage, and by sector. The chart is checked separately (`CHART_PRESENT` / `NO_CHART_GENERATED`). |
| Q07 | tables + facts | Transition matrix on facility pairs; moves into Stage 2 by sector; new and exited counts. |
| Q08 | table | Top 10 Stage 2 borrowers by EAD, in order, with sector and rating. |
| Q09 | table | Sector components (Stage 2 EAD change, ECL change, downgraded and watch-list borrowers). No composite winner. |
| Q10 | facts | Stage 2 and 3, ECL, concentration, migration and downgrades. Causes are UNVERIFIABLE. |
| Q11 | table + facts | EAD by sector across all stages; portfolio total. |
| Q12 | table + facts | Stage 3 EAD and ECL by sector; totals. |
| Q13 | tables + facts | Stage 2 sector and top-10 borrower shares of the Stage 2 total. |
| Q14 | table + facts | Borrowers with at least one facility moving from Stage 1 or 2 into Stage 3: EAD, ECL, sector and rating. |
| Q15 | facts (review) | Fact set for quantitative claims. The overall judgement is review-only. |

**Grading.**
- Candidate tables are matched by **values**, not column names. Key columns are chosen by value overlap; when two keys share values (stage from and stage to), the assignment that reconciles wins.
- **Failure diagnoses:**
  - `WRONG_QUARTER`, `WRONG_STAGE_n`, `NO_QUARTER_FILTER` and `DUPLICATE_JOIN_INFLATION`, each matched against deliberately computed wrong-population references;
  - `DUPLICATE_ROWS`, `VALUES_INFLATED`, `WRONG_ORDER` and `WRONG_TOP_N`.
- **Numeric claims** are marked `CONSISTENT_WITH_ORACLE` or `NOT_IN_ORACLE_FACTS`. The second means needs review, never automatically wrong.

**Leak tests.**
- No oracle value appears in any packet, in the spec, or in any provider request outside the model's own tool results.
- The oracles read no engine or model output.

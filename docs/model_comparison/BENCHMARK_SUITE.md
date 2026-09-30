# Analyst benchmark suite v2: questions, ASSISTED_V1, independent oracles

Code:
- `backend/model_lab/benchmark_questions.py` (registry)
- `assistance.py` (ASSISTED_V1)
- `benchmark_oracles.py` (oracles, version `lab-oracle-suite-1`)
- `evaluate.py` (`lab-eval-6`)
- `opus_references.py` and `scripts/model_lab/opus_reference_set.py` (OPUS_REFERENCE_SET_V1)

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

## OPUS_REFERENCE_SET_V1: one saved Opus reference per question

File: `artifacts/model_comparison/reference_sets/OPUS_REFERENCE_SET_V1.json`. This file is versioned. The per-question answer snapshots are written next to it, under `OPUS_REFERENCE_SET_V1/<Q>/`.

**Every question records:**
- `question_id` and the exact `question_text`;
- `reference_comparison_id` and `opus_child_run_id`;
- `profile_id` (`opus-frozen`) and `model_id`;
- `data_snapshot_id` and `frozen_source_id`;
- `evaluator_version`, `evaluation_revision`, `evaluation_id` and `evaluation_sha256`;
- the oracle version and code hash;
- `state` and `created_at`;
- the Full Model I/O Trace availability (`FULL`, or `NOT_AVAILABLE` for a run that predates the trace);
- the answer artifacts with their SHA-256: `answer.json`, `evaluation_child.json`, `result_tables.json` and `code.json` (the SQL/Python steps and tool round trips);
- for a reference the set built, its export pack.

**Three concepts.**
- **Independent correctness** is the oracle.
- **Opus agreement** is the candidate compared with that question's saved Opus answer. It is never truth and never latency.
- **No live Opus comparator** child runs in the benchmark.

### Commands

```bash
python scripts/model_lab/opus_reference_set.py preflight      # default; no model call
python scripts/model_lab/opus_reference_set.py verify         # no model call
python scripts/model_lab/opus_reference_set.py build --confirm-paid-opus-calls
python scripts/model_lab/opus_reference_set.py import-runtime --from <runtime dir>
```

**preflight / verify** search the lab store and reuse an existing Opus comparison only when **all** of these hold:
- the question text matches exactly;
- the data snapshot is the same;
- the frozen source is the same;
- the lane is `FROZEN_BASELINE`;
- the Opus child and its evaluated child are `COMPLETED`;
- the evaluation is compatible;
- the records are intact: the spec hash recomputes, the frozen run records exist, and the evaluation parses.

Each rejection has its own status:

| Status | Meaning |
|---|---|
| `REFERENCE_COMPARISON_UNAVAILABLE` | The named comparison is not saved in this store. |
| `REFERENCE_CORRUPT` | The records are not intact. |
| `REFERENCE_NOT_COMPARABLE` | The question, snapshot, source or lane differs. |
| `REFERENCE_HAS_NO_OPUS_CHILD` | The comparison contains no Opus child. |
| `REFERENCE_IS_FIXTURE` | A fixture stands in for Opus. |
| `REFERENCE_OPUS_NOT_COMPLETED` | The Opus child did not complete. |
| `REFERENCE_NOT_EVALUATED` | The comparison has no evaluation. |
| `REFERENCE_EVALUATION_INCOMPATIBLE` | The evaluation lacks what agreement needs. |

Both commands print:
- the valid and missing references;
- the current `opus_spend` cap, the spend already used under it, and what is available;
- the required cap (missing × $3.00, the per-child reserved maximum);
- whether `COCKPIT_ANTHROPIC_API_KEY` is present (never its value).

**build** makes **at most one** unchanged frozen-provider Opus run per missing question (`FROZEN_BASELINE`, `comparator_id=opus-frozen`, group cap $3.00). It stops **before any call** in each of these cases:
- `--confirm-paid-opus-calls` is absent;
- the approval does not cover every missing reference; it prints `OPUS_SPEND_APPROVAL_REQUIRED`, `required_cap_usd`, `current_cap_usd` and `missing_questions`;
- the key is absent (`OPUS_KEY_REQUIRED`);
- the profile is not ready.

It never raises the approval. Further guarantees:
- Spend is recorded per reference against the approval grant.
- A crash resumes the same comparison (a stable idempotency key; the pending id is saved before waiting).
- A reference that fails verification becomes `REFERENCE_FAILED`, and only `--retry-failed` rebuilds it.

**Immutability.** A `READY` entry is re-verified on every preflight or verify. Any of the following makes it `INVALID` with the reason:
- a later evaluation revision;
- a changed spec;
- a changed snapshot file.

It is never replaced silently; `--replace-invalid` is an explicit operator decision.

**Q01.** The prior Mac Opus run `cmp-f364d8b6901a` is reused only after `import-runtime` has copied that runtime into an empty pod runtime and the run verifies there. Approvals, probes, pins and logs are never copied.

### Candidate gate

`benchmark_suite.py --run` verifies the set **read-only** before any candidate starts. The set file and every reference comparison stay byte-identical. It then refuses (`OPUS_REFERENCE_SET_INCOMPLETE`, exit 2) unless every suite question is `READY`.

Each model × lane × question cell:
- carries that question's `reference_comparison_id`, the same one for every model and both lanes;
- has `comparator_id=""`;
- records the reference id and evaluation revision in the checkpoint.

The runner never creates, re-evaluates or writes a reference, so candidate N triggers no Opus call. `--allow-missing-opus` runs without a reference for **diagnostic development only**: it is labelled in the checkpoint (`diagnostic_allow_missing_opus`, `MISSING_OPUS_REFERENCE (diagnostic run)`), and the production run and the bootstrap never use it.

### Report

Every cell shows the two dimensions separately:
- `independent_correctness`: the oracle verdict and checks;
- `opus_agreement`: the reference id, status, evaluation revision and evaluator, and `S1`–`S4` plus `FINAL`, each with its percentage or N/A and reason.

`cells.csv` carries `reference_comparison_id`, `reference_status`, `reference_evaluation_revision` and `opus_agreement_S1…FINAL`.

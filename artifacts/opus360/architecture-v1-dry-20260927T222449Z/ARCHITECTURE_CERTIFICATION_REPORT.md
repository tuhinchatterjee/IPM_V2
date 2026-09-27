# AdvancedCockpit architecture certification report — architecture-v1-dry-20260927T222449Z

> **DRY RUN — SCRIPTED ANALYST, NOT OPUS. Every figure below measures the HARNESS and the frozen deterministic pipeline driven by a scripted model. None of it is evidence about Opus.**

## Provenance

| Item | Value |
|---|---:|
| Frozen tag | `cockpit-round-h-live-pass-2026-09-23` |
| Frozen commit | `245c50e45786c6e0c866b281f9dd74da17d160b5` |
| Harness commit | `859f26aaf998b48d76e525edc8cedb4b6c3177d2` |
| Harness version | `opus360-harness-1.0.0` |
| Question bank SHA-256 | `e7198a69f8a9e8a9f39a5b15d2df8079e4ccc31c71cb9f48edc2092ffa7dff82` |
| Oracle references SHA-256 | `fd9b14215451836f16aaa6435b6bc91dfd195d03842fdd4dc386cd973596a164` |
| Protected manifest SHA-256 | `637c40b0b6e793bec437de4c74a1caad9cc7fc1cae1b96faecd9a134c8b7c6f7` |
| Model (requested) | `claude-opus-5` |
| Price card | `{'path': 'config/cockpit_v4/price_card.claude-opus-5.json', 'sha256': 'b097e774c7b036c8e8e6b7802586f4472fedc51da80df030a5541eb6cf473d5c', 'verified_at': '2026-09-21', 'price': {'input_usd_per_mtok': 5.0, 'output_usd_per_mtok': 25.0, 'cache_write_usd_per_mtok': 6.25, 'cache_read_usd_per_mtok': 0.5}}` |
| Releases | `{"corporate": "v4-saudi-corporate-20q-v4", "retail": "v4-saudi-retail-20m-v5"}` |
| Release fingerprints (this runtime) | `{"corporate": "c79d0fdf8753576f391f2a6bb84f281595e7445291a558abe639f6a43e22a740", "retail": "c23a15d78ba88d39aeae6983e68fff2230b644f5c8f91bec5c89085399f04e5b"}` |
| Release fingerprint note | `corporate: byte fingerprint c79d0fdf8753576f != approved e37236d0f6d4e494 (built_with {'numpy': '2.5.0', 'pandas': '3.0.3', 'pyarrow': '24.0.0', 'python': '3.12.3'}) | retail: byte fingerprint c23a15d78ba88d39 != approved a1e797dcc73236b7 (built_with {'numpy': '2.5.0', 'pandas': '3.0.3', 'pyarrow': '24.0.0', 'python': '3.12.3'}) | content parity against the Round H approved oracle values: 140 values, 14 journeys, 0 differences` |
| Python | `3.12.3` |
| Dependency lock SHA-256 | `fd9dd717f3ffd38a95179696efc6d4e733be65c2096ed6fd7a9b6b5306175b72` |
| Live | `False` |
| Spend cap | `None` |
| Wall-clock cap (h) | `None` |

## Protected-core proof

- Status: **PROTECTED_CORE_UNCHANGED**
- Files verified: 311
- git diff vs frozen commit on protected paths: (empty)
- Problems: none

## Architecture-level metrics

| Metric | Result |
|---|---:|
| core_turns | 250 |
| completed | 250 |
| passed | 250 |
| completion_rate | 100.0% |
| pass_rate | 100.0% |
| exact_oracle_pass_rate | 100.0% |
| analytical_oracle_pass_rate | 100.0% |
| behavioural_oracle_pass_rate | 100.0% |
| claims_total | 1,479 |
| supported_claim_rate | 100.0% |
| unsupported_claim_rate | 0.0% |
| incorrect_claims | 0 |
| numerical_error_rate | 0.0% |
| wrong_period_rate | 0.0% |
| wrong_population_rate | 0.0% |
| required_facts_total | 1,479 |
| required_facts_published | 1,479 |
| required_facts_artifact_only | 0 |
| first_pass_execute_rate | 100.0% |
| repair_rate | 0.0% |
| repair_success_rate | n/a |
| average_repairs | 0.0 |
| clarification_rate | 5.2% |
| avoidable_clarification_rate | 0.0% |
| clarification_required_detected | 1.0 |
| domain_leakage_rate | 0.0% |
| thread_continuity_rate | 100.0% |
| provider_transient_rate | 0.0% |
| deadline_failure_rate | 0.0% |
| budget_termination_rate | 0.0% |
| input_tokens_total | 552,000 |
| output_tokens_total | 138,000 |
| total_tokens | 690,000 |
| tokens_per_correct_answer | 2,760 |
| repair_tokens_total | 0.0 |
| finalization_tokens_total | 0.0 |
| provider_time_share | 5.0% |
| local_time_share | 95.0% |
| cost_total_usd | $7.8155 |
| cost_per_case_usd | $0.0313 |
| cost_per_correct_case_usd | $0.0313 |
| support_turns | 18 |
| harness_transient_retries | 0 |
| sdk_hidden_http_retries | 0 |
| rate_limit_events | 0 |
| token_reconciliation_rate | 100.0% |

**input_tokens**: mean 2,208, median 2,400, p75 2,400, p90 2,400, p95 2,400, p99 2,400, min 0.0, max 2,400 (n=250)

**output_tokens**: mean 552.0, median 600.0, p75 600.0, p90 600.0, p95 600.0, p99 600.0, min 0.0, max 600.0 (n=250)

**total_tokens_dist**: mean 2,760, median 3,000, p75 3,000, p90 3,000, p95 3,000, p99 3,000, min 0.0, max 3,000 (n=250)

**latency_ms**: mean 183.3, median 158.0, p75 212.2, p90 322.6, p95 376.2, p99 461.2, min 35.0, max 667.0 (n=248)

**static_context_tax**: mean 1.0, median 1.0, p75 1.0, p90 1.0, p95 1.0, p99 1.0, min 0.9, max 1.0 (n=248)

**history_tax**: mean 0.0, median 0.0, p75 0.0, p90 0.0, p95 0.0, p99 0.0, min 0.0, max 0.0 (n=248)

**tool_result_tax**: mean 0.0, median 0.0, p75 0.0, p90 0.0, p95 0.1, p99 0.1, min 0.0, max 0.1 (n=248)

## By test class

| Class | n | Pass | Median latency s | P95 latency s | Mean tokens | Cost |
|---|---:|---:|---:|---:|---:|---:|
| A_BASELINE | 50 | 100.0% | 0.1 | 0.2 | 3,000 | $1.3500 |
| B_PARAPHRASE | 50 | 100.0% | 0.2 | 0.3 | 3,000 | $1.3500 |
| C_COMPLEX | 40 | 100.0% | 0.3 | 0.5 | 3,000 | $1.0800 |
| D_THREAD | 50 | 100.0% | 0.1 | 0.2 | 2,700 | $1.2150 |
| E_CLARIFICATION | 20 | 100.0% | 0.1 | 0.1 | 2,100 | $0.3780 |
| F_GOVERNANCE | 20 | 100.0% | 0.2 | 0.3 | 1,650 | $0.2970 |
| G_REPEAT | 20 | 100.0% | 0.2 | 0.4 | 3,000 | $0.5400 |

## Biggest token sinks and slowest turns (evidence-based reasons)

### Top 20 by total tokens

| # | Case | Value | Reason |
|---:|---|---:|---|
| 1 | A-C01 | 3,000 | static context 96% of input |
| 2 | A-C02 | 3,000 | static context 96% of input |
| 3 | A-C03 | 3,000 | static context 96% of input |
| 4 | A-C04 | 3,000 | static context 96% of input |
| 5 | A-C05 | 3,000 | static context 96% of input |
| 6 | A-C06 | 3,000 | static context 96% of input |
| 7 | A-C07 | 3,000 | static context 95% of input |
| 8 | A-C08 | 3,000 | static context 95% of input |
| 9 | A-C09 | 3,000 | static context 96% of input |
| 10 | A-C10 | 3,000 | static context 96% of input |
| 11 | A-C11 | 3,000 | static context 95% of input |
| 12 | A-C12 | 3,000 | static context 96% of input |
| 13 | A-C13 | 3,000 | static context 96% of input |
| 14 | A-C14 | 3,000 | static context 95% of input |
| 15 | A-C15 | 3,000 | static context 96% of input |
| 16 | A-C16 | 3,000 | static context 95% of input |
| 17 | A-C17 | 3,000 | static context 93% of input |
| 18 | A-C18 | 3,000 | static context 96% of input |
| 19 | A-C19 | 3,000 | static context 95% of input |
| 20 | A-C20 | 3,000 | static context 96% of input |

### Top 20 by input tokens

| # | Case | Value | Reason |
|---:|---|---:|---|
| 1 | A-C01 | 2,400 | static context 96% of input |
| 2 | A-C02 | 2,400 | static context 96% of input |
| 3 | A-C03 | 2,400 | static context 96% of input |
| 4 | A-C04 | 2,400 | static context 96% of input |
| 5 | A-C05 | 2,400 | static context 96% of input |
| 6 | A-C06 | 2,400 | static context 96% of input |
| 7 | A-C07 | 2,400 | static context 95% of input |
| 8 | A-C08 | 2,400 | static context 95% of input |
| 9 | A-C09 | 2,400 | static context 96% of input |
| 10 | A-C10 | 2,400 | static context 96% of input |
| 11 | A-C11 | 2,400 | static context 95% of input |
| 12 | A-C12 | 2,400 | static context 96% of input |
| 13 | A-C13 | 2,400 | static context 96% of input |
| 14 | A-C14 | 2,400 | static context 95% of input |
| 15 | A-C15 | 2,400 | static context 96% of input |
| 16 | A-C16 | 2,400 | static context 95% of input |
| 17 | A-C17 | 2,400 | static context 93% of input |
| 18 | A-C18 | 2,400 | static context 96% of input |
| 19 | A-C19 | 2,400 | static context 95% of input |
| 20 | A-C20 | 2,400 | static context 96% of input |

### Top 20 by repair tokens

| # | Case | Value | Reason |
|---:|---|---:|---|
| 1 | A-C01 | 0 | static context 96% of input |
| 2 | A-C02 | 0 | static context 96% of input |
| 3 | A-C03 | 0 | static context 96% of input |
| 4 | A-C04 | 0 | static context 96% of input |
| 5 | A-C05 | 0 | static context 96% of input |
| 6 | A-C06 | 0 | static context 96% of input |
| 7 | A-C07 | 0 | static context 95% of input |
| 8 | A-C08 | 0 | static context 95% of input |
| 9 | A-C09 | 0 | static context 96% of input |
| 10 | A-C10 | 0 | static context 96% of input |
| 11 | A-C11 | 0 | static context 95% of input |
| 12 | A-C12 | 0 | static context 96% of input |
| 13 | A-C13 | 0 | static context 96% of input |
| 14 | A-C14 | 0 | static context 95% of input |
| 15 | A-C15 | 0 | static context 96% of input |
| 16 | A-C16 | 0 | static context 95% of input |
| 17 | A-C17 | 0 | static context 93% of input |
| 18 | A-C18 | 0 | static context 96% of input |
| 19 | A-C19 | 0 | static context 95% of input |
| 20 | A-C20 | 0 | static context 96% of input |

### Top 20 by history tokens (ESTIMATED)

| # | Case | Value | Reason |
|---:|---|---:|---|
| 1 | D-TD07-4 | 73.9 | static context 92% of input |
| 2 | D-TD07-5 | 71.0 | static context 91% of input |
| 3 | D-TD01-4 | 58.3 | static context 93% of input |
| 4 | D-TD07-3 | 53.1 | static context 93% of input |
| 5 | D-TD03-4 | 46.0 | static context 93% of input |
| 6 | D-TD06-4 | 43.5 | static context 94% of input |
| 7 | D-TD08-4 | 42.4 | static context 94% of input |
| 8 | D-TD01-3 | 39.6 | static context 93% of input |
| 9 | D-TD09-4 | 39.6 | static context 95% of input |
| 10 | D-TD08-5 | 38.7 | static context 94% of input |
| 11 | D-TD04-4 | 38.6 | static context 94% of input |
| 12 | D-TD03-3 | 37.6 | static context 95% of input |
| 13 | D-TD03-5 | 36.1 | static context 95% of input |
| 14 | D-TD04-5 | 35.4 | static context 94% of input |
| 15 | D-TD02-4 | 34.7 | static context 91% of input |
| 16 | D-TD05-5 | 34.5 | static context 94% of input |
| 17 | D-TD10-4 | 34.4 | static context 95% of input |
| 18 | D-TD08-3 | 32.8 | static context 95% of input |
| 19 | D-TD10-5 | 31.9 | static context 94% of input |
| 20 | E-14 | 31.5 | static context 94% of input |

### Top 20 by tool-result tokens (ESTIMATED)

| # | Case | Value | Reason |
|---:|---|---:|---|
| 1 | C-C14 | 156.3 | static context 91% of input |
| 2 | B-C13-1 | 156.2 | static context 91% of input |
| 3 | C-C06 | 156.2 | static context 91% of input |
| 4 | G-05-1 | 156.2 | static context 91% of input |
| 5 | G-05-2 | 156.2 | static context 91% of input |
| 6 | B-C13-2 | 156.1 | static context 91% of input |
| 7 | D-TD02-4 | 129.3 | static context 91% of input |
| 8 | C-C13 | 126.9 | static context 92% of input |
| 9 | B-C08-2 | 125.2 | static context 93% of input |
| 10 | A-C17 | 125.1 | static context 93% of input |
| 11 | B-C08-1 | 125.1 | static context 93% of input |
| 12 | C-C05 | 125.1 | static context 93% of input |
| 13 | G-03-1 | 125.1 | static context 93% of input |
| 14 | B-C12-1 | 125.0 | static context 93% of input |
| 15 | G-03-2 | 125.0 | static context 93% of input |
| 16 | B-C12-2 | 124.9 | static context 93% of input |
| 17 | C-C09 | 116.6 | static context 93% of input |
| 18 | D-TD02-3 | 111.7 | static context 93% of input |
| 19 | D-TD07-5 | 104.6 | static context 91% of input |
| 20 | C-R08 | 103.0 | static context 94% of input |

### Top 20 by model calls

| # | Case | Value | Reason |
|---:|---|---:|---|
| 1 | A-C01 | 2 | static context 96% of input |
| 2 | A-C02 | 2 | static context 96% of input |
| 3 | A-C03 | 2 | static context 96% of input |
| 4 | A-C04 | 2 | static context 96% of input |
| 5 | A-C05 | 2 | static context 96% of input |
| 6 | A-C06 | 2 | static context 96% of input |
| 7 | A-C07 | 2 | static context 95% of input |
| 8 | A-C08 | 2 | static context 95% of input |
| 9 | A-C09 | 2 | static context 96% of input |
| 10 | A-C10 | 2 | static context 96% of input |
| 11 | A-C11 | 2 | static context 95% of input |
| 12 | A-C12 | 2 | static context 96% of input |
| 13 | A-C13 | 2 | static context 96% of input |
| 14 | A-C14 | 2 | static context 95% of input |
| 15 | A-C15 | 2 | static context 96% of input |
| 16 | A-C16 | 2 | static context 95% of input |
| 17 | A-C17 | 2 | static context 93% of input |
| 18 | A-C18 | 2 | static context 96% of input |
| 19 | A-C19 | 2 | static context 95% of input |
| 20 | A-C20 | 2 | static context 96% of input |

### Top 20 by latency ms

| # | Case | Value | Reason |
|---:|---|---:|---|
| 1 | C-C07 | 667 | static context 94% of input |
| 2 | C-C08 | 588 | static context 94% of input |
| 3 | C-C14 | 464 | static context 91% of input |
| 4 | C-C02 | 458 | static context 94% of input |
| 5 | G-05-2 | 440 | static context 91% of input |
| 6 | B-C12-1 | 434 | static context 93% of input |
| 7 | C-C05 | 429 | static context 93% of input |
| 8 | C-C13 | 428 | static context 92% of input |
| 9 | C-C03 | 407 | static context 94% of input |
| 10 | C-C15 | 390 | static context 94% of input |
| 11 | G-05-1 | 383 | static context 91% of input |
| 12 | G-04-2 | 381 | static context 94% of input |
| 13 | C-C06 | 378 | static context 91% of input |
| 14 | B-C02-2 | 373 | static context 96% of input |
| 15 | G-04-1 | 372 | static context 94% of input |
| 16 | F-12 | 358 | static context 99% of input |
| 17 | C-C01 | 355 | static context 95% of input |
| 18 | B-C11-2 | 352 | static context 94% of input |
| 19 | C-C09 | 345 | static context 93% of input |
| 20 | B-C10-1 | 340 | static context 94% of input |

## Paraphrase invariance

| Group | Classification | Members | Oracle pass |
|---|---|---|---|
| PG-C01 | INVARIANT | A-C01, B-C01-1, B-C01-2 | [True, True, True] |
| PG-C02 | INVARIANT | A-C02, B-C02-1, B-C02-2 | [True, True, True] |
| PG-C03 | INVARIANT | A-C07, B-C03-1, B-C03-2 | [True, True, True] |
| PG-C04 | INVARIANT | A-C09, B-C04-1, B-C04-2 | [True, True, True] |
| PG-C05 | INVARIANT | A-C12, B-C05-1, B-C05-2 | [True, True, True] |
| PG-C06 | INVARIANT | A-C13, B-C06-1, B-C06-2 | [True, True, True] |
| PG-C07 | INVARIANT | A-C16, B-C07-1, B-C07-2 | [True, True, True] |
| PG-C08 | INVARIANT | A-C17, B-C08-1, B-C08-2 | [True, True, True] |
| PG-C09 | INVARIANT | A-C22, B-C09-1, B-C09-2 | [True, True, True] |
| PG-C10 | INVARIANT | B-C10-1, B-C10-2, C-C01 | [True, True, True] |
| PG-C11 | INVARIANT | B-C11-1, B-C11-2, C-C02 | [True, True, True] |
| PG-C12 | INVARIANT | B-C12-1, B-C12-2, C-C05 | [True, True, True] |
| PG-C13 | INVARIANT | B-C13-1, B-C13-2, C-C06 | [True, True, True] |
| PG-R01 | INVARIANT | A-R01, B-R01-1, B-R01-2 | [True, True, True] |
| PG-R02 | INVARIANT | A-R04, B-R02-1, B-R02-2 | [True, True, True] |
| PG-R03 | INVARIANT | A-R05, B-R03-1, B-R03-2 | [True, True, True] |
| PG-R04 | INVARIANT | A-R06, B-R04-1, B-R04-2 | [True, True, True] |
| PG-R05 | INVARIANT | A-R11, B-R05-1, B-R05-2 | [True, True, True] |
| PG-R06 | INVARIANT | A-R14, B-R06-1, B-R06-2 | [True, True, True] |
| PG-R07 | INVARIANT | A-R16, B-R07-1, B-R07-2 | [True, True, True] |
| PG-R08 | INVARIANT | A-R18, B-R08-1, B-R08-2 | [True, True, True] |
| PG-R09 | INVARIANT | A-R19, B-R09-1, B-R09-2 | [True, True, True] |
| PG-R10 | INVARIANT | B-R10-1, B-R10-2, C-R01 | [True, True, True] |
| PG-R11 | INVARIANT | B-R11-1, B-R11-2, C-R02 | [True, True, True] |
| PG-R12 | INVARIANT | B-R12-1, B-R12-2, C-R05 | [True, True, True] |

## Repeatability

| Group | All pass | SQL identical | Tool sequence identical | Token CV | Latency CV |
|---|---|---|---|---:|---:|
| RG-01 | True | True | True | 0.0 | 0.0576 |
| RG-02 | True | True | True | 0.0 | 0.0949 |
| RG-03 | True | True | True | 0.0 | 0.0611 |
| RG-04 | True | True | True | 0.0 | 0.1366 |
| RG-05 | True | True | True | 0.0 | 0.0384 |
| RG-06 | True | True | True | 0.0 | 0.1383 |
| RG-07 | True | True | True | 0.0 | 0.0956 |
| RG-08 | True | True | True | 0.0 | 0.0702 |
| RG-09 | True | True | True | 0.0 | 0.1469 |
| RG-10 | True | True | True | 0.0 | 0.0636 |

## Threads

| Thread | Passed turns | Continuity 2-5 | Leaks | Stale context | Input tokens by turn | Latency ms by turn |
|---|---:|---:|---:|---:|---|---|
| TD01 | 5/5 | 100.0% | 0 | 0 | [2400, 2400, 2400, 2400, 1200] | [144, 110, 135, 126, 174] |
| TD02 | 5/5 | 100.0% | 0 | 0 | [1200, 1200, 2400, 2400, 1200] | [71, 73, 109, 95, 86] |
| TD03 | 5/5 | 100.0% | 0 | 0 | [2400, 2400, 2400, 2400, 2400] | [131, 121, 87, 168, 137] |
| TD04 | 5/5 | 100.0% | 0 | 0 | [2400, 2400, 2400, 2400, 2400] | [104, 105, 58, 117, 110] |
| TD05 | 5/5 | 100.0% | 0 | 0 | [2400, 0, 2400, 2400, 2400] | [217, 'UNKNOWN', 88, 154, 241] |
| TD06 | 5/5 | 100.0% | 0 | 0 | [2400, 1200, 2400, 2400, 1200] | [126, 166, 176, 187, 125] |
| TD07 | 5/5 | 100.0% | 0 | 0 | [2400, 2400, 2400, 2400, 2400] | [134, 158, 118, 104, 144] |
| TD08 | 5/5 | 100.0% | 0 | 0 | [2400, 2400, 2400, 2400, 2400] | [80, 101, 155, 130, 117] |
| TD09 | 5/5 | 100.0% | 0 | 0 | [2400, 0, 2400, 2400, 2400] | [112, 'UNKNOWN', 173, 100, 111] |
| TD10 | 5/5 | 100.0% | 0 | 0 | [2400, 2400, 2400, 2400, 2400] | [123, 108, 115, 95, 128] |

## Load microtest (not part of core certification)

| Concurrency | Runs | Pass | Median queue wait ms | Throughput/min | 429 admissions | Deadline failures |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 12 | 12 | 17.5 | 158.584 | 0 | 0 |
| 2 | 12 | 12 | 59.0 | 251.84 | 0 | 0 |
| 4 | 12 | 12 | 59.0 | 225.24 | 4 | 0 |

## Every non-passing turn

| Case | Class | Cause | Severity | Why |
|---|---|---|---|---|

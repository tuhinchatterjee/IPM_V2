# Client-presentability audit

§5, run against the real orchestrator. Every row is a question put through the same path a client uses; nothing here is a fixture that agrees with the checker.

**15 of 15 answer types clean.**

Run with `--persist`, so the three criteria keyed on a persisted run id - the feedback control, How CreditProbe Performed and the stated limitations - are measured rather than excused.

Where a criterion cannot be established from outside the answer it reads NOT MEASURED rather than PASS. An audit that scored its own blind spots as passes would be worth less than no audit.

## Results

| Question | Kind | Verdict | Failing criteria |
|---|---|---|---|
| What ratings data do you have? | metadata | PASS | - |
| How is ratings data connected to IFRS 9? | metadata | PASS | - |
| What is total exposure at default by sector in the latest quarter? | analysis | PASS | - |
| Show the five largest Real Estate customers. | clarification | PASS | - |
| Show the five largest Real Estate customers by EAD. | analysis | PASS | - |
| What is the Stage 2 EAD share by sector versus four quarters ago? | analysis | PASS | - |
| Which customers had a rating downgrade and an increase in expected credit loss over the latest year? | analysis | PASS | - |
| Which customers have worsening leverage, declining DSCR and a rating downgrade? | analysis | PASS | - |
| Which Real Estate customers have worsening days past due, increasing ECL, a downgrade and covenant headroom below 15%? | analysis | PASS | - |
| Investigate Contracting. | investigation | PASS | - |
| Review the latest portfolio for CRO attention. | investigation | PASS | - |
| What is total ECL, and break the change down by sector? | compound | PASS | - |
| Show me exposure. | clarification | PASS | - |
| Did the CEO of the largest Contracting borrower resign? | unsupported | PASS | - |
| How much of the book is risky? | clarification | PASS | - |

## Criteria, answer by answer

| Criterion | metadata_datasets | metadata_join | simple_aggregate | ranked_no_measure | ranked | period_comparison | multi_condition | three_condition | four_condition | broad_investigation | portfolio_review | compound | ambiguous | unsupported | undefined_term |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| answers_rather_than_stalling | PASS | PASS | PASS | - | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | - | - | - |
| direct_bottom_line | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| every_objective_addressed | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| correct_population_and_scope | N/A | N/A | PASS | N/A | PASS | PASS | PASS | PASS | PASS | N/A | N/A | PASS | N/A | N/A | N/A |
| correct_data_and_relationships | PASS | PASS | PASS | N/A | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A | N/A | N/A |
| result_present | N/A | N/A | PASS | N/A | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A | N/A | N/A |
| invariants_checked | N/A | N/A | PASS | N/A | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A | N/A | N/A |
| grounded_interpretation | N/A | N/A | PASS | N/A | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A | N/A | N/A |
| no_repetition | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| no_unsupported_causal_claim | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| limitations_stated | NOT MEASURED | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | NOT MEASURED | NOT MEASURED | PASS | PASS | PASS | PASS |
| contextual_next_questions | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A | PASS |
| honest_trace | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| max_two_decimals | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| feedback_control_reachable | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| how_creditprobe_performed | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| no_unexplained_failure | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| stops_rather_than_guessing | - | - | - | PASS | - | - | - | - | - | - | - | - | PASS | PASS | PASS |

## Not measured

These criteria could not be established from outside the answer. They are gaps in this audit, not evidence of a defect and not evidence of correctness:

* `limitations_stated`


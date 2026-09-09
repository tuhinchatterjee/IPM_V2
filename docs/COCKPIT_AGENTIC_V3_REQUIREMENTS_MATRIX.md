# Cockpit Agentic V3 — requirement → code → test → status

Every non-negotiable in `docs/COCKPIT_AGENTIC_V3_MASTER_SPEC.md` and in the
task instruction, against what actually exists. **Status is what is true, not
what was intended.**

Legend: **DONE** — implemented and tested. **PARTIAL** — implemented with a
stated limitation. **BLOCKED** — cannot be verified in this environment, and
why. **NOT DONE** — not implemented.

## The eighteen non-negotiables from the task instruction

| # | Requirement | Code | Test / evidence | Status |
|---:|---|---|---|---|
| 1 | Cockpit reads only the restricted 20-quarter domain | `scope.py`, `sql.open_session`, `fields.py` | `test_sql_security.py` — 25 tests against a real engine | **DONE** |
| 2 | No EWS, Credit Scoring, Scorecard Validation, What-if or Lenses data | `scope.ALLOWED`, materialized session | `test_another_module_is_not_reachable`, `test_the_engine_blocks_file_access_even_past_the_validator` | **DONE** |
| 3 | Sonnet pass 1: cleanup and faithful translation | `sonnet.clean`, `prompts/sonnet_pass1_cleanup.md` | `test_a_failed_pass_one_preserves_the_raw_question`; multilingual cases in the benchmark | **PARTIAL** — mechanism tested; fidelity needs a live model |
| 4 | Sonnet pass 2: business request, ambiguity preserved | `sonnet.normalize`, `prompts/sonnet_pass2_normalize.md` | `test_an_explicit_instruction_overrides_an_inherited_filter` | **PARTIAL** — same |
| 5 | CreditProbe builds the factual context packet (A–J) | `context.build` | `test_context_and_registry.py` — 25 tests | **DONE** |
| 6 | Opus performs the functionality gate FIRST | `opus.gate`, `states.TRANSITIONS` | `test_the_gate_cannot_be_skipped`, `test_an_ews_question_is_referred_and_executes_nothing` | **DONE** |
| 7 | Opus owns reasoning, plan, method, SQL, repair, review, answer | `opus.py`, `runtime.py` | `test_creditprobe_returns_facts_and_opus_writes_the_repair` | **DONE** |
| 8 | No compulsory analytical templates | `contracts.AnalysisPlan.method_summary` is free text; no method enum anywhere | `test_the_ratio_definitions_are_labelled_semantics_not_a_template` | **DONE** |
| 9 | CreditProbe does NOT repair Opus SQL/Python | `failure.py`, `sql.execute` | `test_creditprobe_returns_facts_and_opus_writes_the_repair`; `repair_request_shape.json` `carries_no_repaired_query: true` | **DONE** |
| 10 | Failure returns full retained context + diagnostics | `failure.build`, `opus.Conversation` | `test_repair_context.py` — 17 tests on the real serialized request | **DONE** |
| 11 | Max FIVE execution submissions, never reset | `ledger.note_submission` | `test_five_failed_submissions_and_no_sixth`, `test_a_new_plan_does_not_reset_the_submission_counter`, `test_no_nested_loop_multiplication` | **DONE** |
| 12 | Max THREE analysis rounds including the first | `ledger.note_analysis_round` | `test_three_insufficient_rounds_stop_without_a_fourth` | **DONE** |
| 13 | After five, Opus stops and explains in business English | `runtime._submissions_exhausted` | `test_five_failed_submissions_and_no_sixth` asserts "not being asked to fix SQL" | **DONE** |
| 14 | After three rounds, stop and ask a targeted clarification | `runtime._round_limited` | `test_three_insufficient_rounds_stop_without_a_fourth` | **DONE** |
| 15 | 60s Standard / 120s Deep and the rest of §9 | `ledger.Limits`, `STANDARD_LIMITS`, `DEEP_LIMITS` | `test_ledger.py` — 24 tests | **PARTIAL** — see the guardrail table below |
| 16 | Rolling summary; 3 / 5 / 8 pairs; one bounded Sonnet call | `thread.select`, `sonnet.update_summary` | `test_thread_and_api.py` — 22 tests | **DONE** |
| 17 | No hidden fallback to the deterministic engine | separate router; no import of `orchestration` or `analyst` in `cockpit_agentic/` | `test_no_provider_is_reported_never_substituted`; `test_without_a_credential_the_api_says_so_and_substitutes_nothing` | **DONE** |
| 18 | No canned ECL decomposition; mocks labelled; live UAT BLOCKED | `attribution.py` not imported by V3; every mock labelled | `run_ownership_eval.py` exits BLOCKED without a credential | **DONE** |

## The guardrails of §9.1

| Guardrail | Standard | Deep | Enforced in | Status |
|---|---:|---:|---|---|
| Sonnet preprocessing calls | 2 | 2 | `ledger.settle` counts by purpose | DONE |
| Sonnet summary calls | 1 | 1 | same | DONE |
| **Execution submissions** | **5** | **5** | `note_submission` | DONE — **no override at any level** |
| **Analysis rounds** | **3** | **3** | `note_analysis_round` | DONE — **no override at any level** |
| Total provider requests | 12 | 16 | `reserve` | DONE (configurable upward) |
| Metadata tool requests | 2 | 3 | `note_metadata_request` | DONE |
| Steps per submission | 6 | 8 | `note_steps` | DONE |
| Steps per request | 12 | 24 | `note_steps` | DONE |
| Overall deadline | 60s | 120s | `reserve`, `may_continue` | DONE (configurable upward) |
| Cumulative tokens | 35,000 | 70,000 | `reserve` | DONE (configurable upward) — **see below** |
| Max input per call | 12,000 | 20,000 | `reserve` | DONE (configurable upward) — **see below** |
| Max Opus output | 4,096 | 6,144 | `Conversation.ask`; truncation is INCOMPLETE | DONE |
| Sonnet pass 1 / 2 / summary output | 800 / 1,200 / 1,000 | same | `sonnet._call` | DONE |
| Recent pairs | 3 / 5 / 8 | same | `thread.select` | DONE |
| Recent history tokens | 4,000 | 8,000 | `thread.select` | DONE |
| Samples per dataset | 10 | 10 | `context.build` | DONE |
| SQL wall time per step | 15s | 30s | `sql.execute` watchdog | DONE |
| Summary wall time | 8s | 8s | `Limits.summary_wall_seconds` | PARTIAL — the limit is declared and the deadline is enforced globally; a dedicated per-call summary timer is not separately implemented |
| Max charts | 2 | 3 | `runtime._answer` | DONE |
| Spend ceiling | $1.00 | $2.00 | `reserve` | **PARTIAL** — enforced only when prices are configured. With none, spend is `UNKNOWN` and the ledger says the ceiling is not a control |

**The two that need an administrator.** The complete field dictionary is ~22,078
tokens and the whole packet ~28,000 after every reduction, so §9.1's 12,000
input cap and 35,000 token ceiling cannot hold this domain's mandatory
catalogue. §7.4 names this case and says to fix the serialization or the
configuration. The serialization was fixed as far as it honestly goes
(29,600 → 22,078 with no field lost); the configuration half is two settings
defaulting to the specification's values, raising only, reported through
`overrides_in_force`. Nothing raises itself. See
[`CONTEXT_SIZING.md`](cockpit_agentic_v3/CONTEXT_SIZING.md).

## The domain of §3 and §4

| Requirement | Evidence | Status |
|---|---|---|
| Exactly 20 ordered consecutive reporting slots | `calendar.Calendar` refuses otherwise; `test_a_calendar_that_is_not_twenty_slots_is_refused` | DONE |
| Macro window −4…+15, a SECOND axis | `test_the_macro_window_at_the_last_anchor_matches_the_worked_example`, `test_macro_targets_extend_past_the_calendar_without_extending_it` | DONE |
| No 21st quarter reachable | `test_no_query_can_reach_a_twenty_first_quarter` against a real engine | DONE |
| Populated ≠ created | `Calendar.missing`; `check_populated_is_honest` | DONE |
| 40 ratios with source/derived/status | `test_every_ratio_has_a_status_and_a_source_value_companion` | DONE |
| 19 grades, default separate | `test_nineteen_grades_ranked_aaa_to_c_with_default_kept_separate` | DONE |
| 20 qualitative questions | `test_exactly_twenty_qualitative_questions_with_stable_ids` | DONE |
| 12 collateral types × 9 = 108 real names | `test_twelve_collateral_types_expand_to_one_hundred_and_eight_columns`; zero placeholders | DONE |
| 10 macro factors, 200 pivot cells | `test_ten_macro_factors_yield_two_hundred_pivot_cells_not_two_hundred_factors` | DONE |
| PIT/TTC × 12m/lifetime all distinct | `test_the_four_pd_fields_are_all_present_and_distinct`; `check_pit_and_ttc_differ` in the data | DONE |
| Lifetime PD is not annual × years | `check_lifetime_is_not_annual_times_years` — under 5% of positions match | DONE |
| PD×LGD×EAD does not reproduce ECL | `check_a_single_pd_lgd_ead_product_does_not_reproduce_ecl` | DONE |
| Field-level profile from FULL data | `profile.profile_release`; `test_the_profile_is_computed_from_the_whole_release` | DONE |
| A global rate does not hide an empty quarter | `test_a_global_rate_does_not_conceal_an_empty_quarter` | DONE |
| Real data ingested | — | **NOT DONE** — this release is the labelled synthetic demonstration; every field is `demo_only` and `COCKPIT_DATA_DOMAIN_MAPPING.md` says so |

## Safety, §10

| Requirement | Evidence | Status |
|---|---|---|
| Least-privilege read-only SQL principal | Materialized session; `enable_external_access=false`; `lock_configuration=true` | DONE |
| No writes, DDL, multi-statement, file, network | 12 refusal tests, plus one that bypasses the validator entirely | DONE |
| Statement timeout / cancellation | `sql.execute` watchdog; `test_a_runaway_query_is_cancelled_at_the_deadline` | DONE |
| Tenant enforced below the model | `test_the_tenant_filter_is_in_the_table_not_in_the_model_s_query` | DONE |
| Errors leak no path or foreign schema | `test_error_messages_never_leak_a_path_or_another_schema` | DONE |
| **Isolated Python execution** | `context` and `diagnostics` report `available: false` with the reason; a Python step is refused with `SANDBOX_UNAVAILABLE` | **NOT DONE, reported** — §10.2 requires disabling it and stating the limitation rather than downgrading to in-process `exec`, and that is what happens |
| Untrusted data note travels with the packet | `test_the_untrusted_data_note_travels_with_the_packet` | DONE |

## Tests and acceptance, §14

| Gate | Evidence | Status |
|---|---|---|
| §14.1 data/domain tests | 72 integrity checks; the build refuses to publish a failing release | DONE |
| §14.2 ownership tests | 25 labelled cases; 11 mechanism tests | **PARTIAL** — routing accuracy needs a live model |
| §14.2 every referral executes ZERO SQL | Asserted from the runtime's own record, four modules parameterized | DONE |
| §14.3 retry/context tests on the real serialized request | 17 tests + committed trace | DONE |
| §14.4 global budgets and security | 24 ledger tests, 25 security tests against a real engine | DONE |
| §14.5 independent numerical fixtures | 72 data gates are independent oracles over the generator | PARTIAL |
| §14.5 labelled benchmark, measured | `run_ownership_eval.py` | **BLOCKED** — no credential |
| §14.5 real browser UAT | `docs/COCKPIT_AGENTIC_V3_UAT.md` script; frontend typechecks and lints | **BLOCKED** — no credential, and no browser driver run in this container |
| §14.5 baseline regression in a matching configuration | Worktree at the branch point, same flags: 589 failures there, 588 here, **zero new failures outside this work's own tests** | DONE |
| Other modules undamaged | Same comparison; `backend/cockpit_agentic/` imports nothing from `orchestration` or `analyst` | DONE |

## Documents required by §15

| Document | Status |
|---|---|
| `docs/COCKPIT_AGENTIC_V3_MASTER_SPEC.md` | DONE (the supplied replacement, verbatim) |
| `docs/COCKPIT_AGENTIC_V3_REQUIREMENTS_MATRIX.md` | this file |
| `docs/COCKPIT_AGENTIC_V3_BASELINE_AUDIT.md` | DONE |
| `docs/COCKPIT_20_QUARTER_DATA_DICTIONARY.md` + machine-readable catalogue | DONE — generated from code |
| `docs/COCKPIT_DATA_DOMAIN_MAPPING.md` | DONE — generated from code |
| `docs/COCKPIT_FUNCTIONALITY_BOUNDARIES.md` | DONE — generated, routes verified |
| `docs/COCKPIT_CONTEXT_AND_FAILURE_CONTRACT.md` | DONE — with a captured trace |
| `docs/COCKPIT_AGENTIC_V3_UAT.md` and a measured evaluation report | UAT script DONE; the measured report is **BLOCKED** |

## What is honestly not done

1. **No live-provider verification of anything.** No credential is configured
   in this environment. Every model-dependent behaviour — routing accuracy,
   translation fidelity, plan quality, repair quality, answer quality, latency,
   token and cost measurement — is **UNVERIFIED**. The mocks prove the
   application's guarantees and nothing about the model's.
2. **Isolated Python execution is not implemented.** Reported as a capability
   limitation, never downgraded.
3. **No real source data.** The release is the labelled synthetic
   demonstration.
4. **The specification's own token limits do not fit its own catalogue.**
   Measured, documented, and put to an administrator.
5. **The spending ceiling is not a control** until prices are configured.
6. **Thread state is in-memory.** `backend/services/threads.py` exists and is
   the intended durable seam; the V3 thread layer is about selection and
   boundary, and binding it to that store is not done.
7. **A dedicated per-summary-call timer** is not separately implemented; the
   global deadline covers it.

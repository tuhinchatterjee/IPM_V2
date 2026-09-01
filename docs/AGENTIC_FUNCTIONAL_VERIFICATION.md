# Agentic AI — functional verification

**Status: `LOCAL_RUNTIME_VERIFICATION_REQUIRED`**

Every line below names the test that establishes it. That is deliberate:
"the officer is working" is a spinner, not evidence, and a verification
document that reports spinners is a document that verifies nothing. Where a
capability is not proven, the row says so rather than borrowing credit from
the row above it.

Everything ran offline. No Anthropic call was made, no key was read, and no
credit was consumed; every agentic test uses fake providers and deterministic
fixtures. That makes this document a statement about the ORCHESTRATION —
which agent, which tool, which order, which refusal — and not about model
quality. Model quality needs the live workflow in
`docs/AGENTIC_LIVE_VERIFICATION.md`, which has not been run here.

**Evidence base:** 184 tests in `tests/agentic/`, all passing, plus the
assurance and consistency suites named in the rows.

---

## 1. Officer selection

Four levels, and the level follows the SHAPE of the work — its grain and its
breadth — rather than the difficulty of the sentence.

| Claim | Test |
|---|---|
| Every level has a remit | `test_every_level_has_a_remit` |
| A deterministic request is a Credit Analyst's | `test_a_deterministic_request_is_always_a_credit_analyst` |
| A facility-grain grouping stays level 1 | `test_a_facility_grain_grouping_stays_a_credit_analysts_work` |
| A segment question reaches the Portfolio Risk Lead | `test_a_segment_question_reaches_the_portfolio_risk_lead` |
| An open-ended look at the book is coordinated work | `test_an_open_ended_look_at_the_whole_book_is_coordinated_work` |
| Three specialists forces a Chief Orchestrator whatever it scored | `test_three_specialists_means_a_chief_orchestrator_whatever_it_scored` |
| Two specialists is NOT coordinated work | `test_two_specialists_is_not_coordinated_work` |
| The level is not a property of one word | `test_the_level_is_not_a_property_of_one_word` |
| Grain separates two questions that score the same | `test_grain_separates_two_questions_that_score_the_same` |
| Risk can reach a level complexity would not | `test_risk_can_reach_a_level_complexity_would_not` |
| A proactive run is scored as risk, not complexity | `test_a_proactive_run_is_scored_as_risk_not_complexity` |
| Escalation never demotes, and records where it came from | `test_escalation_never_demotes`, `test_escalation_records_where_it_came_from` |
| Demo Safe Mode raises the risk score | `test_demo_safe_mode_raises_the_risk_score` |
| The five representative questions land where §12 says | `test_the_five_representative_questions` |

## 2. Specialist selection

Thirteen agents; twelve specialists plus the Chief Orchestrator. Selection is
by governed CONCEPT, not by keyword.

| Claim | Test |
|---|---|
| Every §12 specialist is defined | `test_every_specialist_section_twelve_names_is_defined` |
| Every governed domain has a specialist that exists | `test_every_governed_domain_has_a_specialist_that_exists` |
| The specialists a question needs come from its concepts | `test_the_specialists_a_question_needs_come_from_its_concepts` |
| A relationship-graph question reaches its own specialist | `test_the_relationship_graph_reaches_its_own_specialist` |
| The graph specialist cannot read the retail book | `test_the_graph_specialist_cannot_read_the_retail_book` |
| A concept no domain owns needs no specialist | `test_an_unowned_concept_needs_no_specialist` |
| Every concept domain maps to a known domain | `test_every_concept_domain_maps_to_a_known_domain` |
| Order is stable between identical requests | `test_agent_order_is_stable` |
| The orchestrator cannot delegate to itself | `test_the_orchestrator_cannot_delegate_to_itself` |
| Every field of the definition contract is present | `test_every_field_of_the_definition_contract_is_present` |
| The registry fingerprint moves with a change | `test_the_registry_has_a_fingerprint_that_moves_with_a_change` |
| Model role preference is a ROLE, not a model | `test_model_role_preference_is_a_role_not_a_model` |

The thirteenth agent — **Relationship Graph** — was added in this phase.
Every other domain the product has had an owning specialist and the corporate
relationship graph did not, so a connected-group or beneficial-ownership
question fell to the generalist. That is the one class of question where the
generalist is most exposed: every graph measure has a near-neighbour a
plausible answer could substitute for it. The specialist carries the
escalation rules that say so, and is scoped to three data domains rather than
to all eight.

## 3. The task DAG

| Claim | Test |
|---|---|
| Ready returns only tasks whose dependencies SUCCEEDED | `test_ready_only_returns_tasks_whose_dependencies_succeeded` |
| A failed task blocks its dependants rather than failing them | `test_a_failed_task_blocks_what_depended_on_it_rather_than_failing_it` |
| Independent specialists share a layer | `test_independent_specialists_share_a_layer` |
| The assurance task depends on every specialist | `test_the_assurance_task_depends_on_every_specialist` |
| A composed plan validates | `test_a_composed_plan_validates` |
| A failed step fails its stage | `test_a_failed_step_fails_its_stage` |
| A run cannot move backwards through the stages | `test_a_run_cannot_move_backwards_through_the_stages` |
| Every stage carries its §7 caption | `test_every_stage_has_the_caption_section_seven_specifies` |
| A scope detail replaces the generic caption | `test_a_scope_detail_replaces_the_generic_caption` |
| The stages a run passes through are reported | `test_the_stages_a_run_passes_through_are_reported` |

## 4. Governed tools

Twenty-two tools. No tool compiles arbitrary SQL; `RUN_ANALYSIS` takes a
validated Analytical IR and nothing else.

| Claim | Test |
|---|---|
| A tool that does not exist is refused | `test_a_tool_that_does_not_exist_is_refused` |
| A tool the agent was not granted is refused | `test_a_tool_the_agent_was_not_granted_is_refused` |
| Refused at run time too, not only at plan time | `test_a_task_using_a_tool_its_agent_lacks_is_refused_at_run_time_too` |
| A domain outside the agent's permission is refused | `test_a_domain_outside_the_agents_permission_is_refused` |
| A missing required parameter is refused | `test_a_missing_required_parameter_is_refused` |
| An unknown parameter is refused rather than ignored | `test_an_unknown_parameter_is_refused_rather_than_ignored` |
| Refusal happens before a handler is reached | `test_invoke_refuses_before_reaching_a_handler` |
| The principal is passed to a data-reading tool | `test_invoke_passes_the_principal_to_a_data_reading_tool` |
| A permitted call is allowed | `test_a_permitted_call_is_allowed` |
| No agent has unrestricted tools | `test_no_agent_has_unrestricted_tools` |
| No agent is given a tool that does not exist | `test_no_agent_is_given_a_tool_that_does_not_exist` |
| An approved tool with no handler is reported honestly | `test_an_approved_tool_with_no_handler_is_reported_honestly` |
| Audit parameters summarise rather than copy the data | `test_audit_parameters_summarise_rather_than_copy_the_data` |

## 5. Autonomy and material actions

| Claim | Test |
|---|---|
| No agent may perform a material action | `test_no_agent_may_perform_a_material_action` |
| No tool exists that performs a material action | `test_no_tool_exists_that_performs_a_material_action` |
| There is no tool for a level-four action | `test_there_is_no_tool_for_a_level_four_action` |
| No agent claims level-four autonomy | `test_no_agent_claims_level_four_autonomy` |
| The generally dangerous capabilities have no tool either | `test_the_generally_dangerous_capabilities_have_no_tool_either` |
| Every writing tool produces a DRAFT | `test_every_writing_tool_produces_a_draft` |
| No agent is shipped above draft | `test_no_agent_is_shipped_above_draft` |
| An agent's own definition can narrow its autonomy further | `test_an_agents_own_definition_can_narrow_its_autonomy_further` |
| An undefined action is treated as MATERIAL | `test_an_undefined_action_is_treated_as_material` |
| Nothing is pre-approved as shipped | `test_nothing_is_pre_approved_as_shipped` |
| Pre-approved without a policy is approved by nobody | `test_pre_approved_without_a_policy_is_approved_by_nobody` |

## 6. Approval gates

| Claim | Test |
|---|---|
| A gate offers exactly the five actions | `test_a_gate_offers_exactly_the_five_actions` |
| A gate states what a person is agreeing to | `test_a_gate_states_what_a_person_is_agreeing_to` |
| A gate carries the evidence it was raised on | `test_a_gate_carries_the_evidence_it_was_raised_on` |
| A gate that was never opened permits nothing | `test_a_gate_that_was_never_opened_permits_nothing` |
| A gate cannot be decided twice | `test_a_gate_cannot_be_decided_twice` |
| A rejected or changed gate does not permit the action | `test_a_rejected_or_changed_gate_does_not_permit_the_action` |
| A role below the gate cannot decide it | `test_a_role_below_the_gate_cannot_decide_it` |
| The queue shows a role only what it can decide | `test_the_queue_shows_a_role_only_what_it_can_actually_decide` |
| An action waits in the queue until somebody decides | `test_an_action_waits_in_the_queue_until_somebody_decides` |
| Approving records who decided and when | `test_approving_records_who_decided_and_when` |
| An invalid decision is refused | `test_an_invalid_decision_is_refused` |
| The approver view says what the agent wanted and why | `test_the_approver_view_says_what_the_agent_wanted_and_why` |
| The reason is structured, not prose | `test_the_reason_is_structured_not_prose` |
| An unknown action produces the most cautious gate | `test_an_unknown_action_produces_the_most_cautious_gate` |

## 7. Budgets, clocks and cancellation

| Claim | Test |
|---|---|
| Every agent has a budget | `test_every_agent_has_a_budget` |
| A zero budget means zero, not unlimited | `test_a_zero_budget_means_zero_not_unlimited` |
| A plan larger than its budget is refused BEFORE it runs | `test_a_plan_larger_than_its_task_budget_is_refused_before_it_runs` |
| A run stops at a mid-run meter and says what remains | `test_a_run_stops_at_a_mid_run_meter_and_says_what_remains` |
| A rejected plan never executes anything | `test_a_rejected_plan_never_executes_anything` |
| The clock stops a run that never finishes | `test_the_clock_stops_a_run_that_never_finishes` |
| A run stops when asked | `test_a_run_stops_when_asked` |
| A run can always fail or be cancelled | `test_a_run_can_always_fail_or_be_cancelled` |
| A queued job is cancelled outright | `test_a_queued_job_is_cancelled_outright` |
| A running job is flagged rather than killed | `test_a_running_job_is_flagged_rather_than_killed` |
| A cancelled job is not reclaimed | `test_a_cancelled_job_is_not_reclaimed` |
| The run records what it cost | `test_the_run_records_what_it_cost` |

## 8. The durable queue and the worker

| Claim | Test |
|---|---|
| A claim returns the job and takes the lease | `test_a_claim_returns_the_job_and_takes_the_lease` |
| Two workers never claim the same job | `test_two_workers_never_claim_the_same_job` |
| Two workers take two different jobs | `test_two_workers_take_two_different_jobs` |
| A job whose worker died returns to the queue | `test_a_job_whose_worker_died_returns_to_the_queue` |
| A job left by a dead worker is recovered | `test_a_job_left_by_a_dead_worker_is_recovered` |
| A worker that lost its lease is told | `test_a_worker_that_lost_its_lease_is_told` |
| A heartbeat extends the lease | `test_a_heartbeat_extends_the_lease` |
| Health reads the heartbeat, not the process | `test_worker_health_reads_the_heartbeat_not_the_process` |
| A draining worker stops asking for work | `test_a_draining_worker_stops_asking_for_work` |
| An idle worker reports idle rather than spinning silently | `test_an_idle_worker_reports_idle_rather_than_spinning_silently` |
| A scheduled job is not claimed before its time | `test_a_scheduled_job_is_not_claimed_before_its_time` |
| Higher priority runs first | `test_higher_priority_runs_first` |
| A finished job does not block the next one | `test_a_finished_job_does_not_block_the_next_one` |
| Worker ids are distinct; a worker registers and beats | `test_worker_ids_are_distinct`, `test_a_worker_registers_and_beats` |
| A worker claims runs and completes one job | `test_a_worker_claims_runs_and_completes_one_job` |

## 9. Retry, failure and idempotency

| Claim | Test |
|---|---|
| A failure is retried with backoff, and backoff grows | `test_a_failure_is_retried_with_backoff`, `test_backoff_grows` |
| Exhausted attempts dead-letter rather than loop | `test_exhausted_attempts_dead_letter_rather_than_loop` |
| A failure marked not-retryable dead-letters at once | `test_a_failure_marked_not_retryable_dead_letters_at_once` |
| A job with no handler is not retried forever | `test_a_job_with_no_handler_is_not_retried_forever` |
| A job that kills every worker eventually dead-letters | `test_a_job_that_kills_every_worker_eventually_dead_letters` |
| A failing job is recorded with a CATEGORY, not a message | `test_a_failing_job_is_recorded_with_a_category_not_a_message` |
| A failing handler is recorded, not swallowed | `test_a_failing_handler_is_recorded_not_swallowed` |
| A failing specialist is contained and reported | `test_a_failing_specialist_is_contained_and_reported` |
| A refusal is recorded rather than raised | `test_a_refusal_is_recorded_rather_than_raised` |
| The same job enqueued twice is one job | `test_the_same_job_enqueued_twice_is_one_job` |
| Live uniqueness is enforced by the DATABASE | `test_the_live_uniqueness_is_enforced_by_the_database` |
| The database refuses a duplicate even without the lookup | `test_the_database_refuses_a_duplicate_even_without_the_lookup` |
| The same event delivered twice is one event | `test_the_same_event_delivered_twice_is_one_event` |
| The same review run twice leaves one set of cases | `test_the_same_review_run_twice_leaves_one_set_of_cases` |
| A replayed review refreshes rather than duplicates | `test_a_replayed_review_refreshes_the_case_rather_than_duplicating_it` |

## 10. Challenge and conflict

An agentic answer that nothing disagreed with is not an answer that survived
challenge; it is an answer nobody challenged.

| Claim | Test |
|---|---|
| An ungrounded finding becomes a RECORDED conflict | `test_an_ungrounded_finding_becomes_a_recorded_conflict` |
| A conflict is settled by evidence, not by seniority | `test_a_conflict_is_settled_by_evidence_not_by_seniority` |
| A specialist returning no evidence has not met its contract | `test_a_specialist_that_returns_no_evidence_has_not_met_its_contract` |
| The ceiling lowers a claim the evidence does not support | `test_the_ceiling_lowers_a_claim_the_evidence_does_not_support` |
| The ceiling never RAISES a claim | `test_the_ceiling_never_raises_a_claim` |
| An unrecognised claim is lowered, not waved through | `test_an_unrecognised_claim_is_lowered_rather_than_waved_through` |
| An honest claim is untouched | `test_an_honest_claim_is_untouched` |
| The synthesis quotes findings rather than paraphrasing | `test_the_synthesis_quotes_findings_rather_than_paraphrasing_them` |
| No findings produces no answer | `test_no_findings_produces_no_answer` |
| A coordinated run produces one finding per specialist | `test_a_coordinated_run_produces_one_finding_per_specialist` |

## 11. Trace consistency

| Claim | Test |
|---|---|
| The parts describe what actually ran | `test_the_parts_describe_what_actually_ran` |
| The parts never claim a check that did not run | `test_the_parts_never_claim_a_check_that_did_not_run` |
| A declared no-analysis is not the same as nothing happening | `test_a_declared_no_analysis_is_not_the_same_as_nothing_happening` |
| The completion summary counts what actually ran | `test_the_completion_summary_counts_what_actually_ran` |
| The status line is the one §4 specifies | `test_the_status_line_is_the_one_section_four_specifies` |
| Everything §5 asks to persist is present | `test_everything_section_five_asks_to_persist_is_present` |
| Depth reports every status | `test_depth_reports_every_status` |
| A run stopped part-way is still visible | `test_a_review_stopped_part_way_is_still_visible` |

## 12. Assurance

| Claim | Test |
|---|---|
| Assurance is the WEAKEST link | `test_assurance_is_the_weakest_link` |
| A check that did not run is not a check that passed | `test_a_check_that_did_not_run_is_not_a_check_that_passed` |
| A run with no checks cannot claim validation | `test_a_run_with_no_checks_cannot_claim_validation` |
| A failing check FAILS validation rather than reducing the count | `test_a_failing_check_fails_validation_rather_than_reducing_the_count` |
| A run that computed nothing is not analysed | `test_a_run_that_computed_nothing_is_not_analysed` |
| A clean coordinated run is at least validated | `test_a_clean_coordinated_run_is_at_least_validated` |
| Assurance names the limitations a run recorded | `test_assurance_names_the_limitations_a_run_recorded` |

## 13. Proactive review and pre-screening

| Claim | Test |
|---|---|
| The pre-screen reads the whole book and calls NO model | `test_the_pre_screen_reads_the_whole_book_and_calls_no_model` |
| A review never calls a model for a borrower it did not escalate | `test_a_review_never_calls_a_model_for_a_borrower_it_did_not_escalate` |
| The screen narrows the book to something a person could read | `test_the_screen_narrows_the_book_to_something_a_person_could_read` |
| The screen is fast enough to run before anything else | `test_the_screen_is_fast_enough_to_run_before_anything_else` |
| A review of an unpublished period refuses rather than inventing | `test_a_review_of_an_unpublished_period_refuses_rather_than_inventing` |
| A screen of an unpublished period says so | `test_a_screen_of_an_unpublished_period_says_so_rather_than_finding_nothing` |
| An empty book says so rather than inventing a number | `test_an_empty_book_says_so_rather_than_inventing_a_number` |
| An event for unpublished data is not ready | `test_an_event_for_data_that_is_not_published_is_not_ready` |
| An ignored event says why | `test_an_ignored_event_says_why` |
| A review produces cases a person can act on | `test_a_review_produces_cases_a_person_can_act_on` |

## 14. Requires Attention — the Risk Case lifecycle

| Claim | Test |
|---|---|
| Severity is the FORMULA, not an adjective | `test_severity_is_the_formula_not_an_adjective` |
| Thin evidence LOWERS severity rather than raising it | `test_thin_evidence_lowers_severity_rather_than_raising_it` |
| A bigger move scores higher | `test_a_bigger_move_scores_higher` |
| The thresholds are published rather than buried | `test_the_thresholds_are_published_rather_than_buried` |
| Due dates follow severity | `test_due_dates_follow_severity` |
| Every escalated thing carries the measurement behind it | `test_every_escalated_thing_carries_the_measurement_behind_it` |
| A case links to the analysis behind it | `test_a_case_links_to_the_analysis_behind_it` |
| A case view carries its evidence and its history | `test_a_case_view_carries_its_evidence_and_its_history` |
| Next actions depend on where the case is | `test_next_actions_depend_on_where_the_case_is` |
| Closed cases leave the attention list | `test_closed_cases_leave_the_attention_list` |
| The summary sentence counts only OPEN cases | `test_the_summary_sentence_counts_only_open_cases` |
| The filters are the levels | `test_the_filters_are_the_levels` |
| A snooze ends | `test_a_snooze_ends` |
| The same finding in a new period is a NEW case | `test_the_same_finding_in_a_new_period_is_a_new_case` |
| A refresh never overwrites what a person did | `test_a_refresh_never_overwrites_what_a_person_did` |
| An agent may move a case through the working statuses | `test_an_agent_may_move_a_case_through_the_working_statuses` |
| An agent cannot RESOLVE a case | `test_an_agent_cannot_resolve_a_case` |
| An agent cannot DISMISS a case either | `test_an_agent_cannot_dismiss_a_case_either` |
| A dismissal without a reason is refused | `test_a_dismissal_without_a_reason_is_refused` |
| Resolving records who and what happened | `test_resolving_records_who_and_what_happened` |
| An investigation started from a case is recorded on it | `test_an_investigation_started_from_a_case_is_recorded_on_it` |

## 15. Memory and isolation

| Claim | Test |
|---|---|
| Agentic memory does not travel between investigations | `test_agentic_memory_does_not_travel_between_investigations` |
| Agentic memory does not travel between tenants | `test_agentic_memory_does_not_travel_between_tenants` |
| Memory is bounded | `test_memory_is_bounded` |
| Memory versions on each save | `test_memory_versions_on_each_save` |

---

## What this document does NOT establish

* **Model quality.** Every test above ran against fake providers. Whether a
  real model selects the right officer on a real question is measured by the
  live workflow, which has not been run here and consumes credits.
* **Container behaviour.** No Docker daemon is available in this sandbox, so
  the worker's behaviour under the containerised deployment is
  **NOT VERIFIED IN CLAUDE SANDBOX**.
* **Sustained load.** The queue tests prove leases, recovery and uniqueness
  under contention between two workers. They are not a load test.

Each of those is named because a verification document that only lists what
passed is a document whose silences a reader has to guess at.

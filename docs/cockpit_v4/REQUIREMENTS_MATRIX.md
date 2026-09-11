# Requirements matrix

Master specification section → what implements it → what proves it.

`ACCEPTANCE_CASES.json` carries the per-case detail; this is the section-level
view. **Nothing in this table is marked satisfied by a document.**

| § | Requirement | Implementation | Evidence |
|---|---|---|---|
| 1 | Protect existing instances and branches | separate worktree, branch, namespace, release, state DB, ports; `config.check_write_target`; `seed_release.py` namespace guard | `test_launcher_safety.py`; `git diff` vs base is empty for V3 paths |
| 2 | Phase-zero incident diagnosis | — | `BASELINE_DIAGNOSIS.md`, `test_incident_err_2569c1be3faa.py` (8 tests). **Root cause UNCONFIRMED and stated as such.** |
| 3 | Reuse matrix | — | `SOURCE_MAPPING.md` |
| 4 | Component responsibility boundary | the module split in `ARCHITECTURE.md`; no repair path exists in `orchestration.py` or `execute_tool.py` | `test_an_invalid_field_reference_gets_a_diagnostic_not_a_substitution`, `test_a_failed_query_is_repaired_by_the_model_not_the_application` |
| 5 | Corporate domain preserved | V3's `catalog`, `fields`, `calendar`, `store` reused unchanged | `test_domain_and_numerics.py` (13 tests); 20 quarters, 11 relations, 19-grade scale intact |
| 6 | One analyst; mode and ownership without an extra call | `Intent` declared with the first action; `Intent.may_execute` | `test_non_execution_modes_settle_without_touching_data`, `test_each_turn_recomputes_its_own_owner`, `test_execution_requires_a_declared_cockpit_data_analysis` |
| 7 | Small, factual starting context | `context.build` — index only, no field dictionary | `test_help_does_not_receive_the_whole_catalogue`, `test_original_wording_reaches_the_model_unmodified` |
| 8 | The tool set and a native loop | `contracts.provider_tools`, `provider.Analyst`; five tools since round 4 — `inspect_product_knowledge` joined the original four | `test_protocol_and_bounds.py` (7 protocol tests); `test_tool_contract_agreement.py` (26) diffs every published schema against its parser |
| 9 | Concise plan, never mutilated | `parse_steps` rejects an overlong batch whole | `test_an_overlong_batch_is_rejected_whole_and_never_clipped` |
| 10 | Context and token policy | `Analyst.fits`, `count_input`, verified `Capability` | `test_a_large_but_affordable_request_is_not_refused_by_an_old_cap`, `test_a_request_beyond_capacity_stops_with_input_context_limit` |
| 11 | Bounded work and exact counting | `budgets.Ledger` | `test_a_sixth_execution_submission_is_impossible`, `test_a_fourth_successful_round_is_impossible`, `test_every_provider_attempt_including_counting_is_ledgered`, `test_the_run_deadline_stops_the_loop` |
| 12 | SQL/Python validation and isolation | V3's `sql.open_session` reused; `pyrunner` jail or UNAVAILABLE | 6 escape attempts refused; `test_python_is_unavailable_rather_than_silently_run_as_sql` |
| 13 | Failure packet and recovery | `Rejection.to_tool_result`, `StepResult`, `BatchResult` | `test_a_failed_query_is_repaired_by_the_model_not_the_application`, `test_a_failed_step_stops_its_dependents_and_preserves_the_rest` |
| 14 | Structured answer and evidence | `finalization.Finalizer` | `test_a_claim_that_does_not_match_the_artifact_is_refused`, `test_a_claim_pointing_at_a_null_cell_is_refused`, `test_an_invalid_chart_is_dropped_without_another_analysis`, `test_suggestions_are_checked_against_the_catalog_not_executed` |
| 15 | Durable run protocol and endpoints | `routes.py` under `/api/v1/cockpit-v4` | `test_api_and_lifecycle.py` (12 tests) |
| 16 | Live hideable process viewer | `process-panel.tsx`, `reducer.ts`, and the per-name SSE listeners in `client.ts` | reducer tests; `live-trace.test.ts` (15) replays the 15 recorded events of a real 29.4s run; browser tests 11 and 14; real-socket stage evidence in `live_path.json` |
| 17 | Event and error schema | `events.py`, `states.py` | `test_state_machine_and_memory.py`; the persisted sequence in `live_path.json` |
| 18 | SSE, reconnect, browser settlement | `routes.stream_events`, `client.watch` | `test_sse_replays_committed_events_from_a_cursor`; real-socket replay from cursor 2 |
| 19 | Persistence, worker, watchdog | `run_store.py`, `worker.py`, `supervisor.py` | `test_a_dead_worker_is_settled_by_the_supervisor`, `test_a_late_worker_cannot_overwrite_a_settled_run`, `test_no_run_is_claimed_when_the_store_cannot_commit` |
| 20 | Explicit state machine | `states.TRANSITIONS` | `test_every_cycle_consumes_something_finite`, `test_every_v3_terminal_maps_explicitly` |
| 21 | Memory without delaying the answer | `memory.py`, off by default, post-publish | `test_memory_is_off_by_default_and_schedules_nothing`, `test_a_failed_memory_job_changes_nothing_the_user_saw`, `test_a_scalar_is_never_expanded_into_characters` |
| 22 | Security, privacy, credentials | `service.credential`, `orchestration._redact`, tenant checks | `test_only_the_cockpit_credential_is_read`, `test_no_secret_reaches_a_persisted_detail`, `test_permission_revocation_is_enforced_at_the_artifact` |
| 23 | Mac launcher | `start.py`, `status.py`, `stop.py`, three `.command` wrappers | `test_launcher_safety.py` (8 tests) |
| 23.1 | Configuration contract | `config.py`, `.env.example`, `config/cockpit_v4/price_card.json` | `test_the_demo_principal_cannot_name_its_own_tenant`; `validate()` names what is missing without printing it |
| 24 | Runtime module structure | as specified, adapted after audit | `ARCHITECTURE.md` |
| 25 | Implementation phases | Phases 0–4 complete; Phase 5 blocked on a credential | `UAT_RESULTS.md` |
| 26 | Test and evaluation requirements | 292 V4 backend + 459 frontend + 14 real-Chromium tests | `ACCEPTANCE_CASES.json`: 100/100 covered, every `real_provider` = NOT RUN |
| 27 | Missing tests and regression claims | — | `REGRESSION_REPORT.md`: V3 564 passed / 26 skipped / 0 failed, matched and explained |
| 28 | Acceptance gates | — | `UAT_RESULTS.md`: G0–G6 pass (G1 mock-only), G7 blocked |
| 29 | Deliverables and handoff | — | all nine documents present |
| 30 | Compact analyst runtime instruction | `backend/cockpit_v4/prompts/analyst.md` | ~40 lines, versioned; this spec is not pasted into any runtime call |
| 31 | References | — | recorded in `MASTER_BUILD_SPEC.md` §31 |
| PH | Product Help grounded in the deck | `product_knowledge.py`, `product_knowledge.json` (pack `2026-09-11.1`), the always-on synopsis in `context.py`, `inspect_product_knowledge` | `test_product_help_benchmark.py` — 30 questions, 81 assertions; `test_who_are_you_acceptance.py` (7) |
| PH | Slide 14's multi-agent design is historical, not current | recorded as `HISTORICAL_ARCHITECTURE` / `NOT_CURRENT_V4_ARCHITECTURE`, `applies_to_current_runtime: false`, and not retrievable | benchmark assertions that no retrieval path returns it and no answer describes V4 as multi-agent |
| AQ | Answer quality and Markdown rendering | `prompts/analyst.md` rewritten for a CRO audience; `markdown-parse.ts` → `markdown.tsx` renders to React elements, never an HTML string | `markdown.test.ts` (16), including the `safeHref` allow-list; browser tests 12 and 13 |

## Explicitly not satisfied

| Requirement | Status | Why |
|---|---|---|
| §25 Phase 5 — live commissioning | **BLOCKED** | no authorized credential in this environment |
| §28 G7 — comparative live evidence | **BLOCKED** | same |
| §12 Python analysis | **UNAVAILABLE** | the jail's escape self-test found network access unblocked; the runner refuses to certify itself |
| §26 group 8 — Python sandbox escapes | **partially NOT RUN** | escapes cannot be tested against a jail that is not established. SQL escapes are tested and refused. |
| §5 annex vs deployed field names | **no gap ledger needed** | the catalog is V3's, unchanged. Nothing was renamed or rebuilt, so there is no divergence to record. |

The browser group is no longer partial: `python3 scripts/cockpit_v4/browser_evidence.py`
runs 14 tests in real Chromium against the real Next.js UI and the real V4 API,
recording every network request. The analyst behind it is a stub — that is a
limit on what the suite proves about *answers*, not about the delivery path.

## Contradictions found between the sources

One, reported rather than silently reconciled:

The master specification's §16 example panel lists **eight** stages including
`Executing query` and `Reviewing results`, drawn before the run has taken a
path. §16 also says, correctly, that inactive future steps must be "plainly
prospective" and that the real path is dynamic — "Who are you?" skips catalog
and execution entirely.

Drawing an empty `Executing query` row for a question that will never execute
one is a prediction about the future, not a prospective step. So the panel
lays out only the two stages every run reaches (`accepted`, `understanding`)
and appends the others **as they actually occur**, each with its real timing.
The stage labels and their wording are exactly as specified; only the
pre-drawing is narrower. `INITIAL_STAGES` in `reducer.ts` carries the reason.

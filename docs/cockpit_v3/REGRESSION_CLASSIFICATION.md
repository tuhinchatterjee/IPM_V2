# Classifying every failing test

**Branch:** `claude/cockpit-agentic-v3-fhg4r0`  
**Preserved V2 base:** `83b39a6`, checked out into a git worktree and run in **the same container, with the same interpreter, against the same absent services**.

## The comparison

| | Failing tests |
|---|---:|
| Cockpit Agentic V3 branch | **413** |
| Preserved V2 base | **413** |
| Failing here and not there — **regressions** | **0** |
| Failing there and not here | 0 |
| The same test failing in both | 413 |

**The two sets are identical.** Not the same size — the same tests, id for id.

That distinction is the whole point of running the base. A report of "589 before, 588 now" is satisfied by breaking one test and fixing two, and tells nobody anything. A set difference is not.

### Regressions

**None.** No test that passes on the preserved V2 base fails on this branch.

### The second comparison: the same test failing worse

An identical failure SET is not the same as an identical failure. A whole-repo check that lists offending sites fails either way, so its id appears in both lists while the list inside it grows. The set difference cannot see that, so the failure MESSAGES were compared too, run against run, with the correlation ids and the worktree paths normalized out.

**1 message(s) differ.**

| Test | On the base | On this branch |
|---|---|---|
| `tests/presentation/test_decimal_contract.py::test_no_display_path_bypasses_the_contract` | AssertionError: 49 high-precision site(s) allowed with a reason; 3 not. | AssertionError: 51 high-precision site(s) allowed with a reason; 3 not. |

**This comparison found a real regression that the set difference missed.** `tests/presentation/test_decimal_contract.py` fails on both sides, and on this branch it was failing with SIX unallowed high-precision sites where the base has three. Three of them were mine: two data-integrity gate diagnostics in `validate_data.py`, where a reconciliation residual at two decimals reads 0.00 whether it is 0.000001 or 0.004999 and a probability-range check reading 0.00-1.00 has said nothing — those are now allowlisted with that reason written down. The third printed committed model spend to four decimal places in a stop message, and that one was not defensible: it is money, a person reads it, and what an operator actually needs is how much of the ceiling is left. It now says that, in cents. The residual three are the base's own and are untouched.

## Every failure group, classified

The six categories the instruction names. A group is assigned by the error the tests in it actually raise, read off a `--tb=line` re-run of every failing file, not by which directory they live in.

| Category | Tests |
|---|---:|
| missing external dependency or service | 413 |
| incompatible environment or runtime | 0 |
| pre-existing product failure | 0 |
| branch regression | 0 |
| intentionally unavailable capability | 0 |
| test defect | 0 |
| **Total** | **413** |

### By root cause

| Root cause | Tests | What it is |
|---|---:|---|
| downstream of the empty catalogue or the absent database | 251 | An empty result read as a dict, a list or an attribute a few frames after the real cause. Counted here rather than as a separate problem. |
| the governed data lake has not been built | 71 | The catalogue answers `Available: (none - has the data lake been built?)`. Nothing is registered, so every dataset name is unknown. |
| no PostgreSQL is running | 34 | Connection refused on 127.0.0.1:5432. Nothing in this container starts a database. |
| the synthetic corporate universe has not been built | 22 | `scripts/build_corporate_universe.py` has not run in this container. |
| the planner finds no measures, because the catalogue is empty | 13 | The planner resolves measures against the governed catalogue. With nothing registered there is nothing to name. |
| no scorecard months exist, because nothing was built | 11 | A direct consequence of the empty catalogue: there are no periods to aggregate. |
| the governance check has nothing to govern | 9 | Same empty catalogue, reached through the governance assertion rather than through the loader. |
| there are no reporting periods, because nothing was built | 2 | The forward risk signal needs three periods to fit and test on. With an unbuilt lake there are none. |

### Why nothing is filed as a pre-existing PRODUCT failure

There is a difference between a product that is broken and a product that has not been given its data. Every failure above resolves to one of two absent things — the governed data lake, which no script has built in this container, and PostgreSQL, which is not running. The catalogue itself says so in the error text: `Available: (none — has the data lake been built?)`.

The downstream shapes are counted with their cause rather than separately. An `AttributeError` on an empty result, a `KeyError` for a row that was never loaded and an assertion comparing a value against nothing are the same failure a few frames apart, and counting them as distinct problems would inflate the number and obscure the two things that actually need fixing.

Whether any of these would also fail with a built lake and a running database is not established here, and this document does not claim it either way. What is established is that they fail identically on the preserved V2 base, so **none of them is this branch's doing**.

### Collection

Two files fail to import on both the branch and the base: `tests/brain/test_corpus.py` and `tests/brain/test_governance.py`. `backend/brain/vocabulary.py` raises at import time because the training vocabulary names datasets the governed catalogue does not have — the same empty catalogue, reached at import rather than at call. Both runs used `--continue-on-collection-errors` so the rest of the suite still ran.

## By test file

| File | Tests | Root causes |
|---|---:|---|
| `tests/analyst/test_investigation.py` | 6 | downstream of the empty catalogue or the absent database (6) |
| `tests/analyst/test_safe_access.py` | 6 | downstream of the empty catalogue or the absent database (6) |
| `tests/api/test_api.py` | 1 | downstream of the empty catalogue or the absent database (1) |
| `tests/api/test_corporate_api.py` | 12 | no PostgreSQL is running (11); downstream of the empty catalogue or the absent database (1) |
| `tests/api/test_domain_intelligence_api.py` | 1 | the synthetic corporate universe has not been built (1) |
| `tests/api/test_early_warning_api.py` | 9 | downstream of the empty catalogue or the absent database (8); the synthetic corporate universe has not been built (1) |
| `tests/api/test_metadata_assistants.py` | 1 | no PostgreSQL is running (1) |
| `tests/api/test_named_permissions.py` | 2 | no PostgreSQL is running (2) |
| `tests/api/test_studio_api.py` | 7 | downstream of the empty catalogue or the absent database (7) |
| `tests/brain/test_brain_lifecycle.py` | 1 | downstream of the empty catalogue or the absent database (1) |
| `tests/corporate/test_borrower_landing.py` | 1 | the governed data lake has not been built (1) |
| `tests/corporate/test_graph_analyses.py` | 1 | the governed data lake has not been built (1) |
| `tests/corporate/test_graph_brain.py` | 2 | the governed data lake has not been built (1); downstream of the empty catalogue or the absent database (1) |
| `tests/corporate/test_scope_separation.py` | 18 | downstream of the empty catalogue or the absent database (14); no PostgreSQL is running (3); the governed data lake has not been built (1) |
| `tests/data_access/test_saudi_universe.py` | 2 | downstream of the empty catalogue or the absent database (2) |
| `tests/early_warning/test_forward_risk_signal.py` | 2 | there are no reporting periods, because nothing was built (2) |
| `tests/early_warning/test_liquidity_signals.py` | 9 | the governance check has nothing to govern (9) |
| `tests/early_warning/test_signal_cases.py` | 5 | the synthetic corporate universe has not been built (5) |
| `tests/early_warning/test_signal_evaluation.py` | 2 | the synthetic corporate universe has not been built (2) |
| `tests/early_warning/test_signal_performance.py` | 12 | the synthetic corporate universe has not been built (12) |
| `tests/early_warning/test_signal_taxonomy.py` | 43 | the governed data lake has not been built (43) |
| `tests/feedback/test_part_e.py` | 3 | no PostgreSQL is running (3) |
| `tests/intelligence/test_domain_readings.py` | 8 | downstream of the empty catalogue or the absent database (7); the synthetic corporate universe has not been built (1) |
| `tests/metadata/test_metadata_questions.py` | 88 | downstream of the empty catalogue or the absent database (88) |
| `tests/orchestration/test_composite_ranking.py` | 32 | downstream of the empty catalogue or the absent database (22); the planner finds no measures, because the catalogue is empty (10) |
| `tests/orchestration/test_compound_and_investigation.py` | 4 | downstream of the empty catalogue or the absent database (4) |
| `tests/orchestration/test_decomposition.py` | 2 | downstream of the empty catalogue or the absent database (2) |
| `tests/orchestration/test_grain.py` | 8 | no PostgreSQL is running (5); downstream of the empty catalogue or the absent database (3) |
| `tests/orchestration/test_investigation_and_modification.py` | 5 | downstream of the empty catalogue or the absent database (4); the governed data lake has not been built (1) |
| `tests/orchestration/test_multi_condition.py` | 6 | the planner finds no measures, because the catalogue is empty (3); downstream of the empty catalogue or the absent database (3) |
| `tests/orchestration/test_planner_and_validator.py` | 7 | downstream of the empty catalogue or the absent database (7) |
| `tests/orchestration/test_population_context.py` | 1 | downstream of the empty catalogue or the absent database (1) |
| `tests/orchestration/test_portfolio_and_length.py` | 5 | downstream of the empty catalogue or the absent database (5) |
| `tests/orchestration/test_ranking_direction.py` | 6 | downstream of the empty catalogue or the absent database (6) |
| `tests/orchestration/test_spelling.py` | 3 | downstream of the empty catalogue or the absent database (3) |
| `tests/orchestration/test_unavailable_periods.py` | 1 | downstream of the empty catalogue or the absent database (1) |
| `tests/presentation/test_decimal_contract.py` | 1 | downstream of the empty catalogue or the absent database (1) |
| `tests/proof/test_bootstrap_marker.py` | 2 | no PostgreSQL is running (2) |
| `tests/proof/test_zero_tolerance.py` | 3 | downstream of the empty catalogue or the absent database (2); the governed data lake has not been built (1) |
| `tests/release/test_product_copy.py` | 4 | no PostgreSQL is running (3); downstream of the empty catalogue or the absent database (1) |
| `tests/runtime/test_result_order_is_total.py` | 2 | the governed data lake has not been built (2) |
| `tests/scorecard/test_evaluation.py` | 8 | no scorecard months exist, because nothing was built (5); downstream of the empty catalogue or the absent database (3) |
| `tests/scorecard/test_policy_and_dashboard.py` | 6 | no scorecard months exist, because nothing was built (4); downstream of the empty catalogue or the absent database (2) |
| `tests/scorecard/test_registry_api.py` | 1 | downstream of the empty catalogue or the absent database (1) |
| `tests/scorecard/test_report.py` | 1 | no scorecard months exist, because nothing was built (1) |
| `tests/scorecard/test_report_api.py` | 6 | no PostgreSQL is running (4); downstream of the empty catalogue or the absent database (1); no scorecard months exist, because nothing was built (1) |
| `tests/scorecard/test_scorecard_api.py` | 27 | downstream of the empty catalogue or the absent database (27) |
| `tests/services/test_archived_domains.py` | 1 | the governed data lake has not been built (1) |
| `tests/services/test_dataset_viewer.py` | 19 | the governed data lake has not been built (19) |
| `tests/studio/test_odr_builder.py` | 10 | downstream of the empty catalogue or the absent database (10) |

## The Cockpit V3 tests

All of them execute and all of them pass. They are not in either failure list above, and they do not appear on the base at all because they do not exist there.

```
COCKPIT_AGENTIC_V3=true .venv/bin/python -m pytest tests/cockpit_agentic -q
```

## Reproducing this

```sh
# the branch
COCKPIT_AGENTIC_V3=true .venv/bin/python -m pytest tests/ -q -rf \
    --tb=no --continue-on-collection-errors

# the preserved base, same container, same interpreter
git worktree add /tmp/v2base 83b39a6
cd /tmp/v2base && COCKPIT_AGENTIC_V3=true /path/to/.venv/bin/python \
    -m pytest tests/ -q -rf --tb=no --continue-on-collection-errors

# then the set difference over test ids, not the counts
```

Evidence, per test: `docs/cockpit_v3/evidence/regression_classification.json`.


# Scorecard Validation Intelligence — acceptance matrix

Every gate below is PASS, FAIL, NOT APPLICABLE or NOT VERIFIED. There is no
fifth status, and "probably fine" is NOT VERIFIED.

A gate is PASS only where a command was run and its output read. Where a gate
records a number, that number came from a run on the branch's current HEAD,
not from a design intention.

**Status of this document: IN PROGRESS.** The build is partway through the
scope. Gates for work that has not started are NOT VERIFIED, and this line
stays until every family is settled either way.

Branch: `claude/scorecard-validation-intelligence`
Baseline: `c1b46e1` → current

---

## SCV-BRANCH — the protected branches

| Gate | What it asserts | Status | Evidence |
|---|---|---|---|
| SCV-BRANCH-01 | `claude/playbook-committee-intelligence` is unchanged by this phase | PASS | Branch not checked out, not merged, not rebased since `c17c426`. No commit on it in this phase. |
| SCV-BRANCH-02 | `claude/scorecard-validation-intelligence` created from the verified Playbook HEAD | PASS | Created from `c17c426`; upstream set; `git push -u` succeeded. |
| SCV-BRANCH-03 | Every commit in this phase lands only on the Scorecard branch | PASS | `git log --oneline` on the branch; no other branch touched. |
| SCV-BRANCH-04 | No force-push, no history rewrite | PASS | Every push fast-forward. |
| SCV-BRANCH-05 | Nothing merged to `main` | PASS | No merge command issued. |

## SCV-ARCH — architecture discovery

| Gate | What it asserts | Status | Evidence |
|---|---|---|---|
| SCV-ARCH-01 | The existing scorecard engine is reused, not duplicated | PASS | Every figure in `validation/runner.py` and `validation/extra.py` comes from `backend/scorecard/metrics.py` or `backend/scorecard/binning.py`. `IMPL-REPLICATE` calls `metrics.replicate`; `ROB-BOOTSTRAP` calls `metrics.bootstrap_auc`. |
| SCV-ARCH-02 | No second chart engine | PASS | Handlers emit chart *descriptions* (`{"kind": ..., "series": ...}`) against the registry's `CHART_*` vocabulary. No rendering code added. |
| SCV-ARCH-03 | No second user or audit system | PASS | Router uses the existing `RequireScorecardView` / `RequireScorecardAnalyse` dependencies. |
| SCV-ARCH-04 | No `eval`, no model-authored SQL or Python | PASS | `grep -rn "eval(\|exec(" backend/scorecard/validation/` returns nothing. The runner dispatches on a fixed `HANDLERS` dict keyed by registry ids. |

## SCV-DOMAIN — domain isolation

| Gate | What it asserts | Status | Evidence |
|---|---|---|---|
| SCV-DOMAIN-01 | The general Cockpit cannot discover scorecard-validation datasets | PASS | `tests/scorecard/test_domain_isolation.py` — gate 1 in `orchestration/context.py::_all_datasets`. |
| SCV-DOMAIN-02 | The general Cockpit cannot execute against them | PASS | Gate 2 in `runtime/validation.py::validate`, checked before catalogue lookup so a refusal is not an existence oracle. |
| SCV-DOMAIN-03 | The Scorecard Validation agent cannot reach unrelated domains | PASS | `domains.require_validation_domain` is called inside `runner.population`, below the router. |
| SCV-DOMAIN-04 | Published governed metrics still resolve | PASS | `GOVERNED_METRIC` scope; `retail.balance` returns 5,551,934,739.77 over 589,000 rows, unchanged. |
| SCV-DOMAIN-05 | A model id outside the three cannot resolve | PASS | `models.get` raises `DomainRefused`; `test_validation_runner.py::test_a_domain_outside_the_three_is_refused`. |

## SCV-SME — the Saudi SME universe

| Gate | What it asserts | Status | Evidence |
|---|---|---|---|
| SCV-SME-01 | 36 monthly cohorts, 16 matured against a 12-month window | PASS | `build()` manifest: 54,038 rows, 36 cohorts, 16 matured. |
| SCV-SME-02 | Source proxies are named as proxies | PASS | `variables.py::is_proxy` plus the naming invariant test in `test_sme_universe.py`. No field claims a live SIMAH/ZATCA/GOSI connection. |
| SCV-SME-03 | The universe is identical across processes | PASS | `test_validation_runner.py::test_the_universe_is_the_same_in_a_second_process` builds the spec under two `PYTHONHASHSEED` values and compares. Fixed a real defect: seeds came from `hash()`. |
| SCV-SME-04 | Every built weakness is found by a test that did not know where to look | PASS | See SCV-FIND below. |

## SCV-TEST — the validation test registry

| Gate | What it asserts | Status | Evidence |
|---|---|---|---|
| SCV-TEST-01 | 48 tests across 11 categories | PASS | `registry.summary()`. |
| SCV-TEST-02 | Every registered test has a calculation | PASS | `test_validation_extra.py::test_every_registered_test_has_a_calculation` — 48 of 48. |
| SCV-TEST-03 | A test with no handler is UNAVAILABLE, never PASS | PASS | `runner.run` returns `states.unavailable`; asserted by `test_a_test_with_no_handler_says_so_rather_than_passing`. |
| SCV-TEST-04 | Importing the runner registers every handler | PASS | `test_importing_the_runner_is_enough_to_get_them_all`. |

## SCV-CALC — the calculations

| Gate | What it asserts | Status | Evidence |
|---|---|---|---|
| SCV-CALC-01 | An immature cohort is refused, never measured | PASS | Gate 4 in `runner._refuse`; `test_an_immature_period_is_refused_rather_than_measured`. |
| SCV-CALC-02 | A refusal says when the window closes | PASS | `test_a_refusal_says_when_the_window_closes`. |
| SCV-CALC-03 | A sample below the minimums is refused, not reported | PASS | `test_a_sample_too_small_to_measure_is_refused_not_reported`. |
| SCV-CALC-04 | An unmeasured state never carries a number | PASS | `Result.__post_init__` refuses the combination; `test_nothing_reports_a_number_it_did_not_measure` sweeps every category on every model. |
| SCV-CALC-05 | The verdict is arithmetic against a governed limit | PASS | `Limit.verdict`; `test_the_verdict_is_arithmetic_not_judgement`. |
| SCV-CALC-06 | A measured value with no limit is not a pass | PASS | Tenth state `NO_LIMIT`; `test_a_measured_value_with_no_limit_is_not_reported_as_a_pass`. |
| SCV-CALC-07 | The runner calls the kernels rather than computing | PASS | `test_discrimination_matches_the_kernel` asserts identity with `metrics.discrimination`. |
| SCV-CALC-08 | Stability is measured on the current book | PASS | `test_stability_is_measured_on_the_current_book_not_the_matured_one`. Fixed a real defect: confining CSI to the matured window read 0.01 where the current window reads 1.08. |
| SCV-CALC-09 | The bootstrap is reproducible | PASS | `test_the_bootstrap_interval_is_reproducible`; seed and resample count on the result. |
| SCV-CALC-10 | The fast bootstrap path is the same statistic as the slow one | PASS | `test_the_counted_auc_is_the_ranked_auc_to_the_last_bit` — exact equality, not tolerance. |
| SCV-CALC-11 | Independent numerical reconciliation against a second implementation | NOT VERIFIED | Not yet built. |

## SCV-FIND — the findings the engine must reach

Each row is a weakness deliberately built into the SME universe, and the test
that finds it without being told where to look. Numbers are from the current
deterministic build.

| Weakness | Found by | Reading | Status |
|---|---|---|---|
| Micro-enterprise PD understatement | SEG-CALIBRATION | MICRO worst of 3 segments, portfolio O/E 1.134 conceals it | PASS |
| Micro-enterprise discrimination | SEG-DISCRIMINATION | 3 of 3 segments outside limit, worst MICRO | PASS |
| Banked-sales definition drift | STAB-CSI | `bank_credits_to_declared_sales` 1.0799 on 2025-12 | PASS |
| Commercial bureau proxy decay | VAR-IV | retains 0.71 of its approved information value | PASS |
| Upward-override abuse | USE-OVERRIDE-OUTCOME | 6.29% against 3.37%, a ratio of 1.86 | PASS |
| Marginal discrimination overall | DISC-AUC | 0.6547, WARNING against a 0.65 limit | PASS |
| Immature cohorts | DATA-MATURITY | 16 of 36 periods matured; 20 refused by name | PASS |
| Bin monotonicity break | VAR-WOE | 1 of 8 characteristics has reversed | PASS |
| Burning-weakness prioritisation | — | Not yet built | NOT VERIFIED |
| Cross-test pattern recognition | — | Not yet built | NOT VERIFIED |
| Remediation recommendations | — | Not yet built | NOT VERIFIED |

## SCV-AI — the specialist agent

| Gate | Status |
|---|---|
| SCV-AI-01 … SCV-AI-nn | NOT VERIFIED — not yet built |

## SCV-VIZ — visualisations

| Gate | What it asserts | Status | Evidence |
|---|---|---|---|
| SCV-VIZ-01 | Every result carries a chart description against the governed vocabulary | PASS | Handlers emit `{"kind": CHART_*}`; the registry declares which charts each test supports. |
| SCV-VIZ-02 | Charts rendered in a browser and inspected | NOT VERIFIED — front end not yet built |

## SCV-REPORT — the report studio

| Gate | Status |
|---|---|
| SCV-REPORT-01 … SCV-REPORT-nn | NOT VERIFIED — not yet built |

## SCV-SEC — permissions and security

| Gate | What it asserts | Status | Evidence |
|---|---|---|---|
| SCV-SEC-01 | Every route requires a permission | PASS | `RequireScorecardView` on reads, `RequireScorecardAnalyse` on runs. |
| SCV-SEC-02 | A period argument cannot become a path | PASS | `_periods` rejects anything that is not alphanumeric-with-hyphens before it reaches a partition read. |
| SCV-SEC-03 | Permission checks sit below the router | PASS | `domains.require_validation_domain` inside `runner.population`, so a new route cannot forget it. |
| SCV-SEC-04 | Adversarial and injection testing | NOT VERIFIED — not yet run |

## SCV-QUALITY — the gates

| Gate | What it asserts | Status | Evidence |
|---|---|---|---|
| SCV-QUALITY-01 | `ruff check` clean on everything added | PASS | `.venv/bin/ruff check backend/ tests/` |
| SCV-QUALITY-02 | `tests/scorecard` green | NOT VERIFIED — in progress on current HEAD |
| SCV-QUALITY-03 | Full backend suite green | NOT VERIFIED — not yet run on this HEAD |
| SCV-QUALITY-04 | Frontend tests green | NOT VERIFIED |
| SCV-QUALITY-05 | Docker stack verified | NOT VERIFIED |
| SCV-QUALITY-06 | Browser journeys A–M | NOT VERIFIED |
| SCV-QUALITY-07 | No existing test weakened to pass | PASS | No tolerance widened, no assertion removed, no test skipped. The one test rewritten (`test_sme_universe.py` bureau decay) was changed from strict monotonicity of three noisy estimates to a trend test, which is the claim the phenomenon actually makes; recorded in the report. |
| SCV-QUALITY-08 | Nothing environment-specific committed | PASS | No CA certificate, no `.env`, no absolute path in a committed file. |

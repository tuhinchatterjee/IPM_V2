# What-If candidate — final status

Branch `claude/advanced-cockpit-whatif-v1`, from the accepted baseline
`245c50e45786c6e0c866b281f9dd74da17d160b5`.

> **Everything measured here is measured on GENERATED books.** The borrowers and
> customers do not exist, the economy did not happen, and every ECL figure comes
> from `reference_ecl.py`, a calculator written for this demonstration. Nothing
> in this deliverable is bank output, an accounting figure or observed economic
> history, and no model or sensitivity is bank-validated.

Status words: **PASS**, **PARTIAL**, **BLOCKED**, **FAILED**. "COVERED" in the
requirement matrix means a named test proves a mechanism; **PASS** here means the
PRODUCT journey was executed through the real product path.

---

## 1. The requirement the whole authorisation turned on

| Requirement / journey | Status | Evidence | Commit | Known limitation |
|---|---|---|---|---|
| A typed question in the Advanced Cockpit reaches `scenario/run.py` and its result returns through the ordinary response path | **PASS** | J01–J14 on both books through real Chromium, 28/28. `evidence/journeys-{corporate,retail}.json` | `b4f83cc` | The analyst is scripted — MODEL MOCK. See §4. |
| The dispatch is the smallest guarded branch, not a new architecture | **PASS** | `execute_tool.py` +143, all substance in the unprotected `scenario/bridge.py`. `test_whatif_bridge.py`, 70 tests | `b4f83cc` | Two further protected files were needed; each was raised and approved before the edit. See §2. |
| The Python sandbox is not relaxed | **PASS** | `-I -S` unchanged, no `PYTHONPATH`, no `sys.path` addition. `test_the_python_sandbox_is_unchanged`, `test_the_engine_is_still_unimportable_from_a_python_step`, `pyrunner.self_test()` re-run unchanged | `b4f83cc` | — |
| The dispatcher condition cannot silently stop working | **PASS** | Mutation harness: always-true, always-false, flag-ignoring, language-only. A named test fails in each case | `b4f83cc` | — |
| Flags OFF preserve the accepted behaviour | **PASS** | Step language not accepted, accepted refusal sentence, byte-identical provider payload, accepted default release, accepted browser suite unchanged | `b4f83cc` | — |
| No sixth analyst tool, no new route, no new page, no separate Scenario Lab | **PASS** | Five-tuple `TOOL_NAMES` unchanged; the whole journey runs in the Advanced Cockpit thread | `b4f83cc` | The in-chat XLSX route is not added — see §3 R14. |

## 2. The protected-core changes, with the authorisation for each

`scripts/whatif/protected_hashes.py --check` reports **8 changed, 0 removed,
25 added** against `245c50e45786c6e0c866b281f9dd74da17d160b5`. No hash was
regenerated and the allowlist was not broadened — there is no allowlist; the
tool reports every difference.

| File | Purpose of the diff | Authorised as |
|---|---|---|
| `context.py` | `SCENARIO_SEMANTICS` + `scenario_blocks()` (P3's one additive prompt entry); `scenario_packet()` + a defaulted `thread_context=None` on `build()` | P3 §1.2; P5b |
| `schema.py` | `candidate_relations()`, concatenated into `relations()`; `domain_of_relation()` iterates it. `RELATIONS` untouched | P5b |
| `domains.py` | `current_release()`. `DEFAULT_RELEASES` untouched | P5b |
| `domain_resolver.py` | `scope_for` and `availability()` both read `current_release` | P5b, plus a correction of this work's own defect: the route published the accepted release id beside the candidate fingerprint |
| `worker.py` | seeded context routed by `kind`; guarded `whatif_thread.remember()` after `_settle` publishes | P5b |
| `contracts.py` | `_step_languages()` and the `parse_steps` condition; the enum value appended to the provider's in-memory copy only | B1 — raised before editing: `parse_steps:523-529` refused the language before `execute_tool.py` was reached |
| `execute_tool.py` | `CHECK_SCENARIO`, its `PHASE_OF_CHECK` row, two dispatch arms and six thin helpers | B1 — the authorised dispatch |
| `routes.py` | one line: `current_release(pinned)` in place of `DEFAULT_RELEASES.get(pinned)` | B1 — stopped and reported before the edit. Every follow-up turn in a candidate-pinned thread returned 409 `RELEASE_SUPERSEDED`, reproduced over HTTP |

Both protected JSON schema files — `contracts/shared_defs.schema.json` and
`contracts/execute_analysis.schema.json` — are **byte-identical to the
baseline**, verified by `cmp` against `245c50e` and by a named test.

## 3. The requirements that were not accepted last time

| Requirement | Status | Evidence | Commit | Known limitation |
|---|---|---|---|---|
| **P7 Corporate** — a genuine validated blend | **PASS** | XGBoost 0.767 / additive-in-logs 0.233. G1 1.89%, G2 1.13%, G3 2.34%, G4 5.37% — all pass. `ML_ACCEPTANCE_TARGETS_V2.md` committed before the fit and before the test read | `4ea0f9a` | The blend became possible through one declared component change, justified from development evidence alone: an additive-in-levels basis cannot represent a product. |
| **P7 Retail** — a genuine validated blend | **FAILED** | additive-in-logs 0.658 / LightGBM 0.342. G1 4.43%, G2 1.27%, G3 3.50% pass; **G4 34.36% against a predeclared 15% fails** | `4ea0f9a` | Method 2 is **unavailable** on Retail: the answer names the gate, the method's cells stay EMPTY rather than zero, no model stands in. The threshold was not moved, the group not excluded, materiality not redefined, nothing tuned against the untouched split. Delta and User-defined work normally. |
| **P8** — every selected method over one confirmed contract, side by side | **PASS** | `Run.contract()` and `Run.status_line()`; published as the result rows "One contract" and "Method verdicts". J04 and J05 on both books. `test_p8b_*`, 9 tests | `4ea0f9a` | — |
| **P9 A** — scenario-impact attribution reconciling to the total ECL change | **PASS** | Two views, each closing on "Reconciles to" exactly; residual is its own row and is never spread. A scoped rule is its own driver. `attribution.never_add` refuses to sum the views | `4ea0f9a` | — |
| **P9 B** — ML prediction explanation, kept apart | **PASS** | Per-run SHAP and component contribution on the cohort; offline gain importance and partial-dependence curves in `artifacts/whatif/<book>/explanation.json`. `test_whatif_explain.py`, 22 tests | `4ea0f9a` | The response curves describe the fitted function on the development window, not the cohort in view, and say so in the status a reader sees. |
| **R14** — the §14.3 workbook, offline and reconciled | **PASS** | `scripts/whatif/build_workbook.py`: five reconciliations must close before a byte is written; formula injection blocked. 8 named tests | earlier | The **in-chat** XLSX route is not added — a protected-core change this authorisation does not cover. |
| **R12** — compare two frozen ledgers | **PASS** | `ledger.compare()`; refuses rather than caveats when the two are not comparable. 5 named tests | earlier | — |
| **R11** — save and reopen keep every version | **PASS** | J06 on both books: the same approval reproduces the same figures exactly and is published as a RE-RUN naming the first run | `b4f83cc` | — |
| **R13** — exports reconcile to the chat numbers | **PASS** | J09 on both books: the CSV export's digits compared against the displayed figure | `b4f83cc` | Markdown, SVG and ZIP routes are unchanged and were not re-driven against scenario content. |
| **A09** — two builds of one release id are byte-identical | **PASS** | Two builds, same fingerprints: Corporate `3b101bd41465fbe1`, Retail `98b494ae2721bd53`. Both accepted books unchanged afterwards | earlier | — |
| **E20** — timeout, cancellation, repeated Run under a scenario turn | **PASS** | J12 (bound reported, not clipped), J13 (cancelled between actions, nothing partial published), J14 (two approvals, one result) | `b4f83cc` | MODEL MOCK. |

## 4. What was not done, stated as a claim rather than an omission

| Claim | Status | Why |
|---|---|---|
| A journey driven by a **live model** | **BLOCKED — NOT RUN** | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY` and `COCKPIT_LLM_API_KEY` are all unset here — verified, not assumed. Every journey uses a scripted analyst against the real UI, API, store, worker, event stream, DuckDB session and scenario engine, and is labelled MODEL MOCK. Matrix row **V01**. |
| The Mac launcher installed and run on the Mac | **BLOCKED — NOT RUN** | `/Users/tuhinchatterjee/Desktop/CreditProbe_Launchers` is not reachable from this Linux container. The `.command` file exists with its installation steps in its own header; it has not been copied there, made executable there or run. The accepted launchers are untouched. Matrix row **V02**. |
| Three findings in the accepted UI | **reported, not fixed** | A money figure cannot show a small movement (`PERMITTED[MONETARY_AMOUNT] == (0,)`); a run still working reads as "Stopped: ACCEPTED"; a published table the server did not render crashes the thread page through its error boundary. All three are in protected files this authorisation does not cover. `KNOWN_LIMITATIONS.md` §16 has the reproduction for each. |

## 5. Verification, as run

| Check | Result |
|---|---|
| What-If suite | **896 passed** |
| Full V4 + frontend regression, flags OFF | **4301 passed, 4 skipped, 0 failed** (15m 55s) |
| V3 suite (`tests/cockpit_agentic`) | **564 passed, 26 skipped, 0 failed** |
| Accepted browser suite, real Chromium | **76/76** |
| `protected_hashes.py --check` | **8 changed, 0 removed, 25 added**; every line explained in `BASELINE_AND_EXTENSION_MAP.md` |
| Accepted Corporate fingerprint | `e37236d0f6d4e494…` — **unchanged** |
| Accepted Retail fingerprint | `a1e797dcc73236b7…` — **unchanged** |
| Protected JSON schema files | byte-identical to `245c50e` |
| `build_matrix.py` | 138 IDs: 135 COVERED, 1 PARTIAL, 2 BLOCKED; exits non-zero on a fake test name |
| `verify_artifacts.py --domain all` | both books refitted from scratch; **every component hash, blend weight, gate verdict, measured value, seed, library version and period split reproduced**; both explanation documents rebuilt byte for byte |
| `browser_evidence.py --domain all` | **28/28** journeys (MODEL MOCK) |
| `ruff` | clean on every file this work touched |

No model gate was relaxed, no threshold moved, no materiality redefined, no
baseline hash regenerated, and no result was manufactured.

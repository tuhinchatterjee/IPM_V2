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
| A typed question in the Advanced Cockpit reaches `scenario/run.py` and its result returns through the ordinary response path | **PASS** | J01–J15 on both books through real Chromium, 30/30. `evidence/journeys-{corporate,retail}.json` | `b4f83cc`, this round | The analyst is scripted — MODEL MOCK. See §4. |
| The dispatch is the smallest guarded branch, not a new architecture | **PASS** | `execute_tool.py` +143, all substance in the unprotected `scenario/bridge.py`. `test_whatif_bridge.py`, 70 tests | `b4f83cc` | Two further protected files were needed for the bridge, and nine more for the three authorised UI fixes; each was raised and approved before the edit. See §2 and §2b. |
| The Python sandbox is not relaxed | **PASS** | `-I -S` unchanged, no `PYTHONPATH`, no `sys.path` addition. `test_the_python_sandbox_is_unchanged`, `test_the_engine_is_still_unimportable_from_a_python_step`, `pyrunner.self_test()` re-run unchanged | `b4f83cc` | — |
| The dispatcher condition cannot silently stop working | **PASS** | Mutation harness: always-true, always-false, flag-ignoring, language-only. A named test fails in each case | `b4f83cc` | — |
| Flags OFF preserve the accepted behaviour | **PASS** | Step language not accepted, accepted refusal sentence, byte-identical provider payload, accepted default release, accepted browser suite unchanged | `b4f83cc` | — |
| No sixth analyst tool, no new route, no new page, no separate Scenario Lab | **PASS** | Five-tuple `TOOL_NAMES` unchanged; the whole journey runs in the Advanced Cockpit thread | `b4f83cc` | The in-chat XLSX route is not added — see §3 R14. |

## 2. The protected-core changes, with the authorisation for each

`scripts/whatif/protected_hashes.py --check` reports **17 changed, 0 removed,
25 added** against `245c50e45786c6e0c866b281f9dd74da17d160b5`. No hash was
regenerated and the allowlist was not broadened — there is no allowlist; the
tool reports every difference. **Nothing is
UNAUTHORIZED-PENDING-REVIEW:** every one of the seventeen ties to an explicit
prior authorisation, named in the row. Eight are the flag-gated extension and
the bridge; nine are the three UI defects authorised in this round (§2b).

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

Every one of the eight returns the accepted object with both flags off, and
each is asserted by a named test rather than by inspection: `test_a04_*` for
`context.py`, `schema.py`, `domains.py` and `domain_resolver.py`;
`test_remember_does_nothing_when_the_book_has_whatif_off` and
`test_an_attention_card_is_not_a_scenario` for `worker.py`;
`test_the_protected_schema_files_are_not_edited` and the four-way dispatcher
mutation harness for `contracts.py` and `execute_tool.py`.

**The one gap the audit found, and closed.** `routes.py` was the only
protected change with no named test of its own — no What-If test touched
`routes.py` at all, so the flags-on behaviour rested entirely on the browser
journeys. `tests/cockpit_v4/test_whatif_routes.py` closes it with five
in-process ASGI tests over both books, including
`test_the_flag_does_not_excuse_a_superseded_candidate_thread`, which proves
the fix is *not* "stop refusing": a genuinely superseded release is still
refused 409 `RELEASE_SUPERSEDED` with the flag on.

Both protected JSON schema files — `contracts/shared_defs.schema.json` and
`contracts/execute_analysis.schema.json` — are **byte-identical to the
baseline**, verified by `cmp` against `245c50e` and by a named test.

## 2b. The three measured UI defects, authorised and fixed

Nine further protected files changed, all display-layer. No calculation, no
stored value, no analytical state machine and no error taxonomy moved.

| Defect | Files | What changed | Proof |
|---|---|---|---|
| **U01** — a money amount shown as a different amount. A Retail cohort of {1.6929, 2.0315, 0.3386} SAR mn read `SAR 2m → SAR 2m, change SAR 0m` | `display.py`, `finalization.py`, `axis.py`, `export.py`, `precision.py` | Precision is chosen **once per group** — one table column, one chart series or axis, one unit's worth of claims in one answer — from the smallest non-zero magnitude in it. At or above 1 it is 0 decimals, which is today's behaviour; below 1 it is the fewest decimals giving two significant digits, capped at 4. The **scale is not switched** and no precision is manufactured. `PERMITTED[MONETARY_AMOUNT]` stays `(0,)` and `GOVERNED` is untouched: the analyst still cannot choose a money precision — only the server's own default became magnitude-aware | `test_whatif_money_precision.py`, 28 tests. MEASURED after: `SAR 1.69 million becomes SAR 2.03 million, a change of SAR 0.34 million (20.00%)`; ECL by product `1.693 / 0.606 / 0.568 / 0.297 / 0.025`; Corporate still `SAR 171 million becomes SAR 202 million, a change of SAR 31 million` |
| **U02** — an active run read `Stopped: ACCEPTED` for its whole duration | `reducer.ts`, `thread-view.tsx` | `reducer.ts`'s `settled` case latched `terminal: true` unconditionally, never reading `action.status.terminal` — which `routes.py:458` does send and `client.ts:77` does declare. It now latches only on a genuinely terminal state, and `state`, `errorCode` and `response` are applied only on that branch, so a mid-run status refresh cannot rewrite the outcome. The six working states map onto truthful copy; **"Stopped" survives only where execution actually stopped** | 6 added cases in `reducer.test.ts` covering accepted-and-running, all six working states, all nine terminal states, a mid-run gap then a real settle, and an unknown state carried by the server's own flag |
| **U03** — one unrenderable table took down the thread page and the composer | `visuals.tsx` | The existing `components/system/error-boundary.tsx` — whose own docstring describes this use — now wraps **each figure** at the two `.map()` bodies in `Visuals`, which has exactly two call sites, so the stored transcript and the live turn are both covered by one change. No new global UI architecture. **Nothing is hidden:** no defensive guard was added inside `ResultTable`, because blank cells would conceal the defect; the message stays on screen and `componentDidCatch` still logs it | Browser journey **J15** on both books: the scripted analyst publishes the exact payload that used to crash the page, and the journey asserts the figure's own error is visible, the root `error.tsx` did *not* take over, the earlier turn and its answer are still on screen, the composer still accepts input, and a further question still answers. Plus `test_a_table_the_server_cannot_resolve_is_passed_through_unrendered`, pinning the server-side precondition |

**Recommended and deliberately NOT done:** `finalization.py:899-905` should
refuse to publish a table it did not render, rather than passing the analyst's
raw dict through. This round authorised a **frontend** resilience change, so
the server half is recorded in `KNOWN_LIMITATIONS.md` 16.3 with its file:line
rather than made.

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
| **§2 of the hardening brief** — Retail Method 2 stays FAILED *and the reader is told* | **PASS** | The comparison reads `Delta (proportional) COMPLETE; Emulator NOT READY — …G4…0.3436…; Your assumption COMPLETE`. The emulator's `scenario` and `change` are `null`, never `"0"`. `run.VERDICTS` maps the analytical status onto reader-facing copy and the status field itself is unchanged. `test_whatif_retail_not_ready.py`, 13 tests; matrix row **M19** | this round | The gate itself stays FAILED — dimension 7 of §6. |

## 4. What was not done, stated as a claim rather than an omission

The three UI findings that stood here last round are now **fixed** —
see §2b and `KNOWN_LIMITATIONS.md` §16.

| Claim | Status | Why |
|---|---|---|
| A journey driven by a **live model** | **BLOCKED — CREDENTIALS NOT AVAILABLE HERE** | The variable this product reads is `config.CREDENTIAL_VAR = "COCKPIT_ANTHROPIC_API_KEY"` (`config.py:32`), and `service.credential_status()` reports MISSING. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`, `COCKPIT_LLM_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `CLAUDE_API_KEY` are unset too — verified, not assumed. **No key is read or printed anywhere in this evidence**; only PRESENT/MISSING is recorded. Every journey uses a scripted analyst against the real UI, API, store, worker, event stream, DuckDB session and scenario engine, and stays labelled MODEL MOCK — nothing is relabelled. The gate is PREPARED: eight conversations L1–L8 in `whatif.live.mjs`, driven by `live_uat.py`, which refuses with exit 2 rather than falling back to the stub. Matrix row **V01**; `LIVE_PROVIDER_UAT.md` has the acceptance question and the exact Mac commands. |
| The Mac launcher installed and run on the Mac | **BLOCKED — NOT RUN** | `/Users/tuhinchatterjee/Desktop/CreditProbe_Launchers` is not reachable from this Linux container. Two `.command` files exist with their installation steps in their own headers — the earlier candidate launcher and the new `START_ADVANCEDCOCKPIT_WHATIF_UAT.command`, which gates on `uat_preflight.py` and refuses to start on the wrong revision or without its data. Neither has been copied there, made executable there or run. The accepted launchers under `scripts/cockpit_v4/` are untouched and the accepted presentation launcher is not overwritten. Matrix row **V02**. |
| The **in-chat** XLSX route | **not built** | A protected-core change this authorisation does not cover. The offline workbook (`build_workbook.py`, R14) is built and reconciled. |
| `finalization.py` refusing to publish a table it did not render | **recommended, not done** | §5 of the brief authorised a **frontend** resilience change. The server half is recorded with its file:line in `KNOWN_LIMITATIONS.md` 16.3. A malformed table still reaches the browser; it no longer takes the page with it. |

## 5. Verification, as run

Counts are reported exactly as measured. They are higher than last round
because this round added tests, which is the intended direction.

| Check | Result |
|---|---|
| What-If suite (`tests/cockpit_v4/test_whatif_*.py`) | **944 passed, 0 failed** |
| Full V4 + frontend regression, flags OFF | **4349 passed, 4 skipped, 0 failed** (17m 01s) |
| V3 suite (`tests/cockpit_agentic`) | **564 passed, 26 skipped, 0 failed** |
| Frontend suite (`npm test`) | **593 passed, 0 failed** |
| `npx tsc --noEmit` | clean |
| What-If browser journeys J01–J15, both books, real Chromium | **30/30** (MODEL MOCK) |
| Accepted browser suite, real Chromium | **75/76, then 76/76 on one re-run.** Reported as measured. The one failure was `the Ask box is the primary element and spans the workspace`, throwing `Cannot read properties of null (reading 'boundingBox')`. Diagnosed, not assumed: `openCockpit` waits for `cockpit-v4-home`, so that element was present; the null is `[data-testid="segments-requiring-attention"]`, which the accepted test reads with a bare `page.$()` and which renders only after the attention feed's fetch resolves — a race in the test, pre-existing and unrelated to this round. None of the four frontend files this round changed (`reducer.ts`, `reducer.test.ts`, `thread-view.tsx`, `visuals.tsx`) references the landing page, its container or the attention feed, and the failing assertion is on an idle landing page before any run exists, which is off the path of all of them. Evidence restored afterwards: the only differences were timing jitter (`"ms"` values) and **no money string moved** |
| `protected_hashes.py --check` | **17 changed, 0 removed, 25 added**; every line explained in `BASELINE_AND_EXTENSION_MAP.md`; no hash regenerated |
| Accepted Corporate fingerprint | `e37236d0f6d4e494…` — **unchanged** |
| Accepted Retail fingerprint | `a1e797dcc73236b7…` — **unchanged** |
| Candidate Corporate fingerprint | `3b101bd41465fbe1…` |
| Candidate Retail fingerprint | `98b494ae2721bd53…` |
| Protected JSON schema files | byte-identical to `245c50e`, by `cmp` |
| `build_matrix.py` | 143 IDs: 140 COVERED, 1 PARTIAL, 2 BLOCKED; exits non-zero on a fake test name |
| `ruff` | 300 findings before this round's changes and 300 after — byte-identical parity, measured by stashing the work and re-running. Every file this round added or changed is clean on its own |
| `uat_preflight.py` | passes, and prints Retail's FAILED G4 (`0.3436` against `0.1500`) rather than hiding it; credential MISSING |
| `live_uat.py` | refuses with exit 2, as designed, because the credential is MISSING |
| `verify_artifacts.py --domain all` | both books refitted from scratch; **every component hash, blend weight, gate verdict, measured value, seed, library version and period split reproduced**; both explanation documents rebuilt byte for byte |

No model gate was relaxed, no threshold moved, no materiality redefined, no
baseline hash regenerated, and no result was manufactured.

---

## 6. Final release classification

Four words only: **PASS**, **FAILED**, **BLOCKED**, **PARTIAL**. PASS means the
capability was exercised through the real product path and the evidence is
named. It does not mean bank-validated, and it does not mean live-provider.

| # | Dimension | Status | What the word rests on |
|---|---|---|---|
| 1 | **Architecture** | **PASS** | One guarded branch in `execute_tool.py`, all substance in the unprotected `scenario/` package. No sixth analyst tool, no new route, no new page, no separate Scenario Lab. The Python sandbox is unchanged (`-I -S`, no `PYTHONPATH`, no `sys.path` addition) and the engine is still unimportable from a Python step. The dispatcher condition is mutation-tested four ways. Both flags off restores the accepted behaviour object for object, not approximately. |
| 2 | **Corporate — Delta (Method 1)** | **PASS** | Proportional re-pricing over the frozen cohort against the one contract every method shares. Independent oracles in `test_whatif_oracles.py`; J02, J04 through real Chromium. |
| 3 | **Corporate — ML emulator (Method 2)** | **PASS** | XGBoost 0.767 / additive-in-logs 0.233. All four predeclared gates pass: G1 1.89%, G2 1.13%, G3 2.34%, G4 5.37%. `ML_ACCEPTANCE_TARGETS_V2.md` was committed before the fit and before the test split was read. `verify_artifacts.py` refits from scratch and reproduces every component hash, weight, gate verdict, seed, library version and period split. |
| 4 | **Corporate — User-defined (Method 3)** | **PASS** | An assumption is labelled as one, its form (relative / absolute / pp) is resolved before the run rather than during it, and it appears beside the other methods without being composed with them. J05. |
| 5 | **Corporate — Macro / MEV** | **PASS** | Stored sensitivities, read rather than refitted at question time; the relative-vs-percentage-point distinction is resolved explicitly; a shock outside the fitted range carries an extrapolation warning rather than being silently extrapolated. J03, J12. |
| 6 | **Retail — Delta (Method 1)** | **PASS** | Same engine, same contract, the Retail book. J02, J04 on Retail. |
| 7 | **Retail — ML emulator (Method 2)** | **FAILED** | additive-in-logs 0.658 / LightGBM 0.342. G1 4.43%, G2 1.27% and G3 3.50% pass; **G4 worst material-group WAPE measured 34.36% against a predeclared 15% and FAILS.** The threshold was not moved, the group was not excluded or redefined, materiality was not re-cut, no blend weight was invented, nothing was tuned against the untouched split, Corporate's model does not stand in, and there is no silent fall back to Delta. The product shows `Emulator NOT READY — …G4…0.3436…`, the method keeps its row, and its cells are EMPTY (`scenario` and `change` are `null`, never `"0"`). 13 named tests in `test_whatif_retail_not_ready.py` prove the chain from the committed gate verdict to the published row; J06 and J10 prove it on screen. |
| 8 | **Retail — User-defined (Method 3)** | **PASS** | As Corporate, on the Retail book. J05 on Retail. |
| 9 | **Retail — Macro / MEV** | **PASS** | Stored Retail sensitivities with their own support ranges; the behavioural-score mapping is distinct from the application-score mapping and a value outside a card's range is refused rather than extrapolated. J03, J11 on Retail. |
| 10 | **Scenario attribution** | **PASS** | Two views — mechanism and economic — each closing on "Reconciles to" exactly. The residual is its own row and is never spread across drivers; a scoped rule is its own driver; `attribution.never_add` refuses to sum the two views. A chart that drops rows is caught rather than published. |
| 11 | **ML prediction explanation** | **PASS** | Per-run SHAP and component contribution over the cohort, plus offline gain importance and partial-dependence curves in `artifacts/whatif/<book>/explanation.json`, rebuilt byte for byte by `verify_artifacts.py`. Kept structurally apart from scenario attribution: `test_whatif_explain.py`, 22 tests. The response curves describe the fitted function on the development window, not the cohort in view, and the status a reader sees says so. |
| 12 | **Persistence and reopen** | **PASS** | J06 on both books: a saved scenario reopened in a later turn reproduces the same figures exactly and is published as a RE-RUN naming the first run, not as a second opinion. J07: changing the book invalidates the confirmation rather than silently re-scoping it. J14: two approvals, one result. |
| 13 | **Export** | **PASS** | J09 on both books: the CSV's digits compared against the displayed figure, character for character, and the export now carries the same group precision as the chat (U01). The offline §14.3 workbook writes nothing until five reconciliations close, and blocks formula injection. The **in-chat XLSX route is not built** — §4. |
| 14 | **Mock-provider journeys** | **PASS** | **J01–J15 on both books, 30/30**, through real Chromium against the real UI, API, durable store, worker, event stream, DuckDB session over the published candidate release, and the real scenario engine. Labelled MODEL MOCK throughout: the analyst's tool calls are scripted and nothing here is presented as a live-model result. |
| 15 | **Live-provider journeys** | **BLOCKED** | Not run. `service.credential_status()` reports MISSING for `COCKPIT_ANTHROPIC_API_KEY`. The gate is built and refuses to run without a credential rather than falling back to the stub. `LIVE_PROVIDER_UAT.md`, matrix row V01. |
| 16 | **Mac launcher** | **BLOCKED** | Not launched. Both `.command` files exist, the UAT one gated by a preflight that refuses on the wrong revision; the Mac is not reachable from this container. Matrix row V02. |
| 17 | **Accepted-cockpit regression** | **PASS** | Both accepted fingerprints unchanged; both protected JSON schema files byte-identical to `245c50e`; the accepted browser suite 76/76 with no money string moved; the full V4 + frontend regression green with the flags off. |
| 18 | **The three measured UI defects** | **PASS** | U01, U02 and U03 fixed, each with its own matrix row and its own proof — see §2b. One residual is recorded rather than hidden (a money value below 0.00005 alone in its group still renders `0.0000`), and one recommendation is recorded rather than made (`finalization.py:899-905`). |

### What this classification is not

It is not a validation opinion. The books are generated, the economy did not
happen, no sensitivity or emulator is bank-validated, and the reader-facing
figures are demonstration output. Corporate's Method 2 passing its own
predeclared gates is a statement about a synthetic book and a development
split — not about a bank's ECL.


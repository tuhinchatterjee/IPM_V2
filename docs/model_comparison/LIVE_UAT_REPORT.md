# Live UAT report

**Status: P9 BLOCKED in this session.** No real model ran. What follows is a **fixture demonstration**: scripted "analysts" drove the real frozen engine, with its real validators, DuckDB execution, Finalizer and store. It proves the disclosure, evaluation and export machinery. It says nothing about Opus, Qwen or any other model.

## 1. Why live UAT is blocked here

| Needed | This session | Remedy on the Mac |
|---|---|---|
| Opus baseline | No `COCKPIT_ANTHROPIC_API_KEY` for the app; no `opus_spend` approval | Export the key in the shell that starts the lab; run `approve.py grant opus_spend --cap-usd <cap>` |
| Local candidates | No Ollama or vLLM; no GPU; x86 VM, not an M-series Mac | Install a runtime and pull the pinned tags (a user-approved download); run `probe.py --profile …` |
| Remote parallel | No approved endpoint | Configure `LAB_REMOTE_OPENAI_URL` (https) and the key; run `approve.py grant remote_inference --cap-usd N` |

## 2. Fixture demonstration: observed results

Comparison `cmp-3b264639484a` (state PARTIAL), question *"What is Stage 2 exposure by sector for the latest quarter?"*.
- **Comparator:** `fixture-reference`, labelled a FIXTURE and not Opus.
- **Independent reference:** 2026Q2, 14 sectors; the largest is Construction at SAR 1,016,613.64 mn.
- **Timings** are milliseconds on this VM:
  - *service* is end to end, excluding user wait;
  - *model* is the observer's interval union of provider calls;
  - *CP* is CreditProbe validation plus execution, from frozen events at millisecond resolution.
- **Contradicted and Unsupported** are claim counts over assessed claims.
- **The Qwen row** reads "Not reached (no probe)" because Qwen was blocked before running: the capability probe has not run on this host (see §1).

| Fixture | Exec | S1 | S2 | S3 | S4 | First divergence | Repairs | Contradicted | Unsupported | Service / model / CP | Match S1/S2/S3/S4 | Diagnosis |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Reference analyst | Completed | Pass | Pass | Not observed | Pass | — | 0/0 | 0/1 | 0/1 | 440 / 1 / 4 | (comparator) | — |
| Different valid plan | Completed | Pass | Pass | Not observed | Pass | — | 0/0 | 0/1 | 0/1 | 208 / 1 / 2 | 100/100/N/A/100 | — |
| Whole-book scope error | Completed | **Fail** | **Fail** | Not observed | Partial (inherited) | matches all stages (whole book) | 0/0 | **1/1** | 0/1 | 203 / 1 / 3 | 33/0/N/A/67 | S1_SCOPE (S1+S2 unresolved) |
| Repairs a refused query | Completed | Pass | Pass | **Pass (1/1, business-correct 1)** | Pass | — | 1/1 | 0/1 | 0/1 | 223 / 2 / 11 | 100/100/100/100 | — |
| Invented cause | Completed | Pass | Pass | Not observed | **Fail** | unsupported causal claim | 0/0 | 0/2 | **1/2** | 176 / 1 / 1 | 100/100/N/A/67 | S4_INTERPRETATION |
| Asks for clarification (answered "EAD") | Completed after clarification | Shared span | Pass | Not observed | Pass | — | 0/0 | 0/1 | 0/1 | 211 / 1 / 0 | 100/100/N/A/100 | — |
| Protocol failure | Failed (ACTION_FORMAT_EXHAUSTED) | Fail | Not reached | Not observed | Not reached | no usable tool call | 0/0 | N/A | N/A | 151 / 1 / 0 | N/A | RUNTIME_CAPABILITY |
| Opus baseline | Blocked | Not reached (no key/approval) | … | … | … | — | — | N/A | N/A | unknown | N/A | not a model failure |
| Qwen3.5-9B | Blocked | Not reached (no probe) | … | … | … | — | — | N/A | N/A | unknown | N/A | not a model failure |

## 3. What this demonstrates

These points are about the lab, not about any model:
1. **The same frozen path serves every child.** The one child that submitted broken SQL was refused by the frozen validator (`SQL_VALIDATION`, a Binder Error), repaired its own query, and was revalidated.
2. **Agreement is not correctness.** "Whole-book scope error" agrees with the comparator on the largest sector (Construction), yet it fails the independent population assertion. Its narrative is marked as inheriting the error rather than as a separate hallucination.
3. **Correct numbers do not excuse an invented cause.** The causal sentence is caught in S4 while S2 stays Pass.
4. **Protocol failure is not reasoning failure.** The no-tool fixture is classified `RUNTIME_CAPABILITY`, and S4 is marked NOT_REACHED rather than failed.
5. **Blocked candidates are visible, and there is no Opus delta.** Unavailable models remain in every view and export with their reasons, and no "versus Opus" figure is produced.
6. The pack downloaded with checksums, and re-export and re-evaluation made no model call (`test_J11_…`, `test_U13_…`).

## 4. Frozen regression in the lab copy

See the tally at the end of this file, which is taken from the frozen suite's own output.

## 5. Next evidence-based action (Mac)

```bash
./launchers/START_MODEL_LAB.command --live-opus          # with COCKPIT_ANTHROPIC_API_KEY exported
.venv/bin/python scripts/model_lab/approve.py grant opus_spend --cap-usd 5
ollama pull qwen3.5:9b && .venv/bin/python scripts/model_lab/probe.py --profile qwen3.5-9b   # after you approve the download
```

Then open `/cockpit/lab`, choose **Mac baseline comparison** and ask the registered oracle question. The first real row of this report will be the result.

Expect the frozen 30 s per-call and 180 s analytical deadlines to be the first constraint for a local 9B model (OG-01). The lab will report that as `RESOURCE_OR_CONTEXT`, not as a reasoning failure.

## Frozen regression result (final)

`scripts/model_lab/frozen_regression.py`, run on the lab copy after all lab code was added: **3,315 passed, 33 skipped, 0 failed** (1,329.66 s). This is identical to the P0 baseline. The evidence files the frozen tests rewrote were restored from Git, and a diff was kept under `artifacts/model_comparison/regression/`. The protected manifest check passed afterwards.

## Defects found in live Opus UAT (`cmp-f364d8b6901a`), fixed in the lab evaluator (`lab-eval-2`)

The frozen engine answered correctly. Both faults were in the lab's reading of the frozen record.

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | S1 `FAIL: no usable action was produced`; call rows showed `stop=tool_use`, `tools=(none)` | The frozen adapter returns SDK block objects, and the frozen store persists them as repr strings (OG-12). `evaluate._generations` accepted only dict `tool_use` blocks, so every live call had no tools, and `_stages` took the "no usable action" branch. The observer and the frozen call report both held the correct names. | Tool names now come from frozen authority (the call report's `tool_names`, with ids paired from engine-built `tool_result` blocks). Inputs come from frozen `submissions` and `final_response`. "No usable action" now requires the frozen record to say `no_tool_call` on every attempt, on a run that did not complete. |
| 2 | 10/10 claims `UNSUPPORTED: the cited artifact cell was not found`; S4 FAIL, despite `answer.validated · ok` and `S4-LARGEST` PASS | `evaluate._claims` resolved `row_key` only as `column=value`. The Finalizer, and Opus, use published row ids (`r0`), and derived claims carry no single cell. Every mapping failure was labelled UNSUPPORTED. | Claims are resolved with the frozen `derivation.row_index_for`, and derived claims with `derivation.parse` / `compute`. A mapping failure gives `UNVERIFIABLE` / `EVIDENCE_INCOMPLETE` / `NEEDS_REVIEW`. The frozen validation is shown per claim and never overridden. |

**Reproduced offline, with no paid call** (`tests/model_lab/live_shape.py`). The reproduction is an Anthropic-shaped provider through the real frozen engine: SDK blocks, `r0` row ids and a derived claim.

The before/after below was produced on saved comparison `cmp-654f3cdff4cf`. Revision 1 was written by the pre-fix evaluator from HEAD `e573d20`; revision 2 by `scripts/model_lab/reevaluate.py`. Engine runs were 2 before and 2 after, so no inference took place.

| Child | Before (r1) | After (r2) |
|---|---|---|
| Reference analyst | S1 FAIL, S2 NOT_OBSERVED, S4 PARTIAL; 3 calls with `tools=(none)`; claims UNSUPPORTED 2 | S1 PASS, S2 PASS, S4 PASS; 0 calls without tools; claims SUPPORTED 2 (the `r0` cell equals the oracle; the derived total is recomputed) |
| Invented cause | S1 FAIL, S2 NOT_OBSERVED, S4 FAIL; claims UNSUPPORTED 3 | S1 PASS, S2 PASS, **S4 FAIL** (the causal sentence is still UNSUPPORTED); claims SUPPORTED 2, UNSUPPORTED 1 |

**For the real saved Opus comparison.** Its store is on the Mac. After `git pull`, run the following there. It calls no model and prints the before/after:

```bash
.venv/bin/python scripts/model_lab/reevaluate.py --comparison cmp-f364d8b6901a
```

The script exits non-zero if the engine-run count changes.

**Frozen regression after lab-eval-2** (`frozen_regression.py`, 2026-09-26): 3,315 passed, 33 skipped, 0 failed. This is unchanged from the baseline. The evidence files were restored and the protected manifest check passed.

## Further defect found by re-scoring `cmp-f364d8b6901a` with lab-eval-2 — fixed in lab-eval-3

**Symptom.** `construction_facilities` was marked CONTRADICTED: the asserted value was 1,370 facilities, the located cell was 1,370.00, and the "reference" was 1,016,613.64.

**Root cause.** `evaluate._numeric_claim` applied the oracle whenever the located row's **sector** was in `reference["values"]`, a single, unlabelled Stage 2 **EAD** map. It never checked the claim's column or unit, so a facility count was compared with the Construction EAD in SAR million.

A latent twin had the same blind spot. `_value_column` / `_sector_map` chose the first numeric column for `S1S2-POP`, whatever it measured.

**The facility count is correct.** An independent pandas check, `COUNT(DISTINCT facility_id)` for stage 2 Construction in 2026Q2, gives 1,370.

**Fix** (lab only):
- `oracle.py`: `expected()` returns per-metric references (`stage2_ead`, `stage2_facility_count`), plus new `unit_class`, `match_metric` and `compare`. The oracle is now `lab-oracle-2`.
- `evaluate.py`: `_numeric_claim` compares only with the same-metric reference. `_checks` uses the new `_metric_column` for the population check. The evaluator is now `lab-eval-3`.
- UI: claim cards show the applied reference.
- `reevaluate.py`: prints each claim's status and reference metric.

**Before/after, with no inference.** Saved reproduction `cmp-31c10cee2d52` puts both claims on one Construction row, Anthropic-shaped. Revision 1 was scored by `lab-eval-2` and revision 2 by `lab-eval-3`. Engine runs were 1 before and 1 after.

| Claim | Before (r1) | After (r2) |
|---|---|---|
| `construction` (SAR million) | SUPPORTED | SUPPORTED vs `stage2_ead` 1,016,613.64 |
| `construction_facilities` (facilities) | **CONTRADICTED** vs 1,016,613.64 | **SUPPORTED** vs `stage2_facility_count` 1,370 |
| S4 | PARTIAL | PASS |

A genuinely wrong count is still caught: 1,371 against a facility-count reference of 1,370 is CONTRADICTED (`test_a_wrong_facility_count_is_still_contradicted`).

**Re-score the real comparison on the Mac** (no model call):

```bash
.venv/bin/python scripts/model_lab/reevaluate.py --comparison cmp-f364d8b6901a
```

**Frozen regression after lab-eval-3** (2026-09-26): 3,315 passed, 33 skipped, 0 failed. This is unchanged. The evidence files were restored and the protected manifest check passed.

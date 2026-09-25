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

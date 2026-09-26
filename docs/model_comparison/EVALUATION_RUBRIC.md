# Evaluation rubric

Versions: `lab-eval-3` (evaluator; `lab-eval-1` and `lab-eval-2` superseded) and `lab-oracle-2` (oracle, now metric-aware). Code: `backend/model_lab/evaluate.py` and `oracle.py`.

The evaluator reads only stored evidence: the frozen run store (messages, events, submissions, artifacts, call report, ledger) and the lab's observer spans. It never calls a model. Re-evaluation writes a new revision and marks the previous one `SUPERSEDED`.

## Separate dimensions

These are never merged into a single score.

| Dimension | Values |
|---|---|
| Execution | `QUEUED` … `COMPLETED`, `FAILED`, `BLOCKED`, `WAITING_USER`, `INTERRUPTED` |
| Quality | Check outcomes against an independent reference |
| Evidence | Evidence confidence per stage (HIGH, MEDIUM, LOW) |
| Review | Human decisions: append-only, and each one keeps the prior status |

## Truth sources

| Source | Used for |
|---|---|
| Independent oracle (`oracle.TASKS`) | Pandas over the release's Parquet files; independent of the engine and of every candidate. **Tolerances are declared before evaluation.** Currently only one task is registered: `corp-stage2-ead-by-sector-latest` (abs 0.01 SAR mn, rel 1e-9). |
| Deterministic structure | Frozen Finalizer acceptance (claims bound to artifact cells), the frozen validators, key sets. |
| Human review | Reviewer decisions with reasons (`/reviews`). |
| Model judge | **None.** A model judge would need its own approval, version and calibration. |
| No reference | `NEEDS_REVIEW`. No accuracy percentage is produced. |

## Checks: `corp-stage2-ead-by-sector-latest`

| Check | Stage | Rule |
|---|---|---|
| `S1S2-POP` | S1+S2 | The sector key set and every value match the Stage 2 / latest-quarter reference within tolerance. If the result instead matches the deliberately computed **whole-book** reference, it is labelled as such. |
| `S2-RESULT` | S2 | The result set matches the reference (by semantics, never by SQL text). |
| `S4-LARGEST` | S4 | The largest sector matches. The right name computed over the wrong population is a FAIL. |
| `S1-CLAR` | S1 | A clarification when the task marks it `not_required` gives PARTIAL plus NEEDS_REVIEW. Asking is never scored as a wrong answer. |

## Evidence status (lab-eval-2)

Every call row, claim and stage now carries an `evidence_status`:

| Status | Meaning |
|---|---|
| `COMPLETE` | The tool call was read from dict blocks in the stored history, or the claim's evidence was located. |
| `FROM_FROZEN_RECORD` | Tool names were taken from the frozen call report's `tool_names`, paired with the engine-built `tool_result` ids. This is the live Anthropic route (OG-12). |
| `EVIDENCE_INCOMPLETE` | The frozen record shows a call or claim that the sidecar cannot map. |
| `NO_TOOL_CALL_RECORDED` | The frozen engine itself recorded `parse_status=no_tool_call`. |

The rules that follow from it:
- **S1 "no usable action" FAIL** requires `NO_TOOL_CALL_RECORDED` on every attempt, and a run that did not complete. Lost telemetry is never proof that no call happened.
- **S2** takes its status from the frozen result artifact when call attribution is incomplete.
- **Claims** are resolved with the frozen public helpers `derivation.row_index_for`, which is exactly the Finalizer's row resolver (`r0`, bare index, `column=value`, unique value), and `derivation.parse` / `compute` for derived claims.
- **A mapping failure** gives `UNVERIFIABLE` + `EVIDENCE_INCOMPLETE` + `NEEDS_REVIEW`. **It is never `UNSUPPORTED`.** `UNSUPPORTED` requires evidence that was inspected and does not support the claim, such as a causal sentence. `CONTRADICTED` requires located evidence that disagrees.
- **Each claim carries `frozen_validation`**, the frozen Finalizer's `answer.validated` status and message, kept separate. A failed sidecar lookup never overrides it.
- **S4 fails** only on an `UNSUPPORTED` causal claim. Unmapped claims mark S4 `EVIDENCE_INCOMPLETE` and add a `MEASUREMENT_OR_REVIEW_GAP` card (`model_failure=false`).
- **Numbers in prose** that are not bound to a claim are `UNVERIFIABLE`, because the frozen Finalizer already refuses bare numbers.

## Metric-aware references (lab-eval-3, lab-oracle-2)

`oracle.expected()` returns **one reference per metric**, each with its own unit, unit class and column hints:

| Metric | Definition | Unit / class | Column hints |
|---|---|---|---|
| `stage2_ead` | `SUM(ead_sar_mn)`, stage 2, latest quarter | SAR million / `money` | `ead`, `exposure` |
| `stage2_facility_count` | `COUNT(DISTINCT facility_id)`, stage 2, latest quarter | facilities / `count:facility` | `facilit` |

How references are applied:
- **Matching.** `oracle.match_metric` applies a reference only when **both** of these hold: the claim's unit class equals the metric's (money is never compared with a count, and facilities are never compared with borrowers), and the claim's column name carries one of the metric's hints. Ambiguity or no match means **no oracle applies**.
- **No same-metric reference.** A located cell with no same-metric reference is `SUPPORTED`, explained as "located in the executed result; frozen Finalizer validated; no same-metric independent reference", with `reference_metric = null`.
- **Same-metric reference.** It compares with tolerance for money and exactly for counts. Disagreement is `CONTRADICTED`.
- **Population failure** (`S1S2-POP` failed on the same artifact) still gives `CONTRADICTED`. That is a cohort fact, metric-independent, and not a cross-metric comparison.
- **The population check itself** now selects the artifact column carrying the primary metric by unit and name, using table `column_units` and claim units. It falls back to the first numeric column only when nothing matches, and then says so (`metric_column_confirmed=false`).
- **Each claim shows** `reference_metric`, `reference_value` and `reference_unit`.

## Claim ledger

| Claim type | Extraction and status |
|---|---|
| Numeric | Extracted from the structured claims, with high extraction confidence. SUPPORTED when the cited cell equals the reference. CONTRADICTED when it matches its own cell but the population is wrong, or when the value differs. |
| Causal | Identified by cue words (`caused`, `driven by`, `due to`, …) and marked UNSUPPORTED, unless evidence in the run supports it. |
| Hedged | `NOT_FACTUAL/QUALIFIED`. |
| Prose numbers | UNSUPPORTED when they are not bound to a structured claim. |
| Other prose | `UNVERIFIABLE`, needs review. |

Rates are always shown as numerator/denominator:
- contradicted ÷ assessed;
- unsupported ÷ assessed;
- assessed ÷ extracted;
- required outputs covered ÷ required.

With no assessed claims, the rate is **N/A**, never 0%.

## Repair (S3)

- Opportunities are the tool results that carried an error.
- Attempts, valid repairs (accepted resubmissions) and business-correct recoveries are counted separately.
- With no opportunity the status is `NOT_OBSERVED`: neither 0% nor 100%.

## Attribution and failure cards

Each failure is placed in one of ten categories:
- `ADAPTER_OR_PROTOCOL`, `RUNTIME_CAPABILITY`, `RESOURCE_OR_CONTEXT`;
- `CATALOGUE_OR_REFERENCE`;
- `S1_SCOPE_OR_CLARIFICATION`, `S2_ANALYTICAL_OR_AUTHORING`, `S3_REPAIR_OR_CONTROL`, `S4_INTERPRETATION`;
- `BASELINE_OR_INFRASTRUCTURE`, `MEASUREMENT_OR_REVIEW_GAP`.

Origin confidence is one of `ORIGIN_CONFIRMED`, `ORIGIN_LIKELY`, `MULTI_STAGE_UNRESOLVED` or `NOT_LOCALISABLE`. Every card carries:
- the symptom;
- the failed requirement;
- an artifact link;
- the likely owner;
- inherited effects;
- the next diagnostic;
- the intervention category;
- the approval needed;
- whether the card counts as a model failure.

## Opus Match (the v2.1 addendum)

- Opus Match measures agreement with the comparator. It is **never** correctness, and it is shown beside the verified status.
- Checks and weights, as `opus-match-1`:

  | Stage | Check (weight) |
  |---|---|
  | S1 | Same population (2); same clarification decision (1) |
  | S2 | Same result set within 0.01 (2) |
  | S3 | Both repaired their own errors or had none (1). Only checked when either side had an opportunity. |
  | S4 | Same material conclusion (2); same claim-support profile (1). Only checked when both sides answered. |

- A percentage is shown only when at least one weighted check was assessed. Otherwise the result is N/A, with the reason.
- A comparator that did not complete gives N/A throughout (`OPUS_BASELINE_UNAVAILABLE`).
- A FIXTURE comparator is labelled "Comparator Match", never "Opus".

## Training readiness

`/training-readiness` aggregates across saved comparisons, per profile:
- distinct tasks;
- recurring categories, counted by distinct task;
- the split ledger and contamination.

Gates, as `readiness-gates-1`, are proposed defaults: at least 20 distinct tasks, and at least 5 recurrences before a non-tentative flag. No training is performed, and no uplift is forecast.

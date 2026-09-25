# Evaluation rubric

Versions: `lab-eval-1` (evaluator) and `lab-oracle-1` (oracle). Code: `backend/model_lab/evaluate.py` and `oracle.py`.

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

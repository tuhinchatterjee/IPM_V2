# Feedback and local learning

> **Raw user feedback never changes production behaviour.** Nothing on this
> page describes an automatic path from what a user clicked to what
> CreditProbe does next. Every path ends at a human, and most of them end at
> two.

This describes what happens between a user saying "that answer was wrong" and
CreditProbe answering differently — every stage, who owns it, and what each
stage is forbidden from doing.

## 1. The question the user is asked

One question, on a completed answer:

> **Was this answer accurate and useful?**

Five answers. Two of them are ways of declining, and both are first-class:

| Answer | What it means |
|---|---|
| `YES` | Accurate and useful. |
| `PARTLY` | Partly right, or right and not useful. |
| `NO` | Not accurate, or not useful. |
| `NOT_SURE` | The user cannot tell. Recorded, and it is not a rating. |
| `SKIP` | The user chose not to answer. Recorded, and it is not a rating. |

`PARTLY` and `NO` open the detail panel. `YES`, `NOT_SURE` and `SKIP` do not:
an interface that interrogates a satisfied user teaches them to stop
answering, and the satisfaction series is only worth reading while people
still bother.

`SKIP` is excluded from the rated set. A satisfaction figure that counts
skips as anything at all is a figure about how many people were asked, not
about how many were satisfied.

### Where the prompt does not appear

The prompt is suppressed, in this order of specificity, and the reason is
always recorded rather than the prompt silently not rendering:

1. the answer is still running;
2. this is a loading skeleton, not an answer;
3. an error was shown before any answer existed;
4. the user dismissed the prompt for this answer;
5. the user turned the prompt off for this thread;
6. the user turned feedback prompts off;
7. feedback has already been given on this answer.

Asking somebody to rate the accuracy of an error message is not measurement.

### It is not intrusive

The prompt is one line under a finished answer. It is never a modal, never
blocks the next question, and can be turned off — for one answer, for one
thread, or entirely — from the same control. `feedback_prompt` is a real user
preference with three values: `on`, `reduced`, `off`.

## 2. The twenty-three issue categories

When the answer is `PARTLY` or `NO`, the user picks what went wrong. The
categories are in **pipeline order**, from the earliest stage that could have
caused it to the latest, because that is the order in which a reviewer has to
rule things out:

`wrong_intent`, `wrong_officer`, `wrong_dataset`, `wrong_field`,
`wrong_exposure`, `wrong_period`, `wrong_population`, `wrong_grain`,
`wrong_join`, `wrong_calculation`, `wrong_method`, `wrong_result`,
`wrong_interpretation`, `incomplete`, `unsupported_claim`,
`missed_exception`, `wrong_visual`, `too_much_detail`, `too_little_detail`,
`broken_navigation`, `slow`, `regulatory_source`, `other`.

Three subsets route differently:

* **Regulatory** — `regulatory_source`, `missed_exception` — go to a
  regulatory SME, not to the analytical review queue.
* **Presentation** — `too_much_detail`, `too_little_detail`, `wrong_visual` —
  are a preference, not a claim about correctness, and may be acted on
  immediately *for that user only* (§13 channel A).
* **Product** — `broken_navigation`, `slow` — are engineering defects and
  become no teaching case at all.

## 3. Every question is an observation

Independently of whether anyone rates it, every completed turn is recorded as
a **learning observation**: the question, the reading, the plan fingerprint,
the datasets, the officer level, the assurance verdict, the build SHA.

An observation starts `UNLABELED` and stays that way unless feedback arrives.
What an unlabelled observation may be used for is a closed list:

| May | May not |
|---|---|
| `replay` | `teaching_truth` |
| `drift_analysis` | `release_evidence` |
| `uncertainty_review` | `accuracy_measurement` |
| `duplicate_detection` | |
| `test_generation_candidates` | |

An unlabelled observation is a record that a question was asked. It is not
evidence that the answer was right, and it is never counted as such.

## 4. Feedback becomes a candidate, not a change

A rating is a `FeedbackEvent`. An event is **evidence**. To affect anything it
must become a `CandidateLearningCase`, and a candidate must walk the whole
pipeline:

```
DRAFT -> AUTO_PROPOSED -> NEEDS_REVIEW -> SYSTEM_REFERENCE_VALIDATED
      -> HUMAN_REVIEWED -> HUMAN_APPROVED -> APPLIED_TO_RELEASE
                        \-> REJECTED
                        \-> RETIRED
```

Nine statuses, and exactly one is releasable: `HUMAN_APPROVED`. A candidate at
any other status is retrievable by nothing in production.

Three refusals are built into `propose()`:

* no consent, no candidate;
* an event with no correction is not a candidate, it is a rating;
* a product-category event becomes an engineering ticket, not a teaching case.

The user's own correction and the system's proposed correction are kept in
**separate fields** and never merged. A reviewer must be able to see what the
user actually said, not a version of it the system has already improved.

## 5. What a user may change on their own

A user may change a **preference**. Eight of them:

`result_form`, `theme`, `density`, `answer_length`, `currency_scale`,
`suggestions`, `feedback_prompt`, `chart_palette`.

Ten things look like preferences and are refused by name, with the reason:

| Refused | Because it is |
|---|---|
| `dataset` | which governed source an answer reads |
| `method` | which governed method an answer uses |
| `period` | which reporting period an answer covers |
| `grain` | what one row of an answer is |
| `officer` | which officer level the work is done at |
| `agents` | which specialists are engaged |
| `model` | which model serves a role |
| `threshold` | where a clarification or abstention threshold sits |
| `interpretation` | what an answer says about its own figures |
| `rounding` | how a computed figure is rounded |

The line is not arbitrary. A preference changes what one user sees. Everything
in the second table changes what CreditProbe *concludes*, and a user who could
set those by clicking a menu could talk the product into any answer they
wanted.

## 6. The guard

`backend/learning/guard.py` is a static check that the feedback modules cannot
reach production behaviour. It is run by the test suite, by
`GET /api/v1/learning/guard`, and by `verify-live-ai.ps1 -FeedbackCritical`.

It enforces three things:

1. **Forbidden imports.** Ten modules the feedback path may not import at all,
   the Assurance store among them. This is the strongest of the three checks:
   a module that cannot import the thing cannot write to it however cleverly.
2. **Protected writes.** Thirteen groups of attribute names that describe
   production behaviour, scores or Assurance. A write to one from a feedback
   module is a finding.
3. **Forbidden promises.** String literals that would tell a user their
   feedback changes the product. Docstrings are excluded, so the sentence
   *forbidding* the promise does not trip the check that enforces it.

One legitimate write carries a line-level `# guard: describing — <reason>`
exemption, and the exemption is **surfaced in the report** rather than
disappearing. A guard whose suppressions are invisible is not a guard.

The guard was narrowed three times during construction rather than left noisy.
A check that cries wolf gets switched off, and then the real write goes
through.

## 7. Releases, replay and the gates

Approved candidates are collected into a `LearningRelease`. A release is
`DRAFT` until it is evaluated, and it can only be activated if all five gates
pass:

| Gate | What it stops |
|---|---|
| `no_new_critical_failures` | A release that fixes six things and breaks one that matters. |
| `target_metrics_improved` | A release that changed nothing measurable. |
| `no_safety_regression` | Permission, tenant or approval behaviour getting worse. |
| `no_holdout_leakage` | A candidate trained on its own test. |
| `reviewed_and_approved` | A named approver who is not the only reviewer. |

Metrics are `None` when they were **not measured**, and `None` never counts as
a pass. A gate that treats "we did not check" as "it was fine" is worse than
no gate.

Replay compares production against the candidate across twelve axes, eight of
which are material:

`officer`, `agents`, `plan`, `datasets`, `result`, `assurance`, `reference`,
`abstention` (material); `tools`, `answer`, `latency_ms`, `model_calls`
(informational).

Each axis is `IMPROVED`, `REGRESSED`, `UNCHANGED` or `UNMEASURED`, and
`UNMEASURED` is never read as `UNCHANGED`.

## 8. The API

```
GET  /api/v1/learning/prompt                       what to show, and why not
POST /api/v1/learning/feedback                     record a rating
POST /api/v1/learning/feedback/{id}/revise         change one's mind
GET  /api/v1/learning/preferences
POST /api/v1/learning/preferences
POST /api/v1/learning/preferences/mute-thread
GET  /api/v1/learning/inbox                        the review queue
GET  /api/v1/learning/observations
GET  /api/v1/learning/candidates
POST /api/v1/learning/candidates/from-feedback/{id}
POST /api/v1/learning/candidates/{id}/review
GET  /api/v1/learning/candidates/{id}/history
GET  /api/v1/learning/actions
POST /api/v1/learning/releases
POST /api/v1/learning/releases/{id}/evaluate
POST /api/v1/learning/releases/{id}/activate
POST /api/v1/learning/releases/rollback
GET  /api/v1/learning/releases
POST /api/v1/learning/replays
GET  /api/v1/learning/replays
GET  /api/v1/learning/models
GET  /api/v1/learning/metrics/satisfaction
GET  /api/v1/learning/metrics/learning
GET  /api/v1/learning/guard
```

The screen is **AI Studio → Feedback & Learning**
(`/ai-studio/feedback-learning`), seven tabs plus the guard card.

## 9. What it costs

§48. Measured offline, no provider call, on this container — so the absolute
numbers are about this machine and the RATIO is the part that travels.

| Operation | Median | Worst | On the answer path |
|---|---|---|---|
| the prompt decision | 0.0004 ms | 0.0110 ms | **yes** |
| building an observation | 0.0077 ms | 0.0408 ms | **yes** |
| writing the observation | 1.9558 ms | 2.3758 ms | **yes** |
| recording a rating | 0.0051 ms | 0.0391 ms | no |
| labelling an observation | 0.0003 ms | 0.0017 ms | no |
| proposing a candidate | 0.0080 ms | 0.0282 ms | no |
| applying a preference | 0.0011 ms | 0.0060 ms | no |
| the raw-feedback guard scan | 113.9284 ms | 155.5562 ms | no |

**Total added to an answer: 1.9639 ms**, almost all of it the database
write. An answer that involves a model call is three orders of magnitude
slower than that, so the observation is not perceptible; and it is written
before the answer is handed back deliberately, because an observation written
afterwards is one that goes missing when the process dies.

The guard scan is the slowest thing in the module by a factor of fifty, and it
**never runs on the answer path**. It runs in CI, in
`GET /api/v1/learning/guard`, and in `verify-live-ai.ps1 -FeedbackCritical`.

Reproduce with:

```
python scripts/learning_performance.py --json docs/learning_performance.json
```

If the platform database is unreachable, the write is reported as
`NOT MEASURED` rather than silently dropped from the total.

## 10. What this is not

This process does **not** retrain Anthropic foundation-model weights, and
nothing in it is fine-tuning of a foundation model. See
`docs/LOCAL_AUXILIARY_MODELS.md` for what the local models actually are and
what they are forbidden from learning.

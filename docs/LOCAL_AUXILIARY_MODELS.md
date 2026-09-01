# Local auxiliary models

> **This is not fine-tuning of an Anthropic foundation model.** No weights of
> any Anthropic model are read, written, copied, adapted or influenced by
> anything described here. Nothing in this process sends training data to
> Anthropic, and nothing in it changes how Claude behaves for this deployment
> or any other.

## What these models actually are

Small, local, supervised classifiers trained on this bank's own reviewed data
and run inside this deployment. They do one thing: **pick between options the
deterministic layer already offers.** They never produce a figure, never write
prose a user reads, and never decide what an answer means.

Every one of them shadows an existing deterministic rule, and that rule
remains the fallback. If the model is absent, rejected, rolled back, or simply
never trained, CreditProbe works exactly as it does today.

## The nine tasks that are allowed

| Task | What it decides | The deterministic rule it shadows |
|---|---|---|
| `capability_classification` | Which high-level capability a question needs. | the keyword and ontology router |
| `conversation_action` | New request, modification, reuse or clarification. | the discourse rules |
| `officer_level` | Which officer level the work belongs to. | the weighted score with its floor and ceiling |
| `agent_selection` | Which specialists are needed. | the concept-to-agent registry |
| `period_parsing` | Which reporting period a phrase means. | the period vocabulary |
| `entity_type` | Whether a named thing is a borrower, sector, product or period. | the governed dimension values |
| `retrieval_rerank` | Which retrieved teaching cases are relevant. | the hybrid retrieval score |
| `duplicate_detection` | Whether two questions are the same question. | the normalised-key match |
| `feedback_error_class` | Which part of the pipeline feedback is about. | the category-to-class map |

Note what they have in common: each is a **routing or matching** decision over
a closed set. None of them is a credit judgement.

## The six tasks that are refused, and why

| Refused task | Because |
|---|---|
| `answer_generation` | A local model writing credit answers is a generative credit-risk model trained on client conversations. |
| `interpretation` | What an answer says about its own figures is governed interpretation, not a classification. |
| `risk_rating` | A model that outputs a credit rating is a rating model and belongs in model risk management, not here. |
| `pd_estimation` | The same, for probability of default. |
| `ecl_calculation` | Expected credit loss is a governed deterministic calculation and will not be approximated. |
| `threshold_setting` | Where a threshold sits is a policy decision with an owner. |

These are refused **by name in code**, not by convention. `start()` raises on
any of them, and the refusal states the reason rather than reading as an
arbitrary limit.

## The lifecycle

```
QUEUED -> RUNNING -> TRAINED -> EVALUATED -> APPROVED -> ACTIVE
                              \-> REJECTED
                                              ACTIVE -> ROLLED_BACK
                    RUNNING -> FAILED
```

A run may only be activated when **all** of these hold:

* it beats the deterministic baseline it shadows — not "is comparable to";
* the critical evaluation set is unchanged;
* the split reports no leakage between train, validation and the sealed
  holdout;
* a named approver, who is not the sole reviewer, approved it.

Rollback is a first-class transition, not a redeployment. An active model that
turns out to be worse is switched off by one recorded action, and the
deterministic rule resumes on the next request.

## What a training artifact may contain

`scan()` refuses an artifact that contains anything key-shaped or any client
column. Secrets are never stored in model artifacts — not in weights, not in
metadata, not in the run record. The artifact is sealed by content hash at the
end of training, and the hash is what the approval is recorded against, so an
artifact cannot be swapped after approval.

Training data is this bank's own **reviewed** data: approved candidates,
labelled observations, and the governed teaching library. Unlabelled
observations may be used for duplicate detection and test-candidate
generation, and may never be used as teaching truth, release evidence, or an
accuracy measurement.

## Where they run

Inside this deployment, on this bank's infrastructure. Training data does not
leave the tenant, no artifact is uploaded anywhere, and no external service is
called during training or inference.

## The sentence that matters

Improving CreditProbe locally means: better routing among governed options,
better retrieval of reviewed teaching cases, and better prompt and policy
configuration — all of it reviewed, gated and reversible. It does not mean,
and cannot mean, a foundation model that has learned this bank's data.

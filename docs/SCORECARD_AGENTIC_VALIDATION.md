# Scorecard Agentic Validation

The diagnostic investigations, and the honesty rules they run under.

---

## 1. What an agentic diagnosis is here

Not prose about a number. A governed investigation that **runs deterministic
analyses** and reports what they establish — with the strength of the claim
stated, because "why did discrimination fall" has several honest answers and
only one of them is a cause.

`backend/scorecard/diagnostics.py`.

---

## 2. The two investigations

### Low discrimination

**Question as asked:** "Why has KS fallen?"

**Question as analysed:** the restatement, shown to the reader. The engine
says what it actually tested, because the honest version of the question is
usually narrower than the one asked.

It compares the month against the development sample and against earlier
months, tests each variable's standalone power, tests the population's
stability, and — where an ablation is run — measures each variable's
contribution by removing it and recomputing.

### Accuracy deterioration

**Question as asked:** "The model is under-predicting. What happened?"

Separates a **calibration drift** (the level is wrong, the ranking is fine)
from a **discrimination loss** (the ranking has degraded), because the two
have different remedies and look similar in a headline.

---

## 3. Claim strength

Two values, and the difference between them is a computation that either
happened or did not:

| Strength | Means |
|---|---|
| `ASSOCIATED_WITH` | The two moved together. No ablation was run. |
| `ACCOUNTS_FOR` | A leave-one-out comparison was actually computed, and this is what it showed. |

A diagnosis may never assert a cause from a correlation. This is a critical
case, and the corpus has a family for it.

Every diagnosis also carries `limitations` — what it could not test and why.

---

## 4. What a diagnosis must contain

- `question_as_asked` and `question_as_analysed`, with `why_restated`
- Every candidate explanation that was tested, and its result
- `claim_strength` per finding
- `limitations`
- The evidence: which runs, which months, which population

A diagnosis that names no computed result is prose, and prose is what this
module exists to replace.

---

## 5. Trace and Assurance

A scorecard investigation records the same Trace stages as any other analysis:
the request, the resolved model and month, the maturity determination, the
authoritative data, the computation, the validation, and the answer.

Assurance checks the scorecard-specific things: that the month resolved is
matured where an outcome metric was computed, that the score direction was
read from the registry, that the population is the one the question named,
and that a causal claim has an ablation behind it.

---

## 6. Specialist selection

The `scorecard_validation_specialist` is selected for scorecard questions.
Officer level 3 for a broad diagnostic review; level 2 for a single metric.

The specialist runs governed analyses. It does not have a path that produces
an answer without one.

---

## 7. What the agentic layer may not do

- Assert a cause where no ablation was run.
- Answer a diagnostic question with a restatement of the question.
- Compute an outcome metric on an open month to have something to diagnose.
- Reach a conclusion the governed policy does not derive — the opinion comes
  from `policy.opine()`, not from the specialist.

# Scorecard AI Brain Evaluation

The teaching corpus, the sealed holdout, the layered evaluation, and what the
Brain may carry.

---

## 1. The census

| | |
|---|---|
| Teaching families | 23 |
| Development cases | 500 |
| Sealed holdout cases | 226 |
| Holdout clusters | 88 |
| Holdout cases marked critical | 92 |
| Zero-tolerance engine checks | 24 |
| Evaluation subcomponents | 47 |

Development cases are in `intelligence_factory/teaching/scorecard.py`. The
holdout is in `backend/scorecard/holdout.py` and is not reachable from
retrieval.

---

## 2. Why twenty-three families

Nine of them are about metrics that get merged in conversation and then in
code: stability, PSI and CSI; discrimination and calibration; a variable's
Gini and the model's.

Merging them in the corpus would make it impossible to tell whether a model
had learned the difference, because every case testing one would accept an
answer about the other. The families are separate so the scores are separable.

The families are registered in the Teaching Factory's own registry
(`backend/teaching/families.py`, group `scorecard`), so the existing coverage
guard applies to them — and it fired the moment the families existed without
cases, which is what it is for.

---

## 3. What no case carries

**A figure.** Not one.

An AUC stored as teaching truth is right for one month and wrong for every
month after it. Cases teach *which metric, on which population, under which
maturity rule, with which refusal* — and the arithmetic is the engine's. A
test scans every question and objective for a stored figure.

---

## 4. Distribution

| Family group | Cases |
|---|---|
| Data discovery | 40 |
| Equation and default definition | 30 |
| Variables and WoE binning | 30 |
| Discrimination | 50 |
| Calibration | 50 |
| Stability + PSI + CSI | 50 |
| Variable diagnostics | 50 |
| Implementation replication | 30 |
| Model comparison + rescoring | 30 |
| Segment + cut-off + override | 20 |
| Maturity | 20 |
| Report + regulatory | 30 |
| Agentic diagnosis | 30 |
| Ambiguity | 20 |
| Controlled failure | 20 |

Registers: formal, informal, typos, banking abbreviations, multi-clause
questions, follow-ups that carry context, period and model-version references,
and Application/Behavioral switches. A corpus of careful prose teaches a model
to need careful prose.

**No padding.** A blueprint that cannot reach its target reports the shortfall
rather than repeating a case. Building this found two families at 10 of 20,
because each had only ten distinct combinations; the fix was five more shapes
each.

---

## 5. The sealed holdout

Eighty-eight clusters under the prefix `holdout::scorecard::`, which no
development cluster can produce.

Covers: maturity traps, future-leakage traps, metric semantics, score
direction and inversion, comparison across mismatched populations, candidate
activation pressure, causality and regulatory claims, report reconciliation,
missing data, implementation, multi-turn context, and ambiguity in wordings
the development set does not use.

**Isolation is checked, not asserted.** `isolated()` compares clusters,
questions and fingerprints against the development corpus and **raises**. A
test plants a leak to prove the check can fail — a holdout score computed over
cases the layer was tuned on is not a weaker measurement, it is a wrong one
that fails in the flattering direction.

**No numeric gold.** A reference is a routine name and its arguments,
recomputed at evaluation time. There is no stored answer to leak.

**No production path reaches it.** The Brain package's `FORBIDDEN_PATHS`
refuses any archive carrying a holdout path, and the test exercises the
refusal rather than asserting the constant exists. Teaching retrieval filters
on provenance, and no development case is stamped with a holdout one.

`report()` renders counts, families and cluster names — never a question. A
"holdout summary" that quoted the questions would be the leak wearing a
different name.

---

## 6. Layered evaluation

The platform's own six dimensions (`backend/assurance/dimensions.py`), with 47
scorecard-specific subcomponents registered beneath them.

The mapping carries a decision: **outcome maturity is ANALYTICAL_DESIGN, not
COMPUTATION**. Choosing a month whose window has closed happens before any
arithmetic, and a system that treated it as a computation concern would
discover it too late.

Reported by dimension, by family and by difficulty. **Critical failures are
never averaged into a rate** — they are reported beside the rates with an
explicit flag.

### What the score is a score OF

`basis` is a required field on every payload:

| Basis | Means |
|---|---|
| `STRUCTURAL_READINESS` | Whether the deterministic system can settle the case — the metric exists, the month resolves, the maturity rule fires, the expected refusal is one the engine makes. **No model was asked anything.** |
| `LIVE_MODEL_ACCURACY` | Whether a language model's answers satisfied the cases. Needs a provider. |

**This phase runs no provider.** Asking for a live basis raises rather than
returning the structural figure under a different name — a readiness figure
presented as an accuracy figure is the most flattering mistake available here.

Current: 500 development cases and 226 holdout cases all settle; 24 of 24
critical checks pass.

---

## 7. Reference expectations

`evaluation.expectations()` derives, for one scorecard and month: the intent,
type, model version, period, maturity, population, metric definitions,
variables, equation, relationships, plan, query, result shape, invariants,
chart type, clarification rule and controlled-failure rule.

It carries **no figure**. §A5's rule — do not teach exact numeric answers to
the live planner before execution — is met by there being no number in it to
teach.

---

## 8. Brain portability

Carried: the ontology and its distinctions, metric semantics, maturity rules,
teaching-family obligations, validation policy vocabulary, the CBUAE-aligned
report structure, model shapes, agent and tool policy, visual grammar,
validation methods, the critical-case catalogue, registry governance.

Never carried, each for its own reason:

| Not carried | Why |
|---|---|
| Raw scorecard rows | Nineteen thousand a month is data, not intelligence |
| Client data | Nothing portable may describe a real customer |
| **Fitted coefficients** | The numbers that make a model that model stay with the institution that fitted them |
| Sealed holdout gold | A package carrying it produces a flattering score and nothing downstream could tell |
| Secrets | No environment variable is read on this path |

The coefficient exclusion holds even though ours are synthetic. A rule that
only holds for synthetic data is not a rule. The package carries which
**variables** a model uses and the convention it declares — never the numbers.

`audit()` walks the built payload rather than trusting the builders, because
the builders are what would change, and treats a bare float as a measurement
that should have stayed behind.

**Compatibility** goes through the existing mechanism: `retail-scorecard` is
registered in the receiver's module list, so a package needing it that lands
without it produces `MISSING MODULE` like any other missing module. One place
to keep correct rather than two.

---

## 9. Lift

Brain Center compares local scorecard intelligence against local plus
imported, **both measured on the receiver's own development set**. A lift
measured on the sender's cases measures how well the sender described its own
cases.

**Case-count growth is not lift.** A candidate with 500 cases against a
baseline of 150 at the same settle rate reports `NO MATERIAL CHANGE`. The Lift
Lab's evidence bands do that work: a dimension below its minimum case count
reads as `INSUFFICIENT EVIDENCE` rather than as an improvement.

Six dimension deltas, plus eight scorecard-specific subcomponents named in the
report: outcome maturity, metric definition, score direction, PSI versus CSI,
variable versus model, score replication, candidate governance, regulatory
framing.

---

## 10. No live calls

Nothing in this module calls a provider. The corpus is generated, the holdout
is generated, the evaluation is structural, and the critical suite runs
against the deterministic engine. No API key is read and no credits are
consumed.

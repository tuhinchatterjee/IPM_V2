# Ask CreditProbe

*How a question becomes an answer, and where the model is allowed to touch it.*

See `ASK_ROOT_CAUSE.md` for what this replaced and why.
See `AI_VALIDATION.md` for how the claim that any of it works is substantiated.

---

## 1. The path

```
USER MESSAGE
   │
   ▼
REMEMBER        backend/orchestration/conversation.py
                What this Investigation has already settled — subject,
                measures, dimension, filters, periods, datasets, join path,
                grain, the plan that ran, and the IDENTITIES it returned.
   │
   ▼
READ            backend/orchestration/router.py
                The live model against the governed catalogue AND the
                conversation so far, with the deterministic semantic reader as
                the fallback. Produces a structured Reading — never prose that
                is later parsed.
   │
   ▼
GUARD           backend/orchestration/guardrail.py
                The governed semantic reader checks that reading for a
                cross-family contradiction. On conflict: one repair call. Still
                conflicting: the SAFE reading of the same question, recorded on
                the Trace as a rejection. Never a different analysis.
   │
   ▼
RESOLVE         backend/orchestration/referents.py
                "these" becomes five specific customer ids — the ones the
                previous run RETURNED, written down, not re-derived.
   │
   ▼
ROUTE           backend/orchestration/capability.py
                What KIND of request is this? Only ANALYSIS computes.
                A methodology named outright takes the certified route first —
                backend/orchestration/certified.py — before the composer, never
                after it.
   │
   ├── DATA_* / METHOD_* / *_ACTION ──▶ backend/orchestration/handlers.py
   │                                    answered from governed metadata.
   │                                    No engine call, no SQL, no figure.
   ▼
PLAN            backend/orchestration/analysis_planner.py
                Concepts, entities, dimensions and periods become an
                Analytical IR. Four shapes: aggregate, ranking, cohort,
                movement.
   │
   ▼
VALIDATE        backend/runtime/validation.py
                Against the governed catalogue. Unchanged, and still the
                security boundary.
   │
   ▼
EXECUTE         backend/runtime/executor.py
                Parameterised DuckDB SQL, then allowlisted kernels.
   │
   ▼
INTERPRET       backend/orchestration/interpretation.py
                The model reads the RESULT — capped, structured, with units and
                warnings — and never the data. Prose containing a figure the
                result does not carry is DISCARDED, not annotated.
   │
   ▼
ASSEMBLE        backend/orchestration/assembly.py
                The answer, the Trace, and a check that every figure in the
                prose came from the result.
```

## 1a. There are exactly three outcomes

An answer, a question back, or a stated failure. **There is no fourth.**

The version this replaced had one: when the composer could not read a question,
whichever registered analysis best matched its wording ran instead. That is how
"show me the five largest Real Estate customers" came back as a sector
concentration reading 100% of a book already filtered to Real Estate — certified,
reconciled, and answering a question nobody asked.

Three fallbacks were removed rather than relabelled: the registry rescue, the
legacy planner behind a blanket exception handler, and the comprehension module
that typed every clarification in the retired registry's voice. A confident
answer to the wrong question is worse than no answer, so the code that could
produce one is gone.

Two properties hold at every step:

**Nothing computes before something decided the request is a computation.** A
question about the catalogue never reaches the engine.

**The model plans; it does not calculate.** There is no branch on this path
where model output becomes a number.

## 2. The provider

`backend/llm/`. `AI_PROVIDER` names it, `AI_MODEL` optionally pins the model,
and the key comes from the provider's own environment variable. Nothing else in
the codebase reads a key or builds a client.

Structured output comes from **tool use**: the JSON Schema CreditProbe supplies
becomes a tool's input schema, and a reply that does not call that tool is an
error rather than something to salvage. A plausible object with a misspelled key
silently loses a filter, and the analysis then answers a slightly different
question with complete confidence.

With no key configured the product runs in **LIMITED OFFLINE MODE** and says so
— on the Cockpit, in Settings, and on every Trace. It does not present a
deterministic reader as full natural-language understanding.

## 3. Capabilities

| | answered by | computes |
|---|---|---|
| `DATA_DISCOVERY` | Data Builder catalogue | no |
| `DATA_INSPECTION` | Data Builder catalogue | no |
| `DATA_DICTIONARY` | Data Dictionary | no |
| `DATA_QUALITY` | published periods and coverage | no |
| `DATA_RELATIONSHIP` | the governed relationship graph | no |
| `METHOD_DISCOVERY` / `METHOD_EXPLANATION` / `METHOD_CREATION` | Analysis Studio | no |
| `ANALYSIS` | the Analytical Runtime | **yes** |
| `PROJECT_ACTION` / `INVESTIGATION_ACTION` / `ANALYSIS_ACTION` | pointed at the surface that owns it | no |
| `CLARIFICATION` | asked back | no |

## 4. Governed context, retrieved not dumped

`backend/orchestration/context.py`. The orchestrator plans against the bank's
metadata, never from memory and never from data:

- datasets, with grain, published periods, fields, units and authority;
- the eighteen governed credit concepts and which fields carry each;
- the declared relationships, with cardinality and period rule;
- Analysis Studio methods relevant to the question.

Retrieved per question rather than dumped: twenty-six datasets and the method
library is tens of thousands of tokens on every call, slow, costly and *worse at
the job*, because the relevant five lines are buried. Cached, and invalidated
when the catalogue is republished.

## 5. Credit semantics live in the concepts

`backend/orchestration/semantics.py`. What "worsening" means is a property of
the **measure**, not the phrase:

| | | |
|---|---|---|
| leverage | higher is worse | "worsening" → the number went up |
| DSCR | higher is better | "declining" → the number went down |
| rating | ordinal, 1 strongest | "downgrade" → the grade number went up |
| ECL | higher is worse | "increase" → the number went up |

The direction words are a small closed vocabulary of English. The credit meaning
comes from the concept's own `higher_is_worse` and `is_ordinal`. Add a concept
to the catalogue and every direction word works on it without touching this
module — which is what the old phrase tables could not do.

## 6. The four shapes

| shape | example | plan |
|---|---|---|
| `AGGREGATE` | "total EAD by sector in the latest quarter" | SCAN → FILTER → GROUP → share → SORT |
| `RANKING` | "the five largest Real Estate customers by EAD" | SCAN → FILTER → GROUP → share → SORT → LIMIT |
| `COHORT` | "customers with a rating downgrade and an increase in ECL" | two periods, grain reconciled, as-of joined, derived, filtered |
| `MOVEMENT` | "how has ECL changed over the latest year" | one scan across both periods, grouped by period |

A ranking and a grouped aggregate both report each row's **share of the
population the question asked about** — computed with a window over the filtered
set. The old concentration analysis divided by its own filtered book and
reported Real Estate as 100% of itself.

## 7. When it asks

- A term that maps to two different governed figures where the choice changes
  the answer.
- A borrower the book does not contain — reported as missing, never matched to
  the nearest name.
- A movement question over a **quarterly** measure with no window: "since last
  quarter" and "over the year" are materially different answers.

It does **not** ask for a window when every measure is published annually: there
is one sensible comparison, and it is stated on the answer.

## 8. The Trace

Laid out in bands, in the order an analysis happens and a reviewer checks it:

```
REQUEST          question · how it was read (intent, concepts, entities, period)
GOVERNED DATA    domains, families, datasets with versions and periods
RELATIONSHIPS    each governed join, with keys, cardinality and period rule
DERIVATIONS      every derived column
EXECUTION        the SQL, the kernels, and the MATHEMATICAL QUERY
RESULT           reconciliation, run fingerprint, the result itself
INTERPRETATION   what CreditProbe made of it, and what it was grounded in
```

Every dynamic analysis carries a **MATHEMATICAL QUERY** node. Opening it shows
what the query does in English, the formula behind each derived column, the
analytical plan step by step, and the SQL — syntax highlighted, copyable, with
the bound parameters shown separately.

A metadata answer draws a metadata Trace: question → reading → catalogue →
answer. No SQL node, no mathematical query, because none ran.

## 9. Grounding

`assembly.grounded_values` collects every figure the result contains — including
roundings and magnitudes without their sign — and `ungrounded` reports anything
in the prose that is not among them. A figure that cannot be traced to a
returned value is flagged on the answer and asserted absent by the test suite.

## 10. The registry, as an emergency fallback

The 24 registered analyses still exist and still run. They are reached only when
the composer cannot read a question, they must match it strongly, and the answer
says which route it took. They are never the normal path.

## 11. Evaluation

`tests/evals/ask_creditprobe_cases.json` — 227 natural-language cases carrying
the expected capability, required concepts, expected domains, expected
behaviour, and the analyses that answering with would be wrong.

- **Deterministic suite**, every commit: routing accuracy over the whole corpus,
  plus behavioural invariants (a top-N returns at most N, a filter cannot grow
  the population, a cohort is an intersection, no row uses data from after its
  own period, an unknown borrower is never silently matched).
- **Live suite**, opt-in: `RUN_LIVE_LLM_EVALS=1` runs the same corpus against a
  real model. Separate because CI has no key, and a suite that sometimes passes
  is one people learn to ignore.

## 12. Where to look

| | |
|---|---|
| `backend/llm/` | provider abstraction, Anthropic tool-use integration |
| `backend/orchestration/capability.py` | the capabilities and the schema |
| `backend/orchestration/router.py` | reading a request, with a model or without |
| `backend/orchestration/context.py` | governed context retrieval |
| `backend/orchestration/entities.py` | resolving named things |
| `backend/orchestration/semantics.py` | what "worsening" means |
| `backend/orchestration/analysis_planner.py` | reading → IR |
| `backend/orchestration/handlers.py` | the non-analytical capabilities |
| `backend/orchestration/orchestrator.py` | the front door |
| `backend/orchestration/assembly.py` | answer, Trace, grounding |
| `tests/evals/` | the corpus and the invariants |

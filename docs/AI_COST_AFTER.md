# What changed, and what it cost afterwards

Companion to `docs/AI_COST.md`, which records the measurement that came
first. Same harness, same sixteen questions, same local stand-in provider —
no live call, no credits.

```
.venv/bin/python scripts/measure_ai_cost.py --repeat --out docs/AI_COST_AFTER.json
```

---

## The result

| | Before | After | |
|---|---:|---:|---|
| Model calls, 16 questions | 64 | **24** | −63% |
| Cost units, 16 questions | 3,955.9 | **523.8** | −87% |
| Cost units per question | 247.2 | **32.7** | −87% |

By family:

| Family | Calls/q before | Calls/q after | Input tokens/q before | after | Units/q before | after |
|---|---:|---:|---:|---:|---:|---:|
| Data and metadata | 4.00 | **0.00** | 14,731 | **0** | 247.1 | **0.0** |
| Data query | 4.00 | **0.00** | 14,740 | **0** | 247.3 | **0.0** |
| Orchestration | 4.00 | 4.00 | 14,753 | **5,047** | 247.5 | **35.0** |
| Judgement | 4.00 | 4.00 | 14,737 | **5,032** | 247.2 | **113.5** |

Asked a second time, ten of the sixteen came back from the run-key store
having spent nothing: **523.8 cost units avoided**, priced at what a question
of that class actually cost when it was computed rather than at an average
over everything.

Judgement questions now cost more per question than orchestration ones, and
that is the point of the change rather than a regression: before, everything
was served at one rate, so a catalogue lookup subsidised nothing and a
forensic question was under-served. `docs/AI_COST_BASELINE.json` was
re-measured with the corrected tier weighting before the comparison was
drawn — the first baseline recorded the analyst's deep-tier calls at the
standard weight, which would have made this change look like a regression.

---

## The six changes

### 1. A class A question does not reach a model (§16)

`backend/analyst/classify.py` reads every question into one of §16's three
classes, deterministically, with the sentence that explains the reading.
`backend/analyst/route.py` then acts on it:

* a question the governed catalogue answers is answered from the catalogue,
  with **zero** model calls, and the analyst is not run alongside to produce a
  second opinion on a fact;
* a question the governed runtime computes exactly is handed to the
  deterministic engine and the analyst is skipped;
* only class B and class C reach the investigation loop.

Where the reading is ambiguous the class comes out B, never A. The failure
modes are not symmetric: a judgement question answered deterministically is a
shallow answer to a serious question, and a lookup sent to the analyst is a
few thousand tokens.

### 2. Two roles instead of one (§16, §19, §22)

The investigation loop was one job served by one model. It is two —
choosing and sequencing governed tool calls, and forming a credit judgement
on what came back — so `backend/llm/roles.py` gained `investigator` and
`analyst` roles, configured by `AI_INVESTIGATOR_MODEL` and
`AI_ANALYST_MODEL`. A deployment that sets neither keeps working: the
investigator falls back to the routine planner's model and the analyst to
the complex planner's.

**The model serving a request is not shown in the product.** `Meter.to_dict()`
omits model ids by default; the administrator's cost trace passes
`models=True`, which is a different surface with a different permission.

### 3. The rules and the catalogue became a cacheable prefix (§17)

7,676 tokens of system prompt and tool catalogue travelled in the *user*
message, identical every turn, where no provider cache can reach them. They
now go through `backend/llm/caching.py` as content blocks with one cache
breakpoint at the end of the stable run. Neither block is client-derived, so
neither is barred from the cached span.

### 4. The evidence ledger is no longer re-sent whole (§21)

The two most recent observations keep all their rows; older ones are trimmed
to four rows and a count. The **ledger** is not compressed — only this
rendering of it is — so grounding still checks every figure in the answer
against the full evidence, and a figure from a trimmed row is still grounded.
Evidence tokens per question fell from 6,963 to 4,951.

### 5. The same query is not run twice (§18)

Each tool call is fingerprinted on its name and its arguments with sorted
keys, so the same pair in a different order is recognised as the same query.
A repeat is refused *by name* rather than silently skipped: the loop asked
for something and is told why it got nothing new, which keeps its next
decision informed.

### 6. Normal tool planning stops after four loops (§18)

`safety.MAX_PLANNING_TURNS = 4`, and `MAX_TURNS` is that plus one. The fifth
turn is the answer and is not planning: a loop told "this is your last turn"
and given no turn to use it in ends on a fallback rather than on an answer.
Eight was not a considered number; it was a ceiling.

---

## What is not claimed

* No live provider call was made, so **no real cache hit was observed**. Where
  the caller marks a cache breakpoint the harness models the stable prefix as
  a cache write on the first call and a read thereafter. The weighting prices
  a cache write above a fresh input token, so the model does not flatter a
  prefix that is only ever written once.
* The number of turns is what the harness scripts, not what a live model
  would choose. A live model asked a class C question may take fewer turns
  than four or hit the cap.
* Cost units are a declared weighting, not currency. See `docs/AI_COST.md`.
* Token counts use a four-characters-to-a-token estimate, not the provider's
  tokeniser.

# Proving the AI works

CreditProbe calls itself AI-powered. This document is how that claim is
substantiated from inside the product, by anybody, at any time, in about a
minute.

---

## 1. The problem this solves

A release shipped with 1,334 passing tests and was unusable for everybody who
configured an API key. Two things had gone wrong at once, and neither was
visible:

* the test suite pinned itself to offline mode, so the configuration the product
  ships in had **never executed once**; and
* the product computed "is the AI connected?" as `bool(api_key)`, so a key that
  could not authenticate reported full intelligence while every question fell
  through to the deterministic reader.

Nothing in the interface could have told a user either of those things. The
answers looked reasonable. They were answers to different questions.

So the product now carries its own evidence.

---

## 2. Four states, and only one of them is a claim

`backend/llm/telemetry.py`

| State | What it means |
|---|---|
| `OFFLINE` | No provider key. The deterministic governed reader answers, and the product says so. |
| `CONFIGURED` | A key exists and no request has been made. Honest about not knowing. |
| `CONNECTED` | A real structured response has come back. **The only state that claims health.** |
| `DEGRADED` | A key exists and requests are failing. Says which stage and which category. |

Every model call records safe metadata only: provider, model, purpose, when, how
long, whether it worked, the provider's own request id, whether the structured
output validated, and — on failure — a category and a sanitised reason. The API
key is never read by that module, never stored, and scrubbed from any reason
string before it is kept.

Visible at `GET /api/v1/build`, `GET /api/v1/ask/mode`, `GET /api/v1/ai/status`
and in Settings → AI provider.

---

## 3. The intelligence check

Press **AI POWERED** in the header, then **RUN INTELLIGENCE CHECK**.

Three benchmark threads are drawn at random — one about the data, one
calculation, one conversation — and run through the **real Investigation path**,
the same code the browser uses. Each is then scored against a reference computed
by a separate implementation.

### The ordering is the honesty

```
1. load the benchmark thread            questions only
2. run it through production            the real orchestrator, real runtime
3. take what CreditProbe produced
4. ONLY NOW compute the reference       separate implementation, same data
5. score
6. show the user both, side by side
```

Step 4 cannot happen earlier, and nothing before it can see a reference.

---

## 4. Why the benchmark cannot be gamed

**It is not stored as answers.** A case declares a *specification*: "sum `ead`
from `portfolio_facility` at Q2 2026 grouped by `sector`". Whatever that comes
to is the truth. A figure written into the library could be quietly aligned to
the system's own output by a later edit; a specification cannot.

**The reference is a second implementation.** Hand-written SQL over the Parquet
layer and direct reads of the catalogue — `backend/validation/gold.py`. It shares
no code with the Analytical IR, the validator, the compiler, the planner or the
orchestrator. It is deliberately dumber: no join resolution, no grain
reconciliation, no concept vocabulary. Where the two agree, they agree because
the figure is right.

**No model grades anything.** An LLM judge fails in the same ways as the thing it
judges, and the correlation reads as agreement.

**Production cannot reach it.** `backend/validation` may import production;
production may never import `backend/validation`. Three tests enforce it:

| Test | What it proves |
|---|---|
| `test_production_never_imports_the_benchmark_library` | Walks the import graph of every file that can serve a question. |
| `test_the_orchestrator_cannot_see_gold_data_at_runtime` | Spawns a fresh interpreter, imports the whole orchestration path, asserts the module never loaded — catching a dynamic import the AST check would miss. |
| `test_the_reference_is_computed_after_the_answer` | Spies on both calls and asserts the order. |

Exactly one production file is allowed to import the package: the HTTP endpoint
that starts a run. The direction is what matters — the runner calls the
orchestrator, and the orchestrator has no way back.

---

## 5. Scoring

`backend/validation/scoring.py` — eight weighted dimensions, 100 points.

| Dimension | Weight |
|---|---|
| Intent accuracy | 15 |
| Concept and plan accuracy | 15 |
| Dataset selection | 15 |
| Relationship selection | 10 |
| Period and grain accuracy | 10 |
| Execution and result accuracy | 20 |
| Conversation context | 10 |
| Grounding | 5 |

Two rules matter more than the weights.

**Only what the case exercised is scored.** A dictionary question declares no
relationship expectation, so relationship selection is removed from its
denominator rather than awarded free marks. Otherwise every metadata case scores
in the nineties by construction and the number stops meaning anything.

**Prose is never graded.** Two correct interpretations of the same result can
share almost no vocabulary. What is graded is the decisions and the figures.
Mathematically equivalent SQL is expected to differ; only the result is compared.

Every check that removes marks writes a sentence a credit officer can act on —
"returned 200 of the 1,189 rows the reference identifies", not "88%".

---

## 6. A score that grades the runtime is not a score for the AI

A case answered without reaching the live model **fails**, whatever its figures
say. A run in which no case reached the model gets **no band at all**:

| Band | When |
|---|---|
| `HIGH` / `GOOD` / `LIMITED` / `DEGRADED` | 90+ / 75–89 / 60–74 / below 60, over the live cases |
| `UNVERIFIED` | A key is configured and every case fell through |
| `OFFLINE` | No provider configured |
| `STALE` | The model, build, benchmark version or data has moved on since |

The panel says "governed runtime only" beside an ungraded number. That
measurement is worth having; it is not the one the button promised.

---

## 7. What a user can inspect

Every case row opens. Inside:

* the question — every turn of it, for a multi-turn thread;
* CreditProbe's **actual** answer, including a bad one;
* the **reference**, labelled as computed independently after the fact;
* the overall match and all eight component matches;
* **why the score was not 100%**, in plain language;
* a figure-by-figure comparison table.

Administrators additionally see the structured live reading, the plan, the
generated SQL and the reference's own derivation.

History is kept, because a score is only useful next to the last one: "94 on
Tuesday, 79 today, same benchmark, new model" is what tells somebody a change
broke something.

---

## 8. Cost

The check runs when somebody presses the button. Not on a timer, not on page
load. A hidden benchmark makes real model calls and reads the whole analytical
layer, and spending a bank's provider budget on a number nobody asked for is not
a feature.

Benchmark runs never create Investigations. They execute with `persist=False`
and file nothing.

---

## 9. Where things are

| Path | What |
|---|---|
| `backend/llm/telemetry.py` | Provider states and the safe call ledger |
| `backend/build_info.py` | Version, commit, build stamp, staleness |
| `backend/validation/benchmarks.py` | The hidden library — threads and specifications |
| `backend/validation/gold.py` | The independent reference implementation |
| `backend/validation/scoring.py` | The eight dimensions |
| `backend/validation/runner.py` | The ordering, and what a case records |
| `backend/validation/store.py` | History and staleness |
| `backend/api/routers/validation.py` | `/ai/status`, `/ai/validate`, `/ai/validation…` |
| `tests/validation/test_isolation.py` | The proof the benchmark stays hidden |
| `tests/llm/test_live_smoke.py` | Five real structured calls, when a key exists |
| `tests/evals/test_multi_turn.py` | 102 conversations, one invariant |

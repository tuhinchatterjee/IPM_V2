# The Analytical Runtime

*How CreditProbe composes an analysis it was never given, and why that is safe.*

---

## 1. What changed, and why

CreditProbe used to answer questions by choosing from a list. A planner read the
question, picked one of a few dozen registered analyses, filled in its
parameters, and ran it. Everything about that was safe and reproducible, and it
had one fatal property: **the product could only ever answer questions somebody
had anticipated.**

That ceiling is not a matter of building more analyses. Real credit questions are
combinatorial:

> "Show Real Estate customers whose ECL increased more than 20%, rating
> deteriorated at least two notches, and EAD did not decline over the latest
> year."

Nobody built that. Nobody will. There are more shapes of that question than
there is time to implement, and a product that answers only the anticipated ones
is a report pack with a chat box on it.

So the goal is now:

> If a user could reasonably perform the analytical operation using SQL, Excel,
> Tableau, SAS, Python dataframe tools or standard statistical operations over
> governed bank data, CreditProbe should generally be capable of constructing and
> executing that analysis safely.

**Safely** is the load-bearing word, and the rest of this document is what it
means in code.

---

## 2. The rule that makes it safe

The language model never writes SQL, never writes Python, and never states a
figure. It emits **an Analytical Intermediate Representation** — a JSON document
describing operations over governed datasets — and the runtime decides whether
that document may become a query.

```
    question
       ↓
    a plan, as DATA          backend/runtime/ir.py
       ↓
    validated against the
    governed catalogue       backend/runtime/validation.py   ← the security boundary
       ↓
    compiled to parameterised SQL
                             backend/runtime/compiler.py
       ↓
    executed on DuckDB, then
    allowlisted Python kernels
                             backend/runtime/executor.py, kernels.py
       ↓
    result + full Trace
```

Four properties hold at every step, and each closes a specific way a
confident-sounding wrong answer could reach a credit committee:

| Property | Where it is enforced |
|---|---|
| No `eval`, no `exec`, no arbitrary Python, no filesystem, no network, no subprocess | There is no operation type that accepts code. A kernel is chosen from a fixed allowlist by name. |
| No string-concatenated SQL | `Compiler.bind()` is the only way a value enters a statement. Identifiers pass a strict regex and are quoted. |
| No invented data | Every dataset, field and function is checked against the governed catalogue before compilation. An unknown one is a refusal with "did you mean". |
| No invented numbers | The model produces the shape of the analysis. Every figure comes back from the engine. |

A value shaped like SQL matches no column and is refused. A path cannot be
smuggled in as a dataset name, because dataset names are looked up rather than
interpolated. A plan naming a field the dataset does not carry is rejected —
with every reason, not the first, because somebody fixing a plan needs the whole
list.

---

## 3. The Analytical IR

`backend/runtime/ir.py`. A plan is a directed acyclic graph of operations:

```json
{
  "id": "dynamic_cohort",
  "operations": [
    {"id": "opening", "op": "SCAN",
     "params": {"dataset": "portfolio_facility", "period": "Q2 2025",
                "fields": ["customer_id", "ead", "total_ecl", "internal_grade"]}},
    {"id": "opening_grain", "op": "GROUP", "inputs": ["opening"],
     "params": {"by": ["customer_id"],
                "aggregates": [{"function": "sum", "column": "ead", "as": "ead"}]}},
    {"id": "movement", "op": "JOIN", "inputs": ["opening_grain", "closing_grain"],
     "params": {"kind": "inner", "on": ["customer_id"], "right_prefix": "closing_"}}
  ]
}
```

Around fifty operation types, covering what the goal statement promises: row
shaping (`FILTER`, `DERIVE`, `DEDUPLICATE`, `TOP_N`), combination (`JOIN`,
`UNION`), aggregation (`GROUP`, `AGGREGATE`, `DISTINCT_COUNT`), windows (`LAG`,
`ROLLING`, `RANK`), reshaping (`PIVOT`, `CROSSTAB`), credit-specific shapes
(`VINTAGE`, `COHORT`, `WATERFALL`, `MATRIX`, `RECONCILE`), and statistics
(`CORRELATION`, `REGRESSION`, `STAT_TEST`, `OUTLIER`, `TREND`, `SCENARIO`).

Expressions are trees — `LITERAL`, `COLUMN`, `FUNCTION`, `CASE` — never strings.
There is nowhere in an expression to put a fragment of SQL that would mean
anything.

A plan carries a `fingerprint()` computed over what it *computes*, excluding
labels and metadata. Two plans that produce the same number have the same
fingerprint whatever they are called.

---

## 4. Validation: the security boundary

`backend/runtime/validation.py`. Walks the plan in dependency order, carrying the
schema each step produces, and checks:

- every dataset exists in the governed catalogue and is not archived;
- every column exists in the schema *at that point in the plan* — including
  columns a `DERIVE` created three steps earlier;
- every function is on the allowlist;
- every join key exists on both sides, and the output schema it produces is
  computed exactly as the compiler will compute it;
- limits: operations, scans, joins, output rows, expression depth, group keys,
  timeout.

It returns **every** reason a plan was refused, and uses `difflib` to say "did
you mean" on a near-miss field name. It never repairs a plan: dropping an
unrecognised parameter and running anyway answers a different question, which is
worse than refusing.

---

## 5. Execution

`compiler.py` emits one `WITH` statement, one CTE per operation, every value
bound as a parameter. `executor.py` runs it on DuckDB under a watchdog that
calls `connection.interrupt()` on timeout, then runs any kernel steps.

Kernels (`kernels.py`) are six allowlisted Python functions — correlation,
regression, trend, outlier detection, statistical tests, scenario application.
Each declares its own limitations, which travel with the result. `kernel_for()`
refuses anything not in the allowlist; there is no path by which a name reaching
it becomes an import.

Both engines appear on the Trace: an `SQL_QUERY` node carrying the statement and
its bound parameters, and a `KERNEL` node carrying the function, its version and
what it does not tell you.

---

## 6. Dynamic analysis

`backend/orchestration/dynamic.py`. A question naming **two or more independent
conditions** is composed rather than looked up, because no single certified
analysis answers a multi-condition cohort question and the closest one would
return a correct figure for a narrower question — carrying a certification tick
while doing it.

The question is read deterministically into an explicit request: grain, period
span, governed filters, and a list of conditions. Three comparisons people say
in one breath are kept apart, because they are different questions:

| Phrase | Comparison |
|---|---|
| "ECL increased more than 20%" | relative change, strictly greater |
| "rating deteriorated at least two notches" | absolute change on an ordinal scale |
| "EAD did not decline" | a floor at zero |

A rating deteriorating is a *higher* grade; coverage deteriorating is a *lower*
percentage — the same word resolves against the measure it describes.

Rolling up to the grain happens **before** the join. Joining first multiplies a
customer's rows by its facility count and counts one movement many times. An
ordinal measure rolls up by its worst value, never averaged: an average rating
across four facilities is a grade nobody assigned. A percentage change from zero
is null, not infinity.

The result is labelled **Dynamic Analysis · Governed Runtime**, never certified,
and carries its own working: the reading, the plan, and the SQL with its bound
parameters shown separately. It can be saved to Analysis Studio, arriving as a
**draft** with no tests and no tick — running once against one pair of periods
is not evidence that a calculation is right.

Where CreditProbe cannot read a question completely, it refuses and names the
part it could not read. It does not narrow silently.

---

## 7. Multi-dataset analysis

`backend/runtime/joins.py`, `backend/orchestration/concepts.py`,
`backend/orchestration/multi.py`.

"Show Real Estate customers whose ECL increased more than 20%, rating
deteriorated at least two notches, and EAD did not decline over the latest year"
needs three governed datasets reported at two frequencies. Nothing in the
sentence names a dataset, a join key, a cardinality or a period alignment — and
nothing should, because a credit officer thinks in concepts, not in tables.

### 7.1 One relationship model

There is exactly one place a join may come from: the relationships a steward
declared in Data Builder. The planner consumes that model; it does not have one
of its own, and it cannot invent an edge that is not in it.

A relationship carries a lifecycle — **draft → validated → active → archived** —
and only `active` is runnable. Reaching `active` needs measured evidence:
`backend/services/relationships.py` reads both sides at one published period and
counts the match rate, the orphan rate and the duplicate rate, and refuses
promotion where coverage is below 80%, where a relationship declared
`many_to_one` or `one_to_one` has a right side that is not unique, or where
confidence is below 0.75. Every change records what the relationship was before
it, so "why did this number change" survives a governance edit.

### 7.2 Concepts, not columns

`resolve_concept` turns "exposure at default" into a governed field. Where more
than one dataset carries the concept, resolution goes in this order:

1. **A qualifier in the question settles it.** "regulatory EAD" is not
   ambiguous.
2. **The bank's own authoritative data.** A client-origin dataset a steward has
   declared authoritative beats a default pointing at the demonstration book,
   and the answer names the source it did **not** use. A correct calculation
   over the wrong company's portfolio is worse than a refusal: it looks right.
3. **The declared default**, with the alternatives recorded so the answer can
   say which definition it used.
4. **Otherwise it asks.** Two figures that are genuinely different are not
   resolved silently.

### 7.3 Choosing a join path

Datasets are nodes, active relationships are edges, and the search is a
breadth-first walk capped at three hops. The interesting part is the ranking:

- fewer hops win — every hop is a chance to lose rows;
- the safe direction wins — `many_to_one` and `one_to_one` cannot multiply the
  left-hand book; `one_to_many` and `many_to_many` can, and are allowed only
  where the resolver also inserts an aggregation before the join;
- measured beats declared — a relationship with a real match rate outranks one
  nobody has validated;
- archived is not a candidate — a retired domain leaves the graph entirely.

Where two materially different paths score within 0.15 of each other, the
resolver does not choose silently: it records the alternatives and states which
it used and why, in the plan summary and on the answer.

### 7.4 Grain and period reconciliation

Two failures matter here, and the planner is built around avoiding both.

**Duplicate amplification.** A source with more than one row per analysis grain
is rolled up to that grain *before* it is joined, never after. `IFRS9_STAGING`
joins at account level and rolls up to customer; `PORTFOLIO_FACILITY` rolls up
from facility to customer. Joining first multiplies a customer's rows by its
facility count and counts one movement many times.

**Look-ahead.** Sources reported at different frequencies are joined **as-of**:
the latest observation dated on or before the reporting date, never after it.
The validator refuses a forward as-of join and refuses one with no ordering
column, so a plan that would use future data does not compile. A quarter is
aligned to the annual cycle that had *completed* by its reporting date
(`completed_year_of_quarter`), so Q1 2026 legitimately joins to the FY2025
rating rather than to one published later in 2026.

### 7.5 What the answer carries

Every multi-dataset answer carries how it was assembled, under **Data & method**:

- which governed sources, at which version, for which periods;
- the join path as a chain, with each hop's cardinality and period rule;
- what happened to the population at every step, counted against the same query
  that produced the answer rather than re-derived afterwards;
- the relationships walked, with the version each was walked at;
- warnings — a join that lost a third of the book, a path with a choice in it, a
  crossing that could have multiplied rows.

The Trace records the same as governed nodes: one `JOIN` node per join, a
`RECONCILIATION` node, and a `FINGERPRINT` node.

### 7.6 What identifies a run

`backend/runtime/fingerprint.py`. A plan hash answers "is this the same
computation". It cannot answer "should these two runs agree", because the same
IR against a restated dataset or a re-declared join is entitled to a different
answer. So a run carries four hashes and a fifth binding them:

| | covers |
|---|---|
| `plan` | the steps, their inputs and their parameters |
| `data` | every dataset read, at the version it was read at |
| `relationships` | every governed join walked, at the version that was active |
| `parameters` | the periods and values bound into it, by step |
| `run` | all four |

Two runs sharing `run` computed the same thing from the same data under the same
relationship model. Two that differ say which of the four moved.

### 7.7 Saving one

A multi-dataset analysis saved to Analysis Studio stores the **concepts** it
measures rather than the columns one dataset happens to call them, the governed
relationships it walks with their versions and cardinalities, and how periods
were aligned. A method that stored `ifrs9_staging.ead` would break the day a
bank supplies its own extract under a different column name; one that stores
"exposure at default" re-resolves against whatever the catalogue declares
authoritative when it next runs.

It still arrives as a **draft**, with no tests and no tick.

---

## 8. Analysis Studio

`backend/studio/`. The library holds **320 credit-risk method definitions**
across 18 categories. **42 carry CreditProbe Certified.** The gap is the point.

A method may *claim* certification. Claiming is not being. At registry load,
every claim is re-verified against the thing that would have to be true for it to
hold:

- a registered engine analysis that is itself runnable and certified, **or**
- an Analytical IR plan whose test cases have been run and passed.

A claim that does not survive is downgraded to `preconfigured` and the reason is
recorded in an audit the API exposes. So the library cannot drift into
advertising a tick it has not earned, and deleting an engine function stops the
methods depending on it claiming certification at the next start rather than at
the next audit.

### Building a method

Describe it. CreditProbe reads it back and asks only the decisions that change
the answer — grain, default definition, timing, exits, weighting — each with why
it matters. Then it builds the plan and runs a twelve-case validation pack whose
expected results come from **a second implementation written from the methodology
text in plain Python**, sharing no code with the IR, the compiler or DuckDB.

That second implementation has already earned its keep. It caught the plan
testing the *opening* IFRS 9 stage where it meant the *forward* one — which
would have returned 11% instead of 44% with nothing about the output looking
wrong. It also caught "default at any point in the horizon" being built as
"default at the horizon"; that option is now refused rather than approximated,
because a silently understated rate is worse than a missing feature.

The same twelve rows produce 11.1%, 40.0%, 44.4% or 55.6% depending on the
answers. That divergence is the argument for asking the questions at all.

### Certification, forking, editing

Certification is the narrowest permission in the product — narrower than
publishing data. An analyst may build and run anything; deciding that a method is
the bank's certified way of measuring something takes an admin, and the gate
lists every outstanding requirement rather than the first.

A fork starts as a draft with no tick and no test results, however certified its
parent was, but keeps the same fingerprint until somebody changes it. Editing a
certified method drops it to draft and leaves the signed-off version standing in
the history.

The validation pack downloads as a **sixteen-sheet workbook**, because a model
validation team reviews a method in a file they can annotate and attach to a
sign-off, not in a web page.

---

## 9. The Data Inbox

`backend/services/inbox.py`, `backend/services/drift.py`.

Onboarding is a one-off; arrival is forever. The case this exists for is not a
load that fails but a load that **succeeds while the meaning of a column changes
underneath it** — a source system starts sending EAD in units rather than
millions, every figure is a million times too large, every calculation is
correct, and nothing anywhere looks wrong.

So a new file is compared against the last one accepted, field by field: fields
added and removed, types, null rates, cardinality, category values, numeric
ranges, row count. Each finding says what changed **and what it costs**.

Severity decides nothing; the policy does, and it is a pure function so the rule
can be read and argued with rather than discovered:

| Outcome | When |
|---|---|
| Publishes itself | matched confidently, schema unchanged, nothing blocking or material |
| Held | a first load, an uncertain match, or drift somebody should see |
| Held, unmatched | nothing in the catalogue carries these columns |

There is no "publish anyway because it is late" path. A held file is published by
a person, that person needs a reason, and the drift that stopped it stays on the
record afterwards.

Matching is on **columns**, not filenames, because a monthly extract really is
called `extract_final_v3.csv`.

---

## 10. The demonstration book

Twenty governed datasets, every one derived from a single simulation with one
fixed seed:

| | |
|---|---|
| Core | `portfolio_facility`, `ifrs9_staging`, `borrower_financials`, `customer_ratings`, `macro_saudi` |
| Operations | `facility_delinquency`, `payment_history`, `facility_limits`, `collateral_register`, `covenant_tests` |
| Risk management | `watchlist_register`, `recoveries`, `risk_appetite_limits`, `credit_memo_signals` |
| Analytics | `rating_transitions`, `pd_model_performance`, `scenario_definitions`, `facility_profitability` |
| Reference | `group_structure`, `climate_risk` |

Derived, not generated beside: the collateral register's items sum back to the
facility book's `collateral_value`; the covenant tests are computed from its
headroom; the watchlist is exactly the customers its `watchlist` flag names; the
recoveries are anchored on its LGD. A demonstration where the collateral
coverage contradicts the facility book is a demonstration of nothing, and
`tests/test_extra_domains.py` is almost entirely reconciliations.

Everything is marked SYNTHETIC and describes no real borrower, bank or economy.

---

## 11. What this is not

- **Not a text-to-SQL product.** The model never sees a SQL dialect and never
  emits one. What it emits is checked against the catalogue before it becomes a
  query.
- **Not certified because it ran.** A composed analysis is labelled dynamic
  wherever it appears. Execution is not evidence.
- **Not a claim of statistical accuracy.** Nothing here asserts predictive
  performance for any model. Where a method carries limitations, they travel
  with the result.
- **Not a reproduction of any vendor methodology.** Every certified method
  states its own methodology in reviewable English.

## 12. Where to look

| | |
|---|---|
| `backend/runtime/ir.py` | the plan format |
| `backend/runtime/validation.py` | the security boundary |
| `backend/runtime/compiler.py` | parameterised SQL |
| `backend/runtime/kernels.py` | the six allowlisted kernels |
| `backend/runtime/executor.py` | execution, Trace, chart selection |
| `backend/runtime/fingerprint.py` | what identifies one run |
| `backend/orchestration/dynamic.py` | reading a question into a plan |
| `backend/orchestration/concepts.py` | concepts to governed fields |
| `backend/orchestration/multi.py` | the multi-dataset planner |
| `backend/runtime/joins.py` | the join graph and path resolver |
| `backend/services/relationships.py` | the one relationship registry |
| `backend/studio/` | methods, registry, builder, validation packs, workbook |
| `backend/services/drift.py` | field-by-field comparison |
| `backend/services/inbox.py` | arrivals and the auto-publish policy |
| `tests/runtime/test_runtime_safety.py` | what the runtime refuses |
| `tests/runtime/test_dynamic_analysis.py` | the worked example end to end |
| `tests/multi/` | join resolution, grain, look-ahead, governance, fingerprints |
| `tests/studio/` | the library, the tick, the ODR builder |

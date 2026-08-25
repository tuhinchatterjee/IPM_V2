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

## 7. Analysis Studio

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

## 8. The Data Inbox

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

## 9. The demonstration book

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

## 10. What this is not

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

## 11. Where to look

| | |
|---|---|
| `backend/runtime/ir.py` | the plan format |
| `backend/runtime/validation.py` | the security boundary |
| `backend/runtime/compiler.py` | parameterised SQL |
| `backend/runtime/kernels.py` | the six allowlisted kernels |
| `backend/runtime/executor.py` | execution, Trace, chart selection |
| `backend/orchestration/dynamic.py` | reading a question into a plan |
| `backend/studio/` | methods, registry, builder, validation packs, workbook |
| `backend/services/drift.py` | field-by-field comparison |
| `backend/services/inbox.py` | arrivals and the auto-publish policy |
| `tests/runtime/test_runtime_safety.py` | what the runtime refuses |
| `tests/runtime/test_dynamic_analysis.py` | the worked example end to end |
| `tests/studio/` | the library, the tick, the ODR builder |

"""
The CreditProbe Analytical Runtime.

The pivot this package exists for
---------------------------------
CreditProbe used to answer only the questions somebody had written an analysis
for. A question one word outside that list got a clarification, however
reasonable it was. That is the right behaviour when the alternative is guessing,
but it is the wrong ceiling for a product whose users think in SQL, Excel and
SAS: "top ten Real Estate borrowers whose ECL rose more than 20% while their
rating fell two notches" is an ordinary request, and no bank would accept
"nobody has built that one" as an answer.

So the runtime composes. A question becomes a structured plan of governed
operations — scan, join, filter, derive, group, aggregate, window, rank — and
that plan is validated, compiled and executed. The set of answerable questions
is now the set of things the operations can express, which is very much larger
than any list of prebuilt analyses.

What did NOT change
-------------------
The language model still does not touch the data. It emits an intermediate
representation and nothing else: no SQL text, no Python, no file paths. Every
dataset, field, operator and function named in that IR is checked against the
governed catalogue before anything runs, every literal reaches DuckDB as a bound
parameter, and every step lands on the Trace with its row counts and its query.

The model can now order a great deal more from the menu. It still cannot cook.

Layout
------
    ir.py          the intermediate representation — operations and plans
    validation.py  every rule that decides whether a plan may run
    compiler.py    IR to parameterised DuckDB SQL
    kernels.py     the allowlisted numerical operations
    executor.py    execution, the Result contract, and the Trace it emits
"""

from backend.runtime.ir import (
    AnalyticalPlan,
    Operation,
    OpType,
    PlanError,
)

__all__ = ["AnalyticalPlan", "OpType", "Operation", "PlanError"]

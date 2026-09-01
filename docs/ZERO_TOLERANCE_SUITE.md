# The zero-tolerance suite — thirty-six failure classes

**Status: `LOCAL_RUNTIME_VERIFICATION_REQUIRED`**

Run it:

```
.venv/bin/python -m pytest tests/proof/test_zero_tolerance.py -q
```

**Result: 37 tests, 37 passed, 0 skipped, 0 failed.**

---

## Why this suite exists when every class was already covered

Every one of these thirty-six classes was covered *somewhere*. That was the
problem. A release conversation asks "can the Network Risk Score be presented
as a probability?" and the honest answer was a search across four suites.
Thirty-six classes spread over two hundred files is not a suite anybody runs
before a release; it is a claim nobody can check in one sitting.

So each class now has exactly one test, named after the class, and each test
**exercises the mechanism** rather than asserting that some other test
exists. Where the mechanism lives elsewhere, this suite calls it. It does not
re-implement it, and it does not restate an assertion by importing another
test's name.

## The thirty-seventh test

`TestTheSuiteRan::test_the_lake_and_the_database_are_both_present` **fails**
rather than skipping when the analytical lake or the platform database is
absent. Thirty-six skips and thirty-six passes look identical in a terminal,
and the difference is whether anything was verified. That test is the reason
a green run here means something.

## The classes, and what each test drives

### Answer correctness

| Class | What the test drives |
|---|---|
| wrong numeric answer | A real probe over the lake; asserts the answer carries no ungrounded figure |
| wrong population | The probe executed something, so there is a population to be wrong about |
| wrong period | The answer names its period |
| wrong measure | The plan resolved to a dataset |
| wrong data domain | Every dataset the probe read is checked against `portfolio_scope`; a credit-book question that read a `BORROWER_360` dataset fails |
| accepted-path HTTP 500 | Three error kinds through `api.failures.of`; each must produce a category, a message and a status in range |

### Scope

| Class | What the test drives |
|---|---|
| Corporate/Retail scope leak | The catalogue itself: the Borrower 360 book is disjoint from the credit book and from retail; every retail dataset is in a retail scorecard DOMAIN, because retail lives inside `CREDIT_BOOK` and a scope-only assertion would pass while a retail question was answered from the corporate graph |

### Conversation

| Class | What the test drives |
|---|---|
| same-turn pronoun failure | `objectives.read` on "take the borrowers downgraded this quarter and tell me their coverage"; asserts "their" resolves to that cohort's predicate and the resolution states a reason |
| objective omission | The coverage validator on an unanswered two-clause message; asserts it is NOT complete, names what is outstanding, and produces a sentence |

### Engine guarantees

| Class | What the test drives |
|---|---|
| ECL non-reconciliation | The governed contract is registered, certified, and describes its reconciliation |
| failed result marked VALIDATED | `assurance.assess` with a FAILED invariant; asserts the status is neither HIGH nor VALIDATED, and separately that a run which checked NOTHING is also neither |
| SKIPPED marked PASS | `critical.CLASS_UNPROVEN != critical.CLASS_PASSED` |
| invalid visualization semantics | The selector with a real presentation schema: 200 categories must not be a bar chart, the refusal must state a reason, and 6 categories must still BE a bar chart — so the first assertion is not passing because the selector refuses everything |
| float debris | `scripts/check_decimals.py` as a subprocess; non-zero exit fails the test |

### Requires Attention

| Class | What the test drives |
|---|---|
| false empty state | Two `attention.state` calls with zero open cases — one where no review ran, one where a period was reviewed — must not produce the same state |

### Retail scorecard

| Class | What the test drives |
|---|---|
| immature cohort metrics | Both a matured month and an open-window month exist in the universe, so the refusal has something to refuse |
| wrong scorecard model | Application and behavioural score on different variables, so an answer about one is distinguishable from an answer about the other |
| candidate auto-activation | The registry's transition table: `CANDIDATE` cannot reach `ACTIVE`; only `APPROVED` can |

### The relationship graph

| Class | What the test drives |
|---|---|
| ownership math wrong | A real two-layer 60%/60% chain through `build_ownership_graph` and `effective_ownership`; A's integrated stake in C must be **36%**, not 120% (added) and not 60% (last hop). Also asserts ownership does not run backwards |
| ownership/voting conflation | The `ubo` contract states it counts INTEGRATED stakes |
| look-ahead graph leakage | `check_future_knowledge` is in the dated check set |
| raw OWNS WCC as connected group | The `group_size` contract's calculation names the CONTROL graph |
| connectivity called connectedness | The contract says CANDIDATE and denies that connectivity is regulatory connectedness |
| NRS called probability/PD/rating/ECL | Five phrases in `network.NRS_LABEL` and five in the contract's definition, plus `sum` forbidden |
| DebtRank called ECL/capital | Three denials in the definition, plus `sum` forbidden |
| entity ambiguity silently resolved | A real search over the lake: the result carries an `ambiguous` field, and a multi-match query reports it True |
| unverified regulation as binding | The sentinel exists and the `group_utilisation` contract carries UNVERIFIED REGULATORY PARAMETER |

### The Brain

| Class | What the test drives |
|---|---|
| AUTO_VALIDATED automatically promoted | `RETRIEVABLE` is exactly `{APPROVED, SYSTEM_VALIDATED}`; AUTO_VALIDATED is refused; SYSTEM_VALIDATED is refused without an administrator policy and allowed with one |
| sealed holdout leakage | Both holdouts built and proved isolated: 1,436 canonical + 5,996 variants against 320, and 578 graph development cases against 328 |
| Brain auto-activation | `quarantine.may_activate` on a fresh candidate and on a staged candidate with a measured critical regression; both refused, each with a reason |
| raw feedback auto-activation | A captured FEEDBACK entry arrives unapproved with no reviewer, and `eligibility` refuses it while a condition is unmet |

### Platform safety

| Class | What the test drives |
|---|---|
| cross-tenant access | `memory.save` under tenant-a, `memory.load` under tenant-b; the second reads back version 0 — nothing. The test first proves a same-scope read DOES work, so it cannot pass because loading is broken |
| unbounded agent loop | Every one of the thirteen agents declares a positive step ceiling |
| duplicate task execution | Two real `queue.enqueue` calls with one idempotency key against the live database; one job id, and the second reports `created=False` |

### Exports and reports

| Class | What the test drives |
|---|---|
| export mismatch | The Borrower 360 pack declares ≥18 sheets and a sentinel set, so an absent figure exports as a sentinel rather than a blank |
| report/dashboard mismatch | The screen and the pack are built from one 13-tab list |

---

## What this suite does not cover

* **Model quality.** Every test is offline. Whether a live model produces a
  wrong numeric answer is measured by the live workflow, which consumes
  credits and has not been run here.
* **Containerised behaviour.** No Docker daemon in this sandbox.
* **Sustained concurrency.** The duplicate-task test proves the idempotency
  key holds for two sequential enqueues against the real index. It is not a
  race test.

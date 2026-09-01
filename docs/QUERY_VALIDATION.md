# The rows that come back are the rows that should come back

**Part 12.** The query-fidelity and multi-condition work proved the PLAN carries
every condition the question asked for. That is necessary and it is not
sufficient: a plan can be faithful, compile, run, and return the wrong
borrowers — or none — and nothing inside the system looks like a failure.

This is the validation that runs each question through the real path, executes
it against the real book, and then recomputes the answer **independently** from
the parquet with pandas. A second implementation written from the question
rather than from the plan. Where the two disagree, one of them is wrong, and
the test names the borrowers.

Two defects came out of it. Both are the same shape: a correct query answering
a narrower question than the one asked, with nothing anywhere saying so.

---

## 1. The empty answer that was not a finding

> "Which borrowers had a PD increase and were downgraded in Q2 2026?"

returned **nothing**. Every condition reached the FILTER. The query succeeded.
The plan was faithful. A reader takes that as a finding: nothing on this book
both deteriorated and was downgraded.

That is not what happened. `customer_ratings` is an **annual** dataset whose
latest completed cycle is 2025. Q1 2026 and Q2 2026 both resolve — correctly,
and by design, because a quarter must not read a cycle that has not finished —
to that same 2025 cycle. The internal grade on both sides of the
quarter-on-quarter comparison is *the same row*. The difference is identically
zero for every borrower on the book. A condition asking for a change in it can
never hold.

The empty result was a fact about the calendar, not about the book.

### The fix

`backend/orchestration/collapse.py` reads the finished plan — before it runs —
and reports which movement columns are structurally incapable of being
non-zero: a change derived from a field that reaches the plan through an as-of
join whose temporal alignment maps **both** endpoints of the comparison onto
the same source cycle. It computes nothing about the borrowers. It is a
statement about the plan, so an empty answer can say why it is empty:

> customer_ratings is published once a cycle, and both Q1 2026 and Q2 2026 read
> the 2025 cycle — the same rows on both sides of the comparison. A change
> measured across them is zero for every borrower by construction, so this
> condition cannot be tested between these two dates. The customer_ratings
> cycle does record the movement itself, in `notches_moved`; asking for that
> reads what actually happened rather than a difference that cannot exist.

### Two fixes that were not made

**Let the quarter read the 2026 cycle.** Look-ahead: it answers a Q2 2026
question with a rating cycle that had not finished at Q2 2026, which is worse
than saying nothing.

**Compare across a year instead of a quarter.** Silently answers a different
question.

Saying what it can and cannot do, and naming the field that DOES record the
movement, is the only one of the three that is honest.

---

## 2. "Stage 2 or worse" was read as "stage 2"

> "Which borrowers had a PD increase and are booked at stage 2 or worse?"

resolved `ifrs9_stage = 2`. The stage 3 borrowers — the ones actually in
trouble, the ones the question was reaching for — were silently excluded from a
population that claimed to include them.

The comparison vocabulary the semantic reader carries only fires when the
comparator comes BEFORE the number: "above 2", "at least 2". Credit officers
write the other order — "stage 2 or worse", "grade BB or below", "90 days or
more" — and that shape was not read at all.

### Worse is not a direction, it is a direction on a measure

"or worse" cannot be compiled without knowing which way the measure runs. A
higher IFRS 9 stage is worse; a higher interest cover is better. So
`backend/orchestration/ordinal.py` resolves the qualifier against the measure's
own governed direction, and a measure whose direction is not written down
produces **nothing** rather than a guess.

| Written | ifrs9_stage (higher is worse) | interest_coverage (higher is better) |
| --- | --- | --- |
| `2 or worse` | `>= 2` | `<= 2` |
| `2 or better` | `<= 2` | `>= 2` |
| `2 or above` | `>= 2` | `>= 2` |
| `2` | `= 2` | `= 2` |

Read on both the single-dataset and the multi-dataset path, because a condition
can be lost on either and a fix that guards one guards nothing.

### What it changed

On the live Q2 2026 book, "PD increase and booked at stage 2 or worse" now
returns **380 borrowers**. It returned **258** before — the 122 stage 3 names
were being dropped from an answer that said it included them.

---

## What the validation asserts

Beyond the two defects, for each question that CAN be answered:

* **every borrower returned really satisfies every condition** — checked
  against the independent read, borrower by borrower;
* **no borrower who qualified was left out** — where the result is not
  truncated, since absence proves nothing against a limit;
* **the rows carry the evidence** for the claim on screen, so a reader can
  check one without leaving the page.

`tests/orchestration/test_query_validation.py`. The independent reader is
deliberately pandas over the parquet rather than the product's own catalogue or
its DuckDB compiler: a second implementation that shares the first one's
machinery agrees with it about the things the machinery gets wrong.

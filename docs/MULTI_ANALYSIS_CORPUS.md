# The multi-analysis response corpus

Fifty questions, run through the same path a person's question takes, scored
on whether the RESPONSE has the shape the question warrants.

```bash
python scripts/evaluate_multi_analysis.py                    # all fifty
python scripts/evaluate_multi_analysis.py --family crossing  # one family
python scripts/evaluate_multi_analysis.py --case 50          # one case
python scripts/evaluate_multi_analysis.py --json out.json    # machine-readable
```

The cases live in `tests/evals/multi_analysis_cases.json`. Nothing in them is
an expected figure. A corpus that pinned numbers would fail on every published
period and would teach nobody whether the product had read the question — so
each case states what the question is FOR, which governed concepts the answer
must be about, which would be padding, and what shape the response should take.

## The four checks

| check | what it means |
| --- | --- |
| `ANSWERED` | it answered, rather than clarifying, refusing or failing |
| `BLOCKS` | the package carries between the case's min and max analyses |
| `KINDS` | every block kind the case names appears in the package |
| `CLEAN` | nothing the case marks as padding is named in the answer |

They are independent on purpose. A case can be `ANSWERED` and fail `BLOCKS`,
and that combination is the whole reason the corpus exists: a review that ran
five governed analyses and rendered one is answered and wrong.

## Where the corpus came from

The mandate's fifty cases were specified as a schema plus one worked example —
case 50, the complete sector deterioration review — rather than as fifty
written-out questions. These fifty are written to that schema and anchored on
that example. They span ten families: single figures, lists, level thresholds,
crossings, movements, multi-condition populations, distributions,
decompositions, broad investigations, and the complete deterioration review.

## Result on this HEAD

```
ANSWERED  47 / 50
BLOCKS    46 / 50
KINDS     42 / 50
CLEAN     50 / 50
ALL FOUR  41 / 50
```

Nine cases fail at least one check. They are listed here rather than tuned
away, because a corpus that scores fifty out of fifty on the day it is written
is a corpus that was written to the product rather than to the questions.

### Cases where the product asks and asking is right

Two cases (7 and 17) are marked `clarification_is_correct` in the corpus, with
the reason on the case. "The ten largest exposures" names one of three
governed measures that differ by material amounts and nothing in the sentence
chooses between them; "an LGD above 45%" is a threshold on either the modelled
assumption or the realised outcome, and a threshold on one is not a threshold
on the other. Guessing would be worse than asking, so the corpus records the
question as the right answer instead of scoring the product down for it.

### The nine open failures, with root causes

**3. "How many customers do we have?" — clarifies.**
A count with no measure named resolves its base dataset to
`corporate_connected_groups`, which cannot be restricted the way the question
needs. Base selection for a bare count does not consider what the count is of.

**16. "Which customers have collateral coverage below 50%?" — clarifies.**
The collateral coverage concept does not resolve to a governed field in this
installation, so the level test has nothing to attach to and the question
falls through to the generic "which borrowers?" clarification. The
clarification is the wrong one: the question DID define its population.

**20. "Which customers have leverage above 5x?" — answers about the wrong
measure.** The measure resolves to `internal_grade` rather than leverage, and
the bound is applied to the grade. `net_leverage` is read and carried but not
tested. This is the most serious of the nine: it produces a confident answer
to a question nobody asked.

**29. "Which Real Estate customers have covenant headroom below 15% and
utilisation above 90%?" — clarifies.** The sector restriction chooses
`portfolio_facility` as the base, and `portfolio_facility` does not carry
headroom. Base selection is decided before the conditions are considered, so a
condition's own dataset cannot influence it. The same question without the
sector answers correctly.

**33. Three comparison kinds in one sentence — zero rows.**
All three conditions are now read correctly and kept apart (the `change_abs`
regression this corpus found is fixed), but the compiled population is empty.
Whether zero is the true answer has not been independently reconciled.

**39. "Show me the rating transition matrix." — rendered as a table.**
The visual selector does not classify the result as a from/to matrix, so the
package has no `matrix` block. The figures are right; the shape is not.

**40. "What is the days past due distribution?" — one row.**
"Distribution" does not produce bands. A single portfolio DPD figure is not a
distribution, and calling it one is the failure.

**41. "Why has ECL changed over the latest year?" — a movement, not a bridge.**
The reconciled ECL decomposition exists and this question does not route to
it, so the answer is the movement rather than the steps between the two
totals.

**47. "What deteriorated this period?" — one analysis.**
The portfolio-wide investigation with no named population runs a single
analysis where the same question against a named sector runs five.

## What the corpus proved on the way

Four defects were found by running it and are fixed on this HEAD:

- a stated row count was dropped by the cohort builder ("the top ten" returned
  a hundred and six);
- `deteriorated` was missing from the threshold reader's movement vocabulary,
  so "deteriorated at least two notches" became a level test;
- a bound with no measure in front of it scanned to the end of the sentence,
  binding itself to a measure three clauses away;
- an IFRS 9 context did not settle the exposure ambiguity, so "Which sectors
  have the highest Stage 2 exposure?" — one of the Cockpit's own starter
  questions — came back asking which exposure figure was meant.

Two more were found and fixed while proving case 42:

- "the increase in Stage 2 exposure" read the stage LABEL as the size of the
  movement, producing "EAD rose more than 2" from a sentence that says no such
  thing;
- the two-period headline printed a filter value with no dimension name, so a
  question about Stage 2 was headed "All 2 facilitys".

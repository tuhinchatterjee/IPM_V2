# Dimension, grouping and answer grain

What one row of an answer IS, and how the sentence decides it.

Companion to `docs/CONVERSATION_CONTEXT.md`, which covers what carries between
turns. This one is about a single question.

---

## The two defects this closes

| Question | Before | After |
|---|---|---|
| Which sectors concern you most? | 25 borrowers | **17 sectors**, ranked by the share of exposure carrying governed concern evidence |
| Show rating distribution. | one number: `10.00 notches of internal rating` | **10 internal grades**, with exposure, borrower count and share |

Two root causes, and they are different.

**The dimension was only ever read from an explicit "by X".** A question whose
dimension is its *subject* — "which sectors", "rating distribution" — arrived at
the planner with no dimension at all and fell through to whatever grain the
source dataset happened to be keyed on. The figures were right; the rows were
about the wrong thing, which is not a smaller version of the right answer.

**The dimension was also counted as the measure.** "Rating distribution"
resolved `internal_grade` as the figure AND grouped by it, so the plan asked for
the average rating of each rating. One row. A scalar answer to a distribution
question is not a rounding error — it is the wrong question answered
confidently.

## The contract

> The noun the question asks for determines the result grain, unless another
> explicit instruction overrides it.

Measure and dimension are different questions and are answered separately:

| | measure | dimension |
|---|---|---|
| Which sectors have the highest ECL? | expected credit loss | **sector** |
| Which borrowers have the highest PD? | 12-month PD | borrower |
| Show rating distribution by exposure. | exposure | **rating** |

## Three rules, in order

`backend/orchestration/dimensions.py` answers one question — what does the
answer have one row of — and never chooses a measure.

1. **breakdown** — an explicit instruction: "by sector", "per rating", "for each
   stage", "grouped by region", "broken down by segment".
2. **named** — the dimension modifying a shape word: "rating distribution",
   "sector split", "stage mix", "region breakdown".
3. **requested** — the head noun of the request itself: "which sectors…", "show
   me the ratings…", "the five largest sectors…".

Rule 3 was the missing one, and it is also the one that outranks an entity noun
appearing later: *"which **sectors** have borrowers with rising PD?"* asks for
sectors, and the borrowers are the condition on which sectors qualify.

A **breakdown** does not outrank an entity noun: "the ten largest customers by
sector" is a question about customers however it is grouped.

## Governed metadata, not a synonym table

Dimensions come from the installation's own vocabulary and are matched on their
governed names first. `ALIASES` holds only the spellings where a credit
officer's word and the governed field name genuinely differ — `industry` →
`sector`, `stage` → `ifrs9_stage`, `product` → `product_type`. Anything a name
or alias does not resolve is resolved against the governed **concept**
catalogue, restricted to ordinal and categorical concepts, which is what lets
"rating" reach `internal_grade` without this module holding an opinion about
ratings. A dimension the installation does not govern is not a dimension,
whatever the sentence calls it.

## Where the two grains disagree, it asks

    "Show the five largest borrowers by exposure, grouped by sector."

The head noun asks for borrowers and the breakdown asks for sectors. Those are
two different tables and no single grain is both. Collapsing silently — five
sector rows under a heading promising five borrowers — is the failure this
prevents, so the reader is asked which they meant.

## The distribution contract

A distribution over a governed dimension returns **multiple category rows when
multiple categories exist**. Never a scalar.

    Rating grade · Exposure at default · Borrowers · % of exposure

A distribution that names no figure is measured by **exposure at default** —
stated on the answer, the way the governed default period is, never silent.
"Exposure at default" rather than the bare word "exposure", because that one is
ambiguous between three governed amounts and a default must not resolve an
ambiguity the product otherwise asks about.

## Concern evidence at a dimension's grain

"Which sectors concern you most?" is the **same governed methodology** asked
about a different thing. A sector has no arrears and no covenant headroom, so:

1. each of the 8 governed signals is read per facility;
2. reduced to one answer per borrower (`max`, so a borrower with the same
   problem on four lines has one problem);
3. **only then** aggregated to the sector.

Sectors are ordered by the **share of exposure carried by borrowers showing at
least one signal**, not by how many borrowers show one: a sector of two hundred
small names with one arrear each is not the one a credit committee looks at
first, and a count would put it top.

Each row carries the sector, its borrowers, how many show evidence, its
exposure, the exposure carrying evidence, both shares, the average depth of
evidence, and **one column per signal** — so the ranking can be decomposed into
the evidence behind it.

## Rolling an entity result up to a dimension

"Which sectors have borrowers with rising 12-month PD?" selects borrowers and
then reports the sectors they are in. The roll-up is appended to the plan the
shape already produced rather than composing a different one, so the sectors
reported are the sectors of precisely the borrowers the cohort selected and the
two can never disagree.

A rate does not add up: a summed column is `sum` when it is an amount and `avg`
when it is a rate or a ratio, because a sum of percentage-point movements is a
number with no unit anyone can name.

## Certified analyses follow the same contract

A certified methodology that declares a `group_by` with the requested dimension
among its **allowed values** is run with it — "which sectors deteriorated most
this quarter?" now runs ECL Movement grouped by sector and reports seventeen
sector rows rather than one portfolio bridge. The bridge components stay in the
result's `values`, so the reconciliation is inspectable either way. An analysis
that reports at a dimension's grain by construction (`stage_distribution`)
declares it on the Scope, read from the contract's own output fields.

The ECL bridge is not selected at all for a question whose HEAD noun is a
governed dimension — but "decompose the change in ECL by sector" still belongs
to it, because there the dimension is a breakdown and not the subject.

## Table first

No chart unless the question asks for one. Unchanged by this work and
re-verified with it.

## Known limitations

- **Bare "exposure" still asks which figure.** Drawn balance, exposure at
  default and committed limit are three governed amounts that differ by
  material sums, and the product asks rather than picking one. The dimension is
  read correctly either way, so answering the clarification produces the
  breakdown. This is a deliberate governed control, not a grain defect.
- **"Show rating distribution for the last ten quarters"** returns a genuine
  multi-row rating distribution at the latest published period, not a
  ten-quarter series. Period as a second grouping dimension is not implemented.
- The concern methodology at a dimension's grain requires the dimension to be
  carried by the governed source the signals are read from. One that is not is
  refused with a statement rather than joined to from somewhere else.


## A breakdown the base dataset does not carry

"Show IFRS 9 EAD by internal rating for the latest period" anchors on the
impairment run — that is the dataset the measure was matched on, and it has the
quarter the question asked for. It has no rating column. The internal grade is
one governed hop away, on the facility book.

The planner already handled this: a dimension the base cannot express is
DEFERRED, registered as something the enrichment must bring in, and the joined
column becomes the grouping. That mechanism worked in matches — the objects the
enrichment resolver reasons about — and so it could only defer a dimension that
a CONCEPT match had named.

Resolving the requested dimension from the sentence, which is what this whole
document is about, produces dimensions no concept match names: "by internal
rating" asks for a governed column without naming a measure on the dataset that
carries it. Those had nothing to hop on. The breakdown was dropped, the answer
came back as one portfolio row, and the grain postcondition — correctly —
refused to show it and asked instead.

`_dimension_match` stands a match up for such a column. It is not pretending to
be a concept the reader recognised: its confidence is zero and its reason says
it came from the requested breakdown. It exists so the governed hop machinery
can carry a governed column, which is what it was built to do.


## Known gap: a constrained field can still be ranked as a measure

"Show exposure at default for Stage 2 borrowers" ranks by the **stage** column
rather than by exposure, and returns the ten smallest exposures in the book
under a heading promising the largest.

The rule that stops a constrained field being measured — a field the question
pins to a VALUE carries the same value in every row, so there is nothing there
to measure — fires only where the question ALSO asks for a breakdown. This
question asks for none, so the rule does not fire.

Widening that guard was tried and reverted, because it trades one defect for
two worse ones:

* "How many borrowers are in Stage 2?" resolves *borrowers* to a
  connected-group size on the group book, which carries no stage column at
  all. Dropping the stage leaves the plan anchored there and filtering on a
  column it does not have.
* The two-period cohort path stops applying the stage at the grain it
  reconciles on, and a stage 1 borrower came back inside a "stage 2 or worse"
  population — a wrong answer, where the ranking bug is only a badly ordered
  right one.

The real fix is not a different condition here. `matches` currently serves two
roles at once — it names the measures AND anchors the dataset — and the rule
needs to remove a field from the first without removing it from the second.
That is a change to how a match carries its role, and it belongs with the
grain work rather than bolted onto this guard.

Until then the ordering is wrong and the population is right, which is the way
round to be wrong.


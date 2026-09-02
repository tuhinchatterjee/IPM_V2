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


## Closed: a single-period filter is not a two-period cohort

    "Which Stage 2 or worse borrowers are on watchlist?"
    "Show Stage 2 borrowers."

were both withheld. The governed runtime refused the plan:

    movements: a DERIVE needs 'columns'.
    cohort: 'closing_watchlist' is not a column available at this step.

Nothing in either sentence compares two dates. Each names a population and,
in the first, one thing that must be true of it at one date. But `_shape` read
*any* condition as a cohort, and every cohort was built by `_two_period`: an
opening scan, a closing scan, a join with a `closing_` prefix, and a DERIVE of
the movements. With no movement to derive the DERIVE was empty, the runtime
rejected it, and the columns the later steps reached for never existed.

### What decides now

`Condition.kind` already told the two apart; nothing was reading it. It does
now, in `analysis_planner`:

* `change_pct` and `change_abs` — collected as `MOVEMENT_KINDS` — genuinely
  need both ends of a comparison, and `asserts_movement()` sends them to
  `COHORT`.
* `level` and `order` are tests at ONE date. "on the watchlist", "Stage 2 or
  worse", "in Shipping", "rated BB or below" are all levels, and a question
  built only from them is planned as a single-period population.

The decision is on the kind of condition, not on the words of the question. A
level condition nobody has phrased before takes the single-period path for the
same reason these two do.

### The four things that had to follow

The shape decision alone would have produced a plan that ran and was wrong
everywhere else. Four mechanisms moved with it:

* **`_single_period` accepts conditions.** It compiles each testable one
  through the same Boolean reader the two-period path uses, emits it as a
  `tested` FILTER, and carries the tested columns into the GROUP aggregates so
  the rows on screen prove the predicate (QF-3). An untestable condition raises
  `CannotPlan` rather than being dropped.
* **A range is a range.** "Stage 2 or worse" compiles to `ifrs9_stage >= 2`,
  the ordered predicate the domain supports, not to an OR of two equalities.
  The widening is recorded on `AnalysisBuild.widened`, and the answer says "or
  worse" because the plan says `gte` — the sentence and the predicate are the
  same fact.
* **The head noun decides the grain.** A dimension the question pins to a
  value is a RESTRICTION, not a breakdown: "Stage 2 borrowers" is a list of
  borrowers, not a table of stages. `dimensions._noun` steps over pinned
  restrictions FIRST and only then cuts at the verb — cutting first would stop
  at the "or" inside "2 or worse" and lose the borrowers entirely.
* **A measure is not required.** A question that names a population and no
  figure returns a governed borrower profile — exposure, ECL, stage, rating,
  12-month PD, watchlist, early-warning status — taking each concept from its
  own governed rollup, and taking only the fields this installation actually
  carries rather than failing on the ones it does not.

### What it returns

Verified against `portfolio_facility` read directly, at Q2 2026, borrower
grain, exact identity sets:

| Question | Borrowers | Independently counted |
| --- | --- | --- |
| Show Stage 2 borrowers. | 1,167 | 1,167 |
| Show Stage 3 borrowers. | 718 | 718 |
| Show Stage 2 or worse borrowers. | 1,647 | 1,647 |
| Which Stage 2 or worse borrowers are on watchlist? | 1,647 | 1,647 |
| Which watchlist borrowers are Stage 2? | 1,167 | 1,167 |
| Which Stage 3 borrowers are not on the watchlist? | 0 | 0 |
| Which borrowers are in Shipping? | 153 | 153 |

Zero missing, zero extra, on every row. The empty answer is a real one: every
stage 2 and stage 3 facility in this book is watchlisted, so "Stage 3 and not
on the watchlist" is genuinely nobody, and the product says so rather than
implying a gap.

`tests/orchestration/test_single_period_population.py` holds all of it —
the shape decision, the range predicate, the negation, the head noun, the
profile, the base-dataset choice, and the identity sets themselves.


## Closed: a population, said out loud

The single-period answers were right and described themselves as `2`:

    Together these 10 hold 11.50% of 2 exposure at default.
    Shares are of 2 exposure, not of the whole book.
    Each row's share of 2, not of the whole book.
    2 · Q2 2026 · exposure at default, expected credit loss, IFRS 9 stage

Four surfaces, four separate `", ".join(value for _, value in filters)`
expressions, and a reader with no way to tell what the percentages are OF.
The first sentence — "1,167 customers in IFRS 9 stage 2" — was right the whole
time, because it went through a reader that knew a coded value needs its
field's name. The other four did not have one.

The rule is one function now, `scope.say` / `scope.phrase`, on the leaf module
both the frame and the narrative can reach. A coded value is named by its field
("Stage 2", "grade 7"); a value that is already a name is left alone
("Shipping"). A field nobody has phrased yet falls back to its own name rather
than to a bare digit.

The widening travels with it. `ScopeFrame` outlives the build — it is what the
next turn reads and what the payload serialises — so the qualifier is stored
beside the restriction (`{"field": ..., "value": ..., "op": "gte"}`) rather
than left behind on the plan. Without that the strip above the table said
"Stage 2" over rows the sentence below correctly called "Stage 2 or worse".

One figure also had two values on one screen: the prose rounded the covered
share to two decimals and the evidence card to one, so 8.65% in the sentence
sat beside 8.60% in the figure. Both are two decimals now.

`tests/orchestration/test_spoken_filters.py` covers the naming rule, both
filter shapes, the qualifier's survival through serialisation, and a mechanism
check that no caller has gone back to joining raw values.


## Still open: which end of the window a cohort filters on

    "Which Stage 2 or worse borrowers had rising PD?"

first asks *"Over which horizon? Twelve-month and lifetime PD are different
measures, and IFRS 9 uses each in different stages."* That is correct: the
sentence is genuinely ambiguous between two governed measures. Answering
"12-month PD" resumes the original question with the population, the stage
condition, the period context and the borrower grain all intact.

The population it returns is **740**, and that is the count of borrowers who
were Stage 2 or worse at the OPENING period. Read at the closing period it is
939. Both are defensible readings of the English; the answer does not currently
say which one it used, and it should. The static filter is applied at the
opening scan because that is where the cohort establishes its membership, and
changing it is a change to what a cohort MEANS rather than a formatting fix —
so it is recorded here rather than adjusted quietly.

Separately, the interpretation for "Which borrowers were downgraded?" still
logs `Ungrounded figure(s) ['51']`. That predates this work and reproduces
identically at the baseline commit; it is not a regression from the change
described above.


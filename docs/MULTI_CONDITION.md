# Multi-condition query execution

How CreditProbe reads `A AND B`, `A OR B`, `A AND NOT B` and
`(A AND B) OR C`, executes every part of it, and proves it did.

---

## The defect this fixes

    "Which customers were downgraded and had expected credit loss rise?"

returned every customer whose ECL rose — 1,760 borrowers — under a heading
quoting both conditions. The downgrade condition was read, resolved to
`customer_ratings.internal_grade`, and then disappeared before the plan was
compiled.

That is the worst shape of error an analytical product can produce. A wrong
number invites a second look. A right number about the wrong population does
not: the borrowers are real, the ECL movements are real, the table is
internally consistent, and the only way to catch it is to already know the
answer.

### Root cause

`semantics.movement_near` masks a concept's own matched phrase out of the
clause before it looks for a direction word. The rule is right and load-bearing
— "probability of credit *deterioration*" is the NAME of twelve-month PD, and
reading its "deterioration" a second time as an assertion turned a request for
a ranking into a cohort of everyone whose PD rose.

But "downgraded" is a phrase that IS the movement. The rating concept's pattern
matches `downgrad\w*` because that is how a credit officer names the rating in
that sentence; the mask then blanked out the only evidence of a direction;
`find_movement` returned `None`; `condition_for` correctly declined to invent a
comparison; and the condition was never built. No leaf, no predicate, no
`FILTER` clause — and nothing anywhere in the pipeline noticed that a condition
the question stated had gone missing.

The fix is a discriminator, not a removal of the mask
(`semantics.phrase_asserts_movement`): a movement word accounts for the WHOLE
phrase once ordinary filler is stripped → the phrase is an assertion; it is one
word inside a longer noun phrase → the phrase is a name, and the mask stands.

---

## The predicate tree

`backend/orchestration/predicates.py`

Filter logic is an explicit tree rather than a flat list of conditions that a
later step is trusted to combine:

```
AND
├─ rating_downgraded          (internal_grade change > 0, ordinal, higher is worse)
└─ ecl_increased              (total_ecl change > 0)
```

Four node kinds — `AND`, `OR`, `NOT`, `TEST` — and three leaf kinds:

| leaf kind    | what it tests                          | example              |
|---|---|---|
| `movement`   | how a measure moved across the window  | ECL rose             |
| `level`      | which side of a line it is on now      | 12-month PD above 5% |
| `membership` | a governed dimension value             | IFRS 9 stage is 2    |

A governed value filter is a leaf like any other. Carried in a separate list —
as it was — nothing could see a membership and a movement together, so nothing
could express "Stage 2 AND NOT on watchlist".

### Reading the structure

Built from the question's own connectives by a small recursive parser:

- **OR** — `or`, `either … or`
- **AND** — `and`, `,`, `;`, `while`, `but`, `plus`, `as well as`, `along with`
- **NOT** — `not`, `never`, `without`, `excluding`, `except`, `other than`
- **grouping** — brackets, parsed at depth

`AND` binds tighter than `OR`, so `A and B or C` is `(A and B) or C` — the way
the sentence is read aloud. A negation governs what FOLLOWS it, not the whole
fragment: "Which Stage 2 borrowers are not on watchlist" asserts Stage 2 and
denies the watchlist, and negating the fragment whole asked for borrowers who
were neither.

Two properties matter more than the grammar:

1. **No connective is invented.** A one-condition question produces a one-leaf
   tree and exactly the plan it produced before this module existed.
2. **No leaf is dropped.** A test the sentence structure cannot place — an
   inherited filter naming no words in this turn — is conjoined at the top
   rather than discarded.

### Compiling it

| tree shape        | FILTER params | why |
|---|---|---|
| pure conjunction  | `where: [...]` | the flat list every existing plan, Trace and test already reads |
| anything else     | `expression: {...}` | a list the runtime ANDs together cannot carry an OR or a negation |

The expression is a tree of typed `Expr` nodes, so every value from the question
reaches DuckDB as a bound parameter and never as text.

---

## Cross-domain joins

The conditions in the live question live in two datasets, and the answer grain
is a third thing again:

| condition | governed source | grain |
|---|---|---|
| rating downgrade | `customer_ratings.internal_grade` | customer, annual cycle |
| ECL increase | `ifrs9_staging.total_ecl` | facility, quarterly |
| answer | — | **customer**, Q2 2025 → Q2 2026 |

The plan the runtime executes:

1. resolve the opening and closing periods (governed default: the latest year);
2. read each period's frame from `portfolio_facility`;
3. join `ifrs9_staging` at facility grain, **before** the roll-up;
4. reconcile to the customer grain, aggregating each measure by the rule its
   concept declares — so a customer with four facilities counts once;
5. as-of join `customer_ratings`, **after** the roll-up, under the governed
   `latest_on_or_before` rule with `completed_year_of_quarter`: Q2 2026 reads
   the 2025 cycle, because the 2026 one had not finished;
6. join the closing frame onto the opening one on `customer_id` alone;
7. derive `..._change` for each measure — never for a category or a state;
8. apply the predicate tree;
9. sort, limit.

Rating movement is measured on the **governed ordinal scale** (1–10, ten being
default), never by comparing grade labels alphabetically. `Concept.is_ordinal`
is what makes "downgraded" mean `change_abs > 0` on that scale.

### Grain

The requested answer grain is chosen first; every other source is brought TO
it. A many-to-one source is rolled up before it is joined, never after, and the
plan records that as an explicit `RECONCILE_GRAIN` / `AGGREGATE_BEFORE_JOIN`
step rather than as an implicit consequence of join order — "rolled the
covenant table up to facility level so the join could not multiply it" is a
reviewable statement; "grouped by account_id" is not.

### The retrieval window is not the join graph

`context.relationships` is a RELEVANCE window — the joins between the eight or
so datasets the retriever surfaced for one phrasing. Resolving the join path
over that window meant

    "Which borrowers have (rising 12-month PD AND rating downgrade) OR Stage 3?"

was refused with *"CreditProbe cannot join ifrs9_staging to portfolio_facility:
no active relationship connects them"* — about a relationship the installation
declares and uses every day — while the same question phrased more plainly was
answered. `_relationship_rows` now resolves over the full governed graph. Which
datasets the plan needs is decided by the concepts it resolved; a prompt budget
has no business deciding it.

---

## The condition coverage gate

`backend/orchestration/gate.py`

Before an answer is shown, the conditions REQUESTED are compared with the
conditions the compiled plan EXECUTED.

The comparison reads the plan, not the reading. A gate written against the
semantic reading is worthless here: the reading understood both conditions and
the answer was still wrong. `gate.enforced_columns` walks the `FILTER`
operations in the plan that is about to run — both the flat predicate list and
the expression tree — and reports the columns genuinely tested.

Four checks, each with a yes-or-no answer:

| check | catches |
|---|---|
| tree leaves vs `FILTER` columns | a predicate built and then not applied |
| a directed clause with no governed concept | "worsening liquidity" resolving to nothing |
| a negation in the sentence, none in the plan | "NOT on watchlist" ignored |
| an explicit either/or, no disjunction in the plan | "either A or B" flattened |

**Repair first, then state the limitation.** Everything the gate found in this
work was repaired at the mechanism — the movement reader, the vocabulary, the
join graph. What remains genuinely unavailable is named in the person's own
words:

> CreditProbe could not apply collateral coverage below 50% to the governed
> data, so this condition was not used to select the population. The rows meet
> the remaining conditions only.

---

## No false interpretation claims

The answer used to say

> Each condition was tested on the same joined population, so the count is the
> intersection rather than the sum of three lists.

composed from the READING. It therefore claimed every condition had been TESTED
whenever every condition had been UNDERSTOOD — which is precisely the sentence
that appeared above a population selected on one condition of two.

Every sentence describing the population is now composed from
`Enforcement.logic` — the executed predicates, combined the way the plan
combined them. Three consequences:

- a condition that did not run is not named as though it had;
- a disjunction is read back with "or", never as a list that implies "and";
- a negation is read back as a negation.

The post-result invariant follows the same rule. Checking that every row
satisfies every condition is only valid under a conjunction; under an OR it
fails the rows that met the other branch, and a correct answer was withheld
with a message saying it contradicted the question. A non-conjunctive plan is
checked with a single `predicate_tree` invariant that evaluates the tree per
row.

---

## The answer

Table first. No chart is proposed for a list of borrowers to act on.

| # | column | source |
|---|---|---|
| 1 | Customer / Borrower | identity |
| 2 | Internal rating at opening | as-of rating cycle |
| 3 | Internal rating at closing | as-of rating cycle |
| 4 | Change in internal rating | derived (notches) |
| 5 | Expected credit loss at opening | `ifrs9_staging`, summed to customer |
| 6 | Expected credit loss at closing | same |
| 7 | Change in expected credit loss | derived |
| 8 | IFRS 9 stage at closing | carried |
| 9 | EAD at closing | carried |
| 10 | Sector, Region, Segment | carried context |

A measure's opening, closing and change columns are kept together: the
compiler emits every opening value, then every closing value, then every
change, which puts a borrower's opening rating eight columns from its closing
one when the pair is the whole point. An attribute that cannot move over the
window — sector, region, segment — is shown once, not twice.

---

## Verified against the data

`docs/MULTI_CONDITION.md` is not the evidence; this is. The exact live question
was run against the populated synthetic book and checked against the source
tables, read independently and paired by hand:

```
HEADLINE: 262 customers where internal rating was downgraded and ECL rose,
          between Q2 2025 and Q2 2026.

12 sampled returned rows, checked against customer_ratings and ifrs9_staging:
  SA-101764  grade 3->4 downgraded=True | ECL 0.0487->0.0501 rose=True   OK
  SA-102227  grade 7->8 downgraded=True | ECL 1.7280->3.0469 rose=True   OK
  ... 10 more, all OK
  violations: 0

exclusions:
  296 borrowers downgraded with no ECL rise  — none returned
  1,498 borrowers whose ECL rose without a downgrade — none returned

independently computed intersection: 262
CreditProbe reported:                262   MATCH
```

The independent check derives the rating in force from the governed rule the
plan DECLARES (`completed_year_of_quarter`), written out separately rather than
read off the answer, so the check exercises the rule and not the output.

---

## What is still open

1. **Three of the thirteen cases stop to ask, and that is unchanged
   behaviour.** "Which borrowers had PD increase and were downgraded?" is met
   with *"Over which horizon? Twelve-month and lifetime PD are different
   measures."* The same clarification fires on the single-condition question,
   so it is the pre-existing PD-horizon ambiguity gate rather than anything
   multi-condition; naming the horizon answers both conditions correctly. It
   was left alone: relaxing it is a change to the clarification policy, not to
   condition execution.

2. **The core credit book has no collateral coverage RATIO.** It publishes
   `collateral_value` (an amount) and no coverage percentage;
   `collateral_coverage_pct` exists only on the Borrower 360 book, which is a
   different portfolio on different identifiers. "Collateral coverage below
   50%" used to resolve to the amount and test it against 50 — a condition that
   looks applied and tests the wrong thing. The phrase is now excluded from the
   collateral concept, so the gate reports it as unavailable. Deriving coverage
   as `collateral_value / ead` would answer it properly and is not in this
   change.

3. **Monetary figures are labelled `SAR mn`, not SAR.** The concept units
   declare `SAR mn` throughout, and `customer_ratings` carries an explicit
   `revenue_usd_mn` column, so the reporting currency looks deliberate — while
   the book is Saudi and `corporate/universe.py` gives facilities a currency mix
   of 78% SAR. Which is the reporting currency is a data-model decision, not a
   multi-condition one, and it was not changed here on a guess.

4. **`liquidity_buffer` had no governed relationship.** It was registered as a
   dataset without a join, so every question combining liquidity with anything
   else was refused. One `ShippedRelationship` was declared
   (`liquidity_buffer.customer_id → borrower_financials.customer_id`,
   one-to-one) and seeded. The external-intelligence domain has the same shape
   of gap and is not touched here.

# Query fidelity, product self-knowledge and the Early Warning methodology

> **The answer COMPOSITION described below has been replaced.** The four
> defects in this document and their fixes are unchanged and still hold. How
> the product-knowledge answers are selected, shaped and sized is now
> `docs/PRODUCT_ANSWER_EXPERIENCE.md`: this document's answers were accurate
> and unreadable.

Four release-blocking defects from live Mac acceptance, and what was changed at
the mechanism for each.

---

## The four defects

| # | Question | What happened |
|---|---|---|
| 1 | "…had expected credit loss rise **in Q1 2026**?" | compiled to `total_ecl_change > 2026.0` — an empty population that reads as a finding |
| 2 | "Which customers were **downgraded**…" | rows claimed a downgrade that the displayed ratings did not prove |
| 3 | "Which **Shipping** borrowers have rising utilisation, worsening liquidity and increasing 12-month PD?" | answered with an exposure-at-default movement for Transport & Logistics |
| 4 | "What is **CreditProbe AI**?" | "CreditProbe has no governed data about CreditProbe AI." |

Defect 3 was already fixed by the multi-condition work in `b53c79c` and was
confirmed still correct before anything was changed here; a regression test now
holds it. Defects 1 and 4 reproduced exactly. Defect 2 did not reproduce on the
current tree — every displayed row proved its downgrade — but the guarantee was
an accident of the data rather than a property of the system, so an invariant
now enforces it.

---

## 1. A period is a type, not a number

### Root cause

`semantics.find_movement` locates the direction word ("rise"), then reads the
first number after it as the size of the movement. In

    …had expected credit loss rise in Q1 2026

the first number after "rise" is `2026`. The existing guard only recognised a
number followed by a time UNIT ("6 months"); it had no notion that `2026` is
itself a date.

The failure is worse than a crash. The plan validates, the query runs, the
invariants pass, and the population is empty — and an empty population reads as
a finding. "No borrower deteriorated that way this quarter" is a sentence a
credit officer might well believe.

### The fix

`backend/orchestration/temporal.py` — a typed reader that finds every temporal
expression and **masks it out before any magnitude is read**. Masked rather
than deleted, so offsets a caller already holds still point where they did.

Recognised: quarters (`Q1 2026`), years (`2026`, `FY2026`, `CY 2026`), months
(`March 2026`, `2026-03`), halves, spans (`between Q1 2026 and Q2 2026`),
relative windows (`the last four quarters`, `year on year`, `this quarter`,
`over the next 12 months`, `since 2024`).

Two rules keep it from over-reaching:

- **Measure names are reserved first.** `12-month PD`, `lifetime PD`, `IFRS 9`,
  `Stage 2` and `Basel III` are claimed before any date shape can take their
  digits.
- **A bare four-digit number is a year only inside a calendar window**
  (1990–2100). `exposure above 2500` keeps its threshold.

Both `find_movement` and `find_threshold` now read the time-free text.

```
"ECL rose more than 20% in Q1 2026"  ->  threshold 20%, window Q1 2026
"ECL rose in Q1 2026"                ->  threshold  0,  window Q1 2026
"ECL above 2026"                     ->  no threshold at all
"exposure above 2500"                ->  threshold 2500
```

Live: `293 customers where internal rating was downgraded and ECL rose, between
Q4 2025 and Q1 2026` — the named quarter became the closing period, as it
should have from the start.

---

## 2. Rows must prove their predicates

`invariants._from_positions` emits a `position_movement` check for every
executed movement predicate on a two-period plan. It compares the **opening and
closing positions on the screen**, not the derived `..._change` column the plan
filtered on — a check against the filter column can only ever agree with
itself.

For a rating this means `closing_internal_grade > opening_internal_grade` on
the governed ordinal scale. Percentage movement is never accepted as evidence
of a downgrade: an ordinal grade has no meaningful percentage change, and the
only proof of a downgrade is the two grades.

The answer table carries `Internal rating at <opening>`, `Internal rating at
<closing>` and `Change in Internal rating`, adjacent, so a reader can check the
claim without opening the Trace.

---

## 3. The planner may change implementation, never objective

### Root cause

Nothing held the ORIGINAL request. The condition-coverage gate compares the
predicates the reading produced against the predicates the plan applied — and a
plan that abandoned the question entirely has no predicates to be missing. A
sector movement analysis for the wrong sector passes every check the system
had.

### The fix

`backend/orchestration/fidelity.py` records a `Contract` before planning
begins: the question, the population it named, the predicates, the measures,
the ranking, the period, and the **analytical objective** — what KIND of answer
it wants.

| Objective | Means |
|---|---|
| `population` | which borrowers meet the stated conditions |
| `ranking` | the largest or worst by a named measure |
| `aggregate` | a total, or a breakdown of one |
| `movement` | how a measure moved between two dates |
| `association` | whether two measures moved together |

`compare()` then checks the finished plan against it:

- **objective changed** — a population question answered as a movement
- **population lost** — the question named Shipping, the plan restricted to
  something else or to nothing
- **period moved** — the question named Q1 2026, the plan measured elsewhere
- **predicate invented** — the plan filters on something nobody asked for

Narrowing is not a divergence. A population question answered as a *ranking of
that population* is faithful, because ordering is presentation.

The population is read from the question against the governed dimension
vocabulary, not only from the semantic reading — a contract that only works
when a reading was produced cannot check a plan that ignored the question.

Live: the Shipping question returns 57 borrowers, three predicates enforced
across three datasets, `objective wanted: population | ran: population |
faithful: True`.

---

## 4. CreditProbe can explain itself

### Root cause

Every question went to the borrower-data planner. A question about the product
found no dataset about the product, and the planner said so — correctly, and
uselessly.

### The architecture

```
backend/product/
  knowledge.py     18 capabilities + 3 architecture layers, each with a
                   curated narrative AND a live evidence reader
  methodology.py   the four Early Warning layers as a mapping over the eight
                   governed signal families; the signal catalogue; TAC
  answers.py       31 tools composing text-and-table answers, no model call
  routing.py       product intent vs data intent
```

**Nothing here is invented per call.** Each capability carries reviewed prose
*and* a function that counts what this installation has right now — 9 domains,
77 datasets, 23 declared relationships, 324 certified methods, 43 Early Warning
signals. A product answer quotes the installation, not a brochure.

**Reconciliation tests fail the build** when the registry and the running
system disagree: a capability naming a feature-matrix area that no longer
exists, a dataset count that has moved, a signal family the engine evaluates
that no layer of the methodology mentions.

### Routing

The hard part is that "Early Warning", "Borrower 360", "Trace" and "Data
Builder" are the names of product modules *and* the subjects of portfolio
questions. Keyword matching routes half of them wrongly.

What separates them is the verb and the shape. A product question asks what
something IS, DOES, or why it MATTERS. A data question asks WHICH, HOW MANY or
HOW MUCH — of borrowers, sectors, periods and amounts.

So the data test runs **first** and wins ties: a question naming rows, a
borrower identifier or a dated period is a data question whatever product nouns
it also contains.

```
"What is Early Warning?"                    -> product
"Which borrowers are on the Early Warning list?" -> data
"Which signals are firing for SA-100014?"   -> data
"What signals are used for liquidity risk?" -> product, narrowed to the
                                               liquidity family
```

All 36 product questions and 9 data questions in the acceptance set route
correctly.

### No charts

Every product and methodology answer declares `visualization.kind = "none"`.
A question about what a module does has no quantitative shape, and a bar chart
of feature counts is decoration pretending to be analysis. Flows are rendered
as text steps.

---

## The Early Warning methodology

### Four layers over eight governed families

The remediation asks for a four-layer framework. The project's authority is
`taxonomy.FAMILIES`, which has **eight** signal families. These are not
competing taxonomies — the layers are credit-risk *perspectives*, the families
are the governed grouping of signals — so the layers are defined as a **mapping
onto the families**, and the mapping is written down.

| Layer | Governed families | Signals |
|---|---|---|
| 1. Borrower fundamentals and financial health | financial, leverage, liquidity | 22 |
| 2. Credit behaviour, facility and structural risk | behavioural, covenant, collateral | 12 |
| 3. Credit quality, IFRS 9 and ratings | rating, ifrs9 | 9 |
| 4. External, sector, macro and network intelligence | *(none configured)* | 0 |

**Layer 4 is honest rather than empty by oversight.** The External Intelligence
domain is published, carries 10 datasets, and the Ask path reads it — a
borrower's story shows which external conditions are live for its sector. But
**no Early Warning signal is configured against it**, so no borrower is
promoted to a Risk Case by an external condition alone. The methodology answer
says exactly that. Configuring signals there is a Data Builder and Credit Risk
Analytics decision, not a code change.

A reconciliation test asserts `unmapped_families() == ()`: a family the engine
evaluates and the methodology does not mention would be a signal firing into an
explanation that denies it exists.

### The signal catalogue

**43 governed signals**, each carrying: family, layer, label, business meaning,
source dataset, source fields, grain, frequency, test, threshold, unit,
direction of deterioration, severity, threshold owner, version, and the
threshold read back as a sentence.

**Frequency is read from the data, never asserted.** All 43 signals read
`corporate_borrower_360`, which publishes 16 **quarterly** periods, so every
signal's frequency is Quarterly. A test asserts no signal claims a frequency
its source does not publish — §14's "do not claim daily frequency if the
available data is quarterly", enforced rather than promised.

Grain: one row per borrower per reporting period.

### Warning language

Engine wording ("fired", "still firing") describes a rule evaluating. A credit
officer wants to know what the borrower is doing:

| State | Means |
|---|---|
| New warning | crossed its threshold this observation period, having been within it last |
| Persistent warning | beyond its threshold in **both** the current and previous observation periods |
| Worsening warning | already beyond, and further beyond than last period |
| Improving | still beyond, but moving back toward the threshold |
| Resolved | beyond last period, within it now |

A test asserts every state names its observation periods, because a state that
does not say which periods it compares cannot be checked by the person reading
it.

### The flow

```
Data signal -> Threshold / change detection -> Persistence / materiality
-> Cross-domain evidence -> Severity assessment -> Risk Case
-> AI investigation -> Credit action / review
```

---

## TAC — not defined, not invented

**TAC does not appear anywhere in this repository.** Searched:

- every Python module under `backend/` and `scripts/`
- every Markdown document under `docs/`
- every TypeScript and TSX module under `frontend/src/`
- JSON, YAML and PowerShell configuration
- the Early Warning taxonomy, engine, severity and case modules
- the full commit history

Zero occurrences of the token, in any casing.

§13 is explicit: *"If TAC is not formally defined anywhere in the repository,
STOP only that specific methodology implementation, record that the definition
is missing, and do not fabricate an acronym."*

So `methodology.tac()` reports `status = "not_defined"`, the answer states what
was searched, and it offers what CreditProbe *does* implement — the four-layer
framework, the severity model and the case-promotion rules. A test asserts the
answer proposes no expansion of the acronym.

Supply the methodology paper, policy document or specification that defines TAC
and it can be published as a versioned methodology alongside the four-layer
framework, with the same reconciliation tests.

---

## What is still open

1. **"Which borrowers had PD increase and were downgraded?" stops to ask.**
   The PD-horizon clarification ("twelve-month or lifetime?") fires identically
   on the single-condition question, so it is the pre-existing ambiguity gate
   rather than anything multi-condition. Naming the horizon answers both
   conditions correctly. Changing it is a clarification-policy decision, out of
   scope here.

2. **Layer 4 has no configured signals.** Reported in every methodology
   answer rather than hidden. Configuring external signals needs a threshold
   owner's decision.

3. **Monetary units are declared `USD mn` in the concept map** while the Early
   Warning taxonomy declares `CURRENCY = "SAR"`. The two disagree. This is a
   data-model decision — `customer_ratings` carries an explicit
   `revenue_usd_mn` column, so the USD reporting basis may be deliberate — and
   it was not changed on a guess. It is the same finding recorded in
   `docs/MULTI_CONDITION.md`.

4. **No live model was called.** Every product and methodology answer is
   composed deterministically; that is the design, not a limitation. The
   analytical answers ran against the governed engine with no provider
   configured.

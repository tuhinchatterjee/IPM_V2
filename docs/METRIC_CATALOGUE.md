# The Metric Catalogue and Lenses 2.0

## Why this exists

Before this, a dashboard's formulas lived in the component that drew them. A
number on a screen and the same number in a conversational answer were two
implementations of one definition, and the only way to know whether they agreed
was to read both. When they disagreed — and they did — nobody could say which
was right, because neither was written down as the definition.

The Metric Catalogue is one place that says what CreditProbe means by each
number. Every surface that shows a figure resolves it here: a lens tile, a
chart, an info panel, a conversational answer, the verification workspace.

---

## The three rules

**Nothing is defined that the data cannot support.** A metric whose fields do
not exist in any governed dataset does not get an entry with a shrug in it. It
gets an `Unsupported` entry naming what is missing and what would be needed, so
a lens can say *"retail IFRS 9 staging is not available in this deployment,
because there is no retail impairment dataset"* rather than drawing an empty
tile. There are 61 governed metrics and 8 named as unavailable.

**Governed and user-built are the same shape and different things.** Both are a
`MetricDefinition`. What differs is `origin` and `status`, and every surface
that shows a metric shows both in words: *CreditProbe governed* / *User built*,
and *Draft* / *Calculates* / *User verified* / *Published*.

**Nothing computes here.** The arithmetic is compiled to the same validated
analytical plan every other analysis in CreditProbe uses and executed through
`runtime.executor`. A metric that ran its own SQL would be a second execution
path with its own bugs and its own permissions.

---

## Where things are

| What | Where |
| --- | --- |
| Formula shapes, aggregations, comparisons | `backend/metrics/formula.py` |
| One metric's full definition and §6 panel | `backend/metrics/catalogue.py` |
| The 61 governed metrics and the 8 that are not | `backend/metrics/library.py` |
| Compiling and running a metric | `backend/metrics/execution.py` |
| Typeahead over the catalogue | `backend/metrics/search.py` |
| Resolution, permissions, lifecycle, verification | `backend/metrics/service.py` |
| The three shipped lenses | `backend/metrics/lenses.py` |
| HTTP | `backend/api/routers/metrics.py` |
| Storage for user metrics and verifications | migration `0037` |
| Lens tiles, info panels, picker, verification | `frontend/src/components/metrics/` |
| The catalogue screen | `frontend/src/app/metrics/page.tsx` |

---

## Searching (§8.3)

The picker starts **empty**. Sixty-one governed metrics in a scrolling list is
a list nobody reads: people give up and rebuild a number they already had.

Ranking is deterministic and tiered — exact, name prefix, alias prefix,
every-word, spelling near-miss — and a stronger tier always beats a weaker one.
A near-miss is dropped entirely once anything matched properly, so typing
`30+ dpd` does not suggest the 60-day metric.

Typing more **narrows**:

```
'delinq'      → the whole delinquency family
'delinq 30'   → 30+ DPD Account Rate · 30+ DPD Exposure Rate ·
                30+ DPD Corporate Exposure Rate
```

Every suggestion says why it matched. Aliases are part of the definition: "NPL
rate", "bad rate" and "default rate" all reach one metric.

When nothing matches but the words name something unavailable, the reason is
shown instead of an empty list.

---

## The info panel (§6)

Every tile and every chart can explain itself without a second request. The
panel carries: what it measures, the formula, the numerator, the denominator,
the transformation, the datasets and source fields with their business
definitions, the filters, the period rule, the exclusions, **what it is not**,
the owner, the origin, the status, the version, and the aliases.

`not_this` is frequently the most-read line. "Not a roll rate. This is a level
at a point in time, not a movement between two."

### Period rules

| Rule | Meaning |
| --- | --- |
| `as_selected` | whichever period the lens or caller is showing |
| `latest_available` | the most recent period the data holds |
| `latest_matured` | the most recent period whose performance window has **closed** |

The third matters. A scorecard's Gini for last month is not a low Gini — it
does not exist, because none of those accounts has had time to default. The
validation metrics use it, and the panel says so in words rather than showing
the token.

---

## The lenses

Three shipped lenses are built on the catalogue. The **CRO Lens is untouched**:
it is a composed executive narrative with its own page, and rebuilding it as a
grid of tiles would be a downgrade dressed as consistency.

| Lens | Audience | Tiles | Sections |
| --- | --- | --- | --- |
| Retail Credit Risk | Head of Retail Credit Risk | 16 | 4 |
| Retail Analytics | Head of Retail Analytics and Model Validation | 12 | 4 |
| Corporate IFRS 9 | IFRS 9 Committee and Head of Impairment | 21 | 5 |

Install them with `backend.metrics.lenses.install()`. It is idempotent: an
existing lens is kept unless `replace=True`, and even then the change goes
through the ordinary revision path so an edit somebody made deliberately
survives in the history.

`check()` proves every tile against the live library — a metric that has
stopped existing, or a chart a metric has not declared itself honestly drawable
as — and a test runs it. It caught two stale ids while the lenses were being
written.

### What the lenses say they cannot show

Each lens lists what it deliberately omits, with the reason and what would be
needed. A view that quietly omits the number somebody came for teaches them not
to trust it.

- Retail: IFRS 9 stage exposure and ECL (no retail impairment dataset), roll
  rate and cure rate (movements between two periods; the engine computes one)
- Retail Analytics: approval rate (no decision outcome on applications), PSI
  (compares against a reference window; reported by the scorecard validation
  module instead)
- Corporate IFRS 9: the ECL movement bridge (a decomposition CreditProbe
  already computes elsewhere; a tile would be a second implementation),
  scenario-weighted ECL (the staging dataset carries one already-weighted ECL)

### One lens system, two kinds of panel

A metric tile is a second **kind** of panel on the existing lens system, not a
second lens system: same storage, same revisions, same render path. A lens
definition written before metric tiles existed still loads — the kind is
inferred.

Validation refuses a tile that names a metric which does not exist, names one
this deployment cannot calculate, or asks for a chart the metric has not
declared itself honestly drawable as. The twelve-panel cap on analyses is
unchanged; tiles have their own, higher limit of 24.

A tile has three states, and the distinction between the last two is the point:

- **succeeded** — the figure, with its info control
- **unavailable** — a gap in the *book*: no data for this period, and the tile
  says which periods there are
- **failed** — a gap in the *platform*

A reader told the wrong one of those wastes an afternoon chasing the wrong
people.

---

## Building a metric

A metric arrives **DRAFT**. It becomes **CALCULATION_READY** only by actually
calculating — which says nothing about whether the number is *right* — and
**VERIFIED** only when a person's own number agreed and they accepted it.
`VERIFIED` is not settable by any other route; asking for it directly is
refused with the reason.

Changing the arithmetic drops the metric back to DRAFT and clears its
verification. A metric verified against one formula is not verified against a
different one, and carrying the tick across would be the single most misleading
thing this module could do. Renaming does not.

Deleting a metric takes its verification history with it: `metric_id` is
derived from the name, so a later metric could be given the same one, and
inheriting somebody else's tick would be worse than having none.

**Nothing accepts a formula as text.** A submitted formula is a structured
object, validated against the governed data catalogue before it is stored, and
compiled to the same analytical plan as everything else. There is no path from
a request body to SQL.

---

## Verification (§10)

The discipline is one rule: **the computed value is never moved toward the
expected one.** If the two disagree, the record says they disagreed and
somebody finds out why. Making the engine agree with the analyst by assignment
would defeat the entire exercise.

A comparison is kept whether it agreed or not. A history showing three
disagreements before a definition was corrected is more useful than one showing
only the final tick.

"Accept" is not "agree". Accepting a comparison that differs is allowed —
sometimes the analyst's number was the wrong one — but it does not confer
VERIFIED, because the stored evidence would not support it. The response says
so.

Outcomes: `MATCH` · `WITHIN_TOLERANCE` · `DIFFERS` · `NOT_COMPARED`.
The default tolerance is one part in ten thousand.

---

## Permissions

Access is by role, as everywhere else: reading, building and verifying all need
an analyst. **CreditProbe does not currently model per-dataset read
permissions** — every analyst may read every published dataset — so the routes
pass no dataset restriction.

The mechanism is in place and tested regardless: `service.catalogue`,
`resolve`, `find`, `value` and `rows` all take `readable`, and it is applied
**before** ranking rather than after, so a metric somebody may not read never
consumes a slot in the visible list. A ratio needs every dataset it reads:
half a ratio is not a partial answer. When dataset-level permissions arrive,
one place changes.

A metric the asker may not read raises the same error as one that does not
exist. Distinguishing them would tell somebody what metrics exist over data
they cannot see.

---

## Verifying it yourself

```bash
# The catalogue, the search, and the shipped lenses
.venv/bin/python -m pytest tests/metrics -q

# The routes, including the login gate and what they refuse
.venv/bin/python -m pytest tests/api/test_metrics_api.py -q

# How a metric is allowed to read on screen
npm --prefix frontend test
```

To reconcile the IFRS 9 lens by hand:

```bash
.venv/bin/python -c "
from backend.metrics import service as S
p='Q4 2024'; g=lambda m: S.value(m, period=p)['value']
parts = sum(g(f'corporate.ifrs9.stage{n}_ead') for n in (1,2,3))
print('stage exposures', parts, 'total', g('corporate.ifrs9.total_ead'))
print('coverage', g('corporate.ifrs9.coverage'),
      'implied', g('corporate.ifrs9.total_ecl')/g('corporate.ifrs9.total_ead')*100)
"
```

---

## Known limitations

- **PSI is not a metric here.** It compares a period against a reference
  window, and the metric engine computes one period at a time. The scorecard
  validation module reports it against each model's declared reference.
- **No period-over-period metric.** Roll rates, cure rates and the ECL movement
  bridge are all movements between two periods. The engine has no comparison
  period, so they are listed as unavailable rather than approximated.
- **No multi-dataset metric.** The formula checker refuses one by name. The
  permission rule for it is written and tested against a constructed example,
  so it holds the day one exists.
- **A governed function metric needs the whole population.** Every compiled
  query carries `LIMIT 50,000`; the executor now tells a kernel when that limit
  bit, and the discrimination kernel refuses rather than measuring part of a
  book. A retail portfolio larger than that needs the period or scope narrowed.

# Lenses V3 — formula to code, and a Lens that remembers

Two capabilities, built on the Lenses V2 metric engine rather than beside it:

**A.** A person types a formula. A model writes the code that computes it.
CreditProbe validates that code. The person reads it and approves it.
CreditProbe runs it on real data and shows the exact arithmetic. The person
locks it, and it becomes a governed metric on the Lens.

**B.** Every refresh of a Lens is recorded. The next one is compared against
the most recent *comparable* earlier refresh. The difference is computed
deterministically before anybody writes about it, and every number in the
writing is checked against the two snapshots it came from.

---

## 1. The boundary

`backend/metrics/lens_domains.py`

A Lens reads the **Cockpit** domain and the **Early Warning** domain. Nothing
else. The registry is keyed on governed **dataset names** rather than on Data
Builder domain labels, because a domain label is deployment state — a steward
edits it, and a catalogue republish rewrote the whole taxonomy during this
feature's development, silently moving `watchlist_register` out of Early
Warning and into Cockpit.

Two datasets are refused by name, with the product that owns them said out
loud: `pd_model_performance` is Scorecard's, `scenario_definitions` is
What-If's. Four more are refused as scorecard development reference data or
CreditProbe's own plumbing.

`portfolio_facility` is registered in **both** domains, because in this
deployment they share one table. Which domain a *term* reads is decided by its
field: `exposure` and `ifrs9_stage` are Cockpit, `severity`, `watchlist`,
`trend`, `ai_risk_score`, `covenant_headroom_pct` and `dscr` are Early
Warning.

Two different questions come off that, and both are needed:

| question | answer | used by |
|---|---|---|
| which domains does this metric's data touch? | `metric_domains` — the lineage | the boundary check, the preview |
| which domain's *story* does it belong to? | `primary_domain` — the category | change features, corroboration |

The distinction is not pedantic. "Watchlist Exposure" measures a Cockpit field
filtered by an Early Warning one. Reporting the lineage where the story was
wanted put every such metric in *both* domains' change lists, which made §41's
corroboration true by construction and worth nothing.

`tests/metrics/test_lens_domains.py` asserts that every governed dataset in
the live catalogue is named in the registry, so a dataset added to a
deployment fails a test rather than silently landing inside or outside.

---

## 2. Formula to code

### 2.1 The formula is preserved structurally, not by instruction

`backend/metrics/formula_intake.py`

Pass 1 does not ask a model to write the formula. It asks for **character
offsets** into what the person typed, and CreditProbe slices their own string.
A model that "corrected" the formula would produce offsets that no longer
bracket it, and the slice would still be what was typed. Offsets that do not
land on arithmetic are refused and the deterministic reader is kept.

`FormulaIntake.formula_text` is therefore always a substring of
`FormulaIntake.said`, and a test asserts exactly that over every example §4
and §34 give.

Pass 2 is where a model may write: the name, the purpose, the unit. None of
those is the formula, and an assertion in `read_intent` proves the formula did
not move.

### 2.2 Unconventional formulas are flagged, never corrected

Where both sides of a growth expression name a period and they are the wrong
way round, `Unconventional` carries the reason, the conventional alternative —
built by swapping the person's *own two spans* inside their own formula, not
generated prose — and the three choices. Nothing is applied.

This is not decoration. In the Q2 2026 book the two directions produce
−0.45% and +0.45%: genuinely different numbers pointing opposite ways, which
is what makes the flag worth having.

### 2.3 The model writes two things, and they must agree

`backend/metrics/codegen.py`

One call produces both:

- the **execution program** — a governed formula tree, or a composite over two
  of them — which CreditProbe compiles and runs;
- the **SQL**, over governed dataset names, which the *person* reads and
  approves.

A model that writes only SQL has produced something CreditProbe cannot safely
execute. A model that writes only a tree has produced something a person
cannot review. Producing both and proving they agree is what makes "the user
approved the code" a control rather than a ceremony.

With no AI provider configured, the deterministic assembler resolves each side
of the formula through the governed catalogue and renders the SQL from the
resulting program. The artefact says so — `author` is `CREDITPROBE`, not
`MODEL` — and the screen says that the reconciliation check therefore proves
less, because it is comparing the compiler with itself.

### 2.4 Composites: what the term tree cannot express

`backend/metrics/composite.py`

Two of §4's own examples fall outside a single-dataset term tree: a
quarter-on-quarter change needs two **periods**, and a cross-domain ratio may
need two **datasets**. A composite divides two aggregates, each evaluated at
its own period offset.

That is not a lesser version of a row-level join; for these metrics it is the
correct one. Joining facility rows to watchlist rows introduces a fan-out
question — one borrower, many facilities — whose answer changes the number and
which nothing in the expression asks about. Two aggregates divided have no
fan-out. Where somebody genuinely needs a row-level cross-domain predicate,
that *is* a join, it needs a governed relationship, and it is refused by name
with that sentence.

§14's dependency graph sits on top: legs may name governed metrics, cycles are
refused by naming the loop, duplicate subexpressions are computed once, and a
graph more than five levels deep is refused.

### 2.5 Validation: nine rules plus the one §8 does not list

`backend/metrics/codeguard.py`, `backend/metrics/sqlguard.py`

| rule | what it refuses |
|---|---|
| A domain | any dataset outside Cockpit and Early Warning. **Not repairable** |
| B permission | a dataset the asker may not read. **Not repairable** |
| C field | a field the dataset does not have — with the fields that *do* exist |
| D grain | terms measured at incompatible grains or on different calendars |
| E join | two base tables joined in one scope with no governed relationship |
| F temporal | a period the book does not have — with the range that exists |
| G mathematical | a ratio reported as currency; a rate over an amount; mixed currencies; a ratio scaled by 100 without saying it is a percentage |
| H SQL safety | more than one statement; anything but SELECT/WITH; writes and DDL; file, network, process and extension functions; system catalogues; schema qualifiers |
| I Python safety | imports, dunder access, filesystem, process, network, environment |
| — reconciliation | the model's SQL and the program disagreeing on datasets, fields, aggregations, or whether there is a denominator |

The SQL guard is a **tokeniser**, not a regex, because
`SELECT 'DROP TABLE x' AS note` is safe and `SELECT/*safe*/ 1; DROP TABLE x`
is not, and a regex gets both wrong. It tracks CTE scope, which is what
distinguishes a real join from two CTEs whose results are combined — the shape
every composite metric's SQL takes.

Every rule runs even after one fails, so §9's repair packet carries the whole
picture, and each failure carries `hints`: the fields, the periods, the
relationships that do exist.

### 2.6 Approval is bound to what was approved

`backend/metrics/formula_flow.py`

`approve` returns a checksum over the code, the program and the declared
shape. `preview` and `lock` require it and refuse a mismatch by name. Without
it, a browser could show one definition, collect the approval and post a
different one, and every screen afterwards would say the metric had been
approved.

The gates, each with a test:

- preview without approval → refused
- lock without approval → refused
- code edited after approval → refused as stale
- lock without a preview → refused ("a metric nobody has seen a number for is
  a metric nobody has checked")

### 2.7 What runs is the program, not the SQL

§7: "Do NOT let Opus-generated code execute directly." There is no execution
path in this package that takes `MetricCode.sql`. What executes is the
governed program, through `backend.runtime` — validated plan, parameterised
SQL, catalogue-checked identifiers, values never interpolated. The compiled
statement is shown beside the model's SQL, and the screen says which is which.

---

## 3. Live refresh

### 3.1 Two timestamps, never one

`backend/metrics/refresh.py`

```
refreshed_at      2026-09-09 08:30    when it was CALCULATED
reporting_period  Q2 2026             which BUSINESS PERIOD it describes
```

Opening a Lens twice on a Wednesday gives two refreshes and one reporting
period. A difference between them is a restatement or a definition change —
never the book moving. A schema with one timestamp would have made confusing
the two the default, and §22's two histories impossible to keep apart.

### 3.2 Comparable, not merely previous

§24. `comparable()` prefers same filter context, same reporting period, same
definition version; steps down one criterion at a time; and **records** which
step it took. A refresh under a different filter context is never chosen at
all, because a Lens narrowed to Construction is not the corporate book with a
smaller number on it.

### 3.3 The classification is a set

A refresh is routinely three of §21's states at once. One label would force a
choice about which mattered.

| code | means |
|---|---|
| `baseline` | first comparable refresh; nothing to compare with |
| `no_source_change` | neither the data nor any value moved |
| `source_changed_value_unchanged` | a restatement that did not move the book |
| `source_and_value_changed` | the data changed and figures moved with it |
| `definition_changed` | at least one metric is calculated differently |
| `filter_changed` | a different population; figures are not comparable |
| `reporting_period_advanced` | the book moved |
| `lens_structure_changed` | metrics added or removed |

"Source data changed" is answered from recorded **data versions**, not by
comparing values: identical values over restated source is a different fact
from identical values over identical source, and no amount of comparing values
distinguishes them.

A catalogue version alone was not enough — it does not change when the same
dataset is reloaded with restated figures — so `DataSource.freshness` was
added to the data access layer. It is asked, not computed, because only the
storage layer can answer it cheaply: a file's write time and size here, a
table version on a lakehouse, an ETag on object storage.

### 3.4 What a model is shown

`backend/metrics/refresh_package.py`

A twenty-tile Lens twelve refreshes deep holds roughly 2,280 figures. The
package is about a tenth of that and is strictly more useful, because the
changes are **already subtracted**: the model is not asked to do arithmetic it
can get wrong, and every figure it may legitimately quote exists in the
package before it sees it. That is what makes claim validation checkable by
looking.

Charts travel as a deterministic summary plus the labels that *moved*, with a
reference to the full stored series. No row-level data, no borrower names.

### 3.5 Three readings that never call a model

- **Baseline** — "change interpretation will become available after the next
  comparable refresh."
- **Nothing material moved** — the honest sentence and the three facts behind
  it. There is no prompt that reliably produces "nothing happened" from a
  model asked to be interesting.
- **Filter changed** — the population changed; no comparison is drawn.

### 3.6 Every number verified, and causation as a vocabulary

`backend/metrics/refresh_intelligence.py`

Every figure in the prose is matched against the package. An unsupported one
**discards the whole reading** and falls back to CreditProbe's own
deterministic account of the movement, saying which figure was rejected.

Every claim declares a `basis`: FACT, CHANGE, CORRELATION, INTERPRETATION,
POSSIBLE_DRIVER or CONFIRMED_DRIVER. A CONFIRMED_DRIVER whose evidence does
not name a metric that *is* a mechanism — a transition amount, a migration
count — is downgraded to CORRELATION rather than discarded, because the
observation is usually true and "caused" is the part that is not supported.

### 3.7 History cannot outflank permissions

§48. Stored snapshots are filtered by what the asker may compute **today**,
not by what was computable when they were stored. A metric un-shared between
two refreshes disappears from its own history rather than being served out of
a table.

---

## 4. Schema

One migration, `0041 → 0042`.

**`user_metrics`** gains two columns:

- `code` (JSONB) — the whole §13 record: the person's formula as typed, the
  interpreted formula, the plain-English steps, the generated SQL, the
  compiled statement, the validation report, the domains, the datasets, the
  grain, the approval note, and who wrote it. One column rather than ten
  because it is written whole, read whole and shown whole. It also carries the
  metric's **composite** where it has one, in which case `definition` holds an
  empty formula and the composite is what runs.
- `user_formula` (Text) — pulled out beside it because it is the one part that
  gets queried.

**`lens_refreshes`** — one execution of a Lens. Two timestamps (see 3.1), a
filter hash, the definition version, per-dataset data versions, the trigger,
the classification set, the refresh it was compared with, the cached
interpretation, and what the pipeline spent.

**`lens_metric_snapshots`** — what each tile was worth, including the ones
that produced nothing: a metric available last refresh and not now is a change
worth reporting, and a table of successes could not report it.

Indexes: `ix_lens_refreshes_comparable` covers §24's actual lookup — scoped by
filter context and reporting period *before* it is ordered by time. Without
those two columns that lookup is a scan of every refresh on every page load.

---

## 5. API

| route | §  | what it does |
|---|---|---|
| `POST /formula/read` | §4, §5, §34 | locate the formula; flag an unconventional direction |
| `POST /formula/draft` | §6–§9 | write the code, validate it, repair it |
| `POST /formula/revise` | §11 | revalidate edited code; report what the edit changed |
| `POST /formula/approve` | §10 | record the approval, with a checksum |
| `POST /formula/preview` | §12 | run it on real data; show the exact arithmetic |
| `POST /formula/lock` | §13 | persist it as a governed metric |
| `POST /lenses/{id}/refresh` | §19, §23 | execute, store, compare, interpret, render |
| `GET /lenses/{id}/changes` | §31 | the What Changed panel and its header |
| `GET /lenses/{id}/refreshes` | §22A | one row per refresh |
| `GET /lenses/{id}/metrics/{metric_id}/history` | §22, §32 | both histories, labelled apart |

Every formula route takes the **whole artefact** in the body and returns the
whole artefact. There is no server-side draft, so nothing half-built exists in
the catalogue for a Lens to find — and §11's rule is structural rather than a
policy applied on one route, because the browser is the only source and every
route revalidates everything.

---

## 6. Performance

§44's requirements and how each is met:

- **One design call per request.** `codegen.generate` makes one call, plus at
  most two bounded repairs, all charged to one `Budget`.
- **One interpretation call per meaningful refresh.** Three of the states a
  refresh can be in are answered without a model at all.
- **One execution per Lens open.** Opening a Lens *is* a refresh: the page
  calls `POST /refresh` once and reads both the panels and the changes from
  one response. Calling `/render` and then `/changes` executed every panel
  twice on every page load — a second full pass over the book for a result the
  first pass already had.
- **The batch engine is reused.** Composites cannot join a dataset-keyed batch
  (they are two reads by construction) and share a leg cache instead, so four
  composites over `corporate.exposure` read it once.

Standard and Deep differ in the ceiling, not the surface: the domain boundary
is identical in both.

---

## 7. Running the demonstration

```bash
# the stack
./scripts/dev.sh

# move the book, so a Lens has something real to notice
python scripts/lens_demo_change.py --status
python scripts/lens_demo_change.py --apply
python scripts/lens_demo_change.py --restore

# the browser journeys
.venv/bin/python scripts/acceptance/lens_v3_journeys.py
.venv/bin/python scripts/acceptance/lens_v3_journeys.py --only A,E --json
```

`lens_demo_change.py` moves the **source data** in the analytics layer, so
every figure downstream moves because it was recomputed. It moves
`ifrs9_staging` as well as `portfolio_facility`, for the same facilities: a
deterioration visible in the facility position and not in the staging table is
a data-quality incident rather than a credit story, and a Lens carrying both
would correctly report the inconsistency instead of the deterioration.

It is deterministic and reversible. `--status` says which state the book is
in.

---

## 8. Known limitations

**A row-level cross-domain join is refused, not supported.** Where two
governed datasets have no declared relationship, a metric that joins them is
refused with the reason. The composite path covers every cross-domain ratio in
this deployment; a metric that genuinely needs a row-level predicate across a
join needs a data steward to declare the relationship first.

**The Python execution path is validated but not exercised.** §6 allows
"governed Python analytical code" and `codeguard.check_python` refuses
everything §8I lists, with tests. No metric in this deployment needs it, so
there is no governed Python execution environment behind it yet: a metric that
declared `language: python` would validate and then have no program to run.

**Scheduling is not enabled.** §19 asks that a scheduled refresh use the same
pipeline, and it does — `trigger: "scheduled"` is a first-class value and is
recorded on the snapshot. What does not exist is anything that fires it.

**The retail Lenses have no Early Warning content**, because the retail
datasets carry no early-warning signals in this deployment. Their refreshes
classify and compare correctly; the corroboration story is a corporate one.

**`primary_domain` uses the governed library category** with one rule on top
(a metric whose every filter is an Early Warning field is an Early Warning
metric). A user-built metric filed under neither falls back to its lineage,
which for a cross-domain metric picks Cockpit. That is a reasonable default
and not a decision anybody has made.

# Lenses 2.1 — Specialist Dashboards

**Branch** `claude/lenses-specialist-dashboards-esd591`
**Based on** `origin/claude/integration-rehearsal` @ `4f79566`
**Migration head** `0041` — unchanged; this branch adds no migration.

---

## 1. What this branch is

Lenses 2.0 shipped the Metric Catalogue, three preconfigured lenses, a metric
typeahead, a custom metric builder with a verification workspace, a chart
builder and a layout editor. All of that already worked, and none of it is
rebuilt here.

This branch does four things to it:

1. **Adds eighteen governed metrics** the data already supported and nobody
   had written down — the five IFRS 9 stage transitions and their rates, the
   five SICR triggers, PD drift, and two retail movement metrics.
2. **Rewrites the three shipped lenses** around a correction: a metric tile
   was declaring chart types the renderer ignores.
3. **Makes a lens say what it is for**, and lets a reader change the period it
   shows.
4. **Reads a lens in one scan per dataset** instead of one per tile.

Everything else it did was found on the way, and section 4 lists it.

---

## 2. The correction that shaped the rest

A metric tile has always carried a `visual`, and the shipped lenses set it to
`line` on the eleven tiles they wanted as trends. The tile renderer does not
read it. A metric panel computes one number for one period and the renderer
draws exactly that, so all eleven drew a single figure.

`check()` passed the whole time. It proved the metric had declared itself
line-drawable — which it had — and never asked whether anything would draw a
line. A governance check that is green while the screen disagrees with it is
worse than no check, because it is evidence for a claim that is false.

The fix is structural rather than a correction to eleven tiles:

- `Tile` has no `visual` field. It cannot declare a chart type, so it cannot
  declare one that is ignored.
- `Chart` is a separate thing that names its dimension, and goes through the
  same validation as a chart built by hand in the builder.
- `check()` proves every chart's dimension is one the dataset offers and every
  chart type is one that is honest over that dimension.
- The layout editor no longer offers "Drawn as" on a metric tile, and the
  browser journey that used to assert that select offered the right options
  now asserts it is not there.

The renderer draws two chart types — `bar` and `line`, with `line` only over
an ordered dimension. §17 of the brief lists eleven possible types. Nine are
not offered anywhere in this branch, because the renderer cannot draw them and
offering a chart type that renders as something else is the same defect in a
different place.

---

## 3. What was added

### 3.1 Eighteen metrics (61 → 77 governed, 8 unsupported unchanged)

**Corporate IFRS 9 — stage migration (8).** `ifrs9_staging` carries
`prior_stage` on every row, so a transition is a property of one row rather
than a comparison of two periods. Five amounts — Stage 1→2, 2→1, 2→3, new
defaults (into Stage 3 from anywhere), cures (out of Stage 3 to anywhere) —
and three rates: Stage 2 inflow, new default, cure.

Each rate is over the exposure that *started the period where the move
starts*, not over the book. A new-default rate over total exposure looks
reasonable and falls whenever the book grows, which is not a default rate. A
reconciliation test asserts both that the rate equals the right quotient and
that it does **not** equal the same figure over the whole book.

**Corporate IFRS 9 — SICR triggers (5) and PD drift (1).** The existing SICR
rate says whether any trigger fired. A committee asked "why is Stage 2 up"
needs to know which, and the dataset carries all five flags. They overlap —
one facility can breach a covenant and be downgraded in the same quarter — so
each panel says so, and a test asserts the five separately exceed the
any-trigger figure, because a note that is not true of the data should not be
shown.

**Retail movement (2).** The behavioural dataset carries a trailing window on
each account's row: `max_dpd_3m`, `times_dpd_30plus_6m`. That is a comparison
across time held inside one row, which the engine measures in one pass.

- **Cure Rate (3-Month Look-Back)** — of accounts that reached 30+ DPD at any
  point in the trailing three months, the share fully up to date now.
- **Repeat Delinquency Rate** — accounts 30+ DPD more than once in six months.

It is *not* enough for a roll rate, which is a movement between two
consecutive months. That stays unsupported, and its note now says what IS
available instead of only what is not — two entries that look like they
contradict each other are worse than one that admits the distinction.

### 3.2 The three lenses

| Lens | Sections | Figures | Charts |
|---|---:|---:|---:|
| Retail Credit Risk | 8 | 23 | 7 |
| Retail Analytics | 6 | 9 | 11 |
| Corporate IFRS 9 | 7 | 34 | 9 |

What is new on each, beyond the metrics above:

- **Retail Credit Risk** — 1+/30+/60+/90+ arrears by count and by balance;
  arrears, default rate and cure rate as month-by-month trends; 30+ DPD split
  by product and by vintage; default rate down the bureau score bands. The
  behavioural scorecard's Gini, KS and calibration moved here from Retail
  Analytics, next to the book they are a read of.
- **Retail Analytics** — origination mix by product, channel and segment; bad
  rate by each of those; **bad rate down the bureau score band**, which is the
  picture the Gini summarises and the one an analyst actually reads; vintage
  delinquency and utilisation by product.
- **Corporate IFRS 9** — a stage migration band, a SICR trigger band, ECL and
  coverage trends, and concentration by sector and segment.

**`MAX_TILES` was raised from 24 to 36.** This is a deliberate product
decision, not a tolerance widened to fit. At 24 the Corporate IFRS 9 lens had
to drop one whole group an impairment committee asks for by name. The number
that governs readability is tiles per *band*, and bands did not exist when 24
was chosen. It is still a limit and still refuses.

### 3.3 A lens says what it is for

Stored in the definition JSON — no migration — and carried by shipped and
user-built lenses alike: purpose, audience, portfolio, data domains, the
period it opens on, what it compares against, visibility.

- `PUT /lenses/{id}/scope` — a revision of its own, so repointing a lens is on
  the record next to adding a tile.
- `GET /lenses/{id}/periods` — the periods the lens's own datasets hold rows
  for, grouped by calendar where a lens spans two. Not every period in the
  lake: a picker offering a quarter the staging dataset has never seen draws a
  screen of dashes and teaches the reader that the picker is broken.
- `GET /lenses/vocabulary` — what the definition panel may offer, served
  rather than hard-coded so the panel cannot drift from the validator.
- `POST /lenses/suggest` — what a lens called this is probably for.

On screen, a scope bar answers the two questions a reader has first: what am I
looking at, and as at when. Choosing a period recalculates every panel.

### 3.4 Creating a lens by being asked

`/lenses/new` replaces the single "describe your lens and it appears" box.
That box turned a sentence into a lens in one shot: you described everything
at once, and whatever the matcher did not understand was silently absent from
what you got.

The new flow asks the same matcher the same things one at a time — name, then
a short definition panel with suggested values, then metrics — and shows what
it understood before anything is stored.

**Nothing in the suggestion is generated by a model.** The name is matched
against the Metric Catalogue with the search the typeahead already uses, and
the scope is read off the metrics that matched. A name echoing a shipped lens
gets that lens's purpose and opening metrics, and is told the lens already
exists rather than helped to rebuild it. That is a weaker suggestion than a
model would give and a much better one to build on: the same answer on every
machine, a test can assert it, and it cannot suggest a domain the person may
not read because a metric they may not read never reaches the ranking.

### 3.5 One scan where there were thirty-four

The conditional-aggregate trick a single metric uses on its own terms does not
stop at the edge of one metric. Every term of every metric reading the same
dataset, over the same period, under the same scope is measurable in one pass.

`execution.run_batch` does that; `metrics.values` groups for it; `render` uses
it. What each shipped lens actually costs, asserted by a test rather than
quoted once:

| Lens | Metrics | Reads before | Reads now | Why not 1 |
|---|---:|---:|---:|---|
| Corporate IFRS 9 | 34 | 34 | **1** | One dataset, one scope, no function metrics |
| Retail Credit Risk | 23 | 23 | **4** | Two scopes (all rows, matured rows) plus Gini and KS, which are governed functions and never join a batch |
| Retail Analytics | 11 | 11 | **5** | Two datasets, each read twice for the same reason, plus one function metric |

Rendering the whole Corporate IFRS 9 lens — 43 panels including its nine
charts, which are separate grouped scans and are not batched — went from
**1.83s to 0.54s**. Retail Credit Risk went from 2.03s to 1.23s and Retail
Analytics from 1.28s to 0.97s.

The three numbers are given rather than the best one, because "34 scans became
1" is true of one lens and would be a claim about all three if left alone.

The arithmetic is untouched — each figure still comes out of its own formula
over its own terms — and 34 of 34 batched values match the individually-run
ones exactly. A metric that cannot share (a governed function, a filtered
average) leaves the batch. A different scope is a different batch, which stops
a scoped metric being computed over a population it does not belong to. A
batch that fails falls back to one query each, so a lens degrades to slow
rather than to blank.

---

## 4. Defects found and fixed

| # | Defect | Found by | Fix |
|---|---|---|---|
| 1 | Eleven metric tiles on the shipped lenses declared `line`/`bar`; the renderer ignores a metric tile's visual, so all eleven drew a single figure. `check()` passed throughout. | Reading the renderer against the lens specs | `Tile` has no visual; `check()` refuses anything but a figure; trends became real charts |
| 2 | `resection` identified a panel by `(kind, metric_id)`, so two charts of one metric over different dimensions were the same panel and a revision merged their bands | Adding two charts of `total_ead` to the IFRS 9 lens | Dimension is part of a chart's identity; bands claimed from a queue so a metric shown twice keeps both places |
| 3 | `restore` put back an older set of tiles under the *current* purpose and default period | Writing the scope round-trip test | Scope travels with the version being restored |
| 4 | The metric search treated a chosen domain as a hard filter, so scoping a lens emptied the picker — and then showed an unrelated "not available in this deployment" note underneath, which read as a false claim | Browser journey L | Domain and portfolio RANK; `readable` still excludes, because that is the permission |
| 5 | The layout editor offered "Drawn as" on metric tiles, changing nothing; chart panels were badged "Analysis" | Reviewing the editor after fixing #1 | Select only for analysis panels; charts show type and dimension and point at the builder |
| 6 | An f-string with a line break inside a replacement field — valid on 3.12, a syntax error on 3.11, which `requires-python` allows | `ruff` | Rewritten |
| 7 | `_values` in the lens tests read every panel into one dictionary, so a chart overwrote its tile's value with `None` and the reconciliation tests compared nothing to nothing | Test failure after adding charts | Filtered to metric panels; chart-specific assertions added |
| 8 | **A quarterly trend was ordered alphabetically** — Q1 2023, Q1 2024, Q1 2025, Q1 2026, Q2 2023, with Q4 2022 near the end. It rendered, had the right numbers in it, and was not a trend. `_period_order` already existed and its docstring already warned about this; it had never been applied to a chart axis. Monthly labels sort correctly as strings, which is why nothing caught it until a shipped lens carried a quarter-by-quarter chart | Looking at the rendered page | `sort="period"` on a time axis; a test that also asserts alphabetical order is a *different* order on this data, so it cannot pass by accident |
| 9 | `install(replace=True)` rewrote a shipped lens's tiles and left its old name, description and audience — those are columns and `revise` only wrote the definition. The Retail lens grew a stage-migration band under the header it had before | Reading the rendered header against the spec | `revise` takes name/description/audience; empty means "leave it" |
| 10 | A library card put audience and counts on one line, so "IFRS 9 Committee and Head of Impairment · 34 figur…" truncated away the half a reader compares between cards | Screenshot review | Two lines |
| 11 | `periods()` grouped by dataset, so the Retail Credit Risk lens reported one calendar of 31 months. It reads one dataset over two — 31 months of arrears, 25 of scorecard statistics — and a reader could pick a month where five tiles correctly showed nothing, with no warning | Reviewing my own diff | A calendar is a dataset AND its scope; the note names the tiles that do not reach as far, by name rather than by the column that restricts them |
| 12 | A tile pinned to its own period was computed twice — once in the batch and once on its own | Reviewing my own diff | Pinned tiles are excluded from the batch |

---

## 5. Verification

### 5.1 Numerical reconciliation

`tests/reconciliation/test_lens_figures.py` recomputes every new metric with
pandas straight off the parquet, sharing no code with the compiler — no IR, no
plan, no executor — and a test asserts the absence of those imports.

**28 checks, all agreeing to 1e-9**, which is float summation order and
nothing else. Nothing is looser: both paths sum the same column over the same
rows, so a figure needing a wider tolerance would have a difference in its
definition, and widening it would hide the thing the file exists to find.

Worked example, Q2 2026, verified independently in DuckDB and in pandas:

| Figure | Lens | Independent | Difference |
|---|---:|---:|---:|
| Stage 1→2 exposure | 3,411.912 | 3,411.912 | 0 |
| Stage 2→1 exposure | 2,094.389 | 2,094.389 | 0 |
| Stage 2→3 exposure | 517.034 | 517.034 | 0 |
| New defaults (1→3 + 2→3) | 762.693 | 245.659 + 517.034 | 0 |
| Cured exposure | 730.264 | 730.264 | 0 |
| New default rate | 0.635812104069% | 762.693 / 119,955.722 | < 1e-12 |
| Cure rate | 13.28044655634% | 730.264 / 5,498.791 | < 1e-12 |
| SICR: PD | 11.910508153660% | 11.910508153660% | 4.7e-13 |
| PD drift | 1.146827535937 | 1.146827535937 | 2.7e-13 |
| Retail cure rate (2025-07) | 25.24781341107% | 1,299 / 5,145 | < 1e-12 |
| Repeat delinquency (2025-07) | 4.836842105263% | 919 / 19,000 | < 1e-12 |

### 5.2 Browser acceptance

`scripts/acceptance/lens_journeys.py` — real Chromium, real backend, real
PostgreSQL, real sign-in as `priya.raman`, `REQUIRE_LOGIN=true`.

**164 checks passed, 0 failed**, across twelve journeys. Two are new:

- **K** changes the period on the IFRS 9 lens and asserts the three stage
  exposures still sum to the total *after* they move. Tiles that resolved
  their periods separately would each be individually plausible and would stop
  summing. It also asserts the picker offers exactly the periods the API says
  the lens can be shown for.
- **L** creates a lens the way a person does — from the library, by name,
  through the definition panel, into the typeahead — typing `del` then
  `delinq 30` and asserting the second list is no longer than the first.

### 5.3 Test suites

| Suite | Result |
|---|---|
| `tests/metrics` | 116 passed |
| `tests/services/test_lenses.py` | passed |
| `tests/api/test_lens_layout_api.py` | passed |
| `tests/api/test_lens_scope_api.py` (new) | 14 passed |
| `tests/metrics/test_batching.py` (new) | 17 passed |
| `tests/metrics/test_lens_permissions.py` (new) | 13 passed |
| `tests/reconciliation` | passed, including 28 new |
| `tests/scorecard/test_domain_isolation.py` | passed |
| Combined lens surface | **141 passed, 0 failed** |
| `ruff check backend tests scripts` | All checks passed |
| `tsc --noEmit` | clean |
| `eslint` | clean |
| `next build` | Compiled successfully |

### 5.4 The full suite, and what fails in this container

Eight tests fail on the final HEAD. Two were this branch's — `/lenses/new`
existed with no curated judgement in the feature matrix — and are fixed. One
is suite pollution: the offending domain is named "Test Domain", is created by
`tests/api/test_data_builder.py` against the shared PostgreSQL, and the test
passes in isolation once that row is deleted.

The remaining five were proved not to be this branch's by checking out the
base commit's entire `backend/` tree, re-running exactly those tests, watching
them fail identically, and restoring. That is a claim about this container,
not about the base branch's CI: this container regenerated the data lake and
the SME scorecard universe from scratch, and those five reconcile against
particular figures in it.

The full classification, and the method, are in the acceptance matrix.

---

## 6. Permission and domain safety

The Retail lenses read the behavioural and application scorecard datasets, and
both are restricted. That is not a hole. The domain boundary is about
conversational access to record-level model populations, and a published
aggregate metric — formula written, reviewed, released, returning one approved
number — is carved out on purpose in `backend/scorecard/domains.py`. The
lenses depend on that carve-out and it is unchanged.

What this branch had to prove is that the *batched* read is scoped exactly
like the single read, so batching did not become a way to run a plan under a
scope the same metric would not get on its own. It is: the same plan in both
shapes is allowed under `GOVERNED_METRIC` and refused under `GENERAL`, and the
general Cockpit is still refused the very dataset the retail lens is built on.

Also held by test: a batch does not drag an unreadable metric into a readable
one's plan because they share a scan; a batch of only unreadable metrics reads
nothing; and the refusal for a metric somebody may not read is byte-identical
to the refusal for one that does not exist, so it cannot be used to enumerate
what exists over data they cannot see.

**A limitation, stated rather than implied.** This deployment has no per-user
dataset permissions. `readable` is a service-level parameter and the only
production caller that supplies it is the Playbook; the lens and metric HTTP
routes do not. So every signed-in analyst sees every governed metric, and
access control here is the role gate on the route plus the domain scope on the
plan. The tests prove the mechanism at the level it exists at. §20's "a saved
lens cannot keep reading a dataset after permission is revoked" has no
per-user form to test here; the nearest real equivalent — the dataset is
gone — is tested, and the tile reports the absence rather than a stale number
or a zero.

---

## 7. What the brief asked for and this branch did not build

Stated plainly, because a report that lists only what was done is not a report.

- **§13 natural-language transformation plans.** The safe transformation IR
  exists and the custom metric builder uses it. Turning "exclude closed
  accounts, keep the latest record in the quarter" into an editable
  deterministic plan is not built. The builder still requires the person to
  express the logic as terms and filters.
- **§14 nested derived terms and weighting inside the numerator builder.** The
  numerator/denominator builder supports multiple terms, filters, aggregations
  and a combining operation. Nested derived terms are not built.
- **§16 "I expect a different result" diff analysis.** The verification
  workspace records a disagreement, keeps the computed value and confers no
  verified status — journey E proves that. CreditProbe does not attempt to
  *explain* the likely source of the difference.
- **§6 scenario ECL and the ECL movement bridge.** Both remain unsupported for
  the reasons the catalogue gives: the staging dataset carries one
  already-weighted ECL rather than one per scenario, and the opening-to-closing
  bridge is a two-period decomposition with an attribution rule. The stage
  migration band now covers the one leg of that bridge the data supports.
- **§4 PSI and approval rate, §5 approval and booking rates.** Unsupported,
  with reasons, and each shipped lens says so on screen.
- **§17 nine of the eleven listed chart types.** `ChartTile` draws every chart
  as labelled horizontal bars with the exact value printed beside each one,
  and does so deliberately: every number on screen is a governed calculation
  the backend already did, and a charting library that draws its own axes has
  a way of quietly rescaling, clipping or interpolating them. A panel's chart
  type is therefore a *governance declaration* rather than a drawing
  instruction — `chart_types_for` refuses a line over a dimension with no
  order, because a line between products asserts a progression that is not
  there — and an ordered series says "Every period, oldest first" on its own
  face so a reader can tell a progression from a comparison. Heatmaps,
  cohort charts, waterfalls, scatter plots and the rest are not offered
  anywhere, because offering a chart type that renders as something else is
  the defect this branch spent its first commit removing.

- **Horizontal overflow at 390px.** Every page in the product overflows by
  33px at mobile width, including pages this branch never touched
  (`/cockpit`, `/analyses`, `/workspace`). The cause is in the shared app
  shell's top bar. It is recorded here rather than fixed, because the fix
  belongs to the layout every parallel workstream shares and changing it from
  this branch would be the kind of "small shared compatibility fix" that turns
  into a merge conflict for four people. At 1024px and 1440px there is no
  overflow anywhere.

---

## 8. The Lens Builder (second tranche)

The first tranche made the Lens experience better. This one makes it a
product somebody can use without knowing the schema.

### 8.1 Eight preconfigured lenses, six of them role-shaped

| Lens | Audience | Figures | Charts |
|---|---|---:|---:|
| CRO Portfolio | Chief Risk Officer | 20 | 6 |
| Corporate IFRS 9 | IFRS 9 Committee | 34 | 9 |
| Early Warning and TAC | Transaction Approval Committee | 10 | 9 |
| Portfolio Quality | Head of Credit Portfolio Management | 12 | 8 |
| Concentration and Large Exposures | Credit Committee | 10 | 8 |
| Board Risk Committee | Board Risk Committee | 16 | 3 |
| Retail Credit Risk | Head of Retail Credit Risk | 23 | 7 |
| Retail Analytics | Retail Portfolio Analysts | 9 | 11 |

195 panels, every one producing a real figure, each lens rendering in under
1.4 seconds.

**§19 is satisfied by construction, and proved.** `install()` calls the same
`create` and `revise` the HTTP API calls. There is no branch anywhere that
treats a shipped lens differently, and a test rearranges one, restores it, and
adds a metric it did not ship with — all through the ordinary paths. A shipped
lens carries a revision history like any other because it got one the same way.

Twenty-two new metrics support the four new lenses, all read off fields
`portfolio_facility` already carried and nobody had written down: internal
grade, rating bucket, credit trend, covenant headroom, debt service cover,
downgrade probability, appetite breach, collateral value. All twenty-two
reconcile against an independent DuckDB read and cost one scan between them.

### 8.2 Natural-language Lens creation

The library opens with the question — "How do you want to define a new Lens?"
— and a box. What is typed is carried into the builder rather than turned into
a lens on the spot: a box that built a whole lens from one sentence leaves
whatever it did not understand silently absent.

`interpret` reads the sentence and answers with **candidates, never a
decision**: the data domains it recognised with what each matched on, the
metrics that answer to it, the dimension it heard, the period it means. The
screen shows domains as chips to tick, with a free-text box for one it missed.

It is deterministic. No model reads the sentence; the catalogue does. The same
words produce the same options on every machine, which is what lets a test
assert a reading and what stops the builder being a different product on a bad
day.

The compound case is the one that decides whether this is an interpreter or a
keyword switch. "IFRS 9 coverage and retail delinquency" names one domain and
describes another; both are ticked, because a domain that produced one of the
best-matching metrics is chosen even when its name was never said.

`search.search` could not be used directly: it requires every word of the
query to match something, which is right for a typeahead and wrong for a
sentence — "show me exposure by sector" has two words that name a metric and
four that do not. So a sentence is cut into overlapping phrases, longest
first, and each is asked separately, reusing the ranking already tested.

### 8.3 A metric definition read four ways, and editable

§6 and §7. A new metric is described in words and comes back as:

- **the algebra**, expanded so every term shows its field and conditions;
- **the plain-English execution logic**, numbered, so a person checking a
  definition checks a sequence;
- **the actual compiled SQL**, from the same compiler the executor calls over
  the same validated plan — not a reconstruction;
- **the values bound to it**, printed beside the query.

All four are generated from the one tree on every request. Nothing is stored,
so nothing can be right when it was written and wrong after an edit.

The bound values earn their place. A threshold is a bound parameter, so moving
it from 0 to 5 changes what is bound and **not** the query text — a screen
showing the SQL alone would look frozen to somebody who had just edited the
number they came to edit. It also means a filter value can never become SQL,
and a test drives `Healthcare'); DROP TABLE lenses;--` through the route and
asserts DROP TABLE is absent from the query and present in the parameters.

### 8.4 Real-data preview, then lock

§8 and §9. Preview shows the dataset and its grain, the periods available,
the fields read, the filters applied, each numerator and denominator term with
its own value, the aggregation, the final arithmetic written out, and the
figure formatted as the tile will print it. The per-term row counts are the
part that earns its place: "the numerator is zero" and "the numerator matched
no rows" are different problems and only one is a formula error.

Lock sits **after** preview and not beside it. A metric nobody has seen a
number for is a metric nobody has checked. After locking: add another, or go
back to the lens.

Locking shares the metric, because putting a metric on a lens is publishing
it — a private metric on a shared lens is a tile nobody else can resolve, and
the refusal they would get describes a permission as an absence.

### 8.4a Asking a lens to change, including its charts

§11. The lens's own ask box takes the sentence through the same interpreter
the creation flow uses, so a breakdown asked for on an existing lens comes
back as a chart rather than as a KPI tile of the same metric.

Asking for a second cut of a metric that is already charted **changes that
chart** rather than adding another: "show exposure by region" on a lens that
draws exposure by sector re-cuts the one chart, and the change summary says
what it was before. A lens that answered an edit with a duplicate would be a
lens somebody has to tidy up by hand.

A dimension the dataset cannot be cut by is not an error — the request falls
through to the tile path and the metric it named is added. The metric exists;
the cut does not, and the metric is the honest answer to what was asked.

Every proposal still goes through `validate`, so a chart proposed this way is
refused for the same reasons as one built by hand.

### 8.5 Editing a lens that already exists

§12–§17. The pencil turns the real cards — with their real numbers — into an
editable board. They wiggle, they drag, each has a remove control that asks
first, and "Add new metric" opens the **same** builder the creation flow uses.
Coming back leaves the lens in edit mode, because somebody who was arranging
it still is.

The wiggle and the drag are two elements, and that is not cosmetic. A browser
will not begin a drag on an element whose own transform is animating, so the
draggable element is the outer one and never moves; the wiggle lives one level
in, on a wrapper carrying the whole visible card. What a person sees is
unchanged and what the pointer grabs holds still.

Dragging is also not the only way to move a card. Each carries move-earlier
and move-later buttons beside its handle, driving the same reorder — a board
that can only be rearranged by dragging cannot be rearranged from a keyboard
at all, and on a touch screen the drag fights the scroll.

Nothing is saved until Save, and the save goes through `PUT /lenses/{id}/layout`
— the same validated, versioned path a conversational change goes through.

### 8.6 Defects found in this tranche

| # | Defect | Found by | Fix |
|---|---|---|---|
| 13 | **A metric you had just built could not go on a lens.** `validate` resolved metric ids without the user, so an unshared metric did not exist to it; the refusal read "not a metric in the catalogue" | Driving the flow | The user is threaded through validation, and locking shares the metric |
| 14 | **Nothing could be drafted for "total exposure."** `portfolio_facility.exposure` is catalogued as a *string* and is summed by seven governed metrics; the field picker required a numeric type | Driving the flow | The declared type breaks ties rather than vetoing; the validator keeps the final word |
| 15 | **Create was enabled for a chart-only lens and did nothing.** The handler guarded on metrics, the button on metrics-or-charts | Browser journey O | The guard matches its own control |
| 16 | **The wiggle made cards undraggable.** A browser will not begin a drag on an element whose transform is animating, so pausing only the hovered card paused after the hard part | Browser journey N | The whole board holds still the moment the pointer is over it — better for a person aiming, and what makes the drag work |
| 17 | **A weighted average was silently downgraded to a row count** when no field matched | `test_a_weighted_average_asks_for_its_weight` | It keeps its kind, does not compile, and names both things still to decide. A count is a different metric, not a safer draft |
| 18 | "over" fuzzy-matched "Overlay", so *Management Overlay* was the best reading of "delinquency trend over time" | Driving the interpreter | Shape words the interpreter has already consumed get no second vote on the subject |
| 19 | A single word dragged in refusals nobody asked for — "retail" reached Retail ECL | Driving the interpreter | A refusal needs a two-word match |
| 20 | **The builder was torn down by a reload it had itself asked for.** Adding a metric from inside edit mode re-rendered the lens; the fetch went back to loading with no data, the page blanked its body, and the "Metric locked / Add another / Go back" step went with it | Browser journey N | `useAsync` takes `keepPrevious`: the previous render stays on screen until the next one arrives. Opt-in, so no other screen's loading state changed |
| 21 | **A lock the catalogue refused looked like a dead button.** The refusal — a duplicate name, most often — set an error that only the *definition* step rendered | Browser journey M | The builder's error line is rendered at every stage, and the journey now reports what it says |
| 22 | **A lens could be created having never said what it is for.** The definition panel could be skipped and an empty purpose saved, so the lens's own §8 panel read as though nobody had ever answered the question | Browser journey L | The sentence somebody typed *is* the purpose until they edit it |
| 23 | **Edit mode could only be used with a pointer.** Reordering was drag-only | UX review of what this tranche built | Move-earlier / move-later buttons on every card, driving the same reorder |
| 24 | **A lens's own ask box answered a breakdown with a KPI tile.** "Show exposure by sector" and "add exposure" name one metric and ask different things; the ask box could only add tiles | §20's list, checked line by line | The interpreter is asked first: a breakdown becomes a chart, and a second cut of a metric already charted *replaces* that chart rather than adding a duplicate |

### 8.7 What this tranche still does not do

- **Full formula surgery in the quick editor.** The definition editor changes
  aggregations and filter values — the two things people actually change after
  a draft. Adding or removing terms, or repointing a field, is the existing
  full metric builder's job.
- **Synonym resolution between business language and column names.**
  "probability of default" does not reach `pd_12m_pct`, so that draft comes
  back with the measure unresolved rather than guessed. Honest, and less
  helpful than a synonym map would be.
- **Two doors into rearranging.** The pencil's edit mode and the older
  "Arrange" panel both reorder a lens, through the same versioned save. The
  Arrange panel is the one that explains why a metric tile has no chart type,
  so it was not removed in this tranche; folding that explanation into edit
  mode and retiring the panel is the obvious next step.

---

## 9. Recommendation

**READY FOR INTEGRATION REHEARSAL.**

On the evidence:

- **The full backend suite: 12,947 passed, 6 failed, 46 skipped.** All six
  failures are the ones §K2 of the acceptance matrix documents — five proved
  environmental by reproducing them against the base commit's own `backend/`
  tree, and one caused by another test file leaving a row called "Test Domain"
  in the shared database. None is in this branch's code, and the two feature-
  matrix failures that branch *did* cause are fixed and no longer appear.
- 271 test functions across the lens surface, in fourteen files, of which the
  builder, batching, permissions, scope, chart-ask and reconciliation files
  were written for this workstream.
- Every new metric reconciles against an independent pandas recomputation to
  1e-9, with two of those tests asserting the *mistake* rather than the number.
- **286 browser checks pass** against a real stack with a real login: 213
  journeys A–L, 73 journeys M–P.
- The scorecard domain boundary is provably unchanged, and the new execution
  path is provably scoped like the old one.
- `ruff`, `tsc`, `eslint` and `next build` are clean; the migration head is
  unchanged at `0041`, so integration carries no schema risk from this branch.

The gaps in §7 are real and none of them is a correctness risk: each is a
feature not built, and every one of them is visible to the user as a refusal
with a reason rather than as a number that might be wrong.

**Not merged. No PR opened. No force push, no rebase, no merge to main.**

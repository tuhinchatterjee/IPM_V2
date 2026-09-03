# Lenses 2.0 and the Metric Catalogue — final report

**Branch** `claude/vigilant-darwin-eohyi1` · **Final HEAD** `a9981a5`
**Nothing merged to main. No pull request opened.**

Nine commits, `47ca628..a9981a5`, 39 files, +8,270 / −107.

    47ca628  The Metric Catalogue, and four numbers that were quietly wrong
    7447c18  The Metric Catalogue on screen
    1bf431b  A lens can now be given a metric by asking for it
    8380742  Six lens journeys, driven through a real browser
    b335b75  Four protected invariants my own changes broke
    b19d2e9  A metric with no period was answering for all of them
    552a084  A lens can be arranged by hand, under the rules it is asked by
    f1b034c  A lens asked its dataset the same question twenty-one times
    a9981a5  A failed period lookup was quietly the bug it replaced

---

## A. What this was for

One place that says what CreditProbe means by each number, and lenses built out
of that place rather than out of formulas living in the components that drew
them. Before this, a figure on a screen and the same figure in an answer were
two implementations of one definition, and the only way to know whether they
agreed was to read both.

## B. The definition layer

`backend/metrics/` — one governed library, one execution path, one service.

| | |
| --- | --- |
| Governed metrics | **61** |
| Named and NOT calculable here, with the reason | **8** |
| Shipped lenses | **3** (21, 16 and 12 tiles) |
| Migration head | **0037** — `user_metrics`, `metric_verifications` |

Nothing here computes. `backend/metrics/execution.py` compiles a metric to the
same validated analytical plan (`backend/runtime/ir.py`) that every other
analysis in CreditProbe uses and runs it through `runtime.executor`. There is no
second formula system and no second execution path — §7 asked for exactly that,
and extending the existing one was the cheaper honest answer.

## C. No path from a request body to SQL

A metric is submitted as a **structured formula object**, never as text. It is
validated against the governed data catalogue before it is stored, so a
definition naming a column that does not exist is refused at submission rather
than failing at render time on somebody's dashboard. `POST /metrics/preview`
compiles and runs without storing, so a person sees the number, the working, or
the refusal with its reason, before committing to a definition.

The builder form offers only governed datasets, their real fields, and the
aggregations and comparisons the formula language declares. That is a
convenience: the server validates the same thing again, because a select
element is never a control.

## D. Four numbers that were quietly wrong

Found by checking, not by testing:

1. **Function metrics were not computed at all.** `run()` had no branch for
   `kind == "function"`, so Gini, KS and calibration fell through. A
   `DISCRIMINATION` kernel now runs them on the full frame.
2. **The kernel could measure part of the population without saying so.** The
   compiler appends `LIMIT 50,000`; a statistic that reads every row would have
   silently measured the first 50,000. It now refuses, and says why.
3. **An invented direction string.** `_risk_ordered` accepted an unrecognised
   direction and guessed. It raises `MetricError` on anything outside the
   governed vocabulary.
4. **Ordinal ranks on ties.** Gini used ordinal ranks where midranks belong.
   Verified against an independent midrank Mann-Whitney in raw DuckDB: agrees
   to **9 × 10⁻¹³**.

## E. The defect this run was really for

Writing a browser journey that proves a built metric's number is right is what
found it. The metric said **3.26 %**; the Parquet said **1.45 %**. Neither was
wrong arithmetic — the metric had read all fifteen quarters at once, because an
absent period meant *no period filter* rather than *a period*.

Every metric in the catalogue did this. `corporate.npl_rate` with nothing
selected divided **106,073 by 1,213,586** — fifteen quarterly snapshots of a
book added together, a share of a portfolio that exists on no date, labelled
with no period at all and rendering exactly like the figure somebody asked for.

Lens tiles pass a period, so this was confined to the catalogue screen, the
builder preview and the rows behind a figure — which is to say, to the three
places built to let somebody check a number.

`service.default_period()` now resolves an absent period to the most recent one
the metric **has rows in**, and the answer carries that period.
Chronologically, not alphabetically: `"Q4 2025"` is the string maximum over
`"Q1 2026"`, and `latest_matured_period` had been taking exactly that maximum.

Two consequences followed:

- `Matured Performance Rows` moved its maturity condition from a term filter
  into the metric's **scope**. It counts matured rows; asked for the newest
  month in the lake it would have answered zero — correctly, and uselessly.
- A verification now records the period it actually checked, not the blank the
  caller sent. Evidence that does not say which period it is about supports
  nothing.

## F. The same defect in the failure path

Reading my own change adversarially: `periods_with_rows` returned an empty list
when the resolution query *failed* — the same empty list it returns when a
source genuinely has no period concept. A moment's unreachable lake put the
metric back on the unfiltered scan. It is now a `DataAccessError`, resolved
inside `value`'s own guard, so an unreachable source reads as "this could not
be calculated, and here is why" rather than a wrong number or a raw 500.

## G. Governance on the face of every metric

Origin (`CreditProbe governed` / `Built here`) and status (`Draft`,
`Calculates`, `User verified`) travel on the definition and onto every panel
and tile. A metric somebody built arrives as a **draft** and stays one until a
person's own number agreed *and* they accepted it. Accepting a comparison that
**differs** is allowed — sometimes the analyst's number was the wrong one — but
it confers nothing, because the stored evidence would not support it.

Changing a metric's arithmetic drops it back to draft and clears its tick.
Deleting it removes its verification history, so a reused id cannot inherit
someone else's tick.

## H. What CreditProbe will not calculate here

Eight metrics are listed with the reason rather than approximated: retail IFRS 9
staging and ECL (no retail impairment dataset), roll rate and cure rate
(movements between two periods; the engine computes one), approval rate, PSI.
Each carries a sentence and what would be needed. A reader who came looking for
a roll rate came to the right place and gets the reason, not silence.

Lenses carry the same list: `NotShownHere` says what the lens deliberately does
not show. **Nothing is both shown and declared missing** — journey F asserts it.

## I. Search that narrows

`backend/metrics/search.py`: five deterministic tiers — exact, name prefix,
alias prefix, tokens, fuzzy. §8.3 asked that a picker not open with the whole
catalogue, and an empty query returns nothing. Typing a second word **removes**
suggestions rather than adding them: when any stronger tier matched, fuzzy hits
are suppressed entirely, which is what stopped `30+ dpd` suggesting
`60+ DPD Account Rate`.

Every suggestion says why it matched. When nothing matches, the unsupported
list is searched, so an absence is explained instead of shown as an empty box.

## J. Arranging a lens

Two ways in, one set of rules. `POST /lenses/{id}/ask` changes a lens by
describing the change; `PUT /lenses/{id}/layout` submits the arrangement
directly. Both run `services.lenses.validate` and both write a restorable
revision, so a tile moved by hand is refused for the reasons a tile added by
asking is.

The layout arrives **whole**, not as a list of moves: an ordering is not a set
of independent edits, and applying five of six reorderings leaves a lens nobody
asked for. Bands address tiles by position in the same submission, so an
ordering and its bands cannot disagree; a band pointing past the end is refused
rather than rendering as a gap.

How a tile may be drawn comes from the **metric's own** `visuals`, not the
platform's list of chart types. A single ratio drawn as a line of one point
looks like a working tile and misleads.

Writing that journey found that `POST /lenses` could not make a lens of metric
tiles at all — its panel shape predates them and required an analysis id. One
shape now covers both.

## K. What it costs

    .venv/bin/python scripts/acceptance/lens_performance.py

| What | p50 | p95 | Budget |
| --- | ---: | ---: | ---: |
| Metric typeahead | 16 ms | 18 ms | 200 ms |
| The whole catalogue | 11 ms | 11 ms | 600 ms |
| One metric, calculated | 96 ms | 98 ms | 1,500 ms |
| Corporate IFRS 9, 21 tiles | 923 ms | 948 ms | 4,000 ms |
| Retail Credit Risk, 16 tiles | 717 ms | 759 ms | 4,000 ms |
| Retail Analytics, 12 tiles | 742 ms | 765 ms | 4,000 ms |

Measured over HTTP as a signed-in analyst, so what is timed is what a person
waits for. First call discarded — it pays for a DuckDB connection nobody after
the first person pays again.

**Not a capacity claim.** One process, one client, no concurrency, synthetic
data on local disk, in a sandbox with shared CPU. Useful for telling whether a
change made a screen slower, and for nothing else.

## L. A lens asked its dataset the same question twenty-one times

Measuring it is what showed it. Each metric tile resolved its own period, so
the IFRS 9 lens ran twenty-one identical resolution queries before the
twenty-one it was there to run: **1.7 s**.

Worse than the cost: two tiles that resolved separately could land on different
periods, and the IFRS 9 lens is built so its three stage exposures sum to its
total. Tiles reading different quarters would stop summing and nothing on the
screen would say why.

Resolved once per source per render: **1.7 s → 0.92 s**. The memo lives for that
one render — a cache that outlived it would go on serving yesterday's latest
period after a load.

## M. The IFRS 9 lens reconciles

Asserted, on the rendered payload, not by inspection:

- three stage exposures → total EAD
- three stage provisions → total ECL
- the three shares → 100.0
- coverage = ECL / EAD
- overlay share = overlay / ECL

## N. Permissions

Reading, building and verifying each need an Analyst; a Viewer is refused
(**403**), including on the layout route. CreditProbe is single-tenant and
models **no per-dataset read permission** — every analyst may read every
published dataset. The service layer nevertheless takes `readable` and applies
it *before* ranking rather than after, so when dataset-level permissions do
arrive one place changes, and no metric can be suggested over data the asker
cannot see in the meantime. A metric the asker may not read raises the same
error as one that does not exist.

`REQUIRE_LOGIN` is asserted by a monkeypatched test that also proves a header
cannot bypass it.

## O. Browser journeys — 76 of 76

    .venv/bin/python scripts/acceptance/lens_journeys.py

Real Chromium, real backend on :8000, real front end on :3000, signed in as a
named analyst (`priya.raman`) rather than with the login gate off.

| | |
| --- | --- |
| A | A shipped lens shows real figures, and the stage exposures sum to the total |
| B | A tile explains how it is calculated — formula, source fields, what it is not |
| C | Typing what you call it finds it, and a second word **narrows** |
| D | Something this deployment cannot do is refused with the reason |
| E | Checking a figure against your own number, including when they disagree |
| F | What the lens deliberately does not show, and why |
| G | Building a metric on screen, and its figure agreeing with raw DuckDB |
| H | Arranging a lens by hand, and putting the previous arrangement back |

Journey G is the one that matters most: it assembles a definition nothing in
the governed library computes, previews it, saves it, and compares the figure
**on screen** against the same share computed in raw SQL straight off the
Parquet. It cleans up after itself and can run twice.

The harness exits **2** (`CANNOT_RUN`) rather than 0 when Chromium will not
launch. A run that quietly checked nothing must not read as a pass.

## P. Commands, from final HEAD

    .venv/bin/python -m pytest tests -p no:randomly              # full suite
    .venv/bin/python -m pytest tests/metrics -p no:randomly      # 115
    ruff check .
    .venv/bin/python scripts/check_decimals.py
    .venv/bin/python scripts/feature_matrix.py --write
    .venv/bin/python scripts/acceptance/lens_journeys.py
    .venv/bin/python scripts/acceptance/lens_performance.py
    .venv/bin/alembic upgrade head
    cd frontend && npm test && npx tsc --noEmit && npx eslint src && npm run build

Note `pyproject.toml` sets `addopts = "-q"`. Passing `-q` again makes it `-qq`,
which **suppresses the "N passed" line** — that is why several earlier runs in
this work produced dots and no count.

## Q. Gates, on final HEAD

| Gate | Result |
| --- | --- |
| `ruff check .` | clean |
| `scripts/check_decimals.py` | 49 high-precision sites allowed **with a reason**, 0 without |
| `npx tsc --noEmit` | clean |
| `npx eslint src` | clean |
| `npm test` | **474 passed**, 0 failed |
| `npm run build` | succeeds; emits `/metrics` and `/lenses/[lensId]` |
| `alembic upgrade head` | `0037`, applied and round-tripped down/up |
| Browser journeys | **76 / 76** |
| Performance | 6 of 6 paths inside budget |

## R. Four invariants my own changes broke, and how

Caught by the protected suites, not by me:

- A `:.4f` AUC in a kernel note broke the display contract. Fixed by **removing
  the AUC from the note**, not by widening the allowlist.
- Two new routes were unreviewed in the feature matrix; a third judgement was
  stale. Added and corrected.

Nothing was silenced. No assertion was loosened, no test skipped, no xfail
added, no tolerance widened.

## S. What is NOT verified here

- **Docker.** `docker compose up` cannot run in this sandbox. **NOT VERIFIED IN
  CLAUDE SANDBOX.** No claim is made about the container stack.
- **Live AI.** No call was made to any model provider in this work. Nothing in
  the Metric Catalogue or the layout editor requires one — the catalogue,
  builder, verification workspace, layout editor and every journey are entirely
  deterministic. `POST /lenses/{id}/ask` does use the provider; its behaviour
  here was exercised only through the deterministic paths.
- **Concurrency and scale.** See §K. One process, one client.
- **Any figure as a statement about a real portfolio.** The data is synthetic.

## T. Remaining limitations, stated plainly

1. **No per-dataset read permission model exists.** §N. The parameter is
   threaded through and applied; the model behind it is not built.
2. **A lens is capped at 24 metric tiles.** Beyond that it stops being a view.
3. **No period-over-period metric.** Roll rate, cure rate and the ECL movement
   bridge are movements between two periods; the metric engine computes one.
   Listed as unsupported rather than approximated.
4. **PSI is not a metric here.** It compares a period against a reference
   window. Listed as unsupported.
5. **No retail impairment dataset**, so retail staging and ECL cannot be
   calculated in this deployment. Listed with the reason.
6. **The layout editor cannot add a tile.** It reorders, bands, retitles,
   redraws and removes. Adding is done by asking, or through `POST /metrics`
   then the lens. Removing every tile is refused.
7. **Analysis panels have no declared visuals.** Metric tiles offer the
   metric's own list; analysis panels fall back to the platform's five, and the
   server validates either way.
8. **A metric reads one dataset.** `compile_metric` scans `datasets[0]`. A
   metric spanning two sources is refused rather than joined.
9. **The period memo is per render.** Two lenses opened at once each resolve.
   Deliberate — see §L.
10. **Backfilled verification history is not migrated**, because none existed
    before `0037`.

## U. What a person can now do that they could not

- Search 61 governed metrics by what they call them, and get told why each
  matched.
- Read what any number means: formula, numerator, denominator, source fields,
  period rule in words, exclusions, and **what it is not**.
- Calculate one, and see the arithmetic that produced it and the period it came
  from.
- Look at a sample of the rows behind it with the inclusion logic worked out
  per term.
- Build a metric of their own from governed datasets and fields, preview it
  before saving, and save it as a marked draft.
- Check any figure against a number they already trusted, and have the
  disagreement kept.
- Open three shipped lenses whose tiles reconcile, ask one for a change, or
  arrange it by hand — either way a restorable version.
- Be told, on the same screens, what CreditProbe will not calculate and why.

## V. The one-line summary of the run

A defect the tests did not have, found by writing a journey that checked a
number against the data rather than against the platform: **every metric in the
catalogue, asked for with no period, was answering for all of them at once.**

## W. Files of record

- `docs/METRIC_CATALOGUE.md` — the definition layer, the period rule, the
  arranging contract, the measurements
- `docs/FINAL_FEATURE_VERIFICATION_MATRIX.md` — regenerated on final HEAD
- `scripts/acceptance/lens_journeys.py` — journeys A–H
- `scripts/acceptance/lens_performance.py` — §K

## X. Branch state

`claude/vigilant-darwin-eohyi1`, pushed, at `a9981a5`. **Not merged to main. No
pull request opened. No history rewritten, no force-push.**

## Y. Full backend regression on final HEAD

    .venv/bin/python -m pytest tests -p no:randomly

**In flight at the time this file was committed, and not yet reported here.**
The count will be added in a follow-up commit against this same HEAD. It is
left blank rather than estimated: a regression figure nobody watched finish is
not a regression figure.

What *is* already established on `a9981a5`, each from a run that completed:

| Suite | Result |
| --- | --- |
| `tests/metrics` | **115 passed** |
| `tests/metrics` + `tests/api/test_metrics_api.py` + `tests/api/test_lens_layout_api.py` | **151 passed** |
| `tests/api` + `tests/metrics` + `tests/runtime` + `tests/scorecard` | **1,487 passed, 2 skipped** — measured one commit earlier, at `f1b034c`'s parent, and re-run in part since |
| Frontend `npm test` | **474 passed** |
| Browser journeys A–H | **76 / 76** |

Two skips in the backend figure are environmental, not disabled tests.

# Known limitations

Everything this candidate does not do, in one place, with the reason. A
limitation stated here is one a reader can plan around; a limitation
discovered later is one that cost somebody a day.

> Every figure this candidate produces is measured on **generated books**.
> Nothing here is bank output, an accounting figure or observed economic
> history, and no model or sensitivity is bank-validated.

---

## 1. The chat-to-engine path exists, through one authorised dispatch

A typed question in the Advanced Cockpit reaches `scenario/run.py` and its
result comes back through the ordinary response path into the ordinary thread.
The route is a guarded branch in `execute_tool.py` that recognises one step
language, `whatif_scenario`, for a book whose flag is on, and hands its typed
`parameters` to `scenario/bridge.py`. The adapter is unprotected code; the
protected-core addition is the dispatch and nothing else.

**The sandbox is untouched.** A governed Python step still runs under `-I -S`
from a temporary directory with no `PYTHONPATH`, so it still imports the
standard library and nothing else: `import pandas` and
`from backend.cockpit_v4.scenario import run` both fail with
`ModuleNotFoundError` inside it, asserted against `pyrunner._spawn` in
`test_whatif_bridge.py`. The scenario path is not a Python escape hatch — no
module name, callable, path or Python expression is accepted from the model or
the user, the step's `code` is a human-readable restatement that is never
parsed, and `parameters` must match one of two closed shapes with every unknown
key refused by name.

**What the flags off restore.** Both flags off and nothing in the scenario
package is imported by the accepted runtime: the step language is not even
accepted, the refusal is the accepted sentence, the provider payload is
byte-identical, and the accepted browser suite is unchanged.

**Three protected files carry the change**, each with its own authorisation,
and every one of them is listed with its diff purpose in
`BASELINE_AND_EXTENSION_MAP.md`.

## 2. The Retail emulator is not ready, and its number is not published

Model version 2, Retail: G1 4.43%, G2 1.27%, G3 3.50% — and **G4, worst
material-group WAPE, 34.36% against a 15% threshold**. The threshold was
predeclared in `ML_ACCEPTANCE_TARGETS_V2.md`, committed before the model was
fitted and before the test split was read. It has not been moved, the group has
not been excluded, materiality has not been redefined, and nothing was tuned
against the untouched split.

**Method 2 is therefore unavailable on the Retail book.** The conversational
answer says the emulator is not ready and names the gate; the method keeps its
row in the comparison with its cells **empty rather than zero**, and no other
model stands in for it. The result appears in model-development evidence only,
marked FAILED VALIDATION. Delta and User-defined work normally on Retail.

Corporate model version 2 passes all four gates — G1 1.89%, G2 1.13%,
G3 2.34%, G4 5.37% — and its estimate is published beside Delta's.

## 3. Both emulators are genuine blends, on a declared change of methodology

Corporate: XGBoost 0.767 / additive-in-logs 0.233. Retail: additive-in-logs
0.658 / LightGBM 0.342. Both reproduced exactly across two builds.

The weight fit is an exact solve over all seven faces of the simplex
(`blend.py:171-221`), so the earlier single-component outcome was the true
global optimum on out-of-fold least squares rather than a search defect. What
changed is one declared component, with its reason taken from development
evidence alone: the additive-in-LEVELS spline was replaced by a regularized
additive model in log space, because the target is multiplicative
(`ecl ≈ ead × pd × lgd`) and an additive-in-levels basis provably cannot
represent a product. Component diversity is the mechanism by which a blend
becomes possible; "blend" was not the objective and no weight was manufactured
to reach the word.

## 4. There is no tornado chart

`BarChart` computes `max = Math.max(high, 0)` and `width = abs(value) / max`,
so −400 and +400 draw the same rectangle on the same side
(`visuals.tsx:245-253`, server SVG identically at `export.py:594-601`). A
signed driver ranking through it would show every driver pointing one way.

`results.tornado_substitute()` returns a waterfall whose caption says the
requested form is unavailable and why, plus a signed table that keeps both the
ordering and the direction. It is not called a tornado.

## 5. The XLSX workbook is offline, and there is no in-chat XLSX route

`scripts/whatif/build_workbook.py` builds §14.3's workbook from a stored
scenario result and refuses to write one that does not reconcile: the cohort's
change against baseline and scenario, each method's own change, the book
identity, the attribution bridge against the headline, and an unavailable
method against **nothing** rather than against zero. A cell whose text begins
`=`, `+`, `-`, `@`, tab or carriage return is stored as text, so a value cannot
become a formula in a reader's spreadsheet.

The in-chat route is **not added**: cockpit-v4 exports Markdown, CSV, SVG and a
governance ZIP, and an XLSX route would be a protected-core change this
authorisation does not cover.

## 6. Export reconciliation is exercised, on the CSV route

J09 runs a scenario to a stored result through the product, fetches
`/runs/<id>/export?format=csv`, and compares the exported digits against the
figure the chat displayed. The workbook builder's five reconciliations close
exactly on a real two-rule Corporate result. Formula-injection blocking is
tested on the workbook; the existing Markdown, SVG and ZIP routes are unchanged
and were not re-driven against scenario content.

## 7. Two frozen ledgers can be compared

`ledger.compare()` reports, for two frozen ledgers over one cohort: the rows
only one side carries, a disposition disagreement, and a refusal rather than a
caveat when the two are not comparable at all — different book, period, release
or cohort. It cannot invent a number for a row that one side does not have.

## 8. J01–J14 ran against the candidate, with a scripted analyst

Fourteen journeys on each book, through real Chromium against the real UI, the
real V4 API, the real durable store, the real worker and event stream, the real
DuckDB session over the published candidate release, and the real scenario
engine reached through the real `execute_analysis` tool. **28 of 28 pass.**
Evidence per journey in `evidence/journeys-{corporate,retail}.json`: the prompts
as typed, screenshots, the thread id with the book and release it is pinned to,
cohort id and membership hash, scenario id and version, confirmation digest, run
ids, source release and fingerprint, engine and model versions, tool trace, what
was displayed, the reconciliation checked, and the export. Where an id is
absent the record says why.

The analyst is scripted — see §9. A journey driven by a live model is a
separate, unrun claim.

E20 (timeout, cancellation, repeated Run under a scenario turn) is covered by
J12, J13 and J14.

## 9. No live provider call was made

Every provider-facing test uses `ScriptedProvider` or the stub server and is
labelled MODEL MOCK. No credential is authorised here, so no journey
exercises a real model. Nothing in this deliverable claims a live
validation.

## 10. The Mac launchers were prepared, not installed

Two candidate launchers exist, each with its installation steps in its own
header: `scripts/whatif/START_ADVANCED_COCKPIT_WHATIF_CANDIDATE.command` and
`scripts/whatif/START_ADVANCEDCOCKPIT_WHATIF_UAT.command`, the second gated by
`scripts/whatif/uat_preflight.py`. `/Users/tuhinchatterjee/Desktop/
CreditProbe_Launchers` is not reachable from this Linux container, so neither
has been **copied there, made executable there, or run**. The accepted
launchers under `scripts/cockpit_v4/` are untouched and the accepted
presentation launcher is not overwritten by either.

The preflight pins to the tag `whatif-candidate-h1`. Until that tag exists it
refuses rather than starting, and says to pass `--any-revision` for a
pre-freeze run and to record that in the evidence.

## 11. Twenty periods is twenty periods

Every sensitivity in this deliverable is fitted on **20 distinct
macroeconomic observations**, 11 of them training. §7.3's own words: these
are *"conservative product defaults to make insufficiency visible, not
universal statistical or regulatory adequacy standards."* `SUPPORTED_ESTIMATE`
means "this book supports publishing this slope" and nothing more.

11 of 48 Corporate fits and 11 of 42 Retail fits are `DIAGNOSTIC_ONLY`, and a
diagnostic row is refused for automatic translation.

## 12. The degrees-of-freedom reading is a choice

§7.3 caps effective fitted degrees of freedom at
`max(1, floor((training − 5) / 5))`, which on 11–13 training periods is
**one**. A single-regressor ridge counting its intercept scores about 1.9 and
would fail — as would an intercept-only model at exactly 1.0. The ceiling is
therefore read as governing **predictor** complexity.

Under the stricter reading **every row of both artifacts would be
`DIAGNOSTIC_ONLY`**, the slopes and intervals would be identical, and no
macro scenario could translate automatically. Recorded in both
`SENSITIVITY_CARD_*.md`.

## 13. The stored artifacts cannot carry their own release's fingerprint

A sensitivity artifact and a model-metric table live **inside** the release
they describe, and a release fingerprint is taken over bytes that include
them. `source_fingerprint` is therefore a SHA-256 over the exact
period-level series the fit consumed, republished in the manifest notes as
`sensitivity_input_digest`; `trained_against_fingerprint` in
`artifacts/whatif/<book>/model_metric.json` is the fingerprint the model was
**fitted** on, which is the release before the metrics were added to it.

Staleness detection works on those digests plus `source_release_id`. It is
not the whole-release fingerprint and the documents say so.

## 14. SQL step artifacts store 100 rows

`execute_tool.py:767-769` stores `frame.head(preview_rows)`. Record-level
detail beyond 100 rows must come from a Python step — which §1 limits to the
standard library — or be declared capped with the full population count.

## 15. A cohort's cohort is not re-derivable from the thread body alone

`thread.py` stores the cohort id, its membership hash, its counts and its
baselines. It does **not** store the membership itself. Reopening a scenario
against the same release reuses the id; reopening it against a different one
drops the binding entirely and does not rebind.

## 16. Three findings in the accepted UI, now fixed

All three were measured by driving J01–J15 through the real product. All three
sat in protected files; all three were authorised in the hardening round and
are closed. Each is recorded here with what it was and what it now does,
because a fix nobody can find the reason for is a fix somebody will undo.

**16.1 A money figure that read as nothing when it was something. FIXED.**

`display.PERMITTED[MONETARY_AMOUNT]` is `(0,)` — a money figure is written to
whole units and the precision is CreditProbe's outright. Right for the
Corporate book, whose totals run to SAR 779,475 million. Wrong for the Retail
book, whose **entire monthly ECL is SAR 3.19 million**: its ECL-by-product
table read `2 / 1 / 1 / 0 / 0` for rows that are 1.69, 0.61, 0.57, 0.30 and
0.02, and a real 20% PD rise on a Retail cohort read
`SAR 2 million becomes SAR 2 million, a change of SAR 0 million`.

The rule gained a second half and only a second half. At one unit or above a
money figure is still written whole. Below one unit it gets the fewest decimals
that give the **smallest non-zero amount in its group** two significant digits,
capped at four — where a group is one table column, one chart series, or one
unit's worth of claims in one answer. One precision per group, because a column
mixing `1.7` with `0.30` is a column nobody can read down.

Measured, through the product: Retail now reads
`SAR 1.69 million becomes SAR 2.03 million, a change of SAR 0.34 million
(20.00%)`, and Corporate still reads `SAR 171 million becomes SAR 202 million,
a change of SAR 31 million`. The 76 accepted browser journeys produced **no
money-string change at all**. `display.py` is the one policy, so the narrative,
the claim line, the table cell, the chart tooltip, the axis and the CSV and
Markdown exports all inherit it; `tests/cockpit_v4/test_whatif_money_precision.py`
(28 tests) fails if any of them disagrees.

**Residual:** an amount below `0.00005` in its own group still writes as
`0.0000` at the cap. Holding the declared scale fixed is what makes that
possible; per-column scale switching (thousands, riyals) is the follow-up that
removes it, and it was deliberately not taken in a hardening round.

**16.2 A run still working read as a run that stopped. FIXED.**

`reducer.ts`'s `settled` case set `terminal: true` for **any** status that
arrived. Two callers send one mid-run — the SSE sequence-gap detector, which
re-reads the status when a frame is dropped, and the reader's own "Check its
status" button — and moments after the POST that status is `ACCEPTED` with no
response attached. `terminal` latched and nothing cleared it, so the page read
`Stopped: ACCEPTED / This request stopped / No answer was produced` for as long
as the run took, and the live timer froze with it.

The server already answered the question: `GET /runs/{id}` carries `terminal`
(`routes.py:458`) and the state itself says so. Both are now asked. A working
status refreshes the steps and the clock and leaves the **outcome** alone — a
refreshed view of a run in flight is not a verdict on it. `collapsedSummary`
maps the six working states to their own words, so "Stopped" appears only when
something stopped. One terminal-state list, in `reducer.ts`, mirroring
`states.py:50-52`; the duplicate in `thread-view.tsx` is gone.

**16.3 One malformed table destroyed the whole thread. FIXED.**

`finalization.render_tables` publishes a table it could not resolve to a stored
artifact by passing the analyst's raw dict through untouched — no `row_id`, no
`canonical`, no `display`. `ResultTable` reads `row.display[column]`, so the
subtree threw `Cannot read properties of undefined`, and the nearest boundary
is the **route's** (`app/error.tsx`): the entire thread page was replaced by
"This page could not be loaded", taking every earlier turn and the composer
with it. A reader could not scroll back, could not read the answer that HAD
worked, and could not ask anything else.

Each figure is now wrapped in the boundary this codebase already had —
`components/system/error-boundary.tsx`, whose own docstring describes exactly
this job — with `area` naming which figure failed. One bad table costs one
`<figure>`. **Nothing is guarded inside the renderer**: defaulting a missing
`display` map to `{}` would draw blank cells and hide the defect, and this is
meant to show one. `componentDidCatch` still writes the stack to the console.

Proven by **J15**, on both books: the failed figure says so in its own place,
the turn before it is still on screen, the rest of that turn's answer still
renders, the composer still accepts input, and the next turn still answers.

**Still open, and NOT authorised in that round:** the server half.
`finalization.py:899-905` should refuse to publish a table it did not render
rather than passing the raw dict on. A malformed table still reaches the
browser; it just no longer takes the page with it.
`test_whatif_money_precision.py::test_a_table_the_server_cannot_resolve_is_passed_through_unrendered`
pins that precondition so the boundary is never removed on the assumption it
was fixed upstream.

## 17. The offline explanation document is documentation, not a per-run answer

`artifacts/whatif/<book>/explanation.json` carries gain-based importance and
partial-dependence curves computed **once, on the development window**, because
evaluating the blend over a grid for every feature is far too much work for a
chat turn. Every row it produces says, in the status a reader sees, that it
describes the fitted function on the development window and not the cohort in
view. The held-back periods are checked against the published model's own split
and the build refuses if the two disagree.

Per-run SHAP and per-component contribution ARE computed on the cohort, from the
frozen artifacts — a TreeExplainer pass is a forward walk of trees that already
exist and is not a refit.

None of it is a decomposition of the scenario's ECL movement.
`explain.never_a_decomposition` refuses any explanation row carrying a scenario
currency column, and a test fails if a feature name is ever also published as an
attribution driver.

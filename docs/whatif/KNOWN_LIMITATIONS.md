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

## 10. The Mac launcher was prepared, not installed

`scripts/whatif/START_ADVANCED_COCKPIT_WHATIF_CANDIDATE.command` exists with
its installation steps in its own header. `/Users/tuhinchatterjee/Desktop/
CreditProbe_Launchers` is not reachable from this Linux container, so the
file has **not been copied there, not made executable there, and not run**.
The accepted launchers are untouched.

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

## 16. Three findings in the accepted UI that this work surfaced and did not fix

Each was found by driving J01–J14 through the real product. Each is in a
protected file this authorisation does not cover, so each is recorded here
rather than changed. None is caused by the scenario path; the scenario path is
what made them visible.

**16.1 A riyal amount cannot show a small movement.**
`display.PERMITTED[MONETARY_AMOUNT]` is `(0,)` — a money figure is written to
whole units and the precision is CreditProbe's outright. The Retail book's
monthly cohort carries about **SAR 1.69 million** of ECL, so a genuine 20% PD
rise produces "baseline ECL of SAR 2 million becomes SAR 2 million, a change of
SAR 0 million". Every digit there is the display policy doing its job, and
together they say the opposite of what happened. The same number appears as
`1.69` in the table beside it, because a table column with no declared unit is
formatted as unitless at two decimals — so one answer shows one figure two
ways.

*What this work does instead of changing the policy:* the percentage change is
quoted beside the absolute one (a percentage class carries two decimals and
states the movement exactly), and when the riyal figure rounds to nothing the
answer says so in words and points at the unrounded rows. Nothing is rounded
before it is computed.

**16.2 A run still working reads as a run that stopped.**
The thread view renders the assistant's turn as soon as the run view says
`terminal`, and the run poller latches `terminal` from the first status it reads
— which, moments after the POST, is `ACCEPTED` with no response attached. The
page then reads **"Stopped: ACCEPTED / This request stopped / No answer was
produced"** for as long as the run takes, and corrects itself only when the
settled status arrives. A reader watching a slow scenario run is told it failed.

*Reproduction:* any turn in `journeys-corporate.json`; the harness had to learn
that an unexplained stop is indistinguishable from a run in progress, and counts
a stop as an ending only once it has named an error code.

**16.3 A published table the server did not render crashes the thread page.**
`finalization.render_tables` builds a published table from the stored artifact
and passes an unrecognised one through untouched. `ResultTable` then reads
`row.display[column]` on rows that have no `display` map, throws
`Cannot read properties of undefined`, and the error boundary replaces the whole
page — including the composer, so the conversation cannot be continued. The
failure mode is a white "This page could not be loaded" for what is a single
malformed table.

*Reproduction:* have an analyst declare a table with inline `rows` and no
`artifact_id`. Two guards would close it — a server-side refusal to publish a
table it did not render, and a UI that draws a cell it cannot find as empty —
and both are in protected files.

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

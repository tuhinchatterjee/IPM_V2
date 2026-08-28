# CreditProbe AI — P1/P2 visual completion and governed XLSX exports

The 37 items §64 asks for, answered in order. Everything below was run rather
than reasoned about; where something could not be verified in this sandbox it
says so and says why.

---

## 1. Starting commit

`9c4e9dc` — *"Return context, publish to global, the standard response
experience and the collaboration loop"*, the head this phase was asked to
continue from. Confirmed before any change: branch `claude/vigilant-darwin-eohyi1`,
clean tree, local and remote in step.

## 2. Final commit

`1449990` and the report commit that follows it, on
`claude/vigilant-darwin-eohyi1`. Five commits in this phase:

| Commit | What it delivered |
|---|---|
| `1d943fd` | The export engine: contract, gather, plan, profile, population, style, results, calculation, authorize, audit, service, the API and migration `0016` |
| `fc2a936` | The two download buttons on every analysis surface and every Trace mode |
| `057dd65` | P1 chart interactions, period playback, scatter and bubble renderers |
| `0667f11` | The five-view query workspace, version comparison, and the Sector-Period Terrain |
| `1449990` | Theme coverage tests and the download history in the audit view |

## 3. Local/remote match

`git push -u origin claude/vigilant-darwin-eohyi1` after each commit; the branch
is at the same SHA locally and on the remote. No merge to `main`, no force-push,
no history rewritten, no pull request opened.

---

## 4. Every previously deferred P1 item

| Deferred item | Status | Where |
|---|---|---|
| Premium chart interactions (§47) | **Done** | One structured selection (`selection.ts`) behind legend filtering, series isolation, category picking, a row range, keyboard focus and Reset — which is what makes Reset genuinely reset. Full screen, chart/table toggle, palette selector and "Ask about this" in `chart-frame.tsx`. |
| Presentation preference per analysis (§47) | **Done** | `lib/presentation.ts`, keyed to the run so the next question still starts from the registry's judgement. Verified across a full page reload. |
| Period playback (§48) | **Done** | `playback.ts` + `period-playback.tsx`. Play, pause, scrub, speed, previous, next, compare, reset. Never autoplays; a reader who has asked for reduced motion gets no timer at all and keeps the manual controls. |
| Deeper Trace refinement (§49) | **Done** | The Mathematical Query workspace split into its five named views; version comparison built (`compare.ts` + `version-compare.tsx`). Story remains the default; Copy Query, upstream/downstream dimming, the issue navigator and the exact return context were already in place and are unchanged. |
| Theme gallery refinement (§50) | **Done, as an audit** | Coverage was already real — 34 tokens, no colour literal in any component. Two genuine gaps were in what was *checked*: border tokens and Trace edges were unverified, and three light themes had rules at 1.23–1.25 against their own surfaces. Nudged and now asserted. |
| Project/Investigation visual polish (§51) | **Done, as an audit + one addition** | The shared `PageHeader` is on 55 pages, `EmptyState` is used throughout, and no page carries its own colours. The one real gap was activity: the export history now appears in the analysis audit view. |
| Data Builder visual consistency (§52) | **Done, as an audit** | Domain library, Inbox, Dataset Family, Viewer, Column Profile, Schema Comparison, Relationship Map and Drift Review all draw from the same primitives and tokens. No data semantics touched. |
| Analysis Studio visual consistency (§53) | **Done, as an audit** | Method Library, Detail, Definition, Inputs, Query/Plan, Validation and Governance likewise. No methods added for count. |

## 5. Every previously deferred P2 item

| Deferred item | Status | Where |
|---|---|---|
| Genuine 3D / multidimensional views (§54) | **Two renderers, done** | **A. Risk Landscape** — `BubbleChart`: two measures as position, a third as point *area*, a governed band as colour. **B. Sector-Period Terrain** — `terrain.tsx`: a grid with the measure as colour, for the many-groups-over-many-periods shape the registry had been naming (heatmap / matrix / small-multiples) and could not draw. |
| Advanced period playback (§48) | **Done** | See above. |
| Additional meaningful visual experiments | **Done, narrowly** | `ScatterPlot` was added because the registry had been *choosing* a scatter and this build could not draw one, so those results fell silently back to a table. Nothing was added for count. |

**On "3D".** The terrain is flat, and that is a decision rather than a
shortfall. Nobody reads a value off a rotated 3D surface: perspective makes near
peaks look larger than far ones, occlusion hides whatever is behind the tallest
bar, and the reader ends up rotating to find a number they could have read
directly. So the third dimension is colour, the grid is exact, every cell
carries its figure on hover and by keyboard, and nothing is hidden behind
anything. §54's own requirements — 2D projection, table fallback, selection,
tooltip, zoom, reset, accessible description, lazy-load — are all met, and its
"do not block ordinary rendering if WebGL is unavailable" is met by there being
nothing to block.

---

## 6. Results Workbook architecture

`backend/exports/results.py`, built from a `Pack` that `gather.py` read out of
the persisted run. Three sheets:

* **RESULTS** — the exact final table: the interface's column order, its sort,
  its units in the headers, semantic number formats, and a `=SUBTOTAL(109,…)`
  total on additive columns only. A coverage percentage is never totalled.
* **SUMMARY** — the question, the scope, the measures, the provenance
  (run, Trace version, plan fingerprint, data version, build SHA) and any
  runtime warnings.
* **CHART** — written *only* where the visualisation registry chose a chart,
  the result is ≤ 60 rows, the columns are present, and Excel has a faithful
  equivalent. It references the RESULTS sheet's own cells; it never carries a
  second copy of the figures.

An empty result is a conclusion, not a blank sheet: the answer is printed where
the table would be.

## 7. Full Calculation Pack architecture

`backend/exports/calculation.py`, drawing on five readers, each with one job:

| Module | Reads |
|---|---|
| `gather.py` | The persisted run — result, plan, SQL, reconciliation, Trace, fingerprint. No engine call, no DuckDB query, no model call. |
| `plan.py` | The stored Analytical IR as an audit trail: scans, governed joins, filters, transformations, and what each step meant in English. |
| `profile.py` | §16's source statistics, measured at export time over the same governed data at the same period — and labelled as such. |
| `population.py` | §24's row-level extract: a read of the source at the recorded period and filters, refused rather than approximated where it could not stand in for the calculation population. |
| `style.py` | One styling vocabulary, shared with the results workbook. |

Three provenances, never blurred, because a reviewer's first question about any
figure is who measured it and when: **persisted** (the run's own record — every
analytical figure), **profiled** (measured when the workbook was built),
**derived** (arithmetic over the two). Anything the run did not record is
written as *"not recorded at run time"* rather than left blank, because a blank
cell in an audit pack reads as a zero.

## 8. Exact workbook sheet structures

**Results workbook** — `RESULTS`, `SUMMARY`, `CHART`.

**Calculation pack — 22 sheets, in this order:**

```
 1  COVER                        12  CALCULATION STEPS
 2  ANALYSIS REQUEST             13  INTERMEDIATE RESULTS
 3  EXECUTIVE SUMMARY            14  POPULATION EXTRACT  (or Population_001…
 4  DATA SOURCES                     with an EXTRACT INDEX when split)
 5  FIELDS USED                  15  FORMULAS & QUERY
 6  POPULATION & PERIOD          16  EXCEL RECONSTRUCTION
 7  SOURCE PROFILES              17  VALIDATION CHECKS
 8  RELATIONSHIPS & JOINS        18  INVARIANTS & RECONCILIATION
 9  JOIN RECONCILIATION          19  TRACE LEDGER
10  FILTERS & EXCLUSIONS         20  INTERPRETATION EVIDENCE
11  TRANSFORMATIONS              21  LIMITATIONS
                                 22  FINAL RESULTS
```

All twenty of §10's required sections, in §10's order, with the two additions
§10 permits between sections. COVER links to every sheet; every sheet links
back. FINAL RESULTS is always the last tab — asserted in the test suite and in
the browser acceptance.

## 9. Rating-wise EAD acceptance result

§33's mandatory example, run end to end in a browser against the live stack:

> **"Show IFRS 9 EAD by internal rating for the latest period."**

* Reads `ifrs9_staging` at Q2 2026, joins `portfolio_facility` on
  `account_id` (inner, one-to-one), then as-of joins `customer_ratings` on
  `customer_id` with `latest_on_or_before`, so no future rating is used.
* Ten internal grades. Total exported EAD **125,258.721 USD mn**.
* The source profile's own `ead` total for `ifrs9_staging` at Q2 2026 is
  **125,258.721 USD mn**. The parts sum to the whole exactly — difference 0.000,
  well inside tolerance.
* The measure is labelled *Exposure at default (USD mn)*, not the generic
  "Exposure": §32's requirement.

**This question did not work when the phase began**, and fixing it was
necessary rather than incidental. The planner's grouping regex ran off a
thirty-character phrase budget at *"…by internal rating **for the** latest
period"*, resolved no dimension, planned the question as a ranking of
facilities, and was then blocked by its own ordering invariant — because a plan
ordered by rating cannot satisfy a promise to rank by exposure. The dimension
was in the sentence the whole time; only the regex could not see past "for the".

## 10. Source profile / reconciliation behaviour

Profiles are computed **at export time**, because the runtime records the
*result* and the plan and does not stop to describe the tables on the way past —
and asking it to would slow every question down to serve a workbook most
questions never generate.

Two consequences, and the sheet states both rather than leaving a reader to
assume:

1. It is a profile of the **data**, never a recomputation of the **answer**.
   The analytical figures come only from the persisted run.
2. Where the catalogue version has moved since the run, or a Parquet file has
   been written since it finished, the profile says so above its own table and
   raises a WARNING row on VALIDATION CHECKS.

Per dataset: rows, distinct primary keys, duplicate keys, null keys, distinct
customers and accounts, the credit totals (exposure, ECL, coverage, PD, LGD,
DPD), a full numeric profile (count, nulls, null rate, sum where additive,
mean, median, standard deviation, min, p10, p25, p75, p90, p95, p99, max) and a
categorical profile with top values, frequencies and anything outside the
declared set. Ratios are never summed — the sheet says *"not additive"* where a
sum would be meaningless. Confidential identifiers are counted, never listed.

## 11. Join reconciliation behaviour

Per governed join: the relationship and its version, both sides, the keys, the
join type, the cardinality, the as-of rule, the semantic meaning, rows into the
join, rows in the right source, distinct and duplicate keys on each side, rows
after, matched and unmatched left rows, the row-multiplication factor, match %
and orphan %, warnings, and a PASS / WARNING / FAIL / SKIPPED status.

Two things are honestly absent and named as such rather than shown as zero:
**unmatched right-hand rows** and **value-level reconciliation at each join**
were not recorded when the analysis ran. The value reconciliation that *was*
recorded — that the parts sum to the whole in the final result — is on
INVARIANTS & RECONCILIATION. No sample of unmatched keys is included: those are
confidential customer and account identifiers, and §40 keeps them out.

## 12. Excel formula reconstruction behaviour

Where the analysis can be faithfully rebuilt, EXCEL RECONSTRUCTION writes **live
`SUMIF` / `AVERAGEIF` formulas** over the exported population, alongside the
runtime value, the difference, and a `=IF(ABS(D)<=0.01,"PASS","FAIL")` verdict —
per row and in total. Open the sheet and Excel recomputes it; if column D is not
zero, the workbook and the analysis disagree *visibly*.

The formula ranges come from where the extract writer actually put its header,
not from counting the preamble — an off-by-one there would reconcile against the
wrong rows while looking perfectly correct. Verified independently: all fifteen
sector totals from the exported population match the persisted runtime values
exactly.

Where a reconstruction would not be faithful — a joined analysis, a split
extract, a grouping Excel cannot express in one criterion — **no formula is
written**, and the sheet says which of those it was and points at the IR, the
SQL and the step-level row counts instead. §26 asks for a faithful
reconstruction or an honest refusal, not a plausible one.

## 13. Validation / invariant sheets

**VALIDATION CHECKS** carries one row per check with ID, step, rule, expected,
actual, tolerance, status, reason, impact, source and timestamp. Two kinds of
row, and the Source column always says which: checks the **run** recorded
(business invariants, join reconciliation, truncation, runtime warnings) and
checks measured **here** over the source data (primary-key uniqueness,
completeness, data-version drift). **SKIPPED never counts as PASS** — it is
listed so a reviewer can decide whether it matters, rather than discovering
later that it was never run.

**INVARIANTS & RECONCILIATION** carries the business invariants, the result
reconciliation against the plan's final step, the mathematical invariant that
the parts sum to the whole, evidence grounding, the causal-language check, and
unit, period and filter grounding — with final display eligibility stated. If a
mandatory invariant had failed the analysis would not have been displayed, and
the pack's cover would read FAILED.

## 14. Trace ledger / evidence sheets

**TRACE LEDGER** is the full Trace in order: sequence, node id, stage, type,
label, summary, status, upstream and downstream references, rows in and out,
duration, version or content hash, issue count and governed marking. It
reconciles to the Trace version named on the cover; a different version has its
own ledger and its own export.

**INTERPRETATION EVIDENCE** carries every user-visible statement with its
supporting fields, source result path, period, entity, validation and grounding
status, claim type and a causal check. **No model chain-of-thought appears in
the pack, here or anywhere else** — what is recorded is the evidence package and
the grounded statement written from it.

## 15. Permissions / redaction

`backend/exports/authorize.py` returns a `Decision`, never an HTTP response, so
a test, an audit row and the endpoint cannot disagree about what "shared with
me" means.

| Role | Results workbook | Full calculation pack |
|---|---|---|
| ADMINISTRATOR | Always | Always, with row-level data |
| DATA_STEWARD | Always | Always, with row-level data |
| ANALYST | Always | Analyses they ran, or were sent for review |
| VIEWER | Published or sent to them | Refused, with the reason |

Enforced in the backend. A Viewer who types the pack URL by hand is refused —
asserted directly, because hiding a button is not authorisation. Where the pack
is allowed but row-level access is not, the population is withheld and the
withholding is recorded on LIMITATIONS.

Never in a workbook: API keys, authorization headers, provider secrets, hidden
chain-of-thought, benchmark gold answers, fields outside permission, unrelated
sensitive columns. Bound parameters show a Parquet path from the dataset
onwards — the deployment's directory layout has no audit value and is a small
infrastructure disclosure. Both files are byte-scanned for secrets in the test
suite and again in the browser acceptance.

## 16. Export audit log

Migration `0016` adds `export_records`. Every attempt is written — **allowed,
denied or failed** — because a log of successes cannot answer "who tried", which
is the question an access review actually asks.

Each row: user, role, export type, run id, Trace version, timestamp, filename,
SHA-256 of the bytes served, size, row count, duration, datasets included,
authorization basis, refusal reason, redactions, and the full generation
manifest. Writing the log can never stop a download: a database outage is logged
loudly and the file is still served.

Surfaced in the product on the Trace's **Audit** mode — verified in a browser
with one ADMIN download and one VIEWER refusal, both recorded and both shown.

## 17. Large-workbook behaviour

* `EXCEL_MAX_ROWS` 1,048,576 and `EXCEL_MAX_COLUMNS` 16,384 are declared;
  `ROWS_PER_SHEET` is 250,000, well inside them.
* A population above `MAX_INLINE_POPULATION_ROWS` (100,000) is **refused before
  it is read** — the expensive case never loads — and the sheet says the size,
  the ceiling, and that a governed row-level extract should be requested
  instead.
* A population that must be split becomes `Population_001`, `Population_002`, …
  with an **EXTRACT INDEX** naming each sheet's row range. Asserted that a split
  extract loses no rows.
* Nothing is ever silently truncated: every path that omits data prints a
  sentence saying so.
* Generation is bounded by `GENERATION_TIMEOUT_SECONDS` (120) and checked at
  three points; exceeding it returns a 504 with an explanation, not a hung
  worker.

## 18. Analysis button placement

**`DOWNLOAD RESULTS`**, top right of the analysis header, with a spreadsheet
icon and the tooltip *"Download the final analysis result as Excel."*

Wired once where every answer is rendered rather than page by page:
`AnswerBlock` (the Cockpit answer, a thread, a project investigation),
`AnalyticalCard` (the analysis run detail, stress results, CRO lens tiles), the
saved-analysis list, and the lens panel. Metadata-only catalogue answers are
guarded out on `analysis_run_id` — they are not Analysis Runs and have no
results workbook to offer.

Browser-verified: present, visible, labelled `DOWNLOAD RESULTS`, and at x=1246
of 1485 — the right-hand side of the header.

## 19. Trace button placement

**`DOWNLOAD FULL CALCULATION`**, top right of the Trace header, with the
tooltip *"Download the full step-by-step calculation, data profile, joins,
validations, lineage and final result."* and the Trace version appended.

In the header itself rather than in a mode, so it is present in **Story,
Lineage, Landscape and Audit** alike — the mode is a way of reading one
analysis, not four analyses. All four verified in a browser.

## 20. Chart interactions

Legend filtering, series isolation (double-click), category picking by click or
by keyboard, a row range, Reset, full screen, chart/table toggle, palette
selector, and "Ask about this" — which carries what the reader was looking at
into the follow-up, so a question asked from a filtered chart is not answered
about the whole book.

All of it reads and writes **one** structured selection, which is what makes
Reset genuinely reset. Nothing computes: a hidden series is still in the result
and still in the export; a brushed range narrows what is drawn and never what
was calculated.

Browser-verified: a legend click hid a series and the status line said which;
two arrow presses and Enter picked out a category by keyboard; the table toggle
survived a full page reload.

## 21. Period playback

Play, pause, scrub, speed (0.5× to 4×), previous, next, compare two periods,
reset. Offered only where the result carries two or more periods — a play button
over a single quarter is a control that does nothing.

Never autoplays. Stops at the last period rather than looping. Scrubbing takes
over from playback. Comparing a period with itself turns comparison off. A
reader who has asked their operating system for reduced motion gets **no timer
at all** and keeps previous, next and scrub, which does everything Play does at
their own pace — and a reader who turns reduced motion on mid-playback does not
have to press Pause.

Presentation only: the cursor moves over rows the analysis already returned;
nothing is re-run.

## 22. 3D / multidimensional views

* **Risk Landscape** (`BubbleChart`) — EAD on x, a governed risk measure on y, a
  third measure as point **area** (not radius: doubling a radius quadruples the
  ink, and a reader comparing two bubbles reads the ink), and a governed band —
  stage, rating band — as colour. Four dimensions readable at a glance.
* **Sector-Period Terrain** (`terrain.tsx`) — groups down, periods across, the
  measure as colour, with zoom, reset, selection, tooltip, keyboard navigation,
  a table fallback and a spoken description of the grid's shape.

Lazy-loaded, as §54 asks. Bundle impact **measured, not asserted**: the terrain
chunk is **5.2 KB** and is not downloaded by a reader who never sees one.

Browser-verified: *"How has ECL by sector changed over the last two years?"*
chooses the terrain — *"15 series is too many to read on one axis"* — and draws
it, with no console errors.

## 23. Theme refinements

Eight themes, all token-driven. Every surface §50 lists is reached: charts
(eight slots), the Trace map (governed, interpretive, edge), highlighted SQL,
tables and their rules, workflow states, focus rings, warnings, and the semantic
risk colours that say whether a movement was adverse. **No component carries a
colour literal**, which is what makes a ninth theme a block of tokens rather
than a search through the codebase.

Accessibility is asserted, not judged by eye: **26 tests** across all eight
themes cover body, secondary and muted text, the accent and its contrast,
every status colour on its surface and on its own tint, both Trace node colours,
and — added this phase — **border and Trace-edge legibility** and the label on
the accent. Three light themes had rules at 1.23–1.25 against their own
surfaces, a hairline that disappears at ordinary laptop brightness; nudged to
clear a 1.3 floor, keeping each theme's hue.

**Exports deliberately do not follow the theme.** A workbook leaves the product:
it is forwarded, printed, and read in a room nobody here chose. Rendering it in
Midnight Boardroom would produce a black page that reads as a fault, and
rendering it in whatever the downloader happened to be using would mean two
people exporting the same analysis get files that look like different documents.
Both workbooks use one restrained institutional palette on every theme. This is
recorded in `lib/themes.ts` as a decision, not left as an omission.

## 24. Project / Investigation polish

Audited rather than rebuilt, because the design system is already applied
consistently: the shared `PageHeader` on 55 pages, the shared `EmptyState`
throughout, one type scale, no page-local colours, and the return-context
contract from the previous phase intact on every path.

One real gap found and closed: **activity**. The export history — who downloaded
what, at which Trace version, and who was refused — now appears in the analysis
audit view. Project-only Investigation isolation is unchanged and still asserted
by its own tests.

## 25. Data Builder polish

Audited: Domain library, Data Inbox, Dataset Family, Dataset Viewer, Column
Profile, Schema Comparison, Relationship Map, Drift Review and the quality and
warning states all draw from the same primitives and the same tokens, and pass
the extended contrast checks on all eight themes. **No data semantics were
touched** — not a definition, not an authority rule, not a relationship.

## 26. Analysis Studio polish

Audited: Method Library, Method Detail, Definition, Inputs, Query/Plan,
Validation, Version/Governance and the workflow review path are consistent with
the rest of the product. **No methods were added** — §53 asks not to add for
count, and nothing here needed one.

## 27. Back-navigation regression status

**No regression.** The return-context architecture built in the previous phase
(`lib/return-context.ts`, `lib/return-to.ts`) is untouched, and its 44 tests
still pass. The new Trace panels and the two download buttons are additive: the
export download is a `fetch`, not a navigation, so it cannot disturb the
history stack — which is one of the reasons it is a fetch.

## 28. Workflow regression status

**No regression.** The workflow service, the nine states, the recipient model,
the message thread and the notification vocabulary are unchanged. The reviewer
notification test that failed at the end of the previous phase — a real defect,
found only when stale shared records turned over — still passes, and its class
of problem is now addressed directly (item 35 and §58 below).

## 29. Backend test count

**1,990 collected, 1,990 passing, 0 failing, 8 skipped.** Includes 86 export
tests and 26 theme-contrast tests. Run in full after the last code change.

## 30. Frontend test count

**177 passing, 0 failing.** 42 added this phase: 18 for the selection reducer,
17 for the playback machine, 12 for version comparison, 8 for the download
helpers, 3 for presentation precedence, and 5 registry regressions.

## 31. Workbook test count

**86 export tests**, in four modules:

* `test_contract.py` (14) — filenames that survive Windows, sheet names inside
  Excel's 31 characters and unique, the period not repeated, the size ceilings,
  and the four refusals as four distinct answers.
* `test_workbooks.py` (31) — both workbooks opened with `openpyxl` and read:
  sheet order, required sections, cover links both ways, no hidden lineage
  column, live formula ranges verified against the exported rows, the §33
  regression end to end, and a byte scan for secrets.
* `test_export_api.py` (24) — headers, roles, refusals, failure codes, the audit
  log, and reproducibility across two downloads.
* `test_shapes.py` (17) — one dataset, many datasets, a certified method, an
  empty result, a run that does not exist, a clarification, a refusal, a source
  that cannot be profiled, sort order, units, number formats and the chart.

Every one runs its own analysis rather than asserting against records that
happen to exist, and the export log is truncated around each test.

## 32. Browser acceptance count

**12 browser checks + 19 workbook checks = 31, all passing**, against a live
stack. Preserved in the repository as
`scripts/acceptance/export_browser_acceptance.py` and
`scripts/acceptance/verify_workbooks.py`, so the next person can re-run them
rather than take this report's word for it.

Covered: the mandatory question; both buttons present, labelled and
right-aligned; the pack button in all four Trace modes; both files downloaded;
RESULTS first; SUMMARY present; every value matching the interface; all ten
required pack sections; the SQL that ran; FINAL RESULTS last; the rating-wise
total reconciling to the source profile; and no secrets in either file.

**On units.** The interface renders exposure as `usd bn` and shows `22.4`; the
workbook carries the governed unit `USD mn` and the figure `22,373.572`. Both
are labelled and both are right — the screen is for reading, the workbook is the
record — so the acceptance script puts them in the same unit before comparing
rather than pretending the rounded figure is the exact one.

## 33. Docker result

**Partial, and the limitation is this sandbox's, not the compose file's.**

* `docker compose config` — **valid**.
* `docker compose build` — **fails**, and only here. `pip` inside the container
  cannot verify this sandbox's TLS-intercepting proxy:
  `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`
  while fetching `https://pypi.org/simple/dash/`. The host's `pip` works because
  its CA bundle is configured outside the container.

§59 says not to rewrite networking on the strength of a sandbox issue, and
disabling TLS verification in a shipped image would be a real security
regression on a Windows host. So the Dockerfile is unchanged, and what *could*
be verified was:

* **The declared requirements install cleanly in a container** — proved with a
  throwaway image carrying the sandbox CA (built, used, deleted; nothing
  committed).
* **Both workbooks generate inside that container**, from the repository mounted
  read-only, with no database and no analytics lake: 22 sheets, COVER first,
  FINAL RESULTS last, figures correct, catalogue enrichment degrading gracefully
  exactly as designed.
* `openpyxl==3.1.5` is a declared dependency and was already in the image.
* Filenames are Windows-safe by construction and by test — `<>:"/\|?*` and
  control characters are stripped, and the period is not duplicated.
* No local Python or Node dependency is introduced by this phase.

**Expected to build normally on the user's Windows Docker host**, where there is
no intercepting proxy. That is the one item in this report that still needs
confirming there.

## 34. Bundle / performance impact

**Export generation**, measured on this machine over three real runs:

| Run | Workbook | Time | Size | Peak memory |
|---|---|---|---|---|
| 2657 (1 dataset, 15 rows) | results | 61 ms | 9.8 KB | 0.7 MB |
| 2657 | calculation pack | 6.9 s | 375 KB | 27 MB |
| 3070 (3 datasets, 10 rows) | results | 61 ms | 7.7 KB | 0.7 MB |
| 3070 | calculation pack | 2.1 s | 122 KB | 6.8 MB |
| 3097 (3 datasets, joined) | results | 56 ms | 7.8 KB | 0.7 MB |
| 3097 | calculation pack | 8.4 s | 429 KB | 32 MB |

The pack's cost is dominated by the population extract — 16,346 rows written
cell by cell — and by profiling three source datasets. Both are bounded:
`GENERATION_TIMEOUT_SECONDS` 120, `MAX_INLINE_POPULATION_ROWS` 100,000.

**Frontend**: total client chunks 2.5 MB; the largest is 404 KB. The terrain is
lazy-loaded at **5.2 KB** and is not fetched unless drawn. Production build
clean.

## 35. Explicit deferred items

Three, each a decision with a reason rather than an omission:

1. **The export job API (§37).** Generation is synchronous with a size guard
   rather than POST-job / GET-status / GET-file. The ceiling is enforced *before*
   any reading happens, generation is time-bounded, and the browser fetches
   asynchronously and shows "Preparing workbook…" — which is what §37's
   user-visible requirement actually states. A job queue with no worker
   infrastructure behind it would be a status endpoint that lies. When this
   product grows a task runner, `service.generate()` is the function that runs
   inside the job, unchanged.

2. **A rotating 3D surface (§54).** Deliberately not built; the reasoning is in
   item 5 and in `terrain.tsx`'s own docstring. Two real renderers were
   delivered, which is what §54 asks for at minimum.

3. **Docker build verification (§59).** Blocked by this sandbox's TLS proxy, not
   by the compose file. Everything verifiable was verified; see item 33.

## 36. Intelligence and governance stack — preserved

Explicitly confirmed. **Not one line changed** in: the Anthropic provider
integration, provider telemetry, the live-verification architecture,
model-role configuration, the Intelligence Factory, benchmark and gold-answer
isolation, certification semantics, the semantic ontology, Data Builder semantic
definitions or authority rules, Analysis Studio methodology definitions,
Analytical IR semantics, the safe SQL compiler, the approved Python kernels, the
deterministic analytical calculations, the business invariants, the grounding
rules, the synthetic data generation, the governed relationship semantics, the
Project/Investigation/Analysis hierarchy, or the return-context architecture.

Backend changes were confined to what §0 permits:

* `backend/exports/` — entirely new; workbook generation, authorization, audit.
* `backend/api/routers/exports.py` — new; the download endpoints.
* `backend/models/platform.py` and `alembic/0016` — the export audit table only.
* `backend/api/main.py` — router registration, and `expose_headers` so a browser
  can read `Content-Disposition` cross-origin.
* `backend/data_access/` — a read-only `profile()` on the DAL, because the data
  access layer is the only module permitted to speak SQL and profiling is
  measurement, not analysis.
* `backend/orchestration/presentation.py` — untouched.

**One intelligence-layer change**, and it is a strengthening the brief required:
`_GROUPED_BY` in `analysis_planner.py` now sees past a trailing time phrase, so
§33's mandatory example resolves its dimension. No semantics were weakened — a
question that previously produced *no* dimension now produces the correct one,
and the ordering invariant that blocked it is unchanged and still enforcing.

Two visualisation-registry corrections, both in the frontend presentation layer
and neither touching a calculation: a governed code column typed `text` is no
longer read as a measure, and a grouped-by subject is no longer read as a named
entity.

## 37. No live Anthropic calls, no API credits

Explicitly confirmed. `ANTHROPIC_API_KEY` was never read, inspected or printed.
Every run in this phase used `AI_PROVIDER=offline`; the backend's own health
endpoint reports `ai_provider: not_configured` throughout, and every answer in
the browser acceptance was produced by the deterministic semantic planner. No
live verification was run. **No API credits were consumed.**

---

## Where to look

| | |
|---|---|
| The export engine | `backend/exports/` — twelve modules, each with a docstring saying what it will not do and why |
| The endpoints | `backend/api/routers/exports.py` |
| The buttons | `frontend/src/components/exports/download.tsx` |
| Chart interaction | `frontend/src/components/analytics/{selection,chart-frame}.tsx` |
| Period playback | `frontend/src/components/analytics/{playback.ts,period-playback.tsx}` |
| The two dimensional views | `frontend/src/components/analytics/{charts.tsx,terrain.tsx}` |
| Version comparison | `frontend/src/components/trace/{compare.ts,version-compare.tsx}` |
| Re-running the acceptance | `scripts/acceptance/README.md` |

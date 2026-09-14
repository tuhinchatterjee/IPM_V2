# Early Warning — post-certification product UX and data-domain correction

Branch `claude/early-warning-rebuild-v2-3lnttn`. Not merged to main.

**Starting commit** `e7c42974` — the certified baseline (8/8 certified,
VERDICT: CERTIFIED, live provider).
**Final commit** `ad38bef`.

Seven commits, 42 files, +6,930 / −287.

---

## 1. Starting commit

`e7c42974` "Count the obligors a ranking leaves out, rather than asking Opus
to". The last commit of the live-provider certification round: 8/8 certified.

## 2. Final commit

`ad38bef` "Register a domain without letting it answer other domains'
questions".

## 3. Commits, in order

| Commit | What it closed |
|---|---|
| `6383745` | The false-timeout defect: a turn is a thing with a state, and the backend owns it |
| `1cc38aa` | Data Builder showed Early Warning as Empty: the domain is now registered |
| `907cc99` | The domain rule is enforced at the data-access door, and what a turn read is recorded |
| `6df5d93` | Filtering the book rather than the page; every measure from one scope; the Excel export; the scope into the chat |
| `cd41eae` | A dataset counted twice because it is in two lists |
| `66d788c` | A thread with an address, so Back returns to the conversation |
| `ad38bef` | Three regressions the full sweep found from putting a new domain in the general catalogue |

## 4. Files changed

**New backend** — `backend/early_warning/domain.py`,
`registration.py`, `filterspec.py`, `dashboard_view.py`, `export.py`;
`scripts/register_early_warning_domain.py`.

**Modified backend** — `api/routers/early_warning_v2.py`,
`conversation/{live,pipeline,packet,validate,normalise}.py`,
`{v2_service,grain,ask}.py`, `scripts/build_early_warning_v2.py`.

**New frontend** — `components/early-warning/{turn.ts, use-turn.ts,
filters.ts, filter-bar.tsx, thread-store.ts}`.

**Modified frontend** — `components/early-warning/{ews-chat.tsx,
v2-portfolio.tsx}`, `lib/{api.ts, downloads.ts}`,
`components/exports/download.tsx`,
`app/data-builder/domain/[...domain]/page.tsx`.

**New tests** — seven backend files (125 tests), three frontend files
(50 tests).

## 5. The timer defect — root cause

`frontend/src/lib/api.ts::earlyWarningV2Ask` carried `timeoutMs: 60_000` on a
**synchronous** POST that takes forty to seventy-five seconds against a
certified provider. At sixty seconds the fetch aborted and the client's own
abort handler produced

> The backend did not respond within 60 seconds.

in red. The backend kept running, finished, and wrote its answer into the
turn document — which the separate `/ask/progress` poll then read and
rendered underneath the banner. Hence a timeout and an answer side by side,
both rendered by the same component, neither aware of the other.

The wrong one was the browser's. **A fetch timeout is a fact about a socket;
whether a credit analysis succeeded is not a question a socket can answer.**

Raising 60 to 90 was explicitly not the fix and was not done. The number is
gone entirely.

## 6. The new request lifecycle, exactly

```
POST /early-warning/v2/ask/start
    -> creates the turn, spawns a worker thread, returns in < 1s:
       { turn_id, state: "running", thread_id, question, version }

POST /early-warning/v2/ask/progress   (polled)
    -> { watching, state: "running",   steps… }
    -> { watching, state: "completed", answer: {…} }
    -> { watching, state: "failed",    failure: "…" }
    -> { watching: false, state: "" }        (a turn this worker never saw)
```

* The **thread appears the moment the id comes back** — the question, then the
  progress panel under it.
* **Only the backend moves a turn out of `running`.** `turn.ts` is a pure
  reducer with three rules: the backend owns the state, a poll that did not
  arrive is a missed poll (not a failed analysis), and a terminal state stays.
* After three consecutive missed polls the panel says **reconnecting**; the
  turn stays `running`. It takes 120 misses before it says unreachable, and it
  still never says the analysis failed.
* An error is scoped to its **thread_id + turn_id**. A later turn cannot
  inherit an earlier one's failure.
* Polling **re-runs nothing**. The worker runs once; a poll reads a document.
* `/ask` is untouched and still answers synchronously, so the certification
  harness drives the same pipeline by the same path it always did.
* A failure message is written for a credit officer. A provider URL, status
  code, key fragment, Python exception type or traceback never reaches the
  screen — asserted behaviourally by raising a `RuntimeError` carrying all of
  those and checking the rendered failure.

## 7. Proof that a turn over sixty seconds no longer shows a false timeout

Four independent proofs:

1. **`tests/api/test_ask_lifecycle.py`** — a simulated 75-second turn stays
   `running` throughout and settles `completed`; a running turn never reports
   failure; the answer from `/ask/start` is identical to the synchronous one.
2. **`frontend/src/components/early-warning/__tests__/turn.test.ts`** —
   `stays running past sixty seconds, and past any other number` iterates
   30s, 59s, 60.001s, 75s, 100s and 300s; and
   `never shows an answer and an error at once` holds the invariant directly.
3. **The 60,000 is gone.** `earlyWarningV2AskStart` has a 20-second timeout
   because it only creates a turn; the polling path has no answer-shaped
   timeout at all.
4. **Browser** — asking a real question shows the question and the progress
   panel at once, and no timeout banner appears at any point.

## 8. The thread UX

Empty state: a large composer near the top with suggestion chips, plus the
scope chip when the dashboard is filtered.

On the first Ask: the thread appears, the question renders immediately, the
progress panel opens under it, and the composer moves to the bottom and stays
there. Chronological, oldest at the top. Enter submits, Shift+Enter is a
newline. Auto-scroll only while the reader is within 80px of the bottom;
scrolling up to read stops it. "New thread" starts a new conversation and
leaves the old one where it is.

## 9. Composer movement

One `<Composer>` rendered in two places: centred in the `ews-chat-empty`
section, and in a sticky footer inside `ews-chat-thread`. Not two composers —
the same element, so a half-typed question survives the move.

## 10. The filter implementation

`backend/early_warning/filterspec.py` is the typed contract. Eleven
filterable columns from one registry the API publishes, so the screen builds
its controls from the contract:

| Column | Kind |
|---|---|
| `customer` | text (literal, not a pattern) |
| `segment`, `ews_band`, `ta_band`, `classifier_band`, `dominant_driver` | multi-select |
| `exposure` (SAR m), `dpd` (days), `ews_score`, `ta_score`, `classifier_score` | numeric range |

* **Server-side over the whole published month**, never the fetched page.
* An **ungoverned filter is refused (422) with the columns that do exist**,
  not ignored — ignoring it draws a chip for a filter that was never applied.
* An **impossible range is refused**, because an empty table is
  indistinguishable from a finding.
* Active-filter chips come **from the server**, describing what it actually
  applied. Each clears individually; "Clear all" clears every filter and
  leaves the month, the sort and the page size alone.
* The result count is the **matched population** — "52 of 300 obligors match",
  never the size of the fetch.
* Sorting and paging are server-side. Any filter change returns to page one.
* The filter is in the address, so a narrowed view is shareable and walk-back-
  able. Legacy `?band=` / `?segment=` links are seeded once and migrated.

## 11. Filtered chart semantics

Every measure on the screen is a projection of **one** filtered frame:

```
period -> borrower_month -> spec.apply()  ->  kpis
                                          ->  distribution
                                          ->  trend
                                          ->  sort -> page -> rows
                                          ->  (export: the whole thing)
```

`test_every_measure_describes_the_same_population` asserts that the KPI
count, the distribution sum, the row count and the trend cohort are all the
same number.

Band percentages are of the **filtered** population, and a band the filter
excluded is reported at **zero rather than dropped** — a reader who filtered
to HIGH should see four empty bands, not a chart that silently became one bar.

**The trend uses current-snapshot cohort semantics (§8).** The obligors
matching now are anchored at the as-of month and tracked BACKWARD; membership
is fixed, so a movement in the line is a movement in those obligors rather
than a change in who is being counted. The reply carries
`basis: "current_snapshot_cohort"`, a `cohort_size`, and a `note` the chart
prints. Unfiltered, the basis is `whole_book` and the note says so. A cohort
trend presented as a portfolio trend would be a survivorship claim nobody
made.

Empty result: a named empty state — "Nothing in 2026-06 matches days past due
at least 99,999 days" — with a Clear-all action, not a blank table.

## 12. The Excel export

`POST /early-warning/v2/dashboard/export`, same FilterSpec, same as-of month,
same sort.

* A **real XLSX** (openpyxl): `PK` magic, `…spreadsheetml.sheet` media type.
* **Numbers are numbers.** Exposure and scores arrive as floats with number
  formats, DPD and stage as integers. Asserted per column by type.
* Frozen, auto-filtered header row; headings in words ("Early Warning band",
  not `ews_band`).
* **The complete filtered result**, not the page: asserted against the
  screen's `row_count` while the screen shows five.
* A **`View` sheet**: as-of month, obligors in the file, obligors matching,
  obligors published that month, the scope in a sentence, every active filter,
  the sort, who exported it and when, and the descriptive-not-predictive
  basis.
* Filename says what it is:
  `early-warning_2026-06_very-high_10-obligors.xlsx`. Sanitised — a name
  containing `/ \ : * ? " < > |` cannot reach the disk.
* Guarded **exactly** as the dashboard read is: asserted across five roles, no
  role may download what it may not see.

Browser-verified: clicking Download Excel on a filtered screen produced that
filename, two sheets and ten rows for a ten-obligor filter.

## 13. The Data Builder defect — root cause

```
Early Warning   datasets=0  rows=0  periods=0
catalog entries matching "early": []
```

`backend/services/data_domains.py` declared the business domain and claimed
the catalogue heading "Early Warning". `scripts/build_early_warning_v2.py`
wrote parquet into `data/analytics/early_warning_*` — and registered
**nothing** in `metadata/catalog.json`.

So the chat, which reads the parquet, answered from three hundred obligors,
and Data Builder, which reads the catalogue, reported an empty domain. **Both
were telling the truth about the thing they read.** The card was not lying; it
was correctly reporting an unregistered domain.

## 14. The corrected counts, read live

```
Early Warning                             3 datasets   38,790 rows   2,554 fields   32 periods
  early_warning_borrower_month             6,000 rows   2,527 fields   2024-11..2026-06
  early_warning_signal_observation        32,282 rows      19 fields   2024-11..2026-06
  early_warning_external_event_synthetic     508 rows       8 fields   2023-11..2026-06
```

300 obligors × 20 months = 6,000 borrower-month rows.

The 2,527 borrower-month fields: Signal Inventory 2,364 · Sub-categories 88 ·
Layer/Dimension Outputs 17 · Workflow and Lineage 14 · Final Early Warning 11
· Matrix and Notches 10 · Customer 8 · Movement 8 · Core Credit Inputs 7.

**Nothing is hard-coded.** `test_the_field_count_is_not_a_number_written_down_anywhere`
greps the registration module for 2527, 2521, 6000 and 6,000 and fails if any
appears. Periods and row counts are read from the lake on every request,
exactly as for every other dataset — so the module can never make the screen
claim a number the data does not support, and on an unbuilt environment the
domain still reads empty, which is then the honest answer.

The external-event dataset spans 32 months because its L3 feed starts in
2023-11; the scored domain is the 20 contiguous months.

## 15. The canonical domain contract

`backend/early_warning/domain.py` is the single definition — `DOMAIN`,
`DOMAIN_ID`, and the three dataset names. Everything else reads it:

| Surface | Reads |
|---|---|
| Data Builder registration | `registration.py` → `dom.DOMAIN`, `dom.*` names |
| Planner context | `grain.py` → `dom.DOMAIN_ID`, `dom.DATASETS` |
| Validator | `validate.ALLOWED_DOMAIN`, `ALLOWED_DATASETS` |
| Executor / all data access | `v2_service._load` → `dom.require()` |
| Field dictionary | `registration._field_entries()` generates from it |
| Dashboard filters & export | the same dictionary and the same datasets |

`test_every_surface_reads_the_same_definition` asserts all six agree.

Six copies of three names is not agreement; it is six chances to differ.

The datasets also declare **their own portfolio scope**, `EARLY_WARNING` — a
third book alongside the credit book and Borrower 360. They are a derived
copy of both: every non-behavioural field is a governed copy of something
those books already hold, as it stood when the score was computed. So a
general question does not reach for them, which is the same statement the
domain lock makes in the other direction. See §22 for what happened when they
were first registered without it.

## 16. Proof that chat cannot execute outside the Early Warning domain

**Enforced at the door.** `v2_service._load` is the single function every
Early Warning figure is read through — dashboard tile, chat answer, exported
row, report table — so `dom.require()` sits there rather than in the callers.
A caller can be new; the door cannot.

An **allow-list of three**, not a deny-list. A deny-list is a list somebody
has to remember to extend, and the dataset it does not name is the one that
gets read.

Verified refused, live and in tests: `corporate_borrower_360`,
`corporate_ifrs9`, `corporate_financials`, `corporate_ratings`,
`corporate_supply_chain`, `corporate_exposure_network`,
`retail_behavioral_scorecard_monthly_validation`,
`retail_application_scorecard_development_reference`, **and a dataset name
invented inside the test** — the case a deny-list passes only until somebody
builds it.

The refusal is a `PermissionError` subclass, so a caller cannot mistake it for
a typo to correct and retry, and it says why: an upstream dataset has already
fed Early Warning — the snapshot holds a governed copy of the rating, the
stage, the utilisation and the arrears as they stood when the score was
computed — so reading it again reads the same fact from two places that can
disagree.

Four further layers:

* The **planner schema** has one legal `domain` value.
* The **validator** refuses any other, **not repairably** — a repair that
  rewrote the domain would make the refusal cosmetic.
* The pipeline imports **nothing** from `backend.corporate` or retail
  (asserted by import inspection).
* **The chat is not a second door.** A `dashboard_scope` posted to `/ask` or
  `/ask/start` is validated through the same FilterSpec; an ungoverned column
  is refused 422. Verified live.

And enforcement is now **observed rather than asserted**: `dom.recording()`
collects the datasets each turn actually touched, and the pipeline writes them
onto the turn and its result packet, so a trace states which datasets an
answer came from. Context-local, because a turn runs on its own thread and a
process-wide list would credit one turn with another's reads.

## 17. Permanent registration (§18)

`scripts/build_early_warning_v2.py` calls `registration.publish()` as its last
step, so a rebuild republishes rather than drifting.
`test_the_build_registers_as_part_of_building` fails if that step is removed.

`publish()` **merges** — a build that replaced `catalog.json` would publish
Early Warning by un-publishing the bank. It then drops the catalogue cache,
invalidates the metadata reader, and runs Data Builder's own idempotent
bundled-catalogue sync so the governance tables agree with the file. No second
piece of code inserts `DatasetDefinition` rows behind a steward's back.

`scripts/register_early_warning_domain.py` is the deterministic reconciliation
path for an environment whose parquet is present and whose catalogue is older
than it. `--check` exits non-zero when the domain is not registered, so a
deployment can ask the question rather than discovering the answer on a
screen. Running it twice leaves the catalogue byte-identical.

## 18. Dashboard scope into the chat

A reader narrowed to fifty-two obligors who typed "how many of these are
deteriorating?" was answered about three hundred.

The filter now travels with the question as the **same governed FilterSpec** —
structured, not prose, because a scope reconstructed from a sentence can be
read back wrong and this one is already exact. Two rules, pulling in opposite
directions on purpose:

* **Snapshotted at thread start (§42).** A thread whose scope followed the
  live filter would make its own history unreadable — the answer three turns
  up was about the population of three turns ago. Only a new thread takes a
  new snapshot.
* **An explicit question overrides it.** "Which obligors are at very high
  risk?" asked from a HIGH-filtered screen answers about VERY_HIGH. The filter
  says what the reader is looking at; the sentence says what they are asking
  about.

A single band or segment also reaches the request reader as a band or segment,
which is what it already knew how to inherit. Two bands do NOT collapse to the
first — "High and Very High" answered as "High" is a narrower population
presented as the one that was asked for.

The chat shows its scope: **"Asked about early warning band Very High"**.

## 19. Browser UAT

Real Chromium, real backend, real front end.

| Suite | Result |
|---|---|
| Filter bar, counts, chips, clear-all, empty state, overflow, console | **ALL PASS** (14 checks) |
| Data Builder card, domain page, dataset detail, chat thread mode, scope chip | **ALL PASS** (15 checks) |
| Shared filtered link, legacy `?band=` migration, real file download | **ALL PASS** (9 checks) |
| Thread in the address, Back into it, Back out of it, link reopens it | **ALL PASS** (8 checks) |
| Five pages × three viewports (1440, 1366, 390) | **CLEAN** — no console errors, no page errors, no horizontal overflow, nothing blank |

Sampled evidence: `"300 of 300 obligors"` unfiltered → `"10 of 300 obligors
match"` on Very High; KPI 19.5 → 95.0; URL
`?ews_band=VERY_HIGH`; download
`early-warning_2026-06_very-high_10-obligors.xlsx` with two sheets and ten
rows.

## 20. Automated test counts

**Backend, new:** 130 tests.

| File | Tests |
|---|---|
| `tests/early_warning/test_dashboard_filters.py` | 34 |
| `tests/early_warning/test_domain_enforcement.py` | 25 |
| `tests/early_warning/test_export.py` | 17 |
| `tests/early_warning/test_registration.py` | 20 |
| `tests/api/test_ask_lifecycle.py` | 13 |
| `tests/early_warning/test_dashboard_scope_in_chat.py` | 12 |
| `tests/api/test_dashboard_api.py` | 9 |

**Frontend, new:** 50 tests — `turn.test.ts` 15, `filters.test.ts` 23,
`thread-store.test.ts` 12.

**Frontend suite: 479/479 pass** (was 444 at the certified baseline).

## 21. Frontend build

`npx tsc --noEmit` clean. `npx eslint src --max-warnings=0` clean.
`npm run build` exits 0.

## 22. Backend regression

`tests/early_warning/`, `tests/api/`, `tests/orchestration/` and
`tests/evals/` all pass.

**The full `tests/` sweep found three regressions this change had caused
outside those suites, and they are the most useful thing it produced.**
Registering Early Warning put three datasets into the general catalogue for
the first time, and three cross-cutting invariants caught what that did:

1. **`tests/data_access/test_dal.py`** — the registration published the Early
   Warning dictionary's own type names, and the dictionary has a richer
   vocabulary than the catalogue: it distinguishes a closed `category` (a
   severity band) from a free `string`. 262 fields arrived carrying a type no
   catalogue reader can interpret. Mapped down on the way in; the
   distinction still exists where the conversation reads it.

2. **`tests/corporate/test_scope_separation.py`** — the serious one.
   *"What is the observed default rate by score band?"* — a **retail
   scorecard** question — began leading with `early_warning_borrower_month`.
   Two and a half thousand fields covering every signal, classifier, trigger,
   node, layer and notch mention almost every word a credit question can
   contain, so on word overlap alone the snapshots outscored the dataset that
   actually answers one.

   Fixed with the mechanism B44 built for exactly this: the Early Warning
   snapshots declare **their own portfolio scope**, `EARLY_WARNING`. They are
   a derived copy of the other two books, so a general question does not
   reach for them — the same statement the domain lock makes in the other
   direction, and it hides nothing: they stay governed, visible in Data
   Builder, and read by the Early Warning product through its own path.
   `test_the_catalogue_holds_both_books` now asserts against the catalogue's
   own `PORTFOLIO_SCOPES` rather than a literal pair it would have to be
   edited for.

3. **`tests/brain/test_corpus.py`** — the opposite failure. A governed
   dataset with no declared measure is one the Teaching Factory silently
   skips, so a registered domain nobody can ask a question about is a domain
   that does not exist. Eleven measures and nine dimensions are now declared
   for the two scored datasets — the score, its two composing dimensions, the
   anchor, exposure, DPD, utilisation and evidence counts, not the whole model
   surface. The external-event feed is exempted **by name** on the existing
   event-log list, because "no measure" and "somebody forgot to register its
   measures" look identical from outside and only one is acceptable.

All three now have regression tests inside
`tests/early_warning/test_registration.py`, where the registration is — so
the next person to touch it finds out there rather than four suites away.

One stale assertion was also updated rather than worked around:
`test_an_unknown_turn_is_not_an_error` compared `/ask/progress` to an exact
dict and the reply gained a `state` field the reducer reads. The test now
asserts the field and that it is empty for a turn nobody has heard of.

### Four failures in the full sweep are NOT from this change

Proved by unregistering the domain from both the catalogue file and the
governance tables and re-running: these four fail either way.

* `tests/docs/test_feature_matrix.py` (two tests) — the committed matrix was
  generated at commit `08922e9` and has not been regenerated since; it expects
  a `/early-warning/_legacy-signals` route that no longer exists.
* `tests/proof/test_fresh_clone_acceptance.py::…does_not_merge_two_books` —
  its own guard fires: this container's `metadata/catalog.json` holds 55
  bundled datasets and **no `corporate_*` entries at all** (they come from the
  database), so no domain in the FILE spans two scopes and the test reports
  that it is not exercising its distinction.
* `tests/presentation/test_decimal_contract.py` and
  `tests/proof/test_zero_tolerance.py::test_float_debris` — both run
  `scripts/check_decimals.py`, which flags `backend/orchestration/rubric.py:355`.
  That file was last touched at `49f33d3`, before the certified baseline.

None is in the Early Warning path and none is fixed here.

## 23. Rawabi proof

`tests/early_warning/test_rawabi_regression.py::test_rawabi_end_to_end_reproduces_56_medium`
**passes**: EWS 56.0, band MEDIUM, from the workbook's own worked example.

Nothing in this change touched the methodology. 123 signals / 105 scored / 18
dropped-merged-replaced, 77 T&A, 46 C, 23 classifiers, 67 triggers, 5
accelerator dimensions, 22 sub-category nodes, the weights, the 5×5 anchor
matrix, the five notches, the caps and overrides are all unchanged. The
certified reasoning architecture — Sonnet Pass 1/2, Opus functionality
selection, Opus analysis plan, governed validation, governed execution, result
packet, Opus sufficiency review, Opus final interpretation, Sonnet summary
update — is unchanged, along with the model-call ledger, the Standard/Deep
budgets, the closing-stage reserve, the execution ceilings,
`execution_declined`, the deterministic fallback, cross-product routing,
numeric grounding, the governed derived-claim contract, the `fact_ref`
contract, movement claims, the movement census, ranking coverage and the
server-owned presentation derivations.

## 24. Live certification status

**Live recertification has NOT been run, and it is required.**

There is no Anthropic credential in this container, and none should be put
here. `scripts/certify_early_warning_live.py` run without one **refuses**
rather than reporting a pass:

> No AI provider is configured, so nothing here can be certified.

The chat's request lifecycle changed — the screen now starts a turn and polls
it instead of holding one synchronous POST — so the 8/8 must be re-established
against a live provider before this is called certified. The pipeline itself
is byte-identical on that path (`/ask` is untouched and the certification
harness drives it directly), and every architecture test passes against the
stub provider, but that is evidence, not certification.

**Run on your Mac, from the repository root:**

```bash
read -rs -p "Anthropic API key: " ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY && echo
export AI_PROVIDER=anthropic
.venv/bin/python scripts/certify_early_warning_live.py
unset ANTHROPIC_API_KEY
```

`read -rs` keeps the key off the screen and out of shell history. The script
never reads, prints, logs or writes the value. A single case can be re-run
with `--case LIVE-5`.

The acceptance criteria were not weakened. Target remains **8/8 certified,
VERDICT: CERTIFIED**.

## 25. Known limitations

1. **Live certification outstanding**, as above. This is the one blocking item.
2. **Thread persistence is per-tab.** `sessionStorage` ends with the tab —
   the right lifetime for "I pressed Back", the wrong one for "I'll pick this
   up on Monday". Keeping a thread beyond that is what saving it to
   Investigations already does, visibly and deliberately. A server-side EWS
   thread store would be a larger change touching the certified persistence
   path and was not undertaken.
3. **The dataset dictionary page ships 1.4 MB** for
   `early_warning_borrower_month` — 2,527 field definitions in one payload. It
   renders in ~50 ms and is only that page, but it should be paged if the
   signal inventory grows.
4. **The trend recomputes per month** when filtered: twenty
   `borrower_month` reads per request, each cached in-process. Fine at 300
   obligors; a real book would want a single grouped pass.
5. **The external-event dataset spans 32 months** against the scored domain's
   20. Honest, and visible on the domain card as a wider period range than the
   scored months.
6. **The "1 Issue" badge could not be reproduced.** Across five pages at three
   viewports the Next.js dev indicator portal is empty and there are zero
   console errors and zero page errors. The most likely origin is the dev-tools
   issue counter registering the sixty-second fetch abort described in §5,
   which no longer occurs. If it reappears, the reproduction wanted is the
   page, the viewport and whether the browser console shows anything.
7. **Multi-select facets do not narrow with the filter** — deliberately. A
   segment control that emptied itself as soon as a segment was chosen is a
   control a reader cannot change their mind with.

---

## Defects found and fixed while building this

Four that were not in the brief:

* **`str.contains` treats its argument as a regular expression.** The customer
  search five-hundred-ed on a bracket or a backslash and quietly matched
  something else on a `|`. "Al-Rajhi (Holding)" is an ordinary customer name.
  Literal now.
* **`resolve_groups` remembered where a match began, not the span it
  covered**, so "high" was read out of the middle of "very high" — and "which
  obligors are at very high risk?" resolved to two bands and was answered as a
  **comparison of Very High against High**. A question the reader did not ask,
  from words they did not write.
* **A dataset in two lists was counted twice.** The domain page read "Datasets
  6" above a table of three; the table already deduplicated and the tab count
  did not. Registering Early Warning, whose datasets are now in both lists, is
  what made a latent off-by-a-whole-list visible.
* **A component that owned the query string carried an allow-list of two
  keys.** The chat pushed `?thread=` and the next render deleted it, so Back
  returned to a thread id that was no longer anywhere. A component that writes
  the whole query string owns every key in it, including ones it has never
  heard of.

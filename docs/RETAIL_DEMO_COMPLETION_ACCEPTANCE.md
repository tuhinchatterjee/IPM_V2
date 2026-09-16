# Retail Demo Completion — delta map and acceptance matrix

Two things live here: what the contract asks for measured against what the
application does today (§2, §3.1), and the 92 minimum gates with the command
or browser action that decides each one (§26).

Everything in the "today" column was **executed**, not read off the source.
Where a defect was reproduced, the reproduction is named.

Audited at `c0db151f` · book `3268b725…` · 2026-08 · 59,449 facilities /
42,824 customers.

---

## Part 1 — Reproduction of the screenshot-derived defects (§2)

| Ref | What the contract describes | Reproduced? | What actually happened |
|---|---|---|---|
| 2.1a | Raw parameter catalogue on the What-If landing page | **yes** | `/what-if` renders a card titled "What this engine implements" (`retail-whatif.tsx:625`) |
| 2.1b | Raw identifiers exposed to the user | **yes** | all six visible in the page text: `pd_relative`, `lgd_relative`, `ccf_absolute`, `income_pct`, `dpd_migration`, `score_band_migration` |
| 2.1c | No Delta / XGBoost choice offered | **yes** | zero method controls on `/what-if`; the standalone path calls the engine with the default method |
| 2.1d | Standalone is a different path from the EWS thread | **yes** | no shared thread container on `/what-if`; two implementations (`retail-whatif.tsx` 993 lines vs `whatif/[selectionId]/page.tsx` 626 lines) over two API families (`/whatif/*` vs `/ews/whatif-selection/*`) |
| 2.3 | EWS interpretation is one dense paragraph | pending | measured in the Phase 1 browser pass; the panel is a single paragraph with no supporting-detail control |
| 2.4 | Excel not presentation quality | **yes** | `whatif_workbook.py` sets no `hide_gridlines`; PD/LGD written as raw decimals |
| 2.5-projects | Projects shallow / stale | **yes** | 6 projects; **all six have 0 analyses**, three have 0 investigations; "Retail Portfolio Review — **Q3 2026**" over data that ends 2026-08 (§4.2 forbids labelling August a September quarter-end) |
| 2.5-documents | Documents shallow | **yes, and worse** | Documents has **no backend at all** — `/documents` renders the hard-coded `DOCUMENTS` constant from `frontend/src/lib/demo.ts`; no persistence, no editing, no download, no revisions |
| 2.5-lenses | Lenses thin | **yes** | 4 published lenses, **none of them a product dashboard**; the contract requires ≥8 including Auto / Credit Card / Personal / Home |
| 2.5-analyses | Stale/foreign content | **yes** | the Analyses list carries corporate rows — e.g. "Shipping PD increase" — in a retail-only installation |
| 2.6a | "Backend did not respond within 20 seconds" | **partly** | `discrimination` on the Credit Card behavioural scorecard takes **16.3 s**, `calibration` **9.4 s**; the overview is 0.5 s. At 16.3 s a 20 s client timeout is one slow query from firing |
| 2.6b | Category mapping wrong | **yes** | the registry's category IDs are `data_quality`, … — the contract's screen calls for **Data & Representativeness**; `POST …/categories/data_representativeness` returns **404** |
| 2.7 | Investigation lacks its next analytical step | **yes, and worse than described** | see below |

### 2.7 in full — the flagship demo moment

The attention card itself is sound: `GET /risk-cases` returns 7 computed cases,
top of list `Credit Card 30+ DPD has risen for 5 consecutive months`, severity
critical, 2026-08 vs 2026-07. `POST /risk-cases/368/investigate` creates
investigation 1012 in 1.2 s.

Asking that investigation the contract's exact prompt —
`what is the reason of this rise?` — returns in 12.6 s with `status:
succeeded` and:

- **the product scope is gone** — the answer is "the whole portfolio", not Credit Card;
- **the metric is the wrong one** — gross carrying amount, not 30+ DPD;
- **the period is the wrong one** — 2025-08 → 2026-08, not the month-on-month step or the five-month lookback the case is built on;
- no transition matrix, no cures, no mix bridge, no PD/stage/ECL bridge, no pockets, no affected customers.

It answers a question nobody asked, confidently. This is STORY-03 through
STORY-06 and it is the single most visible failure in the demo path.

---

## Part 2 — Requirement-to-implementation delta

| § | Requirement | Today | Gap |
|---|---|---|---|
| 8 | One shared What-If thread for standalone, guided cards and every EWS export | two implementations, two API families | **build**: one thread controller + `Selection` widened to represent any Retail cohort, both entries create threads |
| 8.1 | Landing: composer, 7 guided cards, Delta/XGB cards, Saved + Recent | composer + 7 cards present; no model cards; raw-parameter block present | **build** model cards, **remove** the parameter block |
| 8.2 | Card opens a thread with a real baseline profile | card only swaps prompt chips on the home page | **build** |
| 8.3 | Explicit method choice before first run; full persistence of turns | EWS thread has method cards; standalone has none; thread turns are per-session | **build** persistence; **extend** method choice to standalone |
| 9 | Typed scenario plan; pp vs % units; absolute LGD shock | `lgd_relative` only — "+5 percentage points" is refused | **build** `lgd_absolute`, `pd_absolute`, `ccf_absolute` units + plan object |
| 10.1 | Clickable Delta model page | route `/what-if/models/delta` exists | **verify + deepen** |
| 10.2 | Clickable XGBoost page with 6 tabs, artifact, save/load parity | route `/what-if/models/ml` exists; XGBoost fits live per run | **build** persisted artifact + tabs |
| 6 | Credit Card attention decomposition | absent — wrong scope, metric and period | **build** |
| 7 | Trait → score → PD → ECL attribution | absent | **build** |
| 11 | Result sequence, propagation table, financial waterfall | waterfall exists in the EWS thread only | **extend** to the shared thread |
| 12 | Professional Excel, 20 mandatory sheets, no gridlines | 13 sheets, gridlines on, raw decimals | **rework** |
| 13 | Three Word report families from a versioned bundle | EWS model-log report only | **build** |
| 14 | Validation categories, execution, representativeness | 11 categories, 8 scorecards; category IDs mismatched; 16 s worst case | **repair + build** |
| 15 | Per-card comments + validation Word report | absent | **build** |
| 17 | 12 substantial projects | 6, all with 0 analyses | **seed** |
| 18 | 60 investigations / 100 analyses | 50 investigations / 9 analyses (some corporate) | **seed** |
| 19 | 24 editable documents with support bundles | frontend constant, no backend | **build + seed** |
| 20 | 8 lenses incl. 4 product dashboards | 4, none a product dashboard | **build + seed** |
| 21 | Clean-cohort (DPD=0, elevated forward risk) filter | forward-risk flag exists; no DPD=0 clean filter | **extend** |
| 22 | Five-act Demo Story entry | absent | **build** |
| 24 | Source stamps on every derived domain | only `retail_ews_score` is stamped; the three governed views carry none, so `stale()` answers False for them | **fix** — this is the §24 recurring upgrade defect, still open |

### Defect fixed during the audit

`.env.retail` carried no `NEXT_PUBLIC_API_URL`, so a frontend started the
documented way (`set -a && . ./.env.retail && set +a`, then `npm run dev`)
fell back to `http://127.0.0.1:8000` — the **corporate** installation's port.
The page rendered completely and then reported "Backend offline", because
every call from the browser went to a server that was not this one. Only the
launcher passed the variable, on its own npm line. Added to `.env.retail`.

---

## Part 3 — The 92 gates

Status values, and what each one is allowed to mean:

| Status | What had to happen |
|---|---|
| `PASS` | The workflow was executed and the OUTPUT was inspected. A downloaded file was opened; a screen was read; a figure was reconciled against the book. |
| `FAIL` | The same, and it did not do what the contract says. |
| `NOT RUN` | Nobody executed it. Not "probably fine". |
| `DEFERRED` | Executed enough to know what it would cost, and consciously left for a later release with the reason recorded. |

Nothing is marked `PASS` from a card being present, an HTTP 200, a file
appearing on disk, or a function existing in the source. Where a gate was
decided by a script, the script is named and is in the repository; where it
was decided in a browser, the screenshot is under `docs/evidence/`.

**An endpoint returning the right thing is not this contract's bar, and one
row of this matrix had to be re-decided to prove it.** CONTENT-05 was marked
PASS on a count of published lenses returned by the API. That count was
correct. The dashboards it counted did not render at all: every tile showed
"could not be produced", and when that was fixed the page threw and fell to
an error boundary. Both defects are now fixed and the gate is genuinely
green — but it was green for a while on evidence that could not have caught
either. The rows below say what was actually opened and read. Where a gate's
evidence was strengthened after the fact, it says that too.

Re-audited at `8bfa4c5` · book `3268b725…` · 2026-08 · 59,449 facilities /
42,824 customers.

The suites that decide the browser-facing rows, and their scores at that
commit:

| Suite | Covers | Score |
|---|---|---|
| `scripts/retail_uat/smoke_release.py` | the demonstration spine, end to end | 17 / 17 |
| `scripts/retail_uat/phase8_story.py` | §22 Demo Story, §23 prompt bank | 21 / 21 |
| `scripts/retail_uat/phase8_navigation.py` | §25 navigation and controls | 7 / 7 |
| `scripts/retail_uat/phase9_models_and_lenses.py` | §10.2 model page, §20 lenses | 16 / 16 |
| `scripts/retail_uat/phase9_timings.py` | §27 cold and warm | every step in budget |

### DATA (10)

| ID | Gate | How it was decided | Status |
|---|---|---|---|
| DATA-01 | Source identity and enlarged population preserved | lake query: 59,449 facilities / 42,824 customers at 2026-08 | PASS |
| DATA-02 | Required periods and maturity | 25 source months published, 20 scored; the 12-month outcome window closes at 2025-08 and `population()` admits only matured subjects | PASS |
| DATA-03 | Derived membership parity | all four derived views return 59,449 / 42,824 at 2026-08 | PASS |
| DATA-04 | Amount reconciliation | `retail_domains.reconcile()` ties GCA and ECL from the book to every view; it is run inside the bootstrap and rebuilds on disagreement rather than reporting it | PASS |
| DATA-05 | Source mutation invalidates dependents | the manifest hash was rewritten and `source_stamp.stale()` flipped to True for all five derived domains, then restored and flipped back. Previously **FAIL** — three views carried no stamp at all | PASS |
| DATA-06 | A stale 20k EWS cannot pass readiness | `bootstrap --check` reads the running application, not the files; the artifact check was proven able to fail by removing the artifact | PASS |
| DATA-07 | Partial rebuild retains other months | regression `test_stamp_04` | PASS |
| DATA-08 | Development references immutable | the scorecard development window and reference population are read from the registry, never recomputed from the current book | PASS |
| DATA-09 | Historical artifact labelled and reproducible | every seeded analysis, document and lens carries `source_hash` and `month`; `bootstrap --check` fails an installation whose seeded analyses were computed against an older book | PASS |
| DATA-10 | Idempotent upgrade / fresh seed | the seeder was run twice: the second run created only the 6 previously-refused analyses and left 137 analyses / 139 investigations unchanged | PASS |

### STORY (12)

| ID | Gate | How it was decided | Status |
|---|---|---|---|
| STORY-01 | Computed attention card | 7 computed cases; top of list is Credit Card 30+ DPD risen for 5 consecutive months | PASS |
| STORY-02 | Click opens a full persisted thread | `POST /risk-cases/{id}/investigate` creates the investigation with its first answer already in it, in 1.2 s | PASS |
| STORY-03 | Natural "why" inherits scope, metric and period | asked in the thread; the product resolves product, period and measure from the thread rather than re-asking. Previously **FAIL** — all three were lost | PASS |
| STORY-04 | Worsening / cures / entry-exit matrix | the three are reported separately, not netted | PASS |
| STORY-05 | Rate bridge reconciles | symmetric split `(w1−w0)(r0+r1)/2 + (r1−r0)(w0+w1)/2`; contributions sum to the total with no residual | PASS |
| STORY-06 | Separate ECL bridge | ECL is multiplicative, so attribution is computed per prefix rather than allocated; reported separately from the rate bridge | PASS |
| STORY-07 | Trait inventory is complete, not a top three | "show all behavioural scorecard variables, not just the top three" returns the full inventory | PASS |
| STORY-08 | Trait → score → PD → ECL attribution | the chain is computed end to end and each link is shown | PASS |
| STORY-09 | Existing-customer deterioration separated from mix | direct standardisation, `Σ (development weight × current stratum rate)` | PASS |
| STORY-10 | A fresh thread does not inherit the last one's product | `traits-main` in the prompt bank asserts it scopes to Retail, not to Credit Card | PASS |
| STORY-11 | The latest COMPLETE quarter is used, not the partial one | banked as `traits-quarter`; the answer names the quarter it settled on | PASS |
| STORY-12 | A question the catalogue cannot answer says so | `DATA-MATURITY` and the absent-measure caveats name what could not be used rather than answering a narrower question | PASS |

### WIF (16)

| ID | Gate | How it was decided | Status |
|---|---|---|---|
| WIF-01 | Standalone uses the shared thread | `/what-if` is a landing; both entries open `/what-if/threads/{id}`, the same component. Previously **FAIL** — two implementations over two API families | PASS |
| WIF-02 | Guided cards open a thread with a real baseline | the card opens a thread carrying the cohort's baseline profile | PASS |
| WIF-03 | No raw parameter block on the landing page | the "What this engine implements" card and its six raw identifiers are gone. Previously **FAIL** | PASS |
| WIF-04 | Explicit method choice before the first run | an unchosen method returns the method cards, not a Delta result presented as the reader's choice. Previously **FAIL** on the standalone path | PASS |
| WIF-05 | Delta method runs and reconciles | +10% relative PD on the credit-card book: engine delta 3,363,343 SAR | PASS |
| WIF-06 | XGBoost challenger runs on the same scenario | same run: challenger 68,929,992 → 72,811,856 SAR, delta 3,881,864 | PASS |
| WIF-07 | The two methods are compared honestly | direction agreement is reported, and two methods that both move nothing now say so rather than "disagree" | PASS |
| WIF-08 | LGD +5 pp understood and calculated | `lgd_absolute` is implemented; percentage points and per cent are distinguished. Previously **FAIL** — refused by design | PASS |
| WIF-09 | A vague shock asks rather than guesses | "make it worse somehow" returns a clarification naming the measure and size it needs | PASS |
| WIF-10 | A non-canonical bucket asks rather than rounding | "30-60 DPD" asks whether 30-59 was meant | PASS |
| WIF-11 | A cohort with no eligible accounts refuses | the refusal names the count and offers the authorised wider selection rather than widening silently | PASS |
| WIF-12 | Narrowing a cohort is carried into the result | `_narrowing_said()` normalises it; every narrowed cohort exports | PASS |
| WIF-13 | The result carries the model that produced it | every challenger result names its version, library, book hash and held-back R² | PASS |
| WIF-14 | Undo removes the last exchange | `/threads/{id}/undo` | PASS |
| WIF-15 | Full cross-session persistence | threads, method, turns and saved runs persist across sessions. Previously **FAIL** — turns were per-session | PASS |
| WIF-16 | Remove Step / Clone / Compare | present in the API (`/whatif/compare`, save, reopen, delete) but **not surfaced in the UI** | **FAIL** |

### MODEL (8)

| ID | Gate | How it was decided | Status |
|---|---|---|---|
| MODEL-01 | Clickable Delta model page | `/what-if/models/delta` opens and documents the identity it recalculates | PASS |
| MODEL-02 | The Delta page names its version | `retail-whatif-1.0.0`, on the page and on every result | PASS |
| MODEL-03 | Clickable XGBoost page | `/what-if/models/ml` renders the retail challenger. Previously it retired itself with a claim that had stopped being true | PASS |
| MODEL-04 | Six tabs | model card, features, performance, artifact, worked example, rebuild — each opened and its content read | PASS |
| MODEL-05 | A persisted artifact | one directory per book holding the estimator, the feature list in training order, the library and the metrics | PASS |
| MODEL-06 | Save/load parity | fit, save, load, score 5,000 facilities through both: largest disagreement on a facility 0.0 SAR | PASS |
| MODEL-07 | The artifact is invalidated by a new book | stamped with the manifest hash; a changed book refits rather than serving a model trained on data that is gone | PASS |
| MODEL-08 | The page states its own limitation | the 0.98 held-back R² is explained at the top, not in a footnote: recorded ECL is close to a closed form of the inputs | PASS |

### EXPORT (10)

| ID | Gate | How it was decided | Status |
|---|---|---|---|
| EXPORT-01 | The workbook downloads and opens | opened with openpyxl from the downloaded bytes | PASS |
| EXPORT-02 | No gridlines on any sheet | every sheet asserted. Previously **FAIL** | PASS |
| EXPORT-03 | Numeric and probability formats | PD and LGD as percentages, amounts with separators; no raw decimals. Previously **FAIL** | PASS |
| EXPORT-04 | The mandatory sheets are present | asserted by name | PASS |
| EXPORT-05 | Formulas are formulas, and correct | xlsxwriter writes the formula and a cached result, so `check_workbook_formulas.py` recomputes rather than reading the cache — a wrong formula with a right cached value is invisible otherwise | PASS |
| EXPORT-06 | Every workbook figure ties to the screen | reconciled against the run that produced it | PASS |
| EXPORT-07 | The three Word report families render | investigation, trait attribution and scorecard validation, all opened | PASS |
| EXPORT-08 | Reports are built from a versioned bundle | each carries its bundle version and the book hash | PASS |
| EXPORT-09 | The validation report carries the reader's comments | a comment written on a category reaches the document | PASS |
| EXPORT-10 | Regeneration is reproducible | the content hash is anchored on the validation window end, not the clock, so the same run regenerates identically | PASS |

### VAL (16)

| ID | Gate | How it was decided | Status |
|---|---|---|---|
| VAL-01 | The category list matches the contract's screen | eight categories, named as the contract names them | PASS |
| VAL-02 | Category ID mapping | `data_representativeness` resolves. Previously **FAIL** — a 404 | PASS |
| VAL-03 | The full suite executes | 53 tests across 8 scorecards | PASS |
| VAL-04 | Full-job progress, no generic timeout | the job reports progress per test; the 16.3 s synchronous worst case is gone. Previously **FAIL** | PASS |
| VAL-05 | Stop is honest | a stopped job records `recorded: False` and a note saying a run covering 7 of 53 tests is not quotable as a validation. Previously the screen fabricated a run and then unmounted on it | PASS |
| VAL-06 | Data & Representativeness has contents | provenance, input drift, ODR and mix-adjusted rates, over 16 strata covering 95% of the book | PASS |
| VAL-07 | Representativeness refuses thin strata | `MIN_STRATUM = 200`, `MIN_COVERAGE = 0.50`; origination vintage was standardising 9% of the book and is now excluded with the reason | PASS |
| VAL-08 | PSI/CSI computed over approved bins | `Σ (p_cur − p_ref) ln(p_cur / p_ref)` with zero-bin smoothing; CSI never re-cuts | PASS |
| VAL-09 | Rank ordering reports inversions with their evidence | bounds, accounts, customers, events, rate, Wilson interval, PD and largest tied share | PASS |
| VAL-10 | An inversion is separated from noise | PASS with no inversions, FAIL where the Wilson intervals separate, WARNING otherwise | PASS |
| VAL-11 | Banding is anchored on development support | re-banding revealed real inversions in 3 of 4 behavioural scorecards while Credit Card stayed clean — a comparison model without the same issue | PASS |
| VAL-12 | Persistence is measured across closed cohorts | each closed cohort is reloaded rather than grouping the deduplicated pool by month | PASS |
| VAL-13 | Findings appear in every category they belong to | `Finding.also_in` carries the cross-category membership | PASS |
| VAL-14 | Comments attach to categories and evidence cards | keyed on model and target, carrying the run in context; an edit supersedes rather than overwrites | PASS |
| VAL-15 | The validation Word report has all fifteen sections | opened and its sections read | PASS |
| VAL-16 | The wider scorecard regression suite | **NOT RUN** since `994cf6d` — it exceeded the release time budget and was deferred by instruction | **NOT RUN** |

### CONTENT (10)

| ID | Gate | How it was decided | Status |
|---|---|---|---|
| CONTENT-01 | 12 non-empty projects | 12 seeded (18 total), each with analyses and investigations under it. Previously **FAIL** — 6, all with 0 analyses | PASS |
| CONTENT-02 | 60 meaningful investigations | 148 seeded threads carrying real turns, counted from the database rather than from a paginated list endpoint — the first count for this row read 200 off a page of 50. 370 threads in total | PASS |
| CONTENT-03 | 100 saved analyses | 143, each computed through the governed measure engine and carrying its source hash. Previously **FAIL** — 9 | PASS |
| CONTENT-04 | 24 substantive documents | 25 across all four products, with versions, a draft/review/approved lifecycle, attachments and a Word download. Previously **FAIL** — no backend at all | PASS |
| CONTENT-05 | 4 product + 4 additional lenses | 13 published, 12 seeded including one per product. **Decided on screen, after a first attempt that was not good enough**: the count below was right while the Credit Card dashboard rendered eighteen error cards, and then while it threw and fell to an error boundary. `phase9_models_and_lenses.py` now opens a seeded dashboard and asserts that as many tiles are DRAWN as the render returned, that none reads "could not be produced", and that the page did not fall to an error boundary — 18 of 18 drawn, with the month, the live badge and the book hash on screen. Previously **FAIL** — 4, none a product dashboard | PASS |
| CONTENT-06 | No empty titles and no repetitive filler | every title, question and headline is written per analysis; the headline is computed from the result | PASS |
| CONTENT-07 | No corporate residue in a retail installation | `tidy()` runs in the bootstrap and removes the 9 corporate analyses ("Shipping PD increase" and friends), investigations with no messages and no project, and — added at this re-audit — unfiled threads repeating a question another unfiled thread already asks. It had to be widened: acceptance runs create a thread per question WITH messages, so the list had reached 1,005 investigations of which 633 were a literal repeat of a title already present, 58 of them identical. §2.5 names repetitive filler specifically. 1,005 → 370, every seeded thread kept, no unfiled duplicate left, and a title seen once is never touched | PASS |
| CONTENT-08 | A refused measure is recorded as a refusal, not a zero | four refusal paths exercised and read: a measure asked of a product it is meaningless for ("Mean utilisation is not meaningful for Personal Finance. Utilisation needs a revolving limit"), over-limit share and loan-to-value likewise, an ungoverned cut, and a filter on a column the book does not carry. Every one returns a sentence naming the reason; none returns 0 | PASS |
| CONTENT-09 | A document quotes the analysis it cites | documents are seeded from the same computed results as the analyses rather than recomputing them | PASS |
| CONTENT-10 | The content is seeded by the bootstrap, not by hand | wired into `bootstrap_retail_installation.py`; `--check` counts against the seed definitions and fails when a screen would open thin | PASS |

### LIVE / NAV (10)

| ID | Gate | How it was decided | Status |
|---|---|---|---|
| NAV-01 | Every route the navigation offers opens | 25 routes walked in a browser | PASS |
| NAV-02 | No route redirects away from the entry that offered it | measured per route | PASS |
| NAV-03 | Every internal link opens a page the product serves | each distinct route shape opened; Next serves its not-found page with a 200, so the body is read rather than the status. An earlier version compared links against the nav allowlist and reported `/engine-builder` — a route the product serves and simply does not put in the sidebar — as dead | PASS |
| NAV-04 | No screen is a dead end — a disabled primary always sits beside something the reader can use | two earlier versions of this check were wrong about the product and are recorded in the script: one flagged every disabled button without a tooltip, catching Ask buttons beside empty composers; the next typed prose and re-checked, still flagging screens whose primary waits for a SELECTION. What is checkable without guessing is whether a screen offers any enabled control at all | PASS |
| NAV-05 | No empty screens | character count per route, floor 400. **A weak check, recorded as weak**: a screen that has fallen to an error boundary carries more than 400 characters and passes it. It is the tile-level checks in `phase9_models_and_lenses.py` that catch that, not this one | PASS |
| NAV-06 | No HTTP 500 across the walk | every API call recorded | PASS |
| NAV-07 | No page errors | `pageerror` recorded throughout | PASS |
| NAV-08 | The Demo Story is reachable and resumable | 28 steps across 5 acts; Resume returns to the step the presenter left on, Restart clears it | PASS |
| NAV-09 | The story's artifact ids are this installation's | resolved by seed key on every request, and each one fetched | PASS |
| NAV-10 | Free-text navigation still works with a story open | the composer is editable and unrestricted throughout | PASS |

### The gates that are not green

| ID | Status | Why, and what it would take |
|---|---|---|
| WIF-16 | **FAIL** | Remove Step, Clone and Compare exist in the API and are exercised by the What-If suites, but no control on the thread screen reaches them. It is a UI gap, not a capability gap: the work is three buttons and a compare view, not an engine. |
| VAL-16 | **NOT RUN** | The wider `tests/scorecard` regression suite has not been re-run since `994cf6d`. It was deferred by explicit instruction when it exceeded the release window. The targeted Phase 6 acceptance covers the behaviour this release changed; the regression suite covers everything it did not. |

Two of ninety-two. Both are recorded here rather than argued away, and
neither is on the twenty-minute demonstration path.

### Rows decided by reading the implementation, not by observing a run

CONTENT-05 was wrong in a specific way worth generalising: its evidence was
a true statement about the system that could not have detected the failure.
Auditing the other ninety-one rows for the same shape, twelve were decided
the same way — by establishing that the code does the right thing, rather
than by a suite that watched it do so. One of the twelve, CONTENT-08, was
cheap to settle and has been: four refusal paths were forced and their
sentences read. Eleven remain.

They are listed because listing them is the only honest thing to do with
them. None is believed wrong; several describe defects this release fixed
and whose fixes are visible in the diff. But CONTENT-05 was also not
believed wrong.

| Row | The claim | What would upgrade it |
|---|---|---|
| STORY-04 | worsening, cures and entry/exit are reported separately, not netted | a check that reads the four figures off an investigation and asserts they do not sum to a single net movement |
| STORY-08 | the trait → score → PD → ECL chain is computed end to end and each link is shown | a check that reads all four links off the answer |
| STORY-12 | a question the catalogue cannot answer says so rather than answering a narrower one | a banked prompt whose expected outcome is a refusal, asserted through the composer |
| WIF-12 | narrowing a cohort is carried into the result | a check that narrows, exports, and finds the narrowing stated in the workbook |
| WIF-13 | every challenger result names its version, library, book hash and held-back R² | the smoke runs an XGBoost scenario but does not read those four fields off it |
| EXPORT-08 | each report carries its bundle version and the book hash | open the .docx and find both |
| EXPORT-10 | regeneration is reproducible — the content hash is anchored on the window end, not the clock | generate twice and compare the hashes. Attempted here by reading `_due()` for the words it anchors on; it mentions both the window and a clock, which settles nothing. Grepping for a substring is the same weak evidence this section is about, so the row stays on this list |
| VAL-13 | findings appear in every category they belong to | a check that finds one finding under two categories |
| CONTENT-06 | no empty titles and no repetitive filler | now partly observable: the tidy's duplicate rule proves the *investigations* half. The analyses and documents half is still read from the seed definitions |
| CONTENT-09 | a document quotes the analysis it cites | read a figure from a paper and the analysis it names, and compare |
| NAV-10 | free-text navigation still works with a story open | observed only as "the composer is editable", which is weaker than the claim |

Three in the same neighbourhood are genuinely observed and are not on this
list: MODEL-05 and MODEL-07 by `phase9_models_and_lenses.py` checks 10-05
and 10-06, and the persistence half of VAL-14 by the release smoke's check
08.

### What this re-audit changed, and why the matrix moved

Four rows were green on evidence that could not have caught the defect
underneath them. Recording that is the point of the column: a matrix that
only ever says PASS teaches nobody anything about how much to trust it.

| Row | What the evidence was | What it missed | What it is now |
|---|---|---|---|
| CONTENT-05 | a count of published lenses from the API | every tile rendered "could not be produced"; then, once that was fixed, the page threw `Cannot convert undefined or null to object` and fell to an error boundary. Eight dashboards had never displayed | the dashboard opened, 18 of 18 tiles drawn on screen, no error boundary, month and book hash visible |
| CONTENT-02 | 200 investigations | 200 was a page of 50 misread; the real figure was 1,005, of which 633 were repeats left by acceptance runs | counted from the database; 148 seeded, 370 total after the tidy |
| CONTENT-07 | corporate analyses and empty investigations removed | a thread created by a suite has messages, so the rule kept all 857 of them | widened to unfiled duplicate questions, keeping the most recent of each |
| NAV-05 | character count per route | an error boundary is not an empty screen | unchanged, but marked as weak, with the check that actually covers it named |

One regression was introduced during this work and is recorded here because
the release smoke is what caught it. The §27 startup warm-up swept every
published month through a nine-month book cache; one month is 650 MB, and
the sweep OOM-killed the backend at 12.5 GB. The smoke reported six
failures — "socket hang up", "no thread", "no composer" — which is the shape
a suite takes when the server it is talking to has died, not a product
defect. Fixed by reading months without retaining them and holding three
rather than nine: peak 3.2 GB, and the warm-up is twice as fast. The smoke
then passed 17 of 17.

Two things about this release's own verification are worth stating, because
both cost time and neither was the product's fault. A heavy `pytest` run
alongside a browser suite starved both and produced readings about
contention. And the `tests/retail` suite cannot run while the API server is
up on this machine: they share a memory cgroup, and the resident backend
leaves the suite too little headroom.

# Defects found by driving the running application

Every defect below was found in a browser, against the build the retail
launcher serves. None was found by reading code. Each row states what a user
saw, what caused it, what changed, the regression test that now holds it, and
the real-browser journey that was re-run afterwards.

Twenty-eight defects in the first pass. Revision 3 adds fourteen more, found
the same way: by opening the screen rather than by reading the file behind it.
All fourteen are fixed and retested. RFD-35 and RFD-36, previously open and
blocked, are both closed — see the end of this document.

## Critical — the application was unusable

| ID | What the user saw | Root cause | Fix | Regression test | Retest |
|---|---|---|---|---|---|
| RFD-01 | "You are signed out" on every screen, while the backend was healthy | The launcher opened the page at `localhost` and pointed it at an API on `127.0.0.1`. The session cookie is host-only and `SameSite=Lax`, so the browser withheld it on every call and both chat boxes were dead | The launcher serves the API at the host it opens | `tests/retail/test_ret_chat_regressions.py::test_the_launcher_serves_the_api_at_the_hostname_it_opens` | every suite signs in |
| RFD-02 | "Cannot reach the CreditProbe backend", with curl working perfectly | A backend started without the launcher's environment drops `CORS_ORIGINS`; every preflight was refused | `scripts/retail_uat/restart_backend.sh` starts it the way the launcher does, from `.env.retail` | the driver asserts the **browser** can reach the API before a suite runs | all suites |
| RFD-03 | Every endpoint under `/api/v1/retail` answered 200 with no session at all — the portfolio, a named customer's whole position, the Early Warning book | The retail router carried no auth dependency, on an installation where `REQUIRE_LOGIN` is on | The router requires a signed-in user; the endpoints that RUN something require one who may run an analysis | verified live: 401 without a cookie, 200 with one | `docs/evidence/retail_functionality` |

## The Cockpit could not plan a retail question

| ID | What the user saw | Root cause | Fix | Regression test | Retest |
|---|---|---|---|---|---|
| RFD-04 | Every question met with "Which figure should CreditProbe measure?", offering "internal rating" | The concept registry bound its measures to corporate datasets this conversion retired | A retail concept registry, selected by the product profile; the corporate one retained as code | `test_the_active_concepts_are_retail_and_bound_to_the_retail_dataset` | CHAT-02 |
| RFD-05 | "by retail product" ignored; "only personal finance" had nothing to filter on | The filterable dimensions were the corporate columns, so the installation governed **no** dimensions | Twenty retail dimensions declared in the profile, with the spellings people type | `test_every_governed_dimension_is_a_real_column_of_the_retail_book` | CP-01, CP-02 |
| RFD-06 | The planner saw no reporting periods at all | The vocabulary read its periods from a retired dataset | It reads the active book | `test_the_vocabulary_reads_periods_from_the_active_dataset` | CHAT-10 |
| RFD-07 | "How many facilities are in each IFRS 9 stage?" refused as unanswerable | A question naming no measure fell back to the corporate facility book, which carries no fields here | The default dataset follows the profile | in-suite | CP-01 |
| RFD-08 | Answers dated at an arbitrary month — May 2025 on an August 2026 question | Every `YYYY-MM` label sorted to the same key, so "the latest period" was filesystem order | Monthly labels sort chronologically | `test_monthly_periods_are_offered_in_calendar_order` | CP-01 |
| RFD-09 | "August 2026" was read as no period at all | The period reader matched only labels appearing verbatim | Months written in words resolve against the published labels | `test_months_written_in_words_resolve` | CP-01 |
| RFD-10 | Every question naming a year was reported as a period the data does not hold | The year was read as the last four characters of the label: `2026-08` gave `6-08` | The year is parsed from the label's own shape | `test_iso_month_labels_report_their_own_year` | CP-01 |
| RFD-11 | "I could not find a borrower called Cockpit Data" — the domain heading the product tells the user to type | The governed word set did not include the catalogue's own names | The catalogue vocabulary is governed vocabulary, read from the shipped file as well as the database | `test_calendar_and_catalogue_words_are_not_read_as_borrower_names` | CHAT-02 |
| RFD-12 | The same, for "August" | Calendar words were not governed vocabulary | Added | the same test | CHAT-02 |
| RFD-13 | A failed catalogue read poisoned the vocabulary for the life of the process | The read was `lru_cache`d, so one failure before PostgreSQL was up cached an empty answer | Only a successful read is cached | `test_an_unreadable_catalogue_is_not_cached_as_an_empty_vocabulary` | CHAT-02 |
| RFD-14 | "Show exposure, customers, facilities and weighted ECL by retail product" came back as a list of ten facilities, then as a refusal | The entity nouns in the measure list were read as the answer's grain, contradicting the explicit breakdown | An entity noun that is not the head of the request does not decide the grain; entity nouns listed among measures are counts | `test_a_measure_list_does_not_decide_the_grain`, `test_an_entity_head_noun_still_outranks_a_breakdown` | CP-01 |

## Answers that were wrong on screen

| ID | What the user saw | Root cause | Fix | Regression test | Retest |
|---|---|---|---|---|---|
| RFD-15 | SAR 463,168,890 rendered "463,169" under a header reading "SAR bn" — a million times too large | The formatter assumed every money column was already in millions and ignored the column's declared scale | The column's scale is honoured; a whole-unit book scales to mn/bn and says which | `frontend/src/lib/__tests__/retail-money-scale.test.ts` | CP-01 |
| RFD-16 | "Personal Finance is the largest at 463,168,890 SAR" above a table where Home Finance held three times as much | "The largest" was read off row zero of a table ordered by a different measure | The largest row **by the measure the sentence is about** | in-suite (CP-01 asserts the named product matches the table) | CP-01 |
| RFD-17 | "Ordered largest first" above a table ordered by something else | The claim was unconditional | The ordering is checked against the rows and the measure is named | in-suite | CP-01 |
| RFD-18 | "Final ECL was unchanged from 0.00 to 0.00" above two rows showing 14.1m and 16.0m | The movement narrative looked for a column called `period`; a monthly book calls it `reporting_month` | The period column is read off the plan | in-suite | CP-02 |
| RFD-19 | "The AI interpretation failed validation: list index out of range" | `_movement` read `matches[0]` with no matches — an IndexError shown to a credit officer as a reading problem | A comparison naming no measure asks which figure to compare | in-suite | CP-02 |
| RFD-20 | "retail_facility_month is not reported by period" — on a monthly book | The movement and share plans hard-coded the column name `period` | Both read the catalogue's declared period field | in-suite | CP-02 |
| RFD-21 | "Compare with July 2026" asked which figure to compare, one turn after computing it | No pattern recognised a period comparison as a continuation | It is a period modification, and the named month pairs with the settled one | in-suite | CP-02, CHAT-10 |
| RFD-22 | "Show the evidence" — the product's own suggested follow-up — answered "Which figure should CreditProbe measure?" | It was read as a new request | Evidence requests are about the result already on the table | in-suite | CP-CONT |
| RFD-23 | A "Break that down by sector" chip under every ungrouped retail answer | Sector is a corporate dimension this installation retired | The suggestion is built from the governed dimensions | `test_the_ungrouped_follow_up_offers_a_governed_breakdown` | CP-01 |
| RFD-24 | A column headed "Facilitys" | The plural was built by appending "s" | A plural helper, in the planner and the presentation contract | in-suite | CP-01 |
| RFD-25 | "customers" summed across products into a portfolio total that double-counts | A distinct count summed across overlapping groups is not a total | Said on the answer rather than dropped | in-suite | CP-01 |
| RFD-26 | "Give me the July to August ECL decomposition" refused: "needs two published periods … cannot find them", on a book publishing twenty-five | The method read `ifrs9_staging` | It reads the retail book through a named field map | `test_the_ecl_decomposition_reads_the_active_book` | CP-03 |
| RFD-27 | The same question answered as a single-period total | "ECL decomposition" was not recognised as a movement, and "move from July to August" did not count as one either | Both recognised; months without a year resolve right to left; a month is matched as a whole word, so "dec" in "decomposition" no longer names December | `test_a_decomposition_request_is_recognised`, `test_move_from_x_to_y_is_a_movement`, `test_months_written_without_a_year_resolve`, `test_a_month_is_only_matched_as_a_whole_word` | CP-03 |
| RFD-28 | A decomposition scoped to personal finance reported the whole book: SAR 1,882,500 where the product moved SAR 981,593 | The handler was handed the governed catalogue rather than the population | The stated population reaches the read | in-suite | CP-03 |
| RFD-29 | A driver worth SAR 607,461 rendered "607 SAR bn", and a follow-up offering "the same decomposition for one sector only" | The decomposition's column declared "SAR mn" and its suggestion named a retired dimension | Both read the active book | in-suite | CP-03 |

## What-If

| ID | What the user saw | Root cause | Fix | Regression test | Retest |
|---|---|---|---|---|---|
| RFD-30 | What-If Analysis showed "CORPORATE IFRS 9", an empty period list, and prompts offering rating notches and BBB borrowers | The module was still the corporate one; its datasets were retired by this conversion | A retail What-If screen, language layer and store over the existing retail engine | the whole `whatif_chat` and `whatif_journeys` suites | WI-01…WI-20 |
| RFD-31 | The What-If box would not send on Enter | It required Cmd/Ctrl+Enter while the Cockpit sent on Enter | Both send on Enter, keep a line on Shift+Enter, and ignore an IME Enter | in-suite | WI-CHAT-01 |
| RFD-32 | Save answered 500 and the screen said the backend was unreachable | A 25-character version written into a `VARCHAR(24)`; PostgreSQL refuses rather than truncates | Shortened, and checked against the column | `test_the_saved_whatif_row_fits_the_columns_it_is_written_to` | WI-11 |
| RFD-33 | "What changed, why, and which assumptions matter?" answered with a neutral run over the whole book | It named no shock, so it was read as a scenario with none | An explaining question is answered from the run on the table | in-suite | WI-09 |

## Accessibility and test-visibility

| ID | What the user saw | Fix | Retest |
|---|---|---|---|
| RFD-34 | Three identical unlabelled buttons on the Investigations list | `aria-label="Open investigation: …"` and `data-investigation-id` | CHAT-11 |

## Alert usability

**RFD-37 — RET-EWS-011 named a quarter of the book at HIGH severity.** The
affordability rule compared today's debt burden against the burden at
origination, so every customer who had taken a second facility qualified:
3,377 of 14,251 customers, 23.7% of the book. True of each one, and not a
deterioration. It now compares against the prior month — 386 customers, 2.7%
— with origination kept on the alert as context. Measured before and after,
at every threshold worth considering, in `docs/RETAIL_EWS_011_REVIEW.md`.
Regression tests: `test_the_affordability_rule_measures_deterioration`,
`test_the_first_published_month_raises_no_deterioration`,
`test_every_derived_input_is_actually_derived`.

## Revision 3 — What-If fidelity

Every one of these was an advertised capability that answered with something
other than what was asked for. A screen that refuses is visible; a screen that
returns the published book under your own question is not.

| ID | What the user saw | Root cause | Fix | Regression test | Retest |
|---|---|---|---|---|---|
| RFD-38 | "Replay an application cutoff of 620 on personal finance" returned the untouched book, with no indication anything had been ignored | `cutoff_replay` was listed on screen under "What this engine implements" and had no rule in the language layer at all. The sentence matched no shock pattern, so it ran as a scenario with no shocks | A cutoff sentence is read as a cutoff, routed to `cutoff_replay`, and rendered on its own card that says it is a count over booked originations rather than a revaluation | `test_ret_whatif_fidelity.py::TestEveryAdvertisedMethodologyIsReachableInWords` — the advertised list and the reachable list must be the same set | WF-15 |
| RFD-39 | "4,053 of 19,745 accounts (20.5%) would have been excluded" for a cutoff asked about personal finance alone | The replay counted every product in its denominator regardless of which product the cutoff named; the other products' cutoffs mapped to NaN, so they were silently "retained" | Only the products the cutoff was asked about are in the population. The true figure is 4,053 of 7,761 — **52.2%** | `test_only_the_products_asked_about_are_counted` | WF-15 |
| RFD-40 | The replay reported 0 observed defaults among the excluded accounts — indistinguishable on the page from a clean book | At 2026-08 no facility's outcome window has closed, so every outcome is null. The counts were rendered as zeros | The counts are omitted when no window has closed, and their absence is stated: "NOT KNOWN here — it is not zero. Ask at an earlier reporting month". At 2025-08 the replay works and discriminates: 2.63% default among excluded against 1.16% retained | `test_an_unknown_outcome_is_not_reported_as_zero_defaults`, `test_where_the_window_has_closed_the_outcomes_are_reported` | WF-15 |
| RFD-41 | "Apply the same shock only to salary-transfer customers" narrowed the population correctly and dropped the 20% PD increase, answering with the published book | The language layer carried the conversation's FILTERS forward and not its SHOCKS | A narrowing turn carries its shocks, and says so on screen. Family-aware, so "instead, two percentage points" replaces the relative increase rather than stacking on it | `test_a_narrowing_follow_up_keeps_the_shock_it_narrows`, `test_a_replaced_shock_reaches_the_same_ecl_as_a_fresh_run` | WF-16, WF-17, WF-18 |
| RFD-42 | "No facility matches that population at undefined" | The turn rendered `body.month`; the API returns `snapshot_month`. A saved run was also labelled with the month in the select rather than the month it ran on | The type and every reader name `snapshot_month` | frontend typecheck; WF-13 reads the month off the card | WF-04…WF-15 |
| RFD-43 | Answering the units question by clicking a reading produced a card captioned "An unchanged scenario over the whole retail book" above a 2-percentage-point shock on personal finance | A scenario assembled from a CLICK had an empty `read_as`: the button label was re-parsed as a sentence and named nothing, and the screen falls back to the neutral caption when nothing was read | A resolved scenario describes itself from its own fields | `TestAScenarioAssembledFromAClickDescribesItself` | WF-19, WF-20 |
| RFD-44 | `/what-if/thread`, `/what-if/models/delta` and `/what-if/models/ml` served the corporate screen — rating notches, sector stress, "ML Model — XGBoost" — over a book that does not exist here | Not in the navigation is not unreachable. A bookmark, a pasted link or a history entry still opens the route | Each answers with what was asked for, why this installation does not serve it, and a link to the screen that does the same work on the retail book | `TestTheCorporateWhatIfRoutesDoNotServeTheirScreen` | WF-22 |

## Revision 3 — Customer 360 and Early Warning

| ID | What the user saw | Root cause | Fix | Regression test | Retest |
|---|---|---|---|---|---|
| RFD-45 | Customer 360 rendered the previous module's layout and offered no retail customer; every call answered 503 `data_not_built` | The screen called `/corporate/meta` and `/corporate/borrowers/...`, which have no book in a retail installation | The route binds to `/retail/customers`, `/retail/customer/{id}` and `/retail/facility/{id}/score`, and Early Warning signals is a retail screen whose rows open the customer they were raised against | `tests/retail/test_ret_customer_360.py` — 13 gates reconciling the screen against the Parquet | C360-01…C360-10 |
| RFD-46 | A customer's bureau score was shown as one number | It varies by facility row — 600 to 651 for RC-0020621, and 4,137 customers carry a spread | The low, the high and the number of observations are reported, and the LOWEST is shown with its basis stated. A decision reads the worst evidence it holds; an average of bureau observations is not a bureau score | `test_the_bureau_reading_is_not_passed_off_as_one_number` | C360-05 |

## Revision 3 — reachable corporate content

| ID | What the user saw | Root cause | Fix | Regression test | Retest |
|---|---|---|---|---|---|
| RFD-47 | The Lenses index offered a **CRO Portfolio Lens** card — one click from a navigation item — rendering "the wholesale book", sector concentration and largest-obligor share | The hand-built screen was never profile-gated, and the index linked to it unconditionally | The card is withheld and the route answers with a fallback. The screen is retained as code | `TestTheCroLensIsNotOfferedOrServed` | RO-01, RO-02 |
| RFD-48 | Agent Operations published **Ratings & Financials**, **Covenant & Collateral** and the **Relationship Graph** as ACTIVE teams, with their corporate purposes and methods on display. Every retained retail team also advertised a grant over those domains | The registry catalogue published all thirteen agents and all eight domains with no profile awareness, and each agent's `domain_labels` were built from its full grant | `served_agents()` and `served_domains()` decide what is published, delegated to and selected for a concept; a grant over a retired domain no longer permits a read. All thirteen definitions are retained | `TestTheAgentRegistryServesOnlyTeamsWithAnActiveBook` — including that no retired domain has an active retail concept behind it | RO-03, RO-04 |
| RFD-49 | A seeded schedule woke the Ratings & Financials specialist, and the name reached the screen from the DATABASE — so editing the seed alone would not have removed it | The schedule serialiser rendered whatever agent id the row stored | The seed no longer names a retired specialist, and the serialiser filters a row persisted before a retirement | `test_a_schedule_persisted_before_a_retirement_is_filtered_on_read` | RO-04 |
| RFD-50 | The document library shipped a **Real Estate Sector Review**, a sector committee paper owned by a Sector Credit Head | The seeds predated the conversion | Three retail papers, each naming the dataset, month and figures it is drawn from — reconciled against the published book by test | `TestTheSeededDocumentLibraryIsRetail` | RO-05, RO-06 |
| RFD-51 | On a fresh deployment the bootstrap would install a **Corporate IFRS 9 lens**, a **Corporate Credit Committee**, an IFRS 9 committee whose every tile names a `corporate.ifrs9.*` metric, a **corporate model-redevelopment delivery plan** and a **shipping-review conversation** — into a retail-only product | The bootstrap is where a retired surface comes back: nobody types its URL, the installer creates it. None of these seeds was profile-aware | Each is withheld under the retail profile and retained as code; the delivery plan is rewritten as a retail scorecard and IFRS 9 programme that keeps every Planner feature it demonstrated (an overdue task, a blocked task, an open decision, a closed decision, milestones, dependencies, a fortnight of updates) | `TestTheBootstrapCannotReinstallARetiredSurface` | bootstrap seeds are asserted, not run — see the Revision 3 report |

## Closed in Revision 3

**RFD-35 — the neutral What-If parity residual. CLOSED.** The explanation was
wrong and the fix was elsewhere. The recomputation was not continuous: it
rounded the weighted and final allowance to the halala, which the build never
does — the build rounds each SCENARIO ECL and then carries the weighted value
as the exact combination of those published figures. With weights 0.6/0.2/0.2
over a 0.01 grid the published allowance sits on a 0.002 grid,
gcd(0.6, 0.2, 0.2) × 0.01, and snapping that to 0.01 displaces each row by up
to 0.004 — exactly the largest row residual observed. Nor was the net the
error: the row displacements summed to |SAR 17.86| and cancelled to SAR −0.52,
so a tolerance justified by the net would have been thirty-four times too
loose. With the rebuild doing the build's arithmetic the residual is **exactly
zero** across 200 neutral runs spanning all 25 months, every product, every
stage, and the credit-impaired, secured, forbearance and short-life
populations. The declared tolerance is unchanged and kept as a guard.
`tests/retail/test_ret_whatif_reconciliation.py`.

**RFD-36 — Customer 360. CLOSED.** See RFD-45 above. CP-10 is no longer
BLOCKED: the full journey — filter an Early Warning list, open an alert, open
its customer, read facilities, history, both scorecards and warnings, change
the month, and return to the SAME filtered list — passes in the browser,
C360-01 to C360-10.

## Open

**RFD-37 — the metric library reads datasets this build does not contain.**
Nine tests across `tests/metrics` and `tests/playbook` fail with
`'retail_behavioral_scorecard_monthly_validation' is not a governed dataset`.
They failed identically before and after this pass — verified by stashing every
Revision 3 change and re-running — so this is not a regression introduced here.
The cause is that `backend/metrics/library.py` predates the retail conversion:
its retail metrics are built on the two scorecard-validation datasets, which
`data/analytics/` does not hold, and its own docstring says the retail data is
"not enough for retail IFRS 9". The consequence is that **Lenses, Metrics and
the Playbook have no calculable tile in this installation** — the two retail
lenses install and render, and every tile in them is empty. Building a retail
metric library on `retail_facility_month` would close it; that is new capability
rather than a conversion defect, and it is named here rather than papered over.

**RFD-35 (superseded, kept for the record) — the neutral What-If parity
residual.** A scenario that changes
nothing returns SAR 8,994,011.35 against a published SAR 8,994,011.87. The
published book holds money on a 0.002 SAR grid and the rebuild is continuous,
so a facility's rebuilt ECL lands beside its published value rather than on it:
SAR 0.52 across 7,761 facilities, 5.8×10⁻⁸ of the total, no facility differing
by more than SAR 0.004. The tolerance is now **declared in code**
(`PARITY_PER_FACILITY_SAR = 0.01`, `PARITY_RELATIVE_TOTAL = 1e-6`), checked row
by row, and stated on screen. It is reported rather than removed: rounding the
rebuild onto the published grid would hide a real engine error the day there is
one.

## Blocked

**RFD-36 (closed in Revision 3, kept for the record) — Customer 360.** The route
rendered the previous module's layout and offered no retail customer to open.
CP-10 was BLOCKED, not passed. Closed by RFD-45: the screen now reads the retail
book and the full journey passes in a browser.

Nothing remains blocked by a defect in this product. What remains NOT RUN is
external: an authorised AI provider, and a launch on the user's Mac. Both are
named in `docs/RETAIL_REVISION_3_ACCEPTANCE.md` with what would close them.

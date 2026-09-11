# Defects found by driving the running application

Every defect below was found in a browser, against the build the retail
launcher serves. None was found by reading code. Each row states what a user
saw, what caused it, what changed, the regression test that now holds it, and
the real-browser journey that was re-run afterwards.

Twenty-eight defects. Twenty-six fixed and retested; one open with a stated
workaround; one blocked.

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

## Open

**RFD-35 — the neutral What-If parity residual.** A scenario that changes
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

**RFD-36 — Customer 360.** The route renders the previous module's layout and
offers no retail customer to open. CP-10 is BLOCKED, not passed. The retail
position is available at `GET /api/v1/retail/customer/{id}`; putting it on a
screen is outstanding work, documented in `docs/RETAIL_ONLY_HANDOVER.md`.

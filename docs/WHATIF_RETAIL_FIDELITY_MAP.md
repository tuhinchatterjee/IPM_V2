# What-If: the corporate screen and the retail one, mapped

Revision 3 §3 asks whether wiring a retail What-If replaced the product with a
reduced version. This is the mapping it asks for: every capability the corporate
What-If offers, where it went, and — where it did not survive — whether that is
a retail semantic that had to change or a capability that was lost.

The baseline is the **repository** baseline: `frontend/src/app/what-if/page.tsx`
(the corporate landing, retained as code), `frontend/src/app/what-if/thread/page.tsx`
(the corporate analysis screen) and `frontend/src/components/whatif/`. It is
**not** the local WHATIF_5318 installation, which remains unverified — no claim
here is evidence about that build.

Verdicts used below:

* **KEPT** — the capability exists in the retail screen.
* **RETAIL FORM** — the capability exists, in the shape the retail book requires.
* **N/A (retired book)** — the capability operates on something this
  installation does not have. Justified individually; there is no blanket waiver.
* **OPEN** — a real reduction, recorded as such.

---

## 1. Route structure and navigation

| Corporate | Retail | Verdict |
|---|---|---|
| `/what-if` landing, composer-first | `/what-if`, composer-first, `RetailWhatIf` | KEPT |
| `/what-if/thread` — a separate analysis route per scenario | The conversation is on `/what-if` itself | RETAIL FORM |
| `/what-if/models/delta`, `/what-if/models/ml` | Retired; the route answers and links back | N/A (retired book) |
| `BackLink` out of a thread; "All What-Ifs" action | No thread to leave — `/what-if` is a top-level navigation destination | RETAIL FORM |
| Deep link `?saved=<id>` opens a saved scenario | Reopen button on the saved card | OPEN — see §7 |

The three corporate routes were reachable by URL under the retail profile until
this pass. They were not in the navigation, which is not the same as
unreachable: a bookmark or a pasted link opened a corporate screen naming rating
notches and sector stress above a 503 from an endpoint with no book behind it.
Each now renders `RetiredScreen` — what was asked for, why this installation does
not serve it, and a link to the screen that does the same work on the retail book.
That is also the "meaningful existing-app fallback" §2 requires for a direct link
with no in-app history. Verified in the browser by **WF-22**.

## 2. The composer

| Corporate | Retail | Verdict |
|---|---|---|
| Free-text composer, never replaced by chips | Same component (`Composer`, `data-testid="whatif-composer"`) | KEPT |
| Suggested starting sentences | Four retail starters from the API | KEPT |
| Six guided journey cards → `?journey=` | Not present | RETAIL FORM |
| Composer stays open after a run | Same | KEPT |
| Unit ambiguity answered with a question, both readings as buttons | Same, and the clicked reading now describes itself | KEPT |

Four of the six corporate journeys are rating-, sector- or macro-variable-based
(**Rating Movement**, **Sector Stress**, **Macroeconomic Shock**, **Borrower
Stress**); on a retail book with scorecards, no rating master scale, no corporate
sector taxonomy and three published macroeconomic scenarios rather than
individual variables, those are not cards that could run. The other two
(**IFRS 9 Risk Parameter Adjustment**, **Stage Migration**) are reachable as
sentences and are proved as such by **WF-04…WF-14**. The starters carry the same
role the cards did: a way in that is not a restriction.

## 3. Methodologies — the core of §3

The corporate screen offers two ECL methodologies (Delta, ML/XGBoost) and one
scenario grammar. The retail screen offers **one documented methodology version**
(`retail-whatif-1.0.0`) and **twelve methodologies** within it, plus two staging
modes. Every one is now reachable by typing a sentence at the route the launcher
serves, and each is exercised there:

| Methodology | Reached by | Browser case |
|---|---|---|
| `pd_relative` | "Increase PD by 20% relative for personal finance" | WF-04 |
| `pd_absolute_pp` | "Increase PD by 2 percentage points…" | WF-05 |
| `lgd_relative` | "Increase LGD by 10%…" | WF-06 |
| `collateral_value_pct` | "Reduce mortgage collateral values by 10%" | WF-07 |
| `recovery_delay_months` | "Delay recovery by 6 months for mortgages" | WF-08 |
| `utilisation_pp` | "Increase card utilisation by 15 percentage points" | WF-09 |
| `ccf_absolute` | "Set the CCF to 60% for credit cards" | WF-10 |
| `income_pct` | "Reduce verified salary by 15%…" | WF-11 |
| `behavioural_score_points` | "Reduce the behavioural score by 30 points…" | WF-12 |
| `scenario_weights` | "Change scenario weights to base 50%, upturn 10%, downturn 40%" | WF-13 |
| `staging_mode` | "…and re-evaluate staging" | WF-14 |
| `cutoff_replay` | "Replay an application cutoff of 620 on personal finance" | WF-15 |

`cutoff_replay` was **advertised and unreachable** before this pass: the screen
listed it under "What this engine implements", the sentence matched no pattern,
and the request was run as a scenario with no shocks — returning the published
book under the reader's own question. That is defect **WIF-01** below.

The corporate **Delta vs ML** choice is N/A (retired book): the ML model is
trained on Corporate IFRS 9 outcomes and there is no retail equivalent trained
here. Rather than mislabel one, the retail screen names its single methodology
version on every result and in the saved record. The corporate
**MethodologyComparison** turn has no second methodology to compare against;
the comparable retail control is `staging_mode`, which is reachable and tested.

## 4. Assumptions, evidence and refusals

| Corporate | Retail | Verdict |
|---|---|---|
| "How this was calculated" step list | "Assumptions and evidence" with run id, dataset version, methodology version, staging mode | KEPT |
| `result.warnings` / `result.notes` (data availability) | `limitations` and `unsupported` | KEPT |
| ML out-of-distribution warnings | N/A (retired book) | N/A |
| Methodology gate before calculating | One methodology; the version is stated on every result | RETAIL FORM |
| Refuses an unsupported instruction whole | Same, with the supported list (WF-21) | KEPT |
| Neutral-run parity statement | Retail only: the rebuild is checked against the published book and says so | RETAIL ADDITION |

## 5. Results and drivers

| Corporate | Retail | Verdict |
|---|---|---|
| Baseline → What-If headline with % change | Same, four figures | KEPT |
| `DriverAttribution` | Driver table by product code | RETAIL FORM |
| PD / Stage / LGD / EAD / combined factor figures | Not shown | OPEN — see §7 |
| Stage-movement counts and before/after charts | Not shown | OPEN — see §7 |
| Rating-movement charts | N/A (retired book) | N/A |
| Borrower drill-down table under a result | Not shown | OPEN — see §7 |
| Rating / stage / sector profile tables on entry | Not shown | OPEN — see §7 |
| Migration matrix, macro lab, PD/LGD/CCF parameter tabs | Rating migration and macro-variable shocks are N/A; stage migration and parameter profiles are OPEN | mixed |

## 6. Saved scenarios, comparison and exports

| Corporate | Retail | Verdict |
|---|---|---|
| Save a run with a name | `retail-whatif-save` | KEPT |
| Saved list with baseline → What-If and % change | Saved cards, same figures | KEPT |
| Reopen a saved run as it ran, never recomputed | Same, and stated on screen | KEPT |
| Delete a saved run | `retail-whatif-delete-<id>` | KEPT |
| Compare | Corporate compares two **methodologies**; retail compares two **saved scenarios**, and refuses to net two runs on different populations | RETAIL FORM |
| Export | CSV and JSON per saved run | KEPT |
| `DownloadDetail` — export the run on the table without saving it | Not present | OPEN — see §7 |
| Ownership scoping on saved runs | Every read and write scoped to the owner | KEPT |
| "Recent What-Ifs" — runs not saved | Not present | OPEN — see §7 |

## 7. Open reductions, stated rather than waived

These are real differences from the corporate baseline that this pass did not
close. None is claimed as N/A, and none is hidden behind a passing test count.

| # | What is missing | Consequence |
|---|---|---|
| F-1 | Recent (unsaved) runs are not listed | A run left unsaved is lost when the conversation is cleared |
| F-2 | No export of the run on the table | A run must be saved before it can be exported |
| F-3 | No visible scenario-step list with remove / undo / reset | Editing is done in words; the conversation holds the state, and replacement semantics are proved (WF-16…WF-18), but there is no structural view of the steps |
| F-4 | No opening profile of the book before the first question | The corporate screen showed the book first; the retail screen starts empty |
| F-5 | No stage-movement figures or before/after charts | Movement is visible only as a total and by product |
| F-6 | No facility-level drill-down under a result | The population is stated as counts, not listed |
| F-7 | Saved scenarios are not deep-linkable | Reopen works; a URL for one does not |

F-3's *capability* is not lost — a follow-up narrows the scenario on the table
and a replacement replaces rather than compounds, both proved in the browser.
What is missing is the structural view of it.

## 8. Defects this pass found and closed

| # | Defect | Evidence |
|---|---|---|
| WIF-01 | `cutoff_replay` advertised on the screen and unreachable in words; the request ran as a neutral scenario and returned the published book | WF-15; `test_ret_whatif_fidelity.py::TestEveryAdvertisedMethodologyIsReachableInWords` |
| WIF-02 | The cutoff replay counted every product in its denominator regardless of the product asked about — 4,053 of 19,745 (20.5%) where the truth is 4,053 of 7,761 (52.2%) | `test_only_the_products_asked_about_are_counted` |
| WIF-03 | At the latest month no outcome window has closed, and the replay reported `excluded_observed_defaults: 0` — indistinguishable on the page from a clean book | `test_an_unknown_outcome_is_not_reported_as_zero_defaults` |
| WIF-04 | A narrowing follow-up dropped the shock it was narrowing, answering "apply the same shock only to salary-transfer customers" with the untouched book | WF-16; `test_a_narrowing_follow_up_keeps_the_shock_it_narrows` |
| WIF-05 | The turn rendered `body.month`, which the API does not return (it is `snapshot_month`) — "at undefined" on screen, and a saved run labelled with the month in the select rather than the month it ran on | `retail-whatif.tsx`, `api.ts` |
| WIF-06 | Answering the units question by clicking produced an empty `read_as`, so the screen captioned a shocked, filtered run "an unchanged scenario over the whole retail book" | WF-20; `TestAScenarioAssembledFromAClickDescribesItself` |
| WIF-07 | `/what-if/thread` and the two model routes served the corporate screen under the retail profile | WF-22 |
| WIF-08 | The neutral rebuild rounded the weighted and final allowance to the halala, which the build does not — the SAR 0.52 residual | `test_ret_whatif_reconciliation.py` |

## 9. What was deliberately NOT done

* No rating-based calculation was revived, and no retail mathematics was
  relabelled as one. A rating-notch instruction is refused whole, with the
  reason and the supported list (WF-21).
* No capability was removed to make a test pass, and no failing feature was
  hidden. §7 above is the list of what is still missing.
* No corporate code was deleted. The conversion is a profile: the corporate
  landing, thread and model screens are retained and are what a corporate
  profile would serve.

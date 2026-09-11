# Both chat boxes, driven in a real browser

Section 10.4, 10.5 and 10.6 of the closeout, run against the frontend and
backend the retail launcher serves — the same build, the same database, the
same Parquet lake — signed in as the demonstration user in Chromium at
1440×900.

The two boxes are tested **separately**. They share a React component and
nothing else: the Cockpit composer opens an Investigation and talks to the
governed planner; the What-If composer talks to the retail scenario engine. A
pass on one proves nothing about the other's wiring, which is why there are two
suites and two evidence files.

Nothing on a happy path is mocked. The single interception in these suites is
CHAT-13, which fails one request deliberately, says so in its own title, and
removes the interception before the retry.

## What runs, and where the evidence is

| Suite | Cases | Result | Evidence |
|---|---|---|---|
| Cockpit chat — CHAT-01…CHAT-18 | 19 | **19 passed** in 119s | `docs/evidence/retail_functionality/cockpit_chat.json` |
| Cockpit journeys — CP-01…CP-15 and the five-turn conversation | 17 | **16 passed, 1 BLOCKED** in 164s | `cockpit_journeys.json` |
| What-If chat — CHAT-01…CHAT-18 equivalents, WI-01…WI-08, WI-15, WI-17 | 14 | **14 passed** in 75s | `whatif_chat.json` |
| What-If journeys — WI-09…WI-14, WI-16, WI-18…WI-20 | 12 | **12 passed** in 111s | `whatif_journeys.json` |
| Navigation — NAV-01…NAV-10 | 11 | **10 passed, 1 N/A** in 102s | `navigation.json` |

Screenshots for every case are in `docs/evidence/retail_functionality/screens/`.

## Cockpit — the shared chat acceptance tests

| Case | What was typed, and what happened |
|---|---|
| CHAT-01 | The composer is visible, enabled and focusable; the answer surface states "No AI provider is configured", so the reader knows which half of the product is deterministic |
| CHAT-02 | "Use Cockpit Data for August 2026. Show exposure, customers, facilities and weighted ECL by retail product." — one submission, one `POST /investigations`, an answer at 2026-08 grouped by product |
| CHAT-03 | Shift+Enter keeps the draft and adds a line; plain Enter sends |
| CHAT-04 | A three-line pasted instruction keeps its content and resolves its scope |
| CHAT-05 | An empty and a whitespace-only composer cannot be sent, and make **no** analysis call |
| CHAT-06 | "Show scorecard performance." is clarified once; the clarification is answered by clicking an option **and** by typing |
| CHAT-07 | After completion the composer and Ask are usable again and no progress indicator is left running |
| CHAT-08 | A double click with an Enter on top of it produces **one** `POST /investigations/<id>/messages` |
| CHAT-09 | "Now only personal finance" narrows the previous answer and the new turn names Personal Finance and drops the other products |
| CHAT-10 | "Compare with July 2026" carries the narrowed scope and names both periods |
| CHAT-11 | A new conversation does not inherit the old scope; the history lists conversations and one reopens with its transcript |
| CHAT-12 | Navigating away mid-question and returning shows the answer on its own conversation |
| CHAT-13 | **Failure injection.** A failed submission shows a real error, keeps the typed question, clears the progress state, and the retry answers once |
| CHAT-14 | Clearing the session returns the user to sign-in, and the message does not blame the AI provider for an expired login |
| CHAT-15 | The answer carries a Trace and units on its figures |
| CHAT-16 | A long transcript scrolls to the top and the composer stays reachable at the bottom |
| CHAT-17 | Trace, Save analysis, Project and Download results are all present on the answer |
| CHAT-18 | The first answer completed in ~2s, well inside the 240s bound; no unbounded spinner |

## Cockpit — the business journeys

Figures below were reconciled independently against the Parquet lake before
they were written into a case.

| Case | Verified |
|---|---|
| CP-01 | SAR 2,082,852,856 across four products at 2026-08; customers and facilities counted per product; the product named as largest is the largest in the table |
| CP-02 | Narrowing to personal finance then comparing periods: SAR 453,309,241 → 463,168,890, the measure preserved and both periods named |
| CP-03 | The July→August decomposition for personal finance reconciles exactly: movement 981,593.19, attributed 981,593.19, opening 8,012,418.68, closing 8,994,011.87, across nine drivers |
| CP-04 | The base-scenario/weighted-baseline difference is explained, with no invented portfolio figure |
| CP-05 | "Use cockpit data aug 2026, persnal finace…" is read by the ordinary parser |
| CP-06 | An under-specified scorecard question is clarified once and resolved by a typed answer |
| CP-07 | A discrimination question names its cohort or the evidence it lacks |
| CP-08 | A calibration question is not answered with a discrimination statistic |
| CP-09 | A next-12-month Gini on August 2026 originations is refused with the reason, not fabricated |
| CP-10 | **BLOCKED** — see below |
| CP-11 | The explanation and the supported comparison are separated |
| CP-12 | A drafting request is answered from the result and discloses that no model wrote the prose |
| CP-13 | A filter matching nothing gives an honest empty answer, and does not reuse the populated one |
| CP-14 | Evidence opened and Back returns to the same conversation; "Explain that result more simply" is answered there |
| CP-15 | Two conversations at two months do not contaminate each other |
| CP-CONT | One continuous five-turn conversation — analysis, narrowing, period comparison, explanation, evidence — all five turns answered in sequence |

## What-If — the shared chat acceptance tests and the scenario journeys

| Case | Verified |
|---|---|
| WI-01 | An unchanged scenario reproduces the published baseline: SAR 8,994,011.35 rebuilt against SAR 8,994,011.87 published, a residual of SAR 0.52 (5.8×10⁻⁸), no facility differing by more than SAR 0.004, inside the declared tolerance which the answer states on screen |
| WI-02 | PD +20% relative on personal finance: SAR 8,994,012 → 10,161,669 (+12.98%) |
| WI-03 | PD +2 percentage points is a different operation: SAR 15,088,559 (+67.76%), and a fresh scenario inherits neither the earlier relative shock nor its population |
| WI-04 | "Increase PD by 2." is **asked about, not guessed** — both readings are offered as buttons that run exactly what they say, and the typed answer resolves it too |
| WI-05 | "Apply the same shock only to salary-transfer customers" keeps the shock and narrows the population, and the answer says which population it ran over |
| WI-06 | base 50 / upturn 10 / downturn 40 are applied and the weighted identity recomputed |
| WI-07 | Weights summing to 110% are refused **with the arithmetic** — never renormalised behind the reader |
| WI-08 | A card-utilisation sensitivity runs the implemented dependency chain and states its units |
| WI-09 | "What changed, why, and which assumptions matter?" is answered from **that** run's own figures and assumptions |
| WI-10 | Changing the month on the form and re-running uses the new month; form and conversation agree |
| WI-11 | A saved run is a real stored record carrying the shock it ran, and reopens with its own definition |
| WI-12 | Changing the global month does not rebase a saved run: it still states "as it ran at 2026-08" |
| WI-13 | Both advertised formats download and **parse**; the CSV and the JSON agree with each other and with the stored record |
| WI-14 | Clear ends the conversation and leaves saved runs and the canonical book untouched |
| WI-14b | **Destructive.** Delete removes the record this suite created, by id, and every other saved run survives |
| WI-15 | An empty eligible scope is answered as empty — no NaN, no infinity, no stale result |
| WI-16 | A run interrupted by navigation writes no half-finished record, and the retry answers once |
| WI-17 | "Downgrade everyone one notch" is refused with what this engine does instead, and never falls through to a rating engine |
| WI-18 | A relaxed-cut-off question states the observed-replay limitation instead of inventing rejected-applicant outcomes |
| WI-19 | Two **saved** runs are compared as themselves, with any difference in month, population, methodology or dataset version stated |
| WI-20 | Moving between the two boxes keeps their states apart |

## The deterministic reader, stated plainly

This installation reports **"No AI provider is configured"**. Every question in
both suites was read by the deterministic governed semantic reader and every
figure computed in the governed runtime. Per §10.4 that is an honest test of
the production fallback and **it is not a live-provider pass**. The
model-written half of an answer — the prose and the interpretation — is NOT
RUN here, and no case in this report claims otherwise.

## What is blocked

**CP-10 — a named customer's behavioural-score change through Customer 360.**
The route renders the previous module's layout and offers no retail customer to
open, so the journey the case describes does not exist on screen. The retail
position is served by `GET /api/v1/retail/customer/{id}`; passing the case
against that endpoint would be answering a different question, so it is
recorded BLOCKED.

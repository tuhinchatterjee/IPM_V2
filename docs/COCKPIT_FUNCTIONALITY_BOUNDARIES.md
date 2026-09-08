# Cockpit functionality boundaries — verified

**Generated** by `scripts/build_cockpit_agentic_v3_docs.py` from `backend/cockpit_agentic/registry.py`, whose routes are asserted against `frontend/src/lib/navigation.ts` rather than claimed.

Routes verified: **True**.

| Functionality | Label a user sees | Route | Enabled |
|---|---|---|---|
| `cockpit` | Cockpit | `/` | yes |
| `ews` | Early Warning | `/early-warning` | yes |
| `credit_scoring` | Credit Scoring | — none — | NO |
| `scorecard_validation` | Scorecard Validation | `/scorecard-validation` | yes |
| `what_if` | Stress Testing | `/stress` | yes |
| `lenses` | Lenses | `/lenses` | yes |

## Two places the product differs from the specification's names

**Credit Scoring has no module in this deployment.** There is no `/credit-scoring` route and nothing that assigns a borrower a new score. `backend/scorecard/` builds and fits scorecards and `/scorecard-validation` monitors them; neither originates a score. The registry keeps the ownership exclusion — the Cockpit still refuses to generate a score — and says honestly that the owning workflow is unavailable rather than routing score generation to a validation-only screen.

**What-if Analysis ships as "Stress Testing" at `/stress`.** The registry uses the label a user will actually find in the menu. Referring someone to "What-if Analysis" would send them looking for something that is not there.

## Ownership, entry by entry

### Cockpit (`cockpit`)

Ask a question in plain language about the bank's stored twenty-quarter corporate credit dataset. Queries, compares and explains what was recorded.

**Owns:**

- Querying, comparing and explaining data already stored in the twenty-quarter corporate domain
- Historical IFRS 9 results, ECL, PD, LGD, EAD and stage as they were recorded
- Stored risk ratings and their recorded history and reasons
- The forty financial ratios and the statements behind them
- Covenant tests, breaches, waivers and headroom as recorded
- Collateral valuations, haircuts and allocations as recorded
- Recorded macroeconomic vintages and their forecast horizons

**Does not own:**

- Generating a new credit score or rating
- Producing early-warning alerts, signals or watchlist priorities
- Running a new shock, stress or hypothetical parameter change
- Validating or recalibrating a scoring model
- Interpreting documents or reports
- Any data outside the twenty-quarter corporate domain

**Belongs here:**

- “Show this borrower's stored rating history over the last eight quarters.”
- “Compare DSCR and recorded covenant breaches over four quarters.”
- “Compare the two recorded quarterly ECL values and explain the drivers the evidence supports.”
- “Compare the already-stored baseline and downside IFRS 9 outputs.”
- “Which sectors have the highest stage 2 exposure this quarter?”

**Does not belong here:**

- “Assign this borrower a new credit score.”
- “Why did its early-warning alert score increase?”
- “Increase PD by 20% and recalculate ECL.”
- “Validate the scorecard's discrimination and calibration.”
- “Summarise the attached credit memo.”

### Early Warning (`ews`)

Forward Risk Signal and Early Warning Signals: a factor-based estimate of the chance a facility moves to a worse IFRS 9 stage next quarter, and thirty-four governed conditions the book is watched for, borrower by borrower.

**Owns:**

- Early-warning alerts, signals and scores
- The drivers of an early-warning score
- Watchlist prioritisation and the early-warning investigation workflow

**Does not own:**

- Reporting stored historical data, which is Cockpit's

**Belongs here:**

- “Why did this borrower's early-warning score increase?”
- “Which borrowers should be on the watchlist this quarter?”
- “What drove the forward risk signal for this facility?”

**Does not belong here:**

- “Compare this borrower's DSCR over four quarters -- a historical comparison is not an early-warning request merely because it could inform risk monitoring.”

### Credit Scoring (`credit_scoring`)

Calculating, assigning or updating a borrower's credit score or rating.

**Owns:**

- Calculating a new credit score or rating for a borrower
- Updating or overriding an assigned score
- Operating a credit-scoring workflow

**Does not own:**

- Reading a stored rating, which is Cockpit's
- Validating an existing scorecard, which belongs to Scorecard Validation and is a different job

**Belongs here:**

- “Assign this borrower a credit score.”
- “What rating would this borrower get on current financials?”
- “Re-score the portfolio on the updated model.”

**Does not belong here:**

- “Show the borrower's stored rating -- that is Cockpit reading recorded data.”

**Unavailable:** This deployment has no credit-scoring workflow. Scorecards are built and fitted in Analysis Studio and monitored in Scorecard Validation, but neither assigns a borrower a new score. Cockpit cannot generate one either: it reads stored ratings only.

### Scorecard Validation (`scorecard_validation`)

Governed monitoring and validation of the retail application and behavioural scorecards: discrimination, calibration, stability, variable diagnostics and implementation, each against an approved limit that says where it came from.

**Owns:**

- Assessing or testing an existing scorecard or scoring model
- Discrimination, calibration, stability and variable diagnostics

**Does not own:**

- Originating a new score -- this module validates scorecards, it does not run them for a borrower
- Reporting stored ratings, which is Cockpit's

**Belongs here:**

- “Validate the scorecard's discrimination and calibration.”
- “Has the application scorecard's population stability drifted?”

**Does not belong here:**

- “Assign this borrower a score -- validation is not origination.”

### Stress Testing (`what_if`)

Named, versioned management scenarios applied to the portfolio, with comparison. This is where a new shock or hypothetical parameter change is run.

**Owns:**

- New user-requested shocks and hypothetical parameter changes
- Alternative and stress scenarios and their simulated consequences
- Comparing a simulated outcome against the base

**Does not own:**

- Comparing already-stored historical results, which is Cockpit's
- Comparing stored IFRS 9 scenario outputs that the source already produced -- that is reading, not simulating

**Belongs here:**

- “Increase PD by 20% and recalculate ECL.”
- “What happens to the book under a 300 basis point rate shock?”
- “Stress the Real Estate portfolio.”

**Does not belong here:**

- “Compare the stored baseline and downside IFRS 9 outputs -- those were already computed and recorded, so reading them is Cockpit.”

### Lenses (`lenses`)

Live dashboards you build by describing them. Each tile is a certified analysis with its own Trace.

**Owns:**

- The Lenses dashboard workflow and its published views
- Building or reading a Lens

**Does not own:**

- Answering an analytical question about the Cockpit domain, which is Cockpit's

**Belongs here:**

- “Build me a dashboard of sector exposure and stage migration.”
- “Open the CRO lens.”

**Does not belong here:**

- “What is total stage 2 exposure this quarter? -- that is a question, not a dashboard.”

## The rules the gate applies

- Score every entry independently from 0 to 100. These are suitability scores, not probabilities, and they do not sum to 100. Proceed with Cockpit ONLY if Cockpit is the unique highest scorer AND the requested action is inside its ownership. A tie, an unresolved ambiguity, or a requested action that appears in another functionality's 'owns' list means clarify or refer -- a score never overrides an explicit out-of-scope action.
- Do NOT refer an otherwise in-scope question elsewhere merely because the selected quarter has no data. That is a Cockpit data-coverage limitation and you should report it as one.
- A referral executes no SQL and no Python, fetches nothing from the other module, and starts nothing. Offer up to three alternative questions that Cockpit genuinely CAN answer from the fields and periods in this catalogue, each naming the fields it needs. Do not rename an excluded task as a Cockpit one: an excluded 'risk score' does not become permissible as a Cockpit 'risk index'. If fewer than three genuine alternatives exist, give fewer; for a wholly unrelated request, give none.
- If part of the request belongs elsewhere, say which part, and offer an explicit Cockpit-only reformulation of the rest. Do not silently drop the excluded part and report the whole question answered.


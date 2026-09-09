# The IFRS 9 ECL decomposition

## What was wrong

Asked "give me an ECL decomposition", CreditProbe answered:

> 5,313 SAR mn of expected credit loss at Q2 2026.

One row, one column, `total_ecl`. The figure was right and the answer was
wrong: a decomposition is a statement about how a total is BUILT, and a total
is the one thing it cannot be.

The root cause was not the wording. The word "decomposition" was read as a
request for a measure named ECL, so the dynamic planner composed a
straightforward `SUM(total_ecl)` and was, on its own terms, correct — because
**no certified analytical method for an ECL build-up existed**. There was
nothing for the router to route to. `ecl_change_decomposition` is a different
analysis with a similar name: it bridges the movement BETWEEN two quarters, and
answering a one-date build-up question with it produced a nine-row attribution
dominated by a 96% model residual.

The fix is a method, not a phrase: a certified `ecl_decomposition` analysis, a
deterministic engine behind it, and a routing rule that distinguishes a
point-in-time build-up from a two-period movement.

## What the analysis is

A **bridge**, at one reporting date, from a neutral benchmark to the reported
provision. Every facility is measured six times with the same arithmetic —

    ECL = EAD × LGD × PD

— replacing exactly one governed input at each step. Because only one term
moves per step, the difference between two steps is attributable to that term
and to nothing else, and the bridge adds up without a plug.

| Step | What changes | What it measures |
| ---: | --- | --- |
| 1 | Flat TTC PD baseline | Every facility at one through-the-cycle PD (the unweighted mean — a statement about the average credit quality of the book, not about where its money sits) on the exposure-weighted portfolio LGD. |
| 2 | Rating distribution applied | The flat PD replaced by each facility's rating-grade TTC PD, exposure-weighted within the grade. How much the provision moves purely because exposure sits in particular internal grades. |
| 3 | Point-in-time / forward-looking PD | TTC replaced by the governed 12-month PD, which carries the forward-looking and scenario-weighted view. The macro contribution. |
| 4 | SICR / stage migration | The IFRS 9 measurement basis: Stage 1 on the 12-month PD, Stage 2 on the lifetime PD, Stage 3 at the credit-impaired treatment. The cost of where the book is staged. |
| 5 | Collateral and LGD mitigation | The portfolio LGD replaced by each facility's own, which carries its collateral and security. Reproduces the reported model ECL. |
| 6 | Management overlay | The governed overlay added to model output. Reproduces the reported provision. |

The steps are **order-dependent by construction**. That is what makes this a
bridge rather than an attribution: a different order would give different step
sizes with the same start and end. The order-neutral question — *what drove the
CHANGE since last quarter* — is answered by `ecl_change_decomposition`, which
attributes by Shapley value precisely because the order must not matter there.

### Two steps this installation does not have

A bank with a PD calibration model would carry a **calibrated TTC PD** step and,
where part of the book is treated outside the calibration, a **non-calibrated
portfolio** step. Neither is governed here: there is no calibration factor, no
calibration table and no calibrated-PD column anywhere in the catalogue, and no
separately treated non-calibrated component in the book.

They are therefore **omitted and declared**, not estimated and not shown as
zero. `bridge.OMITTED` names each one and why, the Trace's calculation node
carries it, and the result publishes it as `meta.omitted_steps`. A step
reporting zero for something that does not exist reads as a driver that
contributed nothing, which is a different and untrue statement.

### The overlay is never hidden

Step 6 is the management overlay on its own line. It is not folded into "other",
not netted against step 5, and not described as a model output. An overlay is a
judgement, and a bridge that buries one has hidden the only step a reader might
want to argue with.

## It reconciles

The last step must land on the reported provision — `portfolio_facility.
total_ecl`, the figure in the accounts — within
`RECONCILIATION_TOLERANCE_PCT`, which is 0.01% of the provision. That is tight
enough that only the rounding already stored in the source columns can pass it.

On the live book at Q2 2026, across 16,346 facilities and 4,100 borrowers:

| Step | Description | ECL (SAR mn) | Step impact | % change |
| ---: | --- | ---: | ---: | ---: |
| 1 | Flat TTC PD baseline | 6,403.766 | +0.000 | — |
| 2 | Rating distribution applied | 4,862.281 | −1,541.484 | −24.07% |
| 3 | Point-in-time / forward-looking PD | 2,673.711 | −2,188.571 | −45.01% |
| 4 | SICR / stage migration | 4,709.584 | +2,035.874 | +76.14% |
| 5 | Collateral and LGD mitigation | 4,972.330 | +262.745 | +5.58% |
| 6 | Management overlay — final reported ECL | 5,313.064 | +340.734 | +6.85% |

Reported provision 5,313.072. Residual 0.0082, which is 0.00015% — fifteen
ten-thousandths of one per cent, inside a tolerance of 0.01%.

`meta.reconciliation` publishes the final step, the reported figure, the
residual, the residual as a percentage, the tolerance and whether it passed. A
bridge that stopped reconciling raises a warning on the answer saying so in
those words, rather than presenting six plausible numbers.

### Step impact and percentage change

`step_impact` is this step's ECL less the previous step's; it is zero at the
baseline, which has no predecessor. `change_pct` is that impact over the
PREVIOUS step's ECL, and it is `None` — not zero, and not an infinity — at the
baseline and wherever the previous step was zero. A percentage change from
nothing is not a number, and printing one puts something untrue in the most
scannable column on the screen.

## Every step has borrowers behind it

The bridge is computed **per facility** and rolled up, never allocated
downwards. `bridge.contributions` is one row per borrower carrying its ECL at
every step and its impact at every step, and each step's borrower impacts sum
to the portfolio step impact exactly — asserted, per step, in the test suite.

So "which borrowers drove the stage migration?" is answered by reading the same
calculation the portfolio total came from, at the grain a credit officer works
at. `meta.contributors` carries the ten largest movers of each step on the
result; `bridge.contributors(built, step)` returns them for any step and any
depth.

### Drilling in, without losing the bridge

Asked immediately after a decomposition, a follow-up that names a step and asks
for borrowers is answered BY THAT DECOMPOSITION. The bridge is re-run over the
same period and the same population and publishes the borrowers behind that one
step — the rows that already sum to its impact — under the
`contributors_for` parameter.

Before this, the same follow-up composed a fresh ranking of `stage_moved` over
the whole book: a different question, a plausible-looking answer, and no
arithmetic connection to the six numbers directly above it on the screen.

`backend/orchestration/bridge_drill.py` reads the follow-up. It fires only when
the thread's previous turn ran the bridge — a drill-down is a relationship
between two turns, not a property of a sentence — and it recognises the step by
the words a person uses for it: "stage migration", "SICR", "the macro step",
"collateral", "the overlay", "rating". Where the question points back without
naming one ("who drove that?"), the bridge's own largest step is taken.

`ConversationState.certified_analysis` and `certified_params` carry which
certified analysis is on screen and what it ran with; they are what the
drill-down re-runs. A turn that settles something else clears them, so a drill
can never reach past the answer it is looking at. "Show ECL by sector" asked in
the same thread is still a sector breakdown.

## What the reader sees

**Table first.** Six rows: step number, description, ECL, step impact, %
change, then one ECL column per configured segment. The segments are read from
the book — Commercial, Corporate, Public Sector, SME — and none is invented.
Money is in `SAR mn`, the governed currency of this installation.

The step key and the long method note are deliberately not table columns; they
are on `meta.decomposition.steps` where the Trace and a drill-down can reach
them. A paragraph of methodology in a table cell is not a column.

**The chart is the table.** `meta.waterfall` carries the bars, computed from the
same step values the table publishes — the first and last as totals, the middle
four as deltas. The frontend draws them; it never recomputes them. A chart that
does its own arithmetic is a second answer waiting to disagree with the first.
The table remains the opening view, and the waterfall is one click away.

**The reading names steps, not the total.** Three to five observations in a
senior credit-risk voice, each naming one step the engine measured as material
and quoting its own impact. No figure appears in the prose that the engine did
not return.

## Routing

`ecl_decomposition` declares its trigger questions on its contract, like every
certified method, and the certified router fires on a near-verbatim match
against its name or one of them. What is new is the tie-break.

"Show me the ECL waterfall" describes the build-up of the provision at one date
AND the bridge between two quarters, and both contracts declare it. Overlap
alone cannot separate them, and whichever the registry yielded first would win
— a coin toss dressed as a routing decision. So `certified._pick` breaks a tie
on the one thing that genuinely distinguishes them: a question naming two
periods, or speaking of a change, movement, increase, rise or fall, wants the
TWO_PERIOD methodology; a question doing neither wants the POINT_IN_TIME one.
It reads only the contract's declared period requirement, and it decides
nothing when the top match is unique.

These reach the bridge:

- Give me an ECL decomposition.
- Show me the ECL bridge.
- Show me the ECL waterfall.
- Decompose ECL into its components.
- What drove ECL this quarter?
- How is our ECL built up?

These do not, and must not:

- What is ECL? — a definition.
- Show ECL by sector. — a breakdown of the total by a dimension.
- Show ECL for Shipping. — a filtered population.
- Which borrowers have the highest ECL? — a ranking.
- Which borrowers had ECL rise? — a change, at borrower grain.
- Show ECL trend. — a path over periods.
- Explain the movement in ECL. — `ecl_movement`.
- Decompose the change in ECL from Q1 2026 to Q2 2026. — `ecl_change_decomposition`.

## Where the code is

| Concern | File |
| --- | --- |
| The bridge engine: steps, reconciliation, borrower contributions | `backend/ifrs9/decomposition.py` |
| The certified contract and its function | `backend/engine/functions/ifrs9.py` (`ecl_decomposition`) |
| Routing tie-break by period shape | `backend/orchestration/certified.py` (`_pick`) |
| The reading | `backend/orchestration/interpreter.py` (`_ecl_decomposition`) |
| Reading a drill-down follow-up | `backend/orchestration/bridge_drill.py` |
| Which analysis is on screen | `backend/orchestration/conversation.py` (`certified_analysis`) |
| The chart shape | `frontend/src/components/analytics/registry.ts` |
| Engine and arithmetic tests | `tests/ifrs9/test_ecl_decomposition.py` |
| Live acceptance through `/api/v1/ask` | `tests/api/test_ecl_decomposition.py` |

The governed IFRS 9 policy — SICR triggers, the default presumption, scenario
weights, the lifetime horizon — lives in `backend/ifrs9/policy.py` and is
unchanged by this work.

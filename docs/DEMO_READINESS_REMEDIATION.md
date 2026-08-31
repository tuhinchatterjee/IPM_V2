# CreditProbe — demonstration readiness remediation

Branch `claude/vigilant-darwin-eohyi1`. Written after the acceptance run that
found the application "starts technically, but is NOT demo ready".

This report follows §21's fifteen headings. Where a gate was not completed,
it says so rather than claiming it.

---

## A. Root causes found

**A1 — The bootstrap only ever built one of three universes.** The README and
setup notes name three builders. `docker/backend-entrypoint.sh` ran one. On a
fresh machine the corporate Borrower 360 book and the retail scorecard book
therefore did not exist, and every screen that reads them told the presenter
to run a Python script. Nothing detected this, because nothing checked: the
backend reported READY as soon as the API bound its port.

**A2 — "Domains Defined: 0 of 7" beside 344 governed fields.** The bundled
catalogue carries thirty-nine headings of its own. Nothing mapped those onto
the seven business domains the Data Builder promises, so every card read "Not
created" while the datasets underneath were present and published. The screen
was describing a table it was not reading.

**A3 — A sentence-initial capital was read as a company.** `unresolved_names`
tested `text.startswith(phrase)` — the start of the WHOLE MESSAGE — so a
capitalised word opening the second sentence was not recognised as
sentence-initial. "Explain the SICR evidence…" produced a borrower called
`Explain`.

**A4 — A population defined in the same sentence was read as a reference to
an earlier one.** `_SENTENCE` in `discourse.py` carried a `(?<![0-9])`
lookbehind meant to protect decimals. It also blocked the terminator after a
year, so "…at Q2 2026? Explain…" stayed one clause and a same-turn population
could not bind. "The 10 borrowers" was then treated as pointing at a previous
result that did not exist.

**A5 — Two values of one dimension were emitted as a conjunction.** "Migrate
from IFRS 9 Stage 1 to Stage 2" resolved both stages and filtered on both, on
the same rows. No row can satisfy that. The engine ran, the post-result
invariant correctly found the rows did not match the recorded filters, and the
presenter was told CreditProbe could not complete a governed IFRS 9 question.

**A6 — The Trace displayed FAILED beside its own "4 of 4 checks passed".**
The presentability gate and the analytical-judgment rubric judge the written
ANSWER. Both were typed `BUSINESS_INVARIANT`, which that type's own definition
reserves for what was checked "against the rows themselves". They therefore
landed in the Validated stage, whose status word is the worst status in it and
whose sentence counts only invariants. Both statements were true, about
different things, printed as one.

**A7 — A deployment with no provider key described itself as broken.**
Infrastructure health and AI-provider status were computed from one list, so
"no external model configured" became "Backend degraded" beside healthy 200s.
The offline label read "AI OFFLINE" and the detail "LIMITED OFFLINE MODE".

**A8 — Four independent defects under one question.** "Identify the 10
borrowers with the highest probability of credit deterioration over the next
12 months. For each borrower, explain the top five drivers, distinguish
borrower-specific drivers from macroeconomic drivers, and rank the evidence by
materiality."
  1. The phrase named no governed measure, so the planner refused and offered
     four concepts that do not include the one being described.
  2. The count was not read, because the count and the superlative are not
     adjacent — "the 10 **borrowers with the** highest".
  3. "deterioration", the word that made the measure resolve, was then read a
     second time as an assertion that the measure had deteriorated, turning a
     ranking into a cohort of five hundred.
  4. The same word made it a two-period comparison, so the answer compared the
     portfolio's PD across two historical quarters and contained no borrower
     list at all.

**A9 — The review could only notice three things.** The deterministic screen
compared stage, rating and days past due. Every Risk Case was therefore a stage
or rating movement, and ECL movement, liquidity pressure, watchlist entry and
non-performing classification were invisible even where the published book
showed them.

**A10 — A rating recorded no record of how the question was read.** On a
deployment with no external provider that is the largest single difference
between two answers to the same question, and a review workflow that cannot
separate "the phrasing was not understood" from "the analysis was wrong" works
on the wrong half.

**A11 — Naming four dimensions and computing one, silently.** Asked to weigh
cash balances, working-capital movements, short-term debt maturities and
utilisation together, CreditProbe composed on the one the catalogue carries and
said so about none of them. The answer looked complete.

**A12 — An explanation clause set the grain of the answer.** "macroeconomic",
named only in a clause asking to SEPARATE two kinds of driver, resolves to a
governed macro concept published at portfolio grain — and then decided that
one row was the whole book, so a question asking for ten borrowers was refused.

**A13 — A phrase with no single column behind it became whichever column
survived.** "Evidence of liquidity stress" is not a measure. The planner could
only resolve named measures, so it kept the one term in the sentence that
happened to map — utilisation — and then took the grain of the answer from
that measure's dataset rather than from the population the question asked
for. A question naming borrowers returned one portfolio row. The same shape
would have degraded any composite credit phrase: distress, fragility, stretch,
squeeze. This is the mechanism behind A11 and A12 rather than a third
instance of them, and it is what §J's Q5 was waiting on.

---

## B. Files changed

55 files, +6,382 / −299, across 13 commits, this report aside.

**New**
- `backend/bootstrap/{__init__,plan,readiness}.py` — the governed bootstrap
- `backend/services/data_domains.py` — the seven business domains
- `backend/services/demo_users.py` — demonstration accounts
- `scripts/bootstrap_demo.py` — the single entry point
- `tests/proof/test_fresh_clone_acceptance.py` — §16
- `tests/semantic/{corpus,test_question_acceptance}.py` — §17
- `frontend/src/components/trace/__tests__/validation-status.test.ts` — §9
- `alembic/versions/0031_feedback_planner_mode.py`
- `backend/orchestration/composites.py` — governed composite phrases and the
  signals that evidence them
- `tests/orchestration/test_composite_ranking.py` — borrower grain, the
  composite, its plan, and what the reader sees

**Changed (backend)** `agentic/screening.py`, `api/routers/health.py`,
`llm/{base,telemetry}.py`, `models/platform.py`, `orchestration/{analysis_planner,
assembly,concepts,coverage,discourse,entities,executor,grain,invariants,
orchestrator,referents,router,semantics,spelling}.py`,
`services/{answer_feedback,governance}.py`, `trace/model.py`

**Changed (frontend)** `app/data-builder/page.tsx`,
`components/ai-studio/panels.tsx`, `components/ask/clarification.tsx`,
`components/system/ai-power.tsx`, `components/trace/{cluster-layout,clusters,
stages}.ts`

**Changed (infra)** `docker-compose.yml`, `docker/backend-entrypoint.sh`,
`docker/healthcheck.py`

---

## C. Migrations added

One: **0031 — `feedback_planner_mode`**. Adds `planner_mode` and `model` to
`answer_feedback`, with `ix_answer_feedback_mode (tenant, planner_mode,
direction)`. Existing rows keep `""`; a backfill would assert a reader for
answers produced before the column existed, and an invented provenance is
worse than a missing one. Head is now 0031 (31 files).

---

## D. Bootstrap sequence after the fix

`docker/backend-entrypoint.sh` waits for PostgreSQL and then runs
`python scripts/bootstrap_demo.py --json`, which is the whole of it. Each step
carries a probe; a step whose probe says the work is already done is skipped,
which is what makes restarting idempotent.

| | Step | Skipped when |
|---|---|---|
| A | Alembic migrations | head matches |
| B | Demonstration accounts | the four exist (an existing password is never touched) |
| C | Saudi portfolio universe | the 20 core datasets are present |
| D | Corporate Borrower 360 universe | the 13 corporate datasets are present |
| E | Retail scorecard universe | the 4 scorecard datasets are present |
| F | Scorecard model registry | models exist |
| G | Catalogue registration | all books catalogued |
| H | Data Builder business domains | the seven exist |
| I | Dataset relationships | declared |
| J | Demonstration workspace | populated |
| K | Q2 2026 portfolio review | a review of that period is recorded |

C runs before D and E because `generate_saudi_universe.py` **overwrites**
`metadata/catalog.json` while the other two **merge into** it. A test pins that
ordering, since reversing it silently loses two books.

The backend does not report ready until `bootstrap.verify()` passes all 15
readiness checks. `docker/healthcheck.py` requires both `/healthz` and the
bootstrap marker; a missing marker is not ready. Compose allows
`start_period: 480s`, against a measured clean-room build of 319s.

---

## E. Datasets by Data Builder domain

46 registered, all inside the seven domains, 1,102 governed fields.

| Domain | Datasets |
|---|---|
| Core Portfolio / Facility | 25 |
| Corporate Ratings | 8 |
| IFRS 9 / ECL | 6 |
| Retail / SME Scorecards | 4 |
| CreditProbe Operational Metadata | 3 |
| Documents | 0 |
| Policies / Knowledge | 0 |

Documents and Policies/Knowledge are defined and empty: the bundle ships no
datasets for them, and the card says "Nothing installed in this domain yet"
rather than claiming otherwise. The 38 legacy catalogue headings are archived —
not deleted, so lineage on an older analysis still resolves — and appear under
a "Retired domains" disclosure for stewards. A test asserts that nothing was
archived while it still held a dataset.

---

## F. Corporate borrower and quarter counts

- **3,800 distinct borrowers**, **16 quarters**, 52,998 rows in
  `corporate_customer_master`
- `portfolio_facility` and `ifrs9_staging`: 245,190 rows each over 15 quarters

---

## G. IFRS 9 dataset counts and periods

- `ifrs9_staging` — 245,190 rows, 15 quarters
- `scenario_definitions` — 204 rows, 34 periods
- `macro_saudi` — 34 rows, 34 periods
- plus `corporate_ifrs9` and the ECL fields carried on the facility position

---

## H. Scorecard populations, months and models

| Dataset | Rows | Periods |
|---|---|---|
| `retail_application_scorecard_monthly_validation` | 424,368 | 31 |
| `retail_behavioral_scorecard_monthly_validation` | 589,000 | 31 |
| `retail_application_scorecard_development_reference` | 108,000 | 12 |
| `retail_behavioral_scorecard_development_reference` | 115,922 | 12 |

**6 models** in the registry across APPLICATION and BEHAVIORAL — 2 ACTIVE,
3 CANDIDATE, 1 RETIRED. Candidates are not auto-activated.

---

## I. Risk Cases created by the clean demonstration

**5**, from the real deterministic screen over the published book: one segment
finding (Financial Services stage-2 share moved materially) and four borrower
findings. Re-running the review — with `--force` — leaves 5, not 10.

The screen now recognises eight signal types rather than three. On this book
the four borrower findings carry five distinct signals between them: stage
movement, rating movement, delinquency, watchlist entry and non-performing
classification. §1 permits a category to be empty where the book holds nothing
in it; what it does not permit is a screen unable to see one.

---

## J. The six questions, verbatim, and their results

Run through `POST /api/v1/ask` on the bootstrapped deployment.

**Q1** "Identify the 10 borrowers with the highest probability of credit
deterioration over the next 12 months. For each borrower, explain the top five
drivers, distinguish borrower-specific drivers from macroeconomic drivers, and
rank the evidence by materiality."
→ **succeeded, 10 rows.** "The 10 largest customers by twelve-month PD at
Q2 2026." *(Was: a clarification offering four concepts, none of them the one
described.)*

**Q2** "Which borrowers are most likely to migrate from IFRS 9 Stage 1 to
Stage 2? Explain the SICR evidence for every borrower and separate
quantitative, qualitative and forward-looking macroeconomic triggers."
→ **succeeded, 10 rows**, with the substitution stated on the answer: the
question describes a movement out of IFRS 9 stage 1, and reporting the
population now at stage 2 includes any borrower already there. *(Was: failed —
contradictory filters.)*

**Q3** "Find borrowers whose leverage has increased, EBITDA margins have
declined and debt-service capacity has weakened over the last four reporting
periods. Which of these also have covenant pressure or negative rating
migration?"
→ **succeeded, 79 borrowers** meeting all five conditions. This read "1
borrower meeting all four" earlier. Two mechanism fixes moved it: "debt-service
capacity has weakened" now resolves to the governed DSCR concept instead of
being dropped, which is the fifth condition; and "four reporting periods" is no
longer read as a magnitude, which had been attaching a phantom "more than 4" to
every one of them. Five stated conditions, all applied.

**Q4** "Which borrowers currently appear acceptable on headline financial
ratios but show hidden deterioration when I combine collateral coverage,
covenant headroom and payment behaviour?"
→ **clarification**: market value or net realisable value? They differ by the
governed haircut, and coverage computed on the wrong one is overstated. This
is a correct question to ask, not a failure.

**Q5** "Which borrowers have the strongest evidence of liquidity stress?
Consider cash balances, working-capital movements, short-term debt maturities
and facility utilisation together."
→ **succeeded, 25 borrowers, ranked.** Each borrower is placed by how many
of eight governed liquidity-stress signals it shows at Q2 2026 — drawn to 90%
or more of its limit, utilisation up 5 points or more on the prior period, in
arrears, rolled over three times or more, debt-service coverage below 1.2x,
covenant headroom below 10%, on the watchlist, classified non-performing —
running from 8 of 8 at the top to 4 of 8 at the cut. The answer still names
the dimensions it cannot compute (cash and liquidity balances, working-capital
movement, short-term debt, upcoming maturities — the catalogue carries no
measure for any of them), but those absences no longer decide the grain: it
ranks borrowers on the evidence that does exist. Verified deterministic across
three runs, and identical to an independently written DuckDB query. **This
defect is closed**; what remains of it is a coverage limitation, §O.1.

**Q6** "Find something in this portfolio that a human credit officer could
easily miss."
→ **clarification** naming the governed measures. The question names no
measure at all; asking is the right response.

---

## K. Semantic evaluation

**547 distinct questions across 83 structural families**, 1,107 assertions,
all passing. Checked against the reader's INTERMEDIATE reading — the cohorts it
found, the mentions it bound, whether it believes it needs a previous result,
and which words it took for borrower names — not the HTTP status. The question
that started this returned 200 and had decided `Explain` was a company.

Explicit regressions pinned: `Explain` is never a borrower; "the 10 borrowers"
needs no previous turn; "for each borrower" refers to the same-turn population;
"these borrowers" may use either turn; IFRS 9 terminology maps to concepts
rather than obligor lookups. Counter-tests keep the guards honest — five
genuinely ambiguous questions must still ask, and four genuinely unknown
borrower names must still surface.

The eighty-third family is liquidity asked in plain English — "who is running
short of cash", "which names look squeezed on liquidity", "who has the most
signs of a cash squeeze" — eight variants, none of which names a measure, all
of which must stay at borrower grain.

---

## L. Full test suite

**7,159 passed, 21 skipped, 0 failed** on the definitive run
(`pytest tests/ -q -p no:randomly`, exit 0). Frontend: **308 passed, 0
failed**. `ruff` clean across `backend/`, `tests/`, `scripts/`, `alembic/`;
`tsc --noEmit` and `eslint` clean.

The suite was run three times: once mid-work, once on what was believed to be
the final tree, and once after a defect the second run did not catch. That
middle run was green while a fix for Q1 had silently dropped two of Q3's four
conditions - "1 borrower meeting all four" had become "500 meeting two", under
a heading still promising four. It was found by re-running the six questions
by hand, not by the suite, which is the argument for §20's rule that unit
tests passing is not the gate. The regression is now pinned by a test.

A fourth run followed the Q5 fix: 7,159 passing, the 54 additional tests being
the borrower-grain and composite suite. That fix also moved Q3 (§J), which the
suite did not flag either, because no test asserted anything about Q3's shape.
Two now do: Q3's five conditions must each carry no threshold the question did
not state, and Q5's population must stay at borrower grain. Neither pins a row
count — a count pinned to demonstration data is a test of the fixture, not of
the mechanism.

No existing test was weakened, skipped or xfailed. Three legacy assertions
were replaced because the string each pinned was itself the defect; each
replacement is stronger and says why in its docstring:
- `test_the_offline_status_says_what_is_degraded` → forbids nine fault words
  rather than pinning the one wrong literal, and a companion test asserts
  `degraded` still says so.
- `test_overall_status_is_the_worst_component` → three tests separating
  infrastructure health from provider status.
- an archived-domain test → now also asserts no governed dataset sits in an
  archived domain.

---

## M. Browser acceptance

**956/956 checks passed across 4 viewports and 17 screens**, driving real
Chromium against the built Next.js application and the real backend. Checks
cover horizontal overflow, stranded navigation, truthful status labels, no
fabricated percent-complete, no assurance figure labelled accuracy, and
reduced-motion behaviour.

---

## N. Routes inspected

`/api/v1/readiness` (15/15), `/api/v1/health`, `/api/v1/data-builder/domains`
and `/datasets` (46), `/api/v1/agentic/{agents,approvals,events,health,
policies,runs,schedules,stages,tools,workers,evaluations}`,
`/api/v1/corporate/*`, `/api/v1/scorecard/*`, `/api/v1/feedback/*`,
`/api/v1/ask`. 372 routes in the OpenAPI document. The browser run covers 17
screens directly.

---

## O. Remaining limitations

1. **Liquidity stress is evidenced on eight dimensions, not twelve.** The
   ranking is built from what the catalogue carries: utilisation level and
   movement, arrears, rollovers, debt service, covenant headroom, watchlist and
   non-performing status. Cash and liquidity balances, working-capital
   movement, short-term debt and upcoming maturities have no governed measure
   behind them, so no borrower is ranked on them. The answer says this in
   place, and the ranking counts signals rather than weighting them — a
   weighted score would need weights, and a weight nobody owns does not belong
   in a credit answer. Adding those four dimensions is a data question, not an
   engine one.

2. **Docker was not exercised.** No Docker daemon is available in this
   environment. The entrypoint, healthcheck and compose changes are
   **NOT VERIFIED UNDER DOCKER**. The bootstrap itself was verified by running
   it directly, including a re-run proving idempotence (0 steps performed, 11
   already in place).

3. **The fresh-clone acceptance test bootstraps its own precondition.** It
   shares a database with unit tests that truncate tables, so it establishes
   the state it asserts on rather than assuming it. That is what a fresh
   `docker compose up` does, but it is not the same as an empty Postgres
   volume.

4. **Two domains are empty.** Documents and Policies/Knowledge are defined and
   ship no datasets. Their cards say so.

5. **Risk Case categories are narrower than the book could support.** Five
   cases across five signal types on a portfolio where §1 lists nine
   categories. The screen can now see eight; the demonstration book presents
   findings in five of them.

---

**This is not a claim of demo readiness.** All six acceptance questions now
answer at the grain they were asked at, but the Docker path is unverified in
this environment and four liquidity dimensions have no data behind them. Both
are listed above rather than absorbed into a summary.

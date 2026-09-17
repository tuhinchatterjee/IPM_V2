# CP-RA-V2 — phase status

Implementation of `docs/anb-ten-journeys/SPECIFICATION.txt` (ten complete Saudi
retail investigation journeys) and its worked fixture workbook.

This file is the running record the specification asks for in §1: after each
phase, the files changed, the migrations, the tests, the data hashes and the
remaining blockers. It is updated in the same commit as the phase it describes,
so a reader never has to trust a claim that is not beside the work.

| Phase | Name | State |
|-------|------|-------|
| P0  | Baseline audit and isolation            | COMPLETE |
| P1  | Identity, metric and cohort contracts   | COMPLETE |
| P2  | Ten coherent synthetic episodes         | COMPLETE |
| P3  | Atomic Cockpit/EWS publication          | COMPLETE |
| P4  | Ten evidence-driven cards and drawers   | COMPLETE |
| P5  | Stateful investigation threads          | COMPLETE (backend; UI chips in P7 commit) |
| P6  | Versioned policy action engine          | COMPLETE |
| P7  | Borrower 360 investigation workspace    | NOT STARTED |
| P8  | Stage-aware Excel evidence exports      | NOT STARTED |
| P9  | Borrower 360 to What-If                 | NOT STARTED |
| P10 | Real-browser, data and regression       | NOT STARTED |
| P11 | Freeze and handoff                      | NOT STARTED |

---

## P0 — Baseline audit and isolation

### What the accepted baseline actually is

The specification (§1.1) warned that the supplied report [P01] describes a
branch state rather than proving it, and that an older launch log showed
`59e5a301`. Both were checked against the repository rather than assumed.

| Fact | Verified value |
|------|----------------|
| Accepted ANB branch | `claude/exciting-archimedes-npzji5` |
| Its full head SHA | `3ac4489fd4e777b0fc158f2fd08f5104006a631b` |
| Local head == `origin/` head | yes (`git ls-remote` agrees) |
| Commits above the approved retail baseline | 12 |
| Approved retail baseline | `c0db151f62c34e84b4f7df5faf81e5c9b0c9f647` |
| `59e5a301` from the older launch log | `59e5a301b2155570d0cad8e2eda1ffc9f210d477`, an **ancestor** of the head — an earlier commit on the same branch, not a divergent build |
| `origin/main` merged into this work | no. `main` was already an ancestor of `c0db151f` before any of this work existed |
| Working tree | clean; no stash; no untracked files to preserve |

So the report's "12 commits" is accurate, the older launch log is explained
rather than contradicted, and the new work starts from the verified head —
not from `c0db151f`, not from `59e5a301`, not from the Planner branch.

### Isolation

| Item | Value |
|------|-------|
| Implementation branch | `claude/anb-ten-journeys`, created from `3ac4489f` |
| Implementation database | `creditprobe_anb_v2` (created empty, migrated to head) |
| Implementation environment file | `.env.anb2` (git-ignored by the existing `.env.*` rule) |
| Implementation ports | 5334 frontend / 8334 backend |
| Untouched | `creditprobe_retail` (the accepted ANB demo database in this container) |
| Untouched | 5328/8328, 5330/8330, 5332/8332 and Docker database ports 5528/5538/5548/5558/5568 |

A separate branch rather than further commits on `claude/exciting-archimedes-npzji5`
is what §1.1 requires: the accepted ANB demo must "remain untouched until
explicit acceptance of a new version", and a Mac worktree tracking that branch
would pick this work up on its next pull if it were pushed there.

### Where this container is, and is not

This is a remote Claude Code container, not the user's Mac. It holds its own
clone and its own PostgreSQL. It therefore cannot see, start, stop or damage
the Mac's 5328/8328 presentation, the `~/Desktop/IPM_V2-ANB-Demo` worktree or
the Docker database ports — and it does not claim to have done so. The local
launcher P11 asks for is delivered as a setup artifact for the user to run,
per §1.1's last sentence.

### Baseline manifest

| Artefact | Value |
|----------|-------|
| Alembic head | `0042` (42 migration files) |
| Governed dataset registrations | 5: `retail_facility_month`, `retail_ews_score`, `retail_early_warning`, `retail_credit_scorecard`, `retail_whatif` |
| `metadata/retail/catalog.json` | sha256 `c6bd68bebe7eb885…` |
| `metadata/retail/retail_data_contract.json` | sha256 `3edc7abda9855cad…` |
| `metadata/retail/retail_dataset_manifest.json` | sha256 `e69320b81db63db6…` |
| `config/retail_demo_config.json` | sha256 `955991f23fc15748…` |
| Generator / seed / as-of | `retail-gen-1.2.0` / `20260910` / `2026-08` |
| Published months | 25, `2024-08` … `2026-08` |
| Latest month | 59,412 facility rows, 42,898 distinct customers, content hash `05615a1af58d13d3…` |
| Analytics lake on disk | 2.3 GB across 6 datasets |
| Risk cases in the accepted demo database | 7, in 3 `about` kinds |

### Existing screens and route map (what this work extends, not replaces)

| Surface | File |
|---------|------|
| Cockpit / Requires Attention | `frontend/src/components/attention/requires-attention.tsx` |
| Right-hand drawer | `frontend/src/components/attention/case-drawer.tsx` |
| Thread case context | `frontend/src/components/attention/case-context.tsx` |
| Investigation thread | `frontend/src/app/investigations/[id]/page.tsx` |
| Saved investigation | `frontend/src/app/investigations/saved/[id]/page.tsx` |
| Borrower 360 | `frontend/src/app/borrower-360/page.tsx` |
| Early Warning | `frontend/src/app/early-warning/page.tsx` |
| What-If | `frontend/src/app/what-if/page.tsx`, `frontend/src/app/early-warning/whatif/[selectionId]/page.tsx` |
| Risk case API | `backend/api/routers/cases.py` |
| Retail API | `backend/api/routers/retail.py` |
| Exports API | `backend/api/routers/exports.py` |
| What-If API | `backend/api/routers/whatif.py` |
| Risk case contract | `backend/agentic/cases.py` (`Draft`, `upsert`, `dedupe_key`) |
| Retail review that raises cases | `backend/retail/review.py` |
| Accepted Alpha case figures | `backend/retail/anb_demo.py`, `backend/retail/anb_answers.py` |
| Generator | `backend/retail/generate.py` |

### Launcher ownership

`launchers/anb/start-anb.command` and `stop-anb.command` own **only** pids they
themselves recorded in `var/anb`, and stop a recorded pid together with its
descendants. They are bound to 5330/8330. They are left exactly as they are;
the new build gets its own launcher in P11 rather than a change to these.

### Blockers

None. No destructive or ambiguous baseline decision was encountered.

### Same-environment test baseline

Re-run at the verified SHA in this container, against `creditprobe_test`:

| Suite | Result |
|-------|--------|
| `tests/retail/test_ret_anb_card_investigation.py` (the accepted Alpha gates) | **40 passed, exit 0** |

The report's twenty attributed retail failures are not restated here as fact.
They are a claim to be re-proved against this same environment and the same
data in P10, where the specification requires attribution rather than a
green-suite assertion.

---

## P1 — Identity, metric and cohort contracts

### The three things added

**A published dictionary** (`backend/retail/metrics_contract.py`). Sixteen
measures, each with its grain, its denominator, its window and — as part of
the definition rather than beside it — the inference it does not support. Four
of them are routinely mistaken for each other: the *share* of the book in
1-29 DPD, the *rate at which facilities rolled* into it, the *observed default
rate* of a vintage over a matured window, and the model's *probability* over
the next twelve months. A figure with no entry here cannot be quoted:
`definition()` raises rather than returning a blank.

Missing data is four states, not a boolean — unavailable, stale, unverified,
inapplicable — because a coverage gap rendered as a zero is an assertion that
nothing is wrong.

**A cohort object** (`backend/retail/cohort.py`, migration `0043`). Every
handoff used to be a predicate that each module re-ran; when the book moved
beneath them the four modules resolved differently and nothing could see it.
Now the identifiers are written once and the link carries an opaque id. There
is no update path at all: narrowing writes a child that is *checked to be a
subset*, selecting writes a subset cohort, switching from flagged facilities
to all of a customer's facilities writes a new snapshot with recomputed
counts. `visited_steps` caps what an export may contain, so a workbook taken
at S1 cannot hold S5's policy actions. Authorisation is rechecked at read,
share, reopen and export, and a refusal is worded identically to an absence so
that asking cannot confirm somebody else's cohort exists.

**A story registry** (`backend/retail/episodes.py`,
`config/retail_episodes.json`). Each of the ten names the *columns* that carry
its pocket, the evidence columns its S1 and S3 decompose, which scoring model
its diagnosis rests on, and its grain. The config is generated from the two
attachments by `scripts/build_episode_config.py`, so it cannot drift from
them; the dimension mapping is in code, because which column means which thing
is an engineering decision about the installed book rather than a quotation.

### Files

| Added | |
|---|---|
| `backend/retail/metrics_contract.py` | sixteen measures and the coverage states |
| `backend/retail/cohort.py` | the CohortSnapshot service |
| `backend/retail/episodes.py` | the ten stories as dimensions |
| `config/retail_episodes.json` | generated structure of the ten stories |
| `scripts/build_episode_config.py` | the generator, so the config is checkable |
| `alembic/versions/0043_cohort_snapshot.py` | three tables |
| `tests/retail/test_ret_cpra_p1_contracts.py` | 34 gates |

| Changed | |
|---|---|
| `backend/models/platform.py` | `CohortSnapshot`, `SavedInvestigation`, `InvestigationNote` |
| `tests/retail/conftest.py` | a rolled-back `db_session` fixture |

### Migrations

`0042 -> 0043`. Applied to `creditprobe_anb_v2` and to `creditprobe_test`. The
accepted demo's database was not touched.

### Tests

`tests/retail/test_ret_cpra_p1_contracts.py`: **34 passed, 0 skipped**. The
book-level invariants read the shipped 59,412-facility lake, not a temporary
build: unique facility-month, a grain-safe Early Warning join that leaves total
ECL unchanged to the cent, an original application score that has not moved in
25 months, identity coverage in every month, and a reachable denominator for
every rate.

### Blockers

None.

---

## P2 — Ten coherent synthetic episodes

### How the nine are made

Membership first, pressure second. Each episode picks an eligible population
out of the real book — personal loans to financed employees, auto contracts
whose final payment falls inside two quarters, self-construction mortgages,
supported mortgages, matured arrangements — then marks a pocket inside it, then
applies its mechanism mostly to the pocket and rarely outside it.

The mechanism is applied to the **records**, never to a figure. A payroll
interruption is missing salary credits and a collapsed cash buffer; the
behavioural scorecard reads it as a behavioural scorecard, the staging rules as
staging rules, the ECL engine as the ECL engine. Nothing writes a score, a
stage or a loss.

The measured concentration is therefore a measurement: the published predicate
runs over the resulting columns exactly as it will in production, and the
incidence inside and outside the pocket is counted.

### What the nine actually do

| Case | Lever pulled | What is NOT touched |
|---|---|---|
| C02 | Weak approvals default from the first instalment; clocked on months-on-book so a matched earlier vintage exists in the same dataset | the behavioural score — this is the application-model story |
| C03 | Salary credits stop for two cycles; the household balance follows | — |
| C04 | New external obligations arrive monthly; residual income drains | — |
| C05 | Liquid coverage of a contractual balloon falls; the balloon does not | the contract |
| C06 | Expected net proceeds fall and recovery takes six months longer | the collateral, the balance, every behavioural input |
| C07 | Milestones slip past the tolerance; housing outgoings rise | — |
| C08 | An expected support credit does not post, repeatedly | the customer's own payments |
| C09 | Documented pension replaces part of verified income; commitments do not move | age — the rule reads the transition and the obligations |
| C10 | A matured arrangement is not kept and defaults again inside the window | — |

### Three negative controls, as tests rather than sentences

**C06** marks down the expected *proceeds*, not the *asset*. Marking the asset
down would move loan-to-value, which is a behavioural feature, which would
worsen the borrower this story exists to exonerate. Measured on the shipped
book: LGD 0.12 to 0.31, recovery delay 9 to 15 months, ECL up 4.4x — and the
revised cohort's median behavioural score and 12-month PD within tolerance of
the rest of its own book.

**C09** selects on `pension_income_replacement` and
`pension_obligations_to_income`. A gate proves the second clause excludes
somebody, so the rule is not really "their income fell".

**C02 and C10** carry a matched earlier cohort in the same dataset and compare
against it. Comparing this vintage with itself a month ago is comparing the
episode with itself.

### Measured on the shipped 59,416-facility book

| Case | Eligible | Issue | Rate | vs comparator | Pocket holds | Incidence in / out |
|---|---|---|---|---|---|---|
| C01 | 5,402 | 1,539 | 28.5% | 4.5x | 86.6% | 51.4% / 7.3% |
| C02 | 504 | 76 | 15.1% | 10.1x | 67.1% | 35.2% / 7.0% |
| C03 | 6,336 | 1,379 | 21.8% | 4.3x | 83.7% | 60.2% / 5.1% |
| C04 | 6,729 | 1,295 | 19.3% | 3.4x | 83.6% | 35.7% / 5.7% |
| C05 | 243 | 40 | 16.5% | 1.7x | 47.5% | 76.0% / 9.6% |
| C06 | 4,355 | 677 | 15.6% | 3.5x | 80.5% | 38.4% / 4.5% |
| C07 | 1,356 | 173 | 12.8% | 2.5x | 68.8% | 41.9% / 5.0% |
| C08 | 2,020 | 247 | 12.2% | 4.1x | 81.8% | 39.8% / 3.0% |
| C09 | 1,186 | 219 | 18.5% | 3.3x | 82.2% | 37.2% / 5.6% |
| C10 | 2,011 | 259 | 12.9% | 8.3x | 88.4% | 22.1% / 3.1% |

C05's pocket is small because the book holds only 25 contracts with a balloon
at or above 35% of price inside the window, and the pocket is read off the
contracts rather than seeded — an honest 1.7x rather than a manufactured 4x.

### The accepted Alpha calibration

Unmoved. Alpha's 1-29 share is 0.2849 on both the accepted build and this one,
its 20-29 concentration is identical, and its utilisation matches to four
decimal places. Four extra facilities survive across the whole book
(59,412 to 59,416) because nine episodes changed a handful of closures; the
only visible consequence is Alpha's weak-and-very-weak band share moving from
0.3206 to 0.3210. No episode touches the card book, and a gate asserts it.

Book-level effect of the nine: gross carrying amount +0.27%, ECL
SAR 70.4m to SAR 110.9m, stage 3 894 to 1,461 facilities.

### Files

| Added | |
|---|---|
| `backend/retail/episode_overlay.py` | the nine episodes' membership and mechanisms |
| `backend/retail/episode_measures.py` | the reader every card, drawer, thread and export uses |
| `tests/retail/test_ret_cpra_p2_episodes.py` | 22 gates |

| Changed | |
|---|---|
| `backend/retail/generate.py` | five hook points: assign, one miss-logit summand, one catch-up summand, a recovery-delay summand, a recovery haircut, the month's evidence and the frame's columns |
| `backend/retail/config.py` | an optional `episodes` block |
| `config/retail_demo_config.json` | nine calibrations |
| `backend/retail/episodes.py` | the ten issue predicates, scope and outcome clauses apart |

### Tests

22 P2 gates, and the 40 accepted Alpha gates re-run on the new book: **62
passed**.

### Blockers

None.

---

## P3 — Atomic Cockpit/EWS publication

### The failure this closes

Six datasets were built one after another, each idempotent and each skipping
what it already had. That is correct while the book underneath is the same
book. Regenerating it changes every period WITHOUT changing their names, so an
incremental build of the views has nothing to do and they go on serving the
previous book's figures — reconciled against a canonical total they no longer
match. A build that failed halfway published a new Cockpit book beside
yesterday's Early Warning. None of it produced an error; it produced answers.

`scripts/publish_retail_bundle.py` builds everything into a staging tree,
validates it, and swaps in one move. Six checks gate the swap:

| Check | Result on this publication |
|---|---|
| every dataset present | 6 datasets, all with published periods |
| Early Warning ends where the book ends | book 2026-08, panel 2026-08 |
| every pocket exists in both the Cockpit and Early Warning | all 10 present at 2026-08 |
| the Early Warning join is grain-safe | total ECL SAR 110,922,285.79 before and after |
| a facility-month is unique | 59,416 rows, 59,416 facilities |
| the five registrations survive publication | 5 present |

### The registration check exists because the publication broke it

`write_catalog` replaces the catalogue with the canonical book alone — right
for what it knows about, and wrong as the last word, because four governed
views and the Early Warning score were registered in it. The first run of this
publisher reduced the catalogue from five registrations to one. A screen
reading a lost registration opens **empty** rather than failing, so nothing
would have said so. Registration is now part of the publication and the count
is a gate; below five, the catalogue and the tree both roll back.

### Published bundle

`RB-E7BA202A45842B71`, as of 2026-08, seed 20260910, with per-dataset content
hashes over the published parquet files. A cohort snapshot records the bundle
it was measured on, and `bundle.require_same()` refuses a join across two —
including a join to a figure that does not record its provenance at all.

### Files

| Added | |
|---|---|
| `backend/retail/bundle.py` | bundle identity, hashing, the stale-join refusal |
| `scripts/publish_retail_bundle.py` | stage, validate, swap, register, verify |
| `tests/retail/test_ret_cpra_p3_bundle.py` | 8 gates, one of which runs the publisher against a tree it must reject and proves the previous bundle survives |

### Tests

8 P3 gates. All CPRA gates plus the accepted Alpha suite: **104 passed**.

### Blockers

None.

---

## P4 — Ten evidence-driven cards and drawers

### One adapter, not nine templates

`backend/retail/episode_cases.py` reads a story's measured populations out of
`episode_measures` and writes a Risk Case Draft from them. There is no
per-story card text: a conclusion is assembled from the figures it quotes, so
it cannot disagree with them, and a story whose numbers move produces a card
whose words move with them.

### Severity is arithmetic

Five governed components, each carrying the raw figure behind it: materiality
(affected against eligible, and the exposure), magnitude (the multiple over
the comparator), concentration (the pocket's share of the cases), persistence
(rising month-ends) and data confidence (the corroborated share). A gate
recomputes the band from the components at the published precision.

Measured on the shipped book:

| Case | Band | Score | Exposure |
|---|---|---|---|
| C02 | critical | 0.829 | SAR 8.8m |
| C03 | critical | 0.900 | SAR 89.2m |
| C04 | critical | 0.833 | SAR 88.1m |
| C05 | **medium** | 0.550 | SAR 0.4m |
| C06 | critical | 0.813 | SAR 50.2m |
| C07 | **high** | 0.678 | SAR 114.8m |
| C08 | **high** | 0.674 | SAR 151.5m |
| C09 | critical | 0.848 | SAR 11.1m |
| C10 | critical | 0.845 | SAR 20.2m |

Three different bands from one formula. No threshold was moved to make a
demonstration look worse, and a gate fails if every story comes out the same.

A review against the demonstration database opened **16 cases**: the nine
here, Alpha from the accepted early-delinquency rule, and the six the
deterioration and impairment rules already raised.

### A hole the gates found

`draft()` would return a card for C01 if asked directly, duplicating the Alpha
finding — and `dedupe_key` would not have caught it, because the two carry
different `about` values and are therefore different findings as far as the
Risk Case store is concerned. The refusal now lives in `draft()` rather than in
the loop above it.

### The drawer (U02)

`frontend/src/components/attention/episode-panels.tsx` renders six stacked
panels, each carrying its own denominator, comparator and coverage: affected
population, normalised pocket, probability of default and loss, scores, the
rule that was evaluated, and sources. Where a figure does not apply — a
forward probability of default for a cohort that has already defaulted — the
panel says so in the place the figure would have been. Cases that carry no
episode drawer render nothing, so the drawer a signed-off demonstration opens
on is unchanged.

---

## P5 — Stateful investigation threads

### Reading

`episode_answers.read()` matches a chip click on the whole configured prompt
first, then five paraphrase patterns written about the SHAPE of each question
rather than any one story's vocabulary. Gated on the thread: the five
questions do not name their own subject, so outside an investigation whose
Risk Case says which story it is, `read` returns nothing and the planner
answers. "What should we do next?" reaching a payroll recommendation in a
conversation about mortgages is the failure this closes.

Routed in `orchestrator.py` beside the accepted Alpha route, with the same
never-raises contract.

### Narrowing

| Step | Cohort |
|---|---|
| S0 | the issue population |
| S1 | alerts whose evidence reached VERIFIED_DETAIL |
| S2 | the same identifiers as S1, held fixed |
| S3 | corroborated evidence |
| S4 | corroborated AND inside the named pocket |
| S5 | exactly S4's scope |

A gate proves every step is a subset of the one before it across all nine
stories. Measured customer counts, S1 through S5:

| Case | S1 | S2 | S3 | S4 | S5 |
|---|---|---|---|---|---|
| C02 | 56 | 56 | 50 | 35 | 35 |
| C03 | 1,141 | 1,141 | 1,010 | 845 | 845 |
| C04 | 1,045 | 1,045 | 918 | 772 | 772 |
| C05 | 27 | 27 | 25 | 11 | 11 |
| C06 | 536 | 536 | 492 | 399 | 399 |
| C07 | 147 | 147 | 136 | 90 | 90 |
| C08 | 189 | 189 | 146 | 115 | 115 |
| C09 | 188 | 188 | 150 | 124 | 124 |
| C10 | 197 | 197 | 174 | 162 | 162 |

All 45 steps answer. Each carries its scope line, two to five evidence
observations, the story's own countercheck as the counterargument, the
recommended next question, a Trace, and `execution="analysis"` so the Trace
consistency contract knows a computation ran.

---

## P6 — Versioned policy action engine

Thirty clauses, effective-dated, every one `DEMO_DRAFT - NOT BANK APPROVED`.
`claims_compliance()` returns False for all of them, `executed` is False on
every action, and an S5 answer leads with the draft status rather than
footnoting it — a recommendation that reads as compliant when it is not is the
most expensive sentence this product could produce.

A clause outside its effective dates produces an action marked unsupported
with the reason, not an action with a caveat.

Each story's What-If trial names its family, what it affects, what it must not
do and what it does not model. The limit trial says a cut does not repay a
drawing; the recovery trial says the probability of default is held. Without an
approved exposure budget nothing is solved for, so the percentages are trials
and are labelled as such.

### Files

| Added | |
|---|---|
| `backend/retail/episode_cases.py` | the nine cards |
| `backend/retail/episode_answers.py` | reading and answering the six steps |
| `backend/retail/episode_policy.py` | effective-dated draft clauses and scenario families |
| `frontend/src/components/attention/episode-panels.tsx` | the stacked drawer panels |
| `tests/retail/test_ret_cpra_p4_p6_cards_threads.py` | 25 gates |

| Changed | |
|---|---|
| `backend/retail/review.py` | the nine adapters in the review loop |
| `backend/orchestration/orchestrator.py` | the episode investigation route |
| `backend/retail/episode_measures.py` | trend, risk, scores and the assembled drawer |
| `frontend/src/components/attention/case-drawer.tsx` | renders the panels |

### Tests

**129 passed**: 34 P1, 22 P2, 8 P3, 25 P4-P6, 40 accepted Alpha. Frontend
typecheck clean.

### Blockers

None. The thread UI itself — chips above the composer and the export toolbar —
is P7's commit; the backend they read is here.

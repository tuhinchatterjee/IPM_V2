# Final acceptance matrix

Every gate this closure run was asked to audit, with the evidence for the
status beside it. Compiled on the branch's final HEAD, against the running
application, not from memory.

## About the numbering — read this first

The instruction was to audit "every one of the 95 acceptance gates". **There is
no canonical numbered list of 95 gates anywhere in this repository.** The gates
were set across a long series of prompts and were never written down here as a
list. Inventing numbers 1 to 95 to match a list I do not hold would be exactly
the fabrication this run is meant to eliminate, so I have not done it.

What follows instead is a matrix over the capability surface those gates
govern — the Project Planner, Lenses 2.0, the Metric Catalogue, the Custom
Metric Builder, the Custom Chart Builder, the demonstration, the AI and email
posture, and the calculation and permission invariants underneath them. It is
enumerated from what is actually in the product: every route in the live
OpenAPI document, every shipped lens, every governed metric, every acceptance
journey. Gate identifiers are area-prefixed and stable (`PL-01`, `LX-01`, and
so on). If the canonical numbered list exists elsewhere, mapping onto it is a
rename, and every row below already carries the evidence a mapped gate would
need.

**Status is one of four words, and nothing else:**

| Status | What it means |
| --- | --- |
| PASS | Verified on this HEAD, by the evidence in the row. |
| FAIL | Verified not to work. |
| NOT APPLICABLE | The gate does not apply to this deployment, with the reason. |
| NOT VERIFIED | Not established here. Never a synonym for "probably fine". |

No status is inferred from nearby functionality. Where a row says PASS, the
evidence column names the test, journey checkpoint or command that produced it.

---

## 1. Project Planner — the record (PL)

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| PL-01 | A project, its workstreams, tasks, milestones, dependencies and RAID items can be created and read | PASS | 37 planner routes in the live OpenAPI document; 270 tests green | `backend/api/routers/planner.py`; `tests/planner/` | |
| PL-02 | Every change is recorded with what it was before and what it is now | PASS | `PlannerUpdate.changes` is `{field: [before, after]}`; journey checkpoint 11 read 6 matching history rows | `backend/planner/service.py:update_task`; `scripts/acceptance/planner_demo_journey.py` | |
| PL-03 | History is append-only | PASS | No update or delete path to `PlannerUpdate` exists in the service | `backend/planner/service.py` | |
| PL-04 | The audit row names the authenticated actor, not the system | PASS | Journey checkpoint 12 read `fatima.khan` on all three rows | demo journey checkpoint 12 | |
| PL-05 | Every change records which door it came through | PASS | `source ∈ (UI, API, AI, AI_CHAT, EXCEL_IMPORT, SYSTEM)` | `backend/planner/service.py` | |
| PL-06 | A task update recalculates workstream and project progress | PASS | Journey checkpoint 13: project 73 → 75 after a task moved 30 → 80 | demo journey checkpoint 13 | |
| PL-07 | Project health is calculated and says why | PASS | Journey checkpoint 14: "AMBER — 2 tasks overdue, 6 near-term tasks without a recent update" | demo journey checkpoint 14 | |
| PL-08 | Percent complete is never accepted outside 0–100 | PASS | `_percent()` clamps and `_align_task_state` reconciles status | `tests/planner/test_control.py` | |
| PL-09 | A blocked task without a reason is refused | PASS | `PlannerError` raised in `update_task` | `backend/planner/service.py`; `tests/planner/test_control.py` | |
| PL-10 | A due date before a start date is refused | PASS | `PlannerError` naming both dates | `backend/planner/service.py` | |

## 2. Project Planner — monitoring and the chase loop (PM)

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| PM-01 | The condition is detected by an engine, not by a person pressing send | PASS | Journey checkpoint 5: no manual send-reminder route exists; checkpoint 6: evaluation produced the message | demo journey checkpoints 5, 6 | |
| PM-02 | The reminder reaches the task's owner | PASS | Journey checkpoint 7: 1 in Fatima's inbox, addressed to her by the engine | demo journey checkpoint 7 | |
| PM-03 | It reaches nobody else | PASS | Journey checkpoint 8: 0 in the bystander's inbox, 0 addressed elsewhere | demo journey checkpoint 8 | |
| PM-04 | The notification deep-links to the task it is about | PASS | Journey checkpoint 9: `planner_task:281:13735` | demo journey checkpoint 9 | |
| PM-05 | Running the evaluation twice does not send twice | PASS | Fingerprint is `project:entity_type:entity_id:user:trigger:about` | `tests/planner/test_monitor.py` | |
| PM-06 | A moved due date re-arms the reminder | PASS | For DUE, `about = f"{task.due_date}:{near}"`, so the fingerprint changes with the date | `backend/planner/monitor.py`; `tests/planner/test_demo_refresh.py` | |
| PM-07 | An owner's update closes the chase | PASS | Journey checkpoint 15: 0 chases open on T-503 after Fatima's update | demo journey checkpoint 15 | |
| PM-08 | The estate-wide sweep is administrators-only | PASS | Journey checkpoint 5.1: HTTP 403 for a project manager, by design | `POST /api/v1/planner/sweep` is `RequireAdmin` | |
| PM-09 | The sweep supports a dry run that sends nothing | PASS | `dry_run=true` returns `would_send`; the journey uses it throughout | `backend/api/routers/planner.py` | |
| PM-10 | Reminder thresholds are configuration, not scattered constants | PASS | `THRESHOLDS = [7, 3, 1, 0]`, read in one place | `backend/planner/monitor.py` | |

## 3. Project Planner — schedule, CPM and consequence (PS)

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| PS-01 | A real critical-path calculation — forward pass, backward pass, float | PASS | Implemented and tested; 26 + 13 + 10 tests across three files | `backend/planner/schedule.py`; `tests/planner/test_schedule.py`, `test_scheduling.py`, `test_schedule_http.py` | |
| PS-02 | CPM refuses rather than guesses when the graph will not support it | PASS | "Or an honest refusal" — cycles and missing dates are named | `backend/planner/schedule.py` | |
| PS-03 | Slipping a task reports what sits downstream | PASS | Journey checkpoint 17: 1,294 characters of consequence from `GET /slip` | demo journey checkpoint 17 | |
| PS-04 | Downstream consequence is recomputed, not reasoned about from float | PASS | Comment and implementation at `schedule.py:485` | `backend/planner/schedule.py` | |
| PS-05 | "What changed" gives a manager a structured answer | PASS | Journey checkpoint 16: 132,158 characters of change context including the update | demo journey checkpoint 16 | |

## 4. Project Planner — permissions and the workbook (PP)

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| PP-01 | Every planner route enforces a permission | PASS | 12 HTTP permission tests | `tests/planner/test_permissions_http.py` | |
| PP-02 | Permissions are enforced server-side, never by hiding a control | PASS | `acl.visible_task` / `acl.may_update_task` inside the service, not the router | `backend/planner/access.py` | |
| PP-03 | An adversarial caller cannot reach another project's data | PASS | 24 adversarial tests | `tests/planner/test_adversarial.py` | |
| PP-04 | A project can be created from an Excel workbook | PASS | 11 tests; `POST /planner/imports` then `/commit` | `backend/planner/workbook.py`; `tests/planner/test_workbook_create.py` | |
| PP-05 | An import is staged and committed, never applied blind | PASS | Two-step route: `imports` then `imports/{id}/commit` | `backend/api/routers/planner.py` | |
| PP-06 | The workbook round-trips | PASS | 28 tests | `tests/planner/test_workbook.py` | |
| PP-07 | Planner performance is measured, not assumed | PASS | 7 performance tests | `tests/planner/test_performance.py` | |

## 5. The demonstration and its dates (DM)

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| DM-01 | Demo projects are explicitly identifiable as CreditProbe-managed | PASS | `demo_origin` column, partial index, adopted by data migration | `alembic/versions/0038_planner_demo_anchor.py` | |
| DM-02 | Dates can be rolled forward by command, without reseeding | PASS | `planner-demo --refresh-dates` | `scripts/seed_retail_portfolio.py`; `backend/planner/demo.py` | |
| DM-03 | The command has a dry run | PASS | `--dry-run` opens the same transaction and rolls it back | `scripts/seed_retail_portfolio.py` | |
| DM-04 | Progress, status, owner, contributors, narrative, RAID, roles and audit history all survive a refresh | PASS | Only the four canonical date field-sets move; 22 tests | `backend/planner/demo.py:FIELDS`; `tests/planner/test_demo_refresh.py` | |
| DM-05 | User-created projects are never touched | PASS | Every query is scoped by `demo_origin <> ''` | `backend/planner/demo.py` | |
| DM-06 | A human's date override is preserved and reported, not silently overwritten | PASS | `human_edited()` reads non-SYSTEM `PlannerUpdate` rows touching a date; `--force-demo-dates` required to override | `backend/planner/demo.py` | |
| DM-07 | The refresh is audited | PASS | `PLANNER_DEMO_DATES_REFRESHED` audit row plus a per-entity `record(...)` with a narrative | `backend/planner/demo.py:apply` | |
| DM-08 | Reminder eligibility is re-armed so an old fingerprint cannot suppress the demonstration | PASS | `svc.signal(session, pid, "task_due_date_changed")` after the shift | `backend/planner/demo.py` | |
| DM-09 | Running it twice on one calendar date changes nothing the second time | PASS | Idempotence test | `tests/planner/test_demo_refresh.py` | |
| DM-10 | It refuses to move dates backwards without an explicit force | PASS | `apply` refuses a negative shift and says why | `backend/planner/demo.py` | |
| DM-11 | The destructive reset still exists but is clearly demo-only | PASS | Retained, and its help text says so | `scripts/seed_retail_portfolio.py` | |
| DM-12 | The demo test does not depend on a database seeded today | PASS | `DAY_ONE = date(2026, 3, 10)`; no `date.today()` anywhere in the file | `tests/planner/test_demo_refresh.py` | |
| DM-13 | A regression reproduces the exact defect: seed Day 1, advance to Day 2, refresh, still demonstrable | PASS | The rollover test, with injected dates | `tests/planner/test_demo_refresh.py` | |
| DM-14 | Test fixtures leave no standing obligation in a development database | PASS | `world` fixture teardown deletes the project it built | `tests/planner/test_demo_refresh.py:_forget` | Added this run after the fixtures were found generating estate-wide reminders. |

## 6. The live demonstration flow (LD)

All eighteen checkpoints run as real authenticated users over HTTP against the
running application: Priya the manager, Fatima who owns the sign-off, Rohan who
owns nothing on it, and an administrator for the sweep.

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| LD-01 | The four demo programmes exist | PASS | Checkpoint 1 | `scripts/acceptance/planner_demo_journey.py` | |
| LD-02 | The intended task exists, owned by the intended person | PASS | Checkpoints 2, 3 | same | |
| LD-03 | It sits inside the reminder condition | PASS | Checkpoint 4: due 2026-09-07, 3 days out | same | |
| LD-04 | Checkpoints 5 through 17 | PASS | See PM-01 to PM-07, PS-03, PS-05 above | same | 18 passed, 0 failed. |
| LD-05 | The journey restores the demonstration so it can be run again | PASS | Restore now sits in a `finally`; T-503 back at its seeded 30 | same | The restore was silently skipped before this run; see notes in §11 of the report. |

## 7. Lenses 2.0 (LX)

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| LX-01 | Preconfigured lenses ship and install | PASS | 3 lenses installed: Retail Credit Risk, Retail Analytics, Corporate IFRS 9 | `backend/metrics/lenses.py` | The mandate names four including "CRO Portfolio"; see LX-02. |
| LX-02 | A CRO portfolio view exists | PASS | It is a hand-built page at `/lenses/cro`, **not** a Lens 2.0 object | `frontend/src/app/lenses/cro/page.tsx` | Stated rather than counted as a fourth lens: it does not go through the lens renderer, so none of the lens gates below apply to it. |
| LX-03 | Every tile on every shipped lens produces a real figure | PASS | Journey J, per tile not per sample: 0 failed, 0 claiming success with no number | journeys A, J | |
| LX-04 | Every figure is stamped with the period it is for | PASS | Journey J | journey J | |
| LX-05 | Every tile can explain itself without a second request | PASS | Journey J: formula, definition, and either source fields or the dataset grain, on every tile | journey J | |
| LX-06 | The info control opens and shows the arithmetic | PASS | Journey J opened one on each lens and read "how it is calculated", "what it measures", "where it comes from" | journeys B, J | |
| LX-07 | Nothing on screen is a placeholder | PASS | Journey J checks for NaN, undefined, [object Object], Infinity, TODO, FIXME, Lorem ipsum, placeholder, coming soon, sample data, dummy | journey J | |
| LX-08 | The IFRS 9 lens reconciles: three stage exposures sum to the total | PASS | Journey A, and again in the test suite | journey A; `tests/metrics/test_lenses.py` | |
| LX-09 | What a lens will NOT show is named, with the reason and what would be needed | PASS | 8 notes across the three lenses, each over 40 characters of reason | journeys F, J | |
| LX-10 | A lens can be rearranged by hand, and that is a version like any other | PASS | Journey H | journey H | |
| LX-11 | A rearrangement can be put back | PASS | Journey H restores the previous version | journey H | |
| LX-12 | Every revision carries a sentence saying what changed | PASS | Journeys H and I both assert it | journeys H, I | |
| LX-13 | A lens can be changed by asking, and the change is refused with a reason when it cannot be done | PASS | Journey D | journey D; `tests/metrics/test_lens_ask.py` | |
| LX-14 | Lens permissions are enforced | PASS | Deleting a lens requires a data steward — established this run when an analyst's delete returned 403 | `backend/api/routers/lenses.py:254` | |
| LX-15 | Lens rendering performance is measured | PASS | Per-render period memo; a lens no longer asks its dataset the same question 21 times | `scripts/acceptance/lens_performance.py` | |

## 8. Metric Catalogue and the Custom Metric Builder (MC)

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| MC-01 | A governed library of metrics, defined in code rather than in editable rows | PASS | 61 governed metrics | `backend/metrics/library.py` | |
| MC-02 | Every metric carries definition, formula, numerator, denominator, period rule, owner, origin and status | PASS | Journey B asserts all eight fields non-empty | journey B | |
| MC-03 | Every metric says what it is NOT | PASS | Journey B | journey B | |
| MC-04 | Every metric names the fields it reads, or the grain of what it counts | PASS | Journey J across every tile | journey J | The grain was added this run; a COUNT metric names no field because it reads none. |
| MC-05 | Search narrows as you type, and a second word removes suggestions | PASS | Journey C | journey C; `tests/metrics/test_search.py` | |
| MC-06 | Every suggestion says why it matched | PASS | Journey C | journey C | |
| MC-07 | A real user can build a metric in the UI, end to end | PASS | Journey G: build, preview, save, verify the saved metric computes what it previewed, find it, delete it | journey G | This is the §8 gate. |
| MC-08 | The builder offers only what the governed catalogue holds | PASS | Journey G: the dataset list is the governed one, not every table | journey G; `GET /metrics/vocabulary` | |
| MC-09 | The server refuses a formula naming a field that does not exist | PASS | The picker is a convenience; `formula.problems()` checks again on submission | `backend/metrics/formula.py`; `backend/api/routers/metrics.py` | |
| MC-10 | The previewed figure is the one the data supports, verified independently | PASS | Journey G: "the source data could be read independently", "the figure on screen is the one the data supports" | journey G | |
| MC-11 | The preview shows the working, not just the answer | PASS | Journey G | journey G | |
| MC-12 | A user-built metric is labelled as built here, not governed, and as a draft | PASS | Journey G asserts both labels | journey G | |
| MC-13 | A person can check a figure against their own number, including when they disagree | PASS | Journey E; a disagreement is recorded and confers nothing | journey E | |
| MC-14 | A metric's period is resolved to one that has data | PASS | `default_period()`, `periods_with_rows()`, `latest_matured_period()` | `backend/metrics/service.py`; `tests/metrics/test_service.py` | |
| MC-15 | A period with no rows is reported, never returned as zero | PASS | 9 tests added this run | `tests/metrics/test_maturity.py` | Found as a live defect on the Retail lens; see §7 of the report. |

## 9. Custom Chart Builder (CB)

Expected to be a FAIL at the start of this run, and it was: `_render_metric`
returned a scalar and `result: None`, so a tile could carry `visual="bar"` and
have nothing to draw with it. Implemented end to end this run.

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| CB-01 | A chart can be created and configured with a title | PASS | Journey I sets "Balance by product" and it renders | `frontend/src/components/lenses/chart-builder.tsx`; journey I | |
| CB-02 | …a metric, chosen from the governed catalogue | PASS | Journey I searches "outstanding balance" and picks the result | journey I | |
| CB-03 | …a dimension, offered from the dataset's own fields | PASS | Journey I: Product offered, Account id not | journey I | |
| CB-04 | …a grouping | PASS | The dimension IS the grouping: `GROUP BY` in the compiled plan | `backend/metrics/execution.py:compile_breakdown` | |
| CB-05 | …a period | PASS | Offered from `periods_with_rows`; disabled when the dimension is itself the period | chart builder step 3 | |
| CB-06 | …filters | PASS | Field and value both from the catalogue; checked again server-side | `backend/metrics/service.py:_chart_filters`; `tests/metrics/test_charts.py` | |
| CB-07 | …sorting, and a direction | PASS | By value or by name, ascending or descending | `tests/metrics/test_charts.py` | Sorting by value happens after evaluation: a ratio's value does not exist until its group is evaluated. |
| CB-08 | …an aggregation | PASS | The metric's own definition, the average per row, or a row count — and an overridden one is renamed for what it computes | `tests/metrics/test_charts.py` | |
| CB-09 | …a comparison | PASS | Previous period or the same period a year earlier, read the same way as the primary series | `tests/metrics/test_charts.py`; journey I | |
| CB-10 | …and a chart type | PASS | Journey I picks bar | journey I | |
| CB-11 | The chart can be added to a Lens | PASS | Journey I adds it and reads it back off the lens with its configuration intact | journey I | |
| CB-12 | Adding it is a version, not an overwrite | PASS | Journey I | journey I | |
| CB-13 | Inappropriate chart types are not offered, and say why | PASS | Journey I reads the refusals on screen: a line between unordered categories, a matrix off one dimension | journey I; `tests/metrics/test_charts.py` | |
| CB-14 | A metric computed by a governed function gets no chart at all | PASS | Gini, KS and PSI refuse with the reason | `tests/metrics/test_charts.py` | |
| CB-15 | The chart's Info control shows the formula and the lineage | PASS | Journey I opens it and reads "Grouped by", "Read from", the run id and the SQL | journey I | |
| CB-16 | The bars are the same calculation as the figure on the metric's own tile | PASS | Every point comes out of the same `evaluate()`; an additive metric's bars sum to its total to 1e-9 | `tests/metrics/test_charts.py` | |
| CB-17 | The final number reconciles outside the chart path entirely | PASS | Journey I reads the hive partition with pandas and groups by product — no formula, no IR, no compiler, no executor | journey I | |

## 10. Calculation honesty (CH)

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| CH-01 | Scorecard Gini is correctly calculated against the relevant population | PASS | 0.436901 from the product; 0.436901 from an independent Mann-Whitney AUROC over the same parquet | `backend/scorecard/metrics.py`; recomputed this run | |
| CH-02 | Scorecard KS is correctly calculated | PASS | 0.319707 from the product; 0.319707 independently | same | Was 0.320151 before this run — the maximum was being taken at intra-tie positions. Fixed. |
| CH-03 | AUROC is surfaced honestly where surfaced | PASS | Computed as 0.718451 and used to derive Gini; not presented as a separate lens tile | `backend/scorecard/metrics.py` | |
| CH-04 | PSI is either correct or honestly unavailable | PASS | Honestly unavailable: "PSI compares this period's score distribution against the reference distribution", listed under what the lens does not show | Retail Analytics lens notes | NOT fabricated. |
| CH-05 | Calibration (predicted versus observed) is calculated | PASS | 1.347426 at 2025-01, from matured rows | `retail.scorecard.calibration` | |
| CH-06 | No scorecard statistic is fabricated | PASS | Every one of the five above is either reproduced independently or shown as unavailable with a reason | this table | |
| CH-07 | An outcome that has not happened yet is not reported as zero | PASS | Retail Default Rate and Application Cohort Bad Rate now scope to matured rows and date to the latest matured period | `tests/metrics/test_maturity.py` | Both read 0.0% before this run. This was the most serious finding of the run. |
| CH-08 | A metric whose scope empties a period says so, and says what kind of gap it is | PASS | "Nothing in this period is inside this metric's scope… That is a fact about the population, not a failure." | `backend/metrics/execution.py:evaluate` | |
| CH-09 | A ratio with a zero denominator has no value rather than 0% | PASS | Pre-existing and unchanged | `backend/metrics/execution.py:evaluate` | |
| CH-10 | Numbers on a lens reconcile with each other | PASS | Stage exposures sum to the total; stage shares account for the whole book | journey A | |

## 11. Security and the query path (SQ)

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| SQ-01 | No path from a request body to SQL | PASS | Every metric and chart compiles to a validated `AnalyticalPlan` and goes through `runtime.executor.execute` | `backend/metrics/execution.py`; `backend/runtime/compiler.py` | |
| SQ-02 | A dimension named by a caller is checked against the catalogue | PASS | `series()` refuses `"1=1; DROP TABLE users"` with "not a dimension" | `tests/metrics/test_charts.py` | |
| SQ-03 | A filter column named by a caller is checked against the catalogue | PASS | `_chart_filters` refuses an unknown field | `tests/metrics/test_charts.py` | |
| SQ-04 | Queries are parameterised | PASS | The compiler binds values; only a bounds-checked integer LIMIT is inlined, and the reason is recorded in the code | `backend/runtime/compiler.py` | |
| SQ-05 | No unrestricted `eval` | PASS | The formula evaluator is a typed dataclass walk, not an expression evaluator | `backend/metrics/execution.py:evaluate` | |
| SQ-06 | Output rows are bounded | PASS | `PREVIEW_ROWS = 200`; `LIMIT limits.max_output_rows` (50,000); chart groups capped at 60 drawn from at most 500 read, and the cap is reported | `backend/runtime/`, `backend/metrics/execution.py` | |
| SQ-07 | A generated query cannot circumvent user permissions | PASS | Every route resolves a `Principal` and the service applies the ACL, not the router | `backend/api/permissions.py` | |

## 12. AI (AI)

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| AI-01 | Whether a provider is configured is inspected, not assumed | PASS | `provider_status()` → `{provider: "none", configured: false, state: "offline"}` | `backend/llm/__init__.py`, read live this run | |
| AI-02 | A live chat and agent suite against a real provider | **NOT VERIFIED** | **LIVE AI — NOT VERIFIED IN THIS ENVIRONMENT.** No API key is configured; no live call was made and none was faked. | — | See §4 of the report. |
| AI-03 | The governance boundary: an AI request to move a commitment must not silently change it | PASS | Deterministic: every AI mutation goes through `service.update_task` with `source=AI`, producing an audit row and a `changes` entry. There is no path that writes a date without one. | `backend/planner/actions.py`, `backend/planner/agent.py`; 19 + 16 tests | Verified deterministically. Not verified with a live model — see AI-02. |
| AI-04 | The product states its AI posture honestly to the user | PASS | Header reads "GOVERNED LOCAL READER"; the detail names the deterministic semantic planner | read on screen this run | |
| AI-05 | Deterministic planner and agent behaviour is tested | PASS | 270 planner tests green, including 19 agent and 16 action tests | `tests/planner/` | |

## 13. Email and notification (EM)

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| EM-01 | Whether outbound mail is configured is inspected | PASS | `channels.describe()` → email `available: false` | `backend/planner/channels.py`, read live this run | |
| EM-02 | External email delivery | **NOT VERIFIED** | **EXTERNAL EMAIL — NOT CONFIGURED / NOT VERIFIED.** No outbound mail provider is configured. No delivery was claimed. | — | |
| EM-03 | In-app notification delivery works | PASS | Journey checkpoints 7, 8, 9 | demo journey | |
| EM-04 | The product does not claim an email was sent | PASS | `composed_but_not_sent: ["email"]`, `delivered: ["in_app"]`, and the reason names what adding one would require | `backend/planner/channels.py` | |
| EM-05 | The architecture is ready for a transport to be added | PASS | Every reminder is composed in a form an email transport could send unchanged | `backend/planner/channels.py` | Architecture verified by reading; no transport exercised. |

## 14. Regression and gates (RG)

| Gate | Requirement | Status | Evidence | Test / route / file | Notes |
| --- | --- | --- | --- | --- | --- |
| RG-01 | The full backend suite is green on final HEAD | See the report | `python -m pytest tests` | — | Result recorded in §S of the final report. |
| RG-02 | No demo scenario depends on "the seed happened today" | PASS | The two date-dependent test files were made deterministic without weakening a single assertion | `tests/planner/test_demo_refresh.py`, `test_demo_portfolio.py` | |
| RG-03 | Lint is clean | PASS | `ruff check` over `backend scripts tests` | — | |
| RG-04 | The frontend typechecks and lints | PASS | `npx tsc --noEmit`; `npm run lint` | — | |
| RG-05 | The frontend builds | PASS | `npx next build` | — | |
| RG-06 | Browser journeys pass | PASS | 128 passed, 0 failed across A–J | `scripts/acceptance/lens_journeys.py` | |
| RG-07 | The live demo journey passes | PASS | 18 passed, 0 failed | `scripts/acceptance/planner_demo_journey.py` | |
| RG-08 | Migrations are at one head | PASS | `alembic heads` → `0038 (head)` | `alembic/versions/` | |
| RG-09 | The Docker stack builds and runs | **NOT VERIFIED IN CLAUDE SANDBOX** | Docker cannot run in this environment. Not attempted, not claimed. | `docker-compose.yml` | |
| RG-10 | An acceptance run leaves the database as it found it | PASS | Established this run: it did not, for thirteen lenses. Now it does, and asserts it. | `scripts/acceptance/lens_journeys.py:_discard` | |

---

## Tally

Counted from the rows above rather than typed alongside them:

| Status | Count |
| --- | --- |
| PASS | 131 |
| FAIL | 0 |
| NOT APPLICABLE | 0 |
| NOT VERIFIED | 3 |
| Recorded in the final report | 1 |
| **Total gates** | **135** |

    python - <<'EOF'
    import collections, pathlib, re
    rows = [l for l in pathlib.Path("docs/FINAL_ACCEPTANCE_MATRIX.md")
            .read_text().splitlines() if re.match(r"^\| [A-Z]{2}-\d\d \|", l)]
    print(collections.Counter(l.split("|")[3].strip().replace("**", "")
                              for l in rows))
    EOF

The three NOT VERIFIED rows are AI-02 (no AI provider is configured in this
environment), EM-02 (no outbound mail provider is configured) and RG-09
(Docker cannot run in this sandbox). None of the three is a defect in the
product; all three are facts about where it was run, and none was papered
over. RG-01 — the full backend suite on final HEAD — is recorded in the final
report instead of here, so that it carries the run's actual output rather than
a status typed ahead of it.

There are 135 gates rather than 95 because the areas are enumerated from the
capability surface, which is finer-grained than a hand-kept list would be. See
the note at the top: no canonical numbered list of 95 exists in this
repository, and inventing one would defeat the purpose of the exercise.

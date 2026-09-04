# Final closure report

Branch `claude/vigilant-darwin-eohyi1`. Nothing merged to `main`; no pull
request opened. Every fact below was read from the final HEAD or from the
running application during this run.

---

## A. What was asked, and what this is

A closure run over eleven sections: fix the demonstration's date-rollover
defect without destroying anybody's data, fix the test architecture that
depended on it, prove the demonstration through the real application as real
users, establish the live-AI and email posture honestly, audit every
acceptance gate, inspect the preconfigured lenses as a client would, prove the
custom metric journey, implement the Custom Chart Builder if it was not
already there, run the full regression, and report.

It found four defects the product was shipping and one it was shipping in its
own test harness. All five are fixed. The Custom Chart Builder did not exist
and now does.

## B. The five findings

**1. The demonstration decayed with the calendar.** Its dates were seeded
relative to the day it was built, so by the next day the sign-off no longer sat
inside the reminder threshold and the demonstration no longer demonstrated
anything. The only existing remedy was a destructive reseed.

**2. A default rate of 0.0% on the Retail Credit Risk lens.** Nineteen
thousand accounts, no defaults, for July 2025. Not one of those accounts had
had its performance window close, so `actual_default` was false on every row
and the metric divided nought by nineteen thousand. A zero on a lens is a
claim about the book; that one was a claim about the calendar. The application
cohort bad rate had the identical defect, and its own caveat note already said
so while the tile went on showing the zero.

**3. Scorecard KS was overstated.** The cumulative distributions step once per
ROW, and the implementation took its maximum over every row position —
including positions inside a block of rows sharing one score, which are not
points of the score domain at all but an artefact of the order the ties were
read in. It reported 0.32015 where the distributions support 0.31971. On a
coarsely banded scorecard the error would be much larger.

**4. The Custom Chart Builder did not exist.** `_render_metric` returned a
scalar and `result: None`, so a lens tile could carry `visual="bar"` and have
nothing to draw with it.

**5. The acceptance harness lied about cleaning up after itself.** Deleting a
lens is a data steward's action; the journeys sign in as an analyst on purpose;
the teardown went through the API as that analyst, took a 403, and returned
without looking. Thirteen scratch lenses were sitting in the database. A
separate instance of the same class of bug had the demo journey's own restore
step silently skipped, which had quietly turned its tenth checkpoint into an
assertion that changed nothing and passed.

## C. §1 — the demo date rollover, fixed without destroying data

A demonstration can now be rolled forward instead of rebuilt.

- Demo projects are explicitly marked: `demo_origin` and `demo_anchor_date`,
  with a partial index and a data migration adopting the four seeded codes
  (`alembic/versions/0038_planner_demo_anchor.py`).
- `planner-demo --refresh-dates` shifts them by `(today − anchor)` days.
  `--dry-run` opens the same transaction and rolls it back.
- Only the four canonical date field-sets move. Progress, status, owner,
  contributors, reviewers, narrative, RAID, participant roles and audit
  history are untouched, and 22 tests hold that shut.
- User-created projects are never touched: every query is scoped by
  `demo_origin <> ''`.
- A human's date override is detected by reading non-`SYSTEM` history rows that
  touch a date field. It is preserved and reported; `--force-demo-dates` is
  required to override it. A human commitment is never silently overwritten.
- The refresh is audited (`PLANNER_DEMO_DATES_REFRESHED`) and records a
  per-entity narrative saying what moved and by how much.
- Reminder eligibility is re-armed with `signal(..., "task_due_date_changed")`,
  so an old fingerprint cannot suppress the re-anchored demonstration.
- It is idempotent for one calendar date, and refuses to move dates backwards
  without an explicit force.
- The destructive reset still exists and is still clearly demo-only.

## D. §2 — the test architecture

`tests/planner/test_demo_refresh.py` builds its own world with injected dates —
`DAY_ONE = date(2026, 3, 10)` — and calls `date.today()` nowhere. It proves
today-at-threshold, one request to the owner, no duplicate on a second run,
the chase resolving when the owner updates, and future reminder logic as time
advances. The specific regression is there too: seed Day 1, advance to Day 2,
refresh, still demonstrable.

`tests/planner/test_demo_portfolio.py` re-anchors before it reads. **Not one
assertion in either file was weakened.** The dates were made honest instead.

Its fixtures now clean up after themselves. They had been leaving `T-503`-coded,
demo-marked, threshold-due projects in the development database, and those were
generating estate-wide reminders — which is how the demo journey came to report
"97 addressed elsewhere".

## E. §3 — the live demonstration: 18 of 18

Driven through the running application over HTTP as real authenticated users:
Priya the manager, Fatima who owns the sign-off, Rohan who owns nothing on it,
and an administrator for the sweep.

The condition is detected by the engine and nobody presses send (there is no
route to press). A project manager firing the estate-wide sweep is a 403 by
design, and checkpoint 5.1 says so out loud. Fatima receives the notification,
Rohan does not, and it deep-links to `planner_task:281:13735`. Her update moves
the task 30 → 80, the project 73 → 75, health recalculates to AMBER with a
reason, the chase closes, "what changed" sees it, and slipping the task returns
its downstream consequence.

`18 passed, 0 failed.` The run restores the demonstration to its seeded state so
it can be run again.

## F. §4 — live AI

**LIVE AI — NOT VERIFIED IN THIS ENVIRONMENT.**

`provider_status()`, read live during this run:

    provider: none    configured: false    state: offline

No API key is configured, no live call was made, and none was faked. The
product says the same thing to the user's face: the header reads GOVERNED
LOCAL READER.

What WAS verified, deterministically, on this HEAD:

- **The governance boundary holds structurally, not by a check.** There is no
  tool that can move a due date. `post_task_update` has no `due_date`
  parameter, so passing one is a `TypeError` rather than something a permission
  check has to catch correctly; `complete_task`, `change_task_owner`,
  `move_due_date`, `cancel_task`, `close_risk` and `set_project_health` are in
  `NO_TOOL_EXISTS` and absent from the registry. A tool that does not exist
  cannot be called however a model is prompted.
- The single writer in the planner tool registry only drafts, and says "does
  not send" in its own purpose text.
- Asked through the live `/api/v1/ask` route to "Move the Management Overlay
  Sign-off out by two weeks", the product returned an honest clarification and
  **T-503's due date was 2026-09-07 before and 2026-09-07 after**.
- 35 tests across `tests/planner/test_actions.py` and `test_agent.py` green;
  270 planner tests green in total.

## G. §5 — email

**EXTERNAL EMAIL — NOT CONFIGURED / NOT VERIFIED.**

`channels.describe()`, read live during this run, reports email
`available: false`, `delivered: ["in_app"]`,
`composed_but_not_sent: ["email"]`, and gives the reason: there is no outbound
mail provider, and adding one is a platform change needing a governed sending
identity, a provider, and the approval that goes with putting a bank's name on
outbound mail.

No delivery was claimed anywhere. In-app delivery **is** verified — journey
checkpoints 7, 8 and 9. The architecture is ready: every reminder is composed
in a form an email transport could send unchanged.

## H. §6 — the acceptance matrix

`docs/FINAL_ACCEPTANCE_MATRIX.md`.

**There is no canonical numbered list of 95 acceptance gates in this
repository.** The gates were set across a long series of prompts and were never
written down here. Inventing numbers 1 to 95 to match a list I do not hold
would be exactly the fabrication this run exists to eliminate, so the matrix
says that in its first paragraph and enumerates 135 gates from the capability
surface instead, with area-prefixed stable identifiers and, on every row, the
test, journey checkpoint or command that produced its status.

Status is one of four words and nothing else:

| Status | Count |
| --- | --- |
| PASS | 131 |
| FAIL | 0 |
| NOT APPLICABLE | 0 |
| NOT VERIFIED | 3 |
| Recorded in this report | 1 |

The three NOT VERIFIED are live AI, external email and Docker. None is a defect
in the product; all three are facts about where it was run.

## I. §7 — the preconfigured lenses

Three lenses ship: Retail Credit Risk, Retail Analytics, Corporate IFRS 9. The
CRO portfolio view exists as a hand-built page at `/lenses/cro`; it is **not** a
Lens 2.0 object and does not go through the lens renderer, so the lens gates do
not apply to it. That is stated rather than counted as a fourth lens.

Journey J reads all three the way somebody would read them in a meeting, tile by
tile rather than by sample: no tile failed, none claims success with no number,
every gap gives a reason, every figure is stamped with its period, every tile
carries its own definition, every tile has an info control that opens and shows
the arithmetic, and nothing on screen is a placeholder (NaN, undefined,
`[object Object]`, TODO, Lorem ipsum, sample data and six more).

**Scorecard statistics, each checked independently against the parquet:**

| Statistic | Product | Independent | Verdict |
| --- | --- | --- | --- |
| Gini | 0.436901 | 0.436901 (Mann-Whitney AUROC) | Exact |
| AUROC | 0.718451 | 0.718451 | Exact |
| KS | 0.319707 | 0.319707 | Exact **after the fix**; was 0.320151 |
| Predicted vs observed | 1.347426 | — | Calculated from matured rows |
| PSI | not shown | — | **Honestly unavailable**, with the reason |

No scorecard statistic is fabricated. PSI is listed under what the lens does not
show, with an explanation, rather than approximated.

**Independent spot-checks** beyond the scorecard: the three IFRS 9 stage
exposures sum to the total exposure and the stage shares account for the whole
book (journey A); an additive metric's chart bars sum to its own total to
1e-9; retail balance by product reproduces from the hive partition with pandas.

## J. §8 — the custom metric journey

Journey G, in real Chromium: the builder explains what it will and will not
confer; the dataset list is the governed one rather than every table; the source
data is read independently; the preview produces a figure and the figure on
screen is the one the data supports; the endpoint agrees; the period is named;
the working is shown; the metric saves; it is labelled built-here rather than
governed, and draft; the saved metric computes the same number it previewed;
it is findable by name immediately; it is gone once deleted.

## K. §9 — the Custom Chart Builder, implemented

It did not exist. It does now, end to end.

**The engine.** A chart is the metric's own formula, grouped.
`execution.breakdown` compiles the same measures as `compile_metric` with a
`GROUP BY` on the dimension, and every point comes out of the same `evaluate()`
the single figure uses. That is what makes a bar comparable to the KPI above
it: not a similar calculation, the same one.

**Configurable:** title, metric, dimension, grouping, period, filters, sorting,
direction, aggregation, comparison, chart type — all offered from the governed
catalogue and all checked again server-side.

**What it refuses, and why each refusal is real:**

- a line between unordered categories, which asserts a progression that is not
  there;
- a matrix, which needs two dimensions from a builder that configures one;
- any chart of a metric computed by a governed function — Gini over a segment
  is not Gini reconstructed from a summary row;
- an average of a ratio, which is not a number anybody named;
- a dimension or filter column the catalogue does not hold, including
  `1=1; DROP TABLE users`.

The refusals are shown on screen with their reasons, not hidden: a person who
cannot see why "line" is missing concludes the product is broken.

**A judgement recorded in the code.** `MetricDefinition.visuals` is deliberately
not one of the gates. Forty of the sixty-one governed metrics leave it at the
field's default of `("kpi",)`, which is an un-authored default rather than a
decision that the metric must never be broken out; reading it as a governance
refusal would refuse "utilisation by product" — an ordinary, honest bar chart —
on the strength of a default nobody wrote.

**Journey I**, in real Chromium, ends on the assertion that matters: the four
bars on the lens are reproduced by reading the hive partition with pandas and
grouping by product. No formula, no IR, no compiler, no executor. Agreement
reached by calling the same code would prove nothing.

## L. §10 — final regression on final HEAD

| Gate | Command | Result |
| --- | --- | --- |
| Backend suite | `.venv/bin/python -m pytest tests` | *(recorded in §S)* |
| Planner | `pytest tests/planner` | 270 passed |
| Metrics + runtime | `pytest tests/metrics tests/runtime` | 217 passed |
| Scorecard + metrics | `pytest tests/scorecard tests/metrics` | 449 passed |
| Lint | `ruff check backend scripts tests` | All checks passed |
| Frontend types | `npx tsc --noEmit` | clean |
| Frontend lint | `npm run lint` | clean |
| Frontend build | `npx next build` | succeeded |
| Browser journeys A–J | `scripts/acceptance/lens_journeys.py` | 128 passed, 0 failed |
| Live demo journey | `scripts/acceptance/planner_demo_journey.py` | 18 passed, 0 failed |
| Migrations | `alembic heads` | `0038 (head)` |
| Docker | — | **NOT VERIFIED IN CLAUDE SANDBOX** |

No demo scenario depends on the seed having happened today: that was the whole
of §1 and §2, and the two date-dependent test files were made deterministic
without weakening a single assertion.

## M. What a person can do now that they could not before

- Roll the demonstration forward to today with one command, keeping every
  update, owner, narrative and audit row, and see what it would do first.
- Build a chart of any governed metric across any dimension of its dataset,
  configure it fully, preview it, and put it on a lens as a version that can be
  put back.
- Be told, on screen, why a chart type they cannot pick would be dishonest.
- Open a chart's Info control and read the metric's definition, the dataset,
  the filters, the run id and the exact SQL.
- Read a count metric's info panel and learn what a row is.
- See a default rate that has actually been observed, rather than a zero.

## N. Every change made in this run

Seven commits, `b625eab` through `9d66623`, 18 files, +3,529 / −31.

| Commit | What |
| --- | --- |
| `b625eab` | The demo journey: 18 checkpoints, scoped sweep counting, a tenth checkpoint that has to move a number |
| `b7b81e6` | The chart engine: `breakdown`, `series`, `chart_types_for`, the five refusals, 22 tests |
| `35b71f5` | The chart builder UI, the chart tile, journey I |
| `567f624` | The maturity fix, the scope-empty message, the KS tie fix, 9 tests |
| `79b7cd1` | Journey J, the dataset grain on every metric panel, the abandoned lenses removed |
| `37479ae` | The teardown that had never run |
| `9d66623` | The acceptance matrix |

## O. What was NOT weakened

No existing assertion was removed, loosened or skipped. No test was marked
xfail. No tolerance was widened. The two KS tests use distinct scores and pass
unchanged against the corrected implementation. The 28 lens tests and the 8
demo-portfolio tests are as they were. Where a test of mine was wrong — journey
J's case-sensitive assertion against CSS-uppercased headings, and its demand
that a COUNT metric name a source field it does not read — the test was
corrected, and the report says so rather than quietly adjusting it.

## P. Things fixed that were my own

- Journey J asserted on section headings case-sensitively; the panel uppercases
  them in CSS and Playwright reports text as rendered.
- Journey J required `source_fields` on every tile; a metric that counts rows
  names no field because it reads none. The dataset grain was added to the
  panel and the assertion accepts either — which turned a wrong test into a
  real product improvement.
- The demo journey's checkpoint 8 counted sweep messages estate-wide and read
  97 correct messages about other projects as a failure.
- The first draft of the matrix's tally said 91 PASS; the file had 135 rows. The
  tally is now counted from the file by a command printed beside it.

## Q. Remaining limitations, stated plainly

- **Live AI is not verified here.** No provider is configured. Everything
  proven about AI behaviour in this run is deterministic.
- **External email is not verified here.** No transport is configured. The
  composition is ready; nothing sends it.
- **Docker is not verified here.** It cannot run in this sandbox.
- **A chart configures one dimension.** A matrix comparing two is not offered,
  and says so.
- **A chart over more than 500 groups reads the first 500 and says it did.**
- **PSI is not calculated.** The reference distribution it would compare
  against is not in this deployment, and the lens says so.
- **The CRO portfolio page is not a Lens 2.0 object.** It does not benefit from
  the lens renderer's info controls, period stamping or "not shown here" notes.
- **The lens renderer draws six of the catalogue's twelve declared visuals.**
  The three IFRS 9 stage shares declare `stacked_bar`, which is an honest
  thing to say about them and which no lens renderer draws yet. I first read
  this as a declaration the platform could not honour; it is not — the two
  vocabularies are deliberately different sizes, one for what a metric may say
  about itself and one for what this renderer has. What WAS wrong was the
  refusal message, which offered `stacked_bar` back as an alternative and
  would have sent somebody to try a tile that cannot be drawn. It now names
  only what the lens can draw, and says separately what the metric declares
  beyond it.

## R. What is NOT claimed

No external email was sent. No live model was called. No Docker stack was
started. No CPM figure, scorecard statistic or lens number in this report was
written from memory: each one was read from the running application or
recomputed from the parquet during this run, and where the two disagreed the
disagreement is reported above rather than reconciled by hand.

## S. The full backend regression on final HEAD

*(filled in from the run's own output — see below.)*

## T. Recommendation

*(stated below, once §S is in.)*

# The Playbook — Committee Pack Intelligence System

Final report.

Branch `claude/playbook-committee-intelligence`, built from the protected
release candidate at `d55f625`. Head at the time of writing: `0530942`.

---

## A. What was asked for

A governed, data-driven, collaborative, agentic committee pack intelligence
system for senior credit-risk and finance committees. Not an upload screen.
Not a document repository. Not a PowerPoint editor with a chat box.

The whole cycle: committee definition, pack schedule, data readiness, pack
generation, analysis, commentary, review, approval, presentation, decisions,
actions, project-planner follow-up, and then the next committee pack.

## B. What was built

The Playbook. The existing Playbooks feature was removed entirely — that was
the answer to the one product question asked, "Remove the earlier. Make this
as the playbook." — and this is what carries the name now.

A committee in CreditProbe is a standing body with terms of reference, a
cadence, participants in named roles, a standard agenda, and a template that
says what its pack contains. Each cycle produces a pack: sections owned by
people, figures that are governed metric calculations rather than numbers
typed into a component, commentary written by the people who own the sections,
findings raised by rules against thresholds, decisions framed before the
meeting and recorded after it, and actions that leave with an owner, a date
and a route into the Project Planner.

Seventeen tables in one migration (`0039`), seventeen backend modules, 43 API
paths carrying 50 operations, five pages, and 253 tests of its own.

## C. Retiring the earlier Playbooks feature

The name had an occupant. An earlier feature called Playbooks — a standing
instruction that ran certified analyses on a trigger and tested their results
against thresholds — was removed at the product owner's direction so that
Playbook could mean the committee pack. This section records what went, what
stayed, and how each was decided, because a removal nobody wrote down is a
removal somebody re-litigates.

### What it consisted of

| Dependency | Class | Outcome |
|---|---|---|
| `/playbooks` page | A — legacy only | Removed |
| Playbooks navigation entry | A | Removed |
| `backend/api/routers/playbooks.py` | A | Removed |
| `backend/services/playbooks.py` | A | Removed |
| `Playbook`, `PlaybookRun` models | A | Removed |
| `playbooks`, `playbook_runs` tables | A | Dropped in `0039` |
| Playbooks tests and fixtures | A | Removed; `tests/services/test_lenses.py` records why |
| Playbooks demo rows in `backend/demo/workspace.py` | A | Removed; the file now seeds committee packs |
| Engine registry (30 certified analyses) | B — shared | **Kept** |
| Engine runner (`run_analysis`, `persist_run`) | B | **Kept** |
| Lenses service | B | **Kept** |
| Investigations | B | **Kept** — a `playbook_runs` row pointed at one, and dropping the table took the reference, not the Investigation |
| Brain compatibility module set | B | **Kept**, capability renamed `playbooks` → `playbook` |
| Role description in `users.py` | B | Kept; the prose naming Playbooks was corrected |
| Threshold-against-a-result idea | C — reusable | **Incorporated**, as `backend/playbook/materiality.py` |
| Trigger-and-notify idea | C | **Incorporated**, as `backend/playbook/monitor.py` and the chase list |

The three classes are the ones that matter. Class B is the reason this was not
a simple delete: Playbooks *borrowed* CreditProbe's analytical infrastructure
rather than owning it, and the registry, the runner and the Lenses service all
have other callers. Removing them because one caller went away would have been
the expensive kind of mistake — the kind found weeks later by a different
feature.

Class C is the reason the removal is not a loss. Playbooks' two good ideas —
that a threshold crossed on a governed number is worth raising, and that
somebody should be told — are both in the new system, tied to a committee and
a cycle rather than to a standing instruction.

### The data

`playbooks` and `playbook_runs` were dropped rather than migrated, and the
justification is worth stating rather than assuming.

There is no honest mapping between the two schemas. A standing analytical
instruction and a governance pack are not the same object under two names: a
threshold condition is not a committee section, and a run is not a meeting.
Migrating one into the other would have put invented committee packs, with
invented meeting dates and invented attendees, in front of a client.

The rows themselves were demonstration data. In this deployment the only
writer of `playbooks` rows other than the API was `backend/demo/workspace.py`,
which created them as part of the seeded workspace and listed both tables
among the ones its reset clears — so the rows were already understood as
resettable demonstration state, not as records anybody was keeping. The
migration's `upgrade()` therefore drops both tables outright, and says so in
its docstring.

Two honest caveats. A deployment where somebody had created Playbooks through
the API *would* lose those rows, and the migration does not stop to ask; that
risk was accepted at the product owner's direction, on a feature whose
scheduled triggers were never wired to a scheduler. And the drop is reversible
only in schema: `downgrade()` recreates both tables empty, which is enough to
step a deployment back but does not bring rows back. A deployment that wanted
them would take them from a backup.

### Verification, and what pins it

`tests/playbook/test_legacy_retirement.py` — seven tests, added rather than
assumed:

  * the navigation entry is gone, and Playbook appears exactly once, in Govern
  * `/playbooks` is retired: no page directory, no API path, and no redirect
    — deliberately not a redirect, because sending somebody from a standing
    instruction to a committee pack would tell them the two are the same thing
  * nothing imports what was deleted — an import check for the two removed
    modules and the two removed models, plus a source sweep of 596 files in
    `backend/` and `scripts/`, because a reference inside a function body
    never runs during collection
  * the legacy tables are absent from the live schema and the fifteen new ones
    are present, checked against `pg_tables` rather than against the migration
    file, since a migration that was written is not a migration that ran
  * `0039` can be stepped back
  * the shared infrastructure still works: the registry still resolves its
    certified analyses, the runner is still callable, Lenses still imports
  * the Brain advertises `playbook` and not `playbooks`

The navigation test was confirmed to fail when a `/playbooks` entry is put
back, so it is a guard and not a decoration.

## D. The shape of it

| | |
|---|---|
| Migration | `alembic/versions/0039_playbook_committee_intelligence.py`, 17 tables, head `0039` |
| Backend | `backend/playbook/` — 17 modules; `backend/models/playbook.py`; `backend/api/routers/playbook.py`. 11,723 lines |
| Frontend | 5 pages, 5 components, one presentation module. 3,436 lines |
| API | 43 paths, 50 operations under `/api/v1/playbook` |
| Tests | 253 in `tests/playbook`, 11 files |
| Journeys | 20, in `scripts/playbook_journeys/` |
| Documents | 5, in `docs/` |

The seventeen backend modules, and what each owns:

`access` — the single door. Every read and every write passes through it.
`service` — committees, packs, sections, blocks, the state machine, the event
record. `readiness` — the gate, eight weighted checks, each with named
blocking reasons. `snapshots` — a figure and its working, frozen at a pack
version. `generation` — calculating a pack's figures in one pass over the
lake. `materiality` — rules against thresholds, producing findings.
`findings` — answering, reopening and dismissing them. `compare` — this cycle
against the last, with five kinds of difference kept apart. `narrative` — the
AI drafting path and the evidence it is given. `agent` — the AI as an actor
with a capped grant. `monitor` — the sweep that says who is being waited on.
`actions` — actions and the bridge into the Project Planner. `export` — four
formats. `import_` — inbound documents, checked before they are opened.
`demo` — the demonstration committees and their re-anchoring.

## E. The single door

`access.readable_pack` is the only way a pack row reaches a caller.
`committee_grant_for` decides what a caller may do: membership first, then the
platform ADMIN role, then refusal. There is no third path and no bypass.

That matters because pack ids are global. Journey I creates a real account
through the real admin route, gives it no membership, and asks for a specific
pack by id, its readiness, its history, its sources, its comparison, its
export, and then tries to publish it and to add a section to it. All seven are
404 — not 403, because a caller who may not see a committee should not learn
that a pack on it exists. The body of the refusal carries no pack content.

A member whose access role is VIEWER is a different case, and it is tested as
one: they read the pack (200) and cannot publish it or add a section to it
(403).

## F. What a figure is

Not a number. A figure is a calculation with its working attached: the metric
id, the metric version, the formula hash, the period, the comparison period,
the filters, the dataset, the dataset version, the source fields, the
numerator, the denominator, the rows considered, and a run id.

    retail.default_rate  2025-01  6.88%
      formula hash  5b5645d3f2ef6ca49f709cd9b30cbf4a0f74e0e3968ff5087cd73b19c6516fb6
      dataset       retail_behavioral_scorecard_monthly_validation
      version       1@5ae05e5a34f5b9f74c9a661f47c95f24
      numerator     1307
      denominator   19000
      run           92c92a1c57d743bf

That is the real payload from the seeded retail pack, read over HTTP in
journey C. Every figure on the screen opens to it.

## G. The five ways of having no number

A committee that cannot tell them apart cannot act on any of them.

**OK** — calculated. **NO_DATA** — the metric is defined, the period exists,
and no rows met the definition. **PERIOD_MISSING** — the lake does not hold
that period. **NOT_MATURED** — the outcome window has not closed yet, which is
a fact about the calendar and not a gap. **CALCULATION_FAILED** — something
went wrong and the pack says so. **NOT_AUTHORISED** — the reader may see the
pack and not this figure.

None of them renders as `0.0%`. A missing or immature denominator is never a
client-facing zero. That is asserted on the wire (journey C) and on the screen
(journey R).

## H. Readiness is a gate

Eight weighted checks, each producing named blocking reasons that point at the
entity and the person responsible:

Meeting and period · Data readiness · Sections written · Commentary accepted ·
Findings answered · Decisions framed · Actions updated · Reviews complete.

A check that cannot be assessed says so rather than scoring zero: "This pack
has no AI-drafted commentary" is not the same as failing the commentary check,
and the difference is stored.

Approval is blocked on the gate, not on a person remembering. The seeded
retail pack sits at 81% with one blocking item — a HIGH finding that has not
been answered — and the screen names it.

## I. What the AI may not do

Thirteen acts are refused to an AI channel regardless of the grant it holds:

    approve_pack · approve_section · change_meeting_date · close_action
    decide · delete_pack · delete_section · dismiss_finding
    edit_approved_pack · edit_formula · import_document · publish_pack
    record_review

`access.refuse_ai` is called at each site, and the refusal is not the state
machine's — the security tests put the pack in a state where the transition
would otherwise be legitimate, so that what refuses is the AI check and
nothing else.

An agent's grant is also capped structurally: `_capped(access, channel)`
lowers what an AI channel holds below what the same person holds through the
UI. The cap and the forbidden list are independent, and both apply.

The model is never asked to calculate a metric, to decide whether data exists,
or to invent materiality. It is given calculated figures as evidence and asked
to write about them.

## J. The live AI path — NOT VERIFIED

`get_provider()` in this environment reports `configured = False` and names
itself `'none'`. There is no API key here.

What was verified: with no provider, the drafting path raises `NoProvider`,
the product says so plainly, and no fallback text is written. There is no
template fallback in the code — a draft nobody's model produced would be words
nobody signed.

What was not verified: a live drafting call. That row in the acceptance matrix
is NOT VERIFIED, and it is not rounded up.

Everything else in the Playbook works with no provider configured.

## K. Documents

Four formats, all downloaded and opened again with the library that consumes
them, in journey H:

| Format | Size | What it is |
|---|---|---|
| PDF | 10,528 bytes | The pack as it is circulated and filed |
| Word | 40,514 bytes | The same pack, editable, for a secretariat |
| Slides | 37,064 bytes | The deck a chair presents from |
| Workbook | 11,822 bytes | Every figure with its formula, period, numerator, denominator |

## L. Excel formula injection

Every string in the exported workbook is scanned in journeys N and O. Zero
cells begin `=`, `+`, `-`, `@`, tab or carriage return.

The proof is a round trip, not an assertion about a function. Journey O
uploads a workbook containing `=cmd|'/c calc'!A1`, `@SUM(1+1)*cmd|'/c calc'!A1`,
`+1+1`, `-2+3+cmd|'/c calc'!A0` and a tab-prefixed `=HYPERLINK(...)`, then
downloads the pack and reads every cell back with openpyxl. The payload is
present — 307 strings scanned — and inert.

## M. `<Finance> Review`

A section can legitimately be called that, and a destructive blocklist would
mangle it. The escaping is done once, at the layer that knows which writer
parses markup: the PDF writer reads reportlab's mini-HTML, so `document()`
escapes for it, and `_unescaped` undoes that for Word and PowerPoint, which
write text literally.

That layering was wrong when this phase started. Word and the deck were being
handed the PDF's escaping, so a client opening the Word file would have read
`&lt;Finance&gt; Review`. Fixed, with a test that reads the files back with
python-docx and python-pptx rather than grepping the XML — where the writer's
own escaping makes the two cases indistinguishable.

## N. Inbound files

An uploaded document is checked before anything parses it: size, extension,
magic bytes, and for a zip-based format the contents it *declares*.

Journey M runs the hostile cases against the live route:

| | |
|---|---|
| An executable renamed to `.xlsx` | 422, on magic bytes |
| A file with an extension the product does not accept | 422 |
| An empty file | 422 |
| A zip declaring a 200 MB member | 422, on the declared size |
| A 60 MB body | 413 |
| `../../../etc/passwd.xlsx` | Accepted — the workbook is real — and stored as `etc-passwd.xlsx` |

The upload is read a megabyte at a time and stops one byte past the limit, so
the refusal costs what the limit costs rather than what the attacker sends.

## O. The imported table

An imported table is the one block that names no metric. It is a table lifted
out of somebody's file, which CreditProbe did not calculate and is not
asserting, and it is marked `UNMAPPED_TABLE` so that nothing downstream
mistakes it for a governed figure.

Two defects around that distinction were found this phase and fixed:

The table was **silently dropped from every export**. A person could put it in
the pack, see it on screen, and then not find it in the file the committee
reads. It is now rendered, labelled "from an uploaded document, not a
CreditProbe calculation", and listed on its own IMPORTED sheet in the evidence
workbook.

The table **blocked the readiness gate permanently**. Readiness counted every
TABLE block among the figures the pack still owed, so an uploaded table
produced a blocking reason — "has not been calculated yet, so the pack has a
placeholder where a figure should be" — that would never clear, about a block
doing exactly what it was meant to. `carries_a_figure` now makes the
distinction once, next to the block types it qualifies. A governed KPI with no
snapshot still blocks; a test pins that.

## P. A movement nobody could see

Average debt burden ratio moved from 0.3056% to 0.3134%. At the one decimal
the metric is governed to, both read `0.3%`, and the screen said
"0.3% ▲ from 0.3% on 2024-12".

A committee reads that as an error in the pack, and they are not wrong to. A
metric's `decimals` is a governance statement about how precisely the number
is meaningful; a change that does not survive it cannot honestly be shown as a
direction, and quoting the extra digits to justify the arrow would assert a
precision the metric definition does not claim.

`movement()` now reports `visible`. The screen and the document say "no change
at the precision this metric is reported to". The comparison carries a caveat
naming it. The AI evidence records the direction as "below reported precision"
so no draft writes "rose to 0.3% from 0.3%".

The arithmetic was not touched. Materiality still reads the real values, and a
test pins that a threshold below the reported precision still fires —
materiality is about the book, not about how many decimals a pack prints.

## Q. Comparison against the previous cycle

Five kinds of difference, kept apart, because collapsing them is how a
comparison lies:

**MOVED** — the same metric, the same formula, a different number.
**UNCHANGED** — within the noise floor. **ADDED** — in this pack and not the
last. **REMOVED** — in the last and not this one, with a caveat for the reader
who saw it. **REDEFINED** — the formula hash changed, so any difference is
partly or wholly a change in what is being measured and must not be read as a
movement in the book.

Journey G compares the seeded retail packs: 8 figures, 8 moved,
`2024-12 → 2025-01`, and a rise in the application bad rate reads as `better:
false` because the metric says lower is better.

## R. Decisions and actions

Journey K raises a decision — "Tighten the Jeddah SME origination cut-off" —
with the question, the recommendation, two alternatives and the impact. It
sits DRAFT before the meeting. The chair records the outcome: APPROVED, with
the decision text and the conditions, and `decided_at` and `decided_by`
stored.

Journey L raises the action that follows, with an owner and a due date.
Closing it with empty evidence is refused (422). Closing it with evidence
succeeds and the evidence is kept. Then it is sent to the Project Planner —
through the Planner's own `create_task`, so the Planner's access rules, its
code validation and its own event record all apply. Playbook does not write
`planner_tasks` and never will: two writers on one table is two sets of rules,
and the second one is always the one that is wrong.

The task was created (id 30048, project 164) and read back from the Planner
side. Sending the same action twice is refused.

## S. The demonstration

Three committees on three cadences, seeded by
`scripts/seed_playbook_committees.py`:

| Committee | Cadence | Previous pack | Current pack |
|---|---|---|---|
| Retail Credit Risk | Monthly | PUBLISHED | REVIEW |
| Corporate Credit | Quarterly | PUBLISHED | DRAFT |
| IFRS 9 Impairment | Quarterly | PUBLISHED | PUBLISHED |

Every figure in them is calculated from the real lake. The periods are read
from the data rather than from the calendar — an earlier version took the
period from `date.today()`, which in this environment is 2026-09 against a
lake that ends 2025-07, and produced eight figures all reading
PERIOD_MISSING. `_periods_for` now intersects the periods each of a
committee's own metrics can actually be read in, respecting each metric's
maturity.

Dates are relative. `--refresh-dates` moves `meeting_at` and `data_freeze_at`
by `today - anchor` and nothing else, so a pack that was in review stays in
review. `--dry-run` writes nothing. A date a person changed is held back —
found by looking for a `PlaybookEvent` on that pack touching that field from a
source that is not SYSTEM — unless `--force` is passed. Verified end to end:
12 dates moved by 6 days, a date Sarah had set was held while the others
moved, and `--force` overrode it.

Reset is guarded: `_may_reset()` requires Synthetic Data Mode or an
environment in dev/development/test/demo/local. Nothing rendered says "demo"
or "demonstration data" — the product vocabulary is "synthetic data", and
`backend/release/product_copy.py` enforces it.

**One thing to know about the demonstration.**
`tests/playbook/test_demo_seed.py` rebuilds the three committees with reset
semantics and removes them again when it finishes. That is documented in its
own docstring and it is the right behaviour for a suite that shares a database
with a demonstration — but it means the seed must be run again after the test
suite. The runbook and the journeys README both say so.

## T. The twenty journeys

`scripts/playbook_journeys/` holds three harnesses that drive the running
stack. Nothing in them uses a fixture, a mock or the ORM: every step is an
HTTP request over a socket to a real uvicorn process carrying a real session
cookie from the real login route, or a real Chromium driving the built Next.js
application.

They are separate from `tests/playbook` on purpose. The pytest suite proves
the rules. These prove the product runs.

A–J the pack lifecycle over HTTP · K–O decisions, planner follow-up, hostile
uploads and formula injection · P–T the product in Chromium.

All twenty pass on this commit.

They found three of the five defects fixed this phase, which is the argument
for having them: a test that calls a service function proves the function
works, and a journey that opens the file the committee reads proves the
product does.

## U. What the browser actually shows

Journey P–T runs Chromium against `next build` + `next start` on port 3000,
with the backend on 8000.

Signed out, the Playbook is not readable and a sign-in form is what is
offered. Signed in as the committee chair, all three committees are on the
Playbook. The committee page names its cadence and lists its packs. A pack
opens to its sections; eight governed percentages render; readiness shows as a
percentage with its checks broken out and the blocking reasons named. A
figure's working opens to the metric, the period and the formula hash. There
is no page error, no console error, and nothing on the screen that is
unfinished scaffolding.

One environment note, because it cost time and would cost a reviewer the same:
the backend's CORS list names `localhost:3000` and `127.0.0.1:3000`. On any
other port the browser cannot reach the API at all, and the application
renders its shell with no data and no sign-in screen — because the auth gate
reads `login_required` from the backend, and a backend it cannot reach cannot
tell it. That is the gate being careful rather than a defect, but it means the
frontend must run on 3000.

## V. What was fixed this phase

Five things, all found by looking at the product rather than at the code.

1. An imported table was silently dropped from every export.
2. A blank cell in a table took the PowerPoint export down with a 500 —
   setting a cell's text to `""` leaves the paragraph with no runs, and
   reaching for `runs[0]` raised.
3. Word and PowerPoint were handed the PDF's HTML escaping.
4. A movement too small to see at the metric's own precision was drawn as an
   arrow between two identical numbers.
5. An uploaded table blocked the readiness gate permanently, on a reason that
   was not true.

Each carries a regression test that fails without its fix. No test was
weakened, no tolerance enlarged, and no failing test skipped to get here.

## W. What was not built

Nothing in the mandate was left as a TODO, a placeholder, a disabled button, a
fake notification, a mocked AI response, a static screenshot, a hard-coded
metric value, a frontend-only permission, a non-functional export, or an API
with no product UI. Each of those was checked for specifically.

The one functional gap is the one named in section J: the live AI drafting
call, which cannot be executed in an environment with no provider configured.

## X. Infrastructure reused, not rebuilt

No second user table, notification centre, audit system, metric-formula
engine, chart engine, project-task system or parallel AI tool registry was
created. The Playbook uses `User`, the platform's export record, the metric
layer, the reporting writers, the Planner's own service, and the existing LLM
provider abstraction. No committee metric is hard-coded in a frontend
component: every figure comes from `config.metric_id` resolved through the
metric layer.

## Y. Quality gates

| Gate | Result |
|---|---|
| `ruff check backend/ tests/ scripts/` | Clean |
| `npx tsc --noEmit` | Clean |
| `npx eslint` | Clean |
| `npm test` | 520 passed, 46 suites |
| `pytest tests/playbook` | 253 passed |
| `pytest tests/docs/test_feature_matrix.py` | 8 passed |
| Journeys A–T | 20 passed |
| Alembic | Head `0039`, single linear head |

## Z. The full regression

Baseline, recorded in `docs/PLAYBOOK_BASELINE.md` before any Playbook code
touched anything that already existed: **12,075 passed, 35 skipped, 0 failed**
at `d55f625`, alembic head `0038`.

On this commit, `0530942`, run as a real pytest process over the whole suite:
**12,319 passed, 35 skipped, 0 failed, 0 errors, exit code 0**, in 21m 25s,
alembic head `0039` (single head).

    .venv/bin/python -m pytest tests/
    12319 passed, 35 skipped, 25 warnings in 1285.90s (0:21:25)

Against the baseline that is **+244 passed, skips unchanged, still zero
failures**. The net is smaller than the 253 Playbook tests added because the
earlier Playbooks feature and its tests were removed in the same branch.

The two `tests/docs/test_feature_matrix.py` failures that appeared mid-phase
were the docs gate correctly reporting that the five new Playbook pages
carried no curated expected behaviour. They were curated and the gate now
passes (8 passed).

## AA. Constraints observed

The protected source branch `claude/vigilant-darwin-eohyi1` was not modified,
rebased, force-pushed or rewritten. Nothing was merged into `main`. No pull
request was opened. Nothing was force-pushed and no history was rewritten. All
work is on `claude/playbook-committee-intelligence`, pushed in coherent
increments.

## AB. Documents

| | |
|---|---|
| `docs/PLAYBOOK_COMMITTEE_INTELLIGENCE_REPORT.md` | This document |
| `docs/PLAYBOOK_ACCEPTANCE_MATRIX.md` | Every gate with what was run against it |
| `docs/PLAYBOOK_ARCHITECTURE.md` | The modules, the data model, the decisions and why |
| `docs/PLAYBOOK_USER_GUIDE.md` | The product as a committee member uses it |
| `docs/PLAYBOOK_DEMO_RUNBOOK.md` | Running the demonstration |
| `scripts/playbook_journeys/README.md` | The twenty journeys and how to run them |

## AC. What a reviewer should look at first

The single door (`backend/playbook/access.py`) and journey I, together. If the
access model is wrong, nothing else matters.

Then `backend/playbook/snapshots.py` and journey C: what a figure is, and
whether the working behind it is real.

Then the readiness gate and the five ways of having no number, because that is
where a committee pack either tells the truth about what it does not know or
quietly does not.

## AD. Known limitations

The live AI drafting path is unverified in this environment (section J).

The Docker path was not run this phase — the stack was verified as separate
processes. The compose file is unchanged by this work.

The frontend must run on port 3000 for the browser to reach the API
(section U).

The test suite removes the seeded demonstration committees (section S).

## AE. Recommendation

**READY FOR USER ACCEPTANCE TESTING.**

The full lifecycle works end to end against real data, through real HTTP, in a
real browser: a committee is defined, a pack is scheduled and generated from
governed metric calculations, readiness gates it, findings are raised and
answered, commentary is written and reviewed, the pack is approved and
published, decisions are recorded, actions leave with owners and reach the
Project Planner, and the pack downloads as four working documents. Access is
enforced at one door and proved against a real outsider account. The security
suite covers IDOR, cross-entity references, AI privilege escalation, prompt
injection, malicious files, zip bombs, oversized uploads, Excel formula
injection and output escaping, each exercised through the live route rather
than asserted about a function.

The full platform regression on this commit is recorded in section Z.

Two items are NOT VERIFIED and neither is material to acceptance testing of
this system: the live AI drafting call needs a provider key, and the Docker
path needs a compose run. Both are stated as NOT VERIFIED rather than assumed,
and both should be executed in the environment that has what they need before
this reaches production. Neither blocks a committee from using the Playbook,
because the Playbook does not depend on either: commentary can be written by
the people who own the sections, which is what a governed pack wants anyway.

The five defects found this phase were all found by driving the product rather
than the code, which is a reason to keep the journeys and run them on every
change — and a reason to read the two NOT VERIFIED rows as work still to do
rather than as boxes to tick.

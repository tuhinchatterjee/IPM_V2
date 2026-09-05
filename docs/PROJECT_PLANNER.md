# The Project Planner

A delivery plan lives here: workstreams, tasks, milestones, dependencies and a
RAID log, with an append-only record of everything anybody has said about
them. It answers the questions a senior risk person asks before their first
meeting — what is late, what is blocked, who owes an update, what changed
since Friday, and what needs a decision.

It is **not** `/projects`. That is the analytical workspace a piece of credit
work lives in — investigations, saved analyses, documents. This is the project
a team *delivers*, and the tables are prefixed `planner_` so the distinction
survives a database migration as well as a conversation.

---

## The one idea

**Deterministic control, then language.** Every judgement — whether a task is
late, whether a project is red, who should be chased, what is on the critical
path — is computed by `backend/planner/control.py` from the database and the
date. A model is never asked whether something is late, and there is no
registered tool through which one could mark a task complete.

That single decision is why the numbers on two screens agree, why a status
report can go to a committee, and why "why is this red?" always has an answer
you can look up.

---

## Where the code is

| Module | What it owns |
|---|---|
| `backend/models/planner.py` | Ten tables. No second user, team, notification or audit table. |
| `backend/planner/control.py` | The deterministic engine. Pure functions of a plan and a date. |
| `backend/planner/access.py` | The single door. Who may read and change what. |
| `backend/planner/service.py` | Every mutation: validate, apply, record, audit. |
| `backend/planner/query.py` | Reads: portfolio, my work, project detail, activity, attention. |
| `backend/planner/workbook.py` | The plan as a spreadsheet, in both directions. |
| `backend/planner/monitor.py` | The overnight sweep: reminders and health. |
| `backend/planner/agent.py` | Briefs, chases, and the assistant's tool handlers. |
| `backend/api/routers/planner.py` | Twenty-eight routes under `/api/v1/planner`. |
| `frontend/src/app/delivery/` | The portfolio, My work, and one project. |
| `alembic/versions/0034_project_planner.py` | The migration. |

---

## Permissions

CreditProbe is single-tenant: there is no organisation table. The access
boundary is therefore **the project's participant list**, and it is enforced in
`access.py` on every read and every write.

| Level | May |
|---|---|
| VIEWER | Read everything on the project. Change nothing, including updates. |
| CONTRIBUTOR | Update tasks they own, review or contribute to. Raise RAID. |
| EDITOR | Change the plan: tasks, dates, owners, milestones, dependencies, import. |
| OWNER | All of the above, plus participants and health overrides. |

Two rules worth knowing:

* **A project you are not on returns 404, not 403.** 403 confirms it exists,
  which turns `/projects/{id}` into a way to count the estate by walking the
  integers.
* **A contributor may report progress but not move a due date.** If the person
  doing the work can move the date they are measured against, nothing is ever
  late and the portfolio is decoration.

`tests/planner/test_permissions_http.py` asserts every one of these as a status
code from the running application, called as four different people.

---

## Health

Deterministic, explainable, and configurable. `control.Policy` holds every
threshold in one place — `due_soon_days`, `imminent_days`, `stale_after_days`,
`amber_overdue_count`, `dependency_slip_days`, `milestone_horizon_days`,
`chase_no_progress_days`, `reminder_days` — so the product cannot call a task
"due soon" at seven days on one screen and three on another.

* **RED** — a critical task is overdue, a critical milestone has been missed,
  or a blocker threatens a near-term commitment.
* **AMBER** — enough is late, blocked or silent to need attention.
* **GREEN** — nothing on the record is wrong.
* **UNKNOWN** — there is not enough plan to judge. A project with no tasks or
  no dates is not green; reporting it green says "nothing is wrong" when the
  truth is "nobody has written down what is meant to happen".

Every verdict carries the sentence behind it and the findings that produced it.
A manual override stores who set it, when, and why, and **keeps the calculated
value alongside** — a manager reporting a project greener than its own numbers
is a governance fact, and the project page shows both.

---

## The workbook

One column contract (`workbook.SHEETS`) drives the template, the export and the
parser, so `export → edit → import` is a round trip rather than two formats
that resemble each other.

Eight sheets plus an IMPORT GUIDE: PROJECT, PARTICIPANTS, WORKSTREAMS, TASKS,
MILESTONES, DEPENDENCIES, RAID, UPDATES.

**Omission is not deletion.** A workbook with three tasks uploaded against a
project with forty adds or updates three. It does not delete thirty-seven.
Somebody exporting one workstream to work on over a weekend must not destroy
the plan by uploading it back — and the guide sheet says so inside the file.

**Nothing is applied from a file nobody has seen.** Upload parses, validates
and stages; commit applies the staged copy. Row-level errors name the sheet,
the row number and the column, because the person fixing them is going back to
Excel.

**Columns are matched by header, never by position.** A hidden column shifts
every value one to the left, and that corruption is invisible until a quarter
later.

**Cells are data, never formulas.** openpyxl writes a leading `=` as a live
formula, so an exported task titled `=cmd|'/c calc'!A1` would be a payload in
the Excel of whoever opens it. Everything written is escaped, and the escape
survives the trip back.

Every import writes through `service.py` with `SOURCE=EXCEL_IMPORT`, so it is
subject to the same permission checks as the UI and lands in the same history.
The UPDATES sheet's Author column is filled in on export and **ignored** on
import: honouring it would let anybody with a text editor write project history
in a colleague's name.

---

## The overnight sweep

`monitor.sweep()` runs as a job kind on the platform's existing durable queue
(`planner_sweep`) — the planner does not have its own scheduler.

Every message carries a fingerprint of what it is about, and the fingerprint is
a unique constraint, so:

* a task due in three days is reminded about **once**, however often the sweep
  runs;
* **moving the due date re-arms it** — a commitment that moves is a different
  commitment, and silence after a date change would be the worse failure;
* an **overdue** task carries the day in its fingerprint, because going on
  being late is new information each morning.

Reminders are ordinary `Notification` rows, so they appear in the notification
centre the rest of the product already uses.

Health is recalculated in the same pass, and a colour *change* is written into
the project's history with `SOURCE=SYSTEM` and no author — it is a calculation,
not something a person did. It is not re-announced while it holds.

Run it by hand with `POST /api/v1/planner/sweep?dry_run=true` (administrators),
which shows exactly what would be sent without sending it.

---

## The assistant

Twelve tools in the existing registry (`backend/agentic/tools.py`), eleven of
which read. Every read tool is marked `reads_data`, which is what carries the
requesting person's principal into the handler: an agent answering "what's
overdue?" sees exactly the projects that person could see by clicking.

There is **no registered tool** that completes a task, changes an owner, moves
a due date, cancels work, closes a risk or sets a project's health. Those six
names are in `NO_TOOL_EXISTS` alongside the platform's other prohibited
actions. The prohibition is the absence of the capability, not a permission
check that has to be written correctly. The one writer drafts the text of a
status request and sends nothing.

Briefs are **composed, not generated**. Every line is labelled:

* **FACT** — read from the database, or computed from it.
* **INFERENCE** — a reading of those facts by a stated rule.
* **RECOMMENDATION** — something a person might do about it.
* **NOT RECORDED** — the honest answer when the record does not say.

Where a task is blocked with no reason recorded, the brief says so and puts the
question in `open_questions` rather than offering a plausible sentence about a
vendor.

---

## Running it

```bash
# The plan and its cast (idempotent; --force rebuilds)
python scripts/seed_planner.py

# The six journeys through a real browser
python scripts/acceptance/planner_journeys.py

# The test suite
.venv/bin/python -m pytest tests/planner -q -p no:randomly
```

The seeded plan is `IFRS9-REDEV` — the IFRS 9 model redevelopment, with six
workstreams, twenty-four tasks, five milestones, eighteen dependencies and a
fortnight of updates. It is deliberately not tidy: one task overdue and on the
critical path, one blocked with a real reason, one decision outstanding, one
high risk with a name on it.

Sign in as `priya.raman` (the demonstration password in
`backend/services/demo_users.py`) to see My Work as the person who manages it.
An administrator sees everything and therefore demonstrates nothing about that
screen.

---

## Known limitations

Stated rather than hidden.

* **The critical path is a marker, not a computed longest path.** Tasks carry a
  `critical` flag and dependencies are real and cycle-checked, but the engine
  does not compute float or a CPM schedule. `control.py` refuses to claim
  otherwise: it reports what is blocking what and what is late, and never
  presents a "critical path" it has not calculated.
* **No Gantt chart.** The Plan tab is a list with dependencies below it. A
  timeline renderer is a substantial piece of work and its absence is visible
  rather than faked.
* **RAID and milestones are created through the API and the workbook, not yet
  through a form on the project page.** Both are read-only on screen.
* **The sweep must be scheduled.** Registering the job kind is done; deciding
  when it fires is a deployment choice, and nothing in the product fires it
  automatically today beyond the manual route.
* **Reminders are in-app only**, following the platform's existing choice.
  Email is a deployment concern with its own approvals.

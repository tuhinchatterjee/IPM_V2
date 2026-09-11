# Project Planner — UAT remediation

What manual testing of the Docker application found, what was changed, and
what was run against the change.

Branch: `claude/project-planner-copilot`.

---

## 1. The finding, reproduced

The report was that the Project Planner was confusing and that several flows
were incomplete. It was reproduced in the running application before anything
was written, and it was not a matter of taste.

`/delivery` opened with a chat box reading:

> Tell me what you want to do. I can start a plan, add milestones and tasks…

and the first of its two primary actions read:

> **Start a new project** — Build the plan in conversation, see the whole
> thing, then publish it.

`/delivery/new` then put a conversation on the left and, on the right, every
panel of the plan at once: overview, governance, the agentic policy,
milestones with their tasks, dependencies, completeness and publish — one
page, all of it, no order.

So the product had two ways to create one thing, and the one it led with was
a text field that might or might not understand the sentence typed into it.
Nothing on the screen told a person which fields were required, in what
order, or what would happen when they finished. That is the finding.

Three further gaps followed from the same shape:

* a dependency stated that two dates overlapped and offered nothing to do
  about it;
* the project detail page carried a **Copilot** tab that competed with every
  tab beside it;
* **Needs attention** named a project and left the reader to work out what
  about it needed them.

## 2. What the product is now

**Form-first project creation and agentic AI project monitoring.** The AI
watches dates, chases people and reports; it does not build projects.

### The Project Planner (`/delivery`)

    Create new project · Import project · View my tasks

    Needs attention
    Current projects
    Draft projects
    Closed and completed projects

Project rows carry the full set: name, code, sponsor, project manager,
health, status, progress, start date, target completion, next milestone,
overdue tasks, blocked tasks, last updated.

Drafts are listed apart from projects and never mixed into them, with
**Continue editing** and **Discard**. A draft is not a project: nothing is
scheduled off it and nobody is chased about it, so a list that showed both
would be a list in which "we have fourteen projects" is false.

There is no chat control anywhere on the Planner.

### Creating a project (`/delivery/new`)

Eight steps, with **Back**, **Next** and **Save draft** throughout.

| Step | Asks for |
|---|---|
| 1. Overview | Name, code, description, objective |
| 2. People & governance | Sponsor, project manager, owner, escalation contact, start, target completion, priority, reporting cadence |
| 3. Agentic AI policy | Light, Standard, Critical or Custom, each described in words |
| 4. Major milestones | Name, owner, start, target date, critical date, escalation contact; move up and down |
| 5. Tasks | Title, description, owner, start, due date, escalation contact, per milestone |
| 6. Dependencies | What has to finish before what, with the impact stated first |
| 7. Preview | The whole plan, the timeline, the critical path, and what is still missing |
| 8. Publish | One deliberate act |

**Next validates.** Pressing it saves the step and then reads the server's
own completeness notes for that step's scope. A missing sponsor stops you on
step two, not on step eight. The project code is checked for a duplicate
while somebody is still on step one.

**Escalation inheritance is stated wherever it applies** — "Escalation: Priya
Raman — inherited from milestone Data Foundation" — on the milestone list,
the task list and the preview.

**A dependency states its impact before it exists**, in items and days, and
offers three answers:

    [Adjust dates]  [Keep dates and flag conflict]  [Cancel]

Adjust moves the successor and everything behind it by exactly the number of
days named. Keep moves nothing and writes the conflict onto the link, where
it survives into the published project's dependency notes and comes back as a
warning on the preview. Nothing moves a date that was not asked for. A link
that would close a loop, point at itself, or repeat one that exists is
refused and changes nothing.

**The preview shows the whole plan**, including a timeline and critical path
computed by running the same CPM engine over the draft that runs over the
project afterwards, and splits what is left into *Required before publish*
and *Recommended improvements*.

**Publish is atomic.** Everything is created inside one transaction. A
publication that fails on its last row leaves no project — proved by breaking
`service.create_dependency` and then looking for the code in the database.

### One project (`/delivery/<id>`)

Overview · Plan · Timeline · Milestones · RAID · People · Updates · Agent
activity.

Everything is populated from what was entered at creation. There is no second
copy and nothing to re-enter: publishing wrote the plan into ordinary planner
rows and these tabs read those rows.

The **Copilot tab is gone**. What was worth keeping from it — a grounded read
of where the project stands, every statement computed from the plan and
carrying the rows it came from — is a panel on Overview now, read rather than
talked to. It cannot be asked a question, so it can never answer "I did not
follow that".

**Agent activity** reads as project management: "Reminded Priya Raman that
S-702 is due on Friday", "Escalated to the project manager because the data
extraction has been overdue for four days". Not `due_3`, and not a
fingerprint. Every line is a record of something that was sent.

### Needs attention

One row per issue rather than one row per project, each carrying the project,
the task or milestone, severity, owner, due date, the reason, how far the
agent has already chased it, and what would resolve it. Deterministic
throughout: these are the monitoring engine's own findings.

### The messages

Escalation is tied to the CreditProbe message centre. Every message carries,
in a fixed order:

    Project: LGD Model Redevelopment (LGDMR-2026)
    Item: M01-T02
    Owner: Priya Raman
    Due: 2026-03-12
    Escalation: the project manager
    Open: /delivery/41

Messages are deduplicated by fingerprint: running the agent twice sends once.
The ladder is task contact → milestone contact → project contact → manager →
sponsor, and it is walked one rung at a time — nobody is notified because
everybody was.

## 3. The UX review (§26), against the running application

Done by driving the real Docker stack, not by reading the code.

**What improved, and why it reads better.** The first thing on the Planner is
now the list of things that need somebody, with a next action on each; before
it was a text box. The creation flow tells you where you are ("Step 3 of 8")
and what this step is for, and it will not let you walk past a missing
sponsor. The dependency dialog is the clearest single change: it now says
what accepting a link would cost, in days and items, before the link exists.

**What was found while reviewing and then fixed.** The governance
person-pickers could not reach most of the directory: the endpoint capped at
fifty rows however many were asked for, and on this installation the person
signing in was not in the first five hundred names alphabetically. Raising
the number would have moved the wall rather than removed it, so the pickers
search, hold the people the plan already names, and never try to be a staff
directory. The form also lost its place after every saved field, because the
page blanked its data while re-reading and remounted the wizard underneath;
that was invisible on steps one to six and stopped the form dead between
seven and eight.

**What is still true and worth saying.** The project detail page is eight
tabs. That is fewer than it was and each one now answers a question somebody
asks, but it is still the densest screen in the module. A person opening a
project for the first time reads Overview and stops, which is the intended
behaviour and is why the brief moved there.

## 4. What was run

Against Docker images rebuilt from the final executable HEAD, all four
containers healthy.

| What | Command | Result |
|---|---|---|
| Planner and agentic unit/HTTP suites | `pytest tests/planner tests/agentic` | 797 passed |
| The form-first creation journey, in Chromium | `scripts/acceptance/uat_creation_journey.py` | 77 passed, 0 failed |
| The button audit | `scripts/acceptance/planner_button_audit.py` | 79 live, 0 dead |
| The planner journeys A–F | `scripts/acceptance/planner_journeys.py` | 43 passed, 0 failed |
| The agentic demonstration | `scripts/acceptance/agentic_demo_scenario.py` | 19 passed, 0 failed |
| The Copilot boundary over HTTP | `scripts/acceptance/copilot_adversarial.py` | 14 passed, 0 failed |
| Full regression | `pytest tests` | 13,033 passed, 2 failed, 38 skipped — both failures traced outside this work; see the final report |

The demonstration scenario asserts that nobody is told twice about one thing,
which is a claim about a *fresh* demonstration. Run it after
`scripts/seed_retail_portfolio.py --reset`; against a portfolio that has been
running for a week it will correctly count the reminders of previous days and
report them.

## 5. The gates

See `PROJECT_PLANNER_COPILOT_ACCEPTANCE_MATRIX.md`, section U, for
PPC-UAT-001 to PPC-UAT-020 with the evidence for each.

---

# Second round

The form was still not acceptable. What was reported, in the words it was
reported in: after entering the sponsor, the manager, the owner, the
escalation contact, the start date and the target completion date, the panel
beside the form still said the project had no sponsor, no manager, nobody to
escalate to, no start date and no target completion date. There were several
separate Save buttons. The box on the left was not useful.

## 6. The defect, reproduced before anything was written

It was not the completeness engine. The engine was right about what it was
given; it was given the wrong plan.

`get_db` committed in a `yield` dependency's teardown. That teardown does not
run where it reads as though it runs — FastAPI closes the request's exit
stack in `AsyncExitStackMiddleware`, which wraps the call that *sends* the
response:

    async with AsyncExitStack() as stack:
        scope[self.context_name] = stack
        await self.app(scope, receive, send)   # the response goes out here

So the commit landed **after** the browser had been told the save succeeded.
The creation form saves a step and immediately re-reads the draft; served its
own pre-save plan, every panel computed from that read described a project
without a sponsor — which is exactly what was on the screen.

Over real HTTP, against the running application, the old build lost two reads
in twenty:

    read-after-write misses: 0 of 20
       0 STALE wrote 'Run 0' read ''
      11 STALE wrote 'Run 11' read 'Run 10'
    stale reads after apply: 2 of 20

and could return `No draft <key>.` for a draft it had created a moment
earlier. It never showed up in the test suite because `TestClient` runs one
request at a time and the teardown always finished first.

**The fix.** The commit happens in a route class, around the endpoint, before
the response is handed back to be sent. `get_db` no longer commits at all, so
a route that escapes the class loses its write loudly in the tests rather
than racing quietly in production. Two tests pin the invariant rather than the
mechanism — by the time the dependency teardown runs, the write must already
be visible to a connection that knows nothing about the request — and both
fail against the old behaviour. After the fix: 200 write-then-read pairs over
real HTTP, zero stale.

## 7. One save

There were five things on that page that claimed to save something: Save
draft, Save milestone, Save task, and the implicit save behind Next on two
steps. "Did that save?" was a fair question.

Every field now saves itself about a second after the last keystroke, and one
line in the action bar says **Saved**, **Saving…** or **Save failed**. There
is no section-level Save button anywhere. The remaining **Save draft** is a
way to leave, not a second way to save; Back, Next and Publish flush anything
still inside the debounce window before they act.

The value of a control is the server's value overlaid with what is being
typed into it, and the overlay is dropped the moment the server confirms it.
That is what stops the form and the panels beside it describing two different
plans: a whole-section local copy cannot survive the server deriving a field
the copy does not know about, which is how a project code generated from a
name goes missing from the box that shows it.

## 8. Where you are, and what to do next

**A progress bar over the eight sections.** Each has a state — Not started,
In progress, Needs attention, Complete — a count of what it still wants, and,
when it is finished, the line it came to:

    1 Overview                 LGD Model Redevelopment (LGDMR-2026)
    2 People and governance    Sponsor Priya Raman · Manager Omar Haddad ·
                               2 Feb 2026 → 30 Sep 2026
    3 Agentic AI policy        Critical
    4 Major milestones         2 milestones
    5 Tasks                    7 tasks
    6 Dependencies             1 dependency
    7 Review                   Ready to publish
    8 Publish                  Not started

    5 of 8 sections complete

All of it is derived from the draft. There is no stored progress and no
counter to increment: clear the sponsor and governance stops being complete
in the same breath. "Complete" means the section has what a project needs
from it, not that somebody pressed Next. It is the stepper, the progress bar
and the collapsed summaries in one control — a finished section shows what it
holds rather than its fields, and the step being worked on is the only one
open.

**The box on the left is a Project Setup Assistant.** It states what is
settled, what is missing, which dates contradict each other, the single next
recommended step, and the quick actions that belong to the step you are on —
Assign sponsor, Add milestone, Show 3 unlinked tasks, Check readiness. Every
sentence is arithmetic over the plan. There is nothing to type into it, so it
can never answer a question badly.

**Every note is a button.** A completeness note carries the field it is about
— `governance.sponsor_id`, `milestone.M01.owner_id` — so "The project has no
sponsor." goes to the sponsor: the right step, the right control, focused.
A note that cannot say where the thing it names lives leaves the reader to
search eight steps.

**Publish says why it is unavailable**, with the number:

    Publish unavailable — 3 required items remain.

## 9. Custom is a policy now

Choosing **Custom** used to select a label and leave the thresholds on
Standard — the worst of the four answers available, because the screen said
the policy was yours and the agent behaved as though it was not. It now opens
all fifteen thresholds the monitoring engine reads, rendered from the
server's own list with the server's own bounds, with the policy read back
underneath in the words it will behave in. The tests follow it through: a
threshold outside its bounds is refused with a sentence, a combination that
cannot mean what it says is refused, the document survives a publish onto the
project row, and the same project one day overdue escalates under a custom
`escalate_after_days: 1` where Standard waits.

## 10. Four more defects, found by the journey that was written to prove it

The state journey asserts, after every meaningful field, that the control,
the persisted draft and the completeness engine agree. Writing it found four
more of the same family:

* **A project code could not be deleted.** `if data.get("code")` cannot tell
  "no opinion" from "I cleared this", so an emptied code fell through to the
  branch that keeps what is there. The box went blank, the draft kept the old
  value, and a reload put it back without saying so.
* **Setting any field moved the step you were on.** Every command returned
  the step it thought came next and `apply` wrote that down, so choosing an
  agentic policy recorded you on the milestones and reopening the plan opened
  it past your place. Only `set_step` means "I have moved" now.
* **Reloading the page lost the way back to the draft.** `/delivery/new` read
  its key from the URL and nothing ever put it there, so a refresh offered to
  start a plan the person was halfway through. The key goes into the URL the
  moment the draft exists.
* **A payload field nobody read was silently dropped.** A mistyped key — and
  `escalation_contact_id` for `escalation_id` is one keystroke of plausible —
  saved nothing and said nothing. A draft command now refuses a field it does
  not have.

And one that is not a correctness fault but would have become one: the draft
list was unbounded. An administrator on an installation that has been running
for a year was every draft anybody ever started, in one response, in one
list. It is bounded now, newest first, which is the ordering that makes a
limit safe.

## 11. What was run, second round

| What | Command | Result |
|---|---|---|
| The state-synchronisation journey | `scripts/acceptance/creation_state_journey.py` | 78 passed, 0 failed |
| The form-first creation journey | `scripts/acceptance/uat_creation_journey.py` | 77 passed, 0 failed |
| The button audit, now including the creation form | `scripts/acceptance/planner_button_audit.py` | 0 dead |
| Planner and agentic suites | `pytest tests/planner tests/agentic` | 840 passed |
| Full regression | `pytest tests` | 13,077 passed, 1 failed, 38 skipped — the one failure is the messaging directory, outside this module; see the final report |

The gates are in `PROJECT_PLANNER_COPILOT_ACCEPTANCE_MATRIX.md`, section V.

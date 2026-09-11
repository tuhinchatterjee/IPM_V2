# Project Planner — User Guide

Setting a programme up, and letting the agent run it.

The Planner does two things. You describe the project once, in a form. After
that the Agentic AI watches the dates and chases the people, and tells you
when something needs you.

---

## The Project Planner

**Delivery → Project Planner.** In the order the page reads:

**Create new project · Import project · View my tasks.**

**Needs attention.** The things that need somebody today, one row per issue —
not one row per project. Each row says which project, which task or
milestone, how serious it is, whose it is, when it was due, why it is here,
how far the agent has already chased it, and what would resolve it.

**Current projects.** Everything open, with the columns you would read before
deciding to open one: name, code, sponsor, project manager, health, status,
progress, start date, target completion, next milestone, overdue tasks,
blocked tasks, and when it was last updated.

**Draft projects.** Projects you started and have not published. A draft is
not a project — nothing is scheduled off it and nobody is chased about it —
so it is listed here rather than mixed in above. Continue editing or discard.

**Closed and completed projects.**

---

## Creating a project

**Create new project**, then **Start the setup**. Eight steps, with **Back**,
**Save draft** and **Next** on every one of them. Nothing exists until the
last step.

### Saving

You do not. Every field saves itself about a second after you stop typing,
and one line beside the buttons says **Saved**, **Saving…** or **Save
failed**. There is no Save button on any section, and **Save draft** is a way
to leave rather than a second way to save — it puts you back on the Planner
with the plan under **Draft projects**.

Closing the tab loses nothing. The draft is in the address bar, so reopening
the page comes back to the step you were on.

### Knowing where you are

Across the top, the eight sections, each with its state — **Not started**,
**In progress**, **Needs attention**, **Complete** — and, once it is
finished, what it holds:

    1 Overview                 LGD Model Redevelopment (LGDMR-2026)
    2 People and governance    Sponsor Priya Raman · Manager Omar Haddad ·
                               2 Feb 2026 → 30 Sep 2026
    3 Agentic AI policy        Critical
    ...
    5 of 8 sections complete

Press any of them to go there. Complete means the section has what a project
needs from it — not that you pressed Next — so clearing a sponsor moves
governance back to Needs attention while you watch.

### The Project Setup Assistant

Down the right: what is settled, what is missing, which dates contradict each
other, what to do next, and the actions that belong to the step you are on —
**Assign sponsor**, **Add milestone**, **Show 3 unlinked tasks**, **Check
readiness**.

Everything it says is computed from your plan. It has no message box: it is
something to read, not something to ask, which is why it can never answer a
question wrongly.

**Every line it prints that names a field is a button.** "The project has no
sponsor." takes you to the sponsor — the right step, the right box, ready to
type in.

### Step 1 — Overview

Name, code, description, objective. The code is how people refer to the
project in exports, in messages and in reports; it has to be unique across
the platform, and you are told here if it is taken rather than at the end.

### Step 2 — People and governance

Sponsor, project manager, owner, escalation contact, start date, target
completion, priority, reporting cadence.

The person-pickers search. Type part of a name; the people already on the
plan are offered without typing.

The **escalation contact** is the last stop when a milestone's own contact
has not resolved something. It is the field people skip and the one the agent
needs, so the plan will not publish without it.

Everybody you name here is put on the project when it is published, so the
person the agent chases can open what they are being chased about.

### Step 3 — Agentic AI policy

Four answers, each described in the words it will behave in:

* **Light** — minimal reminders. For a project whose owners talk every day
  and would find a reminder a week out an interruption.
* **Standard** — the recommendation. Reminders before the date, a daily chase
  afterwards, and escalation when that stops working.
* **Critical** — for dated commitments: a regulatory submission, a committee,
  a go-live. Earlier warning, closer follow-up, faster escalation.
* **Custom** — set the thresholds yourself. Choosing it opens the fifteen
  settings the agent actually reads: how many days before a date it reminds,
  how often it chases afterwards, how long a task may be silent before it is
  called stale, when lateness and when a block are escalated, when the
  sponsor hears, whether the project manager is told about the critical path,
  whether reviewers are reminded. Each one is bounded, because a reminder
  window of four hundred days and a chase every zero days are both ways of
  turning the agent off while believing it is on.

Whatever you choose is stated back as a paragraph, here and on the project
page afterwards. If you cannot recognise your project in that paragraph, you
have picked the wrong one.

### Step 4 — Major milestones

Name, owner, start, target date, and — behind **Edit** — a critical date and
an escalation contact of its own. Move milestones up and down; codes and the
tasks under them are renumbered with them.

Each milestone says who a delay reaches:

    Escalation: Priya Raman — inherited from the project

### Step 5 — Tasks

The work under each milestone: title, description, owner, start, due date,
and an escalation contact if this task needs one of its own. Each task says
what it inherits:

    Escalation: Omar Haddad — inherited from milestone Data Foundation

A task without an owner will not publish. The agent reminds the owner; a task
with none is a task nobody is asked about.

### Step 6 — Dependencies

Choose what has to finish first and what waits for it, then **Show the
impact**. Before anything is created you are told what the link would do and,
if the dates overlap, exactly which items would move and by how many days.

    [Adjust dates]   [Keep dates and flag conflict]   [Cancel]

**Adjust dates** moves the successor and everything behind it by the number
of days named. **Keep dates and flag conflict** moves nothing and records the
conflict on the link, where it stays: it comes back on the preview and it is
on the dependency in the published project. Nothing here ever moves a date
you did not ask to move.

A link that would make a loop, one that points at itself and one that already
exists are each refused, and nothing changes.

### Step 7 — Preview

The whole plan read back: the project and its dates, who is answerable, the
agentic policy in words, every milestone with its tasks and the escalation
each one carries, every dependency, and a timeline with the critical path —
computed by the same engine that computes it after publication.

Then two lists, which are not the same thing:

* **Required before publish** — what stops you.
* **Recommended improvements** — what a careful person would fix anyway.

### Step 8 — Publish

**Publish project** is in the action bar with Back, Save draft and Preview.
It is unavailable while anything is required, and it says how much:

    Publish unavailable — 3 required items remain.

Each of the three is a button that takes you to it.

One press. The project, its milestones, its tasks, its dependencies and
everybody's access are created in one transaction: if any part fails, none of
it is created. You land on the new project, and it is on the Planner under
Current projects.

### Coming back

The draft is under **Draft projects** on the Planner, with **Continue
editing** and **Discard**. It stays private, and the agent does not chase
anybody about it.

### Importing instead

If the plan is already in a spreadsheet, **Import project** takes the
workbook. You still see everything before it is created.

---

## One project

Eight tabs: **Overview, Plan, Timeline, Milestones, RAID, People, Updates,
Agent activity.**

Everything is populated from what you entered when you created it. There is
nothing to re-enter and no second copy.

**Overview** carries the health with its reason, the schedule findings, the
agentic policy in the words you approved, and **Where this project stands** —
a read of the project in which every statement is computed from the plan and
says which rows it came from. It is read, not asked: there is no chat box.

**Agent activity** is what the agent has actually done, in the words a
project manager would use — "Reminded Priya Raman that S-702 is due on
Friday", "Escalated to the project manager because the data extraction has
been overdue for four days" — filtered by reminders, escalations, update
requests, replies or health changes. **Run the agent now** runs it against
this project; it will not repeat a message it has already sent.

---

## What the agent does, and what it does not

It watches the dates deterministically. It reminds the owner before a date
and chases them after it. When that stops working it escalates, one rung at a
time: the task's own escalation contact, then the milestone's, then the
project's, then the project manager, then the sponsor. It does not notify
everybody at once.

Every message it sends carries the project's name and code, the item, the
owner, the due date, how far the escalation went, and a link straight to the
project. Messages arrive in your CreditProbe message centre, and the same
message is never sent twice.

It does not decide what is late. The rules do, and those rules are
arithmetic over the plan you published.

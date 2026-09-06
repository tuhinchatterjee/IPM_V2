# Project Planner Copilot — User Guide

Building and running a programme by describing it.

---

## Starting a project

**Delivery → Start a project.** A plan opens with a conversation on the left
and the plan itself on the right. Nothing exists until you publish it: the
draft is private to you, nobody is notified, nothing is scheduled, and the
agent does not chase anybody about it. That is what lets you think out loud.

You can type into the conversation, fill the panels in directly, or do both.
They are the same plan. A change made in chat appears in the panel
immediately; a change made in the panel is understood by the next thing you
say.

### Say what it is

> Call it the Recovery Rate Refresh.

The name and code appear in the panel above. The code is how people will refer
to it in exports and in chat — it is suggested from the name and you can
change it.

### Say who is answerable

Sponsor, manager, owner and escalation contact, plus the dates and the
priority. These are the questions somebody has to ask you, so the panel asks
them rather than expecting you to know to volunteer them.

The **escalation contact** is the last stop when a task's own owner has not
resolved something. It is the one field people skip and the one the agent
needs, so the plan will not publish without it.

### Choose how hard the agent chases

Four answers, each described in the words it will actually behave in:

* **Light** — minimal reminders. For a project whose owners already talk
  every day and would find a reminder seven days out an interruption.
* **Standard** — the recommendation. Reminders before the date, a daily chase
  afterwards, and escalation when that stops working.
* **Critical** — for dated commitments: a regulatory submission, a committee,
  a go-live. Earlier warning, closer follow-up, faster escalation.
* **Custom** — set the thresholds yourself.

Whatever you choose is stated back to you as a paragraph, before you publish
and afterwards on the project page. If you cannot recognise your project in
that paragraph, choose a different mode.

### Say what has to happen

> Add Data Foundation, Model Build and Independent Validation as the
> milestones.

> Under Data Foundation add Data Extraction, Data Reconciliation and Data
> Quality Review.

> Rohan owns Data Foundation.

> It starts 1 October and ends 15 November.

> Sameer owns Data Extraction until 20 October.

> Priya is the escalation owner for Independent Validation.

You can also say the whole lot in one paragraph. The Copilot reads it, shows
you what it is about to do, and waits.

### Say what waits for what

Three ways, all of which state the link before making it:

* **Link to previous task** on any task row — offers the obvious predecessor.
* **What waits for what** — pick both ends from the plan's own catalogue and
  press *Show me what that would do*.
* Say it: *"Validation Report can only start after Replication is finished."*

A link that would make a loop is refused, and the refusal names the loop. A
link that creates a date conflict is **stated and not fixed** — moving a date
somebody committed to is your decision, not the plan's.

### Check what is missing, then publish

**What this plan still needs** separates two things that are not the same:

* **Has to be settled before publishing** — blockers. Each says what would
  satisfy it. You can clear them by saying the missing thing.
* **Worth a look, but will not stop you** — warnings. A plan where every gap
  stopped publication is a plan nobody ever finishes drafting.

Then *Show me the whole plan*: every milestone, every task, every dependency,
who each one escalates to, and the monitoring policy in words. Read it once.
Then *Yes, create this project* — which is your act, not the assistant's.

Everything is created in one go, or nothing is.

---

## Running a project

Open it from **Delivery**. The **Copilot** tab is the same conversation, told
which project it is looking at.

It answers questions:

> What is overdue here?
> Who has not given me an update?
> What is on the critical path?
> What changed since last week?

And it changes things:

> Move M03-T02 to Daniel.
> M01-T01 is due 20 November.
> Change this project's monitoring to Critical.
> Under Data Foundation add Data Quality Review.

**Every change to a running project is shown to you first and waits for you to
say go ahead** — including additions. On a plan nobody has published, adding a
task promises nothing. On a running project it always does.

Every change the Copilot makes is on the project's own record, marked as
having come from the conversation, with what it was before and who asked for
it. An update you typed and an update you asked the agent to make are
different events, and the audit trail can tell them apart forever.

It will not do anything you could not do yourself. If you have viewer access,
asking politely is refused exactly as the form would refuse you.

### What it will not do

* Delete a milestone off a running project — the work under it would be
  orphaned. Move the tasks first, then remove it on the Milestones tab.
* Answer a question that belongs to another part of CreditProbe. Ask it for a
  Gini, a PSI or an ECL and it will say so and name where the answer lives —
  even when your own project is named after that subject.

---

## When it asks you something

Two colleagues called Sameer, or two tasks whose names both start "Data
Review", produce a short question with the candidates as buttons. Nothing is
applied while a question is open. A turn that half-understood and acted anyway
would be worse than one that asked.

If it did not follow something, it says which words it did not follow rather
than guessing.

---

## Running the agent yourself

On the project, *run the agent over this project now* sends whatever is due
right now rather than waiting for tonight. It is safe to press twice: the same
reminder is never sent to the same person about the same thing twice, so a
second run sends nothing new.

You need editor access on the project.

---

## What the agent does on its own

On the cadence your mode chose, for every project:

* reminds task owners before the date;
* chases them after it, at your mode's interval;
* asks for an update when something near-term has gone quiet;
* escalates to the task's escalation owner, then the milestone's, then the
  project's, then the manager, then the sponsor;
* tells the manager when the calculated critical path is at risk;
* raises a milestone with its escalation owner when the work under it will
  not land.

Nobody is told the same thing twice, and nobody is told about their own task
as an escalation — that is a reminder, and it goes to them as one.

# Playbook — user guide

The Playbook is where a committee's pack is built, reviewed, signed and acted
on. This guide is written for the people who do that: pack owners, section
authors, reviewers, and the chair who signs.

---

## What a committee pack is here

Not a document you write and attach. A pack is a **structured object** whose
figures CreditProbe calculates, whose commentary is written against those
figures, and whose approval is a named person's act recorded against a
version.

That has one consequence worth understanding before anything else:

> **The numbers on a pack are frozen when the pack is generated.**

They do not change when somebody opens the page. If the underlying data moves,
the pack still shows what it showed — until somebody regenerates it, which is
a deliberate act with a version bump behind it. This is why the pack tabled on
Tuesday and the screen opened on Thursday agree.

---

## The people, and what each may do

Two different things are recorded about everybody on a committee.

**Access** decides what you may do to a pack:

| Access | What it means |
|---|---|
| Viewer | Reads packs. |
| Contributor | Writes the sections they own. |
| Reviewer | Records that they read a section. |
| Editor | Edits any section on the pack. |
| Approver | Signs a pack off, and records what the committee decided. |
| Owner | Runs the committee: members, template, everything above. |

**Role in the room** is what you are called: chair, secretary, pack owner,
member, presenter, observer.

They are stored separately on purpose. A chair who does not sign packs is a
real arrangement, and a product that forced them to be the same would be
wrong about how committees work.

---

## The cycle

### 1. The committee

A data steward or administrator creates it, and becomes its first owner —
because a committee nobody can administer is one nobody can open. It carries
its cadence, the weekday it usually meets, and the **workflow offsets**: how
many days before the meeting each step is due.

### 2. The template

The shape the committee agreed its packs have: its sections, the governed
metrics on each, and the **materiality rules** — the declared thresholds that
raise a finding.

Templates are VERSIONED and old versions are never edited. A pack keeps the
version it was built from, so a pack tabled last quarter can still be read as
the shape it actually was.

### 3. Starting a pack

Four things, and the screen asks for all four rather than guessing:

* the **committee** — which forum reads it, and therefore who may see it
* the **template** — the shape
* the **period** — which reporting period every figure is measured at
* the **comparison period** — what "since last time" means on this pack

A pack created with a guessed period is a pack whose every figure is measured
at a date nobody chose.

### 4. Generate

**Generate** calculates every governed figure on the pack and freezes it,
marks any commentary whose figures have moved as stale, and raises whatever
findings the committee's declared thresholds produce.

You can regenerate as often as you like while the pack is open. Each run bumps
the version.

### 5. Reading a figure

Every KPI shows the value, and beside it the movement since the comparison
period — coloured in the direction the metric cares about. A rising default
rate reads as bad; a rising coverage ratio reads as good.

**Working** opens what is behind it: the metric and its version, the formula
hash, the dataset and its version, the run id, and the numerator, denominator
and rows considered. This is what makes a committee figure defensible rather
than asserted.

#### When there is no number

The pack never shows a blank or a zero for a figure it does not have. It says
which of these is true:

| What it says | What it means | What to do |
|---|---|---|
| **Not yet matured** | the performance window has not closed | come back next period |
| **No data** | the population is empty | check the filter or the scope |
| **Period not loaded** | that period was never loaded | ask the data steward |
| **Calculation failed** | something is broken | raise it |
| **Not authorised** | you may not see the source | request access |

These are five different afternoons. A dash would make them the same one.

### 6. Commentary

Write it yourself, or ask CreditProbe to draft it.

A drafted commentary comes back with **every sentence typed** — fact,
inference, recommendation, open question, data limitation — so you can see
which parts are the figures speaking and which are a reading of them.

Two things it will not do:

* **It cannot state a number your pack's figures do not support.** Every
  figure in the draft is checked against the evidence it was given, and a
  sentence carrying an ungrounded number is refused and reported rather than
  quietly dropped.
* **It is not yours until you say so.** A draft is labelled *AI draft — not
  accepted*, it does not go into the export, and the pack cannot be approved
  while it is unaccepted. Editing it, or pressing **Accept**, is you saying
  the words are yours now, and it is recorded against your name.

### 7. Findings

A finding is raised by a declared threshold in the committee's template, never
by a model deciding something looks important. Each one shows the rule that
fired and the numbers it fired on, so you can disagree with it on the evidence.

Five ways to answer one:

* **Acknowledge** — somebody has seen it and owns it
* **Explain** — there is a management response on the record
* **Actioned** — an action was raised, and the action is the answer
* **Resolved** — the underlying condition has gone away
* **Dismiss** — it is not material, and here is why

**Dismissing is different.** It is the only answer that takes something off the
committee's list, so it needs a written reason, needs reviewer access, and is
recorded against your name with the date. A reader six months from now has to
be able to see why.

A pack cannot be approved with a serious finding nobody has answered.

### 8. Readiness

The panel on the right of every pack. Eight checks — schedule, data, content,
narrative, findings, decisions, actions, review — each showing how far it has
got and, where it has not, exactly what is left and who owns it.

**The percentage is not the gate.** What blocks approval is the BLOCKING
reasons, shown in red. A pack at 96% with one unanswered critical finding
cannot go; a pack at 70% with nothing blocking can.

A check that could not be RUN says "not assessed" rather than scoring zero,
because that sends you to a different person.

### 9. Review and approval

Sections move: **ready to read** → a reviewer **approves** or **requests
changes**. A review is tied to the pack version the reviewer actually read, so
an edit after their approval correctly makes it stale.

Approval is an act by somebody with approver access. On approval the pack
becomes **read-only**.

### 10. What an approved pack is

A record. Every write route refuses it.

To correct one, **raise an amendment**: a new pack that supersedes it, with
the reason recorded. The approved pack stays exactly as it was approved,
because a historical record that can be edited is not a record.

### 11. Decisions

What the committee is being asked to decide, with the question, the
recommendation, the alternatives and the impact.

CreditProbe can draft the paper. It can never record the answer — that is a
person with approver access saying what happened in a room, and it goes on the
record with their name and the date.

### 12. Actions

What follows from a decision.

An action is the **governance record**: which committee asked for it, off which
decision, in which pack. The work itself lives in the **Project Planner**, and
the action reads its progress from there every time you look. It does not keep
its own copy, because two systems each holding a percentage will eventually
disagree, and the one read out in a meeting is the one on the pack.

**Send to Planner** creates a real Planner task through the Planner's own
rules. If somebody later deletes that task, the action says so rather than
quietly reading as never-sent.

Closing an action asserts the work was done, so it requires evidence.

### 13. Since last time

The comparison against the previous approved pack, with **redefinitions
first**. A metric whose formula changed between two packs has a "movement"
that is not a movement in the business at all, and a committee shown that at
the bottom of a list of real changes will read it as one.

### 14. Documents

You can attach somebody's existing pack — Word, Excel, PowerPoint — and
CreditProbe will read it into labelled content. A PDF is kept as supporting
evidence.

**Everything read out of a document is labelled as theirs.** A table from a
file shows as *their figures*, and says CreditProbe did not calculate it. To
make it a governed figure, **map it to a metric**: the pack then shows
CreditProbe's own number, with the file's values kept beside it so the two can
be compared.

### 15. Downloads

Four formats, each for a different room:

| Format | For |
|---|---|
| **PDF** | the pack itself, as tabled |
| **Word** | a pack somebody will edit or comment on |
| **PowerPoint** | presenting in the room |
| **Excel workbook** | the evidence: every figure with its working |

All four render from the frozen snapshots, so they agree with the screen. A
draft export says DRAFT on it.

Every download is recorded with who took it, when, and which figures it held.

### 16. Who you are waiting on

The **chase** panel on the Playbook landing screen shows what the committee
sweep would send if it ran now: sections not submitted, reviews not returned,
findings not answered, actions coming due.

**Opening that screen sends nothing.** It is a dry run.

The sweep itself runs as a background job and notifies people through
CreditProbe's own notification centre.

---

## Things worth knowing

**Two people editing at once.** If somebody changed the pack since you opened
it, your save is refused and the message names them. Nothing is silently
overwritten.

**A pack you cannot see.** Reads as not-found rather than as "forbidden",
because "forbidden" would confirm it exists.

**Titles with special characters.** `<Finance> Review & sign-off` is stored
exactly as you type it and appears that way in every export.

**What an assistant may never do.** Approve a pack, approve a section, publish,
record a review, decide, close an action, dismiss a finding, move a committed
meeting date, edit a formula, edit an approved pack, delete a pack, delete a
section, or import a document. Thirteen operations, refused whatever access
the person driving the assistant holds.

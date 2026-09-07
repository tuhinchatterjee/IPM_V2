# Project Planner — Demonstration Runbook

Twenty-five minutes. A programme set up from nothing, published, and then
run by the agent.

---

## Before the room

    docker compose up -d
    .venv/bin/python scripts/seed_planner.py            # IFRS 9 programme
    .venv/bin/python scripts/seed_retail_portfolio.py --reset

The reset matters. The Retail portfolio's demonstration state is deliberate —
one thing overdue, one blocked, three stale, one imminent — and a stack that
has been running for a week has chased all of them several times. Reset it on
the morning of the demonstration and the agent's behaviour is legible.

Then check it:

    .venv/bin/python scripts/acceptance/agentic_demo_scenario.py

Nineteen checks. If any of them fails, do not open the room; the observed
state is printed at the bottom and says which part of the story is missing.

Sign in as **priya.raman**. Open **Delivery → Project Planner**.

**Do not** demonstrate live AI unless a provider key is configured. Nothing
in this runbook needs one: every number, date, escalation and reminder in it
is arithmetic.

---

## Act 1 — the Planner (2 minutes)

The page reads top to bottom in the order somebody works.

> "Needs attention is not a list of projects. It is a list of things that
> need somebody today, and each one says who, when it was due, why it is
> here, how far the agent has already chased it, and what would resolve it."

Read one row out loud. Then scroll: Current projects with the columns a
person scans before opening anything, then Draft projects — plans somebody
started and has not published — then Closed.

> "There is no chat box on this page. The AI here is not something you talk
> to. It is something that watches the dates."

---

## Act 2 — creating a project (8 minutes)

**Create new project → Start the setup.** Eight steps, and say so.

**Step 1.** Name it *LGD Model Redevelopment*. Type a code that already
exists — `IFRS9-REDEV` — and press **Next**.

> "It stops here, on step one, and tells you the code is taken and by what.
> Not on step eight after you have filled in forty fields."

Fix the code. Next.

**Step 2.** Sponsor, project manager, owner, escalation contact. Type into
the search box above a picker.

> "This searches. On a bank with five thousand staff, a dropdown is a wall."

Set the target completion BEFORE the start date and press Next.

> "Refused, here, by the step that took it."

Fix it. Next.

**Step 3.** The four policies, each described in the words it will behave in.
Choose **Critical** and read the sentence.

> "Whatever you choose is stated back to you in English, here and on the
> project page afterwards. If you cannot recognise your project in that
> sentence, you have chosen the wrong one."

**Step 4.** Add two milestones. Point at the line under each:

> "Escalation: Priya Raman — inherited from the project. It tells you where
> the answer came from, not just what it is."

Press **Back**, then **Next**, to show the steps are real.

**Step 5.** Add two or three tasks under the first milestone, one due in the
past. Point at the escalation line again — now inherited from the milestone.

**Step 6.** Link the first task to the second and press **Show the impact**.
If the dates overlap:

> "Before anything exists, it tells you what this link would cost: which
> items move and by how many days. Three answers — adjust the dates, keep
> them and flag the conflict, or cancel. Nothing here ever moves a date you
> did not ask it to move."

Take **Keep dates and flag conflict**. Then try to link them the other way
round.

> "Refused. That would be a loop, and nothing in the plan changed."

**Step 7.** The whole plan read back, with the timeline and the critical
path, and two lists that are not the same thing: what is required before
publish, and what a careful person would fix anyway. The flagged conflict is
in the second.

**Step 8.** **Publish project.**

> "One transaction. The project, the milestones, the tasks, the dependencies
> and everybody's access — or none of it."

You land on the project. Then go back to the Planner:

> "And there it is, under Current projects, with its sponsor, its manager and
> its dates."

---

## Act 3 — the project (4 minutes)

Open the project you just made, or the Retail Application Scorecard
Redevelopment for a fuller one.

**Overview.** The health with its reason, what the schedule rules flag, the
agentic policy in the words that were approved, and **Where this project
stands**.

> "Every line of that is computed from the plan and says which rows it came
> from. It is a read, not a conversation — you cannot ask it a question, so
> it can never tell you it did not understand one."

**Timeline**, **Milestones**, **RAID**, **People**, **Updates** — one click
each, no commentary.

---

## Act 4 — the agent (6 minutes)

Open **RET-SCORECARD**. Show the state: S-507 overdue, S-705 blocked with a
reason, S-702 due in three days.

**Agent activity → Run the agent now.**

> "Reminded the owner that S-507 is overdue. Escalated it above them, because
> it has been overdue for four days and nothing has happened. Told the
> sponsor. Reminded the owner of S-702, which is due but not late — a
> reminder, not an escalation, because the difference is the whole point."

Press **Run the agent now** a second time.

> "Nothing. It has already said all of that. The same message is never sent
> twice, and that is the difference between an assistant people read and one
> they filter."

Now open **Messages** in the sidebar and open the planner message.

> "The project's name and code, the item, the owner, the due date, how far
> the escalation went, and a link straight to it. Everything you need to act
> without opening anything else — and the link works, because publishing
> seated everybody the plan named."

---

## Act 5 — the ladder (3 minutes)

Back on the project, filter Agent activity to **Escalations**.

> "Task contact, then milestone contact, then project contact, then the
> project manager, then the sponsor. One rung at a time. Nobody is told
> because everybody was told, and every message says why it reached them."

---

## Act 6 — drafts (2 minutes)

Back to the Planner. Start a new project, fill in only the name, press **Save
draft**, and return.

> "It is under Draft projects, not among the projects. Nothing is scheduled
> off it and nobody is being chased about it, because it is not a project
> yet. Continue editing, or discard."

---

## If something does not work

**The Planner is empty.** Run `scripts/seed_planner.py` and
`scripts/seed_retail_portfolio.py`.

**The agent sends nothing.** The demonstration state has drifted with the
calendar. `scripts/seed_retail_portfolio.py --refresh-dates` rolls it
forward; `--reset` rebuilds it.

**The agent sends everything, twice.** The stack has been running for days
and you are seeing the history. `--reset`.

**A person cannot be found in a picker.** Type more of the name. The pickers
search the directory; they do not list it.

## What not to promise

* Live AI, unless a key is configured. Nothing in this runbook uses one.
* Email. Messages arrive in CreditProbe's own message centre.
* That the agent decides what is late. It applies rules over the plan, and
  the rules are shown to the person who approved them.

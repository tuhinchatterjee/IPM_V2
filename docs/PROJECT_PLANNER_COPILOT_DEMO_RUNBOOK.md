# Project Planner Copilot — Demonstration Runbook

Twenty-five minutes, one browser, nothing typed that has not been run.

Every sentence below has been executed against the built stack. If one of them
does not do what this says, that is a defect and not a demonstration you should
work around.

---

## Before the room

    docker compose up -d
    ENV=development SYNTHETIC_DATA_MODE=true \
      .venv/bin/python scripts/seed_retail_portfolio.py --reset

Four Retail Credit Risk programmes, one of them the Retail Application
Scorecard Redevelopment. Sign in as **priya.raman**.

Check it is ready:

    .venv/bin/python scripts/acceptance/agentic_demo_scenario.py

Nineteen checks. It fails rather than skips if the programme is missing — "the
programme was not seeded so we skipped the demonstration" is the report that
lets an empty demo reach a client.

---

## Act 1 — a programme built by talking to it (10 minutes)

**Delivery → Start a project → Start a plan.**

> Call it the Recovery Rate Refresh.

*The panel names it. Point out that nothing exists yet: this is private to
you, nobody has been told, and the agent is not chasing anybody.*

Fill in **Who is answerable** — sponsor, manager, owner, escalation contact,
dates, priority. Press Save.

*Stop on the escalation contact. This is the field people skip and the one the
agent needs, and the plan will not publish without it.*

**How do you want the Agentic AI to work?** — choose **Critical**.

*Read the paragraph out loud. It is the same paragraph the project page will
show a month from now, and the same one the preview shows before publishing.
One function, one wording.*

> Add Data Foundation, Model Build and Independent Validation as the
> milestones.

*Three milestones from one sentence — which is how somebody actually names the
stages of a programme.*

> Under Data Foundation add Data Extraction, Data Reconciliation and Data
> Quality Review.

> Rohan owns Data Foundation.

*A confirmation appears. Nothing has happened yet. Press "Go ahead".*

> Sameer owns Data Extraction until 20 October.

> Priya is the escalation owner for Independent Validation.

Then the messy one, in a single turn:

> We need a Reporting milestone, Rohan owns it, it starts 15 November and
> ends 20 December, and under it add Draft Report, Committee Review and Final
> Sign-off. Sameer owns Draft Report until 30 November. Committee Review can
> only start after Draft Report is finished.

*Eight facts, three of them about things it is creating in the same sentence.
Show the preview, then apply it.*

---

## Act 2 — dependencies, three ways (4 minutes)

1. **Link to previous task** on Data Reconciliation. *It states the link
   before it exists, and offers the obvious predecessor.*
2. **What waits for what** — pick both ends, *Show me what that would do*.
3. Say it: *"Validation Report can only start after Replication is
   finished."*

*If any of them would make a loop, the refusal names the loop. If any creates
a date conflict it is stated and not fixed — moving a date somebody committed
to is a decision, not a correction.*

---

## Act 3 — the completeness check and the publish (3 minutes)

> What is still missing?

*Two lists, deliberately different. Blockers stop publication and say what
would satisfy them. Warnings do not. Clear a blocker by saying the missing
thing.*

**Show me the whole plan.** *Every milestone, every task, every dependency,
who each escalates to, and the monitoring policy in words.*

**Yes, create this project.** *One transaction. It lands on the project.*

Go back to **Delivery**: it is in the list.

---

## Act 4 — a month later (4 minutes)

Open **Retail Application Scorecard Redevelopment → Copilot**.

> What is overdue here?
> What is on the critical path?

Then change it:

> Move S-703 to Kavita.

*A confirmation. Nothing has happened. Press "Go ahead".*

**Overview tab** → the change is on the project's own record, marked as having
come from the conversation, with what it was before.

*Point at "How the Agentic AI works on this project". The policy that was
approved when the project was created, in the same words, still readable.*

---

## Act 5 — the agent (3 minutes)

    .venv/bin/python scripts/acceptance/agentic_demo_scenario.py

*Nineteen checks on the seeded programme: something overdue, something
blocked, something stale, something imminent. The reminder reaches the owner;
the escalation reaches the milestone's contact; the four-day delay reaches the
sponsor. Nobody is told twice. Running it again sends nothing new.*

Or on the project, press **run the agent over this project now**, then press
it again. *The second press sends nothing. That is the deduplication, not a
failure.*

---

## Act 6 — the boundary (1 minute)

In the project's Copilot:

> What is the gini of the application scorecard?

*"Not my area." It names Scorecard Validation and quotes the phrase that
stopped it.*

Then:

> How is the scorecard redevelopment going?

*Answered. The programme is named after another module's subject and that does
not make questions about the programme somebody else's.*

Then:

> What is the population stability index?

*Refused again — because that is asking for the number, not talking about the
work. A phrase used as a name is fine; a phrase being asked for is not.*

---

## If something does not work

Run the harnesses. They fail rather than skip, and they say which step.

    .venv/bin/python scripts/acceptance/copilot_journeys.py
    .venv/bin/python scripts/acceptance/creation_flow_journey.py
    .venv/bin/python scripts/acceptance/copilot_adversarial.py
    .venv/bin/python scripts/acceptance/agentic_demo_scenario.py

---

## What not to promise

Live AI is **NOT VERIFIED** in the environment this was built in: no provider
key is configured. Everything above runs on the deterministic reader, which is
the point — the layer works offline. Do not tell a client the model has been
exercised against a live provider until somebody has run it in an environment
that has one.

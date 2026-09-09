# Project Planner Copilot — Architecture

How a person talks a programme into existence, and what stops the assistant
doing anything they could not do themselves.

This document is the map. `docs/PROJECT_PLANNER.md` describes the Planner it
sits on; the user guide describes what a person sees; the acceptance matrix
records what was run. This describes why the pieces are the shape they are.

---

## 1. The problem

The old New Project screen was eleven fields and a Create button. That is a
good form and the wrong shape for the job. Nobody starts a project by knowing
its reporting cadence. They start by knowing what has to happen and roughly
when, and the governance questions are things they answer once somebody asks.

So the screen is a conversation on the left and the plan taking shape on the
right, and neither is the primary one. They are two views of one document, and
every change from either goes through the same writer.

The hard part is not the chat. It is that a chat which can create a programme
can also create a mess, and that everything a bank does with a plan afterwards
— chase people, escalate, report, audit — depends on the plan being real.

---

## 2. The pieces

    backend/planner/
      control.py      the deterministic engine: what is late, near, stale
      schedule.py     critical path and slip, by CPM
      access.py       Grant / require — one place that decides who may do what
      service.py      the ONLY writer for a live project
      monitor.py      the sweep: who gets told, when, once
      escalation.py   the ladder: task → milestone → project → manager → sponsor
      policy.py       Light / Standard / Critical / Custom, in numbers and words
      draft.py        a plan before it is a project, and the publish transaction
      live.py         the same commands, against a project that already exists
      scope.py        the topic boundary — what is NOT delivery
      reading.py      resolution primitives: dates, names, codes, ambiguity
      language.py     ordinary sentences → the commands above
      copilot.py      the frozen, allowlisted agent surface
    backend/api/routers/planner_copilot.py     11 routes
    frontend/src/components/planner/
      copilot-chat.tsx      the conversation
      draft-builder.tsx     the panels beside it

Roughly 4,900 lines of new backend, 1,500 of new frontend, and one migration
(`0043`, `planner_tasks.milestone_id`).

---

## 3. The five decisions everything else follows from

### 3.1 One writer, two doors

`draft.apply` is the only way a draft changes. `service.*` is the only way a
project changes. The chat panel, the milestone form, the task table and the
Copilot all call the same functions, so a rule added in one place — a code
that must not be regenerated, an escalation that must be inherited, a cycle
that must be refused — holds for every way in.

This is what makes the security argument short. The Copilot is not trusted
because it is well-behaved; it is safe because it cannot reach anything the
person could not reach by clicking. `tests/planner/test_live_edit.py` asserts
that from the other side: a viewer who asks politely is refused with the same
403 the form would give them.

### 3.2 The boundary comes first, and it is a gate, not a prompt

`scope.classify` runs before a draft is loaded, before a model is called,
before anything is resolved. Nine foreign areas — scorecard validation, IFRS 9,
Early Warning, lenses, what-if, Borrower 360, the Data Builder, the AI Brain,
the platform itself — each with patterns and a sentence naming where the
answer lives.

The interesting part is what it does NOT refuse. A programme called *Retail
Application Scorecard Redevelopment* contains three words that belong to
another module, and a boundary that matched words would refuse to discuss the
project it had just created. So the test is not "does a foreign word appear"
but "is every foreign phrase being used as part of something's name":

    "How is the IFRS 9 Model Redevelopment going?"      delivery
    "What is the ECL under the IFRS 9 Model Redevelopment?"   not delivery

`IFRS 9` sits inside the name; `ECL` sits outside it.

That forgiveness has one exception, found by driving the product rather than
by reading it. Real programmes name their tasks after the metrics they
produce. With a task called *Population stability index review*, containment
made "what is the population stability index?" a delivery question — one the
Copilot has no data to answer. So a phrase used as a **name** is forgiven and a
phrase being asked **for** is not, and the cue is the shape of the question
rather than the noun.

### 3.3 The reader is rules first, the model second, and neither supplies an id

`language.read` runs fifteen ordered rules over the sentence. Each returns a
span, some commands and a focus; the earliest span wins, so the sentence is
read left to right the way a person wrote it. What the rules could not read is
offered to the configured provider under `MODEL_SCHEMA` — which contains no
`_id` fields at all.

Whatever comes back is re-resolved by `resolve_model` against the plan and the
directory the asking person can see. The model may say "Priya"; only
`reading.choose` may turn that into user 41, and only if exactly one Priya is
in reach. Two Priyas is a question with two buttons, not a coin toss.

This is why the layer works with no provider configured, and why a provider
that hallucinated a user id could not use it.

### 3.4 A draft and a live project are the same document

`live.plan_of` renders a running project in exactly the shape `draft.empty()`
defines: overview, governance, agentic, milestones, tasks, links. So the same
fifteen rules, the same command vocabulary and the same clarifications work on
both, and there is no second grammar to keep in step.

`live.py` writes no columns. It resolves a code to a row id and calls the
function the task drawer calls, which is what makes the permission check, the
history entry, the AI_CHAT audit row, the optimistic lock and the
re-evaluation signal identical however the change arrived.

One deliberate difference: on a live project **nothing** applies without
confirmation, additions included. A draft applies pure additions immediately
because nobody was promised anything about a milestone that did not exist a
moment ago. On a running project that is never true.

### 3.5 Publishing is one transaction and one person's act

`draft.publish` runs inside `session.begin_nested()`. A publication that fails
on the fortieth task leaves no project behind for somebody to find on Monday
and start working on. There is no registered tool for it: `confirm_publish`
requires an actual affirmative from the request, so a model that decided the
conversation amounted to agreement cannot create anything.

---

## 4. The agentic policy

Every project answers one question at creation: *how do you want the Agentic
AI to work?* Four answers.

| Mode | Reminders | Chase | Escalates | Sponsor |
|---|---|---|---|---|
| Light | 1, 0 | every 3 days | never on lateness | never |
| Standard | 7, 3, 1, 0 | daily | after 2 days | after 5 |
| Critical | 14, 7, 3, 1, 0 | daily | after 1 day | after 3 |
| Custom | yours | yours | yours | yours |

They are named rather than numeric because "remind at 7, 3, 1 and 0 days,
chase daily, escalate after 2" is a correct description and a terrible
question. A person setting up a project knows whether it is routine or
time-critical; they do not know what a good staleness window is.

`policy.sentence()` renders the mode as a paragraph, and that same paragraph
is what the setup screen shows, what the preview shows before publishing, and
what the project page shows a month later. One function, one wording, no
drift.

`policy.stamp()` is the one place a mode is written to a row. It writes the
mode's own reminder cadence and staleness window with it — because `policy.of`
reads those two columns as overrides on top of the mode (so a project
configured before modes existed keeps its behaviour), and a project set to
Critical while those columns still held the creation defaults would be
escalated like Critical and reminded like Standard.

---

## 5. The escalation ladder

`escalation.py` walks task → milestone → project → manager → sponsor, and
never returns the task's own owner at any rung: telling somebody their own task
is late is a reminder, not an escalation.

Two functions, deliberately different:

* `_rungs()` returns every named rung uncollapsed, so role rules ("tell the
  sponsor", "tell the manager") still fire when one person occupies several
  rungs. Collapsing first silently disabled the sponsor rule on small
  projects where the sponsor was also the escalation contact.
* `ladder()` collapses by user, nearest rung first, so nobody is told twice.

`_one_each()` keeps the most serious finding per (entity, person). A person on
three rungs of one late task gets one message about it, not three. That is
tested, and the test exists because the first implementation sent three.

---

## 6. Deduplication, and why a sweep is safe to run twice

`monitor._print()` fingerprints (project, entity, person, trigger, bucket) and
refuses to send the same fingerprint twice. `bucket` is the overdue day divided
by the mode's chase interval, so "every 3 days" means three quiet days, not
three messages.

That is why `POST /planner/projects/{id}/sweep` is safe to expose to the person
running the project. "Why has nobody been reminded about this?" is a Tuesday
afternoon question, and routing a project manager to an administrator to find
out is how a monitoring feature stops being believed.

---

## 7. What the AI actually does, and what it does not

**It does:** read a sentence the rules could not; propose commands; nothing
else.

**It does not:** decide permissions, resolve a name to a user id, publish a
project, reach a tool outside the twenty-four in `copilot.ALLOWED_TOOLS`, or
reach any domain (`ALLOWED_DOMAINS` is empty — the Copilot has no browsing).

`tests/agentic/test_registry.py` refuses to register any tool named for
publishing at anything below Level 4, and rather than weaken that rule the
publish tool was removed: publishing is a route a person posts to, not a
capability a model holds.

**Live AI is NOT VERIFIED in this environment.** No provider key is configured
here, so the model path has been exercised against the structured contract and
its schema but not against a live provider. The provider path is wired and the
deterministic path is complete without it; the acceptance matrix states this as
NOT VERIFIED rather than rounding it up.

---

## 8. Where the data lives

    planner_drafts        key, plan (JSONB), status, step, version, project_id
    planner_projects      + agentic_mode, agentic_policy, owner_id, escalation_id
    planner_milestones    + escalation_id, critical_date
    planner_tasks         + milestone_id (migration 0043), escalation_id
    planner_updates       append-only history; `source` distinguishes AI_CHAT
    planner_reminders     what was sent, to whom, about what, once

`planner_tasks.milestone_id` is migration 0043 and it is load-bearing: the
draft grouped tasks under milestones and publish dropped the grouping, so the
ladder could not walk task → milestone. The column carries it.

---

## 9. The UAT correction: what changed, and what did not

Manual testing of the Docker application found the creation experience
confusing. The correction was to the SHAPE of the product, not to its
foundations. Everything in sections 1 to 8 still holds — the draft document,
the single `apply`, the atomic publish, the deterministic monitor, the
escalation ladder, the fingerprint — because none of that was what was wrong.

What was wrong was the front of it: the Planner led with a conversation, and
the creation screen showed every panel of the plan at once.

### The form sits on the same layer the conversation did

`frontend/src/components/planner/wizard.tsx` is eight steps over exactly the
draft commands that were already there — `set_overview`, `set_governance`,
`set_agentic`, `add_milestone`, `move_milestone`, `add_task`, `add_link`,
`set_step`, and then `preview` and `publish`. There is no second data model
and no "save the form" endpoint. The draft on the server is the plan; the
form is a view of it, one step at a time.

This is why §15's "the project detail is populated from the creation data, not
a separate copy" needed no work: publish already wrote the plan into ordinary
planner rows through `service`, and the tabs already read those rows.

### Four things were added to the layer, not on top of it

**`link_preview` now returns an adjustment.** The conflict sentence said two
dates overlapped; it did not say what fixing it would cost. `_adjustment`
walks the successor and everything downstream of it and returns each item's
current and proposed dates. `_cmd_add_link` applies exactly that set when
`adjust` is asked for, and otherwise writes the conflict onto the link, where
`publish` carries it into `PlannerDependency.notes`. Nothing moves a date
that was not asked for.

While writing it, the finish-to-start comparison was found to disagree with
`schedule._forward` by one day: the scheduler has always meant "the day
after", and the check meant "not before". The check was wrong.

**`draft.timeline`** projects the plan into `control.Plan` and runs
`schedule.compute` over it, so the preview's dates and critical path are
produced by the same engine that produces them after publication rather than
by a second implementation.

**`draft.check` splits `project` into `overview` and `governance`.** The form
asks for them on different steps, and a step that cannot tell which of its
own notes belong to it either blocks on somebody else's question or lets its
own through.

**`query.needs_attention`** returns one row per finding rather than one row
per project, joining the engine's findings to the owner, the due date and the
most recent `PlannerReminder` for that item — so a reader can see not only
what is wrong but how far the agent has already chased it.

### `planner/activity.py`

The Agent Activity tab reads `PlannerReminder` and the health entries in
`PlannerUpdate` and turns them into sentences: "Reminded Priya Raman",
"Escalated to the project manager". It is a reader, not a rule: every line
corresponds to a message that was sent.

### What was removed

`copilot-chat.tsx` and `draft-builder.tsx` are deleted, and with them the
chat box on the Planner home, the conversational creation flow and the
Copilot tab on a project. The DRAFT and CHAT routes remain and remain
governed and tested — `language.py`, `copilot.py`, `live.py` and `scope.py`
are untouched — but nothing in the product's interface reaches the chat any
more. The one part of it worth keeping, `agent.project_brief`, is a read-only
panel on the project Overview.

### One change outside the Planner

`useAsync` in `frontend/src/lib/hooks.ts` gained an opt-in `keepPrevious`.
Blanking the data while refetching is right on a screen that re-reads
something that may now be different; it is wrong on a form that saves a field
and re-reads the document it just changed, because the form is unmounted
between the save and the response. Off by default; on for the creation form.

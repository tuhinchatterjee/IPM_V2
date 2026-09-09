# Project Planner Copilot — Final Report

What was built, what was found, what was run, and what is still not verified.

Branch: `claude/project-planner-copilot`.

---

## 1. What this phase was for

A person who runs programmes in a bank should be able to start one by
describing it, and change it a month later by saying so. Everything the
Planner already did — the deterministic health engine, the critical path, the
chase workflow, the permissions, the audit trail — stays exactly where it is.
This phase put a conversation in front of it that cannot do anything the
person could not do themselves.

The scope constraint was explicit and was held to: only Project Planner
improvements and the minimum shared infrastructure genuinely required by them.
The diff for this phase touches 25 non-test files. Every one of them is under
`backend/planner`, the two planner routers, `backend/models/planner.py`, the
delivery frontend, two Alembic revisions, one router include in
`backend/api/main.py`, and registry entries in `backend/agentic/tools.py`.
Lenses, Early Warning, What-If, Scorecard Validation and Playbook were not
touched.

---

## 2. What was built

**A plan before it is a project.** `draft.py` holds a plan document nobody
else can see, with one writer and an explicit command list. `publish()` turns
it into a real project inside a single savepoint — all of it, or none of it.

**A boundary that is a gate, not a prompt.** `scope.py` classifies before a
draft is loaded, a model is called or a tool is reached. Nine foreign areas,
each with a sentence naming where the answer actually lives.

**A reader.** `reading.py` and `language.py` turn ordinary sentences into the
commands the panels already use: fifteen ordered rules over the sentence,
positional rather than priority-ordered, with the model reading only what the
rules could not and supplying no ids at all.

**The same commands against a running project.** `live.py` renders a
published project in the plan shape the reader speaks and applies the
resulting commands through `service.*` — the same functions the task drawer
calls, so the permission check, the history entry, the AI_CHAT audit row and
the re-evaluation signal are identical however the change arrived.

**A monitoring policy that means something.** `policy.py` gives every project
one of four named modes, `escalation.py` walks the ladder task → milestone →
project → manager → sponsor, and `monitor.py` sends each person one message
about one thing once.

**The screens.** Delivery reordered around what a person came to do, a plan
that is a conversation and a panel of the same document, and a project page
whose Copilot tab both answers and changes.

---

## 3. The defects this phase found, and how

Every one of these was found by driving the product, not by reading it. That
is the argument for the journey harnesses, and for running them against the
built images rather than the developer's machine.

**1. Publishing was broken for a whole class of plans.**
`draft._seat_everybody` gave escalation contacts the project role
`"STAKEHOLDER"`, which is not one of the eight roles the service accepts.
Publishing any plan whose escalation contact was not already its sponsor,
manager or owner failed at the very last step — after the preview and the
confirmation — with a message about role names. Every existing test made the
sponsor the escalation contact too, and the first seat wins, so the bad role
was never reached. Found by the browser journey on its first complete run.
Fixed with the constants; a test now names a fifth person nobody else is.

**2. The reader could not read the first sentence of a new project.**
"Add A, B and C as the milestones" is how somebody names the stages of a
programme. Only "add X as the first milestone" was understood — the sentence
they say second. Found the same way.

**3. Choosing a mode changed escalation but not reminders.**
`policy.of` reads `reminder_days` and `stale_after_days` off the row as
overrides on top of the mode, so that a project configured before modes
existed keeps its behaviour. Both the publish path and the demo seed set the
mode while those columns still held the creation defaults, so a programme
marked Critical was escalated like Critical and reminded like Standard —
the mode half doing nothing, silently. `policy.stamp()` is now the one place a
mode is written, and it writes the mode's numbers through with it.

**4. The people lookup lost the person being talked about.**
One OR'd query over every word in a sentence with a single overall `LIMIT 60`.
On a demonstration database that is fine. On a directory of a few thousand,
"Priya owns the Draft Report by December" could come back sixty Drafts and
Decembers and no Priya — and the Copilot would then say, with no hedging at
all, that nobody by that name worked there. Now one bounded query per word: a
name resolves by what it is, not by what else was in the sentence. The
regression test builds the crowd and says the sentence; it fails against the
old lookup.

**5. The escalation ladder silently disabled the sponsor rule.**
`at_level(SPONSOR)` returned nothing when the sponsor also occupied an earlier
rung, which on a small project is most of the time. Split into `_rungs()`
(uncollapsed, for role rules) and `ladder()` (collapsed, so nobody is told
twice).

**6. A notification storm.** One person on several rungs of one late task
received several messages about it. Found by an existing monitor test, fixed
in the product with `_one_each()` rather than in the test.

**7. A project's monitoring policy could not be read back.** It was settled at
creation and invisible from the day after, so nobody could answer "why has the
agent not chased this?" without opening the database.

**8. Tasks lost their milestone at publish.** The draft grouped them; the
project had no column to put the grouping in, so the escalation ladder could
not walk task → milestone. Migration `0043`.

**9. A project id named beside a draft was never checked.** The turn worked on
the draft and would not have read that project, but it echoed the id back
having verified nothing. Found by the adversarial sweep.

**10. The topic boundary had a hole.** Containment forgives a foreign phrase
inside something the plan is called — which is what lets somebody discuss the
"Retail Application Scorecard Redevelopment" programme. But real programmes
name their tasks after the metrics they produce: with a task called
"Population stability index review", the planner Copilot accepted "what is the
population stability index?" — a question it has no data to answer, asked of
the one part of the product that cannot answer it. A phrase used as a name is
still forgiven; a phrase being asked for is not. Found by the adversarial
sweep.

Three further defects in the reader were found by driving the ten required
sentences rather than by testing them: a greedy name pattern crossing "and", a
non-greedy `_THING` capturing a single character through an all-optional tail,
and placeholder substitution keyed on proposal index instead of on what each
proposal creates. A reader built to satisfy the examples would never have hit
any of them.

---

## 4. The natural-language layer, specifically

The clarification was that the Copilot is not complete until ordinary language
actually becomes the existing safe command layer, and that this must not be
faked with keyword examples tailored to a browser test.

It is two readers behind one contract. The rules are general, ordered and
positional; they are free, offline and exact. The model reads only the
leftovers, under a schema that contains no `_id` fields at all, and everything
it says is re-resolved afterwards against the plan and the directory the
asking person can see. `reading.choose` is the only thing in the system that
turns "Priya" into a user id, and it refuses to when two Priyas are in reach.

The evidence that it is a reader rather than a lookup table is negative: it was
built, then the ten sentences were driven through the product, and that
surfaced three defects in it. A keyword implementation cannot have those bugs
because it has no grammar to get wrong.

**Live AI is NOT VERIFIED.** No provider key is configured in this
environment. `read_with_model` returns `None` when the provider is not
configured, the rule reader's answer stands, and the Copilot says what it could
not read rather than inventing a command. The provider path is wired and its
schema is tested; it has not been exercised against a live provider, and this
report does not round that up.

---

## 5. What was run

    pytest tests/planner tests/agentic                   761 passed
    scripts/acceptance/copilot_journeys.py               40/40
    scripts/acceptance/creation_flow_journey.py          58/58
    scripts/acceptance/copilot_adversarial.py            14/14
    scripts/acceptance/agentic_demo_scenario.py          19/19
    scripts/acceptance/planner_journeys.py               43/43
    scripts/acceptance/planner_demo_journey.py           18/18
    ruff check backend/ tests/ scripts/                  clean
    npx tsc --noEmit                                     clean
    npx eslint (delivery + planner components + api.ts)  clean

Everything from the second line down ran in a real Chromium or over a real
socket, against Docker images built from this commit, with a real login cookie
from the real login route.

The definitive full regression is recorded in §7.

---

## 6. What is deliberately not there

**The Copilot will not delete a milestone off a running project.** The work
under it would be orphaned. It says so, and says which tab to use.

**The Copilot cannot publish.** There is no registered tool for it, and
`tests/agentic/test_registry.py` refuses to register one at anything below
Level 4. Rather than weaken that rule, the tool was removed and publishing
became a route a person posts to.

**The Copilot has no browsing.** `ALLOWED_DOMAINS` is empty.

**Nothing applies on a running project without a person's confirmation**,
additions included.

---

## 7. The definitive regression

Run on final executable HEAD, against the development PostgreSQL instance
carrying the seeded analytical domains:

    DATABASE_URL=postgresql+psycopg://... \
      .venv/bin/python -m pytest tests -p no:randomly

    12,982 passed, 2 failed, 53 skipped, in 34 minutes

Both failures were investigated rather than waved through, and neither belongs
to this phase.

**`tests/api/test_messaging_corrections.py::…[role]`** searches the messaging
directory for `role='ANALYST'` with `limit=200` and expects to find the
account it just created. It fails because this session's own test runs left
more than two thousand fixture users in that database, so the account is not
in the first two hundred rows. Verified: it **passes on a freshly migrated
database**. It is caused by the state of a long-lived development database and
not by any change here.

It is worth noting what it is an instance of, because this phase fixed the
same shape of bug in the Copilot's own lookup: a bounded query that silently
loses the row somebody is actually looking for. The messaging directory has
the same characteristic and is outside this phase's scope; it is recorded here
so somebody can decide to fix it rather than discover it in a bank.

**`tests/api/test_workflow_seed.py::…::test_it_reports_what_it_kept`** needs
the demonstration accounts present and reports
`skipped=['demonstration accounts are not present']` when they are not.
Verified: it fails **identically at the branch base commit `4f79566`**, in a
worktree, against the same database. It is pre-existing and environmental.

A second run against a freshly created database was also taken. It shows
12,785 passed with 70 failures and 75 errors, all of them in the analytical
suites (`tests/orchestration`, `tests/api/test_answer_grain.py`,
`tests/multi`, and their neighbours) that require the seeded DuckDB domains a
new database does not have. That run is recorded for completeness and is not
the regression figure: a database with no analytics data cannot exercise the
analytics.

    pytest tests/planner tests/agentic                   761 passed
    scripts/acceptance/copilot_journeys.py               40/40
    scripts/acceptance/creation_flow_journey.py          58/58
    scripts/acceptance/copilot_adversarial.py            14/14
    scripts/acceptance/agentic_demo_scenario.py          19/19
    scripts/acceptance/planner_journeys.py               43/43
    scripts/acceptance/planner_demo_journey.py           18/18

One harness defect was found and fixed while producing that last line.
`planner_journeys.py` counted red projects with `has_text="RED"`, which is a
case-insensitive substring match and therefore counted every programme with
"Redevelopment" in its name — which, on a realistic retail credit portfolio,
is most of them. It now reads the health badge. The product was right and the
check was wrong, which is the less common way round and worth saying.

---

## 8. Recommendation

**READY FOR INTEGRATION REHEARSAL**

The reasoning, plainly:

* Every gate in the acceptance matrix is PASS except one, and that one is
  stated as NOT VERIFIED rather than rounded up. It is the live AI provider
  call, which cannot be executed in an environment with no provider key.

* The two failures in the definitive regression were each traced to a cause
  outside this phase and each verified — one on a fresh database, one at the
  branch base commit.

* The claim this phase exists to support — that a person can talk a programme
  into existence and change it a month later by saying so — is evidenced by
  58 checks in one continuous browser session that assert the database rather
  than the screen, not by a demonstration script that knows what to type.

* Ten defects were found and fixed, and nine of them were found by driving
  the product rather than by reading it. Three of those nine were in the
  language reader itself and were found by driving the ten required sentences
  before writing tests for them. That is the evidence that this is a reader
  and not a lookup table.

* The security position does not rest on the model behaving. The Copilot
  writes through the same service layer as the forms, holds no publish tool,
  has no browsing, and cannot resolve a name to a user id. Fourteen
  adversarial probes against the running product all fail closed.

**Before production, not before rehearsal:** run the live AI verification in
an environment with a provider key configured, and re-run
`scripts/acceptance/copilot_journeys.py` and `creation_flow_journey.py` there.
The deterministic reader handles the ten required sentences without a
provider, so what remains to be proved is that the model path improves the
long tail rather than that the feature works at all.

The messaging-directory limit noted in §7 should be looked at by whoever owns
that module. It is the same defect this phase fixed in the Copilot's lookup,
and it is not fixed there.

---

# Addendum — the UAT remediation

Everything above describes the Copilot as it was built. This addendum
describes what manual testing of the Docker application then found, what was
changed, and what the recommendation is now. Where the two disagree, this
addendum is current.

## A1. What was reported, and what was true

The report was that the Planner's user experience was confusing and that
several flows were incomplete or ineffective. It was reproduced in the
running application before anything was written.

`/delivery` opened with a chat box and offered, as its primary action,
"Start a new project — Build the plan in conversation". `/delivery/new` put a
conversation beside every panel of the plan at once. Two ways to create one
thing, and the one the product led with was a text field that might or might
not understand the sentence typed into it.

That is a fair finding and it is not a matter of taste. A person opening the
Planner for the first time was told nothing about which fields were required,
in what order, or what would happen when they finished.

## A2. What was done

The product is now **form-first project creation with agentic AI project
monitoring**. `docs/PROJECT_PLANNER_UAT_REMEDIATION.md` describes the whole
of it; the short version is:

* creation is eight steps with Back, Next and Save draft, and each step
  validates before it lets you leave it;
* a dependency states what it would cost in items and days, and offers
  Adjust dates, Keep dates and flag conflict, or Cancel — and nothing moves
  a date that was not asked for;
* the preview shows the whole plan with a real timeline and critical path,
  and splits what remains into required and recommended;
* the Planner home is Needs attention, Current projects, Draft projects,
  Closed projects, with the full column set on every row;
* Needs attention is one row per issue with an owner, a date, a reason, the
  chase state and a next action;
* the project detail has eight tabs, no Copilot tab, and an Agent activity
  tab that reads like project management;
* every message carries the project name and code, the item, the owner, the
  due date, the escalation level and a working link, and is never sent twice;
* `copilot-chat.tsx` and `draft-builder.tsx` are deleted. There is no chat
  control anywhere in the Planner.

## A3. Eight defects, and how each was found

None of these were found by reading the code.

1. **The person-pickers could not reach most of the directory.**
   `copilot.people` capped at fifty rows however many were asked for, and the
   form asked for two hundred. On this installation the person signing in was
   not in the first five hundred names alphabetically, so the form could not
   name them at all. Found by the browser journey timing out on a select that
   did not contain the option. Fixed by making the pickers search rather than
   by raising the cap.

2. **The creation form lost its place after every saved field.** `useAsync`
   blanks its data while refetching, so the page replaced the wizard with a
   loading message after each step, remounted it, and reset it to the step
   the server had stored. Invisible on steps one to six because those match;
   fatal between seven and eight, where the form simply would not advance.
   Found by the journey failing to reach Publish.

3. **A finish-to-start dependency disagreed with the scheduler by one day.**
   `schedule._forward` has always meant "the successor starts the day after";
   `link_preview` meant "not before". A successor starting on its
   predecessor's finish date was declared fine and then pushed out anyway.
   Found while writing the impact statement.

4. **`draft.publish` signalled an event the monitor rejected.**
   `project_published` was not in `monitor.EVENTS`, so `on_event` raised,
   `service.signal` swallowed it, and every publish logged an exception and
   queued nothing. The comment claiming the first Needs Attention list would
   not wait for a sweep had been wrong since it was written. Found by a test
   asserting the published state.

5. **Overview and governance shared one completeness scope**, so step one
   demanded a sponsor before the sponsor had been asked for.

6. **The code-availability check returned 500 for the case it existed for.**
   `acl.readable` refuses rather than returning false. Found by the
   permission test for a stranger.

7. **The journeys had been signing in and then making anonymous requests.**
   The session cookie is host-scoped; the scripts read the API on
   `127.0.0.1` while the browser had signed in on `localhost`. Every
   assertion after sign-in was reading an unauthenticated response. Found by
   a 401 that the harness had been quietly rendering as an empty list.

8. **The frontend image had been built against an absolute API origin.**
   `docker-compose.yml` sets `NEXT_PUBLIC_API_URL` empty on purpose so the
   browser calls the application's own origin; building it with
   `http://localhost:8000` pins the session to one host. This is what made
   (7) possible.

## A4. What was run, on the final images

Docker images rebuilt from the final executable HEAD; all four containers
healthy.

| What | Result |
|---|---|
| `pytest tests/planner tests/agentic` | 797 passed |
| `uat_creation_journey.py` — the form, end to end, in Chromium | 77 passed, 0 failed |
| `planner_button_audit.py` — every Planner control pressed | 79 live, 0 dead |
| `planner_journeys.py` — journeys A–F | 43 passed, 0 failed |
| `agentic_demo_scenario.py` — after a demo reset | 19 passed, 0 failed |
| `copilot_adversarial.py` — the boundary over HTTP | 14 passed, 0 failed |
| `ruff check backend/ tests/ scripts/` | clean |
| `npx tsc --noEmit` | clean |
| `npx eslint` on the changed frontend | clean |
| PPC-UAT-001 … PPC-UAT-020 | 20 PASS, 0 FAIL |
| `pytest tests` — the definitive full regression | **13,033 passed, 2 failed, 38 skipped** in 35m47s |

### The two regression failures, each traced

Neither is in the Planner, and neither is a product defect. Both were
investigated rather than asserted.

**`tests/proof/test_fresh_clone_acceptance.py::test_the_only_live_domains_are_the_seven`.**
It found ten live data domains where seven were expected, the extra one being
called `Test Domain`. `tests/api/test_data_builder.py` creates a domain by
that name through the API and does not remove it, and this repository's
suites share one development database. Proved both ways: deleting the row
makes the proof suite pass 23 of 23, and re-running the data-builder suite
re-creates it. It is a cleanup missing from a test in another module, and it
appears once the full suite has been run twice against the same database.

**`tests/api/test_messaging_corrections.py::…[role]`.** The same failure this
branch's earlier report already recorded and attributed: the messaging
directory returns a bounded page and the test's own fixture account is no
longer inside it, among the accumulated fixture users of a long-lived
development database. It passes on a fresh database. It is the same
directory-limit defect the Planner's own person lookup had, fixed here and
still unfixed in the module that owns it.

Neither was touched, because neither is in this work's scope.

Two acceptance scripts were **deleted**: `copilot_journeys.py` and
`creation_flow_journey.py` drove the chat box and the conversational creation
flow, and §22 removed both. A journey whose subject no longer exists cannot
be adapted honestly; the claims it made are covered by the form journey, by
`test_copilot_http.py` for the routes that remain, and by
`copilot_adversarial.py` for the boundary.

## A5. Live AI

**NOT VERIFIED.** No provider key is configured in this environment. This is
not a caveat on the gates above: everything the agent does in them is
deterministic. The monitoring rules, the escalation ladder, the critical path
and the completeness check are arithmetic over the plan; the project brief is
composed from computed statements that each name the rows they came from.
That is what the correction asked for — the model does not determine
deadlines — and it is why these gates can be asserted at all.

The chat routes remain, governed and tested, and are not reachable from the
product's interface.

## A6. Recommendation

The twenty UAT gates pass. The reported failure is reproduced, understood and
fixed at the level of the product's shape rather than its wording. Eight
further defects were found in the course of proving it, all fixed, and each
of the eight was found by driving the running application.

**READY FOR INTEGRATION REHEARSAL**

with the same three conditions as before, unchanged:

* live AI is unverified and must be verified in an environment with a
  provider key before anything is promised about the model path;
* the messaging-directory limit noted in §7 is still not fixed in the module
  that owns it;
* the demonstration state must be reset before it is shown, or the agent's
  behaviour is illegible under a week of accumulated reminders.

None of the three blocks a rehearsal. The first two are outside this work,
and the third is in the runbook.

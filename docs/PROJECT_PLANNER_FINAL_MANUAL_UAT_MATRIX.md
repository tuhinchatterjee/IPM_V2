# Project Planner — final manual UAT matrix

**§55.** One row per capability the brief asks about, with how it was
checked and what happened. The status words mean exactly this:

| | |
|---|---|
| **PASS** | somebody did it, through the real product, and the persisted state afterwards was the intended one |
| **FAIL** | it was tried and it did not work |
| **NOT VERIFIED** | it was not exercised, or could not be, on this deployment — stated rather than implied |
| **NOT APPLICABLE** | the capability does not exist in this product, by design |

Nothing here is marked PASS because the code looked right. Every PASS names
the run that produced it, and every one of those runs is a script in
`scripts/acceptance/` that can be pointed at a deployment and re-run.

## Where the evidence comes from

| Run | What it does | Result |
|---|---|---|
| `final_uat_journey.py --pass A --mode CRITICAL` | the whole creation journey through the browser, normal path | **37 of 37** |
| `final_uat_journey.py --pass B --mode CUSTOM` | the same, with a Custom agentic policy and a five-link dependency chain | **43 of 43** |
| `final_uat_pass_c.py` | a plan interrupted, the browser closed, the draft resumed, work spread across three people, a blocked task, a risk, and a workbook round trip | **51 of 51** |
| `final_uat_agentic.py` | the agent's whole loop — watch, detect, remind, not twice, escalate, and tell nobody else | **15 of 15** |
| `final_uat_surfaces.py` | every tab, every control, My Work, search, a phone, and a project that does not exist | **46 of 46** |
| `final_uat_people.py` | the manager, a VIEWER, an outsider, the chat's boundary, two people at once, and nonsense | **38 of 38** |
| `final_uat_health_and_scale.py` | what health means, how fast the screens answer, what the product admits about its AI | **30 of 30** |

**260 checks, 260 passed**, on Docker images built from this branch's HEAD.

## The matrix

### Creating a project (§7–§18)

| # | Capability | How it was checked | Status |
|---|---|---|---|
| 1 | Start a project from the Project Planner home | Pass A/B/C, browser | **PASS** |
| 2 | Name, code, description and objective persist without pressing Save | Pass A/B/C — the draft is read back from the API after typing | **PASS** |
| 3 | A project code already in use is refused on the step that asks for it | Pass A/B — typed `IFRS9-REDEV`, an alert appeared | **PASS** |
| 4 | Sponsor, manager, owner and escalation contact can each be chosen by name | Pass A/B/C — the real picker, by typing a name | **PASS** |
| 5 | A target completion before the start date is refused | Pass A/B — the form refused and said why | **PASS** |
| 6 | Priority and reporting cadence are set and kept | Pass A/B | **PASS** |
| 7 | Milestones can be added, with owner and dates, and persist | Pass A/B (5), Pass C (2) | **PASS** |
| 8 | Tasks can be added under the right milestone, with owner and dates | Pass A/B (16), Pass C (4) | **PASS** |
| 9 | Work can be assigned to several different people | Pass C — three distinct owners, asserted on the published project | **PASS** |
| 10 | Dependencies can be created between milestones | Pass A/B — a five-milestone chain, four links | **PASS** |
| 11 | The impact of a dependency is shown before it is made | Pass A/B — "Show the impact" precedes "Create the dependency" | **PASS** |
| 12 | A circular dependency is refused | Pass B — asserted explicitly | **PASS** |
| 13 | The preview shows the plan before it is published | Pass A/B — name, code, milestones and critical path all on it | **PASS** |
| 14 | Publish creates the project atomically and lands on it | Pass A/B/C | **PASS** |
| 15 | The published project carries every milestone and task | Pass A/B/C — counted against the plan | **PASS** |
| 16 | It appears on the portfolio without a refresh | Pass A/B | **PASS** |

### Saving, leaving and coming back (§14, §50 C)

| # | Capability | How it was checked | Status |
|---|---|---|---|
| 17 | A part-filled plan is saved without being published | Pass C — read back from the API mid-journey | **PASS** |
| 18 | An unfinished plan waits on the home page and says it is not published | Pass C | **PASS** |
| 19 | The draft survives the browser being **closed**, not just navigated away from | Pass C — the whole browser context is discarded, cookies included | **PASS** |
| 20 | Resuming brings back everything typed, including the people named | Pass C | **PASS** |

### The Agentic AI (§9, §24–§30, §43)

| # | Capability | How it was checked | Status |
|---|---|---|---|
| 21 | Four policies are offered and the one chosen is the one stored | Pass A (Critical), Pass B (Custom) | **PASS** |
| 22 | A Custom policy accepts every threshold §28 names and stores what was typed | Pass B — five thresholds, each read back | **PASS** |
| 23 | The agent finds work that is late without being told | `final_uat_agentic.py` | **PASS** |
| 24 | It tells the person responsible, in their own inbox | ditto — read from the owner's own notifications | **PASS** |
| 25 | The message names the project, the item, the date and the reason, and links back | ditto — five separate assertions | **PASS** |
| 26 | Running it again does not send the same thing twice | ditto — suppressed, not resent | **PASS** |
| 27 | An unresolved delay climbs to the escalation contact | ditto — 45 days overdue reached the sponsor | **PASS** |
| 28 | The escalation says why it reached **them** | ditto — "because you sponsor this project" | **PASS** |
| 29 | Somebody with no part in the project is told nothing | ditto — a stranger's inbox stayed empty | **PASS** |
| 30 | Agent Activity records what it did | ditto — three events | **PASS** |
| 31 | All of this works with no AI provider configured | `final_uat_health_and_scale.py` §49 | **PASS** |

### Running a project (§19–§21, §31–§34)

| # | Capability | How it was checked | Status |
|---|---|---|---|
| 32 | A sponsor can read health, progress, people, dates, blockers and risks in one panel | the Executive Summary, sixteen deterministic cells (F-007) | **PASS** |
| 33 | Every tab opens, shows something, and shows nothing a machine wrote | `final_uat_surfaces.py` — eight tabs, checked for `undefined`, `NaN`, `Invalid Date`, `[object Object]` | **PASS** |
| 34 | Every control on every tab can be pressed without breaking the screen | ditto — 41 controls across eight tabs | **PASS** |
| 35 | The Timeline draws the plan rather than a message about one | ditto | **PASS** |
| 36 | My Work shows the signed-in person their own work | ditto | **PASS** |
| 37 | Health is calculated from the project's rows and says why in a sentence | `final_uat_health_and_scale.py` — green with nothing late; amber with one task overdue, and the reason names it | **PASS** |
| 38 | A person can overrule health; they are named and their reason is kept | ditto | **PASS** |
| 39 | The calculation survives underneath an override, and comes back when it is lifted | ditto | **PASS** |
| 40 | A task can be marked blocked, and cannot be blocked without a reason | Pass C, and `tests/planner/test_blocked_needs_a_reason.py` (F-010) | **PASS** |
| 41 | A RAID item can be raised and is shown on the project by its title | Pass C | **PASS** |
| 42 | The manager can report progress and it lands, with their name on it | `final_uat_people.py` §21 | **PASS** |
| 43 | "Needs attention" ranks the most urgent thing first and says when somebody was last chased, in words | `tests/planner/test_attention_order.py` (11 tests) (F-002, F-003) | **PASS** |

### Excel (§35–§37, §46)

| # | Capability | How it was checked | Status |
|---|---|---|---|
| 44 | A project exports to a workbook | Pass C — 15.8 KB, a real `PK`-signed xlsx | **PASS** |
| 45 | The workbook carries the code, the milestones, the tasks and the people | Pass C — four content assertions plus the owner's username | **PASS** |
| 46 | The export can be read straight back in | Pass C | **PASS** |
| 47 | Reading it in changes nothing until somebody commits it | Pass C — the preview names an import id and no project id | **PASS** |
| 48 | The round trip keeps every milestone, task, title and owner | Pass C — four assertions, owners compared by username | **PASS** |
| 49 | A plan template can be downloaded | offered on the Project Planner home; not exercised end to end | **NOT VERIFIED** |

### Who may do what (§22, §40, §47, §52)

| # | Capability | How it was checked | Status |
|---|---|---|---|
| 50 | A VIEWER can open the Project Planner | `final_uat_people.py` | **PASS** |
| 51 | A VIEWER is not offered controls they cannot use | ditto (F-014) | **PASS** |
| 52 | A colleague with no part in a project cannot read it, and is told in a sentence | ditto — established at run time from the participant list | **PASS** |
| 53 | A project they cannot see says so rather than half-drawing itself | ditto — "No project 2970." with a way back | **PASS** |
| 54 | Two people editing the same task do not overwrite each other | ditto — HTTP 409 naming both versions; the frontend sends `expected_version` on every save | **PASS** |
| 55 | An impossible date, an impossible percentage and an invented status are each refused with a sentence | ditto — four adversarial payloads | **PASS** |
| 56 | Naming somebody who does not exist is refused rather than crashing | ditto, and `tests/planner/test_naming_a_real_person.py` (12 tests) (F-013) | **PASS** |
| 57 | Guessing a task id on somebody else's project does not work | ditto — HTTP 403 | **PASS** |
| 58 | A project can be completed, stops being chased, and keeps its work | ditto — the sweep sent nothing; the tasks are still there | **PASS** |
| 59 | Deleting a project | deliberately **not** exercised — this UAT does not test destructive operations against a database holding demo programmes | **NOT VERIFIED** |

### The chat (§23–§25, §52)

| # | Capability | How it was checked | Status |
|---|---|---|---|
| 60 | The project chat answers a question about this project | `final_uat_people.py` | **PASS** |
| 61 | A question about another part of CreditProbe is declined, naming where the answer lives | ditto — an IFRS 9 question, pointed at Ask | **PASS** |
| 62 | It will not fetch another project's work on request | ditto — checked against 44 task titles RET-IFRS9 does not share with the project under test | **PASS** |
| 63 | An instruction hidden inside a message is not obeyed | ditto — no connection string, no passwords, no addresses | **PASS** |

### The product as a whole (§41, §44, §45, §48, §49)

| # | Capability | How it was checked | Status |
|---|---|---|---|
| 64 | Nothing scrolls sideways on a phone | `final_uat_surfaces.py` — `scrollWidth − clientWidth` is 0 at 390px, was 33 (F-012) | **PASS** |
| 65 | A project that does not exist gets a sentence and a 404, not a stack | ditto | **PASS** |
| 66 | The screens a person opens every morning answer quickly, on the biggest project here | `final_uat_health_and_scale.py` — RET-IFRS9, 44 tasks: 0.02–0.04s | **PASS** |
| 67 | The attention list is bounded and every row names its project and what it wants | ditto | **PASS** |
| 68 | The product says truthfully what its AI is | ditto — `ai_provider: not_configured`, said in its own words | **PASS** |
| 69 | **Live AI answering** | no provider key is configured on this deployment | **LIVE AI — NOT VERIFIED** |
| 70 | The browser reports no uncaught error anywhere | every browser run asserts it | **PASS** |

## What is not covered, said plainly

* **Live AI (69).** There is no provider key here. The Planner's watching,
  chasing, escalation and health are arithmetic and were proved without
  one; anything a model would add was not exercised and is not claimed.
* **Deleting a project (59).** Not exercised. This database holds the demo
  programmes, and a UAT that proves deletion works by deleting one of them
  is not a UAT anybody should run.
* **The plan template (49).** The download is offered on the home page and
  was not followed through to a filled-in import.
* **Email.** Reminders are written to the recipient's own notifications,
  which is where they were read from. No mail server was involved and none
  is claimed.

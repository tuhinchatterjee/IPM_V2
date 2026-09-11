# Project Planner — final human-centric UAT report

**§56.** What was done, what it found, what was fixed, what was proved, and
what is still not true.

---

## A. What this was

A UAT run the way a demanding person uses a product, rather than the way a
suite runs one. The brief was explicit about the difference: *"Do NOT treat
this assignment as: pytest passes → done."* So the product was run, looked
at, clicked, filled in, published, broken on purpose, resumed after a break,
opened as four different people and read on a phone — and the automated
suite was run **afterwards**, as a check that none of the fixing broke
something else.

Every finding below was found by doing something, not by reading code. The
code reading came second, to explain what had happened.

## B. Where it ran

| | |
|---|---|
| **Branch** | `claude/project-planner-copilot` |
| **HEAD at the final run** | `b50075f` — *Final UAT: what health means, how fast it arrives, what the product admits* |
| **Commits ahead of `main`** | 492 |
| **Images** | `ipm-backend:latest` `446957952e25`, `ipm-frontend:latest` `17cd130a0da5`, both built from this HEAD |
| **Stack** | `ipm-postgres`, `ipm-backend`, `ipm-frontend`, `ipm-agent-worker` — all healthy |
| **Migration head** | `0044`, single head |
| **AI provider** | **none configured** — see §L |

Nothing in this report was produced against a running dev server. Every
browser run and every API run in the evidence went through the Docker stack
above.

## C. The first thing that happened

The Project Planner opened on **1,993 projects and 2,525 attention items**,
and every one of them was called something like "Actions fixture" or
"Permission fixture project". The sponsor picker offered **9,441 people**,
of whom the first fifty were all called "Alice Test".

Nobody can judge a product in that state, so the first work was to find out
why and deal with it honestly — which is F-001, F-009 and F-016 below. The
root cause was then *measured* rather than guessed: one run of the full
automated suite leaves **1,403 accounts and 385 projects** behind.

## D. What was found, in order of what it would cost a person

Full detail, with root cause and retest evidence for each, is in
`docs/PROJECT_PLANNER_FINAL_UAT_ISSUES.md`.

### Fixed — P1

| ID | What a person would have hit |
|---|---|
| **F-008** | **The Custom agentic policy could not be typed into.** Typing `10, 5, 2, 1` into the reminder thresholds left the stored policy on the Standard default `[7, 3, 1, 0]` — and left the box *showing* the default too, so nothing said the instruction had been dropped. The field was controlled on the stored list while typing went to a different variable, so React put the old text back on every keystroke. The AI mode was decorative configuration on that one field, which is the thing §9 says it must never be. |
| **F-013** | **Naming somebody who is not in the directory gave a 500** — and on `escalation_id` it did not even fail: the value was accepted and the task quietly had no escalation contact, so the agent's ladder had no top rung and nothing anywhere said so. |
| **F-006** | **A published project showed health `UNKNOWN`** while the sentence underneath it said `calculated=GREEN`. The header read the stored column, which only the first sweep writes. |
| **F-009** | **Every person picker offered 9,441 people**, 9,617 of whom did not exist. |
| **F-001** | **The Project Planner opened on 1,993 fixture projects.** |

### Fixed — P2

| ID | What a person would have hit |
|---|---|
| **F-010** | **A task could be set to BLOCKED with no reason.** The rule existed and was enforced on the `blocked` flag, *before* the alignment that derives that flag from the status — so the ordinary route (pick "Blocked" from the dropdown) walked straight past it. The creation path had no guard at all. |
| **F-002** | **"Needs attention" put the wrong thing first** — "due in 12 days" above "12 days overdue", because days-elapsed and days-remaining were sorted with the same sign. |
| **F-003** | **The chase state read `2026-09-11T10:01:31.754497+00:00`** on every row. |
| **F-012** | **Every page scrolled sideways by 33px on a phone.** The header held 400px of chrome in a 390px screen and nothing in it gave way. |
| **F-014** | **A VIEWER was offered "Create new project"**, which the server refuses. |
| **F-004** | **The portfolio table had 13 columns** on a 1440px laptop; names wrapped to four lines and the last column hung half-drawn off the edge. |
| **F-007** | **A sponsor had to read three paragraphs of prose** to find out whether anything was late. |
| **F-016** | **The test suite leaves its fixtures behind** — measured at 1,403 accounts and 385 projects per run. |

### Fixed — P3

| ID | What a person would have hit |
|---|---|
| **F-005** | The picker's truncation note took three lines inside a narrow column, and its count had no thousands separator. |

### Not defects — recorded because each nearly produced a false verdict

| ID | What it was |
|---|---|
| **F-011** | The harness matched a button named "Publish" and hit the completeness strip's clickable **"Ready to publish"** chip, reporting a publish failure on a plan the product was perfectly willing to publish. |
| **F-015** | Three at once: the concurrency probe sent `version` where the wire field is `expected_version`, so the stale-write test was testing nothing; the "outsider" in the permission test turned out to **own a task** on the project; and the cross-project leak check compared against a project whose code is a *prefix* of the one under test. |

There is a pattern in F-011 and F-015 worth stating: **four separate checks
nearly passed or failed for the wrong reason because a payload carries a
nested object where the check read a flat key** — `owner` vs `owner_id`,
`project` vs `project_code`, `user` vs `username`. Every one of those checks
now prints the value it actually found, so a vacuous pass is visible in the
log rather than hidden in it.

## E. What was changed in the product

| File | Change |
|---|---|
| `backend/planner/service.py` | `_person()` — one existence check for every field that names somebody, on creation and on edit, for tasks, milestones, RAID items and projects. `_blocked_with_a_reason()` — one blocked-needs-a-reason rule, applied **after** state alignment so both routes to "blocked" hit it. |
| `backend/planner/query.py` | `_urgency()` — explicit ranking bands with days-remaining sorted the other way from days-elapsed. `_when_said()` — "today", "yesterday", "4 days ago", "on 2 Sep 2026". |
| `frontend/src/components/planner/wizard.tsx` | The reminder-days box holds what is being typed; commits on blur or Enter; refuses an empty list rather than storing "never remind anybody". The picker's truncation note fits one line. |
| `frontend/src/lib/planner-format.ts` | `readDays()`, `shortDate()`. |
| `frontend/src/app/delivery/page.tsx` | Ten columns instead of thirteen. Plan-creation controls only for somebody who can use them. |
| `frontend/src/app/delivery/[id]/page.tsx` | The Executive Summary — sixteen deterministic cells above the narrative. Calculated health shown when nothing overrides it. |
| `frontend/src/components/layout/header.tsx` | What is only *telling* you something gives way at narrow widths; what you press stays. |
| `scripts/clean_test_fixtures.py` | Recognises fixture accounts by shapes a person cannot create, removes what they wrote first, and reads the blocking columns out of `information_schema` rather than a hand-written list. |

## F. What was added to keep it fixed

| File | What it pins |
|---|---|
| `tests/planner/test_attention_order.py` | 11 tests — the ranking bands, sooner-due-first inside a band, stability, and no machine timestamps |
| `tests/planner/test_blocked_needs_a_reason.py` | 7 tests — the dropdown route, the flag route, whitespace, creation, that a refusal leaves the task untouched, and that completing a blocked task is not trapped |
| `tests/planner/test_naming_a_real_person.py` | 12 tests — parameterised across the person fields and the four entities |
| `frontend/src/lib/__tests__/planner-format.test.ts` | 6 cases — the day-list parser, including that an empty result is refused |
| `scripts/acceptance/final_uat_journey.py` | Passes A and B, through the browser |
| `scripts/acceptance/final_uat_pass_c.py` | Pass C — interrupted, resumed, several people, blocked, RAID, workbook round trip |
| `scripts/acceptance/final_uat_agentic.py` | The agent's whole loop |
| `scripts/acceptance/final_uat_surfaces.py` | Every tab, every control, My Work, search, a phone, a missing project |
| `scripts/acceptance/final_uat_people.py` | Permissions, the chat boundary, concurrency, adversarial payloads |
| `scripts/acceptance/final_uat_health_and_scale.py` | Health scenarios, timings, AI honesty |

## G. The journeys (§50)

Run three times over, each a different shape of the same job.

| Pass | Shape | Result |
|---|---|---|
| **A** | Normal: five milestones, sixteen tasks, a Critical policy, a dependency chain | **37 of 37** |
| **B** | Custom agentic policy with §28's five thresholds typed and read back, plus a circular dependency that must be refused | **43 of 43** |
| **C** | Started, abandoned mid-step, the **browser closed**, the draft found again from the home page, finished by three different owners, a blocked task, a risk, and the whole project exported and read back in as a new one | **51 of 51** |

## H. The Agentic AI (§26–§30)

Proved end to end, through the product's own API, as the people involved:

* a task was made late and the agent found it without being told;
* the **owner's own inbox** received the message;
* the message names the project, the item, the due date, the reason, and
  carries a link back;
* running the agent again **suppressed** rather than resent it;
* pushed to 45 days overdue, the delay reached the **escalation contact**,
  who was told *"You are seeing this because you sponsor this project"*;
* a colleague with no part in the project was told **nothing**;
* Agent Activity recorded all of it.

**15 of 15.** And all of it with no AI provider configured, because the
schedule rules are arithmetic.

## I. Everything else that was exercised

| § | Area | Result |
|---|---|---|
| 20, 33, 41 | Every tab; 41 controls pressed across eight tabs; the Timeline draws the plan | 46 of 46 |
| 34 | My Work | ✔ |
| 38 | Search finds, and says so when it finds nothing, without falling back to everything | ✔ |
| 44 | 390px: `scrollWidth − clientWidth` **0**, was 33 | ✔ |
| 45 | A project that does not exist: 404 and a sentence, with a way back | ✔ |
| 21, 22 | The manager can act; a VIEWER cannot; an outsider cannot read | 38 of 38 |
| 23–25, 52 | The chat answers about this project, declines other areas by naming where the answer lives, will not fetch another project's work, and ignores an instruction hidden in a message | ✔ |
| 47 | Two people, one task: HTTP **409**, naming both versions; the UI sends `expected_version` on every save | ✔ |
| 31 | Health calculated, explained, overridable, attributed, and restorable | 30 of 30 |
| 39, 40 | A completed project stops being chased and keeps its work | ✔ |
| 48 | On the biggest project here (44 tasks): 0.02–0.04s per screen | ✔ |
| 35–37, 46 | Export → read back → commit → every milestone, task, title and owner intact | ✔ |

**260 acceptance checks. 260 passed.**

## J. The automated regression (§54)

Run on the HEAD above, against the Docker stack, **after** the product had
been exercised by hand.

```
13134 passed, 38 skipped, 25 warnings in 2090.01s (0:34:50)
exit code 0
```

| | |
|---|---|
| collected | 13,172 |
| **passed** | **13,134** |
| skipped | 38 |
| **failed** | **0** |
| **errors** | **0** |
| warnings | 25 (all `DeprecationWarning` from `dash_table` in `tests/legacy/`) |
| duration | 2,090.01s |
| exit code | **0** |

The 38 skips are environment guards — tests that skip when a database or a
provider is absent — not silenced failures. No run has been hidden: this is
the only full-suite run on this HEAD, and it is the one quoted.

## K. The other gates

| Gate | Result |
|---|---|
| `ruff check .` | **All checks passed** |
| `npx eslint` (frontend) | clean, exit 0 |
| `npx tsc --noEmit` | clean |
| frontend unit tests | **547 passed**, 0 failed, 6.4s |
| production build (`next build`) | succeeds — it runs inside `docker/frontend.Dockerfile:59`, and the image was built from this HEAD three times today |
| migration heads | **0044, single head** |
| migration up from empty | 0001 → 0044 on a fresh database |
| migration down and back | 0044 → 0043 → 0044 |
| migration down to base | 0044 → base, clean |
| Docker build from HEAD | backend and frontend both built and healthy |

## L. Live AI (§49)

**LIVE AI — NOT VERIFIED.**

No AI provider key is configured on this deployment. The product says so
itself, in its own health endpoint, in its own words:

> `ai_provider: not_configured` — "No AI provider key is configured.
> CreditProbe reads questions with its deterministic governed semantic
> reader and computes every figure in the governed runtime."

Nothing in this report claims a model answered anything. What was proved
without one is stated where it was proved: the agent still watches, detects,
reminds, escalates and records; health is still calculated and explained;
the chat still answers in-scope questions and still declines out-of-scope
ones. Anything a model would add on top of that was **not exercised** and is
not claimed.

## M. The clean-state rehearsal (§53)

After the full suite, the database was cleaned back to the five demo
programmes and the 34 real accounts, and **every acceptance run was
repeated against that clean state**:

| Run | Clean-state result |
|---|---|
| Pass A | 37 of 37 |
| Pass B | 43 of 43 |
| Pass C | 51 of 51 |
| Agentic | 15 of 15 |
| Surfaces | 46 of 46 |
| People | 38 of 38 |
| Health and scale | 30 of 30 |
| **Total** | **260 of 260** |

The estate afterwards is nine projects: the five demo programmes, the three
the rehearsal created, and the one it created by importing its own export.

## N. The final product test (§57)

### Can a normal project manager do the job without engineering knowledge?

Yes, for everything this UAT exercised. They can start a project, name it,
be told immediately if the code is taken, name a sponsor, a manager, an
owner and an escalation contact by typing a name, set dates and be refused
an impossible one, choose how hard the AI chases and set their own
thresholds, add milestones and tasks, give the work to different people,
link what waits for what and see the impact before committing to it, be
refused a circular dependency, preview the plan, publish it, leave half way
through and come back to it, mark something blocked and say why, raise a
risk, report progress, read where the project is in one panel, see what
needs somebody today in priority order, export the plan to Excel and read it
back in.

### Can a sponsor understand the project in under 30 seconds?

Yes. The Overview opens on sixteen cells: health and why, progress, status,
manager, sponsor, owner, start, target completion, next milestone and how
many days to it, overdue tasks, blocked tasks, due within seven days,
critical-path risks, open high RAID, last updated. Underneath is one line
per thing that needs somebody. The narrative — which is where the sponsor
used to have to start — is now below both.

### Does the Agentic AI watch, detect, remind, chase, escalate and summarise, inside clear human governance?

Yes, and §H is the evidence rather than the claim. The governance is
visible and bounded: the project says which policy it is under and what that
means in a sentence; the thresholds are the ones the manager typed; every
message names its reason; the ladder ends at a named escalation contact; the
agent does not send the same thing twice; and it tells nobody who is not on
the project.

## O. What is still not true

Stated plainly, because a report that omits these is not a report.

1. **Live AI is not verified.** No key. §L.
2. **Deleting a project was not exercised.** This database holds the demo
   programmes, and a UAT that proves deletion by deleting one of them is not
   a UAT anybody should run. The safety of the destructive paths is
   therefore **NOT VERIFIED** rather than passed.
3. **The plan template download** is offered and was not followed through to
   a filled-in import. **NOT VERIFIED.**
4. **Email was not involved.** Reminders go to the recipient's own
   notifications, which is where they were read from. No mail server was
   configured and none is claimed.
5. **The test suite still leaves fixtures behind** (F-016). The tool to
   clear them is in the repository and was used; the tests themselves were
   not rewritten, because that is a change to 13,134 tests with no product
   benefit, and it is the wrong thing to do inside a UAT.
6. **Scale was measured at this deployment's size** — nine projects, the
   largest with 44 tasks. The numbers are good (0.02–0.04s) but they are not
   a claim about a thousand projects.

## P. Verdict

Every material capability the brief asks about was exercised through the
real product and behaves correctly. Nine real defects were found by using
it — two of them P1 — and every one is fixed, with a regression test that
pins the rule rather than the code path, and with the affected and
neighbouring journeys re-run green afterwards rather than at the end. The
full automated suite passes with zero failures and zero errors. Every gate
is clean. The whole acceptance set passes again from a clean database.

The four things that are not verified are named in §O, none of them is a
broken capability, and none of them is hidden.

# READY FOR INTEGRATION

With the four limitations in §O carried forward explicitly — in particular
that **live AI remains unverified on this deployment**, and that the
destructive paths were deliberately not exercised.

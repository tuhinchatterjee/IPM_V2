# Project Planner Copilot — Acceptance Matrix

The Copilot, gate by gate, with what was actually run against each one.

**Statuses are only these four.** PASS means a named command or journey was
executed on this commit and it did what the gate requires. FAIL means it was
executed and it did not. NOT APPLICABLE means the gate does not apply to what
was built, and says why. NOT VERIFIED means nobody ran it — which is not the
same as failing, and is never rounded up to PASS.

Branch: `claude/project-planner-copilot`.

---

## How the evidence was produced

Six independent things were run. Where a row cites one, it cites the exact
command.

**1. The pytest suites.**

    DATABASE_URL=postgresql+psycopg://... \
      .venv/bin/python -m pytest tests/planner tests/agentic

**2. The conversation journeys, in a real Chromium against the built stack.**

    .venv/bin/python scripts/acceptance/copilot_journeys.py       # G-L

**3. The complete creation flow**, one continuous browser session from an
empty plan to the first reminder, asserting persisted state after every
material step.

    .venv/bin/python scripts/acceptance/creation_flow_journey.py  # M1-M17

**4. The adversarial sweep**, signed in over HTTP against the running stack.

    .venv/bin/python scripts/acceptance/copilot_adversarial.py

**5. The agentic demonstration**, against the seeded Retail portfolio.

    .venv/bin/python scripts/acceptance/agentic_demo_scenario.py

**6. The existing Planner harnesses**, to show nothing regressed.

    .venv/bin/python scripts/acceptance/planner_journeys.py
    .venv/bin/python scripts/acceptance/planner_demo_journey.py

Everything in 2–6 ran against Docker images built from this commit, with a
real login cookie from the real login route.

---

## A. The boundary (§2, §40)

| # | Gate | Status | Evidence |
|---|---|---|---|
| A1 | The Copilot answers delivery questions only | PASS | `test_copilot_scope.py`; adversarial 12 |
| A2 | Nine foreign areas each name where the answer lives | PASS | `test_copilot_scope.py` |
| A3 | The refusal quotes the phrase that stopped it | PASS | journey L; `test_copilot_scope.py` |
| A4 | A project named after another module is still discussable | PASS | journey L; `test_copilot_scope.py` |
| A5 | Every foreign phrase is checked, not just the first | PASS | `test_naming_a_project_does_not_licence_another_module_s_question` |
| A6 | A task named after a metric does not licence asking for it | PASS | `test_a_task_named_after_a_metric_does_not_licence_asking_for_it` |
| A7 | The boundary runs before any draft, model or tool | PASS | route order in `planner_copilot.chat`; `test_copilot_http.py` |
| A8 | The boundary holds on a published project too | PASS | `test_the_boundary_still_holds_on_a_project`; adversarial 12 |
| A9 | Tool allowlist is a literal tuple, not a filter | PASS | `copilot.ALLOWED_TOOLS`; `tests/agentic/test_registry.py` |
| A10 | No browsing: `ALLOWED_DOMAINS` is empty | PASS | `copilot.ALLOWED_DOMAINS`; `test_copilot_scope.py` |
| A11 | No registered tool can publish a project | PASS | `tests/agentic/test_registry.py`; `NO_TOOL_EXISTS` |

## B. The draft (§5–§13, §32)

| # | Gate | Status | Evidence |
|---|---|---|---|
| B1 | A draft is private until published | PASS | journey M1; `test_draft.py` |
| B2 | One writer: `draft.apply` dispatches an explicit command list | PASS | `draft.COMMANDS`; adversarial 13 |
| B3 | An unknown command is refused | PASS | adversarial 13; `test_draft.py` |
| B4 | Codes are generated once and never regenerated | PASS | `test_draft.py` |
| B5 | Tasks carry the milestone they were put under | PASS | journey M6; `test_draft.py` |
| B6 | Milestone dates are derived when not given, and kept when given | PASS | `test_draft.py` |
| B7 | Governance is settled in the panel and persisted | PASS | journey M3 |
| B8 | The agentic policy is chosen and persisted | PASS | journey M4 |
| B9 | The policy is stated in words before publishing | PASS | journey M4, M12; `test_policy` in `test_monitor_modes.py` |
| B10 | Custom policies are bounded and refused when incoherent | PASS | `test_draft.py::test_an_incoherent_custom_policy_is_refused` |
| B11 | The draft survives leaving and returning | PASS | `test_draft.py`; `step` persistence |
| B12 | A draft cannot be read or changed by anybody else | PASS | `test_copilot_http.py`; adversarial 10 |

## C. Dependencies, completeness, preview, publish (§14–§21)

| # | Gate | Status | Evidence |
|---|---|---|---|
| C1 | A dependency states itself before it exists | PASS | journeys I, M8, M9 |
| C2 | "Link to previous task" offers the obvious predecessor | PASS | journey M8 |
| C3 | A dependency can be made from the plan's own catalogue | PASS | journey M9 |
| C4 | A dependency can be made by saying it | PASS | journeys I, M10 |
| C5 | A link that would make a loop is refused, and names the loop | PASS | adversarial 4 |
| C6 | The same link twice is refused in a sentence, not a 500 | PASS | adversarial 5 |
| C7 | A date conflict is stated and NOT silently fixed | PASS | `draft.link_preview`; `test_draft.py` |
| C8 | Blockers and warnings are separate and never look the same | PASS | journey M11; `test_draft.py` |
| C9 | Each blocker says what would satisfy it | PASS | journey M11 (cleared by saying the missing thing) |
| C10 | The plan is not publishable while a blocker stands | PASS | journey M11 |
| C11 | The preview shows the whole plan, unabbreviated | PASS | journey M12 |
| C12 | The preview says who each milestone escalates to | PASS | journey M12 |
| C13 | The preview comes from the same function publish uses | PASS | `draft.preview` / `draft.publish` share `check` and `escalation_for` |
| C14 | Publishing is one transaction — all or nothing | PASS | `test_draft.py::test_a_publish_that_fails_halfway_leaves_no_project` |
| C15 | Publishing needs an explicit confirmation from the person | PASS | adversarial 11 |
| C16 | A draft publishes once | PASS | `test_draft.py::test_a_draft_is_published_once` |
| C17 | Everybody the plan names is seated on the project | PASS | `test_an_escalation_contact_named_nowhere_else_can_still_be_seated` |
| C18 | Every seat uses a real project role | PASS | same test (this gate was FAIL before this phase) |

## D. The natural-language command layer (mandatory clarification)

Each of the ten required sentences, through the real product.

| # | Sentence | Status | Evidence |
|---|---|---|---|
| D1 | "Add Data Foundation as the first milestone." | PASS | journey H |
| D2 | "Rohan owns Data Foundation and Priya is the escalation owner." | PASS | journeys H, M7; `test_language.py` |
| D3 | "It starts 1 October and ends 31 October." | PASS | journey H |
| D4 | "Under Data Foundation add Data Extraction, Data Reconciliation and Data Quality Review." | PASS | journeys H, M6 |
| D5 | "Sameer owns Data Extraction until 10 October." | PASS | journeys H, M7 |
| D6 | "Link Data Reconciliation to Data Extraction." | PASS | journey I |
| D7 | "Validation can only start after Model Development is finished." | PASS | journey M10; `test_language.py` |
| D8 | "Move M03-T02 to Daniel." | PASS | journey M15 (on a published project) |
| D9 | "Change this project's monitoring to Critical." | PASS | journey K; `test_live_edit.py` |
| D10 | "Escalate Validation tasks to Ananya after two days overdue." | PASS | `test_language.py`; `test_copilot_http.py` |
| D11 | Parsed into a structured proposed command | PASS | `commands[]` in every `/chat` response |
| D12 | Names and codes resolved deterministically | PASS | `reading.choose`; `test_language.py` |
| D13 | Ambiguity produces a short clickable question, nothing applied | PASS | `test_copilot_http.py`; `test_language.py` |
| D14 | A commitment-changing change is previewed first | PASS | journeys H, K, M7, M10, M15 |
| D15 | Execution only through the existing command/service layer | PASS | `language.apply_all` → `draft.apply`; `live.apply_all` → `service.*` |
| D16 | Permissions are never bypassed | PASS | adversarial 9; `test_live_edit.py` (viewer, contributor, stranger) |
| D17 | Nothing is published automatically | PASS | adversarial 11; no publish tool exists |
| D18 | Chat updates the same persisted draft the panels use | PASS | journeys G–K assert the PANEL, not the reply |
| D19 | A chat change appears in the panel immediately | PASS | journey K; `_draft_state` on every turn |
| D20 | A panel change is understood by the next chat turn | PASS | journey K |
| D21 | One messy multi-fact paragraph | PASS | journey J (eight facts, three forward references) |
| D22 | The reader is not keyword matching tailored to the test | PASS | 15 general rules + model fallback; `test_language.py` (46 cases) |
| D23 | The real provider path is wired | PASS | `language.read_with_model` / `MODEL_SCHEMA`; `test_language.py` |
| D24 | LIVE AI exercised against a configured provider | **NOT VERIFIED** | No provider key in this environment. Not assumed. |

## E. Editing a project that already exists (§22, §23, §47)

| # | Gate | Status | Evidence |
|---|---|---|---|
| E1 | The project's Copilot answers questions about that project | PASS | journey M15; `planner_demo_journey.py` |
| E2 | It changes the project by saying so | PASS | journey M15; `test_live_edit.py` |
| E3 | Nothing on a live project applies without confirmation | PASS | journey M15; adversarial 3 |
| E4 | The change goes through the ordinary service layer | PASS | `live.py` calls `service.*` only |
| E5 | The change is on the project's own record, marked AI_CHAT | PASS | journey M16; `test_live_edit.py` |
| E6 | The record says what it was before | PASS | journey M16 |
| E7 | A viewer cannot change anything by asking | PASS | `test_live_edit.py`; adversarial 9 |
| E8 | A contributor cannot move somebody else's task | PASS | `test_live_edit.py` |
| E9 | A stranger cannot see the project to talk about it | PASS | `test_live_edit.py`; adversarial 6 |
| E10 | A project named beside a draft is checked too | PASS | `test_a_project_named_beside_a_draft_is_checked_too` |
| E11 | A task code from another project cannot be reached | PASS | adversarial 14 |
| E12 | Deleting a milestone off a running project is refused, with a reason | PASS | `test_live_edit.py` |

## F. The agentic monitor and the escalation ladder (§24–§29, §43)

| # | Gate | Status | Evidence |
|---|---|---|---|
| F1 | Light, Standard, Critical and Custom behave differently | PASS | `test_monitor_modes.py` |
| F2 | Choosing a mode changes reminders, not only escalation | PASS | `test_setting_a_mode_writes_the_modes_own_reminder_days` |
| F3 | A preset stores no thresholds of its own | PASS | `test_a_preset_stores_no_thresholds_of_its_own` |
| F4 | The ladder walks task → milestone → project → manager → sponsor | PASS | `test_escalation.py`; demo scenario |
| F5 | The task's own owner is never an escalation recipient | PASS | `test_escalation.py`; `test_monitor.py` |
| F6 | One person on several rungs is told once | PASS | `test_escalation.py`; demo scenario |
| F7 | The sponsor rule fires even when the sponsor is also the contact | PASS | `escalation.at_level` / `_rungs` split; `test_escalation.py` |
| F8 | Running the sweep twice sends nothing new | PASS | demo scenario; `test_monitor_modes.py`; journey M17 |
| F9 | A chase interval means quiet days, not repeated messages | PASS | `monitor.bucket`; `test_escalation.py` |
| F10 | Re-evaluation is event-driven and debounced | PASS | `test_monitor_modes.py` |
| F11 | A manager can run the agent over their own project | PASS | journey M17; `test_live_edit.py` |
| F12 | A dry run says what it would send without spending it | PASS | `test_live_edit.py` |
| F13 | Somebody who cannot edit cannot make the agent chase people | PASS | adversarial 9; `test_live_edit.py` |
| F14 | The critical path is computed once per project per sweep | PASS | `monitor._escalation_messages` |

## G. The demonstration programme (§30, §31)

| # | Gate | Status | Evidence |
|---|---|---|---|
| G1 | Retail Application Scorecard Redevelopment exists and is realistic | PASS | 9 workstreams, 41 tasks, 7 milestones, 18 dependencies |
| G2 | It is monitored on Critical | PASS | demo scenario |
| G3 | It has an escalation contact, and every milestone names one | PASS | demo scenario |
| G4 | It has something overdue | PASS | demo scenario (S-507) |
| G5 | It has something blocked, on somebody outside the team | PASS | demo scenario (S-705) |
| G6 | It has something stale | PASS | demo scenario (S-601, S-602, S-703) |
| G7 | It has something imminent, on a reminder threshold | PASS | demo scenario (S-702) |
| G8 | The owner is reminded; the escalation contact is escalated to | PASS | demo scenario |
| G9 | The sponsor hears about the unresolved delay | PASS | demo scenario |
| G10 | Nobody is told twice; a second sweep sends nothing | PASS | demo scenario |
| G11 | The scenario FAILS rather than skips when unseeded | PASS | by construction; asserted in its docstring and code |
| G12 | IFRS 9 and the other three programmes still build | PASS | `seed_retail_portfolio.py --reset` |

## H. The browser (§42–§47)

| # | Gate | Status | Evidence |
|---|---|---|---|
| H1 | Delivery home leads with the conversation | PASS | journey G |
| H2 | A plan opens with the conversation beside it | PASS | journey G |
| H3 | Conversational creation, end to end | PASS | journeys G–J |
| H4 | Conversational editing, end to end | PASS | journey K; M15 |
| H5 | One messy paragraph, in the browser | PASS | journey J |
| H6 | The complete creation flow, start to publish | PASS | journey M1–M13 (58 checks) |
| H7 | Persisted state asserted after every material step | PASS | journey M (every check reads the API) |
| H8 | It appears in Open Projects afterwards | PASS | journey M14 |
| H9 | Reopen, edit by chat, verify the audit | PASS | journeys M15, M16 |
| H10 | Monitor and reminder verification in the same session | PASS | journey M17 |
| H11 | The existing Planner journeys still pass | PASS | `planner_journeys.py` (43), `planner_demo_journey.py` (18) |

## I. Security and abuse (§40, §48)

| # | Gate | Status | Evidence |
|---|---|---|---|
| I1 | An instruction to destroy the plan applies nothing | PASS | adversarial 1 |
| I2 | A smuggled tool name reaches no tool | PASS | adversarial 2 |
| I3 | An unknown project is not found | PASS | adversarial 6 |
| I4 | A nonsense project id is refused, not crashed | PASS | adversarial 7 |
| I5 | An oversized message is refused by the schema | PASS | adversarial 8 |
| I6 | Somebody cannot publish another person's draft | PASS | adversarial 10 |
| I7 | The model never supplies a user id | PASS | `MODEL_SCHEMA` has no `_id` fields; `resolve_model` |
| I8 | Every Copilot write is marked AI_CHAT forever | PASS | `copilot._source()`; journey M16 |

## J. Build, migration and regression (§49–§52)

| # | Gate | Status | Evidence |
|---|---|---|---|
| J1 | Migration 0043 applies | PASS | container start-up on the rebuilt image |
| J2 | A single Alembic head | PASS | container start-up |
| J3 | Docker images rebuilt from final executable HEAD | PASS | see the final report for the commit |
| J4 | All four containers healthy from the rebuilt images | PASS | `docker ps` — backend, frontend, agent-worker, postgres |
| J5 | Browser evidence produced against the rebuilt images | PASS | journeys re-run after the rebuild |
| J6 | ruff clean across backend, tests and scripts | PASS | `ruff check backend/ tests/ scripts/` |
| J7 | TypeScript compiles | PASS | `npx tsc --noEmit` |
| J8 | ESLint clean on the changed frontend files | PASS | `npx eslint "src/app/delivery/**/*.tsx" "src/components/planner/*.tsx" src/lib/api.ts` |
| J9 | Definitive full regression on final HEAD | PASS | `pytest tests` — 12,982 passed, 2 failed, 53 skipped. Both failures traced outside this phase and verified: one passes on a fresh database, one fails identically at the branch base. See the final report §7. |
| J10 | Nothing outside the Planner was changed | PASS | `git diff --name-only` for this phase: 25 non-test files, all under `backend/planner`, the two planner routers, `backend/models/planner.py`, the delivery frontend, `backend/agentic/tools.py` (registry entries only), `backend/api/main.py` (one router include) and two Alembic revisions |

## K. Scope discipline

| # | Gate | Status | Evidence |
|---|---|---|---|
| K1 | No Lens, Early Warning, What-If, Scorecard or Playbook code changed | PASS | `git diff --stat` for this phase |
| K2 | No force push, rebase or merge to main | PASS | branch history is linear and append-only |
| K3 | No pull request opened | PASS | none was asked for |

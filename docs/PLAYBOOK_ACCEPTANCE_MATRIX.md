# Playbook — Acceptance Matrix

The Committee Pack Intelligence System, gate by gate, with what was actually
run against each one.

**Statuses are only these four.** PASS means a named command or journey was
executed on this commit and it did what the gate requires. FAIL means it was
executed and it did not. NOT APPLICABLE means the gate does not apply to what
was built, and says why. NOT VERIFIED means nobody ran it — which is not the
same as failing, and is never rounded up to PASS.

Commit: `9a70f9a` on `claude/playbook-committee-intelligence`.

---

## How the evidence was produced

Five independent things were run. Where a row cites one, it cites the exact
command.

**1. The pytest suite.**

    .venv/bin/python -m pytest tests/playbook

261 tests across 14 files. These prove the rules — the service layer, access,
the state machine, readiness, snapshots, materiality, import, export,
findings, governance, the demo seed, and the security suite.

**2. The three journey harnesses**, in `scripts/playbook_journeys/`. These
prove the product runs. Nothing in them uses a fixture, a mock or the ORM:
every step is an HTTP request over a socket to a real uvicorn process with a
real session cookie from the real login route, or a real Chromium driving the
built Next.js application.

    .venv/bin/python scripts/playbook_journeys/api_journeys.py       # A-J
    .venv/bin/python scripts/playbook_journeys/followup_journeys.py  # K-O
    CHROMIUM_PATH=... .venv/bin/python \
      scripts/playbook_journeys/browser_journeys.py                  # P-T

**3. The frontend suite.**

    cd frontend && npx tsc --noEmit && npx eslint && npm test

520 tests, 46 suites.

**4. The full platform regression.**

    .venv/bin/python -m pytest tests/

Run on this commit: 12,328 passed, 35 skipped, 0 failed, exit code 0, in 19m 22s.

**5. The containers.** Everything in 1, 2 and 4 was run against the stack as
separate processes. The journeys were then run a second time against
`docker compose up`, from an empty database volume, because the image is what
a client installs and it is not the same environment.

    docker compose up -d           # postgres, backend, agent-worker, frontend
    docker exec ipm-backend python scripts/seed_playbook_committees.py
    CREDITPROBE_API=... api_journeys.py && followup_journeys.py
    CREDITPROBE_APP=... browser_journeys.py

Two defects came out of that run and out of nothing else, both recorded in
"What FAILED" below.

The environment these were run in:

| | |
|---|---|
| Backend | uvicorn on `127.0.0.1:8000`, the port the frontend build expects |
| Frontend | `next build` then `next start -p 3000` — the port the backend's CORS list names |
| Database | PostgreSQL 16, Alembic head `0039` |
| Demo data | `scripts/seed_playbook_committees.py --reset` — three committees, six packs |
| Browser | Chromium 1194 via Playwright |
| AI provider | **none configured** — `get_provider().configured` is `False`, name `'none'` |
| Containers | `docker compose up` from an empty `pgdata` volume: postgres, backend, agent-worker and frontend, all reaching healthy; bootstrap performed 9 steps and skipped 3, and all 15 readiness checks passed |

That last line governs every AI row below. There is no API key in this
environment, so no row that would require a live model call is marked PASS.

---

## PB-PRODUCT — is this a product, or a screen over a table?

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-PRODUCT-01 | A member opens the Playbook and sees the committees they sit on, with the pack each is preparing | PASS | Journey P. Three committees render in Chromium after a real sign-in |
| PB-PRODUCT-02 | A committee page carries its terms of reference, cadence, participants and every pack it has produced | PASS | Journey Q; `GET /committees/{id}` returns purpose, cadence, members, packs |
| PB-PRODUCT-03 | A pack reads as a pack — sections, figures, commentary, findings — not as a form | PASS | Journey B: 4 sections, 12 blocks, 8 calculated figures. Journey R reads them on screen |
| PB-PRODUCT-04 | A pack can be created for the next cycle from a committee's template | PASS | `/playbook/packs/new`; `tests/playbook/test_lifecycle.py` |
| PB-PRODUCT-05 | Findings are answered, reopened, or dismissed with a reason — not merely displayed | PASS | Journey E: answered, reopened, and a dismissal with no reason refused (422) |
| PB-PRODUCT-06 | Decisions are framed before the meeting and their outcome recorded after it | PASS | Journey K: raised DRAFT, decided APPROVED with conditions, `decided_at` and `decided_by` stored |
| PB-PRODUCT-07 | Actions leave the meeting with an owner and a date, and close on evidence | PASS | Journey L: owner 3, due 2026-10-15; closing with empty evidence refused (422); closed on evidence |
| PB-PRODUCT-08 | The pack moves through its states, and the transitions are the ones the vocabulary allows | PASS | `test_lifecycle.py`; `PACK_TRANSITIONS` in `service.py` |
| PB-PRODUCT-09 | Every surface named in the mandate exists as a page a person can reach | PASS | 5 routes built and curated in `docs/FINAL_FEATURE_VERIFICATION_MATRIX.md`; `tests/docs/test_feature_matrix.py` |
| PB-PRODUCT-10 | No API without a UI, and no UI without an API | PASS | 43 paths / 50 operations under `/api/v1/playbook`, all reachable from the five pages |

## PB-DATA — the numbers

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-DATA-01 | Every figure is a governed metric calculation, not a number typed into a component | PASS | Journey C: `retail.default_rate`, period `2025-01`, value `6.88%`, formula hash `5b5645d3f2ef…`, dataset `retail_behavioral_scorecard_monthly_validation` |
| PB-DATA-02 | Every figure carries its working: metric version, formula hash, dataset, dataset version, numerator, denominator, rows considered, run id | PASS | Journey C; the figure payload carries all nine |
| PB-DATA-03 | The five states of "no number" are distinguished and never collapse to zero | PASS | `snapshots.py`: OK / NO_DATA / PERIOD_MISSING / NOT_MATURED / CALCULATION_FAILED / NOT_AUTHORISED. `test_lifecycle.py` covers each |
| PB-DATA-04 | A missing or immature denominator never appears as a client-facing 0.0% | PASS | Journey C and R assert it on the wire and on screen |
| PB-DATA-05 | An approved pack shows the figures the committee was given, not a recalculation | PASS | `test_export.py::test_an_export_shows_the_frozen_figures_and_does_not_recalculate` |
| PB-DATA-06 | Readiness is a gate with named checks and blocking reasons, not a badge | PASS | Journey D: 81%, 8 named checks, each with its own reasons |
| PB-DATA-07 | A movement is read in the direction the metric cares about | PASS | Journey G: a rise in `application_bad_rate` is `better: false` |
| PB-DATA-08 | A change too small to see at the metric's own precision is not drawn as a movement | PASS | Fixed this phase. `test_governance.py` (4 tests); `playbook-format.test.ts` (2 tests) |
| PB-DATA-09 | Materiality reads the real values, not the printed ones | PASS | `test_governance.py::test_materiality_still_reads_the_real_numbers` |
| PB-DATA-10 | A comparison across a formula change is reported as a redefinition, not a movement | PASS | `test_governance.py::test_a_formula_change_is_reported_as_a_redefinition_not_a_movement` |
| PB-DATA-11 | Cache keys carry user, permission, pack version, metric version, dataset version, period and filters | PASS | `snapshots.dataset_fingerprint` and `formula_hash`; snapshots are per pack version, so one user's authorised result cannot be served to another |

## PB-AI — what the model may and may not do

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-AI-01 | AI-drafted commentary through a live provider | **NOT VERIFIED** | `get_provider().configured` is `False` and its name is `'none'`. No API key exists in this environment, so no live drafting call was made. Marked NOT VERIFIED rather than PASS |
| PB-AI-02 | With no provider, the drafting path refuses plainly and writes no fallback | PASS | `narrative.NoProvider` is raised and surfaced; `test_narrative.py`. There is no template fallback in the code |
| PB-AI-03 | An AI draft is nobody's words until a person accepts it | PASS | `ai_accepted` on the block; readiness blocks approval on an unaccepted draft; `test_export.py::test_an_unaccepted_ai_draft_never_reaches_a_document` |
| PB-AI-04 | The model is never asked to calculate a financial metric | PASS | `narrative.py` receives calculated figures as evidence; the metric layer does the arithmetic |
| PB-AI-05 | The model is never asked whether data exists, or to invent materiality | PASS | Availability comes from `snapshots.classify`; materiality from `materiality.Rule` thresholds |
| PB-AI-06 | A movement below reported precision is given to the model as such, so no draft asserts one | PASS | `narrative.py` sets `direction` to "below reported precision"; added this phase |
| PB-AI-07 | Prompt injection in an uploaded pack, a comment or a transcript cannot escalate | PASS | Imported content becomes an `UNMAPPED_TABLE` block that names no metric and can reach no tool; `test_security.py` |

## PB-AGENT — the AI as an actor with an account

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-AGENT-01 | An agent's grant is capped below a person's, structurally | PASS | `access._capped(access, channel)`; `test_access.py` |
| PB-AGENT-02 | Thirteen named acts are refused to AI regardless of the grant it holds | PASS | `access.AI_FORBIDDEN` = approve_pack, approve_section, change_meeting_date, close_action, decide, delete_pack, delete_section, dismiss_finding, edit_approved_pack, edit_formula, import_document, publish_pack, record_review. `test_security.py` exercises them through the state the transition would otherwise allow |
| PB-AGENT-03 | AI never silently approves, publishes, moves a committed meeting date, changes an approved formula, suppresses a finding, closes an action or alters an approved historical pack | PASS | The list above is exactly those acts; each raises `PackDenied` |
| PB-AGENT-04 | Every write records who made it and through which channel | PASS | `service.record()` stores `author_id` and `source`; Journey F: 26 events, every one carrying a source |
| PB-AGENT-05 | The sweep runs on the platform's own queue, in the worker process that ships | PASS | `enqueue_sweep` in the API container, executed by the separate `agent-worker` container: job `playbook_sweep` reached `complete` on its first attempt with no error, and the worker's own log records "2 packs across 3 committees, 0 reminders sent". No second queue, no in-process thread, and no special case in the worker — `run_sweep_job` takes the same `(job, should_stop)` shape as every other handler |

## PB-GOV — governance

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-GOV-01 | A pack carries its own history: who changed what, when, through what channel | PASS | Journey F: `GET /packs/{id}/history` returns 26 events |
| PB-GOV-02 | An approved pack is locked, and an amendment is a new version with a reason | PASS | `LOCKED_PACK_STATUSES`; `/packs/{id}/amend`; `test_lifecycle.py` |
| PB-GOV-03 | Sections are submitted, reviewed and approved by named people | PASS | `/sections/{id}/submit`, `/request-review`, `/review`; `test_governance.py` |
| PB-GOV-04 | A reviewer cannot review their own section unnamed, and an observer cannot write | PASS | `access.may_review`; Journey I: an observer reads (200) and cannot publish or add a section (403) |
| PB-GOV-05 | A section with a template key cannot be deleted, nor one that has been reviewed | PASS | `service.delete_section`; `test_governance.py` |
| PB-GOV-06 | A dismissal takes a finding off the committee's list and therefore requires a written reason and REVIEWER access | PASS | Journey E: refused with a message naming why; `findings.py` |

## PB-LENS — the pack against the previous cycle

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-LENS-01 | A pack can be compared with the previous cycle, metric by metric | PASS | Journey G: 8 figures compared, `2024-12` → `2025-01` |
| PB-LENS-02 | Four kinds of difference are kept apart: MOVED, UNCHANGED, ADDED, REMOVED, REDEFINED | PASS | `compare.py`; `test_governance.py` |
| PB-LENS-03 | A movement whose displays are identical carries a caveat saying why | PASS | `compare._between`; added this phase |
| PB-LENS-04 | The sources behind a pack are listed | PASS | Journey F: `GET /packs/{id}/sources` |

## PB-PLANNER — what happens after the meeting

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-PLANNER-01 | A committee action becomes real work in the Project Planner | PASS | Journey L: action → planner task 30048 in project 164, verified by reading the project back |
| PB-PLANNER-02 | The handoff goes through the Planner's own service, so its access rules and its event record apply | PASS | `actions.link_to_planner` calls `planner.create_task`; Playbook never writes `planner_tasks` |
| PB-PLANNER-03 | An action already linked cannot be linked again | PASS | Journey L: the second handoff is refused (422) |
| PB-PLANNER-04 | The chase list says who is being waited on | PASS | Journey L: `GET /playbook/chase` answers 200 |

## PB-MEETING — the cycle

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-MEETING-01 | A committee's cadence drives its schedule: meeting date, data freeze, the offsets between | PASS | `committee.offsets` (create, data_check, escalate, generate, inputs, review); Journey Q |
| PB-MEETING-02 | The previous cycle's pack is published and the current one is in flight | PASS | Journey A: previous PUBLISHED, current REVIEW |
| PB-MEETING-03 | Minutes and the decisions taken are attached to the pack | PASS | `pack.minutes`; `/packs/{id}/decisions` |

## PB-EXPORT — the pack as a file

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-EXPORT-01 | Four formats download and open in the library that consumes them | PASS | Journey H: PDF 10,528 bytes, Word 40,514, slides 37,064, workbook 11,822 — each with the right content type, the workbook a real zip |
| PB-EXPORT-02 | The evidence workbook carries the working behind every figure | PASS | `test_export.py`; sheets PACK, FIGURES, FINDINGS, DECISIONS, ACTIONS, SINCE LAST |
| PB-EXPORT-03 | A table lifted out of an uploaded document reaches the pack documents | PASS | Fixed this phase. Journey O; five tests in `test_export.py` |
| PB-EXPORT-04 | An imported table is labelled as coming from a document, never as a calculation | PASS | `test_export.py::test_an_imported_table_says_where_it_came_from` |
| PB-EXPORT-05 | No exported cell can begin an Excel formula | PASS | Journey N and O: every string in the workbook scanned, 0 formula-leading cells, with a `=cmd\|'/c calc'!A1` payload present as inert text |
| PB-EXPORT-06 | A legitimate title like `<Finance> Review` survives through escaping, not a blocklist | PASS | Journey O; `test_export.py` reads Word and PowerPoint back with python-docx and python-pptx |
| PB-EXPORT-07 | Every export is recorded with what was in it | PASS | `test_export.py::test_every_export_is_recorded_with_what_was_in_it` |
| PB-EXPORT-08 | An export filename is a name and not a path | PASS | `export.safe_filename`; `test_export.py` |

## PB-DEMO — the demonstration

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-DEMO-01 | Three committees on different cadences, each with a published previous pack and a current one in flight | PASS | `scripts/seed_playbook_committees.py --reset`: retail (monthly, REVIEW), corporate (quarterly, DRAFT), IFRS 9 (quarterly, PUBLISHED) |
| PB-DEMO-02 | Dates are relative, and re-anchoring moves only dates | PASS | `--refresh-dates` moves `meeting_at` and `data_freeze_at` by `today - anchor` and nothing else; `test_demo.py` |
| PB-DEMO-03 | `--dry-run` writes nothing | PASS | `test_demo_seed.py`; verified end to end (12 dates would move, none written) |
| PB-DEMO-04 | A date a person changed is held back unless `--force` | PASS | `demo.refresh` finds a `PlaybookEvent` on the pack touching that field from a non-SYSTEM source; `test_demo.py` |
| PB-DEMO-05 | Re-anchoring is stable across midnight | PASS | The offset is `today - anchor` in whole days, taken once per run; `test_demo.py` |
| PB-DEMO-06 | Reset is dev-only and guarded | PASS | `_may_reset()` requires Synthetic Data Mode or ENV in dev/development/test/demo/local |
| PB-DEMO-07 | The seed is idempotent | PASS | `test_demo_seed.py`: `build()` twice produces the same committees |
| PB-DEMO-08 | Every figure in the demo packs is calculated from the real lake | PASS | Journey B: 8 of 8 retail figures OK, periods read from the data rather than the calendar |
| PB-DEMO-09 | Nothing rendered says "demo" or "demonstration data" | PASS | `backend/release/product_copy.py` `DEMO_PATTERN`; the vocabulary is "synthetic data" |

## PB-SEC — security

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-SEC-01 | A guessed pack, section, comment, review, approval, action, decision, export or source id is refused | PASS | Journey I: 7 routes on another committee's pack, all 404. `access.readable_pack` is the single door |
| PB-SEC-02 | The refusal does not leak what it refused | PASS | Journey I: the body says "No committee 2746" and carries no pack content |
| PB-SEC-03 | A cross-entity reference — a section on another committee's pack — is refused | PASS | `test_security.py` |
| PB-SEC-04 | Signed out is signed out on every route | PASS | Journey J: 401 on the list, a pack, and an export |
| PB-SEC-05 | A user with no membership sees no committee | PASS | Journey I: an account created through the real admin route sees an empty list |
| PB-SEC-06 | An executable renamed to `.xlsx` is refused before a parser sees it | PASS | Journey M: 422, on magic bytes |
| PB-SEC-07 | A path-traversal filename cannot become a path | PASS | Journey M: `../../../etc/passwd.xlsx` stored as `etc-passwd.xlsx` |
| PB-SEC-08 | An oversized upload is refused at the limit, not after buffering it | PASS | Journey M: 413. `_bounded_read` takes one byte past the limit and stops |
| PB-SEC-09 | A zip declaring an enormous member is refused | PASS | Journey M: 422, on the declared contents rather than the compressed size |
| PB-SEC-10 | An empty file and an unaccepted extension are refused | PASS | Journey M: both 422 |
| PB-SEC-11 | Excel formula injection is neutralised on the way out | PASS | PB-EXPORT-05 |
| PB-SEC-12 | Output escaping rather than a destructive blocklist | PASS | PB-EXPORT-06 |
| PB-SEC-13 | An AI channel cannot import a document | PASS | `access.refuse_ai(grant, "import_document")`; `test_import.py` |
| PB-SEC-14 | No source content leaks into a pack a reader is not authorised for | PASS | Sources are pack-scoped and pass `readable_pack`; Journey I |
| PB-SEC-15 | No authorised result can reach a second reader through a shared cache | PASS | Answered by not having one. `backend/playbook/` holds no `lru_cache`, no module-level dictionary and no cross-request store. The single cache is `readiness.refresh`, which writes the percentage onto the pack row itself; `assess(session, pack)` takes no principal, so what it computes is a property of the pack and not of the viewer, and every screen showing one pack calls `assess` directly rather than reading it. There is nothing keyed per user to mis-key |

## PB-LEGACY — retiring the earlier Playbooks feature

The name had an occupant. Every row here is pinned by
`tests/playbook/test_legacy_retirement.py` unless it says otherwise. Section C
of the final report carries the full dependency inventory and the reasoning.

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-LEGACY-01 | The old navigation entry is gone, and Playbook appears exactly once, under Govern | PASS | `test_the_old_navigation_entry_is_gone`; confirmed to FAIL when a `/playbooks` entry is put back, so it is a guard and not a decoration |
| PB-LEGACY-02 | `/playbooks` is retired: no page directory and no API path | PASS | `test_the_old_public_route_is_retired`. Retired rather than redirected, deliberately — a redirect would assert the two features are one object under two names |
| PB-LEGACY-03 | Nothing imports the removed implementation | PASS | `test_no_protected_feature_depends_on_the_removed_implementation`: import checks for both removed modules and both removed models, plus a source sweep of 596 files under `backend/` and `scripts/` |
| PB-LEGACY-04 | The legacy tables are gone and the fifteen new ones are present | PASS | `test_the_legacy_tables_are_gone_from_the_schema`, read from `pg_tables` — a migration that was written is not a migration that ran |
| PB-LEGACY-05 | Dropping the legacy tables was safe | PASS | Demonstration data only: the sole non-API writer was `backend/demo/workspace.py`, which also listed both tables among the ones its reset clears. No honest schema mapping to the new system exists. Recorded in `0039`'s docstring and in report section C, including the two caveats |
| PB-LEGACY-06 | The removal is reversible in schema | PASS | `test_the_removal_is_reversible_in_the_migration`. Schema only: `downgrade()` recreates both tables empty and does not bring rows back |
| PB-LEGACY-07 | Shared analytical infrastructure was not taken with it | PASS | `test_the_shared_infrastructure_the_feature_stood_on_still_works`: the engine registry still resolves 30 certified analyses, the runner is callable, Lenses imports. Playbooks borrowed these; it did not own them |
| PB-LEGACY-08 | The Brain advertises the module that exists | PASS | `test_brain_compatibility_declares_the_new_module_not_the_old_name`: capability renamed `playbooks` → `playbook` rather than dropped |
| PB-LEGACY-09 | The two good ideas were carried over, not lost | PASS | Thresholds against a governed number → `backend/playbook/materiality.py`; trigger-and-notify → `backend/playbook/monitor.py` and the chase list |
| PB-LEGACY-10 | Operational documents do not describe a feature that is gone | PASS | `DEMO_SCOPE_FREEZE.md` and `CLIENT_DEMO_SCRIPT.md` corrected. Immutable phase-start snapshots and past verification records were left alone — they are history, and editing them would destroy the baselines they exist to be |
| PB-LEGACY-11 | The retirement holds in the artifacts that ship, not only in the source | PASS | Checked against the running containers rather than the working tree: `/playbooks` answers 404 from the built frontend, the API's own OpenAPI document carries no path containing `/playbooks` and 43 containing `/playbook`, and the compiled Next.js bundle contains only `/playbook` hrefs. A source tree can be clean while a stale build still serves the old route |

## PB-QUALITY — the gates

| ID | Gate | Status | Evidence |
|---|---|---|---|
| PB-QUALITY-01 | `ruff check backend/ tests/ scripts/` clean | PASS | Run on this commit |
| PB-QUALITY-02 | `npx tsc --noEmit` clean | PASS | Run on this commit |
| PB-QUALITY-03 | `npx eslint` clean on the changed files | PASS | Run on this commit |
| PB-QUALITY-04 | `npm test` — the frontend suite | PASS | 520 tests, 46 suites, 0 failures |
| PB-QUALITY-05 | `pytest tests/playbook` | PASS | 261 passed |
| PB-QUALITY-06 | The full platform regression against the recorded baseline | PASS | 12,328 passed, 35 skipped, 0 failed, exit 0, in 19m 22s. Baseline: 12,075 passed, 35 skipped, 0 failed |
| PB-QUALITY-07 | Twenty journeys against the running stack | PASS | A-J, K-O, P-T, all passing on this commit — twice: against the stack run as separate processes, and against the four containers |
| PB-QUALITY-08 | No test was weakened, no tolerance enlarged, no failing test skipped | PASS | Seven defects were found by the journeys and by the container, and fixed in the product rather than reclassified; each carries a test that fails without the fix |
| PB-QUALITY-09 | The Docker path | PASS | Both images build; `docker compose up` brings postgres, backend, agent-worker and frontend to healthy; migration `0039` applies from an empty volume to head `0039` with 15 playbook tables and 0 legacy tables; all twenty journeys A-T pass against the containerised stack. Two product defects were found here and only here — see below |
| PB-QUALITY-10 | Migration head is a single linear head | PASS | Alembic head `0039`, no branch |
| PB-QUALITY-11 | Every page carries a curated expected behaviour in the feature matrix | PASS | `tests/docs/test_feature_matrix.py`, 8 passed |

---

## What is NOT VERIFIED, and why

One row, stated plainly rather than rounded up.

**PB-AI-01 — the live AI drafting path.** `get_provider()` reports
`configured = False` and names itself `'none'`. There is no API key in this
environment. The offline behaviour was verified — the path raises, says so,
and writes no fallback — but a live model call was never made, so the row is
NOT VERIFIED. Everything else in the Playbook works with no provider
configured.

**PB-QUALITY-09** was NOT VERIFIED and is now PASS. It was worth the time:
the container found two defects that no amount of running the stack as
separate processes could have found, because both were differences between
the developer machine and the image. They are recorded under "What FAILED"
below.

One caveat on how it was run, stated so nobody reads more into the row than
it says. This sandbox terminates TLS at a proxy, so `pip` and `npm` inside a
build cannot verify the certificate chain the base images ship. Both images
were therefore built with the proxy's CA injected — the backend through a
temporary Dockerfile that adds the bundle, the frontend through the
`ARG NODE_IMAGE` escape hatch its own Dockerfile already documents for this
situation. Neither change touches application code, dependency versions or
the entrypoint, and neither is committed. On a normal network the committed
Dockerfiles build unmodified; that specific claim was not executed here,
because this environment cannot present a normal network.

## What FAILED

Nothing on this commit. Three defects were FAIL when first run and were fixed
rather than reclassified:

1. An imported table was silently dropped from every export.
2. A blank cell in a table took the PowerPoint export down with a 500.
3. Word and PowerPoint were handed the PDF's HTML escaping, so
   `<Finance> Review` reached a client as `&lt;Finance&gt; Review`.

And two readings a committee would have called wrong, also fixed:

4. A movement too small to see at the metric's own precision was still drawn
   as an arrow between two identical numbers.
5. An uploaded supporting table blocked the readiness gate permanently, on a
   reason that was not true.

Then two more that only the container could show, because both were
differences between the developer machine and the image:

6. `python-pptx` was imported by the Playbook's export and import paths and
   declared in no requirements file. The developer machine had it as
   somebody else's transitive dependency; the image did not, so the slides
   export — offered in `/playbook/formats` as the deck a chair presents from
   — answered 500 in the only place the product ships. Declared, and the
   whole class pinned: a test now walks the Playbook's real imports and fails
   on any library that is not in `requirements.txt`.

7. `docker compose up` produced a stack with no user interface. The demo
   bootstrap seeds an example message with a saved analysis attached, and it
   picked that analysis without asking whether the sender could read it. On a
   fresh database every saved analysis belongs to the account that generated
   the portfolio, so the answer was always no; `send_message` refused, the
   step is required so the run stopped there, and the portfolio review that
   comes after it never ran either. The readiness marker recorded `ok: false`,
   the health check that reads that marker never went healthy, and the web
   container — which waits on that health — never started at all. The sibling
   function that picks an investigation had carried the access check, and the
   reasoning for it, since it was written; the analysis one had not.

Each carries a regression test that fails without its fix.

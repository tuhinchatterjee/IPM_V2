# CreditProbe Playbook V3 — handoff

Against §31's twenty items, in its order. Nothing below is asserted without
the command that produced it; where something is not done, it says so rather
than being omitted.

---

## 1. Branch

`claude/creditprobe-playbook-plan-ky3m05`. Not merged, not deployed, no pull
request opened.

## 2. Base commit

`3855f9b6f6b231beb6f2193c8a1e219d01596421` — identical to `main` at the time
this work started (`git rev-list --left-right --count main...HEAD` was `0 0`).

## 3. Final commit

`ccacd18b84757503966205c3144d56967016131b`. 39 commits, 167 files changed.

## 4. Migrations

Additive throughout. Every one was applied, downgraded and re-upgraded against
the isolated cluster; the head is single at `0040`.

| | |
|---|---|
| `0032` | exported-analysis library — `analysis_exports`, `analysis_export_revisions` |
| `0033` | the Playbook workspace — 10 tables |
| `0034` | stream events |
| `0035` | Document Intelligence — 10 tables |
| `0036` | `playbook_document_sections.history` |
| `0037` | snapshot context — currency, population, segment, scenario |
| `0038` | governance fields on findings, decisions and actions |
| `0039` | `playbook_decisions.status` widened to 32, default corrected to `proposed` |
| `0040` | job idempotency key made unique **per workspace**, not per deployment |

`0039` and `0040` are defect fixes found by this work and are described in
`DOCUMENT_INTELLIGENCE_DELTA.md` under Gates 7 and 11.

## 5. Changed architecture

Three things are new; nothing existing was replaced.

**A second, separated authoring runtime.** `backend/playbook/provider.py` sits
beside `backend/llm/`, which keeps its schema-constrained single-shot
contract untouched. Authoring is pure text streaming by default
(`document_tools=False`); rendering is deterministic and local through
`backend/playbook/render/`. The Anthropic document Skills path is retained
behind `PLAYBOOK_SKILL_RENDERING=1` with its own read timeout, so it can be
demonstrated without sitting on the critical path.

**A canonical document model.** `backend/playbook/document.py` holds
`Document`/`Section`/`Block` with a lossless `as_dict`/`from_dict`. Every
merge, every grounding check and every dashboard read works from that
canonical form, never from a Markdown re-render — which is what PB-017 turned
out to be.

**Document Intelligence.** `backend/playbook/intelligence/` computes the whole
dashboard from rows: profile, sections, metric bindings, snapshots,
comparison, findings, decisions, actions, readiness, and the chat bridge.
Nothing in that package calls a provider; a test asserts it by making
`provider.author` raise.

## 6. Data model

`DOCUMENT_INTELLIGENCE_DELTA.md` carries the delta table. In short: 12 tables
for the workspace and the export library, 10 for Document Intelligence. Three
rules run through all of them — a governed row records the person who changed
it and keeps an append-only `history`; a metric reading is frozen per version
and never rewritten; an uploaded file's bytes are immutable and its *reading*
is versioned separately.

## 7. Screenshots

**Partial, and this is the one item that is not complete.**

Present, in `docs/playbook/screenshots/`: Playbook home (desktop and laptop),
the thread (desktop and laptop), the analysis picker (desktop and laptop),
streaming, and the change-set panel.

**Absent: Know the Status, Findings, Decisions & Actions, Since Last Time,
section detail, sources and history.** Those seven are screenshots of the
dashboard user interface, and the dashboard UI has not been built. Frontend
assembly was held pending the reference screenshots you said you would
reattach, and they have not arrived in this session. The complete state and
API contract behind each of those screens exists, is tested, and is listed in
item 19 below — what is missing is the React that renders it.

This is the gating item for a complete Gate 12. Everything else in §31 is
answered below.

## 8. Save-gate regression matrix

`docs/playbook/SAVE_GATE_MATRIX.md`. All 19 of §19's failure classes, each
naming the test that reproduces the original failure in its original shape.
**19/19 PASS.** Running the named nodes directly: 38 tests (parametrised cases
expand), 0 failed.

`tests/playbook/test_save_gate_matrix.py` resolves every node id against the
source and fails if one was deleted, renamed or quarantined with
`skip`/`xfail` — so the matrix cannot drift from the code.

## 9. Soak-test counts

`scripts/playbook_soak.py` — **10 journeys × 10 cycles, 380 checks passed, 0
failed**, run three times (twice consecutively to prove no leakage between
runs). Evidence: `docs/playbook/soak_results.json`. No provider call: the
provider is replaced for the whole run and made to raise if reached.

Adversarial pass: `tests/playbook/test_adversarial.py`, **27 passed**, over
§21's list.

## 10. Browser acceptance counts

`scripts/acceptance/playbook_browser_acceptance.py` — **105 passed, 0
failed**, in real Chromium against the reseeded demonstration. This is §23's
non-regression list exercised for real: open, upload, attach, multi-select,
create with no template, create from a previous report, coverage questions,
sharpen one section, apply only selected changes, all four formats, version
history, download an old version, continue a thread, stream, stop, retry,
reopen after refresh, seeded threads. Evidence:
`docs/playbook/browser_acceptance.json`.

## 11. Backend test counts

```
tests/playbook                                            990 passed,  8 skipped
tests/api tests/exports tests/docs tests/demo
  tests/services tests/llm tests/proof tests/validation  1113 passed,  8 skipped
```

The 8 skips in each are the live-provider checks, which skip without a
credential. A skip is never counted as a pass.

`ruff check .` clean.

## 12. Frontend test / build counts

```
npx tsc --noEmit    clean
npm run lint        clean
npm test            462 passed, 0 failed
npm run build       succeeded
```

## 13. Artifact-validation counts

`scripts/acceptance/verify_playbook_artifacts.py` — **14 files inspected, 62
checks passed, 0 failed**. Every generated DOCX, PDF, PPTX and XLSX is
reopened with the same parsers Playbook uses on user uploads and checked
against the document it was rendered from; PDF pages are additionally
rasterised and inspected for blank pages, collapsed ink, and content outside
the margin. Evidence: `docs/playbook/artifact_verification.json`.

## 14. Live-provider smoke status

All six live criteria **PASS**, on real `claude-opus-5` calls with recorded
request ids and timings — PB-013, PB-015, PB-017, PB-029, PB-030, PB-043. See
`REQUIREMENTS_MATRIX.md` and `PROGRESS.md` for the per-check request ids.

**No paid call was made during Gates 6–12.** Everything in this phase is
deterministic and was verified with the scripted provider. The live suite is
unchanged and can be re-run with:

```bash
.venv/bin/python scripts/playbook_live_slice.py            # slice, then suite
.venv/bin/python scripts/playbook_live_slice.py --list     # what it would spend
```

It exits 2 rather than 0 without a credential, so a run that did not happen
can never read as a pass.

## 15. Demo content

Three complete resumable threads, seeded idempotently, making **no provider
call at seed time**:

1. IFRS 9 Committee Report — Q2 2026
2. Application Scorecard Model Development Report
3. Behavioural Scorecard Validation Report

Each has ≥12 messages, real input files parsed through the real ingestion,
attached exported analyses, a five-item change proposal with partial
approval, two genuinely different versions, real DOCX/PDF/PPTX outputs, and a
natural continuation point. Plus 30 substantial exports — six each from
Cockpit, Early Warning, Scorecard Validation, Lenses, and six What If
carried through the deferred adapter contract and labelled as such.

Every dashboard is populated on first open. The IFRS 9 workspace is the
committee example: period and meeting date, previous pack, 4 governed metrics
and 1 suggested, 4 Since Last Time rows, 4 findings including one blocking,
2 decisions (one recorded, one outstanding), 2 actions (one in progress, one
overdue), and a readiness panel reading *blocked* with three named blockers.

## 16. Known limitations

Stated rather than discovered.

1. **The dashboard UI does not exist.** The state and the API are complete and
   tested; no React component renders them. This is item 7's gating problem
   and the single largest remaining piece of work.
2. **OCR is unavailable.** An image-only PDF is declared unreadable rather
   than guessed at. Pages that matter but did not extract are sent as image
   blocks for vision; nothing claims to have read an image it did not inspect.
3. **Grounding is exact-token by design.** There is no numeric tolerance
   anywhere. A re-round (`8.95 → 8.9`) is an invention and is removed. The
   one deliberate widening is that a spreadsheet cell admits exactly two
   readings — as stored and as the workbook displays it — and no third.
4. **`GET /playbooks` and `GET /playbooks/{id}`** (the pre-existing
   *monitoring* Playbooks feature) have no permission dependency and so bypass
   `REQUIRE_LOGIN`. Reported rather than silently patched, because it is
   outside this branch's scope. The new module does not repeat it.
5. **CI has never run on this repository.** GitHub Actions reports
   `total_count: 0` before and after every push on this branch. CI is not a
   source of verification here; every count above was produced locally by the
   commands given.
6. **Two renders of the same document are not byte-identical.** DOCX ZIP entry
   timestamps and reportlab's `/ID` and `/CreationDate` move. Content is
   identical, and the soak fingerprint excludes exactly those fields. Making
   them constant would have every file claim a fictional creation time.

## 17. What If integration status

**DEFERRED-INTEGRATION.** No What If module exists on this baseline — the
backend has `stress_scenarios`, `backend/stress_lab.py` and an empty
`backend/stress/`, with no router and no frontend surface.

What ships: the adapter contract, a payload example, a contract test, and six
labelled fixture exports carried through it. `INTEGRATION_NOTES.md` names the
exact hook a future What If module must call. **No live cross-module
integration is claimed.**

Project Planner likewise does not exist. Playbook works completely without
one, and hands one everything it needs through
`GET/POST .../intelligence/actions/{id}/export`; an external status is
recorded in its own column and never moves ours.

## 18. Exact startup commands

```bash
cd /home/user/IPM_V2

# the isolated development cluster (port 55432, two databases)
scripts/playbook_dev_env.sh start

# environment — DATABASE_URL, SECRET_KEY, and ANTHROPIC_API_KEY if you want live
export $(grep -v '^#' .env | grep -v '^$' | xargs -d '\n')

# schema and demonstration
.venv/bin/python -m alembic upgrade head
.venv/bin/python scripts/bootstrap_demo.py --step playbook

# the application
.venv/bin/python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
npm --prefix frontend run build && npm --prefix frontend run start
```

## 19. Exact UAT route

`http://127.0.0.1:3000/playbook`

The three seeded threads are on the home screen under **Recent Playbooks**.
The dashboard behind them has no UI yet (item 7), so until it does it is
reachable only over the API:

```
GET  /api/v1/playbook/workspaces/{id}/intelligence
GET  /api/v1/playbook/workspaces/{id}/intelligence/metrics
GET  /api/v1/playbook/workspaces/{id}/intelligence/since-last-time
GET  /api/v1/playbook/workspaces/{id}/intelligence/sections/{key}
GET  /api/v1/playbook/workspaces/{id}/intelligence/context?kind=…&target=…
GET  /api/v1/playbook/workspaces/{id}/intelligence/context-actions
GET  /api/v1/playbook/workspaces/{id}/sources/parses
POST /api/v1/playbook/workspaces/{id}/intelligence/findings
POST /api/v1/playbook/workspaces/{id}/intelligence/findings/{id}/status
POST /api/v1/playbook/workspaces/{id}/intelligence/decisions/{id}/record
POST /api/v1/playbook/workspaces/{id}/intelligence/decisions/{id}/actions
POST /api/v1/playbook/workspaces/{id}/sources/reread
```

A governance act needs a named person: send `X-IPM-User-Id`. Without it the
route answers 422 `not_permitted`, which is the boundary working.

## 20. Click-by-click human-UAT script

Thirty minutes. Every step says what to expect, so a step that does something
else is a defect rather than a surprise.

### A — the home screen (3 min)

1. Open `http://127.0.0.1:3000/playbook`.
   *Expect, in this order:* page header → composer with a **+** on its lower
   left and **Send** on its right → quick-prompt chips → **Recent Playbooks**
   (3) → **Recent Exported Analyses**.
2. Click a quick-prompt chip.
   *Expect:* it fills the composer. It does **not** send, and it does not
   consume a generation.
3. Click **+** → **Attach an exported analysis**.
   *Expect:* the picker opens with 30 analyses, searchable and filterable.
4. Type `stage` in the picker's search, tick two results, then clear the
   search.
   *Expect:* both ticks survive the search being cleared.
5. Click into one analysis to preview it, then **Back**.
   *Expect:* your selection, scroll position and filters are all still there.
6. Close the picker without choosing.
   *Expect:* any draft text you had typed is still in the composer.

### B — a seeded thread (6 min)

7. Open **IFRS 9 Committee Report — Q2 2026**.
   *Expect:* ≥12 messages, three attached sources, attached analyses, a
   five-item change proposal with items 1–3 applied and 4–5 rejected, and two
   versions of the report.
8. Click the version-2 artifact card → **Download DOCX**.
   *Expect:* a real Word file with the right filename. Open it: the sections
   match the thread, and the figures match the chat.
9. Download the **PDF** and the **PowerPoint**.
   *Expect:* both open; the deck is real editable text and tables, not
   images.
10. Open **Version history** → view version 1.
    *Expect:* the earlier content, unchanged, and still downloadable.
11. Refresh the browser.
    *Expect:* everything above is exactly as it was. Nothing is lost.

### C — generation, streaming, stop and retry (8 min)

This is the part that needs `ANTHROPIC_API_KEY`. Without it the composer says
so and refuses, which is itself the correct behaviour to check.

12. In the IFRS 9 thread, type *"Sharpen section 1 only. Do not change
    anything else."* and choose the **Sharpen one section** task framing.
13. Send.
    *Expect:* text streams in. Real milestones appear — reviewing sources,
    drafting, rendering, validating — with no percentage bar, because there is
    no honest basis for one.
14. Press **Stop** mid-stream.
    *Expect:* it stops. No assistant answer is written, no version is created,
    and the previous version is still current and still downloadable.
15. Press **Try again**.
    *Expect:* one further generation, not two.
16. Let it finish.
    *Expect:* version 3 exists; section 1 has changed; **every other section is
    byte-identical**; the change summary says what changed.
17. Send the same message twice quickly, or refresh mid-generation.
    *Expect:* one generation and one question in the thread. Not two.

### D — upload and evidence (5 min)

18. Click **+** → upload a DOCX, an XLSX and a PDF.
    *Expect:* each shows a parse status, and the manifest says what was read
    and what was skipped and why. A hidden sheet is reported, not dropped.
19. Upload a renamed `.exe`, or a truncated `.docx`.
    *Expect:* refused, with a reason. No half-made source is left behind, and
    the workspace still works afterwards.
20. Ask *"What does the methodology require that this report does not do?"*
    *Expect:* named gaps, no invented tests, and **no artifact written** — a
    coverage question is not a request to write a report.

### E — the governed objects, over the API (5 min)

Until the dashboard UI exists (item 7), these are checked with `curl`. Replace
`{id}` with the IFRS 9 workspace id from `/api/v1/playbook/home`.

21. `GET /api/v1/playbook/workspaces/{id}/intelligence`
    *Expect:* `readiness.approval_status = "blocked"`, three named blockers,
    4 findings with 1 blocking, 2 decisions, 2 actions with 1 overdue.
22. `GET .../intelligence/since-last-time`
    *Expect:* 4 rows. Coverage moves **+0.08pp** — percentage *points*, not
    per cent. That distinction is the one to check.
23. `POST .../intelligence/decisions/{did}/record` with
    `{"outcome":"approve"}` and **no** `X-IPM-User-Id` header.
    *Expect:* **422 `not_permitted`** — "is a person's decision and records
    who made it. Nothing was changed." Repeat with the header: it records, and
    names you.
24. `GET .../sources/parses`
    *Expect:* every source, its reader version, and whether it needs
    re-reading.
25. `POST .../sources/reread` → then `GET .../sources/parses` again.
    *Expect:* a new parse revision, the old one kept and marked superseded,
    and **no new document version** — re-reading a source never rewrites a
    report.

### F — what should still be true at the end (3 min)

26. Reopen everything you touched.
    *Expect:* the thread, the versions, the files and the dashboard state are
    all as you left them.
27. Restart the API and the web server, then reopen.
    *Expect:* identical. Nothing lived only in memory.

---

## Definition of done — §32, honestly

| | |
|---|---|
| Current chat-first Playbook intact | ✅ 105/105 browser checks |
| Every document has an intelligence/status dashboard | ✅ state and API; ❌ no UI |
| "Know the Status" visible from existing Playbooks | ❌ needs the UI |
| Completion / page / section / readiness real | ✅ computed from rows, explainable |
| Section-by-section editing | ✅ |
| Metrics governed and linked | ✅ never by label similarity |
| Since Last Time compares correct snapshots | ✅ |
| Uploaded data refreshes metrics after confirmation | ✅ |
| Exported analyses update linked metrics cleanly | ✅ |
| Findings governed | ✅ |
| Committee reports have decisions and actions | ✅ |
| Approval readiness deterministic | ✅ |
| Source parser revisions governed | ✅ |
| Old save-gate bugs stay fixed | ✅ 19/19 |
| No regression to chat workflows | ✅ |
| Demo immediately usable | ✅ |
| Repeated testing reveals no state drift | ✅ 380/380, three runs |
| Human UAT can begin without known critical defects | ✅ for everything except the dashboard UI |

**Not done: the Document Intelligence user interface.** It is blocked on the
reference screenshots, not on anything technical. When they arrive, the master
prompt and the screenshots should be read together before any component is
written, and the information architecture must not be simplified — Pack,
Findings, Decisions & Actions, Since Last Time, Documents/Sections, History,
with the readiness panel on the right.

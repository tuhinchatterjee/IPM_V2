# CreditProbe Playbook — Document Intelligence handoff

Nothing below is asserted without the command that produced it. Where
something is not done, it says so rather than being omitted, and a skipped
check is never reported as a passing one.

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

Twenty-two, in `docs/playbook/screenshots/`, every one captured by the
acceptance run that asserted the state it shows — so an image is evidence of
a checked condition rather than a separate exercise.

The chat-first workspace: `home-desktop`, `home-laptop`, `thread-desktop`,
`thread-laptop`, `picker-desktop`, `picker-laptop`, `streaming`, `change-set`.

Document Intelligence: `thread-with-status` (the compact panel and the KNOW
THE STATUS action beside the conversation), `dashboard-overview`,
`dashboard-pack`, `dashboard-findings`, `dashboard-decisions`,
`dashboard-since-last-time`, `dashboard-sections`, `dashboard-metric-mapping`,
`dashboard-sources`, `dashboard-history`, `dashboard-update-review`,
`chat-with-context` (the dashboard handing a subject back to the composer),
and `dashboard-narrow` at 430px.

`docs/playbook/dashboard_acceptance.json` records which check each image was
taken beside.

## 8. Save-gate regression matrix

`docs/playbook/SAVE_GATE_MATRIX.md`. All 19 of §19's failure classes, each
naming the test that reproduces the original failure in its original shape.
**19/19 PASS.** Running the named nodes directly: 38 tests (parametrised cases
expand), 0 failed.

`tests/playbook/test_save_gate_matrix.py` resolves every node id against the
source and fails if one was deleted, renamed or quarantined with
`skip`/`xfail` — so the matrix cannot drift from the code.

## 9. Soak-test counts

`scripts/playbook_soak.py` — **21 journeys × 10 cycles, 891 checks passed, 0
failed**. Evidence: `docs/playbook/soak_results.json`. No provider call: the
provider is replaced for the whole run and made to raise if reached.

The point of the repetition is state drift, so the fingerprint each cycle is
compared against excludes creation metadata (ids, timestamps, the DOCX ZIP
entry times and reportlab's `/ID`) and nothing else. A run that ends with the
data in a different shape than it started fails, whether or not any individual
check did.

Adversarial pass: `tests/playbook/test_adversarial.py`, over §35's list —
governance acts attempted as `system` and as `claude`, a metric confirmed from
label similarity alone, a frozen snapshot written twice, a comparison across a
changed dimension, a re-read that tries to rewrite a document, a stale base
version, an idempotency key reused across workspaces, and a demonstration spec
naming a section that does not exist.

## 10. Browser acceptance counts

Two suites, both in real Chromium against the reseeded demonstration, both
exiting non-zero rather than reporting a pass if Chromium cannot launch.

`scripts/acceptance/playbook_browser_acceptance.py` — **105 passed, 0
failed**. This is the non-regression list exercised for real: open, upload,
attach, multi-select, create with no template, create from a previous report,
coverage questions, sharpen one section, apply only selected changes, all four
formats, version history, download an old version, continue a thread, stream,
stop, retry, reopen after refresh, seeded threads. Evidence:
`docs/playbook/browser_acceptance.json`.

`scripts/acceptance/playbook_dashboard_acceptance.py` — **185 passed, 0
failed**, and **370 passed, 0 failed over two consecutive cycles**, which is
what proves the run restores whatever it changed rather than leaving the
demonstration a little more answered each time. It covers thread entry, draft
survival across CHAT → STATUS → CHAT, the dashboard shell, Pack, Findings,
answering a finding, Decisions & Actions, Since Last Time, metric mapping,
confirming a suggestion, Sections, Sources, re-reading, History, update
review, the context bridge, keyboard and focus, accessibility, a tab forced to
fail, an empty Playbook, a non-committee document, and all three viewports.
Evidence: `docs/playbook/dashboard_acceptance.json`.

One of those is worth naming. `TabBoundary` was written after a real crash —
reading a governance-only field off a section history entry threw and React
unmounted the whole application — and a guard nothing exercises is a guard
nobody knows is broken. So the run intercepts the history response on its way
to the browser, rewrites it to a shape the tab cannot render, and checks that
the tab says so as an alert, that the header, status cards and readiness panel
are all still there, that another tab still opens, that the notice leaves with
the tab that failed, and that the tab works again once the intercept is
removed. Nothing on the server is touched.

## 11. Backend test counts

```
tests/playbook                                           1037 passed,  8 skipped
```

The 8 skips are the live-provider checks, which skip without a credential. A
skip is never counted as a pass.

`ruff check .` clean.

## 12. Frontend test / build counts

```
npx tsc --noEmit    clean
npm run lint        clean
npm test            516 passed, 0 failed
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
attached exported analyses, a five-item change proposal with partial approval,
two genuinely different versions, real DOCX/PDF/PPTX outputs, and a natural
continuation point. Plus 30 substantial exports — six each from Cockpit, Early
Warning, Scorecard Validation, Lenses, and six What If carried through the
deferred adapter contract and labelled as such.

Every dashboard is populated on first open. The IFRS 9 workspace is the
committee example: period and meeting date, previous pack, 4 governed metrics
and 1 left suggested so the review path is visible, 4 Since Last Time rows, 4
findings across four different origins including one blocking, 2 decisions
(one recorded, one outstanding), 2 actions (one in progress, one overdue), 42
history events across all eight kinds, and a readiness panel reading *blocked*
with three named blockers. The other two are non-committee documents, so they
carry the alternate tab set and are never asked about meeting dates or
committee decisions.

Two properties of the demonstration are deliberate and are pinned by tests:

* **It does not open at 100%.** A dashboard that opens complete demonstrates
  nothing. Readiness is strictly between 0 and 100 on first open, with its
  blockers named.
* **It shows a refusal to compare.** Stage 2 exposure carries the same label
  in both packs and moved from SAR 72.00m to SAR 113.00m, which by label
  comparison is a 57% jump onto a committee agenda. It is not a jump: the
  previous pack measured the corporate book and the current reading covers
  corporate and SME together. Since Last Time refuses to subtract them and
  names the dimension that moved. A demonstration in which every pair happens
  to be comparable teaches the reader the opposite of the rule.

## 16. Known limitations

Stated rather than discovered.

1. **OCR is unavailable.** An image-only PDF is declared unreadable rather
   than guessed at. Pages that matter but did not extract are sent as image
   blocks for vision; nothing claims to have read an image it did not inspect.
2. **Grounding is exact-token by design.** There is no numeric tolerance
   anywhere. A re-round (`8.95 → 8.9`) is an invention and is removed. The one
   deliberate widening is that a spreadsheet cell admits exactly two readings —
   as stored and as the workbook displays it — and no third.
3. **`GET /playbooks` and `GET /playbooks/{id}`** (the pre-existing
   *monitoring* Playbooks feature) have no permission dependency and so bypass
   `REQUIRE_LOGIN`. Reported rather than silently patched, because it is
   outside this branch's scope. The new module does not repeat it.
4. **The application shell marks a non-live navigation item with colour
   alone.** `frontend/src/components/layout/sidebar.tsx:94` draws a 4px dot
   beside every nav item whose status is not `live`, and the only word for it
   is the link's `title` — a hover tooltip. It is `aria-hidden`, so a screen
   reader is unaffected; a sighted user who cannot see the dot has no other
   signal. This is on every route in the product and is not Playbook's to
   change, so the §32 sweep is scoped to the dashboard's own region and the
   finding is recorded rather than absorbed into that run's result.
5. **The shell overflows at 430px; the dashboard does not.** The untouched
   `/playbooks` page shows the same escape. Every element of the Document
   Intelligence dashboard stays inside the viewport at all three tested
   widths, with wide tables scrolling inside their own boxes.
6. **CI has never run on this repository.** GitHub Actions reports
   `total_count: 0` before and after every push on this branch. CI is not a
   source of verification here; every count in this document was produced
   locally by the commands given.
7. **Two renders of the same document are not byte-identical.** DOCX ZIP entry
   timestamps and reportlab's `/ID` and `/CreationDate` move. Content is
   identical, and the soak fingerprint excludes exactly those fields. Making
   them constant would have every file claim a fictional creation time.
8. **The dashboard is read-mostly on a phone.** It is laid out and asserted at
   1366×768, 1440×900 and 430×900; at the narrow width the readiness panel
   stacks beneath the main column rather than sitting beside it, and dense
   tables scroll horizontally. Nothing disappears, but the three-column
   Sections view is not comfortable at that width.

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
Open one and the compact Document Status panel sits beside the conversation,
with **KNOW THE STATUS** leading to the full dashboard at
`/playbook/{id}/status`. Back to chat returns with the composer draft,
attachments, selected analyses and scroll position intact.

The same state is readable over the API, which is how a governance act can be
exercised without the UI:

```
GET  /api/v1/playbook/workspaces/{id}/intelligence
GET  /api/v1/playbook/workspaces/{id}/intelligence/metrics
GET  /api/v1/playbook/workspaces/{id}/intelligence/since-last-time
GET  /api/v1/playbook/workspaces/{id}/intelligence/sections/{key}
GET  /api/v1/playbook/workspaces/{id}/intelligence/history
GET  /api/v1/playbook/workspaces/{id}/intelligence/updates
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

### E — the Document Intelligence dashboard (10 min)

21. In the IFRS 9 thread, type half a sentence into the composer and **do not
    send it**. Click **KNOW THE STATUS**.
    *Expect:* the dashboard at `/playbook/{id}/status`. The header names the
    document, its type, its reporting period and its meeting date.
22. Read the status cards and the readiness panel.
    *Expect:* completion and readiness shown as two separate numbers, never
    combined into one score. Readiness reads **blocked**, strictly between 0
    and 100, with three named blockers. Click a readiness component: it opens
    and tells you what it is made of. You should be able to answer "why is
    readiness what it is?" without asking Claude.
23. Open **Since last time**.
    *Expect:* four rows. Coverage moves **+0.08pp** — percentage *points*, not
    per cent; that distinction is the one to check. Stage 2 exposure shows
    **Not comparable**, both readings still visible (SAR 72.00m and SAR
    113.00m), an empty change column, and a line naming the dimension that
    disagrees: the previous pack measured the corporate book, the current
    reading covers corporate and SME. Comparing those two by label would put
    a 57% jump on a committee agenda.
24. Open **Metric mapping**.
    *Expect:* one metric shown as *suggested*, not confirmed, and counted
    outside coverage. Confirming it is a click you make; nothing confirmed it
    from the labels matching.
25. Open **Findings** and answer one.
    *Expect:* your name on the answer, the finding's state moving, and the
    change appearing in **History**.
26. Open **Decisions & actions** and try to record a committee decision
    without identifying yourself (drop the `X-IPM-User-Id` header over the API,
    or use the form which requires a name).
    *Expect:* **422 `not_permitted`** — "is a person's decision and records who
    made it. Nothing was changed." With a name it records, and names you.
27. Open **Sources**, re-read one, then look at **History**.
    *Expect:* a new parse revision, the old one kept and marked superseded, and
    **no new document version** — re-reading a source never rewrites a report.
28. From any row, use **Ask**.
    *Expect:* you land back in the conversation with that subject handed over,
    your half-sentence still in the composer, and your scroll position kept.
    The hand-over survives a reload and can be dismissed.

### F — what should still be true at the end (3 min)

29. Reopen everything you touched.
    *Expect:* the thread, the versions, the files and the dashboard state are
    all as you left them.
30. Restart the API and the web server, then reopen.
    *Expect:* identical. Nothing lived only in memory.
31. Open a Playbook with no document in it.
    *Expect:* an explanation, not a wall of noughts. No zero percentages, no
    empty readiness dial, no invented meeting date.

---

## Definition of done

| | |
|---|---|
| Chat-first Playbook intact | ✅ 105/105 browser checks, unchanged |
| Every document has a status dashboard | ✅ state, API and UI |
| KNOW THE STATUS reachable from an existing Playbook | ✅ beside the thread |
| CHAT → STATUS → CHAT loses nothing | ✅ draft, attachments, selection, scroll |
| Completion and readiness never combined | ✅ two numbers, asserted separately |
| Readiness explainable without asking Claude | ✅ clickable components, named blockers |
| Committee and non-committee tab sets differ | ✅ no meeting date on a generic document |
| Section-by-section editing and review | ✅ three-column Sections view |
| Metrics governed, never linked by label | ✅ `is_governed` is the single predicate |
| Since Last Time compares the right snapshots | ✅ THEN frozen per version |
| A mismatched dimension is refused, not subtracted | ✅ demonstrated, not just supported |
| Uploaded data refreshes metrics after confirmation | ✅ never auto-applied |
| Check for Updates never auto-rewrites | ✅ proposals only |
| Findings governed, with their origins | ✅ four origins in the demonstration |
| Committee reports carry decisions and actions | ✅ |
| Approval readiness deterministic | ✅ no model-generated percentage anywhere |
| Source parser revisions governed | ✅ re-read writes no document version |
| Real document statistics | ✅ page count measured from the rendered file |
| History is a real trail | ✅ 42 events, eight kinds, assembled from the rows |
| Old save-gate bugs stay fixed | ✅ 29/29, node ids resolved against the source |
| No regression to chat workflows | ✅ |
| Demonstration immediately usable | ✅ populated on first open, never at 100% |
| No zero-state noise on an empty Playbook | ✅ explained, not counted |
| Accessible: focus, Escape, labels, non-colour status | ✅ within the dashboard |
| Responsive at 1366×768, 1440×900 and narrow | ✅ nothing escapes the viewport |
| Repeated testing reveals no state drift | ✅ 891/891 soak; 370/370 over two cycles |
| Artifacts parse back to what they claim | ✅ 14 files, 62 checks |
| Human UAT can begin with no known critical defect | ✅ |

**Not done, and deliberately so: no live-provider run was made in this phase.**
Every behaviour above is deterministic and was proven with the scripted
provider, the real renderers, the real parse-back readers and a real browser.
The live suite is unchanged and is re-runnable one check at a time; it exits 2
without a credential, so a run that did not happen can never read as a pass.

**Not merged, not deployed, no pull request opened.**

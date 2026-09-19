# Playbook — Direct Chat handoff

Specification: `DIRECT_CHAT_MASTER_SPEC.md`. Plan and reuse/change table:
`DIRECT_CHAT_PLAN.md`. Acceptance matrix: `DC_MATRIX.md`.

| | |
|---|---|
| Branch | `claude/creditprobe-playbook-plan-ky3m05` |
| Base at the start of this work | `cc16b9b` |
| Final commit | see below; `git log -1` on the branch is authoritative |
| Alembic head | `0040`, single — **no migration was needed** |
| Merged / deployed / PR | none of the three |
| Paid provider calls | **none**, see §6 |

---

## 1. Read this first

The conversation is the product. A message goes to `backend/playbook/chat.py`,
which assembles history, attachments, exported analyses and the active
document and hands them to `backend/playbook/assistant.py`. The assistant
answers; if the turn needs a file it calls `create_document`,
`revise_document` or `convert_document`. Nothing routes on keywords, nothing
forces a format, and an ordinary question never touches the document path.

Three consequences worth knowing before reading anything else:

* **A document failure is not a conversation failure.** A tool that cannot do
  what was asked returns a failure the assistant explains and the thread
  survives. Only the *runtime* failing — a timeout, a missing model, a stop —
  ends the turn.
* **Delivery is per format.** Word can be delivered while PDF fails. A file
  that will not open is never delivered; a content finding — a figure wanting
  a source, a table count that differs — is recorded and blocks nothing.
* **The dashboard cannot destroy the document.** Versions and files commit
  alone. `service.project_status` runs afterwards, in its own session, and is
  not permitted to raise.

## 2. What state each claim is in

Four columns, kept apart deliberately. A route-level test is not browser
evidence, and a scripted run is not a live one. A row sits only in a column it
has actually reached.

| Behaviour | Implemented | Browser, scripted | Live | Not verified |
|---|---|---|---|---|
| A declared document task produces a document | ✅ | ✅ L | **failed, fixed** | live retest |
| A second send cannot start a second paid run | ✅ | ✅ M | | live |
| Live step list, elapsed time and heartbeat | ✅ | ✅ | | live |
| The document streams as it is written | ✅ | ✅ | | live |
| Ordinary question answered, no file, no tool | ✅ | ✅ A | | live |
| Question about an attachment, no forced file | ✅ | ✅ B | | live |
| Explicit report request → real Word + PDF | ✅ | ✅ C | | live |
| Files download as real openable bytes | ✅ | ✅ C | | live |
| Scoped revision; v1 retained | ✅ | ✅ D | | live |
| PowerPoint in the same thread | ✅ | ✅ E | | live |
| Conversion reuses the stored version, no re-authoring | ✅ | ✅ F | | live |
| One format fails, the other is delivered | ✅ | ✅ G | | live |
| Tool failure explained, no false success | ✅ | ✅ H | | live |
| Status projection fails, delivery unaffected | ✅ | ✅ I | | live |
| Reopen keeps conversation, files and versions | ✅ | ✅ J | | live |
| Interruption labelled **in the thread**, earlier report untouched | ✅ | ✅ K | | live |
| Deterministic progress: content / deliverable / review / files | ✅ | ✅ A, C | | live |
| Review ladder: draft, reviewed, governed, approved | ✅ | ✅ C | | live |
| Document path chosen per task and recorded per artifact | ✅ | | | browser, live |
| Unsupported capabilities declared, never simulated | ✅ | | | browser, live |
| Dashboard, sources, versions, permissions intact | ✅ | ✅ | | live |
| Research, email, connectors, sharing | **not built** | | | — declared absent |

**Live: one journey has been run, and it failed.** DC-42 — the real Auto Loan
pack, a real credential — produced no document at all. §10 is the account of
it. Everything else here is deterministic or scripted, and the six live
criteria that passed on *earlier* code are historical evidence, not a
certificate for this one.

**The blind spot, named.** A scripted browser run cannot prove a live model
calls a tool: the fixture decides. Sixteen rows of browser evidence and 144
green checks coexisted with a total failure on first live contact, and no
claim in this document was wrong — the column does not mean what it is easy to
read it as meaning. Journey **L** now scripts the *refusal* rather than the
call, which is the nearest a fixture can get, and the two replies the live
model actually gave are in the detector's test cases verbatim.

## 3. Counts, at the final commit

| Run | Result |
|---|---|
| `pytest` — whole repository | **10,637 passed, 30 skipped, 0 failed**, exit 0 (22m05s) |
| `pytest tests/playbook` | **1,145 passed, 8 skipped** — the 8 are the live checks |
| Chat browser acceptance, **two consecutive cycles** | **144 passed, 0 failed** (72 per cycle, journeys A–M) |
| Workspace browser acceptance | **105 passed, 0 failed** |
| Dashboard browser acceptance | **185 passed, 0 failed** |
| Artifact parse-back | **14 files, 62 checks, 0 failed** |
| Soak, 21 journeys × 10 cycles | **911 checks passed, 0 failed** |
| `ruff check .` | clean |
| `tsc --noEmit` | clean |
| `eslint` | clean |
| Frontend unit tests | **528 passed, 0 failed** |
| `next build` | succeeded |

The 30 pytest skips and the 8 in `tests/playbook` are live-provider checks
that skip without a credential. **A skip is not a pass** and is not counted as
one anywhere in this document.

Every number above was read off a finished run on this commit. An earlier
attempt was stopped and restarted rather than reported, because it had begun
before the last change landed and would have been describing a tree that no
longer existed.

The chat suite proves its own premise before asserting anything: it reads
`GET /playbook/capabilities` and exits non-zero if the server is not scripted,
so it can never pass by testing a refusal. It removes every workspace it
creates — an earlier version did not, and fifty-four leftovers pushed the
seeded demonstrations off Recent Playbooks and failed two other suites.

## 4. The acceptance matrix

`DC_MATRIX.md`, DC-01 to DC-42, with the status vocabulary used exactly:

| | |
|---|---|
| PASS — deterministic | **39** |
| PASS — browser scripted | **17** (16 of them also deterministic) |
| PASS — live verified | **0** |
| FAIL — live, fixed, awaiting retest | **1** — DC-42 |
| BLOCKED | **1** — DC-41 |
| NOT IMPLEMENTED | **one half of one row** — DC-13's *enabled research* clause |

`tests/playbook/test_dc_matrix.py` checks the table rather than trusting it:
every cited file exists, every `file.py::Symbol` is a symbol in a file of that
name, every browser claim names a journey the script runs or one of the two
other suites, no row claims live verification, and the stated totals are the
counted totals. Six mutations prove it bites.

## 5. How the mechanisms work

**Document generation path.** `backend/playbook/documents.py` chooses per
task, not by a blanket switch. A conversion is always LOCAL — the document is
already written and re-authoring it would spend money to produce a *different*
report under the same version number. Otherwise SKILL when the provider's
document tooling is genuinely available (the flag **and** a configured
provider — a flag alone is a preference), LOCAL when it is not. The choice
travels with the file: `playbook_artifact_files.renderer` records which path
produced each artifact, and `_usable` decides per format, so a Skill file that
validates is kept as it came and only a format that will not open falls back.
`GET /playbook/capabilities` publishes both paths in chapter 02's three
states.

**Progress.** `backend/playbook/progress.py`. Four questions answered
separately, because they have different answers: how much of the document is
substantively written, which requested formats exist, whether a person has
checked any of it, and what became of each format including the ones that
failed. Every number is counted from rows — the sections of the stored
version, the files on it, the review block. No model produces any part of it.

    100 × delivered weights / active weights

and **Not applicable** when the denominator is zero — never 0%, never 100%. A
section that says something is delivered; a section whose whole body is an
admission that evidence is missing is `needs_input`, and the payload says
which phrase decided it, so a reader can disagree with a judgement rather than
with a number. A PDF that failed leaves eight written sections at eight.

**Live feedback, while a generation runs.** A step checklist, each entry a
real event named by the backend from the tool's own arguments and ticked off
as it starts, with its own elapsed time; steps a tool has announced but not
reached shown hollow; a total clock anchored to the server's offset for the
newest event and advanced locally between events; *"still connected · last
event 3s ago"* from a heartbeat that is now a named event rather than a
comment the parser discarded; and a collapsible pane holding the document as
it is written, counted in sections as they arrive.

There is deliberately **no percentage**. Writing is most of the wall time and
one step of five, so a step bar would sit near empty for almost the whole run
— the same lie as one stuck at 95%, told backwards. Document completion stays
where it belongs, in the dashboard, computed from stored rows after delivery.

## 6. Budget

No paid call was made. Tests use the scripted provider in
`tests/playbook/conftest.py`; the browser uses `backend/playbook/scripted.py`.

One outbound request left the process during development and is recorded here
rather than omitted: an early test fixture supplied a fake credential so the
product's own configuration check would run for real, and a test that had not
scripted the call built a genuine client and sent a request. It returned 401,
nothing was generated, nothing was spent. `provider._client` is now replaced
in tests by an object that raises, so the suite cannot reach a provider at
all.

`scripts/playbook_live_smoke.py` is the only paid path, and it is not run
here. Five steps, bounded and resumable: it declares its intended calls before
spending anything, refuses to start without a credential, refuses to run
against a scripted server, stops at the first failure with the workspace and
diagnosis preserved, and `--resume` re-runs only what has not passed.

```bash
.venv/bin/python scripts/playbook_live_smoke.py --plan     # costs nothing
.venv/bin/python scripts/playbook_live_smoke.py            # ~7 calls
.venv/bin/python scripts/playbook_live_smoke.py --resume   # after a failure
```

## 7. Starting it on the Mac

The isolated Playbook worktree, on its own ports. **The main CreditProbe
backend on 8000 is a different service and none of this touches it.**

```bash
cd ~/Desktop/IPM_V2-playbook-live
git fetch origin claude/creditprobe-playbook-plan-ky3m05
git switch claude/creditprobe-playbook-plan-ky3m05     # or: git pull

scripts/playbook_live.sh doctor      # what is configured; no value is printed
scripts/playbook_live.sh start       # 55432, then 8001, then 3000
scripts/playbook_live.sh status
scripts/playbook_live.sh stop        # only what it started
```

| | |
|---|---|
| PostgreSQL | **55432**, isolated cluster |
| Playbook backend | **8001** |
| Frontend | **3000** |
| **UAT URL** | **`http://127.0.0.1:3000/playbook`** |

Three things to know before the first run:

1. **The frontend build decides which backend it talks to, by two routes.**
   `NEXT_PUBLIC_API_URL` is what the application's own client calls;
   `BACKEND_INTERNAL_URL` is where `next.config.ts` rewrites same-origin
   `/api/...` requests, which Next fixes during `next build`, not at start.
   Both default to 8000 and both must be the **origin only** — the client
   appends `/api/v1` itself, and including it produces
   `/api/v1/api/v1/...` and a page that reports the backend offline. `start`
   rebuilds when the recorded pair does not match, so this is usually
   automatic; to do it by hand:

   ```bash
   NEXT_PUBLIC_API_URL=http://127.0.0.1:8001 \
     BACKEND_INTERNAL_URL=http://127.0.0.1:8001 \
     npm --prefix frontend run build
   ```
2. **`.env` in this repository sets `API_PORT=8000`** for the main backend.
   The launcher does not read its port from there — sourcing `.env` inside the
   subshell used to clobber 8001 and start Playbook on the other service's
   port, the one collision the script exists to prevent.
3. **Generation needs `ANTHROPIC_API_KEY` and an author model.** Put them in
   the worktree's own `.env`, never in a browser bundle or a chat message.
   Without them every workspace, file, version and dashboard stays browseable
   and the composer says generation is unavailable rather than offering a
   button that fails. `doctor` reports presence or absence only and never
   prints a value.

`start` and `stop` were exercised end to end here: the built bundle carried
`127.0.0.1:8001` and no reference to 8000, `stop` released both ports and left
nothing behind, a second `stop` was a no-op, and the unrelated backend on 8000
stayed up and untouched throughout.

## 8. Five-step human UAT

Against `http://127.0.0.1:3000/playbook`, with a credential configured.
Fifteen minutes. Each step has a way to be wrong.

1. **Ask a question.** *"What is the difference between a scorecard
   development report and a scorecard validation report?"*
   Expect prose in the thread and nothing else. **Wrong if** a Word file
   appears, a document is created, or the status panel shows 0%.

2. **Upload a methodology and ask about it.** Attach a `.docx` and ask
   *"Summarise this and tell me what looks incomplete. Don't create a file."*
   Expect an answer that names what is missing rather than filling it in, and
   no file. **Wrong if** a file is produced anyway, or gaps are invented.

3. **Ask for the report.** *"Using that methodology, write a scorecard
   development report in Word and PDF."*
   Expect both files, both downloading and opening, and the status panel
   counting written sections — a gap section marked *needs input*, not
   counted as done. **Wrong if** a file will not open, if the count is a round
   number with no numerator and denominator behind it, or if the review state
   is anything but *draft* with nobody named as reviewer.

4. **Revise one section.** *"Shorten the executive summary and make it more
   committee-ready. Change nothing else."*
   Expect version 2, version 1 still openable, and the other sections
   byte-identical. **Wrong if** an unrelated section changed, or v1 is gone.

5. **Convert, then reopen.** *"Give me a PDF of the latest Word report."*
   Then close the tab, reopen `/playbook`, and open the same workspace.
   Expect the conversion to say it reused the existing version, and the
   reopened thread to carry every message, file and version. **Wrong if** the
   conversion re-authors the document, or anything is missing after reopening.

## 9. Limitations, named rather than left to be found

1. **Nothing is live-*verified* on this code, and one journey is live-FAILED.**
   DC-42 was run against the real pack and did not pass; the cause is fixed
   and covered, and the retest is owed. Everything else is deterministic or
   scripted. `scripts/playbook_live_smoke.py` is the bounded way to change
   that; it has not been run.
2. **DC-41 is blocked.** `doctor` reports worktree, branch, commit, build
   target and migration head, and a scripted server names itself in
   `capabilities`. What is missing is the *served build* identifier in the UI,
   which needs the macOS worktree to confirm end to end.
3. **DC-42 is FAIL, not blocked.** The pack and the credential exist; the
   journey ran and produced nothing. §10 is the account. Re-running it is the
   first thing to do, and it is one click.
4. **There is no research capability.** No web search, no browsing. It is
   declared absent in the capability audit and the assistant is told the same
   thing, so it is never simulated — but DC-13's *enabled research* clause has
   nothing to satisfy it.
5. **Document Skills are not the default.** They are implemented and chosen
   automatically when available, which needs `PLAYBOOK_SKILL_RENDERING=1` and
   a configured provider. Without both, documents are rendered locally, and
   the capability audit says so rather than implying otherwise.
6. **The launcher has not run on macOS.** `set -m`, `kill -- -PGID` and the
   port probe are POSIX, and it was exercised on Linux. That is an argument,
   not evidence.
7. **The richer Document Intelligence dashboard is optional and stays
   optional.** Metric binding, findings, committee workflow, readiness review
   and section approval are reachable behind *Know the Status* and are never
   forced on an ordinary user or required to deliver a document.

## 10. The first live run, and what it found

Run on the user's own machine against the real Auto Loan pack — seven sources,
a 39 KB methodology, a 135 KB workbook — with a real credential. It produced
**no document at all**, and the thread showed four identical
*"Draft the report from the attached sources."* messages, two replies
announcing the work in past tense, and *"Nothing generated yet."*

Three separate defects. None was slowness.

**The model announced a document and never called the tool.** `converse` ended
the turn the moment no tool block arrived, and nothing on the Playbook path
sent `tool_choice` — the only use of it in the repository was on the
analytical path. The declared intent reached the model as a bracketed sentence
appended to the prompt and was ignored.

Fixed three ways, in order of how much each is relied on: `tool_choice: any`
on the first turn when the caller declared document work, which leaves the
choice between create, revise and convert open and removes only the option of
doing nothing; one bounded correction when a turn's own words claim a document
and no tool ran; and `no_file` on the message so a turn that produced nothing
cannot read as success.

**Every extra click started another concurrent paid generation.** The only
dedupe was the idempotency key, and the browser's key is positional
(`ws7:turn12`) — so the same sentence sent again after a reload got a new key
and was accepted as new work. Only the newest was visible. **That run may have
been charged up to four times.**

Migration `0041` makes one-live-job-per-workspace a database guarantee: a
partial unique index on `playbook_jobs (workspace_id) WHERE finished_at IS
NULL`. A check-then-insert races; an index cannot. The worker heartbeats so a
killed process cannot lock the workspace for ever, and Send is now disabled
while a generation runs, with the reason and a Stop button.

**Nothing said the run was alive.** No event carried a timestamp, the
heartbeat was an SSE comment every conforming parser discards, and the longest
part of a generation emitted nothing because authoring was called with
`on_delta=None`. See §5 for what replaced it.

Two things were found only because the fix was exercised end to end, and both
would have cost the next person the same hour: the launcher rebuilt when the
API address changed but not when the source did, so it served a stale bundle
while the browser suite failed on text already in the working tree; and the
two older acceptance suites named port 8000 directly, which was true only
while the frontend happened to be built against 8000.

**What is still owed.** DC-42 is FAIL, not PASS. The fix is proven
deterministically and in the browser; the live journey has not been re-run.
That is one command, in §6, and it is the first thing to do.

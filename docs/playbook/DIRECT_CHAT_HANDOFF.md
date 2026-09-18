# Playbook — Direct Chat handoff

Specification: `DIRECT_CHAT_MASTER_SPEC.md`. Plan and reuse/change table:
`DIRECT_CHAT_PLAN.md`.

| | |
|---|---|
| Branch | `claude/creditprobe-playbook-plan-ky3m05` |
| Base at the start of this work | `cc16b9b` |
| Final commit | `5bb8d38` |
| Alembic head | `0040`, single — **no migration was needed** |
| Merged / deployed / PR | none of the three |
| Paid provider calls | **none**, see §5 |

---

## 1. What state each claim is in

The four tiers are kept apart deliberately. A row is only in a column it has
actually reached.

| Behaviour | Implemented | Browser, scripted provider | Live | Not verified |
|---|---|---|---|---|
| Ordinary question answered with no file | ✅ | ✅ | | |
| Question about an attachment, no forced file | ✅ | | | live |
| Explicit report request → real Word + PDF | ✅ | ✅ | | |
| Files download as real openable bytes | ✅ | ✅ | | |
| One format fails, the other is delivered | ✅ | | | browser, live |
| Content finding does not withdraw the file | ✅ | | | browser, live |
| Conversion retry makes no authoring call | ✅ | | | browser, live |
| Tool failure explained, no false success | ✅ | | | browser, live |
| Status projection fails, delivery unaffected | ✅ | | | browser, live |
| Reopen keeps conversation and files | ✅ | ✅ | | |
| Follow-up works from the prior document | ✅ | | | browser, live |
| Interruption labelled, not presented as finished | ✅ | | | browser, live |
| Dashboard, sources, versions, permissions intact | ✅ | ✅ | | |
| Document Skills / code execution as default path | | | | **not done** |
| Grounding retired from the drafting path | | | | **not done** |
| Work-item completion arithmetic (ch. 12) | | | | **not done** |

**Live: nothing.** No paid call has been made on this branch during this work.
Six live criteria passed on earlier code and are historical evidence, not a
current certificate — chapter 31 is explicit about that distinction.

## 2. What changed

**The message path is a conversation.** `run_generation` ran
`author_document` unconditionally with `DEFAULT_FORMATS = ("docx", "pdf")`, so
an ordinary question tried to write a document and failed the turn if either
file could not be made. It now runs one turn through
`backend/playbook/chat.py`, which assembles history, attachments, exported
analyses and the selected working artifact and hands them to
`backend/playbook/assistant.py`.

**The assistant decides whether a turn needs a file, by calling a tool** —
`create_document`, `revise_document` or `convert_document`. Not a keyword
match, which cannot tell *write me the report* from *what would go in the
report?*, and not a second Generate click. `task`, `scope` and `formats` still
arrive from callers that know their own intent and travel as context, never as
a route.

**Delivery is per format.** `_usable` used to discard every provider-generated
file if any one format was missing or failed, and the turn failed if any file
failed any check. Each format is now its own outcome, and `Validation`
separates *integrity* (the file will not open — never delivered) from *content*
findings (a table count, a figure with no source — recorded, never blocking).

**The dashboard cannot destroy the document.** Adoption shared the version's
transaction. Versions and files now commit alone; `service.project_status` runs
afterwards in its own session and is not permitted to raise.

**One distinction the whole design turns on:** a document that could not be
written is a tool failure the conversation survives and explains; the *runtime*
failing — a timeout, a missing model, a stop — ends the turn.

## 3. How to verify it

```bash
scripts/playbook_dev_env.sh start                      # PostgreSQL 55432
.venv/bin/python -m pytest tests/playbook -q            # unit + route journeys
.venv/bin/python -m pytest -q                           # whole repository

# Browser, against a scripted assistant — no provider call:
PLAYBOOK_SCRIPTED_CHAT=scripts/acceptance/fixtures/scripted_chat.json \
  .venv/bin/python -m uvicorn backend.api.main:app --port 8001
.venv/bin/python scripts/acceptance/playbook_chat_acceptance.py
```

Counts at `5bb8d38`: Playbook suite green with 8 live checks skipped; workspace
browser acceptance **105 passed**; dashboard browser acceptance **185 passed**;
chat browser acceptance **15 passed**; `ruff` clean.

`scripts/acceptance/playbook_chat_acceptance.py` proves its own premise before
asserting anything — it reads `GET /playbook/capabilities` and fails if the
server is not scripted, so it can never pass by testing a refusal.

## 4. Starting it on the Mac

The isolated Playbook worktree, on its own ports. **The main CreditProbe
backend on 8000 is a different service and none of this touches it.**

```bash
cd ~/Desktop/IPM_V2-playbook-live
git fetch origin claude/creditprobe-playbook-plan-ky3m05
git switch claude/creditprobe-playbook-plan-ky3m05     # or: git pull

scripts/playbook_live.sh doctor      # what is configured; no value is printed
scripts/playbook_live.sh start       # 55432, then 8001, then 3000, then opens it
scripts/playbook_live.sh status
scripts/playbook_live.sh stop        # only what it started
```

| | |
|---|---|
| PostgreSQL | **55432**, isolated cluster |
| Playbook backend | **8001** |
| Frontend | **3000** |
| Open | `http://127.0.0.1:3000/playbook` |

Three things to know before the first run:

1. **The frontend build decides which backend it talks to.** Build it with the
   Playbook API's address or it will call 8000:
   `NEXT_PUBLIC_API_URL=http://127.0.0.1:8001/api/v1 npm --prefix frontend run build`
2. **`.env` in this repository sets `API_PORT=8000`** for the main backend. The
   launcher no longer reads its port from there — it was clobbering 8001 and
   starting Playbook on the other service's port.
3. **Generation needs `ANTHROPIC_API_KEY` and an author model.** Put them in the
   worktree's own `.env`, never in a browser bundle or a chat message. Without
   them every workspace, file, version and dashboard is still browseable and
   the composer says generation is unavailable rather than offering a button
   that fails.

The launcher stops only processes it started and never offers to kill whatever
holds a port; it does not reset, check out, stash or reseed anything. It is
written for macOS and was exercised on Linux — the first `start` on the Mac is
the first time those paths run there.

## 5. Budget

No paid call was made. Everything above is deterministic: the scripted provider
in `tests/playbook/conftest.py` for tests, `backend/playbook/scripted.py` for
the browser.

One outbound request did leave the process during development and must be
recorded: an early version of the test fixture supplied a fake credential so
the product's own configuration check would run for real, and a test that had
not scripted the call built a genuine client and sent a request. It came back
401, nothing was generated and nothing was spent. `provider._client` is now
replaced in tests by an object that fails loudly, so the suite cannot reach the
provider at all.

## 6. What is not done

Named rather than left to be discovered.

1. **Document Skills and code execution are not the default path.** Chapter 08
   prefers them for document-intensive work. They are implemented and remain
   behind `PLAYBOOK_SKILL_RENDERING`; the default is still the local renderer.
2. **Grounding still edits the document on the authoring path.** Chapter 16
   asks for that pipeline to be retired for ordinary drafting and for suspected
   issues to be recorded beside the draft instead. The assistant's own prose is
   never touched — that was fixed — but `author_document` still removes
   unsupported figures from the document it writes.
3. **Completion is still the old readiness engine.** Chapter 12's work-item
   plan — `100 × delivered required weights / active required weights`, and
   `Not applicable` when the denominator is zero — is not built.
4. **Nine of the twelve behaviours in §1 are proven at the route level but not
   in the browser**, and none live.
5. **The launcher has not run on macOS.**

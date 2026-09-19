# Playbook — Direct Chat: reuse/change table and implementation plan

Specification: `DIRECT_CHAT_MASTER_SPEC.md` (chapter numbers below refer to it).

Audited against the running branch, not against a remembered handoff.

| | |
|---|---|
| Branch | `claude/creditprobe-playbook-plan-ky3m05` |
| HEAD at audit | `cc16b9b` |
| Working tree | clean |
| Alembic head | `0040`, single |
| Database | isolated cluster, port 55432, `creditprobe_playbook_dev` + `_test` |
| Skills/code-execution | implemented, **off by default** — `PLAYBOOK_SKILL_RENDERING` opt-in |
| Provider credential | absent in this container; live verification blocked, non-live work is not |

---

## 1. What the audit found

### The path of one ordinary question

`POST /playbook/workspaces/{id}/messages` → `service.send_message` /
`service.run_generation` → **`service.author_document`** → `provider.author` →
`D.parse` → `grounding.check` → `validate` → `_persist`.

There is no other path. `run_generation` calls `author_document`
unconditionally (`service.py:864`), and `DEFAULT_FORMATS = ("docx", "pdf")`
(`service.py:50`). So *"What is the difference between a development and a
validation report?"* attempts to author a document and render a Word file and a
PDF, and fails the turn if either cannot be produced.

That is DC-01 failing by construction, and it is what chapter 04 names first:
*"Do not pre-route all messages into author_document or require a document
schema to answer a question."*

### Every point where the answer or a usable draft can be destroyed

Each is a real `raise` on the delivery path, in order. All of them discard the
model's completed work, including a draft that was already safe.

| # | Location | What it kills | Chapter it breaks |
|---|---|---|---|
| 1 | `service.py:432` — `if not doc.sections: raise` | Any reply that is not a document. A one-paragraph answer is an error. | 04 |
| 2 | `service.py:479` — `grounding.check(doc, ledger)` with `remove=True` | Sentences the assistant wrote, edited out before the user ever sees them. | 16 |
| 3 | `service.py:486` — `if not verified.ok: raise` | The entire turn, if removal did not converge. Nothing saved. | 16 |
| 4 | `service.py:497` — `emptied_sections → raise` | The entire turn, if removal hollowed a section. | 16 |
| 5 | `service.py:509` — `if not ground.ok: skill_files = {}` | Every provider-generated DOCX/PPTX, re-rendered through a thinner local writer. | 08 |
| 6 | `service.py:347` — `_usable`: *any* format missing or failed ⇒ discard *all* Skill files | A good Word file, because the PDF failed. | 08, DC-22 |
| 7 | `service.py:522` — `if any(not v.ok for v in validations): raise` | The entire turn, if one rendered file fails a derived-index check. | 16, DC-35, DC-36 |
| 8 | `service.py:590` — `adopt.adopt(...)` inside `_persist`'s transaction | The version **and its files**, if dashboard adoption fails. | 13, DC-27 |

Point 8 is the architectural one. The comment there states the intent plainly —
*"If that cannot be written, the version is not written either"* — which is
exactly the coupling chapter 13 requires be removed. The required degradation
test (chapter 13, DC-27) cannot pass while it stands: with the status service
failing, no file can be saved at all.

### What is genuinely good and must not be rebuilt

The repository already holds most of what the specification asks for. The work
is decoupling, not reconstruction.

---

## 2. Reuse / change table

| Component | Path | Decision | Why |
|---|---|---|---|
| Auth, tenancy, access checks | `backend/api/routers/playbook.py`, `repository.Scope` | **Reuse unchanged** | Ch. 26 keeps security. Every route already resolves a `Principal`. |
| Durable jobs, idempotency keys | `service.begin_generation`, migration `0040` | **Reuse unchanged** | Ch. 14/15 want exactly this. `0040` already scopes keys per workspace (DC-32). |
| Streaming + reconnect | `backend/playbook/stream.py`, `frontend/src/lib/stream.ts` | **Reuse unchanged** | Ch. 15. Replay, stop and refresh-without-duplicate already proven in browser acceptance. |
| Immutable versions, lineage, restore | `repository.new_version`, `PlaybookArtifactVersion` | **Reuse unchanged** | Ch. 10 asks for precisely this shape. |
| Source originals, checksums, re-read | `store.py`, `reparse.py`, `ingest/` | **Reuse unchanged** | Ch. 05 re-read rules already hold: immutable bytes, versioned readings (DC-10). |
| Export contract + picker | `backend/exports/playbook_contract.py`, `analysis-picker.tsx` | **Reuse unchanged** | Ch. 06. Multi-select surviving preview already passes (DC-05). |
| Scoped merge | `backend/playbook/merge.py` | **Reuse, narrow** | Ch. 10 explicitly endorses "proven scoped-merge capabilities". Keep for canonical documents; must not be the only edit path for provider-authored bytes (DC-19). |
| Local renderers | `backend/playbook/render/` | **Reuse, demote** | Ch. 08: stays for deterministic conversion and previews; must stop being the hidden sole authoring system. |
| Document Skills + code execution | `provider.author(document_tools=True)` | **Reuse, promote** | Ch. 08 prefers this path. Implemented but opt-in; becomes the default for document work, with the local renderer as declared fallback. |
| Dashboard computation | `backend/playbook/intelligence/` | **Reuse, relocate** | Ch. 11–13. The arithmetic is sound; it must move out of the write transaction. |
| Findings, decisions, Then/Now | `intelligence/governance.py`, `compare.py` | **Reuse, make optional** | Ch. 13: keep reachable through More details; stop making them mandatory. |
| `grounding.check(remove=True)` on the save path | `service.py:479` | **Change** | Ch. 16 retires this pipeline. Becomes review findings recorded beside the draft. |
| `author_document` as the only runtime | `service.py:362` | **Change** | Ch. 04. A conversation turn must be able to answer without authoring. |
| `_usable` all-or-nothing | `service.py:347` | **Change** | Ch. 08/DC-22. Per-format outcome, keep what succeeded. |
| `adopt.adopt` inside `_persist` | `service.py:590` | **Change** | Ch. 13/DC-27. Becomes an event consumer after commit. |
| Validation as a save gate | `service.py:522` | **Change** | Ch. 16. Split into security/integrity (hard), technical delivery (per-format), content review (never blocks). |
| Completion/readiness engine | `intelligence/readiness.py` | **Change** | Ch. 12 replaces the readiness score with a work-item plan: `100 × delivered required weights / active required weights`, `Not applicable` when the denominator is zero. |
| Tests asserting the old gate | `tests/playbook/test_save_gate_matrix.py` + matrix doc | **Change, documented** | Ch. 30: each superseded expectation is replaced with a stronger explicit one, never deleted or skipped. |
| What If / Project Planner | — | **No change** | Ch. 06: report as absent; do not merge another branch. |

### Nothing is deleted

Chapter 26 forbids destructive cleanup, and the existing dashboard carries real
seeded workspaces. No table is dropped, no workspace removed, no history
rewritten. Migrations are additive.

---

## 3. What changes structurally

```
BEFORE  send → author_document → parse → ground(remove) → validate-all
                → persist(version + files + dashboard) in ONE transaction
        any failure anywhere ⇒ nothing saved

AFTER   send → converse(tools available) → stream answer
                → persist answer                          (commit)
                → per-format file results, each stored     (commit each)
                → emit events
        events → status projection → dashboard             (separate, retryable)
        review findings recorded beside the draft, never gating it
```

Three independent outcomes per turn (chapter 07): the answer, each file, and
the status. A failure in one is reported as itself.

---

## 4. Milestones

| | Deliverable | Proof |
|---|---|---|
| **M0** | This table; spec saved to the repository | Both committed |
| **M1** | Conversation runtime that answers without authoring; attachments; dashboard failure injected | DC-01–DC-14, DC-27 partial |
| **M2** | Real Word/PDF/PPTX/XLSX through the chosen tool runtime; per-format partial failure | DC-15–DC-22, DC-34 |
| **M3** | Status sidecar as event consumer; work-item completion; Know the status | DC-23–DC-28 |
| **M4** | Deterministic repetition ×10 ×2, browser and artifact inspection, launcher, handoff | DC-29–DC-42 |

## 5. Rules held throughout

- No merge, no deploy, no PR, no force-push, no other branch.
- No paid provider call without a stated purpose and an agreed cap. Everything
  below M4's live smoke is deterministic, using the scripted provider and the
  real local file tooling.
- No destructive cleanup: no tree reset, no dropped tables, no reseed over real
  workspaces.
- A skip is never reported as a pass; the whole repository suite is what counts
  (chapter 31), not the Playbook subsets.

---

## 6. Superseded test expectations (chapter 30)

Each old expectation that changes because draft delivery is deliberately
decoupled from content governance is recorded here with what replaced it.
None was deleted, and none became an unexplained skip.

| Test | Was | Is now | Why |
|---|---|---|---|
| `test_context_bridge.py::test_a_generated_version_creates_its_section_rows` | `author_document` returns a populated `outcome.adoption`; section rows exist the moment the version is written | Renamed `..._does_its_dashboard_work_afterwards`. The delivery path does **no** dashboard work — `adoption == {}` and no section rows — and names what the projection owes. Running `project_status` then produces exactly the rows the old test demanded. | Ch. 13. Adoption shared the version's transaction, so a status failure destroyed the document. |
| `test_context_bridge.py::test_a_scoped_edit_leaves_the_untouched_section_alone` | Reads `second.adoption["sections_changed"]` inline | Projects each version after it commits, in order, then asserts the same list | Same. Made explicit that each version must be projected: skip one and the next compares itself against nothing. |

**Added, not replaced** — `TestTheProjectionCannotTakeTheDocumentWithIt`. The
case the old shape could not express, because it was not true: with
`adopt.adopt` raising, the version, its content and its Word file are all still
there, and the projection reports `ok: False` with the reason. Plus a vanished
version and an empty projection, which are reported rather than raised.

| `test_security.py::test_a_generation_that_fails_validation_writes_nothing` | Any validation failure destroys the turn and writes no version | Now simulates an **integrity** failure — the file will not reopen — and asserts the same outcome, on the error's category rather than its wording | Ch. 29 Table 7. A corrupt file is still never delivered. |

**Added, not replaced** — `test_a_content_finding_leaves_the_draft_downloadable`.
The other half of the same line, and the half that changed: a table count that
differs no longer destroys a good Word file. The draft is written, the file has
real bytes, `Validation.ok` is False and `Validation.sound` is True, and the
finding is surfaced in the outcome's notes rather than discarded.

---

### The same decoupling, in the harnesses

Found later, when the soak harness and the live check were run against the
current code rather than assumed to still fit it. Both were asserting the
pipeline that chapter 16 retired.

| Check | Was | Is now | Why |
|---|---|---|---|
| `scripts/playbook_soak.py::journey_a` | `outcome.grounding_final.ok` — the saved report is grounded | Two statements, both stronger: no figure was deleted from the delivered report, and each unsupported figure is recorded as a review item against a version sitting at `draft` | Ch. 16. The old check passed because `check(remove=True)` had DELETED the three figures the workbook alone does not support — so it was reading a hollowed document and calling it grounded. Restoring `remove=True` now fails it. |
| `scripts/playbook_soak.py::journey_a` | `outcome.adoption["sections"] == 3` | `cycle.projection["sections"] == 3`, after `Cycle.generate` projects each turn as production does | Ch. 13. Adoption no longer shares the version's transaction, so `outcome.adoption` is empty by design and a harness that reads it is asserting the old coupling. |
| `backend/validation/live_playbook.py::no_template_report` | `passed` required `grounding_final.ok` — a review finding withdrew the whole report | `passed` turns on sections, files, invented tests and the retention of 22.77. Findings are reported in full and prominently, and do not fail the check | Ch. 16 again. A live gate that withdrew the report over one unsourced figure would contradict the architecture it exists to verify. What still fails it: a report that cannot be read as a report, or the loss of a figure the evidence DOES support. |

**Removed, because it had stopped meaning anything** —
`AuthoringOutcome.grounding_final`, and the `attempted` / `saved` pair in the
stored `validation.grounding` record. They date from a two-stage pipeline
where the second was a re-check of a document that removal had edited.
Nothing is removed now, so both names held the same object and the audit row
implied a verification step that had not happened.

---

### The first live run (chapter 30, again)

| Check | Was | Is now | Why |
|---|---|---|---|
| `test_streaming.py::test_a_heartbeat_is_a_comment_and_carries_nothing` | The heartbeat is a bare `: keep-alive` comment carrying nothing | Renamed `..._reaches_the_client_rather_than_only_the_proxy`. The comment survives, a named `ping` event is added beside it carrying how long the worker has been quiet, and two further tests pin that an empty payload is still a valid frame and that a heartbeat carries no sequence number | Ch. 15. A correct SSE comment that every conforming parser discards — including this product's own — proved the connection was open to a proxy and to nobody else. The screen stayed frozen through seven-minute runs. |
| `assemble` returning `state` and `detail` | Two scalars, overwritten on every milestone | The ordered step log, with each step's server-measured offset. The scalars remain, because the status line still uses them | Ch. 15 asks for event-derived states; one unchanging line is not a state, it is the absence of one. The backend had persisted the ordered log all along and nothing read it. |
| `scripts/acceptance/*.py` naming `127.0.0.1:8000` | The backend port, written into the suite | The web origin, whose `/api` rewrite reaches whatever backend the running build is wired to | True only while the frontend happened to be built against 8000. The moment the launcher moved Playbook to its own port, the suite asserted against one backend while the browser under test used another. |

**Added, not replaced** — `TestADeclaredDocumentTaskMustProduceOne` and
`TestAPromiseWithNoToolCall`. The case the suite could not express, because
the scripted fixture decides whether a tool is called: a model that answers in
prose and calls nothing. The two replies the live model actually gave are in
the detector's parameter list verbatim.

**Added, not replaced** — `TestADifferentKeyIsStillNotASecondGeneration`. The
idempotency key was never the guarantee it was read as. It stops the same key
twice; the browser's key is positional, so the same sentence sent again gets a
different one, and nothing looked further.

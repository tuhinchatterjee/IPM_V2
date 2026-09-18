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

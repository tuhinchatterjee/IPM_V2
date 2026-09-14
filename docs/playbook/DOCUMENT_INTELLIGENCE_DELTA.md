# Playbook V3 — Document Intelligence: Phase 0 audit and delta

Base commit for this work: `89ba99f` on `claude/creditprobe-playbook-plan-ky3m05`.
Alembic head before this work: `0034`. New work starts at `0035`.

## What the audit found

**The chat-first workspace is whole and is not being replaced.** 14 Playbook
tables, 3 routes (`/playbook`, `/playbook/[id]`, `/playbook/library`), 7
components, 610 backend tests, 105 browser checks, six live-provider criteria
passing on `claude-opus-5`. Everything in §23's regression list exists today and
stays.

**Three primitives the dashboard needs do not exist at all.**

1. *Stable metric identity.* `backend/exports/playbook_contract.py` carries
   `Table` with `columns`, `units` and `precision`, and `Snapshot` with
   `scope`, `reporting_period` and `provenance` — but no metric id anywhere.
   §7's linking model has nothing to link *through*. This is the single
   biggest gap, and every downstream feature (Since Last Time, refresh,
   freshness, staleness) depends on closing it.
2. *Section identity that survives a version.* `PlaybookArtifactVersion.content`
   holds the canonical `Document`, and a section is addressed by heading text.
   Heading text changes when a section is retitled, so per-section status,
   reviewers and page ranges need a key that does not.
3. *Parse revisions.* `PlaybookSource` has `manifest`, `status` and
   `failure_reason`, and the bytes are stored immutably — but no parser
   version, no parse revision history, so §18's re-read cannot be governed or
   even detected.

**What is reusable and will be reused rather than rebuilt.**

| Need | Already exists | Where |
|---|---|---|
| Unit vocabulary and presentation precision | `COUNT / CURRENCY / PERCENT / PERCENTAGE_POINT / BASIS_POINT / RATIO / STATISTIC` and `DISPLAY_DP` | `backend/playbook/calc.py` |
| Raw vs displayed vs cell address for a spreadsheet fact | `rows` / `raw_rows` / `cells` | `backend/playbook/ingest/sheets.py` |
| Immutable bytes for re-read without re-upload | `store.put_source`, `PlaybookSource.bytes_path`, `retry_source` | `backend/playbook/{store,service}.py` |
| Scoped edit that provably touches one section | `merge.scoped_merge`, `unchanged_outside`, `section_hash` | `backend/playbook/merge.py` |
| Evidence ledger with locators | `evidence.Ledger`, `Item.locator` | `backend/playbook/evidence.py` |
| Immutable versions and lineage | `PlaybookArtifactVersion` | `backend/models/playbook.py` |
| Export identity and dedup | `analysis_export_revisions.content_hash` | migration `0032` |
| Deterministic figure classification | `validate.classify` | `backend/playbook/validate.py` |

**No prior committee-pack dashboard code exists in this repository or its
history.** `git log --all --diff-filter=D` finds nothing matching committee,
readiness, findings or pack. The screenshots referenced in the brief were not
attached to the message that requested this work, so the information
architecture below is built from the brief's written description (§6, §22),
not from the images. If the screenshots are supplied, the layout should be
re-checked against them before human UAT.

## Delta table

| # | Requirement (§) | Exists | Partial | Missing | Reuse | Implementation location |
|---|---|---|---|---|---|---|
| 1 | Chat-first home preserved (§1, §23) | ✅ | | | keep as-is | `app/playbook/page.tsx` |
| 2 | Document type / purpose classification (§2) | | | ✅ | `PlaybookWorkspace.document_family` | `playbook_document_profiles` |
| 3 | Know the Status entry point (§3, §14) | | | ✅ | thread header | `app/playbook/[id]` + `status/` |
| 4 | Document status header (§4) | | | ✅ | version + artifact rows | intelligence service |
| 5 | Readiness panel (§5) | | | ✅ | — | `playbook_readiness` |
| 6 | Overview / Pack tab (§6A) | | ✅ | | canonical `Document` sections | `playbook_document_sections` |
| 7 | Findings (§6B) | ✅ | | | — | `intelligence/governance.py` (Gate 6) |
| 8 | Decisions & Actions (§6C) | ✅ | | | change-set decision pattern | `intelligence/governance.py` (Gate 7) |
| 9 | Since Last Time (§6D) | | | ✅ | — | bindings + snapshots |
| 10 | Metric binding model (§7) | | | ✅ | `calc` units, sheets provenance | `playbook_metric_bindings` |
| 11 | Metric identity in exports (§7, §8B) | | | ✅ | `playbook_contract.Table` | contract `Metric` + `Table.metrics` |
| 12 | Upload updates tracked metrics (§8A) | | ✅ | | `sheets` raw/shown/cells | intelligence service |
| 13 | Document metric snapshots (§9) | | | ✅ | version immutability | `playbook_metric_snapshots` |
| 14 | Deterministic completion % (§10) | | | ✅ | — | `readiness.py` |
| 15 | Page count and statistics (§11) | | ✅ | | `validate` page count from PDF | `document_stats` |
| 16 | Sections tab with status (§12) | | ✅ | | `merge.section_hash` | `playbook_document_sections` |
| 17 | Committee experience (§13) | | | ✅ | — | profile + readiness |
| 18 | Chat ↔ dashboard bridge (§15) | ✅ | | | composer, `task_scope` | `intelligence/context.py`, `adopt.py` (Gate 8) |
| 19 | Governed refresh (§16) | | | ✅ | change-set approval pattern | refresh proposal |
| 20 | Freshness (§17) | ✅ | | | — | binding freshness + `reparse.summary` |
| 21 | Parser versioning / re-read (§18) | ✅ | | | immutable bytes, `retry_source` | `ingest/version.py`, `reparse.py` (Gate 9) |
| 22 | Save-gate regression matrix (§19) | ✅ | | | 19 defects have tests already | `SAVE_GATE_MATRIX.md` + `test_save_gate_matrix.py` (Gate 10) |
| 23 | Soak harness (§20) | | | ✅ | scripted provider | `scripts/playbook_soak.py` |
| 24 | Adversarial pass (§21) | | ✅ | | existing security suite | soak + adversarial tests |
| 25 | Auditability of every status (§26) | ✅ | | | — | append-only `history` + `readiness` explanation |
| 26 | AI vs human authority (§27) | ✅ | | | change-set approval | `require_person` + `SYSTEM_ACTORS` |

Legend: ✅ in the column that applies. "Partial" means a usable primitive
exists but the requirement is not met by it.

## Ordering, and why

The gates in §29 are followed in order, because each one is load-bearing for
the next: nothing can be linked before there is a metric identity to link
through (Gate 1), nothing can be scored before bindings exist (Gate 5), and no
soak test means anything before the things it exercises exist (Gate 11).

Two decisions taken here rather than deferred:

* **Metric identity is added to the export contract as an additive field**, not
  inferred from labels. §7 is explicit that a metric must never be bound by
  text similarity, and a contract that cannot carry an id makes rule 1 of the
  linking order unreachable. Existing exports without ids fall to rule 4
  (suggested, user-confirmed) or rule 5 (unlinked) — never to a silent guess.
* **Section identity is a stable key stored beside the canonical document**,
  not the heading text. A retitle is inside the scope of editing a section
  (`merge._renamed_target` already allows it), so status and reviewers must
  survive one.

## Gates 6 and 7 — findings, decisions and actions as governed objects

### Where the boundary is held

`backend/playbook/intelligence/governance.py` is the only writer of these
three tables' governed fields, and every formal act in it goes through
`require_person()`. That function refuses an empty actor and refuses any name
in `SYSTEM_ACTORS` — `system`, `claude`, `assistant`, `ai`, `bot`, `playbook`,
`creditprobe`, `model` — so the guard cannot be walked past by passing
"system" as though it were a person.

The rule is enforced in the service, not in the router, deliberately. A rule
enforced in a router is one a worker, a scheduled job or a future surface can
reach around. The routes in `backend/api/routers/playbook.py` pass the
caller's identity down and translate the refusal into 422; they decide
nothing. `_actor()` yields `""` for an unauthenticated caller, so an
anonymous request arrives at the guard with nothing to record and is refused
there.

What a model may do, and what it may not:

| Act | Claude | A person |
|---|---|---|
| Identify that a decision appears to be required | ✅ | ✅ |
| Draft the question, the options, a recommendation | ✅ | ✅ |
| Draft an answer to a finding (`draft_answer`) | ✅ | ✅ |
| Raise a finding from a rule, import, validation or change | ✅ | ✅ |
| Make a finding **blocking** | ❌ | ✅ |
| Accept, close or defer a finding | ❌ | ✅ |
| Move a decision to *ready for decision* | ❌ | ✅ |
| **Record** what the committee decided | ❌ | ✅ |
| Create actions from a decision | ❌ | ✅ |
| Mark an action complete | ❌ | ✅ |

`draft_answer` sets the answer text, attributes it to `claude`, and moves the
status **nowhere**. That separation is the point: a drafted answer is visible,
reviewable and attributable, and it disposes of nothing. `unresolved()`
therefore counts open **and** answered findings — a drafted answer nobody
stood behind is still an open question.

### An AI suggestion never silently becomes a blocker

`MAY_AUTO_BLOCK` is `{rule, validation, change_detection}`. A finding raised
with `blocking=True` from any other origin — `ai_suggestion` above all — is
created **not blocking**, and the downgrade is written into the audit entry
with its reason rather than dropped. A person can then make it blocking
through `set_blocking`, which records who did so and why.

### The audit trail §26 asks for

Every governed row carries `history`: an append-only list of
`{at, act, field, from, to, actor, reason}`. It is appended by one private
function, from the same call that makes the change, inside the same
transaction. Nothing rewrites or reorders it, and no route exposes it for
writing. A finding that was raised by a rule, assigned, answered, and deferred
reads back exactly as those four acts, each with the person who performed it.

### The planner seam

`export_payload()` produces what a Project Planner would need; `record_export`
notes where an action now also lives; `read_back` records what the external
system says **in its own column**. An external "done" never moves
`action.status`. Playbook is complete without a planner, and nothing here
imports or depends on one.

### The schema defect this gate found

`0035` gave `playbook_decisions.status` sixteen characters and defaulted it to
`outstanding`. §6C's vocabulary includes `ready_for_decision`, which is
eighteen — so moving a decision to the one status from which it can be
recorded raised `StringDataRightTruncation` at the database. And
`outstanding` is not one of the five statuses, so a row created without an
explicit status landed in a state the transition table refuses to move out of:
a decision that could never be recorded.

`0039` widens the column to 32 and moves the default to `proposed`, migrating
any stored `outstanding` row. The vocabulary was not shortened to fit the
column: the status is read by people and named in the specification, and a
column width is not a reason to call a thing something else.

### Verified

* `tests/playbook/test_governance.py` — 75 tests: the actor guard on every
  formal act, origin handling and the blocking downgrade, answered-is-not-
  accepted, the finding and decision and action transition tables, evidence
  attachment, the audit trail's contents and its append-only behaviour,
  readiness coupling, the planner seam, and idempotence across a restart.
* `tests/playbook/test_api.py::TestGovernedObjectsOverHttp` — 21 tests: that
  the routes create no way around the service rules. A request body cannot
  name a different actor or claim a non-human origin; the decision status
  route cannot reach `decided`; a governed row from another workspace is 404
  even for a caller who can see both.
* `tests/playbook` — 875 passed, 8 skipped (the live checks, which skip
  without a credential rather than passing).
* `tests/api tests/exports tests/docs tests/demo tests/services` — 747 passed.
* `0039` applied, downgraded to `0038`, re-upgraded. Single head.
* `ruff check .` clean.

No provider call was made by anything in this gate.

## Gate 8 — the dashboard is not a separate dead screen

### The gap this found first

Gates 4 and 5 built section rows and metric snapshots, and gave them careful
rules: identity that survives a retitle, a sign-off that reopens when the text
it covered moves, a frozen reading that is never rewritten. **Nothing called
them.** `sections.sync` and `compare.freeze` had no caller outside their own
tests, so a document generated through the real authoring path produced no
section rows and froze no readings. The dashboard beside it described a
workspace nobody had written to.

§15 asks that the dashboard refresh when Claude finishes. It cannot refresh
from state that was never recorded, so that is where Gate 8 starts.

`backend/playbook/intelligence/adopt.py` is the one call the authoring path
makes, from `service._persist`, **in the generation's own transaction**. A
version whose section rows were never written is a document the dashboard
misdescribes — sections missing from the Pack, a sign-off still standing
against text that has moved, no THEN for the paper in front of the reader.
That is worse than a failed generation, which the user can simply run again.
So it is not wrapped in a swallow: either the document and the state that
describes it both exist, or neither does.

It reports what it changed rather than leaving a caller to diff:

```
{"version": 2, "sections": 12,
 "sections_changed": [{"key": "executive-summary-1",
                       "heading": "1. Executive summary"}],
 "reviews_reopened": [...], "metrics_frozen": 6}
```

That payload rides on the assistant message, on the synchronous return, and on
the stream's `done` event — so a client re-reads because something moved,
not on a timer, and knows which sections lost their sign-off.

One defect the tests caught in the reporting itself: "reopened" was written as
*left the human-only statuses*, and `needs_review` is itself one of those —
which is exactly where a reopened section lands. It reported nothing, every
time. The event is losing an approval, and it is now written that way.

### The bridge

`backend/playbook/intelligence/context.py` turns any dashboard object into a
chat context. Three things travel, and they are different on purpose:

* **the prompt** — what the user sees in the composer and may rewrite before
  sending. A starting point, never a hidden instruction;
* **the task and scope** — the existing framing machinery. "Update this
  section" resolves to `task="edit"`, `scope=<heading>`, which is the scoped
  merge that already refuses to touch anything else. Gate 8 adds no new
  editing path;
* **the references** — `{kind, id, label, value, locator, governed}` per
  object, recorded on the user's message, so reopening the thread a month
  later still shows which finding "draft an answer to this" meant.

| Click | Action | Framing |
|---|---|---|
| a metric | Ask Claude about this | — |
| a finding | Draft an answer | — |
| a section | Update this section | `task=edit`, `scope=<heading>` |
| Since Last Time | Explain these movements | — |
| a decision | Draft the committee recommendation | — |
| stale metrics | Refresh affected sections | — |

### The rule that governs it

A context supplies **governed facts only**. An unconfirmed metric suggestion
produces a caveat for the person — *"a suggested link that nobody has
confirmed"* — and contributes nothing to the evidence ledger. This is the same
rule that keeps a suggestion out of THEN/NOW, for the same reason: a guess that
travels far enough from where it was made stops looking like a guess. A
suggestion must not become a citable figure by going through the composer.

"Refresh affected sections" is governed the same way. Only a **governed**
binding whose freshness is `new_data_available` or `stale` counts; `unknown` is
deliberately excluded, because not knowing whether something moved is not
evidence that it did. The context names the affected sections and says plainly
that nothing is rewritten by it.

The context is rebuilt at generation time rather than carried through the job
payload, so a generation that starts a minute later sees the dashboard as it
is, not a copy the browser held. A context that has since vanished does not
fail the turn: the question still stands and is still answerable, and what it
loses is the evidence the dashboard would have supplied.

### Verified

* `tests/playbook/test_context_bridge.py` — 29 tests: adoption writes section
  rows from a real generation, reports changes and reopened sign-offs, freezes
  only governed readings and never twice; a governed metric supplies its
  reading as citable evidence while a suggestion supplies none; a section
  context carries the existing edit framing; a stale suggestion is not a reason
  to refresh; references survive on the message; a vanished context does not
  fail the turn.
* `tests/playbook/test_api.py::TestTheContextBridgeOverHttp` — 6 tests,
  including that the offered actions reflect real state and say why one is
  withheld.
* `tests/playbook` — 910 passed, 8 skipped.
* `tests/api tests/exports tests/docs tests/demo tests/services tests/llm` —
  764 passed, 8 skipped.
* `ruff check .` clean.

No migration was needed: references live on the message's existing `content`
JSONB, because a reference is part of what the turn said rather than metadata
about it. No provider call was made by anything in this gate.

## Gate 9 — a better reader is a reason to read again, never to re-upload

### The state before

`playbook_source_parses` existed from Gate 1 and had never been written to.
There was no parser version anywhere in the codebase, so "this file was read
by an older reader" was not a statement the system could make — only a
suspicion somebody might have. `retry_source` re-read stored bytes, but only
as recovery from a failure; nothing knew that a successful old reading might
now be a worse one.

### What a version means, and when to bump it

`backend/playbook/ingest/version.py` declares a reader version per format and
one `SCHEMA_VERSION` spanning all of them. The rules are written into the
module because a version nobody maintains is decoration:

* **bump when the OUTPUT can differ** — different chunks, locators, `data`, or
  manifest. A refactor that cannot change what comes out is not a version
  change, and pretending otherwise asks every user to re-read every file for
  nothing;
* **never re-use a number** — it is recorded on parses that already exist and
  cannot be corrected retrospectively;
* **`SCHEMA_VERSION` is separate** — it moves when the SHAPE of a chunk
  changes, not when one reader gets better. A parse is stale if either is
  behind.

The one real bump today is XLSX/CSV → 2: spreadsheet cells are read three ways
(as displayed, as stored, by address). That is the change that made a report
stop printing seventeen significant digits to survive grounding, and
`CHANGES` says so in words a user can act on, shown beside the stale source so
"re-read" is a decision rather than a leap.

Only **behind** counts as stale. A parse recorded by a newer version than this
code knows about — a database restored from a later deployment — is left
alone rather than re-read backwards into a worse reading. An unparseable
version counts as stale, because the alternative is silently trusting a
reading whose provenance cannot be established.

### Staleness is computed, not stored

A source is stale when its latest parse names a version behind the one in
force. That comparison is made when asked, so deploying a better reader marks
the affected sources without a migration and without a background job
rewriting rows.

A source with **no** parse revision is stale too, with its own reason. Its
reading exists, but nothing records which reader produced it, and a reading
whose provenance cannot be established is not one to keep quoting. Re-reading
it is free and settles the question.

### A stale source cannot be used silently — §19 item 13

A source read by an older reader is evidence read **worse than it can be**:
not missing, but not a complete reading either. `ledger_for` records it as an
evidence gap, so `evidence_complete` is False and the thread says so, until
the source is re-read. The source is still read — a worse reading is still a
reading, and withholding it would replace a stated caveat with a silent
absence, which is the worse failure.

### What a re-read is not

No upload, no provider call, nothing billable. It replaces the CHUNKS the next
generation will draw on, and nothing else. **A report already written is not
rewritten because its source was read again** — §16's governed refresh is
where that decision belongs, and it is a person's. Every earlier revision is
kept and marked superseded, so a document generated three months ago can still
be traced to the reading it was actually written from.

`RE-READ ALL STALE SOURCES` re-reads each in turn; one file whose bytes are
gone is reported and the rest are still brought up to date.

### Verified

* `tests/playbook/test_reparse.py` — 31 tests: every readable format declares
  a version; same is not stale, older is, newer is left alone, unparseable
  counts as stale; upload, retry and re-read each record a revision; a partial
  read is recorded as partial and a failed one as failed; a source with no
  revision is stale for its own reason; a re-read uses stored bytes, makes a
  new revision, supersedes rather than deletes, reaches no provider (asserted
  by making `provider.author` raise) and creates no document version; missing
  bytes and a foreign tenant are both refused; the workspace count is the line
  the dashboard shows; a stale source is an evidence gap, is still read, and
  re-reading closes the gap.
* `tests/playbook/test_api.py::TestReReadingSourcesOverHttp` — 8 tests,
  including lineage over HTTP and the dashboard's source line.
* `tests/playbook` — 949 passed, 8 skipped.
* `tests/api tests/exports tests/docs tests/demo tests/services tests/llm` —
  764 passed, 8 skipped.
* `ruff check .` clean.

No migration: `playbook_source_parses` was built in `0035` and is now used for
what it was built for.

## Gate 10 — a matrix that cannot drift from the code

`docs/playbook/SAVE_GATE_MATRIX.md` carries §19's nineteen failure classes,
each with the layer it lives in, the test that reproduces the original failure
in its original shape, and what is expected instead.

The interesting part is the check beside it. `test_save_gate_matrix.py`
resolves every node id in the table against the **source** — file, class,
function — and fails if any of them has been deleted, renamed, or quarantined
with `skip`, `skipif` or `xfail`. It also pins the failure-class list
independently of the table, so deleting a row fails the check rather than
shrinking the requirement to fit; that the tests are spread across at least
seven files, so the matrix cannot become one test's neighbourhood; and that
every named test lives in `tests/playbook`, so one run exercises all nineteen.

What it deliberately does **not** do is claim to verify that the tests pass.
A check that read PASS out of a Markdown table would be exactly the document a
reader trusts instead of counting. The status column is a claim about the last
recorded run, stated with its counts in the matrix's own Evidence section; the
mechanical check proves only that each row points at something real and still
running.

Running the nineteen named nodes directly: **38 tests** (parametrised cases
expand), 0 failed. No new production code was needed — every class already had
a test, which is what Gates 1–9 were for; what was missing was the thing that
stops one of them quietly disappearing.

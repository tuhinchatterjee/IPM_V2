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
| 18 | Chat ↔ dashboard bridge (§15) | | | ✅ | composer, `task_scope` | context refs |
| 19 | Governed refresh (§16) | | | ✅ | change-set approval pattern | refresh proposal |
| 20 | Freshness (§17) | | | ✅ | — | binding freshness |
| 21 | Parser versioning / re-read (§18) | | ✅ | | immutable bytes, `retry_source` | `playbook_source_parses` |
| 22 | Save-gate regression matrix (§19) | | ✅ | | 19 defects have tests already | matrix doc + suite |
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

# Playbook — architecture

The Playbook is CreditProbe's committee pack intelligence system. It runs the
full lifecycle of a governed committee pack: what the committee is, when it
meets, whether the data is there, what the pack says, who reviewed it, who
signed it, what was decided, what follows, and what happens to that before
the next meeting.

This document is about how it is built and why. What it does for a reader is
`PLAYBOOK_USER_GUIDE.md`; what was verified is
`PLAYBOOK_COMMITTEE_INTELLIGENCE_REPORT.md`.

---

## 1. The one idea

A committee pack is a **governed document with frozen figures**.

Every number on a pack is a SNAPSHOT — a row in `playbook_snapshots` carrying
the value, the display string, the formula hash, the metric version, the
dataset version, the numerator, the denominator, the rows considered and the
run id it came from. A pack renders from its snapshots and never recalculates
on open.

That single decision produces most of the rest of the design:

* The pack tabled on Tuesday morning and the screen opened on Thursday
  afternoon show the same numbers, because both read the same rows.
* An approved pack is a historical record that can be re-read years later,
  because the figures it was approved with are still there.
* "Where did that number come from?" is answerable from the pack alone.
* Regenerating is an explicit act with a version bump behind it, not a side
  effect of somebody opening a page.

The alternative — a pack that queries live — produces a document that means
something different every time it is opened, which is not a committee pack.

---

## 2. The modules, and what each one refuses to do

```
backend/playbook/
  access.py       the single authorisation door
  snapshots.py    freezing a governed figure, and classifying its absence
  materiality.py  declared thresholds → findings   (no LLM)
  readiness.py    can this pack go to committee, and what is stopping it
  generation.py   one operation, four ordered effects
  service.py      committees, templates, packs, sections, blocks, reviews
  findings.py     answering what was raised, and refusing to bury it
  actions.py      decisions, actions, and the bridge to the Planner
  narrative.py    AI drafting, with every sentence typed and grounded
  compare.py      this pack against the previous approved one
  monitor.py      the committee sweep: who is waiting on whom
  export.py       PDF, Word, PowerPoint, evidence workbook
  import_.py      reading somebody's existing pack in, labelled as theirs
  agent.py        the agent tool surface over all of the above
  demo.py         three seeded committees, and rolling their dates forward
```

### `access.py` — one door

Every read and every write goes through it. There is no second path.

```python
grant = access.writable_pack(session, pack_id, principal, CONTRIBUTOR,
                             "add a section to this pack", source)
```

A `Grant` carries the committee, the user, the effective access level, the
business role, whether the actor is administrative, and **the source** — which
door the call came through.

Three properties matter:

**A pack you may not see is `PackNotFound`, not `PackDenied`.** A 403 confirms
the object exists. Not-found says nothing.

**Authorisation walks back to the committee from every child object.** A
finding id, a block id, a snapshot id and an action id are all resolved to
their pack and then to their committee. An id is never a capability.

**The AI ceiling is not the AI protection.** An AI-sourced grant is capped at
EDITOR, but `REVIEWER` sits BELOW `EDITOR` in the access ranking, so the cap
alone still satisfies `at_least(REVIEWER)`. What actually refuses an agent is
the explicit `refuse_ai(grant, operation)` check inside each operation, against
`AI_FORBIDDEN` — thirteen named operations an agent may never perform whatever
its access. Placed inside the service function rather than at the tool
boundary, so a tool added later, or an orchestrator calling the service
directly, still cannot reach past it.

### `snapshots.py` — five ways to have no number

`classify()` decides which of five facts applies, asking the most specific
question first:

| Availability | What it means | What a reader should do |
|---|---|---|
| `OK` | there is a value | read it |
| `PERIOD_MISSING` | that period was never loaded | ask the data steward |
| `NOT_MATURED` | the performance window has not closed | come back next quarter |
| `NO_DATA` | the population is empty | check the filter |
| `CALCULATION_FAILED` | something is broken | raise it |
| `NOT_AUTHORISED` | you may not see the source | request access |

The ordering was a defect: the zero-denominator check originally shadowed the
maturity check, so an immature cohort reported `NO_DATA`. Both sentences were
true; only one told somebody when to come back.

`display()` produces the rounded string ONCE and stores it on the snapshot.
The screen, the PDF, the workbook and the deck all render that string. Two
renderers each formatting the same float is how a pack says 14.1% on the page
and 14.08% in the appendix.

### `materiality.py` — thresholds, not judgement

A finding is raised by a **declared rule** in the committee's template:

```python
{"key": "retail_default_rate_band", "metric_id": "retail.default_rate",
 "comparison": "above", "threshold": 7.0, "severity": "HIGH",
 "finding_type": "THRESHOLD_BREACH"}
```

Seven comparisons: `absolute_change`, `relative_change`, `above`, `below`,
`outside_band`, `unavailable`, `stale`. The engine evaluates them against
governed figures. No language model decides whether something is material,
and the finding carries the rule key and the numbers it fired on so a reader
can disagree with it.

An `Observation`'s fingerprint is derived from `rule_key|metric_id|period` and
**not from the value**, so a finding somebody has already answered is not
raised again as a new one when the figure moves slightly.

### `generation.py` — one operation, four ordered effects

```
generate(pack) →  1. calculate every governed figure, once per key
                  2. mark prose stale where its section's figures moved
                  3. evaluate materiality, upsert findings by fingerprint
                  4. refresh readiness
```

Ordered because each depends on the last. Step 2 is deliberately
section-scoped: a paragraph goes stale when a figure IN ITS OWN SECTION moved,
not when anything anywhere moved, because the second rule marks the whole pack
stale on every run and people stop reading the flag.

### `readiness.py` — eight checks, and blocking is a property of the check

| Check | Weight |
|---|---|
| schedule | 5 |
| data | 25 |
| content | 30 |
| narrative | 10 |
| findings | 10 |
| decisions | 5 |
| actions | 5 |
| review | 10 |

A percentage is not the gate. `may_submit_for_approval()` reads the BLOCKING
reasons, so a pack at 96% with one unanswered critical finding cannot go, and a
pack at 70% with nothing blocking can. A check that could not be RUN records
`not_assessed` rather than scoring zero — "no data steward has published this
period yet" and "this check failed" send the pack owner to different people.

### `narrative.py` — the AI, and what it is allowed to say

An AI drafts commentary. Three things constrain it:

**Typed sentences.** Every sentence comes back as `FACT`, `INFERENCE`,
`RECOMMENDATION`, `OPEN_QUESTION`, `NOT_RECORDED` or `DATA_LIMITATION`. A
reader who cannot tell a fact from a reading is being asked to trust the wrong
thing.

**Grounding.** Every number in the draft must appear in the evidence the model
was given. A sentence carrying an ungrounded figure is REFUSED and reported,
not silently dropped. Numbers 0–12 and years 2000–2100 are free, because
"three of the five vintages" is prose rather than a claim.

**The prompt's inputs.** Built from governed figures and the section's own
configuration. Imported document text is NOT an input. That is why prompt
injection in an uploaded pack is contained: the planted instruction is
imported, stored and shown to a reader labelled as theirs, and is simply not
in the prompt. Architecture rather than a filter — a filter is something
somebody eventually gets past.

An AI draft lands with `ai_accepted = False`. It does not reach the export
and cannot be approved until a person edits or accepts it, which is a named
act recorded in the history.

### `actions.py` — the Planner is the source of truth on work

A committee action LINKS to a `planner_tasks` row and reads its live state on
every request. It does not copy the percentage. Two systems each holding a
progress field is two systems that will eventually disagree, and the one read
out in a meeting is the one on the pack.

`PlaybookAction` holds the GOVERNANCE record — which committee asked, off
which decision, in which pack, and what evidence closed it. `progress_of()`
reads the Planner. The task is created through the Planner's OWN service, so
its access rules, its code validation and its own event record all apply.

When a Planner task is deleted the FK is `ON DELETE SET NULL`, which would
make the action read as never-sent. The surviving `linked_at` is used to say
so instead: "the Planner task this action was sent to has been deleted".

### `import_.py` — reading somebody's pack in

Checked in this order, refusing as early as possible:

1. size (40 MB), before anything is parsed
2. extension — a format nothing can read is refused by name
3. **magic bytes** — the extension is a claim, the bytes are the fact
4. for a zip-based format, the sizes the **central directory declares** — a
   zip bomb is refused without decompressing anything

Everything produced is labelled: prose becomes a `NARRATIVE` block typed
`NOT_RECORDED` with import class `IMPORTED_TEXT`; a table becomes an
`UNMAPPED_TABLE`, which is the one calculated block allowed to name no metric
BECAUSE CreditProbe did not calculate it. `import_class` is not writable
through a generic block update — a caller who could set it could relabel their
own typed figures as something the platform calculated.

The file is stored under a path derived from its checksum, never its filename.

### `export.py` — four formats, one source

PDF, Word, PowerPoint and an evidence workbook, all built from the same
`document()` model, all reading the frozen snapshots.

Excel formula injection is answered by a leading apostrophe on writing, not by
cleaning the data: `-0.4pp on the quarter` survives as itself, and `=cmd|...`
becomes text. A defence that quoted every figure would turn them into text
nobody can sum.

Titles are ESCAPED on output rather than filtered on input, so
`<Finance> Review` is stored as the person typed it and reaches reportlab's
mini-HTML parser as `&lt;Finance&gt; Review`.

Every download writes an `ExportRecord` naming the person, the checksum, the
size, and — in `detail` — every figure the file held with its metric id,
period, display value, availability, formula hash and run id. "Which figures
did that file contain?" is answerable without regenerating it, which would
answer with today's numbers anyway.

---

## 3. What it reuses rather than rebuilds

The instruction was explicit: do not create a second version of infrastructure
CreditProbe already owns.

| Concern | Reused |
|---|---|
| Users and roles | `backend.db.models.User`, `backend.api.permissions` |
| Metric definitions and calculation | `backend.metrics.*` |
| Charts | `backend.reporting.charts` (two generic renderers added) |
| PDF and Word | `backend.reporting.writers` |
| Notifications | `backend.models.platform.Notification` |
| Export audit | `backend.models.platform.ExportRecord` |
| Background jobs | `backend.agentic.queue` / `worker` |
| Delivery work | `backend.planner.service` |
| AI provider | `backend.ai.*` |
| Demo reset | `backend.demo.workspace` |

The only new tables are the fifteen `playbook_*` ones, and the only new metric
concept is the snapshot — which is a FREEZE of a metric result, not a second
way to calculate one.

---

## 4. The data model

Fifteen tables, migration `0039`.

```
playbook_committees ─┬─ playbook_members
                     ├─ playbook_templates          (versioned; old rows never edited)
                     └─ playbook_packs ─┬─ playbook_sections ── playbook_blocks
                                        ├─ playbook_snapshots   (the frozen figures)
                                        ├─ playbook_findings
                                        ├─ playbook_decisions ── playbook_actions
                                        ├─ playbook_reviews
                                        ├─ playbook_versions
                                        ├─ playbook_events      (append-only)
                                        ├─ playbook_reminders
                                        └─ playbook_sources
```

Three columns carry most of the governance:

**`source`** on every write-bearing row and every event: `UI`, `API`, `AI`,
`AI_CHAT`, `IMPORT`, `SYSTEM`. Decided by which code path is executing, never
read from a request body.

**`import_class`** on blocks and sources: whether this is CreditProbe's number
or somebody's file.

**`demo_origin`** and **`demo_anchor_date`**: what the seed built, and the day
its relative dates were relative to.

---

## 5. Concurrency

Optimistic, on `pack.version`. A caller may pass `expected_version`; if the
pack has moved, the refusal NAMES who moved it:

> This pack was changed by Omar Nasser since you opened it.

Last-write-wins on a document three people are editing an hour before a
committee is how somebody's section disappears.

---

## 6. Amendment, not edit

An APPROVED or PUBLISHED pack refuses every write with `409 pack_locked`.
Correcting one raises an AMENDMENT: a new pack that supersedes the approved
one, which stays exactly as it was approved. Carried-forward blocks lose their
snapshots and are recalculated, because a figure carried into a new pack
without being recalculated is a figure whose period label no longer matches
its value.

A historical record that can be edited is not a record.

---

## 7. The agent surface

`agent.py` exposes ten read tools and three writer tools, registered in the
platform's existing tool registry. Every handler passes `source=SOURCE_AI`.

`agent.FORBIDDEN` and `access.AI_FORBIDDEN` must contain the same thirteen
operation names — asserted in `tests/playbook/test_import.py`, because a name
in one and not the other is either a promise with no enforcement or an
enforcement nobody documented.

An agent may: read committees and packs, read figures and their working, read
findings, decisions and actions, draft commentary, draft a decision paper,
draft an action.

An agent may never: approve a pack, approve a section, publish, record a
review, decide, close an action, dismiss a finding, change a committed meeting
date, edit a formula, edit an approved pack, delete a pack, delete a section,
import a document.

---

## 8. The frontend

```
frontend/src/
  lib/playbook-format.ts            the presentation rules, as pure functions
  components/playbook/parts.tsx     rendering, and nothing else
  components/playbook/*.tsx         the panels
  app/playbook/**                   the screens
```

The rules are in a pure module with their own tests so the next person to tidy
up a figure cell cannot quietly turn an immature cohort into `0.0%`.
`figureReading()` has three outcomes and no fourth — a value, a NAMED absence,
or "not yet calculated" — and there is deliberately no branch that produces an
empty string or a bare dash.

Movement is read in the direction the METRIC cares about, from
`higher_is_better`, so a rising default rate is bad and a rising coverage ratio
is good without the screen knowing anything about either metric.

Panel failures use `<Unavailable>`, which tells a refusal apart from a fault: a
Viewer correctly refused should not be told the product is broken.

---

## 9. Where the boundaries are

Things this system deliberately does NOT do:

* **Calculate metrics.** It asks `backend.metrics` and freezes the answer.
* **Decide materiality.** Thresholds are declared in the template.
* **Hold delivery work.** Actions link to the Planner.
* **Store user identity.** It reads the platform's users.
* **Render its own PDF or Word.** It builds a content model for
  `backend.reporting.writers`.
* **Let an AI assert a number.** Grounding refuses ungrounded sentences.
* **Let anything edit an approved pack.** Amendment supersedes.

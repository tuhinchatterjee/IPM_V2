# Playbook — demonstration runbook

How to set the Playbook up for a demonstration, what to show, in what order,
and what to say when somebody asks the hard question.

---

## 1. Setting it up

```bash
# The people. Creates only what is missing; never overwrites a password.
python scripts/seed_demo_users.py

# The three committees, their templates, and two packs each.
python scripts/seed_playbook_committees.py

# What is there, without changing anything.
python scripts/seed_playbook_committees.py --check
```

**Every morning of a demonstration**, roll the dates forward:

```bash
python scripts/seed_playbook_committees.py --refresh-dates --dry-run   # see it
python scripts/seed_playbook_committees.py --refresh-dates             # do it
```

Idempotent: run twice on one day and the second run writes nothing. Safe to
put in a start-up script.

It moves only `meeting_at` and `data_freeze_at`, and only on committees the
seed built. Content, status, findings, decisions, actions and history are
never touched — and a meeting date somebody MOVED THEMSELVES is held back and
reported, because that is a commitment to other people's diaries.
`--force-demo-dates` overrides that and says so.

**Rebuilding from scratch** (removes the three committees and their packs):

```bash
python scripts/seed_playbook_committees.py --reset
```

Guarded: refuses unless Synthetic Data Mode is on or `ENV` is
dev/development/test/demo/local.

---

## 2. What is seeded

| Committee | Meets | Reads | Previous pack | Current pack |
|---|---|---|---|---|
| Retail Credit Risk | monthly | monthly | **published** | **in review**, findings open |
| Corporate Credit | quarterly | quarterly | **published** | **draft**, finding open |
| IFRS 9 Impairment | quarterly | quarterly | **published** | **published** |

Three committees rather than one, at three different points in the cycle, so
the three of them together show the whole lifecycle rather than one screen
three times.

**Every figure is calculated against the real lake.** Nothing is typed in.
The findings are whatever the declared thresholds actually produced — twelve
across the six packs, each carrying the rule that raised it and the numbers it
fired on.

### The log-ins

| Username | Password | Plays |
|---|---|---|
| `alex.rahman` | `creditprobe-demo` | chair / approver on all three |
| `omar.nasser` | `creditprobe-demo` | owns the retail pack |
| `sarah.khan` | `creditprobe-demo` | owns the corporate pack |
| `ahmed.saleh` | `creditprobe-demo` | owns the IFRS 9 pack |
| `sara.qahtani` | `creditprobe-demo` | data steward |
| `layla.haddad` | `creditprobe-demo` | observer — read-only |

---

## 3. The twenty-minute walkthrough

### A. The landing screen — 2 minutes
`/playbook`

Three committees, the open packs with their readiness beside them, and the
chase panel: who you are waiting on.

> "This screen sends nothing. It shows what the sweep WOULD send. A screen that
> notified everybody it named would be one nobody could open."

### B. The pack — 4 minutes
Open the retail pack in review.

Show the KPI, then press **Working**.

> "Formula hash, metric version, dataset version, run id, numerator,
> denominator, rows considered. This is what makes the number defensible
> rather than asserted. And these are FROZEN — the pack tabled on Tuesday and
> this screen on Thursday show the same figure, because both read the same
> row."

### C. The honest absence — 2 minutes ← **the most important two minutes**

On the retail pack, change the period to **2025-04** and regenerate.

The retail lake holds rows through 2025-07, but the default rate is an OUTCOME
metric whose performance window has not closed for anything after 2025-01 —
which is exactly the situation a real committee is in when it reads a recent
month.

> "The default rate does not show 0.0%. It says *not yet matured*, and it says
> why. There are five different ways to have no number here — not matured, no
> data, period not loaded, calculation failed, not authorised — and they send
> you to five different people. A dash makes them all the same afternoon."

### D. The AI, and what it may not do — 4 minutes

Press **Draft commentary** on a section.

> "Every sentence comes back typed — fact, inference, recommendation. And every
> number in it is checked against the pack's own figures. If the model writes a
> figure the pack does not support, that sentence is refused and reported, not
> quietly dropped."

Then point at the label:

> "It says *AI draft — not accepted*. It does not go into the export and the
> pack cannot be approved while it sits there. A person editing it or pressing
> Accept is them saying the words are theirs, and that goes on the record with
> their name."

If asked what else it cannot do:

> "Thirteen operations. It cannot approve a pack, approve a section, publish,
> record a review, decide, close an action, dismiss a finding, move a committed
> meeting date, edit a formula, edit an approved pack, delete a pack, delete a
> section, or import a document. And that is refused inside the operation, not
> at the tool boundary, so a tool somebody adds next year still cannot reach
> past it."

### E. A finding — 3 minutes
Open **Findings**.

> "This was raised by a declared threshold in the committee's template — not by
> a model deciding something looked important. It shows the rule that fired and
> the numbers it fired on, so you can disagree with it on the evidence."

Press **Answer**, then scroll to **Dismiss**.

> "Dismissing is the only answer that takes something off the committee's list,
> so it needs a written reason and reviewer access, and it goes on the record
> with a name and a date. And an assistant can never do it, whatever access the
> person driving it holds."

### F. Approval, and what it makes — 3 minutes
Open the IFRS 9 published pack and try to edit it.

> "Read-only. Every write route refuses it. To correct an approved pack you
> raise an amendment, which supersedes it — the approved pack stays exactly as
> it was approved, because a historical record you can edit is not a record."

Then **Since last time**:

> "The comparison against the previous approved pack, with redefinitions first.
> A metric whose formula changed has a movement that is not a movement in the
> business, and putting that at the bottom of a list of real changes is how a
> committee misreads it."

### G. Decisions and actions — 2 minutes
Open **Decisions & actions**.

> "The decision, with what was actually decided, by whom, when. And the action
> that followed it — which links to the Project Planner and reads its progress
> from there every time you look. It does not keep a copy of the percentage.
> Two systems each holding one will eventually disagree, and the one read out
> in a meeting is the one on the pack."

### H. The download — 2 minutes
Take the **evidence workbook**.

> "Four formats, all rendered from the same frozen snapshots, so they agree with
> the screen. This one carries the working behind every figure. And every
> download is recorded with who took it and which figures it held — so
> 'what was in that file' is answerable without regenerating it, which would
> answer with today's numbers anyway."

---

## 4. The hard questions

**"How do I know the AI didn't make that number up?"**
> It cannot. The pack's figures come from the metric engine, not from the model
> — the model is only shown them. And every number in a drafted sentence is
> checked against that evidence; an ungrounded one is refused. Press Working on
> any figure and you get the formula hash and the run id it came from.

**"What if someone puts instructions in a document they upload?"**
> Try it. It gets imported, stored and shown to a reader labelled as theirs —
> and it is not in the drafting prompt, because imported text is not one of the
> prompt's inputs. That is architecture, not a filter. A filter is something
> somebody eventually gets past.

**"Can a colleague read my committee's packs?"**
> No, and a pack they may not see reads as not-found rather than forbidden,
> because forbidden confirms it exists. Every id on a pack — findings, blocks,
> snapshots, actions — resolves back to its committee before anything is
> returned.

**"What happens if the data changes after we approve?"**
> Nothing, to that pack. It renders from the snapshots it was approved with.
> The next pack shows the new figures and the comparison says what moved.

**"Why is the meeting date months after the reporting period?"**
> The demonstration lake ends at a fixed point while the meeting dates are
> relative to today, so the two are deliberately independent here. In a real
> deployment the data is current and they line up. The pack always labels the
> period it is measuring.

**"Can I show it with our own data?"**
> The committees, templates and thresholds are configuration. The metrics come
> from the governed catalogue. Point it at a real lake and the same screens
> produce your figures.

---

## 5. If something is wrong on the day

**A pack is empty.** It was never generated. Press Generate.

**Every figure says "period not loaded".** The pack's period is not one the
lake holds — which is different from *not yet matured*. `--reset` picks the
periods from the data, intersected across the committee's own metrics, so a
freshly seeded pack always resolves.

**Dates look stale.** `--refresh-dates`.

**A committee is missing.** `--check` says what is there;
`python scripts/seed_playbook_committees.py` builds what is missing.

**Drafting says the AI is unavailable.** No provider is configured. Everything
else works; skip section D or show an already-drafted block.

**Somebody edited a demonstration pack yesterday.** Leave it — `--refresh-dates`
does not touch content, and their edit is part of the story. Use `--reset` only
if you want it gone.

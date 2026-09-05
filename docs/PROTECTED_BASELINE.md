# The protected baseline

Behaviour that has already been paid for, and the two commands that prove it is
still there.

## Why this exists

Every development phase adds capability. The failure that costs the most is
never the new thing not working — that is obvious within minutes. It is the new
thing working while something already finished quietly stops, because that is
discovered days later by somebody who was relying on it, and by then nobody
remembers which change did it.

So the behaviour below is **protected**: it is not to be regressed by later
work, and it is not to be rewritten unless a genuine architectural conflict is
found and stated.

## The two commands

```bash
python scripts/protected_baseline.py --json before.json     # backend, ~3 min
node   scripts/acceptance/protected-paths.mjs               # browser, ~3 min
```

Run both **three** times around any significant change: before it, after each
phase, and again on the final HEAD. The first run is what makes the later ones
mean anything — a group that was already red is not the new change's fault, and
recording the before-state is the only honest way to say so:

```bash
python scripts/protected_baseline.py --compare before.json
```

`--compare` prints `REGRESSED BY THIS CHANGE` and exits non-zero **only** for a
group that was green and is now red. Groups that were already failing are
listed separately rather than counted against the change.

The browser script needs the backend on `:8000` and the frontend on `:3000`.
Override with `CREDITPROBE_API`, `CREDITPROBE_WEB`, `CREDITPROBE_USER` and
`CREDITPROBE_PASSWORD`.

This is deliberately **not** the full suite. The full suite is the gate before a
release; this is the gate around an edit, and a gate nobody has time to run is a
gate that does not exist.

## What is protected

### The three concepts, kept apart

| Concept | Means | Must never become |
| --- | --- | --- |
| **Messages** | all communication between people, whatever it carries | filed elsewhere because it carries an analysis or a review request |
| **Workflow** | administrator-only operational oversight, in counts | a mailbox, or a way to read somebody's mail |
| **Notifications** | one person's unread and attention state | several counters that drift apart |

### Backend groups

| Group | The promise |
| --- | --- |
| `messaging` | A message reaches Sent and Inbox. A self-send reaches both. A request stays a message. Attachments carry their share grants. |
| `system-messages` | CreditProbe is a governed sender, not an account: its messages land in the Inbox, count as unread, and carry no provider branding. |
| `attention-counts` | One authoritative unread count. Reading moves every badge at once, 3 → 2 → 1 → 0. The two header badges stay disjoint. |
| `permissions` | Participation is authorization. No reading another pair's thread, another person's draft, or an attachment by guessed id. An administrator does not become a participant by being an administrator. |
| `admin-workflow` | Workflow is ADMIN-only at the route, not merely hidden in the navigation. |
| `single-period-population` | "Show Stage 2 borrowers" returns borrowers at one period. A level condition is a population, not a two-period cohort, and no measure is needed to return entities. |
| `stage-widening` | "Stage 2 or worse" is stage >= 2 under ordered-stage semantics, and the scope line says so in words. |
| `movement-vocabulary` | "How has ECL moved" is measure movement; "moved to Stage 3" is migration. The two must not collapse. |
| `context-carry-forward` | Sector, borrower, population, period and filters survive the next turn. |
| `ordinal-reference` | "The second one" resolves to the second row actually on screen. |
| `answer-grain` | A question about sectors returns sector rows. The head noun decides the grain. |
| `multi-condition` | AND, OR, NOT and nesting survive planning, and every predicate asked for is provable on the rows returned. |
| `ecl-decomposition` | The ECL bridge stays multi-step, reconciled and drillable, and never collapses to a scalar. |
| `cockpit` | Three suggestions from the approved five, and a greeting that is presentation only. |

### Browser paths

Sign-in; the Cockpit greeting (default, edit, immediate update, reload, reset,
identity untouched); exactly three suggestions from the approved five; the
recipient picker on focus, by job title and by whole name, self-send, chips and
removal; sharing a real analysis as a card; send confirmation without
navigating to Workflow; the self-addressed copy in both boxes; Shared with me
reconciling; the 3 → 2 → 1 → 0 countdown with the header badge, the tile and
the workspace all agreeing and persisting across a reload; Workflow as
oversight with no message content, no conversation rows and an anonymous caller
refused; and no horizontal overflow at 1440px.

### Also protected, covered by the full suite rather than by these two commands

What-If and the TAC, the four Early Warning layers, the borrower scorecard,
Borrower 360 and the relationship graph, and the export/download paths. None of
them should need rebuilding; if a change touches them, run their suites too.

## Recorded baseline

`6c13bdf` — *The review runs last again, and the matrix knows the new pages*

| | |
| --- | --- |
| Backend groups | **14 / 14 green** |
| Backend tests | **932 passed, 12 skipped, 0 failed** in 2.6 minutes |
| Browser checks | **40 / 40 pass, 0 problems** |
| Frontend tests | **448 passed** |
| Typecheck, lint (frontend), ruff (backend) | clean |
| Alembic | single head, `0032` |

### Known red outside the protected set, at this same commit

Two things fail in the full suite and are **not** in the protected baseline.
Both are recorded here so a later run does not mistake them for new damage.

1. `tests/demo/test_seeded_projects.py::TestTheLeakIsClosed` — a `Test lens` and
   a `Test appetite check` left in the development database by an earlier run.
   Environmental, not a code defect; identical on the previous commit. The
   remedy is the governed sweeper, which also reaches demo objects the seeded
   workflow attaches to, so it has not been run unasked.
2. `tests/evals/test_remediation_threads.py::test_thread_g_never_cites_a_figure_above_its_own_threshold`
   — the test demands `closing_`-prefixed columns, which only a two-period
   cohort produces. "Which customers have covenant headroom below 15%?" is a
   level condition at the present period, and the Phase 0 planner change made
   exactly that shape plan as a single period. The eval encodes the older
   shape. It has **not** been amended: whether that answer should stay
   single-period or should carry the opening comparative beside it is a product
   decision, and quietly relaxing a safety assertion to match new behaviour is
   how a safety assertion stops being one.

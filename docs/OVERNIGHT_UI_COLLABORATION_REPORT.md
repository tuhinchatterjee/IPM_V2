# Overnight phase — UI, collaboration and navigation

Branch `claude/vigilant-darwin-eohyi1`. Five commits.

## 1. Starting commit

`7f00b9a09bea7b14acc2f9352b18023049faec5a` — matches the expected commit
in §0.

## 2. Final commit

`7bd8168`. All five, in order:

| Commit | |
|---|---|
| `e78349e` | Back went to an index, not to where you came from |
| `88f434b` | An answer with no reading, and a workflow with one reviewer |
| `8411154` | Three things the browser found that the tests could not |
| `7692961` | Two documents for the two things that changed shape |
| `7bd8168` | A notification that read like a label, and the §68 report |

Across the phase: 52 files changed, 6,845 insertions, 406 deletions.
20 new files, two
Alembic migrations (`0014`, `0015`), and **no new npm or Python
dependencies** — `package.json` and `package-lock.json` are byte-identical
to the starting commit.

## 3. Local/remote match

Local `HEAD` and `origin/claude/vigilant-darwin-eohyi1` are the same
commit. Nothing was merged to main, nothing force-pushed, no history
rewritten, no pull request opened.

## 4. Major UI architecture changes

Three new architectural pieces, each free of React so it can be tested
directly with `node --test`:

- **`lib/return-context.ts`** — the return-context contract. One named
  builder per source in the product; the only sanctioned way to
  construct a return href.
- **`components/analytics/registry.ts`** — the visualization registry.
  Chooses a chart from the RESULT'S SHAPE, never from prose.
- **`components/ask/insight.ts`** — selects the key insight and the
  implications from what the backend already established. Never
  composes.

And three new components: `components/collaboration/share.tsx` (the one
recipient picker), `components/collaboration/notifications.tsx` (the
header notification centre), `components/analytics/primary-visual.tsx`
(chart with a table toggle).

The Workflow screen was rebuilt around §46's five views.

## 5. Typography/theme changes

None. The type roles, the eight themes and the surface tokens were
already in place and are untouched. Every new surface — the key-insight
region, the evidence token, the share dialog, the notification panel —
is built from the existing tokens, so all eight themes render them
without knowing they exist.

## 6. Response structure

The layout had five sections; §11 asks for eleven. It now runs:

1. USER QUESTION *(rendered by the thread)*
2. BOTTOM LINE
3. KEY INSIGHT
4. ANALYST'S READING
5. PRIMARY VISUAL
6. SUPPORTING EVIDENCE *(collapsed)*
7. WHAT DESERVES ATTENTION
8. LIMITATIONS
9. DEEP ANALYSIS *(collapsed)*
10. TECHNICAL DETAIL *(collapsed)*
11. SUGGESTED NEXT QUESTIONS → composer

Two changes matter beyond the ordering:

**Limitations moved after the supporting evidence.** A limitation
disclosed after the follow-up buttons is a limitation disclosed to
nobody; a reader is deciding whether to act at exactly that point.

**§15's explicit negative finding.** An analysis that returns no rows
has answered the question. Rendering its empty table underneath made it
look as though the product had failed to produce one; it now says so as
a conclusion.

KEY INSIGHT and WHAT DESERVES ATTENTION are **selected, never
composed**. `insight.ts` ranks findings the backend already wrote and
returns one unchanged. Every figure in a CreditProbe answer is quoted
from an engine result and checked against the grounding rules — a
highlighted box holding the one sentence nobody verified would undo
that in the most prominent place on the screen.

## 7. Inline evidence / number semantics

`lib/credit-semantics.ts` and `components/analytics/evidence.tsx`.

**Colour is credit-risk meaning, not arithmetic sign.** A green plus
beside an ECL increase is the failure this prevents. The direction comes
from the semantic ontology's `higher_is_worse`, which now reaches the
frontend as presentation metadata on each evidence item
(`backend/orchestration/assembly.py`). Where the ontology has nothing to
say the figure is **not coloured at all** — there is deliberately no
name-guessing fallback, because an uncoloured figure asks the reader to
think and a miscoloured one stops them.

Never colour alone: every token carries an arrow, a word and a full
`aria-label`. A level (as opposed to a movement) is neutral and carries
no arrow — a dash beside a present figure reads as a missing value.

Clicking a token highlights the matching row in the table, matched on
the identity column only.

## 8. Interpretation highlighting / deep analysis

§52: the first sentence of the analyst's reading — the primary
conclusion — carries a restrained accent surface. One sentence, not the
paragraph. The splitter refuses to break on a decimal or an
abbreviation, because a highlight ending mid-figure draws the eye to
half a number.

§53: **DEEP ANALYSIS** is an expandable holding the evidence chain with
its tokens, the observations, the driver ranking in the engine's own
order, what the result does not prove, and the recommended next
analysis. A section with nothing in it does not render, and the whole
disclosure is absent when there is nothing behind it.

## 9. Suggested-question behaviour

Unchanged and already correct: three or four contextual suggestions
derived from the executed result by `backend/orchestration/suggestions.py`,
one click sends in the same thread, and the Cockpit shows three opening
suggestions with a dismiss control. No work was needed here beyond
keeping it in its §11 position.

## 10. Chart registry and default rules

`chooseVisualization(columns, rows)` reads the backend's presentation
contract — what each column IS, its semantic type, whether it identifies
a row, whether it is a period — and returns a form, an x column, the
series, the reason, and the alternatives.

The default is a **table**, and it wins wherever a chart would mislead:
too many categories, unreadable labels, record-level results,
heterogeneous columns. The reason is shown on screen rather than left
for the reader to infer.

Two rules the browser review added:

- a `*_share_pct` column is the measure expressed as a proportion, not a
  second measure. Counting it as one produced a scatter of a quantity
  against its own share.
- more than one identity column over more rows than a chart can label is
  a listing, not a measurement.

## 11. Chart interactions

Chart/table toggle on every result the registry can draw. Inline
evidence tokens highlight the corresponding table row. Palette control,
legend and tooltips were already in place. When the ideal form has no
renderer in this build, the first alternative the registry itself listed
is drawn and the page says which form it would rather have — silently
falling back to a table loses the toggle as well as the chart.

§22's rule that a presentation-only change reuses the current result and
performs no new computation was already implemented in
`orchestrator._as_presentation_change` and is untouched.

## 12. Touch behaviour

Not changed in this phase. Every new control is a real `<button>` or
`<input>` with a visible focus ring and a hit area at or above 32px, so
they are usable by touch, but no gesture work was done and pinch/pan on
charts remains as it was.

## 13. 3D / multidimensional views implemented

**None.** §65 marks 3D as P2 and says explicitly: *"Do not produce
shallow 3D work while P0 is incomplete."* P0 filled the night. The
registry names `bubble` and `risk-landscape` and chooses them correctly
for the right shapes; neither has a renderer yet, so those results fall
back to a scatter or a table with the reason shown.

## 14. Bundle / performance impact

No new dependencies — `package.json` and `package-lock.json` are
byte-identical to the starting commit. The new code is roughly 2,400
lines of TypeScript across nine modules; three of them (`return-context`,
`registry`, `insight`) are pure functions with no React import.

Built static chunks: 57 files, 2.8 MB on disk uncompressed. `next build`
completes in ~1.3s warm. The one real runtime addition is that composed
analyses now render a recharts chart where they previously rendered only
a table — recharts was already a dependency and already loaded by every
certified analysis, so no new code enters the graph.

### Verified in the browser, not only in a test

Opening `/trace/2934?mode=audit&returnTo=/investigations/1938%23turn-1&…`
against the running stack restores Audit mode and renders a Back control
reading **"← Exposure by sector"** whose `href` is
`/investigations/1938#turn-1` — the exact turn. Switching mode rewrites
the address to `?mode=lineage` without adding a history entry.

## 15. Trace improvements

Scoped to what §36 and §5 required rather than a redesign:

- mode and selected node live in the URL, so a link out carries them and
  a link back restores them
- the dataset a step read is now a **link** into Data Builder, carrying
  that node as its return context. It was text, so the answer to "which
  data was this?" was to memorise the name and leave.

Story / Lineage / Landscape / Audit, the clusters, the issue strip and
the inspector are unchanged.

## 16. Back-navigation architecture

Documented in full in `docs/NAVIGATION.md`. Three query parameters —
`returnTo`, `returnLabel`, `returnType`. `returnTo` is a complete
in-product URL, so the scroll anchor, selected tab, trace mode and node,
and dataset period all travel inside it and need no parameter of their
own.

Three screens held state a return link could not carry, so it moved into
the address: the Project's tab, the Trace's mode and node, and Early
Warning's opened facility. All three use `history.replaceState` rather
than a router push — thirty history entries for one Trace would break
the browser's own Back.

Only same-origin relative paths are honoured. `//evil.example` and
`javascript:` are refused and the caller's own default is used instead.
That rule is a security boundary and is unit-tested.

## 17. Back-path acceptance results

All ten §5 paths, each walked end to end in
`frontend/src/lib/__tests__/back-paths.test.ts` — the link is built the
way the screen builds it and read back the way the destination reads it.

| Path | Lands on | |
|---|---|---|
| Cockpit → Investigation → Trace | the exact turn | ✅ |
| Cockpit → Investigation → Method | the exact turn | ✅ |
| Project → Investigation → Trace | the investigation, then the project's tab | ✅ |
| Project → Investigation → Method | the exact turn | ✅ |
| Saved Analysis → Trace | that row in Analyses | ✅ |
| Lens → Analysis → Trace | the lens | ✅ |
| Early Warning → Borrower → Trace | that borrower's row | ⚠️ see below |
| Data Builder → Dataset → Relationship | the dataset at its period | ✅ |
| Trace → Dataset in Data Builder | the same node, same mode | ✅ |
| Dynamic run → Analysis detail | the source conversation | ✅ |

**Early Warning is the one path that could not be built as written.** A
Forward Risk Signal score is a fitted model rather than a governed
engine run, so a borrower has no Trace of its own to open. What the row
now has is **Investigate this borrower**, which opens an Investigation
carrying that exact row as its Back — so the journey completes by way of
the analysis that does produce a Trace. Fabricating a Trace for a score
that has none would have been worse than the honest detour.

## 18. Project / Investigation / Analysis behaviour

The object model is unchanged; the rule §4 states was half-enforced and
is now complete.

The global list already excluded project threads — that is what makes a
Project a container rather than a tag. What did not exist was any way to
publish one. The only route to the global list was **Move**, which is a
different operation: it takes the thread OUT of the project and the
project's own record of what was explored goes with it.

`published_globally` (migration `0014`, default false) and
`POST /investigations/{id}/publish`. Publishing leaves the thread where
it is and lists it in both places; the global list marks a published
thread with a small globe so a reader can see it arrived from a project.
No existing row was opted in.

## 19. Dynamic-run versus Method behaviour

Unchanged and already correct (`lib/analysis-links.ts`): a composed plan
has no library entry, so it links to the run that produced it rather
than to `/engine-builder/dynamic_analysis`, which reported *"not a
registered CreditProbe analysis"*. Now covered by a §58 journey test as
well as its own unit tests.

## 20. Workflow features

Documented in `docs/COLLABORATION.md`. Migration `0015`.

- **Recipients are a set** — people and teams in one request. A team is
  expanded to its members at read time, never stored, so somebody who
  joins Credit Review today sees what it was sent yesterday.
- **Seven actions** — review, comment, approve, request changes, FYI,
  sign-off, assign action. The action is what is being asked FOR;
  the state is where the asking has got to.
- **Nine states** — §44's nine. Two stored ids read differently from the
  words on screen (`submitted`→Sent, `withdrawn`→Cancelled) and are
  deliberately **not renamed**: they are the state machine every stored
  decision depends on, and rewriting them would edit history that exists
  in order not to be edited.
- Message, priority, optional due date, and the object's **version** as
  it was when sent.
- `POST /workflow/{id}/opened` records §44's OPENED as an observation:
  idempotent, and an item already in review does not go backwards
  because somebody reloaded.
- **Send** is on the Investigation, the Project and every saved Analysis,
  through one recipient picker.

## 21. Internal messaging

A thread against the workflow item: replies, @mentions, attachments
(analysis / investigation / project), and per-message resolution.
Internal only — the brief says not to build external email, and what the
product owes a user is that work addressed to them is visible the moment
they open CreditProbe.

Saying something on a sent item moves it to **Commented**, which tells
the sender there is something to read without claiming a decision.

**A mention is not a comment.** Everybody on the item is notified
`commented`; anybody named is notified `mentioned`. An inbox that cannot
tell "somebody said something on a thread you are on" from "somebody
asked you specifically" is one people stop reading — and `mentions` is
its own inbox view for the same reason.

## 22. Notifications

A bell in the header with an unread count, on every screen, deliberately
out of the Cockpit. Each notification **deep-links to the exact object**,
carrying a return context so Back returns to the inbox. A notification
whose object type has no page renders as text rather than as a link — a
link landing on a 404 makes a reader conclude the product is broken
rather than that there is nothing to open.

Not polled: read when the panel opens and after anything that would
change it.

## 23. Role enforcement

Backend-side, on the endpoint, as §50 requires — *"Frontend hiding is
not sufficient."* A request that never went near the UI is refused the
same way, and the message names the roles that would work.

One change: **a Viewer may now comment and reply.** §50 says a Viewer
may "comment where permitted", and that is their one write. Sending
somebody an object asking them to comment on it and then refusing their
reply is a failure that would have gone unnoticed, because the request
would simply have looked unanswered. A Viewer still cannot send work,
cannot decide, and cannot create an analysis — asserted in three tests.

## 24. Backend test count

**1,880 collected, all passing** — `pytest tests --ignore=tests/llm`
exits 0 with no `F` in the progress output. (This project's pytest
configuration suppresses the trailing "N passed" line behind the
warnings summary, so the count is the collected total and the pass is
the exit code.) 20 tests are new in this phase:

- `tests/api/test_hierarchy_api.py` — 4 tests for §4: a project thread
  is not in the global list, publishing puts it in both places,
  unpublishing takes it back out, a standalone thread is already global.
- `tests/api/test_workspace_api.py` — 16 for §43–§46 and §50: multiple
  recipients, teams, the seven actions, the nine states, opening as an
  observation, the message thread, replies, mentions, attachments,
  resolution, the five inbox views, completing versus approving, and
  three role-enforcement tests.

The 16 live-provider tests in `tests/llm/` are skipped: no key is
configured, which is exactly the state they are designed to skip in.

One existing test caught a real regression in this phase and is worth
recording. Replacing `submit()` with the multi-recipient `send()` changed
the reviewer's notification from *"Review requested: Q2 pack"* to
*"Review: Q2 pack"* — the chip label leaking into a sentence. It passed
on the first few runs because the shared development database still held
notifications written by earlier runs under the old wording, and only
failed once the data turned over. The fix was to the message, not the
test: each action now has the words it uses in a notification, separate
from the words on its chip, because a notification is read in a list of
other people's sentences.

## 25. Frontend test count

**117 passing** (`node --test --experimental-strip-types`), up from 61.
56 new:

| File | | |
|---|---|---|
| `lib/__tests__/return-context.test.ts` | 25 | the contract |
| `lib/__tests__/back-paths.test.ts` | 12 | §58, the ten journeys |
| `lib/__tests__/credit-semantics.test.ts` | 7 | §51, risk direction |
| `components/ask/__tests__/response.test.ts` | 13 | §61 |
| `components/ask/__tests__/insight.test.ts` | 5 | §52 sentence splitting |
| `components/analytics/__tests__/registry.test.ts` | 24 | §62 shapes |

## 26. Browser acceptance count

**20 screenshots at 1440×900**, on the production build, with DOM
checks on each: zero console errors, zero page errors, and zero
horizontal overflow anywhere (every page measured −15px, i.e. content
narrower than the viewport).

Verified live, not asserted about: the §11 answer layout end to end with
a real governed result; the workflow detail with a real two-message
thread, real recipient names and an "(opened)" stamp; the notification
panel with a live unread count of 3; the share dialog and its filter;
the Cockpit populated from the briefing endpoint.

## 27. Docker result

**Images build cleanly. Runtime could not be verified in this sandbox.**

`docker compose build` succeeds for both images against the CA-pinned
bases, and `db` starts and reports healthy. The backend container then
cannot reach it: its `/etc/resolv.conf` carries `8.8.8.8` rather than
Docker's embedded resolver at `127.0.0.11`, so `db` does not resolve —
and container-to-container TCP to the database's address is
`Network is unreachable`, so bridge networking between containers is not
functioning here at all.

That is this remote environment's Docker networking, not the compose
file: nothing in `docker-compose.yml`, either Dockerfile or the
entrypoint was touched in this phase, and the same stack was verified
end to end in an earlier one. **This is worth re-running on a normal
Docker host before release** — it is the one gate in §66 I could not
close.

## 28. Screens visually reviewed

Cockpit (loading and settled) · Investigations · Projects · Analyses ·
Workflow inbox (empty and populated) · Workflow detail with message
thread · Notification centre · Share dialog · Share dialog filtered ·
Investigation thread · Ordinary answer, upper and lower · A second
answer (ECL by sector) · Trace index · Data Builder · Analysis Studio ·
CRO Lens · Early Warning.

Against §64's questions:

- *Does this still look like a generic admin dashboard?* No. The Cockpit
  opens on one question. An answer opens on one sentence.
- *Is anything too large?* No. The largest type on an answer is the
  17px bottom line.
- *Is the important interpretation obvious?* Yes — KEY INSIGHT sits
  between the answer and the reading, with its figures attached.
- *Is the user ever stranded?* Not on any path tested. Every detail view
  has a context-aware Back.
- *Can the answer be understood without opening technical detail?*
  Yes — everything above DEEP ANALYSIS is the answer.
- *Are charts useful rather than decorative?* Now yes; two rules were
  fixed to make them so.
- *Are collaboration actions coherent?* One Send control, one picker,
  one inbox, one bell.
- *Is the current object type clear?* Yes — every header carries its
  eyebrow, and workflow rows name the object type and version.

## 29. Explicit deferred items

Nothing was silently dropped. What is not done:

**P2, deferred by §65's own instruction** — 3D and multidimensional
views (§27), advanced period playback (§26), visual experiments. §65:
*"Do not produce shallow 3D work while P0 is incomplete."*

**P1, not reached** — premium visualization interactions beyond the
chart/table toggle (§23, §25, §29): pointer/touch gesture work, chart
full-screen, "Ask about this" from a chart selection, legend filtering,
theme-gallery refinement.

**Registry forms without renderers** — the registry names two dozen
forms and this build draws six. `sankey`, `treemap`, `histogram`,
`box`, `parallel-coordinates`, `bubble`, `risk-landscape`,
`small-multiples` and `stacked-area` are chosen correctly and fall back
to the nearest drawable alternative or the table, with the intended form
named on screen. Adding a renderer later changes nothing else.

**§54's two extras** — a Data Steward sending a dataset-quality issue
for review, and an Analysis Studio methodology approval workflow. Both
objects are already `REVIEWABLE`, so the backend accepts them today;
what is missing is a Send control on those two screens.

**Accessibility (§57) and performance (§56)** were not separately
audited. New controls are real buttons with focus rings and labels, but
no contrast audit or Lighthouse pass was run.

**The recipient picker's directory** is unsorted and unpaginated beyond
its filter. Fine at demo scale; a real bank's directory wants grouping.

## 30. Intelligence stack — explicitly unchanged

I confirm that **nothing in §0's hard boundary was changed or
weakened**:

Anthropic provider integration · provider telemetry · live verification
architecture · Quick/Critical verification semantics · model-role
configuration · semantic ontology · Data Builder semantics · Analysis
Studio methodologies · Analytical IR semantics · SQL compiler semantics
· approved Python kernels · deterministic calculations · business
invariants · grounding rules · Intelligence Factory · benchmark and gold
isolation · certification logic · synthetic data universe · governed
relationships.

The backend touched in this phase is exactly what §0 permits:

| File | Change |
|---|---|
| `models/platform.py` | new columns and two new tables |
| `services/threads.py` | `publish()`; the global listing's WHERE clause |
| `services/workflow.py` | multi-recipient send, states, message thread |
| `api/routers/hierarchy.py` | one endpoint |
| `api/routers/workspace.py` | four endpoints, two permission changes |
| `api/routers/users.py` | one read-only directory endpoint |
| `api/permissions.py` | one new permission set |
| `orchestration/assembly.py` | `direction` on evidence — presentation metadata |

The last is the only one that touches the analytical path, and it is
additive: `_evidence()` attaches the ontology's existing
`higher_is_worse` to figures the assembler was already emitting. No
figure changed, no calculation was added, and the ontology was read
rather than edited.

The visualization registry deliberately lives in the **frontend**, over
the presentation contract the backend already publishes. Putting chart
selection near the compiler would have been a change to the analytical
path for a presentation decision.

## 31. Anthropic calls and credits

I confirm that **no live Anthropic call was made at any point in this
phase, and no credits were consumed.**

- `ANTHROPIC_API_KEY` was never asked for, read, printed or inspected.
- The running stack reported **AI OFFLINE** throughout — visible in
  every screenshot — and every answer used the deterministic governed
  semantic reader.
- The 16 tests in `tests/llm/` skip without a key, and skipped.
- `verify-live-ai.ps1` was not run.
- The two live answers rendered for §64 were produced by the offline
  planner and the governed runtime.

---

## Quality gates (§66)

| Gate | |
|---|---|
| `ruff check backend tests scripts alembic` | ✅ clean |
| `pytest tests --ignore=tests/llm` | ✅ exit 0, 1,880 collected |
| `python scripts/check_powershell.py` | ✅ all scripts |
| `tsc --noEmit` | ✅ clean |
| `eslint` | ✅ clean, 0 warnings |
| `next build` | ✅ 27 routes |
| `node --test` | ✅ 117 passed |
| `alembic upgrade head` | ✅ 0013 → 0015 |
| Browser review at 1440×900 | ✅ 20 screens, 0 errors, 0 overflow |
| `docker compose build` | ✅ both images |
| `docker compose up` | ⚠️ sandbox networking — see item 27 |

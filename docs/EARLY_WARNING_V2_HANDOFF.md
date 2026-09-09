# Early Warning V2 — handoff

Branch `claude/early-warning-rebuild-v2-3lnttn`. Not merged to main.

This covers the whole Early Warning V2 build: the scoring engine rebuilt against the
authoritative workbook, and then the three things that turn a correct score into a
product — an assistant that can answer about it, a governed set of things to do about
it, and screens and reports that say what the numbers mean.

Where the artifacts disagree, precedence is: mathematics from the workbook, UX from the
screens deck, report structure from the two reference reports, **and actual values from
CreditProbe's own data**. No figure from the deck or from the reference reports is
hard-coded anywhere in this build.

---

## 1. The model

Rebuilt in `backend/early_warning/` against `CreditProbe-EWS-Framework-v2.xlsx`.

| | |
|---|---|
| Signals | 123 in the inventory, 105 scored, 18 dropped / merged / replaced |
| Classifiers | 23, across 8 sub-categories |
| Triggers | 67 |
| Accelerator | 5 dimensions (magnitude, velocity, persistence, repetition, corroboration) |
| Decay | class-specific, with a persistence hold — the clock starts on cure, not on age |
| Sub-category nodes | 22, worst-of with uplift inside a node, weighted blend across |
| Layer / dimension | 6 outputs (L1–L4 trigger-and-accelerator, L2 and L4 classifier) |
| Combination | published 5×5 anchor matrix, read rather than computed |
| Notches | 5, each 8 points, net capped at ±2 |
| Order | anchor → notches → caps → overrides |

`tests/early_warning/test_rawabi_regression.py` reproduces the workbook's own worked
example exactly: anchor 72, notches −1/−1/0/0/0, final EWS 56 MEDIUM.

Explicitly not what this is: 35 classifiers, a flat weighted sum, a universal recency
decay, λ=0.60 breadth, or CCM multiplication. Each of those was in an earlier reading of
the model and each is now impossible to reach through the code.

**The model is not calibrated.** Every weight, band and multiplier is a documented
starting calibration, not an estimate fitted to default data. The tool orders obligors;
it does not predict them, and nothing it emits is a probability. That sentence travels
with every answer, every screen and every report scope, because a limit stated in one
place and dropped in another is a limit nobody reads.

Data: 15 monthly snapshots for 300 obligors at `ews-v2.1.0`, built by
`scripts/build_early_warning_v2.py`.

## 2. Signals explain themselves

`early_warning_signal_observation` used to persist six columns and discard everything
that produced the score. It now carries the trigger severity band and score, all five
accelerator dimension bands and multipliers, the decay factor, class, half-life and
floor, the cure state and age, the layer and role, and the source system, dataset and
tier.

That is what makes "show me the evidence behind that node" answerable from the reading
that produced the score rather than from a reconstruction of it, and what fills the
lineage table the reference borrower report specifies.

`tests/early_warning/test_signal_observation_schema.py` asserts every column is present
and non-null for a fired signal, that an uncured signal carries a decay factor of 1.0,
and that severity × accelerator reproduces the score.

## 3. The assistant

Before this, the assistant could not answer an Early Warning question at all. There was
no handler; a question about an Early Warning obligor was checked against the credit
book's customer master, failed to find it, and came back "CreditProbe could not find
that borrower in the published data" — accurate about the book it looked in, and useless.

Four new modules:

- **`facts.py`** — the fact pack. Every figure any answer may state, computed from the
  Early Warning domain only, across eleven scopes. Derived measures nothing else
  computed: per-layer contribution to a movement between two periods (returning `None`
  rather than a guess when a period is missing), concentration as a measured share,
  the live-versus-structural reading, anchor-versus-notch movement attribution, and
  grade-versus-EWS divergence.
- **`actions.py`** — the governed action library, keyed to all 22 sub-category nodes.
  Every entry carries an owner that resolves to a real ladder rung or specialist route,
  a timeframe, and the specific evidence that closes it. "If I only do one thing" is
  answered by reversibility then cost — never by the score of the node it came from,
  because the cheap reversible action keeps every other one available afterwards.
- **`compose.py`** — the reading. Sentence selection is driven by what the pack shows,
  so an answer about a concentrated segment reads differently from one about a
  broad-based move because the facts differ, not because a different template was
  chosen.
- **`ask.py`** — deterministic intent matching over the bounded question family, with
  borrower and group names resolved against this domain's own data. It returns nothing
  rather than falling back to a portfolio summary: answering "how much is in arrears?"
  with the portfolio's early warning score is a non-sequitur that reads like an answer,
  and declining is what lets the domain lock refuse it properly.

**The rule the whole design rests on:** prose may quote only figures the pack carries.
Three violations were found and fixed by the grader rather than by inspection — a sum
computed on the way to the sentence, and action timeframes read from the library instead
of the pack.

The assistant will not change a score and will not close a case. Asked for either, it
says so and names the route that does exist: an override is a documented control counted
as one, and an escalation is a decision the matrix routes to a person.

## 4. Diagnosis

`diagnosis.py` splits by variance reduction in the EWS score, with the minimum leaf
fixed as a share of the root population (a bug caught by its own test: the floor was
shrinking per node, producing a 12-obligor leaf under a 30 floor). Candidate splits come
from the domain's own columns. The descriptive-not-predictive caveat and "never use a
leaf as an approval rule" travel as data, so every surface repeats them.

## 5. Escalation and actions

`route_for()` existed and was called nowhere in `backend/`. Escalation now consults the
matrix for the rung when the caller supplies none, stamps a due date from the
acknowledgement and decision SLAs, informs the notified roles alongside the deciding
rung, records the matrix version and the routing cell on the case evidence, and sets the
`workflow_item_id` FK that was never set. Recommended actions and the draft escalation
note are served from the library.

## 6. Reports

All five scopes generate, each with charts embedded in the `.docx`:

| Scope | Size | Chart images |
|---|---|---|
| borrower | 91,215 bytes | 1 |
| portfolio | 130,325 bytes | 2 |
| segment | 99,792 bytes | 1 |
| all_segments | 339,759 bytes | 6 |
| multi_borrower | 294,246 bytes | 5 |

Action and remediation tables are emitted as **sections**, because the writer ignores
top-level `actions` / `remediation` keys — which is why those keys were `[]` in every
builder and nobody noticed. `tests/early_warning/test_report_charts.py` opens each
generated document as a zip and asserts `word/media/*.png` exists, because before it no
test anywhere asserted a chart was embedded and `charts.render()` swallows every
exception.

## 7. Screens

One nav item, one product. On the Early Warning page:

- A **chat box at the top**, answering in place through the domain's own endpoint rather
  than the general one — narrower on purpose, so it cannot reach another book by
  construction rather than by a lock that has to hold.
- A **portfolio reading** above the tables: which layer carries the movement, whether the
  risk sits in a handful of names or across the book, and what follows from either.
- The **15-month trend**, which was fetched on every page load and never drawn.
- An **arbitrary level**: segment, grade, stage, region, relationship manager,
  utilisation band, or the layer where risk is being detected. The grade level carries
  the divergence note, because grade and early warning are not meant to track each other
  and a reader who expects them to reads the gap as an error rather than as the alert it
  is.
- **`chart-rules.ts`** decides where a chart earns its place. Trends, distributions,
  comparisons and movement get one; methodology explanations, single-signal evidence,
  recommendations and escalation decisions do not. Two months is a pair of numbers, so
  it is not drawn as a trend. The same list is enforced on the server, so the two cannot
  drift.

## 8. The quality suite

`backend/orchestration/rubric.py` gains eleven Early Warning criteria, decided by
arithmetic with no model in the loop — a grader that disagrees with itself cannot say
whether a change improved anything.

**Safety (4):** no figure the pack does not carry; no binary debris; never a claim to
have changed a score or closed a case; and never "improved" about a fall the notches
produced while the condition underneath was flat or worse.

**Quality (7):** names the node not just the number; names the source system when
evidence is asked for; distinguishes live from structural; recommends only with an
owner, a timeframe and a closing test; states its limits; offers a specific next drill;
and does not attach a chart to a question with no shape to show.

`tests/evals/early_warning_cases.json` holds the 40 adversarial cases across the ten
families, each naming one way the answer could be wrong. Three cases fail the rubric on
purpose, because a grader that passes everything is measuring nothing.

Running it found eight real defects, all fixed:

1. An action answer never said whether the weakness was live or structural. For the
   weakest obligor in the book that mattered — its arrears reading is very low against a
   very high classifier reading, so there is nothing live to contain, and the first thing
   recommended was containment.
2. A methodology question got one fixed description of the framework whatever was asked.
   Five parts now answer for themselves from the engine.
3. "How do the notches work?", "What are the limits of this tool?" and "Are we
   double-counting?" were declined outright.
4. "How does the book look by rating?" returned the whole book, because the word "book"
   outranked the cut that was explicitly asked for.
5. An obligor named by position — "the weakest borrower" — resolved to nothing, so every
   action question about it was answered about the portfolio.
6. Two figures were quoted from outside the pack (a composer-computed sum, and the
   action timeframes).
7. The layer scope silently dropped the not-calibrated caveat every other scope carries.
8. Two of these were the checker's own fault: "tier-3" was read as minus three, and a
   driver-tree split label carries a threshold the pack does hold.

## 9. The live-model seam

The interpretation seam that offers a result to a provider, checks the prose it returns
against what the result establishes, and discards the whole thing rather than annotating
it now applies to Early Warning answers too, with the fact pack as the grounding result.

The deterministic reading is written first and is what stands when there is no provider,
when the model declines, when the call fails, or when what comes back quotes a figure the
pack does not carry. That ordering is what makes configuring a provider an improvement
rather than a risk. No provider is configured in this deployment; verified inert.

---

## Verification

Run on the branch head, against the built domain and a live database.

| Suite | Result |
|---|---|
| `tests/early_warning/` | **1428 passed**, 2 failed, 1 skipped, 3 errors |
| `tests/evals/test_early_warning_brain.py` | **209 passed**, 2 skipped |
| `tests/api/` + `tests/evals/` | **651 passed**, 45 failed, 308 skipped, 5 errors |
| `tests/orchestration/` | **616 passed**, 79 failed, 72 skipped, 31 errors |
| Frontend `npm test` | **389 of 389 passed** |
| `npm run typecheck` / `lint` / `build` | clean |

**On the failures.** All five in `tests/early_warning/` are
`test_forward_risk_signal.py`, the legacy fitted signal, which needs at least three
quarterly reporting periods this sandbox does not have. The api, evals and orchestration
failures are `DatasetNotPublishedError: portfolio_facility` and missing legacy quarterly
data, from the same cause.

None of them are regressions, and that was measured rather than assumed: stashing the
whole change set and re-running gives **45 failed / 442 passed / 5 errors** for
api+evals, against **45 failed / 651 passed / 5 errors** with it — the identical
failures and 209 added passes. Orchestration sits at exactly its established baseline of
79 failed / 31 errors.

**Live checks.** Every `/api/v1/early-warning/v2` endpoint answers 200:
the overview, `segments`, `levels`, `level/{field}`, `insight`, `suggestions`,
`methodology`, `diagnose`, `ask`, and the report and escalation routes. `POST /ask`
returns `scope=portfolio` for a portfolio question, `scope=methodology` with the
deduplication rule for the double-counting question, `scope=action` for an action
question, and `answered=false` with a stated reason for "What is the weather in
Riyadh?".

**Browser.** Chat box, insight panel, trend chart and level selector all present; a
question answers in place with its interpretation; the action answer carries owner,
timeframe and closing evidence and says the weakness is structural; nothing says
"monitor closely"; the grade level renders with its divergence note and the URL carries
it, so Back and a shared link both work. Zero console errors.

## Known gaps

- Layer 3 external intelligence is synthetic in this build. It is marked as such on
  every answer, screen and report that leans on it.
- The five legacy Forward Risk Signal tests need quarterly data that is not built in this
  sandbox. They are untouched by this work.

The money convention is now consistent: one writer per side, mirrored character for
character, with tables naming their unit once in the header. See `EARLY_WARNING_V2_UAT.md`
§10 for what was wrong and what replaced it.

---

**Readiness:** `EARLY_WARNING_V2_UAT.md` carries the UAT record — model invariants
confirmed from the engine, the four journeys and browser history verified live, the eight
AI questions with their actual answers and grades, Escalate/Inform into Messages, the
investigations round trip, report reconciliation, and every remaining non-pass classified
against a measured branch-point baseline.

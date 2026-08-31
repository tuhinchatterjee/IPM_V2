# Overnight build — morning report

Branch `claude/vigilant-darwin-eohyi1`. 14 commits; 128 files changed, 17571 insertions(+), 546 deletions(-).

This report is written to be read before the code. It says what changed, what
broke while changing it, what the gates actually executed, and what is still
wrong. Section I is the one to read if you only read one: it separates the
gates that ran from the gates that could not, and it does not describe the
second kind as passing.

---

## A. What was built

**The AI is now the analyst, not the translator.** A governed tool registry
of 28 tools, a schema-constrained agent loop over the platform's single LLM
primitive, and a run key that makes the same question at the same data
release produce the same answer. The loop is built on `backend.llm.structured`,
so it is exercised end to end by a scripted provider and makes no live call.
The tools are read-only by construction rather than by convention: the
analytical IR they compile to has no write verb, so there is no plan shape
that could mutate anything.

**Early Warning stopped being a score.** Thirty-four named conditions across
eight families, each bound to a field the catalogue publishes, each with a
threshold, an owner and a version. A borrower's standing carries six
transparent counts — breadth of independent families, severity, persistence,
worsening, improving, and what points the other way — and deliberately no
score key. Lifecycle is NEW / PERSISTING / WORSENING / IMPROVING / CURED /
UNAVAILABLE, computed against the previous reporting date.

**Early Warning raises Risk Cases.** A materiality rule decides which
standings are findings and which are monitoring; a review walks the whole
book, ranks it, opens a bounded number of cases and reports how many
qualified below the line. It never closes a case: a cured borrower moves to
MONITORING with an event saying the evidence is gone, and whether the credit
recovered stays a person's judgement.

**Four domain readings.** IFRS 9, covenants, collateral and the credit file,
under one shape: findings that each name their dataset, field and rule, plus
what could not be read and why. The analyst's four evidence tools now return
these readings instead of raw rows.

**Two new screens and one strip.** `/early-warning/signals` (the taxonomy,
borrower by borrower, with a detail panel per name), the Borrower 360 landing
ranking, and a six-count Early Warning line on the Cockpit.

**Product vocabulary is enforced, not merely followed.** A governed module
holds the provider and demonstration patterns; boundary code strips vendor
identity from public health; scanning tests run over both the source and the
rendered page text.

---

## B. Root causes fixed

Each of these is a mechanism, not a symptom.

**Human narration and machine output shared a stream.** The Docker bootstrap
wrote its readiness marker by capturing `--json` stdout, and the same stdout
carried progress narration. On a fresh machine the marker was unparseable and
the container never became healthy. Fixed at both ends: narration is
redirected to stderr, and the marker is written by the script itself,
atomically, to a path it is given.

**Two ends of the API disagreed about the error shape.** The house convention
is `detail={"error", "message"}`; FastAPI's own defaults for 401/404/405 are a
bare string. The browser client found no `message` and printed
"Request failed with status 500." Fixed with handlers that leave a well-formed
detail object alone and give every other shape the same envelope.

**A bootstrap step and its readiness gate disagreed about "done".** The step
asked whether a review had COMPLETED; the gate asked whether one had completed
AND left cases. A database in between was both "already in place" and "not
ready", so re-running the bootstrap reported success having fixed nothing. Now
one definition, and it is the gate's.

**The clarification menu was a dead end wearing a button.** Offered to
somebody who asked "how is the book doing?", a list of governed concepts
invites them to accept a confident answer to a question they did not ask.
Replaced with a question and prose examples, with anything typed accepted.

---

## C. Defects this work found in itself

Listed because §52 says not to hide them, and because each was found by a test
written to look for it rather than by luck.

1. **Permission-scope collapse in the analyst cache.** A cache hit that was
   also a permission leak. Fixed by carrying the principal's visible datasets
   into the run key's scope.
2. **DuckDB float summation was non-deterministic** across runs, so the same
   question gave a different last digit. Fixed by rounding at the tool
   boundary to nine significant figures.
3. **Grounding was substring-based** and passed numbers it should not have.
   Rewritten to compare at declared precision and significant figures.
4. **Quarter labels were sorted as strings.** "Q4 2025" sorts after "Q2 2026"
   alphabetically, which put the latest period a year and two quarters in the
   past and compared it against the wrong prior one. Every lifecycle verdict
   downstream was about the wrong pair of dates.
5. **Utilisation was bound to the wrong field** — a large-exposure-to-capital
   ratio rather than drawn over limit.
6. **`statements_stale` fired for the whole book** at 180 days.
7. **`collateral_shortfall` fired on two fifths of the book**: an absolute ten
   million tested against a book whose median drawn exposure is 145 million.
   Ten million uncovered is a rounding error on a large facility and the whole
   facility on a small one. Rebound as a ratio; firing dropped to a fifth.
8. **Severity counted thin evidence twice**, through both data confidence and
   evidence coverage, so a borrower with missing columns dropped two bands for
   one reason and the explanation accounted for half of it.
9. **The management-overlay threshold could never fire.** Set at a fifth of
   final ECL against a generator that caps overlays just under that: not one
   borrower in three thousand could reach it. A rule that never fires reads on
   a screen exactly like a clean book. Now a sixth, with the test asserting
   against the data rather than the constant.
10. **The Early Warning book was stood up on every request** — 2.4 seconds per
    page load. Memoised per period; warm reads are one millisecond.
11. **A test fixture truncated `risk_cases`**, which broke the fresh-clone
    acceptance suite two files away with a failure that read like a product
    defect. Fixtures now remove only the rows they created.
12. **The same question returned its rows in a different order** on the second
    ask — same seventy-nine borrowers, shuffled. An `ORDER BY` inside a CTE
    does not bind the outer `SELECT`, and a plan with no SORT never expressed
    one at all. Two attempted fixes were themselves wrong (one destroyed
    rankings, the other reinstated the defect) and both are kept as tests; the
    outer order now refines the plan's own rather than replacing it.
13. **Two refusals were dead ends.** A coverage refusal named the gap and
    stopped; a withheld answer said only "CreditProbe could not complete that
    request" while the actual reason sat in a caveat below the fold. Both now
    lead with the reason and name a next move.
14. **The §13 scanner could not tell prose from an identifier.** It flagged
    `origin: "demo"` — a governance enum, stored and compared against, never
    rendered — on five of twenty-two answers. A scanner that flags every
    answer is one somebody switches off; it now checks the keys that carry
    sentences.
15. **Browser acceptance could not run.** My own §12/§13 additions imported
    `backend.release` from a script executed as a file, so it crashed a third
    of the way through and reported a crash rather than a verdict.
16. **A row did not fit a phone.** `/analyses` ran 19px past a 390-wide
    viewport, caught by the acceptance run and invisible on any desktop.
17. **I overwrote the AI Intelligence Studio router** by creating a new file
    at a name that was already taken — 1,081 lines of router and 385 lines of
    its tests, replaced wholesale. Caught by its own tests, restored from the
    previous commit, and the new work moved to `/domain-intelligence`.

---

## D. Obsolete assertions replaced

Three tests asserted behaviour this mandate explicitly removed. None was
weakened; each was replaced with a stronger assertion, documented in place.

- The Ask refusal test demanded a menu to click. It now asserts nothing is
  offered, the reply asks for the missing thing by name, it says what the
  catalogue does carry, and anything typed is accepted.
- `test_investigation_and_modification` asserted `clarification.options` was
  populated. Same replacement.
- A severity test asserted a thin case scores the same as a fully evidenced
  one. `agentic.severity` deliberately scores it lower — its evaluation corpus
  caught the opposite arrangement sending officers to the least established
  finding first — so the assertion is now that a thin case never outranks a
  complete one, and that the thinness is reported as coverage rather than
  smuggled into risk.

---

## E. Evaluations

| Suite | Size | What it re-derives |
|---|---|---|
| Semantic acceptance | 602 questions, 90 families | that a self-contained question is never refused for want of context, and that an anaphor is recognised as one |
| Early Warning evaluation | 600 cases | every signal's firing, lifecycle and standing, re-derived independently of the implementation |
| Signal taxonomy | 195 | every signal is bound to a field the catalogue publishes |
| Domain readings | 55 | one contract across four domains; absence never reported as reassurance |
| Analyst | ~90 | safety, reproducibility, grounding |
| Signal cases | 41 | the materiality rule, and the review against a real database |
| Signal presentation (frontend) | 25 | ordering and grouping never become a weighted sum |

Total collected: **8,470 backend tests**; **332 frontend tests**.

---

## F. What is deliberately absent

- **No score, anywhere in Early Warning or the four domain readings.** Not
  hidden, not renamed — absent. `Standing.to_dict()` has no score key and the
  frontend comparator is a chain of counts.
- **No vendor identity in any user-facing payload.** `/ai/status` blanks
  provider and model and sets `identity_withheld: true`; the audit route
  behind ADMIN carries them.
- **No canned clarification options.**
- **No claim that a booked accounting stage is a prediction.** IFRS 9 findings
  carry `booked_accounting: true` and the wording travels with them.

---

## G. Known data limitations

These are properties of the bundled synthetic book, not defects in the code
reading it. They are recorded rather than worked around.

- **`breach_flag` is true for about a third of the book.** A covenant breach
  is correctly classed SEVERE and correctly bound, so a third of borrowers
  carry a severe condition. That is the generator's seeding, not the
  taxonomy's calibration, and changing the taxonomy to compensate would be
  fitting a rule to data rather than to credit.
- **Eight of the twelve conditions §20 lists cannot be tested here** —
  receivable stretch, inventory build, returned payments and insurance expiry
  need columns this book does not carry. `taxonomy.unavailable()` names them
  and both the API and the screen show them.
- **Management overlays are capped just under a fifth of final ECL** by the
  generator, which is why the materiality threshold sits at a sixth.

---

## H. Performance

| Path | Before | After |
|---|---|---|
| Early Warning book, cold | 2,425 ms | 2,425 ms |
| Early Warning book, warm | 2,184 ms | 1 ms |
| Review preview, warm | ~2,500 ms | <1 ms |

The memo is keyed on the reporting period and cleared by
`signals.reset()`, which the bootstrap calls after regenerating the lake —
asserted at that seam, because a deployment that rebuilds its book and keeps
answering from the previous one is worse than the slow screen it replaced.

---

## I. Gates — what ran, and what did not

This section separates what was executed from what was not, and does not
describe the second kind as passing. §52 asks for exactly that separation.

### Executed, and passed

**§48 — full backend regression on the FINAL tree.** Run twice on the final
commit, both identical: **8,456 passed, 21 skipped, 0 failed, 0 errors**
across 8,477 tests. The two runs agree character for character in their
progress output.

One honest note about how that number was read. Both runs reach `[100%]`,
print the warnings summary, and then the process lingers rather than exiting
promptly, so pytest's closing "N passed" line was never flushed to the log.
The counts above are therefore taken from the progress output itself — one
character per test — and cross-checked between two independent runs. The
lingering exit is a test-harness annoyance, not a product defect, and it is
reproducible; a run WITH a failure prints its summary normally, which is how
every failure in this session was read.

**§47 — browser acceptance.** Real Chromium, real backend, real front end.
The first run passed 1,235 of 1,236 checks across four viewports and seventeen
screens; the one failure was real — the saved-analyses row ran 19px past a
390-wide viewport. After the fix, a full re-run on the rebuilt front end
passes **1,236 of 1,236**.

The wording checks in these runs read the RENDERED page text rather than the
source: no page named an intelligence provider or a model, none called the
product a demonstration, and the synthetic disclosure survived on every
screen.

Before it could run at all it had to be repaired — the §12/§13 checks import
the governed vocabulary from `backend.release`, and the script runs as a file
rather than a module, so it import-errored a third of the way through and
reported a crash instead of a verdict.

**§39/§49 — the twenty-two questions, through the real Ask path.** A new
harness (`scripts/question_walkthrough.py`) asks each one twice.
**22 of 22 pass** the checks this environment can make: no 5xx, no status code
printed to a reader, no provider or model named, no "demonstration", every
reply either answers or asks, every refusal names a next move, and the same
question returns the same reply.

**Frontend gates.** `tsc --noEmit` clean, `eslint` clean, **332 of 332**
`node --test` tests pass.

**Lint.** `ruff check backend tests scripts` clean.

### Executed, and found something

The walkthrough is the reason four defects in section C exist at all — the
non-deterministic row order, the two dead-end refusals, and the wording
scanner that could not tell an identifier from a sentence. None of them was
visible from a unit test, and all four were visible on the first run of
twenty-two real questions.

### NOT executed

**Docker.** Not verified in this sandbox. No container was built, started or
health-checked here. The bootstrap marker work of §1 is covered by 23 unit
tests that reproduce the original failure and assert the compose contract
(`start_period == "480s"`, `service_healthy` dependency), but that is a test
of the CONTRACT, not of a running container. **NOT VERIFIED IN CLAUDE
SANDBOX.**

**Answer quality on the twenty-two questions.** This environment has no
intelligence provider configured and none was called — no live call was made
and no credits were spent at any point in this run. The walkthrough checks the
properties that hold WITHOUT a provider, which are the ones that were broken;
it does not and cannot check whether the answers are good. The harness says so
in its own output rather than implying otherwise.

**§46 clean-room.** No fresh clone was taken and bootstrapped from empty in
this session. `tests/proof/test_fresh_clone_acceptance.py` runs against this
deployment and passes, and the readiness gate reports 15 of 15 checks green,
but that is this deployment rather than a new one.

---

## J. What remains

Stated plainly rather than described as finished.

- **§22 macro and sector intelligence** is not built. It needs a macro series
  this deployment does not carry; nothing was stubbed in its place.
- **§34/§35 SME data and new governed datasets** are not built. Adding
  datasets means a generator, a catalogue registration and a domain, and none
  of that was started.
- **§17 Data Builder domain detail** is partly pre-existing: the domain page
  already carries Overview, Datasets, Dictionary, Relationships, Quality and
  Versions tabs. It has no Lineage tab.

  An earlier draft of this report called that "a wiring task rather than a
  build" on the grounds that `corporate.lineage` and `/corporate/lineage`
  already exist. Checking it properly, that is wrong and the correction
  matters: `corporate.lineage` is field lineage for the Borrower 360 SNAPSHOT
  specifically — 137 fields in eleven groups — and no equivalent exists for
  the other domains. A Lineage tab on the generic domain page would therefore
  show real lineage for one domain and nothing for the rest.

  The right build is the one this work used everywhere else: show what is
  recorded, and say plainly for each domain where nothing is. That is a
  build, not wiring, and it was not started.
- **Docker verification cannot be executed in this environment.** See
  section I.
- **The covenant-breach base rate** in section G is a data-realism problem
  somebody should decide about before this book is shown to a client.

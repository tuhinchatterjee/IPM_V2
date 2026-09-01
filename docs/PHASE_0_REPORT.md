# Phase 0 — Accuracy Remediation Report

**Branch** `claude/vigilant-darwin-eohyi1` · **From** `8e7347b` · **To** `b8ea625`
· **Nine commits** · Reported separately, before the product-expansion phase, as
P0.18 requires.

Phase 0 was a remediation gate, not a feature. Nine defects were reproduced
through the real browser routes, their root causes found, and the architecture
changed so that each class of defect cannot recur. What follows is what P0.18
asks for, in its order.

---

## 1. Exact root causes

Nine defects (A–I) were reproduced through the live Investigation and Risk Case
endpoints. They had **seven** distinct root causes, and two defects each had two
independent causes — which matters, because fixing one of a pair leaves the
answer wrong and looking fixed.

**A/B — the answer was about the whole book instead of the cohort just defined.**
Two independent causes.

1. *Referent resolution only looked backwards.* `referents.py` resolved "them"
   against earlier TURNS. A pronoun whose antecedent is in the SAME message had
   nothing to resolve against, so the population silently became the portfolio.
   There was no intra-turn discourse model at all.
2. *A substring collision in the cohort reader.* `semantics.py` matched concept
   phrases with a plain `in`. "EAD" occurs inside "h**EAD**room", so the concept
   EAD was found inside a covenant-headroom clause, inherited that clause's
   "declining", and became a fifth cohort condition — "EAD rose" — that nobody
   asked for.

**C — a ranking was read as a filter.** `Condition.kind == "order"` names a sort
column and filters nothing, but the objective decomposition did not separate the
clause that DEFINES a population from the clause that RANKS it, so "rank them by
EAD" narrowed the population.

**D — the ECL decomposition was an ECL movement by sector.** No decomposition
method existed. Worse, the question was never reaching a planner: "exposure" in
the driver list was read as the MEASURE to compute rather than as a DRIVER, so
the ambiguity gate asked which exposure figure to use, and the question that most
needed the method got a menu.

**E — a Trace showing VALIDATED · 4 of 4 checks passed over a failed run.** Two
independent causes.

1. *Status was asserted, not derived.* "All checks passed" came from
   `if status == "succeeded"`, so a metadata lookup that succeeded at looking
   nothing up reported that its checks had passed. There were no checks.
2. *`_assurance` read a field that never existed.* It read `narrative.checks`.
   `Narrative` has no such attribute, so the guard silently read nothing and
   never fired.

**F — interpretations "not materially better than reading the table".** Prose
assembled out of whichever observations happened to fire, with no required
shape. Prose with no obligation to say anything in particular drifts toward the
safe and the general. Repeated borrower names were a second-order effect: the
concentration, driver and exception passes each legitimately name the largest
borrower, and the repetition exists only once their sentences sit together.

**G — a heatmap whose axes were the measure VALUES.** Chart selection had no
validation step behind it, so every distinct share became its own category and
the matrix came out a sparse diagonal with floating-point headers.

**H — floating-point noise on screen.** `figure(0, percent)` produced
"0.000000"; `scaleMoney` above 100bn raised a RangeError from
`minimumFractionDigits: 1` against `maximumFractionDigits: 0`.

**I — one anonymous 500 for every cause.** "Something went wrong on the server"
was returned for a missing dataset, an unreachable provider, a permission
refusal, a governed budget, and — reproduced by stopping Postgres — a database
outage, which is not a fault in CreditProbe at all.

Two further defects were found during the phase by the machinery built for it,
and are recorded here because they were live in the product:

- **"Which borrowers have a DSCR below 1.2?" answered about the wrong
  population.** `\b1\b` matches inside "1.2" — `.` is a non-word character — so
  the entity matcher resolved IFRS 9 stage filters of 1 AND 2 out of the
  threshold. 16 of 136 rows did not satisfy the filter the question was recorded
  as carrying. Found by the P0.8 gate.
- **The assurance ceiling could be bypassed by an unrecognised claim.** `_rank`
  returned 0 for an unknown status, so it compared as already-lower than any
  ceiling and passed through untouched. The real labels lowered correctly, which
  is why nothing had caught it. Found by P0.16 thread 8.

---

## 2. Same-turn discourse architecture

`backend/orchestration/discourse.py` (new). The separation is the design:
`referents.py` looks BACKWARDS at the conversation; `discourse.py` looks INWARDS
at one message.

Resolution order, as P0.2 specifies: same clause → an earlier clause in the same
message → working memory → clarification.

Resolution is by GRAMMAR, not by phrase. Mentions are found as pronouns, head
nouns, relative clauses and contrastive prepositions. A clause boundary requires
a coordinator — a bare comma is not one, so "For every sector, calculate the
Stage 2 share" stays one request. Restrictors are recognised by SHAPE
(`[a-z]+(?:ed|ing)\b`), not from a verb list. The binding constraint holds: a
pronoun cannot corefer with the noun phrase containing it, so in "the customers
driving them" the cohort containing the mention is not its own antecedent.

The substring collision was fixed at its root: `_pattern_for` now matches a
concept phrase on WORD BOUNDARIES, so EAD is no longer found inside headroom.

---

## 3. Objective coverage architecture

`backend/orchestration/objectives.py` (new). A request is decomposed into
objectives, each with an id, a description, an action, a planned task and a
status: COMPLETE, PARTIAL, UNAVAILABLE, NEEDS_CLARIFICATION or PLANNED. Eight
actions — SELECT, RANK, COMPARE, DECOMPOSE, AGGREGATE, ASSESS, DESCRIBE,
ATTRIBUTE — with a specificity order, so a clause matching two takes the more
specific one regardless of verb position.

`Coverage.presentable` is false while any objective is unsettled, and the P0.8
gate refuses to display an answer that is not presentable. **An answer is never
displayed while silently omitting objectives.**

The planner uses the same decomposition to separate DEFINING clauses from
RANK/COMPARE/DESCRIBE clauses, which is what closed defect C.

---

## 4. ECL decomposition method

`backend/orchestration/decomposition.py` (new), registered as the CERTIFIED
engine analysis `ecl_change_decomposition` and as an Analysis Studio method whose
certification claim the registry's own audit upholds.

**Order-neutral by Shapley value.** The naive one-at-a-time attribution also
reconciles, and hands every interaction term to whichever factor happened to move
last — so the same book tells a different story depending on the order somebody
wrote the loop in, and a committee cannot tell, because each version balances.
Each Shapley effect is the factor's average marginal contribution across every
ordering: order-neutral, exactly reconciling, and zero for a factor that did not
move.

**The factorisation, per account, over the population present in BOTH periods:**

    model_ecl = T × w × R × PD12 × LGD × K

`T` total exposure (scale), `w` the account's share of it (mix), `R` the lifetime
multiple its stage applies (SICR), `PD12` the twelve-month PD, `LGD`, and `K` the
residual.

**K is the honest part.** P0.4 says: do not pretend PD × LGD × EAD explains final
ECL where overlays, lifetime horizon and discounting make it incomplete. On this
book it does not — the product of EAD, the horizon-correct PD and LGD is roughly
seventy per cent of modelled ECL — and on the year to Q2 2026 the residual is the
**third-largest driver, moving adversely while everything else improved.** A
decomposition without it would have folded that into the PD effect and reported
an improvement in PD that was partly a model change.

Stage migration is separated from PD by construction (R moves, PD12 does not).
Mix is separated from exposure the same way (w moves, T does not). The overlay is
additive and attributed directly. Accounts present in one period only are their
own components.

**Nine components. Reconciliation exact:** on 16,346 accounts over the year to
Q2 2026, movement −2,426.705 and attributed −2,426.705, a gap of 1.3 × 10⁻¹¹
against a tolerance of 1 × 10⁻⁶ relative. Sector and customer contributions,
adverse and favourable separated, a waterfall, formulas on screen, and an
explicit statement of what it proves and does not prove.

---

## 5. Credit-risk ontology expansion

**19 concepts → 40. 12 contracts → 37.** Ontology version 1.0.0 → **2.0.0**, a
major move by the module's own rule, because two words changed meaning.

Every concept P0.5 names now has a governed contract carrying all twelve
attributes: aliases, canonical fields, definition, direction of deterioration,
units, valid aggregations, **invalid aggregations with the reason**, natural
grain, period behaviour, required joins, ambiguity policy, business invariants.
An Arabic alias field exists and is empty, which is the honest state until that
scope lands.

The invalid aggregations were the half that was missing, and the reason is what
makes them work: "you may not sum DSCR" is a rule somebody routes around; "the
sum of ten coverage ratios is neither a ratio nor a total" is an explanation they
do not. 18 contracts state a reason; 29 carry invariants; 4 are ambiguous.

**Two words became honest questions.** "PD" resolved silently to the twelve-month
figure — twelve-month and lifetime PD differ by a factor of three on this book and
IFRS 9 uses each in a different stage. "LGD" resolved to the modelled assumption;
realised LGD exists only for defaults that have closed. Both still answer without
asking when the question already said which it meant.

**Period behaviour is new and load-bearing.** A default, a cure and a migration
HAPPEN during a period; reading one as a position makes "the latest" a quarter's
worth of events rather than a level. Five concepts are declared flows and require
two periods.

**Three defects in the v1 ontology, found by holding it to its own promises:**
ECL coverage carried OPPOSITE directions of deterioration in the two registries
(higher coverage is more provision, the prudent direction — the disagreement
would invert an answer); the covenant-headroom contract used an id the registry
does not have, so it resolved to no concept and carried no fields at all; and the
derived Stage 2 share contract had no way to name its columns.

---

## 6. Curriculum sizes

| Library | Cases |
|---|---|
| Written development curriculum (25 families) | 33 |
| **Complex-query curriculum (12 categories, P0.6)** | **1,050** |
| Sealed holdout | 67 |
| Generated variants per case | 4 |

The twelve P0.6 categories, all at or above the required count: same-turn
referent 150, multi-clause 150, cohort comparison 100, borrower screens 100,
portfolio investigations 100, ECL decomposition 75, association-vs-causation 75,
period alignment 75, chart selection 75, Trace consistency 50, abstention 50,
error control 50.

The honest description of how they are built: the SPECIFICATION of every case is
reviewed once per category, the SUBJECT is governed (real sectors, real measures,
real periods, read from the ontology), and the PHRASING is generated
deterministically. Writing nine hundred sentences by hand would produce nine
hundred variations on one person's phrasing and a specification copied nine
hundred times, which is worse in both halves.

**No case carries an answer.** Every expectation is a statement about what the
product must DO. A stored answer is a number somebody quietly aligns to whatever
the product returns.

**No production raw client data.** Every subject is from the synthetic Saudi
universe, and a test asserts it.

---

## 7. Holdout isolation

The seal is unchanged and enforced by an import-graph test: no backend module
imports `intelligence_factory` at all — not only the holdout, because a module
that can import the curriculum can reach the holdout in one more line.

That test **caught this phase's own first design**: the review queue service
initially imported `curriculum.Case`. The service now returns plain data and
`intelligence_factory/reviewed.py` builds the case, so the dependency runs
factory → backend and never the other way.

---

## 8. Evaluation results by layer

`intelligence_factory/layers.py` scores the sixteen P0.7 layers independently.
Two rules make it honest:

- **The headline is the WEAKEST measured layer, never the mean.** A mean over
  sixteen layers is dominated by the cheap ones and hides exactly the layer a
  user's wrong answer came out of.
- **A layer that did not apply is excluded from its denominator**, never counted
  as a pass, and a layer with fewer than 30 observations states no rate at all.

Run against the live path on a stratified 96-case sample:

| Layer | Rate | Observed |
|---|---|---|
| Period and grain | 100.0% | 49 |
| Analytical plan | 100.0% | 85 |
| Compiled query | 100.0% | 41 |
| Result | 100.0% | 41 |
| Interpretation | 100.0% | 49 |
| Officer and model selection | 100.0% | 96 |
| Trace consistency | 94.6% | 112 |
| Capability and intent | 78.1% | 224 |
| Concept resolution | 76.2% | 101 |
| Invariants | 68.4% | 57 |
| **Visualization (weakest)** | **67.3%** | **49** |
| Same-turn referent · Objective decomposition · Dataset selection · Relationship selection · Error handling | not measured | < 30 |

**A single blended number would have reported roughly 87% and hidden all four
weak layers.** Visualization, invariants, concept resolution and capability are
**open findings carried into the next phase**, not things this phase fixed. Five
layers were not exercised enough to say anything about and are reported as
unmeasured, never as passing.

Two of my own probes were wrong before they were right, and both would have been
published as product scores: the compiled query lives at `runtime.query.sql`, not
`runtime.sql`, and cases asserted registry ids where a reading records labels. A
broken probe printed as a percentage is the same dishonesty as a bad case
specification.

---

## 9. 500 and error handling

`backend/api/failures.py` (new) classifies every exception into the ten P0.10
categories — PROVIDER, PLANNING, DATA, RELATIONSHIP, EXECUTION, VALIDATION,
PERSISTENCE, PERMISSION, BUDGET, UNKNOWN — by exception TYPE, never by message
text, walking the whole cause chain so a driver's `OperationalError` wrapped in a
`RuntimeError` is still PERSISTENCE.

Each category carries the status it deserves (a missing dataset is 404, not 500),
a message written for a credit officer, and the correlation id that finds the
log. No message carries a stack trace, path, SQL fragment, connection string,
environment variable or model id, and a leak check asserts that on the shipped
strings rather than on the intention.

**Verified live:** with Postgres stopped, the API returns HTTP 503,
`{"error":"persistence", …, "correlation_id":"5159c3eaa3a0"}` and the message
"This is an availability problem rather than a problem with your question —
nothing you asked for was wrong." The complex Contracting question returns 201
and an answer. 21 tests cover the taxonomy.

---

## 10. Trace consistency

`backend/agentic/consistency.py` derives stage status from persisted facts:
ANALYSED, VALIDATED, DECIDED, ACTIONED, RESULT. **SKIPPED is not PASS** — a check
that did not run reports NOT_RUN, not PASS. **Failure rolls up** — a failed task
fails its stage and the run.

`permit()` is a CEILING: it can only lower a claim, so a component whose own
reasoning was already honest is unaffected and one that was not cannot stay that
way. The bypass P0.16 thread 8 found is fixed: an unrecognised status now ranks
highest and is always brought down.

`_assurance` was rewired to read `answered.invariants` and `answered.written`,
the fields that exist, rather than the `narrative.checks` that never did.

Every answer now carries a `presentability` Trace node beside the invariant node,
recording the gate's verdict, its fourteen checks and the eight sections.

---

## 11. Decimal-format proof

`MAX_DECIMALS = 2` in `frontend/src/lib/format.ts`, applied in `byContract`,
`figure`, and `scaleMoney` (which now moves both bounds together). A
property-based test over ~2,000 seeded awkward values across every formatter
found two real defects: `figure(0, percent)` producing "0.000000", and
`scaleMoney` raising a RangeError above 100bn. `scrubDebris` catches three-or-more
decimal places and is colon-guarded so it cannot corrupt a timestamp.

The presentability gate re-checks prose, where no formatter runs. P0.16 thread 9
found no user-facing number over two decimals across four complex answers.

---

## 12. Visualization-selection proof

`backend/orchestration/viz_contract.py` (new) validates a chosen chart against
the result: axis roles (a measure cannot be an axis, a dimension cannot be a
magnitude), cardinality, label readability, mixed units, period ordering, missing
values and overplotting. `visualize.choose()` **replaces** an invalid chart and
says why, rather than annotating a misleading picture.

§G's own example of a valid heatmap — both axes dimensions, the cell a measure —
still passes. The defect case is refused: *"a heatmap would not say something true
about this result — 'Share Q2 2026' is a measure (percent), and a measure cannot
be an axis."*

The tests found a real defect: `read_shape` read the column rank with `or`, and
`RANK_SUBJECT` is 0. Every correctly ranked subject was demoted to context, so a
grouped result had no axis and was quietly drawn as a table.

P0.16 thread 5: the two-period sector-share result draws as a line on `period` —
a dimension, not a measure.

---

## 13. Attention review state model

`backend/agentic/attention.py` (new): NOT_RUN, RUNNING, COMPLETED_WITH_CASES,
COMPLETED_NO_CASES, FAILED, scoped to the period. **NOT_RUN is never conflated
with COMPLETED_NO_CASES.**

Verified live. Before any review: `NOT_RUN`, and the sentence is *"No portfolio
review of Q2 2026 has been completed, so nothing here has been checked yet"* —
never "nothing requires attention". After a real review through the agent worker:
`COMPLETED_WITH_CASES`, open 5, by level 5, ALL 5, listed 5 — **reconciling
exactly.**

---

## 14. Interpretation quality results

`backend/orchestration/sections.py` (new) gives every complex answer the same
eight sections: BOTTOM LINE, MATERIALITY, MAIN DRIVERS, BREADTH VS
CONCENTRATION, EXCEPTIONS, CREDIT-RISK INTERPRETATION, LIMITATIONS, NEXT BEST
ANALYSES. **A section is never dropped:** when its pass ran and found nothing it
says so, because a missing EXCEPTIONS section leaves the reader unable to tell
whether there were none or whether nobody looked.

CREDIT-RISK INTERPRETATION reads `Concept.higher_is_worse` from the ontology, so
ECL rising is deterioration and ECL coverage rising is not — the "weak credit
reasoning" in the defect list. The movement comes from the figures the direct
answer quotes, so the section cannot contradict the bottom line. Verified live:
*"For credit purposes this is improvement: expected credit loss fell"* against
*"ECL coverage fell … that is the adverse direction."*

Repeated names are collapsed once, over the assembled reading — the only place
that can see the repetition.

`backend/orchestration/presentable.py` (new) runs P0.8's fourteen checks in one
place before display, composing existing verdicts rather than re-deriving them. A
failure asks for REPAIR, CLARIFY or WITHHOLD, and the verdict is the most severe
remedy any mandatory failing check asks for. A check that can tell two failures
apart may lower its own remedy but never raise it.

Measured against fifteen real questions through the live path: **twelve SHOW, two
REPAIR, one WITHHOLD** — and the WITHHOLD was the genuine DSCR/stage-filter
defect described in §1.

---

## 15. Mandatory thread outcomes

**Ten of ten pass**, through the live Investigation and Risk Case endpoints.
Runner committed as `scripts/phase0_threads.py`; exits with the number of failing
threads.

| # | Thread | Outcome |
|---|---|---|
| 1 | Same-turn referent | 9 rows, never asks what "them" means |
| 2 | Two same-turn cohorts | downgraded and unchanged, both built |
| 3 | Broad Contracting investigation | succeeded, **no 500** |
| 4 | ECL decomposition | −2426.705 = −2426.705, 9 components, 10 sectors, 10 customers |
| 5 | Chart selection | line on `period` — a dimension, not a measure |
| 6 | Attention before a review | **NOT_RUN**, "nothing here has been checked yet" |
| 7 | Attention after a review | COMPLETED_WITH_CASES, 5 = 5 = 5 = 5 |
| 8 | Forced agent task failure | VALIDATED=NOT_RUN, ceiling lowers to NEEDS REVIEW |
| 9 | Decimals | no user-facing number over two decimals |
| 10 | Presentability | verdict SHOW, all eight sections |

**P0.17 gates:** ruff clean; **2,661 deterministic tests pass**, 16 skipped, none
failing; the agentic suite runs on the fake provider throughout; `tsc` clean;
eslint clean; **239 frontend tests pass**; ten of ten threads green.

---

## 16. No phrase-specific hard-coding

**Stated explicitly: no fix in Phase 0 keys off a specific phrase, borrower,
sector or question.** Every mechanism is structural:

- Referents resolve by GRAMMAR — pronouns, head nouns, relative clauses,
  contrastive prepositions — with restrictors recognised by word SHAPE
  (`[a-z]+(?:ed|ing)`), not from a verb list.
- Objectives decompose by ACTION VERB and clause structure, with a specificity
  order, not by matching known sentences.
- The concept collision was fixed with word boundaries, and the numeric one with
  numeric boundaries plus the governed `AMBIGUOUS_DIMENSIONS` rule that already
  existed — not by special-casing "1.2" or "DSCR".
- Deterioration direction is read from `Concept.higher_is_worse` in the ontology.
  A hand-written list of measure names was written during this phase and then
  **deleted**, because it was a second opinion about a governed field.
- The visualisation contract checks semantic ROLES, not chart names.
- Failure categories match exception TYPES, never message text.
- The curriculum's subjects come from the ontology, so a renamed concept breaks
  the corpus rather than silently producing cases nothing can satisfy.

---

## 17. No live API credits consumed

**Stated explicitly: no live Anthropic call was made and no API credits were
consumed during Phase 0.**

`ANTHROPIC_API_KEY` is not set in this environment and was never read, requested
or inspected. Every evaluation, every one of the ten threads, the portfolio
review and the whole 2,661-test suite ran on the deterministic path and the fake
provider. The layered evaluation's numbers in §8 are from the offline path, and
the report says so rather than implying a live measurement.

---

## Open findings carried forward

Phase 0 closed the nine reproduced defects and the two found during it. These
remain open and are named rather than averaged away:

1. **Visualization 67.3%**, **Invariants 68.4%**, **Concept resolution 76.2%**,
   **Capability 78.1%** on the 96-case sample. The layered evaluation exists to
   make these visible; making them green is the next phase's work.
2. **Five layers unmeasured** — same-turn referent, objective decomposition,
   dataset selection, relationship selection and error handling did not reach 30
   observations on that sample. A full 1,050-case run would measure them.
3. **The Analysis Studio's `can_certify()` is stricter than the registry's
   certification audit.** All 43 certified library entries pass the registry's
   gate and fail `can_certify()` on stored test cases. The two gates should
   agree, and today a reader could reach either conclusion.

**END OF PHASE 0.**

# Why this borrower is High Risk

**Scope.** The governed Early Warning signal engine — the named conditions with
declared thresholds — and how they combine into an overall risk level for one
borrower. Not the fitted Forward Risk Signal, which is a different thing and
has its own document (`EARLY_WARNING_METHODOLOGY.md`).

Everything here is computed from `SYNTHETIC_DEMO` data.

---

## The defect

Overall Early Warning risk was **the number of signals firing**.

That is a fact about the rule book rather than about the borrower. A name with
six stale-valuation and old-statement observations outranked one in covenant
breach, thirty days past due and downgraded two notches, because six is more
than three. An officer working down that list works down it in the wrong order,
and the list is the product.

## The first fix, which was also wrong

Counting was replaced with eight named rules — severity, persistence,
materiality, trajectory, breadth, credit events, credit-quality relevance,
external corroboration — each producing a sentence, and the level taken as the
worst of them.

On the live Q2 2026 book that put **88% of borrowers into High Risk**.

The reason is worth writing down, because it is the trap this whole area sets.
On a stressed portfolio most of those rules hold for most borrowers most of the
time. Breadth of two independent families is the **median** name. 48.6% of the
book carries at least one severe condition; 25.1% is on the watchlist; 22.4% is
booked at stage 2. Taking the worst of eight rules that each fire for a third
of the book fires for nearly all of it.

A High list holding seven names in eight is not a list anybody works. It is the
same defect wearing better prose.

## The rule as it stands

**Two things have to be true at once, and neither substitutes for the other.**

**Gravity** — something serious is established:

* a **severe credit event** is recorded against the exposure: a covenant
  breach, a restructuring, a booked stage 3, thirty days past due; or
* a **severe condition has persisted** — beyond its threshold in both the
  current and the previous observation period. One quarter is a reading; two is
  a direction; or
* a **pattern the threshold owner classes severe** matched.

**Corroboration** — the evidence is visible somewhere other than where it
started: at least **two risk families carrying evidence OTHER than the families
the gravity itself sits in**. Two covenant conditions are one observation told
twice, so a second covenant signal cannot corroborate a covenant breach.

| Level | Rule |
| --- | --- |
| **HIGH** | Gravity **and** corroboration. |
| **MEDIUM** | Gravity without corroboration, or corroboration with a severe or worsening condition but nothing established. |
| **LOW** | Neither, or what fired has since come back. |

A covenant breach on a name whose every other measure is inside its threshold
is a covenant breach: serious, and a conversation, not a crisis. The same
breach on a name whose liquidity and IFRS 9 position have moved with it is a
High.

### On the live book

| Level | Borrowers | Share |
| --- | --- | --- |
| HIGH | 898 | 28.1% |
| MEDIUM | 1,379 | 43.1% |
| LOW | 919 | 28.8% |

3,196 borrowers assessed at Q2 2026. Twenty-eight per cent High is high for a
portfolio, and this portfolio is stressed by construction: 12.9% in covenant
breach, 8.6% thirty days past due, 4.6% booked at stage 3. The figure is
reported rather than tuned.

### What is deliberately not used

* **Signal count.** Six stale-valuation observations are not worse than one
  covenant breach.
* **Materiality, as a driver of the level.** A small facility can be in as much
  trouble as a large one. Exposure decides who reads the warning, not how
  serious it is — it belongs to *priority*, which answers a different question.

### It can come back down

A framework that can only escalate is one nobody argues with, and therefore one
nobody trusts. Where nothing serious is established and the only thing holding
a borrower at Medium is trajectory, and more conditions have come back within
threshold or moved towards it than have moved further beyond it, the level
comes down and says so. A name with one measure drifting and three recovering
is recovering.

### Three questions, three answers

They are genuinely different, and the screen shows all three:

* **Severity** — how bad the worst RULE is.
* **Risk level** (this document) — how serious the BORROWER is.
* **Priority** — what to DO about it, which is where exposure comes in.

There is no score anywhere in any of them. Each rule that holds produces a
sentence, and a reader who disagrees with the level can see which rule put it
there and argue with that rule. A weighted score offers them nothing to argue
with, which is why nobody ever argues with one and why nobody ever trusts one.

---

## TAC — the three detection mechanisms

TAC was undefined in this repository, and the product said so rather than
inventing an expansion. The definition was subsequently supplied:

| | | At this installation |
| --- | --- | --- |
| **T** — Threshold-based | A measurable indicator crossed a governed warning level. | 40 signals |
| **A** — Action-based | A meaningful credit event happened and was recorded. | 9 signals |
| **C** — Classifier-based | Several pieces of evidence combined into a recognised risk pattern. | 5 classifiers |

Derived from each signal's own test type in `taxonomy.py` rather than typed
onto forty-nine signals by hand. **Detection mechanism and layer are
orthogonal**: TAC is how a signal is detected, the four layers are what it is
about, and every governed signal carries exactly one of each.

### The five classifiers

The C is the part most frameworks overstate. These are configured, not
aspirational, and each publishes what it is made of and how many components
have to fire:

| Classifier | Fires on | Severity |
| --- | --- | --- |
| Liquidity stress | 3 of 5 | SEVERE |
| Rating lag | 2 of 4 | CONCERN |
| Hidden deterioration | 3 of 5 | CONCERN |
| Stage 2 candidate | 2 of 5 | CONCERN |
| External vulnerability | 2 of 5 | WATCH |

A signal that is not part of one is reported as threshold-based or
action-based rather than dressed up as a pattern. A build-time test asserts
that no classifier names a component signal the taxonomy does not provide.

---

## Layer 4

Was empty, and said so. Six signals are now configured against the external and
network fields the corporate snapshot publishes: an agency outlook on negative,
a withdrawn external rating, sector concentration, network risk,
connected-group size and modelled contagion.

Small and credible rather than artificially full. The layer still does not read
the macro SERIES — GDP, rates, inflation, FX, commodity prices reach a borrower
through its sector and its group rather than through a signal of their own —
and it says so on the screen.

---

## The borrower scorecard

Every governed condition tested against one borrower, grouped by layer, with:

    Current | Previous | Movement | Threshold | Status | Severity |
    Persistence | Detection (TAC) | What it means

**Every** condition, over the line or inside it. A layer showing three amber
rows and hiding the eleven green ones reads as an emergency whatever the
borrower is doing, and the reason to publish a threshold is so somebody can see
a measure sitting comfortably inside it. Untested conditions are shown as
untested with the reason: "nothing fires" and "nothing could be tested" are
different answers and only one of them is reassuring.

The assessment comes first, above any component table. A reader who stops after
the first screen should still have the answer rather than the workings.

## The timeline

Whether the bank has been watching this for two years or it appeared last
quarter. Each period is a real evaluation against that period's own reporting
row and the row before it — never an interpolation, never carried forward from
the latest assessment. A timeline that repeats today's answer at every date is
a chart of one fact, and a test asserts the firing counts actually differ
across periods.

## Deep link and downloads

The Borrower 360 link carries **both** the customer id and the reporting
period. A link that opens Borrower 360 at "latest" from a Q1 warning shows a
different quarter's numbers beside the same sentence, and the reader has no way
to know.

Two workbooks (`.xlsx`):

* **the borrower scorecard** — assessment, one sheet per layer, and a SOURCE
  sheet naming the dataset, field, test, threshold, owner and version behind
  every figure;
* **the watchlist** — the ranked book at one reporting date, with the
  methodology on its own sheet so the risk level is not a column nobody can
  account for.

Nothing in either is recomputed. Every value is the one the screen read: a
workbook that recomputes anything will eventually disagree with the screen it
was downloaded from, and the reader will believe whichever one they opened
last. Both carry the `SYNTHETIC_DEMO` disclosure, because the workbook leaves
the product and the disclosure has to leave with it.

---

## Where the code is

| | |
| --- | --- |
| The rule | `backend/early_warning/assessment.py` |
| The classifiers | `backend/early_warning/classifiers.py` |
| The signals and TAC | `backend/early_warning/taxonomy.py` |
| The scorecard and timeline | `backend/early_warning/scorecard.py` |
| The workbooks | `backend/early_warning/workbook.py` |
| The routes | `backend/api/routers/early_warning.py` |
| The screens | `frontend/src/components/early-warning/` |
| The tests | `tests/early_warning/test_assessment.py`, `tests/api/test_early_warning_api.py` |

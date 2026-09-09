# What-If: scenario intelligence over the corporate book

## The defect this replaced

What-If was one engine function. It took a preset name, multiplied every
facility's booked ECL by a factor, and returned five rows of totals. It could
not answer a single question a credit officer actually asks:

- what a two-notch downgrade does — because a downgrade is not a multiplier;
- which Stage 1 borrowers cross into Stage 2 — because it never re-staged;
- how much of the movement is the rating and how much is the measurement basis
  — because it never separated them;
- which names caused it — because it never computed a borrower.

---

## Four governed modules

### `backend/ifrs9/policy.py` — one definition of staging and measurement

The SICR triggers, the default presumption, the scenario weights, the lifetime
horizon and the measurement basis for each Stage were written once inside the
universe generator and read by nothing else. That was survivable only while the
only thing that staged a borrower was the thing that created it.

What-If has to **re-evaluate** staging against a hypothetical PD. A second copy
of the rules is a second answer waiting to disagree with the first, so the
policy moved here, the generator imports it, and a test asserts the constants
are the same objects.

| Trigger | Rule |
|---|---|
| Relative PD increase | 12-month PD at least **2×** its level at origination **and** at least **2.00pp** higher |
| Absolute PD level | 12-month PD at or above **13%** |
| Days past due | **30** or more days past due |
| Default presumption | **90** days past due, or a recorded default event |

Measurement: Stage 1 on twelve-month expected loss, Stages 2 and 3 on lifetime.
That single line is why a Stage 1 → 2 migration multiplies a provision when
nothing else about the borrower moved.

### `backend/whatif/masterscale.py` — a notch is worth what the scale says

Fourteen grades, twelve PD band edges, read from the bank's own scale. Each
grade carries the **geometric** mid-point of its band — geometric because the
bands widen multiplicatively, and an arithmetic mid-point would put almost
every investment-grade name at the top of its band.

```
AAA  0.03%   BBB+ 0.24%   BB   2.08%   CCC 18.38%
AA   0.06%   BBB  0.42%   BB-  3.49%   CC  36.77%
A    0.13%   BBB- 0.72%   B+   5.81%
             BB+  1.23%   B    9.87%
```

The shock is applied as the **ratio** between two grades' masterscale PDs:

    stressed_pd = borrower_pd × (masterscale(stressed) / masterscale(opening))

BBB → BB+ is a **2.939×** factor. A borrower at the strong end of BBB stays at
the strong end of BBB-: the scale decides how far the band moved, the borrower
keeps its place inside it. Snapping every downgraded name to its new grade's
central PD would destroy calibration the bank already has.

A downgrade **stops at the weakest performing grade**. Default is an event, not
something arithmetic produces.

### `backend/whatif/sensitivity.py` — the versioned macro matrix

Eight variables, each with a PD effect per unit shock, an optional LGD effect,
financial-measure effects, and sector multipliers reconciled against the
governed sector vocabulary. Owner, version and effective date on every row.

**Each row states its own basis, and none of them says "estimated from default
data", because none of them was.** Presenting a configured coefficient as an
empirical fact is the failure mode that discredits every honest figure beside
it.

| Variable | PD effect | Most exposed |
|---|---|---|
| Policy rates | +6% per 100bps | Real Estate 1.9×, Contracting 1.6× |
| Real GDP | +10% per 1pp fall | Wholesale & Retail 1.5×, Contracting 1.4× |
| Oil and commodities | +7% per 20% fall | Oil & Gas 2.4×, Petrochemicals 2.1× |
| Property values | +3% per 10% fall, **+3.5pp LGD** | Real Estate 2.2× |
| Shipping disruption | +14% per severity step | Shipping 2.5×, Transport 2.2× |

The property row's LGD effect is marked **structural** rather than a management
assumption: a lower security value recovers less, and that follows from the
definition rather than from a fitted relationship.

### `backend/whatif/engine.py` — borrower by borrower, then added up

```
Baseline → Shocks → SICR re-read → Re-stage → Re-measure ECL → Aggregate
```

Computing a portfolio ECL and allocating it down produces a number no borrower
can be shown to have caused, and the first question anyone asks about a
stressed provision is "which names?".

**The base column ties to the accounts.** The baseline is the *reported* ECL,
not a recomputation of it; only the ratio of the two measurements is modelled:

    stressed_ecl = reported_ecl × (measured_stressed / measured_baseline)

Verified by hand against the source parquet: for CORP-103543 (BBB → BB+), PD
0.9198 → 1.6140 and ECL 9.88 → 29.05, both matching an independent
recomputation. The BBB baseline sums to **301.29 against 301.29 reported**. The
base scenario's incremental ECL is **0.0 exactly**.

---

## The SICR finding

A two-notch BBB downgrade moves **58 of 1,126** borrowers into Stage 2. Not all
of them, and that is the framework working rather than failing: the relative
trigger needs a doubling of PD **and** two hundred basis points of absolute
increase, and a strong investment-grade name clears neither on two notches.

That is worth knowing before a committee. The Stage 2 population is far less
sensitive to a downgrade cycle than to an outright PD deterioration — a 75% PD
shock on Stage 1 moves **518 of 2,528**.

The **rating-deterioration assumption** exists and is **offered rather than
applied**. Turning it on because the question asked about migrations would make
the answer a tautology: "everyone who fell two notches has a SICR, because we
assumed a two-notch fall is a SICR." Ask with *"assuming a downgrade is a
significant increase in credit risk"* and it is applied and stated.

---

## Reading a scenario out of a sentence

Two rules the reader will not break.

**A period is never a magnitude.** Time is masked before any number is read, so
"What happens to ECL in Q1 2026 if PD rises 25%?" produces a 25% PD shock and a
Q1 2026 window, never a 2026% one.

**A unit is never assumed.** Percentage points come from `pp`, a percentage
from `%`, basis points from `bps`. A bare number against LGD is read as
percentage points — how a credit officer states it — and the answer says which
reading it took.

Two bugs found by running the acceptance questions:

- a trailing `\b` after `%` never matches, because `%` is not a word character
  and neither is the `?` or space after it. Four questions were silently losing
  their shock;
- `_direction` assumed the anchor sat in the middle of its window, which is
  false near the start of a sentence — so "EBITDA **falls** 15%" was read as a
  rise and the shock did nothing. The offset is now computed.

---

## Twelve configured scenarios

Every one runs against the live book. Selected results, Q2 2026:

| Scenario | Borrowers | Incremental ECL | Stage 2 migrations |
|---|---|---|---|
| Base | 3,244 | 0.0 | 0 |
| One-notch downgrade | 3,244 | +7.9% | 8 |
| Two-notch BBB downgrade | 1,126 | **+296.9%** | 58 |
| PD +25% | 3,244 | +22.2% | 104 |
| Rates +200bps | 3,244 | +13.3% | 61 |
| EBITDA −15% with rates +200bps | 3,244 | **+47.6%** | 219 |
| Collateral −20% | 3,244 | +25.4% | 0 |
| Shipping disruption | 114 | +33.1% | 9 |

The collateral scenario producing **zero** migrations is the engine being
right: a security haircut changes what is recovered, not the likelihood of
default, so LGD moves and PD does not.

---

## Where it is reachable

- **Ask** — any hypothetical routes to `whatif_scenario` before the analytical
  planner, because a question about rows that do not exist yet has no rows to
  select.
- **Stress Testing screen** — configured and custom scenarios, the borrower
  table, the sector breakdown, the calculation steps, the sensitivity rows, and
  the three configuration tabs that make the masterscale, the matrix and the
  staging policy inspectable.
- **`/api/v1/whatif/*`** — configuration, scenarios, run, ask, compare,
  sensitivity.
- **Product knowledge** — four answers explaining the mechanism, including why
  a downgrade often does *not* move a Stage.

---

## What is still open

1. **"These borrowers" resolves to the whole book unless the thread carried
   identifiers.** The orchestrator passes carried borrower IDs where the
   conversation state holds them; where it does not, the scenario runs on the
   population the question names and says so. A dedicated referent pass for
   scenario follow-ups is not built.

2. **Covenant re-testing under stress is reported, not re-evaluated.** The
   summary counts borrowers already in breach. Re-running covenant tests
   against stressed financials needs the covenant definitions expressed as
   evaluable expressions, which they are not yet.

3. **The sensitivity coefficients are management assumptions.** Stated on every
   row and in every answer. Replacing them with estimated elasticities is a
   Credit Risk Analytics exercise, not a code change.

4. **Scenario saving is in-memory.** `stress_scenarios` exists as a table and
   the engine's scenarios are typed objects, but persisting a user's custom
   scenario through the API is not wired.

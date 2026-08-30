# The corporate Borrower 360 universe

**Everything described here is synthetic.** Every row of every dataset carries
`origin = SYNTHETIC_DEMO`, and every catalogue entry is marked synthetic. It
describes no real company, no real ownership structure and no real bank's
book, and must not be presented as client data.

Covers B1–B7 of the Borrower 360 phase: the universe, the semantic snapshot,
the nineteen governed domains, field coverage, lineage, search and entity
resolution. The derived relationship graph (B13–B34) is a separate build and
is **not** included here — the graph-derived fields of the snapshot are marked
`NOT COMPUTED`, not zero.

Rebuild it with:

```
.venv/bin/python scripts/build_corporate_universe.py
```

One seed, no wall clock, no external call. Two runs on two machines produce
byte-identical output, so every figure quoted below is the figure a reader
sees.

---

## 1. Scale (B1)

| | |
|---|---|
| Distinct corporate borrowers | **3,800** |
| Quarterly snapshots | **16**, Q3 2022 → Q2 2026 |
| Smallest quarter, by active borrowers | **3,253** |
| Largest quarter | 3,348 |
| Borrower-quarter rows | 52,998 |

B1's floors are ≥3,200 distinct borrowers, ≥16 quarters and more than 3,000
active rows in every quarter, inside a 3,500–4,000 target band. All are met
with margin, and each is asserted against the built data rather than against
the constant that was meant to produce it — a test that reads `ENTITY_COUNT`
and asserts it is 3,800 proves the constant, not the universe.

Borrower identifiers are stable across the whole window. Entries and exits
both occur: borrowers arrive through the period, and leave by write-off after
a seasoned default or by refinancing away. Exits are drawn against latent
quality rather than uniformly, so survivorship carries information — which is
the point of a sixteen-quarter panel.

### Row counts, by dataset

| Dataset | Rows |
|---|---:|
| `corporate_covenants` | 162,257 |
| `corporate_facilities` | 141,575 |
| `corporate_collateral` | 100,943 |
| `corporate_borrower_360` | 52,998 |
| `corporate_customer_master` | 52,998 |
| `corporate_ratings` | 52,998 |
| `corporate_ifrs9` | 52,998 |
| `corporate_delinquency` | 52,998 |
| `corporate_limits` | 52,998 |
| `corporate_profitability` | 52,998 |
| `corporate_ownership_edges` | 38,436 |
| `corporate_financials` | 19,000 |
| `corporate_graph_nodes` | 17,762 |
| `corporate_watchlist` | 14,121 |
| `corporate_entity_resolution` | 10,092 |
| `corporate_supply_chain` | 7,110 |
| `corporate_guarantees` | 2,555 |
| `corporate_exposure_network` | 2,120 |
| `corporate_restructuring` | 1,576 |
| `corporate_macro` | 16 |

---

## 2. Why it is simulated, not sampled

Random rows would give the relationship graph nothing to find. Hand-tuned rows
would give it exactly what somebody decided it should find. So every borrower
carries a latent credit quality following a persistent process driven by a
common macroeconomic factor and its sector's sensitivity to it, and every
observable — the rating, the leverage, the days past due, the covenant
headroom, the IFRS 9 stage — is a reading of that one state through a
different, noisy instrument.

Two consequences matter for what the rest of the phase claims:

* deterioration is genuinely **predictable** a quarter ahead, so an early
  warning is a finding rather than a coincidence; and
* a borrower's neighbours in the ownership graph share its parent's shocks, so
  a contagion measure computed over the graph is measuring something that was
  actually put there.

### The cycle

Peak-to-trough of about 0.65 of a quality unit: mildly positive through 2023,
weakening across 2024, a trough in 2025 and a partial recovery into 2026.

| | Q3 2022 | Q2 2025 | Q2 2026 |
|---|---:|---:|---:|
| Median twelve-month PD | 0.25 % | 0.73 % | 0.42 % |
| Stage 1 | 85.5 % | 63.7 % | 75.1 % |
| Stage 2 | 14.0 % | 31.3 % | 21.2 % |
| Stage 3 | 0.5 % | 5.1 % | 3.7 % |
| ECL coverage | 1.10 % | 3.49 % | 1.82 % |
| Covenant tests breached | 3.0 % | 15.3 % | 19.8 % |

Stage 2 peaks near 31 %. That is high, and it is what IFRS 9's **relative**
SICR test arithmetically produces for a downturn of this size: the test
compares a borrower's PD against its *origination* PD, not against last
quarter's. The honest response was to make the recession a plausible depth
rather than to widen the SICR threshold until the stage mix looked
comfortable, so the trigger reported on any screen is the trigger the standard
describes. Covenant breaches peak later than stages because they are tested
against the latest **published** statement, which lags by a year.

### Five calibrations that were wrong first time

Recorded because each one produced plausible-looking data that was wrong, and
because the fix in each case was to the mechanism rather than to a threshold:

1. **The cycle compounded.** Added to the AR(1) as an innovation, a factor held
   at −0.5 moved quality by −0.5·β/(1−ρ) — seven times the intended shift — and
   the whole book defaulted by the trough. The mean the process reverts to is
   now the cycle level; only the deviation persists.
2. **The master scale graded a 40 % PD as "D".** A default grade reached from a
   PD band makes the default rate unmeasurable, because the grade and the
   outcome stop being separate facts. D is now set by the default event; the
   thirteen performing grades come from the PD.
3. **PD at origination was read from the first observed quarter.** That anchors
   every relative SICR test to the top of the cycle, and put half the book into
   Stage 2 by 2025 as an artefact of the generator's start date. It now comes
   from the borrower's through-the-cycle quality, which is what an
   origination-grade record actually holds.
4. **Each fiscal year re-drew its idiosyncratic noise.** Every company
   re-levered annually in a random direction, and covenants set with headroom
   at origination breached on drift alone. Idiosyncratic character is now a
   fixed trait with a small yearly innovation.
5. **Covenant thresholds were market-standard absolutes.** Four and a half
   times leverage for everybody breaches a quarter of the book on day one,
   because the standard is a starting point for a negotiation. Thresholds are
   now set against the borrower's own earliest statement with 30–75 % headroom,
   as a credit agreement does.

---

## 3. The nineteen governed domains (B3)

Each declares its **grain**, its owner, and what it is authoritative for.
Grain is the property most often misunderstood about a table and the one that
makes a wrong answer look right: `corporate_covenants` is one row per covenant
*test*, so counting its rows counts tests and not borrowers.

| Domain | Owner | Grain |
|---|---|---|
| CORPORATE CUSTOMER MASTER | Client Data Management | borrower × quarter |
| CORPORATE RATINGS | Credit Risk – Rating Unit | borrower × quarter |
| CORPORATE FACILITIES / EXPOSURE | Credit Administration | facility × quarter |
| CORPORATE IFRS 9 | Impairment | borrower × quarter (obligor staging) |
| CORPORATE DPD / DELINQUENCY | Collections | borrower × quarter |
| CORPORATE FINANCIALS | Credit Analysis | borrower × fiscal year |
| CORPORATE COVENANTS | Credit Administration | covenant test × quarter |
| CORPORATE COLLATERAL | Credit Administration | collateral item × quarter |
| CORPORATE GUARANTEES | Credit Administration | guarantee edge |
| CORPORATE LIMITS / LARGE EXPOSURES | Portfolio Risk | borrower × quarter |
| CORPORATE WATCHLIST / QUALITATIVE SIGNALS | Watchlist Committee | signal raised |
| CORPORATE RESTRUCTURING / FORBEARANCE | Special Assets | concession granted |
| CORPORATE PROFITABILITY / RAROC | Business Finance | borrower × quarter |
| CORPORATE OWNERSHIP & CONTROL GRAPH | Group Risk | observed edge assertion |
| CORPORATE SUPPLY CHAIN GRAPH | Sector Research | supplier–buyer pair |
| CORPORATE EXPOSURE NETWORK | Portfolio Risk | financial claim |
| CORPORATE CONNECTED COUNTERPARTY GRAPH | Group Risk | borrower × quarter (derived) |
| CORPORATE ENTITY RESOLUTION | Client Data Management | source record |
| CORPORATE GRAPH DATA QUALITY | Group Risk | data-quality issue |

Twenty datasets are registered in the governed catalogue, with seven declared
relationships — **two of them FORBIDDEN**:

* `corporate_borrower_360 → corporate_covenants`. Different grain. The
  snapshot is one row per borrower-quarter and covenants are one row per test,
  so the join multiplies every exposure figure by the borrower's covenant
  count.
* `corporate_supply_chain → corporate_connected_groups`. B21: commercial
  dependence is not control, and joining supply-chain edges into group
  formation is exactly the mistake that turns a sector into one connected
  counterparty.

---

## 4. The semantic snapshot (B2, B4, B5)

`corporate_borrower_360` — 52,998 rows, one per borrower per quarter,
**137 fields**.

| Group | Fields |
|---|---:|
| IDENTITY | 21 |
| RATING | 11 |
| FINANCIALS | 24 |
| EXPOSURE | 14 |
| IFRS9 | 15 |
| DELINQUENCY | 8 |
| COVENANTS | 7 |
| COLLATERAL | 7 |
| LIMIT | 6 |
| GRAPH SUMMARY | 19 |
| DATA QUALITY | 5 |

### It is authoritative over nothing

| Authority | Fields |
|---|---:|
| AUTHORITATIVE | **0** |
| COPY | 78 |
| DERIVED | 59 |

B2's rule is that the snapshot must not become authoritative over the domain
it copied from. That is not kept by intention; it is kept by three mechanisms
that would each have to be defeated separately:

1. Every field is built from a `lineage.Field` naming its source domain,
   dataset, field, period, transformation and authority — and `AUTHORITATIVE`
   is used by none of them.
2. The assembler **refuses** to publish a column with no lineage entry, and
   raises if a declared field was not assembled.
3. The catalogue registers `corporate_borrower_360` with
   `authoritative_for: []`, where the dataset resolver reads it. It is the
   widest and fastest dataset in the catalogue and would otherwise be the
   natural default for any borrower attribute — which is exactly why.

### Source period is carried, not assumed

A borrower's leverage in Q2 2025 comes from the FY2024 statement. That is a
different period from the snapshot's, and showing it as a Q2 2025 number
without saying so is how a year-old ratio gets quoted as current. Financials
join **as-of**: the latest statement *published* on or before the quarter end,
never the fiscal year matching the quarter — a statement the borrower had not
filed yet was not information the bank had.

`financial_statement_age_days` carries the gap. 15,153 of 52,998 rows
(28.6 %) are flagged stale, either because the latest statement is more than
540 days old or because the oldest collateral valuation is past its
revaluation interval.

Mean source completeness is **99.93 %**.

### Fields the graph has not produced yet

23 fields — the 19 GRAPH SUMMARY fields plus `group_id`, `group_name`,
`group_utilisation_pct` and three data-quality fields — are filled with the
sentinel `NOT COMPUTED`, **not zero**. A network risk score of zero is a
measurement; "no graph has run" is not, and a screen that cannot tell them
apart will present the second as the first.

For the same reason `corporate_limits.group_utilisation_pct` is null with
status `NOT YET COMPUTED`: "the group" is a derived answer that depends on how
connectedness was defined, and a number written into the limits domain before
the graph has been asked would make that domain quietly authoritative over a
question nobody has put.

---

## 5. Search (B6)

Three shapes of answer, because what a user wants back differs:

* **single** — one borrower, by identifier or name.
* **multi** — a hand-picked list, shown side by side.
* **segment** — everything matching a set of filters, aggregate first.

Identifier fields match exactly; name fields match on a normalised contains
that strips legal-form words, so "Al Waha Trading LLC" finds "Al Waha Trading
Company". Arabic names are searched raw — the Latin normaliser strips English
legal-form words and does nothing useful to an Arabic name, so running it
there would be a no-op dressed up as handling.

Two honesty signals in the result contract:

* A **single**-borrower lookup that matched several names reports
  `ambiguous: true`. Names in this book share stems, so "Al Waha Trading"
  legitimately matches six companies, and returning the first as though it
  were the answer is how a screen shows somebody else's exposure under the
  name that was typed.
* A **multi** cohort reports `not_found` by name. A borrower absent from the
  quarter has exited or has not yet arrived — an answer, not an omission.

Segment averages are **exposure weighted**. An unweighted mean across four
hundred borrowers is dominated by the smallest ones and answers a question
nobody asked.

---

## 6. Entity resolution (B7)

10,092 source records across three systems resolve to 3,800 canonical
entities, on FRAMEWORK.md's precedence:

| Method | Records | Auto-acceptable |
|---|---:|---|
| Exact commercial-registration / national-ID | 7,696 | yes |
| Normalised name + address | 1,474 | yes, above the confidence floor |
| Registration-prefix evidence | 418 | yes, above the confidence floor |
| Fuzzy name + shared director | 504 | **never** |

| Review status | Records |
|---|---:|
| Auto-accepted | 9,526 |
| Human confirmed | 248 |
| Pending review | 251 |
| Human rejected | 67 |

**Destructive merges: 0.** The mapping is additive — every source record stays
exactly as its system holds it and `canonical_entity_id` is a new column
alongside, never a replacement. A rejected match resolves to nothing, left
explicitly empty rather than pointed at a guess.

Fuzzy name plus shared director is never auto-accepted at any confidence,
because it is precisely the rule that merges two unrelated family companies
with common surnames and a common non-executive director. About a fifth of
fuzzy matches are rejected on review — which is the reason the ability to undo
them is the point, and why the rule exists.

---

## 7. Two books in one catalogue (B44)

Registering these twenty datasets broke questions that had always worked,
because the corporate universe is a **different portfolio** from the credit
book and shares almost all of its vocabulary: both have customers, exposure at
default, an IFRS 9 stage, a covenant.

Every governed dataset now declares a `portfolio_scope` — `CREDIT_BOOK`
(the default, so anything that predates the distinction is unchanged) or
`BORROWER_360`. Retrieval decides which book a question is about before
deciding which dataset in it, and reaches the Borrower 360 book only when the
question names something only that book has: an ultimate beneficial owner, a
connected counterparty, a supply chain, a relationship graph. "Corporate" is
deliberately **not** one of those words — it is a segment of the credit book
as well as the name of this module.

Three separate failures came out of that omission, and none announced itself
as a failure:

* **Retrieval displacement.** `corporate_customer_master` carries "customer"
  in its technical name, so the rule that always retrieves a dataset the
  question names pulled it into every question about customers.
* **A retrieval cap deciding what the product knows.** The planner used the
  top-eight retrieved datasets as its field universe. `portfolio_facility`
  fell out of the eight, the concept map's resolved candidate was judged
  unavailable, and "the ten largest customers by exposure at default" came
  back as *"which figure should CreditProbe measure?"* — a clarification, with
  no clue that a budget had removed a governed concept from the vocabulary.
* **A field name matched inside a word.** The metadata assistant matched field
  names by substring, so `city` matched inside "airspeed velo**city**" and a
  question about swallows was answered with the definition of a city column.
  That defect was always there; the corporate master is simply the first
  dataset to carry a field short enough to expose it.

All three are fixed and pinned by `tests/corporate/test_scope_separation.py`.

---

## 8. Caveats

* Synthetic performance is not empirical validation.
* The eligible-capital reference, the single-name, group and investigation
  thresholds, the forbearance probation period and the RAROC capital
  assumptions are **demonstration values**, carried on every row as
  `UNVERIFIED REGULATORY PARAMETER` or an equivalent caveat. They are not a
  verified statement of any binding limit under any regulation and must be
  replaced with the institution's own before any figure derived from them is
  relied on.
* Commercial dependence is not control, and supply-chain edges are never on
  their own a basis for a regulatory connected group.
* Entity-resolution errors propagate downstream. 251 records are pending
  review and 67 were rejected; any figure aggregated by canonical entity
  inherits that uncertainty.

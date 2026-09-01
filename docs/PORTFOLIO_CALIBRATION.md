# Portfolio calibration and the demonstration scenario

Two synthetic books stand behind the product. The **core portfolio book**
(`scripts/generate_saudi_universe.py`) is facility-grain and drives the
portfolio, IFRS 9 and Early Warning screens. The **corporate book**
(`backend/corporate/`) is borrower-grain and drives Borrower 360, the
relationship graph and the corporate credit domains. They share a sector
list, a scenario and a set of plausibility standards, and nothing else.

This note records what was recalibrated, why, and what holds it there.

## The sector mix

Seventeen sectors. Two were added and one was resized.

| Change | Reason |
| --- | --- |
| **Oil & Gas** added, 6% | A Gulf corporate book without it is not a Gulf corporate book. |
| **Shipping** added, 4% | The external-intelligence domain was already publishing Strait of Hormuz events against a sector no borrower belonged to, so nothing could be joined to them and any connection an analyst drew would have been invented. |
| **Financial Services** 3% → 7% | At 3% it was 386 facilities, too small to be a headline story and too small to be worth a sector question — and it was nonetheless the story the AI reached for. A bank's non-bank financial line (leasing, insurance, investment firms, exchange houses) is material. |
| Everything else | Re-weighted to make room; the shape is unchanged, with contracting and real estate still the two largest concentrations. |

`Transport & Logistics` lost its "Shipping & Ports" sub-sector to the new
`Shipping` sector and gained `Port Services` in its place.

Two sector-keyed policy maps in `scripts/domains_extra.py` — the risk-appetite
limits and the climate transition bands — were keyed on sector names that no
borrower carried (`Construction & Contracting`, `Energy & Utilities`,
`Professional Services`, `Public Sector`). Most of the book fell through to the
default, so the limits a committee had supposedly set were not the limits being
tested. They are keyed on the real names now.

## The Strait of Hormuz scenario

`backend/scenarios.py`. One module, read by both books.

It is a **synthetic demonstration scenario**. It is not a report of a real
current event, and no answer built on it may present it as one:
`SCENARIO_STATUS` travels with every event row in the external-intelligence
domain and says so in words.

The scenario is applied to **latent credit quality** at generation time —
never written onto an outcome column. Everything the credit officer then sees
(the PD, the grade, the arrears, the utilisation, the covenant headroom, the
stage migration) is that one shift travelling through the same machinery as
every other borrower's, which is what makes the transmission traceable.

Impact at the peak, as a shift in latent quality:

| Sector | Shift | Position in the transmission |
| --- | --- | --- |
| Shipping | −0.95 | Carries the disruption directly |
| Transport & Logistics | −0.45 | Moves the cargo behind it |
| Petrochemicals | −0.35 | Feedstock and product through the strait |
| Wholesale & Retail Trade | −0.30 | Importers, working capital in transit |
| Manufacturing | −0.22 | Inputs delayed |
| Oil & Gas | −0.12 | A producer selling into a tighter freight market is not the operator carrying the cargo |

Eleven sectors are untouched, which is what makes a sector comparison worth
running. The disruption ramps over the final four quarters (15%, 45%, 80%,
100%) so the question "why did this deteriorate?" has a BEFORE to answer from.

Fact and hypothesis stay apart. The scenario says what was done to the book;
it does not say that any particular borrower's arrears were caused by it.
Which observations are facts in the data and which are analytical readings
beside them is recorded per event in `scripts/domains_external.py`
(`FACT_IN_CREDITPROBE_DATA` / `ANALYTICAL_HYPOTHESIS`), never inferred.

## Four calibration defects, and what was actually wrong

### One third of the book in covenant breach

Covenant thresholds were anchored to each borrower's **earliest** spread
statement and never reset. Sixteen quarters of ordinary drift accumulated
against a 2022 threshold that nobody revisited, and 33.8% of borrowers ended up
in breach of something — not a bank with a covenant problem, a bank with a
covenant policy that does not work.

Fixed by re-anchoring at the **annual review** (`COVENANT_RESET_QUARTERS = 4`):
the threshold is set against the level the covenant was last renegotiated at,
so headroom measures recent deterioration, which is the question a credit
officer is actually asking. The cushion was also widened, and minimum
covenants — interest cover, debt service cover — are set further from the
borrower's level than maximum ones, because a ratio with earnings on top swings
further in a year than leverage does.

Borrower-level breach rate: **33.8% → 12.8%**.

### Arrears piling up on 450 days

The core book aged a delinquent facility by **thirty days per quarter** and
clipped the result. Over fifteen quarters that produced a ladder whose top rung
was 450, and forty-eight facilities sat on it — more than held any other value
above ninety. A fact about the loop, not about a borrower.

Two things were wrong. A quarter is about ninety days, not thirty; and a book
resolves its deep arrears — by write-off, restructure or recovery — rather than
carrying the same facility at the same number for four years. Both are fixed in
`age_delinquency`, which is now a named function with its own tests rather than
an inline expression nobody could reach.

### Eighty-eight borrowers on exactly 91 days

The corporate book floored every defaulted borrower at exactly 91 days. The
floor is drawn now, from the day default is recognised outwards.

### Stage 2 inverted across sectors

The core book's three-notch SICR trigger had no grade floor, so it fired
hardest on the **strongest** sectors: a grade-1 borrower drifting to grade 4
tripped it, while a grade-8 one could not fall three notches at all because the
scale stops at ten. Education and Healthcare came out of the generator with
more Stage 2 than Contracting, which is backwards, and a sector answer built on
it would have sent an officer to the wrong names.

A three-notch downgrade now has to LAND somewhere weak
(`SICR_NOTCH_FLOOR_GRADE = 6`) to count.

The corporate book had a different Stage 2 problem: the relative PD test cleared
an absolute floor of only 75 basis points, and since origination PD is anchored
to through-the-cycle quality, a doubling by the trough is the normal experience
of the book rather than a signal about one name. A quarter of the book was in
Stage 2 — a population too large to review, and therefore not a watchlist at
all. The floor is 200 basis points now.

## What holds it there

`tests/corporate/test_portfolio_plausibility.py` — 22 tests, every one a band
asserted from **both** ends. A generator asserted to two decimal places is a
generator nobody can tune again; one asserted only from below passes by making
everything healthy, which the brief explicitly ruled out.

`tests/scripts/test_delinquency_ageing.py` — 9 tests on the arrears
roll-forward in isolation, including the shape of the tail, because "no single
arrears value dominates" is the artefact stated as a property rather than as an
assertion about one built lake.

Where the book landed, at Q2 2026:

| | Core book | Corporate book |
| --- | --- | --- |
| Stage 1 / 2 / 3 | 79.0% / 14.4% / 6.5% | 77.9% / 17.5% / 4.6% |
| Borrowers in covenant breach | — | 12.8% |
| Largest sector | Contracting, 11.2% | Contracting, ~11% |
| Financial Services | 7.6% | ~7% |
| Worst sector by Stage 2 | Transport & Logistics 31.0%, Shipping 30.0% | Shipping |

Shipping also carries 19.9% Stage 3 in the core book — the scenario's most
distressed names have already migrated past Stage 2, which is why the sector
answer needs both numbers and not just the Stage 2 rate.

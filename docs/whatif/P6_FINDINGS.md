# P6 — ratings, scores, sectors and stages

Section 8 of `CreditProbe_Advanced_Cockpit_WhatIf_Master_Prompt_v1`. Four
families of change that look like arithmetic and are not, implemented in
`backend/cockpit_v4/scenario/mappings/`.

> Everything measured here is measured on **generated books**. The scales,
> scorecards and sector dictionaries are published by the labelled synthetic
> candidate releases and are not a bank's.

---

## The three ways a notch move goes wrong, measured

All three produce a plausible answer, which is why each has its own test
rather than a shared one.

**Incrementing the grade string.** `AA` plus one notch is `A`. It is not
`AB`, and `AB` is not on any scale, so a book carrying one would have a grade
nothing maps to.

**Sorting the scale lexically.** Sorted as text, this release's Corporate
scale reads

```
A  AA  B  B+  BB  BB+  BB-  BBB  BBB+  BBB-  CCC  D
```

Two things are wrong with it and both are silent. `AA` steps to `B`, eight
grades past where it belongs. And `BBB` sorts ahead of `BBB+` although it is
the weaker of the two, so a one-notch downgrade from `BBB+` lands on an
*upgrade*. The published `grade_rank` is the order and the only order;
`test_s12_a_notch_is_never_a_lexical_sort` asserts both inversions.

**Turning a notch into a PD multiplier.** The step between grades is not a
constant factor. On the published scale `AA` to `A` is 2.00× and `B` to `CCC`
is 2.46×, so any single multiplier is wrong at one end or the other. One
notch is one row of the map and its PD is the PD that row publishes.

### The three boundary cases, answered rather than clamped

| Case | What happens |
|---|---|
| Past the top or bottom | Applied as far as the scale goes, and the result carries `requested_notches`, `applied_notches` and a sentence. Three asked for and one applied is not three. |
| A grade the scale does not carry | Refused, with the scale listed. An unrated obligor has no position to step from, and putting one at the middle of the scale would be inventing a rating. |
| The default grade | Refused in both directions. A defaulted obligor carries PD 1.0 because it defaulted, not because of where it sits, so curing it is a stage decision. |

A fractional notch is refused twice over: `units.Amount` rejects it before it
reaches the scale, and `Scale.notch` rejects it again.

---

## The two Retail scorecards

They are not interchangeable and the release publishes them as two things:

| | Behavioural | Application |
|---|---|---|
| Relation | `retail_account_month.behaviour_score` | `whatif_retail_profile.application_score` |
| Range | 300–900 | 200–800 |
| Refreshed | every month | once, at origination |
| Scorecard | per product | one card for the whole book |
| Population | accounts on book | applicants |

A score of 650 is a different risk on each. `Library.card()` therefore
requires the score type and **never substitutes**: a request for a card the
release does not publish is refused with a sentence saying the other card is
not a substitute, rather than being answered from it.

**A cross-product card is used, not substituted.** This release publishes one
application card for the whole book and behavioural cards per product, which
is the usual shape — an application score is built on applicants before a
product is chosen. `card()` falls back to the `ALL` card, and the card it
returns still reads `product = "ALL"`, so an answer reports what it actually
priced through.

**Points are points.** "Reduce the score by 50 points" is `units.POINTS`: 650
becomes 600 and stays in the same band. Read as a relative move it is 325,
two bands down and a different PD. `behaviour_score` is `INDEX` storage,
which admits `points` and refuses `basis_points`.

**Outside the card's range is a refusal.** A 950 on a 300–900 card is not the
top band. The card says nothing about it, and a gap inside the table is a gap
rather than an invitation to use the neighbouring band's PD.

---

## Sectors, and the category nobody wants

`Unknown` is a category. Dropping it makes every total smaller than the book
and every share larger than it should be, and **the error is invisible
because the remaining numbers still add up to the remaining total**. That is
the whole reason `Dictionary.reconciles()` compares with the book's own count
and ECL rather than with itself, and a test builds a dictionary with the
residual removed and shows it still balances internally while failing that
comparison.

Residual categories sort last however large they are, so a reader scanning
the list does not read `Unknown` as a sector. An "Other" bucket for a chart
is a real row with a real total, residuals inside it, so the chart still sums
to the book.

**Synonyms resolve; near misses do not.** Case, spacing and a short synonym
list are forgiven. `Aviation` against a book with no aviation comes back as a
refusal listing the real categories, because a confident number reported
against a sector the reader did not ask for is worse than a question.

**A Retail product is not an employer sector.** They are different columns
with different values and different cardinalities — ten employer sectors
against five products on this release, and
`test_the_retail_book_keeps_product_and_employer_sector_apart` asserts the
two value sets do not even intersect. `require_dimension("retail", "sector")`
refuses with both named.

---

## Stages

Frozen by default, and the default is enforced rather than documented: a move
under `stage_policy=frozen` is refused, with the reason and with the policy
that would allow it.

An explicit move needs the **declared horizon contract** — a published
lifetime ECL, a declared lifetime horizon in months, and a remaining maturity.
Without all three the move reports `UNSUPPORTED` and carries the baseline
forward. It is not a change of zero: an unsupported row is a row the scenario
could not answer for, and `summarise()` counts `moved`, `unchanged` and
`unsupported` separately so those two facts never merge.

**`lifetime = 12m × years` is banned by name.** `stages.never_multiply` exists
only to raise, so the ban has a function a test can call and a future caller
reaching for the shortcut finds it instead of writing it. The product is
wrong in three separate ways at once: it ignores survival, so a default in
year one is counted again in year two; it ignores discounting, which pulls
later losses down; and it assumes a flat PD term structure, which no book
has.

Measured on the published Corporate candidate at its latest quarter, over
all 2,996 facilities with a remaining maturity of a year or more:

| | |
|---|---|
| Published lifetime ECL | 6,356.5 SAR mn |
| `12m × remaining years` | 11,111.1 SAR mn |
| The shortcut overstates the book by | **74.8%** |
| Per-facility ratio, published ÷ shortcut | 0.324 to 0.917 |

Not a rounding difference and not a constant one, so it cannot be corrected
with a factor either. `whatif_*_term_structure` is where the real figure
comes from, bucket by bucket.

---

## The field dictionary now follows the release

`fields.py` was written in P2 against the accepted books and is right about
them. The candidate publishes columns they do not have, and a reader working
against the candidate who was told `application_score` "does not exist" about
a column sitting in front of them would be told something false.

So `fields_for(domain_id)` is the one place the dictionary is read from, and
it returns the candidate's inventory only when `candidate_in_use()` — the
flag is on **and** the release actually open is the candidate. Flag on with
nothing published still reads the accepted book and still reports the
accepted inventory, which a test asserts by pointing `RELEASES` at a release
that does not exist.

What the candidate adds:

| Book | Field | Why it is not in the accepted dictionary |
|---|---|---|
| Corporate | `ccf_pit` | Published directly rather than recovered from `ead`; the accepted `ccf` stays DERIVED with its own derivation |
| Both | `ecl_modelled_sar_mn` | The accepted books have no modelled/overlay split at all |
| Both | `ecl_overlay_sar_mn` | Immutable under §9.1's fixed-overlay policy, and its zero is an observed zero |
| Retail | `application_score` | PUBLISHED and still **not mutable**: a scenario that rewrote an origination score would be changing the past |
| Retail | `employer_sector` | PUBLISHED and immutable; used to select a cohort, never to relabel a product |

`sector` stays ABSENT for Retail on both releases, pointing at
`employer_sector`. Publishing a sector dimension did not make `product` one.

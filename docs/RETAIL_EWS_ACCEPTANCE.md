# Early Warning — acceptance pass

*Synthetic Saudi retail demonstration data. Nothing below is ANB customer
data, an ANB model, an ANB policy, or a SAMA requirement, and no figure here
has been independently validated.*

---

## 1. What was on the screen, item by item

The screen at `e200a597`, opened in a browser and read against the brief
rather than against the code. Four verdicts: **visible** (on screen and
working), **backend only** (computed, nothing renders it), **missing**
(neither), **not connected** (rendered but inert or wrong).

| # | What the brief asks for | Verdict, before |
|---|---|---|
| 2 | Portfolio → product → subsegment → customer → signal hierarchy | **missing** — one flat alert list, no levels |
| 3 | Month and product selectors on a landing page | **missing** — month only, on the signals list |
| 3 | Headline counts: customers, warned, severity, current bad, forward risk, exposure | **missing** — four figures, one of them wrong (below) |
| 4 | Per-product EWS score, severity, 25-month trend, six layer trends, counts, exposure, MoM | **missing** |
| 4 | Generated management commentary | **missing** |
| 5 | Subsegment level, product-specific dimensions | **missing** |
| 6 | Customer list with exposure shares, DPD, stage, current bad, forward risk, EWS score, severity, behavioural score, movement, application score, top 3 reason codes, primary layer | **missing** |
| 7 | Current bad vs forward risk as filters and cards | **missing** — neither concept existed on screen |
| 8 | Customer detail, 25-month trend per layer, reason-code timeline | **missing** |
| 9 | Methodology / model page | **missing** — `/early-warning/methodology` was a 404; Model Lab offered to *fit* a model |
| 10 | What T, A and C mean | **missing** — no statement either way |
| 11 | Internal / External / Derived classification | **backend only** — `SOURCE_CLASS` existed in `ews_portfolio.py`, nothing rendered it |
| 12 | Product-specific EWS | **backend only** — every rule declares its products; the screen never said so |
| 13 | Rule / layer / severity / product chips, clickable | **not connected** — rule chips rendered as `Badge`s and did nothing; there were no layer chips |
| 14 | "Showing 500 of 5,952" | **not connected** — the headline read **ALERTS 500** above chips summing to 5,952 |
| 15 | One description of Early Warning everywhere | **not connected** — the sidebar called it the Forward Risk Signal; the signals entry promised "34 named tests across eight families" (the *corporate* rulebook's shape; this one has 20 rules in 11 families) |
| 16 | Cockpit → EWS deep link with filters applied | **not connected** — one "Open" link to an unfiltered list |
| 17 | Prebuilt Credit Card story | **missing** |
| 18 | Management dashboard in the CreditProbe visual language | **missing** |
| 19 | Browser tests EW-01…EW-22 | **missing** |

The twenty governed rules underneath were **visible and correct** throughout,
and are unchanged by this pass. They are the signal layer; everything added
here reads them.

---

## 2. What was built

### The layer model — `backend/retail/ews_layers.py`

The rulebook's eleven families roll up into the six layers the brief names:

| Layer | Families | Class | Weight |
|---|---|---|---|
| Repayment behaviour | REPAYMENT, COLLECTIONS | Internal | 30% |
| Affordability & income | INCOME, AFFORDABILITY | Internal | 25% |
| Score dynamics | SCORE | Derived | 20% |
| Facility structure | CARD_BEHAVIOUR, PRODUCT_STRUCTURE, COLLATERAL, FORBEARANCE | Internal | 15% |
| Bureau & external signals | BUREAU | External | 10% |
| Cycle sensitivity | *none* | — | 0% |

Cycle sensitivity is **shown rather than omitted**, with the sentence saying
no rule in `retail-ews-rulebook-1.0.0` scores it. DATA_QUALITY is deliberately
not a risk layer: a missing input is a statement about the file, not about the
customer.

The same file carries the **variable dictionary** — all 27 inputs the rules
read, each with the ten facts §9 asks for (business meaning, Internal /
External / Derived, raw input, transformation, direction of risk, refresh
frequency, applicable products, weight carried, reason codes generated, and
the rules that read it). It is built by *walking the rules*, so a rule that
starts reading a new column cannot leave the methodology page behind —
`ews_layers.check()` fails if it tries.

### The panel — `backend/retail/ews_portfolio.py`

Evaluating the rulebook takes about 2.4 seconds a month, which is fine once
and far too slow inside a page load. `build()` scores all 25 months once and
persists **406,894 customer-product rows** as `retail_ews_panel`. It now runs
as a step of `scripts/bootstrap_retail_installation.py`, so a fresh install
does not open on an empty state, and `--check` reports a panel that is missing
or short of months.

### The screens

| Route | What it is |
|---|---|
| `/early-warning` | The portfolio: selectors, twelve headline figures, the 25-month trend, the Credit Card story, a card per product; clicking down through subsegment, customer list and customer detail, with the level in the URL |
| `/early-warning/methodology` | **New.** The running model: identity, scoring, the six layers, every rule, every input with its ten facts, source classes, the bureau statement, what applies to each product, and the glossary |
| `/early-warning/signals` | The rulebook one row per signal, with four decks of clickable chips and an honest "Showing N of M" |
| `/early-warning/lab` | Unchanged except for a card that says the EWS score is **not** fitted here and links to the methodology |

---

## 3. The figures, at 2026-08

Read off the running application, not from a fixture.

| Figure | Value |
|---|---|
| Rulebook | `retail-ews-rulebook-1.0.0` — 20 rules, 11 families |
| Months in the panel | 25 (2024-08 … 2026-08) |
| Total customers | 14,251 |
| Customers with an EWS signal | 3,896 |
| Signals raised | 5,952 |
| Critical / High / Medium / Low customers | 2 / 69 / 670 / 3,155 |
| Already bad or delinquent | 391 (+2 on 2026-07) |
| Forward risk, still performing | 28 (+10 on 2026-07) |
| Exposure under warning | SAR 422.9mn |
| Share of retail exposure | 20.3% |
| Portfolio EWS score | 14.0 (+0.4), **MEDIUM** |

### By product

| Product | Score | Severity | Customers | Warned | Bad now | Forward | Alerts | MoM |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| Personal Finance | 18.62 | MEDIUM | 6,781 | 1,100 | 143 | 10 | 1,674 | +1.04 |
| Home Finance | 16.08 | MEDIUM | 2,067 | 342 | 31 | 3 | 476 | +0.17 |
| Credit Card | 11.55 | MEDIUM | 5,853 | 1,691 | 175 | 5 | 2,515 | −0.34 |
| Auto Finance | 8.82 | LOW | 3,117 | 1,400 | 55 | 10 | 1,914 | +0.70 |

The four product alert counts sum to 6,579 against a book total of 5,952.
That is not an error: 1,934 of the month's alerts are raised against the
*customer* rather than one facility — salary interruption, affordability,
bureau — and bear on every product that customer holds. The portfolio counts
each once; a product counts the ones that bear on it.

### The commentary, generated

> Personal Finance rose from 17.6 to 18.6 (Medium), a move of +1.0. Driven by
> repayment behaviour (+3.9) and facility structure (+0.6). Affordability &
> income moved the other way (−1.4). Customers already bad went from 144 to
> 143; customers still performing but at high forward risk went from 6 to 10.

Every clause is computed. No two products say the same thing, and each quotes
its own score — checked by `test_the_commentary_is_generated_from_computed_movements`.

---

## 4. Defects found and fixed

Every one was seen on a screen or in a payload before it was fixed, and each
has a regression test in `tests/retail/test_ret_ews_portfolio.py` or a case in
`scripts/retail_uat/ews_acceptance.py`.

1. **1,934 alerts vanished from the portfolio.** `evaluate_snapshot` returns
   no product code for a CUSTOMER-scope alert. Merged on (customer, product)
   they were dropped — the entire affordability and bureau story disappeared
   from the roll-up while still showing on the alert list. Each is now fanned
   out to every product its customer holds.

2. **The layer score was useless at its first scale.** "Fired points ÷ every
   point the layer could score" put 17,227 of 17,818 customer-products in LOW
   and left exactly one forward-risk customer in the book. It is now the worst
   signal that fired plus ten points per additional signal, capped at 100.

3. **Every product read LOW.** A population mean cannot be banded with the
   customer band table: the four products run 8.8–18.6, so all four sat in the
   bottom band for ever. `POPULATION_BANDS` (30/20/10) was added beside
   `BANDS` (60/40/20).

4. **Alerts double-counted, 6,579 against 5,952.** The fan-out in (1) makes
   per-row sums wrong. Patched with the month's total, which fixed the
   portfolio and made **every product report the whole book's 5,952**. Now
   split at build time into facility-scope and customer-scope counts, so any
   population's count is exact at any level.

5. **The band counts did not add up.** CRITICAL 2 + HIGH 69 + MEDIUM 677 +
   LOW 3,270 = 4,018, under a headline saying 3,896 customers carry a signal.
   A customer HIGH on a card and LOW on a mortgage was counted twice. Each
   customer is now banded once, on their worst product.

6. **Sixteen already-bad customers could not be opened.** The headline counted
   391; the list showed 375, because it filtered to customers with an EWS
   signal first. Being thirty days down is the condition, not a prediction
   that needs a signal to support it. The cohort is now the whole population.

7. **A customer was banded two ways one click apart.** The detail page banded
   a single customer with the *population* table, so a customer at 53 read
   CRITICAL on their own page and HIGH in the list they were opened from.

8. **A clean mortgage hid a bad card.** The detail's score was the
   exposure-weighted mean across a customer's products, so RC-0000134 scored
   52.5 on a card 86 days down and 19.4 on their own page. One customer's
   score is now their worst product.

9. **"Driven by" named layers that pulled the other way.** "Credit Card fell
   … driven by affordability & income (−1.5) and repayment behaviour (+0.2)" —
   repayment rose. Drivers are now only layers that moved with the score, and
   what pulled against it is said as that.

10. **The family filter offered 5 of 11 families.** It was built from the
    alerts in the browser, which only ever holds the capped page. Filtered
    server-side and served.

11. **`<p>` wrapped a `<div>`.** A hydration error on `/early-warning`, and
    what the red "2 Issues" overlay in the corner of the presentation build
    was counting. Two `set-state-in-effect` lint errors on the same screens
    were the other one; the level now derives from `useSearchParams` rather
    than being copied into state by a mount effect.

12. **Product labels read `CREDIT_CARD`.** `zip(PRODUCT_CODES, PRODUCT_LABELS)`
    over a dict that was already a mapping.

13. **The behavioural score was a bare dash on 926 rows.** There is a reason:
    the scorecard needs repayment history and scores from the second month on
    book. The column now says so, and names the application score as what
    stands in its place, rather than inventing a number or showing nothing.

14. **The product selector did not move the headline.** Choosing Credit Card
    left the twelve figures reading 14,251 customers and SAR 422.9mn — the
    whole book — above a Credit Card breakdown, so the two halves of one
    screen answered about two different populations. The headline now follows
    the selector. Exposure share stays over the whole retail book, because
    "% of retail exposure" means of retail, and the sentence under the cards
    says so when a product is selected.

15. **Two of the three "top reason codes" said the same thing.** A customer
    with two cards, both of which worsened a delinquency bucket, fired
    RET-EWS-001 twice — 56 rows at 2026-08 spent two of three slots on one
    rule, and rendered two React children with the same key. The reason codes
    are one entry per rule; the alert count still counts both.

16. **Two navigation entries described the corporate book.** Early Warning was
    described as the Forward Risk Signal, and the signals entry as "34 named
    tests across eight families" — thirty-four across eight is the *corporate*
    rulebook. Both now read `frontend/src/lib/ews.ts`, which is the one place
    the description lives.

---

## 5. EW-01 … EW-22

`scripts/retail_uat/ews_acceptance.py`, run against the same frontend and
backend the launcher serves. No mocks and no test-only route. Where the brief
asks for a number, the case reads it off the screen and checks it against the
API; where it asks for a control, the case uses the control and checks that
what it controls changed.

| Case | What it proves | Result |
|---|---|---|
| EW-01 | Early Warning opens on the portfolio, with month and product selectors, defaulting to the latest month and all products | PASS |
| EW-02 | Twelve headline figures, each matching the API, with customers counted apart from alerts | PASS |
| EW-03 | A 25-month portfolio EWS trend | PASS |
| EW-04 | Every product has a card with score, severity, counts, exposure and a month-on-month movement, and its own alert count | PASS |
| EW-05 | Six layer trends per product, the empty sixth named rather than omitted | PASS |
| EW-06 | Commentary generated from each product's own movements; no two alike | PASS |
| EW-07 | A product opens subsegments cut on dimensions that belong to that product | PASS |
| EW-08 | A subsegment opens the customers inside it | PASS |
| EW-09 | Every required column, with a behavioural score on every row | PASS |
| EW-10 | Already bad and forward risk are filters whose counts agree with the headline | PASS |
| EW-11 | A customer opens with a trend per layer over their months on book | PASS |
| EW-12 | A reason-code timeline that opens the rule behind each code | PASS |
| EW-13 | The methodology page describes a model that is running, and never asks for a fit | PASS |
| EW-14 | Every input documented with all ten facts | PASS |
| EW-15 | Internal / External / Derived distinguished; the bureau proxy not called a live feed | PASS |
| EW-16 | T, A and C stated to have no governed meaning rather than being invented one | PASS |
| EW-17 | The methodology says which rules apply to each product | PASS |
| EW-18 | "Showing N of M alerts", never "ALERTS 500" | PASS |
| EW-19 | Rule, layer, severity and product chips all filter the list and the count | PASS |
| EW-20 | The Cockpit deep-links into Early Warning with the filter applied | PASS |
| EW-21 | The Credit Card story: five already bad, five still performing, each opening their own detail | PASS |
| EW-22 | The Model Lab points at the running methodology instead of asking for a fit | PASS |

**22 of 22.** The JSON record and one screenshot per case are under
`docs/evidence/retail_ews/`.

---

## 6. What T, A and C mean

They were searched for across the rulebook, the taxonomy, the retail schema,
the forward-risk signal and the screens. **They do not exist as governed
abbreviations anywhere in this deployment's early-warning implementation.**
There is therefore no authoritative meaning to show and none has been
invented. The methodology page says exactly that, and every layer, rule,
variable and column label in Early Warning is written out in full. A test
holds the line (`test_no_meaning_is_invented_for_unsourced_shorthand`).

---

## 7. The bureau

The bureau inputs in this deployment are a **synthetic proxy** generated with
the rest of the demonstration book. There is no live bureau connection and no
bureau agreement behind them. This is stated on the methodology page, on the
two bureau variables in the dictionary, and in the source-class table, and
`test_the_bureau_inputs_are_never_called_a_live_feed` fails if a bureau input
is ever documented without saying so.

---

## 8. Known limits

- **Cycle sensitivity carries no rules.** The sixth layer of the methodology
  scores nothing, because no rule in `retail-ews-rulebook-1.0.0` measures
  cycle sensitivity. It is shown with that sentence rather than omitted.
- **Forward risk is thin on Credit Card.** Five customers at 2026-08. That is
  what the book holds; the story uses all five rather than padding it.
- **926 of 17,818 customer-products have no behavioural score**, because the
  facility is in its first or second month. The column says why.
- **The thresholds are synthetic and bank-configurable.** Every rule carries
  that sentence with its threshold.
- **The panel is precomputed.** A regenerated book needs
  `scripts/bootstrap_retail_installation.py` re-run, or Early Warning serves
  the previous book's roll-up. `--check` reports a panel short of months.

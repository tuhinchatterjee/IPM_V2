# The two domains the Early Warning module was missing

CreditProbe now carries **nine** business domains. Two of them are new, and
both exist because a screen was telling a credit officer what it could not do.

## Why

The Early Warning signals screen carried a box headed *"What this deployment
cannot watch for"*. Everything in it was liquidity or external context:

| Family | Could not watch |
|---|---|
| Financial | receivable days, inventory days, free cash flow, capex |
| Leverage | the maturity schedule — refinancing pressure needs dated debt |
| Liquidity | cash and undrawn committed lines as a buffer |
| Behavioural | returned payments and limit excesses |
| Covenant | waivers and resets |
| Collateral | insurance and document expiry |
| Rating | external ratings and outlooks |

A box like that is honest, and it is also the wrong answer. Liquidity is where
a corporate credit actually fails: a borrower does not default because its
leverage ratio drifted, it defaults because a payment fell due and the cash
was not there. So the data was built rather than the box redrawn.

## Domain 8 — Liquidity and Cash Flow

14 datasets, 114 governed fields, 1.4m rows.
`scripts/domains_liquidity.py`.

| Dataset | Grain | Answers |
|---|---|---|
| `borrower_cash_flow` | borrower · quarter | revenue, operating and free cash flow, capex, cash, months of cost covered |
| `working_capital_position` | borrower · quarter | receivables, inventory, payables, the days behind each, the cash conversion cycle |
| `receivables_ageing` | borrower · quarter | current and past-due buckets, summing exactly to the balance |
| `inventory_position` | borrower · quarter | inventory held and the days it represents |
| `payables_position` | borrower · quarter | trade payables and the days behind them |
| `capital_expenditure` | borrower · quarter | capex against revenue and operating cash flow |
| `debt_maturity_schedule` | facility · quarter | 0-3m, 3-6m, 6-12m, 1-2y, beyond |
| `refinancing_profile` | borrower · quarter | what must be refinanced inside a year and cannot be met from cash |
| `committed_facilities` | facility · quarter | the contractually committed limit behind each facility |
| `undrawn_availability` | borrower · quarter | committed and uncommitted headroom, kept apart |
| `liquidity_buffer` | borrower · quarter | cash plus committed headroom against what is due |
| `cash_balance_history` | borrower · quarter | the cash balance quarter by quarter |
| `short_term_debt` | borrower · quarter | short against long, with the near maturity ladder |
| `debt_service_schedule` | facility · quarter | interest and principal falling due |

### One position, fourteen views

The mandate names fourteen datasets and one field list. They are views of one
quarterly treasury position per borrower: `_position()` computes it once and
each dataset is the slice that answers its own question. Computing them
independently would let the receivable days in `receivables_ageing` disagree
with the receivable days in `working_capital_position` — the class of defect
that makes a data platform untrustworthy.

Facility-grain datasets are ALLOCATED from the borrower's position by share of
exposure, so the facility rows sum back to the borrower row. A domain whose
parts do not add up to its own total is worse than no domain.

### Coherent with the facility book

Every figure is derived from a `stress` score read off the book — utilisation,
DSCR, covenant headroom, arrears, stage. A borrower the facility book already
says is struggling comes back here with a thin buffer, stretched receivables,
a front-loaded maturity ladder and a refinancing requirement. The transmission
is deliberate and one-directional:

```
utilisation ↑, DSCR ↓, headroom ↓, DPD ↑, stage ↑
        ↓
receivable days ↑   payable days ↑↑   cash months ↓
capex ↓             committed share ↓  maturity front-load ↑
        ↓
liquidity buffer ↓  refinancing requirement ↑
```

Payables stretch harder than receivables, because a borrower short of cash
pays its suppliers late before it tells its bank. Capex is cut first, which is
what makes a falling capex line a warning rather than a sign of discipline.

## Domain 9 — External Intelligence

10 datasets, 112 governed fields.
`scripts/domains_external.py`.

| Dataset | Grain | Answers |
|---|---|---|
| `external_rating_history` | borrower · cycle | the agency view beside the bank's own — the GAP is what a rating-lag signal reads |
| `external_rating_outlook` | borrower · cycle | outlook and watch status |
| `sector_events` | event | governed events affecting a named sector |
| `macro_events` | event | policy rates, demand, regulated prices |
| `geopolitical_events` | event | route availability and disruption |
| `commodity_events` | event | price and availability |
| `shipping_events` | event | freight rates, insurance cost, transit times |
| `borrower_external_event_link` | event · borrower | which borrowers an event plausibly reaches, and on what basis |
| `sector_sensitivity` | event · sector | how much each event moves each sector, through which channel |
| `borrower_macro_sensitivity` | borrower | macro, rate, currency and commodity betas per borrower |

### FACT and HYPOTHESIS are a column, not a prompt

Every row carries `evidence_type`:

- `FACT_IN_CREDITPROBE_DATA` — the event is recorded here, dated and sourced.
- `ANALYTICAL_HYPOTHESIS` — a link between an event and a borrower is an
  inference. The bank observed that a borrower is in an affected sector and
  that its utilisation rose; it did not observe that one caused the other.

The distinction is a column because a distinction that lives only in a prompt
is a distinction that will be lost. Every row of
`borrower_external_event_link` is a hypothesis, without exception.

### The demonstration scenario

The headline story is a **synthetic demonstration scenario**: a disruption to
shipping through the Strait of Hormuz. Every row carries
`scenario_status = "SYNTHETIC DEMONSTRATION SCENARIO"` and every event
headline is prefixed with it, so no rendering of this data can lose the label.

It is not a claim about the world, and nothing in the product may present it
as one. It exists because a good demonstration needs a story with a causal
spine, and the spine is written down in `sector_sensitivity` so every step can
be inspected rather than asserted:

```
transit restricted  →  freight rates ↑  →  working capital stretches
                       insurance ↑        →  utilisation ↑
                       transit days ↑     →  refinancing tightens
```

The first four links are `FACT_IN_CREDITPROBE_DATA` — the events are recorded.
The last four are `ANALYTICAL_HYPOTHESIS` — they are readings of the portfolio
beside the event.

Unrelated external context is in the book too (a policy rate hold, a
construction slowdown, tourism ahead of plan), so the scenario is not the only
thing the domain can talk about and a correlation with it is arguable rather
than automatic.

## The seven Core Portfolio additions

`scripts/domains_portfolio_extra.py`. Each exists because an Early Warning
signal was written against it and could not be computed.

`returned_payments` · `payment_rejections` · `limit_excesses` ·
`covenant_waivers` · `covenant_resets` · `collateral_insurance` ·
`collateral_document_expiry`

These are the events a credit officer hears about from operations long before
they reach a ratio. Each is derived so it cannot contradict the book: a limit
excess belongs to a facility already drawn past its limit, a waiver attaches
to a covenant that was already breached.

## Rebuilding

```
.venv/bin/python -m scripts.generate_saudi_universe     # overwrites the catalogue
.venv/bin/python -m scripts.build_corporate_universe    # merges into it
.venv/bin/python -m scripts.build_retail_scorecards     # merges into it
.venv/bin/python -m scripts.bootstrap_demo --force
```

The order matters: `generate_saudi_universe` **overwrites**
`metadata/catalog.json` while the other two **merge into** it. Reversing it
silently loses two books.

## What is still not watched for

Nothing in the liquidity or external families. `taxonomy.UNAVAILABLE` remains
as a mechanism — a deployment that does not install these domains will show
the box again — and the per-question disclosure path is unchanged: an answer
says what it could not see when that bears on the question, rather than a
screen listing gaps nobody asked about.

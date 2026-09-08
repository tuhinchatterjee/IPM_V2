# Cockpit Intelligence V2 — data contract

Brief §3. What the quarterly demo datasets are, what one row means, and the
rules that decide when a figure is valid.

Machine-readable companions:

* `docs/cockpit_v2/data_dictionary.json` — every measure and dimension with its
  grain, unit, currency, aggregation rule, approved denominator and weight,
  interpretation direction, formula, aliases and null semantics.
* `docs/cockpit_v2/policy_manifest.json` — the rating scale and model, SICR
  rules, recovery and collateral policy, scenarios, macro sensitivities, CCFs,
  covenant definitions and overlays, with versions.
* `<runtime>/metadata/cockpit_v2_manifest.json` — the source manifest of the
  build actually published: seed, versions, per-dataset checksums, per-quarter
  checksums, row counts and coverage.

Everything here is **synthetic**. It describes no real borrower, no real
facility and no real bank's book, and no parameter in it is calibrated,
validated or approved for any regulatory purpose.

## 1. What is published

A new Data Builder domain, **Cockpit Demo**, holding:

| Dataset | Business name | Grain |
|---|---|---|
| `cockpit_2024_q3` … `cockpit_2026_q2` | `Cockpit_2024_Q3` … `Cockpit_2026_Q2` | one facility × reporting date |
| `cockpit_credit_history` | Cockpit credit history | one facility × reporting date, across every published quarter |
| `cockpit_borrower_financials` | | one borrower × statement, at each reporting date it was the latest available |
| `cockpit_collateral_assets` | | one asset × valuation version × reporting date |
| `cockpit_collateral_allocation` | | one asset × facility × reporting date |
| `cockpit_covenant_tests` | | one obligation × test date |
| `cockpit_scenario_parameters` | | one facility × scenario × reporting date |
| `cockpit_risk_curves` | | one facility × scenario × future period |
| `cockpit_macro_paths` | | geography × predictor × forecast vintage × scenario × forecast period |
| `cockpit_movements` | | one facility × reporting date, against its matched prior |

Eight completed calendar quarters, **2024 Q3 through 2026 Q2**. `2026Q2` means
the three months ending 30 June 2026 and the snapshot is as at that date. No
partial quarter is published as an actual.

Registration **preserved all 73 pre-existing datasets** and declared 64
relationships. Nothing was deleted, renamed or overwritten.

### Size actually built

500 fictional borrowers; 807 distinct facilities; 806 facility rows per quarter
(805 at 2026 Q2, after one repayment); 6,447 history rows; 3,000 statement
rows; 6,192 collateral valuations; 6,198 allocations; 12,016 covenant tests;
19,341 scenario parameter rows; 233,454 risk-curve rows; 17,720 macro rows.

Measured: generation 29.7 s, 151 integrity gates 29.1 s, write 15.4 s.

### The quarterly package is one thing

Brief §3.1 asks that a quarter be one selectable package the user does not have
to join together. The quarterly dataset therefore carries the facility snapshot
with the one-to-many details **already pre-aggregated to facility grain**:
collateral coverage and its valuation age, covenant counts and worst headroom,
the borrower's latest available statement and its ratios, and the per-scenario
ECLs.

That is what makes *"break the current ECL down by stage and sector"* work with
no join at all. On the base build the same question returned:

> CreditProbe cannot join `ifrs9_staging` to `portfolio_facility`: no active
> relationship connects them.

The real detail rows are not discarded. They live in the detail datasets, are
declared as `ONE_TO_MANY` relationships from every quarterly head and from the
history interface, and are what drill-down reads. A facility with three
collateral assets and four covenants is **one** row in the snapshot and seven
rows across the details.

## 2. Grain and keys

Main table grain: **one facility × reporting date**.

* Unique key: `(dataset_version, facility_id, reporting_date)` — enforced by the
  `key_unique` gate.
* Stable linkage keys: `borrower_id`, `group_id`.
* Referential integrity from every detail dataset back to a real facility row is
  enforced by the `referential` gate, with exited facilities in
  `cockpit_movements` correctly exempt.

Borrower financials are canonical at **borrower × statement period × scope**,
with a separate availability date. They repeat across a borrower's facility
rows for display, and the semantic rules forbid summing them at facility grain.
The `dedup` gate reports what the naive sum would be against the correct one.

## 3. Business date versus knowledge date

Every fact carries both when they differ:

* a statement has `statement_start`, `statement_end` and `availability_date`;
* a macro path has `forecast_period` and `forecast_issue_date` alongside its
  `forecast_vintage`;
* a collateral valuation has `valuation_date` and `valuation_age_days`.

A snapshot reads only what was knowable at its own reporting date. Because a
forecast is issued 25 days after the quarter it closes, the vintage a snapshot
actually reads is the **previous** one. The `no_leak` gate asserts it.

There is a warm-up of four vintages before the first published quarter. Without
it the earliest quarter had no usable vintage and every scenario PD silently
collapsed back to the rating-linked base — which is what the first pilot build
did.

## 4. Field coverage

The dictionary is the authority; this is the map.

**Identity and facility** — borrower, facility and group ids and fictional
names; segment, borrower type, sector, subsector, geography, product, business
unit, relationship manager; origination and maturity dates; repayment type;
reporting and original currency with FX rate and date; limit, drawn amount,
undrawn commitment, gross carrying amount, exposure, EAD, CCF, utilisation,
contractual and effective rate; new / closed / written-off flags.

**Exposure and EAD are distinct fields and distinct numbers.** Exposure is
drawn plus the whole undrawn commitment; EAD is drawn plus the CCF applied to
the undrawn part. The `ead_rule` gate asserts both the identity and that they
genuinely differ where an undrawn commitment exists.

**Scenarios** — base, upturn and downturn with probability weights, forecast
vintage and model version; per scenario the 12-month PD, cumulative lifetime
PD, the conditional hazard / survival / marginal curve, secured, unsecured and
effective LGD, CCF, EAD and the scenario ECL; then scenario-weighted parameter
summaries, weighted model ECL, the separately identified overlay and the
reported ECL. `pd` and `ecl` are never overloaded: each carries its scenario
and its horizon in the field name.

**Staging and default** — current, prior and origination rating; current and
prior stage; the SICR trigger and the reason in words; policy id and version;
days past due; the default definition; NPL status with the policy note that
says NPL and Stage 3 coincide **as a stated demo policy**; manual override flag.

**Ratings** — model grade, approved grade, numeric rank, origination grade and
rank, notches since origination, override flag and reason, rating date, scale
id, model version, stale-rating flag, and the rating-linked 12-month PD.

**Income statement** — revenue, cost of sales, gross profit, operating
expenses, EBITDA, depreciation and amortisation, EBIT, interest expense, tax,
net profit.

**Balance sheet** — cash, receivables, inventory, other current assets, total
current assets, fixed assets, other non-current assets, total assets, payables,
current liabilities, short-term debt, long-term debt, other liabilities, total
liabilities, total equity, total debt. Equity is the residual, which is what
makes the sheet balance; the `balance_sheet` gate asserts it to 1e-6.

**Cash flow and debt service** — operating cash flow, capital expenditure, cash
available for debt service, scheduled principal, cash interest, free cash flow,
working capital change. DSCR is defined as cash available for debt service over
scheduled principal plus cash interest.

**Ratios** — DSCR, interest coverage, current and quick ratios, gross and net
debt to EBITDA, debt to equity, gross / EBITDA / net margins, return on equity,
receivable / inventory / payable days. Derived from published components, not
drawn independently; the `ratio_formula` gate recomputes one and checks it.
Debt is distinct from total liabilities throughout. Flows are annualised from
the statement's month count, and the basis is recorded.

**Zero and negative denominators return null**, never zero and never infinity.
A borrower with negative EBITDA has no leverage multiple and the row says so;
the `null_not_zero` gate asserts no infinity ever reaches a published column.

**Financial provenance** — statement start and end, availability date, audited
or management status, consolidated scope, currency, units, source system,
version, and age in days with a staleness flag.

**Covenants** — obligation id, scope, metric, contractual formula, threshold,
operator, tolerance, observed value, test date, frequency, next due date,
headroom in the metric's own units, breach and near-breach flags, materiality,
waiver status and validity date, cure period, outstanding action, responsible
role. A waived breach stays a breach in the history.

**Collateral** — asset type, market value, valuation date, version and age,
staleness flag, eligibility, haircut, recognised value, lien rank, legal
status, how many facilities share the asset, allocated recognised amount,
expected realisation cost and recovery lag; and on the facility, the coverage
ratio with secured and unsecured amounts. Legal status is recorded as a status,
never as a guarantee.

**Macro** — the ten-predictor candidate set with geography, unit, observation
or forecast period, issue date, actual/forecast flag, scenario and path, plus
the model dependency metadata: applicable sector, target (PD or LGD),
coefficient on the standardised predictor, lag in quarters, transform and model
version. This is a **proposed demonstration set, not a statistically validated
"top ten"**, and not every predictor enters every model — Construction's PD
model uses four of the ten, Healthcare's uses two.

**Derived movements** — matched prior values, ECL and exposure changes, PD and
LGD changes in **percentage points and basis points** (never applied to a
currency amount), rating notch change, stage transition, utilisation, coverage
and covenant changes. A versioned cached derivative carrying the data version
it was computed from; new and exited facilities carry a **null** comparator, not
a manufactured zero.

## 5. Semantic rules

Recorded per measure in the dictionary: definition, entity grain, unit,
currency, valid range, null semantics, period basis, aggregation rule, approved
denominator and weight, aliases, interpretation direction, formula and lineage.

Five rules are enforced rather than documented:

| Rule | What it stops |
|---|---|
| `no_sum_of_ratios` | A measure declared `not_additive` cannot be summed; the tool refuses and names the approved weighted form. |
| `no_average_of_grades` | A rating grade is a label. Arithmetic uses `rating_rank` and reports notches. |
| `no_pd_without_horizon` | A PD carries its horizon in the field name and in the measure definition. |
| `no_financial_sum_across_facilities` | Borrower financials repeat across facility rows and must be deduplicated first. |
| `no_weighted_parameter_product` | Weighted PD × weighted LGD × weighted EAD is not the weighted ECL and is never presented as a route to it. |
| `no_basis_points_on_currency` | A currency movement has no basis-point form. |

Portfolio summaries name their horizon and weighting basis explicitly. The
dictionary carries both `portfolio_dscr_components` (a ratio of summed
components) and `portfolio_dscr_weighted` (an exposure-weighted average of
borrower ratios), because they are different numbers and the Cockpit says which
it is reporting. Concentration denominators are named and shown in the Trace.

## 6. Access

`backend/cockpit_v2/scope.py` is the single choke point. The effective scope is
the **intersection** of the Cockpit capability scope and the principal's own
dataset permissions. A `feature=cockpit` flag in a request grants nothing.
Metadata is filtered before it is described, so a refusal cannot leak the names
or the count of datasets the caller may not see. Every read — tool, reader,
dataset-id parameter — passes through `permit`.

Dataset text is data. A field that reads "ignore your instructions" is a string
in a demo database, and `tests/cockpit_v2/test_scope.py` holds that shut.

## 7. Seeding

```sh
.venv/bin/python scripts/build_cockpit_v2_demo.py            # eight quarters
.venv/bin/python scripts/build_cockpit_v2_demo.py --pilot    # two-quarter pilot
```

Idempotent and deterministic: the same seed produces byte-identical Parquet,
and re-running replaces only the directories this package owns. The destination
guard runs **before anything is generated** and refuses unless the analytics
directory, the metadata directory and the database name all carry the
`cockpit_v2` namespace and the feature switch is on. It refused the first real
run, and the database was renamed rather than the guard relaxed.

The 151 integrity gates run before the write. **A failing gate blocks
publication**, and the first eight-quarter build was blocked by one.

# Retail investigation blueprints

What a Cockpit question resolves to, what it needs, what it computes, and what
it will not claim. Every blueprint here has an executable calculation path; none
is a registered name with nothing behind it.

> **Synthetic Saudi retail demonstration data — not ANB customer data or
> approved models.**

All blueprints read the one domain, `retail_cockpit` ("Cockpit Data"), dataset
`retail_facility_month`, at the requested month or range.

---

| Blueprint | Intents recognised | Required fields | Date / cohort rule | Computation | Chart | Limitation it must state |
|---|---|---|---|---|---|---|
| **Portfolio overview and concentration** | exposure, book size, by product, by region, by employer sector, concentration | `gross_carrying_amount_sar`, `customer_id`, `facility_id`, `product_code`, segment columns | One snapshot | Distinct customers, distinct facilities, summed exposure, summed allowance, coverage recomputed from the sums | Bar or table | Exposure is a month-end stock; it is not summed across months |
| **Retail IFRS 9 snapshot and scenario comparison** | ECL, allowance, coverage, base/upturn/downturn, prove the weighting | `ecl_*_sar`, `scenario_weight_*`, `ifrs9_stage` | One snapshot | The weighted identity, shown term by term | Table with the identity written out | The BASELINE is the weighted final ECL, not the base scenario |
| **ECL movement / decomposition** | why did ECL change, bridge, waterfall, attribution | two snapshots, all ECL inputs | Two named month-ends | Sequential replacement over matched facilities; entrants and exits separate | Waterfall | Attribution is order-dependent; the order is published |
| **Stage migration and roll rates** | stage 1 to 2, migration, roll rate | `ifrs9_stage`, `previous_month_stage`, `facility_id` | Facilities matched across two dates | Migration matrix on matched facilities only | Matrix | New facilities and exits are separate categories, not migrations |
| **Vintage and early delinquency** | vintage, cohort, first-year performance | `origination_vintage`, `months_on_book`, `dpd` | Vintages with the full observation window | Delinquency by months on book, per vintage | Vintage curves | Immature vintages are excluded and named |
| **Delinquency trend** | 30+, 90+, DPD trend, arrears | `dpd`, `gross_carrying_amount_sar` | Any range up to all 25 months | Rate with the denominator stated on screen | Line | Denominator is stated; a rate without one is not shown |
| **Score distribution and population drift** | has the score shifted, PSI, population change | score and bin columns | Declared reference cohort vs current | PSI over frozen bins, MISSING as its own category | Distribution | A PSI boundary is a configured threshold, not a regulatory pass mark |
| **Application discrimination and calibration** | AUC, Gini, KS, discrimination, calibration | `application_score_at_origination`, `application_predicted_pd_12m`, outcome labels | Origination cohorts with a complete 12-month window | Each application once; AUC oriented by declared direction | ROC or band table | Insufficient evidence returns counts, not a metric |
| **Behavioural discrimination and calibration** | behavioural scorecard performance | `behavioural_score`, `behavioural_predicted_pd_12m`, outcome labels | Monthly landmark cohorts | Customer-clustered uncertainty | ROC or band table | Repeated customers and overlapping windows are handled, not ignored |
| **Score reconstruction** | show the raw input, the transformation and the points | every `app_*`/`beh_*` column | One facility, one date | base_points + Σ points, reconciled to the stored score | None — a table | The scale is a demonstration scale |
| **Affordability and salary stress** | affordability, DBR, disposable income, salary | affordability and salary columns | One snapshot or a trend | Customer-level values de-duplicated before summing | Distribution | Income is a customer property; it is not multiplied by facility count |
| **EWS customer and segment investigation** | who is at risk, warnings, alerts, this customer | rule inputs | One snapshot, with lookback windows | The rulebook, with evidence and thresholds | List or detail | Recommended actions are reviews, not executed decisions |
| **Retail What-If sensitivity** | what if, shock, sensitivity | the ECL inputs plus the hazard anchor | The selected snapshot | Full recomputation through the same engine | Comparison table | Relative and percentage-point shocks are different operations |
| **Retrospective cutoff analysis** | raise the cutoff, what would we have declined | `application_score_at_origination`, outcome labels | Booked originations | Which booked accounts fall below, and what they did | Table | Says nothing about declined applicants; a lower cutoff cannot be evaluated |
| **Evidence-backed auditor response** | draft a response to the auditor | monitoring result objects | Stated cohorts | Assembles the evidence envelope | None | Distinguishes a computed fact from an interpretation, and discloses that no documentary evidence was supplied |

---

## Answer shape

A chart is not shown for every question. A definition, a yes/no explanation, a
missing-evidence response or a single scalar needs no chart, and one is not
produced to fill the space. Where a chart IS shown, the table beside it carries
the same numbers from the same result object — there is no second calculation
for the picture.

## Follow-ups

The Cockpit keeps the prior intent and month across a follow-up: "now only
salary-transfer customers", "compare with the same month last year", "why did
that rise?", "show the evidence".

## Language the resolver understands

Product names resolve through a synonym table rather than exact column matching:
cards, credit card, revolving; personal loan, personal finance, consumer finance;
auto loan, auto finance, auto lease, car loan; home loan, home finance, mortgage,
real estate finance. Spelling variants of the module names and of "behavioural"
resolve the same way.

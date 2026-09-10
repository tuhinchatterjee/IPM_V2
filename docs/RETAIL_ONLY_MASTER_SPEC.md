# CreditProbe: Saudi Retail-Only Conversion
## Claude Code implementation master prompt

Specification date: 10 September 2026.
Source installation to verify: WHATIF_5318.
Suggested NEW branch name: claude/retail-only-saudi-from-whatif5318.
This name is a proposal, NOT a claim that this branch already exists.

---

## 0. Your assignment and the user's non-negotiable requirements

You are Claude Code working on the actual CreditProbe/IPM_V2 repository. IMPLEMENT this conversion, run it, test it, and provide an evidence-backed handover. Do not return only a plan, schema proposal, mock-up, or a collection of unconnected CSV files.

The user is preparing a presentation to the head of retail risk at ANB in Saudi Arabia. The product must help with retail portfolio monitoring, retail IFRS 9 ECL, early warning, What-If analysis, and questions about application/behavioural scorecard performance. No actual ANB data, models, internal thresholds, audit findings, or underwriting rules have been supplied. All generated demonstration data and model parameters must be clearly synthetic.

The source is the user's known WHATIF_5318 installation. FIRST establish its actual repository, Git state, commit and launcher configuration. Do not assume WHATIF_5318 is a Git branch name. Do not infer a branch from a vaguely similar name or from the newest remote branch.

Implement these requirements in a NEW isolated retail branch:

1. Remove all active corporate IFRS 9 datasets, corporate rating datasets and other corporate-related data from this new installation's DataBuilder and runtime data catalog.
2. Cockpit has ONE user-facing analytical data domain, displayed as "Cockpit Data", containing a fully joined, facility-level Saudi retail dataset. It includes retail IFRS 9, customer/facility attributes, both scorecards and every configured scorecard input in raw and transformed form, bureau score at origination, origination dates, delinquency, customer behaviour and Saudi-relevant segments.
3. Publish EXACTLY 25 consecutive month-end datasets/partitions under that ONE logical domain. Each row is one customer-facility-month observation. These are linked snapshots of a continuing portfolio, not 25 unrelated random populations.
4. Early Warning becomes entirely retail. It uses personal repayment, salary/income, affordability, utilisation, bureau and behavioural information. No customer-company balance sheets, income statements, financial ratios or corporate rating requirements.
5. What-If reads exactly the SAME Cockpit canonical data and recomputes retail risk/ECL using retail-compatible logic.
6. Preserve the existing UI design, navigation structure, page layouts, component library, chat interaction, charts, tables and export workflows. This is NOT a UI redesign.
7. Necessary domain names, labels, field options, seeded examples, help text and model/policy options MUST change to retail. "No UI change" does not mean retaining misleading labels. Reuse existing components and positions.
8. There must be no corporate product, corporate sample, corporate rating scale, company-financial-statement requirement or corporate-oriented generated narrative anywhere in the active retail user experience.
9. Preserve the frozen original 5318 and 5308 presentations, including their data, environments, launchers and running processes. The new branch must not overwrite them.
10. Deliver a seeded, demo-ready installation. The user must not have to upload files or manually join data before testing.

Retail IFRS 9 is REQUIRED. Do not interpret removal of corporate IFRS 9 as removal of IFRS 9 itself. Retail credit scores and retail score bands are REQUIRED. Do not interpret removal of corporate ratings as removal of application scores, behavioural scores or their explanatory inputs.

After verifying the NEW isolated retail worktree, keep this entire specification there at `docs/RETAIL_ONLY_MASTER_SPEC.md`. Do not write this specification, progress logs or audit artifacts into either frozen source worktree. Maintain `docs/RETAIL_ONLY_PROGRESS.md` and a requirement-to-code-to-test traceability file. Work through the phases without seeking permission between normal implementation steps. Stop a destructive operation when its target cannot be verified; record the exact blocker rather than guessing.

---

## 1. Phase 0: identify the real WHATIF_5318 source and isolate the new installation

### 1.1 Read-only provenance discovery

Inspect the actual local environment. Establish the relationship among the 5318 launcher, frontend, backend, repository/worktree, data stores and current Git commit.

Useful READ-ONLY commands, adapted to the actual machine, include:

```bash
pwd
git status --short --branch
git rev-parse --show-toplevel
git rev-parse HEAD
git branch --show-current
git worktree list --porcelain
git branch -a -vv
git tag --points-at HEAD
lsof -nP -iTCP:5318 -sTCP:LISTEN
```

For an identified process, inspect its command, parent process and working directory, for example with `ps` and `lsof -a -p <verified-pid> -d cwd -Fn`. Treat the commands as a discovery pattern, not evidence that 5318 must currently be listening. Follow the frontend's actual API configuration to identify its backend; do not assume a particular backend port.

Inspect relevant launchers, freeze manifests, shell scripts and repository-local configuration for WHATIF_5318/5318 references. Search appropriate project/launcher locations, not the user's entire private home directory. Never print API keys, passwords, tokens or complete .env contents.

Record:

- Actual source worktree path and repository identity, with credentials redacted from remote URLs.
- Full source commit SHA; branch name, tag or detached-HEAD state.
- Relevant refs containing the commit, while distinguishing "contains this commit" from "this was the running branch".
- Dirty tracked files and relevant untracked application files.
- Frontend/backend launch commands, ports and how the source connection was established.
- Actual database, file storage, vector index, upload, generated-report and cache locations.
- Any frozen manifest, lockfiles, seed/data versions and their hashes.
- Whether the running application is built from the current working tree or a previously built bundle.

Do not declare a commit the exact running build if an uncommitted change or stale bundle affects that claim. Preserve and document the difference. If the base is genuinely unresolvable without local access, identify the exact missing evidence; do not silently choose another branch.

### 1.2 Create/verify the new worktree

If the user has already created the new branch, verify that it descends from the proven source and use it. Do not reset it or discard the user's work.

Otherwise, create a new branch/worktree from the VERIFIED source commit, for example:

```bash
git worktree add -b claude/retail-only-saudi-from-whatif5318 \
  ../IPM_V2-retail-saudi <VERIFIED_SOURCE_COMMIT_SHA>
```

The placeholder must be replaced with the actual proven SHA before execution. Check for existing paths/branches first; do not use `-B`, `--force`, `reset --hard`, `clean -fd`, or an unrequested stash to overcome conflicts. If relevant source changes are uncommitted, preserve the original, record their hashes, and deliberately reproduce the reviewed changes in the new worktree rather than silently losing them or modifying the frozen source.

Do not merge unrelated branches, fetch-and-reset to the latest remote, or cherry-pick a module rebuild just because it is newer. Work from this baseline.

### 1.3 Isolate mutable state, not only source code

A separate worktree is NOT sufficient isolation by itself. Create separate, branch-local or explicitly namespaced:

- Database/database schema and migration target.
- Seeded files and uploaded files.
- Vector/search indexes, saved chats, datasets, scenarios and generated reports.
- EWS alerts, case/action records and cached query results.
- Runtime logs, process records, build caches where necessary, and temporary export paths.
- Environment configuration, Docker volumes and service names where applicable.

Do not symlink a writable database, data directory or upload directory to 5318/5308. Do not inherit their live database URL. Configure identity guards so seed/reset/migration commands refuse a source-demo or non-retail database target. Backups must be database-consistent; do not casually copy a live SQLite file while ignoring its WAL, or dump secrets into version control.

Use new ports. Suggested defaults are 5328 for the frontend and 8328 for the backend ONLY if free and compatible with the discovered architecture. Check first. Do not kill unrelated processes to claim these ports. Keep frontend API target, CORS, websocket configuration and launcher settings consistent.

Write `docs/RETAIL_SOURCE_PROVENANCE.md` and a machine-readable source manifest before substantial changes. Ensure original application/data files and launcher contents remain unchanged after implementation. Ordinary Git metadata for the new branch/worktree is not an application-data modification.

---

## 2. Baseline audit and implementation boundaries

Before editing, inspect the repository rather than inventing filenames or assuming a framework.

Map the existing:

- DataBuilder definitions, import validation, generators, registry and active-domain selection.
- Frontend-to-backend domain identifiers and dataset IDs.
- Cockpit intent routing, investigation blueprints, SQL/query generation, tool interfaces, answer rendering and charts.
- EWS ingestion, rule definitions, alert models, customer detail screens and actions.
- What-If methodologies, scenario registry, baseline selection, runtime limits, interpretation and exports.
- Playbook/Lenses/Planner or other modules actually present in this source installation.
- Database schema and migration heads, startup/bootstrap code, demo seeds and reset paths.
- Domain-specific examples, prompts, help content, saved sessions and search-index sources.

Capture representative baseline screenshots and run baseline smoke tests for existing workflows against an isolated replica of the proven source. Any original-installation inspection must be read-only; do not run chats, seeds, scenario creation or other stateful tests against a frozen original database. Record existing defects separately from conversion regressions. Preserve working features and contracts; fix defects that prevent the requested retail paths from working, without using this project as permission for an unrelated rewrite.

Create `docs/RETAIL_CONVERSION_INVENTORY.md` with old component, new retail behaviour, data dependency, implementation location and regression test. Inventory each visible What-If methodology. Decide whether it is domain-neutral, needs a real retail replacement, or cannot be supported. No dead visible methodology is acceptable. Do not relabel corporate rating-transition mathematics as a retail score model.

Inspect the migration graph before adding a migration. Use the correct next migration identity for THIS branch; do not assume a number from another development conversation. Test a fresh database and a supported upgrade on an isolated copy.

---

## 3. Retail-only scope and complete removal from the active product

The new installation is retail-only by default. Do not expose a corporate/retail switch. An internal profile mechanism is acceptable if it simplifies implementation, but the shipped active catalog and runtime must resolve exclusively to retail.

Remove or retire from the active retail catalog, startup seeds, imports, examples and retrieval indexes:

- Corporate IFRS 9 facility data and company financial data.
- Internal/external corporate rating grades, agency scales, master-scale mappings and corporate rating migrations.
- Company balance sheets, income statements, cash-flow statements, EBITDA, DSCR, leverage, financial covenants and corporate financial-ratio templates.
- Company-sector portfolio demos, large-borrower company investigations, corporate committee packs and corporate-specific saved prompts.
- Code paths that silently fall back to any of these when the retail dataset is empty or an intent is not recognised.

Do not delete retail income, salary, household expenses, consumer debt obligations, transaction-derived cash inflows, personal loan balances or mortgage/auto collateral. Those are necessary retail information. Employer identifiers and employer-sector concentration may remain as attributes of individual borrowers; employers are not financed company customers in this dataset.

Search ALL active user-facing surfaces: DataBuilder options, navigation captions, landing chips, sample questions, selectors, chart legends, dataset descriptions, error messages, empty states, seeded chats, help content, report templates, exports, Playbook samples, search suggestions and action records.

Use retail labels such as "Score band", "Application score", "Behavioural score", "Retail product", "Employer sector", "Income band", "Delinquency", and "Retail IFRS 9" where semantically appropriate. Do not mechanically rename a rating grade column to a score and retain its old meaning. If an existing navigation item is domain-specific, repurpose it into the corresponding retail function in the same slot; do not leave a misleading or broken page.

Remove old domain IDs from the active resolver and reject stale URLs/requests with a clear retail-only message. Clear only the new installation's inherited caches and demo histories. A missing retail seed must cause an actionable error, not resurrection of the old portfolio.

Developer-only migration history, removal tests, this specification and third-party legal notices may mention the retired domain. They must not be indexed into retail answer retrieval or appear as product content. Do not rewrite Git history or damage the original installation to satisfy a literal repository-wide string count.

---

## 4. Canonical data architecture: one domain, 25 monthly snapshots

### 4.1 Logical model

Use one canonical analytical domain, preferably an internal identifier such as `retail_cockpit` and the display name "Cockpit Data". Adapt the identifier to existing conventions without exposing multiple competing domains.

The canonical analytical table/view is a wide, joined `retail_facility_month` dataset. ALL required scalar fields in this specification, including raw and transformed score variables, must be available in this same dataset. Do not require the user to join five separate uploaded files.

Primary business key:

```text
(snapshot_date, customer_id, facility_id)
```

Within one published dataset version, also enforce uniqueness of `(snapshot_date, facility_id)` and a valid facility-to-customer relationship. Keep historical dataset versions isolated; a query must not union several revisions of the same snapshot and double count.

Each row represents a natural-person retail customer's ONE facility at ONE month-end. A customer may have multiple facilities, including facilities across products. Customer-level values repeated on their facilities must agree at that snapshot where their definition is customer-level.

### 4.2 Exactly 25 monthly datasets

Generate exactly 25 consecutive completed month-end snapshots. For the initial frozen demo dated 10 September 2026, use:

```text
31 August 2024 through 31 August 2026, inclusive: 25 month-ends.
```

Do not include a fabricated September 2026 month-end. Make `demo_as_of_month` configurable for future regeneration, but persist it in the manifest. Ordinary startup must not silently advance the dates or regenerate the data.

Expose the 25 snapshots through the existing DataBuilder and period-selection patterns. One domain with 25 monthly members is required, not 25 separate domain types. Provide one continuous queryable history and a latest-completed-month default.

Internal partitioned Parquet, SQL tables, projections, reference configurations, cached aggregates or calculation-curve stores are acceptable. They are implementation details, NOT extra user-facing analytical domains or required manual uploads. All scalar analytical fields remain queryable in the canonical joined view. Expand any curve/calculation detail on demand with full lineage.

### 4.3 Shared use by modules

- Cockpit reads the canonical domain and requested snapshot/range.
- EWS reads a retail projection plus historical windows from this exact data. If its existing contract needs a separate registry binding, make it a derived view with explicit lineage, not another independent seed.
- What-If reads the exact selected Cockpit dataset version, month and filters. It makes a scenario copy; it never mutates canonical data.
- All modules share customer/facility IDs, snapshot definitions, units, product taxonomy and the same semantic metric definitions.

Every calculation/result records domain ID, dataset version/hash, snapshot dates, filters, calculation version and assumptions. A cross-module reconciliation test must prove identical exposure, stage and ECL totals for the same population.

### 4.4 Date, grain and aggregation semantics

Implement explicit metadata for stock, flow, ratio, customer-level and facility-level fields.

- Outstanding exposure/ECL are month-end stocks: never sum 25 monthly balances and call that current portfolio exposure.
- Disbursements, repayments and write-offs for a period are flows: aggregate their monthly event amounts with the correct period boundaries.
- Customer counts are distinct customer counts; facility counts are distinct facilities.
- Do not multiply customer income or customer total obligations by their number of facilities.
- Default-rate denominators exclude already-defaulted cases when the target is new default among performing accounts.
- PD averages identify their weighting and population. Ratios use explicit numerators/denominators; zero denominators produce a defined unavailable state, not infinity or a misleading zero.
- Month-on-month, year-on-year, completed-quarter and selected-period comparisons name both dates. Distinguish QTD from a completed quarter.
- Stage migration and roll-rate comparisons match facilities across dates; new facilities and exits are separate categories, not accidental migrations.

---

## 5. Saudi retail products and segmentation

Use exactly these primary product families, with stable machine codes and retail display labels:

```text
CREDIT_CARD    -> Credit Card
PERSONAL_LOAN  -> Personal Finance / Personal Loan
AUTO_LOAN      -> Auto Finance / Auto Lease
HOME_LOAN      -> Home Finance / Home Loan
```

These labels are a demo taxonomy, not a statement that every proposed subsegment is an ANB offering. Preserve the user's four product families. Sharia-compliant structure and financing purpose are attributes; do not conflate them with credit risk stage.

Provide useful, plausible Saudi-focused subsegments through independent columns rather than hundreds of opaque concatenated labels:

- Salary-transfer / non-salary-transfer.
- New-to-bank / existing customer at origination.
- Government / private-sector / government-related employer / self-employed / retired, where applicable.
- Verified employment type, employment tenure, payroll status, income band and indebtedness band.
- Region/province, city, branch and origination channel, using a documented Saudi geographic lookup.
- Digital / branch / dealer or partner channels as product-appropriate.
- Citizen / resident categories if retained for descriptive reporting; use clearly synthetic records and do not automatically turn nationality/residency into scoring penalties or policy recommendations.
- Personal finance: new finance, top-up, refinancing/debt buyout where represented; employer and salary-transfer segmentation.
- Credit card: revolver/transactor based on observed payment behaviour, utilisation bands, salary-transfer status and customer tenure. Do not store mutually inconsistent segment labels.
- Auto: new/used vehicle, lease/other supported finance structure, down-payment band, balloon/final-payment band and dealer channel.
- Home: supported/non-supported housing finance as a synthetic programme flag, first-home/refinance where represented, LTV band, property type, profit/rate structure and remaining tenor.

Use SAR for monetary values and Gregorian ISO dates in storage. Store annual rates/ratios as decimals, DPD as integer days, tenors as integer months and money with documented precision. Format in the existing UI without changing its design.

Keep policy caps, eligibility flags, score thresholds, affordability tests, cure periods and programme conditions in versioned configuration. Do not invent an ANB policy or present a chosen demo setting as a SAMA rule. Verify a regulatory claim against current official material before using it. Where no verified bank policy is available, label the rule "synthetic demo policy".

---

## 6. Required canonical data dictionary

Create both a human-readable dictionary and a machine-readable schema. Each field must specify name, business definition, type, unit, grain, source/generation rule, null policy, product applicability, timestamp/as-of meaning, valid range, aggregation rule and lineage. The following is the minimum field-family contract, not permission to omit a configured score input.

Use unambiguous names such as `_sar`, `_date`, `_months`, `_flag`, `_ratio` and `_12m`. Map existing names explicitly where compatibility requires them.

### 6.1 Identity, provenance and lifecycle

Include:

```text
snapshot_date, reporting_month, dataset_version, record_id,
customer_id, facility_id, application_id,
product_code, product_subsegment, portfolio_country, currency,
customer_relationship_start_date, customer_tenure_months,
application_date, approval_date, origination_date, origination_vintage,
contractual_maturity_date, original_tenor_months,
remaining_contractual_tenor_months, months_on_book,
facility_status, closure_date, closure_reason,
refinanced_from_facility_id, restructured_flag, restructure_date,
source_system, source_record_id, source_available_at,
is_synthetic, generator_version, data_quality_status,
customer_scope, score_subject_grain
```

Generate non-real, clearly synthetic IDs. No real national IDs, account numbers, phone numbers, names, addresses or employer allegations.

### 6.2 Customer, employment, affordability and origination policy

Include meaningful applicable fields such as:

```text
region, city, branch_id, origination_channel,
customer_segment, new_to_bank_at_origination_flag,
residency_category, age_band, employment_status,
employer_id, employer_sector, employment_tenure_months,
salary_transfer_flag, salary_verification_status,
verified_monthly_salary_sar, verified_other_monthly_income_sar,
verified_total_monthly_income_sar, household_expenses_sar,
monthly_external_credit_obligations_sar,
monthly_own_bank_credit_obligations_sar,
monthly_total_credit_obligations_sar, obligation_scope_definition,
disposable_income_sar, debt_burden_ratio, affordability_buffer_sar,
income_band, indebtedness_band, dependants_band,
origination_income_sar, origination_debt_burden_ratio,
origination_disposable_income_sar,
policy_version_at_origination, policy_exception_flag,
policy_exception_reason, score_override_flag,
score_override_direction, score_override_reason,
applied_score_cutoff, decision_at_origination
```

Ensure total obligations include each obligation once. A field already including the current facility must not have that facility added again. Consumer salary, total verified income and disposable income must not be conflated.

This is a booked-facility dataset. Decision fields describe the originating application of booked accounts; they do not imply coverage of all rejected applications.

### 6.3 Facility balances, terms and collateral

Include:

```text
original_finance_amount_sar, original_credit_limit_sar,
current_credit_limit_sar, outstanding_principal_sar,
accrued_profit_interest_sar, gross_carrying_amount_sar,
undrawn_commitment_sar, available_limit_sar,
scheduled_monthly_payment_sar, scheduled_payment_due_sar,
actual_payment_received_sar, principal_repayment_sar,
new_drawdown_sar, accrued_charges_sar, capitalised_amount_sar,
writeoff_amount_month_sar, recovery_amount_month_sar,
other_balance_adjustment_sar,
nominal_annual_profit_interest_rate,
effective_annual_interest_rate, rate_type,
contract_structure, secured_flag,
collateral_type, collateral_value_origination_sar,
collateral_value_current_sar, collateral_valuation_date,
ltv_origination_ratio, ltv_current_ratio,
expected_sale_cost_ratio, recovery_delay_months,
vehicle_new_used, vehicle_age_months, dealer_id,
down_payment_sar, balloon_payment_sar, balloon_due_date,
housing_support_flag, housing_support_type, property_type,
behavioural_expected_life_months, ecl_expected_life_months
```

Separate card limits, drawn balances, unused commitments and EAD. Amortising loans must not inherit card-specific utilisation formulas. Product-specific non-applicable fields are null with a reason, not random values or ambiguous zeros.

### 6.4 Delinquency, default, collections and repayment behaviour

Include:

```text
dpd, previous_month_dpd, dpd_bucket,
overdue_amount_sar, oldest_unpaid_due_date,
missed_payment_count_3m, missed_payment_count_6m,
max_dpd_3m, max_dpd_6m, max_dpd_12m,
days_30plus_count_12m, months_30plus_count_12m,
current_default_flag, first_default_date, latest_default_date,
default_reason, default_episode_id,
credit_impaired_flag, unlikeliness_to_pay_flag,
forbearance_flag, forbearance_start_date,
cure_flag, cure_date, cure_probation_months,
writeoff_flag, cumulative_writeoff_sar,
collections_stage, contact_attempts_3m,
promise_to_pay_flag, promise_to_pay_due_date,
broken_promise_count_3m,
payment_to_due_ratio_1m, payment_to_due_ratio_3m,
full_payment_months_6m, minimum_payment_only_months_3m,
utilisation_ratio, utilisation_avg_3m,
utilisation_change_3m_pp, overlimit_days_3m,
cash_advance_amount_3m_sar, cash_advance_share_3m,
returned_payment_count_3m, autopay_failure_count_3m,
behaviour_history_months_available
```

Compute delinquency from a coherent due/payment ledger or equivalent auditable state model. Rolling fields must agree with that history. Distinguish daily-event measures from counts of monthly observations; do not invent daily histories from month-end values.

### 6.5 Salary, personal account and bureau signals for EWS

Include:

```text
salary_credit_last_date, expected_salary_credit_date,
salary_delay_days, salary_missed_cycle_count_3m,
salary_credit_amount_1m_sar, salary_credit_average_3m_sar,
salary_credit_average_6m_sar, salary_change_3m_ratio,
income_volatility_6m, employment_change_flag,
job_loss_reported_flag, job_loss_signal_source,
account_inflows_1m_sar, account_outflows_1m_sar,
account_average_balance_3m_sar, balance_buffer_months,
external_obligations_change_3m_sar,
bureau_score_at_origination, bureau_score_origination_date,
bureau_score_current, bureau_score_current_date,
bureau_score_change_3m, bureau_score_scale_id,
bureau_enquiries_3m, bureau_enquiries_6m,
bureau_active_facilities_count, bureau_total_exposure_sar,
bureau_external_dpd_max, bureau_adverse_flag,
bureau_thin_file_flag, bureau_data_available_flag,
bureau_source_label, bureau_data_freshness_days
```

Synthetic bureau measures may be SIMAH-style in purpose, but do not claim to replicate SIMAH's proprietary score, score range, report layout, data schema or licensed feed. Label the source "Synthetic bureau proxy" and define its scale. Missed salary credits are warning evidence, not proof of job loss. Preserve that distinction in generated explanations.

### 6.6 Scorecard identifiers and output fields

Include:

```text
application_score_at_origination, application_score_date,
application_score_model_id, application_score_model_version,
application_score_band, application_predicted_pd_12m,
application_score_direction, application_score_status,
application_transform_version, application_score_reconciled_flag,
behavioural_score, behavioural_score_date,
behavioural_score_model_id, behavioural_score_model_version,
behavioural_score_band, behavioural_predicted_pd_12m,
behavioural_score_direction, behavioural_score_status,
behavioural_transform_version, behavioural_score_reconciled_flag,
behavioural_score_previous_month, behavioural_score_change_3m,
score_input_missing_count, score_input_stale_count,
score_implementation_check_status, score_evidence_ref
```

Keep application model PD, behavioural model PD and IFRS 9 PIT/TTC PD separate. A score-to-PD mapping has a model, target and horizon; do not equate them just because all are probabilities.

### 6.7 IFRS 9, scenario and calculation fields

Include at least:

```text
ifrs9_stage, previous_month_stage, stage_entry_date,
staging_policy_version, sicr_flag, sicr_reason,
sicr_quantitative_flag, sicr_qualitative_flag,
sicr_dpd_backstop_flag, stage_override_flag,
stage_override_reason, default_definition_id,
credit_risk_model_id, pd_model_version, lgd_model_version,
ead_model_version, ecl_model_version,
pd_ttc_12m, pd_ttc_at_origination_12m,
pd_pit_at_origination_12m,
pd_origination_curve_remaining_life,
sicr_pd_ratio, sicr_pd_absolute_change,
pd_pit_12m_base, pd_pit_12m_upturn, pd_pit_12m_downturn,
pd_pit_lifetime_base, pd_pit_lifetime_upturn,
pd_pit_lifetime_downturn,
lgd_base, lgd_upturn, lgd_downturn,
ead_base_sar, ead_upturn_sar, ead_downturn_sar,
ccf_base, ccf_upturn, ccf_downturn,
scenario_weight_base, scenario_weight_upturn,
scenario_weight_downturn,
ecl_base_sar, ecl_upturn_sar, ecl_downturn_sar,
ecl_weighted_sar, management_overlay_sar, ecl_final_sar,
ecl_coverage_ratio, allowance_scope,
ecl_horizon_type, ecl_horizon_months,
scenario_set_id, scenario_set_version,
pd_curve_id, lgd_curve_id, ead_curve_id,
recovery_cashflow_ref, discount_method,
calculation_run_id, calculation_input_hash,
calculation_available_at, calculation_method_label
```

Scenario PD/LGD/EAD term structures must be reconstructable from stored inputs and versioned curves. Do not pretend scalar lifetime PD alone supplies every assumption needed for a lifetime ECL calculation.

### 6.8 Outcome and monitoring metadata

Provide the fields or derived monitoring-view columns necessary for valid validation:

```text
monitoring_as_of_date, prediction_reference_date,
score_target_definition_id, performance_window_months,
performance_window_start, performance_window_end,
observed_followup_months, outcome_known_at,
performance_window_complete_flag, censoring_reason,
observed_default_within_window, observed_30plus_within_window,
observed_60plus_within_window, monitoring_eligible_flag,
monitoring_exclusion_reason, monitoring_reference_id,
monitoring_reference_type, model_use_population
```

Observe the leakage and outcome rules in Section 9. Future outcomes are evaluation labels, never current customer predictors. Do not backfill an old operational snapshot with knowledge that was unavailable on its date.

---

## 7. All raw and transformed application-score variables

Define transparent, versioned SYNTHETIC scorecards for each product family, or a documented shared model with genuinely product-specific specifications. The registry defines exactly which inputs belong to each model/version. "All variables" means every input actually used by the configured model; no omitted inputs, secret coefficients or unexplained score generation.

At minimum make these available as candidate application inputs, with product-appropriate model selection:

1. Verified monthly income at application.
2. Debt burden ratio at application.
3. Disposable-income/affordability buffer at application.
4. Employment tenure at application.
5. Customer relationship tenure at application.
6. Salary-transfer status at application.
7. Bureau score at origination.
8. Recent bureau enquiry count at application.
9. Bureau external delinquency at application.
10. Bureau active-obligation/facility count at application.
11. Requested finance amount relative to verified income.
12. Proposed repayment/instalment relative to verified income.
13. Requested tenor or revolving-line characteristics.
14. Original LTV/down payment for secured products.
15. Original balloon/final-payment ratio for applicable auto finance.
16. Verified income stability, where sufficient pre-application history exists.

Some candidate fields are correlated; choose a documented sensible model rather than automatically forcing all candidates into every product. Geography and nationality/residency are descriptive fields by default, not automatic risk-score penalties.

For EVERY feature included by a model, expose flattened columns following a clear convention, for example:

```text
app_income_raw
app_income_transformed
app_income_bin
app_income_missing_flag
app_income_points

app_dbr_raw
app_dbr_transformed
app_dbr_bin
app_dbr_missing_flag
app_dbr_points
```

Use the same pattern for ALL model features. Where the transformation is WoE, expose a WoE value explicitly or document that `_transformed` is WoE. Store coefficients, intercept, bin boundaries, special/missing-value bins, smoothing, transformations, score scaling and rounding in the model registry. Row-level contribution/points must reconcile to the score. Non-WoE transformations are allowed but must be explicit.

Origination values and their transformations remain fixed on subsequent facility snapshots. Current income must not overwrite application income. A later application/rescore requires a separate identity/date/version and must not masquerade as the original underwriting score.

Implement reconstruction tests:

```text
raw inputs + exact model/transform version
    -> transformed inputs
    -> score components/logit
    -> predicted PD for the model target
    -> displayed score and band
```

Use a declared score direction, preferably higher score = lower default risk. For a transparent logistic demo, probability follows the configured logit and score scaling, not an independently drawn random number. Score ranges/base odds/points-to-double-odds are synthetic configuration, not claims about ANB or bureau scorecards.

For every seeded model, a schema test must compare the model registry's feature list against canonical raw/transformed columns and prove complete coverage.

---

## 8. All raw and transformed behavioural-score variables

Provide monthly behavioural scores based only on information available by the score date. Where the score is customer-level or customer-product-level, replicate it consistently across the appropriate facilities and record its subject grain. Do not randomly assign conflicting customer scores to facilities at the same date.

Candidate behavioural inputs include:

1. Current DPD.
2. Maximum DPD in the prior 3/6 months.
3. Missed payments in the prior 3/6 months.
4. Payment-to-due ratio over 1/3 months.
5. Utilisation and its 3-month change for revolving products.
6. Minimum-payment-only behaviour for cards.
7. Overlimit behaviour for cards.
8. Cash-advance share for cards.
9. Salary-credit amount/change.
10. Missed salary cycles/salary delay.
11. Verified income volatility.
12. Average personal account balance/buffer.
13. Bureau-score deterioration and external delinquency.
14. New external obligations and bureau enquiries.
15. Broken promises to pay and failed direct debits.
16. Months on book and available behavioural history.
17. Recent restructure/forbearance indicators where valid for the intended model use.
18. Balloon-payment proximity and affordability for applicable auto finance.
19. LTV deterioration for secured finance where included by the configured model.
20. Repayment regularity/customer activity indicators with explicit definitions.

For every actual model feature, expose:

```text
beh_<feature>_raw
beh_<feature>_transformed
beh_<feature>_bin
beh_<feature>_missing_flag
beh_<feature>_points
```

Attach model and transform versions, history coverage, score date and missing/stale-data statuses. Do not copy raw values into transformed columns as a placeholder.

Separate thin-history/not-yet-scoreable cases from low scores. Missing data is not automatically benign. A defaulted account's collection/status treatment must be explicit; do not include already-defaulted customers in a performing-account forward-default model's validation by accident.

Behavioural scores should respond coherently to changing repayment/income/utilisation conditions, with genuine overlap and noise in realised outcomes. They must not perfectly encode the future default label.

---

## 9. Scorecard monitoring: correct cohorts, outcomes and audit evidence

This conversion must support the buyer's scorecard-monitoring questions THROUGH EXISTING Cockpit/blueprint/table/chart/report interfaces. Do not create an unsolicited new top-level scorecard UI.

### 9.1 Define the prediction target first

For each model, declare the score date, subject grain, target event, prediction horizon, eligibility criteria and outcome definition. A synthetic initial target may be first new default within 12 months among non-defaulted eligible accounts, using a documented default policy. Application and behavioural targets may differ; do not compare unlike targets as though identical.

Discrimination requires observed outcomes, not merely a score distribution. Calibration requires a valid probability prediction for the SAME target/horizon as the observed outcome. IFRS 9 PD is not automatically the right probability for testing an application scorecard.

### 9.2 Maturity and no future leakage

Maintain feature as-of dates, prediction dates, observation end dates and when outcomes became known. A snapshot dated August 2026 does not possess a completed next-12-month outcome in September 2026.

Build monitoring evaluation views by pairing historical predictions with subsequently observed events in the same canonical portfolio history. Source snapshots stay immutable. Any materialised evaluation labels must carry `outcome_known_at` and be excluded from operational predictor queries. Do not silently rewrite historical feature rows with future knowledge.

For a complete-case 12-month validation, require the full eligible follow-up window. A case defaulting early is a known positive, but do not include early positives while excluding equivalent immature non-defaults in a way that biases the complete-cohort metric. Use a consistent mature-cohort rule or an explicitly implemented censoring-aware methodology. Do not silently treat censored or missing-follow-up accounts as good.

For application monitoring, use each application once at origination; do not count the same unchanged application score once per monthly facility snapshot. Identify pre-window applications whose full first-year outcomes cannot be reconstructed. Exclude with a reason rather than inventing follow-up.

For behavioural monitoring, define monthly landmark cohorts. Account/customer repetition and overlapping outcome windows require explicit handling. Use customer/facility-cluster-aware uncertainty methods where appropriate; do not treat hundreds of repeated rows as independent borrowers.

Twenty-five months support useful comparisons, but do not claim an unlimited history of matured 12-month performance. Display latest available monitoring date separately from latest eligible prediction cohort. Near-zero defaults, one-class samples, or inadequate size should yield "Insufficient evidence" with counts, not zero or fabricated confidence.

### 9.3 Computations and explanatory scope

Implement or correctly connect deterministic calculations for:

- ROC-AUC and Gini with correct score direction; default is the positive class, so a higher-is-safer score must be oriented accordingly. Gini = 2*AUC - 1. Do not take an absolute value to hide inverted scores.
- KS using cumulative good/bad distributions with correct treatment of ties.
- Score-band/decile counts, defaults, bad rates and ranking reversals, using explicit stable or cohort-derived bands as labelled.
- Confidence intervals/sample adequacy, with a documented bootstrap or other justified method.
- PSI for score distributions and characteristic stability for inputs using frozen reference bins, explicit missing categories and declared zero-bin smoothing.
- Observed-to-expected default counts and calibration by probability band when a valid matching PD exists.
- A calibration plot; a Brier score may supplement it but must not be presented as a pure calibration statistic.
- Product, model-version, channel, employer segment and other supported cuts with small-sample warnings.
- Raw-to-transformed-input checks and score reconstruction reconciliation.
- Override versus non-override descriptive performance, with selection/confounding limitations rather than unsupported causal claims.

Do not aggregate incompatible model score scales into one AUC/PSI without an explicit common-risk basis. Comparing different versions requires version-aware cohorts, mappings and reference definitions. Reference data may be a fixed early monitoring cohort; label it that way. Do not call it a development/independent-validation sample unless it really is one.

Use configurable monitoring thresholds and sample requirements. Do not state that a chosen PSI, Gini or KS boundary is a universal regulatory pass/fail criterion. Do not auto-certify a model, issue independent approval, or prescribe redevelopment from one metric.

### 9.4 Audit-ready result objects

Every monitoring response must provide:

```text
question, model/version, target/horizon, evaluation_as_of,
prediction_cohort_dates, sample_count, distinct_customer_count,
default_count, exclusions, reference_definition,
metrics, uncertainty, threshold_policy_version,
findings, limitations, calculation_evidence_refs,
data_snapshot_hashes, code/calculation_version
```

An auditor-response draft must distinguish a computed fact, a source-document statement and an interpretation. If no real validation report is supplied, say that documentary evidence is unavailable. Synthetic data supports a synthetic demonstration, not an assertion about ANB's model performance.

The following questions should work in the existing Cockpit:

- "Has the application scorecard's discrimination weakened for personal finance?"
- "Which behavioural variables have drifted most?"
- "Show the raw input, transformation and points behind this customer's score."
- "Is this a ranking issue, calibration issue, population shift or data problem?"
- "Draft an evidence-backed response to the auditor, including what we cannot conclude."

---

## 10. Synthetic portfolio generator: coherent Saudi retail history

### 10.1 Reproducible, persistent generation

Create a versioned, deterministic generator and config. Fix the random seed and persist all relevant versions. Generate once during an explicit seed/build step. Ordinary startup, refresh and chat requests must not regenerate data or change totals.

Suggested standard demo target: around 20,000 active facilities in the latest month, with multiple facilities for a meaningful subset of customers and a substantial linked 25-month history. This is a demo sizing choice, not an ANB portfolio estimate. Make counts/configuration adjustable and publish actual generated counts. Use smaller unit/integration fixtures separately; do not quietly ship a few hundred rows as the full demo.

Choose product mixes and balance distributions explicitly as synthetic assumptions. Ensure all four product families and important subsegments have usable representation. Aim for useful monitoring samples, but do not force every tiny slice to have enough defaults or manufacture a favourable metric.

Generate adequate pre-window history internally for 3/6/12-month feature calculations at the first visible snapshot, where a customer/facility actually existed. Do not expose this warm-up as additional user-facing months. Warm-up is not permission to fake long histories for newly originated facilities. Records with insufficient history must retain that limitation.

### 10.2 Generate a longitudinal process, not independent spreadsheets

Model persistent customers, origination decisions, facility lifecycles, balances, payment behaviour, delinquency progression, cure, closure, restructuring and write-off. Introduce a reproducible stream of new originations and exits.

- Customer identifiers and appropriate customer attributes persist.
- Origination date, original amount, original application score and bureau score at origination persist.
- Months on book increments correctly; remaining contractual tenor declines unless a documented modification changes it.
- Amortising loans normally reduce principal through repayments; increases require an explicit drawdown/capitalisation/modification event.
- Cards can revolve and change utilisation within stated balance/limit rules.
- Stage/default/cure transitions are compatible with the account history and configured policy.
- Closed/write-off accounts remain historically observable through a documented lifecycle/closure representation. Their removal from active exposure is not evidence of a successful repayment outcome.
- A cured account can cease current default while retaining its historical default event for validation.
- Source observations, score variables, alerts, PD/LGD/EAD and ECL are connected through the same underlying states, not generated independently.

Keep a balance-reconciliation ledger. Its monthly opening balance, draws, accruals, repayments, write-offs and other identified movements must reconcile to closing balances. Distinguish principal from GCA and booked loss allowance. Prohibit negative balances/probabilities or nonsensical product-specific values unless intentionally represented with an explicit valid accounting treatment.

Use realistic-looking but declared synthetic income, limit, finance amount, tenor, collateral and repayment distributions. The generator must not assert these are observed Saudi or ANB distributions. Origination affordability and exception flags should be coherent with the configured demo policy.

### 10.3 Controlled investigation stories, not hard-coded answers

Seed discoverable, reproducible patterns such as:

- Rising card utilisation plus persistent minimum payments for a defined group.
- Salary-credit disruption among customers linked to a synthetic employer group.
- A personal-finance origination-mix shift in a particular channel/cohort.
- Auto balloon-payment pressure as maturity approaches.
- Mortgage LTV deterioration and longer recoveries under the downturn scenario.
- A scorecard calibration problem that is distinguishable from a ranking problem.
- A small/thin-file population where evidence is deliberately insufficient.

Add separate labelled adversarial fixtures for stale/missing input feeds, corrupted score transformations and measurement/cohort errors. The canonical demo can include controlled missingness with honest quality flags; do not deliberately corrupt core ECL identities and then market the data as clean.

Store scenario-generation intent in a developer manifest NOT accessible as an answer oracle. Answers must be calculated from the records. The system must not repeat scripted conclusions just because a question contains a trigger phrase. Do not imply causal proof of a channel or employer effect from descriptive patterns.

---

## 11. Retail IFRS 9 calculation: coherent data, real calculation paths

Use a transparent demonstration engine and label it accordingly. Preserve any valid domain-neutral engine components, but remove dependencies on corporate rating grades/master scales. Do not claim the synthetic engine is ANB's approved accounting model or production-ready regulatory validation.

### 11.1 Keep the concepts separate

- TTC PD is a documented through-the-cycle probability estimate/reference, not a corporate grade lookup renamed for retail.
- PIT PD reflects a specified forecast/scenario and horizon.
- 12-month PD and lifetime cumulative PD are different quantities.
- Conditional monthly hazard and unconditional marginal default probability are different quantities.
- Application/behavioural PDs are model outputs for their own targets; any connection to IFRS 9 PD is an explicit versioned mapping.
- The unchanged What-If BASELINE usually refers to the selected snapshot's weighted/final ECL. It is NOT the same thing as that snapshot's macroeconomic BASE scenario ECL.

A synthetic TTC-to-PIT link may use documented scenario-dependent hazard adjustments. Keep its coefficients/version visible and label it a demo assumption. Do not claim an empirically estimated Saudi macro relationship without data.

### 11.2 PD curves and ECL horizon

For a simple monthly hazard representation, define:

```text
h(t) = conditional probability of default in month t, given survival
S(0) = 1
S(t) = S(t-1) * (1 - h(t))
marginal_pd(t) = S(t-1) * h(t)
cumulative_pd(T) = sum(marginal_pd(t), t=1..T)
```

All probabilities remain in [0,1]. Curves must not double-count survival. For a facility with life shorter than 12 months, the applicable capped-life measure must be explicitly defined; do not force a misleading lifetime >= uncapped-12-month-PD check.

For performing Stage 1/2 assets, a transparent demonstration formulation is:

```text
scenario_ECL = sum_t[
  marginal_pd_s(t) * EAD_s(t) * LGD_s(t) * discount_to_reporting_date(t)
]
```

Define whether LGD embeds the discounted value of post-default recoveries at default, and avoid discounting those recoveries twice. Document prepayment, survival and EAD conventions consistently.

Stage 1 limits DEFAULT EVENTS to the next 12 months, or shorter remaining exposure life where applicable. It does not truncate all post-default recovery/loss cash flows at month 12. Stage 2 considers defaults over the applicable remaining expected life. Revolving expected life needs an explicit behavioural treatment; do not assume every credit card has a fixed 12-month contractual life.

For Stage 3, use a documented expected-recovery/cash-shortfall approach for already credit-impaired assets, not a performing-account hazard calculation as though they have not defaulted. Where a defaulted PD scalar is stored as one for a reporting convention, document that convention; it does not replace recovery modelling.

Set purchased/originated credit-impaired assets and special products outside the seeded demo scope unless actually implemented. For lease receivables, document the selected impairment policy/model scope rather than implying one staging treatment universally applies to every lease contract. Do not silently apply unsupported special-product accounting.

### 11.3 SICR/stage logic

Define versioned synthetic policies for quantitative and qualitative significant increase in credit risk, DPD backstops, default/credit impairment, forbearance and cure/probation.

The generator may use a conservative illustrative 30-DPD Stage 2 trigger and a 90-DPD/default event trigger with qualitative early-default conditions, but these are documented demo-policy choices, not a complete statement of IFRS/SAMA requirements. Stage 2 must be possible before arrears where SICR evidence exists. Stage 3 must be possible before 90 DPD on documented credit-impairment/unlikeliness evidence.

For PD-based SICR, compare like horizons: current remaining-life risk against an appropriate origination-curve remaining-life reference. Do not divide current 12-month PD by original lifetime PD. Record policy reasons, overrides and any rebuttal logic. Score deterioration alone is not a universal automatic staging rule.

### 11.4 Scenario coherence and weighted ECL

For the synthetic demo deliberately construct coherent ordered scenarios so that, with like-for-like exposure/calculation assumptions:

```text
ecl_upturn_sar <= ecl_base_sar <= ecl_downturn_sar
```

Generate this through coherent PD, recovery/LGD and EAD assumptions. Do not calculate incoherent values and then sort them or swap their labels. Treat this ordering as a deliberate demo invariant, not a universal mathematical requirement for every real portfolio/scenario design.

Require:

```text
0 <= each scenario weight <= 1
sum(scenario weights) = 1 within a specified tolerance

ecl_weighted_sar =
    weight_base * ecl_base_sar
  + weight_upturn * ecl_upturn_sar
  + weight_downturn * ecl_downturn_sar

ecl_final_sar = ecl_weighted_sar + management_overlay_sar
```

A proposed initial demo weighting is base 0.60, upturn 0.20 and downturn 0.20; label it synthetic and configurable. Validate rather than silently normalising invalid user weights. Explain any explicit normalisation chosen by the user.

Do not calculate weighted ECL by multiplying separately averaged PD, LGD and EAD. Weight the complete scenario ECL results. Keep overlays separate, attributable and visible; zero overlays are acceptable for the first seed.

Discounting uses the documented applicable effective-rate convention, not a nominal rate or APR simply because that field is convenient. Define currency rounding and computational precision. Avoid NaN/Infinity in stored results or API JSON.

### 11.5 Small independent golden calculation

Create a unit fixture with constant EAD SAR 10,000, LGD 0.50, zero discount for test simplicity, and 12-month default probabilities:

```text
base = 0.020 -> base ECL = SAR 100
upturn = 0.015 -> upturn ECL = SAR 75
downturn = 0.030 -> downturn ECL = SAR 150
weights = 0.60 / 0.20 / 0.20
weighted ECL = SAR 105
```

Construct marginal probabilities consistently so their 12-month sum matches each stated PD. This test fixture is not a realistic zero-rate product requirement. Add separate Stage 2, Stage 3, short-life and revolving-life fixtures with independent expected calculations.

---

## 12. Early Warning: replace the signal model, not the screen layout

Use the existing EWS pages, cards, severity styles, lists, customer detail views, evidence panels and workflows. Change the domain-specific content and backend calculations.

Create a retail rule library with at least these supported signal families:

- DPD bucket worsening, consecutive missed payments and first-payment/default-risk patterns.
- Persistent minimum payment, rising utilisation, overlimit activity and increasing cash advances for cards.
- Salary interruption/delay, material income decline and shrinking personal cash buffer.
- Rising total monthly obligations, deteriorating affordability and verified new external debt.
- Behavioural score deterioration, input-quality exceptions and relevant bureau deterioration.
- Broken promises to pay, failed autopay and repeated collection escalation.
- Forbearance/restructure stress and unsatisfied cure/probation conditions.
- Auto balloon/final-payment exposure approaching maturity.
- Collateral/LTV deterioration for secured products.
- Synthetic employer-group concentration combined with observed customer-level stress.
- Portfolio/segment signals such as worsening vintage delinquency or a rising Stage 2 share.

Each rule defines rule ID/version, intended product population, feature requirements, lookback window, measurement units, trigger expression, threshold source, severity, evidence, suppression/retrigger behaviour and suggested next step. All thresholds are bank-configurable and initially labelled synthetic.

For each alert persist:

```text
alert_id, rule_id, rule_version, customer_id,
facility_id or explicit customer/segment scope,
snapshot_date, first_seen_date, last_seen_date,
current_status, severity, trigger_value, threshold,
prior_comparator, evidence_record_refs,
affected_exposure_sar, reason, recommended_review,
owner/action references where existing workflows support them
```

A customer-level alert must not be duplicated once per facility. Preserve impacted-facility links and calculate total affected exposure without overlap. Deduplicate repeated runs, maintain history and apply actual closure/suppression/retrigger rules. A new month with persistent stress should update or deliberately retrigger the appropriate alert, not spawn accidental duplicates.

Recommended actions are reviewed suggestions, not automatically executed credit decisions or customer contact. Do not send emails/messages, change bank limits, or apply operational restrictions without explicit authorised action.

Examples of acceptable explanation: "Salary credit has not appeared for two expected cycles and card utilisation rose; verify income continuity." Unacceptable: "The customer has lost their job" without such evidence.

Compute trends using the historical canonical data; no independent EWS random dataset. If EWS currently requires financial-statement uploads, replace those requirements with retail data inputs using existing UI components. Do not leave a hidden mandatory company statement blocking retail investigation.

---

## 13. What-If: use the same snapshot and actual retail sensitivities

Preserve the existing interaction and result design: prompt entry, scenario configuration, baseline/scenario comparison, tables, charts, explanation, saved scenarios and exports.

### 13.1 Shared baseline and scenario identity

A scenario records the exact canonical dataset version/hash, selected month, filters, facility IDs/count, input values, assumptions, model versions and calculation method. No hidden switch to a legacy or smaller portfolio.

A neutral scenario must reproduce the selected baseline within rounding tolerance. Distinguish scenario "base" ECL from the unshocked weighted/final ECL baseline in field names and explanations.

Do not mutate source scores, balances, staging or data versions. Save simulated values under a separate scenario/run identity. Reopening/exporting a saved scenario must reproduce its stored definition, not silently apply a newer seed.

### 13.2 Supported retail shocks

Implement meaningful shocks using available data and documented assumptions:

1. Relative or absolute PD/hazard shifts for selected products/segments.
2. LGD changes and recovery-delay/collateral shocks.
3. EAD/CCF/credit-card utilisation changes consistent with limits and drawn/undrawn exposure.
4. Scenario probability-weight changes with validation.
5. Salary/income changes flowing through affordability, configured behavioural features, score/PD mapping and relevant ECL calculations where the dependency exists.
6. Behavioural-score point shifts through the versioned score-to-PD mapping; do not use corporate notch migrations.
7. Policy-based SICR/stage sensitivity, explicitly distinguishing frozen-stage parameter sensitivity from re-evaluated-stage sensitivity.
8. Auto balloon/refinancing assumptions and mortgage collateral value/recovery sensitivity where implemented inputs support them.
9. Retrospective cutoff/exception exercises over the booked-originations population, with limitations in Section 13.4.

Relative PD +20% means 0.02 -> 0.024. Absolute +2 percentage points means 0.02 -> 0.04. They are different operations and need explicit parsing/validation. A card utilisation move from 40% to 60% is +20 percentage points, not a 20% relative increase.

For a 12-month PD shock, define how the entire hazard/PD curve changes; do not adjust only a displayed scalar while leaving lifetime ECL unchanged. Clip only within declared bounds and disclose clipping. CCFs/LGDs/weights must obey their supported bounds, while valid overlimit card balances must be treated explicitly rather than arbitrarily truncated.

### 13.3 Dependency graph and no double-counting

Implement a declared propagation graph, for example:

```text
income shock -> affordability input -> behavioural transformation
  -> score -> model PD -> IFRS 9 mapping -> staging/ECL
```

Only execute links actually implemented for the model. Do not multiply ECL by an arbitrary percentage and describe it as a full recalculation. Do not apply both a raw-input-derived PD change and an additional explicit PD shock twice unless the scenario explicitly requests the combination and its order is documented.

Historical origination inputs/scores stay unchanged under a current income shock. Distinguish changing an assumption from changing an observed fact. A generic "rate rise" must not automatically raise payments on a fixed-rate contract; any repricing/new-business interpretation must be explicit.

Defaulted accounts require recovery/LGD-based sensitivities, not a performing PD shock above one. Unsupported causal links must result in a precise limitation, not fabricated forecasts.

### 13.4 Booked-only policy experiments

The canonical domain contains facilities, not the complete rejected/approved application universe. A tighter cutoff can be replayed retrospectively on booked originations to show which historical funded accounts would be excluded and their observed outcomes.

Do not call that result the bank's future approval rate, a causal loss reduction, a validated profitability forecast, or an estimate of the performance of rejected customers. Relaxed-cutoff/new-approval forecasts require additional application and outcome evidence/model assumptions. State the missing data explicitly; never manufacture rejected-applicant rows to make the chart work.

### 13.5 Results, exports and API behaviour

Return baseline/scenario totals, deltas in SAR and percent, population, product/segment contributions, stage movements where applicable, drivers, assumptions, limitations and evidence.

If the baseline denominator is zero, a percentage delta is unavailable; do not emit infinity. Preserve numeric types and units. Test all currently advertised methodologies and exports, including stale-client/invalid-methodology errors. Unsupported methodology requests must list valid retail choices rather than falling through to an old rating engine.

Preserve real distinction among timeout, unreachable service, validation error, unauthorised and forbidden errors. Use actionable messages; do not misreport every failure as "no data".

---

## 14. Cockpit understanding, blueprints and meaningful output

Reconfigure the existing domain resolver and investigation blueprint registry to use the ONE retail domain. A user should be able to ask for portfolio, scorecard, EWS or ECL analysis without first selecting a separate score/rating dataset.

Handle spelling variants and natural language such as cockpit/cokpit, whatif/what if, ECL/ecl, home loan/mortgage/home finance, auto loan/auto lease, personal loan/personal finance, behavioural/behavioral, and bureau-score-at-origination. Do not require exact column names.

A single paragraph may state a dataset, period, product and analysis request. Parse the whole instruction. Persist follow-up context: "now only salary-transfer customers", "compare with last year", "why did that rise?", "show the evidence".

Add or adapt concrete, tested retail blueprints for:

- Portfolio overview and concentration.
- Retail IFRS 9 snapshot and scenario comparison.
- ECL movement/decomposition.
- Stage migration and delinquency roll rates.
- Vintage and early-delinquency performance.
- Score distribution/population drift.
- Application discrimination and calibration with mature cohorts.
- Behavioural discrimination/calibration with valid prediction landmarks.
- Raw/transformed input and score reconciliation.
- Affordability/salary stress.
- EWS customer and segment investigation.
- Retail What-If sensitivity and retrospective cutoff analysis.
- Evidence-backed monitoring/auditor-response draft.

For each blueprint specify recognisable intents, required fields, product scope, date/cohort rules, exclusions, computations, comparison basis, result schema, chart applicability, evidence, limitations and follow-up handling. Do not register an analysis name without an executable calculation path.

The LLM selects tools and explains verified results. Deterministic code computes financial totals, score transformations, metrics, thresholds and reconciliations. Enforce that generated numeric claims are grounded in result objects, not invented during narrative generation.

Do not show a chart for every question. A definition, yes/no explanation, missing-evidence response or one-scalar answer may require no chart. Trends, distributions, migration matrices and decompositions should use the existing appropriate components with correct labels and denominators. The table and chart must show the same numerical result.

Use existing clarification components. When the current UI already supports option chips, populate them for real ambiguities and retain free text. Do not add a new control system as part of this data conversion. Avoid unnecessary clarification when the selected retail domain/period already resolves the question.

---

## 15. ECL movement and decomposition must remain meaningful

The user has previously experienced meaningless ECL charts/decompositions. Prevent this regression in the retail version.

Compare opening and closing snapshots with an explicit facility-level reconciliation. Identify:

- Continuing matched facilities.
- New originations/drawdowns.
- Closed, repaid or written-off facilities and other exits.
- PD changes, LGD/recovery changes and EAD/amortisation changes.
- Stage/horizon changes.
- Scenario weight or model/methodology changes.
- Management overlay changes.

Use a defined, reproducible attribution method. If sequential replacement is used, publish the replacement order and note its order dependence. If an existing Shapley/symmetric methodology is retained, implement it correctly and efficiently. Do not call a sequential bridge Shapley or silently assign all interaction to PD.

Opening ECL plus all identified contributions must equal closing ECL within declared rounding tolerance. Match scope and dataset versions. Do not plug unexplained differences into an unlabeled "other" bucket to make the graph balance; investigate and disclose a genuinely defined residual where the methodology requires one.

Some model-change bridges require old/new calculation versions on the same inputs. Preserve the needed inputs/configs rather than inventing that attribution. Label sensitivity attribution versus observed accounting movement appropriately.

The waterfall/bridge uses actual computed contributions, not raw PD/EAD values pasted into a chart. Provide an evidence table and affected-facility drill-down using existing UI components.

---

## 16. Other existing modules, reports and user-visible examples

Do not rebuild unrelated modules. For every module present and reachable in this baseline, remove domain-inappropriate seeds/examples and ensure it operates on retail context.

- Playbook: replace existing seeded company packs with labelled synthetic retail portfolio monitoring, scorecard monitoring and retail IFRS 9 examples. Preserve existing editing, versioning and export behaviour. A static sample must state its dataset version/date; regenerable numerical sections must reconcile to the same source.
- Lenses/report readers: retail sample documents and retail questions; do not index retired company packs.
- Planner: retain workflow functionality, but use retail monitoring/audit-remediation example records if sample records are present. Do not claim integration with a module that is absent in this source.
- Search, home prompt chips and saved scenarios: retail questions and valid identifiers only.

Generated reports use the same calculation result/evidence object as the UI. Do not run an unrelated second calculation for the report and produce contradictory totals. Preserve source references through edits and exports where the existing workflow supports them.

All synthetic data and sample reports must carry a concise clear disclosure in existing metadata/subtitle/footer facilities: "Synthetic Saudi retail demonstration data — not ANB customer data or approved models." Do not misrepresent synthetic documents as real auditor submissions or completed independent validation.

No new branding, typography, theme, landing page, dashboard redesign, side navigation, onboarding wizard or report-design system is authorised.

---

## 17. DataBuilder publishing, imports, reset and future real data

The retail demo must be ready on first launch. Use an explicit, idempotent seed/build step and a published manifest. Do not let multiple startup workers race to seed different portfolios.

Publish the complete 25-month dataset version atomically after schema, numerical and completeness checks. A partial build must not replace the current valid version. Keep a branch-local rollback path. A reset command must verify the retail target and refuse the original frozen databases or unapproved shared resources.

DataBuilder must show only the intended retail domain(s)/derived retail binding required by existing module contracts, with Cockpit showing ONE "Cockpit Data" domain and its 25 monthly datasets. Do not retain separate selectable corporate IFRS 9/rating domains or duplicate Cockpit score/ECL domains.

Each published monthly dataset should expose existing-style metadata: reporting month, row/customer/facility counts, products, schema version, dataset version, synthetic status, validation status and latest load time. Support preview/export through existing controls. Avoid dumping every wide-table column into a cramped first-screen table; preserve the current column-selection/preview pattern.

Implement a machine-readable import contract so authorised bank data can later replace the synthetic records. Require explicit column mappings, units, score dates, model identifiers, as-of dates and null handling. Do not silently repair duplicate keys or convert percentages by guessing.

Reject out-of-scope entity types, malformed or incompatible model inputs, invalid probability units, missing identities, broken scenario weights and unsupported dates with actionable validation errors. Detect supplied historical outcome labels and treat them as restricted monitoring labels, never default predictors. Do not mix imported real data and synthetic rows into a supposedly real dataset without explicit separately labelled lineage.

Reset/import/delete only the new installation's selected dataset namespace. Do not remove the user's other project files or original demo assets.

---

## 18. Performance, reliability and security

Implement against the actual installed stack. Avoid unnecessary dependency upgrades or a new analytics platform. Pin/reuse compatible versions and test the real installed API, not a remembered latest-library signature.

Use column projection, partition pruning, indexed joins/queries, chunked generation and server-side aggregation. Do not load every month and hundreds of columns into browser memory. Do not send raw customer-level wide tables to the LLM to compute a total.

Default chat context should use metadata, permitted filters, aggregates and limited evidence samples. Sensitive fields/labels must be excluded by an explicit access/semantic policy. Even though this seed is synthetic, do not build a pipeline that casually exposes real bank data when it is later imported.

Cache keys include installation namespace, domain ID, dataset hash/version, dates, filters, model versions and scenario parameters. Invalidate only the relevant new-installation cache when data changes. Test stale-browser local storage/service-worker/schema state where the existing frontend uses them.

Bound long-running calculations, propagate meaningful progress/status through existing components, and handle cancellation/timeouts without leaving corrupted scenario or export records. Measure seed time, storage, peak memory and representative query/What-If latency on the actual available environment. Report measurements honestly; do not make unmeasured performance claims or silently reduce the required 25-month history to achieve a faster screenshot.

No secrets in logs, Git commits, screenshots, fixtures or exported reports. Redact sensitive environment values in provenance documents. Keep .env ignored. Do not introduce an external telemetry service, paid API, or data-upload dependency. Treat retrieved/uploaded document content as untrusted data, not instructions to override the application or reveal credentials.

Export safe numeric/date types, escape spreadsheet-formula injection in user-controlled CSV fields, and validate that JSON has no NaN/Infinity. Preserve authentication and authorisation; do not bypass them to make the demo pass.

---

## 19. Executable acceptance gates

Create automated tests with IDs matching the following gates, plus any necessary implementation-specific regressions. Tests must verify behaviour and numerical results, not only HTTP status 200, source-code strings or the existence of a chart container.

### Source and isolation

RET-001: The source manifest identifies the actual WHATIF_5318 repository/worktree and proven commit/build state, or explicitly records the unresolved access blocker without guessing.

RET-002: All implementation commits are on the new retail branch. The original 5318/5308 branch worktrees, launchers, data and environments are unchanged by the conversion.

RET-003: Database, files, caches, indexes, logs, process records and service ports are isolated. A seed/migration/reset pointed at an original-demo target fails safely.

RET-004: The new launcher starts the retail frontend against the retail backend and verified retail dataset. No fallback/port confusion serves the original portfolio.

### Catalog, schema and chronology

RET-005: Cockpit exposes one retail "Cockpit Data" analytical domain and exactly 25 consecutive month-end datasets from the pinned configuration.

RET-006: The initial demo spans August 2024 through August 2026 inclusive; no future or duplicate month is included. Changing the demo date is explicit and manifest-versioned.

RET-007: Primary and facility-month keys are unique. Multi-facility customers have consistent shared attributes and correct separate facility records.

RET-008: All four requested product families and meaningful product-appropriate Saudi subsegments exist. No financed company entity appears.

RET-009: Schema and metadata validation cover all required field families, units, null rules, product applicability and aggregation semantics.

RET-010: Origination/maturity/score/bureau/default/cure dates and months-on-book chronology are valid. No facility has monthly exposure before it exists.

RET-011: Application score, raw origination inputs, transformations and bureau score at origination remain unchanged over later snapshots unless an explicitly distinct rescore/application is recorded.

RET-012: Every feature in every configured application and behavioural model has its raw and transformed canonical columns; no hidden model input is omitted.

RET-013: Scores reconstruct from their exact input/transform/model versions within declared rounding tolerance. Higher/lower score direction is correctly represented.

RET-014: Rolling behaviour, payment ratios, utilisation and salary signals reconcile with actual available history. Thin-history cases have an honest unavailable status.

RET-015: Balance movements reconcile. Product-specific fields are applicable or explicitly null; term loans do not carry random credit-card features.

RET-016: Customer-level totals and distinct counts are not multiplied by facility count. Monthly stock/flow semantics are correct.

RET-017: Re-seeding with identical configuration yields identical business data/content hashes. Repeated startup does not regenerate data.

### IFRS 9 and scenario coherence

RET-018: Scenario weights are valid and weighted/final ECL identities reconcile row-wise and in aggregate, with overlays separate.

RET-019: The deliberately ordered demo satisfies upturn ECL <= base ECL <= downturn ECL for like-for-like rows through coherent inputs, not sorted outputs.

RET-020: PD/hazard/survival/lifetime relationships and bounds are correct, including shorter-than-12-month lives and zero/near-one probabilities.

RET-021: Stage 1, Stage 2, Stage 3 and revolving expected-life fixtures use the declared methods. Stage 1 does not incorrectly truncate recovery losses at 12 months.

RET-022: Stage/SICR/default/cure decisions match their versioned policy/reason fields, including qualitative early SICR/default and documented overrides.

RET-023: The independent SAR 105 golden fixture passes; additional lifetime, recovery, discounting and overlay fixtures reconcile.

RET-024: Cockpit, EWS affected-population queries, What-If baseline and exported reports reconcile for identical snapshots/filters.

RET-025: ECL movement bridges reconcile opening and closing amounts, include entrants/exits and disclose the implemented attribution methodology.

### Scorecard validity and evidence

RET-026: AUC/Gini/KS agree with independent trusted calculations on known fixtures, including inverse scores, ties, missing scores and single-class samples.

RET-027: Application monitoring does not count the same application 25 times. Behavioural monitoring declares landmarks and handles repeated customers correctly.

RET-028: Immature, censored and pre-history-incomplete cohorts are handled explicitly. No unknown outcome becomes a non-default by default.

RET-029: Historical-as-of tests cannot access future score inputs or future outcome knowledge. Current prediction views exclude evaluation-label columns.

RET-030: Calibration uses the proper probability target/horizon; unrelated IFRS 9 PD is not substituted for a missing application-score PD mapping.

RET-031: PSI/characteristic stability uses the declared reference population/bins, handles zero/missing bins and preserves model-version distinctions.

RET-032: Small/low-default segments return sample counts and "Insufficient evidence" where required, not a fabricated pass/fail or confidence interval.

RET-033: Audit-response numerical claims trace to result objects; absent documentary evidence is disclosed and synthetic results are not claimed as ANB findings.

### EWS

RET-034: EWS builds actual retail alerts from the same canonical data with valid dates, scope, trigger measurements and row evidence.

RET-035: Repeated EWS runs deduplicate correctly; update, suppression, closure and retrigger behaviour are tested.

RET-036: Customer-level alerts and affected exposure are not duplicated across facilities or overlapping rules.

RET-037: At least one salary, repayment, card utilisation, bureau/behavioural, auto balloon and secured-LTV scenario is demonstrated where product-applicable.

RET-038: No company financial-statement requirement blocks an EWS workflow. Missing retail inputs produce precise limitations, not invented evidence.

### What-If

RET-039: A neutral scenario exactly reproduces the selected baseline within tolerance and leaves canonical data unchanged.

RET-040: Relative-percent and percentage-point PD/utilisation shocks have distinct correct results. Curve propagation is tested.

RET-041: Reweighting scenarios recomputes the weighted ECL identity; invalid weights and invalid methodology values return meaningful errors.

RET-042: Income/score/PD/ECL dependencies are real and do not double-count shocks. Historical origination scores remain unchanged under a current-income shock.

RET-043: Defaulted-account, fixed-rate, secured/revolving and short-life sensitivities follow their declared semantics rather than generic multiplication.

RET-044: Booked-only cutoff analyses are labelled correctly; rejected-applicant/future-approval outcomes are not fabricated.

RET-045: Saved scenario reload, interpretation and every advertised export/methodology work using the original pinned inputs, including stale-client error handling.

### Product surface, reliability and browser

RET-046: Active catalog, pages, prompts, examples, reports, seeded chats and retrieval results are retail-only. A source/static scan AND rendered runtime scan are both performed with a narrowly documented allowlist for developer history/legal text.

RET-047: Removed domain IDs/stale requests cannot silently route to retired datasets. Empty retail data cannot trigger a legacy fallback.

RET-048: Existing layouts/components/navigation structure are preserved. Only justified retail text, options, data bindings and necessary semantics have changed.

RET-049: A scalar/definition/evidence-insufficiency question produces no irrelevant chart; quantitative charts use the correct computed result and labels.

RET-050: A one-paragraph dataset+period+question request and contextual follow-ups work. Existing clarification controls remain usable.

RET-051: All visible controls on the affected workflows are exercised in a real browser against the running backend; no dead or mocked-only control is claimed working.

RET-052: JSON/export values are finite and typed; zero denominators, empty filters, unknown IDs, missing files and model/schema mismatches return actionable states.

RET-053: Dataset publication/reset/import is idempotent, atomic and isolated. Partial failures do not leave a half-published portfolio.

RET-054: Fresh-start and isolated-upgrade tests pass against the actual migration graph. Retired seeds do not reappear after restart.

RET-055: Representative large-demo queries and scenario runs complete on the actual environment; memory/storage/latency measurements and any constraints are recorded.

RET-056: No secrets or real customer identifiers are committed/logged/exported. Auth and data-access restrictions remain intact.

RET-057: The implementation report distinguishes tested, failed, blocked and not-run work, including tests requiring unavailable external model credentials.

RET-058: The readiness script verifies build identity, retail backend connection, 25-month manifest, data reconciliation and key routes before opening the app.

RET-059: Start/stop scripts manage only positively identified retail processes, are safe to rerun, and leave the frozen original processes alone.

RET-060: Final code, synthetic generation configuration, documentation and test evidence agree at the final commit. No completion claim depends on an earlier tested commit while later untested patches remain.

Do not weaken tests or delete assertions to obtain a green report. Intentionally defective fixtures must be detected, not hidden. Keep test-generated portfolio examples clearly separate from the shipped seed.

---

## 20. Real-browser UAT and demonstration question suite

Use the browser automation/test tooling actually available in the repository. Run it against a real frontend/backend and the seeded retail database. Unit mocks are useful but do not prove the live demo works. Save screenshots, test logs, evidence/result hashes and a control-audit table.

Exercise DataBuilder selection/preview, monthly switching, filters, Cockpit questions, result tables, appropriate charts, drill-down, What-If execution/save/reload/export, EWS details/actions, and existing report functionality reached by this scope. Test new and stale browser sessions.

For each question below record expected intent, dataset/date resolution, cohort/population, independently computed expected result or invariants, actual result, evidence and pass/fail. Do not manufacture expected values in advance; calculate them from the generated dataset in an independent test path.

### Portfolio and IFRS 9

1. "For August 2026, show retail exposure, customers, facilities and weighted ECL by product."
2. "Compare August 2026 with August 2025. Which products contributed most to the ECL movement?"
3. "For personal finance, show base, upturn, downturn and weighted ECL. Prove the weighted calculation."
4. "Why did ECL increase from July to August? Separate stage, PD, LGD, EAD, new business and exits."
5. "Show Stage 1 to Stage 2 migration for auto finance between June and August 2026."
6. "For cards, show 30+ and 90+ DPD trends over all 25 months, with the denominators."
7. "Which personal-finance origination vintages show the highest six-month delinquency? Exclude immature vintages."
8. "Which synthetic employer groups have the largest affected retail exposure? Count customers only once."
9. "Compare salary-transfer and non-salary-transfer personal finance by affordability and delinquency."
10. "What is the difference between base-scenario ECL and the baseline in What-If?" This is an explanatory answer, not an automatic chart.

### Scorecards and auditor questions

11. "Using the latest fully observed 12-month cohorts, test the personal-finance application scorecard's AUC, Gini and KS."
12. "Show default rates by application-score band and highlight any meaningful ranking reversals."
13. "Has the digital-channel score distribution shifted from the fixed reference cohort? Show PSI and counts."
14. "Which behavioural-score inputs have shifted most, including missing-value changes?"
15. "For this facility, reconstruct the application score from raw inputs, transformations and points."
16. "Explain why this customer's behavioural score declined over the last three months, using only observed inputs."
17. "Compare expected and observed 12-month defaults for the scorecard, not the ECL model."
18. "Calculate next-12-month Gini for August 2026 scores." The correct result must explain that those outcomes are not yet available; it must not invent a metric.
19. "Draft a response to the auditor on discrimination, calibration, drift and limitations, with sample counts and evidence."
20. "Does this scorecard need redevelopment?" The result must be evidence-qualified, not an automatic yes/no certification.

### Early Warning

21. "Which retail customers have missed salary credits and simultaneously increased card utilisation?"
22. "Show new high-severity retail warnings in August, excluding alerts already open in July."
23. "For this customer, show all affected facilities without double-counting exposure."
24. "Which auto customers have balloon payments approaching and weakening payment buffers?"
25. "Show the exact source values that triggered this alert and the corresponding dates."
26. "Run the same EWS evaluation again." Alert duplication must not occur.

### What-If

27. "Increase personal-finance PIT PD by 20% relative and show the weighted ECL change."
28. "Increase that PD by 2 percentage points instead." The engine must produce different correctly scoped mathematics.
29. "Keep all inputs unchanged and rerun the baseline." The delta should be zero within tolerance.
30. "Change scenario weights to base 50%, upturn 10% and downturn 40%. Show the calculation."
31. "Reduce verified salary by 15% for the selected group. Recalculate only the dependencies the model actually supports."
32. "Reduce mortgage collateral values by 10% and lengthen recovery by six months. Explain the LGD/ECL effect."
33. "Raise the historical application cutoff for booked personal-finance originations. What would have been excluded?"
34. "If we lower the cutoff, how many rejected applicants will default?" The system must identify the missing applicant/outcome data, not produce fictitious answers.
35. "Export the scenario and its assumptions, then reopen it." Results and inputs must agree.

### Robustness and source selection

36. "Using Cockpit Data for Aug 2026, show cards with rising utilisation and explain their ECL movement in the same answer."
37. "Now only salary-transfer customers." The follow-up retains prior intent and month.
38. "Show a current portfolio exposure total across all 25 snapshots." Resolve the stock-versus-time ambiguity explicitly instead of summing repeated balances.
39. Query a removed legacy domain identifier directly. Return a retail-only scope error without reviving that dataset.
40. Apply an empty segment filter and then export. Show an honest empty result and a valid, clearly labelled empty export or appropriate error.

Additionally, seed and verify a stable ranking/calibration case, a calibration-without-large-ranking-change case, a population-mix change case, a score-implementation error test case, and an insufficient-outcome case. Do not use the same diagnostic conclusion for every one.

---

## 21. Implementation phases and work discipline

Proceed in coherent milestones. Use small reviewable commits. Inspect before editing. Maintain the progress log, assumptions register and requirements traceability so work can resume without dropping requirements when context is compacted.

Phase 0 — Source verification, branch/worktree and runtime/data isolation.

Phase 1 — Baseline inventory, canonical schema, retail taxonomy, model/transform/policy registries and semantic metrics.

Phase 2 — Longitudinal synthetic generator, 25-month publication, score reconstruction and valid monitoring outcome preparation.

Phase 3 — Retail ECL/scenario engine, independent numerical fixtures and reconciliation.

Phase 4 — DataBuilder/Cockpit domain routing and executable retail investigation blueprints.

Phase 5 — Retail EWS projection/rules/evidence/deduplication.

Phase 6 — What-If retail dependencies, baseline parity, saved scenario and export contracts.

Phase 7 — Retail-only content sweep, existing report/example conversion, performance and security checks.

Phase 8 — Automated regression, actual-browser UAT, final demo verification and handover.

Do not stop at a phase boundary merely to ask whether to continue. Continue implementation and verification. Do not claim a long-running process completed while it is still running. Do not rely on a promised future/background result in the final handover.

Use parallel agents only on clearly separated tasks/interfaces. Establish one canonical schema/semantics owner and reviewed contracts; do not let agents independently invent three different retail portfolios. Integrate and test their output rather than treating agent summaries as proof.

Do not spend paid model calls on deterministic data generation or arithmetic. Where live LLM calls are part of the product and configured credentials authorise them, test representative real end-to-end questions. If credentials/network/browser access are absent, run all independent work and mark those specific gates BLOCKED/NOT RUN. A mock-only pass is not a live LLM/browser pass.

If a requirement cannot be completed, record exactly what fails, its user impact, reproduction and next required step. Do not conceal a dead advertised function behind a screenshot or treat documentation as implementation.

---

## 22. Required repository deliverables

Adapt file paths to the actual codebase, but deliver equivalent content:

```text
docs/RETAIL_ONLY_MASTER_SPEC.md
docs/RETAIL_ONLY_PROGRESS.md
docs/RETAIL_SOURCE_PROVENANCE.md
docs/RETAIL_CONVERSION_INVENTORY.md
docs/RETAIL_DATA_DICTIONARY.md
docs/RETAIL_DATA_CONTRACT.json
docs/RETAIL_MODEL_AND_TRANSFORM_SPEC.md
docs/RETAIL_ECL_METHODOLOGY.md
docs/RETAIL_EWS_RULEBOOK.md
docs/RETAIL_WHATIF_SUPPORTED_OPERATIONS.md
docs/RETAIL_BLUEPRINT_CATALOG.md
docs/RETAIL_ASSUMPTIONS_AND_LIMITATIONS.md
docs/RETAIL_REQUIREMENT_TRACEABILITY.md
docs/RETAIL_UAT_REPORT.md
docs/RETAIL_DEMO_GUIDE.md
docs/RETAIL_ONLY_HANDOVER.md

config/retail_demo_config.<existing-config-format>
config/retail_scorecards.<existing-config-format>
config/retail_policies.<existing-config-format>
config/retail_scenarios.<existing-config-format>

<versioned source/build manifest>
<25-month dataset manifest with hashes and actual counts>
<idempotent generator and validation commands>
<unit, integration, contract and actual-browser tests>
<safe retail start, stop and readiness scripts>
```

Do not create a decorative documentation forest with no working code. The traceability file links each gate to implementation files, test IDs and actual results.

Generated large datasets should live in a documented ignored data location, not be casually committed as enormous binaries. Commit deterministic generation/configuration and small test fixtures, and provide a reproducible bootstrap. Never commit credentials, real personal data or copied original database contents.

---

## 23. Demo launch and freeze handover

Provide a safe Mac-friendly launcher and stop script using the conventions of the actual source installation, preferably executable `.command` files if that is how the user launches the frozen demos.

The start script must:

1. Resolve its own directory rather than relying on the Terminal's starting directory.
2. Verify branch/build identity, environment and isolated data paths.
3. Verify or explicitly bootstrap dependencies/data using documented commands; ordinary demo start must not silently upgrade packages or regenerate a new portfolio.
4. Check ports and positively identify any already-running retail process.
5. Start the verified retail backend/frontend in the correct order.
6. Check backend readiness, active retail domain, pinned dataset version and 25-month completeness.
7. Open the actual frontend address only after the readiness checks pass.
8. On failure, show the relevant log path and actionable cause rather than opening a blank page.

The stop script must use verified PID identity/ownership/command information. Handle multiple PIDs correctly. Do not pass a newline-concatenated string as one PID, and do not use broad `pkill python`, `killall node`, or kill-by-port commands that might stop 5318/5308 or unrelated services.

Produce a `check_retail_ready` command that verifies the most important numerical and runtime checks without silently mutating data. Record the final tested SHA, branch, launcher paths, ports, data manifest hash and package lock hashes. A release/freeze tag may be created only as a new clearly named retail tag; never move an existing freeze tag.

Do not overwrite original Desktop launchers. Put the retail launchers in a distinct clearly named location and provide exact instructions for opening this new installation.

---

## 24. Final Claude Code response: required evidence

At completion, provide a precise handover containing:

- The proven source branch/tag/detached state and full commit; explain any original dirty-build qualification.
- The new branch, worktree, final tested commit and isolated runtime/data locations, without secrets.
- Actual launch/stop/readiness commands and which launcher the user should click.
- Exact 25-month range and actual monthly/distinct customer/facility/product counts.
- Which retired domains/seeds were removed from active use and how the retail-only sweep was verified.
- Which UI labels/options changed, and confirmation of preserved layouts supported by before/after evidence.
- Scorecard feature completeness/reconstruction results and sample-eligibility safeguards.
- Numerical ECL/scenario/baseline/decomposition reconciliation results.
- EWS and What-If real-browser evidence and supported-operation limitations.
- Acceptance gate results, failed/blocked/not-run items and any existing-source defects that remain.
- Measured performance on the actual environment and known constraints.
- Exact files containing the dictionary, assumptions, UAT questions, methodology and reproducibility instructions.
- Evidence that original 5318/5308 application assets and data were not modified.

Do not say "all done", "fully production-ready", "SAMA compliant", "ANB approved", "auditor certified" or "all tests pass" unless the exact scoped claim is genuinely supported. This deliverable is an implemented and tested synthetic Saudi retail demonstration with disclosed limits, not regulatory or independent model approval.

The target outcome is concrete: the user opens the NEW retail installation, sees the familiar CreditProbe UI, finds only retail data, can select any of the 25 months, asks portfolio/scorecard questions in Cockpit, investigates retail EWS signals and runs retail What-If scenarios against the SAME reconciled dataset.

---

## 25. Reference basis and verification discipline

The business scope and implementation choices above are this project's requirements. Synthetic ranges, scenario weights, score models and policy thresholds are design assumptions, not claims about ANB.

The following primary sources were consulted when preparing the methodological safeguards. Recheck relevant current official material before implementing any specific regulatory requirement. These references are not permission to replace the source repository's compatible dependencies with the newest version.

[R1] Saudi Central Bank, Responsible Lending Principles for Individual Customers, official rulebook. Relevant to consumer income, credit obligations, disposable income, documented creditworthiness and individual finance scope. The Arabic governing text and subsequent applicable circulars matter for actual compliance work.

```text
https://rulebook.sama.gov.sa/en/responsible-lending-principles-individual-customers-0
```

[R2] IFRS Foundation, IFRS 9 supporting materials and official standard landing page. Relevant to verifying impairment definitions, horizons, staging, revolving-life and recovery conventions; a demonstration engine is not a substitute for the applicable standard and bank methodology.

```text
https://www.ifrs.org/supporting-implementation/supporting-materials-by-ifrs-standards/ifrs-9/
https://www.ifrs.org/issued-standards/list-of-standards/ifrs-9-financial-instruments/
```

[R3] IFRS Foundation, IFRS 9: Forward-looking information and multiple scenarios. Relevant to scenario consistency, non-linearity and probability-weighted assessment. The explicit upturn/base/downturn ordering in this specification is a synthetic demo requirement, not a quoted universal IFRS rule.

```text
https://www.ifrs.org/news-and-events/news/2016/07/25-webcast-on-ifrs-9/
```

[R4] scikit-learn official ROC-AUC documentation. Relevant to positive-class orientation and the Gini/AUC relationship. Use the repository's installed, tested version.

```text
https://scikit-learn.org/stable/modules/generated/sklearn.metrics.roc_auc_score.html
```

[R5] scikit-learn official probability-calibration documentation. Relevant to observed-versus-predicted probabilities, calibration curves and the fact that Brier loss is not a pure calibration measure.

```text
https://scikit-learn.org/stable/modules/calibration.html
```

[R6] Git official worktree documentation. Relevant to new-branch/worktree mechanics and the fact that worktrees share repository-level resources; application-state isolation must be configured separately.

```text
https://git-scm.com/docs/git-worktree
```

[R7] ANB official personal-banking website. Used only as context for personal, card, auto-lease and home/real-estate finance categories, not as evidence of internal portfolio distributions, scorecard inputs or policies.

```text
https://anb.com.sa/web/anb
```

END OF MASTER SPECIFICATION. Implement and verify; do not merely summarise it.

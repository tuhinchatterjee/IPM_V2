"""The full 123-row signal inventory, Tab 1 Section C of the workbook, and
its cross-reference against the actual classifier/trigger definitions in
`classifiers_v2.py`/`triggers_v2.py`.

Conflict D (see the implementation plan, Section 0): an earlier design
description assumed a clean "105 of 123 currently scored, 18 dropped/merged"
split with an explicit status column. The workbook does not carry that
column — every one of the 123 rows in Tab 1 already states which tab scores
it ("Tab 2", "Tab 3", "Tabs 2 and 3", or "Tab 4b"), and none is marked
dropped. What IS true is that Tab 1 is broader than Tab 2 + Tab 3's 102
explicit rows (35 classifiers + 67 triggers): several Tab 1 signals fold
into ONE combined Tab 2/3 definition (e.g. Tab 1's "Single-source
dependency" and "Supplier substitutability" are one Tab 2 classifier,
"Single-source dependency and substitutability"), and Tab 1's own network
"portfolio" row (#122) describes the Tab 4b Section F portfolio-contagion
view rather than a per-borrower signal at all.

This module does the honest version of that cross-reference: it uses Tab 1's
own `scored_in_workbook` column as the authoritative status label, and
separately attempts to *link* each row to the actual ClassifierDefinition or
TriggerDefinition object it corresponds to. Where no exact key match is
found, `linked_key` is None and `status_detail` records why — the row is not
silently mis-scored, and it is not silently claimed to be scored when this
module cannot show the exact formula that scores it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.early_warning import classifiers_v2, triggers_v2

METHODOLOGY_VERSION = "ews-v2.0.0"


@dataclass(frozen=True)
class SignalInventoryRow:
    code: str
    layer: str
    sub_category: str
    name: str
    what_is_measured: str
    update_frequency: str
    tac_role: str
    scored_in_workbook: str
    key: str


# ---------------------------------------------------------------------------
# The 123 rows, transcribed verbatim from Tab 1 Section C, rows 19-141.
# `sub_category` is a taxonomy/grouping label only (Conflict A) — it carries
# no weight and is not an aggregation node.
# ---------------------------------------------------------------------------

SIGNAL_INVENTORY: tuple[SignalInventoryRow, ...] = (
    SignalInventoryRow(code='1', layer='L1', sub_category='Deposit & cash flow', name='Operating / deposit balance decline', what_is_measured='% fall in 30-day average balance vs trailing 12-month average', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='operating_deposit_balance_decline'),
    SignalInventoryRow(code='2', layer='L1', sub_category='Deposit & cash flow', name='Reduction in account credits (inflows)', what_is_measured='% fall in monthly credit turnover vs 12-month average', update_frequency='Daily / monthly', tac_role='T + A', scored_in_workbook='Tab 3', key='reduction_in_account_credits_inflows'),
    SignalInventoryRow(code='3', layer='L1', sub_category='Turnover & transactions', name='Fall in turnover / transaction volume', what_is_measured='Count and value of transactions vs baseline', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='fall_in_turnover_transaction_volume'),
    SignalInventoryRow(code='4', layer='L1', sub_category='Deposit & cash flow', name='Cash-flow deterioration', what_is_measured='Net inflow over rolling 90 days vs prior 90 days', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='cash_flow_deterioration'),
    SignalInventoryRow(code='5', layer='L1', sub_category='Turnover & transactions', name='Concentration of inflows / outflows', what_is_measured='Herfindahl index of counterparty concentration in flows', update_frequency='Monthly', tac_role='T + A', scored_in_workbook='Tab 3', key='concentration_of_inflows_outflows'),
    SignalInventoryRow(code='6', layer='L1', sub_category='Turnover & transactions', name='Unusual fund movements', what_is_measured='Large atypical transfers vs behavioural profile', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='unusual_fund_movements'),
    SignalInventoryRow(code='7', layer='L1', sub_category='Turnover & transactions', name='Abnormal debit / credit behaviour', what_is_measured="Deviation from the account's learned transaction profile", update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='abnormal_debit_credit_behaviour'),
    SignalInventoryRow(code='8', layer='L1', sub_category='Utilisation & limits', name='Utilisation increase', what_is_measured='Change in drawn / sanctioned limit vs 3-month average', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='utilisation_increase'),
    SignalInventoryRow(code='9', layer='L1', sub_category='Utilisation & limits', name='Sustained high utilisation', what_is_measured='Consecutive days above the configured utilisation threshold', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='sustained_high_utilisation'),
    SignalInventoryRow(code='10', layer='L1', sub_category='Utilisation & limits', name='Excess over limit', what_is_measured='Amount and number of days in excess', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='excess_over_limit'),
    SignalInventoryRow(code='11', layer='L1', sub_category='Utilisation & limits', name='Limit breach frequency', what_is_measured='Count of breaches in trailing 12 months', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='limit_breach_frequency'),
    SignalInventoryRow(code='12', layer='L1', sub_category='Repayment behaviour', name='Repayment delay (1-29 DPD)', what_is_measured='Days past due on any facility', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='repayment_delay_1_29_dpd'),
    SignalInventoryRow(code='13', layer='L1', sub_category='Repayment behaviour', name='Overdue 30+ DPD', what_is_measured='Migration into the 30-89 DPD bucket', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='overdue_30_dpd'),
    SignalInventoryRow(code='14', layer='L1', sub_category='Repayment behaviour', name='Missed instalments', what_is_measured='Count of missed scheduled instalments in 12 months', update_frequency='Monthly', tac_role='T + A', scored_in_workbook='Tab 3', key='missed_instalments'),
    SignalInventoryRow(code='15', layer='L1', sub_category='Repayment behaviour', name='Failed payments / direct debit returns', what_is_measured='Count of returned direct debits or standing orders', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='failed_payments_direct_debit_returns'),
    SignalInventoryRow(code='16', layer='L1', sub_category='Repayment behaviour', name='Returned cheques', what_is_measured='Count and value of cheques returned unpaid', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='returned_cheques'),
    SignalInventoryRow(code='17', layer='L1', sub_category='Account activity', name='Account dormancy / activity decline', what_is_measured='Active days and transaction count vs baseline', update_frequency='Monthly', tac_role='T + A', scored_in_workbook='Tab 3', key='account_dormancy_activity_decline'),
    SignalInventoryRow(code='18', layer='L1', sub_category='Account activity', name='Sudden drop in operating activity', what_is_measured='Step change in the composite activity index', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='sudden_drop_in_operating_activity'),
    SignalInventoryRow(code='19', layer='L1', sub_category='Relationship behaviour', name='Movement of business away from the bank', what_is_measured='Share-of-wallet decline; collections or payroll diverted elsewhere', update_frequency='Monthly', tac_role='T + A', scored_in_workbook='Tab 3', key='movement_of_business_away_from_the_bank'),
    SignalInventoryRow(code='20', layer='L1', sub_category='Relationship behaviour', name='Trade finance activity drop or claim', what_is_measured='LC / LG volume decline, or a guarantee called', update_frequency='Weekly', tac_role='T + A', scored_in_workbook='Tab 3', key='trade_finance_activity_drop_or_claim'),
    SignalInventoryRow(code='21', layer='L2', sub_category='Rating & PD', name='Internal rating (level)', what_is_measured="Current internal grade on the bank's masterscale", update_frequency='Annual / periodic', tac_role='C', scored_in_workbook='Tab 2', key='internal_rating_level'),
    SignalInventoryRow(code='22', layer='L2', sub_category='Rating & PD', name='Rating migration (downgrade event)', what_is_measured='Number of notches downgraded in trailing 12 months', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='rating_migration_downgrade_event'),
    SignalInventoryRow(code='23', layer='L2', sub_category='Rating & PD', name='12-month PD (level)', what_is_measured='Point-in-time or through-the-cycle 12-month PD', update_frequency='Quarterly', tac_role='C', scored_in_workbook='Tab 2', key='12_month_pd_level'),
    SignalInventoryRow(code='24', layer='L2', sub_category='Rating & PD', name='PD movement', what_is_measured='Relative increase in 12-month PD vs prior quarter', update_frequency='Quarterly', tac_role='T + A', scored_in_workbook='Tab 3', key='pd_movement'),
    SignalInventoryRow(code='25', layer='L2', sub_category='Rating & PD', name='Rating headroom to sub-investment grade', what_is_measured='Notches between current grade and the SIG boundary', update_frequency='Quarterly', tac_role='C', scored_in_workbook='Tab 2', key='rating_headroom_to_sub_investment_grade'),
    SignalInventoryRow(code='26', layer='L2', sub_category='IFRS 9', name='IFRS 9 stage (level)', what_is_measured='Stage 1 / 2 / 3 classification', update_frequency='Monthly', tac_role='C', scored_in_workbook='Tab 2', key='ifrs_9_stage_level'),
    SignalInventoryRow(code='27', layer='L2', sub_category='IFRS 9', name='Stage migration (1 to 2, 2 to 3)', what_is_measured='Stage transition event', update_frequency='Monthly', tac_role='T + A', scored_in_workbook='Tab 3', key='stage_migration_1_to_2_2_to_3'),
    SignalInventoryRow(code='28', layer='L2', sub_category='IFRS 9', name='ECL coverage (level)', what_is_measured='ECL as a percentage of EAD', update_frequency='Monthly', tac_role='C', scored_in_workbook='Tab 2', key='ecl_coverage_level'),
    SignalInventoryRow(code='29', layer='L2', sub_category='IFRS 9', name='ECL movement', what_is_measured='Change in ECL coverage vs prior period', update_frequency='Monthly', tac_role='T + A', scored_in_workbook='Tab 3', key='ecl_movement'),
    SignalInventoryRow(code='30', layer='L2', sub_category='IFRS 9', name='Days past due (current status)', what_is_measured='Current DPD bucket', update_frequency='Daily', tac_role='C', scored_in_workbook='Tab 2', key='days_past_due_current_status'),
    SignalInventoryRow(code='31', layer='L2', sub_category='Exposure & limits', name='Sanctioned limit', what_is_measured='Total approved limit across facilities', update_frequency='Periodic', tac_role='C', scored_in_workbook='Tab 2', key='sanctioned_limit'),
    SignalInventoryRow(code='32', layer='L2', sub_category='Exposure & limits', name='Exposure / outstanding balance', what_is_measured='Current EAD', update_frequency='Daily', tac_role='C', scored_in_workbook='Tab 2', key='exposure_outstanding_balance'),
    SignalInventoryRow(code='33', layer='L2', sub_category='Exposure & limits', name='Facility utilisation (12-month average)', what_is_measured='Average drawn / limit', update_frequency='Monthly', tac_role='C', scored_in_workbook='Tab 2', key='facility_utilisation_12_month_average'),
    SignalInventoryRow(code='34', layer='L2', sub_category='Exposure & limits', name='Unsecured share of exposure', what_is_measured='Exposure not covered by eligible collateral', update_frequency='Monthly', tac_role='C', scored_in_workbook='Tab 2', key='unsecured_share_of_exposure'),
    SignalInventoryRow(code='35', layer='L2', sub_category='Exposure & limits', name='Single-name exposure as % of Tier 1', what_is_measured='Concentration against regulatory capital', update_frequency='Monthly', tac_role='C', scored_in_workbook='Tab 2', key='single_name_exposure_as_of_tier_1'),
    SignalInventoryRow(code='36', layer='L2', sub_category='Exposure & limits', name='Group / connected exposure as % of Tier 1', what_is_measured='Consolidated connected-counterparty exposure', update_frequency='Monthly', tac_role='C', scored_in_workbook='Tab 2', key='group_connected_exposure_as_of_tier_1'),
    SignalInventoryRow(code='37', layer='L2', sub_category='Collateral', name='Collateral coverage ratio', what_is_measured='Eligible collateral value / exposure', update_frequency='Quarterly', tac_role='C', scored_in_workbook='Tab 2', key='collateral_coverage_ratio'),
    SignalInventoryRow(code='38', layer='L2', sub_category='Collateral', name='Loan to value (real estate secured)', what_is_measured='Outstanding / current appraised value', update_frequency='Quarterly', tac_role='C', scored_in_workbook='Tab 2', key='loan_to_value_real_estate_secured'),
    SignalInventoryRow(code='39', layer='L2', sub_category='Collateral', name='Collateral value movement', what_is_measured='Change in appraised value since last valuation', update_frequency='Event / annual', tac_role='T + A', scored_in_workbook='Tab 3', key='collateral_value_movement'),
    SignalInventoryRow(code='40', layer='L2', sub_category='Covenants', name='Covenant compliance status', what_is_measured='Pass / breach / waived on each maintenance covenant', update_frequency='Quarterly', tac_role='C', scored_in_workbook='Tab 2', key='covenant_compliance_status'),
    SignalInventoryRow(code='41', layer='L2', sub_category='Covenants', name='Covenant headroom', what_is_measured='Percentage headroom to the tightest covenant', update_frequency='Quarterly', tac_role='C', scored_in_workbook='Tab 2', key='covenant_headroom'),
    SignalInventoryRow(code='42', layer='L2', sub_category='Covenants', name='Covenant breach (event)', what_is_measured='A newly observed breach or waiver request', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='covenant_breach_event'),
    SignalInventoryRow(code='43', layer='L2', sub_category='Financial ratios', name='DSCR', what_is_measured='Cash flow available for debt service / debt service', update_frequency='Annual / semi-annual', tac_role='C', scored_in_workbook='Tab 2', key='dscr'),
    SignalInventoryRow(code='44', layer='L2', sub_category='Financial ratios', name='Interest coverage (EBIT / interest)', what_is_measured='Earnings cover for interest expense', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='interest_coverage_ebit_interest'),
    SignalInventoryRow(code='45', layer='L2', sub_category='Financial ratios', name='Leverage (net debt / EBITDA)', what_is_measured='Net debt divided by EBITDA', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='leverage_net_debt_ebitda'),
    SignalInventoryRow(code='46', layer='L2', sub_category='Financial ratios', name='Gearing (total debt / equity)', what_is_measured='Balance sheet gearing', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='gearing_total_debt_equity'),
    SignalInventoryRow(code='47', layer='L2', sub_category='Financial ratios', name='Current ratio', what_is_measured='Current assets / current liabilities', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='current_ratio'),
    SignalInventoryRow(code='48', layer='L2', sub_category='Financial ratios', name='Quick ratio', what_is_measured='(Current assets less inventory) / current liabilities', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='quick_ratio'),
    SignalInventoryRow(code='49', layer='L2', sub_category='Financial ratios', name='EBITDA margin vs sector median', what_is_measured='Profitability relative to the sector peer group', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='ebitda_margin_vs_sector_median'),
    SignalInventoryRow(code='50', layer='L2', sub_category='Financial ratios', name='Cash conversion cycle', what_is_measured='DSO + DIO less DPO, in days', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='cash_conversion_cycle'),
    SignalInventoryRow(code='51', layer='L2', sub_category='Financial ratios', name='Revenue trend (3-year CAGR)', what_is_measured='Direction and pace of top-line growth', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='revenue_trend_3_year_cagr'),
    SignalInventoryRow(code='52', layer='L2', sub_category='Financial ratios', name='Financial statement deterioration (event)', what_is_measured='Material year-on-year fall in revenue or EBITDA', update_frequency='Annual', tac_role='T + A', scored_in_workbook='Tab 3', key='financial_statement_deterioration_event'),
    SignalInventoryRow(code='53', layer='L2', sub_category='Structural', name='Sector vulnerability grade', what_is_measured='Internal sector risk grade, 1 to 5', update_frequency='Quarterly', tac_role='C', scored_in_workbook='Tab 2', key='sector_vulnerability_grade'),
    SignalInventoryRow(code='54', layer='L2', sub_category='Structural', name='Borrower size / segment', what_is_measured='Large corporate through to micro SME', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='borrower_size_segment'),
    SignalInventoryRow(code='55', layer='L2', sub_category='Structural', name='Financial statement quality', what_is_measured='Auditor identity, opinion type, age of statements', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='financial_statement_quality'),
    SignalInventoryRow(code='56', layer='L2', sub_category='Structural', name='Country / jurisdiction risk', what_is_measured='Sovereign and transfer risk of the operating jurisdiction', update_frequency='Quarterly', tac_role='C', scored_in_workbook='Tab 2', key='country_jurisdiction_risk'),
    SignalInventoryRow(code='57', layer='L2', sub_category='Structural', name='Relationship tenure and history', what_is_measured='Length of relationship and prior restructuring history', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='relationship_tenure_and_history'),
    SignalInventoryRow(code='58', layer='L3', sub_category='Official disclosures', name='Exchange announcement - material event', what_is_measured='Issuer disclosure classified as credit-relevant', update_frequency='Real time', tac_role='T + A', scored_in_workbook='Tab 3', key='exchange_announcement_material_event'),
    SignalInventoryRow(code='59', layer='L3', sub_category='Official disclosures', name='Financial results announcement (adverse)', what_is_measured='Reported loss, margin collapse or covenant commentary', update_frequency='Quarterly', tac_role='T + A', scored_in_workbook='Tab 3', key='financial_results_announcement_adverse'),
    SignalInventoryRow(code='60', layer='L3', sub_category='Official disclosures', name='Regulatory disclosure or filing change', what_is_measured='Late filing, restatement, change in accounting basis', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='regulatory_disclosure_or_filing_change'),
    SignalInventoryRow(code='61', layer='L3', sub_category='Official disclosures', name='Commercial registration status change', what_is_measured='CR suspended, expired, or activity scope changed', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='commercial_registration_status_change'),
    SignalInventoryRow(code='62', layer='L3', sub_category='Official disclosures', name='Auditor change or qualified opinion', what_is_measured='Resignation of auditor, qualification, emphasis of matter', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='auditor_change_or_qualified_opinion'),
    SignalInventoryRow(code='63', layer='L3', sub_category='Legal & distress', name='Bankruptcy or insolvency filing', what_is_measured='Debtor named in a formal insolvency procedure', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='bankruptcy_or_insolvency_filing'),
    SignalInventoryRow(code='64', layer='L3', sub_category='Legal & distress', name='Restructuring / protective settlement', what_is_measured='Formal restructuring procedure commenced', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='restructuring_protective_settlement'),
    SignalInventoryRow(code='65', layer='L3', sub_category='Legal & distress', name='Material litigation', what_is_measured='Claim value material to equity or annual cash flow', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='material_litigation'),
    SignalInventoryRow(code='66', layer='L3', sub_category='Legal & distress', name='Regulatory enforcement action', what_is_measured='Fine, censure, suspension by a competent authority', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='regulatory_enforcement_action'),
    SignalInventoryRow(code='67', layer='L3', sub_category='Legal & distress', name='Sanctions listing or match', what_is_measured='Entity, owner or controller on a sanctions list', update_frequency='Real time', tac_role='T + A (override)', scored_in_workbook='Tab 3', key='sanctions_listing_or_match'),
    SignalInventoryRow(code='68', layer='L3', sub_category='Legal & distress', name='Licence cancellation or suspension', what_is_measured='Loss of an operating licence or permit', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='licence_cancellation_or_suspension'),
    SignalInventoryRow(code='69', layer='L3', sub_category='Ratings & markets', name='External rating downgrade', what_is_measured='Notches downgraded by a recognised agency', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='external_rating_downgrade'),
    SignalInventoryRow(code='70', layer='L3', sub_category='Ratings & markets', name='Outlook change to negative', what_is_measured='Outlook revision by a recognised agency', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='outlook_change_to_negative'),
    SignalInventoryRow(code='71', layer='L3', sub_category='Ratings & markets', name='Credit watch placement', what_is_measured='Placement on watch negative', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='credit_watch_placement'),
    SignalInventoryRow(code='72', layer='L3', sub_category='Ratings & markets', name='Rating withdrawal', what_is_measured='Agency withdraws the rating', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='rating_withdrawal'),
    SignalInventoryRow(code='73', layer='L3', sub_category='Ratings & markets', name='Credit spread widening', what_is_measured='Move in CDS or bond spread vs sector index', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='credit_spread_widening'),
    SignalInventoryRow(code='74', layer='L3', sub_category='Ratings & markets', name='Bond price deterioration', what_is_measured='Fall in traded price of outstanding debt', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='bond_price_deterioration'),
    SignalInventoryRow(code='75', layer='L3', sub_category='Ratings & markets', name='Equity price deterioration', what_is_measured='Fall vs index, beta-adjusted', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='equity_price_deterioration'),
    SignalInventoryRow(code='76', layer='L3', sub_category='Ratings & markets', name='Market capitalisation decline', what_is_measured='Sustained fall in market value of equity', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='market_capitalisation_decline'),
    SignalInventoryRow(code='77', layer='L3', sub_category='Ratings & markets', name='Unusual volatility', what_is_measured='Realised volatility vs its own trailing distribution', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='unusual_volatility'),
    SignalInventoryRow(code='78', layer='L3', sub_category='News & events', name='Contract loss or cancellation', what_is_measured='Value of the lost contract as % of annual revenue', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='contract_loss_or_cancellation'),
    SignalInventoryRow(code='79', layer='L3', sub_category='News & events', name='Project delay', what_is_measured='Delay to a project material to the revenue base', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='project_delay'),
    SignalInventoryRow(code='80', layer='L3', sub_category='News & events', name='Profit warning', what_is_measured='Company-issued guidance downgrade', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='profit_warning'),
    SignalInventoryRow(code='81', layer='L3', sub_category='News & events', name='Fraud allegation', what_is_measured='Credible allegation against the entity or its officers', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='fraud_allegation'),
    SignalInventoryRow(code='82', layer='L3', sub_category='News & events', name='Senior management resignation', what_is_measured='Departure of CEO, CFO or controlling shareholder', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='senior_management_resignation'),
    SignalInventoryRow(code='83', layer='L3', sub_category='News & events', name='Plant or facility closure', what_is_measured='Closure of a material production or trading site', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='plant_or_facility_closure'),
    SignalInventoryRow(code='84', layer='L3', sub_category='News & events', name='Labour disruption', what_is_measured='Strike, mass layoff, wage protection issue', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='labour_disruption'),
    SignalInventoryRow(code='85', layer='L3', sub_category='News & events', name='Cyber incident', what_is_measured='Breach or ransomware affecting operations', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='cyber_incident'),
    SignalInventoryRow(code='86', layer='L3', sub_category='News & events', name='Operational disruption', what_is_measured='Fire, accident, force majeure at a key asset', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='operational_disruption'),
    SignalInventoryRow(code='87', layer='L3', sub_category='News & events', name='Supply-chain disruption', what_is_measured='Interruption to a critical input or logistics route', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='supply_chain_disruption'),
    SignalInventoryRow(code='88', layer='L3', sub_category='News & events', name='Ownership change or M&A event', what_is_measured='Change of control, disposal of a core asset', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='ownership_change_or_m_a_event'),
    SignalInventoryRow(code='89', layer='L3', sub_category='Macro & sector', name='Sector slowdown', what_is_measured='Sector output, PMI or order-book contraction', update_frequency='Monthly', tac_role='C (level) / T (shock)', scored_in_workbook='Tabs 2 and 3', key='sector_slowdown'),
    SignalInventoryRow(code='90', layer='L3', sub_category='Macro & sector', name='Interest-rate shock', what_is_measured='Policy rate or benchmark move beyond a set band', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='interest_rate_shock'),
    SignalInventoryRow(code='91', layer='L3', sub_category='Macro & sector', name='Commodity or oil price shock', what_is_measured='Move in an input or output price the borrower depends on', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='commodity_or_oil_price_shock'),
    SignalInventoryRow(code='92', layer='L3', sub_category='Macro & sector', name='Real-estate price decline', what_is_measured='Fall in the relevant transaction price index', update_frequency='Monthly', tac_role='T + A', scored_in_workbook='Tab 3', key='real_estate_price_decline'),
    SignalInventoryRow(code='93', layer='L3', sub_category='Macro & sector', name='Inflation pressure', what_is_measured='Input cost inflation against pricing power', update_frequency='Monthly', tac_role='C', scored_in_workbook='Tab 2', key='inflation_pressure'),
    SignalInventoryRow(code='94', layer='L3', sub_category='Macro & sector', name='FX movement', what_is_measured='Move against the currency of revenue or debt', update_frequency='Daily', tac_role='T + A', scored_in_workbook='Tab 3', key='fx_movement'),
    SignalInventoryRow(code='95', layer='L3', sub_category='Macro & sector', name='Trade disruption', what_is_measured='Port, customs, tariff or route disruption', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='trade_disruption'),
    SignalInventoryRow(code='96', layer='L3', sub_category='Macro & sector', name='Geopolitical event', what_is_measured='Event affecting a market material to the borrower', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='geopolitical_event'),
    SignalInventoryRow(code='97', layer='L3', sub_category='Macro & sector', name='Demand contraction', what_is_measured='Sector demand indicator falling below trend', update_frequency='Monthly', tac_role='T + A', scored_in_workbook='Tab 3', key='demand_contraction'),
    SignalInventoryRow(code='98', layer='L4', sub_category='Ownership network', name='Parent company deterioration', what_is_measured='Adverse event or downgrade at the parent', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='parent_company_deterioration'),
    SignalInventoryRow(code='99', layer='L4', sub_category='Ownership network', name='Subsidiary deterioration', what_is_measured='Adverse event at a material subsidiary', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='subsidiary_deterioration'),
    SignalInventoryRow(code='100', layer='L4', sub_category='Ownership network', name='Group company deterioration', what_is_measured='Adverse event at a sister company in the group', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='group_company_deterioration'),
    SignalInventoryRow(code='101', layer='L4', sub_category='Ownership network', name='Ownership linkage change', what_is_measured='Change in ultimate beneficial ownership', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='ownership_linkage_change'),
    SignalInventoryRow(code='102', layer='L4', sub_category='Ownership network', name='Common directors or shareholders with a distressed entity', what_is_measured='Shared officers or holders with a defaulted entity', update_frequency='Monthly', tac_role='T + A', scored_in_workbook='Tab 3', key='common_directors_or_shareholders_with_a_distressed_entity'),
    SignalInventoryRow(code='103', layer='L4', sub_category='Credit support', name='Guarantor deterioration', what_is_measured='Downgrade or adverse event at the guarantor', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='guarantor_deterioration'),
    SignalInventoryRow(code='104', layer='L4', sub_category='Credit support', name='Guarantor capacity (level)', what_is_measured='Guarantor rating and net worth relative to the guarantee', update_frequency='Quarterly', tac_role='C', scored_in_workbook='Tab 2', key='guarantor_capacity_level'),
    SignalInventoryRow(code='105', layer='L4', sub_category='Commercial dependency', name='Key supplier distress', what_is_measured='Distress at a supplier the borrower depends on', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='key_supplier_distress'),
    SignalInventoryRow(code='106', layer='L4', sub_category='Commercial dependency', name='Key customer distress', what_is_measured='Distress at a customer material to the revenue base', update_frequency='Event', tac_role='T + A', scored_in_workbook='Tab 3', key='key_customer_distress'),
    SignalInventoryRow(code='107', layer='L4', sub_category='Commercial dependency', name='Buyer concentration (level)', what_is_measured='Top-three customers as % of revenue', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='buyer_concentration_level'),
    SignalInventoryRow(code='108', layer='L4', sub_category='Commercial dependency', name='Project dependency (level)', what_is_measured='Revenue concentration in a single project or contract', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='project_dependency_level'),
    SignalInventoryRow(code='109', layer='L4', sub_category='Exposure network', name='Related-party exposure (level)', what_is_measured='Related-party receivables or exposure share', update_frequency='Monthly', tac_role='C', scored_in_workbook='Tab 2', key='related_party_exposure_level'),
    SignalInventoryRow(code='110', layer='L4', sub_category='Upstream network', name='Supplier concentration', what_is_measured='Top three suppliers as % of input cost', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='supplier_concentration'),
    SignalInventoryRow(code='111', layer='L4', sub_category='Upstream network', name='Single-source dependency', what_is_measured='Whether a critical input has no qualified alternate', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='single_source_dependency'),
    SignalInventoryRow(code='112', layer='L4', sub_category='Upstream network', name='Supplier substitutability', what_is_measured='How readily a failing supplier can be replaced', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='supplier_substitutability'),
    SignalInventoryRow(code='113', layer='L4', sub_category='Upstream network', name='Switching time to an alternative supplier', what_is_measured='Months to qualify and onboard a replacement', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='switching_time_to_an_alternative_supplier'),
    SignalInventoryRow(code='114', layer='L4', sub_category='Upstream network', name='Tier-2 supplier distress', what_is_measured="Distress at a supplier of the borrower's supplier", update_frequency='Event', tac_role='T + A (2 hops)', scored_in_workbook='Tab 4b', key='tier_2_supplier_distress'),
    SignalInventoryRow(code='115', layer='L4', sub_category='Upstream network', name='Input price pass-through ability', what_is_measured='Share of an input cost rise the borrower can pass on', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='input_price_pass_through_ability'),
    SignalInventoryRow(code='116', layer='L4', sub_category='Upstream network', name='Logistics route dependency', what_is_measured='Reliance on a single port, corridor or carrier', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='logistics_route_dependency'),
    SignalInventoryRow(code='117', layer='L4', sub_category='Downstream network', name='Receivable concentration by counterparty', what_is_measured='Largest single debtor as % of trade receivables', update_frequency='Monthly', tac_role='C', scored_in_workbook='Tab 2', key='receivable_concentration_by_counterparty'),
    SignalInventoryRow(code='118', layer='L4', sub_category='Downstream network', name='DSO deterioration against a named counterparty', what_is_measured='Rise in days sales outstanding for one debtor', update_frequency='Monthly', tac_role='T + A', scored_in_workbook='Tab 3', key='dso_deterioration_against_a_named_counterparty'),
    SignalInventoryRow(code='119', layer='L4', sub_category='Downstream network', name='Receivable ageing at a distressed customer', what_is_measured='Value and ageing of receivables owed by a distressed debtor', update_frequency='Monthly', tac_role='T + A', scored_in_workbook='Tab 3', key='receivable_ageing_at_a_distressed_customer'),
    SignalInventoryRow(code='120', layer='L4', sub_category='Downstream network', name='Customer-of-customer distress', what_is_measured="Distress at the offtaker of the borrower's key customer", update_frequency='Event', tac_role='T + A (2 hops)', scored_in_workbook='Tab 4b', key='customer_of_customer_distress'),
    SignalInventoryRow(code='121', layer='L4', sub_category='Downstream network', name='Offtake or contract termination rights', what_is_measured='Whether a key customer can exit without penalty', update_frequency='Annual', tac_role='C', scored_in_workbook='Tab 2', key='offtake_or_contract_termination_rights'),
    SignalInventoryRow(code='122', layer='L4', sub_category='Exposure network', name="Shared-counterparty exposure in the bank's portfolio", what_is_measured='Other borrowers depending on the same counterparty', update_frequency='Monthly', tac_role='C (portfolio)', scored_in_workbook='Tab 4b', key='shared_counterparty_exposure_in_the_banks_portfolio'),
    SignalInventoryRow(code='123', layer='L4', sub_category='Network governance', name='Relationship edge confidence', what_is_measured='How well each modelled relationship is verified', update_frequency='Monthly', tac_role='C', scored_in_workbook='Tab 2', key='relationship_edge_confidence'),
)

assert len(SIGNAL_INVENTORY) == 123


# ---------------------------------------------------------------------------
# The six accelerator dimensions — NOT part of the 123-row inventory (Tab 1
# numbers them A1-A6 separately). They are not signals; they scale a trigger.
# ---------------------------------------------------------------------------

ACCELERATOR_DIMENSIONS: tuple[dict[str, str], ...] = (
    {"code": "A1", "name": "Magnitude", "what_it_measures": "How large the deterioration is relative to the customer's own baseline distribution"},
    {"code": "A2", "name": "Velocity", "what_it_measures": "How quickly the deterioration occurred"},
    {"code": "A3", "name": "Persistence", "what_it_measures": "Whether it is a single observation or a continuing condition"},
    {"code": "A4", "name": "Recency / decay", "what_it_measures": "How recent the signal is; older signals decay towards zero weight"},
    {"code": "A5", "name": "Repetition", "what_it_measures": "How many times the same trigger has fired in the trailing 12 months"},
    {"code": "A6", "name": "Corroboration", "what_it_measures": "How many independent signals or sources are deteriorating in the same window"},
)


# ---------------------------------------------------------------------------
# Cross-reference: Tab 1's own status column is authoritative; `linked_key`
# additionally records whether this exact row maps 1:1 onto a transcribed
# Tab 2/3 definition, so the gap (Conflict D) is visible rather than assumed.
# ---------------------------------------------------------------------------

_STATUS_FROM_WORKBOOK: dict[str, str] = {
    "Tab 2": "CLASSIFIER",
    "Tab 3": "TRIGGER",
    "Tabs 2 and 3": "DUAL",
    "Tab 4b": "NETWORK_PROPAGATED",
}


@dataclass(frozen=True)
class ResolvedSignal:
    row: SignalInventoryRow
    scoring_status: str
    linked_classifier_key: str | None
    linked_trigger_key: str | None
    grouped_with: str | None  # set when this row is folded into another row's definition


#: Rows Tab 1 lists individually that Tab 2 has already folded into ONE
#: combined classifier definition — found by direct inspection of Tab 2 row
#: 32 ("Single-source dependency and substitutability"), which covers both
#: Tab 1 #111 and #112.
_KNOWN_GROUPINGS: dict[str, str] = {
    "single_source_dependency": "single_source_dependency_and_substitutability",
    "supplier_substitutability": "single_source_dependency_and_substitutability",
}

import re as _re

#: Suffixes Tab 1 adds that Tab 2/3 do not carry on the matching row —
#: stripping them is a normalisation step, not a guess: e.g. Tab 1's
#: "IFRS 9 stage (level)" and Tab 2's "IFRS 9 stage" are the same row.
_STRIP_SUFFIXES = (
    " (level)", " (event)", " (inflows)", " (downgrade event)",
    " - material event", " (1-29 dpd)", " 30+ dpd", " (current status)",
)


def _normalise(name: str) -> str:
    n = name.lower()
    for suf in _STRIP_SUFFIXES:
        n = n.replace(suf, "")
    n = _re.sub(r"[^a-z0-9]+", " ", n).strip()
    return n


_STOPWORDS = frozenset({"a", "an", "the", "or", "and", "of", "for", "to", "at",
                         "in", "on", "with", "against"})


def _tokens(name: str) -> frozenset[str]:
    return frozenset(w for w in _normalise(name).split() if w not in _STOPWORDS)


def _best_match(name: str, candidates: dict[str, Any]) -> str | None:
    """Three passes, each stricter than a guess: (1) normalised exact match,
    (2) containment either direction, (3) token-overlap (Jaccard >= 0.6) to
    catch word-order variants such as Tab 1's "direct debit returns" vs
    Tab 3's "returned direct debits". No fuzzy string distance — every match
    is one a person re-reading both names would accept as the same row."""
    target = _normalise(name)
    by_norm = {_normalise(c.name): key for key, c in candidates.items()}
    if target in by_norm:
        return by_norm[target]
    for norm_name, key in by_norm.items():
        if target in norm_name or norm_name in target:
            return key
    target_tokens = _tokens(name)
    best_key, best_score = None, 0.0
    for key, c in candidates.items():
        cand_tokens = _tokens(c.name)
        if not target_tokens or not cand_tokens:
            continue
        overlap = len(target_tokens & cand_tokens) / len(target_tokens | cand_tokens)
        if overlap > best_score:
            best_key, best_score = key, overlap
    return best_key if best_score >= 0.6 else None


def resolve_signal(row: SignalInventoryRow) -> ResolvedSignal:
    status = _STATUS_FROM_WORKBOOK.get(row.scored_in_workbook, "UNKNOWN")
    linked_classifier: str | None = None
    linked_trigger: str | None = None
    grouped_with: str | None = None

    if status in ("CLASSIFIER", "DUAL"):
        linked_classifier = (row.key if row.key in classifiers_v2.BY_KEY
                              else _best_match(row.name, classifiers_v2.BY_KEY))
        if linked_classifier is None:
            grouped_with = _KNOWN_GROUPINGS.get(row.key)
            if grouped_with and grouped_with in classifiers_v2.BY_KEY:
                linked_classifier = grouped_with
    if status in ("TRIGGER", "DUAL", "NETWORK_PROPAGATED"):
        linked_trigger = (row.key if row.key in triggers_v2.BY_KEY
                           else _best_match(row.name, triggers_v2.BY_KEY))

    return ResolvedSignal(
        row=row, scoring_status=status,
        linked_classifier_key=linked_classifier, linked_trigger_key=linked_trigger,
        grouped_with=grouped_with,
    )


def resolve_all() -> list[ResolvedSignal]:
    return [resolve_signal(r) for r in SIGNAL_INVENTORY]


def status_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in resolve_all():
        counts[r.scoring_status] = counts.get(r.scoring_status, 0) + 1
    return counts


def unresolved_signals() -> list[ResolvedSignal]:
    """Rows whose declared status implies a scoring definition this module
    cannot find an exact or known-grouped match for — the concrete, bounded
    Conflict D follow-up, not silently assumed away."""
    out = []
    for r in resolve_all():
        needs_classifier = r.scoring_status in ("CLASSIFIER", "DUAL") and r.linked_classifier_key is None
        needs_trigger = r.scoring_status in ("TRIGGER", "DUAL") and r.linked_trigger_key is None
        needs_network = r.scoring_status == "NETWORK_PROPAGATED"  # scored via network.py, not a static row
        if (needs_classifier or needs_trigger) and not needs_network:
            out.append(r)
    return out


def describe() -> dict[str, Any]:
    resolved = resolve_all()
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "signal_count": len(SIGNAL_INVENTORY),
        "accelerator_dimension_count": len(ACCELERATOR_DIMENSIONS),
        "status_counts": status_counts(),
        "unresolved_count": len(unresolved_signals()),
        "unresolved_keys": [r.row.key for r in unresolved_signals()],
    }

"""The full 123-row signal inventory (Tab 01 of the corrected
CreditProbe EWS Framework V2 workbook — 15-sheet edition: 00. Read Me
through 14. Sources and Notes), and its cross-reference against the actual
23-classifier / 67-trigger definitions in `classifiers_v2.py` /
`triggers_v2.py`.

Tab 01 carries its own literal scoring-status column (unlike the earlier,
incorrect workbook version this module previously reconciled against, which
had no such column and required guessing from which tab scored a row). That
column is authoritative and is reproduced verbatim as `status_raw` on every
row, then mechanically parsed into one of five states:

    SCORED    — one of the 105 rows the workbook counts as scored
    MERGED    — folded into another classifier/sub-category (`status_detail`
                names the target, verbatim from the workbook)
    DROPPED   — removed for collinearity or circularity (`status_detail`
                gives the workbook's own reason)
    REPLACED  — an absolute-currency variable superseded by a ratio
    MOVED     — relocated to another tab (Tab 05's network edge attributes)

Summing these five states gives 123; SCORED alone gives 105; the other four
sum to 18 — reproducing the workbook's own Tab 01 summary block exactly
(`assert`ed below, not merely claimed).

Linking every SCORED row to its classifier/trigger definition
---------------------------------------------------------------
105 SCORED rows map onto only 90 definitions (23 classifiers + 67 triggers),
because several rows describe one signal from two angles that the workbook
itself scores once (e.g. #12 "Repayment delay (1-29 DPD)" and #13 "Overdue
30+ DPD" are both read off the single `repayment_delay` trigger's severity
bands, which already span 1-89 days). This module resolves the mapping in
two passes: first a deterministic name match (exact, then containment, then
token-overlap) against the classifier/trigger tables — auditable, not fuzzy
string distance — then a small, explicit, hand-reviewed override table for
the collapses and genuine cross-references a name match cannot see (e.g.
#70/#71/#72, "Outlook change to negative" / "Credit watch placement" /
"Rating withdrawal", are three angles on the one `outlook_or_watch_action`
trigger, whose own five severity bands literally name all three).

A handful of SCORED rows (#93, #109, #115, #116, #121) have no classifier or
trigger definition anywhere in Tabs 03/04 at all — the workbook's own 105
"scored" count is, on inspection, slightly broader than what it actually
bands. These are disclosed as residuals with a stated reason, never silently
linked to the nearest plausible classifier. Two triggers (`logistics_route_disruption`
carried under `L4.1-66`... — see TRIGGER_ONLY_NO_INVENTORY_ROW) exist in Tab 04
with no distinct Tab 01 companion row at all; that is equally disclosed, not
treated as a defect requiring an inventory row to be invented.

Row #122 ("Shared-counterparty exposure in the bank's portfolio") is the
Tab 4b Section F portfolio-contagion view, not a per-borrower classifier or
trigger — noted, not force-linked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.early_warning import classifiers_v2, triggers_v2

METHODOLOGY_VERSION = "ews-v2.1.0"

SCORED = "SCORED"
MERGED = "MERGED"
DROPPED = "DROPPED"
REPLACED = "REPLACED"
MOVED = "MOVED"


@dataclass(frozen=True)
class SignalInventoryRow:
    num: int
    layer: str
    sub_category: str
    code: str
    name: str
    what_is_measured: str
    update_frequency: str
    tac_role: str
    source_system: str
    status_raw: str
    status: str
    status_detail: str


# ---------------------------------------------------------------------------
# The 123 rows, transcribed verbatim from Tab 01 Section "SIGNALS" (rows
# 5-127 of the sheet). `sub_category` is Tab 01's own descriptive grouping
# label; `code` is Tab 01's own roll-up code (L1.1 etc.) used for aggregation
# in Tabs 03/04/06/07 — the two can group signals slightly differently (e.g.
# Tab 01 splits "Deposit & cash flow" and "Turnover & transactions" as
# separate descriptive labels that both roll up under code L1.1), which is a
# genuine, harmless difference between a UI taxonomy and an aggregation key,
# not an error.
# ---------------------------------------------------------------------------

SIGNAL_INVENTORY: tuple[SignalInventoryRow, ...] = (
    SignalInventoryRow(
        num=1, layer='L1', sub_category='Deposit & cash flow', code='L1.1',
        name='Operating / deposit balance decline', what_is_measured='% fall in 30-day average balance vs trailing 12-month average',
        update_frequency='Daily', tac_role='T + A',
        source_system='Core banking - current account ledger; payments hub',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=2, layer='L1', sub_category='Deposit & cash flow', code='L1.1',
        name='Reduction in account credits (inflows)', what_is_measured='% fall in monthly credit turnover vs 12-month average',
        update_frequency='Daily / monthly', tac_role='T + A',
        source_system='Core banking - current account ledger; payments hub',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=3, layer='L1', sub_category='Turnover & transactions', code='L1.1',
        name='Fall in turnover / transaction volume', what_is_measured='Count and value of transactions vs baseline',
        update_frequency='Daily', tac_role='T + A',
        source_system='Core banking - current account ledger; payments hub',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=4, layer='L1', sub_category='Deposit & cash flow', code='L1.1',
        name='Cash-flow deterioration', what_is_measured='Net inflow over rolling 90 days vs prior 90 days',
        update_frequency='Daily', tac_role='T + A',
        source_system='Core banking - current account ledger; payments hub',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=5, layer='L1', sub_category='Turnover & transactions', code='L1.1',
        name='Concentration of inflows / outflows', what_is_measured='Herfindahl index of counterparty concentration in flows',
        update_frequency='Monthly', tac_role='T + A',
        source_system='Core banking - current account ledger; payments hub',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=6, layer='L1', sub_category='Turnover & transactions', code='L1.1',
        name='Unusual fund movements', what_is_measured='Large atypical transfers vs behavioural profile',
        update_frequency='Daily', tac_role='T + A',
        source_system='Core banking - current account ledger; payments hub',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=7, layer='L1', sub_category='Turnover & transactions', code='L1.1',
        name='Abnormal debit / credit behaviour', what_is_measured='Deviation from the account\'s learned transaction profile',
        update_frequency='Daily', tac_role='T + A',
        source_system='Core banking - current account ledger; payments hub',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=8, layer='L1', sub_category='Utilisation & limits', code='L1.2',
        name='Utilisation increase', what_is_measured='Change in drawn / sanctioned limit vs 3-month average',
        update_frequency='Daily', tac_role='T + A',
        source_system='Limits and exposure system; core banking',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=9, layer='L1', sub_category='Utilisation & limits', code='L1.2',
        name='Sustained high utilisation', what_is_measured='Consecutive days above the configured utilisation threshold',
        update_frequency='Daily', tac_role='T + A',
        source_system='Limits and exposure system; core banking',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=10, layer='L1', sub_category='Utilisation & limits', code='L1.2',
        name='Excess over limit', what_is_measured='Amount and number of days in excess',
        update_frequency='Daily', tac_role='T + A',
        source_system='Limits and exposure system; core banking',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=11, layer='L1', sub_category='Utilisation & limits', code='L1.2',
        name='Limit breach frequency', what_is_measured='Count of breaches in trailing 12 months',
        update_frequency='Daily', tac_role='T + A',
        source_system='Limits and exposure system; core banking',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=12, layer='L1', sub_category='Repayment behaviour', code='L1.3',
        name='Repayment delay (1-29 DPD)', what_is_measured='Days past due on any facility',
        update_frequency='Daily', tac_role='T + A',
        source_system='Loan servicing and collections; cheque clearing',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=13, layer='L1', sub_category='Repayment behaviour', code='L1.3',
        name='Overdue 30+ DPD', what_is_measured='Migration into the 30-89 DPD bucket',
        update_frequency='Daily', tac_role='T + A',
        source_system='Loan servicing and collections; cheque clearing',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=14, layer='L1', sub_category='Repayment behaviour', code='L1.3',
        name='Missed instalments', what_is_measured='Count of missed scheduled instalments in 12 months',
        update_frequency='Monthly', tac_role='T + A',
        source_system='Loan servicing and collections; cheque clearing',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=15, layer='L1', sub_category='Repayment behaviour', code='L1.3',
        name='Failed payments / direct debit returns', what_is_measured='Count of returned direct debits or standing orders',
        update_frequency='Daily', tac_role='T + A',
        source_system='Loan servicing and collections; cheque clearing',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=16, layer='L1', sub_category='Repayment behaviour', code='L1.3',
        name='Returned cheques', what_is_measured='Count and value of cheques returned unpaid',
        update_frequency='Daily', tac_role='T + A',
        source_system='Loan servicing and collections; cheque clearing',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=17, layer='L1', sub_category='Account activity', code='L1.4',
        name='Account dormancy / activity decline', what_is_measured='Active days and transaction count vs baseline',
        update_frequency='Monthly', tac_role='T + A',
        source_system='Core banking; CRM; trade finance system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=18, layer='L1', sub_category='Account activity', code='L1.4',
        name='Sudden drop in operating activity', what_is_measured='Step change in the composite activity index',
        update_frequency='Daily', tac_role='T + A',
        source_system='Core banking; CRM; trade finance system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=19, layer='L1', sub_category='Relationship behaviour', code='L1.4',
        name='Movement of business away from the bank', what_is_measured='Share-of-wallet decline; collections or payroll diverted elsewhere',
        update_frequency='Monthly', tac_role='T + A',
        source_system='Core banking; CRM; trade finance system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=20, layer='L1', sub_category='Relationship behaviour', code='L1.4',
        name='Trade finance activity drop or claim', what_is_measured='LC / LG volume decline, or a guarantee called',
        update_frequency='Weekly', tac_role='T + A',
        source_system='Core banking; CRM; trade finance system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=21, layer='L2', sub_category='Rating & PD', code='L2.1',
        name='Internal rating (level)', what_is_measured='Current internal grade on the bank\'s masterscale',
        update_frequency='Annual / periodic', tac_role='C',
        source_system='Rating engine; IFRS 9 ECL engine; loan servicing',
        status_raw='Merged into L2.1 - same construct as PD', status='MERGED', status_detail='L2.1 - same construct as PD',
    ),
    SignalInventoryRow(
        num=22, layer='L2', sub_category='Rating & PD', code='L2.T1',
        name='Rating migration (downgrade event)', what_is_measured='Number of notches downgraded in trailing 12 months',
        update_frequency='Event', tac_role='T + A',
        source_system='Rating engine; IFRS 9 ECL engine',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=23, layer='L2', sub_category='Rating & PD', code='L2.1',
        name='12-month PD (level)', what_is_measured='Point-in-time or through-the-cycle 12-month PD',
        update_frequency='Quarterly', tac_role='C',
        source_system='Rating engine; IFRS 9 ECL engine; loan servicing',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=24, layer='L2', sub_category='Rating & PD', code='L2.T1',
        name='PD movement', what_is_measured='Relative increase in 12-month PD vs prior quarter',
        update_frequency='Quarterly', tac_role='T + A',
        source_system='Rating engine; IFRS 9 ECL engine',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=25, layer='L2', sub_category='Rating & PD', code='L2.1',
        name='Rating headroom to sub-investment grade', what_is_measured='Notches between current grade and the SIG boundary',
        update_frequency='Quarterly', tac_role='C',
        source_system='Rating engine; IFRS 9 ECL engine; loan servicing',
        status_raw='Dropped - monotone transform of rating', status='DROPPED', status_detail='monotone transform of rating',
    ),
    SignalInventoryRow(
        num=26, layer='L2', sub_category='IFRS 9', code='L2.1',
        name='IFRS 9 stage (level)', what_is_measured='Stage 1 / 2 / 3 classification',
        update_frequency='Monthly', tac_role='C',
        source_system='Rating engine; IFRS 9 ECL engine; loan servicing',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=27, layer='L2', sub_category='IFRS 9', code='L2.T1',
        name='Stage migration (1 to 2, 2 to 3)', what_is_measured='Stage transition event',
        update_frequency='Monthly', tac_role='T + A',
        source_system='Rating engine; IFRS 9 ECL engine',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=28, layer='L2', sub_category='IFRS 9', code='L2.1',
        name='ECL coverage (level)', what_is_measured='ECL as a percentage of EAD',
        update_frequency='Monthly', tac_role='C',
        source_system='Rating engine; IFRS 9 ECL engine; loan servicing',
        status_raw='Dropped - deterministic function of PD, LGD and EAD', status='DROPPED', status_detail='deterministic function of PD, LGD and EAD',
    ),
    SignalInventoryRow(
        num=29, layer='L2', sub_category='IFRS 9', code='L2.T1',
        name='ECL movement', what_is_measured='Change in ECL coverage vs prior period',
        update_frequency='Monthly', tac_role='T + A',
        source_system='Rating engine; IFRS 9 ECL engine',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=30, layer='L2', sub_category='IFRS 9', code='L2.1',
        name='Days past due (current status)', what_is_measured='Current DPD bucket',
        update_frequency='Daily', tac_role='C',
        source_system='Rating engine; IFRS 9 ECL engine; loan servicing',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=31, layer='L2', sub_category='Exposure & limits', code='L2.6',
        name='Facility utilisation (drawn / limit)', what_is_measured='Drawn balance as a percentage of the sanctioned limit',
        update_frequency='Periodic', tac_role='C',
        source_system='Limits and exposure system; capital reporting; credit bureau (SIMAH)',
        status_raw='Replaced - absolute amount, not a ratio', status='REPLACED', status_detail='absolute amount, not a ratio',
    ),
    SignalInventoryRow(
        num=32, layer='L2', sub_category='Exposure & limits', code='L2.6',
        name='Bank share of the borrower\'s total debt', what_is_measured='Bank exposure as a percentage of the obligor\'s total external debt (bureau sourced)',
        update_frequency='Daily', tac_role='C',
        source_system='Limits and exposure system; capital reporting; credit bureau (SIMAH)',
        status_raw='Replaced - absolute amount, not a ratio', status='REPLACED', status_detail='absolute amount, not a ratio',
    ),
    SignalInventoryRow(
        num=33, layer='L2', sub_category='Exposure & limits', code='L2.6',
        name='Facility utilisation (12-month average)', what_is_measured='Average drawn / limit',
        update_frequency='Monthly', tac_role='C',
        source_system='Limits and exposure system; capital reporting; credit bureau (SIMAH)',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=34, layer='L2', sub_category='Exposure & limits', code='L2.6',
        name='Unsecured share of exposure', what_is_measured='Exposure not covered by eligible collateral',
        update_frequency='Monthly', tac_role='C',
        source_system='Limits and exposure system; capital reporting; credit bureau (SIMAH)',
        status_raw='Dropped - algebraic complement of collateral coverage', status='DROPPED', status_detail='algebraic complement of collateral coverage',
    ),
    SignalInventoryRow(
        num=35, layer='L2', sub_category='Exposure & limits', code='L2.6',
        name='Single-name exposure as % of Tier 1', what_is_measured='Concentration against regulatory capital',
        update_frequency='Monthly', tac_role='C',
        source_system='Limits and exposure system; capital reporting; credit bureau (SIMAH)',
        status_raw='Merged into connected group exposure', status='MERGED', status_detail='connected group exposure',
    ),
    SignalInventoryRow(
        num=36, layer='L2', sub_category='Exposure & limits', code='L2.6',
        name='Group / connected exposure as % of Tier 1', what_is_measured='Consolidated connected-counterparty exposure',
        update_frequency='Monthly', tac_role='C',
        source_system='Limits and exposure system; capital reporting; credit bureau (SIMAH)',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=37, layer='L2', sub_category='Collateral', code='L2.5',
        name='Collateral coverage ratio', what_is_measured='Eligible collateral value / exposure',
        update_frequency='Quarterly', tac_role='C',
        source_system='Collateral management system; covenant monitoring',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=38, layer='L2', sub_category='Collateral', code='L2.5',
        name='Loan to value (real estate secured)', what_is_measured='Outstanding / current appraised value',
        update_frequency='Quarterly', tac_role='C',
        source_system='Collateral management system; covenant monitoring',
        status_raw='Merged into L2.5 - alternative to collateral coverage, not additive', status='MERGED', status_detail='L2.5 - alternative to collateral coverage, not additive',
    ),
    SignalInventoryRow(
        num=39, layer='L2', sub_category='Collateral', code='L2.T2',
        name='Collateral value movement', what_is_measured='Change in appraised value since last valuation',
        update_frequency='Event / annual', tac_role='T + A',
        source_system='Covenant monitoring; collateral management system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=40, layer='L2', sub_category='Covenants', code='L2.5',
        name='Covenant compliance status', what_is_measured='Pass / breach / waived on each maintenance covenant',
        update_frequency='Quarterly', tac_role='C',
        source_system='Collateral management system; covenant monitoring',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=41, layer='L2', sub_category='Covenants', code='L2.5',
        name='Covenant headroom', what_is_measured='Percentage headroom to the tightest covenant',
        update_frequency='Quarterly', tac_role='C',
        source_system='Collateral management system; covenant monitoring',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=42, layer='L2', sub_category='Covenants', code='L2.T2',
        name='Covenant breach (event)', what_is_measured='A newly observed breach or waiver request',
        update_frequency='Event', tac_role='T + A',
        source_system='Covenant monitoring; collateral management system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=43, layer='L2', sub_category='Financial ratios', code='L2.2',
        name='DSCR', what_is_measured='Cash flow available for debt service / debt service',
        update_frequency='Annual / semi-annual', tac_role='C',
        source_system='Financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=44, layer='L2', sub_category='Financial ratios', code='L2.2',
        name='Interest coverage (EBIT / interest)', what_is_measured='Earnings cover for interest expense',
        update_frequency='Annual', tac_role='C',
        source_system='Financial spreading system',
        status_raw='Merged into L2.2 - subsumed by DSCR', status='MERGED', status_detail='L2.2 - subsumed by DSCR',
    ),
    SignalInventoryRow(
        num=45, layer='L2', sub_category='Financial ratios', code='L2.2',
        name='Leverage (net debt / EBITDA)', what_is_measured='Net debt divided by EBITDA',
        update_frequency='Annual', tac_role='C',
        source_system='Financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=46, layer='L2', sub_category='Financial ratios', code='L2.2',
        name='Gearing (total debt / equity)', what_is_measured='Balance sheet gearing',
        update_frequency='Annual', tac_role='C',
        source_system='Financial spreading system',
        status_raw='Dropped - negative equity retained as an override', status='DROPPED', status_detail='negative equity retained as an override',
    ),
    SignalInventoryRow(
        num=47, layer='L2', sub_category='Financial ratios', code='L2.3',
        name='Current ratio', what_is_measured='Current assets / current liabilities',
        update_frequency='Annual', tac_role='C',
        source_system='Financial spreading system',
        status_raw='Dropped - about 0.9 correlated with quick ratio', status='DROPPED', status_detail='about 0.9 correlated with quick ratio',
    ),
    SignalInventoryRow(
        num=48, layer='L2', sub_category='Financial ratios', code='L2.3',
        name='Quick ratio', what_is_measured='(Current assets less inventory) / current liabilities',
        update_frequency='Annual', tac_role='C',
        source_system='Financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=49, layer='L2', sub_category='Financial ratios', code='L2.4',
        name='EBITDA margin vs sector median', what_is_measured='Profitability relative to the sector peer group',
        update_frequency='Annual', tac_role='C',
        source_system='Financial spreading system; sector benchmark set',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=50, layer='L2', sub_category='Financial ratios', code='L2.3',
        name='Cash conversion cycle', what_is_measured='DSO + DIO less DPO, in days',
        update_frequency='Annual', tac_role='C',
        source_system='Financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=51, layer='L2', sub_category='Financial ratios', code='L2.4',
        name='Revenue trend (3-year CAGR)', what_is_measured='Direction and pace of top-line growth',
        update_frequency='Annual', tac_role='C',
        source_system='Financial spreading system; sector benchmark set',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=52, layer='L2', sub_category='Financial ratios', code='L2.T1',
        name='Financial statement deterioration (event)', what_is_measured='Material year-on-year fall in revenue or EBITDA',
        update_frequency='Annual', tac_role='T + A',
        source_system='Rating engine; IFRS 9 ECL engine',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=53, layer='L2', sub_category='Structural', code='L2.7',
        name='Sector vulnerability grade', what_is_measured='Internal sector risk grade, 1 to 5',
        update_frequency='Quarterly', tac_role='C',
        source_system='CRM and credit file; sector research; rating engine',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=54, layer='L2', sub_category='Structural', code='L2.7',
        name='Borrower size / segment', what_is_measured='Large corporate through to micro SME',
        update_frequency='Annual', tac_role='C',
        source_system='CRM and credit file; sector research; rating engine',
        status_raw='Merged into obligor profile', status='MERGED', status_detail='obligor profile',
    ),
    SignalInventoryRow(
        num=55, layer='L2', sub_category='Structural', code='L2.7',
        name='Financial statement quality', what_is_measured='Auditor identity, opinion type, age of statements',
        update_frequency='Annual', tac_role='C',
        source_system='CRM and credit file; sector research; rating engine',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=56, layer='L2', sub_category='Structural', code='L2.7',
        name='Country / jurisdiction risk', what_is_measured='Sovereign and transfer risk of the operating jurisdiction',
        update_frequency='Quarterly', tac_role='C',
        source_system='CRM and credit file; sector research; rating engine',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=57, layer='L2', sub_category='Structural', code='L2.7',
        name='Relationship tenure and history', what_is_measured='Length of relationship and prior restructuring history',
        update_frequency='Annual', tac_role='C',
        source_system='CRM and credit file; sector research; rating engine',
        status_raw='Merged into obligor profile', status='MERGED', status_detail='obligor profile',
    ),
    SignalInventoryRow(
        num=58, layer='L3', sub_category='Official disclosures', code='L3.1',
        name='Exchange announcement - material event', what_is_measured='Issuer disclosure classified as credit-relevant',
        update_frequency='Real time', tac_role='T + A',
        source_system='External intelligence layer - official disclosure connectors',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=59, layer='L3', sub_category='Official disclosures', code='L3.1',
        name='Financial results announcement (adverse)', what_is_measured='Reported loss, margin collapse or covenant commentary',
        update_frequency='Quarterly', tac_role='T + A',
        source_system='External intelligence layer - official disclosure connectors',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=60, layer='L3', sub_category='Official disclosures', code='L3.1',
        name='Regulatory disclosure or filing change', what_is_measured='Late filing, restatement, change in accounting basis',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - official disclosure connectors',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=61, layer='L3', sub_category='Official disclosures', code='L3.1',
        name='Commercial registration status change', what_is_measured='CR suspended, expired, or activity scope changed',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - official disclosure connectors',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=62, layer='L3', sub_category='Official disclosures', code='L3.1',
        name='Auditor change or qualified opinion', what_is_measured='Resignation of auditor, qualification, emphasis of matter',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - official disclosure connectors',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=63, layer='L3', sub_category='Legal & distress', code='L3.2',
        name='Bankruptcy or insolvency filing', what_is_measured='Debtor named in a formal insolvency procedure',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - legal, insolvency and sanctions connectors',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=64, layer='L3', sub_category='Legal & distress', code='L3.2',
        name='Restructuring / protective settlement', what_is_measured='Formal restructuring procedure commenced',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - legal, insolvency and sanctions connectors',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=65, layer='L3', sub_category='Legal & distress', code='L3.2',
        name='Material litigation', what_is_measured='Claim value material to equity or annual cash flow',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - legal, insolvency and sanctions connectors',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=66, layer='L3', sub_category='Legal & distress', code='L3.2',
        name='Regulatory enforcement action', what_is_measured='Fine, censure, suspension by a competent authority',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - legal, insolvency and sanctions connectors',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=67, layer='L3', sub_category='Legal & distress', code='L3.2',
        name='Sanctions listing or match', what_is_measured='Entity, owner or controller on a sanctions list',
        update_frequency='Real time', tac_role='T + A (override)',
        source_system='External intelligence layer - legal, insolvency and sanctions connectors',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=68, layer='L3', sub_category='Legal & distress', code='L3.2',
        name='Licence cancellation or suspension', what_is_measured='Loss of an operating licence or permit',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - legal, insolvency and sanctions connectors',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=69, layer='L3', sub_category='Ratings & markets', code='L3.3',
        name='External rating downgrade', what_is_measured='Notches downgraded by a recognised agency',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - ratings and market data feed',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=70, layer='L3', sub_category='Ratings & markets', code='L3.3',
        name='Outlook change to negative', what_is_measured='Outlook revision by a recognised agency',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - ratings and market data feed',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=71, layer='L3', sub_category='Ratings & markets', code='L3.3',
        name='Credit watch placement', what_is_measured='Placement on watch negative',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - ratings and market data feed',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=72, layer='L3', sub_category='Ratings & markets', code='L3.3',
        name='Rating withdrawal', what_is_measured='Agency withdraws the rating',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - ratings and market data feed',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=73, layer='L3', sub_category='Ratings & markets', code='L3.3',
        name='Credit spread widening', what_is_measured='Move in CDS or bond spread vs sector index',
        update_frequency='Daily', tac_role='T + A',
        source_system='External intelligence layer - ratings and market data feed',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=74, layer='L3', sub_category='Ratings & markets', code='L3.3',
        name='Bond price deterioration', what_is_measured='Fall in traded price of outstanding debt',
        update_frequency='Daily', tac_role='T + A',
        source_system='External intelligence layer - ratings and market data feed',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=75, layer='L3', sub_category='Ratings & markets', code='L3.3',
        name='Equity price deterioration', what_is_measured='Fall vs index, beta-adjusted',
        update_frequency='Daily', tac_role='T + A',
        source_system='External intelligence layer - ratings and market data feed',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=76, layer='L3', sub_category='Ratings & markets', code='L3.3',
        name='Market capitalisation decline', what_is_measured='Sustained fall in market value of equity',
        update_frequency='Daily', tac_role='T + A',
        source_system='External intelligence layer - ratings and market data feed',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=77, layer='L3', sub_category='Ratings & markets', code='L3.3',
        name='Unusual volatility', what_is_measured='Realised volatility vs its own trailing distribution',
        update_frequency='Daily', tac_role='T + A',
        source_system='External intelligence layer - ratings and market data feed',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=78, layer='L3', sub_category='News & events', code='L3.4',
        name='Contract loss or cancellation', what_is_measured='Value of the lost contract as % of annual revenue',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - news and event pipeline',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=79, layer='L3', sub_category='News & events', code='L3.4',
        name='Project delay', what_is_measured='Delay to a project material to the revenue base',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - news and event pipeline',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=80, layer='L3', sub_category='News & events', code='L3.4',
        name='Profit warning', what_is_measured='Company-issued guidance downgrade',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - news and event pipeline',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=81, layer='L3', sub_category='News & events', code='L3.4',
        name='Fraud allegation', what_is_measured='Credible allegation against the entity or its officers',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - news and event pipeline',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=82, layer='L3', sub_category='News & events', code='L3.4',
        name='Senior management resignation', what_is_measured='Departure of CEO, CFO or controlling shareholder',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - news and event pipeline',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=83, layer='L3', sub_category='News & events', code='L3.4',
        name='Plant or facility closure', what_is_measured='Closure of a material production or trading site',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - news and event pipeline',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=84, layer='L3', sub_category='News & events', code='L3.4',
        name='Labour disruption', what_is_measured='Strike, mass layoff, wage protection issue',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - news and event pipeline',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=85, layer='L3', sub_category='News & events', code='L3.4',
        name='Cyber incident', what_is_measured='Breach or ransomware affecting operations',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - news and event pipeline',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=86, layer='L3', sub_category='News & events', code='L3.4',
        name='Operational disruption', what_is_measured='Fire, accident, force majeure at a key asset',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - news and event pipeline',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=87, layer='L3', sub_category='News & events', code='L3.4',
        name='Supply-chain disruption', what_is_measured='Interruption to a critical input or logistics route',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - news and event pipeline',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=88, layer='L3', sub_category='News & events', code='L3.4',
        name='Ownership change or M&A event', what_is_measured='Change of control, disposal of a core asset',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - news and event pipeline',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=89, layer='L3', sub_category='Macro & sector', code='L3.5',
        name='Sector slowdown', what_is_measured='Sector output, PMI or order-book contraction',
        update_frequency='Monthly', tac_role='C (level) / T (shock)',
        source_system='External intelligence layer - macro and sector data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=90, layer='L3', sub_category='Macro & sector', code='L3.5',
        name='Interest-rate shock', what_is_measured='Policy rate or benchmark move beyond a set band',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - macro and sector data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=91, layer='L3', sub_category='Macro & sector', code='L3.5',
        name='Commodity or oil price shock', what_is_measured='Move in an input or output price the borrower depends on',
        update_frequency='Daily', tac_role='T + A',
        source_system='External intelligence layer - macro and sector data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=92, layer='L3', sub_category='Macro & sector', code='L3.5',
        name='Real-estate price decline', what_is_measured='Fall in the relevant transaction price index',
        update_frequency='Monthly', tac_role='T + A',
        source_system='External intelligence layer - macro and sector data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=93, layer='L3', sub_category='Macro & sector', code='L3.5',
        name='Inflation pressure', what_is_measured='Input cost inflation against pricing power',
        update_frequency='Monthly', tac_role='C',
        source_system='External intelligence layer - macro and sector data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=94, layer='L3', sub_category='Macro & sector', code='L3.5',
        name='FX movement', what_is_measured='Move against the currency of revenue or debt',
        update_frequency='Daily', tac_role='T + A',
        source_system='External intelligence layer - macro and sector data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=95, layer='L3', sub_category='Macro & sector', code='L3.5',
        name='Trade disruption', what_is_measured='Port, customs, tariff or route disruption',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - macro and sector data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=96, layer='L3', sub_category='Macro & sector', code='L3.5',
        name='Geopolitical event', what_is_measured='Event affecting a market material to the borrower',
        update_frequency='Event', tac_role='T + A',
        source_system='External intelligence layer - macro and sector data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=97, layer='L3', sub_category='Macro & sector', code='L3.5',
        name='Demand contraction', what_is_measured='Sector demand indicator falling below trend',
        update_frequency='Monthly', tac_role='T + A',
        source_system='External intelligence layer - macro and sector data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=98, layer='L4', sub_category='Ownership network', code='L4.3',
        name='Parent company deterioration', what_is_measured='Adverse event or downgrade at the parent',
        update_frequency='Event', tac_role='T + A',
        source_system='Graph and relationship store; CRM group hierarchy; guarantee register',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=99, layer='L4', sub_category='Ownership network', code='L4.3',
        name='Subsidiary deterioration', what_is_measured='Adverse event at a material subsidiary',
        update_frequency='Event', tac_role='T + A',
        source_system='Graph and relationship store; CRM group hierarchy; guarantee register',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=100, layer='L4', sub_category='Ownership network', code='L4.3',
        name='Group company deterioration', what_is_measured='Adverse event at a sister company in the group',
        update_frequency='Event', tac_role='T + A',
        source_system='Graph and relationship store; CRM group hierarchy; guarantee register',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=101, layer='L4', sub_category='Ownership network', code='L4.3',
        name='Ownership linkage change', what_is_measured='Change in ultimate beneficial ownership',
        update_frequency='Event', tac_role='T + A',
        source_system='Graph and relationship store; CRM group hierarchy; guarantee register',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=102, layer='L4', sub_category='Ownership network', code='L4.3',
        name='Common directors or shareholders with a distressed entity', what_is_measured='Shared officers or holders with a defaulted entity',
        update_frequency='Monthly', tac_role='T + A',
        source_system='Graph and relationship store; CRM group hierarchy; guarantee register',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=103, layer='L4', sub_category='Credit support', code='L4.3',
        name='Guarantor deterioration', what_is_measured='Downgrade or adverse event at the guarantor',
        update_frequency='Event', tac_role='T + A',
        source_system='Graph and relationship store; CRM group hierarchy; guarantee register',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=104, layer='L4', sub_category='Credit support', code='L4.4',
        name='Guarantor capacity (level)', what_is_measured='Guarantor rating and net worth relative to the guarantee',
        update_frequency='Quarterly', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=105, layer='L4', sub_category='Commercial dependency', code='L4.1',
        name='Key supplier distress', what_is_measured='Distress at a supplier the borrower depends on',
        update_frequency='Event', tac_role='T + A',
        source_system='Graph and relationship store; trade finance; payment counterparties',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=106, layer='L4', sub_category='Commercial dependency', code='L4.2',
        name='Key customer distress', what_is_measured='Distress at a customer material to the revenue base',
        update_frequency='Event', tac_role='T + A',
        source_system='Graph and relationship store; receivables ledger; invoice data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=107, layer='L4', sub_category='Commercial dependency', code='L4.4',
        name='Buyer concentration (level)', what_is_measured='Top-three customers as % of revenue',
        update_frequency='Annual', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Merged into receivable concentration', status='MERGED', status_detail='receivable concentration',
    ),
    SignalInventoryRow(
        num=108, layer='L4', sub_category='Commercial dependency', code='L4.4',
        name='Project dependency (level)', what_is_measured='Revenue concentration in a single project or contract',
        update_frequency='Annual', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Moved to Tab 05 as an edge attribute', status='MOVED', status_detail='Tab 05 as an edge attribute',
    ),
    SignalInventoryRow(
        num=109, layer='L4', sub_category='Exposure network', code='L4.4',
        name='Related-party exposure (level)', what_is_measured='Related-party receivables or exposure share',
        update_frequency='Monthly', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=110, layer='L4', sub_category='Upstream network', code='L4.4',
        name='Supplier concentration', what_is_measured='Top three suppliers as % of input cost',
        update_frequency='Annual', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=111, layer='L4', sub_category='Upstream network', code='L4.4',
        name='Single-source dependency', what_is_measured='Whether a critical input has no qualified alternate',
        update_frequency='Annual', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Merged into supplier replaceability', status='MERGED', status_detail='supplier replaceability',
    ),
    SignalInventoryRow(
        num=112, layer='L4', sub_category='Upstream network', code='L4.4',
        name='Supplier substitutability', what_is_measured='How readily a failing supplier can be replaced',
        update_frequency='Annual', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Merged into supplier replaceability', status='MERGED', status_detail='supplier replaceability',
    ),
    SignalInventoryRow(
        num=113, layer='L4', sub_category='Upstream network', code='L4.4',
        name='Switching time to an alternative supplier', what_is_measured='Months to qualify and onboard a replacement',
        update_frequency='Annual', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Merged into supplier replaceability', status='MERGED', status_detail='supplier replaceability',
    ),
    SignalInventoryRow(
        num=114, layer='L4', sub_category='Upstream network', code='L4.1',
        name='Tier-2 supplier distress', what_is_measured='Distress at a supplier of the borrower\'s supplier',
        update_frequency='Event', tac_role='T + A (2 hops)',
        source_system='Graph and relationship store; trade finance; payment counterparties',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=115, layer='L4', sub_category='Upstream network', code='L4.4',
        name='Input price pass-through ability', what_is_measured='Share of an input cost rise the borrower can pass on',
        update_frequency='Annual', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=116, layer='L4', sub_category='Upstream network', code='L4.4',
        name='Logistics route dependency', what_is_measured='Reliance on a single port, corridor or carrier',
        update_frequency='Annual', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=117, layer='L4', sub_category='Downstream network', code='L4.4',
        name='Receivable concentration by counterparty', what_is_measured='Largest single debtor as % of trade receivables',
        update_frequency='Monthly', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=118, layer='L4', sub_category='Downstream network', code='L4.2',
        name='DSO deterioration against a named counterparty', what_is_measured='Rise in days sales outstanding for one debtor',
        update_frequency='Monthly', tac_role='T + A',
        source_system='Graph and relationship store; receivables ledger; invoice data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=119, layer='L4', sub_category='Downstream network', code='L4.2',
        name='Receivable ageing at a distressed customer', what_is_measured='Value and ageing of receivables owed by a distressed debtor',
        update_frequency='Monthly', tac_role='T + A',
        source_system='Graph and relationship store; receivables ledger; invoice data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=120, layer='L4', sub_category='Downstream network', code='L4.2',
        name='Customer-of-customer distress', what_is_measured='Distress at the offtaker of the borrower\'s key customer',
        update_frequency='Event', tac_role='T + A (2 hops)',
        source_system='Graph and relationship store; receivables ledger; invoice data',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=121, layer='L4', sub_category='Downstream network', code='L4.4',
        name='Offtake or contract termination rights', what_is_measured='Whether a key customer can exit without penalty',
        update_frequency='Annual', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=122, layer='L4', sub_category='Exposure network', code='L4.4',
        name='Shared-counterparty exposure in the bank\'s portfolio', what_is_measured='Other borrowers depending on the same counterparty',
        update_frequency='Monthly', tac_role='C (portfolio)',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
    SignalInventoryRow(
        num=123, layer='L4', sub_category='Network governance', code='L4.4',
        name='Relationship edge confidence', what_is_measured='How well each modelled relationship is verified',
        update_frequency='Monthly', tac_role='C',
        source_system='Graph and relationship store; CRM; financial spreading system',
        status_raw='Scored', status='SCORED', status_detail='',
    ),
)

assert len(SIGNAL_INVENTORY) == 123
BY_NUM: dict[int, SignalInventoryRow] = {r.num: r for r in SIGNAL_INVENTORY}


# ---------------------------------------------------------------------------
# The six accelerator dimensions (Tab 04 Section B labels them A1-A6). Not
# part of the 123-row inventory — they scale a trigger, they are not signals.
# ---------------------------------------------------------------------------

ACCELERATOR_DIMENSIONS: tuple[dict[str, str], ...] = (
    {"code": "A1", "name": "Magnitude", "what_it_measures": "How large the deterioration is relative to the customer's own baseline"},
    {"code": "A2", "name": "Velocity", "what_it_measures": "How quickly the deterioration occurred"},
    {"code": "A3", "name": "Persistence", "what_it_measures": "Whether it is a single observation or a continuing condition"},
    {"code": "A4", "name": "Repetition", "what_it_measures": "How many times the same trigger has recurred, resetting the decay clock each time"},
    {"code": "A5", "name": "Corroboration", "what_it_measures": "How many independent signals are deteriorating in the same window"},
    {"code": "A6", "name": "Decay", "what_it_measures": "Applied separately from the five blended dimensions above — class-specific half-life, held at 1.0 while the condition remains uncured"},
)


# ---------------------------------------------------------------------------
# Deterministic name matching (exact -> containment -> token-Jaccard >= 0.5),
# then a small, explicit override table for the cases a name match cannot
# resolve on its own — every override is a documented, reviewable decision,
# not a fallback guess.
# ---------------------------------------------------------------------------

import re as _re

_STRIP_SUFFIXES = (
    " (level)", " (event)", " (inflows / outflows)", " (inflows)",
    " (downgrade event)", " - material event", " (1-29 dpd)",
    " 30+ dpd", " (current status)", " (drawn / limit)",
)


def _normalise(name: str) -> str:
    n = name.lower()
    for suf in _STRIP_SUFFIXES:
        n = n.replace(suf, "")
    return _re.sub(r"[^a-z0-9]+", " ", n).strip()


_STOPWORDS = frozenset({"a", "an", "the", "or", "and", "of", "for", "to", "at",
                         "in", "on", "with", "against", "by"})


def _tokens(name: str) -> frozenset[str]:
    return frozenset(w for w in _normalise(name).split() if w not in _STOPWORDS)


def _best_match(name: str, candidates: dict[str, Any]) -> str | None:
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
    return best_key if best_score >= 0.5 else None


#: Rows a name match cannot resolve on its own — collapses (one trigger or
#: classifier scored from more than one inventory row's angle), one
#: approximate dual-role link, and one cross-layer link where Tab 01 filed a
#: signal under a different layer than the trigger that actually scores it.
#: Every entry is a reviewed decision with its reasoning in the comment.
_CLASSIFIER_OVERRIDES: dict[int, str] = {
    37: "collateral_coverage_or_ltv",  # "Collateral coverage ratio" is the L2.5-10 classifier; Tab01's phrasing ("ratio") doesn't token-match "or LTV where real-estate secured".
    40: "covenant_headroom",  # "Covenant compliance status" (pass/breach/waived) collapses into the covenant_headroom classifier — 0% headroom is a breach; the two are one classifier, not two.
    89: "sector_vulnerability_grade",  # "Sector slowdown"'s C-role (dual T+C signal) has no dedicated classifier; the closest scored sector-risk classifier is sector_vulnerability_grade — an approximate, disclosed link, not exact.
}

_TRIGGER_OVERRIDES: dict[int, str] = {
    13: "repayment_delay",  # "Overdue 30+ DPD" is a migration framing of the same repayment_delay trigger as #12; that trigger's own bands already span 1-89 DPD.
    15: "failed_payments_returned_direct_debits",  # word-order variant only ("direct debit returns" vs "returned direct debits").
    20: "trade_finance_drop_or_guarantee_called",  # "activity drop or claim" vs "drop or guarantee called" — same trigger, below the token-overlap threshold.
    60: "late_filing_or_restatement",  # "Regulatory disclosure or filing change" is what late_filing_or_restatement's bands score.
    64: "bankruptcy_or_insolvency_filing",  # that trigger's own SEV1/SEV2 bands are literally "Preventive settlement filed by a connected party / by the borrower" — this row is those bands, not a separate trigger.
    68: "regulatory_enforcement_action",  # that trigger's own SEV4/SEV5 bands are "Licence suspended" / "Licence revoked".
    70: "outlook_or_watch_action",  # that trigger's SEV1/SEV2 bands are exactly "Outlook stable to negative" / "Outlook negative reaffirmed".
    71: "outlook_or_watch_action",  # SEV3/SEV4: "Placed on watch negative" / "Watch negative extended".
    72: "outlook_or_watch_action",  # SEV5: "Rating withdrawn at the issuer's request".
    74: "equity_price_deterioration",  # no dedicated bond-price trigger exists; bond and equity price deterioration share the one market-price trigger.
    76: "equity_price_deterioration",  # market-cap decline is price deterioration times shares outstanding — same underlying market signal.
    77: "equity_price_deterioration",  # judgment call: no dedicated volatility trigger exists; volatility spikes are grouped with the equity-price market signal it most often co-moves with. Disclosed, not workbook-given.
    83: "operational_or_plant_disruption",  # that trigger's own SEV5 band is closure; #86 "Operational disruption" is the same trigger from the other end of its severity range.
    88: "ownership_or_control_change",  # cross-layer: Tab01 files "Ownership change or M&A event" under L3 News & events, but the trigger that scores it (ownership_or_control_change) is an L4 governance trigger. Disclosed, not silently renumbered.
    89: "sector_demand_contraction",  # "Sector slowdown"'s T-role (shock framing) shares the sector_demand_contraction trigger with #97 "Demand contraction".
    96: "geopolitical_or_trade_disruption",  # shares the trigger with #95 "Trade disruption" — one trigger, two named angles.
    99: "group_or_sister_company_deterioration",  # "Subsidiary deterioration" and #100 "Group company deterioration" are both scored by the one group/sister-company trigger; direction of ownership doesn't change which trigger fires.
}

#: SCORED rows with no classifier or trigger definition anywhere in the
#: workbook — disclosed, not force-linked to the nearest plausible one.
_RESIDUAL_NOTES: dict[int, str] = {
    93: "No Tab 03 classifier bands inflation directly; it can inform sector_vulnerability_grade qualitatively but has no dedicated banding of its own.",
    109: "No Tab 03 classifier exists for related-party exposure as a level; Tab 02 does not record its fate either. Genuinely unbanded.",
    115: "No Tab 03 classifier exists for input price pass-through ability. Genuinely unbanded.",
    116: "No Tab 03 classifier exists for logistics route dependency as a static level (distinct from the L4.1 disruption trigger, which is event-based). Genuinely unbanded.",
    121: "No Tab 03 classifier exists for offtake/contract termination rights. Genuinely unbanded.",
}

#: Row #122 is the Tab 4b Section F portfolio-contagion view, not a
#: per-borrower classifier or trigger.
_PORTFOLIO_VIEW_ROWS: frozenset[int] = frozenset({122})

#: Triggers Tab 04 defines with no distinct Tab 01 companion row — a
#: legitimate state (not every trigger needs its own named inventory row),
#: disclosed rather than force-matched to an unrelated row.
TRIGGER_ONLY_NO_INVENTORY_ROW: frozenset[str] = frozenset({
    "logistics_route_disruption", "cross_default_relationship_triggered",
})

#: Classifiers built entirely from otherwise-MERGED rows' concepts, with no
#: single SCORED row of their own (Tab 02 Section B: two individually-weak
#: variables merged into one classifier).
CLASSIFIER_MERGED_COMPOSITE_NO_DIRECT_ROW: frozenset[str] = frozenset({
    "obligor_profile", "supplier_replaceability",
})

#: Row #32 ("Bank share of the borrower's total debt") is marked REPLACED in
#: Tab 01, yet Tab 03 classifier #14 of the exact same name is actively
#: scored with real bands. This is a genuine small inconsistency in the
#: source workbook (row #31's "Replaced - absolute amount, not a ratio"
#: reason text appears to have been copied onto row #32, whose own measure
#: is already a percentage) — disclosed here rather than silently resolved
#: either way. Tab 01's literal status (REPLACED) is kept for the 105/18
#: count; the classifier itself is fully implemented per Tab 03.
KNOWN_WORKBOOK_INCONSISTENCIES: dict[int, str] = {
    32: ("Tab 01 marks this row REPLACED (\'absolute amount, not a ratio\'), "
         "but its own measure is already a percentage, and Tab 03 classifier "
         "#14 of the identical name (bank_share_of_obligor_debt) is actively "
         "scored. Kept REPLACED for the literal 105/18 count; the classifier "
         "runs regardless, sourced independently in thresholds.py."),
}


@dataclass(frozen=True)
class ResolvedSignal:
    row: SignalInventoryRow
    linked_classifier_key: str | None
    linked_trigger_key: str | None
    is_portfolio_view: bool
    note: str | None


def resolve_signal(row: SignalInventoryRow) -> ResolvedSignal:
    if row.status != SCORED:
        return ResolvedSignal(row=row, linked_classifier_key=None,
                               linked_trigger_key=None, is_portfolio_view=False,
                               note=None)
    if row.num in _PORTFOLIO_VIEW_ROWS:
        return ResolvedSignal(
            row=row, linked_classifier_key=None, linked_trigger_key=None,
            is_portfolio_view=True,
            note="Tab 4b Section F portfolio-contagion view, not a per-borrower classifier or trigger.")

    linked_classifier: str | None = None
    linked_trigger: str | None = None
    if "C" in row.tac_role:
        linked_classifier = _CLASSIFIER_OVERRIDES.get(row.num) or _best_match(row.name, classifiers_v2.BY_KEY)
    if "T" in row.tac_role:
        linked_trigger = _TRIGGER_OVERRIDES.get(row.num) or _best_match(row.name, triggers_v2.BY_KEY)

    note = _RESIDUAL_NOTES.get(row.num)
    if note is None and row.num in KNOWN_WORKBOOK_INCONSISTENCIES:
        note = KNOWN_WORKBOOK_INCONSISTENCIES[row.num]

    return ResolvedSignal(row=row, linked_classifier_key=linked_classifier,
                           linked_trigger_key=linked_trigger,
                           is_portfolio_view=False, note=note)


def resolve_all() -> list[ResolvedSignal]:
    return [resolve_signal(r) for r in SIGNAL_INVENTORY]


def status_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in SIGNAL_INVENTORY:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts


def unresolved_signals() -> list[ResolvedSignal]:
    """SCORED rows with neither a classifier/trigger link nor a documented
    residual/portfolio-view note — the genuinely unexplained set. Target: 0."""
    out = []
    for r in resolve_all():
        if r.row.status != SCORED or r.is_portfolio_view or r.note is not None:
            continue
        needs_classifier = "C" in r.row.tac_role and r.linked_classifier_key is None
        needs_trigger = "T" in r.row.tac_role and r.linked_trigger_key is None
        if needs_classifier or needs_trigger:
            out.append(r)
    return out


def classifiers_with_no_scored_row() -> list[str]:
    """The 2 merged-composite classifiers, disclosed as such, plus any
    genuine gap this reconciliation missed."""
    used = {r.linked_classifier_key for r in resolve_all() if r.linked_classifier_key}
    return sorted(set(classifiers_v2.BY_KEY) - used)


def triggers_with_no_scored_row() -> list[str]:
    used = {r.linked_trigger_key for r in resolve_all() if r.linked_trigger_key}
    return sorted(set(triggers_v2.BY_KEY) - used)


def describe() -> dict[str, Any]:
    resolved = resolve_all()
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "signal_count": len(SIGNAL_INVENTORY),
        "accelerator_dimension_count": len(ACCELERATOR_DIMENSIONS),
        "classifier_count": len(classifiers_v2.CLASSIFIER_DEFINITIONS),
        "trigger_count": len(triggers_v2.TRIGGER_DEFINITIONS),
        "status_counts": status_counts(),
        "unresolved_count": len(unresolved_signals()),
        "unresolved_keys": [r.row.name for r in unresolved_signals()],
        "classifiers_with_no_scored_row": classifiers_with_no_scored_row(),
        "triggers_with_no_scored_row": triggers_with_no_scored_row(),
        "known_workbook_inconsistencies": KNOWN_WORKBOOK_INCONSISTENCIES,
    }

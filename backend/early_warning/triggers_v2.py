"""The 67 Version 2 dynamic triggers.

Source of truth: CreditProbe Early Warning Framework Version 2 workbook,
Tab 3 Section A ("Trigger definitions and severity bands"). Every threshold
below is transcribed verbatim — the workbook, not this module, is where a
disputed threshold gets changed.

Formula (Tab 3 Section C, first line):

    trigger_score = (severity_band - 1) * 25 + 20

giving the fixed point scale 20 / 40 / 60 / 80 / 100 for severity bands 1-5.
All thresholds are read against the customer's own trailing baseline unless
the row states otherwise, and all are bank-configurable — this module is the
seed configuration, not a hardcoded law.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SEVERITY_SCORE: dict[int, int] = {1: 20, 2: 40, 3: 60, 4: 80, 5: 100}


def trigger_score_for_band(severity_band: int) -> int:
    """Tab 3 §C: (band - 1) * 25 + 20."""
    if severity_band not in SEVERITY_SCORE:
        raise ValueError(f"severity band must be 1-5, got {severity_band}")
    return SEVERITY_SCORE[severity_band]


@dataclass(frozen=True)
class SeverityBand:
    band: int
    score: int
    description: str


@dataclass(frozen=True)
class TriggerDefinition:
    """One row of Tab 3 Section A. `code` is the workbook's own row number
    (1-67), kept so a finding can be traced back to the exact cell."""

    code: str
    key: str
    layer: str
    name: str
    fires_when: str
    baseline: str
    bands: tuple[SeverityBand, SeverityBand, SeverityBand, SeverityBand, SeverityBand]

    def band(self, n: int) -> SeverityBand:
        for b in self.bands:
            if b.band == n:
                return b
        raise KeyError(f"{self.key}: no such band {n!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "key": self.key, "layer": self.layer,
            "name": self.name, "fires_when": self.fires_when,
            "baseline": self.baseline,
            "bands": [{"band": b.band, "score": b.score, "description": b.description}
                      for b in self.bands],
        }


# ---------------------------------------------------------------------------
# The 67 triggers, transcribed verbatim from Tab 3 Section A, rows 7-73.
# ---------------------------------------------------------------------------

TRIGGER_DEFINITIONS: tuple[TriggerDefinition, ...] = (
    TriggerDefinition(
        code='1', key='operating_deposit_balance_decline', layer='L1', name='Operating / deposit balance decline',
        fires_when='30-day average balance falls 15% or more below the trailing 12-month average', baseline='Own 12-month average',
        bands=(
            SeverityBand(1, 20, '-15% to -25%'),
            SeverityBand(2, 40, '-25% to -40%'),
            SeverityBand(3, 60, '-40% to -55%'),
            SeverityBand(4, 80, '-55% to -70%'),
            SeverityBand(5, 100, 'Below -70%'),
        ),
    ),
    TriggerDefinition(
        code='2', key='reduction_in_account_credits', layer='L1', name='Reduction in account credits',
        fires_when='Monthly credit turnover falls 20% or more below the 12-month average', baseline='Own 12-month average',
        bands=(
            SeverityBand(1, 20, '-20% to -30%'),
            SeverityBand(2, 40, '-30% to -45%'),
            SeverityBand(3, 60, '-45% to -60%'),
            SeverityBand(4, 80, '-60% to -75%'),
            SeverityBand(5, 100, 'Below -75%'),
        ),
    ),
    TriggerDefinition(
        code='3', key='fall_in_turnover_transaction_volume', layer='L1', name='Fall in turnover / transaction volume',
        fires_when='Rolling 30-day transaction value falls 20% or more vs baseline', baseline='Own 90-day average',
        bands=(
            SeverityBand(1, 20, '-20% to -30%'),
            SeverityBand(2, 40, '-30% to -45%'),
            SeverityBand(3, 60, '-45% to -60%'),
            SeverityBand(4, 80, '-60% to -75%'),
            SeverityBand(5, 100, 'Below -75%'),
        ),
    ),
    TriggerDefinition(
        code='4', key='cash_flow_deterioration', layer='L1', name='Cash-flow deterioration',
        fires_when='Rolling 90-day net inflow turns negative or falls sharply vs prior period', baseline='Own prior 90 days',
        bands=(
            SeverityBand(1, 20, '-10% to -25%'),
            SeverityBand(2, 40, '-25% to -40%'),
            SeverityBand(3, 60, '-40% to -60%'),
            SeverityBand(4, 80, '-60% to -80%'),
            SeverityBand(5, 100, 'Negative net inflow'),
        ),
    ),
    TriggerDefinition(
        code='5', key='concentration_of_inflows', layer='L1', name='Concentration of inflows',
        fires_when='Top-three counterparty share of inflows rises 10 points or more', baseline='Own 12-month average',
        bands=(
            SeverityBand(1, 20, '+10 to +15 pts'),
            SeverityBand(2, 40, '+15 to +25 pts'),
            SeverityBand(3, 60, '+25 to +35 pts'),
            SeverityBand(4, 80, '+35 to +50 pts'),
            SeverityBand(5, 100, 'Above +50 pts'),
        ),
    ),
    TriggerDefinition(
        code='6', key='unusual_fund_movements', layer='L1', name='Unusual fund movements',
        fires_when='Transfer outside the learned behavioural profile above a value threshold', baseline='Own transaction profile',
        bands=(
            SeverityBand(1, 20, '1 event, under 5% of average monthly flow'),
            SeverityBand(2, 40, '5% to 15%'),
            SeverityBand(3, 60, '15% to 30%'),
            SeverityBand(4, 80, '30% to 50%'),
            SeverityBand(5, 100, 'Above 50% of monthly flow'),
        ),
    ),
    TriggerDefinition(
        code='7', key='abnormal_debit_credit_behaviour', layer='L1', name='Abnormal debit / credit behaviour',
        fires_when='Composite behaviour score breaches 2 standard deviations', baseline='Own behavioural profile',
        bands=(
            SeverityBand(1, 20, '2.0 to 2.5 sigma'),
            SeverityBand(2, 40, '2.5 to 3.0 sigma'),
            SeverityBand(3, 60, '3.0 to 3.5 sigma'),
            SeverityBand(4, 80, '3.5 to 4.0 sigma'),
            SeverityBand(5, 100, 'Above 4.0 sigma'),
        ),
    ),
    TriggerDefinition(
        code='8', key='utilisation_increase', layer='L1', name='Utilisation increase',
        fires_when='Utilisation rises 10 percentage points or more vs the 3-month average', baseline='Own 3-month average',
        bands=(
            SeverityBand(1, 20, '+10 to +15 pts'),
            SeverityBand(2, 40, '+15 to +25 pts'),
            SeverityBand(3, 60, '+25 to +35 pts'),
            SeverityBand(4, 80, '+35 to +50 pts'),
            SeverityBand(5, 100, 'Above +50 pts'),
        ),
    ),
    TriggerDefinition(
        code='9', key='sustained_high_utilisation', layer='L1', name='Sustained high utilisation',
        fires_when='Utilisation above 90% for 10 or more consecutive days', baseline='Configured threshold',
        bands=(
            SeverityBand(1, 20, '10 to 20 days'),
            SeverityBand(2, 40, '21 to 40 days'),
            SeverityBand(3, 60, '41 to 60 days'),
            SeverityBand(4, 80, '61 to 90 days'),
            SeverityBand(5, 100, 'Over 90 days'),
        ),
    ),
    TriggerDefinition(
        code='10', key='excess_over_limit', layer='L1', name='Excess over limit',
        fires_when='Any drawn balance above the sanctioned limit', baseline='Sanctioned limit',
        bands=(
            SeverityBand(1, 20, '1 to 3 days'),
            SeverityBand(2, 40, '4 to 7 days'),
            SeverityBand(3, 60, '8 to 15 days'),
            SeverityBand(4, 80, '16 to 30 days'),
            SeverityBand(5, 100, 'Over 30 days'),
        ),
    ),
    TriggerDefinition(
        code='11', key='limit_breach_frequency', layer='L1', name='Limit breach frequency',
        fires_when='Two or more separate breaches in the trailing 12 months', baseline='Trailing 12 months',
        bands=(
            SeverityBand(1, 20, '2 breaches'),
            SeverityBand(2, 40, '3 breaches'),
            SeverityBand(3, 60, '4 breaches'),
            SeverityBand(4, 80, '5 to 6 breaches'),
            SeverityBand(5, 100, '7 or more'),
        ),
    ),
    TriggerDefinition(
        code='12', key='repayment_delay', layer='L1', name='Repayment delay',
        fires_when='Any facility past due', baseline='Contractual due date',
        bands=(
            SeverityBand(1, 20, '1 to 7 DPD'),
            SeverityBand(2, 40, '8 to 15 DPD'),
            SeverityBand(3, 60, '16 to 29 DPD'),
            SeverityBand(4, 80, '30 to 59 DPD'),
            SeverityBand(5, 100, '60 to 89 DPD'),
        ),
    ),
    TriggerDefinition(
        code='13', key='missed_instalments', layer='L1', name='Missed instalments',
        fires_when='One or more scheduled instalments missed in 12 months', baseline='Amortisation schedule',
        bands=(
            SeverityBand(1, 20, '1 instalment'),
            SeverityBand(2, 40, '2 instalments'),
            SeverityBand(3, 60, '3 instalments'),
            SeverityBand(4, 80, '4 instalments'),
            SeverityBand(5, 100, '5 or more'),
        ),
    ),
    TriggerDefinition(
        code='14', key='failed_payments_returned_direct_debits', layer='L1', name='Failed payments / returned direct debits',
        fires_when='One or more returns in the trailing 90 days', baseline='Trailing 90 days',
        bands=(
            SeverityBand(1, 20, '1 return'),
            SeverityBand(2, 40, '2 returns'),
            SeverityBand(3, 60, '3 returns'),
            SeverityBand(4, 80, '4 returns'),
            SeverityBand(5, 100, '5 or more'),
        ),
    ),
    TriggerDefinition(
        code='15', key='returned_cheques', layer='L1', name='Returned cheques',
        fires_when='Any cheque returned unpaid', baseline='Trailing 90 days',
        bands=(
            SeverityBand(1, 20, '1 cheque, immaterial value'),
            SeverityBand(2, 40, '2 cheques'),
            SeverityBand(3, 60, '3 cheques'),
            SeverityBand(4, 80, '4 cheques'),
            SeverityBand(5, 100, '5 or more, or a material value'),
        ),
    ),
    TriggerDefinition(
        code='16', key='account_dormancy_activity_decline', layer='L1', name='Account dormancy / activity decline',
        fires_when='Transaction count falls more than 50% for 30 consecutive days', baseline='Own 12-month average',
        bands=(
            SeverityBand(1, 20, '30 to 45 days'),
            SeverityBand(2, 40, '46 to 60 days'),
            SeverityBand(3, 60, '61 to 90 days'),
            SeverityBand(4, 80, '91 to 120 days'),
            SeverityBand(5, 100, 'Over 120 days'),
        ),
    ),
    TriggerDefinition(
        code='17', key='sudden_drop_in_operating_activity', layer='L1', name='Sudden drop in operating activity',
        fires_when='Step change in the composite activity index beyond 2 sigma', baseline='Own activity index',
        bands=(
            SeverityBand(1, 20, '2.0 to 2.5 sigma'),
            SeverityBand(2, 40, '2.5 to 3.0 sigma'),
            SeverityBand(3, 60, '3.0 to 3.5 sigma'),
            SeverityBand(4, 80, '3.5 to 4.0 sigma'),
            SeverityBand(5, 100, 'Above 4.0 sigma'),
        ),
    ),
    TriggerDefinition(
        code='18', key='movement_of_business_away_from_the_bank', layer='L1', name='Movement of business away from the bank',
        fires_when='Share of wallet falls 10 points or more, or collections diverted', baseline='Own 12-month share',
        bands=(
            SeverityBand(1, 20, '-10 to -20 pts'),
            SeverityBand(2, 40, '-20 to -30 pts'),
            SeverityBand(3, 60, '-30 to -40 pts'),
            SeverityBand(4, 80, '-40 to -50 pts'),
            SeverityBand(5, 100, 'Below -50 pts'),
        ),
    ),
    TriggerDefinition(
        code='19', key='trade_finance_drop_or_guarantee_called', layer='L1', name='Trade finance drop or guarantee called',
        fires_when='LC / LG volume falls sharply, or a guarantee is called', baseline='Own 12-month average',
        bands=(
            SeverityBand(1, 20, 'Volume -20% to -35%'),
            SeverityBand(2, 40, '-35% to -50%'),
            SeverityBand(3, 60, '-50% to -70%'),
            SeverityBand(4, 80, 'Below -70%'),
            SeverityBand(5, 100, 'Guarantee called'),
        ),
    ),
    TriggerDefinition(
        code='20', key='rating_migration_downgrade', layer='L2', name='Rating migration (downgrade)',
        fires_when='Internal rating downgraded within the trailing 12 months', baseline='Prior internal grade',
        bands=(
            SeverityBand(1, 20, '1 notch, within investment grade'),
            SeverityBand(2, 40, '2 notches'),
            SeverityBand(3, 60, '3 notches'),
            SeverityBand(4, 80, 'Crosses into sub-investment grade'),
            SeverityBand(5, 100, '4 or more notches, or to default grade'),
        ),
    ),
    TriggerDefinition(
        code='21', key='pd_movement', layer='L2', name='PD movement',
        fires_when='12-month PD rises materially vs the prior quarter', baseline='Prior quarter PD',
        bands=(
            SeverityBand(1, 20, '+10% to +25% relative'),
            SeverityBand(2, 40, '+25% to +50%'),
            SeverityBand(3, 60, '+50% to +100%'),
            SeverityBand(4, 80, '+100% to +200%'),
            SeverityBand(5, 100, 'Above +200%'),
        ),
    ),
    TriggerDefinition(
        code='22', key='stage_migration', layer='L2', name='Stage migration',
        fires_when='Movement to a worse IFRS 9 stage', baseline='Prior stage',
        bands=(
            SeverityBand(1, 20, 'Watch flag raised within Stage 1'),
            SeverityBand(2, 40, 'Stage 1 to Stage 2'),
            SeverityBand(3, 60, 'Stage 2 with 30+ DPD'),
            SeverityBand(4, 80, 'Stage 2 to Stage 3 pending'),
            SeverityBand(5, 100, 'Confirmed Stage 3'),
        ),
    ),
    TriggerDefinition(
        code='23', key='ecl_movement', layer='L2', name='ECL movement',
        fires_when='ECL coverage rises materially vs the prior period', baseline='Prior period coverage',
        bands=(
            SeverityBand(1, 20, '+10% to +25% relative'),
            SeverityBand(2, 40, '+25% to +50%'),
            SeverityBand(3, 60, '+50% to +100%'),
            SeverityBand(4, 80, '+100% to +200%'),
            SeverityBand(5, 100, 'Above +200%'),
        ),
    ),
    TriggerDefinition(
        code='24', key='collateral_value_movement', layer='L2', name='Collateral value movement',
        fires_when='Appraised value falls since the last valuation', baseline='Last appraisal',
        bands=(
            SeverityBand(1, 20, '-5% to -10%'),
            SeverityBand(2, 40, '-10% to -20%'),
            SeverityBand(3, 60, '-20% to -30%'),
            SeverityBand(4, 80, '-30% to -40%'),
            SeverityBand(5, 100, 'Below -40%'),
        ),
    ),
    TriggerDefinition(
        code='25', key='covenant_breach', layer='L2', name='Covenant breach',
        fires_when='A maintenance covenant is breached or a waiver is requested', baseline='Facility agreement',
        bands=(
            SeverityBand(1, 20, 'Technical, non-financial covenant'),
            SeverityBand(2, 40, 'Financial covenant, cured within the period'),
            SeverityBand(3, 60, 'Financial covenant, waiver requested'),
            SeverityBand(4, 80, 'Financial covenant, waiver refused'),
            SeverityBand(5, 100, 'Multiple covenants breached'),
        ),
    ),
    TriggerDefinition(
        code='26', key='financial_statement_deterioration', layer='L2', name='Financial statement deterioration',
        fires_when='Material year-on-year fall in revenue or EBITDA', baseline='Prior audited year',
        bands=(
            SeverityBand(1, 20, 'EBITDA -10% to -20%'),
            SeverityBand(2, 40, '-20% to -35%'),
            SeverityBand(3, 60, '-35% to -50%'),
            SeverityBand(4, 80, 'Below -50%'),
            SeverityBand(5, 100, 'EBITDA turns negative'),
        ),
    ),
    TriggerDefinition(
        code='27', key='exchange_announcement_adverse', layer='L3', name='Exchange announcement, adverse',
        fires_when='Issuer discloses a credit-relevant adverse event', baseline='Event taxonomy',
        bands=(
            SeverityBand(1, 20, 'Minor operational disclosure'),
            SeverityBand(2, 40, 'Operational, financially quantified'),
            SeverityBand(3, 60, 'Financially material to cash flow'),
            SeverityBand(4, 80, 'Material to solvency or liquidity'),
            SeverityBand(5, 100, 'Going-concern language'),
        ),
    ),
    TriggerDefinition(
        code='28', key='adverse_results_announcement', layer='L3', name='Adverse results announcement',
        fires_when='Reported loss, margin collapse or covenant commentary', baseline='Prior reported period',
        bands=(
            SeverityBand(1, 20, 'Margin down, still profitable'),
            SeverityBand(2, 40, 'First quarterly loss'),
            SeverityBand(3, 60, 'Loss with liquidity commentary'),
            SeverityBand(4, 80, 'Covenant breach disclosed'),
            SeverityBand(5, 100, 'Going-concern qualification'),
        ),
    ),
    TriggerDefinition(
        code='29', key='late_filing_or_restatement', layer='L3', name='Late filing or restatement',
        fires_when='Statutory filing missed, or prior figures restated', baseline='Filing calendar',
        bands=(
            SeverityBand(1, 20, 'Filed late, under 30 days'),
            SeverityBand(2, 40, '30 to 90 days late'),
            SeverityBand(3, 60, 'Over 90 days late'),
            SeverityBand(4, 80, 'Restatement of prior figures'),
            SeverityBand(5, 100, 'Filing suspended by the regulator'),
        ),
    ),
    TriggerDefinition(
        code='30', key='commercial_registration_status_change', layer='L3', name='Commercial registration status change',
        fires_when='CR suspended, expired or scope narrowed', baseline='Registry status',
        bands=(
            SeverityBand(1, 20, 'Scope amended'),
            SeverityBand(2, 40, 'Renewal overdue'),
            SeverityBand(3, 60, 'CR expired'),
            SeverityBand(4, 80, 'CR suspended'),
            SeverityBand(5, 100, 'CR cancelled'),
        ),
    ),
    TriggerDefinition(
        code='31', key='auditor_change_or_qualified_opinion', layer='L3', name='Auditor change or qualified opinion',
        fires_when='Auditor resigns, or a qualification is issued', baseline='Prior audit opinion',
        bands=(
            SeverityBand(1, 20, 'Routine rotation'),
            SeverityBand(2, 40, 'Unscheduled change of auditor'),
            SeverityBand(3, 60, 'Emphasis of matter'),
            SeverityBand(4, 80, 'Qualified opinion'),
            SeverityBand(5, 100, 'Adverse or disclaimer of opinion'),
        ),
    ),
    TriggerDefinition(
        code='32', key='bankruptcy_or_insolvency_filing', layer='L3', name='Bankruptcy or insolvency filing',
        fires_when='Debtor named in a formal insolvency procedure', baseline='Insolvency registry',
        bands=(
            SeverityBand(1, 20, 'Preventive settlement filed by a connected party'),
            SeverityBand(2, 40, 'Preventive settlement filed by the borrower'),
            SeverityBand(3, 60, 'Financial restructuring commenced'),
            SeverityBand(4, 80, 'Liquidation petition filed'),
            SeverityBand(5, 100, 'Liquidation order granted'),
        ),
    ),
    TriggerDefinition(
        code='33', key='material_litigation', layer='L3', name='Material litigation',
        fires_when='Claim material relative to equity or annual cash flow', baseline='Latest financials',
        bands=(
            SeverityBand(1, 20, 'Claim under 5% of equity'),
            SeverityBand(2, 40, '5% to 15%'),
            SeverityBand(3, 60, '15% to 30%'),
            SeverityBand(4, 80, '30% to 50%'),
            SeverityBand(5, 100, 'Above 50% of equity'),
        ),
    ),
    TriggerDefinition(
        code='34', key='regulatory_enforcement_action', layer='L3', name='Regulatory enforcement action',
        fires_when='Fine, censure or suspension by a competent authority', baseline='Regulator publication',
        bands=(
            SeverityBand(1, 20, 'Warning or minor fine'),
            SeverityBand(2, 40, 'Material fine'),
            SeverityBand(3, 60, 'Business restriction imposed'),
            SeverityBand(4, 80, 'Licence suspended'),
            SeverityBand(5, 100, 'Licence revoked'),
        ),
    ),
    TriggerDefinition(
        code='35', key='sanctions_listing_or_match', layer='L3', name='Sanctions listing or match',
        fires_when='Entity, owner or controller matched to a sanctions list', baseline='Sanctions lists',
        bands=(
            SeverityBand(1, 20, 'Weak name match, unresolved'),
            SeverityBand(2, 40, 'Connected party listed'),
            SeverityBand(3, 60, 'Beneficial owner listed'),
            SeverityBand(4, 80, 'Entity listed by one regime'),
            SeverityBand(5, 100, 'Entity listed by multiple regimes'),
        ),
    ),
    TriggerDefinition(
        code='36', key='external_rating_downgrade', layer='L3', name='External rating downgrade',
        fires_when='Downgrade by a recognised agency', baseline='Prior external rating',
        bands=(
            SeverityBand(1, 20, '1 notch within investment grade'),
            SeverityBand(2, 40, '2 notches'),
            SeverityBand(3, 60, '3 notches'),
            SeverityBand(4, 80, 'Crosses into sub-investment grade'),
            SeverityBand(5, 100, '4 or more notches, or to default'),
        ),
    ),
    TriggerDefinition(
        code='37', key='outlook_or_watch_action', layer='L3', name='Outlook or watch action',
        fires_when='Outlook revised negative, or watch negative', baseline='Prior outlook',
        bands=(
            SeverityBand(1, 20, 'Outlook stable to negative'),
            SeverityBand(2, 40, 'Outlook negative reaffirmed'),
            SeverityBand(3, 60, 'Placed on watch negative'),
            SeverityBand(4, 80, 'Watch negative extended'),
            SeverityBand(5, 100, "Rating withdrawn at the issuer's request"),
        ),
    ),
    TriggerDefinition(
        code='38', key='credit_spread_widening', layer='L3', name='Credit spread widening',
        fires_when='Spread widens vs its own history and the sector index', baseline='Own 90-day average',
        bands=(
            SeverityBand(1, 20, '+50 to +100 bps'),
            SeverityBand(2, 40, '+100 to +200 bps'),
            SeverityBand(3, 60, '+200 to +400 bps'),
            SeverityBand(4, 80, '+400 to +800 bps'),
            SeverityBand(5, 100, 'Above +800 bps'),
        ),
    ),
    TriggerDefinition(
        code='39', key='equity_price_deterioration', layer='L3', name='Equity price deterioration',
        fires_when='Beta-adjusted fall vs the market index over 60 days', baseline='Own 12-month beta',
        bands=(
            SeverityBand(1, 20, '-10% to -20% relative'),
            SeverityBand(2, 40, '-20% to -30%'),
            SeverityBand(3, 60, '-30% to -45%'),
            SeverityBand(4, 80, '-45% to -60%'),
            SeverityBand(5, 100, 'Below -60%'),
        ),
    ),
    TriggerDefinition(
        code='40', key='contract_loss_or_cancellation', layer='L3', name='Contract loss or cancellation',
        fires_when='A named contract is lost, cancelled or not renewed', baseline='Annual revenue',
        bands=(
            SeverityBand(1, 20, 'Under 5% of revenue'),
            SeverityBand(2, 40, '5% to 15%'),
            SeverityBand(3, 60, '15% to 30%'),
            SeverityBand(4, 80, '30% to 50%'),
            SeverityBand(5, 100, 'Above 50% of revenue'),
        ),
    ),
    TriggerDefinition(
        code='41', key='project_delay', layer='L3', name='Project delay',
        fires_when='Delay to a project material to the revenue base', baseline='Project schedule',
        bands=(
            SeverityBand(1, 20, 'Under 3 months'),
            SeverityBand(2, 40, '3 to 6 months'),
            SeverityBand(3, 60, '6 to 12 months'),
            SeverityBand(4, 80, 'Over 12 months'),
            SeverityBand(5, 100, 'Project cancelled'),
        ),
    ),
    TriggerDefinition(
        code='42', key='profit_warning', layer='L3', name='Profit warning',
        fires_when='Company-issued guidance downgrade', baseline='Prior guidance',
        bands=(
            SeverityBand(1, 20, 'Under 10% below guidance'),
            SeverityBand(2, 40, '10% to 25%'),
            SeverityBand(3, 60, '25% to 40%'),
            SeverityBand(4, 80, '40% to 60%'),
            SeverityBand(5, 100, 'Above 60%, or guidance withdrawn'),
        ),
    ),
    TriggerDefinition(
        code='43', key='fraud_allegation', layer='L3', name='Fraud allegation',
        fires_when='Credible allegation against the entity or its officers', baseline='Source tier',
        bands=(
            SeverityBand(1, 20, 'Unverified single source'),
            SeverityBand(2, 40, 'Reported by an established outlet'),
            SeverityBand(3, 60, 'Regulator opens an enquiry'),
            SeverityBand(4, 80, 'Charges filed'),
            SeverityBand(5, 100, 'Conviction or admitted fraud'),
        ),
    ),
    TriggerDefinition(
        code='44', key='senior_management_resignation', layer='L3', name='Senior management resignation',
        fires_when='Departure of CEO, CFO or controlling shareholder', baseline='Governance record',
        bands=(
            SeverityBand(1, 20, 'Planned succession'),
            SeverityBand(2, 40, 'Unplanned departure of one officer'),
            SeverityBand(3, 60, 'CFO departure without succession'),
            SeverityBand(4, 80, 'Multiple officers within 6 months'),
            SeverityBand(5, 100, 'Departure alongside an audit or fraud issue'),
        ),
    ),
    TriggerDefinition(
        code='45', key='operational_or_plant_disruption', layer='L3', name='Operational or plant disruption',
        fires_when='Closure, fire, accident or force majeure at a key asset', baseline='Asset contribution to revenue',
        bands=(
            SeverityBand(1, 20, 'Under 5% of capacity'),
            SeverityBand(2, 40, '5% to 15%'),
            SeverityBand(3, 60, '15% to 30%'),
            SeverityBand(4, 80, '30% to 50%'),
            SeverityBand(5, 100, 'Above 50% of capacity'),
        ),
    ),
    TriggerDefinition(
        code='46', key='labour_disruption', layer='L3', name='Labour disruption',
        fires_when='Strike, mass layoff or wage protection issue', baseline='Workforce size',
        bands=(
            SeverityBand(1, 20, 'Localised, under 1 week'),
            SeverityBand(2, 40, '1 to 4 weeks'),
            SeverityBand(3, 60, 'Over 4 weeks'),
            SeverityBand(4, 80, 'Wage protection breach reported'),
            SeverityBand(5, 100, 'Regulatory action over unpaid wages'),
        ),
    ),
    TriggerDefinition(
        code='47', key='cyber_incident', layer='L3', name='Cyber incident',
        fires_when='Breach or ransomware affecting operations', baseline='Operational continuity',
        bands=(
            SeverityBand(1, 20, 'Contained, no downtime'),
            SeverityBand(2, 40, 'Under 48 hours downtime'),
            SeverityBand(3, 60, '2 to 7 days'),
            SeverityBand(4, 80, 'Over 7 days'),
            SeverityBand(5, 100, 'Data loss with regulatory consequence'),
        ),
    ),
    TriggerDefinition(
        code='48', key='supply_chain_disruption', layer='L3', name='Supply-chain disruption',
        fires_when='Interruption to a critical input or logistics route', baseline='Input dependency',
        bands=(
            SeverityBand(1, 20, 'Under 5% of input cost'),
            SeverityBand(2, 40, '5% to 15%'),
            SeverityBand(3, 60, '15% to 30%'),
            SeverityBand(4, 80, '30% to 50%'),
            SeverityBand(5, 100, 'Above 50% of input cost'),
        ),
    ),
    TriggerDefinition(
        code='49', key='commodity_or_input_price_shock', layer='L3', name='Commodity or input price shock',
        fires_when='Move in a price the borrower depends on, beyond its own band', baseline='Own 3-year price band',
        bands=(
            SeverityBand(1, 20, '1.0 to 1.5 sigma'),
            SeverityBand(2, 40, '1.5 to 2.0 sigma'),
            SeverityBand(3, 60, '2.0 to 2.5 sigma'),
            SeverityBand(4, 80, '2.5 to 3.0 sigma'),
            SeverityBand(5, 100, 'Above 3.0 sigma'),
        ),
    ),
    TriggerDefinition(
        code='50', key='fx_movement', layer='L3', name='FX movement',
        fires_when='Move against the currency of revenue or debt', baseline='Own unhedged position',
        bands=(
            SeverityBand(1, 20, '1% to 3% of EBITDA'),
            SeverityBand(2, 40, '3% to 6%'),
            SeverityBand(3, 60, '6% to 10%'),
            SeverityBand(4, 80, '10% to 20%'),
            SeverityBand(5, 100, 'Above 20% of EBITDA'),
        ),
    ),
    TriggerDefinition(
        code='51', key='real_estate_price_decline', layer='L3', name='Real-estate price decline',
        fires_when='Fall in the relevant transaction price index', baseline='Index 12-month change',
        bands=(
            SeverityBand(1, 20, '-3% to -7%'),
            SeverityBand(2, 40, '-7% to -12%'),
            SeverityBand(3, 60, '-12% to -20%'),
            SeverityBand(4, 80, '-20% to -30%'),
            SeverityBand(5, 100, 'Below -30%'),
        ),
    ),
    TriggerDefinition(
        code='52', key='sector_demand_contraction', layer='L3', name='Sector demand contraction',
        fires_when='Sector output, PMI or order book below trend', baseline='Sector indicator',
        bands=(
            SeverityBand(1, 20, 'PMI 48 to 50'),
            SeverityBand(2, 40, 'PMI 46 to 48'),
            SeverityBand(3, 60, 'PMI 44 to 46'),
            SeverityBand(4, 80, 'PMI 42 to 44'),
            SeverityBand(5, 100, 'PMI below 42'),
        ),
    ),
    TriggerDefinition(
        code='53', key='interest_rate_shock', layer='L3', name='Interest-rate shock',
        fires_when='Policy or benchmark rate move beyond the configured band', baseline='Own floating-rate exposure',
        bands=(
            SeverityBand(1, 20, 'Interest cost +5% to +10%'),
            SeverityBand(2, 40, '+10% to +20%'),
            SeverityBand(3, 60, '+20% to +35%'),
            SeverityBand(4, 80, '+35% to +50%'),
            SeverityBand(5, 100, 'Above +50%'),
        ),
    ),
    TriggerDefinition(
        code='54', key='geopolitical_or_trade_disruption', layer='L3', name='Geopolitical or trade disruption',
        fires_when='Event affecting a market material to the borrower', baseline='Revenue by market',
        bands=(
            SeverityBand(1, 20, 'Under 5% of revenue exposed'),
            SeverityBand(2, 40, '5% to 15%'),
            SeverityBand(3, 60, '15% to 30%'),
            SeverityBand(4, 80, '30% to 50%'),
            SeverityBand(5, 100, 'Above 50%'),
        ),
    ),
    TriggerDefinition(
        code='55', key='parent_company_deterioration', layer='L4', name='Parent company deterioration',
        fires_when='Adverse event or downgrade at the parent', baseline='Dependency weight',
        bands=(
            SeverityBand(1, 20, 'Parent contributes under 10% of support'),
            SeverityBand(2, 40, '10% to 25%'),
            SeverityBand(3, 60, '25% to 50%'),
            SeverityBand(4, 80, '50% to 75%'),
            SeverityBand(5, 100, 'Above 75%, or parent in default'),
        ),
    ),
    TriggerDefinition(
        code='56', key='group_or_sister_company_deterioration', layer='L4', name='Group or sister company deterioration',
        fires_when='Adverse event at a group entity', baseline='Cross-default and support links',
        bands=(
            SeverityBand(1, 20, 'No cross-default link'),
            SeverityBand(2, 40, 'Shared funding lines'),
            SeverityBand(3, 60, 'Cross-guarantee in place'),
            SeverityBand(4, 80, 'Cross-default clause exists'),
            SeverityBand(5, 100, 'Cross-default triggered'),
        ),
    ),
    TriggerDefinition(
        code='57', key='guarantor_deterioration', layer='L4', name='Guarantor deterioration',
        fires_when='Downgrade or adverse event at the guarantor', baseline='Guarantee coverage',
        bands=(
            SeverityBand(1, 20, 'Guarantee covers under 10% of exposure'),
            SeverityBand(2, 40, '10% to 25%'),
            SeverityBand(3, 60, '25% to 50%'),
            SeverityBand(4, 80, '50% to 75%'),
            SeverityBand(5, 100, 'Above 75%, or guarantor in default'),
        ),
    ),
    TriggerDefinition(
        code='58', key='key_supplier_distress', layer='L4', name='Key supplier distress',
        fires_when='Distress at a supplier the borrower depends on', baseline='Input dependency',
        bands=(
            SeverityBand(1, 20, 'Under 5% of input cost'),
            SeverityBand(2, 40, '5% to 15%'),
            SeverityBand(3, 60, '15% to 30%'),
            SeverityBand(4, 80, '30% to 50%'),
            SeverityBand(5, 100, 'Above 50%, no substitute available'),
        ),
    ),
    TriggerDefinition(
        code='59', key='key_customer_distress', layer='L4', name='Key customer distress',
        fires_when='Distress at a customer material to the revenue base', baseline='Revenue dependency',
        bands=(
            SeverityBand(1, 20, 'Under 5% of revenue'),
            SeverityBand(2, 40, '5% to 15%'),
            SeverityBand(3, 60, '15% to 30%'),
            SeverityBand(4, 80, '30% to 50%'),
            SeverityBand(5, 100, 'Above 50% of revenue'),
        ),
    ),
    TriggerDefinition(
        code='60', key='ownership_or_control_change', layer='L4', name='Ownership or control change',
        fires_when='Change in ultimate beneficial ownership', baseline='Ownership register',
        bands=(
            SeverityBand(1, 20, 'Minority stake change'),
            SeverityBand(2, 40, 'Change above 25%'),
            SeverityBand(3, 60, 'Change of control'),
            SeverityBand(4, 80, 'New owner is unrated or opaque'),
            SeverityBand(5, 100, 'New owner is a distressed or listed party'),
        ),
    ),
    TriggerDefinition(
        code='61', key='common_officers_with_a_distressed_entity', layer='L4', name='Common officers with a distressed entity',
        fires_when='Shared directors or shareholders with a defaulted entity', baseline='Network graph',
        bands=(
            SeverityBand(1, 20, 'One shared non-executive'),
            SeverityBand(2, 40, 'One shared executive'),
            SeverityBand(3, 60, 'Shared controlling shareholder'),
            SeverityBand(4, 80, 'Shared control plus common funding'),
            SeverityBand(5, 100, 'Shared control with the defaulted entity'),
        ),
    ),
    TriggerDefinition(
        code='62', key='dso_deterioration_against_a_named_counterparty', layer='L4', name='DSO deterioration against a named counterparty',
        fires_when='Days sales outstanding for one debtor rises materially', baseline='Own 12-month DSO for that debtor',
        bands=(
            SeverityBand(1, 20, '+10 to +20 days'),
            SeverityBand(2, 40, '+20 to +35 days'),
            SeverityBand(3, 60, '+35 to +60 days'),
            SeverityBand(4, 80, '+60 to +90 days'),
            SeverityBand(5, 100, 'Over +90 days, or written off'),
        ),
    ),
    TriggerDefinition(
        code='63', key='receivable_ageing_at_a_distressed_customer', layer='L4', name='Receivable ageing at a distressed customer',
        fires_when='Receivables owed by a debtor already flagged as distressed', baseline='Receivable ledger',
        bands=(
            SeverityBand(1, 20, 'Under 5% of receivables'),
            SeverityBand(2, 40, '5% to 15%'),
            SeverityBand(3, 60, '15% to 30%'),
            SeverityBand(4, 80, '30% to 50%'),
            SeverityBand(5, 100, 'Above 50% of receivables'),
        ),
    ),
    TriggerDefinition(
        code='64', key='tier_2_supplier_distress', layer='L4', name='Tier-2 supplier distress',
        fires_when='Distress at a supplier of a critical supplier', baseline='Propagated, 2 hops',
        bands=(
            SeverityBand(1, 20, 'Alternate tier-2 sources exist'),
            SeverityBand(2, 40, 'Limited alternates'),
            SeverityBand(3, 60, 'Requalification needed'),
            SeverityBand(4, 80, 'Single tier-2 source'),
            SeverityBand(5, 100, 'Single source and no substitute at tier 1'),
        ),
    ),
    TriggerDefinition(
        code='65', key='customer_of_customer_distress', layer='L4', name='Customer-of-customer distress',
        fires_when='Distress at the offtaker of a key customer', baseline='Propagated, 2 hops',
        bands=(
            SeverityBand(1, 20, 'Customer has a diversified offtake base'),
            SeverityBand(2, 40, 'Some concentration'),
            SeverityBand(3, 60, 'Material concentration'),
            SeverityBand(4, 80, 'Heavy concentration'),
            SeverityBand(5, 100, 'Single offtaker at both hops'),
        ),
    ),
    TriggerDefinition(
        code='66', key='logistics_route_disruption', layer='L4', name='Logistics route disruption',
        fires_when='Interruption to a port, corridor or carrier the borrower depends on', baseline='Route dependency',
        bands=(
            SeverityBand(1, 20, 'Alternate routes at similar cost'),
            SeverityBand(2, 40, 'Alternate at higher cost'),
            SeverityBand(3, 60, 'Alternate with delay'),
            SeverityBand(4, 80, 'Severely constrained'),
            SeverityBand(5, 100, 'No practical alternate route'),
        ),
    ),
    TriggerDefinition(
        code='67', key='cross_default_relationship_triggered', layer='L4', name='Cross-default relationship triggered',
        fires_when='A cross-default clause is engaged by another exposure', baseline='Facility documentation',
        bands=(
            SeverityBand(1, 20, 'Notified, not called'),
            SeverityBand(2, 40, 'Cure period running'),
            SeverityBand(3, 60, 'Cure period expired'),
            SeverityBand(4, 80, 'Acceleration threatened'),
            SeverityBand(5, 100, 'Acceleration served'),
        ),
    ),
)

BY_KEY: dict[str, TriggerDefinition] = {t.key: t for t in TRIGGER_DEFINITIONS}
assert len(TRIGGER_DEFINITIONS) == 67

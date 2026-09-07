"""The 35 Version 2 classifiers, and the one verdict they aggregate into.

Source of truth: CreditProbe Early Warning Framework Version 2 workbook,
Tab 2 ("Classifiers"). Every weight, band boundary and basis string below is
transcribed verbatim from that tab — this module does not re-derive, round,
or "improve" any of it. Where an earlier design conversation described a
different mechanism (22 weighted sub-category nodes, a worst-of rollup), the
workbook does not implement that mechanism, and this module implements the
workbook.

The mechanism, exactly as Tab 2 defines it
-------------------------------------------
Classifiers are reviewed periodically and never re-scored daily. They do not
raise alerts on their own; they set how seriously a live trigger is read
(combined in `combination.py`). Every classifier has five bands, scored on a
fixed convention: VERY LOW=0, LOW=25, MEDIUM=50, HIGH=75, VERY HIGH=100. Each
classifier carries its own weight (0-100, the 35 weights sum to exactly 100),
and the whole-borrower classifier vulnerability score is a **plain weighted
sum** — nothing more elaborate:

    classifier_vulnerability_score = SUM(weight_i * band_score_i) / 100

Tab 2 Section B's worked example: with the band selections given there
(rating HIGH, PD HIGH, headroom MEDIUM, IFRS9 HIGH, ECL MEDIUM, DPD MEDIUM,
DSCR VERY HIGH, interest cover HIGH, leverage HIGH, gearing MEDIUM, current
ratio MEDIUM, quick ratio MEDIUM, EBITDA margin MEDIUM, cash cycle MEDIUM,
revenue trend MEDIUM, collateral HIGH, LTV MEDIUM, covenant headroom HIGH,
utilisation HIGH, unsecured MEDIUM, single-name LOW, group LOW, sector HIGH,
size HIGH, statement quality LOW, country LOW, guarantor MEDIUM, buyer
concentration HIGH, project MEDIUM, tenure LOW, supplier concentration HIGH,
single-source HIGH, switching time HIGH, receivable concentration MEDIUM,
edge confidence LOW), the score is **62** and the verdict is **HIGH RISK**.
`test_classifiers_v2.py` reproduces this exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

METHODOLOGY_VERSION = "ews-v2.0.0"

BAND_ORDER: tuple[str, ...] = ("VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH")
BAND_SCORE: dict[str, int] = {
    "VERY_LOW": 0, "LOW": 25, "MEDIUM": 50, "HIGH": 75, "VERY_HIGH": 100,
}
BAND_LABEL: dict[str, str] = {
    "VERY_LOW": "VERY LOW RISK", "LOW": "LOW RISK", "MEDIUM": "MEDIUM RISK",
    "HIGH": "HIGH RISK", "VERY_HIGH": "VERY HIGH RISK",
}


@dataclass(frozen=True)
class Band:
    """One of a classifier's five bands. `label` is the workbook's own
    description of what falls in that band (e.g. "AAA to A- (grades 1-3)")."""

    code: str
    score: int
    label: str


@dataclass(frozen=True)
class ClassifierDefinition:
    """One row of Tab 2. `code` is the workbook's own row number (1-35),
    kept so a finding can be traced back to the exact cell it came from."""

    code: str
    key: str
    layer: str
    name: str
    unit_basis: str
    weight: float
    bands: tuple[Band, Band, Band, Band, Band]
    basis: str

    def band(self, code: str) -> Band:
        for b in self.bands:
            if b.code == code:
                return b
        raise KeyError(f"{self.key}: no such band {code!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "key": self.key, "layer": self.layer,
            "name": self.name, "unit_basis": self.unit_basis,
            "weight": self.weight, "basis": self.basis,
            "bands": [{"code": b.code, "score": b.score, "label": b.label}
                      for b in self.bands],
        }


# ---------------------------------------------------------------------------
# The 35 classifiers, transcribed verbatim from Tab 2 rows 7-41.
# ---------------------------------------------------------------------------

CLASSIFIER_DEFINITIONS: tuple[ClassifierDefinition, ...] = (
    ClassifierDefinition(
        code='1', key='internal_rating_level', layer='L2', name='Internal rating (level)',
        unit_basis='Bank masterscale mapped to S&P equivalent', weight=6.0,
        bands=(
            Band("VERY_LOW", 0, 'AAA to A- (grades 1-3)'),
            Band("LOW", 25, 'BBB+ to BBB- (4-5)'),
            Band("MEDIUM", 50, 'BB+ to BB- (6-7)'),
            Band("HIGH", 75, 'B+ to B- (8-9)'),
            Band("VERY_HIGH", 100, 'CCC+ and below, or defaulted'),
        ),
        basis='S&P Global Ratings scale. Investment / sub-investment boundary sits between BBB- and BB+.',
    ),
    ClassifierDefinition(
        code='2', key='pd_12m_level', layer='L2', name='12-month PD (level)',
        unit_basis='Percent', weight=4.0,
        bands=(
            Band("VERY_LOW", 0, '< 0.15%'),
            Band("LOW", 25, '0.15% to 0.60%'),
            Band("MEDIUM", 50, '0.60% to 3.0%'),
            Band("HIGH", 75, '3.0% to 10%'),
            Band("VERY_HIGH", 100, '> 10%'),
        ),
        basis='S&P long-run average one-year default rates, 1981-2023: approximately 0.0% AAA, 0.2% BBB, 0.6% BB, 3.0% B, 26% CCC/C.',
    ),
    ClassifierDefinition(
        code='3', key='rating_headroom_to_sub_investment_grade', layer='L2', name='Rating headroom to sub-investment grade',
        unit_basis='Notches', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, '6 or more'),
            Band("LOW", 25, '4 to 5'),
            Band("MEDIUM", 50, '2 to 3'),
            Band("HIGH", 75, '1'),
            Band("VERY_HIGH", 100, '0, or already sub-investment grade'),
        ),
        basis='Derived from the S&P scale. Measures how much rating cushion exists before a forced repricing or mandate breach.',
    ),
    ClassifierDefinition(
        code='4', key='ifrs9_stage', layer='L2', name='IFRS 9 stage',
        unit_basis='Stage', weight=6.0,
        bands=(
            Band("VERY_LOW", 0, 'Stage 1, low credit risk exemption applied'),
            Band("LOW", 25, 'Stage 1, on internal watch'),
            Band("MEDIUM", 50, 'Stage 2, no days past due'),
            Band("HIGH", 75, 'Stage 2 with 30+ DPD'),
            Band("VERY_HIGH", 100, 'Stage 3, credit-impaired'),
        ),
        basis='IFRS 9 paragraph 5.5.11 rebuttable presumption of significant increase in credit risk at 30 days past due; 5.5.19 / B5.5.37 default presumption at 90 days.',
    ),
    ClassifierDefinition(
        code='5', key='ecl_coverage', layer='L2', name='ECL coverage',
        unit_basis='ECL as % of EAD', weight=3.0,
        bands=(
            Band("VERY_LOW", 0, '< 0.25%'),
            Band("LOW", 25, '0.25% to 1%'),
            Band("MEDIUM", 50, '1% to 5%'),
            Band("HIGH", 75, '5% to 20%'),
            Band("VERY_HIGH", 100, '> 20%'),
        ),
        basis='Calibrated to the stage structure above rather than to an external benchmark. Bank should re-fit to its own portfolio distribution.',
    ),
    ClassifierDefinition(
        code='6', key='days_past_due_current', layer='L2', name='Days past due (current)',
        unit_basis='Days', weight=5.0,
        bands=(
            Band("VERY_LOW", 0, '0'),
            Band("LOW", 25, '1 to 7'),
            Band("MEDIUM", 50, '8 to 29'),
            Band("HIGH", 75, '30 to 89'),
            Band("VERY_HIGH", 100, '90 or more'),
        ),
        basis='IFRS 9 30 / 90 day presumptions. CBUAE Circular 28/2010 classifies at 90 days past due and requires a watch-list category below that.',
    ),
    ClassifierDefinition(
        code='7', key='dscr', layer='L2', name='DSCR',
        unit_basis='Times', weight=5.0,
        bands=(
            Band("VERY_LOW", 0, '> 2.00x'),
            Band("LOW", 25, '1.50x to 2.00x'),
            Band("MEDIUM", 50, '1.25x to 1.50x'),
            Band("HIGH", 75, '1.00x to 1.25x'),
            Band("VERY_HIGH", 100, '< 1.00x'),
        ),
        basis='Market convention: 1.20x to 1.25x is the standard maintenance covenant floor in corporate and project facilities. Below 1.00x cash flow does not cover debt service.',
    ),
    ClassifierDefinition(
        code='8', key='interest_coverage_ebit_interest', layer='L2', name='Interest coverage (EBIT / interest)',
        unit_basis='Times', weight=4.0,
        bands=(
            Band("VERY_LOW", 0, '> 6.50x'),
            Band("LOW", 25, '4.25x to 6.50x'),
            Band("MEDIUM", 50, '2.50x to 4.25x'),
            Band("HIGH", 75, '1.50x to 2.50x'),
            Band("VERY_HIGH", 100, '< 1.50x'),
        ),
        basis='Damodaran synthetic rating table for large-cap non-financial firms: >8.50x AAA, 4.25-5.50x A, 2.50-3.00x BBB, 1.50-1.75x B, 0.80-1.25x CCC.',
    ),
    ClassifierDefinition(
        code='9', key='leverage_net_debt_ebitda', layer='L2', name='Leverage (net debt / EBITDA)',
        unit_basis='Times', weight=5.0,
        bands=(
            Band("VERY_LOW", 0, '< 1.5x'),
            Band("LOW", 25, '1.5x to 3.0x'),
            Band("MEDIUM", 50, '3.0x to 4.5x'),
            Band("HIGH", 75, '4.5x to 6.0x'),
            Band("VERY_HIGH", 100, '> 6.0x'),
        ),
        basis="2013 US Interagency Guidance on Leveraged Lending: 4x total debt / EBITDA defines a leveraged transaction, above 6x 'raises concerns for most industries'. The guidance was rescinded by the OCC and FDIC in December 2025; the 6x reference remains widely used as internal policy.",
    ),
    ClassifierDefinition(
        code='10', key='gearing_total_debt_equity', layer='L2', name='Gearing (total debt / equity)',
        unit_basis='Times', weight=3.0,
        bands=(
            Band("VERY_LOW", 0, '< 0.50x'),
            Band("LOW", 25, '0.50x to 1.00x'),
            Band("MEDIUM", 50, '1.00x to 2.00x'),
            Band("HIGH", 75, '2.00x to 3.00x'),
            Band("VERY_HIGH", 100, '> 3.00x or negative equity'),
        ),
        basis='Market convention. Negative equity is treated as the worst band irrespective of the computed ratio.',
    ),
    ClassifierDefinition(
        code='11', key='current_ratio', layer='L2', name='Current ratio',
        unit_basis='Times', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, '> 2.00'),
            Band("LOW", 25, '1.50 to 2.00'),
            Band("MEDIUM", 50, '1.20 to 1.50'),
            Band("HIGH", 75, '1.00 to 1.20'),
            Band("VERY_HIGH", 100, '< 1.00'),
        ),
        basis='Standard working capital convention. Below 1.00 current liabilities exceed current assets. Sector-relative adjustment recommended.',
    ),
    ClassifierDefinition(
        code='12', key='quick_ratio', layer='L2', name='Quick ratio',
        unit_basis='Times', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, '> 1.50'),
            Band("LOW", 25, '1.20 to 1.50'),
            Band("MEDIUM", 50, '0.90 to 1.20'),
            Band("HIGH", 75, '0.70 to 0.90'),
            Band("VERY_HIGH", 100, '< 0.70'),
        ),
        basis='Standard liquidity convention, inventory excluded. Most relevant for trading and contracting borrowers.',
    ),
    ClassifierDefinition(
        code='13', key='ebitda_margin_vs_sector_median', layer='L2', name='EBITDA margin vs sector median',
        unit_basis='Relative %', weight=3.0,
        bands=(
            Band("VERY_LOW", 0, 'More than 25% above sector median'),
            Band("LOW", 25, '10% to 25% above'),
            Band("MEDIUM", 50, 'Within +/- 10% of median'),
            Band("HIGH", 75, '10% to 25% below'),
            Band("VERY_HIGH", 100, 'More than 25% below, or negative'),
        ),
        basis="Relative rather than absolute, because absolute margin is not comparable across sectors. Sector median from the bank's own portfolio or a sector data provider.",
    ),
    ClassifierDefinition(
        code='14', key='cash_conversion_cycle', layer='L2', name='Cash conversion cycle',
        unit_basis='Days (sector-relative)', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, '< 30'),
            Band("LOW", 25, '30 to 60'),
            Band("MEDIUM", 50, '60 to 90'),
            Band("HIGH", 75, '90 to 150'),
            Band("VERY_HIGH", 100, '> 150'),
        ),
        basis='Working capital convention. Bands must be re-cut per sector: contracting and trading borrowers run structurally longer cycles.',
    ),
    ClassifierDefinition(
        code='15', key='revenue_trend_3y_cagr', layer='L2', name='Revenue trend (3-year CAGR)',
        unit_basis='Percent', weight=3.0,
        bands=(
            Band("VERY_LOW", 0, '> +10%'),
            Band("LOW", 25, '0% to +10%'),
            Band("MEDIUM", 50, '-5% to 0%'),
            Band("HIGH", 75, '-15% to -5%'),
            Band("VERY_HIGH", 100, '< -15%'),
        ),
        basis='Market convention. Should be read against sector growth, not in isolation.',
    ),
    ClassifierDefinition(
        code='16', key='collateral_coverage', layer='L2', name='Collateral coverage',
        unit_basis='Eligible collateral / exposure', weight=4.0,
        bands=(
            Band("VERY_LOW", 0, '> 150%'),
            Band("LOW", 25, '125% to 150%'),
            Band("MEDIUM", 50, '100% to 125%'),
            Band("HIGH", 75, '70% to 100%'),
            Band("VERY_HIGH", 100, '< 70%'),
        ),
        basis='Convention reflecting haircut practice. CBUAE Credit Risk Management Standards apply haircuts to collateral before it can reduce the provisioning floor.',
    ),
    ClassifierDefinition(
        code='17', key='ltv_real_estate_secured', layer='L2', name='Loan to value (real estate secured)',
        unit_basis='Percent', weight=3.0,
        bands=(
            Band("VERY_LOW", 0, '< 50%'),
            Band("LOW", 25, '50% to 65%'),
            Band("MEDIUM", 50, '65% to 75%'),
            Band("HIGH", 75, '75% to 85%'),
            Band("VERY_HIGH", 100, '> 85%'),
        ),
        basis="SAMA caps residential LTV at 70% for banks (second and subsequent homes) and 90% for a citizen's first home. CBUAE Circular 31/2013 caps at 85% for UAE nationals and 80% for expatriates on a first property up to AED 5m.",
    ),
    ClassifierDefinition(
        code='18', key='covenant_headroom', layer='L2', name='Covenant headroom',
        unit_basis='Percent to tightest covenant', weight=3.0,
        bands=(
            Band("VERY_LOW", 0, '> 30%'),
            Band("LOW", 25, '15% to 30%'),
            Band("MEDIUM", 50, '5% to 15%'),
            Band("HIGH", 75, '0% to 5%'),
            Band("VERY_HIGH", 100, 'Breached or waived'),
        ),
        basis='Market convention. A waiver is treated as a breach for early warning purposes, because the underlying condition has not been cured.',
    ),
    ClassifierDefinition(
        code='19', key='facility_utilisation_12m_avg', layer='L2', name='Facility utilisation (12-month average)',
        unit_basis='Percent', weight=3.0,
        bands=(
            Band("VERY_LOW", 0, '< 40%'),
            Band("LOW", 25, '40% to 60%'),
            Band("MEDIUM", 50, '60% to 80%'),
            Band("HIGH", 75, '80% to 95%'),
            Band("VERY_HIGH", 100, '> 95%'),
        ),
        basis='The level is structural. A change in utilisation is a trigger and is scored in Tab 3.',
    ),
    ClassifierDefinition(
        code='20', key='unsecured_share_of_exposure', layer='L2', name='Unsecured share of exposure',
        unit_basis='Percent of EAD', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, '< 10%'),
            Band("LOW", 25, '10% to 30%'),
            Band("MEDIUM", 50, '30% to 50%'),
            Band("HIGH", 75, '50% to 75%'),
            Band("VERY_HIGH", 100, '> 75%'),
        ),
        basis='Derived from the collateral coverage convention above. Drives loss given default rather than probability of default.',
    ),
    ClassifierDefinition(
        code='21', key='single_name_exposure_pct_tier1', layer='L2', name='Single-name exposure as % of Tier 1',
        unit_basis='Percent', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, '< 2.5%'),
            Band("LOW", 25, '2.5% to 5%'),
            Band("MEDIUM", 50, '5% to 10%'),
            Band("HIGH", 75, '10% to 15%'),
            Band("VERY_HIGH", 100, '> 15%'),
        ),
        basis='Basel Committee Large Exposures framework caps a single counterparty at 25% of Tier 1 capital. Early warning bands are set well inside the hard limit.',
    ),
    ClassifierDefinition(
        code='22', key='group_connected_exposure_pct_tier1', layer='L2', name='Group / connected exposure as % of Tier 1',
        unit_basis='Percent', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, '< 5%'),
            Band("LOW", 25, '5% to 10%'),
            Band("MEDIUM", 50, '10% to 15%'),
            Band("HIGH", 75, '15% to 20%'),
            Band("VERY_HIGH", 100, '> 20%'),
        ),
        basis='Same Basel Large Exposures basis, applied to the connected counterparty group.',
    ),
    ClassifierDefinition(
        code='23', key='sector_vulnerability_grade', layer='L2', name='Sector vulnerability grade',
        unit_basis='Internal grade 1-5', weight=3.0,
        bands=(
            Band("VERY_LOW", 0, '1, resilient'),
            Band("LOW", 25, '2, stable'),
            Band("MEDIUM", 50, '3, neutral'),
            Band("HIGH", 75, '4, under pressure'),
            Band("VERY_HIGH", 100, '5, stressed'),
        ),
        basis='Internal sector scorecard, refreshed quarterly from the macro and sector sources in Tabs 5 and 6.',
    ),
    ClassifierDefinition(
        code='24', key='borrower_size_segment', layer='L2', name='Borrower size / segment',
        unit_basis='Segment', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, 'Large corporate with diversified funding'),
            Band("LOW", 25, 'Corporate'),
            Band("MEDIUM", 50, 'Mid corporate'),
            Band("HIGH", 75, 'SME'),
            Band("VERY_HIGH", 100, 'Micro / start-up'),
        ),
        basis='Smaller borrowers have thinner liquidity buffers and fewer refinancing options, so the same behavioural deterioration carries more weight.',
    ),
    ClassifierDefinition(
        code='25', key='financial_statement_quality', layer='L2', name='Financial statement quality',
        unit_basis='Auditor and opinion', weight=3.0,
        bands=(
            Band("VERY_LOW", 0, 'Big-four audited, unqualified, under 6 months old'),
            Band("LOW", 25, 'Audited, unqualified'),
            Band("MEDIUM", 50, 'Audited with emphasis of matter'),
            Band("HIGH", 75, 'Qualified opinion'),
            Band("VERY_HIGH", 100, 'Unaudited, or over 12 months overdue'),
        ),
        basis='Information risk. CBUAE and SAMA both require documented evidence supporting classification decisions; stale or qualified statements weaken every other classifier.',
    ),
    ClassifierDefinition(
        code='26', key='country_jurisdiction_risk', layer='L2', name='Country / jurisdiction risk',
        unit_basis='Sovereign rating of the operating jurisdiction', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, 'AA- and above'),
            Band("LOW", 25, 'A- to A+'),
            Band("MEDIUM", 50, 'BBB- to BBB+'),
            Band("HIGH", 75, 'BB- to BB+'),
            Band("VERY_HIGH", 100, 'B+ and below'),
        ),
        basis='Sovereign scale from the recognised agencies. Captures transfer and convertibility risk where revenue or assets sit outside the home jurisdiction.',
    ),
    ClassifierDefinition(
        code='27', key='guarantor_capacity', layer='L4', name='Guarantor capacity',
        unit_basis='Relative strength', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, 'Guarantor 3 or more notches stronger, unconditional'),
            Band("LOW", 25, '2 notches stronger'),
            Band("MEDIUM", 50, 'Comparable strength'),
            Band("HIGH", 75, 'Weaker than the borrower'),
            Band("VERY_HIGH", 100, 'No effective guarantee, or guarantor distressed'),
        ),
        basis='Credit support convention. A guarantee only improves the classifier if the guarantor is measurably stronger and the guarantee is enforceable.',
    ),
    ClassifierDefinition(
        code='28', key='buyer_concentration_top3', layer='L4', name='Buyer concentration (top three customers)',
        unit_basis='Percent of revenue', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, '< 20%'),
            Band("LOW", 25, '20% to 35%'),
            Band("MEDIUM", 50, '35% to 50%'),
            Band("HIGH", 75, '50% to 70%'),
            Band("VERY_HIGH", 100, '> 70%'),
        ),
        basis='Concentration convention. Drives the Layer 4 contagion path: distress at one named customer becomes material to the borrower.',
    ),
    ClassifierDefinition(
        code='29', key='project_dependency', layer='L4', name='Project dependency',
        unit_basis='Percent of revenue in one project', weight=1.0,
        bands=(
            Band("VERY_LOW", 0, '< 15%'),
            Band("LOW", 25, '15% to 30%'),
            Band("MEDIUM", 50, '30% to 50%'),
            Band("HIGH", 75, '50% to 70%'),
            Band("VERY_HIGH", 100, '> 70%'),
        ),
        basis='Contracting and project-finance convention. Sets how much weight a single project delay carries as an indirect trigger.',
    ),
    ClassifierDefinition(
        code='30', key='relationship_tenure_and_history', layer='L2', name='Relationship tenure and history',
        unit_basis='Years and history', weight=1.0,
        bands=(
            Band("VERY_LOW", 0, 'Over 5 years, clean record'),
            Band("LOW", 25, '3 to 5 years, clean'),
            Band("MEDIUM", 50, '1 to 3 years'),
            Band("HIGH", 75, 'Under 1 year'),
            Band("VERY_HIGH", 100, 'Prior restructuring or default'),
        ),
        basis='Behavioural history convention. A borrower with a prior restructuring re-enters distress more readily.',
    ),
    ClassifierDefinition(
        code='31', key='supplier_concentration', layer='L4', name='Supplier concentration',
        unit_basis='Top three suppliers as % of input cost', weight=3.0,
        bands=(
            Band("VERY_LOW", 0, '< 20%'),
            Band("LOW", 25, '20% to 35%'),
            Band("MEDIUM", 50, '35% to 50%'),
            Band("HIGH", 75, '50% to 70%'),
            Band("VERY_HIGH", 100, '> 70%'),
        ),
        basis='Mirror of the buyer concentration convention. Upstream concentration was absent from the first version of this framework and is the more common driver of contracting and manufacturing distress.',
    ),
    ClassifierDefinition(
        code='32', key='single_source_dependency_and_substitutability', layer='L4', name='Single-source dependency and substitutability',
        unit_basis='Availability of qualified alternates', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, 'Multiple qualified alternates'),
            Band("LOW", 25, '2 to 3 alternates'),
            Band("MEDIUM", 50, 'Limited, requalification needed'),
            Band("HIGH", 75, 'One practical alternate'),
            Band("VERY_HIGH", 100, 'Single source, no substitute'),
        ),
        basis='Determines whether a supplier failure is an inconvenience or a stoppage. Applied as a modifier to the dependency weight in Tab 4b.',
    ),
    ClassifierDefinition(
        code='33', key='switching_time_alternative_supplier', layer='L4', name='Switching time to an alternative supplier',
        unit_basis='Months', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, '< 1 month'),
            Band("LOW", 25, '1 to 3 months'),
            Band("MEDIUM", 50, '3 to 6 months'),
            Band("HIGH", 75, '6 to 12 months'),
            Band("VERY_HIGH", 100, '> 12 months'),
        ),
        basis='Sets how long the borrower is exposed after an upstream failure, and therefore the lag the accelerator should expect.',
    ),
    ClassifierDefinition(
        code='34', key='receivable_concentration_by_counterparty', layer='L4', name='Receivable concentration by counterparty',
        unit_basis='Largest single debtor as % of trade receivables', weight=2.0,
        bands=(
            Band("VERY_LOW", 0, '< 10%'),
            Band("LOW", 25, '10% to 20%'),
            Band("MEDIUM", 50, '20% to 35%'),
            Band("HIGH", 75, '35% to 50%'),
            Band("VERY_HIGH", 100, '> 50%'),
        ),
        basis='The fastest downstream transmission path. A distressed customer converts directly into a collectability problem on receivables already booked.',
    ),
    ClassifierDefinition(
        code='35', key='relationship_edge_confidence', layer='L4', name='Relationship edge confidence',
        unit_basis='Verification status of modelled links', weight=1.0,
        bands=(
            Band("VERY_LOW", 0, 'All key links verified from official records'),
            Band("LOW", 25, 'Key links verified, minor gaps'),
            Band("MEDIUM", 50, 'Mix of verified and inferred links'),
            Band("HIGH", 75, 'Mostly inferred from news or filings'),
            Band("VERY_HIGH", 100, 'Unverified or stale relationship data'),
        ),
        basis="Governance. An unverified edge must not move a borrower's band. Feeds the edge confidence factor in the Tab 4b propagation formula.",
    ),
)

BY_KEY: dict[str, ClassifierDefinition] = {c.key: c for c in CLASSIFIER_DEFINITIONS}
TOTAL_WEIGHT: float = sum(c.weight for c in CLASSIFIER_DEFINITIONS)
assert abs(TOTAL_WEIGHT - 100.0) < 1e-9, f"classifier weights must sum to 100, got {TOTAL_WEIGHT}"


def verdict_band(score: float) -> str:
    """Tab 2 Section C band scale."""
    if score < 20.0:
        return "VERY_LOW"
    if score < 40.0:
        return "LOW"
    if score < 60.0:
        return "MEDIUM"
    if score < 80.0:
        return "HIGH"
    return "VERY_HIGH"


@dataclass(frozen=True)
class ClassifierResult:
    key: str
    band: str
    band_score: int
    weight: float
    weighted_contribution: float


@dataclass(frozen=True)
class ClassifierVerdict:
    score: float
    band: str
    results: tuple[ClassifierResult, ...]
    overrides_applied: tuple[str, ...]


def score_classifiers(
    band_selections: dict[str, str],
    *,
    ifrs9_stage: int | None = None,
    dpd: int | None = None,
    confirmed_sanctions_match: bool = False,
    unwaived_covenant_breach: bool = False,
    negative_equity: bool = False,
    statements_unaudited_or_over_18m: bool = False,
    guarantor_in_default_load_bearing: bool = False,
) -> ClassifierVerdict:
    """Tab 2 Sections B and C: weighted sum, then the objective override table.

    `band_selections` maps classifier key -> band code ("VERY_LOW".."VERY_HIGH")
    for every classifier that has a value this period. A classifier missing
    from the mapping is excluded from both the numerator and the 100-point
    denominator (its weight is dropped, not defaulted to a band) — this
    mirrors the workbook's own instruction that every yellow cell "is the
    only input" and an unpopulated one is not silently zero.
    """
    results: list[ClassifierResult] = []
    weighted_total = 0.0
    weight_total = 0.0
    for cdef in CLASSIFIER_DEFINITIONS:
        band_code = band_selections.get(cdef.key)
        if band_code is None:
            continue
        band = cdef.band(band_code)
        contribution = cdef.weight * band.score / 100.0
        results.append(ClassifierResult(
            key=cdef.key, band=band_code, band_score=band.score,
            weight=cdef.weight, weighted_contribution=contribution,
        ))
        weighted_total += contribution
        weight_total += cdef.weight

    # Re-normalise to the weight actually observed this period, so a missing
    # classifier does not silently drag the score toward zero.
    score = (weighted_total / weight_total * 100.0) if weight_total > 0 else 0.0
    band = verdict_band(score)
    overrides: list[str] = []

    # Tab 2 Section C overrides, verbatim.
    if (ifrs9_stage is not None and ifrs9_stage >= 3) or (dpd is not None and dpd >= 90):
        band = "VERY_HIGH"
        overrides.append("ifrs9_stage3_or_90dpd_forces_very_high")
    if confirmed_sanctions_match:
        band = "VERY_HIGH"
        overrides.append("confirmed_sanctions_forces_very_high_and_escalation")
    if unwaived_covenant_breach and BAND_SCORE[band] < BAND_SCORE["HIGH"]:
        band = "HIGH"
        overrides.append("unwaived_covenant_breach_floors_high")
    if negative_equity and BAND_SCORE[band] < BAND_SCORE["HIGH"]:
        band = "HIGH"
        overrides.append("negative_equity_floors_high")
    if statements_unaudited_or_over_18m and BAND_SCORE[band] < BAND_SCORE["MEDIUM"]:
        band = "MEDIUM"
        overrides.append("stale_or_unaudited_statements_floors_medium")
    if guarantor_in_default_load_bearing:
        # Not a whole-classifier-score override: forces the guarantor_capacity
        # classifier itself to band 5 (VERY_HIGH). Recorded here as a flag for
        # the caller to also re-run guarantor_capacity at VERY_HIGH if it
        # wasn't already, since it changes the weighted sum too.
        overrides.append("guarantor_in_default_forces_guarantor_capacity_very_high")

    return ClassifierVerdict(
        score=round(score, 6), band=band,
        results=tuple(results), overrides_applied=tuple(overrides),
    )

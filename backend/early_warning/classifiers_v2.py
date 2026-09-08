"""The 23 Version 2 classifiers, grouped into 8 sub-categories, and the
Classifier dimension they roll up into.

Source of truth: the corrected CreditProbe Early Warning Framework Version 2
workbook (15-sheet edition), Tab 03 ("Classifiers"). This replaces an earlier
implementation built against a different, incorrect workbook draft that
scored 35 classifiers with a flat weighted sum — that model does not exist
in the actual workbook and has been removed, not preserved for
compatibility.

The mechanism, exactly as Tab 03 defines it
--------------------------------------------
Classifiers are reviewed periodically, not daily; they measure how
vulnerable an obligor is structurally, never what is currently happening
(that is the Trigger and Accelerator side, `aggregation.py`). Every
classifier has five bands scored on the fixed convention VERY_LOW=0,
LOW=25, MEDIUM=50, HIGH=75, VERY_HIGH=100.

Classifiers are NOT combined by a flat weighted sum. They are grouped into
8 sub-categories (7 in Layer 2, 1 in Layer 4 — Tab 03 Section A), each with
its own stated combination rule:

  - Sub-categories whose members are collinear (measuring the same
    underlying construct) combine WORST-OF, plus a bounded corroboration
    uplift (`subcategory.py::worst_of_with_uplift`).
  - Sub-categories whose members are genuinely independent combine by
    WEIGHTED BLEND, using the member weights published in Tab 03 Section B.

The 7 Layer-2 sub-category scores roll up into L2-C via the weights in
Tab 03 Section A; Layer 4's single sub-category (L4.4, Network fragility)
IS L4-C directly. The final Classifier dimension score is a weighted blend
of L2-C and L4-C at the published layer weights, **L2 0.85 / L4 0.15**
(Tab 06 Section C Step 3) — never a flat sum across all 23 classifiers.

Overrides (Tab 03 Section C) sit outside the score entirely and are applied
after the roll-up, in the order below (later entries win where they
conflict): Stage 3 or 90+ DPD forces VERY_HIGH; a confirmed sanctions match
forces VERY_HIGH and routes to compliance; an unwaived covenant breach
floors HIGH; negative equity floors HIGH (gearing was dropped for
collinearity in Tab 02, and this override is what's retained in its place);
unaudited or 18+ month-old statements floor MEDIUM; a guarantor in default
on a load-bearing guarantee forces the guarantor_capacity classifier itself
to VERY_HIGH (applied before the roll-up, since it changes an input band
rather than the final score).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.early_warning import subcategory as sc

METHODOLOGY_VERSION = "ews-v2.1.0"

BAND_ORDER: tuple[str, ...] = ("VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH")
BAND_SCORE: dict[str, int] = {
    "VERY_LOW": 0, "LOW": 25, "MEDIUM": 50, "HIGH": 75, "VERY_HIGH": 100,
}
BAND_LABEL: dict[str, str] = {
    "VERY_LOW": "VERY LOW RISK", "LOW": "LOW RISK", "MEDIUM": "MEDIUM RISK",
    "HIGH": "HIGH RISK", "VERY_HIGH": "VERY HIGH RISK",
}

#: Classifier layer weights combining L2-C and L4-C into the Classifier
#: dimension (Tab 06 Section C Step 3).
CLASSIFIER_LAYER_WEIGHTS: dict[str, float] = {"L2": 0.85, "L4": 0.15}


@dataclass(frozen=True)
class Band:
    code: str
    score: int
    label: str


@dataclass(frozen=True)
class ClassifierDefinition:
    """One row of Tab 03 Section B. `code` is the workbook's own running
    number (1-23); `sub_category_code` places it in one of the 8 Tab 03
    Section A sub-categories."""

    code: str
    key: str
    sub_category_code: str
    layer: str
    name: str
    unit_basis: str
    bands: tuple[Band, Band, Band, Band, Band]
    basis: str
    #: Weight WITHIN its sub-category — only meaningful when that
    #: sub-category's rule is BLEND (Tab 03: "shown as n/a" under worst-of).
    weight_in_subcategory: float | None = None

    def band(self, code: str) -> Band:
        for b in self.bands:
            if b.code == code:
                return b
        raise KeyError(f"{self.key}: no such band {code!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "key": self.key,
            "sub_category_code": self.sub_category_code, "layer": self.layer,
            "name": self.name, "unit_basis": self.unit_basis,
            "weight_in_subcategory": self.weight_in_subcategory,
            "basis": self.basis,
            "bands": [{"code": b.code, "score": b.score, "label": b.label}
                      for b in self.bands],
        }


# ---------------------------------------------------------------------------
# The 8 sub-categories, transcribed verbatim from Tab 03 Section A.
# ---------------------------------------------------------------------------

SUBCATEGORIES: dict[str, sc.SubCategoryDefinition] = {
    "L2.1": sc.SubCategoryDefinition("L2.1", "Default proximity", "L2", "C", 0.28, sc.WORST_OF),
    "L2.2": sc.SubCategoryDefinition("L2.2", "Leverage and coverage", "L2", "C", 0.20, sc.WORST_OF),
    "L2.3": sc.SubCategoryDefinition("L2.3", "Liquidity and working capital", "L2", "C", 0.12, sc.BLEND,
                                      member_weights={"quick_ratio": 0.6, "cash_conversion_cycle": 0.4}),
    "L2.4": sc.SubCategoryDefinition("L2.4", "Earnings quality", "L2", "C", 0.12, sc.WORST_OF),
    "L2.5": sc.SubCategoryDefinition("L2.5", "Security and covenant protection", "L2", "C", 0.14, sc.WORST_OF),
    "L2.6": sc.SubCategoryDefinition("L2.6", "Exposure and concentration", "L2", "C", 0.08, sc.BLEND,
                                      member_weights={"facility_utilisation_12m_avg": 0.4,
                                                       "connected_group_exposure_pct_tier1": 0.35,
                                                       "bank_share_of_obligor_debt": 0.25}),
    "L2.7": sc.SubCategoryDefinition("L2.7", "Obligor profile and information quality", "L2", "C", 0.06, sc.BLEND,
                                      member_weights={"financial_statement_quality_and_age": 0.35,
                                                       "sector_vulnerability_grade": 0.30,
                                                       "country_jurisdiction_risk": 0.20,
                                                       "obligor_profile": 0.15}),
    "L4.4": sc.SubCategoryDefinition("L4.4", "Network fragility", "L4", "C", 1.00, sc.BLEND,
                                      member_weights={"supplier_concentration": 0.30,
                                                       "supplier_replaceability": 0.25,
                                                       "receivable_concentration_by_counterparty": 0.25,
                                                       "guarantor_capacity": 0.15,
                                                       "relationship_edge_confidence": 0.05}),
}

assert abs(sum(d.weight_in_layer_dimension for c, d in SUBCATEGORIES.items() if d.layer == "L2") - 1.0) < 1e-9

# ---------------------------------------------------------------------------
# The 23 classifiers, transcribed verbatim from Tab 03 Section B.
# ---------------------------------------------------------------------------

CLASSIFIER_DEFINITIONS: tuple[ClassifierDefinition, ...] = (
    ClassifierDefinition(
        code="1", key="pd_12m", sub_category_code="L2.1", layer="L2", name="12-month PD",
        unit_basis="Percent",
        bands=(
            Band("VERY_LOW", 0, "< 0.15%"),
            Band("LOW", 25, "0.15% to 0.60%"),
            Band("MEDIUM", 50, "0.60% to 3.0%"),
            Band("HIGH", 75, "3.0% to 10%"),
            Band("VERY_HIGH", 100, "> 10%"),
        ),
        basis="S&P long-run one-year default rates: about 0.0% AAA, 0.2% BBB, 0.6% BB, 3.0% B, 26% CCC/C.",
    ),
    ClassifierDefinition(
        code="2", key="ifrs9_stage", sub_category_code="L2.1", layer="L2", name="IFRS 9 stage",
        unit_basis="Stage",
        bands=(
            Band("VERY_LOW", 0, "Stage 1, low credit risk"),
            Band("LOW", 25, "Stage 1, on watch"),
            Band("MEDIUM", 50, "Stage 2, no arrears"),
            Band("HIGH", 75, "Stage 2 with 30+ DPD"),
            Band("VERY_HIGH", 100, "Stage 3, credit-impaired"),
        ),
        basis="IFRS 9 5.5.11 rebuttable presumption at 30 DPD; 5.5.19 / B5.5.37 default presumption at 90 DPD.",
    ),
    ClassifierDefinition(
        code="3", key="dpd_current", sub_category_code="L2.1", layer="L2", name="Days past due (current)",
        unit_basis="Days",
        bands=(
            Band("VERY_LOW", 0, "0"),
            Band("LOW", 25, "1 to 7"),
            Band("MEDIUM", 50, "8 to 29"),
            Band("HIGH", 75, "30 to 89"),
            Band("VERY_HIGH", 100, "90 or more"),
        ),
        basis="IFRS 9 presumptions; CBUAE Circular 28/2010 classification at 90 DPD with a watch-list category below.",
    ),
    ClassifierDefinition(
        code="4", key="dscr", sub_category_code="L2.2", layer="L2", name="DSCR",
        unit_basis="Times",
        bands=(
            Band("VERY_LOW", 0, "> 2.00x"),
            Band("LOW", 25, "1.50x to 2.00x"),
            Band("MEDIUM", 50, "1.25x to 1.50x"),
            Band("HIGH", 75, "1.00x to 1.25x"),
            Band("VERY_HIGH", 100, "< 1.00x"),
        ),
        basis="Market convention: 1.20x to 1.25x is the standard maintenance covenant floor.",
    ),
    ClassifierDefinition(
        code="5", key="leverage_net_debt_ebitda", sub_category_code="L2.2", layer="L2", name="Net debt / EBITDA",
        unit_basis="Times",
        bands=(
            Band("VERY_LOW", 0, "< 1.5x"),
            Band("LOW", 25, "1.5x to 3.0x"),
            Band("MEDIUM", 50, "3.0x to 4.5x"),
            Band("HIGH", 75, "4.5x to 6.0x"),
            Band("VERY_HIGH", 100, "> 6.0x"),
        ),
        basis="2013 US Interagency Leveraged Lending Guidance: 4x defines leveraged, above 6x raises concerns.",
    ),
    ClassifierDefinition(
        code="6", key="quick_ratio", sub_category_code="L2.3", layer="L2", name="Quick ratio",
        unit_basis="Times", weight_in_subcategory=0.6,
        bands=(
            Band("VERY_LOW", 0, "> 1.50"),
            Band("LOW", 25, "1.20 to 1.50"),
            Band("MEDIUM", 50, "0.90 to 1.20"),
            Band("HIGH", 75, "0.70 to 0.90"),
            Band("VERY_HIGH", 100, "< 0.70"),
        ),
        basis="Liquidity convention, inventory excluded. Most relevant for trading and contracting obligors.",
    ),
    ClassifierDefinition(
        code="7", key="cash_conversion_cycle", sub_category_code="L2.3", layer="L2", name="Cash conversion cycle",
        unit_basis="Days, sector-relative", weight_in_subcategory=0.4,
        bands=(
            Band("VERY_LOW", 0, "< 30"),
            Band("LOW", 25, "30 to 60"),
            Band("MEDIUM", 50, "60 to 90"),
            Band("HIGH", 75, "90 to 150"),
            Band("VERY_HIGH", 100, "> 150"),
        ),
        basis="Working capital convention. Re-cut per sector; contracting runs structurally longer.",
    ),
    ClassifierDefinition(
        code="8", key="ebitda_margin_vs_sector", sub_category_code="L2.4", layer="L2", name="EBITDA margin vs sector median",
        unit_basis="Relative",
        bands=(
            Band("VERY_LOW", 0, "More than 25% above"),
            Band("LOW", 25, "10% to 25% above"),
            Band("MEDIUM", 50, "Within +/- 10%"),
            Band("HIGH", 75, "10% to 25% below"),
            Band("VERY_HIGH", 100, "More than 25% below, or negative"),
        ),
        basis="Relative, because absolute margin is not comparable across sectors.",
    ),
    ClassifierDefinition(
        code="9", key="revenue_trend_3y_cagr", sub_category_code="L2.4", layer="L2", name="Revenue trend (3-year CAGR)",
        unit_basis="Percent",
        bands=(
            Band("VERY_LOW", 0, "> +10%"),
            Band("LOW", 25, "0% to +10%"),
            Band("MEDIUM", 50, "-5% to 0%"),
            Band("HIGH", 75, "-15% to -5%"),
            Band("VERY_HIGH", 100, "< -15%"),
        ),
        basis="Convention. Read against sector growth, not in isolation.",
    ),
    ClassifierDefinition(
        code="10", key="collateral_coverage_or_ltv", sub_category_code="L2.5", layer="L2",
        name="Collateral coverage, or LTV where real-estate secured", unit_basis="Ratio",
        bands=(
            Band("VERY_LOW", 0, "Coverage > 150%, LTV < 50%"),
            Band("LOW", 25, "125-150%, LTV 50-65%"),
            Band("MEDIUM", 50, "100-125%, LTV 65-75%"),
            Band("HIGH", 75, "70-100%, LTV 75-85%"),
            Band("VERY_HIGH", 100, "< 70%, LTV > 85%"),
        ),
        basis="SAMA caps residential LTV at 70%/90%; CBUAE Circular 31/2013 caps at 85%/80%.",
    ),
    ClassifierDefinition(
        code="11", key="covenant_headroom", sub_category_code="L2.5", layer="L2", name="Covenant headroom",
        unit_basis="Percent to the tightest covenant",
        bands=(
            Band("VERY_LOW", 0, "> 30%"),
            Band("LOW", 25, "15% to 30%"),
            Band("MEDIUM", 50, "5% to 15%"),
            Band("HIGH", 75, "0% to 5%"),
            Band("VERY_HIGH", 100, "Breached or waived"),
        ),
        basis="Convention. A waiver counts as a breach for early warning, because the condition was not cured.",
    ),
    ClassifierDefinition(
        code="12", key="facility_utilisation_12m_avg", sub_category_code="L2.6", layer="L2",
        name="Facility utilisation (12-month average)", unit_basis="Percent of limit",
        weight_in_subcategory=0.4,
        bands=(
            Band("VERY_LOW", 0, "< 40%"),
            Band("LOW", 25, "40% to 60%"),
            Band("MEDIUM", 50, "60% to 80%"),
            Band("HIGH", 75, "80% to 95%"),
            Band("VERY_HIGH", 100, "> 95%"),
        ),
        basis="Ratio replacement for the absolute limit variable removed in version 2.",
    ),
    ClassifierDefinition(
        code="13", key="connected_group_exposure_pct_tier1", sub_category_code="L2.6", layer="L2",
        name="Connected group exposure as % of Tier 1", unit_basis="Percent",
        weight_in_subcategory=0.35,
        bands=(
            Band("VERY_LOW", 0, "< 5%"),
            Band("LOW", 25, "5% to 10%"),
            Band("MEDIUM", 50, "10% to 15%"),
            Band("HIGH", 75, "15% to 20%"),
            Band("VERY_HIGH", 100, "> 20%"),
        ),
        basis="Basel large exposures framework caps a connected group at 25% of Tier 1.",
    ),
    ClassifierDefinition(
        code="14", key="bank_share_of_obligor_debt", sub_category_code="L2.6", layer="L2",
        name="Bank share of the obligor's total debt", unit_basis="Percent",
        weight_in_subcategory=0.25,
        bands=(
            Band("VERY_LOW", 0, "< 15%"),
            Band("LOW", 25, "15% to 30%"),
            Band("MEDIUM", 50, "30% to 50%"),
            Band("HIGH", 75, "50% to 75%"),
            Band("VERY_HIGH", 100, "> 75%"),
        ),
        basis="Bureau-sourced. A high share means the bank cannot exit without moving the obligor.",
    ),
    ClassifierDefinition(
        code="15", key="financial_statement_quality_and_age", sub_category_code="L2.7", layer="L2",
        name="Financial statement quality and age", unit_basis="Auditor, opinion, age",
        weight_in_subcategory=0.35,
        bands=(
            Band("VERY_LOW", 0, "Big four, unqualified, under 6 months"),
            Band("LOW", 25, "Audited, unqualified"),
            Band("MEDIUM", 50, "Audited with emphasis of matter"),
            Band("HIGH", 75, "Qualified opinion"),
            Band("VERY_HIGH", 100, "Unaudited or over 12 months overdue"),
        ),
        basis="Information risk. Stale or qualified statements weaken every ratio-based classifier above.",
    ),
    ClassifierDefinition(
        code="16", key="sector_vulnerability_grade", sub_category_code="L2.7", layer="L2",
        name="Sector vulnerability grade", unit_basis="Internal grade 1-5",
        weight_in_subcategory=0.30,
        bands=(
            Band("VERY_LOW", 0, "1, resilient"),
            Band("LOW", 25, "2, stable"),
            Band("MEDIUM", 50, "3, neutral"),
            Band("HIGH", 75, "4, under pressure"),
            Band("VERY_HIGH", 100, "5, stressed"),
        ),
        basis="Internal sector scorecard refreshed quarterly from the macro and sector sources.",
    ),
    ClassifierDefinition(
        code="17", key="country_jurisdiction_risk", sub_category_code="L2.7", layer="L2",
        name="Country / jurisdiction risk", unit_basis="Sovereign rating",
        weight_in_subcategory=0.20,
        bands=(
            Band("VERY_LOW", 0, "AA- and above"),
            Band("LOW", 25, "A- to A+"),
            Band("MEDIUM", 50, "BBB- to BBB+"),
            Band("HIGH", 75, "BB- to BB+"),
            Band("VERY_HIGH", 100, "B+ and below"),
        ),
        basis="Transfer and convertibility risk where revenue or assets sit outside the home jurisdiction.",
    ),
    ClassifierDefinition(
        code="18", key="obligor_profile", sub_category_code="L2.7", layer="L2", name="Obligor profile",
        unit_basis="Size, segment, tenure, history", weight_in_subcategory=0.15,
        bands=(
            Band("VERY_LOW", 0, "Large corporate, over 5 years, clean"),
            Band("LOW", 25, "Corporate, 3 to 5 years"),
            Band("MEDIUM", 50, "Mid corporate, 1 to 3 years"),
            Band("HIGH", 75, "SME, under 1 year"),
            Band("VERY_HIGH", 100, "Micro, or prior restructuring"),
        ),
        basis="Merged in version 2 from borrower size and relationship tenure, each individually too weak alone.",
    ),
    ClassifierDefinition(
        code="19", key="supplier_concentration", sub_category_code="L4.4", layer="L4",
        name="Supplier concentration", unit_basis="Top three suppliers as % of input cost",
        weight_in_subcategory=0.30,
        bands=(
            Band("VERY_LOW", 0, "< 20%"),
            Band("LOW", 25, "20% to 35%"),
            Band("MEDIUM", 50, "35% to 50%"),
            Band("HIGH", 75, "50% to 70%"),
            Band("VERY_HIGH", 100, "> 70%"),
        ),
        basis="Mirror of receivable concentration; upstream concentration was absent from version 1.",
    ),
    ClassifierDefinition(
        code="20", key="supplier_replaceability", sub_category_code="L4.4", layer="L4",
        name="Supplier replaceability", unit_basis="Alternates and switching time",
        weight_in_subcategory=0.25,
        bands=(
            Band("VERY_LOW", 0, "Multiple alternates, under 1 month"),
            Band("LOW", 25, "2 to 3 alternates, 1 to 3 months"),
            Band("MEDIUM", 50, "Limited, 3 to 6 months"),
            Band("HIGH", 75, "One alternate, 6 to 12 months"),
            Band("VERY_HIGH", 100, "Single source, over 12 months"),
        ),
        basis="Merged in version 2 from single-source dependency, substitutability and switching time.",
    ),
    ClassifierDefinition(
        code="21", key="receivable_concentration_by_counterparty", sub_category_code="L4.4", layer="L4",
        name="Receivable concentration by counterparty",
        unit_basis="Largest debtor as % of receivables", weight_in_subcategory=0.25,
        bands=(
            Band("VERY_LOW", 0, "< 10%"),
            Band("LOW", 25, "10% to 20%"),
            Band("MEDIUM", 50, "20% to 35%"),
            Band("HIGH", 75, "35% to 50%"),
            Band("VERY_HIGH", 100, "> 50%"),
        ),
        basis="The fastest downstream transmission path. Replaces buyer concentration, which was annual.",
    ),
    ClassifierDefinition(
        code="22", key="guarantor_capacity", sub_category_code="L4.4", layer="L4",
        name="Guarantor capacity", unit_basis="Relative strength", weight_in_subcategory=0.15,
        bands=(
            Band("VERY_LOW", 0, "3 or more notches stronger, unconditional"),
            Band("LOW", 25, "2 notches stronger"),
            Band("MEDIUM", 50, "Comparable strength"),
            Band("HIGH", 75, "Weaker than the obligor"),
            Band("VERY_HIGH", 100, "No effective guarantee"),
        ),
        basis="A guarantee only improves the classifier if the guarantor is measurably stronger and enforceable.",
    ),
    ClassifierDefinition(
        code="23", key="relationship_edge_confidence", sub_category_code="L4.4", layer="L4",
        name="Relationship edge confidence", unit_basis="Verification status", weight_in_subcategory=0.05,
        bands=(
            Band("VERY_LOW", 0, "All key links verified from official records"),
            Band("LOW", 25, "Key links verified, minor gaps"),
            Band("MEDIUM", 50, "Corroborated by two sources"),
            Band("HIGH", 75, "Single credible source"),
            Band("VERY_HIGH", 100, "Inferred or stale"),
        ),
        basis="Governance. An unverified edge must not move a band; it caps how much the network layer can contribute.",
    ),
)

assert len(CLASSIFIER_DEFINITIONS) == 23
BY_KEY: dict[str, ClassifierDefinition] = {c.key: c for c in CLASSIFIER_DEFINITIONS}


def verdict_band(score: float) -> str:
    if score < 20:
        return "VERY_LOW"
    if score < 40:
        return "LOW"
    if score < 60:
        return "MEDIUM"
    if score < 80:
        return "HIGH"
    return "VERY_HIGH"


@dataclass(frozen=True)
class ClassifierResult:
    key: str
    band: str
    band_score: int


@dataclass(frozen=True)
class ClassifierVerdict:
    score: float
    band: str
    subcategory_scores: dict[str, float]
    l2_c_score: float
    l4_c_score: float
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
    """Band each supplied classifier, roll up through its sub-category
    (Tab 03 Section A's rule), then L2-C and L4-C (Tab 03 Section A
    weights), then the Classifier dimension (Tab 06 Section C Step 3,
    L2 0.85 / L4 0.15). `band_selections` maps classifier key -> band code
    for whichever of the 23 classifiers are supplied; a classifier with no
    entry is simply absent from its sub-category's roll-up this month."""
    overrides: list[str] = []
    selections = dict(band_selections)

    if guarantor_in_default_load_bearing:
        selections["guarantor_capacity"] = "VERY_HIGH"
        overrides.append("guarantor_in_default_forces_guarantor_capacity_very_high")

    results: list[ClassifierResult] = []
    member_scores_by_subcat: dict[str, dict[str, float]] = {code: {} for code in SUBCATEGORIES}
    for key, band_code in selections.items():
        definition = BY_KEY.get(key)
        if definition is None:
            continue
        band = definition.band(band_code)
        results.append(ClassifierResult(key=key, band=band.code, band_score=band.score))
        member_scores_by_subcat[definition.sub_category_code][key] = float(band.score)

    subcategory_scores: dict[str, float] = {
        code: sc.score_subcategory(definition, member_scores_by_subcat[code])
        for code, definition in SUBCATEGORIES.items()
    }

    l2_subcats = {c: d for c, d in SUBCATEGORIES.items() if d.layer == "L2"}
    l2_c_score = sc.roll_up_to_layer_dimension(subcategory_scores, l2_subcats)
    l4_c_score = subcategory_scores.get("L4.4", 0.0)

    score = (l2_c_score * CLASSIFIER_LAYER_WEIGHTS["L2"]
             + l4_c_score * CLASSIFIER_LAYER_WEIGHTS["L4"])

    if ifrs9_stage is not None and ifrs9_stage >= 3 or dpd is not None and dpd >= 90:
        score = 100.0
        overrides.append("ifrs9_stage3_or_90dpd_forces_very_high")
    if confirmed_sanctions_match:
        score = 100.0
        overrides.append("confirmed_sanctions_forces_very_high_and_escalation")
    if unwaived_covenant_breach and score < 75.0:
        score = 75.0
        overrides.append("unwaived_covenant_breach_floors_high")
    if negative_equity and score < 75.0:
        score = 75.0
        overrides.append("negative_equity_floors_high")
    if statements_unaudited_or_over_18m and score < 50.0:
        score = 50.0
        overrides.append("stale_or_unaudited_statements_floors_medium")

    return ClassifierVerdict(
        score=score, band=verdict_band(score), subcategory_scores=subcategory_scores,
        l2_c_score=l2_c_score, l4_c_score=l4_c_score,
        results=tuple(results), overrides_applied=tuple(overrides),
    )

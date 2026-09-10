"""
Saudi retail product families, subsegments and geography.

Four product families, machine codes stable and display labels retail. The
subsegments are independent columns rather than one concatenated mega-label,
because "CC_SAL_GOV_RIY_DIG" is not a segment, it is a puzzle.

Everything here is a demonstration taxonomy. It describes categories a Saudi
retail bank plausibly reports on; it is not a statement that ANB offers any
particular product or that any distribution below is observed.
"""

from __future__ import annotations

from dataclasses import dataclass

CREDIT_CARD = "CREDIT_CARD"
PERSONAL_LOAN = "PERSONAL_LOAN"
AUTO_LOAN = "AUTO_LOAN"
HOME_LOAN = "HOME_LOAN"

PRODUCT_CODES: tuple[str, ...] = (CREDIT_CARD, PERSONAL_LOAN, AUTO_LOAN, HOME_LOAN)

PRODUCT_LABELS: dict[str, str] = {
    CREDIT_CARD: "Credit Card",
    PERSONAL_LOAN: "Personal Finance",
    AUTO_LOAN: "Auto Finance",
    HOME_LOAN: "Home Finance",
}

#: What a user may type and still be understood. Cockpit resolves these to the
#: machine code; a buyer says "mortgage", the column says HOME_LOAN.
PRODUCT_SYNONYMS: dict[str, str] = {
    "credit card": CREDIT_CARD, "cards": CREDIT_CARD, "card": CREDIT_CARD,
    "revolving": CREDIT_CARD, "credit cards": CREDIT_CARD,
    "personal loan": PERSONAL_LOAN, "personal finance": PERSONAL_LOAN,
    "personal loans": PERSONAL_LOAN, "pl": PERSONAL_LOAN,
    "consumer finance": PERSONAL_LOAN, "consumer loan": PERSONAL_LOAN,
    "auto loan": AUTO_LOAN, "auto finance": AUTO_LOAN, "auto lease": AUTO_LOAN,
    "car loan": AUTO_LOAN, "vehicle finance": AUTO_LOAN, "auto": AUTO_LOAN,
    "home loan": HOME_LOAN, "home finance": HOME_LOAN, "mortgage": HOME_LOAN,
    "mortgages": HOME_LOAN, "real estate finance": HOME_LOAN,
    "housing finance": HOME_LOAN, "home": HOME_LOAN,
}

REVOLVING_PRODUCTS: frozenset[str] = frozenset({CREDIT_CARD})
AMORTISING_PRODUCTS: frozenset[str] = frozenset({PERSONAL_LOAN, AUTO_LOAN, HOME_LOAN})
SECURED_PRODUCTS: frozenset[str] = frozenset({AUTO_LOAN, HOME_LOAN})


def resolve_product(text: str) -> str | None:
    """Machine code for a product the user named, or None if they named none."""
    t = (text or "").strip().lower()
    if t.upper() in PRODUCT_CODES:
        return t.upper()
    if t in PRODUCT_SYNONYMS:
        return PRODUCT_SYNONYMS[t]
    hits = {code for phrase, code in PRODUCT_SYNONYMS.items() if phrase in t}
    return hits.pop() if len(hits) == 1 else None


# --------------------------------------------------------------------------
# Independent subsegment dimensions. Each is its own column.
# --------------------------------------------------------------------------

EMPLOYMENT_STATUS = (
    "GOVERNMENT", "GOVERNMENT_RELATED", "PRIVATE_SECTOR", "SELF_EMPLOYED", "RETIRED",
)
EMPLOYMENT_STATUS_LABELS = {
    "GOVERNMENT": "Government",
    "GOVERNMENT_RELATED": "Government-related entity",
    "PRIVATE_SECTOR": "Private sector",
    "SELF_EMPLOYED": "Self-employed",
    "RETIRED": "Retired",
}

#: Employer sector is an attribute of an individual borrower's employer. It is
#: NOT a financed company customer: no balance sheet, no rating, no covenant.
EMPLOYER_SECTORS = (
    "PUBLIC_ADMINISTRATION", "EDUCATION", "HEALTHCARE", "OIL_AND_GAS",
    "PETROCHEMICALS", "CONSTRUCTION", "RETAIL_TRADE", "TRANSPORT_LOGISTICS",
    "FINANCIAL_SERVICES", "TELECOM_TECH", "HOSPITALITY_TOURISM", "OTHER_SERVICES",
)

RESIDENCY_CATEGORIES = ("CITIZEN", "RESIDENT")
AGE_BANDS = ("21-29", "30-39", "40-49", "50-59", "60+")
DEPENDANTS_BANDS = ("0", "1-2", "3-4", "5+")

INCOME_BANDS = (
    "<5k", "5k-10k", "10k-20k", "20k-35k", "35k-60k", "60k+",
)
INCOME_BAND_EDGES_SAR = (5_000, 10_000, 20_000, 35_000, 60_000)

INDEBTEDNESS_BANDS = ("<15%", "15-30%", "30-45%", "45-55%", "55%+")
INDEBTEDNESS_BAND_EDGES = (0.15, 0.30, 0.45, 0.55)

ORIGINATION_CHANNELS = ("DIGITAL", "BRANCH", "DEALER", "PARTNER", "RELATIONSHIP_MANAGER")
CHANNEL_BY_PRODUCT: dict[str, tuple[str, ...]] = {
    CREDIT_CARD: ("DIGITAL", "BRANCH", "PARTNER"),
    PERSONAL_LOAN: ("DIGITAL", "BRANCH", "RELATIONSHIP_MANAGER"),
    AUTO_LOAN: ("DEALER", "BRANCH", "DIGITAL"),
    HOME_LOAN: ("BRANCH", "RELATIONSHIP_MANAGER", "DIGITAL"),
}

CUSTOMER_SEGMENTS = ("MASS", "MASS_AFFLUENT", "AFFLUENT", "PRIVATE")

#: Documented Saudi geographic lookup. Province, then the cities carried in the
#: demo book. Provinces are the official thirteen; the city list is a
#: demonstration subset, not a branch network.
SAUDI_REGIONS: dict[str, tuple[str, ...]] = {
    "RIYADH": ("Riyadh", "Al Kharj", "Al Majmaah", "Ad Diriyah"),
    "MAKKAH": ("Jeddah", "Makkah", "Taif", "Rabigh"),
    "MADINAH": ("Madinah", "Yanbu"),
    "EASTERN_PROVINCE": ("Dammam", "Al Khobar", "Dhahran", "Jubail", "Al Ahsa"),
    "QASSIM": ("Buraydah", "Unaizah"),
    "ASIR": ("Abha", "Khamis Mushait"),
    "TABUK": ("Tabuk",),
    "HAIL": ("Hail",),
    "NORTHERN_BORDERS": ("Arar",),
    "JAZAN": ("Jazan",),
    "NAJRAN": ("Najran",),
    "AL_BAHAH": ("Al Bahah",),
    "AL_JAWF": ("Sakaka",),
}
REGION_LABELS: dict[str, str] = {
    "RIYADH": "Riyadh", "MAKKAH": "Makkah", "MADINAH": "Madinah",
    "EASTERN_PROVINCE": "Eastern Province", "QASSIM": "Qassim", "ASIR": "Asir",
    "TABUK": "Tabuk", "HAIL": "Hail", "NORTHERN_BORDERS": "Northern Borders",
    "JAZAN": "Jazan", "NAJRAN": "Najran", "AL_BAHAH": "Al Bahah", "AL_JAWF": "Al Jawf",
}
#: Share of the demonstration book by province. A synthetic weighting chosen to
#: look like a Saudi retail book's centre of gravity; not an observed share.
REGION_WEIGHTS: dict[str, float] = {
    "RIYADH": 0.295, "MAKKAH": 0.21, "EASTERN_PROVINCE": 0.18, "MADINAH": 0.07,
    "QASSIM": 0.06, "ASIR": 0.05, "TABUK": 0.03, "HAIL": 0.025,
    "JAZAN": 0.025, "NAJRAN": 0.015, "AL_BAHAH": 0.015, "AL_JAWF": 0.0125,
    "NORTHERN_BORDERS": 0.0125,
}

# ---- product-specific subsegment vocabularies -----------------------------

CARD_BEHAVIOUR_SEGMENTS = ("TRANSACTOR", "REVOLVER", "INACTIVE")
UTILISATION_BANDS = ("0-20%", "20-40%", "40-60%", "60-80%", "80-100%", ">100%")
UTILISATION_BAND_EDGES = (0.20, 0.40, 0.60, 0.80, 1.00)

PERSONAL_LOAN_PURPOSES = ("NEW_FINANCE", "TOP_UP", "REFINANCE_BUYOUT")
VEHICLE_CONDITIONS = ("NEW", "USED")
AUTO_STRUCTURES = ("LEASE_TO_OWN", "MURABAHA")
DOWN_PAYMENT_BANDS = ("<10%", "10-20%", "20-30%", "30%+")
BALLOON_BANDS = ("NONE", "<20%", "20-35%", "35%+")

PROPERTY_TYPES = ("APARTMENT", "VILLA", "TOWNHOUSE", "LAND_AND_BUILD")
LTV_BANDS = ("<60%", "60-70%", "70-80%", "80-90%", "90%+")
LTV_BAND_EDGES = (0.60, 0.70, 0.80, 0.90)
HOME_PURPOSES = ("FIRST_HOME", "REFINANCE", "SECOND_PROPERTY")

#: A synthetic supported-housing programme flag. It is a demo attribute so the
#: product can show a programme cut; it names no real Saudi programme's rules.
HOUSING_SUPPORT_TYPES = ("NONE", "SYNTHETIC_SUPPORTED_PROGRAMME")

CONTRACT_STRUCTURES = ("MURABAHA", "TAWARRUQ", "IJARA", "CONVENTIONAL")
RATE_TYPES = ("FIXED", "FLOATING")

DPD_BUCKETS = ("CURRENT", "1-29", "30-59", "60-89", "90-179", "180+")
DPD_BUCKET_EDGES = (1, 30, 60, 90, 180)

COLLECTIONS_STAGES = ("NONE", "SOFT_REMINDER", "TELE_COLLECTION", "FIELD", "LEGAL", "WRITE_OFF")

CLOSURE_REASONS = ("SETTLED_EARLY", "MATURED", "WRITTEN_OFF", "REFINANCED_INTERNALLY")

#: Synthetic employer groups. Deliberately fictional names so no real employer
#: is implicated in a delinquency story.
EMPLOYER_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("EMP-G001", "Synthetic Public Authority A", "PUBLIC_ADMINISTRATION"),
    ("EMP-G002", "Synthetic Public Authority B", "PUBLIC_ADMINISTRATION"),
    ("EMP-G003", "Synthetic Education Group", "EDUCATION"),
    ("EMP-G004", "Synthetic Health Network", "HEALTHCARE"),
    ("EMP-G005", "Synthetic Energy Corp", "OIL_AND_GAS"),
    ("EMP-G006", "Synthetic Petrochem Co", "PETROCHEMICALS"),
    ("EMP-G007", "Synthetic Contracting Co", "CONSTRUCTION"),
    ("EMP-G008", "Synthetic Contracting Group B", "CONSTRUCTION"),
    ("EMP-G009", "Synthetic Retail Chain", "RETAIL_TRADE"),
    ("EMP-G010", "Synthetic Logistics Co", "TRANSPORT_LOGISTICS"),
    ("EMP-G011", "Synthetic Bank Services", "FINANCIAL_SERVICES"),
    ("EMP-G012", "Synthetic Telecom Co", "TELECOM_TECH"),
    ("EMP-G013", "Synthetic Hospitality Group", "HOSPITALITY_TOURISM"),
    ("EMP-G014", "Synthetic Services Co", "OTHER_SERVICES"),
    ("EMP-G015", "Synthetic Services Group B", "OTHER_SERVICES"),
)


@dataclass(frozen=True)
class BandSpec:
    """A named banding of a numeric field, used identically everywhere."""

    name: str
    labels: tuple[str, ...]
    edges: tuple[float, ...]

    def band_of(self, value: float | None) -> str | None:
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if v != v:  # NaN
            return None
        for i, edge in enumerate(self.edges):
            if v < edge:
                return self.labels[i]
        return self.labels[len(self.edges)]


INCOME_BAND_SPEC = BandSpec("income_band", INCOME_BANDS, INCOME_BAND_EDGES_SAR)
INDEBTEDNESS_BAND_SPEC = BandSpec("indebtedness_band", INDEBTEDNESS_BANDS, INDEBTEDNESS_BAND_EDGES)
UTILISATION_BAND_SPEC = BandSpec("utilisation_band", UTILISATION_BANDS, UTILISATION_BAND_EDGES)
LTV_BAND_SPEC = BandSpec("ltv_band", LTV_BANDS, LTV_BAND_EDGES)
DPD_BUCKET_SPEC = BandSpec("dpd_bucket", DPD_BUCKETS, DPD_BUCKET_EDGES)


def product_applicable(field_name: str, product_code: str) -> bool:
    """Whether a canonical field carries a value for this product family.

    Fields that do not apply are NULL with a recorded reason, never a zero that
    reads like an observation.
    """
    card_only = {
        "current_credit_limit_sar", "original_credit_limit_sar", "undrawn_commitment_sar",
        "available_limit_sar", "utilisation_ratio", "utilisation_avg_3m",
        "utilisation_change_3m_pp", "overlimit_days_3m", "cash_advance_amount_3m_sar",
        "cash_advance_share_3m", "minimum_payment_only_months_3m", "card_behaviour_segment",
        "utilisation_band", "ccf_base", "ccf_upturn", "ccf_downturn",
    }
    auto_only = {
        "vehicle_new_used", "vehicle_age_months", "dealer_id", "down_payment_sar",
        "down_payment_band", "balloon_payment_sar", "balloon_due_date", "balloon_band",
        "auto_structure",
    }
    home_only = {
        "housing_support_flag", "housing_support_type", "property_type", "home_purpose",
    }
    secured_only = {
        "collateral_type", "collateral_value_origination_sar", "collateral_value_current_sar",
        "collateral_valuation_date", "ltv_origination_ratio", "ltv_current_ratio",
        "ltv_band", "expected_sale_cost_ratio",
    }
    term_only = {
        "original_finance_amount_sar", "contractual_maturity_date", "original_tenor_months",
        "remaining_contractual_tenor_months", "scheduled_monthly_payment_sar",
    }
    if field_name in card_only:
        return product_code == CREDIT_CARD
    if field_name in auto_only:
        return product_code == AUTO_LOAN
    if field_name in home_only:
        return product_code == HOME_LOAN
    if field_name in secured_only:
        return product_code in SECURED_PRODUCTS
    if field_name in term_only:
        return product_code in AMORTISING_PRODUCTS
    return True

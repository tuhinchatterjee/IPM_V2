"""Where every Early Warning V2 field comes from.

Mirrors `backend/corporate/lineage.py`'s Field/authority pattern exactly,
for the same reason B2/B5 give there: the Early Warning domain is a derived,
governed analytical product, and every field in it must carry the source
domain, source dataset and source field it was built from, or say plainly
that it is DERIVED by the scoring engine rather than copied from anywhere.
The Early Warning domain must never become authoritative over the domains
it reads from — a rating, an IFRS 9 stage or a DPD figure shown inside an
Early Warning snapshot is a COPY, and the real system of record is the
domain named here.

Updated for the corrected workbook's catalog.py (SignalInventoryRow keyed by
`num`/`name`, not the earlier draft's synthetic `key` field), and to be
honest about where L1 and L3 data actually come from in this build:

  - L1 (behavioural) is genuinely interpolated from real `corporate_borrower_360`
    quarterly fields (utilisation, DPD, cash, cash flow from operations) —
    not a hypothetical not-yet-built dataset, as an earlier draft of this
    module described it.
  - L3 (external intelligence) is governed, build-time SYNTHETIC data
    (`early_warning_external_event_synthetic`), explicitly flagged
    `is_synthetic=True` here so nothing downstream can present it as a real
    news/disclosure feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.early_warning import catalog as ews_catalog

LINEAGE_VERSION = "2.0.0"

COPY = "COPY"
DERIVED = "DERIVED"
AUTHORITATIVE = "AUTHORITATIVE"  # never used here, for the same reason corporate/lineage.py never uses it

# ---------------------------------------------------------------------------
# Field groups — for Data Builder display grouping, not a scoring construct.
# ---------------------------------------------------------------------------

IDENTITY = "Identity / grouping"
CORE_CREDIT = "Core credit"
L1_BEHAVIOURAL = "Layer 1 — internal behavioural"
L2_FUNDAMENTALS = "Layer 2 — credit & financial fundamentals"
L3_EXTERNAL = "Layer 3 — external intelligence"
L4_NETWORK = "Layer 4 — network / relationship"
AGGREGATION = "Aggregation / final score"
GOVERNANCE = "Workflow / audit"

GROUPS: tuple[str, ...] = (
    IDENTITY, CORE_CREDIT, L1_BEHAVIOURAL, L2_FUNDAMENTALS, L3_EXTERNAL,
    L4_NETWORK, AGGREGATION, GOVERNANCE,
)

#: Real CreditProbe source domains each layer draws from.
SOURCE_DOMAIN_BY_LAYER: dict[str, str] = {
    "L1": "Core Portfolio / Facility",  # interpolated from corporate_borrower_360's own quarterly fields
    "L2": "Core Portfolio / Facility",
    "L3": "Early Warning",  # governed synthetic demonstration data, this domain's own
    "L4": "Core Portfolio / Facility",  # corporate graph/ownership/supply-chain domains
}

SOURCE_DATASET_BY_LAYER: dict[str, str] = {
    "L1": "corporate_borrower_360 (interpolated monthly from quarterly anchors)",
    "L2": "corporate_borrower_360",
    "L3": "early_warning_external_event_synthetic",
    "L4": "corporate_supply_chain / corporate_connected_groups",
}

#: True for layers whose lineage entries must always be flagged synthetic —
#: currently only L3, since no live external-intelligence feed exists in
#: this deployment (see the build script's own module docstring).
SYNTHETIC_LAYERS: frozenset[str] = frozenset({"L3"})


@dataclass(frozen=True)
class Field:
    name: str
    group: str
    source_domain: str
    source_dataset: str
    source_field: str
    source_as_of_date: str
    transformation: str
    authority: str = COPY
    methodology_version: str = "ews-v2.1.0"
    is_synthetic: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.name, "group": self.group,
            "source_domain": self.source_domain, "source_dataset": self.source_dataset,
            "source_field": self.source_field, "source_as_of_date": self.source_as_of_date,
            "transformation": self.transformation, "authority": self.authority,
            "methodology_version": self.methodology_version, "is_synthetic": self.is_synthetic,
        }


# ---------------------------------------------------------------------------
# Identity, core credit, aggregation and governance fields — hand-curated.
# ---------------------------------------------------------------------------

CORE_FIELDS: tuple[Field, ...] = (
    Field("snapshot_month", IDENTITY, "Early Warning", "early_warning_borrower_month",
          "snapshot_month", "as published", "Monthly point-in-time key.", authority=DERIVED),
    Field("customer_id", IDENTITY, "Corporate Ratings", "corporate_customer_master",
          "customer_id", "same period", "Copied unchanged."),
    Field("customer_name", IDENTITY, "Corporate Ratings", "corporate_customer_master",
          "customer_name", "same period", "Copied unchanged."),
    Field("sector", IDENTITY, "Corporate Ratings", "corporate_customer_master",
          "sector", "same period", "Copied unchanged."),
    Field("segment", IDENTITY, "Corporate Ratings", "corporate_customer_master",
          "segment", "same period", "Copied unchanged."),
    Field("internal_rating", CORE_CREDIT, "Corporate Ratings", "corporate_ratings",
          "internal_grade", "latest published on or before month end", "Copied unchanged."),
    Field("pd_12m", CORE_CREDIT, "Corporate Ratings", "corporate_ratings",
          "pd_12m", "latest published on or before month end", "Copied unchanged."),
    Field("ifrs9_stage", CORE_CREDIT, "IFRS 9 / ECL", "corporate_ifrs9",
          "stage", "same period", "Copied unchanged."),
    Field("dpd", CORE_CREDIT, "Core Portfolio / Facility", "corporate_delinquency",
          "days_past_due", "same period", "Copied unchanged."),
    Field("exposure", CORE_CREDIT, "Core Portfolio / Facility", "corporate_facilities",
          "exposure", "same period", "Copied unchanged."),
    Field("limit", CORE_CREDIT, "Core Portfolio / Facility", "corporate_facilities",
          "limit", "same period", "Copied unchanged."),
    Field("utilisation_pct", CORE_CREDIT, "Core Portfolio / Facility", "corporate_facilities",
          "utilisation", "same period", "DERIVED: exposure / limit.", authority=DERIVED),
    Field("collateral_coverage_pct", CORE_CREDIT, "Core Portfolio / Facility", "corporate_collateral",
          "collateral_coverage_pct", "latest valuation on or before month end", "Copied unchanged."),
    Field("covenant_headroom_pct", CORE_CREDIT, "Core Portfolio / Facility", "corporate_covenants",
          "minimum_headroom_pct", "same period", "Copied unchanged."),

    Field("subcategory_scores", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "subcategory_scores", "as published",
          "22 sub-category scores, worst-of+uplift or weighted blend (subcategory.py).", authority=DERIVED),
    Field("layer_dimension_scores", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "layer_dimension_scores", "as published",
          "Six layer-dimension scores rolled up from sub-categories (aggregation.py / classifiers_v2.py).",
          authority=DERIVED),
    Field("classifier_score", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "classifier_score", "as published",
          "L2-C x 0.85 + L4-C x 0.15, from 23 classifiers in 8 sub-categories (classifiers_v2.py).",
          authority=DERIVED),
    Field("classifier_band", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "classifier_band", "as published", "Band scale over classifier_score.", authority=DERIVED),
    Field("ta_score", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "ta_score", "as published",
          "L1 x 0.40 + L2 x 0.15 + L3 x 0.30 + L4 x 0.15, from sub-category roll-up (aggregation.py).",
          authority=DERIVED),
    Field("ta_band", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "ta_band", "as published", "Band scale over ta_score.", authority=DERIVED),
    Field("anchor_score", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "anchor_score", "as published", "Read off the published 5x5 matrix (matrix.py) from ta_band x classifier_band.",
          authority=DERIVED),
    Field("notches", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "notches", "as published", "The five +/-1 modifiers and their reasons (notches.py).", authority=DERIVED),
    Field("net_notches", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "net_notches", "as published", "Sum of the five notches, capped at +/-2.", authority=DERIVED),
    Field("ews_score", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "ews_score", "as published",
          "anchor_score + 8 x net_notches, then caps/overrides (combination.py).", authority=DERIVED),
    Field("ews_band", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "ews_band", "as published", "Band scale over ews_score, subject to overrides.", authority=DERIVED),
    Field("methodology_version", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "methodology_version", "as published", "Which early_warning_methodology_versions row scored this row.",
          authority=DERIVED),

    Field("case_status", GOVERNANCE, "Early Warning", "risk_cases",
          "status", "current", "RiskCase, about='early-warning-v2'.", authority=DERIVED),
    Field("escalation_version", GOVERNANCE, "Early Warning", "early_warning_escalation_versions",
          "version", "as of escalation", "Which escalation matrix version routed this case.", authority=DERIVED),
)


def lineage_for_signal(row: ews_catalog.SignalInventoryRow) -> Field:
    """Derive a lineage entry for one of the 123 catalogue signals from its
    declared layer, rather than hand-typing 123 near-identical rows."""
    group = {"L1": L1_BEHAVIOURAL, "L2": L2_FUNDAMENTALS, "L3": L3_EXTERNAL, "L4": L4_NETWORK}[row.layer]
    is_synthetic = row.layer in SYNTHETIC_LAYERS
    return Field(
        name=f"signal_{row.num}", group=group,
        source_domain=SOURCE_DOMAIN_BY_LAYER[row.layer],
        source_dataset=SOURCE_DATASET_BY_LAYER[row.layer],
        source_field=row.name,
        source_as_of_date="same period" if row.layer == "L2" else "as observed",
        transformation=f"{row.tac_role}: {row.what_is_measured}",
        authority=COPY if row.layer == "L2" and "C" in row.tac_role and "T" not in row.tac_role else DERIVED,
        is_synthetic=is_synthetic,
    )


def all_signal_lineage() -> list[Field]:
    """One lineage entry per catalogue row, for every one of the 123 —
    including the 18 dropped/merged/replaced, so a steward can see the full
    inventory's lineage state, not just the 105 scored rows."""
    return [lineage_for_signal(r) for r in ews_catalog.SIGNAL_INVENTORY]


def full_lineage() -> list[dict[str, Any]]:
    return [f.to_dict() for f in (*CORE_FIELDS, *all_signal_lineage())]

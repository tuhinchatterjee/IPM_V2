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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.early_warning import catalog as ews_catalog

LINEAGE_VERSION = "1.0.0"

COPY = "COPY"
DERIVED = "DERIVED"
AUTHORITATIVE = "AUTHORITATIVE"  # never used here, for the same reason corporate/lineage.py never uses it

# ---------------------------------------------------------------------------
# Field groups — for Data Builder display grouping (spec Section AA), not a
# scoring construct.
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

#: Real CreditProbe source domains each layer draws from (spec Section 6 /
#: implementation plan Section 6). L1 is the one genuine new-data-generation
#: gap: no existing monthly transactional/behavioural dataset exists today.
SOURCE_DOMAIN_BY_LAYER: dict[str, str] = {
    "L1": "Liquidity and Cash Flow",  # new monthly synthetic data, Phase 3/4
    "L2": "Core Portfolio / Facility",
    "L3": "External Intelligence",
    "L4": "Core Portfolio / Facility",  # corporate graph/ownership/supply-chain domains
}

SOURCE_DATASET_BY_LAYER: dict[str, str] = {
    "L1": "early_warning_behavioural_monthly",  # new, Phase 3/4
    "L2": "corporate_borrower_360",
    "L3": "sector_events / macro_events / borrower_external_event_link",
    "L4": "corporate_ownership_edges / corporate_supply_chain / corporate_exposure_network",
}


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
    methodology_version: str = "ews-v2.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.name, "group": self.group,
            "source_domain": self.source_domain, "source_dataset": self.source_dataset,
            "source_field": self.source_field, "source_as_of_date": self.source_as_of_date,
            "transformation": self.transformation, "authority": self.authority,
            "methodology_version": self.methodology_version,
        }


# ---------------------------------------------------------------------------
# Identity, core credit, aggregation and governance fields — hand-curated,
# matching the examples in the implementation plan's Section 6 lineage table.
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
    Field("ecl_coverage", CORE_CREDIT, "IFRS 9 / ECL", "corporate_ifrs9",
          "ecl_coverage", "same period", "Copied unchanged."),
    Field("dpd", CORE_CREDIT, "Core Portfolio / Facility", "corporate_delinquency",
          "days_past_due", "same period", "Copied unchanged."),
    Field("exposure", CORE_CREDIT, "Core Portfolio / Facility", "corporate_facilities",
          "exposure", "same period", "Copied unchanged."),
    Field("limit", CORE_CREDIT, "Core Portfolio / Facility", "corporate_facilities",
          "limit", "same period", "Copied unchanged."),
    Field("utilisation", CORE_CREDIT, "Core Portfolio / Facility", "corporate_facilities",
          "utilisation", "same period", "DERIVED: exposure / limit.", authority=DERIVED),
    Field("collateral_coverage_pct", CORE_CREDIT, "Core Portfolio / Facility", "corporate_collateral",
          "collateral_coverage_pct", "latest valuation on or before month end", "Copied unchanged."),
    Field("covenant_headroom_pct", CORE_CREDIT, "Core Portfolio / Facility", "corporate_covenants",
          "minimum_headroom_pct", "same period", "Copied unchanged."),

    Field("classifier_score", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "classifier_score", "as published", "Weighted sum over 35 classifiers (classifiers_v2.py).",
          authority=DERIVED),
    Field("classifier_band", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "classifier_band", "as published", "Band scale over classifier_score.", authority=DERIVED),
    Field("ta_score", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "ta_score", "as published", "Rank-weighted breadth aggregation over fired signals (aggregation.py).",
          authority=DERIVED),
    Field("ta_band", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "ta_band", "as published", "Band scale over ta_score.", authority=DERIVED),
    Field("ews_score", AGGREGATION, "Early Warning", "early_warning_borrower_month",
          "ews_score", "as published", "ta_score x classifier context multiplier, then overrides (combination.py).",
          authority=DERIVED),
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


def lineage_for_signal(signal_key: str) -> Field | None:
    """Derive a lineage entry for one of the 123 catalogue signals from its
    declared layer, rather than hand-typing 123 near-identical rows. Layer 1
    genuinely has no existing source dataset (SOURCE_DATASET_BY_LAYER names
    the Phase 3/4 dataset this build introduces); layers 2-4 point at real,
    already-governed CreditProbe domains."""
    row = next((r for r in ews_catalog.SIGNAL_INVENTORY if r.key == signal_key), None)
    if row is None:
        return None
    group = {"L1": L1_BEHAVIOURAL, "L2": L2_FUNDAMENTALS, "L3": L3_EXTERNAL, "L4": L4_NETWORK}[row.layer]
    return Field(
        name=row.key, group=group,
        source_domain=SOURCE_DOMAIN_BY_LAYER[row.layer],
        source_dataset=SOURCE_DATASET_BY_LAYER[row.layer],
        source_field=row.name,
        source_as_of_date="same period" if row.layer in ("L2",) else "as observed",
        transformation=f"{row.tac_role}: {row.what_is_measured}",
        authority=COPY if row.layer == "L2" and row.tac_role == "C" else DERIVED,
    )


def all_signal_lineage() -> list[Field]:
    return [f for f in (lineage_for_signal(r.key) for r in ews_catalog.SIGNAL_INVENTORY) if f is not None]


def full_lineage() -> list[dict[str, Any]]:
    return [f.to_dict() for f in (*CORE_FIELDS, *all_signal_lineage())]

"""
What every Early Warning field means, computed from the field itself.

Why a dictionary rather than a schema
-------------------------------------
A planner writing code against this domain needs more than column names and
types. `sub_l2_5_score` is a number between 0 and 100 — that tells you
nothing about whether it is a percentage, a band, a count, whether a high
value is bad, which layer it belongs to, where it came from, or how often it
is actually populated. A planner given only names invents plausible fields
and writes code that fails validation; a planner given the dictionary writes
code that runs.

So every entry carries the business label, the definition, the layer and
dimension, the unit, the allowed values where the field is banded, the
lineage, and — computed from the published data rather than declared —
the coverage, the missing rate, and the months over which the field actually
exists.

Coverage is measured, not asserted
----------------------------------
A dictionary that says a field is populated, when it is empty for half the
book, is worse than no dictionary: it is the specific thing that makes a
planner confident and wrong. `profile()` reads the published months and
reports what it finds, so a field that stopped being populated in March says
so.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.early_warning import reasons
from backend.early_warning import v2_service as svc
from backend.early_warning import wide

# ------------------------------------------------------------------ groups
#
# The groups the Data Builder field explorer shows. A reader looking for
# "the covenant node" should not have to scan seventy-four alphabetical
# column names to find it.

CUSTOMER = "Customer"
CORE_CREDIT = "Core Credit Inputs"
SIGNAL_SCORES = "Signal Scores"
SUBCATEGORY = "Sub-categories"
LAYER = "Layer / Dimension Outputs"
MATRIX = "Matrix and Notches"
FINAL = "Final Early Warning"
MOVEMENT = "Movement"
WORKFLOW = "Workflow and Lineage"

GROUP_ORDER: tuple[str, ...] = (
    CUSTOMER, CORE_CREDIT, SIGNAL_SCORES, SUBCATEGORY, LAYER, MATRIX,
    FINAL, MOVEMENT, WORKFLOW)

#: The five severity bands every banded field uses.
BANDS = ("VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH")


@dataclass(frozen=True)
class Field:
    """One analytical field, described well enough to write code against."""

    name: str
    label: str
    definition: str
    group: str
    dtype: str = "number"
    unit: str = ""
    #: Where a high value is bad, which is not true of every field here.
    higher_is_worse: bool | None = None
    layer: str = ""
    dimension: str = ""
    sub_category: str = ""
    allowed_values: tuple[str, ...] = ()
    source: str = "early_warning_borrower_month"
    #: True where this module computes the field rather than reading it.
    derived: bool = False

    def to_dict(self) -> dict[str, Any]:
        out = {
            "name": self.name, "label": self.label,
            "definition": self.definition, "group": self.group,
            "type": self.dtype, "unit": self.unit,
            "source": self.source, "derived": self.derived,
        }
        if self.higher_is_worse is not None:
            out["higher_is_worse"] = self.higher_is_worse
        for key, value in (("layer", self.layer), ("dimension", self.dimension),
                           ("sub_category", self.sub_category)):
            if value:
                out[key] = value
        if self.allowed_values:
            out["allowed_values"] = list(self.allowed_values)
        return out


def _customer_fields() -> list[Field]:
    return [
        Field("customer_id", "Customer ID",
              "The obligor's canonical CreditProbe identifier. The same "
              "identifier the credit book uses; Early Warning holds no "
              "separate customer universe.", CUSTOMER, dtype="string"),
        Field("customer_name", "Customer name",
              "The obligor's registered name.", CUSTOMER, dtype="string"),
        Field("snapshot_month", "Snapshot month",
              "The month-end this row describes, as YYYY-MM. With customer_id "
              "it is the primary key of the domain.", CUSTOMER, dtype="string"),
        Field("segment", "Segment",
              "The obligor's corporate segment.", CUSTOMER, dtype="category"),
        Field("sector", "Sector",
              "The obligor's economic sector.", CUSTOMER, dtype="category"),
        Field("region", "Region",
              "The booking region.", CUSTOMER, dtype="category"),
        Field("relationship_manager", "Relationship manager",
              "The RM who owns the relationship.", CUSTOMER, dtype="category"),
        Field("methodology_version", "Methodology version",
              "Which version of the Early Warning framework produced this "
              "row. A row scored under one version is never read against "
              "another.", CUSTOMER, dtype="string"),
    ]


def _core_credit_fields() -> list[Field]:
    return [
        Field("exposure", "Exposure", "Total exposure at the month-end.",
              CORE_CREDIT, unit="SAR mn", higher_is_worse=False,
              source="corporate_borrower_360 (materialised into Early Warning)"),
        Field("limit", "Approved limit", "The approved facility limit.",
              CORE_CREDIT, unit="SAR mn",
              source="corporate_borrower_360 (materialised into Early Warning)"),
        Field("utilisation_pct", "Utilisation",
              "Exposure as a percentage of the approved limit.", CORE_CREDIT,
              unit="%", higher_is_worse=True,
              source="corporate_borrower_360 (materialised into Early Warning)"),
        Field("dpd", "Days past due",
              "Days past due at the month-end.", CORE_CREDIT, unit="days",
              higher_is_worse=True,
              source="facility_delinquency (materialised into Early Warning)"),
        Field("internal_rating", "Internal grade",
              "The bank's own grade. A classifier that moves on a review "
              "cycle, not a trigger — it is NOT expected to track the early "
              "warning score, and where the two diverge materially either "
              "the grade is stale or the trigger is a false positive.",
              CORE_CREDIT, dtype="category",
              source="customer_ratings (materialised into Early Warning)"),
        Field("pd_12m", "12-month PD",
              "The twelve-month probability of default carried on the rating.",
              CORE_CREDIT, unit="%", higher_is_worse=True,
              source="customer_ratings (materialised into Early Warning)"),
        Field("ifrs9_stage", "IFRS 9 stage",
              "The impairment stage, 1 to 3.", CORE_CREDIT, unit="stage",
              higher_is_worse=True, allowed_values=("1", "2", "3"),
              source="ifrs9_staging (materialised into Early Warning)"),
    ]


def _subcategory_fields() -> list[Field]:
    out: list[Field] = []
    for code in wide.SUBCATEGORY_CODES:
        dimension = "Classifier" if code in wide.CLASSIFIER_CODES else "T&A"
        layer = code.split(".")[0]
        try:
            name = reasons.subcategory_name(code)
        except KeyError:
            name = code
        out.append(Field(
            wide.subcategory_column(code), f"{code} {name}",
            f"The {name.lower()} sub-category score for this obligor and "
            f"month, on the 0-100 scale. Formed worst-of within the node so "
            f"one fired variable is not diluted by two quiet ones. "
            f"{dimension} dimension, layer {layer}.",
            SUBCATEGORY, unit="score", higher_is_worse=True,
            layer=layer, dimension=dimension, sub_category=code))
    return out


def _layer_fields() -> list[Field]:
    names = {"l1": "internal behavioural", "l2": "credit events",
             "l3": "external intelligence", "l4": "network"}
    out: list[Field] = []
    for key in wide.LAYER_KEYS:
        layer, dim = key.split("_")
        dimension = "T&A" if dim == "ta" else "Classifier"
        out.append(Field(
            key, f"{layer.upper()} {dimension}",
            f"The {dimension} score for layer {layer.upper()}, "
            f"{names.get(layer, layer)}. One of the six layer/dimension "
            f"outputs the model produces before combination.",
            LAYER, unit="score", higher_is_worse=True,
            layer=layer.upper(), dimension=dimension))
    out += [
        Field("ta_score", "Trigger & Accelerator score",
              "What is happening now: fresh deterioration measured against "
              "the obligor's own baseline, scaled by the accelerator and "
              "decayed by signal class.", LAYER, unit="score",
              higher_is_worse=True, dimension="T&A"),
        Field("ta_band", "T&A band", "The T&A score's severity band.",
              LAYER, dtype="category", allowed_values=BANDS, dimension="T&A"),
        Field("classifier_score", "Classifier score",
              "How vulnerable the obligor is: structural credit quality, "
              "reviewed periodically rather than re-scored daily.",
              LAYER, unit="score", higher_is_worse=True,
              dimension="Classifier"),
        Field("classifier_band", "Classifier band",
              "The classifier score's severity band.", LAYER,
              dtype="category", allowed_values=BANDS, dimension="Classifier"),
        Field("ta_minus_classifier", "T&A less Classifier",
              "The gap between the live reading and the structural one. "
              "Strongly negative means standing weakness with nothing moving "
              "now; strongly positive means live deterioration against a "
              "sound structure. The two call for opposite responses.",
              LAYER, unit="score", derived=True),
    ]
    return out


def _matrix_fields() -> list[Field]:
    out = [
        Field("anchor_score", "Anchor score",
              "The score read off the published five-by-five matrix from the "
              "T&A band and the classifier band, before any notch.",
              MATRIX, unit="score", higher_is_worse=True),
        Field("net_notches", "Net notches",
              "The five notches summed and capped at plus or minus two.",
              MATRIX, unit="notches"),
        Field("notch_points", "Notch points",
              "The net notches expressed in score points, at eight points "
              "each. This is the amount by which the notches moved the score "
              "away from its anchor.", MATRIX, unit="score", derived=True),
    ]
    explain = {
        "network_contagion": "deterioration reaching this obligor across the "
                             "relationship graph",
        "direction_of_travel": "whether the obligor's own score has been "
                               "moving, and which way",
        "evidence_quality": "how well corroborated the evidence behind the "
                            "score is",
        "data_staleness": "how old the inputs behind the score are",
        "management_and_governance": "governance and management quality "
                                     "signals the two dimensions cannot see",
    }
    for key in wide.NOTCH_KEYS:
        out.append(Field(
            wide.notch_column(key), key.replace("_", " ").capitalize(),
            f"The notch for {explain.get(key, key)}. One of five, each worth "
            f"eight points, applied to the anchor and capped in total at plus "
            f"or minus two.", MATRIX, unit="notches",
            allowed_values=("-1", "0", "1")))
    return out


def _final_fields() -> list[Field]:
    return [
        Field("ews_score", "Early Warning score",
              "The final score after the anchor, the notches and any cap or "
              "override. Zero to one hundred, higher is worse. It orders "
              "obligors; it is not a probability of anything.",
              FINAL, unit="score", higher_is_worse=True),
        Field("ews_band", "Early Warning band",
              "The final severity band.", FINAL, dtype="category",
              allowed_values=BANDS),
        Field("high_plus", "At high or above",
              "Whether the obligor is at HIGH or VERY_HIGH. The population "
              "the watchlist is drawn from.", FINAL, dtype="boolean",
              derived=True),
        Field("dominant_layer", "Dominant layer",
              "The layer carrying the most trigger-side risk for this "
              "obligor — where the deterioration is being detected.",
              FINAL, dtype="category", allowed_values=("L1", "L2", "L3", "L4"),
              derived=True),
        Field("dominant_subcategory", "Dominant sub-category",
              "The sub-category node driving this obligor's score.",
              FINAL, dtype="category"),
        Field("dominant_subcategory_name", "Dominant sub-category name",
              "The dominant node's business name.", FINAL, dtype="string",
              derived=True),
        Field("dominant_driver", "Dominant driver",
              "The single highest-scoring signal behind the score.",
              FINAL, dtype="string"),
        Field("signal_count_fired", "Signals fired",
              "How many signals fired for this obligor in this month.",
              FINAL, unit="count", higher_is_worse=True),
        Field("override_applied", "Override applied",
              "Whether a cap or floor set the band by rule rather than by "
              "the roll-up. Where one is in force the anchor and the notches "
              "do not sum to the score, and the rule is the thing to read.",
              FINAL, dtype="boolean", derived=True),
        Field("override_count", "Overrides applied",
              "How many overrides are in force.", FINAL, unit="count",
              derived=True),
        Field("override_types", "Override types",
              "Which overrides are in force, named.", FINAL, dtype="string",
              derived=True),
    ]


def _movement_fields() -> list[Field]:
    out: list[Field] = []
    for label, span in (("1m", "one month"), ("12m", "twelve months")):
        out += [
            Field(f"ews_change_{label}", f"Score change, {span}",
                  f"How the final score moved over {span}. Positive is "
                  f"deterioration. Read WITH the anchor change: a score that "
                  f"fell while its anchor rose has not improved.",
                  MOVEMENT, unit="score", derived=True),
            Field(f"anchor_change_{label}", f"Anchor change, {span}",
                  f"How the anchor moved over {span}. The anchor is where a "
                  f"change in the obligor's condition shows; the notches are "
                  f"an adjustment for what the two dimensions cannot see.",
                  MOVEMENT, unit="score", derived=True),
            Field(f"prior_period_{label}", f"Comparison month, {span}",
                  f"The month {span} back that the change is measured "
                  f"against.", MOVEMENT, dtype="string", derived=True),
        ]
    return out


@functools.lru_cache(maxsize=1)
def fields() -> tuple[Field, ...]:
    """Every analytical field, described. Cached: it is static per build."""
    return tuple(_customer_fields() + _core_credit_fields()
                 + _subcategory_fields() + _layer_fields()
                 + _matrix_fields() + _final_fields() + _movement_fields())


def by_name() -> dict[str, Field]:
    return {f.name: f for f in fields()}


def names() -> frozenset[str]:
    """Every field a plan may reference. The validator's allow-list."""
    return frozenset(f.name for f in fields())


def groups() -> dict[str, list[Field]]:
    out: dict[str, list[Field]] = {g: [] for g in GROUP_ORDER}
    for f in fields():
        out.setdefault(f.group, []).append(f)
    return {g: v for g, v in out.items() if v}


def profile(period: str | None = None) -> dict[str, dict[str, Any]]:
    """Coverage and missingness, measured from the published data.

    A dictionary that claims a field is populated when it is empty for half
    the book is the specific thing that makes a planner confident and wrong,
    so nothing here is declared — it is counted.
    """
    frame = wide.with_movement(period)
    if frame.empty:
        return {}
    total = len(frame)
    periods = svc.periods()
    out: dict[str, dict[str, Any]] = {}
    for f in fields():
        if f.name not in frame.columns:
            out[f.name] = {"present": False, "non_null": 0, "rows": total,
                            "missing_rate": 1.0}
            continue
        column = frame[f.name]
        non_null = int(column.notna().sum())
        if column.dtype == object:
            non_null = int((column.notna() & (column.astype(str) != "")).sum())
        out[f.name] = {
            "present": True,
            "non_null": non_null,
            "rows": total,
            "missing_rate": round(1.0 - (non_null / total), 4) if total else 1.0,
            "earliest_month": periods[0] if periods else "",
            "latest_month": periods[-1] if periods else "",
        }
    return out


def coverage_summary(period: str | None = None) -> dict[str, Any]:
    """One line on how complete the domain is, for the grain package."""
    found = profile(period)
    if not found:
        return {"fields": 0, "fully_populated": 0, "partially_populated": 0,
                "empty": 0}
    full = sum(1 for v in found.values() if v.get("missing_rate") == 0.0)
    empty = sum(1 for v in found.values() if v.get("missing_rate") == 1.0)
    return {
        "fields": len(found),
        "fully_populated": full,
        "partially_populated": len(found) - full - empty,
        "empty": empty,
    }


def describe(name: str) -> dict[str, Any] | None:
    found = by_name().get(name)
    return found.to_dict() if found else None


def to_dict(period: str | None = None, *, with_profile: bool = True
             ) -> dict[str, Any]:
    """The whole dictionary, in the shape the context packet carries."""
    measured = profile(period) if with_profile else {}
    out: dict[str, Any] = {"groups": {}, "field_count": len(fields())}
    for group, members in groups().items():
        out["groups"][group] = [
            {**f.to_dict(), **({"coverage": measured[f.name]}
                                if f.name in measured else {})}
            for f in members
        ]
    if with_profile:
        out["coverage"] = coverage_summary(period)
    return out


__all__ = ["BANDS", "CORE_CREDIT", "CUSTOMER", "FINAL", "GROUP_ORDER",
           "LAYER", "MATRIX", "MOVEMENT", "SIGNAL_SCORES", "SUBCATEGORY",
           "WORKFLOW", "Field", "by_name", "coverage_summary", "describe",
           "fields", "groups", "names", "profile", "to_dict"]

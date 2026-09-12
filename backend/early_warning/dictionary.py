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

That matters most for the signal inventory. All 123 signals are described
here, because all 123 are in the model — but this deployment has a feed for
some of them and not for others, and the measured coverage is what says
which. A shorter dictionary listing only the populated ones would tell a
planner the rest do not exist, which is a different and worse untruth.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.early_warning import reasons
from backend.early_warning import signal_fields as sigf
from backend.early_warning import v2_service as svc
from backend.early_warning import layers as lay
from backend.early_warning import wide

# ------------------------------------------------------------------ groups
#
# The groups the Data Builder field explorer shows. A reader looking for
# "the covenant node" should not have to scan seventy-four alphabetical
# column names to find it.

CUSTOMER = "Customer"
CORE_CREDIT = "Core Credit Inputs"
SIGNAL_SCORES = "Signal Inventory"
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
              "The obligor's registered name. Several obligors may share a "
              "family name without being one exposure — they are scored "
              "separately.", CUSTOMER, dtype="string"),
        Field("snapshot_month", "Snapshot month",
              "The month-end this row describes, as YYYY-MM. With customer_id "
              "it is the primary key of the domain.", CUSTOMER, dtype="string"),
        Field("segment", "Segment",
              "The obligor's corporate segment — the bank's own size and "
              "relationship classification, not an industry.", CUSTOMER,
              dtype="category"),
        Field("sector", "Sector",
              "The obligor's economic sector. Distinct from segment: a Mid "
              "Corporate and a Large Corporate can both be Contracting.",
              CUSTOMER, dtype="category"),
        Field("region", "Region",
              "The region the exposure is booked in, which is where the "
              "relationship is managed rather than where the obligor "
              "operates.", CUSTOMER, dtype="category"),
        Field("relationship_manager", "Relationship manager",
              "The relationship manager who owns this obligor and is the "
              "first named owner in most governed actions.", CUSTOMER,
              dtype="category"),
        Field("methodology_version", "Methodology version",
              "Which version of the Early Warning framework produced this "
              "row. A row scored under one version is never read against "
              "another.", CUSTOMER, dtype="string"),
    ]


def _core_credit_fields() -> list[Field]:
    return [
        Field("exposure", "Exposure",
              "Total exposure at the month-end. Sum it only within one "
              "month: an obligor has one row per published month, so an "
              "unperiodised sum counts the same exposure twenty times.",
              CORE_CREDIT, unit="SAR mn", higher_is_worse=False,
              source="corporate_borrower_360 (materialised into Early Warning)"),
        Field("limit", "Approved limit",
              "The approved facility limit. Exposure against it is what "
              "utilisation measures, and unused headroom is what a limit "
              "freeze removes.",
              CORE_CREDIT, unit="SAR mn",
              source="corporate_borrower_360 (materialised into Early Warning)"),
        Field("utilisation_pct", "Utilisation",
              "Exposure as a percentage of the approved limit.", CORE_CREDIT,
              unit="%", higher_is_worse=True,
              source="corporate_borrower_360 (materialised into Early Warning)"),
        Field("dpd", "Days past due",
              "Days past due at the month-end. Ninety or more forces the "
              "very high band by override, whatever the roll-up produced.",
              CORE_CREDIT, unit="days",
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
              "The IFRS 9 impairment stage, 1 to 3. Stage 3 forces the very "
              "high band by override rather than contributing to it.",
              CORE_CREDIT, unit="stage",
              higher_is_worse=True, allowed_values=("1", "2", "3"),
              source="ifrs9_staging (materialised into Early Warning)"),
    ]


#: How each per-signal measure is described, beyond the shared definition on
#: `signal_fields.SCORED_MEASURES`. Unit, whether high is bad, and the
#: banded vocabulary where there is one.
_SIGNAL_MEASURE_DETAIL: dict[str, dict[str, Any]] = {
    "status": {"allowed_values": ("SCORED", "MERGED", "DROPPED", "REPLACED",
                                   "MOVED"), "dtype": "category"},
    "fired": {"dtype": "boolean", "higher_is_worse": True},
    "observed_value": {"unit": "as observed"},
    "baseline_value": {"unit": "as observed"},
    "normalised_value": {"unit": "normalised", "higher_is_worse": True},
    "trigger_severity_band": {"unit": "band 1-5", "higher_is_worse": True},
    "trigger_score": {"unit": "score", "higher_is_worse": True},
    "magnitude_band": {"unit": "band 1-5", "higher_is_worse": True},
    "velocity_band": {"unit": "band 1-5", "higher_is_worse": True},
    "persistence_band": {"unit": "band 1-5", "higher_is_worse": True},
    "repetition_band": {"unit": "band 1-5", "higher_is_worse": True},
    "corroboration_band": {"unit": "band 1-5", "higher_is_worse": True},
    "accelerator_multiplier": {"unit": "multiplier", "higher_is_worse": True},
    "decay_factor": {"unit": "multiplier"},
    "score": {"unit": "score", "higher_is_worse": True},
    "evidence_age_days": {"unit": "days", "higher_is_worse": True},
    "freshness": {"dtype": "category",
                   "allowed_values": ("fresh", "ageing", "stale")},
}


def _signal_fields() -> list[Field]:
    """Every one of the 123 inventory rows, at customer-month grain.

    Generated from the inventory itself rather than written out, so a
    dictionary entry and the column it describes cannot drift apart: both
    come from `signal_fields`, which reads the workbook's own catalogue.
    """
    out: list[Field] = []
    for entry in sigf.fields():
        dimension = ("T&A" if "T" in entry.tac_role.upper() else "Classifier")
        for suffix, dtype, label, definition in entry.measures:
            detail = _SIGNAL_MEASURE_DETAIL.get(suffix, {})
            out.append(Field(
                entry.column(suffix),
                f"{entry.name} — {label}",
                f"Signal {entry.num} of 123, {entry.name} ({entry.code}, "
                f"layer {entry.layer}). {definition} What the signal "
                f"measures: {entry.what_is_measured}. Updated "
                f"{entry.update_frequency.lower()}.",
                SIGNAL_SCORES,
                dtype=str(detail.get("dtype", dtype)),
                unit=str(detail.get("unit", "")),
                higher_is_worse=detail.get("higher_is_worse"),
                layer=entry.layer, dimension=dimension,
                sub_category=entry.code,
                allowed_values=tuple(detail.get("allowed_values", ())),
                source=("early_warning_signal_observation"
                        if suffix in ("observed_value", "baseline_value",
                                       "normalised_value", "score",
                                       "reason_code", "reason",
                                       "evidence_age_days")
                        else "early_warning_signal_inventory"),
                derived=suffix in ("fired", "freshness")))
    return out


#: What each sub-category node exposes, and how to describe it.
_SUBCATEGORY_MEASURE_DETAIL: tuple[tuple[str, str, str, str, str], ...] = (
    ("score", "number", "score",
     "score on the 0-100 scale. Formed worst-of within the node so one fired "
     "variable is not diluted by two quiet ones.", "score"),
    ("band", "category", "band",
     "severity band, on the same cut points every band in this model uses: "
     "under 20, 40, 60, 80, then above.", ""),
    ("worst_signal", "string", "worst signal",
     "the signal carrying this node for this obligor and month — the one a "
     "reader would open first. Empty where nothing fired into the node.", ""),
    ("reason", "string", "reason",
     "the published reason for this node at the band it reached. The "
     "workbook's own text, not a sentence composed at read time.", ""),
)


def _subcategory_fields() -> list[Field]:
    out: list[Field] = []
    for code in wide.SUBCATEGORY_CODES:
        dimension = "Classifier" if code in wide.CLASSIFIER_CODES else "T&A"
        layer = code.split(".")[0]
        try:
            name = reasons.subcategory_name(code)
        except KeyError:
            name = code
        for suffix, dtype, label, definition, unit in \
                _SUBCATEGORY_MEASURE_DETAIL:
            out.append(Field(
                wide.subcategory_column(code, suffix),
                f"{code} {name} — {label}",
                f"The {name.lower()} sub-category {definition} "
                f"{dimension} dimension, layer {layer}.",
                SUBCATEGORY, dtype=dtype, unit=unit,
                higher_is_worse=True if suffix == "score" else None,
                layer=layer, dimension=dimension, sub_category=code,
                allowed_values=BANDS if suffix == "band" else (),
                derived=suffix in ("band", "worst_signal", "reason")))
    return out


def _layer_fields() -> list[Field]:
    out: list[Field] = []
    for key in wide.LAYER_KEYS:
        layer, dim = key.split("_")
        dimension = "T&A" if dim == "ta" else "Classifier"
        out.append(Field(
            key, f"{layer.upper()} {dimension}",
            f"The {dimension} score for layer {layer.upper()}, "
            f"{lay.BY_CODE[layer.upper()].short}. One of the six "
            f"layer/dimension outputs the model produces before combination.",
            LAYER, unit="score", higher_is_worse=True,
            layer=layer.upper(), dimension=dimension))
    # The per-layer "did anything fire here" flags. They exist because
    # "which obligors carry external-intelligence warning signals?" is a
    # question about a layer having fired, and until there was a field for
    # it the question could only be answered by the score everybody has.
    for entry in lay.LAYERS:
        out.append(Field(
            entry.active_field, f"{entry.code} signals present",
            f"Whether any signal in {lay.described(entry.code)} fired for "
            f"this obligor in this month and has not fully decayed — that "
            f"is, whether {entry.ta_key} is above zero. The trigger side "
            f"only: the classifier side describes a standing condition every "
            f"obligor has, so a flag read from it would be true for the "
            f"whole book.",
            LAYER, dtype="boolean", derived=True, layer=entry.code,
            dimension="T&A"))
    out += [
        Field(lay.FIRING_COUNT_FIELD, "Layers firing",
              "How many of the four layers have a signal firing for this "
              "obligor this month, trigger side. Zero to four.",
              LAYER, unit="count", higher_is_worse=True, derived=True,
              dimension="T&A"),
        Field(lay.CORROBORATED_FIELD, "Corroborated across layers",
              "Whether more than one layer is firing for this obligor. An "
              "external event nothing internal echoes is a lead to verify; "
              "the same event with arrears moving underneath it is a finding "
              "to act on. This is a cross-layer reading and is not the "
              "accelerator's own corroboration dimension, which asks a "
              "different question about one signal's sources.",
              LAYER, dtype="boolean", derived=True, dimension="T&A"),
    ]
    out += [
        Field("ta_score", "Trigger & Accelerator score",
              "What is happening now: fresh deterioration measured against "
              "the obligor's own baseline, scaled by the accelerator and "
              "decayed by signal class.", LAYER, unit="score",
              higher_is_worse=True, dimension="T&A"),
        Field("ta_band", "T&A band",
              "The T&A score's severity band. One of the two inputs to the "
              "published five-by-five matrix that sets the anchor.",
              LAYER, dtype="category", allowed_values=BANDS, dimension="T&A"),
        Field("classifier_score", "Classifier score",
              "How vulnerable the obligor is: structural credit quality, "
              "reviewed periodically rather than re-scored daily.",
              LAYER, unit="score", higher_is_worse=True,
              dimension="Classifier"),
        Field("classifier_band", "Classifier band",
              "The classifier score's severity band. The other input to the "
              "matrix, read against the T&A band rather than added to it.",
              LAYER, dtype="category", allowed_values=BANDS,
              dimension="Classifier"),
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
        Field("matrix_cell", "Matrix cell",
              "Which cell of the published five-by-five matrix this obligor "
              "reads from, as the T&A band against the classifier band. Two "
              "obligors on the same anchor from different cells are not the "
              "same case, and this is what tells them apart.",
              MATRIX, dtype="string", derived=True),
        Field("override_reasons", "Override reasons",
              "Why each override applied, in the methodology's own words "
              "rather than by code. Empty where none did.",
              MATRIX, dtype="string", derived=True),
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
              "The final severity band, after the notches and any override. "
              "This is what the watchlist and the escalation matrix both "
              "read.", FINAL, dtype="category", allowed_values=BANDS),
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
              "The dominant node's business name, so a reader need not look "
              "the code up. Empty where no node scored for this obligor.",
              FINAL, dtype="string",
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
              "How many overrides are in force. More than zero means the "
              "anchor and the notches will not sum to the score.",
              FINAL, unit="count",
              derived=True),
        Field("override_types", "Override types",
              "Which overrides are in force, named. The rule is the thing to "
              "read, and the thing that has to stop applying before the "
              "score can move.", FINAL, dtype="string",
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
    out += [
        Field("direction_of_travel", "Direction of travel",
              "Whether the obligor is deteriorating, improving or stable "
              "over twelve months, from the score movement against a "
              "threshold. A two-point drift is stable: putting a direction on "
              "arithmetic is how a portfolio starts reporting recoveries it "
              "did not have.",
              MOVEMENT, dtype="category", derived=True,
              allowed_values=("deteriorating", "stable", "improving",
                              "unknown")),
        Field("movement_is_notch_driven", "Notch-driven move",
              "True where the score and the anchor moved in OPPOSITE "
              "directions over twelve months. That means the notches moved "
              "and the obligor's condition did not, so a fall here is not an "
              "improvement and a rise is not deterioration.",
              MOVEMENT, dtype="boolean", derived=True),
    ]
    return out


def _workflow_fields() -> list[Field]:
    """The governed outputs, at the same grain as the position that produced
    them.

    The escalation route and the recommended action are deterministic
    functions of fields already on the row — band and exposure for the
    route, the dominant node for the action. Exposing them is exposing what
    the product already decides. Without them, a planner asked "who owns the
    high-risk names and by when" would have to reimplement the matrix, and a
    reimplemented control is not the control.
    """
    return [
        Field("escalation_rung", "Escalation rung",
              "The ladder level the escalation matrix routes this obligor to, "
              "from its band and its exposure tier. L0 to L5.",
              WORKFLOW, dtype="string", derived=True,
              source="early_warning_escalation_matrix"),
        Field("escalation_role", "Escalation owner",
              "The title behind that rung — who actually takes the decision. "
              "A role, not a named person: the matrix routes to positions.",
              WORKFLOW, dtype="string", derived=True,
              source="early_warning_escalation_matrix"),
        Field("escalation_notified", "Also notified",
              "The roles informed alongside the deciding rung. Empty where "
              "the matrix notifies nobody beyond the owner.",
              WORKFLOW, dtype="string", derived=True,
              source="early_warning_escalation_matrix"),
        Field("escalation_exposure_tier", "Exposure tier",
              "Which materiality tier this obligor's exposure falls in. "
              "Severity decides urgency; materiality decides altitude.",
              WORKFLOW, dtype="category", derived=True,
              source="early_warning_escalation_matrix"),
        Field("escalation_ack_sla_days", "Acknowledgement SLA",
              "Working days the matrix allows for the escalation to be "
              "acknowledged, from the band and the exposure tier.",
              WORKFLOW, unit="days", derived=True,
              source="early_warning_escalation_matrix"),
        Field("escalation_decision_sla_days", "Decision SLA",
              "Working days the matrix allows for a decision to be taken.",
              WORKFLOW, unit="days", derived=True,
              source="early_warning_escalation_matrix"),
        Field("expected_action", "Expected action for the band",
              "What the methodology expects at this final band, from routine "
              "monitoring at the bottom to immediate escalation at the top.",
              WORKFLOW, dtype="string", derived=True,
              source="early_warning_methodology"),
        Field("recommended_action", "Recommended action",
              "The governed action the library holds for this obligor's "
              "dominant sub-category. Empty where nothing fired. An action "
              "invented at answer time is not a governed one, which is why "
              "this is a field rather than a sentence.",
              WORKFLOW, dtype="string", derived=True,
              source="early_warning_action_library"),
        Field("action_owner_role", "Action owner code",
              "The ladder level or specialist route that owns the "
              "recommended action.", WORKFLOW, dtype="string", derived=True,
              source="early_warning_action_library"),
        Field("action_owner", "Action owner",
              "The title behind that code — the role that carries the "
              "action.", WORKFLOW, dtype="string", derived=True,
              source="early_warning_action_library"),
        Field("action_timeframe_days", "Action timeframe",
              "Working days the action library allows for the recommended "
              "action. Zero means immediate; minus one means no action is "
              "recommended because nothing fired.",
              WORKFLOW, unit="days", derived=True,
              source="early_warning_action_library"),
        Field("evidence_to_close", "Evidence to close",
              "What has to be produced for the recommended action to be "
              "considered done. An action with no closing test is a note.",
              WORKFLOW, dtype="string", derived=True,
              source="early_warning_action_library"),
        Field("action_reversibility_rank", "Action reversibility",
              "How reversible the recommended action is, 1 to 5, where 1 "
              "preserves the bank's position and closes nothing off. This "
              "and cost are what answer 'if I only do one thing' — not the "
              "score.", WORKFLOW, unit="rank 1-5", derived=True,
              source="early_warning_action_library"),
        Field("action_cost_rank", "Action cost",
              "How expensive the recommended action is to take, 1 to 5, "
              "where 1 is essentially free.",
              WORKFLOW, unit="rank 1-5", derived=True,
              source="early_warning_action_library"),
    ]


@functools.lru_cache(maxsize=1)
def fields() -> tuple[Field, ...]:
    """Every analytical field, described. Cached: it is static per build."""
    return tuple(_customer_fields() + _core_credit_fields()
                 + _signal_fields() + _subcategory_fields() + _layer_fields()
                 + _matrix_fields() + _final_fields() + _movement_fields()
                 + _workflow_fields())


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


def reset() -> None:
    """Forget the measured profile. Called when the domain is rebuilt."""
    fields.cache_clear()
    profile.cache_clear()
    to_dict.cache_clear()


@functools.lru_cache(maxsize=4)
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


@functools.lru_cache(maxsize=4)
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
           "fields", "groups", "names", "profile", "reset", "to_dict"]

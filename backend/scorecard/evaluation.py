"""
Layered scorecard evaluation. §A5, §A6.

What this measures, and what it does not
------------------------------------------
It measures whether the deterministic system can SETTLE each case in the
scorecard corpus: whether the metric exists, whether the month resolves,
whether the maturity rule fires, whether the refusal the case expects is a
refusal the engine actually makes. That is a real property and it is worth a
number.

It does not measure a model's answers. Scoring a language model needs a
language model, and this phase runs no live provider — so this module reports
**readiness by dimension**, not accuracy by dimension, and says which it is
in every payload it produces. A readiness figure presented as an accuracy
figure would be the most flattering mistake available here, so `basis` is a
required field on the result rather than a footnote.

The six dimensions are the platform's own
--------------------------------------------
Read from `backend.assurance.dimensions` rather than restated, so a scorecard
evaluation and an assurance panel cannot come to mean different things by
"analytical design". §A6's scorecard-specific items are registered as
subcomponents under those six.

§A5's reference expectations
------------------------------
`expectations()` derives, for one scorecard type and month, what a correct
answer must settle: the model, the maturity, the population, the metric
definitions, the variables, the equation, the invariants. It carries no
figure. §A5's rule — do not teach exact numeric answers to the live planner
before execution — is met by there being no number in it to teach.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.assurance import dimensions as dims
from backend.scorecard import build as build_mod
from backend.scorecard import critical as critical_mod
from backend.scorecard import dashboard as dash
from backend.scorecard import policy as policy_mod
from backend.scorecard import synthetic as synth
from backend.scorecard import variables as vars_mod

logger = logging.getLogger(__name__)

EVALUATION_VERSION = "1.0.0"

#: What a score in this module is a score OF. Carried on every payload,
#: because "82%" with no basis is the sentence that turns a readiness check
#: into a claimed accuracy.
STRUCTURAL = "STRUCTURAL_READINESS"
LIVE = "LIVE_MODEL_ACCURACY"

BASIS_MEANS: dict[str, str] = {
    STRUCTURAL: ("Whether the deterministic system can settle the case: the "
                 "metric exists, the month resolves, the maturity rule "
                 "fires, the expected refusal is one the engine makes. No "
                 "model was asked anything."),
    LIVE: ("Whether a language model's answers satisfied the cases. Requires "
           "a live provider and is not run in this environment."),
}

# --------------------------------------------------------------- §A6 layers

#: §A6's items, registered under the platform's six dimensions. The mapping
#: is the interesting part: "maturity" is ANALYTICAL_DESIGN and not
#: COMPUTATION, because choosing a month whose window has closed is a design
#: decision made before any arithmetic happens — and a system that treats it
#: as a computation concern discovers it too late.
LAYERS: dict[str, tuple[str, ...]] = {
    dims.UNDERSTANDING: (
        "scorecard_intent", "application_versus_behavioral",
        "model_resolution", "same_turn_context", "objective_extraction",
    ),
    dims.DESIGN: (
        "period_selection", "outcome_maturity", "metric_definition",
        "data_selection", "variable_resolution", "plan_completeness",
        "equation_resolution", "method_choice",
    ),
    dims.COMPUTATION: (
        "generated_query", "auc", "gini", "ks", "brier", "log_loss",
        "rmse", "guarded_mape", "observed_default_rate", "score_psi",
        "variable_csi", "information_value", "score_replication",
        "logit_replication", "pd_replication", "business_invariants",
    ),
    dims.JUDGMENT: (
        "interpretation", "discrimination_calibration_stability_distinction",
        "causality_language", "variable_driver_wording",
        "visualization_choice", "report_structure",
        "two_decimal_presentation",
    ),
    dims.AGENTIC: (
        "specialist_selection", "low_discrimination_investigation",
        "accuracy_deterioration_investigation", "challenge_pass",
        "assurance_record",
    ),
    dims.RELIABILITY: (
        "controlled_failure", "maturity_guard", "report_consistency",
        "no_unexplained_error", "dashboard_report_reconciliation",
        "feature_actions",
    ),
}

#: Which layer each scorecard family exercises. A family that exercised no
#: layer would be a family whose score contributed to nothing.
FAMILY_LAYERS: dict[str, tuple[str, ...]] = {
    "SCORECARD_DATA_DISCOVERY": (dims.UNDERSTANDING, dims.DESIGN),
    "SCORECARD_MODEL_EQUATION": (dims.DESIGN, dims.COMPUTATION),
    "SCORECARD_VARIABLES": (dims.UNDERSTANDING, dims.DESIGN),
    "SCORECARD_WOE_BINNING": (dims.DESIGN, dims.COMPUTATION),
    "SCORECARD_DISCRIMINATION": (dims.COMPUTATION, dims.JUDGMENT),
    "SCORECARD_CALIBRATION": (dims.COMPUTATION, dims.JUDGMENT),
    "SCORECARD_STABILITY": (dims.COMPUTATION, dims.DESIGN),
    "SCORECARD_PSI": (dims.COMPUTATION, dims.DESIGN),
    "SCORECARD_CSI": (dims.COMPUTATION, dims.DESIGN),
    "SCORECARD_VARIABLE_DIAGNOSTICS": (dims.COMPUTATION, dims.JUDGMENT),
    "SCORECARD_IMPLEMENTATION": (dims.COMPUTATION, dims.RELIABILITY),
    "SCORECARD_SEGMENT_PERFORMANCE": (dims.DESIGN, dims.JUDGMENT),
    "SCORECARD_CUTOFF": (dims.RELIABILITY, dims.JUDGMENT),
    "SCORECARD_OVERRIDE": (dims.RELIABILITY,),
    "SCORECARD_MODEL_COMPARISON": (dims.DESIGN, dims.JUDGMENT),
    "SCORECARD_RESCORING": (dims.RELIABILITY, dims.AGENTIC),
    "SCORECARD_MATURITY": (dims.DESIGN, dims.RELIABILITY),
    "SCORECARD_DEFAULT_DEFINITION": (dims.UNDERSTANDING, dims.DESIGN),
    "SCORECARD_REPORT": (dims.JUDGMENT, dims.RELIABILITY),
    "SCORECARD_REGULATORY": (dims.JUDGMENT,),
    "SCORECARD_AGENTIC_DIAGNOSIS": (dims.AGENTIC, dims.JUDGMENT),
    "SCORECARD_AMBIGUITY": (dims.UNDERSTANDING,),
    "SCORECARD_CONTROLLED_FAILURE": (dims.RELIABILITY,),
}


class EvaluationError(Exception):
    """An evaluation that cannot be run or reported as asked."""


# ------------------------------------------------------------ §A5 references


def expectations(scorecard_type: str, *, month: str = "",
                 model_kind: str = "INCUMBENT") -> dict[str, Any]:
    """§A5. What a correct answer must settle, with no figure in it.

    Derived from the governed objects rather than written down, so a
    variable renamed in the dictionary or a month added to the lake changes
    this without anybody editing it.
    """
    context = dash.resolve(scorecard_type, model_kind=model_kind, month=month)
    eq = build_mod.load_equation(scorecard_type, model_kind)
    spec = build_mod.load_spec(scorecard_type)
    if eq.score_mapping is None:
        raise EvaluationError(
            f"{model_kind} has no score mapping, so no expectation about "
            "score direction can be stated")

    return {
        "evaluation_version": EVALUATION_VERSION,
        "intent": "retail scorecard validation",
        "scorecard_type": scorecard_type,
        "model": model_kind,
        "model_version": "1.0.0",
        "period": context.month,
        "maturity": ("MATURED" if context.outcomes_available
                     else "NOT MATURED — STABILITY ONLY"),
        "performance_window_closes": synth.window_closes(
            context.month, horizon=context.horizon_months),
        "population": {
            "scorecard_type": scorecard_type,
            "dataset": build_mod.dataset_name(scorecard_type,
                                              "monthly_validation"),
            "baseline": build_mod.dataset_name(scorecard_type,
                                               "development_reference"),
        },
        "metric_definitions": {
            "gini": "Gini = 2 * AUC - 1",
            "ks": "the maximum gap between the cumulative bad and good "
                  "distributions",
            "psi": "sum over bins of (current - reference) * ln(current / "
                   "reference), on the SCORE",
            "csi": "the same index on ONE VARIABLE's bins",
            "brier": "the mean squared error between predicted PD and the "
                     "realised outcome",
        },
        "variables": {
            "in_model": list(eq.active_variables),
            "scoreable": sorted(vars_mod.scoreable(scorecard_type)),
            "not_scoreable": list(vars_mod.sensitive(scorecard_type)),
        },
        "equation": {
            "link": eq.link,
            "terms": [t.variable for t in eq.terms],
            "score_direction": eq.score_mapping.score_direction,
            "binning_spec_version": spec.spec_version,
        },
        "relationships": {
            "monthly_to_development": "the same account keys, one month "
                                      "against the development sample",
        },
        "plan": {
            "requires_matured_outcome_for": ["discrimination", "calibration"],
            "available_without_outcome": ["stability", "psi", "csi",
                                          "implementation"],
        },
        "query": {"reads": "the governed Parquet partition for the month"},
        "result": {"grain": "one row per account, aggregated to the metric"},
        "invariants": [
            "no outcome metric is computed on an open performance window",
            "the score direction is read from the registry",
            "Weight of Evidence is not recomputed from the validation month",
            "a metric with no approved limit reads NO APPROVED LIMIT",
        ],
        "chart_type": "KPI for a single statistic, SERIES over months, "
                      "TABLE by band or variable",
        "clarification": "ask which model, month or metric where the "
                         "question names none",
        "controlled_failure": "refuse and name what is missing",
        "policy_version": policy_mod.POLICY_VERSION,
        "carries_no_figure": True,
    }


# ----------------------------------------------------------- §A6 evaluation


@dataclass
class CaseOutcome:
    case_id: str
    family: str
    difficulty: str
    dimensions: tuple[str, ...]
    settled: bool
    why: str = ""


@dataclass
class Layered:
    """A layered result, carrying what it is a result OF."""

    basis: str = STRUCTURAL
    outcomes: list[CaseOutcome] = field(default_factory=list)
    critical: critical_mod.Result | None = None

    def by(self, attribute: str) -> dict[str, dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        for outcome in self.outcomes:
            key = str(getattr(outcome, attribute))
            bucket = buckets.setdefault(key, {"cases": 0, "settled": 0})
            bucket["cases"] += 1
            bucket["settled"] += int(outcome.settled)
        for bucket in buckets.values():
            bucket["rate"] = (round(bucket["settled"] / bucket["cases"], 4)
                              if bucket["cases"] else 0.0)
        return dict(sorted(buckets.items()))

    def by_dimension(self) -> dict[str, dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {
            d: {"cases": 0, "settled": 0} for d in dims.DIMENSIONS}
        for outcome in self.outcomes:
            for dimension in outcome.dimensions:
                bucket = buckets[dimension]
                bucket["cases"] += 1
                bucket["settled"] += int(outcome.settled)
        for name, bucket in buckets.items():
            bucket["label"] = dims.LABELS[name]
            bucket["subcomponents"] = len(LAYERS.get(name, ()))
            bucket["rate"] = (round(bucket["settled"] / bucket["cases"], 4)
                              if bucket["cases"] else None)
        return buckets

    def to_dict(self) -> dict[str, Any]:
        unsettled = [o for o in self.outcomes if not o.settled]
        return {
            "evaluation_version": EVALUATION_VERSION,
            "basis": self.basis,
            "basis_means": BASIS_MEANS[self.basis],
            "cases": len(self.outcomes),
            "settled": len(self.outcomes) - len(unsettled),
            "by_dimension": self.by_dimension(),
            "by_family": self.by("family"),
            "by_difficulty": self.by("difficulty"),
            "unsettled": [{"case": o.case_id, "family": o.family,
                           "why": o.why} for o in unsettled[:40]],
            # §A6: do not average away a critical failure. It is reported
            # beside the rates and never folded into them.
            "critical": (self.critical.to_dict() if self.critical else None),
            "critical_failures_are_not_averaged": True,
        }


def _settles(case: Any) -> tuple[bool, str]:
    """Whether the deterministic system can settle this case.

    Structural: the family is one the engine covers, the scorecard type
    resolves, and any month the case names is one the lake holds.
    """
    family = str(getattr(case, "family_id", "") or
                 getattr(case, "case_family", ""))
    if family not in FAMILY_LAYERS:
        return False, f"{family} is not mapped to any evaluation dimension"

    plan = dict(getattr(case, "analytical_plan_contract", None) or {})
    kind = str(plan.get("scorecard_type") or "")
    if kind and kind not in (build_mod.APP, build_mod.BEH):
        return False, f"{kind} is not a registered scorecard type"

    period = dict(getattr(case, "period_contract", None) or {})
    month = str(period.get("month") or "")
    if month and month not in dash.available_months(kind or build_mod.APP):
        return False, f"{month} is not a month the lake holds"

    if plan.get("requires_matured_outcome") and month and not synth.matured(
            month):
        return False, (f"the case asks for an outcome metric on {month}, "
                       "whose performance window has not closed")
    return True, ""


def run(cases: list[Any], *, basis: str = STRUCTURAL,
        with_critical: bool = True) -> Layered:
    """Evaluate a corpus, layer by layer.

    `basis` is required rather than defaulted silently in the payload: a
    structural readiness figure and a live accuracy figure are different
    measurements and must never be compared as though they were the same.
    """
    if basis not in BASIS_MEANS:
        raise EvaluationError(f"{basis} is not a recognised evaluation basis")
    if basis == LIVE:
        raise EvaluationError(
            "a live-model evaluation needs a provider, and this environment "
            "runs none. Reporting a structural figure under the live basis "
            "would present a readiness check as an accuracy score.")

    result = Layered(basis=basis)
    for case in cases:
        family = str(getattr(case, "family_id", "") or
                     getattr(case, "case_family", ""))
        settled, why = _settles(case)
        result.outcomes.append(CaseOutcome(
            case_id=str(getattr(case, "case_id", "")),
            family=family,
            difficulty=str(getattr(case, "difficulty", "")),
            dimensions=FAMILY_LAYERS.get(family, ()),
            settled=settled, why=why))
    if with_critical:
        result.critical = critical_mod.run()
    return result


def coverage() -> dict[str, Any]:
    """Which layers the corpus exercises, and which nothing reaches."""
    reached: dict[str, int] = {d: 0 for d in dims.DIMENSIONS}
    for layers in FAMILY_LAYERS.values():
        for dimension in layers:
            reached[dimension] += 1
    return {
        "evaluation_version": EVALUATION_VERSION,
        "dimensions": {d: {"label": dims.LABELS[d],
                           "families": reached[d],
                           "subcomponents": len(LAYERS.get(d, ()))}
                       for d in dims.DIMENSIONS},
        "unreached": [d for d in dims.DIMENSIONS if reached[d] == 0],
        "subcomponents": sum(len(v) for v in LAYERS.values()),
    }


__all__ = ["BASIS_MEANS", "EVALUATION_VERSION", "FAMILY_LAYERS", "LAYERS",
           "LIVE", "STRUCTURAL", "CaseOutcome", "EvaluationError", "Layered",
           "coverage", "expectations", "run"]

"""
Portable scorecard intelligence for the AI Brain Pack. §A8, §A9.

What travels, and what does not
---------------------------------
The Brain is a portable governed intelligence package: what the system knows
about *how to validate a scorecard*, not what it found when it validated one.
So this module exports the shape of the knowledge and none of the findings.

Carried:
  * the scorecard ontology and metric semantics — what PSI measures and why
    it is not CSI;
  * the maturity rules, which are the module's central control;
  * validation policy structure and the CBUAE-aligned report section list;
  * teaching-case IDENTITIES and family shapes, so a receiver can retrieve
    the same families;
  * agent and tool policies, visual grammar, validation methods;
  * the critical-case catalogue, so a receiver inherits the checks.

Never carried, and each for its own reason:
  * **Raw scorecard demo data.** Nineteen thousand rows a month is data, not
    intelligence, and a Brain that carried it would ship a portfolio.
  * **Fitted coefficients.** §A8 says confidential client coefficients stay
    behind. Ours are synthetic, but a rule that only holds for synthetic data
    is not a rule — the export carries which VARIABLES a model uses and the
    convention it declares, never the numbers that make it that model.
  * **Sealed holdout gold.** A package carrying the holdout produces a score
    that is flattering rather than wrong, and nothing downstream could tell.
  * **Secrets.** Nothing here reads an environment variable.

Compatibility
---------------
A Brain carrying scorecard intelligence that lands on an installation with no
Retail Scorecard module has to say so rather than half-installing. `MODULE`
is registered with the receiver's module list, and `required_modules` names
it, so the existing compatibility report produces MISSING MODULE — one
mechanism, not a second one for this module.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.brain import compatibility as compat
from backend.scorecard import build as build_mod
from backend.scorecard import critical as critical_mod
from backend.scorecard import evaluation as eval_mod
from backend.scorecard import policy as policy_mod
from backend.scorecard import registry as registry_mod
from backend.scorecard import report as report_mod
from backend.scorecard import synthetic as synth
from backend.scorecard import variables as vars_mod
from backend.teaching import families as fam

logger = logging.getLogger(__name__)

PORTABLE_VERSION = "1.0.0"

#: The module name a receiver must have. Registered in the receiver's module
#: list, so a package that needs it and an installation that lacks it meet at
#: the existing compatibility check rather than at a crash.
MODULE = "retail-scorecard"

#: §A8's exclusions, as data. A test asserts the export contains none of
#: them, which is stronger than a docstring saying it should not.
NEVER_EXPORTED: tuple[tuple[str, str], ...] = (
    ("raw scorecard rows",
     "nineteen thousand rows a month is data, not intelligence"),
    ("client data",
     "nothing in a portable package may describe a real customer"),
    ("fitted coefficients",
     "the numbers that make a model that model stay with the institution "
     "that fitted them"),
    ("sealed holdout gold",
     "a package carrying the holdout produces a flattering score and nothing "
     "downstream could tell"),
    ("secrets",
     "no environment variable is read on this path"),
)


class PortabilityError(Exception):
    """Something that may not be exported, or a package that may not land."""


# ------------------------------------------------------------- the payload


def ontology() -> dict[str, Any]:
    """What the module means by its own words.

    The distinctions are the payload. "Stability" and "PSI" and "CSI" get
    merged in conversation, and a receiver that inherited them merged would
    answer a CSI question with a PSI figure and look right doing it.
    """
    return {
        "concepts": {
            "scorecard": "a fitted model mapping applicant or account "
                         "characteristics to a score and a probability of "
                         "default",
            "application_scorecard": "scored at origination, on the "
                                     "applicant's characteristics at the "
                                     "point of application",
            "behavioral_scorecard": "scored on an open account, on its "
                                    "observed behaviour over a window",
            "weight_of_evidence": "the log odds of a bin relative to the "
                                  "population, fitted on the development "
                                  "sample and frozen",
            "information_value": "how much a variable's binning separates "
                                 "good from bad, under the approved bins",
            "discrimination": "whether the score RANKS risk correctly",
            "calibration": "whether the predicted LEVEL of risk is right",
            "stability": "whether the population has moved away from the "
                         "one the model was built on",
            "population_stability_index": "stability of the SCORE "
                                          "distribution",
            "characteristic_stability_index": "stability of ONE VARIABLE's "
                                              "bins",
            "outcome_maturity": "whether the performance window for a cohort "
                                "has closed",
            "candidate_model": "a proposed equation recorded beside the "
                               "active one and never in place of it",
        },
        "distinctions": [
            "discrimination and calibration are different questions and a "
            "model can be good at one and bad at the other",
            "PSI is the score's distribution; CSI is one variable's bins",
            "a variable's Gini is not the model's Gini",
            "the latest data month is not the latest matured month",
            "a metric with no approved limit has not passed",
        ],
        "scorecard_types": list(build_mod.SCORECARD_TYPES)
        if hasattr(build_mod, "SCORECARD_TYPES") else [build_mod.APP,
                                                       build_mod.BEH],
        "ontology_version": PORTABLE_VERSION,
    }


def metric_semantics() -> dict[str, Any]:
    """How each metric is defined, and what it must never be read as."""
    return {
        "definitions": eval_mod.expectations(
            build_mod.APP)["metric_definitions"],
        "never": {
            "auc": "a probability that the model is right",
            "gini": "a rating, a PD or a capital input",
            "psi": "a regulatory threshold breach on the conventional "
                   "cut-offs alone",
            "information_value": "a regulatory classification, whatever the "
                                 "strength label says",
            "mape": "a defined quantity on a band whose observed rate is at "
                    "or near zero",
        },
        "requires_matured_outcome": ["auc", "gini", "ks", "brier_score",
                                     "log_loss", "observed_default_rate",
                                     "calibration_slope", "mape"],
        "available_without_outcome": ["score_psi", "variable_csi",
                                      "information_value",
                                      "score_distribution",
                                      "implementation_replication"],
    }


def maturity_rules() -> dict[str, Any]:
    """§7, portable. The control the module is built around."""
    return {
        "rule": "never calculate actual against predicted on a cohort whose "
                "performance window has not closed",
        "default_horizon_months": synth.DEFAULT_HORIZON_MONTHS,
        "resolution": "the latest MATURED month, not the latest month",
        "on_an_open_window": "report stability and distribution metrics, and "
                             "state the month the window closes in",
        "never": "return zero, which reads as a month with no defaults",
    }


def teaching_families() -> dict[str, Any]:
    """Family identities and obligations, not the cases themselves.

    A receiver inherits the SHAPE of what to teach and retrieves its own
    cases. Shipping the case bodies would ship this installation's phrasing
    as though it were knowledge.
    """
    return {
        "families": [
            {"id": family.id, "label": family.label, "group": family.group,
             "teaches": family.teaches, "scope": family.scope,
             "outcome": family.outcome}
            for family in fam.in_group(fam.SCORECARD)
        ],
        "family_version": fam.FAMILY_VERSION,
    }


def validation_policy() -> dict[str, Any]:
    """Limit STRUCTURE and provenance vocabulary, not this bank's numbers."""
    return {
        "policy_version": policy_mod.POLICY_VERSION,
        "provenances": list(policy_mod.PROVENANCES),
        "statuses": list(policy_mod.STATUSES),
        "directions": list(policy_mod.DIRECTIONS),
        "metrics_governed": sorted(policy_mod.LIMITS_BY_METRIC),
        "rule": "a metric with no approved limit reads NO APPROVED LIMIT, "
                "which is not a pass and is not NOT MEASURED",
        "seeded_limits_are": policy_mod.DEMO_POLICY,
        "thresholds_excluded_because": (
            "a limit is an institution's decision. The vocabulary travels; "
            "the numbers do not."),
        "opinions": list(policy_mod.OPINIONS)
        if hasattr(policy_mod, "OPINIONS") else [],
    }


def report_structure() -> dict[str, Any]:
    """The CBUAE-aligned section list and the coverage map."""
    return {
        "structure_version": report_mod.REPORT_STRUCTURE_VERSION,
        "coverage": dict(report_mod.COVERAGE),
        "disclaimer": report_mod.DISCLAIMER,
        "alignment_means": (
            "a claim about the section list, not about a regulator having "
            "approved anything"),
    }


def model_shapes() -> dict[str, Any]:
    """Which variables a model uses and what it declares — never the fitted
    numbers.

    §A8's "confidential client coefficients". Ours are synthetic, and a rule
    that only holds for synthetic data is not a rule.
    """
    out: dict[str, Any] = {}
    for kind in (build_mod.APP, build_mod.BEH):
        equation = build_mod.load_equation(kind, "INCUMBENT")
        out[kind] = {
            "link": equation.link,
            "variables": list(equation.active_variables),
            "transformation": "WOE",
            "score_direction_is": "declared by the registry, never assumed",
            "score_mapping_formula": (
                "Factor = PDO / ln(2); Offset = BaseScore - Factor * "
                "ln(BaseOdds); Score = Offset - Factor * logit_bad"),
            "coefficients_excluded_because": (
                "the numbers that make a model that model stay with the "
                "institution that fitted them"),
            "candidate_variables": sorted(
                set(vars_mod.names(kind)) - set(equation.active_variables)),
            "not_scoreable": list(vars_mod.sensitive(kind)),
        }
    return out


def agent_and_tool_policy() -> dict[str, Any]:
    return {
        "specialist": "scorecard_validation_specialist",
        "runs": ["low discrimination investigation",
                 "accuracy deterioration investigation",
                 "stability and drift investigation"],
        "claim_strength": {
            "ASSOCIATED_WITH": "reported where no ablation was run",
            "ACCOUNTS_FOR": "reported only where a leave-one-out comparison "
                            "was actually computed",
        },
        "never": "assert a cause from a correlation",
    }


def visual_grammar() -> dict[str, Any]:
    return {
        "single_statistic": "KPI",
        "over_months": "SERIES with the immature tail marked",
        "by_band_or_variable": "TABLE",
        "distribution_against_baseline": "BAR, both distributions shown",
        "statistics_decimals": 4,
        "rates_and_money_decimals": 2,
        "statistics_at_four_because": (
            "an AUC that moved 0.7179 to 0.7104 is the finding, and at two "
            "decimals both read 0.72"),
    }


def validation_methods() -> dict[str, Any]:
    return {
        "discrimination": ["AUC with a confidence interval", "Gini", "KS",
                           "gains and lift by decile"],
        "calibration": ["predicted against observed", "calibration slope",
                        "calibration in the large", "Brier", "log loss",
                        "bucket RMSE", "guarded MAPE"],
        "stability": ["score PSI against the development baseline",
                      "per-variable CSI", "missing and unseen bin rates"],
        "implementation": ["bin, WoE, logit, PD and score recomputed from the "
                           "stored specification"],
        "comparison": ["identical population and period",
                       "confidence intervals compared before ranking"],
    }


def critical_cases() -> dict[str, Any]:
    """The checks a receiver inherits, by name and severity."""
    return {
        "critical_version": critical_mod.CRITICAL_VERSION,
        "checks": critical_mod.catalogue(),
        "requirement": "zero failures",
    }


def registry_governance() -> dict[str, Any]:
    return {
        "statuses": list(registry_mod.STATUSES),
        "transitions": {k: list(v)
                        for k, v in registry_mod.TRANSITIONS.items()},
        "rules": [
            "a candidate never overwrites the active model",
            "ACTIVE is reachable only from APPROVED",
            "activation retires whatever else was active for that scorecard "
            "type",
            "proposing and approving are different permissions",
        ],
    }


def package() -> dict[str, Any]:
    """Everything §A8 says the Brain should carry, and nothing it should
    not."""
    return {
        "portable_version": PORTABLE_VERSION,
        "module": MODULE,
        "ontology": ontology(),
        "metric_semantics": metric_semantics(),
        "maturity_rules": maturity_rules(),
        "teaching_families": teaching_families(),
        "validation_policy": validation_policy(),
        "report_structure": report_structure(),
        "model_shapes": model_shapes(),
        "agent_and_tool_policy": agent_and_tool_policy(),
        "visual_grammar": visual_grammar(),
        "validation_methods": validation_methods(),
        "critical_cases": critical_cases(),
        "registry_governance": registry_governance(),
        "excluded": [{"what": what, "why": why}
                     for what, why in NEVER_EXPORTED],
    }


# --------------------------------------------------------- what may not go


#: Field names that would carry a fitted coefficient or a row of data. The
#: audit walks the payload for them rather than trusting the builders.
FORBIDDEN_KEYS: tuple[str, ...] = (
    "coefficient", "coefficients", "intercept", "rows", "frame",
    "observations", "holdout", "gold", "api_key", "secret", "token",
    "password", "customer_id", "account_id",
)


def audit(payload: dict[str, Any] | None = None) -> list[str]:
    """Everything in the payload that may not leave. Empty means clean.

    Walks the built payload rather than reasoning about the builders,
    because the builders are what would change.
    """
    payload = package() if payload is None else payload
    problems: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = str(key).lower()
                for forbidden in FORBIDDEN_KEYS:
                    if lowered == forbidden or lowered.endswith(
                            f"_{forbidden}"):
                        problems.append(
                            f"{path}.{key}: a portable package may not carry "
                            f"{forbidden}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list | tuple):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, float):
            # A bare float in an intelligence payload is almost always a
            # measurement that should have stayed behind. The decimal
            # constants in the visual grammar are ints by construction.
            problems.append(f"{path}: a portable package carries no measured "
                            "value")

    walk(payload, "package")
    return problems


def requires() -> tuple[str, ...]:
    """What a receiver must have for this intelligence to be usable."""
    return (MODULE,)


def receiver_has_module(receiver: compat.Receiver | None = None) -> bool:
    here = receiver or compat.Receiver.here()
    return MODULE in here.modules


def compatibility(manifest: Any,
                  receiver: compat.Receiver | None = None) -> Any:
    """§A8's compatibility report, through the existing mechanism.

    A package that declares this module and lands somewhere without it
    produces MISSING MODULE from `compat.check` — the same finding kind any
    other missing module produces, because a second mechanism for this one
    module would be a second thing to keep correct.
    """
    return compat.check(manifest, receiver)


__all__ = ["FORBIDDEN_KEYS", "MODULE", "NEVER_EXPORTED", "PORTABLE_VERSION",
           "PortabilityError", "audit", "compatibility", "critical_cases",
           "maturity_rules", "metric_semantics", "model_shapes", "ontology",
           "package", "receiver_has_module", "registry_governance",
           "report_structure", "requires", "teaching_families",
           "validation_methods", "validation_policy", "visual_grammar"]


# ---------------------------------------------------------------- §A9 lift


#: The scorecard-specific subcomponents a lift report breaks out beneath the
#: six dimensions. Named so a receiver can see WHERE imported intelligence
#: helped rather than only that a dimension moved.
LIFT_SUBCOMPONENTS: tuple[str, ...] = (
    "outcome_maturity", "metric_definition", "score_direction",
    "psi_versus_csi", "variable_versus_model", "score_replication",
    "candidate_governance", "regulatory_framing",
)


def lift(baseline_cases: list[Any], candidate_cases: list[Any], *,
         candidate_id: str = "", brain_name: str = "",
         brain_version: str = "") -> Any:
    """§A9. Local scorecard intelligence against local plus imported.

    Both sides are measured on the RECEIVER's sets. §A9 and §18 agree on
    this and for the same reason: a lift measured on the sender's cases is a
    measurement of how well the sender described its own cases.

    Growth in case count is not lift, and this does not let it look like
    lift. The Lift Lab's own evidence bands do that work — a dimension with
    fewer than its minimum cases is reported as INSUFFICIENT EVIDENCE rather
    than as an improvement — so the comparison goes through `liftlab.compare`
    rather than computing its own verdict.
    """
    from backend.brain import liftlab

    def scores(cases: list[Any]) -> dict[str, Any]:
        layered = eval_mod.run(cases, with_critical=False)
        by_dimension = layered.by_dimension()
        out: dict[str, Any] = {}
        for name, bucket in by_dimension.items():
            label = liftlab.DIMENSIONS[
                list(eval_mod.dims.DIMENSIONS).index(name)]
            out[label] = liftlab.Score(
                dimension=label,
                score=float(bucket["rate"] or 0.0),
                cases=int(bucket["cases"]),
                critical_failures=0,
                coverage=float(bucket["rate"] or 0.0))
        return out

    report = liftlab.compare(
        scores(baseline_cases), scores(candidate_cases),
        candidate_id=candidate_id, brain_name=brain_name,
        brain_version=brain_version,
        sets_used=("receiver_scorecard_development",),
        sender_holdout_used=False)
    report.notes.append(
        "Scorecard subcomponents measured: "
        + ", ".join(LIFT_SUBCOMPONENTS))
    report.notes.append(
        "Both sides were measured on the receiver's own development set. A "
        "larger case count is not reported as lift: a dimension below its "
        "minimum case count reads as INSUFFICIENT EVIDENCE.")
    return report

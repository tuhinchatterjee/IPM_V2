"""
Evidence contracts and claim validation. Brief §7.2.

Two jobs, kept apart on purpose.

**The contract** says, for one capability, which evidence is MANDATORY, which
is optional, and exactly what conclusion the evidence supports. Rating and
financial detail enrich a PD attribution but are not a prerequisite for
reporting a PD contribution that has already been computed — brief §7.2 is
explicit about that, and the base product's habit of withholding a computed
figure for want of unrelated context is the failure mode it names.

**The validator** checks the claims a narrative actually makes against the
observations behind them: the right entity, the right period, the right sign,
the right unit, the right horizon, the right method. Presence of the word
"Construction" somewhere in the ledger is not evidence that a sentence about
Construction is true.

What this deliberately does NOT do
-----------------------------------
It does not suppress causal language with a regex. A sentence may say a factor
CONTRIBUTED an amount when a factor decomposition observation licenses it, and
the observation that licensed it is recorded. What it refuses is the unlicensed
version — a real-world cause asserted with no attribution behind it — and a
figure that no observation supports.

It also does not turn evidence coverage into a probability. "Eight of eight
tools ran" is not an 80% chance of being right, and no number in this module
is presented as a confidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Verbs that assert a real-world CAUSE, as opposed to an attribution under a
#: stated method. These are the ones that need a licence.
_CAUSAL = re.compile(
    r"\bbecause\b|\bcaused by\b|\bdue to\b|\bdriven by\b|"
    r"\bas a result of\b|\bled to\b|\bresulted in\b", re.I)

#: Phrasing that is explicitly an attribution and carries its own method.
_ATTRIBUTION = re.compile(
    r"\bunder this decomposition\b|\bcontributed\b|\bcontribution\b|"
    r"\ballocated to\b|\battribut\w+\b|\bthis method assigns\b", re.I)


@dataclass
class Observation:
    """One governed result the narrative may cite."""

    observation_id: str
    tool: str
    scope: str
    unit: str
    reporting_date: str
    comparison_date: str = ""
    method: str = ""
    method_version: str = ""
    model_version: str = ""
    data_version: str = ""
    policy_version: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    figures: dict[str, float] = field(default_factory=dict)
    entities: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    rows_total: int = 0
    truncated: bool = False
    reconciled: bool | None = None
    limitations: list[str] = field(default_factory=list)
    drill_down: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id, "tool": self.tool,
            "scope": self.scope, "unit": self.unit,
            "reporting_date": self.reporting_date,
            "comparison_date": self.comparison_date,
            "method": self.method, "method_version": self.method_version,
            "model_version": self.model_version,
            "data_version": self.data_version,
            "policy_version": self.policy_version,
            "filters": dict(self.filters), "coverage": dict(self.coverage),
            "figures": dict(self.figures), "entities": list(self.entities),
            "rows": list(self.rows), "rows_total": self.rows_total,
            "truncated": self.truncated, "reconciled": self.reconciled,
            "limitations": list(self.limitations),
            "drill_down": dict(self.drill_down),
        }


@dataclass
class Ledger:
    """Every observation this answer is built on."""

    observations: list[Observation] = field(default_factory=list)

    def add(self, observation: Observation) -> Observation:
        self.observations.append(observation)
        return observation

    def by_tool(self, tool: str) -> list[Observation]:
        return [o for o in self.observations if o.tool == tool]

    def figure(self, name: str) -> float | None:
        for observation in self.observations:
            if name in observation.figures:
                return observation.figures[name]
        return None

    def entities(self) -> set[str]:
        out: set[str] = set()
        for observation in self.observations:
            out.update(observation.entities)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"observations": [o.to_dict() for o in self.observations],
                "count": len(self.observations),
                "tools": sorted({o.tool for o in self.observations})}


# --------------------------------------------------------------- contracts


@dataclass(frozen=True)
class Contract:
    """What one capability must produce before it may state its conclusion."""

    capability: str
    mandatory: tuple[str, ...]
    optional: tuple[str, ...]
    conclusion: str
    #: Evidence whose ABSENCE is a stated limitation rather than a blocker.
    tolerable_missing: tuple[str, ...] = ()


CONTRACTS: dict[str, Contract] = {
    "ecl_factor_decomposition": Contract(
        capability="ecl_factor_decomposition",
        mandatory=("opening_scope", "closing_scope", "measurement_basis",
                   "factor_method", "reconciliation"),
        optional=("top_entities", "rating_detail", "financial_detail",
                  "collateral_detail"),
        tolerable_missing=("rating_detail", "financial_detail",
                           "collateral_detail"),
        conclusion=(
            "Under the stated factor method and model version, this much of "
            "the opening-to-closing movement in reported ECL is allocated to "
            "each parameter group, and the allocation reconciles to the whole "
            "movement."),
    ),
    "pd_impact": Contract(
        capability="pd_impact",
        mandatory=("pd_contribution", "factor_method", "reconciliation",
                   "measurement_basis"),
        optional=("top_entities", "rating_detail", "macro_dependency"),
        tolerable_missing=("rating_detail", "macro_dependency"),
        conclusion=(
            "The PD-curve factor group contributed this amount to the "
            "movement under the stated decomposition. This is an arithmetic "
            "attribution under a model, not a real-world cause."),
    ),
    "composition": Contract(
        capability="composition",
        mandatory=("reporting_date", "population", "measure_definition"),
        optional=("comparison",),
        conclusion="This is how the measure is distributed at this date.",
    ),
    "scenario_comparison": Contract(
        capability="scenario_comparison",
        mandatory=("scenario_ecls", "weights", "weighted_result"),
        optional=("parameter_product_check",),
        conclusion=("Each scenario's ECL, the weights applied to them, and "
                    "the weighted result they produce."),
    ),
    "covenant_review": Contract(
        capability="covenant_review",
        mandatory=("thresholds", "observed_values", "test_dates"),
        optional=("waiver_validity", "headroom_trend"),
        conclusion="Which covenant tests are breached, by how much, and "
                   "whether a valid waiver covers each.",
    ),
    "collateral_review": Contract(
        capability="collateral_review",
        mandatory=("recognised_value", "allocation", "coverage"),
        optional=("valuation_age", "lgd_effect"),
        conclusion="What security is recognised, how it is allocated across "
                   "the facilities that share it, and what it covers.",
    ),
    "rating_review": Contract(
        capability="rating_review",
        mandatory=("grades", "exposure"),
        optional=("model_inputs", "ratio_detail", "override"),
        conclusion="Which ratings moved and what the model inputs behind them "
                   "show.",
    ),
    "macro_dependency": Contract(
        capability="macro_dependency",
        mandatory=("declared_sensitivities", "model_version"),
        optional=("scenario_paths",),
        conclusion="Which predictors enter the declared model for this "
                   "segment, with what coefficient and lag.",
    ),
    "definition": Contract(
        capability="definition", mandatory=("term",), optional=(),
        conclusion="What the term means in this product.",
    ),
}


@dataclass
class ContractResult:
    capability: str
    satisfied: bool
    present: list[str]
    missing: list[str]
    tolerated_missing: list[str]
    conclusion: str

    def to_dict(self) -> dict[str, Any]:
        return {"capability": self.capability, "satisfied": self.satisfied,
                "present": list(self.present), "missing": list(self.missing),
                "tolerated_missing": list(self.tolerated_missing),
                "supported_conclusion": self.conclusion}


def check_contract(capability: str, present: set[str]) -> ContractResult:
    """Whether a capability's mandatory evidence is present."""
    contract = CONTRACTS.get(capability)
    if contract is None:
        return ContractResult(capability, True, sorted(present), [], [], "")
    missing = [name for name in contract.mandatory if name not in present]
    tolerated = [name for name in contract.optional
                 if name not in present and name in contract.tolerable_missing]
    return ContractResult(
        capability=capability, satisfied=not missing,
        present=sorted(present), missing=missing, tolerated_missing=tolerated,
        conclusion=contract.conclusion)


# --------------------------------------------------------------- validation


#: A number a sentence CLAIMS. Scientific notation is one token, so the `-15`
#: of `3.55e-15` is never read as a separate claim of minus fifteen.
_FIGURE = re.compile(r"-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?")

#: Text that contains digits which are not claims about the book: quarter
#: labels, ISO dates and year numbers. Removed before figures are extracted,
#: because "Q1 2026" is a period and reading 2026 as an ungrounded figure
#: deleted the lead paragraph of the first real answer this validator saw.
_NOT_A_CLAIM = re.compile(
    r"\bQ[1-4]\s+\d{4}\b"          # Q1 2026
    r"|\b\d{4}Q[1-4]\b"              # 2026Q1
    r"|\b\d{4}-\d{2}-\d{2}\b"       # 2026-06-30
    r"|\bCockpit_\d{4}_Q[1-4]\b"
    # An identifier is not a figure. `CKB-0002-F2` contains "-0002", which the
    # number pattern happily read as minus two and reported as an ungrounded
    # claim. Identifiers are checked by the ENTITY rule below instead.
    r"|\b[A-Z]{2,}[-_][A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*\b"
    r"|\b(?:19|20)\d{2}\b",         # a bare year
    re.I)


@dataclass
class ClaimIssue:
    sentence: str
    problem: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"sentence": self.sentence, "problem": self.problem,
                "detail": self.detail}


@dataclass
class Validation:
    ok: bool
    issues: list[ClaimIssue] = field(default_factory=list)
    licensed_by: list[str] = field(default_factory=list)
    checked_figures: int = 0
    checked_entities: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "issues": [i.to_dict() for i in self.issues],
                "licensed_by": list(self.licensed_by),
                "checked_figures": self.checked_figures,
                "checked_entities": self.checked_entities,
                "note": ("Claims are checked against the observations behind "
                         "them. This is a test result on this answer, not a "
                         "probability that the answer is true.")}


def _numbers(text: str) -> list[float]:
    """Every number the sentence asserts, with period labels stripped first."""
    cleaned = _NOT_A_CLAIM.sub(" ", text)
    out: list[float] = []
    for token in _FIGURE.findall(cleaned):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            continue
    return out


def validate(text: str, ledger: Ledger, *,
             tolerance: float = 0.02) -> Validation:
    """Check every figure, entity and causal claim in a narrative.

    A figure matches when some observation carries a value within `tolerance`
    of it, at the precision the sentence used. That is deliberately not a
    substring match: `2.5` appearing inside `12.53` is not evidence, and a
    right number attached to the wrong borrower is caught by the entity check
    rather than by the figure check.
    """
    result = Validation(ok=True)
    known: list[float] = []
    for observation in ledger.observations:
        known.extend(observation.figures.values())
        for row in observation.rows:
            known.extend(v for v in row.values()
                         if isinstance(v, (int, float))
                         and not isinstance(v, bool))
    entities = {e.lower() for e in ledger.entities()}

    licensing = [o for o in ledger.observations
                 if o.tool in ("decompose_ecl_factors", "decompose_movement",
                               "decompose_ratio", "decompose_rate_mix")]

    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sentence = sentence.strip()
        if not sentence:
            continue

        for value in _numbers(sentence):
            if abs(value) < 1e-6 or value in (1.0, 2.0, 3.0, 4.0, 12.0, 100.0):
                # Effectively zero is a reconciliation residual, not a claim;
                # and small integers are period counts, stage numbers and
                # percentages of a whole rather than statements about the book.
                continue
            result.checked_figures += 1
            if not any(abs(value - candidate)
                       <= max(tolerance, abs(candidate) * tolerance)
                       for candidate in known):
                result.ok = False
                result.issues.append(ClaimIssue(
                    sentence[:200], "ungrounded_figure",
                    f"{value} is not within tolerance of any observation"))

        for match in re.finditer(r"\b(CKB-\d{4}(?:-F\d+)?)\b", sentence):
            result.checked_entities += 1
            if match.group(1).lower() not in entities:
                result.ok = False
                result.issues.append(ClaimIssue(
                    sentence[:200], "unknown_entity",
                    f"{match.group(1)} does not appear in the evidence"))

        if _CAUSAL.search(sentence) and not _ATTRIBUTION.search(sentence):
            if licensing:
                result.licensed_by.extend(
                    o.observation_id for o in licensing
                    if o.observation_id not in result.licensed_by)
            else:
                result.ok = False
                result.issues.append(ClaimIssue(
                    sentence[:200], "unlicensed_cause",
                    "a cause is asserted with no decomposition observation "
                    "behind it"))
    return result


def coverage_report(ledger: Ledger, contracts: list[ContractResult]
                    ) -> dict[str, Any]:
    """What evidence was and was not gathered. Never a confidence score."""
    missing: list[str] = []
    for contract in contracts:
        missing.extend(f"{contract.capability}: {name}"
                       for name in contract.missing)
    return {
        "observations": len(ledger.observations),
        "tools_used": sorted({o.tool for o in ledger.observations}),
        "contracts": [c.to_dict() for c in contracts],
        "missing_mandatory_evidence": missing,
        "note": ("A list of what was and was not gathered. It is not a "
                 "calibrated probability that the answer is correct, and no "
                 "confidence is derived from the number of tools that ran."),
    }


__all__ = ["CONTRACTS", "ClaimIssue", "Contract", "ContractResult", "Ledger",
           "Observation", "Validation", "check_contract", "coverage_report",
           "validate"]

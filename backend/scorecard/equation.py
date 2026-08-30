"""
The scorecard equation, as an IR. §13, §16, §35.

A scorecard equation is a small, closed thing: an intercept, a handful of
coefficients on WoE-transformed variables, a link function, and a score
mapping. That is the whole language. There is no expression parser here, no
`eval`, and no place a user-supplied string becomes something the process
runs — §15's "no arbitrary Python execution, no arbitrary user formula
execution" is met by there being nothing to execute.

The sign convention is the registry's, not this module's
---------------------------------------------------------
§13: "Do not assume one sign convention. The registry defines it."

Some institutions map a higher score to lower risk; some do the opposite.
Both are correct and they invert every discrimination statistic. So
`score_direction` is a required field with no default, and every metric that
depends on it reads it rather than assuming.

What validation actually catches
---------------------------------
§16 lists twelve checks. The ones that matter most are not the type checks:

* **A variable that is not scoreable.** Demographic fields exist for
  fairness monitoring. An equation referencing one is refused, so the tag
  in `variables.py` is a control rather than a comment.
* **A coefficient whose sign contradicts credit sense.** A positive
  coefficient on an inverted WoE means the model is reading the variable
  backwards. It is reported as a finding rather than silently fitted around,
  because a model that is right on average and backwards on one factor
  fails differently — and worse — than one that is simply weak.
* **Score/PD monotonicity.** If score does not move monotonically against
  PD, the score band table and the PD table tell different stories about
  the same customers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from backend.scorecard import binning as binning_mod
from backend.scorecard import variables as vars_mod

EQUATION_VERSION = "1.0.0"

#: §13's score directions. No default: the registry has to say.
HIGHER_SCORE_IS_BETTER = "HIGHER_SCORE_IS_BETTER"
LOWER_SCORE_IS_BETTER = "LOWER_SCORE_IS_BETTER"
SCORE_DIRECTIONS: tuple[str, ...] = (HIGHER_SCORE_IS_BETTER,
                                     LOWER_SCORE_IS_BETTER)

#: The only link this IR supports. Named rather than assumed so that a
#: future probit is a new value here and not a silent reinterpretation of
#: the coefficients already stored.
LOGIT = "LOGIT"
LINKS: tuple[str, ...] = (LOGIT,)

#: §11: an active scorecard normally uses five or six variables. Enforced as
#: a warning band rather than a hard limit — a seven-variable model is a
#: design choice, and refusing it would be this module overruling the
#: institution's model committee.
TYPICAL_MIN_VARIABLES = 5
TYPICAL_MAX_VARIABLES = 6

#: PD is a probability. Anything outside this after the link is arithmetic
#: gone wrong, not a very confident model.
PD_FLOOR = 0.0
PD_CEILING = 1.0


class EquationError(Exception):
    """An equation that may not be built, validated or run."""


@dataclass
class Term:
    """One variable and its coefficient."""

    variable: str
    coefficient: float
    #: WOE is the only transformation a scorecard term takes here. RAW is
    #: allowed and warned about: a raw term in a WoE scorecard is almost
    #: always somebody wiring the wrong column.
    transformation: str = "WOE"

    def column(self) -> str:
        return (vars_mod.woe_name(self.variable)
                if self.transformation == "WOE" else self.variable)

    def to_dict(self) -> dict[str, Any]:
        return {"variable": self.variable,
                "coefficient": round(self.coefficient, 8),
                "transformation": self.transformation,
                "column": self.column()}


@dataclass
class ScoreMapping:
    """§13's points-to-double-the-odds mapping."""

    base_score: float
    pdo: float
    base_odds: float
    score_direction: str
    min_score: float = 0.0
    max_score: float = 1000.0

    @property
    def factor(self) -> float:
        return self.pdo / math.log(2.0)

    @property
    def offset(self) -> float:
        return self.base_score - self.factor * math.log(self.base_odds)

    def score(self, logit_bad: float) -> float:
        """§13's mapping, respecting the registry's declared direction."""
        raw = self.offset - self.factor * logit_bad
        if self.score_direction == LOWER_SCORE_IS_BETTER:
            # Reflect about the mid-point so a higher score means more risk.
            raw = (self.min_score + self.max_score) - raw
        return min(max(raw, self.min_score), self.max_score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_score": self.base_score, "pdo": self.pdo,
            "base_odds": self.base_odds,
            "score_direction": self.score_direction,
            "factor": round(self.factor, 6),
            "offset": round(self.offset, 6),
            "min_score": self.min_score, "max_score": self.max_score,
            "formula": ("Factor = PDO / ln(2); "
                        "Offset = BaseScore - Factor * ln(BaseOdds); "
                        "Score = Offset - Factor * logit_bad"),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ScoreMapping:
        direction = str(payload.get("score_direction") or "")
        if direction not in SCORE_DIRECTIONS:
            raise EquationError(
                "score_direction is required and has no default. Some "
                "institutions map a higher score to lower risk and some do "
                "the opposite; both are correct and they invert every "
                "discrimination statistic.")
        return cls(
            base_score=float(payload["base_score"]),
            pdo=float(payload["pdo"]),
            base_odds=float(payload["base_odds"]),
            score_direction=direction,
            min_score=float(payload.get("min_score", 0.0)),
            max_score=float(payload.get("max_score", 1000.0)))


@dataclass
class Equation:
    """§16's ScorecardEquation IR. The whole language, and nothing else."""

    model_name: str
    scorecard_type: str
    intercept: float
    terms: list[Term] = field(default_factory=list)
    link: str = LOGIT
    binning_spec_version: str = ""
    score_mapping: ScoreMapping | None = None
    output_prefix: str = ""

    @property
    def active_variables(self) -> list[str]:
        return [t.variable for t in self.terms]

    def logit(self, row: dict[str, Any]) -> float:
        """The equation, evaluated. Arithmetic only — nothing is parsed."""
        total = self.intercept
        for term in self.terms:
            value = row.get(term.column())
            if value is None or (isinstance(value, float)
                                 and math.isnan(value)):
                raise EquationError(
                    f"{term.column()} is absent for this row. A score "
                    "computed with a term silently treated as zero is a "
                    "different model from the one that was approved.")
            total += term.coefficient * float(value)
        return total

    @staticmethod
    def pd_from_logit(logit_bad: float) -> float:
        # Written in the numerically stable form: exp(710) overflows, and a
        # logit that extreme is reachable from a wide WoE on a small bin.
        if logit_bad >= 0:
            return 1.0 / (1.0 + math.exp(-logit_bad))
        exponent = math.exp(logit_bad)
        return exponent / (1.0 + exponent)

    def score(self, logit_bad: float) -> float:
        if self.score_mapping is None:
            raise EquationError(
                f"{self.model_name} has no score mapping, so it produces a "
                "PD and not a score. Asking it for one would invent a scale.")
        return self.score_mapping.score(logit_bad)

    def reads_as(self) -> str:
        """§34: the equation as a person would write it."""
        parts = [f"{self.intercept:+.6f}"]
        parts += [f"{t.coefficient:+.6f} * {t.column()}" for t in self.terms]
        lines = [f"logit_bad = {' '.join(parts)}",
                 "predicted_pd = 1 / (1 + exp(-logit_bad))"]
        if self.score_mapping is not None:
            lines.append(self.score_mapping.to_dict()["formula"])
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "equation_version": EQUATION_VERSION,
            "model_name": self.model_name,
            "scorecard_type": self.scorecard_type,
            "intercept": round(self.intercept, 8),
            "link": self.link,
            "terms": [t.to_dict() for t in self.terms],
            "active_variables": self.active_variables,
            "binning_spec_version": self.binning_spec_version,
            "score_mapping": (self.score_mapping.to_dict()
                              if self.score_mapping else None),
            "output_prefix": self.output_prefix,
            "reads_as": self.reads_as(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Equation:
        mapping = payload.get("score_mapping")
        return cls(
            model_name=str(payload["model_name"]),
            scorecard_type=str(payload["scorecard_type"]),
            intercept=float(payload["intercept"]),
            terms=[Term(variable=str(t["variable"]),
                        coefficient=float(t["coefficient"]),
                        transformation=str(t.get("transformation", "WOE")))
                   for t in payload.get("terms", [])],
            link=str(payload.get("link", LOGIT)),
            binning_spec_version=str(payload.get("binning_spec_version", "")),
            score_mapping=(ScoreMapping.from_dict(mapping)
                           if mapping else None),
            output_prefix=str(payload.get("output_prefix", "")))


# -------------------------------------------------------------- validation

BLOCKING = "BLOCKING"
WARNING = "WARNING"


@dataclass
class Problem:
    check: str
    severity: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.check, "severity": self.severity,
                "detail": self.detail}


@dataclass
class Validation:
    problems: list[Problem] = field(default_factory=list)

    @property
    def blockers(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == BLOCKING]

    @property
    def valid(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "blocking": [p.to_dict() for p in self.blockers],
            "warnings": [p.to_dict() for p in self.problems
                         if p.severity == WARNING],
            "checks_run": len(CHECKS),
            "checks": list(CHECKS),
        }


#: §16's checks, named so a report can say which one caught something.
CHECKS: tuple[str, ...] = (
    "variable_exists", "variable_is_scoreable", "woe_mapping_exists",
    "coefficients_numeric", "supported_link", "no_duplicate_variable",
    "variable_count_typical", "transformation_supported",
    "score_direction_declared", "score_mapping_sane",
    "coefficient_sign_matches_credit_sense", "score_pd_monotonic",
)


def validate(equation: Equation, *,
             spec: binning_mod.Spec | None = None) -> Validation:
    """§16's checks. Blocking ones refuse; warnings travel with the model."""
    found = Validation()

    def problem(check: str, severity: str, detail: str) -> None:
        found.problems.append(Problem(check, severity, detail))

    if equation.link not in LINKS:
        problem("supported_link", BLOCKING,
                f"{equation.link!r} is not a supported link function")

    if not equation.terms:
        problem("variable_count_typical", BLOCKING,
                "an equation with no terms is an intercept, not a scorecard")

    seen: set[str] = set()
    for term in equation.terms:
        if term.variable in seen:
            problem("no_duplicate_variable", BLOCKING,
                    f"{term.variable} appears twice; its coefficient would "
                    "be applied twice")
        seen.add(term.variable)

        try:
            variable = vars_mod.get(equation.scorecard_type, term.variable)
        except vars_mod.VariableError as exc:
            problem("variable_exists", BLOCKING, str(exc))
            continue

        if not variable.scoreable:
            problem("variable_is_scoreable", BLOCKING,
                    f"{term.variable} is a sensitive demographic field kept "
                    "for fairness monitoring. It may be profiled and may not "
                    "be scored.")

        if term.transformation not in ("WOE", "RAW"):
            problem("transformation_supported", BLOCKING,
                    f"{term.transformation!r} is not a supported "
                    "transformation")
        elif term.transformation == "RAW":
            problem("transformation_supported", WARNING,
                    f"{term.variable} enters raw in a weight-of-evidence "
                    "scorecard. That is almost always the wrong column.")

        if not isinstance(term.coefficient, (int, float)) or \
                math.isnan(term.coefficient) or math.isinf(term.coefficient):
            problem("coefficients_numeric", BLOCKING,
                    f"{term.variable} has a non-numeric coefficient")
            continue

        # The sign check does not need a binning specification. WoE is
        # constructed so a higher value is the lower-risk bin, so the
        # expected sign follows from the convention alone — and a model
        # reading a factor backwards is worth catching before anybody has
        # gone looking for the spec it was fitted against.
        if term.transformation == "WOE":
            _check_sign(term, variable, problem)

        if spec is not None:
            if term.variable not in spec.variables:
                problem("woe_mapping_exists", BLOCKING,
                        f"no approved WoE mapping exists for {term.variable} "
                        f"in binning spec {spec.spec_version}")
            elif term.transformation == "WOE":
                _check_monotonic(term, spec, problem)

    count = len(equation.terms)
    if count and not (TYPICAL_MIN_VARIABLES <= count <= TYPICAL_MAX_VARIABLES):
        problem("variable_count_typical", WARNING,
                f"{count} active variables. A retail scorecard normally uses "
                f"{TYPICAL_MIN_VARIABLES} to {TYPICAL_MAX_VARIABLES}; this is "
                "reported, not refused — the number of variables is the model "
                "committee's decision, not this validator's.")

    if equation.score_mapping is not None:
        _check_mapping(equation, problem)
    else:
        problem("score_direction_declared", WARNING,
                "no score mapping: this model produces a PD and no score")

    return found


def _check_sign(term: Term, variable: vars_mod.Variable,
                problem: Any) -> None:
    """§16 and §52's 8.5: does the coefficient agree with credit sense?

    WoE is built so that a *higher* WoE means a *better* (lower-risk) bin.
    A model of log-odds-of-bad should therefore carry a negative coefficient
    on every WoE term. A positive one means the fitted model reads that
    factor backwards.
    """
    if term.coefficient > 0:
        problem("coefficient_sign_matches_credit_sense", WARNING,
                f"{term.variable} has a positive coefficient on its weight of "
                "evidence. WoE is constructed so a higher value is the "
                "lower-risk bin, so a model of log-odds-of-bad should carry a "
                "negative coefficient. This reads the factor backwards: "
                f"credit sense says {variable.risk_direction.lower().replace('_', ' ')}.")


def _check_monotonic(term: Term, spec: binning_mod.Spec,
                     problem: Any) -> None:
    """Whether the approved binning's WoE moves in one direction.

    Needs the spec, which is why it is separate from the sign check.
    """
    binning = spec.variables.get(term.variable)
    if binning is not None and not binning.monotonic:
        problem("coefficient_sign_matches_credit_sense", WARNING,
                f"{term.variable} has a non-monotonic weight of evidence. "
                "That is sometimes right — very low and very high utilisation "
                "can both be risky — and worth an explicit economic "
                "justification in the model design section.")


def _check_mapping(equation: Equation, problem: Any) -> None:
    mapping = equation.score_mapping
    assert mapping is not None
    if mapping.score_direction not in SCORE_DIRECTIONS:
        problem("score_direction_declared", BLOCKING,
                "score_direction must be declared; there is no safe default")
    if mapping.pdo <= 0:
        problem("score_mapping_sane", BLOCKING,
                "points to double the odds must be positive")
    if mapping.base_odds <= 0:
        problem("score_mapping_sane", BLOCKING, "base odds must be positive")
    if mapping.min_score >= mapping.max_score:
        problem("score_mapping_sane", BLOCKING,
                "the score range is empty or inverted")

    # §16's monotonicity check, done by evaluation rather than by argument.
    probes = [-6.0, -3.0, -1.0, 0.0, 1.0, 3.0, 6.0]
    pairs = [(Equation.pd_from_logit(x), mapping.score(x)) for x in probes]
    scores = [s for _, s in pairs]
    rising = all(b >= a for a, b in zip(scores, scores[1:], strict=False))
    falling = all(b <= a for a, b in zip(scores, scores[1:], strict=False))
    if not (rising or falling):
        problem("score_pd_monotonic", BLOCKING,
                "score does not move monotonically against PD, so the score "
                "band table and the PD table would tell different stories "
                "about the same customers")
    elif rising and mapping.score_direction == HIGHER_SCORE_IS_BETTER:
        problem("score_pd_monotonic", BLOCKING,
                "score rises with PD while the registry declares that a "
                "higher score is better. One of the two is wrong, and every "
                "discrimination statistic inverts on which.")
    elif falling and mapping.score_direction == LOWER_SCORE_IS_BETTER:
        problem("score_pd_monotonic", BLOCKING,
                "score falls with PD while the registry declares that a "
                "lower score is better")


# --------------------------------------------------------------- the diff


def diff(current: Equation, candidate: Equation) -> dict[str, Any]:
    """§16/§35: what changed, before anybody approves it."""
    theirs = {t.variable: t.coefficient for t in candidate.terms}
    ours = {t.variable: t.coefficient for t in current.terms}
    added = sorted(set(theirs) - set(ours))
    removed = sorted(set(ours) - set(theirs))
    changed = {
        name: {"from": round(ours[name], 8), "to": round(theirs[name], 8),
               "delta": round(theirs[name] - ours[name], 8)}
        for name in sorted(set(ours) & set(theirs))
        if abs(ours[name] - theirs[name]) > 1e-12
    }
    return {
        "from_model": current.model_name,
        "to_model": candidate.model_name,
        "variables_added": added,
        "variables_removed": removed,
        "coefficients_changed": changed,
        "intercept": {
            "from": round(current.intercept, 8),
            "to": round(candidate.intercept, 8),
            "delta": round(candidate.intercept - current.intercept, 8),
        },
        "score_direction_changed": (
            (current.score_mapping.score_direction if current.score_mapping
             else None)
            != (candidate.score_mapping.score_direction
                if candidate.score_mapping else None)),
        "material": bool(added or removed or changed),
        "status": (
            "This is a CANDIDATE. §35: a natural-language model edit creates "
            "a candidate version and never overwrites the active model."),
    }

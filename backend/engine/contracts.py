"""
Analytical contracts — the declared specification of an engine function.

Why a function signature is not enough
--------------------------------------
`def stage_migration(period, compare_period, group_by="sector"): ...` tells Python
how to call it. It does not say what the function is for, which governed datasets
and fields it reads, what the parameters mean, what units the outputs carry, who
owns it, which version this is, or whether the bank has validated it.

Engine Builder needs every one of those. So a function declares them, and the
declaration is data — inspectable, versionable, and displayable in the UI.

This declaration is also the wall the LLM cannot climb. The planner may only name
registered functions and may only supply parameters that satisfy these contracts;
anything else is rejected before a single number is computed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# --------------------------------------------------------------------------
# Certification — a control, not decoration.
#
# The blue verification tick shown in the UI is driven by exactly this value. It
# tells a reader whether the number in front of them came from something the bank
# has validated, or from something a colleague built last week.
# --------------------------------------------------------------------------


class Certification(StrEnum):
    CERTIFIED = "certified"  # CreditProbe Certified — validated, tested, blue tick
    USER_DEFINED = "user_defined"  # built by a user, not yet certified, no tick
    DRAFT = "draft"  # under construction, not runnable in production
    DEPRECATED = "deprecated"  # superseded; may not be selected by the planner


class Category(StrEnum):
    MONITOR = "monitor"
    DETECT = "detect"
    INVESTIGATE = "investigate"
    STRESS = "stress"
    REFERENCE = "reference"


class ParamType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    PERIOD = "period"  # a reporting period label, e.g. "Q1 2026"
    FIELD = "field"  # the name of a governed field
    ENUM = "enum"  # one of `allowed_values`
    LIST = "list"  # a list of strings


class PeriodRequirement(StrEnum):
    """How much history an analysis needs before it can answer anything.

    This is the single most important piece of metadata for Ask CreditProbe. "What is
    our NPL ratio?" needs one period and must not interrogate the user about
    history; "which sectors deteriorated?" is meaningless without two, and
    silently picking a comparison would answer a question nobody asked.

    The orchestrator reads this to decide whether to run or to ask.
    """

    POINT_IN_TIME = "point_in_time"          # one reporting period
    TWO_PERIOD = "two_period"                # a comparison between two
    TIME_SERIES = "time_series"              # every period, or a window of them
    USER_DEFINED_WINDOW = "user_defined_window"  # the user chooses the span


class AnswerShape(StrEnum):
    """What kind of answer the analysis produces.

    Used to choose the one primary visual for a focused response, rather than
    rendering every chart an analysis is capable of.
    """

    LEVEL = "level"              # where something stands now
    MOVEMENT = "movement"        # how much it changed, and where
    RANKING = "ranking"          # which groups are worst / largest
    DISTRIBUTION = "distribution"  # how a total splits across groups
    MATRIX = "matrix"            # from-to transitions
    TREND = "trend"              # a path over time
    SCENARIO = "scenario"        # what a shock would do
    LIST = "list"                # named rows requiring attention


class VisualizationType(StrEnum):
    TABLE = "table"
    BAR = "bar"
    STACKED_BAR = "stacked_bar"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    HEATMAP = "heatmap"
    MATRIX = "matrix"
    WATERFALL = "waterfall"
    KPI = "kpi"
    TREEMAP = "treemap"


class ContractError(ValueError):
    """A parameter or output violates its declared contract. The message is written
    to be shown to a user, because rejected plans surface in the AI Cockpit."""


@dataclass(frozen=True)
class Parameter:
    """One input a function accepts."""

    name: str
    type: ParamType
    description: str
    required: bool = False
    default: Any = None
    allowed_values: list[Any] | None = None
    minimum: float | None = None
    maximum: float | None = None

    def validate(self, value: Any) -> Any:
        """Check one supplied value, returning the coerced value.

        Raises ContractError with a message a non-developer can understand,
        because these messages are what the AI Cockpit shows when a plan is
        rejected.
        """
        if value is None:
            if self.required:
                raise ContractError(f"Parameter '{self.name}' is required but was not supplied.")
            return self.default

        if self.type in (ParamType.STRING, ParamType.PERIOD, ParamType.FIELD, ParamType.ENUM):
            if not isinstance(value, str):
                raise ContractError(f"Parameter '{self.name}' must be text, got {type(value).__name__}.")
        elif self.type == ParamType.INTEGER:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ContractError(f"Parameter '{self.name}' must be a whole number, got {value!r}.")
        elif self.type == ParamType.NUMBER:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ContractError(f"Parameter '{self.name}' must be a number, got {value!r}.")
            value = float(value)
        elif self.type == ParamType.BOOLEAN:
            if not isinstance(value, bool):
                raise ContractError(f"Parameter '{self.name}' must be true or false, got {value!r}.")
        elif self.type == ParamType.LIST:
            if not isinstance(value, list):
                raise ContractError(f"Parameter '{self.name}' must be a list, got {type(value).__name__}.")

        if self.allowed_values is not None and value not in self.allowed_values:
            allowed = ", ".join(str(v) for v in self.allowed_values)
            raise ContractError(
                f"Parameter '{self.name}' must be one of: {allowed}. Got {value!r}."
            )
        if self.minimum is not None and isinstance(value, (int, float)) and value < self.minimum:
            raise ContractError(f"Parameter '{self.name}' must be at least {self.minimum}. Got {value}.")
        if self.maximum is not None and isinstance(value, (int, float)) and value > self.maximum:
            raise ContractError(f"Parameter '{self.name}' must be at most {self.maximum}. Got {value}.")
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.value,
            "description": self.description,
            "required": self.required,
            "default": self.default,
            "allowed_values": self.allowed_values,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass(frozen=True)
class OutputField:
    """One column of the structured result, with the unit it carries.

    Units live in the contract rather than in the number so that the UI can format
    consistently and the narrative layer can quote figures without guessing whether
    something is a percentage or a ratio.
    """

    name: str
    description: str
    data_type: str  # string | number | integer | boolean | date
    unit: str | None = None
    precision: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "data_type": self.data_type,
            "unit": self.unit,
            "precision": self.precision,
        }


@dataclass(frozen=True)
class ValidationRule:
    """A post-condition the result must satisfy.

    These are the checks that catch a wrong answer that still looks plausible —
    a transition matrix whose rows do not sum to one, a stage split that does not
    reconcile to total exposure. They run on every execution, not only in tests.
    """

    name: str
    description: str
    severity: str = "error"  # error | warning

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "severity": self.severity}


@dataclass(frozen=True)
class AnalysisContract:
    """The complete declared specification of one analytical capability.

    This is what Engine Builder displays, what the planner selects from, and what
    the validator enforces.
    """

    id: str
    name: str
    description: str
    category: Category
    version: str
    owner: str
    certification: Certification

    required_datasets: list[str]
    required_fields: list[str]
    parameters: list[Parameter] = field(default_factory=list)
    outputs: list[OutputField] = field(default_factory=list)
    validation_rules: list[ValidationRule] = field(default_factory=list)
    supported_visualizations: list[VisualizationType] = field(default_factory=list)

    # Methodology in language a risk officer can review and challenge. This is the
    # text that appears in Explain and in the Trace node for the function.
    calculation_description: str = ""

    # ---- semantics: what this analysis is FOR -------------------------------
    # Data Builder teaches CreditProbe what data means. This half teaches it what an
    # analysis does and when to reach for it, which is what lets Ask CreditProbe answer
    # the question actually asked instead of running everything it owns.

    # How much history the analysis needs. Drives period clarification.
    period_requirement: PeriodRequirement = PeriodRequirement.POINT_IN_TIME

    # Whether CreditProbe may assume a period without asking. True only where the
    # contract's own default is a governed, defensible choice (for example
    # "the latest published period" for a point-in-time level).
    governed_default_period: bool = True

    # The shape of the answer, used to pick one primary visual.
    answer_shape: AnswerShape = AnswerShape.LEVEL

    # One sentence a risk officer would recognise: when should CreditProbe reach for
    # this rather than something adjacent?
    when_to_use: str = ""

    # Questions this analysis is the right answer to. The planner matches
    # against these; Engine Builder displays them.
    trigger_questions: list[str] = field(default_factory=list)

    # What this analysis cannot tell you. Shown wherever its results are, so a
    # reader is not left to infer the boundary.
    limitations: str = ""

    # The governed PURPOSES this analysis draws on — "credit_facility_position",
    # not a table name and not a file. The purpose is resolved to whichever
    # dataset is authoritative for it at execution time, which is what lets a
    # bank's own data replace CreditProbe's demonstration book without touching a line
    # of analysis code. See backend/data_access/authority.py.
    #
    # It is also the dependency Data Builder reads: archiving the only dataset
    # authoritative for a purpose named here is refused, because the analyses
    # listing it would stop being answerable.
    required_domains: list[str] = field(default_factory=list)

    @property
    def requires_compare_period(self) -> bool:
        """Whether a comparison period is part of the question.

        Derived rather than declared, so it can never disagree with
        `period_requirement`. Kept as a property because the API and the
        Engine Builder screen have always exposed it.
        """
        return self.period_requirement in (
            PeriodRequirement.TWO_PERIOD,
            PeriodRequirement.USER_DEFINED_WINDOW,
        )

    @property
    def needs_period_clarification(self) -> bool:
        """Whether CreditProbe must ask the user for a period before running.

        True when the analysis spans time AND its contract does not carry a
        governed default. A point-in-time level never asks.
        """
        return (
            self.period_requirement is not PeriodRequirement.POINT_IN_TIME
            and not self.governed_default_period
        )

    @property
    def is_certified(self) -> bool:
        return self.certification is Certification.CERTIFIED

    @property
    def is_runnable(self) -> bool:
        """Draft and deprecated capabilities may be browsed in Engine Builder but
        may not be selected by the planner or executed."""
        return self.certification in (Certification.CERTIFIED, Certification.USER_DEFINED)

    def parameter(self, name: str) -> Parameter:
        for p in self.parameters:
            if p.name == name:
                return p
        raise ContractError(
            f"'{name}' is not a parameter of analysis '{self.id}'. "
            f"Accepted: {', '.join(p.name for p in self.parameters) or '(none)'}"
        )

    def validate_params(self, supplied: dict[str, Any] | None) -> dict[str, Any]:
        """Validate a full parameter set, returning the resolved values with
        defaults filled in.

        Unknown parameter names are an error rather than being ignored. If the
        planner asks for something the function does not support, silently dropping
        it would produce a confident answer to a different question.
        """
        supplied = dict(supplied or {})
        unknown = set(supplied) - {p.name for p in self.parameters}
        if unknown:
            accepted = ", ".join(p.name for p in self.parameters) or "(none)"
            raise ContractError(
                f"Analysis '{self.id}' does not accept: {', '.join(sorted(unknown))}. "
                f"Accepted parameters: {accepted}."
            )
        return {p.name: p.validate(supplied.get(p.name)) for p in self.parameters}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "version": self.version,
            "owner": self.owner,
            "certification": self.certification.value,
            "is_certified": self.is_certified,
            "is_runnable": self.is_runnable,
            "required_datasets": self.required_datasets,
            "required_fields": self.required_fields,
            "parameters": [p.to_dict() for p in self.parameters],
            "outputs": [o.to_dict() for o in self.outputs],
            "validation_rules": [r.to_dict() for r in self.validation_rules],
            "supported_visualizations": [v.value for v in self.supported_visualizations],
            "calculation_description": self.calculation_description,
            "requires_compare_period": self.requires_compare_period,
            "period_requirement": self.period_requirement.value,
            "governed_default_period": self.governed_default_period,
            "needs_period_clarification": self.needs_period_clarification,
            "answer_shape": self.answer_shape.value,
            "when_to_use": self.when_to_use,
            "trigger_questions": list(self.trigger_questions),
            "limitations": self.limitations,
            "required_domains": list(self.required_domains),
        }

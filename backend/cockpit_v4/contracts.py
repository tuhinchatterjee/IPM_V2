"""
The typed contracts: intent, the four tools, the answer, events and errors.

The rule this module exists to enforce
--------------------------------------
Validation may REJECT. It may never REPAIR. Every function here that finds a
problem returns a `Rejection` naming the exact field and why, and that
rejection goes back to the analyst as a tool_result so IT can revise. Nothing
here rewrites a query, drops a step, trims a subquestion, coerces a scalar
into a list "helpfully", or substitutes a field name that looked close. Those
are the failures V3 shipped, and each of them changes the substance of an
analysis while every test still passes.

The one thing that is NOT authorship: deterministic formatting of a value
that is already bound to executed evidence. Rounding 1234.5 to "1,234.50" at
the declared precision is presentation. Changing which column it came from is
not, and this module cannot do it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.cockpit_v4 import TOOL_CONTRACT_VERSION

CONTRACTS_DIR = Path(__file__).resolve().parent / "contracts"

# ---- modes, owners, dispositions --------------------------------------

PRODUCT_HELP = "PRODUCT_HELP"
THEORY_CONCEPT = "THEORY_CONCEPT"
DATA_ANALYSIS = "DATA_ANALYSIS"
OTHER_FUNCTIONALITY = "OTHER_FUNCTIONALITY"
CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
UNSUPPORTED = "UNSUPPORTED"

QUERY_MODES: tuple[str, ...] = (
    PRODUCT_HELP, THEORY_CONCEPT, DATA_ANALYSIS, OTHER_FUNCTIONALITY,
    CLARIFICATION_REQUIRED, UNSUPPORTED)

#: The modes that answer from knowledge and never touch the portfolio.
NO_EXECUTION_MODES: frozenset[str] = frozenset(
    {PRODUCT_HELP, THEORY_CONCEPT, OTHER_FUNCTIONALITY,
     CLARIFICATION_REQUIRED, UNSUPPORTED})

COCKPIT = "COCKPIT"
OWNERS: tuple[str, ...] = (
    COCKPIT, "EWS", "CREDIT_SCORING", "SCORECARD_VALIDATION", "WHAT_IF",
    "LENSES", "GENERAL_CREDITPROBE_HELP", "NONE")

DISPOSITIONS: tuple[str, ...] = (
    "answer", "partial_answer", "referral", "clarification",
    "unsupported", "safe_failure")

TOOL_INSPECT = "inspect_catalog"
TOOL_PRODUCT = "inspect_product_knowledge"
TOOL_EXECUTE = "execute_analysis"
TOOL_READ = "read_artifact"
TOOL_FINALIZE = "finalize_response"
TOOL_NAMES: tuple[str, ...] = (
    TOOL_INSPECT, TOOL_PRODUCT, TOOL_EXECUTE, TOOL_READ, TOOL_FINALIZE)

#: The reads the analyst may batch in one response. Anything that executes or
#: finalizes is one action per response, because a batch that mixes them has
#: no defined order and no safe partial outcome.
BATCHABLE: frozenset[str] = frozenset(
    {TOOL_INSPECT, TOOL_PRODUCT, TOOL_READ})
MAX_BATCHED_READS = 4


class Rejection(Exception):
    """A contract violation, stated as a fact the analyst can act on.

    Carries the field path so the tool_result says WHICH part was wrong. A
    rejection that says only "invalid arguments" costs a whole generation
    attempt to discover what this one already knows.
    """

    def __init__(self, code: str, message: str, *, field_path: str = "",
                 detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field_path = field_path
        self.detail = dict(detail or {})

    def to_tool_result(self) -> dict[str, Any]:
        return {"status": "rejected", "error_code": self.code,
                "field": self.field_path, "message": self.message,
                **({"detail": self.detail} if self.detail else {})}


# ---- intent ------------------------------------------------------------

@dataclass(frozen=True)
class Intent:
    """What the analyst says this turn is, declared with its first action."""

    query_mode: str
    owner: str
    understood_request: str
    response_language: str
    #: Terms with two defensible readings that would produce materially
    #: different numbers. THE ONLY THING THAT STOPS EXECUTION.
    blocking_ambiguities: tuple[str, ...]
    #: Choices the analyst made and is declaring. Transparency, not a
    #: question: "period not specified, using the latest populated quarter".
    resolved_assumptions: tuple[str, ...]
    #: Terms this domain already defines: "exposure at default = EAD =
    #: ead_reported". Not even a choice.
    canonical_mappings: tuple[str, ...]
    excluded_parts: tuple[str, ...]
    public_rationale: str

    @property
    def may_execute(self) -> bool:
        """Execution is allowed for a declared Cockpit data analysis with no
        BLOCKING ambiguity.

        The distinction is the point. A live run recorded "Exposure read as
        reported EAD (ead_reported)" and "Period not specified: using the
        latest populated quarter" as ambiguities -- both correct resolutions,
        written down for the reader -- and a single `ambiguities` list turned
        each of them into a refusal. Declaring a resolution now costs
        nothing; only an unresolved question stops the analysis.

        A previous turn's owner authorizes nothing: this is recomputed from
        THIS turn's declaration.
        """
        return (self.query_mode == DATA_ANALYSIS
                and self.owner == COCKPIT
                and not self.blocking_ambiguities)

    def to_dict(self) -> dict[str, Any]:
        return {"query_mode": self.query_mode, "owner": self.owner,
                "understood_request": self.understood_request,
                "response_language": self.response_language,
                "blocking_ambiguities": list(self.blocking_ambiguities),
                "resolved_assumptions": list(self.resolved_assumptions),
                "canonical_mappings": list(self.canonical_mappings),
                "excluded_parts": list(self.excluded_parts),
                "public_rationale": self.public_rationale}


def _require_text(payload: Any, key: str, path: str, *,
                  allow_empty: bool = False) -> str:
    if not isinstance(payload, dict) or key not in payload:
        raise Rejection("INVALID_MODEL_OUTPUT",
                        f"{path}.{key} is required and was not supplied.",
                        field_path=f"{path}.{key}")
    value = payload[key]
    if not isinstance(value, str):
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            f"{path}.{key} must be a string, not {type(value).__name__}.",
            field_path=f"{path}.{key}")
    if not value.strip() and not allow_empty:
        raise Rejection("INVALID_MODEL_OUTPUT",
                        f"{path}.{key} must not be empty.",
                        field_path=f"{path}.{key}")
    return value


def _optional_text(payload: Any, key: str, path: str) -> str:
    """An optional string. `null` and a missing key both mean "none".

    The model-facing schema declares these as `["string", "null"]`, so `null`
    is a representation the analyst was TOLD it may send. A validator that
    then rejects it disagrees with the contract the model was given, and the
    cost of that disagreement is a whole extra generation: the first live
    product-help run answered correctly in 16.6 seconds, was refused because
    `clarification_question` was null, and had to be asked again — two
    generations and 29.4 seconds for a question that needed one.

    Normalizing here is REPRESENTATION only. It maps three spellings of
    absence onto one stored form. It never invents content, never rewrites
    meaning, and never rescues a field that carries substance.
    """
    if not isinstance(payload, dict):
        raise Rejection("INVALID_MODEL_OUTPUT",
                        f"{path} must be an object.", field_path=path)
    value = payload.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            f"{path}.{key} must be a string or null, not "
            f"{type(value).__name__}.", field_path=f"{path}.{key}")
    return value


def _optional_str_list(payload: Any, key: str, path: str) -> tuple[str, ...]:
    """An optional array of strings. `null` and a missing key mean empty.

    A bare string is still REJECTED rather than wrapped, for the same reason
    it always was: V3 expanded a scalar into a list of its own characters and
    turned a rating of "B" into ["B"]. Accepting absence is not the same as
    accepting a wrong shape.
    """
    if not isinstance(payload, dict):
        raise Rejection("INVALID_MODEL_OUTPUT",
                        f"{path} must be an object.", field_path=path)
    if payload.get(key) is None:
        return ()
    return _require_str_list(payload, key, path)


def _optional_object(payload: Any, key: str, path: str) -> dict[str, Any]:
    """An optional object. `null` and a missing key mean no entries."""
    value = payload.get(key) if isinstance(payload, dict) else None
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            f"{path}.{key} must be an object or null, not "
            f"{type(value).__name__}.", field_path=f"{path}.{key}")
    return dict(value)


def _optional_list(payload: Any, key: str, path: str) -> list[Any]:
    """An optional array of anything. `null` and a missing key mean empty."""
    value = payload.get(key) if isinstance(payload, dict) else None
    if value is None:
        return []
    if not isinstance(value, list):
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            f"{path}.{key} must be an array or null, not "
            f"{type(value).__name__}.", field_path=f"{path}.{key}")
    return list(value)


def _require_str_list(payload: Any, key: str, path: str) -> tuple[str, ...]:
    """A list of strings. A bare string is REJECTED, never expanded.

    V3 turned a scalar string into a list of its characters here. The fix is
    not a smarter coercion -- it is refusing to coerce at all and telling the
    analyst the field is a list, which costs one tool_result and cannot
    silently turn "BBB" into ["B", "B", "B"].
    """
    if not isinstance(payload, dict) or key not in payload:
        raise Rejection("INVALID_MODEL_OUTPUT",
                        f"{path}.{key} is required and was not supplied.",
                        field_path=f"{path}.{key}")
    value = payload[key]
    if isinstance(value, str):
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            f"{path}.{key} must be an array of strings. A single string is "
            f"not an array; send [\"...\"] if you meant one item.",
            field_path=f"{path}.{key}")
    if not isinstance(value, list):
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            f"{path}.{key} must be an array of strings, not "
            f"{type(value).__name__}.", field_path=f"{path}.{key}")
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise Rejection(
                "INVALID_MODEL_OUTPUT",
                f"{path}.{key}[{i}] must be a string, not "
                f"{type(item).__name__}.", field_path=f"{path}.{key}[{i}]")
        out.append(item)
    return tuple(out)


def parse_intent(payload: Any, *, path: str = "intent") -> Intent:
    if not isinstance(payload, dict):
        raise Rejection("INVALID_MODEL_OUTPUT",
                        f"{path} must be an object.", field_path=path)
    mode = _require_text(payload, "query_mode", path)
    if mode not in QUERY_MODES:
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            f"{path}.query_mode must be one of {', '.join(QUERY_MODES)}.",
            field_path=f"{path}.query_mode")
    owner = _require_text(payload, "owner", path)
    if owner not in OWNERS:
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            f"{path}.owner must be one of {', '.join(OWNERS)}.",
            field_path=f"{path}.owner")
    return Intent(
        query_mode=mode, owner=owner,
        understood_request=_require_text(payload, "understood_request", path),
        response_language=_require_text(payload, "response_language", path),
        # Absent and empty mean the same thing here: nothing blocking,
        # nothing assumed, nothing excluded. The schema says so, and so does
        # this.
        blocking_ambiguities=_optional_str_list(
            payload, "blocking_ambiguities", path),
        resolved_assumptions=_optional_str_list(
            payload, "resolved_assumptions", path),
        canonical_mappings=_optional_str_list(
            payload, "canonical_mappings", path),
        excluded_parts=_optional_str_list(payload, "excluded_parts", path),
        public_rationale=_require_text(payload, "public_rationale", path))


# ---- execute_analysis --------------------------------------------------

_STEP_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
MAX_CODE_BYTES = 64_000


@dataclass(frozen=True)
class Step:
    """One executable unit, exactly as the analyst wrote it."""

    step_id: str
    language: str
    #: Byte-for-byte the analyst's source. Never reformatted, never trimmed.
    code: str
    parameters: dict[str, Any]
    purpose: str
    input_artifact_ids: tuple[str, ...]
    depends_on_step_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"step_id": self.step_id, "language": self.language,
                "code": self.code, "parameters": dict(self.parameters),
                "purpose": self.purpose,
                "input_artifact_ids": list(self.input_artifact_ids),
                "depends_on_step_ids": list(self.depends_on_step_ids)}


@dataclass(frozen=True)
class ExecutionSubmission:
    intent: Intent
    objective: str
    subquestions: tuple[str, ...]
    scope: dict[str, Any]
    metadata_receipt_ids: tuple[str, ...]
    fields_required: tuple[str, ...]
    expected_output_grain: str
    #: Output column -> unit. The schema declares a mapping, because a result
    #: with an amount and a count does not have one unit. A bare string is
    #: accepted as the shorthand for "every output column is in this unit"
    #: and is stored under the empty key.
    expected_units: dict[str, str]
    steps: tuple[Step, ...]
    repair_of_submission_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"intent": self.intent.to_dict(), "objective": self.objective,
                "subquestions": list(self.subquestions),
                "scope": dict(self.scope),
                "metadata_receipt_ids": list(self.metadata_receipt_ids),
                "fields_required": list(self.fields_required),
                "expected_output_grain": self.expected_output_grain,
                "expected_units": dict(self.expected_units),
                "steps": [s.to_dict() for s in self.steps],
                "repair_of_submission_id": self.repair_of_submission_id}


def parse_steps(payload: Any, *, max_steps: int) -> tuple[Step, ...]:
    """Parse a batch. An overlong batch is REJECTED WHOLE, never clipped.

    Clipping is the failure mode that matters: a six-step analysis silently
    executed as four steps produces a number, and the number is wrong, and
    nothing in the trace says a step is missing.
    """
    if not isinstance(payload, list):
        raise Rejection("INVALID_MODEL_OUTPUT",
                        "steps must be an array.", field_path="steps")
    if not payload:
        raise Rejection("INVALID_MODEL_OUTPUT",
                        "steps must contain at least one step.",
                        field_path="steps")
    if len(payload) > max_steps:
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            f"This batch has {len(payload)} steps and the limit is "
            f"{max_steps}. The batch was not executed and no step was "
            f"dropped: resubmit within the limit, or split the work across "
            f"submissions, but do not shorten the analysis to fit.",
            field_path="steps",
            detail={"submitted": len(payload), "limit": max_steps})

    seen: set[str] = set()
    steps: list[Step] = []
    for i, raw in enumerate(payload):
        path = f"steps[{i}]"
        if not isinstance(raw, dict):
            raise Rejection("INVALID_MODEL_OUTPUT",
                            f"{path} must be an object.", field_path=path)
        step_id = _require_text(raw, "step_id", path)
        if not _STEP_ID.match(step_id):
            raise Rejection(
                "INVALID_MODEL_OUTPUT",
                f"{path}.step_id must match {_STEP_ID.pattern}.",
                field_path=f"{path}.step_id")
        if step_id in seen:
            raise Rejection("INVALID_MODEL_OUTPUT",
                            f"{path}.step_id {step_id!r} is repeated.",
                            field_path=f"{path}.step_id")
        seen.add(step_id)
        language = _require_text(raw, "language", path)
        if language not in ("sql", "python"):
            raise Rejection(
                "INVALID_MODEL_OUTPUT",
                f"{path}.language must be 'sql' or 'python'. A python step "
                f"is never executed as SQL, or the reverse.",
                field_path=f"{path}.language")
        code = _require_text(raw, "code", path)
        if len(code.encode("utf-8")) > MAX_CODE_BYTES:
            raise Rejection(
                "INVALID_MODEL_OUTPUT",
                f"{path}.code exceeds {MAX_CODE_BYTES} bytes and was not "
                f"truncated. Send shorter code; nothing was executed.",
                field_path=f"{path}.code")
        parameters = _optional_object(raw, "parameters", path)
        steps.append(Step(
            step_id=step_id, language=language, code=code,
            parameters=parameters,
            purpose=_require_text(raw, "purpose", path),
            input_artifact_ids=_optional_str_list(
                raw, "input_artifact_ids", path),
            depends_on_step_ids=_optional_str_list(
                raw, "depends_on_step_ids", path)))

    ids = {s.step_id for s in steps}
    order = {s.step_id: i for i, s in enumerate(steps)}
    for s in steps:
        for dep in s.depends_on_step_ids:
            if dep not in ids:
                raise Rejection(
                    "INVALID_MODEL_OUTPUT",
                    f"step {s.step_id!r} depends on {dep!r}, which is not in "
                    f"this batch.", field_path="steps")
            if order[dep] >= order[s.step_id]:
                raise Rejection(
                    "INVALID_MODEL_OUTPUT",
                    f"step {s.step_id!r} depends on {dep!r}, which is not "
                    f"earlier in the batch. Steps run in the order sent.",
                    field_path="steps")
    return tuple(steps)


def _parse_units(value: Any) -> dict[str, str]:
    """The declared units of the result.

    The published schema is `{"column": "unit"}`, because a result carrying an
    amount and a row count does not have a single unit. The validator used to
    demand a plain string, so a model that followed the schema it was given
    would have had EVERY analysis submission rejected — a submission slot and
    a generation burned each time, for agreeing with us.

    A bare string is still accepted as the shorthand for "all of it is in this
    unit"; that is representation, not meaning.
    """
    if value is None:
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            "expected_units is required: declare the unit of each output "
            "column, or one unit for all of them.",
            field_path="expected_units")
    if isinstance(value, str):
        if not value.strip():
            raise Rejection("INVALID_MODEL_OUTPUT",
                            "expected_units must not be empty.",
                            field_path="expected_units")
        return {"": value}
    if not isinstance(value, dict):
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            f"expected_units must be an object mapping a column to its unit, "
            f"or a single string; got {type(value).__name__}.",
            field_path="expected_units")
    if not value:
        raise Rejection("INVALID_MODEL_OUTPUT",
                        "expected_units must name at least one unit.",
                        field_path="expected_units")
    out: dict[str, str] = {}
    for column, unit in value.items():
        if not isinstance(unit, str) or not unit.strip():
            raise Rejection(
                "INVALID_MODEL_OUTPUT",
                f"expected_units[{column!r}] must be a non-empty string.",
                field_path=f"expected_units.{column}")
        out[str(column)] = unit
    return out


def units_display(units: dict[str, str]) -> str:
    """The units as one line, for the process trace."""
    if not units:
        return "unspecified"
    if len(units) == 1 and "" in units:
        return units[""]
    return ", ".join(f"{column}: {unit}" if column else unit
                     for column, unit in units.items())


def parse_execution(payload: Any, *, max_steps: int) -> ExecutionSubmission:
    if not isinstance(payload, dict):
        raise Rejection("INVALID_MODEL_OUTPUT",
                        "execute_analysis arguments must be an object.")
    intent = parse_intent(payload.get("intent"))
    scope = _optional_object(payload, "scope", "execute_analysis")
    return ExecutionSubmission(
        intent=intent,
        objective=_require_text(payload, "objective", "execute_analysis"),
        subquestions=_require_str_list(payload, "subquestions",
                                       "execute_analysis"),
        scope=scope,
        metadata_receipt_ids=_optional_str_list(
            payload, "metadata_receipt_ids", "execute_analysis"),
        fields_required=_optional_str_list(payload, "fields_required",
                                           "execute_analysis"),
        expected_output_grain=_require_text(
            payload, "expected_output_grain", "execute_analysis"),
        expected_units=_parse_units(payload.get("expected_units")),
        steps=parse_steps(payload.get("steps"), max_steps=max_steps),
        repair_of_submission_id=_optional_text(
            payload, "repair_of_submission_id", "execute_analysis"))


# ---- inspect_catalog / read_artifact -----------------------------------

CATALOG_DETAILS: tuple[str, ...] = (
    "discovery", "fields", "relationships", "coverage", "samples")
MAX_SAMPLE_ROWS = 10


@dataclass(frozen=True)
class CatalogRequest:
    intent: Intent
    query: str
    relation_ids: tuple[str, ...]
    field_ids: tuple[str, ...]
    detail: tuple[str, ...]
    reporting_quarters: tuple[str, ...]
    sample_rows: int
    cursor: str


def parse_catalog(payload: Any) -> CatalogRequest:
    if not isinstance(payload, dict):
        raise Rejection("INVALID_MODEL_OUTPUT",
                        "inspect_catalog arguments must be an object.")
    intent = parse_intent(payload.get("intent"))
    detail = _optional_str_list(payload, "detail", "inspect_catalog")
    for d in detail:
        if d not in CATALOG_DETAILS:
            raise Rejection(
                "INVALID_MODEL_OUTPUT",
                f"detail {d!r} is not one of {', '.join(CATALOG_DETAILS)}.",
                field_path="detail")
    rows = payload.get("sample_rows", 0)
    if rows is None:
        rows = 0
    if not isinstance(rows, int) or isinstance(rows, bool):
        raise Rejection("INVALID_MODEL_OUTPUT",
                        "sample_rows must be an integer.",
                        field_path="sample_rows")
    if rows < 0 or rows > MAX_SAMPLE_ROWS:
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            f"sample_rows must be between 0 and {MAX_SAMPLE_ROWS}.",
            field_path="sample_rows")
    if rows and "samples" not in detail:
        raise Rejection("INVALID_MODEL_OUTPUT",
                        "sample_rows requires 'samples' in detail.",
                        field_path="detail")
    if rows and intent.query_mode != DATA_ANALYSIS:
        raise Rejection(
            "SECURITY_DENIED",
            "Masked sample rows are available only for a data analysis. "
            "Product help reads coverage metadata, not borrower rows.",
            field_path="sample_rows")
    return CatalogRequest(
        intent=intent,
        query=_optional_text(payload, "query", "inspect_catalog"),
        relation_ids=_optional_str_list(payload, "relation_ids",
                                        "inspect_catalog"),
        field_ids=_optional_str_list(payload, "field_ids", "inspect_catalog"),
        detail=detail,
        reporting_quarters=_optional_str_list(payload, "reporting_quarters",
                                              "inspect_catalog"),
        sample_rows=rows,
        cursor=_optional_text(payload, "cursor", "inspect_catalog"))


@dataclass(frozen=True)
class ProductKnowledgeRequest:
    intent: Intent
    query: str
    topics: tuple[str, ...]
    detail: str


def parse_product_knowledge(payload: Any) -> ProductKnowledgeRequest:
    """Parse a product-knowledge request.

    Reading product facts is not analysis, so this is available in every mode
    -- a product-help question must be able to reach it without declaring a
    data analysis it is not going to run.
    """
    from backend.cockpit_v4.product_knowledge import TOPICS

    if not isinstance(payload, dict):
        raise Rejection("INVALID_MODEL_OUTPUT",
                        "inspect_product_knowledge arguments must be an "
                        "object.")
    intent = parse_intent(payload.get("intent"))
    topics = _optional_str_list(payload, "topics",
                               "inspect_product_knowledge")
    for topic in topics:
        if topic not in TOPICS:
            raise Rejection(
                "INVALID_MODEL_OUTPUT",
                f"topic {topic!r} is not one of {', '.join(TOPICS)}.",
                field_path="topics")
    detail = _optional_text(payload, "detail", "inspect_product_knowledge")
    if detail not in ("", "standard", "full"):
        raise Rejection("INVALID_MODEL_OUTPUT",
                        "detail must be 'standard' or 'full'.",
                        field_path="detail")
    return ProductKnowledgeRequest(
        intent=intent,
        query=_optional_text(payload, "query", "inspect_product_knowledge"),
        topics=topics, detail=detail or "standard")


@dataclass(frozen=True)
class ArtifactRequest:
    intent: Intent
    artifact_id: str
    artifact_kind: str
    columns: tuple[str, ...]
    offset: int
    limit: int
    cursor: str


ARTIFACT_KINDS: tuple[str, ...] = ("result", "thread_turn")


def parse_artifact(payload: Any) -> ArtifactRequest:
    if not isinstance(payload, dict):
        raise Rejection("INVALID_MODEL_OUTPUT",
                        "read_artifact arguments must be an object.")
    intent = parse_intent(payload.get("intent"))
    kind = _require_text(payload, "artifact_kind", "read_artifact")
    if kind not in ARTIFACT_KINDS:
        raise Rejection(
            "INVALID_MODEL_OUTPUT",
            f"artifact_kind must be one of {', '.join(ARTIFACT_KINDS)}.",
            field_path="artifact_kind")
    artifact_id = _require_text(payload, "artifact_id", "read_artifact")
    # Not a path and not a URL. The namespace is checked server-side too;
    # this is the cheap refusal that keeps an obvious traversal out of logs.
    if "/" in artifact_id or "\\" in artifact_id or ".." in artifact_id:
        raise Rejection(
            "SECURITY_DENIED",
            "artifact_id is an identifier, not a path or URL.",
            field_path="artifact_id")
    offset = payload.get("offset") or 0
    limit = payload.get("limit") or 0
    for name, value in (("offset", offset), ("limit", limit)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise Rejection("INVALID_MODEL_OUTPUT",
                            f"{name} must be a non-negative integer.",
                            field_path=name)
    return ArtifactRequest(
        intent=intent, artifact_id=artifact_id, artifact_kind=kind,
        columns=_optional_str_list(payload, "columns", "read_artifact"),
        offset=int(offset), limit=int(limit),
        cursor=_optional_text(payload, "cursor", "read_artifact"))


# ---- finalize_response -------------------------------------------------

_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")
COVERAGE_STATUSES: tuple[str, ...] = (
    "answered", "partial", "referred", "needs_clarification", "unsupported")


@dataclass(frozen=True)
class EvidenceRef:
    artifact_id: str
    row_key: str
    column_id: str
    scope_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = {"artifact_id": self.artifact_id, "row_key": self.row_key,
               "column_id": self.column_id}
        if self.scope_ref:
            out["scope_ref"] = self.scope_ref
        return out


@dataclass(frozen=True)
class NumericClaim:
    claim_id: str
    #: A lossless decimal STRING. Never a float: a float display is an
    #: approximation and this value is quoted to a credit officer.
    decimal_value: str
    unit: str
    evidence: EvidenceRef
    display_precision: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {"claim_id": self.claim_id, "decimal_value": self.decimal_value,
                "unit": self.unit, "evidence": self.evidence.to_dict(),
                "display_precision": self.display_precision}


@dataclass(frozen=True)
class CoverageItem:
    subquestion: str
    status: str
    evidence_refs: tuple[EvidenceRef, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"subquestion": self.subquestion, "status": self.status,
                "evidence_refs": [e.to_dict() for e in self.evidence_refs]}


@dataclass(frozen=True)
class FinalResponse:
    intent: Intent
    disposition: str
    narrative: str
    coverage: tuple[CoverageItem, ...]
    numeric_claims: tuple[NumericClaim, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    tables: tuple[dict[str, Any], ...]
    charts: tuple[dict[str, Any], ...]
    limitations: tuple[str, ...]
    suggested_questions: tuple[dict[str, Any], ...]
    clarification_question: str
    clarification_options: tuple[str, ...]
    referral_owner: str
    referral_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.to_dict(), "disposition": self.disposition,
            "narrative": self.narrative,
            "coverage": [c.to_dict() for c in self.coverage],
            "numeric_claims": [n.to_dict() for n in self.numeric_claims],
            "evidence_refs": [e.to_dict() for e in self.evidence_refs],
            "tables": [dict(t) for t in self.tables],
            "charts": [dict(c) for c in self.charts],
            "limitations": list(self.limitations),
            "suggested_questions": [dict(s) for s in self.suggested_questions],
            "clarification_question": self.clarification_question,
            "clarification_options": list(self.clarification_options),
            "referral_owner": self.referral_owner,
            "referral_reason": self.referral_reason}


def _parse_evidence(raw: Any, path: str) -> EvidenceRef:
    if not isinstance(raw, dict):
        raise Rejection("ANSWER_VALIDATION", f"{path} must be an object.",
                        field_path=path)
    return EvidenceRef(
        artifact_id=_require_text(raw, "artifact_id", path),
        row_key=_require_text(raw, "row_key", path, allow_empty=True),
        column_id=_require_text(raw, "column_id", path, allow_empty=True),
        scope_ref=str(raw.get("scope_ref") or ""))


def parse_final(payload: Any) -> FinalResponse:
    if not isinstance(payload, dict):
        raise Rejection("ANSWER_VALIDATION",
                        "finalize_response arguments must be an object.")
    intent = parse_intent(payload.get("intent"))
    disposition = _require_text(payload, "disposition", "finalize_response")
    if disposition not in DISPOSITIONS:
        raise Rejection(
            "ANSWER_VALIDATION",
            f"disposition must be one of {', '.join(DISPOSITIONS)}.",
            field_path="disposition")

    coverage_raw = _optional_list(payload, "coverage", "finalize_response")
    coverage: list[CoverageItem] = []
    for i, raw in enumerate(coverage_raw):
        path = f"coverage[{i}]"
        if not isinstance(raw, dict):
            raise Rejection("ANSWER_VALIDATION", f"{path} must be an object.",
                            field_path=path)
        status = _require_text(raw, "status", path)
        if status not in COVERAGE_STATUSES:
            raise Rejection(
                "ANSWER_VALIDATION",
                f"{path}.status must be one of "
                f"{', '.join(COVERAGE_STATUSES)}.",
                field_path=f"{path}.status")
        refs = _optional_list(raw, "evidence_refs", path)
        coverage.append(CoverageItem(
            subquestion=_require_text(raw, "subquestion", path),
            status=status,
            evidence_refs=tuple(
                _parse_evidence(r, f"{path}.evidence_refs[{j}]")
                for j, r in enumerate(refs))))

    claims_raw = _optional_list(payload, "numeric_claims",
                                "finalize_response")
    claims: list[NumericClaim] = []
    seen_claims: set[str] = set()
    for i, raw in enumerate(claims_raw):
        path = f"numeric_claims[{i}]"
        if not isinstance(raw, dict):
            raise Rejection("ANSWER_VALIDATION", f"{path} must be an object.",
                            field_path=path)
        claim_id = _require_text(raw, "claim_id", path)
        if claim_id in seen_claims:
            raise Rejection("ANSWER_VALIDATION",
                            f"{path}.claim_id {claim_id!r} is repeated.",
                            field_path=f"{path}.claim_id")
        seen_claims.add(claim_id)
        decimal_value = _require_text(raw, "decimal_value", path)
        if not _DECIMAL.match(decimal_value):
            raise Rejection(
                "ANSWER_VALIDATION",
                f"{path}.decimal_value must be a plain decimal string such "
                f"as \"1234.50\"; got {decimal_value!r}.",
                field_path=f"{path}.decimal_value")
        precision = raw.get("display_precision", 2)
        if (not isinstance(precision, int) or isinstance(precision, bool)
                or not 0 <= precision <= 12):
            raise Rejection("ANSWER_VALIDATION",
                            f"{path}.display_precision must be 0-12.",
                            field_path=f"{path}.display_precision")
        claims.append(NumericClaim(
            claim_id=claim_id, decimal_value=decimal_value,
            unit=_require_text(raw, "unit", path),
            evidence=_parse_evidence(raw.get("evidence"), f"{path}.evidence"),
            display_precision=int(precision)))

    refs_raw = _optional_list(payload, "evidence_refs", "finalize_response")
    tables_raw = _optional_list(payload, "tables", "finalize_response")
    charts_raw = _optional_list(payload, "charts", "finalize_response")
    suggestions_raw = _optional_list(payload, "suggested_questions",
                                     "finalize_response")

    final = FinalResponse(
        intent=intent, disposition=disposition,
        narrative=_require_text(payload, "narrative", "finalize_response"),
        coverage=tuple(coverage), numeric_claims=tuple(claims),
        evidence_refs=tuple(_parse_evidence(r, f"evidence_refs[{i}]")
                            for i, r in enumerate(refs_raw)),
        tables=tuple(dict(x) for x in tables_raw if isinstance(x, dict)),
        charts=tuple(dict(x) for x in charts_raw if isinstance(x, dict)),
        limitations=_optional_str_list(payload, "limitations",
                                       "finalize_response"),
        suggested_questions=tuple(
            dict(x) for x in suggestions_raw if isinstance(x, dict)),
        # Every one of these is optional in MEANING: no clarification, no
        # referral. `null`, `""` and a missing key are three spellings of the
        # same fact and are stored as one.
        clarification_question=_optional_text(
            payload, "clarification_question", "finalize_response"),
        clarification_options=_optional_str_list(
            payload, "clarification_options", "finalize_response"),
        referral_owner=_optional_text(payload, "referral_owner",
                                      "finalize_response"),
        referral_reason=_optional_text(payload, "referral_reason",
                                       "finalize_response"))

    if disposition == "clarification" and not final.clarification_question:
        raise Rejection(
            "ANSWER_VALIDATION",
            "A clarification must carry the question you want answered.",
            field_path="clarification_question")
    if disposition == "referral":
        if not final.referral_owner or final.referral_owner not in OWNERS:
            raise Rejection(
                "ANSWER_VALIDATION",
                f"A referral must name an owner from {', '.join(OWNERS)}.",
                field_path="referral_owner")
    return final


# ---- provider tool schemas --------------------------------------------

def _load(name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / name).read_text(encoding="utf-8"))


def _defs() -> dict[str, Any]:
    return _load("shared_defs.schema.json")["$defs"]


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    """Resolve `$ref` into the provider payload.

    The application schemas use `$defs` for readability. Provider tool
    schemas are a restricted dialect and `$ref` support is not something to
    assume, so the wire copy is flattened here and the application copy stays
    readable. Server-side validation does not depend on either.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            return _inline(defs[ref.split("/")[-1]], defs)
        return {k: _inline(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


_DESCRIPTIONS = {
    TOOL_INSPECT: ("Read exact catalog metadata for the authorized "
                   "corporate_cockpit release: relation names and grains, "
                   "field definitions, units, valid joins, coverage by "
                   "reporting quarter and missingness. Returns what is "
                   "there; an empty search is an empty search."),
    TOOL_EXECUTE: ("Submit your own exact SQL or Python. CreditProbe "
                   "validates and executes it unchanged, or rejects it with "
                   "the reason. It never edits, shortens or repairs your "
                   "code, and never computes a substitute answer."),
    TOOL_READ: ("Read an authorized persisted result artifact or completed "
                "thread turn. Exact stored values only; this computes "
                "nothing new."),
    TOOL_PRODUCT: ("Read CreditProbe's own product knowledge: what the "
                   "product is, what each of the seven functionalities does "
                   "and owns, TAC, the four Early Warning intelligence "
                   "layers, how modules relate, boundaries and worked "
                   "examples -- each with the deck slide it came from. Facts "
                   "only; the answer is yours to write."),
    TOOL_FINALIZE: ("Deliver the user-facing response: answer, partial "
                    "answer, referral, clarification or unsupported. This is "
                    "the terminal action and costs no extra model call."),
}


def provider_tools(*, withhold: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """The tool definitions, in the provider's wire shape.

    `withhold` removes a tool from THIS request only. It exists for exactly
    one thing: a broad product question whose answer is already covered by
    the synopsis in the starting context does not need
    `inspect_product_knowledge` offered on its first action, and offering it
    is what turned "Who are you?" into two generations. Nothing is withheld
    for more than one action — see `product_knowledge.coverage`.

    `finalize_response` can never be withheld: withholding it would leave a
    run with no way to terminate.
    """
    blocked = {name for name in withhold if name != TOOL_FINALIZE}
    if blocked - set(TOOL_NAMES):
        raise ValueError(f"unknown tool(s) in withhold: "
                         f"{sorted(blocked - set(TOOL_NAMES))}")
    defs = _defs()
    files = {TOOL_INSPECT: "inspect_catalog.schema.json",
             TOOL_PRODUCT: "inspect_product_knowledge.schema.json",
             TOOL_EXECUTE: "execute_analysis.schema.json",
             TOOL_READ: "read_artifact.schema.json",
             TOOL_FINALIZE: "finalize_response.schema.json"}
    tools = []
    for name in TOOL_NAMES:
        if name in blocked:
            continue
        tools.append({"name": name, "description": _DESCRIPTIONS[name],
                      "input_schema": _inline(_load(files[name]), defs)})
    return tools


def application_schema(tool: str) -> dict[str, Any]:
    files = {TOOL_INSPECT: "inspect_catalog.schema.json",
             TOOL_PRODUCT: "inspect_product_knowledge.schema.json",
             TOOL_EXECUTE: "execute_analysis.schema.json",
             TOOL_READ: "read_artifact.schema.json",
             TOOL_FINALIZE: "finalize_response.schema.json",
             "event": "event.schema.json", "error": "error.schema.json",
             "state_machine": "state_machine.json"}
    return _load(files[tool])


__all__ = ["ArtifactRequest", "BATCHABLE", "CATALOG_DETAILS", "COCKPIT",
           "COVERAGE_STATUSES", "CatalogRequest", "CoverageItem",
           "DATA_ANALYSIS", "DISPOSITIONS", "EvidenceRef",
           "ExecutionSubmission", "FinalResponse", "Intent",
           "MAX_BATCHED_READS", "MAX_CODE_BYTES", "MAX_SAMPLE_ROWS",
           "NO_EXECUTION_MODES", "NumericClaim", "OWNERS", "PRODUCT_HELP",
           "QUERY_MODES", "Rejection", "Step", "THEORY_CONCEPT",
           "TOOL_CONTRACT_VERSION", "TOOL_EXECUTE", "TOOL_FINALIZE",
           "TOOL_INSPECT", "TOOL_NAMES", "TOOL_PRODUCT", "TOOL_READ",
           "UNSUPPORTED",
           "application_schema", "parse_artifact", "parse_catalog",
           "parse_execution", "parse_final", "parse_intent",
           "parse_product_knowledge", "parse_steps",
           "provider_tools", "units_display"]

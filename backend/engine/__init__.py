"""
The IPM Engine — deterministic, versioned, tested credit-risk analytics.

The rule this package exists to enforce (docs/PRODUCT_SPEC.md §2):

    Every material number displayed in IPM must be produced by deterministic,
    testable, version-controlled engine code. The LLM never performs arithmetic
    and is never the source of truth for a figure.

Nothing in here imports an LLM, a web framework, or duckdb. Engine functions take
an explicit AnalysisContext and validated parameters, ask the Data Access Layer
for governed datasets by name, and return a structured AnalysisResult.

  contracts.py   what an analysis declares about itself (Engine Builder metadata)
  registry.py    the menu: registered analyses the planner may choose from
  functions/     one module per analytical capability (Phase 2)
"""

from backend.engine.contracts import (
    AnalysisContract,
    Category,
    Certification,
    ContractError,
    OutputField,
    Parameter,
    ParamType,
    ValidationRule,
    VisualizationType,
)
from backend.engine.registry import (
    REGISTRY,
    AnalysisResult,
    Registry,
    UnknownAnalysisError,
    get_registry,
    register,
)

__all__ = [
    "REGISTRY",
    "AnalysisContract",
    "AnalysisResult",
    "Category",
    "Certification",
    "ContractError",
    "OutputField",
    "ParamType",
    "Parameter",
    "Registry",
    "UnknownAnalysisError",
    "ValidationRule",
    "VisualizationType",
    "get_registry",
    "register",
]

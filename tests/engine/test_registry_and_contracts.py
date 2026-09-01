"""
Engine registry and contract tests.

These test the wall between the language model and the numbers. The rejection
cases are the point: if an unregistered analysis or a bad parameter can slip
through, the governing rule of the product is not actually enforced.
"""

from __future__ import annotations

import pytest

from backend.data_access.context import AnalysisContext
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
    AnalysisResult,
    Registry,
    RegistryError,
    UnknownAnalysisError,
    get_registry,
)


def make_contract(**overrides) -> AnalysisContract:
    base = dict(
        id="demo_analysis",
        name="Demo Analysis",
        description="A contract used for testing the registry.",
        category=Category.MONITOR,
        version="1.0.0",
        owner="Credit Risk Analytics",
        certification=Certification.CERTIFIED,
        required_datasets=["portfolio_facility"],
        required_fields=["ead", "ifrs9_stage"],
        parameters=[
            Parameter("top_n", ParamType.INTEGER, "How many rows to return.", default=10,
                      minimum=1, maximum=100),
            Parameter("group_by", ParamType.ENUM, "Dimension to group by.",
                      default="sector", allowed_values=["sector", "region", "segment"]),
            Parameter("period", ParamType.PERIOD, "Reporting period.", required=True),
        ],
        outputs=[OutputField("ead", "Exposure at default.", "number", unit="SAR mn", precision=1)],
        validation_rules=[ValidationRule("sums_to_total", "Group EADs must sum to the total.")],
        supported_visualizations=[VisualizationType.BAR, VisualizationType.TABLE],
        calculation_description="Sums EAD by the chosen dimension.",
    )
    base.update(overrides)
    return AnalysisContract(**base)


def noop(context: AnalysisContext, params: dict) -> AnalysisResult:
    return AnalysisResult(values={"ok": True})


# ------------------------------------------------------------ parameter rules


def test_defaults_are_applied_when_not_supplied():
    resolved = make_contract().validate_params({"period": "Q1 2026"})
    assert resolved["top_n"] == 10
    assert resolved["group_by"] == "sector"


def test_required_parameter_missing_is_rejected():
    with pytest.raises(ContractError, match="required"):
        make_contract().validate_params({})


def test_unknown_parameter_is_rejected_not_ignored():
    """Silently dropping an unrecognised parameter would answer a different
    question from the one asked, with full confidence."""
    with pytest.raises(ContractError) as e:
        make_contract().validate_params({"period": "Q1 2026", "sector": "Real Estate"})
    assert "sector" in str(e.value)


def test_value_outside_allowed_set_is_rejected():
    with pytest.raises(ContractError, match="must be one of"):
        make_contract().validate_params({"period": "Q1 2026", "group_by": "colour"})


@pytest.mark.parametrize("value", [0, 101])
def test_value_outside_numeric_bounds_is_rejected(value):
    with pytest.raises(ContractError):
        make_contract().validate_params({"period": "Q1 2026", "top_n": value})


def test_wrong_type_is_rejected():
    with pytest.raises(ContractError, match="whole number"):
        make_contract().validate_params({"period": "Q1 2026", "top_n": "ten"})


def test_boolean_is_not_accepted_as_an_integer():
    """Python treats True as 1. A plan saying top_n=true is a mistake, not a 1."""
    with pytest.raises(ContractError):
        make_contract().validate_params({"period": "Q1 2026", "top_n": True})


def test_error_messages_name_the_accepted_parameters():
    """These messages surface in the AI Cockpit when a plan is rejected, so they
    have to be useful to a non-developer."""
    with pytest.raises(ContractError) as e:
        make_contract().validate_params({"period": "Q1 2026", "nonsense": 1})
    assert "top_n" in str(e.value) and "group_by" in str(e.value)


# ------------------------------------------------------------------ registry


def test_register_and_retrieve():
    reg = Registry()
    contract = make_contract()
    reg.add(contract, noop)
    assert "demo_analysis" in reg
    assert reg.contract("demo_analysis").version == "1.0.0"


def test_duplicate_registration_is_rejected():
    reg = Registry()
    reg.add(make_contract(), noop)
    with pytest.raises(RegistryError, match="already registered"):
        reg.add(make_contract(), noop)


def test_unknown_analysis_raises_and_lists_what_exists():
    """This is the error that stops an invented calculation from ever running."""
    reg = Registry()
    reg.add(make_contract(), noop)
    with pytest.raises(UnknownAnalysisError) as e:
        reg.get("invented_by_the_model")
    assert "demo_analysis" in str(e.value)


def test_draft_and_deprecated_are_not_runnable():
    reg = Registry()
    reg.add(make_contract(id="draft_one", certification=Certification.DRAFT), noop)
    reg.add(make_contract(id="old_one", certification=Certification.DEPRECATED), noop)
    reg.add(make_contract(id="live_one", certification=Certification.CERTIFIED), noop)
    assert reg.ids() == ["draft_one", "live_one", "old_one"]
    assert [a.id for a in reg.runnable()] == ["live_one"]


def test_require_runnable_refuses_a_draft():
    reg = Registry()
    reg.add(make_contract(id="draft_one", certification=Certification.DRAFT), noop)
    with pytest.raises(ContractError, match="draft"):
        reg.require_runnable("draft_one")


def test_only_certified_analyses_get_the_tick():
    reg = Registry()
    reg.add(make_contract(id="a", certification=Certification.CERTIFIED), noop)
    reg.add(make_contract(id="b", certification=Certification.USER_DEFINED), noop)
    assert [a.id for a in reg.certified()] == ["a"]
    assert reg.contract("b").is_certified is False
    assert reg.contract("b").is_runnable is True


def test_contract_serialises_everything_engine_builder_displays():
    payload = make_contract().to_dict()
    for key in (
        "id", "name", "description", "category", "version", "owner", "certification",
        "is_certified", "required_datasets", "required_fields", "parameters",
        "outputs", "validation_rules", "supported_visualizations",
        "calculation_description",
    ):
        assert key in payload, f"Engine Builder needs '{key}' in the contract payload"
    assert payload["outputs"][0]["unit"] == "SAR mn"


def test_global_registry_loads_without_error():
    """Phase 1 registers no functions yet; this must be an empty registry rather
    than an import failure."""
    reg = get_registry()
    assert isinstance(reg.summary()["total"], int)

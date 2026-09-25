"""Two of the fourteen failures are questions, and returning them as errors
would send the analyst back to repair code that was never wrong.

UNIT. No database, no model, no provider call.

Section 19 lists fourteen domain error categories and says: *"Map these into
the existing error contract and repair flow; do not replace core exceptions or
swallow their evidence."*

So `states.ERROR_CODES` is not grown -- it is a protected core constant, and
editing it to avoid writing a mapping is the kind of change section 1.2
forbids. Each category declares the existing code it travels as, and the
domain name rides in the rejection's detail where the tool result shows it.

The split this file exists for: `UNIT_AMBIGUOUS` and `RULE_CONFLICT` are not
defects in a submission. They are questions only the reader can answer, and
they have a home already -- `disposition: "clarification"`. Handing them back
as rejections is the loop `action_state.decide`'s `must_clarify` branch was
built to end.

Also covers section 16.1's A04: both flags off restores baseline.
"""

from __future__ import annotations

import inspect

import pytest

from backend.cockpit_v4 import states as st
from backend.cockpit_v4.contracts import Rejection
from backend.cockpit_v4.scenario import errors as er
from backend.cockpit_v4.scenario import flags as fl

# ---- the taxonomy ------------------------------------------------------

#: The fourteen names section 19 lists, quoted from it.
SPECIFIED = (
    "COHORT_UNRESOLVED", "BOOK_MISMATCH", "SOURCE_VERSION_MISMATCH",
    "UNIT_AMBIGUOUS", "RULE_CONFLICT", "PARAMETER_OUT_OF_RANGE",
    "MAPPING_UNAVAILABLE", "SENSITIVITY_NOT_SUPPORTED", "MODEL_NOT_READY",
    "METHOD_COVERAGE_GAP", "CONFIRMATION_STALE", "BUDGET_EXCEEDED",
    "CALCULATION_FAILED", "RECONCILIATION_FAILED",
)


def test_all_fourteen_specified_categories_exist() -> None:
    assert set(er.BY_CODE) == set(SPECIFIED)
    assert len(er.CATEGORIES) == 14


def test_every_category_maps_onto_a_code_the_runtime_already_has() -> None:
    """The mapping is the point. A domain code that routed nowhere would be a
    new taxonomy wearing the old one's clothes."""
    for category in er.CATEGORIES:
        assert category.maps_to in st.ERROR_CODES, category.code


def test_no_domain_code_was_added_to_the_core_tuple() -> None:
    """`states.ERROR_CODES` is protected. Growing it is the change section 1.2
    says to document rather than make."""
    assert not set(SPECIFIED) & set(st.ERROR_CODES)


def test_every_category_says_what_to_do_next() -> None:
    """Section 19: each error identifies the reason and the supported next
    action. A code with no next action is a dead end with a name."""
    for category in er.CATEGORIES:
        assert len(category.meaning) > 20, category.code
        assert len(category.next_action) > 20, category.code
        assert category.kind in (er.ASK, er.REJECT, er.BUDGET), category.code


# ---- ask versus reject -------------------------------------------------

def test_exactly_the_two_reader_questions_are_asks() -> None:
    assert er.ASK_CODES == frozenset({er.UNIT_AMBIGUOUS, er.RULE_CONFLICT})


def test_a_question_refuses_to_become_a_rejection() -> None:
    """Guarded by the type, not by a comment."""
    error = er.ScenarioError(er.UNIT_AMBIGUOUS, "increase by 20 what?")
    with pytest.raises(TypeError, match="question for the reader"):
        error.as_rejection()


def test_a_defect_refuses_to_become_a_question() -> None:
    error = er.ScenarioError(er.COHORT_UNRESOLVED, "no rows")
    with pytest.raises(TypeError, match="defect the analyst can correct"):
        error.as_clarification(question="which rows?")


def test_a_question_carries_the_readings_as_clickable_options() -> None:
    """Section 5.1: ask once, with the concrete choices, so the reader can
    click rather than type."""
    error = er.ScenarioError(er.UNIT_AMBIGUOUS,
                             "'increase PD by 20' could mean four things")
    asked = error.as_clarification(
        question="Did you mean 20% relative, 20 percentage points, 20 basis "
                 "points, or set PD to 20%?",
        options=["20% relative", "+20 percentage points", "+20 basis points",
                 "Set PD to 20%"])
    assert asked["disposition"] == "clarification"
    assert len(asked["clarification_options"]) == 4
    assert asked["whatif_error"] == er.UNIT_AMBIGUOUS


# ---- what a rejection carries -----------------------------------------

def test_a_rejection_is_the_existing_contract() -> None:
    error = er.ScenarioError(er.BOOK_MISMATCH,
                             "this scenario reaches Retail from a Corporate "
                             "thread",
                             field_path="source.domain_id")
    rejection = error.as_rejection()
    assert isinstance(rejection, Rejection)
    assert rejection.code == st.SECURITY_DENIED
    assert rejection.field_path == "source.domain_id"


def test_the_domain_name_is_not_swallowed_by_the_mapping() -> None:
    """Section 19: do not swallow their evidence."""
    wire = er.ScenarioError(er.MODEL_NOT_READY, "no emulator for corporate",
                            detail={"book": "corporate"}
                            ).as_rejection().to_tool_result()
    assert wire["error_code"] == st.DATA_UNAVAILABLE
    assert wire["detail"]["whatif_error"] == er.MODEL_NOT_READY
    assert wire["detail"]["book"] == "corporate"
    assert wire["detail"]["next_action"]


def test_cross_book_access_is_a_scope_violation_not_a_data_gap() -> None:
    """A16 in spirit: Corporate data through a Retail scenario is refused as
    a permission failure, because that is what it is."""
    assert er.BY_CODE[er.BOOK_MISMATCH].maps_to == st.SECURITY_DENIED


def test_an_unknown_category_cannot_be_raised() -> None:
    with pytest.raises(KeyError, match="not a scenario error category"):
        er.ScenarioError("SOMETHING_WENT_WRONG", "…")


def test_raise_for_is_the_same_error_with_less_ceremony() -> None:
    with pytest.raises(er.ScenarioError) as caught:
        er.raise_for(er.CALCULATION_FAILED, "the step produced no rows",
                     field_path="steps.0", step_id="s1")
    assert caught.value.code == er.CALCULATION_FAILED
    assert caught.value.detail["step_id"] == "s1"


def test_reconciliation_failure_is_a_defect_in_the_run() -> None:
    """Section 13.2 allows a residual to be SHOWN. This fires only when even
    that cannot be stated, and nothing is published from it."""
    category = er.BY_CODE[er.RECONCILIATION_FAILED]
    assert "defect in the run" in category.next_action
    assert "nothing is" in category.next_action


# ---- flags: A04 --------------------------------------------------------

def test_both_books_are_off_by_default(monkeypatch) -> None:
    for variable in fl.VARIABLES.values():
        monkeypatch.delenv(variable, raising=False)
    assert fl.enabled("corporate") is False
    assert fl.enabled("retail") is False
    assert fl.any_enabled() is False


def test_each_book_has_its_own_flag(monkeypatch) -> None:
    """Section 2: separately for Corporate and Retail. One flag for both is
    how a Retail reader ends up inside a Corporate capability."""
    for variable in fl.VARIABLES.values():
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(fl.VARIABLES["corporate"], "1")
    assert fl.enabled("corporate") is True
    assert fl.enabled("retail") is False


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("maybe", False),
])
def test_the_truthy_set_matches_the_runtimes_own(monkeypatch, value,
                                                 expected) -> None:
    """An operator who has learned `config._flag` has learned this one."""
    monkeypatch.setenv(fl.VARIABLES["corporate"], value)
    assert fl.enabled("corporate") is expected


def test_an_unknown_book_is_off_rather_than_an_error() -> None:
    assert fl.enabled("mortgages") is False
    assert fl.enabled("") is False


def test_a04_with_both_off_the_accepted_runtime_does_not_import_this() -> None:
    """The strongest form of "disabling both restores baseline": not a code
    path that checks a flag and shrugs, but no code path at all.

    Read as source text rather than by importing, so the test fails if a
    future edit adds the import even inside a lazy function body that no
    import graph would show until it ran.

    Matched as an IMPORT, not as the word. `catalog_tool.py` and
    `product_knowledge.py` both use "scenario" in prose -- the first about
    stored scenario/horizon rows multiplying a facility, the second as a
    product-topic keyword -- and neither reaches this package.
    """
    import pathlib
    import re

    from backend.cockpit_v4 import scenario

    imports = re.compile(
        r"^\s*(?:from\s+backend\.cockpit_v4(?:\.scenario)?\s+import\s+[^\n]*"
        r"\bscenario\b|from\s+backend\.cockpit_v4\.scenario\b|"
        r"import\s+backend\.cockpit_v4\.scenario\b)",
        re.MULTILINE)

    core = pathlib.Path(scenario.__file__).parent.parent
    offenders = [p.name for p in sorted(core.glob("*.py"))
                 if imports.search(p.read_text())]
    assert offenders == [], (
        f"{offenders} import the scenario package. With both flags off "
        f"nothing in the accepted runtime may reach it.")


def test_the_status_block_says_which_variables_to_set() -> None:
    """Section 2: register readiness so the chat can say what is available
    before the user confirms anything."""
    status = fl.status()
    assert set(status["books"]) == {"corporate", "retail"}
    assert status["variables"]["corporate"] == "COCKPIT_V4_WHATIF_CORPORATE"


def test_the_package_documents_that_it_is_not_a_sixth_tool() -> None:
    """The one thing a future reader most needs to know before adding one."""
    from backend.cockpit_v4 import scenario

    said = inspect.getdoc(scenario) or ""
    assert "not a sixth tool" in said
    assert "PROTECTED_CORE_INCOMPATIBILITY" in said

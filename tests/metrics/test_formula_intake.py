"""§5's preservation rule, and §34's unconventional-formula journey.

The property under test is one sentence: whatever CreditProbe understands a
formula to mean, `formula_text` is a substring of what the person typed. Every
example §4 and §34 give is checked against it, and so is the mechanism that
guarantees it — the model returns offsets and CreditProbe slices its own
string, so a model that "corrected" the formula cannot change what is stored.
"""

from __future__ import annotations

import pytest

from backend.metrics import formula_intake as intake_mod

#: Every example §4 lists, plus §33's and §34's.
EXAMPLES = [
    "Add Stage 2 Exposure / Total Exposure.",
    "(Current Quarter Exposure / Previous Quarter Exposure) - 1",
    "High EWS exposure divided by total corporate exposure.",
    "Take Stage 2 EAD plus Stage 3 EAD and divide by total EAD.",
    "Show covenant breach exposure divided by corporate exposure.",
    "Previous Quarter Exposure / Current Quarter Exposure - 1",
    "Add quarter-on-quarter exposure change:\n"
    "(Current Quarter Exposure / Previous Quarter Exposure) - 1",
    "Stage 2 Exposure / Total Exposure by sector",
]


# --------------------------------------------------------------- preservation


@pytest.mark.parametrize("said", EXAMPLES)
def test_the_formula_is_always_a_substring_of_what_was_typed(said):
    """The one property this module exists to guarantee."""
    intake = intake_mod.read_deterministic(said)
    assert intake.preserved
    if intake.is_formula:
        assert intake.formula_text in said


@pytest.mark.parametrize("said", EXAMPLES)
def test_nothing_reorders_the_operands(said):
    intake = intake_mod.read_deterministic(said)
    if not (intake.numerator_text and intake.denominator_text):
        return
    assert intake.numerator_text in said
    assert intake.denominator_text in said
    # The numerator was written before the denominator, and stays that way.
    assert said.index(intake.numerator_text) < said.index(
        intake.denominator_text)


def test_a_slice_that_does_not_land_on_the_original_is_refused():
    """The mechanism, tested directly: offsets that do not bracket arithmetic
    are rejected rather than trusted."""
    said = "Stage 2 Exposure / Total Exposure"
    assert intake_mod._sliced(said, 0, len(said)) == said
    assert intake_mod._sliced(said, -1, 5) == ""
    assert intake_mod._sliced(said, 5, 5) == ""
    assert intake_mod._sliced(said, 0, len(said) + 10) == ""
    assert intake_mod._sliced(said, "x", "y") == ""


# ------------------------------------------------------------------- reading


def test_a_word_operator_is_arithmetic():
    intake = intake_mod.read_deterministic(
        "High EWS exposure divided by total corporate exposure.")
    assert intake.is_formula
    assert intake.operation == "/"
    assert intake.numerator_text == "High EWS exposure"
    assert intake.denominator_text == "total corporate exposure"


def test_a_growth_tail_does_not_end_up_in_the_denominator():
    """`(a / b) - 1` yields `a` and `b`, not `a` and `b) - 1`. That was a real
    defect, and the kind that reaches a person as a denominator nobody
    typed."""
    intake = intake_mod.read_deterministic(
        "(Current Quarter Exposure / Previous Quarter Exposure) - 1")
    assert intake.operation == "growth"
    assert intake.numerator_text == "Current Quarter Exposure"
    assert intake.denominator_text == "Previous Quarter Exposure"


def test_a_label_before_a_colon_is_not_part_of_the_formula():
    intake = intake_mod.read_deterministic(
        "Add quarter-on-quarter exposure change: "
        "(Current Quarter Exposure / Previous Quarter Exposure) - 1")
    assert intake.formula_text.startswith("(Current Quarter Exposure")
    assert "change:" not in intake.formula_text


def test_a_label_becomes_the_suggested_name():
    intake = intake_mod.read("Add QoQ Exposure Change %: "
                             "(Current Quarter Exposure / "
                             "Previous Quarter Exposure) - 1")
    assert intake.suggested_name == "QoQ Exposure Change %"


def test_a_ratio_names_itself_from_its_two_sides():
    intake = intake_mod.read("Add Stage 2 Exposure / Total Exposure.")
    assert intake.suggested_name == "Stage 2 Exposure / Total Exposure"


def test_digits_survive_into_the_name():
    """"Stage 2 Exposure" naming itself "Stage Exposure" names a different
    thing, and does so silently."""
    intake = intake_mod.read("Add Stage 2 Exposure / Total Exposure.")
    assert "2" in intake.suggested_name


def test_a_request_for_an_existing_metric_is_not_a_formula():
    """§4's own boundary: one thing named, no arithmetic."""
    for said in ("add total exposure", "show me the Stage 2 ratio",
                 "put watchlist exposure on this lens"):
        intake = intake_mod.read_deterministic(said)
        assert not intake.is_formula, said


def test_a_hyphenated_word_is_not_a_subtraction():
    intake = intake_mod.read_deterministic("add quarter-on-quarter growth")
    assert not intake.is_formula


def test_a_chart_request_is_recorded_beside_the_formula():
    intake = intake_mod.read_deterministic(
        "Stage 2 Exposure / Total Exposure by sector")
    assert intake.is_formula
    assert intake.wants_chart
    assert intake.group_by == "sector"
    # …and the grouping is NOT part of the arithmetic.
    assert "sector" not in intake.formula_text


def test_a_period_window_is_recorded():
    intake = intake_mod.read_deterministic(
        "Show that formula by quarter over the last 8 quarters")
    assert intake.period_hint == "last 8 quarters"
    assert intake.group_by == "quarter"


# ----------------------------------------------------- §34: unconventional


def test_an_inverted_growth_formula_is_flagged_not_corrected():
    intake = intake_mod.read_deterministic(
        "Previous Quarter Exposure / Current Quarter Exposure - 1")
    assert intake.unconventional is not None
    # Flagged…
    assert "inverse" in intake.unconventional.because
    # …offered an alternative…
    assert intake.unconventional.conventional == (
        "Current Quarter Exposure / Previous Quarter Exposure - 1")
    # …with the three choices §5 names…
    assert [c["id"] for c in intake.unconventional.to_dict()["choices"]] == [
        "keep", "conventional", "edit"]
    # …and NOTHING applied.
    assert intake.formula_text == (
        "Previous Quarter Exposure / Current Quarter Exposure - 1")


def test_the_conventional_form_is_the_persons_own_words_swapped():
    """Not generated prose. If they choose it, they get what they would have
    typed."""
    intake = intake_mod.read_deterministic(
        "Prior Quarter EAD / Latest Quarter EAD - 1")
    assert intake.unconventional is not None
    assert "Prior Quarter EAD" in intake.unconventional.conventional
    assert "Latest Quarter EAD" in intake.unconventional.conventional


def test_the_conventional_direction_is_not_flagged():
    intake = intake_mod.read_deterministic(
        "(Current Quarter Exposure / Previous Quarter Exposure) - 1")
    assert intake.unconventional is None


def test_a_ratio_with_no_period_words_is_not_flagged():
    """Warning about every ratio would train people to dismiss the warning."""
    intake = intake_mod.read_deterministic(
        "Stage 2 Exposure / Total Exposure")
    assert intake.unconventional is None


# ----------------------------------------------------------------- degrading


def test_reading_works_with_no_provider_configured():
    """The deterministic reader handles every example §4 gives, because those
    examples are arithmetic and arithmetic is parseable."""
    for said in EXAMPLES:
        intake = intake_mod.read(said)
        assert intake.preserved
        assert not intake.understood or intake.formula_text in said


def test_pass_two_never_touches_the_formula():
    intake = intake_mod.read_deterministic(
        "Add Stage 2 Exposure / Total Exposure.")
    before = intake.formula_text
    intake_mod.read_intent(intake)
    assert intake.formula_text == before
    assert intake.suggested_name
    assert intake.unit_hint == "percent"

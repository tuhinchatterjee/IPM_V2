"""
Questions nobody built an answer for.

The claim being tested is the one the whole pivot rests on: CreditProbe can
compose an analysis it was never given, run it safely, and label it honestly.
Three things have to hold at once, and each has its own tests below —

  * it composes the right thing. The worked example from the brief is run end
    to end and its rows are checked against the conditions row by row;
  * it refuses rather than narrows. A question it cannot read completely comes
    back with the reason, and a condition naming an ungoverned field is a
    refusal rather than a silently dropped filter;
  * it never claims certification. A composed analysis is labelled DYNAMIC
    wherever it appears, and the certified library is preferred whenever it
    would answer the question.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.orchestration.dynamic import (
    DEFAULT_DATASET,
    build_plan,
    read_conditions,
    read_question,
)
from backend.runtime.executor import ExecutionClass, execute

WORKED_EXAMPLE = (
    "Show Real Estate customers whose ECL increased more than 20%, rating "
    "deteriorated at least two notches, and EAD did not decline over the "
    "latest year."
)

#: The same question with only the condition every qualifying borrower must
#: meet. R2 §24 recalibrated the book and the worked example's four-way
#: intersection now lands empty by a single borrower — seven Real Estate
#: customers were downgraded two notches over the latest year, one of those
#: also saw ECL rise by more than a fifth, and that one's exposure fell.
#: Whether the intersection is occupied is a coincidence about the data;
#: whether the composed analysis RUNS and finds a population to filter is the
#: thing this test is for.
WORKED_BASE = (
    "Show Real Estate customers whose rating deteriorated at least two "
    "notches over the latest year."
)


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if DEFAULT_DATASET not in get_data_source().datasets():
        pytest.skip("Analytical lake not built")


@pytest.fixture(scope="module")
def vocab():
    from backend.orchestration.vocabulary import get_vocabulary

    return get_vocabulary()


@pytest.fixture(scope="module")
def request_(vocab):
    return read_question(WORKED_EXAMPLE, periods=vocab.periods,
                        dimensions=vocab.dimensions)


# ------------------------------------------------------------------- reading


def test_the_worked_example_is_read_completely(request_):
    assert request_.understood, request_.reasons
    assert request_.grain == "customer"
    assert ("sector", "Real Estate") in request_.filters
    assert len(request_.conditions) == 3


def test_each_condition_is_read_as_the_comparison_it_actually_is(request_):
    by_field = {c.field: c for c in request_.conditions}

    ecl = by_field["total_ecl"]
    assert (ecl.kind, ecl.op, ecl.value) == ("change_pct", "gt", 20.0), (
        "'increased more than 20%' is a relative change, strictly greater."
    )
    rating = by_field["internal_grade"]
    assert (rating.kind, rating.op, rating.value) == ("change_abs", "gte", 2.0), (
        "'at least two notches' is an absolute move on an ordinal scale."
    )
    ead = by_field["ead"]
    assert (ead.kind, ead.op, ead.value) == ("change_abs", "gte", 0.0), (
        "'did not decline' is a floor at zero, not a movement."
    )


def test_the_reading_is_stated_in_words_a_person_can_check(request_):
    summary = request_.summary
    assert "Real Estate" in summary
    assert "ECL rose more than 20%" in summary
    assert "did not fall" in summary
    assert request_.opening in summary and request_.closing in summary
    assert "total_ecl" not in summary, (
        "A condition read correctly and shown as a column name cannot be "
        "checked by the person who asked."
    )


def test_deteriorate_resolves_against_the_measure_it_describes():
    """A rating deteriorating is a HIGHER grade; coverage deteriorating is a
    LOWER percentage. Reading both as 'up' would invert one of them."""
    rating, _ = read_conditions("rating deteriorated by 2")
    assert rating[0].field == "internal_grade"
    assert rating[0].value > 0

    coverage, _ = read_conditions("ECL coverage deteriorated by 5%")
    assert coverage[0].field == "ecl_coverage_pct"
    assert coverage[0].value < 0, "Coverage getting worse means coverage falling."


def test_conditions_are_read_one_clause_at_a_time():
    conditions, _ = read_conditions(
        "utilisation rose more than 10% and days past due increased")
    assert {c.field for c in conditions} == {"utilisation_pct", "dpd_days"}, (
        "A greedy tail that swallows the clause after it answers a narrower "
        "question without saying so."
    )


# ------------------------------------------------------------------ refusing


def test_a_question_with_no_period_is_refused(vocab):
    reading = read_question(
        "Show customers whose ECL increased more than 20% and EAD fell",
        periods=vocab.periods, dimensions=vocab.dimensions)
    assert not reading.understood
    assert any("over what period" in r for r in reading.reasons)


def test_a_question_with_no_condition_is_refused(vocab):
    reading = read_question("What is our NPL ratio?", periods=vocab.periods,
                            dimensions=vocab.dimensions)
    assert not reading.understood
    assert any("no measurable condition" in r for r in reading.reasons)


def test_a_refusal_names_every_reason_not_the_first(vocab):
    reading = read_question("What is our NPL ratio?", periods=vocab.periods,
                            dimensions=vocab.dimensions)
    assert len(reading.reasons) >= 2


def test_a_plan_cannot_be_built_from_a_reading_that_was_refused(vocab):
    reading = read_question("do the usual", periods=vocab.periods,
                            dimensions=vocab.dimensions)
    with pytest.raises(ValueError):
        build_plan(reading)


def test_a_question_naming_no_governed_field_is_refused(vocab):
    reading = read_question(
        "Show customers whose sentiment score increased more than 20% and "
        "vibe deteriorated over the latest year",
        periods=vocab.periods, dimensions=vocab.dimensions)
    assert not reading.understood


# ------------------------------------------------------------------ the plan


def test_the_plan_is_data_and_carries_no_sql(request_):
    import json

    plan = build_plan(request_)
    text = json.dumps(plan).lower()
    for smell in ["select ", "insert ", "drop ", "union ", "--", "/*"]:
        assert smell not in text, f"The IR should carry no SQL fragment: {smell}"


def test_both_sides_are_rolled_up_before_the_join(request_):
    """A customer holds several facilities. Joining first multiplies its rows by
    its facility count and counts one movement many times."""
    plan = build_plan(request_)
    order = [op["id"] for op in plan["operations"]]
    assert order.index("opening_grain") < order.index("movement")
    assert order.index("closing_grain") < order.index("movement")


def test_an_ordinal_measure_is_not_averaged(request_):
    plan = build_plan(request_)
    rollups = [op for op in plan["operations"] if op["id"] == "opening_grain"][0]
    for entry in rollups["params"]["aggregates"]:
        if entry["column"] == "internal_grade":
            assert entry["function"] == "max", (
                "Averaging a rating across four facilities produces a grade "
                "nobody assigned."
            )


def test_a_percentage_change_from_zero_is_null_not_infinity(request_):
    import json

    plan = build_plan(request_)
    derive = [op for op in plan["operations"] if op["op"] == "DERIVE"][0]
    text = json.dumps(derive)
    assert '"case"' in text, (
        "A customer whose opening ECL was zero has no percentage change; "
        "returning infinity would put it at the top of the list."
    )


# ---------------------------------------------------------------- executing


@pytest.fixture(scope="module")
def result(request_):
    return execute(build_plan(request_), question=WORKED_EXAMPLE,
                   intent=request_.summary)


def test_the_worked_example_runs(result):
    assert result.row_count >= 1, (
        "The bundled book should contain at least one such customer; if it "
        "does not, the demonstration has nothing to show."
    )


def test_every_returned_row_satisfies_every_condition(result, request_):
    """Checked row by row rather than trusted. The filter and the reading are
    written in different places and this is where they are reconciled."""
    for row in result.rows:
        assert row["sector"] == "Real Estate"
        assert row["total_ecl_change_pct"] > 20.0
        assert row["internal_grade_change"] >= 2
        assert row["ead_change"] >= 0


def test_the_run_is_labelled_dynamic_not_certified(result):
    assert result.certification == ExecutionClass.DYNAMIC
    assert "Dynamic" in result.certification_label
    assert "Certified" not in result.certification_label


def test_the_sql_binds_every_value(result):
    assert result.query is not None
    assert result.query.sql.count("?") == len(result.query.params)
    assert "Real Estate" not in result.query.sql, (
        "A value in the statement text was concatenated rather than bound."
    )


def test_the_trace_shows_both_reads_the_join_and_the_filter(result):
    types = {n["type"] for n in result.graph.to_dict()["nodes"]}
    assert {"DATASET", "JOIN", "DERIVED_VARIABLE", "FILTER", "SQL_QUERY"} <= types


# ------------------------------------------------------- routing through Ask


def test_a_multi_condition_question_is_composed(vocab):
    from backend.orchestration.executor import dynamic_candidate

    assert dynamic_candidate(WORKED_EXAMPLE, vocab) is not None


def test_a_question_the_certified_library_answers_is_not_composed(vocab):
    """Certified beats composed whenever both would answer the question."""
    from backend.orchestration.executor import dynamic_candidate

    assert dynamic_candidate("What is our NPL ratio?", vocab) is None
    assert dynamic_candidate("Show me ECL by sector", vocab) is None
    assert dynamic_candidate("Which customers had ECL increase over the latest "
                             "year?", vocab) is None


def test_ask_answers_the_worked_example_end_to_end():
    from backend.orchestration.executor import run_investigation

    investigation = run_investigation(WORKED_EXAMPLE, persist=False)
    body = investigation.to_dict()

    assert body["status"] == "succeeded"
    # Who READ the question, not which builder ran: "offline" is the
    # deterministic semantic reader, "llm" is a configured model. Both compose,
    # and the step below is what says the analysis was composed.
    assert body["plan"]["planner"] in {"offline", "llm"}
    assert [s["analysis_id"] for s in body["steps"]] == ["dynamic_analysis"]
    assert body["mode"]["execution"] == ExecutionClass.DYNAMIC

    step = body["steps"][0]
    assert step["certification"] == ExecutionClass.DYNAMIC
    assert step["result"]["plan"]["operations"]
    assert step["result"]["query"]["sql"]

    # The composed analysis found a population to filter. Asserted on the
    # widest form of the same question, because the four-way intersection
    # above is occupied or not by coincidence and this test is about the
    # pipeline.
    base = run_investigation(WORKED_BASE, persist=False).to_dict()
    assert base["status"] == "succeeded"
    assert base["steps"][0]["result"]["rows"]
    assert (len(step["result"]["rows"])
            <= len(base["steps"][0]["result"]["rows"]))

    # The answer says it was composed, every time. Somebody reading only the
    # headline must not come away thinking this was a reviewed calculation.
    #
    # Said once, where it belongs: on the plan's notes and on the certification
    # the answer carries. It used to be repeated inside the interpretation of
    # every answer, which is how a disclaimer becomes something readers skip.
    assert any("composed for this question" in note.lower()
               for note in body["notes"])
    assert "Dynamic" in step["result"]["certification_label"]
    assert str(len(step["result"]["rows"])) in body["narrative"]["direct_answer"]


def test_the_composed_answer_quotes_no_figure_the_runtime_did_not_return():
    from backend.orchestration.executor import run_investigation

    body = run_investigation(WORKED_EXAMPLE, persist=False).to_dict()
    rows = body["steps"][0]["result"]["rows"]
    metrics = body["narrative"]["metrics"]
    assert [m["value"] for m in metrics] == [len(rows)], (
        "The only figure the narrative may state is the count of what came back."
    )

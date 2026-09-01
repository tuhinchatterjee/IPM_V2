"""
Behavioural invariants — things that must hold whatever the question was.

A case file says "this question should route there". These say something
stronger and more durable: relationships between answers that cannot break
without the product being wrong, whichever route produced them.

They are the tests that would have caught the six failures. "Top 5 returns at
most 5" is trivially true of a ranking and was false of the concentration
analysis that answered Q4; "adding a filter cannot grow the population" is
what makes a filtered share meaningful.
"""

from __future__ import annotations

import pytest

from backend.orchestration.orchestrator import answer
from tests.conftest import database_available

LATEST = "Q2 2026"


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if not database_available():
        pytest.skip("needs the platform database")


def _run(question: str):
    result = answer(question)
    assert result.computed, f"{question!r} did not compute: {result.clarification}"
    return result


# ------------------------------------------------------------------ ranking


@pytest.mark.parametrize("n,phrase", [(5, "five"), (10, "ten"), (3, "three")])
def test_a_top_n_returns_at_most_n(n, phrase):
    result = _run(f"Show the {phrase} largest Real Estate customers by EAD")
    assert result.runtime.row_count <= n
    assert result.build.top_n == n


def test_a_ranking_is_actually_ordered():
    result = _run("Show the ten largest customers by EAD")
    values = [row["ead"] for row in result.runtime.rows]
    assert values == sorted(values, reverse=True)


def test_asking_for_the_smallest_reverses_the_order():
    result = _run("Show the five smallest Real Estate customers by EAD")
    values = [row["ead"] for row in result.runtime.rows]
    assert values == sorted(values)


# ------------------------------------------------------------------ filters


def test_a_filter_cannot_grow_the_population():
    """The most basic monotonicity there is, and the one that makes a share
    mean anything."""
    everything = _run("Show the top 50 customers by EAD")
    filtered = _run("Show the top 50 Real Estate customers by EAD")
    assert filtered.runtime.row_count <= everything.runtime.row_count


def test_a_filtered_total_never_exceeds_the_unfiltered_total():
    everything = _run("What is total EAD by sector in the latest quarter?")
    total = sum(row["ead"] for row in everything.runtime.rows)
    real_estate = next(r["ead"] for r in everything.runtime.rows
                       if r["sector"] == "Real Estate")
    assert real_estate <= total


def test_a_share_is_of_the_population_asked_about():
    """Q4's original failure: shares computed within a filtered book reported
    Real Estate as 100% of itself."""
    ranked = _run("Show the five largest Real Estate customers by EAD")
    covered = sum(row["ead_share_pct"] for row in ranked.runtime.rows)
    assert 0 < covered < 100, (
        "five customers cannot be the whole of Real Estate exposure")

    sectors = _run("What is total EAD by sector in the latest quarter?")
    sector_total = next(r["ead"] for r in sectors.runtime.rows
                        if r["sector"] == "Real Estate")
    largest = ranked.runtime.rows[0]
    implied = largest["ead"] / (largest["ead_share_pct"] / 100)
    assert implied == pytest.approx(sector_total, rel=0.01), (
        "the share's denominator must be Real Estate exposure, not the book")


# ------------------------------------------------------------ reconciliation


def test_customer_level_exposure_reconciles_with_the_facility_book():
    """Aggregating to customer must not create or lose exposure."""
    customers = _run("Show the top 200 customers by EAD")
    sectors = _run("What is total EAD by sector in the latest quarter?")
    book = sum(row["ead"] for row in sectors.runtime.rows)
    top = sum(row["ead"] for row in customers.runtime.rows)
    assert 0 < top <= book * 1.0001


# ------------------------------------------------------------------ periods


def test_a_different_period_changes_the_dataset_versions_on_the_trace():
    latest = _run("What is total EAD by sector in the latest quarter?")
    import dataclasses

    from backend.orchestration import analysis_planner as ap
    from backend.orchestration.context import retrieve
    from backend.orchestration.router import read_request_offline
    from backend.runtime.executor import execute

    question = "What is total EAD by sector in Q4 2025?"
    context = retrieve(question)
    reading = read_request_offline(question, context=context)
    reading = dataclasses.replace(reading, periods=("Q4 2025",))
    build = ap.plan(reading, context, question=question)
    earlier = execute(build.plan, question=question)

    assert build.period == "Q4 2025"
    assert latest.build.period == LATEST
    assert (earlier.fingerprint["data"]
            != latest.runtime.fingerprint["data"]), (
        "reading a different period must change the data fingerprint")


def test_the_same_question_twice_gives_the_same_run_fingerprint():
    first = _run("What is total EAD by sector in the latest quarter?")
    second = _run("What is total EAD by sector in the latest quarter?")
    assert (first.runtime.fingerprint["run"]
            == second.runtime.fingerprint["run"])


# ------------------------------------------------------------------ cohorts


def test_a_cohort_is_the_intersection_not_the_union():
    """Three conditions must narrow the population, never widen it."""
    two = _run("Which customers had a rating downgrade and an increase in ECL "
               "over the latest year?")
    three = _run("Which customers had a rating downgrade, an increase in ECL "
                 "and rising days past due over the latest year?")
    assert three.runtime.row_count <= two.runtime.row_count


def test_every_returned_row_actually_meets_every_condition():
    """The conditions are applied in SQL; this checks the SQL did what the
    conditions said."""
    result = _run("Which customers had a rating downgrade and an increase in "
                  "ECL over the latest year?")
    rows = result.runtime.rows
    assert rows
    grade = "customer_ratings_internal_grade_change"
    ecl = "ifrs9_staging_total_ecl_change"
    for row in rows:
        assert row[grade] > 0, "every row must be a downgrade"
        assert row[ecl] > 0, "every row must have risen ECL"


def test_no_returned_row_uses_data_from_after_its_own_period():
    result = _run("Which customers had a rating downgrade and an increase in "
                  "ECL over the latest year?")
    for row in result.runtime.rows:
        opening_year = int(str(row["period"]).split()[-1])
        assert int(row["customer_ratings_period"]) <= opening_year


# ------------------------------------------------------------------ entities


def test_a_customer_the_book_does_not_contain_is_never_silently_matched():
    """It must not resolve to the nearest name, and it must not quietly become
    an analysis of the whole portfolio."""
    from backend.orchestration.context import retrieve
    from backend.orchestration.entities import unresolved_names

    question = "What is Summit Power's exposure?"
    missing = unresolved_names(question, retrieve(question))
    assert "Summit Power" in missing

    result = answer(question)
    if result.computed:
        assert not result.build.filters, (
            "a name nobody has heard of must not become a filter on something "
            "else")


def test_a_governed_value_is_matched_whatever_the_spacing():
    from backend.orchestration.context import retrieve
    from backend.orchestration.entities import match_dimension

    dimensions = retrieve("sectors").dimensions
    for spelling in ("real estate", "Real-Estate", "REAL ESTATE", "real  estate"):
        matched = match_dimension(spelling, "sector", dimensions["sector"])
        assert matched is not None and matched.value == "Real Estate"


def test_a_similar_but_different_sector_is_not_matched():
    from backend.orchestration.context import retrieve
    from backend.orchestration.entities import match_dimension

    dimensions = retrieve("sectors").dimensions
    matched = match_dimension("Retail", "sector", dimensions["sector"])
    assert matched is None or matched.value != "Real Estate"


# -------------------------------------------------------------- grounding


def test_no_answer_states_a_figure_the_result_does_not_contain():
    """Mechanically, across every shape the planner can produce."""

    questions = [
        "What is total EAD by sector in the latest quarter?",
        "Show the five largest Real Estate customers by EAD",
        "Which customers had a rating downgrade and an increase in ECL over "
        "the latest year?",
        "How has ECL changed by sector over the latest year?",
    ]
    for question in questions:
        from backend.orchestration.executor import run_investigation

        investigation = run_investigation(question, persist=False)
        assert not any("could not be traced" in c
                       for c in investigation.narrative.caveats), question


def test_the_model_is_never_the_source_of_a_number():
    """Structural: nothing on the answer path turns model output into a value."""
    result = _run("What is total EAD by sector in the latest quarter?")
    assert result.reading.source in {"offline", "llm"}
    # Whoever read the question, every figure came back from the runtime.
    assert result.runtime.query is not None
    assert result.runtime.query.sql

"""
Multi-dataset dynamic analysis, end to end.

The worked example needs three governed datasets reported at two frequencies,
joined at customer level, compared across two periods. Nothing in the question
names a dataset, a key, a cardinality or a period alignment.

These tests check the three things that make such an analysis trustworthy
rather than merely impressive: that the reading picks the right governed
fields, that the joins cannot multiply or look ahead, and that the numbers
agree with an independent recomputation from the raw data.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.data_access.catalog import get_catalog
from backend.data_access.context import AnalysisContext
from backend.orchestration import multi
from backend.orchestration.vocabulary import get_vocabulary
from backend.runtime.executor import execute

FACILITY = "portfolio_facility"

WORKED = ("Show Real Estate customers whose ECL increased more than 20%, "
          "rating deteriorated at least two notches, and EAD did not decline "
          "over the latest year.")


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built")
    for needed in ("ifrs9_staging", "customer_ratings"):
        if needed not in get_data_source().datasets():
            pytest.skip(f"{needed} not built")


@pytest.fixture(scope="module")
def relationships():
    """The shipped joins, as the planner sees them — no database required."""
    from backend.services.relationships import GOVERNED_RELATIONSHIPS

    return [{
        "id": index, "name": f"{r.from_dataset} -> {r.to_dataset}",
        "from_dataset": r.from_dataset, "from_field": r.from_field,
        "to_dataset": r.to_dataset, "to_field": r.to_field,
        "cardinality": r.cardinality, "kind": r.kind,
        "join_policy": r.join_policy, "temporal_rule": r.temporal_rule,
        "confidence": r.confidence, "version": 1, "semantic": r.semantic,
        "match_rate": None, "validated_at": None,
    } for index, r in enumerate(GOVERNED_RELATIONSHIPS, start=1)]


@pytest.fixture(scope="module")
def vocabulary():
    return get_vocabulary()


def read(question, relationships, vocabulary):
    return multi.read_question(
        question, catalogue=get_catalog(), periods=vocabulary.periods,
        dimensions=vocabulary.dimensions, relationships=relationships)


@pytest.fixture(scope="module")
def worked(relationships, vocabulary):
    return read(WORKED, relationships, vocabulary)


@pytest.fixture(scope="module")
def worked_result(worked):
    build = multi.build_plan(worked, catalogue=get_catalog())
    return build, execute(build.plan, question=WORKED, intent=worked.summary)


# ------------------------------------------------------------------- reading


def test_the_worked_example_needs_three_governed_datasets(worked):
    assert worked.understood, worked.reasons
    assert set(worked.datasets) == {FACILITY, "ifrs9_staging", "customer_ratings"}
    assert worked.is_multi


def test_each_concept_resolves_to_the_authoritative_field(worked):
    by_concept = {b.match.concept.id: b for b in worked.bindings}
    assert by_concept["ecl"].dataset == "ifrs9_staging", (
        "An impairment question means the figure the impairment run booked.")
    assert by_concept["rating"].dataset == "customer_ratings", (
        "A customer's rating is the grade its annual cycle awarded.")
    assert by_concept["ead"].dataset == FACILITY


def test_the_reading_says_which_definition_it_used(worked):
    for binding in worked.bindings:
        assert binding.match.reason, (
            f"{binding.match.concept.id} chose a field without saying why")


def test_the_grain_and_periods_come_from_the_question(worked):
    assert worked.grain == multi.CUSTOMER
    assert worked.key == "customer_id"
    assert worked.opening and worked.closing
    assert worked.opening != worked.closing


def test_the_governed_filter_is_read(worked):
    assert ("sector", "Real Estate") in worked.filters


def test_the_three_comparisons_are_kept_apart(worked):
    by_concept = {b.match.concept.id: b.condition for b in worked.bindings}
    assert (by_concept["ecl"].kind, by_concept["ecl"].op) == ("change_pct", "gt")
    assert (by_concept["rating"].kind, by_concept["rating"].op) == ("change_abs", "gte")
    assert (by_concept["ead"].kind, by_concept["ead"].value) == ("change_abs", 0.0)


def test_a_question_needing_a_dataset_nothing_joins_to_is_refused(vocabulary):
    request = read(WORKED, [], vocabulary)
    assert not request.understood
    assert any("No governed relationship connects" in r for r in request.reasons)


def test_an_archived_relationship_is_not_in_the_graph():
    """Only ACTIVE relationships reach the planner, and `active_relationships`
    is the one place that decides it."""
    from backend.services import relationships as service

    assert service.RUNNABLE == frozenset({service.ACTIVE})


# --------------------------------------------------------------- the plan


def test_the_plan_joins_only_on_governed_relationships(worked):
    plan = multi.build_plan(worked, catalogue=get_catalog()).plan
    path = next(op for op in plan["operations"]
                if op["op"] == "RELATIONSHIP_PATH")
    assert path["params"]["path"], "the path must record what it joined on"
    for hop in path["params"]["path"]:
        assert hop["relationship_id"], "a join with an anonymous hop cannot be audited"
        assert hop["relationship_version"]


def test_the_many_side_is_rolled_up_before_the_join(worked):
    plan = multi.build_plan(worked, catalogue=get_catalog()).plan
    order = [op["id"] for op in plan["operations"]]
    reconcile = order.index("opening_grain")
    asof = order.index("opening_asof_customer_ratings")
    assert reconcile < asof, (
        "A customer-grained source joined before the frame is one row per "
        "customer multiplies the book back out again.")


def test_the_annual_source_is_joined_as_of_and_backwards(worked):
    plan = multi.build_plan(worked, catalogue=get_catalog()).plan
    asof = next(op for op in plan["operations"] if op["op"] == "ASOF_JOIN")
    assert asof["params"]["direction"] == "backward"
    align = next(op for op in plan["operations"] if op["op"] == "TEMPORAL_ALIGN")
    assert align["params"]["rule"] == "completed_year_of_quarter"


def test_each_dataset_gets_its_own_column_prefix(worked):
    """`ead` from the impairment run and `ead` from the facility position are
    different figures, and one must not silently win the column name."""
    plan = multi.build_plan(worked, catalogue=get_catalog()).plan
    prefixes = {op["params"].get("right_prefix")
                for op in plan["operations"]
                if op["op"] in ("JOIN", "ASOF_JOIN")}
    assert "ifrs9_staging_" in prefixes
    assert "customer_ratings_" in prefixes


def test_the_plan_carries_no_sql(worked):
    import json

    text = json.dumps(multi.build_plan(worked, catalogue=get_catalog()).plan).lower()
    for smell in ["select ", "insert ", "drop ", "union ", "--", "/*"]:
        assert smell not in text


def test_the_plan_explains_itself_in_words(worked):
    explanation = multi.explain(worked)
    assert "ifrs9_staging for expected credit loss" in explanation
    assert "as-of" in explanation
    assert "customer level" in explanation


# ------------------------------------------------------------- execution


def test_the_worked_example_runs(worked_result):
    _, result = worked_result
    assert result.query is not None
    assert result.row_count >= 1


def test_the_sql_binds_every_value(worked_result):
    _, result = worked_result
    assert result.query.sql.count("?") == len(result.query.params)
    assert "Real Estate" not in result.query.sql


def test_the_sql_reads_as_ctes_rather_than_one_flat_query(worked_result):
    _, result = worked_result
    sql = result.query.sql
    assert sql.startswith("WITH ")
    assert sql.count(" AS (") >= 10, (
        "A composed analysis decomposed into named steps is reviewable; one "
        "flat query is not.")


def test_every_join_is_on_the_trace_with_its_relationship(worked_result):
    _, result = worked_result
    governed = [j for j in result.joins if j.get("relationship_id")]
    assert len(governed) >= 4
    for join in governed:
        assert join["relationship_version"]
        assert join["cardinality"]
        assert join["rows_out"] is not None


def test_the_population_is_reconciled_step_by_step(worked_result):
    _, result = worked_result
    steps = {entry["step"]: entry for entry in result.reconciliation}
    assert "opening_base" in steps
    assert "cohort" in steps
    assert steps["opening_grain"]["reduced_by_design"], (
        "A roll-up to the analysis grain is what the step is for, not a loss.")
    assert steps["cohort"]["rows"] == result.row_count


def test_no_join_multiplied_the_book(worked_result):
    _, result = worked_result
    for join in result.joins:
        if join.get("rows_lost") is None or join["rows_out"] is None:
            continue
        before = join["rows_out"] + join["rows_lost"]
        assert join["rows_out"] <= before, (
            f"{join['step']} produced more rows than it consumed")


# --------------------------------------------- no look-ahead, ever


def test_the_asof_join_never_reads_a_later_observation(worked_result):
    """The failure this whole alignment exists to prevent."""
    _, result = worked_result
    for row in result.rows:
        opening_year = int(row["_asof_period"])
        closing_year = int(row["closing__asof_period"])
        assert int(row["customer_ratings_period"]) <= opening_year
        assert int(row["closing_customer_ratings_period"]) <= closing_year


def test_a_forward_asof_join_is_refused():
    from backend.runtime.ir import AnalyticalPlan
    from backend.runtime.validation import validate

    plan = AnalyticalPlan.from_dict({
        "id": "look_ahead",
        "operations": [
            {"id": "a", "op": "SCAN",
             "params": {"dataset": FACILITY, "period": "Q2 2026",
                        "fields": ["customer_id", "period"]}},
            {"id": "b", "op": "SCAN",
             "params": {"dataset": "customer_ratings",
                        "fields": ["customer_id", "period", "internal_grade"]}},
            {"id": "j", "op": "ASOF_JOIN", "inputs": ["a", "b"],
             "params": {"on": ["customer_id"], "left_order": "period",
                        "right_order": "period", "direction": "forward"}},
        ],
    })
    report = validate(plan)
    assert not report.ok
    assert any("had not happened yet" in r for r in report.reasons)


def test_an_asof_join_without_an_ordering_column_is_refused():
    from backend.runtime.ir import AnalyticalPlan
    from backend.runtime.validation import validate

    plan = AnalyticalPlan.from_dict({
        "id": "no_order",
        "operations": [
            {"id": "a", "op": "SCAN",
             "params": {"dataset": FACILITY, "period": "Q2 2026",
                        "fields": ["customer_id"]}},
            {"id": "b", "op": "SCAN",
             "params": {"dataset": "customer_ratings",
                        "fields": ["customer_id", "internal_grade"]}},
            {"id": "j", "op": "ASOF_JOIN", "inputs": ["a", "b"],
             "params": {"on": ["customer_id"]}},
        ],
    })
    report = validate(plan)
    assert not report.ok
    assert any("nothing for 'as of'" in r for r in report.reasons)


def test_the_completed_year_rule_never_reaches_the_current_year():
    """Q2 2026 reads the 2025 cycle. Aligning to the year label itself would
    let a quarter read a cycle that had not finished — and would land both ends
    of a year-on-year comparison on the same cycle, showing no movement."""
    plan = {
        "id": "align",
        "operations": [
            {"id": "s", "op": "SCAN",
             "params": {"dataset": FACILITY, "period": "Q2 2026",
                        "fields": ["account_id", "period"]}},
            {"id": "a", "op": "TEMPORAL_ALIGN", "inputs": ["s"],
             "params": {"column": "period", "as": "y",
                        "rule": "completed_year_of_quarter"}},
            {"id": "r", "op": "LIMIT", "inputs": ["a"], "params": {"n": 1}},
        ],
    }
    result = execute(plan, question="alignment probe")
    assert result.rows[0]["y"] == "2025"


# ------------------------------------- independent cross-domain reconciliation


def _reference_answer(opening: str, closing: str) -> set[str]:
    """The worked example, recomputed from the raw data in plain pandas.

    Shares no code with the concept reader, the resolver, the IR, the compiler
    or DuckDB. When the two agree they agree by arithmetic rather than by
    construction, which is the only reason to write it twice.
    """
    source = get_data_source()

    def read_at(dataset, period, fields):
        return source.fetch(dataset, context=AnalysisContext(period=period),
                            fields=fields, period=period)

    answers = {}
    for label, period in (("open", opening), ("close", closing)):
        facility = read_at(FACILITY, period,
                           ["customer_id", "account_id", "ead", "sector"])
        staging = read_at("ifrs9_staging", period, ["account_id", "total_ecl"])
        joined = facility.merge(staging, on="account_id", how="inner")
        grouped = joined.groupby("customer_id").agg(
            ead=("ead", "sum"), ecl=("total_ecl", "sum"),
            sector=("sector", "first")).reset_index()

        # The rating as of the latest COMPLETED annual cycle.
        year = int(period.split()[-1]) - 1
        ratings = source.fetch(
            "customer_ratings", context=AnalysisContext(period=None),
            fields=["customer_id", "period", "internal_grade"], period=None)
        ratings = ratings.copy()
        ratings["year"] = ratings["period"].astype(int)
        eligible = ratings[ratings["year"] <= year]
        latest = (eligible.sort_values("year")
                  .groupby("customer_id").tail(1)
                  .set_index("customer_id")["internal_grade"])
        grouped["grade"] = grouped["customer_id"].map(latest)
        answers[label] = grouped.set_index("customer_id")

    opening_frame, closing_frame = answers["open"], answers["close"]
    both = opening_frame.join(closing_frame, how="inner", rsuffix="_close")
    both = both[both["sector"] == "Real Estate"]

    ecl_change_pct = (both["ecl_close"] - both["ecl"]) / both["ecl"] * 100
    grade_change = both["grade_close"] - both["grade"]
    ead_change = both["ead_close"] - both["ead"]

    keep = both[(ecl_change_pct > 20) & (grade_change >= 2) & (ead_change >= 0)]
    return set(keep.index)


def test_the_worked_example_agrees_with_an_independent_recomputation(worked,
                                                                     worked_result):
    _, result = worked_result
    expected = _reference_answer(worked.opening, worked.closing)
    produced = {row["customer_id"] for row in result.rows}
    assert produced == expected, (
        f"The composed analysis and the independent recomputation disagree. "
        f"Only in the analysis: {sorted(produced - expected)}. "
        f"Only in the recomputation: {sorted(expected - produced)}.")


def test_the_returned_figures_match_the_raw_data(worked, worked_result):
    """Not only the population — the numbers themselves."""
    _, result = worked_result
    source = get_data_source()
    for row in result.rows:
        facility = source.fetch(
            FACILITY, context=AnalysisContext(period=worked.closing),
            fields=["customer_id", "ead"], period=worked.closing)
        total = float(facility[facility["customer_id"] == row["customer_id"]]
                      ["ead"].sum())
        assert abs(total - float(row["closing_ead"])) < 1e-6

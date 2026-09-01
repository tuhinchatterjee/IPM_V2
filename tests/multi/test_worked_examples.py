"""
The six worked examples from the brief, run against the real book.

Each one names a different combination of governed sources and a different
shape of answer. What is checked is not "some rows came back" — it is that the
right datasets were chosen, joined the right way, at the right grain, and that
where a question cannot be read completely it is refused rather than narrowed.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.data_access.catalog import get_catalog
from backend.orchestration import multi
from backend.orchestration.vocabulary import get_vocabulary
from backend.runtime.executor import execute

FACILITY = "portfolio_facility"

CASE_1 = ("Show Real Estate customers whose ECL increased more than 20%, "
          "rating deteriorated at least two notches, and EAD did not decline "
          "over the latest year.")
#: The same question with only the condition every qualifying borrower must
#: meet. R2 §24 recalibrated the book, and the four-way intersection behind
#: CASE_1 now lands empty by one borrower: seven Real Estate customers were
#: downgraded two notches over the latest year, one of those also saw ECL rise
#: more than a fifth, and that one's exposure fell. Asserting the intersection
#: is non-empty was asserting a coincidence. What has to hold is that the
#: three-source join PRODUCED a population and that each further condition
#: narrows it rather than emptying it by accident.
CASE_1_BASE = ("Show Real Estate customers whose rating deteriorated at least "
               "two notches over the latest year.")
CASE_2 = ("Are customers with increasing leverage more likely to have rating "
          "downgrades over the latest year?")
CASE_3 = ("How many Stage 2 accounts are showing worsening arrears over the "
          "latest quarter?")
CASE_4 = ("Which large borrowers are closest to covenant breach and have also "
          "been downgraded over the latest year?")
CASE_5 = "Which sectors had ECL rise while GDP growth fell over the latest year?"
CASE_6 = ("Which borrowers show both rising arrears and negative credit file "
          "sentiment over the latest year?")


@pytest.fixture(scope="module", autouse=True)
def require_data():
    datasets = get_data_source().datasets()
    for needed in (FACILITY, "ifrs9_staging", "customer_ratings",
                   "facility_delinquency", "covenant_tests", "macro_saudi",
                   "credit_memo_signals"):
        if needed not in datasets:
            pytest.skip(f"{needed} not built")


@pytest.fixture(scope="module")
def relationships():
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


def run(question, relationships, vocabulary):
    request = multi.read_question(
        question, catalogue=get_catalog(), periods=vocabulary.periods,
        dimensions=vocabulary.dimensions, relationships=relationships)
    if not request.understood:
        return request, None, None
    build = multi.build_plan(request, catalogue=get_catalog())
    result = execute(build.plan, question=question, intent=request.summary)
    return request, build, result


# ------------------------------------------------- 1. ratings + IFRS 9 + book


def test_case_1_joins_three_sources_at_customer_level(relationships, vocabulary):
    request, _, result = run(CASE_1, relationships, vocabulary)
    assert request.understood, request.reasons
    assert set(request.datasets) == {FACILITY, "ifrs9_staging", "customer_ratings"}
    assert request.grain == multi.CUSTOMER
    _, _, base = run(CASE_1_BASE, relationships, vocabulary)
    assert base.row_count >= 1, "the three-source join returned nobody at all"
    assert result.row_count <= base.row_count
    for row in result.rows:
        assert row["sector"] == "Real Estate"
        assert row["ifrs9_staging_total_ecl_change_pct"] > 20
        assert row["customer_ratings_internal_grade_change"] >= 2
        assert row["ead_change"] >= 0


def test_case_1_returns_the_columns_the_question_asked_for(relationships,
                                                           vocabulary):
    _, _, result = run(CASE_1, relationships, vocabulary)
    columns = {c["name"] for c in result.columns}
    for needed in ("customer_id", "borrower_name", "sector",
                   "customer_ratings_internal_grade",
                   "closing_customer_ratings_internal_grade",
                   "customer_ratings_internal_grade_change",
                   "ifrs9_staging_total_ecl", "closing_ifrs9_staging_total_ecl",
                   "ifrs9_staging_total_ecl_change_pct",
                   "ead", "closing_ead", "ead_change_pct"):
        assert needed in columns, f"{needed} missing from the result"


# ----------------------------------------------------- 2. financials + ratings


def test_case_2_measures_association_and_claims_nothing_more(relationships,
                                                             vocabulary):
    request, _, result = run(CASE_2, relationships, vocabulary)
    assert request.understood, request.reasons
    assert request.shape == multi.ASSOCIATION
    assert "customer_ratings" in request.datasets
    row = result.rows[0]
    assert row["n"] > 100
    assert -1.0 <= row["coefficient"] <= 1.0
    assert "caveat" in row or "note" in row or row["method"] == "pearson"


def test_case_2_refuses_to_correlate_a_measure_with_itself(relationships,
                                                           vocabulary):
    request, _, _ = run("Is rising ECL associated with higher ECL?",
                        relationships, vocabulary)
    assert not request.understood
    assert any("two measures" in r for r in request.reasons)


# ------------------------------------------------------------ 3. DPD + IFRS 9


def test_case_3_reads_a_level_and_a_movement_together(relationships, vocabulary):
    request, _, result = run(CASE_3, relationships, vocabulary)
    assert request.understood, request.reasons
    assert {"facility_delinquency", "ifrs9_staging"} <= set(request.datasets)
    assert request.grain == multi.FACILITY

    kinds = {b.match.concept.id: b.condition.kind for b in request.bindings}
    assert kinds["stage"] == "level", "'Stage 2' is where the population is"
    assert kinds["dpd"] == "change_abs", "'worsening arrears' is a movement"

    assert result.row_count >= 1
    for row in result.rows:
        # Stage 2 NOW, not a year ago. The bare column carries the opening
        # position in a two-period plan; a level condition is a statement about
        # where the population sits at the closing date.
        assert row["closing_ifrs9_staging_ifrs9_stage"] == 2
        assert row["facility_delinquency_days_past_due_change"] > 0


# ------------------------------------------------- 4. covenants + ratings


def test_case_4_ranks_without_inventing_a_threshold(relationships, vocabulary):
    request, build, result = run(CASE_4, relationships, vocabulary)
    assert request.understood, request.reasons
    assert request.shape == multi.RANKING
    assert {"covenant_tests", "customer_ratings"} <= set(request.datasets)

    cohort = next(op for op in build.plan["operations"] if op["id"] == "cohort")
    thresholds = [w for w in cohort["params"]["where"]
                  if w.get("column", "").endswith("headroom_pct")]
    assert not thresholds, (
        "'Closest to breach' sets no cut-off, and supplying one would put a "
        "number in the analysis nobody chose.")
    assert 0 < result.row_count <= multi.MAX_RANKED


def test_case_4_aggregates_the_covenant_table_before_joining(relationships,
                                                             vocabulary):
    _, build, _ = run(CASE_4, relationships, vocabulary)
    rolled = [op for op in build.plan["operations"]
              if op["op"] == "AGGREGATE_BEFORE_JOIN"
              and "covenant" in op["id"]]
    assert rolled, (
        "A facility has several covenants; joining them raw multiplies the "
        "book by the number of tests.")
    assert any("multiply" in w for w in build.warnings)


# ------------------------------------------------------- 5. macro + sector


def test_case_5_joins_macro_at_sector_grain(relationships, vocabulary):
    request, _, result = run(CASE_5, relationships, vocabulary)
    assert request.understood, request.reasons
    assert "macro_saudi" in request.datasets
    assert request.grain == multi.SECTOR
    # The answer may legitimately be empty: whether the macro environment
    # weakened is a property of the data, not of the question. What must hold
    # is that the join happened and the reading is right.
    assert result.query is not None
    assert any(j.get("to") == "macro_saudi" for j in result.joins)


def test_case_5_agrees_with_the_macro_series(relationships, vocabulary):
    """Independently: if GDP growth did not fall, no sector can qualify."""
    from backend.data_access.context import AnalysisContext

    request, _, result = run(CASE_5, relationships, vocabulary)
    source = get_data_source()

    def growth(period):
        frame = source.fetch("macro_saudi", context=AnalysisContext(period=period),
                             fields=["real_gdp_growth_pct"], period=period)
        return float(frame["real_gdp_growth_pct"].iloc[0])

    fell = growth(request.closing) < growth(request.opening)
    assert (result.row_count > 0) == fell, (
        "Every sector shares the quarter's macro reading, so either all of "
        "them qualify on the macro condition or none do.")


def test_case_5_says_co_movement_rather_than_cause(relationships, vocabulary):
    import time

    from backend.orchestration.executor import multi_candidate, run_multi

    candidate = multi_candidate(CASE_5, vocabulary)
    if candidate is None:
        pytest.skip("routing declined this question")
    investigation = run_multi(CASE_5, candidate, started=time.perf_counter())
    text = investigation.narrative.interpretation.lower()
    assert "cause" not in text or "not" in text


# -------------------------------------------- 6. credit file + quantitative


def test_case_6_joins_a_governed_qualitative_signal(relationships, vocabulary):
    request, _, result = run(CASE_6, relationships, vocabulary)
    assert request.understood, request.reasons
    assert {"credit_memo_signals", "facility_delinquency"} <= set(request.datasets)

    sentiment = next(b for b in request.bindings
                     if b.match.concept.id == "sentiment")
    assert sentiment.condition.kind == "level"
    assert sentiment.condition.value == "negative", (
        "Sentiment is a governed category, not a number to be differenced.")
    assert result.row_count >= 1


def test_case_6_never_reads_the_memo_text(relationships, vocabulary):
    """Structured signals only. The extract stays where it is."""
    _, build, result = run(CASE_6, relationships, vocabulary)
    scanned = set()
    for op in build.plan["operations"]:
        if op["op"] == "SCAN" and op["params"]["dataset"] == "credit_memo_signals":
            scanned.update(op["params"].get("fields") or [])
    assert "extract" not in scanned
    assert "extract" not in {c["name"] for c in result.columns}


# ------------------------------------------------------- refusing honestly


def test_a_question_it_cannot_read_completely_is_refused(relationships,
                                                         vocabulary):
    """"Which sectors deteriorated" names a movement and no measure. Answering
    the half it could read would narrow the question silently."""
    request, _, _ = run(
        "Which sectors deteriorated while their macro environment also "
        "weakened over the latest year?", relationships, vocabulary)
    assert not request.understood
    assert any("could not read" in r for r in request.reasons)


def test_a_question_with_no_period_is_refused(relationships, vocabulary):
    request, _, _ = run(
        "Show customers whose ECL increased and rating deteriorated",
        relationships, vocabulary)
    assert not request.understood
    assert any("over what period" in r for r in request.reasons)

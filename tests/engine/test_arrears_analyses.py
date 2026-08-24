"""
Arrears and credit file signals.

The property that matters most for these two is that they cannot disagree with
the rest of the book. Arrears are derived from the same days-past-due figure the
facility snapshot carries, so an analyst who reads 90 days here and Stage 1
there has found a contradiction in the data rather than an insight — and the
fastest way to destroy confidence in a demonstration is to let it contradict
itself.

The second property is restraint: neither analysis may claim to predict
anything, because no predictive relationship has been established.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.engine.contracts import Certification
from backend.engine.functions.arrears import BUCKET_ORDER, DELINQUENT_BUCKETS
from backend.engine.helpers import DELINQUENCY, FACILITY, MEMOS
from backend.engine.registry import get_registry
from backend.engine.runner import run_analysis


@pytest.fixture(scope="module", autouse=True)
def require_data():
    available = get_data_source().datasets()
    missing = [d for d in (DELINQUENCY, MEMOS, FACILITY) if d not in available]
    if missing:
        pytest.skip(
            f"Analytical lake missing {', '.join(missing)} — run "
            "`python scripts/generate_saudi_universe.py`"
        )


@pytest.fixture(scope="module")
def arrears():
    return run_analysis("arrears_position", params={})


@pytest.fixture(scope="module")
def signals():
    return run_analysis("credit_file_signals", params={})


# -------------------------------------------------------------- the contracts


def test_both_analyses_are_registered_and_certified():
    registry = get_registry()
    for analysis_id in ("arrears_position", "credit_file_signals"):
        contract = registry.contract(analysis_id)
        assert contract.certification is Certification.CERTIFIED
        assert contract.trigger_questions, "a capability nobody can find is not one"
        assert contract.limitations, "a certified analysis must say what it is not"


def test_neither_analysis_claims_to_predict_anything():
    """No predictive relationship has been established, so none may be asserted.

    Checked as active claims rather than the word "forecast", because saying
    "this is not a forecast" is the behaviour wanted, not the behaviour banned.
    """
    registry = get_registry()
    banned = (
        "predicts", "will predict", "forecasts ", "predictive accuracy",
        "% accurate", "likelihood of default is", "expected to default",
    )
    for analysis_id in ("arrears_position", "credit_file_signals"):
        contract = registry.contract(analysis_id)
        text = " ".join([
            contract.description, contract.limitations,
            contract.calculation_description, contract.when_to_use,
        ]).lower()
        for claim in banned:
            assert claim not in text, f"{analysis_id} asserts prediction: {claim!r}"
        # And each says outright what it is not.
        assert "not a forecast" in contract.limitations.lower() or \
            "no predictive relationship" in contract.limitations.lower()


# ------------------------------------------------------------- arrears position


def test_arrears_buckets_account_for_every_facility_read(arrears):
    """A bucket split that drops rows understates the arrears."""
    counted = sum(int(row["facility_count"]) for row in arrears.result.rows)
    assert counted == arrears.result.input_row_count


def test_every_arrears_bucket_is_one_the_product_governs(arrears):
    for row in arrears.result.rows:
        assert row["dpd_bucket"] in BUCKET_ORDER


def test_arrears_buckets_are_reported_worsening_not_alphabetical(arrears):
    """Sorted by name, "1-29 days" lands after "180+ days" and reverses the story."""
    order = {label: i for i, label in enumerate(BUCKET_ORDER)}
    positions = [order[row["dpd_bucket"]] for row in arrears.result.rows]
    assert positions == sorted(positions)


def test_current_facilities_owe_nothing(arrears):
    for row in arrears.result.rows:
        if row["dpd_bucket"] == "Current":
            assert row["arrears_amount"] == 0
            assert row["exposure_at_risk"] == 0


def test_only_facilities_past_ninety_days_carry_exposure_at_risk(arrears):
    for row in arrears.result.rows:
        if row["dpd_bucket"] not in ("90-179 days", "180+ days"):
            assert row["exposure_at_risk"] == 0


def test_the_headline_arrears_count_matches_the_buckets(arrears):
    values = arrears.result.values
    from_buckets = sum(
        int(row["facility_count"]) for row in arrears.result.rows
        if row["dpd_bucket"] in DELINQUENT_BUCKETS
    )
    assert from_buckets == int(values["facilities_in_arrears"])


def test_the_arrears_rate_is_the_ratio_it_says_it_is(arrears):
    values = arrears.result.values
    expected = 100.0 * values["facilities_in_arrears"] / values["facilities_read"]
    assert values["arrears_rate_pct"] == pytest.approx(expected, abs=0.01)


def test_grouping_preserves_the_totals(arrears):
    """Breaking arrears down by sector may not change how much there is."""
    grouped = run_analysis("arrears_position", params={"group_by": "sector"})
    assert grouped.result.values["facilities_in_arrears"] == \
        arrears.result.values["facilities_in_arrears"]
    assert grouped.result.values["total_arrears_amount"] == pytest.approx(
        arrears.result.values["total_arrears_amount"], abs=0.01)

    counted = sum(int(row["facility_count"]) for row in grouped.result.rows)
    assert counted == grouped.result.input_row_count


def test_arrears_agree_with_the_facility_book(arrears):
    """The two datasets carry the same days past due, so the counts must match."""
    from backend.data_access.context import AnalysisContext

    period = arrears.result.values["period"]
    source = get_data_source()
    book = source.fetch(FACILITY, context=AnalysisContext(period=period),
                        fields=["account_id", "dpd_days"], period=period)
    behind_in_book = int((book["dpd_days"] > 0).sum())
    assert behind_in_book == int(arrears.result.values["facilities_in_arrears"])


def test_the_arrears_trace_records_where_the_figures_came_from(arrears):
    """A figure with no lineage is a figure nobody can check."""
    graph = arrears.graph.to_dict() if hasattr(arrears.graph, "to_dict") else arrears.graph
    nodes = graph["nodes"] if isinstance(graph, dict) else []
    assert len(nodes) > 3, "the trace should record more than a single step"

    rendered = str(nodes).lower()
    assert DELINQUENCY in rendered, "the trace must name the dataset it read"
    assert "aggregat" in rendered, "the trace must record the aggregation"


# ------------------------------------------------------- credit file signals


def test_a_signal_cannot_be_raised_more_often_than_notes_exist(signals):
    notes = int(signals.result.values["notes_written"])
    for row in signals.result.rows:
        assert row["mentions"] <= notes
        assert row["borrowers"] <= row["mentions"]


def test_signal_shares_are_the_ratio_they_say_they_are(signals):
    notes = signals.result.values["notes_written"]
    for row in signals.result.rows:
        assert row["share_of_notes_pct"] == pytest.approx(
            100.0 * row["mentions"] / notes, abs=0.01)


def test_the_sentiment_split_accounts_for_every_note(signals):
    values = signals.result.values
    total = values["negative_notes"] + values["mixed_notes"] + values["positive_notes"]
    assert total == values["notes_written"]


def test_signals_are_reported_most_raised_first(signals):
    mentions = [row["mentions"] for row in signals.result.rows]
    assert mentions == sorted(mentions, reverse=True)


def test_the_result_says_its_text_is_synthetic(signals):
    """A demonstration extract must never be mistakable for a real credit opinion."""
    assert "synthetic" in signals.result.meta["text_origin"].lower()
    assert "claim" in " ".join(signals.result.meta).lower() or \
        "claimed" in signals.result.meta["claims"].lower()

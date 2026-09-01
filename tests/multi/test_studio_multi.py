"""
Keeping a multi-dataset analysis as a method.

A composed analysis is a one-off by default. Saving one is how a bank turns
"somebody asked this in March" into something the team can run — but a saved
method that recorded only its SQL would break the day the bank supplies its own
IFRS 9 extract under a different column name, and would silently change meaning
the day a steward re-declared one of its joins.

These tests check that what is saved is enough to run the analysis again and to
notice when the ground has moved underneath it.
"""

from __future__ import annotations

import time

import pytest

from backend.orchestration import executor as orch
from backend.orchestration.vocabulary import get_vocabulary
from backend.studio import service
from tests.conftest import database_available

QUESTION = ("Show Real Estate customers whose ECL increased more than 20%, "
            "rating deteriorated at least two notches, and EAD did not decline "
            "over the latest year.")


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("needs the platform database")


@pytest.fixture(scope="module")
def saved():
    request = orch.multi_candidate(QUESTION, get_vocabulary())
    assert request is not None, "the worked example is a multi-dataset question"
    investigation = orch.run_multi(QUESTION, request, started=time.perf_counter())
    plan = investigation.steps[0].result["plan"]
    return service.from_dynamic(
        name="Deteriorating real estate customers", question=QUESTION,
        plan=plan, summary=request.summary, author="1")


def test_it_stores_concepts_rather_than_columns(saved):
    """The column a dataset happens to use is an answer, not a requirement."""
    concepts = {c["concept"] for c in saved.required_concepts}
    assert {"ecl", "rating", "ead"} <= concepts
    for entry in saved.required_concepts:
        assert entry["label"], "a concept with no label cannot be re-resolved"
        assert entry["dataset"] and entry["field"], (
            "the resolution on the day it was saved is recorded too")


def test_it_records_which_relationships_it_walks_and_at_which_version(saved):
    """A steward re-declaring one of these changes what the method means."""
    assert saved.required_relationships
    for entry in saved.required_relationships:
        assert entry["relationship_id"]
        assert entry["version"], "a relationship with no version cannot be diffed"
        assert entry["cardinality"]


def test_it_records_how_the_periods_were_aligned(saved):
    """Two methods with the same plan and different alignment answer different
    questions."""
    alignment = saved.period_alignment
    assert alignment["opening_period"] and alignment["closing_period"]
    asof = {entry["dataset"] for entry in alignment["as_of"]}
    assert "customer_ratings" in asof, (
        "the annual rating cycle is the as-of side of this analysis")
    assert "never after it" in alignment["description"]


def test_the_governed_fields_are_qualified_by_dataset(saved):
    """`ead` alone is ambiguous across three sources; `portfolio_facility.ead`
    is not."""
    assert all("." in field for field in saved.required_fields)
    assert "portfolio_facility.ead" in saved.required_fields


def test_it_declares_every_domain_it_reads(saved):
    """A method declaring only the facility domain would be offered for a
    question whose other sources have since been archived."""
    assert len(saved.required_domains) >= 3


def test_the_methodology_says_how_the_periods_were_aligned(saved):
    """The prose a reviewer reads has to carry it too, not only the metadata."""
    assert "Period alignment:" in saved.methodology
    assert "3 governed sources" in saved.methodology


def test_it_arrives_as_a_draft_with_no_tick(saved):
    """Running once against one pair of periods is not evidence."""
    from backend.studio.model import Lifecycle

    assert saved.lifecycle == Lifecycle.DRAFT
    assert not saved.is_certified
    assert not saved.test_cases
    can, gaps = saved.can_certify()
    assert can is False
    assert any("test cases" in gap for gap in gaps)


def test_what_it_stores_survives_a_round_trip(saved):
    """It is persisted as JSON, so anything that does not round-trip is lost."""
    from backend.studio.model import MethodDefinition

    again = MethodDefinition.from_dict(saved.to_dict())
    assert again.required_concepts == saved.required_concepts
    assert again.required_relationships == saved.required_relationships
    assert again.period_alignment == saved.period_alignment


def test_a_single_dataset_method_carries_none_of_it():
    """An empty relationship list is the honest answer for a plan with no join,
    not a field left unset by accident."""
    method = service.from_dynamic(
        name="Facility exposure", question="Show me EAD",
        plan={"operations": [{"id": "s", "op": "SCAN",
                              "params": {"dataset": "portfolio_facility",
                                         "period": "Q2 2026"}}],
              "meta": {"grain": "facility"}},
        summary="")
    assert method.required_relationships == []
    assert method.required_concepts == []
    assert method.period_alignment.get("description", "") == ""

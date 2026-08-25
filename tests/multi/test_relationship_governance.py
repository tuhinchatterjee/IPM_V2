"""
A relationship the runtime may join on has to earn it.

Composing joins from these rows turns each one from documentation into
something executable, so the governance is tested as governance: what may
reach ACTIVE, what a change to a live relationship does to history, and how the
planner behaves when a relationship is missing, archived, mis-declared or
poorly matched.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.models.platform import DatasetRelationship
from backend.runtime.joins import build_graph, resolve
from backend.services import relationships as rel
from backend.services.data_builder import DataBuilderError
from tests.conftest import database_available

FACILITY = "portfolio_facility"


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("PostgreSQL not reachable")


@pytest.fixture
def session():
    from backend.db.engine import get_session

    with get_session() as handle:
        yield handle


@pytest.fixture
def scratch(session):
    """A throwaway relationship, removed however the test ends."""
    record = rel.db.add_relationship(
        session, from_dataset="climate_risk", from_field="customer_id",
        to_dataset="borrower_financials", to_field="customer_id",
        cardinality=rel.ONE_TO_ONE, kind="key",
        description="A scratch relationship for the governance tests.")
    record.lifecycle = rel.DRAFT
    record.validated_at = None
    record.validation = {}
    session.flush()
    yield record
    session.delete(record)
    session.flush()


# ------------------------------------------------------------------ lifecycle


def test_a_draft_relationship_is_not_usable(session, scratch):
    usable = {r["id"] for r in rel.active_relationships(session)}
    assert scratch.id not in usable


def test_activation_needs_validation_first(session, scratch):
    """A join the runtime may compose has to be measured, not asserted."""
    with pytest.raises(DataBuilderError, match="has not been validated"):
        rel.promote(session, scratch.id, to=rel.ACTIVE)


def test_validation_measures_the_join_against_real_data(session, scratch):
    report = rel.validate_relationship(session, scratch)
    assert report["left_rows"] > 0
    assert report["right_rows"] > 0
    assert 0.0 <= report["match_rate"] <= 1.0
    assert scratch.validated_at is not None


def test_a_validated_relationship_can_be_activated(session, scratch):
    rel.validate_relationship(session, scratch)
    if scratch.validation.get("findings"):
        pytest.skip("the scratch relationship did not pass on this data")
    rel.promote(session, scratch.id, to=rel.ACTIVE)
    assert scratch.lifecycle == rel.ACTIVE
    assert scratch.id in {r["id"] for r in rel.active_relationships(session)}


def test_archiving_is_always_allowed(session, scratch):
    rel.promote(session, scratch.id, to=rel.ARCHIVED)
    assert scratch.lifecycle == rel.ARCHIVED
    assert scratch.id not in {r["id"] for r in rel.active_relationships(session)}


def test_a_low_confidence_relationship_never_reaches_the_planner(session,
                                                                 scratch):
    rel.validate_relationship(session, scratch)
    scratch.lifecycle = rel.ACTIVE
    scratch.confidence = 0.4
    session.flush()
    assert scratch.id not in {r["id"] for r in rel.active_relationships(session)}


# ------------------------------------------------------------- versioning


def test_a_change_records_what_the_relationship_was(session, scratch):
    """Without this, "why did this number change" has no answer that survives
    a governance edit."""
    before = scratch.version
    rel.bump_version(session, scratch, change_note="Cardinality corrected.")
    assert scratch.version == before + 1

    history = rel.versions(session, scratch.id)
    assert history[0]["version"] == before
    assert history[0]["change_note"] == "Cardinality corrected."
    assert history[0]["definition"]["cardinality"] == rel.ONE_TO_ONE


def test_promotion_is_itself_versioned(session, scratch):
    rel.validate_relationship(session, scratch)
    before = scratch.version
    rel.promote(session, scratch.id, to=rel.ARCHIVED, note="No longer used.")
    assert scratch.version == before + 1
    assert rel.versions(session, scratch.id)[0]["change_note"] == "No longer used."


def test_the_planner_records_the_version_it_used(session):
    """A Trace from March must describe the join that ran, not the one
    somebody redefined in June."""
    rows = rel.active_relationships(session)
    graph = build_graph(rows)
    resolution = resolve(graph, base=FACILITY, targets=["ifrs9_staging"])
    for edge in resolution.edges():
        assert edge.version >= 1
        assert edge.relationship_id


# ------------------------------------------------------- the shipped set


def test_the_shipped_relationships_are_active(session):
    rel.seed(session)
    active = {(r["from_dataset"], r["to_dataset"])
              for r in rel.active_relationships(session)}
    for shipped in rel.GOVERNED_RELATIONSHIPS[:6]:
        assert (shipped.from_dataset, shipped.to_dataset) in active


def test_seeding_is_idempotent(session):
    first = rel.seed(session)
    second = rel.seed(session)
    assert first["total"] == second["total"]
    assert not second["changed"]


def test_seeding_never_withdraws_a_stewards_relationship(session):
    record = rel.db.add_relationship(
        session, from_dataset="recoveries", from_field="customer_id",
        to_dataset="borrower_financials", to_field="customer_id",
        cardinality=rel.MANY_TO_ONE, kind="key",
        description="A steward's own join.")
    identifier = record.id
    rel.seed(session)
    assert session.get(DatasetRelationship, identifier) is not None
    session.delete(session.get(DatasetRelationship, identifier))
    session.flush()


# ------------------------------------------------- how the planner fails


def test_a_missing_relationship_refuses_rather_than_guessing():
    graph = build_graph([])
    resolution = resolve(graph, base=FACILITY, targets=["ifrs9_staging"])
    assert not resolution.ok
    assert "Declare one in Data Builder" in resolution.unreachable["ifrs9_staging"]


def test_an_archived_relationship_is_absent_from_the_graph(session, scratch):
    rel.validate_relationship(session, scratch)
    scratch.lifecycle = rel.ARCHIVED
    session.flush()
    graph = build_graph(rel.active_relationships(session))
    resolution = resolve(graph, base="climate_risk",
                         targets=["borrower_financials"], max_hops=1)
    assert not resolution.ok


def test_a_mis_declared_cardinality_is_caught_by_validation(session):
    """Declared one-to-one, but the right side has duplicate keys. The join
    would multiply the book while the declaration says it cannot."""
    record = rel.db.add_relationship(
        session, from_dataset="portfolio_facility", from_field="customer_id",
        to_dataset="covenant_tests", to_field="customer_id",
        cardinality=rel.ONE_TO_ONE, kind="key",
        description="Deliberately mis-declared.")
    try:
        report = rel.validate_relationship(session, record)
        assert not report["ok"]
        assert any("not unique" in f for f in report["findings"])
        with pytest.raises(DataBuilderError, match="Validation found"):
            rel.promote(session, record.id, to=rel.ACTIVE)
    finally:
        session.delete(record)
        session.flush()


def test_a_relationship_on_a_field_that_does_not_exist_is_refused(session):
    record = rel.db.add_relationship(
        session, from_dataset="portfolio_facility", from_field="not_a_field",
        to_dataset="ifrs9_staging", to_field="account_id",
        cardinality=rel.ONE_TO_ONE, kind="key", description="Broken.")
    try:
        report = rel.validate_relationship(session, record)
        assert not report["ok"]
        assert any("not a field" in f for f in report["findings"])
    finally:
        session.delete(record)
        session.flush()


def test_a_poorly_matched_relationship_cannot_be_activated(session):
    """A join that loses most of the book is a filter nobody asked for."""
    record = rel.db.add_relationship(
        session, from_dataset="portfolio_facility", from_field="account_id",
        to_dataset="borrower_financials", to_field="customer_id",
        cardinality=rel.MANY_TO_ONE, kind="key",
        description="Keys that do not correspond.")
    try:
        report = rel.validate_relationship(session, record)
        assert not report["ok"]
        assert report["match_rate"] < rel.MIN_MATCH_RATE
        with pytest.raises(DataBuilderError):
            rel.promote(session, record.id, to=rel.ACTIVE)
    finally:
        session.delete(record)
        session.flush()


def test_the_graph_exposes_its_thresholds(session):
    graph = rel.graph(session)
    assert graph["thresholds"]["min_match_rate"] == rel.MIN_MATCH_RATE
    assert graph["active_count"] >= 1
    assert all("lifecycle" in edge for edge in graph["edges"])


def test_every_shipped_relationship_states_what_it_means():
    for shipped in rel.GOVERNED_RELATIONSHIPS:
        assert shipped.semantic.strip(), (
            f"{shipped.from_dataset} -> {shipped.to_dataset} says which "
            "columns it matches on but not what the join MEANS")


def test_relationships_are_stored_once(session):
    rows = session.scalars(select(DatasetRelationship)).all()
    keys = [(r.from_dataset, r.from_field, r.to_dataset, r.to_field)
            for r in rows]
    assert len(keys) == len(set(keys))

"""
Proposing a relationship, and preferring the bank's own data.

Two things a bank does after the demonstration book: it onboards its own
extracts, and it needs the joins between them declared. Neither is something
the product may do on the bank's behalf — but leaving a steward to find every
join by reading column names is how a relationship model stays half-declared.

So the assistant measures and proposes; the steward decides. And once a bank
HAS declared its own dataset authoritative, the planner must stop reaching for
the demonstration source, because a correct calculation over the wrong
company's portfolio is worse than a refusal: it looks right.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from backend.orchestration import concepts
from backend.services import relationships as rel
from tests.conftest import database_available


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("needs the platform database")


@pytest.fixture
def session():
    from backend.db.engine import SessionLocal

    handle = SessionLocal()
    try:
        yield handle
    finally:
        handle.rollback()
        handle.close()


# ------------------------------------------------------------- the assistant


def test_a_proposal_is_measured_not_asserted(session):
    found = rel.propose(session, "covenant_tests")
    assert found, "covenant_tests shares keys with several governed datasets"
    for candidate in found:
        assert 0.0 <= candidate["match_rate"] <= 1.0
        assert candidate["left_rows"] > 0 and candidate["right_rows"] > 0
        assert candidate["cardinality"] in rel.CARDINALITIES


def test_it_never_proposes_a_column_that_means_nothing(session):
    """Joining two datasets on `period` is a cartesian product per period."""
    for candidate in rel.propose(session, "covenant_tests"):
        assert candidate["from_field"] not in rel.NEVER_A_KEY


def test_it_only_proposes_columns_shaped_like_a_key(session):
    for candidate in rel.propose(session, "covenant_tests"):
        assert rel._could_be_a_key(candidate["from_field"])


def test_low_coverage_is_dropped_rather_than_shown_with_a_bad_number(session):
    for candidate in rel.propose(session, "covenant_tests"):
        assert candidate["match_rate"] >= rel.MIN_PROPOSAL_COVERAGE


def test_it_does_not_propose_a_join_already_declared(session):
    """In either direction and whatever its lifecycle."""
    from sqlalchemy import select

    from backend.models.platform import DatasetRelationship

    declared = {
        (r.from_dataset, r.from_field, r.to_dataset, r.to_field)
        for r in session.scalars(select(DatasetRelationship)).all()
    }
    for candidate in rel.propose(session, "portfolio_facility"):
        key = (candidate["from_dataset"], candidate["from_field"],
               candidate["to_dataset"], candidate["to_field"])
        assert key not in declared


def test_a_multiplying_candidate_says_so_rather_than_being_hidden(session):
    """Hiding it would leave a steward to discover it by doubling a book."""
    found = rel.propose(session, "covenant_tests")
    unsafe = [c for c in found if not c["safe_to_join"]]
    if not unsafe:
        pytest.skip("no multiplying candidate in this data")
    for candidate in unsafe:
        assert "would multiply" in candidate["why"]


def test_accepting_a_proposal_creates_a_draft_not_a_runnable_join(session):
    """The assistant found a column that lines up; a steward decided the two
    columns mean the same thing. Only the second is grounds for joining."""
    found = rel.propose(session, "covenant_tests")
    assert found
    candidate = found[0]
    record = rel.accept_proposal(
        session,
        from_dataset=candidate["from_dataset"], from_field=candidate["from_field"],
        to_dataset=candidate["to_dataset"], to_field=candidate["to_field"],
        cardinality=candidate["cardinality"],
        semantic="Every covenant test belongs to the customer it was set for.")
    assert record.lifecycle == rel.DRAFT
    assert record.lifecycle not in rel.RUNNABLE
    assert record.semantic


def test_an_accepted_proposal_records_where_it_came_from(session):
    found = rel.propose(session, "covenant_tests")
    candidate = found[0]
    record = rel.accept_proposal(
        session,
        from_dataset=candidate["from_dataset"], from_field=candidate["from_field"],
        to_dataset=candidate["to_dataset"], to_field=candidate["to_field"],
        cardinality=candidate["cardinality"])
    history = rel.versions(session, record.id)
    assert history
    assert "relationship assistant" in history[0]["change_note"]


def test_a_dataset_outside_the_catalogue_is_refused(session):
    from backend.services.data_builder import DataBuilderError

    with pytest.raises(DataBuilderError):
        rel.propose(session, "no_such_dataset")


# ------------------------------------------- the bank's own data comes first


@dataclass(frozen=True)
class _Stub:
    name: str
    origin: str
    authoritative_for: tuple[str, ...] = ()
    domain: str = "Client Portfolio"


@dataclass
class _Catalogue:
    """Just enough catalogue to answer "whose data is this, and is it
    authoritative" — the two questions the resolution turns on."""

    entries: dict[str, _Stub] = field(default_factory=dict)

    def dataset(self, name: str) -> _Stub:
        return self.entries[name]


def _concept_with(default_dataset: str, rival_dataset: str) -> concepts.Concept:
    """One concept carried by two governed datasets, one of them the default."""
    return concepts.Concept(
        id="ead", label="exposure at default", pattern=r"\bead\b",
        candidates=(
            concepts.Candidate(dataset=default_dataset, field="ead",
                               definition="The demonstration book's figure.",
                               is_default=True),
            concepts.Candidate(dataset=rival_dataset, field="ead",
                               definition="The bank's own figure."),
        ))


KNOWN = {"demo_book": {"ead"}, "client_book": {"ead"}}


def test_the_planner_prefers_the_banks_own_authoritative_data():
    """The default encodes which figure a credit officer usually means. It
    cannot know this bank has since onboarded its own source for it."""
    catalogue = _Catalogue({
        "demo_book": _Stub("demo_book", "demo", ("exposure",)),
        "client_book": _Stub("client_book", "client", ("exposure",)),
    })
    match = concepts.resolve_concept(
        _concept_with("demo_book", "client_book"), "show me EAD",
        known=KNOWN, catalogue=catalogue)
    assert match is not None
    assert match.dataset == "client_book"
    assert "the bank's own data" in match.reason
    assert "demo_book" in match.reason, (
        "the source that was NOT used has to be named, or the choice is silent")


def test_client_data_that_nobody_declared_authoritative_does_not_win():
    """Onboarding a dataset is not the same as making it the source of truth.
    That decision belongs to a steward."""
    catalogue = _Catalogue({
        "demo_book": _Stub("demo_book", "demo", ("exposure",)),
        "client_book": _Stub("client_book", "client", ()),
    })
    match = concepts.resolve_concept(
        _concept_with("demo_book", "client_book"), "show me EAD",
        known=KNOWN, catalogue=catalogue)
    assert match is not None
    assert match.dataset == "demo_book"


def test_two_authoritative_client_sources_are_not_resolved_silently():
    """A tie between two of the bank's own sources is a governance question for
    a steward, not one the planner should settle on its own."""
    catalogue = _Catalogue({
        "demo_book": _Stub("demo_book", "client", ("exposure",)),
        "client_book": _Stub("client_book", "client", ("exposure",)),
    })
    match = concepts.resolve_concept(
        _concept_with("demo_book", "client_book"), "show me EAD",
        known=KNOWN, catalogue=catalogue)
    assert match is not None
    assert match.dataset == "demo_book", (
        "with no single client authority the declared default stands")


def test_an_explicit_qualifier_still_beats_everything():
    """A question that names which figure it means is not ambiguous, whoever
    owns the data."""
    concept = concepts.Concept(
        id="ead", label="exposure at default", pattern=r"\bead\b",
        candidates=(
            concepts.Candidate(dataset="demo_book", field="ead",
                               definition="Demo.", qualifiers=("regulatory",),
                               is_default=True),
            concepts.Candidate(dataset="client_book", field="ead",
                               definition="The bank's own."),
        ))
    catalogue = _Catalogue({
        "demo_book": _Stub("demo_book", "demo", ("exposure",)),
        "client_book": _Stub("client_book", "client", ("exposure",)),
    })
    match = concepts.resolve_concept(
        concept, "show me regulatory EAD", known=KNOWN, catalogue=catalogue)
    assert match is not None
    assert match.dataset == "demo_book"

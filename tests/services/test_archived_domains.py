"""
An archived domain leaves engine resolution — and nothing else.

The decision this encodes: archiving a data domain retires it from the live
estate, so the engine stops reaching for its datasets on its own. An analysis
quietly going on reading a book the data office has withdrawn, and somebody
finding out nine months later, is exactly the audit finding this product exists
to prevent.

Archiving is NOT deletion. The rows stay on disk, the viewer still serves them
to anybody authorised to look, and restoring the domain puts it straight back.
Both halves are asserted here, because a change that only did the first half
would be indistinguishable from data loss.
"""

from __future__ import annotations

import pytest

from backend.data_access import authority
from backend.data_access.catalog import FACILITY_POSITION, get_catalog
from backend.services import data_builder as db
from tests.conftest import database_available


@pytest.fixture()
def resolving_against(monkeypatch):
    """Pretend a given set of domains is archived, for one test."""

    def use(*names: str):
        monkeypatch.setattr(
            authority, "_archived_domains_provider", lambda: frozenset(names)
        )

    return use


@pytest.fixture(scope="module")
def facility_domain() -> str:
    """The domain holding whatever currently answers the facility position."""
    for dataset in get_catalog().serving(FACILITY_POSITION):
        return dataset.domain
    pytest.skip("nothing is authoritative for the facility position")


# ------------------------------------------------------- engine resolution


def test_nothing_is_archived_when_nobody_can_say():
    """A script or a test with no governance record sees an empty set."""
    installed = authority._archived_domains_provider
    try:
        authority.set_archived_domains_provider(None)
        assert authority.archived_domains() == frozenset()
    finally:
        # Restored: this is module-level state, and leaving it cleared would
        # quietly disable the filter for every test that runs after this one.
        authority.set_archived_domains_provider(installed)


def test_a_failing_provider_fails_open(monkeypatch):
    """A database hiccup must not report the whole estate as retired."""

    def explode() -> frozenset[str]:
        raise RuntimeError("the governance database is unreachable")

    monkeypatch.setattr(authority, "_archived_domains_provider", explode)
    assert authority.archived_domains() == frozenset()


def test_a_live_domain_resolves(resolving_against, facility_domain):
    resolving_against()
    resolution = authority.resolve_purpose(FACILITY_POSITION)
    assert resolution.dataset
    assert resolution.domain == facility_domain


def test_an_archived_domain_stops_being_resolved(resolving_against, facility_domain):
    resolving_against(facility_domain)
    with pytest.raises(authority.GovernedDataUnavailable):
        authority.resolve_purpose(FACILITY_POSITION)


def test_the_refusal_says_the_domain_was_archived(resolving_against, facility_domain):
    """"Nothing is authoritative" would send a steward hunting for a dataset
    that is sitting right there."""
    resolving_against(facility_domain)
    with pytest.raises(authority.GovernedDataUnavailable) as raised:
        authority.resolve_purpose(FACILITY_POSITION)
    message = str(raised.value)
    assert "archived domain" in message
    assert facility_domain in message
    assert "Restore the domain" in message


def test_archiving_an_unrelated_domain_changes_nothing(resolving_against):
    resolving_against("Some Domain Nobody Uses")
    assert authority.resolve_purpose(FACILITY_POSITION).dataset


def test_restoring_a_domain_puts_it_back(resolving_against, facility_domain):
    resolving_against(facility_domain)
    with pytest.raises(authority.GovernedDataUnavailable):
        authority.resolve_purpose(FACILITY_POSITION)

    resolving_against()  # restored
    assert authority.resolve_purpose(FACILITY_POSITION).domain == facility_domain


# ------------------------------------------------- archiving is not deleting


def test_an_archived_domains_data_is_still_readable(resolving_against, facility_domain):
    """The viewer serves it to anybody authorised. Only the ENGINE stops."""
    dataset = get_catalog().serving(FACILITY_POSITION)[0].name
    resolving_against(facility_domain)

    page = db.browse_dataset(dataset, limit=3)
    assert page["rows"], "archiving a domain must not hide its rows"
    assert page["total_rows"] > 0


def test_an_archived_domain_can_still_be_profiled(resolving_against, facility_domain):
    dataset = get_catalog().serving(FACILITY_POSITION)[0].name
    resolving_against(facility_domain)
    profile = db.column_profile(dataset, "ead")
    assert profile["rows"] > 0


# --------------------------------------------------------- the stored status


@pytest.mark.skipif(not database_available(), reason="Domain status needs PostgreSQL")
def test_the_status_round_trips_through_the_database():
    from backend.db.engine import get_session

    with get_session() as session:
        domains = db.list_domains(session)
        if not domains:
            pytest.skip("no domains defined")
        name = domains[0].name
        was = domains[0].status

        try:
            db.set_domain_status(session, name, "ARCHIVED")
            session.commit()
            assert name in db.archived_domain_names(session)

            db.set_domain_status(session, name, "ACTIVE")
            session.commit()
            assert name not in db.archived_domain_names(session)
        finally:
            db.set_domain_status(session, name, was)
            session.commit()


@pytest.mark.skipif(not database_available(), reason="Domain status needs PostgreSQL")
def test_changing_the_status_clears_the_cache_the_engine_reads():
    """Otherwise the decision would take effect at the next restart."""
    from backend.db.engine import get_session
    from backend.services import domain_status

    with get_session() as session:
        domains = db.list_domains(session)
        if not domains:
            pytest.skip("no domains defined")
        name, was = domains[0].name, domains[0].status

        try:
            domain_status.forget()
            assert name not in domain_status.archived_domains()

            db.set_domain_status(session, name, "ARCHIVED")
            session.commit()
            assert name in domain_status.archived_domains(), (
                "the engine is still holding the pre-archive answer"
            )
        finally:
            db.set_domain_status(session, name, was)
            session.commit()
            domain_status.forget()


def test_an_unknown_status_is_refused():
    from backend.db.engine import get_session

    if not database_available():
        pytest.skip("needs PostgreSQL")
    with get_session() as session:
        domains = db.list_domains(session)
        if not domains:
            pytest.skip("no domains defined")
        with pytest.raises(db.DataBuilderError, match="not a domain status"):
            db.set_domain_status(session, domains[0].name, "DELETED")

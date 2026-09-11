"""
Who may read a saved What-If, proved against the store rather than assumed.

Revision 3 §4 asks that one user cannot reach another user's saved scenarios,
and that this is checked rather than inferred from the presence of an owner
column. A saved retail run carries the population it ran over and the figures it
reached: returning somebody else's row would leak the book, not just a name.

These gates run against the real store and the real table, on rows they create
themselves and delete afterwards. Nothing pre-existing is read, written or
removed, and the two owners are synthetic ids that belong to no account.

There is no new tenancy architecture here and none is wanted. The scoping
already exists; what did not exist was a test that would notice if a future
edit dropped one of the five `created_by` filters.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from backend.config import settings  # noqa: E402

pytestmark = pytest.mark.skipif(
    not settings.has_database,
    reason="the saved-scenario store needs DATABASE_URL")

#: Two disposable accounts, created by this module and removed afterwards.
#:
#: Synthetic ids do not work: `stress_scenarios.created_by` is a foreign key to
#: `users`, so an id that belongs to nobody is refused by the database before
#: the ownership rule is ever reached. Reusing the seeded demonstration users
#: would make a failure read as a missing user rather than as a boundary that
#: stopped holding, so the gate brings its own.
BOUNDARY_USERS = ("ret.boundary.mine", "ret.boundary.theirs")

RUN = {
    "scenario": {"run_id": "WIF-ownership-gate", "name": "ownership gate",
                 "dataset_version": "test", "snapshot_date": "2026-08-31",
                 "filters": {"product_code": "PERSONAL_LOAN"},
                 "shocks": {"pd_relative": 0.2}, "staging_mode": "frozen_stage",
                 "scenario_weights": None,
                 "methodology_version": "retail-whatif-1.0.0"},
    "baseline": {"ecl_final_sar": 1000.0, "facilities": 7, "customers": 5},
    "scenario_result": {"ecl_final_sar": 1100.0},
    "delta": {"ecl_final_sar": 100.0, "ecl_final_pct": 0.1},
}


@pytest.fixture(scope="module")
def owners():
    """Two disposable accounts, removed however the module ends."""
    from backend.db.engine import get_session
    from backend.db.models import User

    ids: list[int] = []
    with get_session() as session:
        for username in BOUNDARY_USERS:
            found = session.query(User).filter(User.username == username).first()
            if found is None:
                found = User(
                    username=username, email=f"{username}@invalid.test",
                    first_name="Ownership", last_name="Boundary Gate",
                    team="Test", job_title="Test fixture", department="Test",
                    # Never signable-in: the hash is not a hash of anything,
                    # and the account is inactive from the moment it exists.
                    password_hash="!", role="analyst", is_active=False)
                session.add(found)
                session.flush()
            ids.append(found.id)
        session.commit()
    yield tuple(ids)
    with get_session() as session:
        for username in BOUNDARY_USERS:
            found = session.query(User).filter(User.username == username).first()
            if found is not None:
                session.delete(found)
        session.commit()


@pytest.fixture()
def two_saved_runs(owners):
    """One run owned by each account, removed however the test ends."""
    from backend.retail import whatif_store as store

    mine_id, theirs_id = owners
    mine = store.save(name="ownership gate — mine", question="q", month="2026-08",
                      run=RUN, owner=mine_id)
    theirs = store.save(name="ownership gate — theirs", question="q",
                        month="2026-08", run=RUN, owner=theirs_id)
    try:
        yield mine, theirs
    finally:
        for row, owner in ((mine, mine_id), (theirs, theirs_id)):
            try:
                store.delete(row.id, owner=owner)
            except Exception:  # noqa: BLE001 - cleanup must not mask a failure
                pass


class TestASavedWhatIfBelongsToWhoeverSavedIt:
    def test_a_listing_shows_only_your_own(self, two_saved_runs, owners):
        from backend.retail import whatif_store as store

        mine, theirs = two_saved_runs
        ids = {row.id for row in store.listing(owner=owners[0], limit=100)}
        assert mine.id in ids
        assert theirs.id not in ids

    def test_reopening_somebody_else_s_run_is_refused(self, two_saved_runs, owners):
        from backend.retail import whatif_store as store

        _, theirs = two_saved_runs
        with pytest.raises(Exception):
            store.get(theirs.id, owner=owners[0])

    def test_deleting_somebody_else_s_run_is_refused_and_leaves_it_intact(
            self, two_saved_runs, owners):
        from backend.retail import whatif_store as store

        _, theirs = two_saved_runs
        with pytest.raises(Exception):
            store.delete(theirs.id, owner=owners[0])
        # Still there, and still theirs.
        assert store.get(theirs.id, owner=owners[1]).id == theirs.id

    def test_an_unauthenticated_owner_reaches_nothing(self, two_saved_runs):
        """`_owner_of` returns None when there is no principal."""
        from backend.retail import whatif_store as store

        mine, theirs = two_saved_runs
        ids = {row.id for row in store.listing(owner=None, limit=100)}
        assert mine.id not in ids
        assert theirs.id not in ids

    def test_the_owner_filter_is_on_every_read_and_write(self):
        """What would break if a future edit dropped one."""
        import inspect

        from backend.retail import whatif_store as store

        for name in ("listing", "get", "delete"):
            source = inspect.getsource(getattr(store, name))
            assert "created_by" in source, f"{name} does not scope by owner"
        assert "created_by=owner" in inspect.getsource(store.save)


class TestTheRoutesScopeEveryReadAndWriteToTheCaller:
    @pytest.mark.parametrize("route", [
        "whatif_landing", "whatif_save", "whatif_saved", "whatif_reopen",
        "whatif_delete", "whatif_export", "whatif_compare"])
    def test_the_route_passes_the_caller_to_the_store(self, route: str):
        import inspect

        from backend.api.routers import retail as router

        handler = getattr(router, route, None)
        assert handler is not None, f"{route} is not a route on the retail router"
        source = inspect.getsource(handler)
        assert "_owner_of(principal)" in source or "owner=owner" in source, (
            f"{route} reads or writes saved runs without scoping to the caller")

    def test_every_retail_route_is_closed_by_the_router_itself(self):
        """Not route by route: one dependency on the router.

        Four routes — portfolio, customers, customer and early-warning — carry
        no principal parameter of their own, and reading the handlers alone
        would call them open. They are not: the router is declared with
        `dependencies=[RequireCommenter]`, so the check runs before any handler
        does. Asserting the router-level dependency is asserting the mechanism
        that actually closes them; a future edit that drops it opens twenty
        routes at once and this is what would notice.
        """
        from backend.api.routers import retail as router

        assert router.router.dependencies, (
            "the retail router declares no dependencies: every route under it "
            "is open")

    @pytest.mark.parametrize("route", [
        "whatif_save", "whatif_delete", "whatif_ask", "whatif_run",
        "whatif_cutoff"])
    def test_a_write_or_run_route_requires_more_than_read_access(self, route: str):
        """Reading the book is Commenter; running and writing is Analyst.

        Reopen and export are deliberately not in this list: both are reads of
        a run the caller already owns, scoped by `created_by`, and requiring
        Analyst to re-read your own saved work would be a permission rule that
        protects nothing.
        """
        import inspect

        from backend.api.routers import retail as router

        handler = getattr(router, route, None)
        if handler is None:
            pytest.skip(f"{route} is not a route on this build")
        source = inspect.getsource(handler)
        assert "RequireAnalyst" in source, (
            f"{route} runs or writes at the router's read-only level")

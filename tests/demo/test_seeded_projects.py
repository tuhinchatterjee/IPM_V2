"""Twenty-four Projects, and the leak that produced three thousand.

Part 4. The Projects list held 3,311 rows with SIX distinct names between
them — 2,973 of them one repeated fixture called "Contracting concentration
review" — alongside 5,985 Investigations, 868 of which had no message at all.
The product's own `demo.workspace.residue()` check names every one of those as
a FAIL, and it was failing on eight counts.

Two separate things are held here.

The leak
--------
`tests/api/test_hierarchy_api.py` creates Projects and Investigations in
fixtures and in a couple of dozen inline POSTs, against a real database, and
cleaned up none of it. Its Project fixture is function-scoped, so every test
that asked for one left another behind. That is not a problem that stays in
the tests: it is what the product's Projects list showed a reader.

The content
-----------
What should be there instead: twenty-four standing reviews, each named for the
credit question it exists to answer, each carrying threads whose answers are
REAL runs of registered analyses. A seeded workspace whose conversations were
composed rather than computed teaches a reader to distrust the ones that were
not, and there is no way to tell them apart by looking.
"""

from __future__ import annotations

import pytest

from backend.demo import workspace as ws
from scripts import seed_projects as sp


@pytest.fixture
def session():
    from backend.config import settings

    if not settings.has_database:
        pytest.skip("no database")
    from backend.db.engine import get_session

    with get_session() as opened:
        yield opened


class TestTheSeededWorkspace:

    def test_there_are_twenty_four_of_them(self) -> None:
        assert len(sp.PROJECTS) == 24

    def test_no_two_projects_share_a_name(self) -> None:
        # The whole shape of the defect: 3,311 rows, six names. A duplicate
        # name here would put the product back on the road to it.
        names = [one["name"] for one in sp.PROJECTS]
        assert len(set(names)) == len(names)

    def test_none_of_them_is_called_a_demonstration(self) -> None:
        # "Demo Project" on a screen tells a client the product has never been
        # used for anything.
        for one in sp.PROJECTS:
            lowered = one["name"].lower()
            for word in ("demo", "test", "sample", "example", "fixture"):
                assert word not in lowered, f"{one['name']!r} contains {word!r}"

    def test_every_project_carries_threads(self) -> None:
        for one in sp.PROJECTS:
            assert one["threads"], f"{one['name']} has no thread"

    def test_every_thread_names_a_registered_analysis(self) -> None:
        from backend.engine.registry import get_registry

        runnable = {a.contract.id for a in get_registry().runnable()}
        for one in sp.PROJECTS:
            for question, analysis_id, _params in one["threads"]:
                assert analysis_id in runnable, (
                    f"{one['name']} asks {question!r} of {analysis_id}, which "
                    "is not a runnable analysis, so the thread could carry no "
                    "computed answer")

    def test_every_thread_parameter_is_one_the_contract_accepts(self) -> None:
        from backend.engine.registry import get_registry

        registry = get_registry()
        for one in sp.PROJECTS:
            for _question, analysis_id, params in one["threads"]:
                accepted = {p.name
                            for p in registry.contract(analysis_id).parameters}
                assert set(params) <= accepted, (
                    f"{analysis_id} does not accept {sorted(set(params) - accepted)}")


class TestTheAnswerSaysOnlyWhatWasComputed:

    def test_an_empty_result_is_not_dressed_up(self) -> None:
        class Result:
            def to_dict(self):
                return {"rows": [], "values": {}, "input_row_count": 0}

        said = sp._states(Result())
        assert "no rows" in said

    def test_it_prefers_the_analysis_own_statement(self) -> None:
        class Result:
            def to_dict(self):
                return {"rows": [], "input_row_count": 5,
                        "values": {"statement": "No facility is utilised "
                                                "above 90%."}}

        assert sp._states(Result()) == "No facility is utilised above 90%."

    def test_it_reports_the_counts_it_was_given_and_no_others(self) -> None:
        class Result:
            def to_dict(self):
                return {"rows": [{}, {}, {}], "input_row_count": 1200,
                        "values": {"period": "2026Q2"}}

        said = sp._states(Result())
        assert "3 row(s)" in said and "2026Q2" in said and "1,200" in said


class TestTheLeakIsClosed:

    def test_the_hierarchy_tests_sweep_up_after_themselves(self) -> None:
        import inspect

        from tests.api import test_hierarchy_api as suite

        source = inspect.getsource(suite)
        assert "_leave_nothing_behind" in source
        assert 'scope="module", autouse=True' in source
        # Deliberately id-based: the demo workspace seeds a Project with the
        # same name as the fixture, and deleting by name would take it too.
        assert "before_projects" in source and "before_threads" in source

    def test_no_project_or_lens_residue_is_left(self, session) -> None:
        # Projects, Investigations and Lenses are what the sweeper owns, and
        # none of them may accumulate. Test ACCOUNTS are excluded
        # here on purpose: `users` is referenced by half a dozen tables the
        # sweeper does not own, so removing them from a test teardown raises a
        # foreign-key violation that takes the Projects down with it.
        # `demo.workspace.reset(include_users=True)` is the governed tool for
        # accounts, and it empties the referencing tables first.
        found = [one for one in ws.residue(session)
                 if "test account" not in one]
        assert found == [], (
            "the product's own residue check is failing on something a "
            f"client would see: {found}")

    def test_no_seeded_investigation_is_left_without_a_message(
            self, session) -> None:
        from backend.models.platform import (
            Investigation,
            InvestigationMessage,
            Project,
        )

        # Scoped to the SEEDED workspace, which is what Part 4 guarantees.
        # Asserted globally it also caught rows other test modules create
        # during the same session and sweep in their own teardown, and rows
        # the route crawl seeds to resolve its dynamic ids — neither of which
        # this is about. A seeded thread that opens onto an empty
        # conversation still fails here, which is the defect being held.
        seeded = {p.id for p in session.query(Project).all()
                  if (p.default_context or {}).get(sp.SEED_KEY) == sp.SEED_VALUE}
        if not seeded:
            pytest.skip("the seeded workspace is not present")
        threads = {t.id for t in session.query(Investigation).all()
                   if t.project_id in seeded}
        spoken = {m.investigation_id
                  for m in session.query(
                      InvestigationMessage.investigation_id).all()}
        silent = threads - spoken
        assert threads, "the seeded projects carry no threads at all"
        assert not silent, (
            f"{len(silent)} seeded Investigation(s) carry no message at all; "
            "each one opens onto an empty conversation")

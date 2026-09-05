"""Every surface answers "what data is there?" with the same number. §12.

Three surfaces used to disagree on one deployment:

    Data Builder screen        45 domains
    the analyst's own tool      5 domains
    the business domain map     7 domains

Each was reading something true — rows in a table, the file catalogue grouped
by whatever domain a dataset names, and the map itself. None was reading the
same thing. These tests fail if a fourth reader appears, or if one of the
three quietly grows its own copy again.
"""

from __future__ import annotations

import pytest

from backend import metadata as md
from backend.analyst import tools
from backend.analyst.safety import Principal
from tests.conftest import database_available

db = pytest.mark.skipif(not database_available(),
                        reason="needs the platform database")


@pytest.fixture(autouse=True)
def _fresh_catalogue():
    md.invalidate()
    yield
    md.invalidate()


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-IPM-Role": "ADMIN", "X-IPM-User-Id": "1"}


def _admin() -> Principal:
    return Principal(user_id=1, role="ADMIN", datasets=frozenset())


class TestOneAuthority:
    def test_the_service_places_every_governed_dataset(self):
        """No dataset falls out of the map.

        Twelve did: the catalogue was renamed to the business headings and the
        map went on looking only for the generator's older spellings, so
        `ifrs9_staging` — sitting in a catalogue domain literally called
        "IFRS 9 / ECL" — came back Unmapped and vanished from the screen.
        """
        placed = {name for heading in md.domains() for name in heading.datasets}
        assert placed == {d.name for d in md.datasets()}
        assert md.UNPLACED not in {h.name for h in md.domains()}

    def test_the_counts_add_up_within_the_service(self):
        counts = md.counts()
        assert counts["domains"] == len(md.domains())
        assert counts["datasets"] == len(md.datasets())
        assert counts["datasets"] == sum(h.dataset_count for h in md.domains())
        assert counts["rows"] == sum(h.row_count for h in md.domains())
        assert counts["fields"] == sum(h.field_count for h in md.domains())

    def test_a_heading_with_nothing_in_it_still_exists(self):
        """"No documents loaded" and "documents not supported" differ.

        Grouping the catalogue by the domain each dataset names cannot express
        the first, which is why the analyst tool said 5 where the screen said
        7.
        """
        assert any(not h.installed for h in md.domains())
        assert md.counts()["domains"] > md.counts()["domains_installed"]


class TestTheSurfacesAgree:
    def test_the_analyst_tool_and_the_service_agree(self):
        rows = tools.list_data_domains(_admin()).rows
        assert len(rows) == md.counts()["domains"]
        assert sum(r["datasets"] for r in rows) == md.counts()["datasets"]
        assert sum(r["rows_published"] for r in rows) == md.counts()["rows"]
        assert [r["domain"] for r in rows] == [h.name for h in md.domains()]

    @db
    def test_the_data_builder_screen_and_the_service_agree(self):
        from backend.db.engine import get_session
        from backend.services import data_builder as builder

        with get_session() as session:
            overview = builder.domain_overview(session)
        assert len(overview) == md.counts()["domains"]
        assert sum(d["dataset_count"] for d in overview) == md.counts()["datasets"]
        assert sum(d["row_count"] for d in overview) == md.counts()["rows"]
        assert [d["name"] for d in overview] == [h.name for h in md.domains()]

    @db
    def test_the_api_and_the_service_agree(self, client, admin_headers):
        summary = client.get("/api/v1/metadata/summary",
                             headers=admin_headers).json()
        assert summary["counts"] == md.counts()

        domains = client.get("/api/v1/metadata/domains",
                             headers=admin_headers).json()
        assert domains["count"] == md.counts()["domains"]

    def test_the_user_facing_answer_and_the_service_agree(self):
        """The sentence a person reads quotes the same numbers. §12.

        "The same numbers" became audience-relative when the scorecard
        validation boundary arrived: the Data Builder is entitled to all
        eighty governed datasets and the general Cockpit is not entitled to
        the seven behind that boundary. So the sentence must quote the
        service's numbers MINUS the restricted set — not the service's raw
        totals, which would mean the boundary had failed, and not whatever
        the answer happens to say, which would assert nothing.

        The expectation is recomputed here from the service and the one
        governed declaration of what is restricted, so it stays exact and
        stays independent of the code that produces the sentence.
        """
        from backend.orchestration import orchestrator as orc
        from backend.scorecard.domains import restricted_datasets

        blocked = restricted_datasets()
        open_datasets = [d for d in md.datasets() if d.name not in blocked]
        open_domains = {d.domain for d in open_datasets}
        every_domain = {d.domain for d in md.datasets()}

        answered = orc.answer("How many data domains do you have?")
        said = answered.result.answer
        counts = md.counts()

        # One whole domain holds the restricted datasets and nothing else, so
        # the Cockpit sees one domain fewer than the catalogue defines.
        assert len(every_domain - open_domains) == 1
        expected_domains = counts["domains"] - 1
        assert f"{expected_domains:,} data domains" in said
        assert f"{len(open_datasets):,} datasets" in said
        assert f"{sum(d.row_count for d in open_datasets):,} rows" in said

        # And the boundary really is the whole of the difference.
        assert counts["datasets"] - len(open_datasets) == len(blocked)

    @db
    def test_a_domain_holds_the_same_datasets_everywhere(self):
        from backend.db.engine import get_session
        from backend.services import data_builder as builder

        with get_session() as session:
            overview = {d["name"]: d for d in builder.domain_overview(session)}
        tool = {r["domain"]: r for r in tools.list_data_domains(_admin()).rows}
        for heading in md.domains():
            assert overview[heading.name]["dataset_count"] == heading.dataset_count
            assert tool[heading.name]["datasets"] == heading.dataset_count
            listed = {d["name"] for d in overview[heading.name]["datasets"]}
            assert listed == set(heading.datasets)


class TestPublishingIsNotStale:
    def test_invalidate_rebuilds_rather_than_serving_the_old_picture(self):
        first = md.catalogue()
        assert md.catalogue() is first
        md.invalidate()
        assert md.catalogue() is not first
        assert md.catalogue().counts() == first.counts()

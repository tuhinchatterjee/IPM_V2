"""
The retail-only sweep, on the surfaces a reader can actually open.

Revision 3 §4 asks that no corporate example, seed, team, prompt or dataset
remain reachable. "Not in the navigation" is not the same as "not reachable",
and "retired as a concept" is not the same as "not on screen": both gaps were
real here.

* **Agent Operations listed three corporate teams as ACTIVE.** Ratings &
  Financials, Covenant & Collateral and the Relationship Graph were published by
  the registry catalogue with their corporate purposes and corporate methods on
  display, in an installation whose active catalogue publishes not one of the
  concepts they read. The Relationship Graph's own definition says the graph is
  built over the corporate book.

* **The document library shipped a Real Estate Sector Review.** A sector
  committee paper, owned by a Sector Credit Head, on a book with no sectors.

* **Three corporate What-If routes answered under the retail profile.**

Definitions are retained as code throughout: the conversion is a profile, and a
corporate profile must still serve all thirteen agents and the corporate
screens. These gates check what is SERVED, not what exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.agentic import registry
from backend.retail import profile

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")


class TestTheAgentRegistryServesOnlyTeamsWithAnActiveBook:
    def test_the_corporate_specialists_are_not_served(self):
        served = {a.agent_id for a in registry.served_agents()}
        assert "ratings_financials" not in served
        assert "covenants" not in served
        assert "relationship_graph" not in served

    def test_the_retail_specialists_still_are(self):
        served = {a.agent_id for a in registry.served_agents()}
        for agent_id in ("data_steward", "credit_analyst", "ifrs9",
                         "delinquency", "portfolio_risk", "early_warning",
                         "stress", "validation", "workflow_coordinator",
                         "chief_orchestrator"):
            assert agent_id in served, agent_id

    def test_the_catalogue_the_screen_reads_names_none_of_them(self):
        catalogue = registry.catalogue()
        names = {a["business_name"] for a in catalogue["agents"]}
        assert "Ratings & Financials" not in names
        assert "Covenant & Collateral" not in names
        assert "Relationship Graph" not in names
        labels = {d["label"] for d in catalogue["domains"]}
        assert "Ratings & Financials" not in labels
        assert "Covenants & Collateral" not in labels
        assert "Relationship Graph" not in labels

    def test_the_orchestrator_cannot_delegate_to_a_retired_specialist(self):
        delegates = {a.agent_id for a in registry.specialists()}
        assert delegates.isdisjoint(registry.RETIRED_IN_RETAIL_AGENTS)

    def test_a_retired_specialist_is_never_selected_for_a_concept(self):
        """Even if a corporate concept somehow reached the router."""
        chosen = {a.agent_id for a in registry.agents_for(
            ["rating", "dscr", "leverage", "headroom", "connected_group", "ubo"])}
        assert chosen.isdisjoint(registry.RETIRED_IN_RETAIL_AGENTS)

    def test_they_are_retired_rather_than_deleted(self):
        """A corporate profile must still be able to serve all thirteen."""
        assert len(registry.AGENTS) == 13
        for agent_id in registry.RETIRED_IN_RETAIL_AGENTS:
            assert registry.agent(agent_id) is not None

    def test_no_retired_domain_has_an_active_retail_concept_behind_it(self):
        """The justification, checked rather than asserted."""
        from backend.orchestration import concepts as cx

        active = {c.id for c in cx.active_concepts()}
        for domain in registry.RETIRED_IN_RETAIL_DOMAINS:
            owned = set(registry.concepts_in(domain))
            assert owned, f"{domain} owns no concept at all"
            assert not (owned & active), (
                f"{domain} owns active retail concepts {sorted(owned & active)} "
                "and should not have been retired")


@pytest.fixture(scope="module")
def documents() -> str:
    """The seeded document library, as the Documents screen reads it."""
    demo = (FRONTEND / "lib" / "demo.ts").read_text()
    start = demo.index("export const DOCUMENTS")
    return demo[start:demo.index("export function findDocument")]


class TestTheSeededDocumentLibraryIsRetail:
    def test_the_real_estate_sector_review_is_gone(self, documents: str):
        assert "Real Estate" not in documents
        assert "Sector Credit Head" not in documents
        assert "Sector committee paper" not in documents

    def test_no_seeded_paper_names_a_corporate_subject(self, documents: str):
        for word in ("sector", "rating", "notch", "covenant", "obligor",
                     "counterparty", "ebitda", "dscr", "leverage",
                     "wholesale", "corporate"):
            assert not re.search(rf"\b{word}", documents, re.I), word

    def test_every_seeded_paper_names_the_book_and_month_it_is_drawn_from(
            self, documents: str):
        """A committee paper whose scope is unstated cannot be checked."""
        assert documents.count("basis:") == documents.count("id: \"")
        assert documents.count("retail_facility_month") == documents.count("basis:")

    def test_the_figures_it_quotes_are_the_published_ones(
            self, documents: str, retail_book):
        """A seeded reference must reconcile, or it is invented content."""
        latest = retail_book.latest()
        assert f"{len(latest):,}" + " facilities" in documents
        assert f"{latest['customer_id'].nunique():,}" + " customers" in documents
        allowance = latest["ecl_final_sar"].sum()
        assert f"SAR {allowance:,.2f}" in documents

    def test_the_months_it_names_are_published_months(
            self, documents: str, retail_book):
        published = set(retail_book.months())
        for month in set(re.findall(r"\b20\d{2}-\d{2}\b", documents)):
            assert month in published, month


class TestTheCorporateWhatIfRoutesDoNotServeTheirScreen:
    @pytest.mark.parametrize("route", [
        "what-if/thread", "what-if/models/delta", "what-if/models/ml"])
    def test_the_route_is_guarded_by_the_profile(self, route: str):
        source = (FRONTEND / "app" / route / "page.tsx").read_text()
        assert "isRetail()" in source, f"{route} has no retail guard"
        assert "RetiredScreen" in source

    @pytest.mark.parametrize("route", [
        "what-if/thread", "what-if/models/delta", "what-if/models/ml"])
    def test_the_corporate_screen_is_retained_as_code(self, route: str):
        """Retired, not deleted — a corporate profile still serves it."""
        source = (FRONTEND / "app" / route / "page.tsx").read_text()
        assert re.search(r"function Corporate\w+\(", source), route
        assert re.search(r"return <Corporate\w+ />", source), route


class TestTheWhatIfScreenOffersNothingTheRetailBookCannotRun:
    def test_the_starters_are_all_runnable_sentences(self):
        from backend.retail import whatif_language as lang

        for sentence in profile.SCENARIO_STARTERS:
            ask = lang.read(sentence, ["2026-08"])
            assert not ask.unsupported, f"{sentence}: {ask.unsupported}"
            assert not ask.is_neutral, (
                f"{sentence!r} is offered on screen and reads as an unchanged "
                "book — a starter that answers with the baseline")

    def test_no_starter_names_a_retired_operation(self):
        joined = " ".join(profile.SCENARIO_STARTERS).lower()
        for word in ("notch", "rating", "sector", "covenant", "downgrade"):
            assert word not in joined, word

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

    def test_a_served_team_does_not_advertise_a_retired_domain(self):
        """The leak a code search misses.

        Eight retained specialists still carry a grant over every domain they
        would read on the corporate book. Published unfiltered, that put
        "Ratings & Financials" and "Relationship Graph" on the card of every
        one of them — a permission over data that is not here, which reads on
        screen as a capability.
        """
        for agent in registry.served_agents():
            published = set(agent.to_dict()["allowed_data_domains"])
            assert published.isdisjoint(registry.RETIRED_IN_RETAIL_DOMAINS), (
                f"{agent.business_name} advertises "
                f"{sorted(published & registry.RETIRED_IN_RETAIL_DOMAINS)}")
            labels = set(agent.domain_labels)
            assert "Ratings & Financials" not in labels
            assert "Covenants & Collateral" not in labels
            assert "Relationship Graph" not in labels

    def test_a_grant_over_a_retired_domain_does_not_permit_a_read(self):
        for agent in registry.AGENTS:
            for domain in registry.RETIRED_IN_RETAIL_DOMAINS:
                assert not agent.may_read(domain), (
                    f"{agent.agent_id} may read {domain}")

    def test_the_seeded_schedules_wake_no_retired_specialist(self):
        from backend.agentic import schedules

        served = {a.agent_id for a in registry.served_agents()}
        for seed in schedules.SEEDS:
            for agent_id in seed.get("agents", []):
                assert agent_id in served, (
                    f"the schedule {seed['name']!r} wakes {agent_id}, which "
                    "this installation does not serve")

    def test_a_schedule_persisted_before_a_retirement_is_filtered_on_read(self):
        """Editing the seed alone would not have removed it.

        The row was already in the database naming `ratings_financials`, so the
        name reached the Agent Operations screen from storage rather than from
        code. The serialiser has to filter, not just the seed.
        """
        import inspect

        from backend.agentic import schedules

        source = inspect.getsource(schedules)
        at = source.index('"agents": [\n            {"agent_id"')
        block = source[at:at + 400]
        assert "served_agents()" in block, (
            "a schedule renders whatever agent id it stored")

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


class TestTheCroLensIsNotOfferedOrServed:
    """The worst place for a retired surface: not a bookmark somebody kept, a
    card the product offers one click from a navigation item."""

    def test_the_route_answers_instead_of_rendering_the_wholesale_book(self):
        source = (FRONTEND / "app" / "lenses" / "cro" / "page.tsx").read_text()
        assert "isRetail()" in source
        assert "RetiredScreen" in source

    def test_the_hand_built_screen_is_retained_as_code(self):
        source = (FRONTEND / "app" / "lenses" / "cro" / "page.tsx").read_text()
        assert re.search(r"function Corporate\w+\(", source)

    def test_the_lenses_index_does_not_offer_the_card(self):
        source = (FRONTEND / "app" / "lenses" / "page.tsx").read_text()
        assert 'href="/lenses/cro"' in source, "the corporate card was deleted"
        card = source[source.index("Built for the executive"):]
        before = source[:source.index("Built for the executive")]
        assert "isRetail() ? null : (" in before[-600:], (
            "the CRO card is offered unconditionally")


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


class TestTheBootstrapCannotReinstallARetiredSurface:
    """The path a retired surface comes back on.

    Nobody types the URL of a Corporate IFRS 9 lens. The installer creates it:
    the bootstrap runs on every fresh deployment, and until this pass it seeded
    a Corporate IFRS 9 lens, a Corporate Credit Committee, an IFRS 9 committee
    whose every tile names a `corporate.ifrs9.*` metric, a corporate
    model-redevelopment delivery plan and a shipping-review conversation into a
    retail-only product.
    """

    def test_the_corporate_lens_is_not_seeded(self):
        from backend.metrics import lenses

        served = {spec.slug for spec in lenses.served()}
        assert "corporate-ifrs9" not in served
        assert "retail-credit-risk" in served
        assert "retail-analytics" in served

    def test_the_corporate_lens_is_retained_as_code(self):
        """Kept in ALL, and kept out of what a retail installation seeds.

        The count is no longer three: the retail product now ships four
        lenses — Retail Credit Risk, Retail IFRS 9 and ECL, Retail Early
        Warning and Retail Analytics. What this gate is about is unchanged
        and is now what it says: the corporate lens still exists as code so a
        corporate profile can install it, and `served()` still withholds it.
        """
        from backend.metrics import lenses

        assert lenses.CORPORATE_IFRS9 in lenses.ALL
        assert lenses.CORPORATE_IFRS9 not in lenses.served()
        assert len(lenses.served()) == len(lenses.ALL) - len(
            lenses.CORPORATE_LENS_SLUGS)

    def test_no_seeded_lens_reads_a_corporate_metric(self):
        from backend.metrics import lenses

        for spec in lenses.served():
            for tile in spec.tiles:
                assert not tile.metric_id.startswith("corporate."), (
                    f"{spec.slug} reads {tile.metric_id}")

    def test_a_lens_already_in_the_database_is_filtered_on_read(self):
        """Withholding it from the installer does nothing for a row that exists.

        This installation already HAD the corporate lens at id 3, named
        "Corporate IFRS 9" on the Lenses screen. Gating `install()` stops a
        fresh deployment and leaves every existing one exactly as it was, so
        the listing filters too — the same mistake as the schedule row.
        """
        import inspect

        from backend.services import lenses as service

        assert "_retired_here" in inspect.getsource(service.listing), (
            "the lens listing renders whatever slug the database holds")
        assert service._retired_here("corporate-ifrs9") is True
        assert service._retired_here("retail-credit-risk") is False
        # A lens somebody built themselves is theirs, whatever it is called.
        assert service._retired_here("my-own-lens") is False

    def test_the_corporate_committees_are_not_seeded(self):
        from backend.playbook import demo

        served = {c.code for c in demo.served_committees()}
        assert "corporate-credit-committee" not in served
        assert "ifrs9-impairment-committee" not in served
        assert "retail-credit-risk-committee" in served

    def test_the_corporate_committees_are_retained_as_code(self):
        from backend.playbook import demo

        # Five now: three retail packs — Portfolio, IFRS 9, Scorecard
        # Assurance — plus the two corporate committees, retained and withheld.
        assert len(demo.COMMITTEES) == 5
        codes = {c.code for c in demo.COMMITTEES}
        assert demo.CORPORATE_COMMITTEE_CODES <= codes

    def test_three_retail_packs_are_served(self):
        """§10 asks for a Portfolio, an IFRS 9 and a Scorecard pack, and until
        this pass the Playbook had one committee whose every tile was empty."""
        from backend.playbook import demo

        served = {c.code for c in demo.served_committees()}
        assert served == {"retail-credit-risk-committee",
                          "retail-ifrs9-committee",
                          "retail-scorecard-committee"}

    def test_every_pack_block_names_a_metric_this_installation_serves(self):
        """A committee pack whose KPI names a retired metric shows a dash."""
        from backend.metrics import library as metric_library
        from backend.playbook import demo

        served = {m.metric_id for m in metric_library.ALL}
        for committee in demo.served_committees():
            for section in committee.template["sections"]:
                for block in section["blocks"]:
                    if block.get("type") != "KPI":
                        continue
                    metric_id = block["config"]["metric_id"]
                    assert metric_id in served, (
                        f"{committee.code} shows {metric_id}, which is not "
                        "served here")
            for rule in committee.template["materiality"]:
                assert rule["metric_id"] in served, (
                    f"{committee.code} has a materiality rule on "
                    f"{rule['metric_id']}, which is not served here")

    def test_the_seeded_delivery_plan_is_retail(self):
        import datetime

        import scripts.seed_planner as planner

        plan = planner.plan(datetime.date.today())
        text = repr(plan).lower()
        for word in ("corporate", "shipping", "real-estate", "real estate",
                     "vessel", "sector", "notch", "covenant", "obligor"):
            assert word not in text, word
        assert "retail" in plan["project"]["name"].lower()

    def test_the_seeded_plan_still_demonstrates_every_planner_feature(self):
        """Retail content, not a thinner plan: the shape has to survive."""
        import datetime

        import scripts.seed_planner as planner

        plan = planner.plan(datetime.date.today())
        statuses = {t[5] for t in plan["tasks"]}
        assert {"COMPLETED", "IN_PROGRESS", "NOT_STARTED", "BLOCKED"} <= statuses
        kinds = {r[0] for r in plan["raid"]}
        assert {"RISK", "DECISION", "ISSUE", "ASSUMPTION"} <= kinds
        assert any(r[0] == "DECISION" and r[4] == "OPEN" for r in plan["raid"])
        assert any(r[0] == "DECISION" and r[4] == "CLOSED" for r in plan["raid"])
        assert any(t[11] for t in plan["tasks"]), "no task is on the critical path"
        assert any(t[12] for t in plan["tasks"]), "no task is blocked"
        assert len(plan["milestones"]) >= 5
        assert len(plan["dependencies"]) >= 15
        assert len(plan["updates"]) >= 8

    def test_the_seeded_conversations_are_retail(self):
        from backend.services import demo_workflow

        source = Path(demo_workflow.__file__).read_text()
        for word in ("shipping", "Corporate", "portfolio_facility"):
            assert word not in source, word
        assert demo_workflow.PREFERRED_RELEASE_DATASET == "retail_facility_month"

    def test_the_release_notification_names_a_dataset_this_product_serves(self):
        from backend.retail import profile
        from backend.services import demo_workflow

        assert not profile.is_retired(demo_workflow.PREFERRED_RELEASE_DATASET)

    def test_the_seed_keys_do_not_name_a_retired_subject(self):
        from backend.services import demo_workflow

        joined = " ".join(demo_workflow.SEED_KEYS)
        assert "shipping" not in joined

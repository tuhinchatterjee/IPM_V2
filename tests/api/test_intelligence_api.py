"""
§35-§39 and §43-§46 over HTTP — the AI Intelligence Studio's backend.

What these tests are about
---------------------------
Not that the routes return 200. That the two rules running through the Studio
hold at the HTTP boundary, where they are easiest to lose:

    nothing here calls a provider;
    nothing here approves anything on its own.

Plus the one §2 requires and nobody notices until it is wrong: ordinary users
do not see case-authoring controls, and a list of every teaching case IS the
authoring surface whether or not it has buttons on it.
"""

from __future__ import annotations

import pytest

from backend.teaching import failures as fl
from backend.teaching import families as fam
from backend.teaching import release as rel
from tests.conftest import database_available

db = pytest.mark.skipif(not database_available(),
                        reason="needs the platform database")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


def admin() -> dict[str, str]:
    return {"X-IPM-Role": "ADMIN", "X-IPM-User-Id": "1"}


def analyst() -> dict[str, str]:
    return {"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "2"}


# ======================================================= §2 who may see what


@pytest.mark.parametrize("path", [
    "/api/v1/intelligence/cases",
    "/api/v1/intelligence/review-queue",
])
def test_an_analyst_may_not_see_the_authoring_surface(client, path):
    """§2: "Ordinary users should not see case-authoring controls." A list of
    every teaching case is that surface whether or not it has buttons."""
    assert client.get(path, headers=analyst()).status_code == 403


def test_an_analyst_may_ask_how_the_product_is_performing(client):
    """The other half of the rule. An analyst given an answer is entitled to
    ask what shaped it."""
    for path in ("/api/v1/intelligence/failures",
                 "/api/v1/intelligence/policy",
                 "/api/v1/intelligence/routing",
                 "/api/v1/intelligence/classifiers",
                 "/api/v1/intelligence/disclosure-sections"):
        assert client.get(path, headers=analyst()).status_code == 200, path


def test_the_retrieval_lab_is_administrator_only(client):
    refused = client.post("/api/v1/intelligence/retrieval-lab",
                          json={"question": "anything"}, headers=analyst())
    assert refused.status_code == 403


# ============================================================ the taxonomy


def test_the_taxonomy_route_carries_every_category_and_its_severity(client):
    body = client.get("/api/v1/intelligence/failures",
                      headers=analyst()).json()
    assert {c["id"] for c in body["categories"]} == set(fl.IDS)
    critical = {c["id"] for c in body["categories"] if c["critical"]}
    assert critical == set(fl.CRITICAL)
    non_defects = {c["id"] for c in body["categories"] if not c["defect"]}
    assert non_defects == {"UNSUPPORTED", "CONTROLLED_FAILURE", "COST_BUDGET"}


# ============================================================== the routing


def test_the_routing_route_names_roles_and_never_a_model_id(client):
    """§23. The Studio is where an administrator would look for a model name,
    and it must show the CONFIGURED one rather than one the code chose."""
    body = client.get("/api/v1/intelligence/routing", headers=analyst()).json()
    assert body["cascade_limits"]["critic_passes"] == 1
    assert body["unavailable_policy"] in body["policies"]
    assert "claude-" not in str(body["routes"])
    assert len(body["stages"]) == 9


def test_the_policy_route_shows_the_thresholds_in_force(client):
    body = client.get("/api/v1/intelligence/policy", headers=analyst()).json()
    assert body["fingerprint"]
    assert len(body["rows"]) == 7
    assert body["candidates"] > 1


# ============================================================== §37 the lab


@db
def test_the_lab_answers_without_calling_a_provider(client, monkeypatch):
    """§37: "No live provider call is required for retrieval preview." Proved
    by making any provider call raise."""
    from backend.llm import anthropic_provider as ap

    def explode(*args, **kwargs):
        raise AssertionError("the Retrieval Lab called a provider")

    monkeypatch.setattr(ap.AnthropicProvider, "structured", explode,
                        raising=False)

    body = client.post("/api/v1/intelligence/retrieval-lab",
                       json={"question": "What is total exposure at default "
                                         "by sector?",
                             "capability": "ANALYSIS"},
                       headers=admin()).json()
    assert "retrieved" in body
    assert "refused" in body
    assert body["predicted_route"]["final_route"]


@db
def test_the_lab_reports_why_cases_were_refused(client):
    """"Nothing came back" is unactionable; "eleven cases were refused on
    portfolio scope" is a fix.

    The lab is asked about a case this test creates, rather than about
    whatever happens to be seeded: the suite empties the teaching library, so
    a test that assumed a populated one would pass or fail on the order the
    files ran in.
    """
    client.post("/api/v1/intelligence/cases", headers=admin(), json={"case": {
        "case_id": "api-lab-1", "title": "Total EAD by sector",
        "family_id": "SINGLE_DOMAIN_AGGREGATION",
        "question": "What is total exposure at default by sector?",
        "objectives": [{"id": "o1", "text": "total EAD by sector"}],
        "analytical_plan_contract": {"group_by": ["sector"]},
        "concepts": ["exposure at default"]}})
    try:
        body = client.post("/api/v1/intelligence/retrieval-lab",
                           json={"question": "zxqv wibble frobnicate"},
                           headers=admin()).json()
        assert body["considered"] >= 1
        assert body["retrieved"] == []
        # Unapproved, so it never even reaches the ranking stage.
        assert body["refused"]
    finally:
        client.post("/api/v1/intelligence/cases/api-lab-1/retire",
                    json={"reviewer": "Amal", "note": "test cleanup"},
                    headers=admin())


@db
def test_the_lab_can_show_the_teaching_pack_it_would_build(client):
    body = client.post("/api/v1/intelligence/retrieval-lab",
                       json={"question": "What is total exposure at default "
                                         "by sector?",
                             "capability": "ANALYSIS",
                             "include_pack": True},
                       headers=admin()).json()
    assert body["pack_tokens"] >= 0
    assert body["token_budget"] > 0


# ==================================================== §35, §36 the workflow


@db
def test_a_case_arrives_unapproved_and_needs_a_person(client):
    """§5 at the HTTP boundary, which is where it is easiest to lose."""
    case = {
        "case_id": "api-tc-1", "title": "Total EAD by sector",
        "family_id": "SINGLE_DOMAIN_AGGREGATION",
        "question": "What is total exposure at default by sector?",
        "objectives": [{"id": "o1", "text": "total EAD by sector"}],
        "analytical_plan_contract": {"group_by": ["sector"]},
        "concepts": ["exposure at default"],
    }
    created = client.post("/api/v1/intelligence/cases",
                          json={"case": case}, headers=admin())
    assert created.status_code == 201
    assert created.json()["case"]["review_status"] == "AUTO_VALIDATED"
    assert created.json()["case"]["retrievable"] is False

    refused = client.post("/api/v1/intelligence/cases/api-tc-1/approve",
                          json={"reviewer": "Amal", "note": ""},
                          headers=admin())
    assert refused.status_code == 422

    approved = client.post("/api/v1/intelligence/cases/api-tc-1/approve",
                           json={"reviewer": "Amal",
                                 "note": "checked against the ontology"},
                           headers=admin())
    assert approved.status_code == 200
    assert approved.json()["case"]["review_status"] == "APPROVED"
    assert approved.json()["case"]["retrievable"] is True

    client.post("/api/v1/intelligence/cases/api-tc-1/retire",
                json={"reviewer": "Amal", "note": "test cleanup"},
                headers=admin())


@db
def test_reading_a_case_shows_a_reviewer_what_section_36_asks_for(client):
    case = {
        "case_id": "api-tc-2", "title": "Total EAD by segment",
        "family_id": "SINGLE_DOMAIN_AGGREGATION",
        "question": "What is total exposure at default by segment?",
        "objectives": [{"id": "o1", "text": "total EAD by segment"}],
        "analytical_plan_contract": {"group_by": ["segment"]},
        "concepts": ["exposure at default"],
    }
    client.post("/api/v1/intelligence/cases", json={"case": case},
                headers=admin())
    body = client.get("/api/v1/intelligence/cases/api-tc-2",
                      headers=admin()).json()
    assert body["case"]["question"].startswith("What is total")
    assert body["teaching_pack"] is not None
    assert body["history"]
    assert body["problems"] == []
    assert "duplicates" in body

    client.post("/api/v1/intelligence/cases/api-tc-2/retire",
                json={"reviewer": "Amal", "note": "test cleanup"},
                headers=admin())


@db
def test_an_unknown_case_is_a_404(client):
    assert client.get("/api/v1/intelligence/cases/nope",
                      headers=admin()).status_code == 404


# ================================================= governance and families


@db
def test_the_governance_route_breaks_the_count_down(client):
    body = client.get("/api/v1/intelligence/governance",
                      headers=analyst()).json()
    assert set(body) >= {"cases", "by_status", "by_authoring_method",
                         "by_provenance", "by_family", "by_difficulty",
                         "by_scope", "by_language", "human_reviewed",
                         "retrievable_now", "sentence"}
    assert "human reviewed without an approval record" in body["sentence"]


@db
def test_the_families_route_lists_every_family_with_its_coverage(client):
    body = client.get("/api/v1/intelligence/families",
                      headers=analyst()).json()
    assert len(body["families"]) == len(fam.FAMILIES)
    gated = [f for f in body["families"] if not f["available"]]
    assert {f["id"] for f in gated} == {"ARABIC_QUERY",
                                        "PROJECT_PLANNER_QUERY"}
    for family in body["families"]:
        assert family["teaches"]


@db
def test_the_overview_leads_with_governance_rather_than_a_score(client):
    """A Studio whose first screen is a percentage teaches everybody who opens
    it that the percentage is the thing to look at."""
    body = client.get("/api/v1/intelligence/overview",
                      headers=analyst()).json()
    assert "governance" in body["library"]
    assert body["release"]["state"]
    assert body["policy"]["fingerprint"]
    assert body["failure_taxonomy"]["categories"] == len(fl.CATEGORIES)


def test_the_releases_route_names_the_gate_state(client):
    body = client.get("/api/v1/intelligence/releases",
                      headers=analyst()).json()
    assert body["gate"]["state"] in body["states"]
    # Derived rather than counted: a release file added by a later section
    # should change this list, and a test that pinned the number would fail
    # for the right change every time.
    assert body["files"] == list(rel.FILES)


def test_the_disclosure_route_lists_section_45s_seven_sections(client):
    body = client.get("/api/v1/intelligence/disclosure-sections",
                      headers=analyst()).json()
    assert len(body["sections"]) == 7

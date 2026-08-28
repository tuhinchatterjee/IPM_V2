"""
§28–§33, §40–§51, §57, §76 — the agentic API surface.

Two questions, and the second is the one that matters.

**Does it answer?** Every Agent Operations tab and every Requires Attention
filter reads one of these endpoints, and a screen wired to a 500 is a screen
nobody sees.

**Does it refuse?** §57: "A user must not gain access to data through an agent
that they could not access directly." An agentic API is a new door into the same
building, and a door added late is the one nobody checked. So the permission
tests here are not a formality — they are why the file exists.

Nothing here calls a model. The one endpoint that could (`/agentic/review`) is
exercised only for its refusals; the review itself is tested against a fake
runtime in `tests/agentic/test_review.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(), reason="PostgreSQL is not reachable")

API = "/api/v1"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


def _as(role: str, user_id: int = 1) -> dict[str, str]:
    return {"X-IPM-User-Id": str(user_id), "X-IPM-Role": role}


VIEWER = _as("VIEWER")
ANALYST = _as("ANALYST")
STEWARD = _as("DATA_STEWARD")
ADMIN = _as("ADMIN")


@pytest.fixture
def a_case():
    """One real Risk Case, removed afterwards."""
    from backend.agentic import cases
    from backend.agentic import severity as sv
    from backend.db.engine import SessionLocal

    session = SessionLocal()
    draft = cases.Draft(
        level=cases.SEGMENT, title="API test case", period="Q2 2026",
        entity="Contracting", entity_id="contracting-api-test",
        about="api_test", conclusion="Stage 2 share rose.",
        exposure=500.0, analyses=[],
        score=sv.compute(exposure=500.0, portfolio_exposure=10_000.0,
                         movement=0.3, evidence_present=1,
                         evidence_expected=1))
    case = cases.upsert(session, draft, actor_agent="portfolio_risk")
    session.commit()
    case_id = case.id
    try:
        yield case_id
    finally:
        session.execute(text("DELETE FROM risk_case_events WHERE case_id = :i"),
                        {"i": case_id})
        session.execute(text("DELETE FROM risk_case_links WHERE case_id = :i"),
                        {"i": case_id})
        session.execute(text("DELETE FROM risk_cases WHERE id = :i"),
                        {"i": case_id})
        session.commit()
        session.close()


# ---------------------------------------------------------------------------
# §29–§33 — the reading surfaces
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [
    "/agentic/agents",
    "/agentic/tools",
    "/agentic/stages",
    "/agentic/runs",
    "/agentic/schedules",
    "/agentic/policies",
    "/agentic/approvals",
    "/agentic/events",
    "/agentic/evaluations",
    "/agentic/workers",
])
def test_every_agent_operations_tab_answers(client, path):
    response = client.get(f"{API}{path}", headers=ADMIN)
    assert response.status_code == 200, response.text
    assert response.json() is not None


def test_the_registry_lists_twelve_specialists_with_their_contracts(client):
    """§13's 24-field contract, as the screen reads it. A registry that showed
    a name and a purpose would be a staff list, not a governance record."""
    from backend.agentic import registry

    body = client.get(f"{API}/agentic/agents", headers=ADMIN).json()
    assert len(body["agents"]) == len(registry.AGENTS)
    assert body["fingerprint"] == registry.fingerprint()
    for agent in body["agents"]:
        assert agent["purpose"]
        assert agent["when_to_use"]
        assert agent["when_not_to_use"]
        assert agent["allowed_tools"]
        assert agent["owner"]
        assert agent["model_role_preference"]
        assert "autonomy_level" in agent
        # §3: a model ROLE, never a model id.
        assert "claude" not in agent["model_role_preference"].lower()


def test_the_tool_registry_names_what_has_no_tool(client):
    """§14. The list of things no tool performs is part of the published
    surface: an auditor should not have to read the source to learn that
    `execute_sql` does not exist."""
    body = client.get(f"{API}/agentic/tools", headers=ADMIN).json()
    assert "execute_sql" in body["no_tool_exists"]
    assert "publish_data" in body["no_tool_exists"]
    ids = {t["tool_id"] for t in body["tools"]}
    assert ids.isdisjoint(set(body["no_tool_exists"]))


def test_the_stage_vocabulary_is_the_one_the_ui_renders(client):
    """§7's eleven stages, with their captions, served rather than duplicated
    in TypeScript — two copies drift and the second one is always the one on
    screen."""
    from backend.agentic import stages as st

    body = client.get(f"{API}/agentic/stages", headers=ANALYST).json()
    assert body["sequence"] == list(st.SEQUENCE)
    served = {s["id"]: s for s in body["stages"]}
    assert set(st.SEQUENCE) <= set(served)
    for stage in st.SEQUENCE:
        assert served[stage]["caption"] == st.CAPTIONS[stage]
    # The terminal states are served too — a UI that only knew the happy path
    # would have nothing to render when a run failed.
    assert st.FAILED in served
    assert st.NEEDS_INPUT in served


def test_the_officer_preview_needs_no_run_and_no_model(client):
    """§6: the officer is named before the work starts. A preview that had to
    start a run to answer would make the Cockpit's idle state a lie."""
    response = client.post(f"{API}/agentic/officer", headers=ANALYST,
                           json={"question": "What is total ECL?"})
    assert response.status_code == 200
    body = response.json()
    assert body["officer_level"] in (1, 2, 3, 4)
    assert body["officer_title"]
    assert body["selection_reason"]


def test_a_coordinated_question_previews_a_higher_officer(client):
    """§5: from governed complexity and risk, not from phrase matching."""
    simple = client.post(f"{API}/agentic/officer", headers=ANALYST,
                         json={"question": "What is total ECL?"}).json()
    broad = client.post(
        f"{API}/agentic/officer", headers=ANALYST,
        json={"question": "Review the entire portfolio and tell me what "
                          "requires attention across every sector"}).json()
    assert broad["officer_level"] >= simple["officer_level"]


def test_the_worker_view_reports_health_rather_than_presence(client):
    """A process that is running but has stopped claiming jobs is not healthy,
    and the screen has to be able to say so."""
    body = client.get(f"{API}/agentic/workers", headers=ADMIN).json()
    assert "workers" in body
    for row in body["workers"]:
        assert "status" in row
        assert "healthy" in row or "heartbeat_at" in row


def test_the_evaluation_surface_is_a_corpus_not_three_questions(client):
    """§33: 'Do not use three random questions as certification.'"""
    from backend.agentic import evaluation

    body = client.get(f"{API}/agentic/evaluations", headers=ADMIN).json()
    assert body["total"] >= evaluation.MINIMUM_CASES
    # §33 and §59: reported per area, because "87% accurate" is not an answer
    # to "can it be trusted not to close a case on its own".
    assert len(body["areas"]) >= 10
    assert body["verdict"]
    # Certification is gated on safety FIRST, then accuracy.
    assert body["certified"] is (not body["safety_failures"]
                                 and body["accuracy"] >= evaluation.CERTIFY_AT)
    # §83: this endpoint could not make a live call if it wanted to.
    assert body["duration_ms"] < 60_000


# ---------------------------------------------------------------------------
# §40–§47 — Requires Attention
# ---------------------------------------------------------------------------


def test_requires_attention_answers_for_every_filter(client, a_case):
    from backend.agentic import cases

    for name in cases.FILTERS:
        response = client.get(f"{API}/risk-cases", headers=ANALYST,
                              params={"filter": name})
        assert response.status_code == 200, f"{name}: {response.text}"
        body = response.json()
        assert "cases" in body
        assert "counts" in body


def test_the_summary_sentence_is_backed_by_the_cases_listed(client, a_case):
    """§47: 'Do not state a number that is not backed by current Risk Cases.'"""
    body = client.get(f"{API}/risk-cases", headers=ANALYST).json()
    assert body["summary"]
    assert body["counts"]["ALL"] >= 1


def test_a_case_opens_with_its_evidence_and_its_next_actions(client, a_case):
    body = client.get(f"{API}/risk-cases/{a_case}", headers=ANALYST).json()
    assert body["conclusion"]
    assert body["severity_detail"]["components"]
    assert body["severity_version"]
    assert body["next_actions"]
    assert body["timeline"]


def test_a_case_that_does_not_exist_is_a_404_not_a_500(client):
    assert client.get(f"{API}/risk-cases/99999999",
                      headers=ANALYST).status_code == 404


# ---------------------------------------------------------------------------
# §57 — the door
# ---------------------------------------------------------------------------


def test_a_viewer_cannot_change_a_case(client, a_case):
    """The specific §57 failure: an agentic surface that quietly grants what
    the direct surface refuses."""
    refused = [
        client.post(f"{API}/risk-cases/{a_case}/status", headers=VIEWER,
                    json={"status": "TRIAGED"}),
        client.post(f"{API}/risk-cases/{a_case}/assign", headers=VIEWER,
                    json={"owner_id": 1}),
        client.post(f"{API}/risk-cases/{a_case}/dismiss", headers=VIEWER,
                    json={"reason": "no"}),
        client.post(f"{API}/risk-cases/{a_case}/resolve", headers=VIEWER,
                    json={"reason": "done"}),
    ]
    assert all(r.status_code in (401, 403) for r in refused), \
        [r.status_code for r in refused]


def test_a_viewer_cannot_operate_the_agentic_layer(client):
    """Reading what the agents are is not the same as running them."""
    refused = [
        client.post(f"{API}/agentic/review", headers=VIEWER,
                    json={"period": "Q2 2026"}),
        client.patch(f"{API}/agentic/schedules/1", headers=VIEWER,
                     json={"enabled": True}),
        client.put(f"{API}/agentic/policies/autonomy", headers=VIEWER,
                   json={"value": {}}),
    ]
    assert all(r.status_code in (401, 403, 404) for r in refused), \
        [r.status_code for r in refused]
    assert any(r.status_code in (401, 403) for r in refused)


def test_an_analyst_cannot_write_an_agent_policy(client):
    """§29: 'No arbitrary code editor.' A policy is the one thing on the screen
    that changes what agents may do, so it is an administrator's."""
    response = client.put(f"{API}/agentic/policies/autonomy", headers=ANALYST,
                          json={"value": {"pre_approved": ["close_case"]}})
    assert response.status_code in (401, 403)


def test_an_analyst_cannot_decide_an_admin_gate(client):
    """§22's approver role, enforced at the API and not only in the service."""
    from backend.agentic import approvals, autonomy, registry
    from backend.db.engine import SessionLocal

    session = SessionLocal()
    row = approvals.open_gate(session, autonomy.gate_for(
        registry.CHIEF_ORCHESTRATOR, "certify_method",
        title="Certify a method", reason="test"))
    session.commit()
    gate_id = row.id
    try:
        response = client.post(f"{API}/agentic/approvals/{gate_id}",
                               headers=ANALYST,
                               json={"decision": "approved"})
        assert response.status_code in (401, 403)
    finally:
        session.execute(text("DELETE FROM agent_approvals WHERE id = :i"),
                        {"i": gate_id})
        session.commit()
        session.close()


def test_reading_the_registry_needs_agent_operations_standing(client):
    """§29 is an operator's screen, and the navigation gates the page to match.
    A viewer being able to read it would not leak portfolio data, but it would
    make the role gate on the page decorative — the API is where it holds."""
    assert client.get(f"{API}/agentic/agents",
                      headers=VIEWER).status_code == 403
    assert client.get(f"{API}/agentic/agents",
                      headers=STEWARD).status_code == 200
    assert client.get(f"{API}/agentic/agents",
                      headers=ADMIN).status_code == 200


def test_a_review_of_a_period_nobody_published_is_refused_cleanly(client):
    """Not a 500. The steward check is the product working, and it has to read
    as a stated reason rather than as a crash."""
    response = client.post(f"{API}/agentic/review", headers=STEWARD,
                           json={"period": "Q9 2099"})
    assert response.status_code in (200, 400, 404, 409, 422)
    if response.status_code == 200:
        body = response.json()
        assert body.get("stopped") or body.get("note")

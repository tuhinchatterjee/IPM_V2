"""
The model registry through its real routes. §12, §35, §87.

These are the routes that write. Everything else in the scorecard module
computes over the lake and can be wrong only by being wrong; these can be
wrong by letting the wrong person do something, which is a different and
worse failure. So the permission cases here are not an afterthought — the
narrower approval permission is the whole of §35's control, and a permission
that is only a hidden button is a permission an attacker has.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from backend.api import permissions as perms
from backend.scorecard import policy as policy_mod
from backend.scorecard import registry as reg
from tests.conftest import database_available

db = pytest.mark.skipif(not database_available(),
                        reason="needs the platform database")

_OWNED = ("scorecard_report_evidence", "scorecard_reports",
          "scorecard_dashboard_pins", "scorecard_model_approvals",
          "scorecard_findings", "scorecard_validation_runs",
          "scorecard_policy_limits", "scorecard_binning_specs",
          "scorecard_model_variables", "scorecard_models")


#: Seeded demonstration users. Real ids on purpose: `_known_user` treats an
#: id that names nobody as anonymous rather than letting it fail a foreign
#: key deep inside a service, so a test using id 42 would silently be
#: testing the anonymous path and asserting nothing about identity.
ALEX, SARA = 1, 2


def headers(role: str = "ADMIN", user_id: int = ALEX) -> dict[str, str]:
    return {"X-IPM-Role": role, "X-IPM-User-Id": str(user_id)}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture
def registered():
    """Seed the default tenant, because that is what the routes read.

    The routes do not take a tenant — it is resolved at the edge and is
    empty in the test harness — so this fixture owns the default tenant's
    scorecard rows for the duration of one test and puts them back.
    """
    from backend.db.engine import SessionLocal

    session = SessionLocal()
    for table in _OWNED:
        session.execute(text(f"DELETE FROM {table} WHERE tenant = ''"))
    session.commit()
    reg.seed(session, created_by="test")
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        for table in _OWNED:
            session.execute(text(f"DELETE FROM {table} WHERE tenant = ''"))
        session.commit()
        session.close()


# ------------------------------------------------------------------ reading


@db
def test_the_registry_lists_every_version_with_its_variables(client,
                                                             registered):
    body = client.get("/api/v1/scorecard/registry",
                      headers=headers()).json()
    assert body["count"] == 6
    assert body["nothing_registered"] == ""
    entry = next(m for m in body["models"]
                 if m["model_id"] == "application-incumbent")
    assert entry["status"] == reg.ACTIVE
    assert entry["origin"] == reg.SYNTHETIC_DEMO
    assert entry["score_direction"]
    assert len(entry["active_variables"]) >= 5
    assert entry["candidate_variables"], "considered-and-rejected is recorded"


@db
def test_an_empty_registry_says_so_rather_than_reporting_no_models(client):
    """An installation built without --register has models it can score with
    and none it can raise a finding against. Reporting that as an empty
    portfolio would hide a fixable gap."""
    from backend.db.engine import SessionLocal

    session = SessionLocal()
    for table in _OWNED:
        session.execute(text(f"DELETE FROM {table} WHERE tenant = ''"))
    session.commit()
    session.close()

    body = client.get("/api/v1/scorecard/registry",
                      headers=headers()).json()
    assert body["count"] == 0
    assert "--register" in body["nothing_registered"]


@db
def test_one_model_carries_its_approval_history_and_legal_moves(client,
                                                                registered):
    body = client.get("/api/v1/scorecard/registry/application-incumbent",
                      headers=headers()).json()
    assert body["model_version"] == "1.0.0"
    assert body["equation"]["terms"]
    assert body["legal_transitions"] == list(
        reg.TRANSITIONS[reg.ACTIVE])
    assert body["approvals"] == []


@db
def test_a_model_nobody_registered_is_a_404_not_an_empty_shell(client,
                                                               registered):
    response = client.get("/api/v1/scorecard/registry/nothing-here",
                          headers=headers())
    assert response.status_code == 404


# -------------------------------------------------------------- transitions


@db
def test_activating_a_candidate_without_approving_it_is_refused(client,
                                                                registered):
    response = client.post(
        "/api/v1/scorecard/registry/application-challenger/transition",
        headers=headers(),
        json={"model_version": "1.0.0", "to_status": "ACTIVE"})
    assert response.status_code == 422
    assert "cannot move to ACTIVE" in response.json()["detail"]["message"]


@db
def test_approval_then_activation_retires_the_incumbent(client, registered):
    for to_status in ("APPROVED", "ACTIVE"):
        response = client.post(
            "/api/v1/scorecard/registry/application-challenger/transition",
            headers=headers(),
            json={"model_version": "1.0.0", "to_status": to_status,
                  "rationale": "Model committee, minute 4.",
                  "committee": "Model Risk Committee"})
        assert response.status_code == 200, response.text
    assert response.json()["status"] == "ACTIVE"

    incumbent = client.get(
        "/api/v1/scorecard/registry/application-incumbent",
        headers=headers()).json()
    assert incumbent["status"] == reg.RETIRED
    assert [a["to_status"] for a in incumbent["approvals"]] == [reg.RETIRED]


@db
def test_the_decision_records_who_made_it(client, registered):
    body = client.post(
        "/api/v1/scorecard/registry/application-challenger/transition",
        headers=headers(role="ADMIN", user_id=SARA),
        json={"model_version": "1.0.0", "to_status": "APPROVED"}).json()
    assert body["decided_by"] == f"ADMIN#{SARA}"


@db
def test_only_an_administrator_may_move_a_model(client, registered):
    """§35. Proposing a change to a credit model and accepting it are
    different acts, and one person doing both is the control failing."""
    for role in ("DATA_STEWARD", "ANALYST", "VIEWER"):
        response = client.post(
            "/api/v1/scorecard/registry/application-challenger/transition",
            headers=headers(role=role),
            json={"model_version": "1.0.0", "to_status": "APPROVED"})
        assert response.status_code == 403, role


def test_approving_is_a_narrower_permission_than_proposing():
    """A property of the policy, not of one route: if the two sets ever
    become equal, the separation of duties is decoration."""
    assert (perms.SCORECARD_MODEL_APPROVE
            < perms.SCORECARD_MODEL_EDIT_CANDIDATE)


# ----------------------------------------------------------------- findings


@db
def test_findings_carry_their_limit_source_through_the_route(client,
                                                             registered):
    reg.record_finding(registered, policy_mod.Finding(
        finding_id="F-API-1", model_id="application-incumbent",
        model_version="1.0.0", period="2024-06",
        category=next(iter(policy_mod.CATEGORIES)),
        title="Score PSI above the demonstration limit",
        description="PSI of 0.31 against a 0.25 limit.",
        severity=policy_mod.HIGH, metric="score_psi", observed=0.31,
        limit_value=0.25, limit_source=policy_mod.DEMO_POLICY, breach=True,
        evidence=[{"metric": "score_psi", "value": 0.31}],
        analysis_run_ids=["RUN-1"], status=policy_mod.OPEN))
    registered.commit()

    body = client.get(
        "/api/v1/scorecard/registry/application-incumbent/findings",
        headers=headers()).json()
    assert body["count"] == 1
    found = body["findings"][0]
    assert found["limit_source"] == policy_mod.DEMO_POLICY
    assert found["breach"] is True
    assert found["evidence"]


@db
def test_a_finding_cannot_be_moved_to_a_status_that_does_not_exist(
        client, registered):
    response = client.post(
        "/api/v1/scorecard/registry/findings/F-API-1/status",
        headers=headers(), json={"status": "SORTED"})
    assert response.status_code == 422


# --------------------------------------------------------------------- pins


@db
def test_a_pin_round_trips_and_belongs_to_the_person_who_made_it(client,
                                                                 registered):
    made = client.post("/api/v1/scorecard/pins", headers=headers(user_id=ALEX),
                       json={"scorecard_type": "APPLICATION",
                             "kind": "metric", "reference": "score_psi",
                             "label": "Score PSI"})
    assert made.status_code == 200, made.text

    mine = client.get("/api/v1/scorecard/pins?scorecard_type=APPLICATION",
                      headers=headers(user_id=ALEX)).json()
    assert [p["reference"] for p in mine["pins"]] == ["score_psi"]

    theirs = client.get("/api/v1/scorecard/pins", headers=headers(user_id=SARA))
    assert theirs.json()["count"] == 0

    removed = client.delete(
        "/api/v1/scorecard/pins?scorecard_type=APPLICATION&kind=metric"
        "&reference=score_psi", headers=headers(user_id=ALEX))
    assert removed.json()["removed"] is True


@db
def test_a_pin_on_a_scorecard_that_does_not_exist_is_refused(client,
                                                             registered):
    response = client.post("/api/v1/scorecard/pins", headers=headers(),
                           json={"scorecard_type": "MORTGAGE",
                                 "kind": "metric", "reference": "gini"})
    assert response.status_code in (404, 422)


# ------------------------------------------------- §35 candidate recording


def _proposal(**overrides) -> dict:
    payload = {
        "model_name": "Application Scorecard v1.1 proposal",
        "intercept": -2.6,
        "terms": [
            {"variable": "bureau_score", "coefficient": -0.82},
            {"variable": "debt_burden_ratio", "coefficient": -0.55},
            {"variable": "employment_tenure_months", "coefficient": -0.41},
            {"variable": "bureau_enquiries_6m", "coefficient": -0.33},
            {"variable": "credit_card_utilisation", "coefficient": -0.28},
        ],
        "based_on": "INCUMBENT",
    }
    payload.update(overrides)
    return payload


def test_a_proposal_is_not_recorded_unless_it_is_asked_to_be(client):
    """The same route previews a diff while somebody is still editing. A
    registry holding every keystroke is a registry nobody reads."""
    body = client.post("/api/v1/scorecard/models/APPLICATION/candidate",
                       headers=headers(), json=_proposal()).json()
    assert body["registry"]["recorded"] is False
    assert body["activated"] is False


@db
def test_a_recorded_proposal_becomes_a_new_version_beside_the_active_one(
        client, registered):
    """§35. A row is added; the ACTIVE model is not touched."""
    before = client.get(
        "/api/v1/scorecard/registry/application-incumbent",
        headers=headers()).json()

    body = client.post("/api/v1/scorecard/models/APPLICATION/candidate",
                       headers=headers(),
                       json=_proposal(record=True,
                                      notes="Reweighted after the Q2 drift.")
                       ).json()
    assert body["registry"]["recorded"] is True, body["registry"]["why_not"]
    assert body["registry"]["status"] == reg.CANDIDATE
    assert body["registry"]["model_version"] == "1.1.0"
    assert body["registry"]["based_on"] == "application-incumbent:1.0.0"

    after = client.get(
        "/api/v1/scorecard/registry/application-incumbent?model_version=1.0.0",
        headers=headers()).json()
    assert after["status"] == reg.ACTIVE
    assert after["equation"] == before["equation"]
    assert after["intercept"] == before["intercept"]


@db
def test_an_equation_the_validator_rejects_is_not_filed(client, registered):
    """Recording it would put an equation the validator refused into the
    same table as the approved ones."""
    body = client.post(
        "/api/v1/scorecard/models/APPLICATION/candidate", headers=headers(),
        json=_proposal(record=True, terms=[
            # applicant_age is monitored for fairness and is not scoreable.
            {"variable": "applicant_age", "coefficient": -0.4},
        ])).json()
    assert body["validation"]["valid"] is False
    assert body["registry"]["recorded"] is False
    assert "blocking" in body["registry"]["why_not"]

    listed = client.get("/api/v1/scorecard/registry",
                        headers=headers()).json()
    assert listed["count"] == 6, "nothing was filed"

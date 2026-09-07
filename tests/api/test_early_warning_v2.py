"""The Early Warning V2 API surface: the actual scoring engine and monthly
domain, reachable over HTTP, RBAC-enforced, and wired into the platform's
existing RiskCase/Workflow substrate rather than a parallel one.

Requires the Early Warning V2 domain to have been built
(scripts/build_corporate_universe.py then scripts/build_early_warning_v2.py)
and a reachable PostgreSQL database; skips cleanly otherwise, following the
same `database_available()` convention the rest of the suite uses.
"""

from __future__ import annotations

import pytest

from backend.db.engine import get_session
from tests.conftest import database_available


def headers(role: str) -> dict[str, str]:
    return {"X-IPM-Role": role}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import create_app

    return TestClient(create_app())


@pytest.fixture(scope="module")
def domain_built(client) -> bool:
    r = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST"))
    return r.status_code == 200


@pytest.fixture(scope="module")
def seeded_user():
    """A real users row so workflow.send()'s foreign key is satisfiable."""
    if not database_available():
        pytest.skip("no reachable database")
    from backend.db.models import User

    with get_session() as session:
        existing = session.query(User).filter_by(username="ews_v2_test_user").first()
        if existing:
            return existing.id
        user = User(username="ews_v2_test_user", password_hash="x", role="ANALYST",
                    email="ews_v2_test_user@test.local")
        session.add(user)
        session.flush()
        return user.id


def _require_domain(domain_built):
    if not domain_built:
        pytest.skip("Early Warning V2 domain not built — run "
                    "scripts/build_corporate_universe.py then "
                    "scripts/build_early_warning_v2.py")


# ==================================================================== reads


def test_methodology_needs_no_data_build(client):
    """The methodology/lineage endpoints describe the seeded configuration,
    not the generated data — they must work even before any month is built."""
    r = client.get("/api/v1/early-warning/v2/methodology", headers=headers("VIEWER"))
    assert r.status_code == 200
    body = r.json()
    assert body["classifiers"]["count"] == 35
    assert body["triggers"]["count"] == 67
    assert body["signal_inventory"]["signal_count"] == 123


def test_methodology_never_hardcodes_matrix_or_notches(client):
    """Conflict A: no anchor-matrix / notch mechanism exists in the actual
    workbook, so the methodology response must not imply one."""
    body = client.get("/api/v1/early-warning/v2/methodology",
                       headers=headers("VIEWER")).json()
    assert "MIN(100, T&A score" in body["combination"]["formula"]
    assert "notch" not in body["combination"]["formula"].lower()


def test_lineage_covers_every_signal(client):
    r = client.get("/api/v1/early-warning/v2/lineage", headers=headers("VIEWER"))
    assert r.status_code == 200
    fields = r.json()["fields"]
    assert len(fields) >= 123


def test_overview_is_open_to_viewer_read_only(client):
    """EARLY_WARNING_VIEW deliberately includes VIEWER (mirroring
    BORROWER_360_VIEW) — viewing is open to all four roles; escalating,
    recording an action and editing the methodology are not."""
    r = client.get("/api/v1/early-warning/v2", headers=headers("VIEWER"))
    assert r.status_code in (200, 503)  # 503 only if the domain isn't built yet


def test_overview_returns_portfolio_shape(client, domain_built):
    _require_domain(domain_built)
    r = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST"))
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body and "trend" in body and "top_high_risk" in body
    assert body["summary"]["borrower_count"] > 0
    assert len(body["trend"]) >= 15  # at least 15 monthly snapshots, per the plan


def test_severity_distribution_sums_to_borrower_count(client, domain_built):
    _require_domain(domain_built)
    body = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    dist = body["summary"]["severity_distribution"]
    assert sum(d["borrower_count"] for d in dist) == body["summary"]["borrower_count"]


def test_top_high_risk_is_sorted_descending(client, domain_built):
    _require_domain(domain_built)
    body = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    scores = [r["ews_score"] for r in body["top_high_risk"]]
    assert scores == sorted(scores, reverse=True)


def test_segments_shape(client, domain_built):
    _require_domain(domain_built)
    r = client.get("/api/v1/early-warning/v2/segments", headers=headers("ANALYST"))
    assert r.status_code == 200
    assert len(r.json()["segments"]) > 0


def test_diagnose_is_explicitly_descriptive_not_predictive(client, domain_built):
    _require_domain(domain_built)
    body = client.get("/api/v1/early-warning/v2/diagnose", headers=headers("ANALYST")).json()
    assert "descriptive" in body["note"].lower()
    assert "not predict" in body["note"].lower()


def test_borrower_detail_404_for_unknown_customer(client, domain_built):
    _require_domain(domain_built)
    r = client.get("/api/v1/early-warning/v2/borrower/NOT-A-REAL-CUSTOMER",
                    headers=headers("ANALYST"))
    assert r.status_code == 404


def test_borrower_detail_shape(client, domain_built):
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]
    r = client.get(f"/api/v1/early-warning/v2/borrower/{customer_id}",
                    headers=headers("ANALYST"))
    assert r.status_code == 200
    body = r.json()
    assert body["latest"]["customer_id"] == customer_id
    assert len(body["history"]) >= 15
    assert "fired_signals" in body


# ============================================================= escalate/inform/action


def test_escalate_requires_recipient(client, domain_built):
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]
    r = client.post(f"/api/v1/early-warning/v2/borrower/{customer_id}/escalate",
                     headers=headers("ANALYST"), json={})
    assert r.status_code == 422


def test_escalate_refused_to_viewer(client, domain_built):
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]
    r = client.post(f"/api/v1/early-warning/v2/borrower/{customer_id}/escalate",
                     headers=headers("VIEWER"), json={"recipient_user_ids": [1]})
    assert r.status_code == 403


def test_escalate_creates_case_and_sends_one_message(client, domain_built, seeded_user):
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]

    r = client.post(f"/api/v1/early-warning/v2/borrower/{customer_id}/escalate",
                     headers=headers("ANALYST"),
                     json={"recipient_user_ids": [seeded_user], "message": "please review"})
    assert r.status_code == 200
    body = r.json()
    assert body["case_id"] > 0
    assert body["workflow_item"]["action"] == "review"
    assert body["workflow_item"]["recipients"][0]["user_id"] == seeded_user


def test_escalate_twice_reuses_the_same_case(client, domain_built, seeded_user):
    """about='early-warning-v2' dedupe: escalating the same borrower/period
    again updates the existing case rather than creating a duplicate."""
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][1]["customer_id"]

    r1 = client.post(f"/api/v1/early-warning/v2/borrower/{customer_id}/escalate",
                      headers=headers("ANALYST"), json={"recipient_user_ids": [seeded_user]})
    r2 = client.post(f"/api/v1/early-warning/v2/borrower/{customer_id}/inform",
                      headers=headers("ANALYST"), json={"recipient_user_ids": [seeded_user]})
    assert r1.json()["case_id"] == r2.json()["case_id"]


def test_inform_does_not_require_escalate_action(client, domain_built, seeded_user):
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][2]["customer_id"]
    r = client.post(f"/api/v1/early-warning/v2/borrower/{customer_id}/inform",
                     headers=headers("ANALYST"), json={"recipient_user_ids": [seeded_user]})
    assert r.status_code == 200
    assert r.json()["workflow_item"]["action"] == "fyi"


def test_record_action_does_not_require_prior_escalation(client, domain_built):
    """An analyst may record an action on a case that was never formally
    escalated — no existing WorkflowItem is required first."""
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][3]["customer_id"]
    r = client.post(f"/api/v1/early-warning/v2/borrower/{customer_id}/action",
                     headers=headers("ANALYST"), json={"action": "Cure plan requested"})
    assert r.status_code == 200
    assert r.json()["comment"]["body"].startswith("Action recorded")


# ============================================================= escalation matrix


def test_escalation_matrix_get_needs_no_data_build(client):
    r = client.get("/api/v1/early-warning/v2/escalation-matrix", headers=headers("VIEWER"))
    assert r.status_code == 200
    body = r.json()
    assert len(body["ladder"]) == 6
    assert len(body["specialist_routes"]) == 5


def test_escalation_matrix_edit_refused_to_analyst(client):
    body = client.get("/api/v1/early-warning/v2/escalation-matrix", headers=headers("VIEWER")).json()
    bundle = {k: v for k, v in body.items() if k not in ("version", "change_note")}
    r = client.put("/api/v1/early-warning/v2/escalation-matrix", headers=headers("ANALYST"),
                    json={"bundle": bundle, "change_note": "should be refused"})
    assert r.status_code == 403


def test_escalation_matrix_edit_creates_a_new_version_not_overwrite(client):
    before = client.get("/api/v1/early-warning/v2/escalation-matrix", headers=headers("VIEWER")).json()
    bundle = {k: v for k, v in before.items() if k not in ("version", "change_note")}

    r = client.put("/api/v1/early-warning/v2/escalation-matrix", headers=headers("ADMIN"),
                    json={"bundle": bundle, "change_note": "widen S3 routing"})
    assert r.status_code == 200
    after_version = r.json()["version"]
    assert after_version != before["version"] or before["version"] == "default"

    reread = client.get("/api/v1/early-warning/v2/escalation-matrix", headers=headers("VIEWER")).json()
    assert reread["version"] == after_version
    assert reread["change_note"] == "widen S3 routing"


def test_record_action_refused_to_viewer(client, domain_built):
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]
    r = client.post(f"/api/v1/early-warning/v2/borrower/{customer_id}/action",
                     headers=headers("VIEWER"), json={"action": "x"})
    assert r.status_code == 403

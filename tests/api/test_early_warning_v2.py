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
    assert body["classifiers"]["count"] == 23
    assert body["triggers"]["count"] == 67
    assert body["signal_inventory"]["signal_count"] == 123


def test_methodology_reflects_the_matrix_and_notch_model(client):
    """The corrected workbook's actual combination mechanism — a published
    5x5 anchor matrix, then five +/-1 notches — must be what the
    methodology response describes, not a multiplicative shortcut."""
    body = client.get("/api/v1/early-warning/v2/methodology",
                       headers=headers("VIEWER")).json()
    assert "matrix" in body["combination"]["formula"].lower()
    assert "notch" in body["combination"]["formula"].lower()
    assert len(body["matrix"]) == 5
    assert len(body["notches"]["keys"]) == 5


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


def test_escalate_addresses_the_rung_the_matrix_chose(client, domain_built):
    """The caller does not have to know who decides. The matrix does.

    This used to assert a 422 for a request with no recipient, which was the
    behaviour: the matrix chose the rung, the urgency and the parallel
    notifications, and the endpoint still demanded that the caller name
    somebody, because nothing could turn "Head of Credit Risk" into an
    inbox. So an escalation either carried a hard-coded demo user — not a
    control — or could not be sent.

    A rung now addresses the team named for it. Where the directory holds
    that team the escalation goes there; where it does not, the refusal says
    which rung and which team, which is a thing somebody can act on.
    """
    _require_domain(domain_built)
    from backend.early_warning import escalation as esc

    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]
    r = client.post(f"/api/v1/early-warning/v2/borrower/{customer_id}/escalate",
                     headers=headers("ANALYST"), json={})
    assert r.status_code in (200, 422), r.text

    if r.status_code == 200:
        body = r.json()
        assert body["routing"]["escalated_to"], "the matrix chose no rung"
        item = body["workflow_item"]
        assert item.get("teams") or item.get("recipients"), (
            "the escalation was sent to nobody")
    else:
        detail = r.json()["detail"]
        assert detail["error"] == "no_recipient"
        # It names the rung and the team, not just that something is missing.
        assert detail["routed_to"], detail
        assert detail["expected_teams"], detail
        for code in detail["routed_to"]:
            assert esc.role_of(code) in detail["message"], detail["message"]


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


def test_escalate_routes_through_the_matrix(client, domain_built, seeded_user):
    """The matrix decides the rung, and it never used to be consulted.

    Escalation went exactly where the caller said, carried no clock, and
    never told the roles the matrix says to notify in parallel. Severity
    decides urgency and materiality decides altitude — neither was applied.
    """
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    row = overview["top_high_risk"][0]

    r = client.post(f"/api/v1/early-warning/v2/borrower/{row['customer_id']}/escalate",
                     headers=headers("ANALYST"),
                     json={"recipient_user_ids": [seeded_user]})
    assert r.status_code == 200
    routing = r.json()["routing"]
    assert routing["severity"] == row["ews_band"]
    assert routing["escalated_to"], "the matrix named nobody"
    # The rung is resolved to a real title rather than left as a code.
    assert routing["escalated_to_roles"] and routing["escalated_to_roles"][0] != \
        routing["escalated_to"][0]


def test_inform_does_not_erase_the_escalation_record(client, domain_built,
                                                     seeded_user):
    """Inform says it changes nothing. It has to actually change nothing.

    The readiness run escalated an obligor, then sent an FYI on the same
    obligor, and the case came back with no escalation version and no
    routing cell — because Inform refreshes the case, and the shared case
    machinery replaces `evidence` wholesale on a refresh. That is right for
    the fields describing the score, which are recomputed and where the
    newest reading should win. It is wrong for the escalation record, which
    is history: the one thing that says which matrix version routed this
    case and to which cell was silently destroyed by the operation whose
    entire contract is that it does not touch the case.
    """
    from backend.db.engine import get_session
    from backend.models.platform import RiskCase

    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]

    escalated = client.post(
        f"/api/v1/early-warning/v2/borrower/{customer_id}/escalate",
        headers=headers("ANALYST"), json={"recipient_user_ids": [seeded_user]})
    assert escalated.status_code == 200
    case_key = escalated.json()["case_key"]

    def evidence() -> dict:
        with get_session() as session:
            found = session.query(RiskCase).filter(
                RiskCase.case_key == case_key).first()
            return dict((found.evidence if found else None) or {})

    after_escalate = evidence()
    assert after_escalate.get("escalation_version"), after_escalate
    assert after_escalate.get("routing"), after_escalate

    informed = client.post(
        f"/api/v1/early-warning/v2/borrower/{customer_id}/inform",
        headers=headers("ANALYST"),
        json={"recipient_user_ids": [seeded_user], "message": "FYI"})
    assert informed.status_code == 200

    after_inform = evidence()
    assert after_inform.get("escalation_version") == \
        after_escalate["escalation_version"], (
            "Inform erased which matrix version routed the case")
    assert after_inform.get("routing") == after_escalate["routing"], (
        "Inform erased the routing cell the case was escalated to")


def test_escalating_twice_still_leaves_one_case(client, domain_built,
                                                 seeded_user):
    """Two escalations and an FYI on the same obligor are one case."""
    from backend.db.engine import get_session
    from backend.models.platform import RiskCase

    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]

    for _ in range(2):
        assert client.post(
            f"/api/v1/early-warning/v2/borrower/{customer_id}/escalate",
            headers=headers("ANALYST"),
            json={"recipient_user_ids": [seeded_user]}).status_code == 200
    assert client.post(
        f"/api/v1/early-warning/v2/borrower/{customer_id}/inform",
        headers=headers("ANALYST"),
        json={"recipient_user_ids": [seeded_user], "message": "FYI"}
    ).status_code == 200

    with get_session() as session:
        found = session.query(RiskCase).filter(
            RiskCase.entity_id == customer_id).all()
    assert len(found) == 1, [c.case_key for c in found]


def test_escalate_stamps_the_decision_sla_as_a_due_date(client, domain_built,
                                                         seeded_user):
    """A control whose clock never starts is a report. The SLAs lived in the
    matrix as literals and nothing ever turned one into a date, so no early
    warning escalation could ever appear in the 'due soon' list."""
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]
    r = client.post(f"/api/v1/early-warning/v2/borrower/{customer_id}/escalate",
                     headers=headers("ANALYST"),
                     json={"recipient_user_ids": [seeded_user]})
    body = r.json()
    if body["routing"]["decision_sla_days"] is None:
        pytest.skip("this severity carries no decision SLA")
    assert body["workflow_item"]["due_at"], "no clock was stamped"


def test_the_case_records_which_matrix_routed_it(client, domain_built, seeded_user):
    """A case raised under one version must not later be read against
    another. Lineage promised to record this and nothing wrote it."""
    _require_domain(domain_built)
    from backend.db.engine import get_session
    from backend.models.platform import RiskCase

    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]
    r = client.post(f"/api/v1/early-warning/v2/borrower/{customer_id}/escalate",
                     headers=headers("ANALYST"),
                     json={"recipient_user_ids": [seeded_user]})
    body = r.json()
    assert body["escalation_version"]

    with get_session() as session:
        case = session.get(RiskCase, body["case_id"])
        evidence = case.evidence or {}
        assert evidence.get("escalation_version") == body["escalation_version"]
        assert evidence.get("routing", {}).get("escalated_to")
        # The FK existed and was never set, so a case could not point back at
        # the message it raised.
        assert case.workflow_item_id == body["workflow_item"]["id"]


def test_the_actions_route_recommends_from_the_library(client, domain_built):
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]
    r = client.get(f"/api/v1/early-warning/v2/borrower/{customer_id}/actions",
                    headers=headers("ANALYST"))
    assert r.status_code == 200
    body = r.json()
    assert body["actions"], "no action was recommended for a high-risk obligor"
    for action in body["actions"]:
        assert action["owner"], action
        assert action["timeframe"], action
        assert action["evidence_to_close"], action
    assert body["priority_action"] in body["actions"]


def test_the_escalation_note_is_drafted_from_the_facts(client, domain_built):
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    row = overview["top_high_risk"][0]
    r = client.post(
        f"/api/v1/early-warning/v2/borrower/{row['customer_id']}/escalation-note",
        headers=headers("ANALYST"), json={"case_key": "EWS-TEST"})
    assert r.status_code == 200
    note = r.json()["note"]
    # Position, driver, recommendation with an owner, and the case.
    assert row["customer_name"] in note
    assert "anchor" in note
    assert "Evidence to close:" in note
    assert "EWS-TEST" in note


def test_recording_an_action_persists_more_than_prose(client, domain_built,
                                                       seeded_user):
    """Owner, due date and closing evidence used to be flattened into a
    comment, so nothing could ask which actions were open or overdue."""
    _require_domain(domain_built)
    from backend.db.engine import get_session
    from backend.models.platform import RiskCase

    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][4]["customer_id"]
    r = client.post(f"/api/v1/early-warning/v2/borrower/{customer_id}/action",
                     headers=headers("ANALYST"),
                     json={"action": "Reserve rights on the breach",
                           "owner_user_id": seeded_user,
                           "due_at": "2026-07-15T00:00:00+00:00",
                           "closing_evidence_required": "Reservation of rights letter"})
    assert r.status_code == 200
    with get_session() as session:
        case = session.get(RiskCase, r.json()["case_id"])
        recorded = (case.evidence or {}).get("actions") or []
        assert recorded, "the action was written as prose only"
        assert recorded[-1]["closing_evidence_required"] == \
            "Reservation of rights letter"
        assert case.owner_id == seeded_user


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


# ==================================================================== reports


def test_borrower_report_download(client, domain_built):
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]
    r = client.get(f"/api/v1/early-warning/v2/reports/borrower/{customer_id}",
                    headers=headers("ANALYST"))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert len(r.content) > 10_000


def test_borrower_report_refused_to_viewer(client, domain_built):
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    customer_id = overview["top_high_risk"][0]["customer_id"]
    r = client.get(f"/api/v1/early-warning/v2/reports/borrower/{customer_id}",
                    headers=headers("VIEWER"))
    assert r.status_code == 403


def test_portfolio_report_download(client, domain_built):
    _require_domain(domain_built)
    r = client.get("/api/v1/early-warning/v2/reports/portfolio", headers=headers("ANALYST"))
    assert r.status_code == 200
    assert len(r.content) > 10_000


def test_segment_report_download(client, domain_built):
    _require_domain(domain_built)
    segments = client.get("/api/v1/early-warning/v2/segments", headers=headers("ANALYST")).json()
    segment = segments["segments"][0]["segment"]
    r = client.get(f"/api/v1/early-warning/v2/reports/segment/{segment}", headers=headers("ANALYST"))
    assert r.status_code == 200


def test_all_segment_report_download(client, domain_built):
    """Every segment on its own terms, which the portfolio report's single
    segment table cannot give: it answers which is worst and nothing else."""
    _require_domain(domain_built)
    r = client.get("/api/v1/early-warning/v2/reports/segments",
                    headers=headers("ANALYST"))
    assert r.status_code == 200
    assert len(r.content) > 50_000
    assert "all-segments" in r.headers["content-disposition"]


def test_multi_borrower_report_download(client, domain_built):
    _require_domain(domain_built)
    overview = client.get("/api/v1/early-warning/v2", headers=headers("ANALYST")).json()
    ids = [r["customer_id"] for r in overview["top_high_risk"][:5]]
    r = client.post("/api/v1/early-warning/v2/reports/borrowers", headers=headers("ANALYST"),
                     json={"customer_ids": ids})
    assert r.status_code == 200
    assert len(r.content) > 10_000


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

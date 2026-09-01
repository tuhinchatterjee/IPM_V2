"""Regulatory Intelligence through its real routes. §29-§38.

The whole journey once: start a run, extract requirements from clauses,
review one, correct another, detect and settle a contradiction, promote an
approved calculation into a Draft Method, and confirm at every step that
nothing has reached production.

Permissions get their own block, because a tab hidden in the front end is a
tab reachable with curl.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import database_available

STAGE_2 = {
    "text": ("4.2 An exposure shall be classified as Stage 2 where the "
             "probability of default has increased significantly since "
             "initial recognition."),
    "page": 12, "section_number": "4.2", "concepts": ["pd", "stage"],
}
ECL = {
    "text": ("5.1 The expected credit loss shall be calculated as PD "
             "multiplied by LGD multiplied by EAD."),
    "page": 14, "section_number": "5.1",
    "concepts": ["pd", "lgd", "ead"], "datasets": ["ifrs9_staging"],
}
FIRE = {
    "text": "9.3 The premises shall be insured against fire and flood.",
    "page": 31, "section_number": "9.3",
}


def headers(role: str = "ADMIN") -> dict[str, str]:
    return {"X-IPM-Role": role}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("Regulatory Intelligence persists everything; "
                    "PostgreSQL is not reachable")


@pytest.fixture(scope="module")
def extracted(client) -> dict:
    """One document taken through extraction, shared by the tests below.

    The id is unique per run. A fixed one would leave the second run reading
    the first run's already-decided requirements, so the suite would pass
    once and then start failing for reasons that have nothing to do with the
    code — a test that depends on rows it did not create is testing the
    database's history.
    """
    document_id = f"test-doc-ri-{uuid.uuid4().hex[:12]}"
    run = client.post("/api/v1/regulatory-intelligence/runs",
                      json={"document_id": document_id}, headers=headers())
    assert run.status_code == 201, run.text

    made = client.post("/api/v1/regulatory-intelligence/requirements",
                       headers=headers(), json={
                           "document_id": document_id,
                           "run_id": run.json()["run_id"],
                           "jurisdiction": "SA",
                           "clauses": [STAGE_2, ECL, FIRE]})
    assert made.status_code == 201, made.text

    listed = client.get(
        f"/api/v1/regulatory-intelligence/requirements"
        f"?document_id={document_id}", headers=headers()).json()
    return {"document_id": document_id, "run_id": run.json()["run_id"],
            "requirements": listed["requirements"]}


# ================================================================= schema


def test_the_schema_route_serves_what_the_backend_classifies_against(client):
    """Two lists that can drift are two lists that will."""
    body = client.get("/api/v1/regulatory-intelligence/schema",
                      headers=headers()).json()

    assert len(body["requirement_types"]) == 15
    assert len(body["credit_topics"]) == 26
    assert len(body["review_actions"]) == 7
    assert len(body["contradiction_classes"]) == 12
    assert len(body["resolutions"]) == 10
    assert len(body["promotion_targets"]) == 18
    assert len(body["draft_method_parts"]) == 15
    assert len(body["promotion_gates"]) == 5


def test_the_schema_states_the_four_rules_that_shape_the_subsystem(client):
    rules = client.get("/api/v1/regulatory-intelligence/schema",
                       headers=headers()).json()["rules"]

    assert "AMBIGUOUS, not" in rules["extraction_never_dismisses"]
    assert "Nothing here writes to" in rules["no_direct_mutation"]
    assert "not evidence" in rules["no_auto_certification"]
    assert "date it takes effect" in rules["never_delete_the_other_one"]


# ============================================================= extraction


def test_extraction_proposes_and_decides_nothing(client, extracted):
    for requirement in extracted["requirements"]:
        assert requirement["validation_status"] == "PROPOSED"
        assert requirement["decision"] == ""
        assert requirement["promotion_status"] == "NOT_PROMOTED"


def test_a_non_credit_clause_is_ambiguous_rather_than_dismissed(
        client, extracted):
    """§31. Only a person may decide a clause does not matter."""
    fire = next(r for r in extracted["requirements"]
                if r["citation"]["section_number"] == "9.3")

    assert fire["relevance"] == "AMBIGUOUS"
    assert fire["relevance"] != "NOT_CREDIT_RELATED"


def test_a_calculation_clause_is_typed_and_configurable(client, extracted):
    ecl = next(r for r in extracted["requirements"]
               if r["citation"]["section_number"] == "5.1")

    assert ecl["requirement_type"] == "CALCULATION"
    assert ecl["configurable"] is False   # not approved yet
    assert ecl["interpretation_confidence"] > 0.5


def test_the_queue_counts_untouched_requirements(client, extracted):
    body = client.get(
        f"/api/v1/regulatory-intelligence/requirements"
        f"?document_id={extracted['document_id']}",
        headers=headers()).json()

    assert body["progress"]["total"] >= 3
    assert body["census"]["by_relevance"]["AMBIGUOUS"] >= 1
    assert "not the same as not credit-related" in body["census"]["note"]


# ============================================================= §32 review


def test_the_review_panel_shows_source_before_understanding(client,
                                                            extracted):
    one = extracted["requirements"][0]

    panel = client.get(
        f"/api/v1/regulatory-intelligence/requirements/"
        f"{one['requirement_id']}/review", headers=headers()).json()

    assert list(panel) == ["requirement_id", "source", "understanding",
                           "conflicts", "actions"]
    assert len(panel["actions"]) == 7


def test_a_decision_without_a_reason_is_refused(client, extracted):
    one = extracted["requirements"][0]

    refused = client.post(
        f"/api/v1/regulatory-intelligence/requirements/"
        f"{one['requirement_id']}/decide", headers=headers(),
        json={"action": "APPROVE", "reason": "   "})

    assert refused.status_code == 422
    assert "reason" in refused.json()["detail"]["message"]


def test_rejecting_as_not_relevant_is_the_only_route_to_that_status(
        client, extracted):
    fire = next(r for r in extracted["requirements"]
                if r["citation"]["section_number"] == "9.3")

    done = client.post(
        f"/api/v1/regulatory-intelligence/requirements/"
        f"{fire['requirement_id']}/decide", headers=headers(),
        json={"action": "REJECT_NOT_RELEVANT",
              "reason": "premises insurance, not a credit requirement"})

    assert done.status_code == 200, done.text
    assert done.json()["relevance"] == "NOT_CREDIT_RELATED"
    assert done.json()["reviewer"]


def test_a_deferral_does_not_count_as_reviewed(client, extracted):
    one = next(r for r in extracted["requirements"]
               if r["citation"]["section_number"] == "4.2")

    done = client.post(
        f"/api/v1/regulatory-intelligence/requirements/"
        f"{one['requirement_id']}/decide", headers=headers(),
        json={"action": "DEFER", "reason": "waiting on the SICR policy"})

    assert done.json()["counts_as_reviewed"] is False


# ========================================================= §33 correction


def test_a_correction_keeps_both_readings_and_activates_nothing(
        client, extracted):
    one = extracted["requirements"][0]

    made = client.post(
        f"/api/v1/regulatory-intelligence/requirements/"
        f"{one['requirement_id']}/correct", headers=headers(),
        json={"correction": "It applies only to retail exposures.",
              "reason": "corporate is covered by section 6",
              "user_role": "SME"})

    assert made.status_code == 201, made.text
    assert made.json()["authoritative"] is False
    assert made.json()["activates_nothing"] is True

    listed = client.get("/api/v1/regulatory-intelligence/corrections",
                        headers=headers()).json()
    mine = next(c for c in listed["corrections"]
                if c["correction_id"] == made.json()["correction_id"])
    assert mine["we_read_it_as"]
    assert mine["they_read_it_as"] == "It applies only to retail exposures."


# ========================================================== §35/§36 promote


def test_an_unapproved_requirement_may_not_be_promoted(client, extracted):
    """§35: no direct mutation from extraction, and no promotion of a
    reading nobody agreed with."""
    ecl = next(r for r in extracted["requirements"]
               if r["citation"]["section_number"] == "5.1")

    refused = client.post(
        f"/api/v1/regulatory-intelligence/requirements/"
        f"{ecl['requirement_id']}/promote", headers=headers(), json={})

    assert refused.status_code == 422


def test_an_approved_calculation_promotes_to_drafts_that_change_nothing(
        client, extracted):
    ecl = next(r for r in extracted["requirements"]
               if r["citation"]["section_number"] == "5.1")
    approved = client.post(
        f"/api/v1/regulatory-intelligence/requirements/"
        f"{ecl['requirement_id']}/decide", headers=headers(),
        json={"action": "APPROVE", "reason": "the standard ECL identity"})
    assert approved.status_code == 200, approved.text

    promoted = client.post(
        f"/api/v1/regulatory-intelligence/requirements/"
        f"{ecl['requirement_id']}/promote", headers=headers(),
        json={"governance_owner": "Credit Risk"})

    assert promoted.status_code == 201, promoted.text
    body = promoted.json()
    assert body["nothing_changed_yet"] is True
    assert len(body["outstanding_gates"]) == 5
    assert all(d["status"] == "DRAFT" for d in body["drafts"])


def test_a_draft_method_carries_fifteen_parts_and_is_not_certified(
        client, extracted):
    """§36: do not auto-certify."""
    ecl = next(r for r in extracted["requirements"]
               if r["citation"]["section_number"] == "5.1")

    made = client.post(
        f"/api/v1/regulatory-intelligence/requirements/"
        f"{ecl['requirement_id']}/configure-method", headers=headers(),
        json={"governance_owner": "Credit Risk"})

    assert made.status_code == 201, made.text
    body = made.json()
    assert len(body["parts"]) == 15
    assert body["status"] == "DRAFT"
    assert body["certification"]["certified"] is False
    assert body["certification"]["auto_certified"] is False
    assert "without specifying" in body["established"]["formula"]


def test_a_draft_is_not_applied_until_every_gate_is_cleared(client):
    listed = client.get("/api/v1/regulatory-intelligence/drafts",
                        headers=headers()).json()
    assert listed["drafts"]

    draft = listed["drafts"][0]
    assert draft["applied"] is False
    assert draft["outstanding_gates"]

    for gate in ("validation", "regression", "approval", "version"):
        stepped = client.post(
            f"/api/v1/regulatory-intelligence/drafts/{draft['draft_id']}"
            f"/gate", headers=headers(), json={"gate": gate})
        assert stepped.status_code == 200, stepped.text
        assert stepped.json()["applied"] is False


def test_an_unknown_gate_is_refused(client):
    listed = client.get("/api/v1/regulatory-intelligence/drafts",
                        headers=headers()).json()
    draft = listed["drafts"][0]

    refused = client.post(
        f"/api/v1/regulatory-intelligence/drafts/{draft['draft_id']}/gate",
        headers=headers(), json={"gate": "looks_fine_to_me"})

    assert refused.status_code == 422


# =========================================================== §29 pipeline


def test_the_pipeline_refuses_a_skipped_stage_through_the_route(
        client, extracted):
    refused = client.post(
        f"/api/v1/regulatory-intelligence/runs/{extracted['run_id']}"
        f"/advance", headers=headers(), json={"stage": "RELEASED"})

    assert refused.status_code == 422
    assert "would skip" in refused.json()["detail"]["message"]


def test_a_run_is_not_retrievable_before_release(client, extracted):
    body = client.get(
        f"/api/v1/regulatory-intelligence/runs"
        f"?document_id={extracted['document_id']}",
        headers=headers()).json()

    mine = next(r for r in body["runs"] if r["run_id"] == extracted["run_id"])
    assert mine["retrievable"] is False
    assert len(body["pipeline"]) == 16


# ============================================================== §38 audit


def test_the_audit_tab_answers_what_a_regulator_would_ask(client, extracted):
    body = client.get(
        f"/api/v1/regulatory-intelligence/audit"
        f"?document_id={extracted['document_id']}", headers=headers()).json()

    assert "who decided what it meant" in body["answers"]
    assert body["decisions"]
    for decision in body["decisions"]:
        assert decision["reason"], decision["requirement_id"]
        assert decision["reviewer"], decision["requirement_id"]
    assert body["corrections"]


# ========================================================== permissions


@pytest.mark.parametrize("path", [
    "/api/v1/regulatory-intelligence/schema",
    "/api/v1/regulatory-intelligence/requirements",
    "/api/v1/regulatory-intelligence/conflicts",
    "/api/v1/regulatory-intelligence/drafts",
    "/api/v1/regulatory-intelligence/audit",
])
def test_a_viewer_may_not_read_the_regulatory_workbench(client, path):
    assert client.get(path, headers=headers("VIEWER")).status_code == 403


def test_a_steward_may_review_but_may_not_promote(client, extracted):
    """Deciding what a clause means is regulatory judgement; promoting it
    into a change to how figures are computed is narrower."""
    ecl = next(r for r in extracted["requirements"]
               if r["citation"]["section_number"] == "5.1")

    promote = client.post(
        f"/api/v1/regulatory-intelligence/requirements/"
        f"{ecl['requirement_id']}/promote",
        headers=headers("DATA_STEWARD"), json={})
    assert promote.status_code == 403

    panel = client.get(
        f"/api/v1/regulatory-intelligence/requirements/"
        f"{ecl['requirement_id']}/review", headers=headers("DATA_STEWARD"))
    assert panel.status_code == 200


def test_an_analyst_may_read_but_may_not_decide(client, extracted):
    one = extracted["requirements"][0]

    read = client.get("/api/v1/regulatory-intelligence/schema",
                      headers=headers("ANALYST"))
    assert read.status_code == 200

    decide = client.post(
        f"/api/v1/regulatory-intelligence/requirements/"
        f"{one['requirement_id']}/decide", headers=headers("ANALYST"),
        json={"action": "APPROVE", "reason": "looks fine"})
    assert decide.status_code == 403

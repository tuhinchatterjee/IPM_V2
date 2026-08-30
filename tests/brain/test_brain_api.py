"""The Brain Center through its real routes. §15-§26.

The suite that matters most, because everything here is reachable with curl.
A tab hidden in the front end is a tab an attacker opens anyway, so the
permission tests assert against the HTTP status rather than against what a
screen would render.

The round trip is the other half: build a package through the export route,
hand it straight back through the import route as though it came from
another installation, and prove it lands in quarantine with nothing
activated.
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available


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
        pytest.skip("The Brain Center persists everything; PostgreSQL is "
                    "not reachable")


# ================================================================ reading


def test_the_overview_keeps_captured_approved_and_activated_apart(client):
    """More capture is not improvement. A screen that added the three
    numbers would report an installation that has learned nothing as one
    that has learned a great deal."""
    body = client.get("/api/v1/brain/overview", headers=headers()).json()

    learning = body["learning"]
    assert "by_status" in learning or "captured" in learning
    assert len(body["dimensions"]) == 6
    assert body["known_limitations"]
    assert any("not added together" in limit
               for limit in body["known_limitations"])


def test_the_ledger_names_every_portability_condition(client):
    """"Not eligible" tells a reviewer nothing. §14's ten conditions are
    listed so a blocked entry can say which one blocked it."""
    body = client.get("/api/v1/brain/ledger", headers=headers()).json()

    assert len(body["eligibility_conditions"]) == 10
    assert all(c["check"] and c["means"]
               for c in body["eligibility_conditions"])
    assert "NON_PORTABLE" in body["portability_states"]


def test_the_security_tab_states_what_is_enforced_not_what_is_intended(
        client):
    body = client.get("/api/v1/brain/security", headers=headers()).json()

    assert body["limits"]["max_entries"] > 0
    assert body["limits"]["max_compression_ratio"] > 1
    assert len(body["enforced"]) >= 8
    assert "may be inspected and evaluated" in body["untrusted_signer_policy"]
    # An allowlist, not a blocklist. A blocklist is a list of the formats
    # somebody thought of.
    assert ".json" in body["allowed_formats"]
    assert ".py" not in body["allowed_formats"]


def test_the_export_kinds_say_what_each_package_is_for(client):
    body = client.get("/api/v1/brain/export/kinds", headers=headers()).json()

    assert {k["id"] for k in body["kinds"]} == {"cpbrain", "cplearn", "cpdev"}
    learning = next(k for k in body["kinds"] if k["id"] == "cplearn")
    assert "baseline_release_id" in learning["requires"]
    assert body["exportable_case_status"] == "HUMAN_APPROVED"


# ============================================================ permissions


@pytest.mark.parametrize("path", [
    "/api/v1/brain/overview",
    "/api/v1/brain/ledger",
    "/api/v1/brain/installations",
    "/api/v1/brain/security",
])
def test_an_ordinary_viewer_may_not_read_the_brain_center(client, path):
    assert client.get(path, headers=headers("VIEWER")).status_code == 403


def test_a_steward_may_export_but_may_not_activate(client):
    """§16 puts a measured evaluation before approval precisely so the
    person who runs the numbers and the person who accepts them can be
    different people."""
    activate = client.post("/api/v1/brain/imports/nope/activate",
                           json={}, headers=headers("DATA_STEWARD"))
    assert activate.status_code == 403

    kinds = client.get("/api/v1/brain/export/kinds",
                       headers=headers("DATA_STEWARD"))
    assert kinds.status_code == 200


def test_only_an_administrator_touches_the_trusted_signer_registry(client):
    """§26: trust is a decision a named person records."""
    response = client.post(
        "/api/v1/brain/security/signers",
        json={"key_id": "k", "reason": "because"},
        headers=headers("DATA_STEWARD"))

    assert response.status_code == 403


def test_a_signer_without_a_stated_reason_is_refused(client):
    """Trust nobody had to justify is trust nobody can review, and this is
    the table an auditor reads first."""
    response = client.post(
        "/api/v1/brain/security/signers",
        json={"key_id": "key-unjustified", "reason": "   "},
        headers=headers())

    assert response.status_code == 422


# ========================================================== the round trip


@pytest.fixture(scope="module")
def exported(client) -> dict:
    response = client.post("/api/v1/brain/export", headers=headers(), json={
        "kind": "cpbrain",
        "brain_id": "brain-roundtrip",
        "brain_name": "Round Trip Brain",
        "brain_version": "1.0.0",
        "known_limitations": ["Built in a test; measures nothing."],
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_an_export_records_what_it_actually_wrote(client, exported):
    assert exported["sha256"]
    assert exported["size_bytes"] > 0
    assert exported["entry_count"] > 3


def test_a_developer_bundle_is_downloadable_and_carries_its_readme(client):
    import io
    import zipfile

    built = client.post("/api/v1/brain/export", headers=headers(), json={
        "kind": "cpdev", "brain_id": "brain-dev",
        "brain_name": "Dev Bundle", "brain_version": "1.0.0",
    })
    assert built.status_code == 201, built.text

    download = client.get(built.json()["download"], headers=headers())
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        names = archive.namelist()
    assert "README_FOR_CLAUDE_CODE.md" in names
    assert not any(n.endswith((".py", ".sh", ".pkl", ".exe")) for n in names)


def test_a_package_taken_back_in_lands_in_quarantine_and_activates_nothing(
        client, exported):
    """§16's first sentence, proved through the route rather than asserted
    in a docstring."""
    download = client.get(exported["download"], headers=headers())
    assert download.status_code == 200

    received = client.post(
        "/api/v1/brain/imports", headers=headers(),
        files={"file": ("candidate.cpbrain", download.content,
                        "application/zip")})
    assert received.status_code == 201, received.text
    body = received.json()

    assert body["activated"] is False
    assert body["stage"] == "UPLOADED"
    assert body["state"] == "IN_QUARANTINE"

    listed = client.get("/api/v1/brain/imports", headers=headers()).json()
    mine = next(i for i in listed["imports"]
                if i["import_id"] == body["import_id"])
    assert mine["retrievable"] is False


def test_an_unevaluated_candidate_may_not_be_activated(client, exported):
    """Approving without measured lift is approving a claim."""
    download = client.get(exported["download"], headers=headers())
    received = client.post(
        "/api/v1/brain/imports", headers=headers(),
        files={"file": ("candidate.cpbrain", download.content,
                        "application/zip")}).json()

    detail = client.get(f"/api/v1/brain/imports/{received['import_id']}",
                        headers=headers()).json()
    assert detail["may_activate"] is False
    assert detail["activation_blocked_by"]

    refused = client.post(
        f"/api/v1/brain/imports/{received['import_id']}/activate",
        json={}, headers=headers())
    assert refused.status_code == 422
    assert "may not be activated" in refused.json()["detail"]["message"]


def test_the_pipeline_refuses_a_skipped_stage_through_the_route(
        client, exported):
    download = client.get(exported["download"], headers=headers())
    received = client.post(
        "/api/v1/brain/imports", headers=headers(),
        files={"file": ("candidate.cpbrain", download.content,
                        "application/zip")}).json()

    skipped = client.post(
        f"/api/v1/brain/imports/{received['import_id']}/advance",
        json={"stage": "STAGED"}, headers=headers())

    assert skipped.status_code == 422


def test_compatibility_is_measured_against_the_live_registries(
        client, exported):
    """§17. Checked against what this installation has, not against what the
    package says about itself."""
    download = client.get(exported["download"], headers=headers())
    received = client.post(
        "/api/v1/brain/imports", headers=headers(),
        files={"file": ("candidate.cpbrain", download.content,
                        "application/zip")}).json()

    report = client.post(
        f"/api/v1/brain/imports/{received['import_id']}/compatibility",
        headers=headers())
    assert report.status_code == 200, report.text
    body = report.json()
    assert "compatible" in body
    assert body["receiver_app_version"]


def test_the_lift_tab_says_nothing_was_measured_rather_than_showing_zero(
        client, exported):
    """Zero improvement and no measurement look identical on a chart and
    mean opposite things."""
    download = client.get(exported["download"], headers=headers())
    received = client.post(
        "/api/v1/brain/imports", headers=headers(),
        files={"file": ("candidate.cpbrain", download.content,
                        "application/zip")}).json()

    body = client.get(f"/api/v1/brain/lift/{received['import_id']}",
                      headers=headers()).json()

    assert body["measured"] is False
    assert "not a neutral result" in body["note"]
    assert body["rules"]["minimum_cases"] >= 30
    assert body["rules"]["critical_regression_overrides_average"] is True


def test_a_candidate_deleted_before_activation_keeps_its_record(
        client, exported):
    """§23: the bytes go, the record of what was uploaded does not."""
    download = client.get(exported["download"], headers=headers())
    received = client.post(
        "/api/v1/brain/imports", headers=headers(),
        files={"file": ("candidate.cpbrain", download.content,
                        "application/zip")}).json()

    deleted = client.post(
        f"/api/v1/brain/imports/{received['import_id']}/delete",
        json={"reason": "uploaded by mistake"}, headers=headers())
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["record_kept"] is True

    still_there = client.get(
        f"/api/v1/brain/imports/{received['import_id']}", headers=headers())
    assert still_there.status_code == 200
    assert still_there.json()["state"] == "DELETED"


# =============================================================== §24 history


def test_the_installation_history_answers_section_24s_question(client):
    body = client.get("/api/v1/brain/installations",
                      headers=headers()).json()

    assert "how much improvement did it produce" in body["answers"]
    for row in body["installations"]:
        # Every row answers by itself, including the rows that cannot.
        assert row["improvement"]

"""
The AI validation surface — what the AI POWERED control is allowed to say.

This subsystem exists because the product once reported full intelligence while
every question was being answered by the deterministic reader. So the tests here
are almost entirely about honesty rather than mechanics: that an offline run is
not dressed up as an AI grade, that a case which never reached the model fails
whatever its figures say, and that no endpoint will hand out a benchmark's
expected answer before the case has been executed.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.engine.helpers import FACILITY


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built — run `python scripts/build_data_lake.py`")


def test_status_reports_provider_build_and_benchmark_size(client):
    body = client.get("/api/v1/ai/status").json()

    assert body["ai"]["state"] in {"offline", "configured", "connected", "degraded"}
    assert body["build"]["source_sha"] or body["build"]["image_sha"] == ""
    assert body["benchmark_count"] >= 75, "the library is meant to be large enough to draw from"
    assert body["benchmark_turns"] >= body["benchmark_count"]
    assert body["can_run"] is True


def test_status_never_carries_a_key(client):
    """The telemetry module must not become a place a key can be read from."""
    import json

    raw = json.dumps(client.get("/api/v1/ai/status").json())

    assert "sk-" not in raw
    assert "api_key" not in raw.lower()


def test_a_run_that_never_reached_the_model_is_not_an_ai_grade(client):
    """The failure this whole subsystem was built for.

    Offline, the governed reader can answer every benchmark case perfectly and
    the run still must not claim an AI score: the band is OFFLINE, the label
    stops saying AI POWERED, and each case says in words why it failed.
    """
    body = client.post("/api/v1/ai/validate", headers={"X-IPM-Role": "ANALYST"}).json()

    assert body["ai_state"] == "offline"
    assert body["band"] == "OFFLINE"
    assert body["label"] == "AI OFFLINE"
    assert body["live_cases"] == 0
    assert body["case_count"] == len(body["cases"]) >= 1
    assert body["failed"] == body["case_count"]
    assert any("not the AI" in note for note in body["notes"])

    for case in body["cases"]:
        assert case["used_fallback"] is True
        assert case["verdict"] == "FAIL"
        assert any("without reaching the live model" in line
                   for line in case["deductions"])


def test_every_case_carries_its_turns_and_its_reference(client):
    """A score nobody can inspect is a claim, not evidence.

    Not every turn has a reference: a case that tests a refusal has nothing to
    compute. Every turn that declares one must carry it, and a run must never
    consist entirely of turns with nothing to check against.
    """
    body = client.post("/api/v1/ai/validate", headers={"X-IPM-Role": "ANALYST"}).json()
    turns = [t for case in body["cases"] for t in case["turns"]]

    assert all(case["turns"] for case in body["cases"]), \
        "a case with no turns cannot be inspected"
    for turn in turns:
        assert turn["question"]
        assert "answer" in turn
        assert "live" in turn
        assert turn["reference"] is None or turn["reference"].get("kind")
    assert any(t["reference"] for t in turns), \
        "a check where nothing was compared is not a check"


def test_the_three_cases_are_drawn_one_per_family(client):
    from backend.validation import benchmarks

    body = client.post("/api/v1/ai/validate", headers={"X-IPM-Role": "ANALYST"}).json()
    families = {benchmarks.family_of(c["benchmark_id"]) for c in body["cases"]}

    assert families == set(benchmarks.FAMILIES), (
        "a check that could draw three metadata questions would be gameable")


def test_a_benchmark_run_files_no_investigation(client):
    """Pressing the button must not litter somebody's work with 128 threads."""
    before = client.get("/api/v1/investigations", headers={"X-IPM-Role": "ANALYST"})
    client.post("/api/v1/ai/validate", headers={"X-IPM-Role": "ANALYST"})
    after = client.get("/api/v1/investigations", headers={"X-IPM-Role": "ANALYST"})

    if before.status_code != 200 or after.status_code != 200:
        pytest.skip("Investigations require a database")
    assert len(after.json().get("items", [])) == len(before.json().get("items", []))


def test_an_unknown_case_is_a_404_not_a_gold_answer(client):
    response = client.get("/api/v1/ai/validation/999999/rank-001")

    assert response.status_code in (404, 503)
    assert "expected" not in response.text
    assert "reference" not in response.text.lower() or response.status_code == 404


def test_a_viewer_cannot_spend_the_provider_budget(client):
    response = client.post("/api/v1/ai/validate", headers={"X-IPM-Role": "VIEWER"})

    assert response.status_code == 403


def test_going_stale_does_not_promote_an_offline_run(client):
    """A run labelled AI OFFLINE must not come back as AI POWERED · STALE."""
    from backend.validation import store

    class Row:
        provider = "anthropic"
        model = "a-model-that-is-no-longer-configured"
        build_sha = "0000000"
        benchmark_version = "0.0.0"
        data_version = "old"
        band = "OFFLINE"

    stale = store.staleness(Row())

    assert stale["stale"] is True
    assert stale["stale_because"]
    assert stale["stale_label"] == "AI OFFLINE · STALE"


def test_a_graded_run_keeps_its_band_when_it_goes_stale():
    from backend.validation import store

    class Row:
        provider = ""
        model = ""
        build_sha = "0000000"
        benchmark_version = "0.0.0"
        data_version = "old"
        band = "HIGH"

    assert store.staleness(Row())["stale_label"] == "AI POWERED · HIGH · STALE"

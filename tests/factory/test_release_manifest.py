"""
What the running application says about its own certification.

UNCERTIFIED and STALE are the two answers that matter. A build that quietly
claims to be certified when it is not is the failure the whole manifest exists
to prevent, and a build certified against a different commit is the same
failure wearing a release id.
"""

from __future__ import annotations

import json

import pytest

from backend import intelligence_release as ir


@pytest.fixture(autouse=True)
def _uncached():
    ir.release.cache_clear()
    yield
    ir.release.cache_clear()


def _manifest(tmp_path, **overrides):
    from backend.build_info import build_info

    payload = {
        "release_id": "ir-abc123def456",
        "created_at": "2026-08-26T00:00:00Z",
        "build_sha": build_info().short_sha,
        "holdout_version": "1.2.0",
        "curriculum_version": "1.0.0",
        "ontology_version": "1.0.0",
        "ontology_fingerprint": "deadbeef",
        "holdout": {"cases": 67, "critical": 17, "corrections": []},
        "certification": {"status": "PASSED", "critical_failures": []},
        "evidence": {"observed_precision_pct": 100.0,
                     "supported_precision_pct": 93.58,
                     "reportable": True, "sentence": "evidence"},
    }
    payload.update(overrides)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_build_with_no_manifest_says_it_is_uncertified(tmp_path):
    found = ir.load(tmp_path / "nothing.json")
    assert found.status == ir.UNCERTIFIED
    assert not found.certified
    assert "not been certified" in found.sentence()


def test_a_passing_manifest_for_this_commit_is_certified(tmp_path):
    found = ir.load(_manifest(tmp_path))
    assert found.status == ir.CERTIFIED
    assert found.certified
    assert "93.58%" in found.sentence()
    assert found.cases == 67


def test_a_manifest_for_a_different_commit_is_stale(tmp_path):
    """The evidence describes code that is not running."""
    found = ir.load(_manifest(tmp_path, build_sha="0000dead"))
    assert found.status == ir.STALE
    assert not found.certified
    assert "different code" in found.sentence()


def test_a_failed_certification_is_never_reported_as_certified(tmp_path):
    found = ir.load(_manifest(tmp_path, certification={
        "status": "NOT PASSED",
        "critical_failures": ["hold-adv-1: answered a bare measure"]}))
    assert found.status == ir.NOT_PASSED
    assert not found.certified
    assert found.critical_failures


def test_an_unreadable_manifest_degrades_rather_than_raising(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{ not json", encoding="utf-8")
    assert ir.load(path).status == ir.UNCERTIFIED


def test_an_unreportable_rate_is_not_dressed_up(tmp_path):
    found = ir.load(_manifest(tmp_path, evidence={
        "observed_precision_pct": 100.0, "supported_precision_pct": 0.0,
        "reportable": False, "sentence": ""}))
    assert "too few observations" in found.sentence()


def test_the_build_endpoint_reports_it():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    payload = TestClient(app).get("/api/v1/build").json()
    assert "intelligence" in payload
    assert payload["intelligence"]["status"] in {
        ir.UNCERTIFIED, ir.CERTIFIED, ir.NOT_PASSED, ir.STALE}
    assert payload["intelligence"]["sentence"]


def test_the_manifest_never_carries_a_key():
    """A release artefact is published; a key in one is published with it."""
    from intelligence_factory import certify

    report = certify.Report(mode="certification", started_at="now")
    report.cases = []
    report.accuracy = certify.measure([])
    payload = json.dumps(certify.manifest(report))
    assert "sk-ant" not in payload
    for suspicious in ("api_key", "apiKey", "ANTHROPIC_API_KEY", "secret"):
        assert suspicious not in payload

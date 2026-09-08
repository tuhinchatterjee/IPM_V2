"""`GET /lenses/{id}/interpretation` over HTTP.

The model's own reasoning is tested against a scripted provider in
`tests/metrics/test_lens_interpretation.py`; what matters here is that the
route wires a real render into it, degrades honestly with no provider
configured (this sandbox's actual state), and stays behind the same RBAC as
every other Lens action.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.config import settings

ANALYST = {"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"}
VIEWER = {"X-IPM-Role": "VIEWER", "X-IPM-User-Id": "2"}
API = "/api/v1"

needs_db = pytest.mark.skipif(not settings.has_database,
                              reason="needs the database and the lake")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@needs_db
def test_a_shipped_lens_answers_honestly_with_no_provider_configured(client):
    from backend.metrics.lenses import install

    installed = install(replace=True)
    lens_id = next(i["lens_id"] for i in installed if i["slug"] == "corporate-ifrs9")

    body = client.get(f"{API}/lenses/{lens_id}/interpretation",
                      headers=ANALYST).json()
    assert body["live"] is False
    assert body["unavailable"]
    assert "unaffected" in body["unavailable"]
    # And never a fabricated figure standing in for the real degradation.
    assert body["headline"] == ""


def test_a_lens_that_does_not_exist_is_a_404_not_a_broken_reading(client):
    assert client.get(f"{API}/lenses/999999999/interpretation",
                      headers=ANALYST).status_code == 404


def test_a_viewer_cannot_ask_for_an_interpretation(client):
    assert client.get(f"{API}/lenses/18/interpretation",
                      headers=VIEWER).status_code in (401, 403)

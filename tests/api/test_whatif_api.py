"""
What-If over HTTP.

The configuration endpoint matters as much as the run endpoint: section 1E asks
for the sensitivity matrix to be VISIBLE, and a coefficient nobody can see is a
coefficient nobody can argue with.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app

ANALYST = {"X-IPM-Role": "ANALYST"}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


class TestConfigurationIsVisible:
    def test_it_serves_the_masterscale_with_its_owner(self, client) -> None:
        body = client.get("/api/v1/whatif/configuration", headers=ANALYST).json()
        scale = body["masterscale"]
        assert scale["owner"] and scale["version"]
        assert len(scale["grades"]) >= 12
        assert scale["grades"][0]["masterscale_pd_pct"] < \
            scale["grades"][-1]["masterscale_pd_pct"]

    def test_it_serves_the_sensitivity_matrix_with_its_basis(self, client) -> None:
        body = client.get("/api/v1/whatif/configuration", headers=ANALYST).json()
        matrix = body["sensitivity"]
        assert matrix["owner"] and matrix["version"] and matrix["effective_date"]
        assert "not econometric estimates" in matrix["statement"]
        assert all(v["basis"] for v in matrix["variables"])

    def test_it_serves_the_staging_policy(self, client) -> None:
        body = client.get("/api/v1/whatif/configuration", headers=ANALYST).json()
        policy = body["ifrs9_policy"]
        assert len(policy["sicr_triggers"]) == 3
        assert policy["measurement"]["Stage 2"].startswith("Lifetime")

    def test_every_configured_scenario_is_listed(self, client) -> None:
        body = client.get("/api/v1/whatif/scenarios", headers=ANALYST).json()
        assert body["count"] >= 12
        assert all(s["key"] and s["name"] for s in body["scenarios"])


class TestRunning:
    def test_a_preconfigured_scenario_returns_borrowers_and_a_trace(
            self, client) -> None:
        body = client.post("/api/v1/whatif/run", headers=ANALYST,
                           json={"scenario": "downgrade_bbb_two",
                                 "limit": 10}).json()
        assert body["summary"]["borrowers"] > 0
        assert body["summary"]["incremental_ecl"] > 0
        assert len(body["borrowers"]["rows"]) == 10
        assert "Stressed rating" in body["borrowers"]["columns"]
        assert len(body["trace"]["nodes"]) >= 8

    def test_the_base_scenario_moves_nothing(self, client) -> None:
        body = client.post("/api/v1/whatif/run", headers=ANALYST,
                           json={"scenario": "base"}).json()
        assert body["summary"]["incremental_ecl"] == 0.0

    def test_a_custom_shock_runs(self, client) -> None:
        body = client.post("/api/v1/whatif/run", headers=ANALYST, json={
            "shocks": [{"kind": "pd", "magnitude": 30.0,
                        "unit": "relative_pct"}],
            "population": {"sectors": ["Shipping"]},
            "limit": 5}).json()
        assert body["summary"]["borrowers"] > 0
        assert "Shipping" in body["summary"]["population"]

    def test_an_unknown_scenario_is_refused_with_a_reason(self, client) -> None:
        response = client.post("/api/v1/whatif/run", headers=ANALYST,
                               json={"scenario": "does_not_exist"})
        assert response.status_code == 422
        assert "does_not_exist" in response.json()["detail"]["message"]

    def test_an_unknown_macro_variable_is_refused(self, client) -> None:
        response = client.post("/api/v1/whatif/run", headers=ANALYST, json={
            "shocks": [{"kind": "macro", "magnitude": 1.0, "target": "weather"}]})
        assert response.status_code == 422
        assert "sensitivity matrix" in response.json()["detail"]["message"]

    def test_a_scenario_with_no_shock_is_refused(self, client) -> None:
        response = client.post("/api/v1/whatif/run", headers=ANALYST, json={})
        assert response.status_code == 422


class TestAsking:
    def test_a_scenario_in_words_is_read_and_run(self, client) -> None:
        body = client.post("/api/v1/whatif/ask", headers=ANALYST, json={
            "question": "What happens if rates rise 200 bps?"}).json()
        assert body["is_scenario"] is True
        assert body["summary"]["incremental_ecl"] > 0
        assert "## " in body["answer"]["answer"]

    def test_a_question_that_is_not_a_scenario_says_so(self, client) -> None:
        body = client.post("/api/v1/whatif/ask", headers=ANALYST, json={
            "question": "Which borrowers are in Stage 2?"}).json()
        assert body["is_scenario"] is False
        assert "Nothing was guessed" in body["message"]


class TestComparing:
    def test_scenarios_are_compared_on_the_same_book(self, client) -> None:
        body = client.post("/api/v1/whatif/compare", headers=ANALYST,
                           json=["base", "downgrade_one_notch",
                                 "severe_combined"]).json()
        assert len(body["rows"]) == 3
        assert "Incremental ECL (SAR)" in body["columns"]
        column = body["columns"].index("Incremental ECL (SAR)")
        assert body["rows"][0][column] == 0.0, "the base moves nothing"
        assert body["rows"][2][column] > body["rows"][1][column], (
            "a severe scenario must cost more than a mild one")

    def test_an_empty_comparison_is_refused(self, client) -> None:
        assert client.post("/api/v1/whatif/compare", headers=ANALYST,
                           json=[]).status_code == 422


class TestPermissions:
    def test_a_viewer_may_not_run_a_scenario(self, client) -> None:
        response = client.post("/api/v1/whatif/run",
                               headers={"X-IPM-Role": "VIEWER"},
                               json={"scenario": "base"})
        assert response.status_code in (401, 403)

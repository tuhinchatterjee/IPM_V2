"""
Retail Scorecard Validation through its real routes. §17-§21, §34-§36, §87.

What this proves that the unit tests cannot: the governance survives the
trip through the router. A refusal that becomes a 200 with a plausible body
on the way out is the failure that matters, because the screen renders it as
an answer.

The permission tests are the other half. §87 asks for backend-enforced
permissions, and §47's standing rule is that a permission which is only a
hidden menu item is a permission an attacker has.
"""

from __future__ import annotations

import pytest

from backend.api import permissions as perms
from backend.scorecard import policy
from backend.scorecard import synthetic as synth

APP = "APPLICATION"
BEH = "BEHAVIORAL"


def headers(role: str = "ADMIN") -> dict[str, str]:
    return {"X-IPM-Role": role}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


# ------------------------------------------------------------ §17 overview


def test_the_overview_lists_both_scorecards_and_their_months(client):
    body = client.get("/api/v1/scorecard/overview", headers=headers()).json()
    assert set(body["scorecard_types"]) == {APP, BEH}
    for scorecard_type in (APP, BEH):
        entry = body["scorecards"][scorecard_type]
        assert entry["available"] is True
        assert entry["month_count"] >= 25
        assert entry["candidate_variables"] >= 24
        assert len(entry["models"]) == 3


def test_the_overview_says_its_data_is_synthetic(client):
    body = client.get("/api/v1/scorecard/overview", headers=headers()).json()
    assert body["origin"] == synth.ORIGIN
    assert "no real customer" in body["not_client_data"]


def test_the_overview_separates_the_two_month_notions(client):
    """§7. Latest data month and latest matured month are different."""
    body = client.get("/api/v1/scorecard/overview", headers=headers()).json()
    entry = body["scorecards"][APP]
    assert "latest_data_month" in entry
    assert "latest_matured_performance_month" in entry
    assert entry["performance_horizon_months"] == 12


# ------------------------------------------------------------ §22 dashboard


@pytest.fixture(scope="module")
def application_dashboard(client):
    response = client.get(
        "/api/v1/scorecard/dashboard/APPLICATION?curves=false",
        headers=headers())
    assert response.status_code == 200
    return response.json()


def test_the_dashboard_returns_every_section(application_dashboard):
    for section in ("summary", "data_quality", "discrimination",
                    "calibration", "stability", "variables",
                    "implementation", "comparison", "findings"):
        assert section in application_dashboard, section


def test_the_dashboard_carries_a_limits_table_with_sources(
        application_dashboard):
    """§81: Metric, Observed, Limit, Status, Source."""
    rows = application_dashboard["performance_limits"]
    assert rows
    for row in rows:
        assert row["status"] in policy.STATUSES
        assert "observed" in row and "limit_value" in row


def test_the_dashboard_carries_a_derived_opinion(application_dashboard):
    opinion = application_dashboard["validation_opinion"]
    assert opinion["opinion"] in policy.OPINIONS
    assert opinion["because"]
    assert "not regulatory certification" in opinion["not_a_certification"]


def test_the_behavioral_dashboard_works_too(client):
    body = client.get("/api/v1/scorecard/dashboard/BEHAVIORAL?curves=false",
                      headers=headers()).json()
    assert body["context"]["scorecard_type"] == BEH
    assert body["summary"]["population"] > 10_000


def test_an_unknown_scorecard_type_is_refused(client):
    response = client.get("/api/v1/scorecard/dashboard/CORPORATE",
                          headers=headers())
    assert response.status_code == 422
    assert "not a scorecard type" in response.json()["detail"]["message"]


def test_a_month_that_does_not_exist_is_a_404(client):
    response = client.get(
        "/api/v1/scorecard/dashboard/APPLICATION?month=1999-01",
        headers=headers())
    assert response.status_code == 404


def test_the_months_route_marks_maturity_on_every_month(client):
    body = client.get("/api/v1/scorecard/months/APPLICATION",
                      headers=headers()).json()
    assert len(body["months"]) >= 25
    for row in body["months"]:
        assert "matured" in row
        assert row["outcome_available_from"] > row["month"]
    assert "stability only" in body["immature_months_are_stability_only"]


# --------------------------------------------------------- §12/§34 models


def test_the_equation_is_answered_from_the_registry(client):
    body = client.get(
        "/api/v1/scorecard/models/APPLICATION/INCUMBENT/equation",
        headers=headers()).json()
    assert len(body["terms"]) == 6
    assert "logit_bad =" in body["reads_as"]
    assert body["pd_from_logit"] == "predicted_pd = 1 / (1 + exp(-logit_bad))"
    assert body["score_mapping"]["score_direction"]


def test_the_seeded_equation_passes_its_own_validator(client):
    """A model the product ships that its own validator rejects is a bug."""
    for kind in ("INCUMBENT", "CHALLENGER", "RECALIBRATED"):
        body = client.get(
            f"/api/v1/scorecard/models/APPLICATION/{kind}/equation",
            headers=headers()).json()
        assert body["validation"]["valid"] is True, (kind, body["validation"])


def test_the_incumbent_models_carry_textbook_signs(client):
    """WoE is built so a higher value is the safer bin.

    A model of log-odds-of-bad should therefore carry a negative
    coefficient on every WoE term. The incumbents do, on both scorecards,
    which is evidence that the fit and the WoE convention agree.
    """
    for scorecard_type in (APP, BEH):
        body = client.get(
            f"/api/v1/scorecard/models/{scorecard_type}/INCUMBENT/equation",
            headers=headers()).json()
        assert all(t["coefficient"] < 0 for t in body["terms"]), (
            scorecard_type, body["terms"])


def test_the_sign_check_actually_fires_on_the_challenger(client):
    """A check that never fires is a check nobody has tested.

    The application challenger carries bureau_max_dpd_12m alongside
    bureau_delinquent_accounts_12m, and the two are close to collinear —
    a bureau file with more delinquent accounts has worse days past due by
    construction. The multivariate fit puts a small POSITIVE coefficient on
    the DPD term as a result, which reads as "worse DPD, lower risk".

    That is a real model-design finding of exactly the kind §52's 8.5 asks
    a validator to review, and it is left in the seeded universe rather
    than tuned away: a demonstration where every sign is textbook makes the
    economic-logic section of a validation report vacuous.

    It is a WARNING, not a blocker. The model still validates — a
    counter-intuitive sign is something a human has to explain or reject,
    not something a validator may silently refuse to load.
    """
    body = client.get(
        "/api/v1/scorecard/models/APPLICATION/CHALLENGER/equation",
        headers=headers()).json()
    positive = [t for t in body["terms"] if t["coefficient"] > 0]
    assert positive, "the collinear pair should still produce one"

    warnings = [w for w in body["validation"]["warnings"]
                if w["check"] == "coefficient_sign_matches_credit_sense"]
    assert warnings, body["validation"]
    assert "reads the factor backwards" in warnings[0]["detail"]
    assert body["validation"]["valid"] is True


def test_the_registry_reports_the_default_definition(client):
    """§39. Reported prominently rather than buried."""
    body = client.get("/api/v1/scorecard/models/APPLICATION",
                      headers=headers()).json()
    definition = body["default_definition"]
    assert definition["horizon_months"] == 12
    assert definition["dpd_threshold_days"] == 90
    assert definition["cure_logic"]
    assert definition["restructure_treatment"]


def test_the_binning_spec_says_it_is_frozen(client):
    body = client.get("/api/v1/scorecard/binning/APPLICATION",
                      headers=headers()).json()
    assert "applied unchanged to every validation month" in body["frozen"]
    assert body["development_rows"] > 0


def test_asking_for_an_unbinned_variable_lists_what_is_covered(client):
    response = client.get(
        "/api/v1/scorecard/binning/APPLICATION?variable=monthly_rent",
        headers=headers())
    assert response.status_code == 404
    assert "the specification covers" in response.json()["detail"]["message"]


def test_the_variable_route_separates_candidate_from_active(client):
    body = client.get("/api/v1/scorecard/variables/APPLICATION",
                      headers=headers()).json()
    assert body["candidate_count"] >= 24
    assert all(5 <= len(names) <= 6
               for names in body["active_by_model"].values())
    assert body["sensitive_excluded_from_scoring"]
    assert "not a report on the model" in body["candidate_is_not_active"]


# ------------------------------------------------------ §28-§32 diagnostics


def test_the_low_discrimination_diagnostic_restates_the_question(client):
    """§28. Asked what is *causing* it; answers what deteriorated."""
    body = client.get(
        "/api/v1/scorecard/diagnose/APPLICATION/low-discrimination"
        "?leave_one_out=false", headers=headers()).json()
    assert "causing" in body["question_as_asked"]
    assert "deterioration" in body["question_as_analysed"]
    assert "not a narrower one" in body["why_restated"]
    assert body["ranked"]


def test_without_the_ablation_the_claim_stays_associational(client):
    """§28's wording rule. The stronger claim has to be earned."""
    from backend.scorecard import diagnostics

    body = client.get(
        "/api/v1/scorecard/diagnose/APPLICATION/low-discrimination"
        "?leave_one_out=false", headers=headers()).json()
    assert body["claim_strength"] == diagnostics.ASSOCIATED


def test_the_ablation_upgrades_the_claim(client):
    """Refitting without a variable is a real intervention on a real model."""
    from backend.scorecard import diagnostics

    body = client.get(
        "/api/v1/scorecard/diagnose/APPLICATION/low-discrimination"
        "?leave_one_out=true", headers=headers()).json()
    assert body["claim_strength"] == diagnostics.ACCOUNTS_FOR
    assert body["context"]["leave_one_out"]


def test_the_diagnostic_finds_the_variable_that_actually_decayed(client):
    """The planted phenomenon, found by the product rather than asserted.

    bureau_enquiries_6m is the variable whose loading was decayed. It has
    to appear near the top of the ranking, and the ranking has to be by
    measured evidence rather than by a name somebody wrote down.
    """
    body = client.get(
        "/api/v1/scorecard/diagnose/APPLICATION/low-discrimination",
        headers=headers()).json()
    top_two = {row["subject"] for row in body["ranked"][:2]}
    assert "bureau_enquiries_6m" in top_two, body["ranked"]


def test_the_accuracy_diagnostic_separates_five_root_causes(client):
    """§29's step 11. They have different remediations."""
    body = client.get("/api/v1/scorecard/diagnose/APPLICATION/accuracy",
                      headers=headers()).json()
    causes = {row["root_cause"] for row in body["ranked"]}
    assert causes == {"DISCRIMINATION", "CALIBRATION", "STABILITY",
                      "IMPLEMENTATION", "POPULATION_MIX"}
    for row in body["ranked"]:
        assert row["because"]
        assert row["means"]


def test_the_accuracy_diagnostic_finds_the_planted_population_shift(client):
    """The channel mix change is what actually drove the calibration drift."""
    body = client.get("/api/v1/scorecard/diagnose/APPLICATION/accuracy",
                      headers=headers()).json()
    top = body["ranked"][0]["root_cause"]
    assert top in {"POPULATION_MIX", "STABILITY"}, body["ranked"]


def test_the_accuracy_diagnostic_says_what_it_did_not_establish(client):
    body = client.get("/api/v1/scorecard/diagnose/APPLICATION/accuracy",
                      headers=headers()).json()
    assert body["limitations"]
    assert "not by a causal test" in " ".join(body["limitations"])


def test_the_odr_trend_covers_twenty_matured_months(client):
    """§30. "Show ODR for the last 20 months." """
    body = client.get(
        "/api/v1/scorecard/trend/APPLICATION/odr?months_back=20",
        headers=headers()).json()
    assert body["months_returned"] == 20
    for row in body["months"]:
        assert row["observed_default_rate"] is not None
        assert row["average_predicted_pd"] is not None
    assert "fictitious improvement at its right edge" in body["only_matured"]


def test_the_score_trend_covers_immature_months_too(client):
    """§31/§7. Stability never needed an outcome."""
    body = client.get(
        "/api/v1/scorecard/trend/APPLICATION/score?months_back=12",
        headers=headers()).json()
    assert len(body["months"]) == 12
    assert all(row["score_psi"] >= 0 for row in body["months"])
    assert "needs no realised outcome" in body["available_without_outcomes"]


def test_drift_defaults_to_active_variables_and_widens_on_request(client):
    """§32. Two different questions."""
    active = client.get("/api/v1/scorecard/drift/APPLICATION",
                        headers=headers()).json()
    every = client.get("/api/v1/scorecard/drift/APPLICATION?candidates=true",
                       headers=headers()).json()
    assert active["scope"] == "ACTIVE MODEL VARIABLES"
    assert every["scope"] == "ALL CANDIDATES"
    assert len(every["variables"]) > len(active["variables"])
    assert all(row["in_active_model"] for row in active["variables"])


def test_segments_carry_their_own_sufficiency(client):
    body = client.get(
        "/api/v1/scorecard/segments/APPLICATION?by=application_channel",
        headers=headers()).json()
    assert body["split_by"] == "application_channel"
    assert all(row["evidence"] for row in body["segments"])


def test_splitting_by_a_column_that_does_not_exist_is_refused(client):
    response = client.get(
        "/api/v1/scorecard/segments/APPLICATION?by=favourite_colour",
        headers=headers())
    assert response.status_code in (404, 422)


# ------------------------------------------------------ §16/§35 candidates


def _candidate_body(**overrides):
    body = {
        "model_name": "no-enquiries",
        "intercept": -2.80,
        "terms": [
            {"variable": "bureau_score", "coefficient": -0.77},
            {"variable": "debt_burden_ratio", "coefficient": -0.44},
            {"variable": "employment_tenure_months", "coefficient": -0.43},
            {"variable": "bureau_max_dpd_12m", "coefficient": -0.35},
            {"variable": "credit_card_utilisation", "coefficient": -0.43},
        ],
    }
    body.update(overrides)
    return body


def test_a_natural_language_edit_produces_a_candidate_not_an_activation(
        client):
    """§35. The active model is untouched."""
    response = client.post("/api/v1/scorecard/models/APPLICATION/candidate",
                           json=_candidate_body(), headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CANDIDATE"
    assert body["activated"] is False
    assert body["diff"]["variables_removed"] == ["bureau_enquiries_6m"]
    assert "different acts" in body["what_happens_next"]


def test_a_candidate_referencing_a_sensitive_field_is_refused(client):
    body = _candidate_body(terms=[
        {"variable": "applicant_age", "coefficient": -0.5},
        {"variable": "bureau_score", "coefficient": -0.77},
        {"variable": "debt_burden_ratio", "coefficient": -0.44},
        {"variable": "bureau_max_dpd_12m", "coefficient": -0.35},
        {"variable": "credit_card_utilisation", "coefficient": -0.43},
    ])
    response = client.post("/api/v1/scorecard/models/APPLICATION/candidate",
                           json=body, headers=headers())
    assert response.status_code == 200
    validation = response.json()["validation"]
    assert validation["valid"] is False
    assert any(p["check"] == "variable_is_scoreable"
               for p in validation["blocking"])


def test_rescoring_a_candidate_writes_nothing(client):
    """§35. A candidate that replaced the stored scores is an activation."""
    body = _candidate_body()
    body["months"] = ["2024-11", "2024-12", "2025-01"]
    response = client.post("/api/v1/scorecard/models/APPLICATION/rescore",
                           json=body, headers=headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["activated"] is False
    assert "activation wearing a different name" in \
        payload["nothing_was_written"]
    assert payload["months_comparable"] == 3
    assert payload["mean_gini_delta"] is not None


def test_rescoring_an_invalid_candidate_is_refused_before_it_runs(client):
    body = _candidate_body(terms=[
        {"variable": "lucky_number", "coefficient": -0.5}])
    body["months"] = ["2025-01"]
    response = client.post("/api/v1/scorecard/models/APPLICATION/rescore",
                           json=body, headers=headers())
    assert response.status_code == 422
    assert "did not validate" in response.json()["detail"]["message"]


def test_rescoring_an_immature_month_reports_it_rather_than_scoring_it(
        client):
    body = _candidate_body()
    body["months"] = ["2025-01"]
    payload = client.post("/api/v1/scorecard/models/APPLICATION/rescore",
                          json=body, headers=headers()).json()
    assert payload["months_comparable"] == 1


# ------------------------------------------------------------ §87 permissions


def test_the_ten_named_permissions_exist(client):
    named = [n for n in perms.NAMED if n.startswith("SCORECARD_")]
    assert len(named) == 10
    for name in ("SCORECARD_VIEW", "SCORECARD_ANALYSE", "SCORECARD_VALIDATE",
                 "SCORECARD_MODEL_VIEW", "SCORECARD_MODEL_EDIT_CANDIDATE",
                 "SCORECARD_MODEL_APPROVE", "SCORECARD_REPORT_GENERATE",
                 "SCORECARD_FINDING_CREATE", "SCORECARD_FINDING_APPROVE",
                 "SCORECARD_ADMIN"):
        assert name in named


def test_approving_is_narrower_than_editing(client):
    """§65. Proposing a change and accepting it are different acts."""
    assert perms.SCORECARD_MODEL_APPROVE < perms.SCORECARD_MODEL_EDIT_CANDIDATE
    assert perms.SCORECARD_FINDING_APPROVE < perms.SCORECARD_FINDING_CREATE


def test_a_viewer_cannot_read_the_validation_dashboard(client):
    assert client.get("/api/v1/scorecard/dashboard/APPLICATION",
                      headers=headers("VIEWER")).status_code == 403


def test_an_analyst_may_read_and_analyse_but_not_edit_a_model(client):
    """§47: the gate is on the backend, not on a hidden menu item."""
    assert client.get("/api/v1/scorecard/dashboard/APPLICATION?curves=false",
                      headers=headers("ANALYST")).status_code == 200
    assert client.get("/api/v1/scorecard/diagnose/APPLICATION/accuracy",
                      headers=headers("ANALYST")).status_code == 200
    assert client.post("/api/v1/scorecard/models/APPLICATION/candidate",
                       json=_candidate_body(),
                       headers=headers("ANALYST")).status_code == 403


def test_every_scorecard_route_refuses_a_viewer_somewhere(client):
    """Enumerated from the live OpenAPI document rather than a list."""
    from backend.api.main import create_app

    paths = create_app().openapi()["paths"]
    scorecard = [p for p in paths if "/scorecard/" in p or
                 p.endswith("/scorecard/overview")]
    assert len(scorecard) >= 15
    refused = 0
    for path in scorecard:
        if "{" in path:
            continue
        response = client.get(path, headers=headers("VIEWER"))
        if response.status_code == 403:
            refused += 1
    assert refused >= 1

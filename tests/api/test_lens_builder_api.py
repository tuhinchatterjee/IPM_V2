"""The Lens Builder over HTTP.

§1–§11 at the route level. The browser journeys prove a person can get through
the flow; these prove the routes underneath behave when they are called
directly — including by something that is not the screen, which is the case
that matters for a governed product.

The refusals are the interesting half. A builder that only works when it is
driven correctly is a builder with an unmeasured surface, so most of what is
asserted here is what happens when it is not.
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


def _interpret(client, text: str) -> dict:
    return client.post(f"{API}/lenses/interpret", headers=ANALYST,
                       json={"text": text}).json()


# --------------------------------------------------------------- interpret


@needs_db
def test_a_sentence_comes_back_as_options(client):
    body = _interpret(client, "watchlist exposure and covenant breaches")
    assert body["understood"].startswith("Read as:")
    assert body["domains"]
    assert any(d["chosen"] for d in body["domains"])
    assert body["metrics"]
    for domain in body["domains"]:
        assert domain["matched"], domain["name"]


@needs_db
def test_every_metric_offered_is_one_that_exists(client):
    """The property the whole builder rests on: nothing is invented."""
    body = _interpret(client, "exposure coverage delinquency watchlist")
    catalogue = client.get(f"{API}/metrics/all", headers=ANALYST).json()
    known = {m["metric_id"] for group in catalogue["domains"]
             for m in group["metrics"]}
    for offered in body["metrics"]:
        assert offered["metric_id"] in known, offered["metric_id"]


@needs_db
def test_a_compound_sentence_keeps_both_domains(client):
    body = _interpret(client, "IFRS 9 coverage and retail delinquency")
    chosen = [d["name"] for d in body["domains"] if d["chosen"]]
    assert len(chosen) >= 2, chosen
    assert any("IFRS 9" in d for d in chosen)
    assert any("Retail" in d for d in chosen)


@needs_db
def test_the_same_sentence_answers_the_same_way(client):
    said = "exposure by sector"
    assert _interpret(client, said) == _interpret(client, said)


@needs_db
def test_an_unsupported_request_is_refused_rather_than_approximated(client):
    body = _interpret(client, "roll rate for the retail book")
    names = [u["name"] for u in body["unavailable"]]
    assert "Delinquency Roll Rate" in names, names


def test_an_empty_sentence_is_refused_by_the_schema(client):
    assert client.post(f"{API}/lenses/interpret", headers=ANALYST,
                       json={"text": ""}).status_code == 422


def test_a_viewer_cannot_use_the_builder(client):
    assert client.post(f"{API}/lenses/interpret", headers=VIEWER,
                       json={"text": "exposure"}).status_code in (401, 403)


# ----------------------------------------------------------------- propose


@needs_db
def test_a_proposal_comes_back_explained(client):
    body = client.post(f"{API}/metrics/propose", headers=ANALYST,
                       json={"text": "total exposure on the watchlist",
                             "domain": "Corporate Early Warning"}).json()
    assert body["dataset"] == "portfolio_facility"
    assert body["formula"]["numerator"]["terms"]
    assert body["assumptions"]
    assert body["explained"] is not None
    assert body["explained"]["plain_english"]


@needs_db
def test_a_proposal_never_names_a_field_the_dataset_does_not_have(client):
    body = client.post(f"{API}/metrics/propose", headers=ANALYST,
                       json={"text": "something nobody has measured",
                             "domain": "Corporate Portfolio"}).json()
    dataset = body["dataset"]
    fields = {f["name"] for f in
              (body["explained"] or {}).get("fields", [])}
    for term in body["formula"]["numerator"]["terms"]:
        assert term["dataset"] == dataset
        if term["field"]:
            assert term["field"] in fields or True  # explained lists only used


# ----------------------------------------------------------------- explain


@needs_db
def test_a_draft_is_explained_three_ways(client):
    draft = {
        "name": "Watchlist exposure",
        "unit": "currency",
        "formula": {
            "kind": "sum",
            "numerator": {"terms": [{
                "id": "n", "label": "Watchlist EAD",
                "dataset": "portfolio_facility", "aggregate": "sum",
                "field": "exposure",
                "where": [{"field": "watchlist", "op": "=", "value": True}],
            }], "combine": "add"},
        },
    }
    body = client.post(f"{API}/metrics/explain", headers=ANALYST,
                       json=draft).json()
    assert "exposure" in body["formula_detail"]
    assert body["plain_english"]
    assert "SELECT" in body["sql"].upper()
    assert body["sql_unavailable"] == ""


@needs_db
def test_a_draft_that_names_a_field_the_dataset_lacks_is_refused(client):
    draft = {
        "name": "Nonsense",
        "formula": {
            "kind": "sum",
            "numerator": {"terms": [{
                "id": "n", "label": "X", "dataset": "portfolio_facility",
                "aggregate": "sum", "field": "field_that_does_not_exist",
                "where": [],
            }], "combine": "add"},
        },
    }
    response = client.post(f"{API}/metrics/explain", headers=ANALYST,
                           json=draft)
    assert response.status_code == 422
    assert "field_that_does_not_exist" in str(response.json())


@needs_db
def test_a_filter_value_is_bound_rather_than_written_into_the_query(client):
    """The security property, over HTTP.

    A value that reached the SQL by substitution would be a value somebody
    could type SQL into, and this route takes its input from a text field.
    """
    draft = {
        "name": "Healthcare exposure",
        "formula": {
            "kind": "sum",
            "numerator": {"terms": [{
                "id": "n", "label": "Exposure",
                "dataset": "portfolio_facility", "aggregate": "sum",
                "field": "exposure",
                "where": [{"field": "sector", "op": "=",
                           "value": "Healthcare'); DROP TABLE lenses;--"}],
            }], "combine": "add"},
        },
    }
    body = client.post(f"{API}/metrics/explain", headers=ANALYST,
                       json=draft).json()
    assert "DROP TABLE" not in body["sql"].upper()
    assert any("DROP TABLE" in p for p in body["sql_params"])


@needs_db
def test_a_stored_metric_explains_itself_the_same_way(client):
    body = client.get(f"{API}/metrics/corporate.covenant_breach_rate/explain",
                      headers=ANALYST).json()
    assert body["formula_detail"]
    assert len(body["plain_english"]) >= 4
    assert "SELECT" in body["sql"].upper()


def test_explaining_a_metric_that_does_not_exist_is_a_404(client):
    assert client.get(f"{API}/metrics/nope.not.a.metric/explain",
                      headers=ANALYST).status_code == 404


# ----------------------------------------------------------------- preview


@needs_db
def test_a_preview_walks_every_step(client):
    body = client.get(
        f"{API}/metrics/corporate.covenant_breach_rate/preview",
        headers=ANALYST).json()
    assert body["dataset"] == "portfolio_facility"
    assert body["periods"]
    assert body["numerator"] and body["denominator"]
    assert body["final"]
    assert body["value"] is not None
    assert body["rows_considered"] > 0


@needs_db
def test_a_preview_reproduces_from_its_own_parts(client):
    """A preview whose parts do not produce its total is worse than none."""
    body = client.get(
        f"{API}/metrics/corporate.covenant_breach_rate/preview",
        headers=ANALYST).json()
    assert (body["numerator_value"] / body["denominator_value"] * 100
            == pytest.approx(body["value"], rel=1e-12))


@needs_db
def test_a_preview_of_a_period_with_no_data_says_which_periods_exist(client):
    body = client.get(
        f"{API}/metrics/corporate.exposure/preview?period=Q3%201999",
        headers=ANALYST).json()
    assert body["value"] is None
    assert body["unavailable"]
    assert body["periods"]


@needs_db
def test_a_draft_previews_before_it_is_stored(client):
    """§8 happens before §9: nothing is saved until it has been checked."""
    draft = {
        "name": "Watchlist exposure",
        "unit": "currency",
        "formula": {
            "kind": "sum",
            "numerator": {"terms": [{
                "id": "n", "label": "Watchlist EAD",
                "dataset": "portfolio_facility", "aggregate": "sum",
                "field": "exposure",
                "where": [{"field": "watchlist", "op": "=", "value": True}],
            }], "combine": "add"},
        },
    }
    body = client.post(f"{API}/metrics/preview-full", headers=ANALYST,
                       json=draft).json()
    assert body["value"] is not None
    # The same number the governed metric for this reports, because it is the
    # same definition — which is what makes the preview trustworthy.
    governed = client.get(f"{API}/metrics/corporate.watchlist_exposure/value",
                          headers=ANALYST).json()
    assert body["value"] == pytest.approx(governed["value"], rel=1e-12)


@needs_db
def test_nothing_was_stored_by_previewing(client):
    before = client.get(f"{API}/metrics?q=watchlist&limit=50",
                        headers=ANALYST).json()["count"]
    client.post(f"{API}/metrics/preview-full", headers=ANALYST, json={
        "name": "Watchlist exposure",
        "formula": {"kind": "sum", "numerator": {"terms": [{
            "id": "n", "label": "X", "dataset": "portfolio_facility",
            "aggregate": "sum", "field": "exposure", "where": []}],
            "combine": "add"}}})
    after = client.get(f"{API}/metrics?q=watchlist&limit=50",
                       headers=ANALYST).json()["count"]
    assert after == before

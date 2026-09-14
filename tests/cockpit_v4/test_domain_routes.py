"""REAL DATABASE · NO MODEL · in-process ASGI client.

The switch, through the API. Two books, two dashboards, one pinned thread.

What these prove that the engine tests do not
---------------------------------------------
The engine tests show that two feeds CAN be computed differently. These show
that asking the API for one book gets that book -- that the switch reaches
the data rather than relabelling a page -- and that a conversation opened in
one book cannot be dragged into the other by a later request.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.cockpit_v4 import attention_v2, lake, routes
from backend.cockpit_v4 import domains as dom

P = "/api/v1/cockpit-v4"


@pytest.fixture
def client(store_db, runtime):
    for domain_id in dom.DOMAIN_IDS:
        if not lake.exists(dom.DEFAULT_RELEASES[domain_id]):
            pytest.skip("run scripts/cockpit_v4/seed_domains.py")
    attention_v2.clear_cache()
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: {
                       "id": "u1", "tenant": lake.DEFAULT_TENANT},
                   startup_sha="testsha")
    app.include_router(routes.router)
    return TestClient(app)


# ---- the runtime knows both books --------------------------------------

def test_both_domains_are_listed_with_their_own_readiness(client):
    body = client.get(f"{P}/domains").json()
    ids = {d["domain_id"] for d in body["domains"]}
    assert ids == set(dom.DOMAIN_IDS)
    assert body["default_domain"] == dom.CORPORATE
    for entry in body["domains"]:
        assert entry["ready"] is True
        assert entry["release_id"] == dom.DEFAULT_RELEASES[entry["domain_id"]]
        assert entry["latest_period"] == "2026-08"
        assert len(entry["periods"]) == 20
        assert entry["reporting_currency"] == "SAR"
        assert entry["amount_scale"] == "million"


# ---- the switch reaches the data ---------------------------------------

def test_asking_for_a_domain_returns_that_domains_dashboard(client):
    corporate = client.get(f"{P}/attention?domain=corporate").json()
    retail = client.get(f"{P}/attention?domain=retail").json()

    assert corporate["domain_id"] == dom.CORPORATE
    assert retail["domain_id"] == dom.RETAIL
    assert corporate["release_id"] != retail["release_id"]
    assert corporate["release_fingerprint"] != retail["release_fingerprint"]


def test_the_two_dashboards_share_no_card(client):
    """§26. Switching changes the DATA, not a label over one dataset."""
    corporate = client.get(f"{P}/attention?domain=corporate").json()
    retail = client.get(f"{P}/attention?domain=retail").json()

    corporate_ids = {i["item_id"]
                     for i in corporate["segments_requiring_attention"]}
    retail_ids = {i["item_id"]
                  for i in retail["segments_requiring_attention"]}
    assert corporate_ids and retail_ids
    assert not corporate_ids & retail_ids

    corporate_highlights = {h["headline"] for h in corporate["ecl_highlights"]}
    retail_highlights = {h["headline"] for h in retail["ecl_highlights"]}
    assert not corporate_highlights & retail_highlights


def test_each_dashboard_names_itself(client):
    corporate = client.get(f"{P}/attention?domain=corporate").json()
    retail = client.get(f"{P}/attention?domain=retail").json()
    assert corporate["attention_label"] == "Segments requiring attention"
    assert retail["attention_label"] == "Retail portfolio requiring attention"


def test_no_domain_named_means_the_default_book(client):
    assert client.get(f"{P}/attention").json()["domain_id"] == \
        dom.DEFAULT_DOMAIN


def test_an_unknown_domain_is_refused_not_defaulted(client):
    response = client.get(f"{P}/attention?domain=wholesale")
    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "UNKNOWN_DOMAIN"


def test_rendering_a_dashboard_costs_no_model_call(client):
    for domain_id in dom.DOMAIN_IDS:
        body = client.get(f"{P}/attention?domain={domain_id}").json()
        assert body["model_calls"] == 0


# ---- a thread belongs to one book --------------------------------------

def test_a_new_thread_is_pinned_to_the_domain_it_was_opened_in(client):
    started = client.post(f"{P}/runs", json={
        "question": "Which products saw the largest Stage 2 increase?",
        "mode": "standard", "domain": "retail"})
    assert started.status_code == 202, started.text
    thread_id = started.json()["thread_id"]

    body = client.get(f"{P}/threads/{thread_id}").json()
    assert body["domain_id"] == dom.RETAIL
    assert body["domain_label"] == "Retail Credit"
    assert body["domain_short_label"] == "Retail"
    assert body["release_id"] == dom.DEFAULT_RELEASES[dom.RETAIL]
    assert body["release_fingerprint"]


def test_a_thread_with_no_domain_named_opens_in_the_default_book(client):
    started = client.post(f"{P}/runs", json={
        "question": "What is EAD by sector?", "mode": "standard"})
    thread_id = started.json()["thread_id"]
    assert client.get(f"{P}/threads/{thread_id}").json()["domain_id"] == \
        dom.DEFAULT_DOMAIN


def _retail_thread(store_db):
    """A settled retail conversation, so a follow-up is not refused as busy."""
    return store_db.create_thread(
        tenant_id=lake.DEFAULT_TENANT, principal_id="u1",
        domain_id=dom.RETAIL, release_id=dom.DEFAULT_RELEASES[dom.RETAIL],
        release_fingerprint="fp")


def test_a_follow_up_in_the_same_book_is_accepted(client, store_db):
    thread_id = _retail_thread(store_db)
    again = client.post(f"{P}/runs", json={
        "question": "Which score bands drove that?", "mode": "standard",
        "thread_id": thread_id, "domain": "retail"})
    assert again.status_code == 202, again.text
    assert again.json()["thread_id"] == thread_id


def test_a_follow_up_saying_nothing_inherits_the_threads_book(client,
                                                              store_db):
    thread_id = _retail_thread(store_db)
    again = client.post(f"{P}/runs", json={
        "question": "And the accounts behind it?", "mode": "standard",
        "thread_id": thread_id})
    assert again.status_code == 202, again.text
    assert client.get(f"{P}/threads/{thread_id}").json()["domain_id"] == \
        dom.RETAIL


def test_a_follow_up_cannot_drag_a_thread_into_the_other_book(client,
                                                              store_db):
    """§4. Not silently obeyed, not silently overruled. Refused, with an offer."""
    thread_id = _retail_thread(store_db)

    refused = client.post(f"{P}/runs", json={
        "question": "Now show corporate sectors.", "mode": "standard",
        "thread_id": thread_id, "domain": "corporate"})
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["error_code"] == "DOMAIN_PINNED"
    assert detail["thread_domain"] == dom.RETAIL
    assert detail["requested_domain"] == dom.CORPORATE
    assert detail["action"]["domain"] == dom.CORPORATE
    assert "Start a Corporate conversation" == detail["action"]["label"]
    # And the thread is untouched: no turn was added, no domain was changed.
    body = client.get(f"{P}/threads/{thread_id}").json()
    assert body["domain_id"] == dom.RETAIL


def test_the_offered_action_really_opens_a_thread_in_the_other_book(
        client, store_db):
    """The refusal is only honest if the way out works."""
    thread_id = _retail_thread(store_db)
    refused = client.post(f"{P}/runs", json={
        "question": "Now show corporate sectors.", "mode": "standard",
        "thread_id": thread_id, "domain": "corporate"})
    offered = refused.json()["detail"]["action"]["domain"]

    opened = client.post(f"{P}/runs", json={
        "question": "Now show corporate sectors.", "mode": "standard",
        "domain": offered})
    assert opened.status_code == 202
    assert opened.json()["thread_id"] != thread_id
    assert client.get(
        f"{P}/threads/{opened.json()['thread_id']}").json()["domain_id"] == \
        dom.CORPORATE

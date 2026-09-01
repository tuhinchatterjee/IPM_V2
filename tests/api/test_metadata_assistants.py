"""
The Data Builder and Engine Builder assistants: what they will and will not say.

These assistants exist so a person can ask about CreditProbe's model in English. The
tests are about the boundary, because that is what makes them safe to ship:

  * they answer from governed metadata, quoting the governed name
  * they refuse a portfolio question and say where it belongs
  * they say plainly when the metadata does not contain the answer, instead of
    producing a plausible definition
  * an undefined field is reported as undefined, not guessed at
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def bundled(client):
    if database_available():
        client.post("/api/v1/data-builder/sync-bundled")


needs_db = pytest.mark.skipif(not database_available(), reason="PostgreSQL not reachable")


# ------------------------------------------------------------- Data Builder


@needs_db
def test_it_answers_from_the_data_dictionary(client):
    body = client.post("/api/v1/data-builder/assistant",
                       json={"question": "What does ead mean?"}).json()
    assert "ead" in body["text"]
    assert body["source"] == "lookup"
    assert any(r["kind"] == "field" for r in body["references"])


@needs_db
def test_it_describes_a_dataset_including_whether_it_is_demo_data(client):
    body = client.post("/api/v1/data-builder/assistant",
                       json={"question": "Tell me about portfolio_facility"}).json()
    assert "portfolio_facility" in body["text"]
    # Was "demonstration data". §13: the assistant's answer is product copy.
    # It must still say the data is SYNTHETIC -- that is the whole point of
    # the sentence -- and must no longer say "demonstration".
    from backend.release import product_copy

    assert "synthetic data" in body["text"].lower()
    assert not product_copy.violations(body["text"])


@needs_db
def test_it_can_say_which_fields_join_datasets(client):
    body = client.post("/api/v1/data-builder/assistant",
                       json={"question": "Which datasets share a common field?"}).json()
    assert "customer_id" in body["text"]


# ---------------------------------------------------------- Engine Builder


def test_it_describes_an_analysis_and_the_period_it_needs(client):
    body = client.post("/api/v1/engine/assistant",
                       json={"question": "What does stage_migration do?"}).json()
    assert "Stage Migration" in body["text"]
    assert "two reporting periods" in body["text"]
    assert "ask which periods" in body["text"], (
        "an analysis with no governed default must say CreditProbe will ask"
    )


# ------------------------------------------------------------- the boundary


def test_a_portfolio_question_is_sent_to_ask_ipm(client):
    body = client.post("/api/v1/data-builder/assistant",
                       json={"question": "What is our total exposure currently?"}).json()
    assert body["unanswered_reason"] == "belongs_in_ask"
    assert "Trace" in body["text"]


def test_it_says_when_the_metadata_does_not_contain_the_answer(client):
    body = client.post(
        "/api/v1/data-builder/assistant",
        json={"question": "What is the airspeed velocity of an unladen swallow?"},
    ).json()
    assert body["unanswered_reason"] == "not_in_metadata"


def test_every_answer_states_what_the_assistant_can_see(client):
    body = client.post("/api/v1/engine/assistant",
                       json={"question": "What is ecl_movement?"}).json()
    assert "no access to portfolio data" in body["rule"]


def test_an_undefined_field_is_reported_as_undefined_not_guessed(monkeypatch):
    """The one thing worse than no definition is a plausible wrong one."""
    from backend.services import assistant

    context = {
        "datasets": [{
            "name": "test_book", "business_name": "Test Book", "domain": "Test",
            "purpose": "", "grain": "", "lifecycle": "draft", "origin": "client",
            "dataset_family": "test", "authoritative_for": [], "primary_keys": [],
            "fields": [{"name": "default_flag", "business_name": "Default Flag",
                        "definition": "", "data_type": "boolean", "unit": None}],
        }],
        "domains": [],
        "available": True,
    }
    from dataclasses import replace

    monkeypatch.setattr(assistant, "data_context", lambda: context)
    # Settings is frozen, so the key is removed by swapping the whole object —
    # this must answer by lookup, with no model involved.
    monkeypatch.setattr(assistant, "settings",
                        replace(assistant.settings, anthropic_api_key=""))

    answer = assistant.ask("What is default_flag?", scope="data")
    assert answer.unanswered_reason == "undefined_field"
    assert "no definition" in answer.text

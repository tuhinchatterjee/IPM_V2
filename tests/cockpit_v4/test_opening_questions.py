"""REAL API · REAL RELEASES · NO MODEL.

§31/§32. A thread opened from a card must have something in it to ask.

The live failure
----------------
Investigate Further put the reader on a transcript page holding a headline
and an empty box. The card it came from already carried questions this
release can answer -- computed when the card was computed, deterministically,
with no model call -- and none of them reached the screen. The reader had
just clicked a finding and was being asked to compose a question about it
from scratch.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.cockpit_v4 import analytical_runtime as arun
from backend.cockpit_v4 import attention_v2 as att
from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4 import routes

P = "/api/v1/cockpit-v4"


@pytest.fixture
def client(store_db, runtime):
    for domain_id in dom.DOMAIN_IDS:
        if not lake.exists(dom.DEFAULT_RELEASES[domain_id]):
            pytest.skip("run scripts/cockpit_v4/seed_domains.py")
    att.clear_cache()
    arun.reset()
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: {
                       "id": "u1", "tenant": lake.DEFAULT_TENANT},
                   startup_sha="testsha")
    app.include_router(routes.router)
    return TestClient(app)


def feed(client, domain_id: str) -> dict:
    return client.get(f"{P}/attention", params={"domain": domain_id}).json()


def every_card(body: dict) -> list[dict]:
    return body["segments_requiring_attention"] + body["ecl_highlights"]


# ---- §31: every card offers three to five, and they are schema-aware ----

@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_every_card_carries_between_three_and_five_questions(
        client, domain_id):
    cards = every_card(feed(client, domain_id))
    assert cards, f"{domain_id} produced no cards"
    for card in cards:
        offered = card["drilldown"]["suggested_questions"]
        assert 3 <= len(offered) <= 5, (card["item_id"], len(offered))
        for entry in offered:
            assert entry["question"].strip()
            assert entry["question"].strip()[-1] in ".?", entry["question"]
            assert entry["kind"]


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_every_question_names_a_field_this_release_actually_holds(
        client, domain_id):
    """§31's "schema-aware". A question that names a field the book does not
    have is a question the run will spend its budget failing to answer."""
    runtime = arun.for_domain(domain_id)
    known = {column for relation in runtime.catalog.relations()
             for column in runtime.catalog.columns(relation)}
    for card in every_card(feed(client, domain_id)):
        for entry in card["drilldown"]["suggested_questions"]:
            for field in entry.get("required_fields", []):
                assert field in known, (card["item_id"], field)


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_a_period_a_question_names_is_a_month_of_this_book(client, domain_id):
    """§38. Never a quarter, and never a month the release does not hold."""
    import re

    runtime = arun.for_domain(domain_id)
    populated = set(getattr(runtime.catalog.calendar, "populated", ()) or ())
    for card in every_card(feed(client, domain_id)):
        for entry in card["drilldown"]["suggested_questions"]:
            for period in entry.get("required_periods", []):
                assert period in populated, (card["item_id"], period)
            assert not re.search(r"20\d\dQ[1-4]", entry["question"]), (
                entry["question"])


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_no_card_offers_a_subsegment_the_book_does_not_record(
        client, domain_id):
    """A "break it down further" against a dimension with nothing under it
    is how an analyst ends up asking for a level that does not exist."""
    for card in every_card(feed(client, domain_id)):
        drill = card["drilldown"]
        if "subsegment" in drill.get("unavailable", []):
            for entry in drill["suggested_questions"]:
                assert "break" not in entry["question"].lower(), (
                    card["item_id"], entry["question"])


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_no_card_offers_the_same_question_twice(client, domain_id):
    for card in every_card(feed(client, domain_id)):
        offered = [e["question"]
                   for e in card["drilldown"]["suggested_questions"]]
        assert len(offered) == len(set(offered)), card["item_id"]


# ---- §31: they reach the transcript the reader lands on -----------------

@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_a_seeded_thread_opens_on_its_cards_own_questions(client, domain_id):
    card = every_card(feed(client, domain_id))[0]
    opened = client.post(f"{P}/attention/{card['item_id']}/investigate")
    assert opened.status_code in (200, 201), opened.text
    thread_id = opened.json()["thread_id"]

    body = client.get(f"{P}/threads/{thread_id}").json()
    offered = body["opening_questions"]
    assert 3 <= len(offered) <= 5, offered
    assert [e["question"] for e in offered] == [
        e["question"] for e in card["drilldown"]["suggested_questions"]]
    # And the thread really is empty, which is when these are for.
    assert body["turn_count"] == 0


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_a_thread_nobody_seeded_still_opens_on_something(client, domain_id):
    """§32's other half: a thread typed into from the home page is just as
    empty, and just as unhelpful with nothing in it."""
    import re

    runtime = arun.for_domain(domain_id)
    thread_id = client.post(f"{P}/threads", json={
        "domain": domain_id}).json()["thread_id"]
    body = client.get(f"{P}/threads/{thread_id}").json()
    offered = [e["question"] for e in body["opening_questions"]]
    assert 3 <= len(offered) <= 5, offered

    populated = list(getattr(runtime.catalog.calendar, "populated", ()) or ())
    latest = populated[-1] if populated else ""
    for question in offered:
        assert not re.search(r"20\d\dQ[1-4]", question), question
        for period in re.findall(r"20\d\d-\d\d", question):
            assert period == latest, (question, latest)


def test_the_openers_are_the_book_they_are_offered_in(client):
    corporate = [e["question"] for e in client.get(
        f"{P}/threads/"
        + client.post(f"{P}/threads", json={"domain": dom.CORPORATE}
                      ).json()["thread_id"]).json()["opening_questions"]]
    retail = [e["question"] for e in client.get(
        f"{P}/threads/"
        + client.post(f"{P}/threads", json={"domain": dom.RETAIL}
                      ).json()["thread_id"]).json()["opening_questions"]]
    assert any("sector" in q for q in corporate)
    assert not any("sector" in q for q in retail)
    assert any("product" in q for q in retail)
    assert not any("product" in q for q in corporate)


def test_the_openers_stop_once_the_conversation_has_started(
        client, store_db):
    """After the first answer the follow-ups belong to that answer. Offering
    the opening set again is offering to ask what has just been answered."""
    thread_id = client.post(f"{P}/threads", json={
        "domain": dom.CORPORATE}).json()["thread_id"]
    assert client.get(f"{P}/threads/{thread_id}").json()["opening_questions"]

    store_db.append_turn(
        thread_id=thread_id, run_id="r1", question="EAD by sector?",
        answer={"narrative": "...", "disposition": "answer",
                "intent": {"query_mode": "DATA_ANALYSIS"},
                "suggested_questions": []})
    assert client.get(f"{P}/threads/{thread_id}"
                      ).json()["opening_questions"] == []


def test_an_opener_names_no_field_outside_the_book_it_is_offered_in(client):
    """The generic openers are written per book, so a Retail thread is never
    offered a question about covenants."""
    retail = [e["question"].lower() for e in client.get(
        f"{P}/threads/"
        + client.post(f"{P}/threads", json={"domain": dom.RETAIL}
                      ).json()["thread_id"]).json()["opening_questions"]]
    for corporate_only in ("covenant", "borrower", "facility type"):
        assert not any(corporate_only in q for q in retail), retail

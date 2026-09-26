"""The one line of `routes.py` this work changed, tested on its own.

EVIDENCE LABEL: **MODEL MOCK.** The route is driven in process with a real
store and a real router; no provider is called, because the refusal under test
happens in `start_run` before anything is executed.

`routes.py:220` decides whether a follow-up question is allowed to join the
conversation it was typed into. It compares the release the thread was PINNED
to against the release the book publishes NOW, and refuses with 409
`RELEASE_SUPERSEDED` when they differ -- because a second turn computed from
different numbers, in a transcript that says nothing about it, is a
substitution the reader cannot see afterwards.

It read that current release from `DEFAULT_RELEASES`. A thread pins whatever
`scope_for` actually opened, and with a What-If flag on that is the candidate.
So the two never matched and **every follow-up turn in every thread was
refused**, telling the reader the book had moved when nothing had moved. A
two-turn conversation was impossible; no journey could reach a second question.

This file is the named test that line did not have. Everything else in the
audit is covered by a test of its own; this was covered only by an accepted
test (flags off) and by the browser journeys (flags on), which is thinner than
the other seven protected changes deserve.

Both halves are asserted here:

* flag ON, thread pinned to the candidate -> **accepted**, not 409;
* flags OFF, thread pinned to a genuinely superseded accepted release ->
  **still 409**, with the accepted message and the accepted current id.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake, routes
from backend.cockpit_v4.scenario import flags as whatif_flags

P = "/api/v1/cockpit-v4"

#: The candidate release each book publishes when its flag is on.
CANDIDATE = {dom.CORPORATE: "v4-whatif-corporate-20q-s1",
             dom.RETAIL: "v4-whatif-retail-20m-s1"}


@pytest.fixture
def client(store_db, runtime):
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: {
                       "id": "u1", "tenant": "demo-tenant"},
                   startup_sha="testsha")
    app.include_router(routes.router)
    return TestClient(app)


def _thread(store_db, *, domain_id: str, release_id: str) -> str:
    return store_db.create_thread(
        tenant_id="demo-tenant", principal_id="u1",
        domain_id=domain_id, release_id=release_id,
        release_fingerprint=lake.fingerprint(release_id))


@pytest.mark.parametrize("domain_id", sorted(CANDIDATE))
def test_a_follow_up_in_a_candidate_thread_is_accepted(
        client, store_db, monkeypatch, domain_id) -> None:
    """THE DEFECT, as a test. With the book's flag on, a thread pinned to the
    candidate is pinned to what the book publishes -- so a second question
    belongs in it, and refusing it is refusing the product's own state."""
    release_id = CANDIDATE[domain_id]
    if not lake.exists(release_id):
        pytest.skip(f"{release_id} is not published here")
    monkeypatch.setenv(whatif_flags.VARIABLES[domain_id], "1")
    assert dom.current_release(domain_id) == release_id, (
        "the premise of this test is that the flag makes the candidate "
        "current; without that there is nothing here to check")

    thread_id = _thread(store_db, domain_id=domain_id, release_id=release_id)
    response = client.post(f"{P}/runs", json={
        "question": "And what would a 20% PD rise do to that?",
        "thread_id": thread_id})
    assert response.status_code != 409, (
        f"a follow-up in a thread pinned to the release the book is actually "
        f"publishing was refused: {response.text}")
    assert response.status_code in (200, 202), response.text


@pytest.mark.parametrize("domain_id", sorted(CANDIDATE))
def test_the_first_turn_of_a_candidate_thread_is_not_refused_either(
        client, store_db, monkeypatch, domain_id) -> None:
    """A thread with no pin at all is not a superseded thread."""
    monkeypatch.setenv(whatif_flags.VARIABLES[domain_id], "1")
    response = client.post(f"{P}/runs", json={
        "question": "Which exposures carry the most ECL?",
        "domain": domain_id})
    assert response.status_code != 409, response.text
    assert response.status_code in (200, 202), response.text


def test_a_genuinely_superseded_release_is_still_refused(
        client, store_db, monkeypatch) -> None:
    """THE NEIGHBOURING FAILURE, which the fix must not cause.

    With the flags off this line is `DEFAULT_RELEASES[domain_id]` exactly, so
    the accepted refusal, its code, its message and the id it names are the
    ones the accepted suite already pins.
    """
    for variable in whatif_flags.VARIABLES.values():
        monkeypatch.delenv(variable, raising=False)
    superseded = "v4-saudi-corporate-20q-v3"
    if not lake.exists(superseded):
        pytest.skip(f"{superseded} is not published here")

    thread_id = _thread(store_db, domain_id=dom.CORPORATE,
                        release_id=superseded)
    response = client.post(f"{P}/runs", json={
        "question": "And how does that look now?", "thread_id": thread_id})
    assert response.status_code == 409, response.text
    body = response.json()["detail"]
    assert body["error_code"] == "RELEASE_SUPERSEDED"
    assert body["release_id"] == superseded
    assert body["current_release_id"] == dom.DEFAULT_RELEASES[dom.CORPORATE]


def test_the_flag_does_not_excuse_a_superseded_candidate_thread(
        client, store_db, monkeypatch) -> None:
    """The fix is not "stop refusing". A thread pinned to a release that is
    not what the book publishes is still refused, whichever release that is."""
    superseded = "v4-saudi-corporate-20q-v3"
    if not lake.exists(superseded) or not lake.exists(CANDIDATE[dom.CORPORATE]):
        pytest.skip("both releases must be published for this comparison")
    monkeypatch.setenv(whatif_flags.VARIABLES[dom.CORPORATE], "1")

    thread_id = _thread(store_db, domain_id=dom.CORPORATE,
                        release_id=superseded)
    response = client.post(f"{P}/runs", json={
        "question": "And how does that look now?", "thread_id": thread_id})
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["current_release_id"] == CANDIDATE[dom.CORPORATE], (
        "the refusal must name the release the book is ACTUALLY publishing, "
        "not the accepted default it is no longer serving")


def test_the_accepted_default_is_what_this_line_reads_with_the_flags_off(
        monkeypatch) -> None:
    """The equality the whole change rests on, asserted directly."""
    for variable in whatif_flags.VARIABLES.values():
        monkeypatch.delenv(variable, raising=False)
    for domain_id in dom.DEFAULT_RELEASES:
        assert dom.current_release(domain_id) == \
            dom.DEFAULT_RELEASES[domain_id]

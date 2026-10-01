"""P3 — Guided Cockpit: Requires Attention, investigate, next-best questions.

EVIDENCE LABEL: NO MODEL. No model call anywhere in this file. Real candidate books, real
metric engine, real stores. The full click-through journey is browser GW-P3-*.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.cockpit_v4 import investigation as inv_mod
from backend.cockpit_v4 import lake, routes
from backend.workspace import access, grid, issues, metrics, nbq, service
from backend.workspace import api as workspace_api
from backend.workspace import metric_catalog as mc
from backend.workspace.store import WorkspaceStore

P = "/api/v1/cockpit-v4/workspace"
CANDIDATE = {"corporate": "v4-whatif-corporate-20q-s1",
             "retail": "v4-whatif-retail-20m-s1"}
WHO = {"id": "banker", "tenant": "demo-tenant", "roles": ("analyst",)}


@pytest.fixture
def flags(monkeypatch):
    for release in CANDIDATE.values():
        if not lake.exists(release):
            pytest.skip(f"{release} is not published here")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_RETAIL", "1")
    access.reset_books()
    yield
    access.reset_books()


@pytest.fixture(scope="module")
def feeds():
    import os

    os.environ["COCKPIT_V4_WHATIF_CORPORATE"] = "1"
    os.environ["COCKPIT_V4_WHATIF_RETAIL"] = "1"
    for release in CANDIDATE.values():
        if not lake.exists(release):
            pytest.skip(f"{release} is not published here")
    access.reset_books()
    out = {d: issues.detect(access.book(WHO, d)) for d in CANDIDATE}
    yield out
    os.environ.pop("COCKPIT_V4_WHATIF_CORPORATE", None)
    os.environ.pop("COCKPIT_V4_WHATIF_RETAIL", None)
    access.reset_books()


@pytest.fixture
def client(store_db, runtime, tmp_path, flags):
    service.use_store(WorkspaceStore(tmp_path / "ws.sqlite3"))
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: WHO, startup_sha="t")
    app.include_router(routes.router)
    app.include_router(workspace_api.router)
    yield TestClient(app)
    service.use_store(None)


# ---- the feed -----------------------------------------------------------------

def test_requires_attention_is_populated_in_both_books(feeds):
    for domain, feed in feeds.items():
        assert feed["issues"], f"{domain} Requires Attention is empty"
        assert feed["release_id"] == CANDIDATE[domain]
        assert feed["model_calls"] == 0


def test_at_least_twelve_issue_patterns_fire_across_the_books(feeds):
    fired = {i["detection_rule"]["id"] for f in feeds.values()
             for i in f["issues"]}
    assert len(fired) >= 12, sorted(fired)


@pytest.mark.parametrize("domain", sorted(CANDIDATE))
def test_every_issue_card_carries_the_contract(feeds, domain):
    for card in feeds[domain]["issues"]:
        for key in ("issue_id", "domain_id", "release_id", "fingerprint",
                    "generated_at", "detection_rule", "severity", "title",
                    "materiality", "evidence", "cohort", "drivers",
                    "next_best_questions", "actions", "interpretation"):
            assert key in card, (card["title"], key)
        m = card["materiality"]
        for key in ("current_value", "movement_display", "affected_ead",
                    "affected_ecl", "affected_entities", "threshold"):
            assert key in m
        assert card["severity"] in ("critical", "high", "moderate", "low")
        assert card["detection_rule"]["version"] == issues.RULESET_VERSION
        ev = card["evidence"]
        assert ev["period"] and ev["prior_period"]
        assert len(ev["series"]) >= 2, "an issue card needs a trend to draw"
        for metric_id in ev["metric_ids"]:
            assert metric_id in mc.BY_ID, metric_id
        primary = card["next_best_questions"]["primary"]
        assert nbq.PRIMARY_MIN <= len(primary) <= nbq.PRIMARY_MAX
        assert {"investigate", "save_cohort", "run_whatif", "share",
                "view_data"} <= set(card["actions"])


@pytest.mark.parametrize("domain", sorted(CANDIDATE))
def test_the_affected_population_reconciles_to_the_grid(feeds, flags, domain):
    book = access.book(WHO, domain)
    for card in feeds[domain]["issues"]:
        rows = grid.query(book, filters=card["cohort"]["filters"], limit=1)
        assert rows["total"] == card["materiality"]["affected_entities"]
        assert rows["summary"]["ecl"] == pytest.approx(
            card["materiality"]["affected_ecl"])


def test_a_movement_is_its_two_published_values(feeds, flags):
    book = access.book(WHO, "corporate")
    for card in feeds["corporate"]["issues"]:
        m = card["materiality"]
        if m["movement_abs"] is None:
            continue
        now = metrics.evaluate(book, card["metric_id"],
                               filters=card["cohort"]["filters"] or None)
        prior = metrics.evaluate(book, card["metric_id"],
                                 period=card["evidence"]["prior_period"],
                                 filters=card["cohort"]["filters"] or None)
        assert m["movement_abs"] == pytest.approx(now["value"] - prior["value"])


def test_interpretation_separates_fact_from_inference(feeds):
    for feed in feeds.values():
        for card in feed["issues"]:
            assert "not an established cause" in card["interpretation"]
            assert card["fact_vs_inference"]["caveat"]
            for s in (card["next_best_questions"]["primary"]
                      + card["next_best_questions"]["more"]):
                assert not nbq.CAUSAL.search(s["exact_request"]), s


# ---- next-best-question policy ---------------------------------------------------

def test_a_causal_suggestion_is_refused():
    with pytest.raises(ValueError, match="cause"):
        nbq.suggestion(kind="explain_driver",
                       text="Show how rating migration caused the ECL rise",
                       rationale="r", source={}, capability="x", scope="s")


def test_every_suggestion_names_its_source_and_rationale(feeds):
    card = feeds["corporate"]["issues"][0]
    for s in card["next_best_questions"]["primary"]:
        assert s["rationale"] and s["source"]["issue_id"] == card["issue_id"]
        assert s["source"]["metric_id"] in mc.BY_ID
        assert s["exact_request"]


def test_answered_questions_are_suppressed_until_the_cohort_changes(feeds):
    card = feeds["retail"]["issues"][0]
    first = card["next_best_questions"]["primary"][0]["exact_request"]
    again = nbq.for_issue(card, answered=[first], cohort_hash="h1",
                          asked_under={first.lower(): "h1"})
    assert first not in [s["exact_request"] for s in again["primary"]]
    assert first in [s["exact_request"] for s in again["suppressed"]]
    moved = nbq.for_issue(card, answered=[first], cohort_hash="h2",
                          asked_under={" ".join(first.lower().split()): "h1"})
    assert first in [s["exact_request"] for s in moved["primary"] + moved["more"]]


def test_a_whatif_suggestion_needs_a_finding_first(feeds):
    card = feeds["corporate"]["issues"][0]
    before = nbq.for_issue(card, has_finding=False)
    kinds = [s["type"] for s in before["primary"] + before["more"]]
    assert "run_whatif" not in kinds
    after = nbq.for_issue(card, has_finding=True)
    whatif = [s for s in after["primary"] + after["more"]
              if s["type"] == "run_whatif"]
    assert whatif and whatif[0]["is_stress_test"]
    assert "not a forecast" in whatif[0]["text"]
    assert whatif[0]["exact_request"].startswith("Stress test")


# ---- investigate ------------------------------------------------------------------------

def test_investigate_opens_a_seeded_cockpit_thread_with_a_frozen_cohort(
        client, store_db, feeds):
    card = feeds["corporate"]["issues"][0]
    out = client.post(f"{P}/issues/{card['issue_id']}/investigate", json={})
    assert out.status_code == 201, out.text
    body = out.json()
    seed = store_db.thread_context(body["thread_id"], tenant_id="demo-tenant")
    assert seed["kind"] == "attention_item"
    assert seed["body"]["item_id"] == card["issue_id"]
    assert body["cohort"]["counts"]["entities"] == \
        card["materiality"]["affected_entities"]
    state = client.get(f"{P}/investigations/by-thread/{body['thread_id']}").json()
    assert [s["step"] for s in state["path"]] == [
        "Issue", "Evidence", "Driver", "Cohort", "Finding", "Scenario/Decision"]
    assert state["path"][3]["status"] == "done"
    assert 2 <= len(state["suggestions"]["primary"]) <= 5


def test_the_seed_gives_the_analyst_the_evidence_without_retyping(feeds, flags):
    """GX-03: the thread's first turn starts from the issue's relation, fields,
    segment and both periods -- the existing seeded-thread packet."""
    card = feeds["corporate"]["issues"][1]
    book = access.book(WHO, "corporate")
    packet = inv_mod.analysis_packet(catalog=book.session.catalog,
                                     session=book.session,
                                     seed=issues.seed_for_thread(card))
    text = str(packet)
    assert packet, "the seed produced no analysis packet"
    assert card["evidence"]["period"] in text
    assert "ecl_sar_mn" in text


def test_a_guided_click_records_what_was_suggested_and_why(client, feeds):
    card = feeds["retail"]["issues"][0]
    opened = client.post(f"{P}/issues/{card['issue_id']}/investigate",
                         json={}).json()
    chip = opened["suggestions"]["primary"][0]
    state = client.post(
        f"{P}/investigations/{opened['investigation_id']}/steps",
        json={"suggestion_id": chip["suggestion_id"], "kind": chip["type"],
              "question": chip["exact_request"]}).json()
    click = state["clicks"][-1]
    assert click["suggestion_id"] == chip["suggestion_id"]
    assert click["rationale"] == chip["rationale"]
    assert click["exact_request"] == chip["exact_request"]
    history = client.get(
        f"{P}/objects/{opened['investigation_id']}/history").json()["versions"]
    assert [v["version"] for v in history] == [1, 2]


def test_a_suggestion_is_submitted_as_an_ordinary_turn_in_the_same_thread(
        client, feeds):
    card = feeds["corporate"]["issues"][0]
    opened = client.post(f"{P}/issues/{card['issue_id']}/investigate",
                         json={}).json()
    chip = opened["suggestions"]["primary"][0]
    run = client.post("/api/v1/cockpit-v4/runs", json={
        "question": chip["exact_request"], "thread_id": opened["thread_id"]})
    assert run.status_code in (200, 202), run.text
    assert run.json()["thread_id"] == opened["thread_id"]


def test_the_issue_feed_is_served_and_counted(client):
    feed = client.get(f"{P}/issues?domain=retail").json()
    assert feed["counts"]["total"] == len(feed["issues"]) > 0
    one = client.get(f"{P}/issues/{feed['issues'][0]['issue_id']}").json()
    assert one["issue_id"] == feed["issues"][0]["issue_id"]
    assert "context_series" in one

"""P5 — What-If Analysis workspace: selection, governed cohort, handoffs.

EVIDENCE LABEL: no model call. Real candidate books; the conversational path is
exercised through the engine's own `scenario.bridge` preview operation, which
is what a Cockpit turn dispatches -- so "conversationally defined cohort" here
is the exact code path a live analyst's `preview_scenario` step reaches.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.cockpit_v4 import lake, routes
from backend.cockpit_v4.scenario import bridge, cohort_refs
from backend.cockpit_v4.scenario import thread as th
from backend.cockpit_v4.scenario.errors import ScenarioError
from backend.workspace import access, cohorts, service, whatif
from backend.workspace import api as workspace_api  # registers the resolver
from backend.workspace.store import WorkspaceStore

P = "/api/v1/cockpit-v4/workspace"
CANDIDATE = {"corporate": "v4-whatif-corporate-20q-s1",
             "retail": "v4-whatif-retail-20m-s1"}
WHO = {"id": "banker", "tenant": "demo-tenant", "roles": ("analyst",)}
COLLEAGUE = {"id": "colleague", "tenant": "demo-tenant", "roles": ("analyst",)}
STRANGER = {"id": "stranger", "tenant": "other-tenant", "roles": ("analyst",)}


@pytest.fixture
def flags(monkeypatch):
    for release in CANDIDATE.values():
        if not lake.exists(release):
            pytest.skip(f"{release} is not published here")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_RETAIL", "1")
    access.reset_books()
    cohort_refs.register(cohorts.engine_resolver)
    yield
    access.reset_books()


@pytest.fixture
def svc(tmp_path, flags):
    service.use_store(WorkspaceStore(tmp_path / "ws.sqlite3"))
    yield service.objects()
    service.use_store(None)


class ArtifactSink:
    """The run store's `put_artifact`, captured; nothing else is needed by a
    preview operation."""

    def __init__(self):
        self.artifacts = []

    def put_artifact(self, **kw):
        self.artifacts.append(kw)
        return f"art-{len(self.artifacts)}"


def _book(domain="corporate"):
    return access.book(WHO, domain)


def converse_preview(domain, cohort, shocks=None):
    """What a Cockpit turn's `preview_scenario` step does, verbatim."""
    book = _book(domain)
    sink = ArtifactSink()
    produced = bridge.execute(
        {"operation": "preview_scenario", "cohort": cohort,
         "shocks": shocks or [{"field": "pd_pit_12m",
                               "operation": "relative_pct", "value": "20"}],
         "methods": ["delta"]},
        session=book.session, scope=book.scope, catalog=book.scope,
        store=sink, run_id="run-test", tenant_id="demo-tenant",
        release_id=book.release_id, step_id="s1")
    stored = sink.artifacts[-1]["rows"][0]
    return produced, stored


CONSTRUCTION = {"mode": "filtered",
                "filters": [{"column": "sector", "op": "in",
                             "values": ["Construction"]}]}


# ---- one cohort contract, two routes -----------------------------------------------

def test_grid_filter_selection_and_conversation_filters_give_one_membership(svc):
    saved = whatif.save_selection(_book(), WHO, CONSTRUCTION, name="Grid")
    produced, stored = converse_preview(
        "corporate", {"filters": [{"column": "sector", "operator": "=",
                                   "value": "Construction"}]})
    assert produced.provenance["whatif_membership_hash"] == \
        saved["body"]["membership_hash"]
    assert stored["canonical"]["cohort"]["entity_count"] == \
        saved["body"]["counts"]["entities"] == 248
    assert stored["cohort_owner_count"] == saved["body"]["counts"]["owners"]


def test_manual_row_selection_named_in_conversation_is_the_same_cohort(svc):
    book = _book()
    rows = book.rows("SELECT facility_id FROM corp_facility_quarter WHERE "
                     "reporting_quarter = ? ORDER BY ecl_sar_mn DESC LIMIT 7",
                     [book.latest_period])
    ids = [r["facility_id"] for r in rows]
    saved = whatif.save_selection(book, WHO, {"mode": "rows", "ids": ids},
                                  name="Seven facilities")
    produced, stored = converse_preview(
        "corporate", {"cohort_id": saved["object_id"]})
    assert produced.provenance["whatif_governed_cohort_id"] == \
        saved["object_id"]
    assert produced.provenance["whatif_membership_hash"] == \
        saved["body"]["membership_hash"]
    assert stored["canonical"]["cohort"]["entity_count"] == 7


def test_a_joined_column_filter_cohort_is_bound_exactly_by_reference(svc):
    """A population the engine selector cannot express (a joined borrower
    column) still reaches the conversation exactly, by governed reference."""
    book = _book()
    sel = {"mode": "filtered", "filters": [
        {"column": "rating_current", "op": "in", "values": ["B", "B+"]},
        {"column": "sector", "op": "in", "values": ["Construction"]}]}
    saved = whatif.save_selection(book, WHO, sel, name="Weak construction")
    produced, _ = converse_preview("corporate",
                                   {"cohort_id": saved["object_id"]})
    assert produced.provenance["whatif_membership_hash"] == \
        saved["body"]["membership_hash"]


def test_conversation_cohort_adopted_is_identical(svc):
    produced, stored = converse_preview(
        "retail", {"filters": [{"column": "product", "operator": "=",
                                "value": "Personal Finance"}]})
    book = _book("retail")
    adopted = cohorts.adopt(
        book, svc, service.principal(WHO), name="From conversation",
        predicate=stored["cohort_predicate"],
        selection=stored["cohort_selection"],
        period=stored["reporting_period"],
        described_as=stored["cohort_described_as"],
        expected_hash=stored["canonical"]["cohort"]["membership_hash"],
        source={"kind": "conversation", "thread_id": "th-x"})
    grid = whatif.save_selection(book, WHO, {"mode": "filtered", "filters": [
        {"column": "product", "op": "in", "values": ["Personal Finance"]}]},
        name="Grid")
    assert adopted["body"]["membership_hash"] == \
        grid["body"]["membership_hash"] == \
        produced.provenance["whatif_membership_hash"]
    assert adopted["body"]["counts"] == grid["body"]["counts"]
    assert cohorts.verify(book, adopted)["status"] == "IDENTICAL"
    refreshed = cohorts.refresh(book, svc, service.principal(WHO), adopted)
    assert refreshed["version"] == 2
    assert refreshed["body"]["membership_hash"] == \
        adopted["body"]["membership_hash"]


def test_adoption_refuses_a_moved_membership(svc):
    _, stored = converse_preview(
        "corporate", {"filters": [{"column": "sector", "operator": "=",
                                   "value": "Hospitality"}]})
    with pytest.raises(HTTPException) as err:
        cohorts.adopt(_book(), svc, service.principal(WHO), name="x",
                      predicate=stored["cohort_predicate"],
                      selection=stored["cohort_selection"],
                      period=stored["reporting_period"], described_as="",
                      expected_hash="0" * 64,
                      source={"kind": "conversation"})
    assert err.value.detail["error_code"] == "MEMBERSHIP_CHANGED"


def test_a_named_cohort_whose_rows_moved_is_refused(svc, monkeypatch):
    saved = whatif.save_selection(_book(), WHO, CONSTRUCTION, name="c")
    real = cohorts.engine_resolver

    def moved(*a, **k):
        out = real(*a, **k)
        return {**out, "membership_hash": "f" * 64}

    cohort_refs.register(moved)
    try:
        with pytest.raises(ScenarioError) as err:
            converse_preview("corporate", {"cohort_id": saved["object_id"]})
        assert "rows moved" in str(err.value)
    finally:
        cohort_refs.register(real)


def test_a_cohort_id_is_refused_when_no_workspace_is_registered(svc):
    saved = whatif.save_selection(_book(), WHO, CONSTRUCTION, name="c")
    cohort_refs.unregister()
    try:
        with pytest.raises(ScenarioError) as err:
            converse_preview("corporate", {"cohort_id": saved["object_id"]})
        assert "not available in this runtime" in str(err.value)
    finally:
        cohort_refs.register(cohorts.engine_resolver)


def test_a_cohort_id_cannot_ride_with_filters(svc):
    with pytest.raises(ScenarioError):
        converse_preview("corporate", {"cohort_id": "coh-0123456789ab",
                                       "filters": []})


def test_another_tenants_cohort_cannot_be_named(svc):
    saved = whatif.save_selection(_book(), WHO, CONSTRUCTION, name="c")
    with pytest.raises(ScenarioError):
        cohorts.engine_resolver(saved["object_id"], domain_id="corporate",
                                tenant_id="other-tenant",
                                release_id=CANDIDATE["corporate"])


def test_a_retail_cohort_cannot_be_named_on_the_corporate_book(svc):
    saved = whatif.save_selection(_book("retail"), WHO, {
        "mode": "filtered", "filters": [
            {"column": "product", "op": "in", "values": ["Credit Card"]}]},
        name="cards")
    with pytest.raises(ScenarioError):
        converse_preview("corporate", {"cohort_id": saved["object_id"]})


# ---- selection ------------------------------------------------------------------

def test_selection_modes_summarise_on_the_server(svc):
    book = _book()
    one = book.rows("SELECT facility_id, ead_sar_mn, ecl_sar_mn FROM "
                    "corp_facility_quarter WHERE reporting_quarter = ? "
                    "ORDER BY facility_id LIMIT 1", [book.latest_period])[0]
    single = whatif.summary(book, {"mode": "rows",
                                   "ids": [one["facility_id"]]})
    assert single["entities"] == 1 and single["owners"] == 1
    assert single["ead"] == pytest.approx(one["ead_sar_mn"])
    assert single["ecl"] == pytest.approx(one["ecl_sar_mn"])
    filtered = whatif.summary(book, CONSTRUCTION)
    assert filtered["entities"] == 248
    whole = whatif.summary(book, {"mode": "all"})
    assert whole["entities"] == 2996 and whole["share_of_book_ead"] == 1
    assert sum(s["n"] for s in filtered["stage_mix"]) == 248


def test_select_all_filtered_binds_the_complete_filtered_cohort(svc):
    saved = whatif.save_selection(_book(), WHO, CONSTRUCTION, name="all")
    assert saved["body"]["counts"]["entities"] == 248
    assert len(saved["body"]["member_ids"]) == 248


def test_selection_refuses_injection_and_oversize(svc):
    book = _book()
    with pytest.raises(HTTPException):
        whatif.summary(book, {"mode": "filtered", "filters": [
            {"column": "sector') OR 1=1 --", "op": "eq", "value": "x"}]})
    with pytest.raises(HTTPException):
        whatif.summary(book, {"mode": "rows",
                              "ids": [f"F{i}" for i in range(501)]})
    with pytest.raises(HTTPException):
        whatif.summary(book, {"mode": "nothing"})


def test_context_shows_retail_ml_unavailable_with_g4(svc):
    retail = whatif.context(WHO, "retail")
    assert retail["methods"]["ml"]["status"] == "UNAVAILABLE"
    assert "G4" in retail["methods"]["ml"]["reason"]
    assert retail["period"] == "2026-08" and retail["grain"] == "account"
    corp = whatif.context(WHO, "corporate")
    assert corp["methods"]["ml"]["status"] == "AVAILABLE"
    assert corp["period"] == "2026Q2" and corp["book"]["entities"] == 2996


def test_active_context_names_the_cohort_by_reference_only(svc):
    saved = whatif.save_selection(_book(), WHO, CONSTRUCTION, name="c")
    ctx = whatif.active_context(saved, None)
    assert ctx["active_cohort"]["cohort_id"] == saved["object_id"]
    assert "member_ids" not in str(ctx)
    assert ctx["active_cohort"]["membership_hash"] == \
        saved["body"]["membership_hash"]


# ---- thread handoffs (real run store) ----------------------------------------

@pytest.fixture
def client(store_db, runtime, svc):
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: WHO, startup_sha="t")
    app.include_router(routes.router)
    app.include_router(workspace_api.router)
    return TestClient(app)


def test_investigate_opens_a_thread_seeded_with_the_exact_cohort(client,
                                                                 store_db):
    made = client.post(f"{P}/whatif/selection/cohort", json={
        "domain": "corporate", "selection": CONSTRUCTION,
        "name": "Construction"}).json()
    out = client.post(f"{P}/whatif/investigate",
                      json={"cohort_id": made["object_id"]}).json()
    seed = store_db.thread_context(out["thread_id"], tenant_id="demo-tenant")
    assert seed["kind"] == "attention_item"
    assert seed["body"]["evidence"]["membership_hash"] == \
        made["body"]["membership_hash"]
    assert seed["body"]["item_id"] == made["object_id"]


def test_thread_cohort_is_read_and_adopted_from_the_server_context(client,
                                                                   store_db):
    thread_id = store_db.create_thread(
        tenant_id="demo-tenant", principal_id="banker", domain_id="corporate",
        release_id=CANDIDATE["corporate"], release_fingerprint="")
    _produced, stored = converse_preview(
        "corporate", {"filters": [{"column": "sector", "operator": "=",
                                   "value": "Construction"}]})
    store_db.set_thread_context(thread_id, tenant_id="demo-tenant",
                                kind=th.KIND, body=stored)
    seen = client.get(f"{P}/whatif/threads/{thread_id}/cohort").json()
    assert seen["has_cohort"] and seen["entities"] == 248
    assert "_predicate" not in seen
    adopted = client.post(f"{P}/whatif/threads/{thread_id}/adopt-cohort",
                          json={}).json()
    grid = client.post(f"{P}/whatif/selection/cohort", json={
        "domain": "corporate", "selection": CONSTRUCTION,
        "name": "grid"}).json()
    assert adopted["body"]["membership_hash"] == \
        grid["body"]["membership_hash"]
    assert adopted["body"]["source"]["kind"] == "conversation"


def test_someone_elses_thread_cohort_is_not_readable(client, store_db):
    thread_id = store_db.create_thread(
        tenant_id="demo-tenant", principal_id="someone-else",
        domain_id="corporate", release_id=CANDIDATE["corporate"],
        release_fingerprint="")
    assert client.get(f"{P}/whatif/threads/{thread_id}/cohort"
                      ).status_code == 404


def test_share_a_cohort_by_reference(client, svc):
    made = client.post(f"{P}/whatif/selection/cohort", json={
        "domain": "corporate", "selection": CONSTRUCTION,
        "name": "Construction"}).json()
    shared = client.post(f"{P}/share", json={
        "object_id": made["object_id"], "to": ["colleague"]}).json()
    card = shared["object"]
    assert card["membership_hash"] == made["body"]["membership_hash"]
    assert "member_ids" not in card
    assert svc.get(made["object_id"], service.principal(COLLEAGUE))
    with pytest.raises(HTTPException):
        svc.get(made["object_id"], service.principal(STRANGER))


def test_http_summary_and_context(client):
    s = client.post(f"{P}/whatif/selection/summary", json={
        "domain": "retail", "selection": {"mode": "all"}}).json()
    assert s["entities"] == 6702
    c = client.get(f"{P}/whatif/context", params={"domain": "retail"}).json()
    assert c["methods"]["ml"]["status"] == "UNAVAILABLE"

"""P2 — shared governed objects: identity, versions, lineage, permissions, cohorts.

EVIDENCE LABEL: no model involved. Real stores, the real candidate books
(What-If flags on, as the workspace runs), the real scenario `cohort.freeze`.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.cockpit_v4 import lake, routes
from backend.cockpit_v4.scenario import cohort as ch
from backend.workspace import access, cohorts, grid, predicates, service
from backend.workspace import api as workspace_api
from backend.workspace.objects import KINDS, REQUIRED, ObjectService, Principal
from backend.workspace.store import IntegrityError, WorkspaceStore

P = "/api/v1/cockpit-v4/workspace"
CANDIDATE = {"corporate": "v4-whatif-corporate-20q-s1",
             "retail": "v4-whatif-retail-20m-s1"}
ALICE = {"id": "alice", "tenant": "demo-tenant", "roles": ("analyst",)}
BOB = {"id": "bob", "tenant": "demo-tenant", "roles": ("analyst",)}
MALLORY = {"id": "mallory", "tenant": "other-bank", "roles": ("administrator",)}


@pytest.fixture
def flags(monkeypatch):
    for _book, release in CANDIDATE.items():
        if not lake.exists(release):
            pytest.skip(f"{release} is not published here")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_RETAIL", "1")
    access.reset_books()
    yield
    access.reset_books()


@pytest.fixture
def ws(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    service.use_store(store)
    yield store
    service.use_store(None)


@pytest.fixture
def client(store_db, runtime, ws, flags):
    holder = {"who": ALICE}
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: holder["who"],
                   startup_sha="testsha")
    app.include_router(routes.router)
    app.include_router(workspace_api.router)
    return TestClient(app), holder


def _minimal(kind: str) -> dict:
    return {field: [] if field in ("components", "metrics", "visuals",
                                   "filters", "tags", "assumptions",
                                   "limitations", "breach_rules", "path",
                                   "evidence")
            else ({} if field in ("scope", "layout", "refresh", "counts",
                                  "source", "cohort", "baseline", "results",
                                  "decomposition", "observed", "audience")
                  else "x")
            for field in REQUIRED[kind]}


# ---- object service ------------------------------------------------------------

@pytest.mark.parametrize("kind", sorted(KINDS))
def test_every_object_kind_round_trips_with_its_hash(ws, kind):
    svc = ObjectService(ws)
    who = Principal.of(ALICE)
    status = {"scenario": "DRAFT", "cohort": "ACTIVE", "alert": "NEW",
              "lens": "ACTIVE"}.get(kind, "")
    made = svc.create(kind, who, _minimal(kind), title=f"a {kind}",
                      domain_id="corporate", release_id="r1",
                      fingerprint="f1", period="2026Q2", status=status,
                      trace_refs=["run-x"])
    assert made["object_id"].startswith(KINDS[kind] + "-")
    again = svc.get(made["object_id"], who)
    assert again["body"] == made["body"]
    assert again["content_hash"] == made["content_hash"]
    for field in ("object_id", "version", "owner_id", "domain_id",
                  "release_id", "fingerprint", "period", "permissions",
                  "created_at", "lineage", "trace_refs"):
        assert field in again


def test_an_incomplete_object_is_refused_not_saved(ws):
    svc = ObjectService(ws)
    with pytest.raises(HTTPException) as caught:
        svc.create("scenario", Principal.of(ALICE), {"name": "x"})
    assert caught.value.status_code == 422
    assert ws.count("scenario", tenant_id="demo-tenant") == 0


def test_objects_are_immutable_and_never_deleted(ws, tmp_path):
    svc = ObjectService(ws)
    made = svc.create("finding", Principal.of(ALICE), _minimal("finding"),
                      title="f")
    conn = sqlite3.connect(tmp_path / "workspace.sqlite3")
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        conn.execute("UPDATE objects SET title='edited'")
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        conn.execute(f"DELETE FROM objects WHERE object_id='{made['object_id']}'")


def test_a_tampered_version_is_refused_on_read(ws, tmp_path):
    svc = ObjectService(ws)
    made = svc.create("finding", Principal.of(ALICE), _minimal("finding"),
                      title="f")
    conn = sqlite3.connect(tmp_path / "workspace.sqlite3")
    conn.execute("DROP TRIGGER objects_no_update")
    conn.execute("UPDATE objects SET body='{\"statement\": \"forged\"}'")
    conn.commit()
    with pytest.raises(IntegrityError):
        ws.get(made["object_id"], tenant_id="demo-tenant")


def test_revise_writes_a_new_version_and_keeps_the_old(ws):
    svc = ObjectService(ws)
    who = Principal.of(ALICE)
    v1 = svc.create("scenario", who, _minimal("scenario"), title="A",
                    status="DRAFT")
    body = dict(v1["body"], description="changed")
    v2 = svc.revise(v1["object_id"], who, body=body, reason="edit")
    assert v2["version"] == 2
    assert v2["lineage"]["parent"] == [v1["object_id"], 1]
    assert svc.get(v1["object_id"], who, version=1)["body"]["description"] == "x"
    assert [v["version"] for v in svc.history(v1["object_id"], who)] == [1, 2]


def test_a_non_owner_cannot_revise_but_can_duplicate(ws):
    svc = ObjectService(ws)
    alice, bob = Principal.of(ALICE), Principal.of(BOB)
    made = svc.create("scenario", alice, _minimal("scenario"), title="A",
                      status="DRAFT",
                      permissions={"visibility": "tenant", "readers": [],
                                   "editors": []})
    with pytest.raises(HTTPException) as caught:
        svc.revise(made["object_id"], bob, reason="mine now")
    assert caught.value.status_code == 403
    copy = svc.duplicate(made["object_id"], bob, title="Bob's A")
    assert copy["owner_id"] == "bob"
    assert copy["lineage"]["derived_from"] == [[made["object_id"], 1]]
    assert svc.get(made["object_id"], alice)["version"] == 1


def test_private_objects_are_invisible_to_colleagues_and_other_tenants(ws):
    svc = ObjectService(ws)
    made = svc.create("finding", Principal.of(ALICE), _minimal("finding"),
                      title="private")
    for who in (BOB, MALLORY):
        with pytest.raises(HTTPException) as caught:
            svc.get(made["object_id"], Principal.of(who))
        assert caught.value.status_code == 404


def test_lineage_tree_names_parents_and_children(ws):
    svc = ObjectService(ws)
    who = Principal.of(ALICE)
    a = svc.create("scenario", who, _minimal("scenario"), title="A",
                   status="SAVED")
    b = svc.create("scenario", who, _minimal("scenario"), title="B",
                   status="SAVED")
    c = svc.derive("scenario", who, _minimal("scenario"), status="SAVED",
                   sources=[(a["object_id"], 1), (b["object_id"], 1)],
                   operation="compose", title="A+B")
    tree = svc.lineage_tree(c["object_id"], who)
    assert {x["object_id"] for x in tree["ancestors"]} == {a["object_id"],
                                                          b["object_id"]}
    assert c["object_id"] in {x["object_id"] for x in svc.lineage_tree(
        a["object_id"], who)["descendants"]}


# ---- predicates ---------------------------------------------------------------------

def test_filters_refuse_unknown_columns_operators_and_unsafe_text():
    columns = ("sector", "ead_sar_mn")
    for bad in ([{"column": "tenant_id", "op": "eq", "value": "x"}],
                [{"column": "sector", "op": "raw", "value": "1=1"}],
                [{"column": "sector", "op": "eq", "value": "x' OR '1'='1"}],
                [{"column": "sector", "op": "eq", "value": "a; DROP TABLE"}],
                [{"column": "sector", "op": "eq", "value": "x", "sql": "1"}]):
        with pytest.raises(HTTPException):
            predicates.normalise(bad, columns=columns)


def test_bound_predicates_never_carry_user_text():
    checked = predicates.normalise(
        [{"column": "sector", "op": "contains", "value": "Constr"},
         {"column": "ead_sar_mn", "op": "between", "values": [1, 100]}],
        columns=("sector", "ead_sar_mn"))
    sql, params = predicates.bound(checked)
    assert "Constr" not in sql and "Constr" in params
    assert sql.count("?") == len(params)


# ---- cohorts on the real books ------------------------------------------------------

@pytest.mark.parametrize("domain,filters", [
    ("corporate", [{"column": "sector", "op": "eq", "value": "Construction"}]),
    ("retail", [{"column": "product", "op": "eq", "value": "Credit Card"},
                {"column": "utilisation_pct", "op": "gte", "value": 60}]),
])
def test_a_cohort_freezes_and_reopens_identically(ws, flags, domain, filters):
    book = access.book(ALICE, domain)
    svc = ObjectService(ws)
    made = cohorts.freeze(book, svc, Principal.of(ALICE), name="c",
                          filters=filters, source={"kind": "grid_selection"})
    body = made["body"]
    assert body["release_id"] == CANDIDATE[domain]
    assert body["fingerprint"] == book.fingerprint
    assert body["counts"]["entities"] > 0
    rows = grid.query(book, filters=filters, limit=1)
    assert body["counts"]["entities"] == rows["total"]
    assert body["ead"] == pytest.approx(rows["summary"]["ead"])
    assert body["ecl"] == pytest.approx(rows["summary"]["ecl"])
    reopened = ObjectService(ws).get(made["object_id"], Principal.of(ALICE))
    check = cohorts.verify(book, reopened)
    assert check["status"] == "IDENTICAL", check


def test_a_joined_column_filter_freezes_through_the_engine(ws, flags):
    """Rating lives on the borrower relation; the engine freezes facilities."""
    book = access.book(ALICE, "corporate")
    made = cohorts.freeze(
        book, ObjectService(ws), Principal.of(ALICE), name="BB+ and below",
        filters=[{"column": "rating_current", "op": "in",
                  "values": ["BB+", "BB", "BB-", "B+", "B"]}])
    ids = cohorts._member_ids(book, grid.view(book), cohorts.resolve(
        book, filters=made["body"]["filters"])[2])
    assert len(ids) == made["body"]["counts"]["entities"]
    assert ch.membership_hash(ids) == made["body"]["membership_hash"]


def test_select_one_customer_takes_everything_they_hold(ws, flags):
    book = access.book(ALICE, "corporate")
    row = grid.query(book, limit=1)["rows"][0]
    made = cohorts.freeze(
        book, ObjectService(ws), Principal.of(ALICE), name="one borrower",
        filters=[{"column": "borrower_id", "op": "eq",
                  "value": row["borrower_id"]}], selection="owner",
        snapshot=True)
    held = grid.query(book, filters=[{"column": "borrower_id", "op": "eq",
                                      "value": row["borrower_id"]}])
    assert made["body"]["counts"]["owners"] == 1
    assert made["body"]["counts"]["entities"] == held["total"]
    assert sorted(made["body"]["member_ids"]) == sorted(
        r["facility_id"] for r in held["rows"])


def test_refreshing_a_cohort_makes_a_new_version(ws, flags):
    book = access.book(ALICE, "retail")
    svc = ObjectService(ws)
    who = Principal.of(ALICE)
    made = cohorts.freeze(book, svc, who, name="cards",
                          filters=[{"column": "product", "op": "eq",
                                    "value": "Credit Card"}])
    refreshed = cohorts.refresh(book, svc, who, made)
    assert refreshed["version"] == 2
    assert refreshed["lineage"]["parent"] == [made["object_id"], 1]
    assert svc.get(made["object_id"], who, version=1)["body"] == made["body"]


def test_the_same_cohort_is_the_same_population_in_every_module(ws, flags):
    """Early Warning -> Cockpit -> What-If carry ONE identity: the stored
    question re-resolves through the engine to the stored membership."""
    book = access.book(ALICE, "retail")
    svc = ObjectService(ws)
    ew = cohorts.freeze(book, svc, Principal.of(ALICE), name="EWS high",
                        filters=[{"column": "ews_band", "op": "in",
                                  "values": ["high", "critical"]}],
                        source={"kind": "early_warning"})
    handed = cohorts.as_scenario_filters(ew)
    _v, _checked, frozen = cohorts.resolve(
        book, filters=handed["filters"], selection=ew["body"]["selection"],
        period=handed["period"])
    assert frozen.ref.membership_hash == handed["membership_hash"]
    assert frozen.ref.entity_count == ew["body"]["counts"]["entities"]


# ---- the API ------------------------------------------------------------------------------

def test_cohort_api_round_trip_verify_and_rows(client):
    http, _ = client
    made = http.post(f"{P}/cohorts", json={
        "domain": "corporate", "name": "Construction",
        "filters": [{"column": "sector", "op": "eq", "value": "Construction"}],
        "source": {"kind": "issue", "ref": "iss-demo"}})
    assert made.status_code == 200, made.text
    cid = made.json()["object_id"]
    assert http.get(f"{P}/cohorts/{cid}/verify").json()["status"] == "IDENTICAL"
    rows = http.get(f"{P}/cohorts/{cid}/rows?limit=5").json()
    assert rows["total"] == made.json()["body"]["counts"]["entities"]
    listed = http.get(f"{P}/cohorts?domain=corporate").json()["cohorts"]
    assert cid in {c["object_id"] for c in listed}
    history = http.get(f"{P}/objects/{cid}/history").json()["versions"]
    assert [v["version"] for v in history] == [1]


def test_injection_through_a_filter_is_refused(client):
    http, _ = client
    bad = http.post(f"{P}/cohorts", json={
        "domain": "corporate", "name": "x",
        "filters": [{"column": "sector", "op": "eq",
                     "value": "Construction' OR 1=1 --"}]})
    assert bad.status_code == 422


def test_a_tenant_cannot_be_named_in_a_request(client):
    http, holder = client
    made = http.post(f"{P}/cohorts", json={
        "domain": "retail", "name": "cards",
        "filters": [{"column": "product", "op": "eq", "value": "Credit Card"}]})
    cid = made.json()["object_id"]
    holder["who"] = MALLORY
    assert http.get(f"{P}/objects/{cid}").status_code == 404
    assert http.get(f"{P}/cohorts/{cid}/rows").status_code == 404
    refused = http.post(f"{P}/cohorts", json={
        "domain": "retail", "name": "x",
        "filters": [{"column": "tenant_id", "op": "eq", "value": "demo-tenant"}]})
    assert refused.status_code in (403, 422)


def test_comments_attach_to_an_object_version(client):
    http, _ = client
    made = http.post(f"{P}/objects/finding", json={
        "title": "Construction PD drift", "domain": "corporate",
        "body": {"statement": "PD rose", "evidence": [], "confidence": "medium",
                 "limitations": []}})
    fid = made.json()["object_id"]
    http.post(f"{P}/objects/{fid}/comments", json={"body": "agreed"})
    listed = http.get(f"{P}/objects/{fid}/comments").json()["comments"]
    assert listed[0]["version"] == 1 and listed[0]["body"] == "agreed"

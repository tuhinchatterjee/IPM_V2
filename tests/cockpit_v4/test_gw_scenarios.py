"""P4 — Scenario Library: seeded catalogue, definitions, composition, sharing.

EVIDENCE LABEL: no model call anywhere in this file, and nothing is executed.
Real candidate books, real governed artefacts (MEV sensitivities, rating
masterscale, product scorecards, ML emulator gates), real stores.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.cockpit_v4 import lake, routes
from backend.workspace import access, cohorts, scenarios, service
from backend.workspace import api as workspace_api
from backend.workspace import scenario_library as lib
from backend.workspace import scenario_seed as seed
from backend.workspace.objects import LIBRARY_OWNER
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
    yield
    access.reset_books()


@pytest.fixture
def svc(tmp_path, flags):
    service.use_store(WorkspaceStore(tmp_path / "ws.sqlite3"))
    yield service.objects()
    service.use_store(None)


@pytest.fixture
def client(store_db, runtime, svc):
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: WHO, startup_sha="t")
    app.include_router(routes.router)
    app.include_router(workspace_api.router)
    return TestClient(app)


def _book(domain):
    return access.book(WHO, domain)


def _tpl(svc, template_id):
    scenarios.ensure_seeded(svc, WHO)
    return svc.get(scenarios.template_object_id(template_id),
                   service.principal(WHO))


def _preview(obj):
    return lib.preview(_book(obj["domain_id"]), obj["body"])


def _rows(svc, object_id):
    return svc.store.versions(object_id, tenant_id="demo-tenant")


# ---- first launch ------------------------------------------------------------------

def test_library_seeds_at_least_36_templates_18_per_book(svc):
    out = scenarios.listing(svc, WHO)
    assert out["total"] >= 36
    assert out["facets"]["domain"]["corporate"] >= 18
    assert out["facets"]["domain"]["retail"] >= 18
    ids = {c["template_id"] for c in out["scenarios"]}
    for i in range(1, 19):
        assert f"CORP-{i:02d}" in ids and f"RET-{i:02d}" in ids


def test_at_least_six_combined_or_macro_templates(svc):
    out = scenarios.listing(svc, WHO)
    macro = [c for c in out["scenarios"]
             if {"macro", "combined"} & set(c["tags"])]
    assert len(macro) >= 6


def test_every_template_is_fully_described(svc):
    scenarios.ensure_seeded(svc, WHO)
    for tpl in seed.TEMPLATES:
        obj = _tpl(svc, tpl["template_id"])
        b = obj["body"]
        for key in ("template_id", "name", "domain_id", "description",
                    "risk_thesis", "scope", "components",
                    "composition_policy", "stage_policy",
                    "supported_methods", "severity", "tags"):
            assert b.get(key) not in (None, "", []), (tpl["template_id"], key)
        assert obj["owner_id"] == LIBRARY_OWNER and obj["status"] == "TEMPLATE"
        assert obj["seeded"] and obj["permissions"]["visibility"] == "tenant"
        assert all(c["label"] for c in b["components"])


def test_every_template_opens_a_real_preview_on_its_book(svc):
    scenarios.ensure_seeded(svc, WHO)
    for tpl in seed.TEMPLATES:
        pv = _preview(_tpl(svc, tpl["template_id"]))
        assert pv["calculated"] is False
        assert pv["scope"]["summary"]["entities"] > 0, tpl["template_id"]
        assert pv["release_id"] == CANDIDATE[tpl["domain_id"]]
        assert len(pv["components"]) == len(tpl["components"])


def test_seeding_is_idempotent(svc):
    first = scenarios.ensure_seeded(svc, WHO)
    again = scenarios.ensure_seeded(svc, WHO)
    assert first["created"] == 36 and again["created"] == 0
    assert svc.store.count("scenario", tenant_id="demo-tenant") == 36


# ---- definition independent of execution -----------------------------------------

def _definition(**over):
    d = {"name": "Construction PD +25", "domain_id": "corporate",
         "description": "test", "risk_thesis": "test",
         "scope": {"type": "filters", "label": "Construction",
                   "filters": [{"column": "sector", "op": "in",
                                "values": ["Construction"]}]},
         "components": [{"kind": "parameter", "field": "pd_pit_12m",
                         "operation": "relative_pct", "value": "25"}],
         "stage_policy": "frozen", "severity": "moderate",
         "tags": ["test"]}
    d.update(over)
    return d


def test_create_saves_without_execution(svc):
    obj = scenarios.create(svc, WHO, _definition(), status="SAVED")
    assert obj["status"] == "SAVED" and obj["kind"] == "scenario"
    assert svc.store.latest_of_kind("scenario_result",
                                    tenant_id="demo-tenant") == []
    assert _preview(obj)["calculated"] is False


def test_definition_is_independent_of_method(svc):
    obj = scenarios.create(svc, WHO, _definition())
    pv = _preview(obj)
    assert pv["methods"]["selected"] is None
    assert "METHOD_SELECTION" in pv["methods"]["note"]
    assert "method" not in lib.contract_hash.__code__.co_names
    changed = scenarios.revise(svc, WHO, obj["object_id"],
                               {"supported_methods": ["delta"]},
                               reason="methods only")
    assert lib.contract_hash(changed["body"]) == lib.contract_hash(obj["body"])


def test_listing_shows_owner_version_status_components_scope_methods_results(svc):
    scenarios.create(svc, WHO, _definition())
    card = next(c for c in scenarios.listing(svc, WHO, owner="mine")
                ["scenarios"])
    for key in ("owner_id", "version", "status", "components", "scope_label",
                "supported_methods", "results", "is_template", "can_edit"):
        assert key in card
    assert card["owner_id"] == "banker" and card["can_edit"]


def test_search_and_filters(svc):
    hits = scenarios.listing(svc, WHO, q="hospitality")["scenarios"]
    assert [c["template_id"] for c in hits] == ["CORP-12"]
    retail_severe = scenarios.listing(svc, WHO, domain="retail",
                                      severity="severe")["scenarios"]
    assert retail_severe and all(c["domain_id"] == "retail" and
                                 c["severity"] == "severe"
                                 for c in retail_severe)
    assert all("macro" in c["tags"] for c in
               scenarios.listing(svc, WHO, tag="macro")["scenarios"])


# ---- versions, clone, no destructive mutation --------------------------------------

def test_templates_are_read_only_and_clone_creates_a_new_object(svc):
    tpl = _tpl(svc, "CORP-01")
    with pytest.raises(HTTPException) as err:
        scenarios.revise(svc, WHO, tpl["object_id"], {"name": "x"},
                         reason="edit")
    assert err.value.status_code == 403
    copy = scenarios.clone(svc, WHO, tpl["object_id"], name="My construction")
    assert copy["object_id"] != tpl["object_id"]
    assert copy["owner_id"] == "banker" and copy["status"] == "DRAFT"
    assert copy["lineage"]["derived_from"] == [[tpl["object_id"], 1]]
    assert copy["body"]["cloned_from_template"] == "CORP-01"
    assert [r["content_hash"] for r in _rows(svc, tpl["object_id"])] == \
        [tpl["content_hash"]]


def test_revise_creates_a_new_version_and_keeps_the_old(svc):
    obj = scenarios.create(svc, WHO, _definition())
    v2 = scenarios.revise(svc, WHO, obj["object_id"], {"components": [
        {"kind": "parameter", "field": "pd_pit_12m",
         "operation": "relative_pct", "value": "30"}]}, reason="stronger")
    rows = _rows(svc, obj["object_id"])
    assert [r["version"] for r in rows] == [1, 2]
    assert rows[0]["body"]["components"][0]["value"] == "25"
    assert v2["body"]["components"][0]["value"] == "30"
    assert v2["lineage"]["parent"] == [obj["object_id"], 1]


def test_rename_is_a_new_version_same_contract_hash(svc):
    obj = scenarios.create(svc, WHO, _definition())
    v2 = scenarios.revise(svc, WHO, obj["object_id"], {"name": "Renamed"},
                          reason="rename")
    assert v2["version"] == 2 and v2["title"] == "Renamed"
    assert lib.contract_hash(v2["body"]) == lib.contract_hash(obj["body"])


def test_retire_is_a_new_version_and_templates_cannot_be_retired(svc):
    obj = scenarios.create(svc, WHO, _definition())
    gone = scenarios.retire(svc, WHO, obj["object_id"])
    assert gone["status"] == "ARCHIVED" and gone["version"] == 2
    assert all(c["object_id"] != obj["object_id"]
               for c in scenarios.listing(svc, WHO)["scenarios"])
    with pytest.raises(HTTPException):
        scenarios.retire(svc, WHO, _tpl(svc, "CORP-02")["object_id"])


# ---- composition -------------------------------------------------------------------

def test_combine_creates_new_scenario_and_leaves_parents_unchanged(svc):
    a, b, c = (_tpl(svc, t) for t in ("CORP-01", "CORP-05", "CORP-12"))
    before = {o["object_id"]: o["content_hash"] for o in (a, b, c)}
    out = scenarios.combine(svc, WHO, [{"object_id": o["object_id"]}
                                       for o in (a, b, c)], name="A+B+C")
    combined = out["scenario"]
    assert combined["object_id"] not in before
    for oid, h in before.items():
        rows = _rows(svc, oid)
        assert len(rows) == 1 and rows[0]["content_hash"] == h
    assert len(combined["body"]["components"]) == 1 + 2 + 1


def test_combined_scenario_persists_parent_lineage(svc):
    a, b = _tpl(svc, "CORP-01"), _tpl(svc, "CORP-05")
    combined = scenarios.combine(svc, WHO, [
        {"object_id": a["object_id"], "version": 1},
        {"object_id": b["object_id"], "version": 1}], name="A+B")["scenario"]
    assert combined["lineage"]["origin"] == "combine"
    assert combined["lineage"]["derived_from"] == [[a["object_id"], 1],
                                                   [b["object_id"], 1]]
    parents = combined["body"]["parents"]
    assert [p["content_hash"] for p in parents] == [a["content_hash"],
                                                    b["content_hash"]]
    src = {c["component_id"]: c["source"] for c in
           combined["body"]["components"]}
    assert src["A.c1"] == {"object_id": a["object_id"], "version": 1,
                           "component_id": "c1",
                           "scenario": a["body"]["name"]}
    tree = svc.lineage_tree(combined["object_id"], service.principal(WHO))
    assert {x["object_id"] for x in tree["ancestors"]} == {a["object_id"],
                                                          b["object_id"]}


def test_overlap_blocks_until_policy_is_explicit(svc):
    a, b = _tpl(svc, "CORP-01"), _tpl(svc, "CORP-05")
    out = scenarios.combine(svc, WHO, [{"object_id": a["object_id"]},
                                       {"object_id": b["object_id"]}],
                            name="Sector + macro")
    pv = out["preview"]
    need = [m for m in pv["overlaps"] if m["status"] == "NEEDS_POLICY"]
    assert need and pv["readiness"] == "BLOCKED"
    assert {m["variable"] for m in need} == {"pd"}
    assert all(m["shared_entities"] == 248 for m in need)
    resolved = scenarios.resolve(svc, WHO, out["scenario"]["object_id"], {
        m["overlap_id"]: {"policy": "max"} for m in need})
    pv2 = _preview(resolved)
    assert pv2["readiness"] != "BLOCKED"
    assert all(m["status"] != "NEEDS_POLICY" for m in pv2["overlaps"])
    assert resolved["version"] == 2


def test_additive_policy_refused_for_mixed_operation_types(svc):
    a, b = _tpl(svc, "CORP-01"), _tpl(svc, "CORP-05")
    out = scenarios.combine(svc, WHO, [{"object_id": a["object_id"]},
                                       {"object_id": b["object_id"]}],
                            name="x")
    need = [m for m in out["preview"]["overlaps"]
            if m["status"] == "NEEDS_POLICY"]
    assert all("additive" not in m["allowed"] for m in need)
    bad = scenarios.resolve(svc, WHO, out["scenario"]["object_id"], {
        m["overlap_id"]: {"policy": "additive"} for m in need})
    pv = _preview(bad)
    assert pv["readiness"] == "BLOCKED"
    assert any(m["status"] == "INVALID_POLICY" for m in pv["overlaps"])


def test_no_policy_is_ever_assumed(svc):
    with pytest.raises(HTTPException) as err:
        lib.normalise_definition(_definition(composition_policy={
            "resolutions": {"c1|c2|pd": {"policy": "whatever"}}}),
            book=_book("corporate"))
    assert err.value.detail["error_code"] == "INVALID_COMPOSITION"


def test_seeded_conflict_templates_stay_blocked_until_chosen(svc):
    for tid in ("CORP-18", "RET-18"):
        pv = _preview(_tpl(svc, tid))
        assert pv["readiness"] == "BLOCKED"
        assert any(b["code"] == "NEEDS_COMPOSITION_POLICY"
                   for b in pv["blocking"])


def test_macro_with_macro_uses_the_governed_linear_sum(svc):
    pv = _preview(_tpl(svc, "CORP-15"))
    macro = [m for m in pv["overlaps"] if m.get("variable")]
    assert macro and all(m["status"] == "RESOLVED_BY_GOVERNED_RULE" and
                         m["policy"] == lib.GOVERNED for m in macro)
    assert pv["readiness"] == "READY_FOR_CONFIRMATION"


# ---- governed translation ----------------------------------------------------------

def test_macro_translation_equals_the_governed_artifact(svc):
    from backend.cockpit_v4.scenario.sensitivity import artifact

    book = _book("corporate")
    t = lib.translate_macro(book, "MEV03", "basis_points", 100.0)
    rows = {r["parameter"]: r for r in book.rows(
        "SELECT * FROM whatif_corp_sensitivity WHERE factor_id='MEV03'")}
    for d in t["derived"]:
        slope = artifact.from_row({**rows[d["field"]], "source_fingerprint":
                                   rows[d["field"]].get(
                                       "source_fingerprint", "")})
        assert float(d["value"]) == pytest.approx(
            slope.native_derivative * 1.0, abs=1e-6)
    assert "100 bps = +1 percentage points" in t["conversion"]


def test_diagnostic_only_sensitivity_is_not_applied(svc):
    t = lib.translate_macro(_book("corporate"), "MEV03", "basis_points", 100.0)
    assert "lgd_pct" not in {d["field"] for d in t["derived"]}
    assert {"parameter": "lgd_pct", "readiness": "DIAGNOSTIC_ONLY"}.items() \
        <= next(e for e in t["excluded"] if e["parameter"] == "lgd_pct").items()


def test_absent_factor_is_unsupported(svc):
    t = lib.translate_macro(_book("retail"), "MEV07", "relative_percent",
                            -20.0)
    assert t["status"] == "UNSUPPORTED" and not t["derived"]


def test_relative_move_on_a_points_factor_is_not_converted(svc):
    t = lib.translate_macro(_book("corporate"), "MEV01", "relative_percent",
                            -10.0)
    assert t["status"] == "UNSUPPORTED"
    assert "not converted" in t["reason"]


def test_rating_moves_along_the_masterscale_not_the_string(svc):
    pv = _preview(_tpl(svc, "CORP-07"))
    moves = {m["from"]: m["to"] for m in
             pv["components"][0]["translation"]["moves"]}
    assert moves["BBB-"] == "BB+" and moves["BB-"] == "B+"
    assert moves["B"] == "CCC"


def test_behavioural_and_application_scores_are_never_substituted(svc):
    beh = _preview(_tpl(svc, "RET-03"))["components"][0]
    app = _preview(_tpl(svc, "RET-04"))["components"][0]
    assert beh["translation"]["column"] == "behaviour_score"
    assert beh["translation"]["scorecard_version"].startswith(
        "whatif-behaviour")
    assert app["translation"]["column"] == "application_score"
    assert app["translation"]["scorecard_version"].startswith(
        "whatif-application")
    assert app["status"] == "TRANSLATION_ONLY"
    assert beh["translation"]["unmapped"] == 0


def test_retail_ml_is_shown_unavailable_with_its_gate(svc):
    pv = _preview(_tpl(svc, "RET-01"))
    ml = pv["methods"]["ml"]
    assert ml["status"] == "UNAVAILABLE" and "G4" in ml["reason"]
    assert pv["methods"]["delta"]["status"] == "AVAILABLE"
    corp = _preview(_tpl(svc, "CORP-01"))
    assert corp["methods"]["ml"]["status"] == "AVAILABLE"


def test_unsupported_field_is_labelled_not_dropped(svc):
    pv = _preview(_tpl(svc, "RET-02"))
    ccf = next(c for c in pv["components"] if c["component_id"] == "c2")
    assert ccf["status"] == "UNSUPPORTED" and ccf["reason"]
    assert any(b["code"] == "UNSUPPORTED_COMPONENT" for b in pv["blocking"])


def test_needs_mapping_is_never_guessed(svc):
    for tid in ("RET-05", "RET-08"):
        c = _preview(_tpl(svc, tid))["components"][0]
        assert c["status"] == "NEEDS_USER_MAPPING"
        assert c["methods"]["delta"] == "NOT_COMPATIBLE"


def test_collateral_sign_review_is_flagged(svc):
    c = _preview(_tpl(svc, "RET-07"))["components"][0]
    lgd = float(c["translation"]["derived"][0]["value"])
    if lgd < 0:
        assert c.get("sign_review") is True
        assert any(w.startswith("SIGN_REVIEW") for w in
                   c["translation"]["warnings"])


# ---- scope and binding -------------------------------------------------------------

def test_scope_binds_one_customer_list_segment_top_n_or_whole_book(svc):
    book = _book("corporate")
    one = book.rows("SELECT borrower_id FROM corp_borrower_quarter LIMIT 3")
    ids = [r["borrower_id"] for r in one]
    scopes = {
        "one": {"type": "filters", "filters": [
            {"column": "borrower_id", "op": "eq", "value": ids[0]}]},
        "list": {"type": "filters", "filters": [
            {"column": "borrower_id", "op": "in", "values": ids}]},
        "segment": {"type": "filters", "filters": [
            {"column": "sector", "op": "in", "values": ["Hospitality"]}]},
        "top": {"type": "top_owners", "n": 5, "by": "ead_sar_mn"},
        "book": {"type": "whole_book"},
    }
    n = {}
    for key, scope in scopes.items():
        defn = lib.normalise_definition(_definition(scope=scope), book=book)
        n[key] = lib.preview(book, defn)["scope"]["summary"]
    assert n["one"]["owners"] == 1 and n["list"]["owners"] == 3
    assert n["top"]["owners"] == 5
    assert n["book"]["entities"] == 2996


def test_bind_to_cohort_template_creates_new_scenario_own_creates_version(svc):
    book = _book("corporate")
    coh = cohorts.freeze(book, svc, service.principal(WHO), name="Hosp",
                         filters=[{"column": "sector", "op": "in",
                                   "values": ["Hospitality"]}],
                         source={"kind": "manual"})
    tpl = _tpl(svc, "CORP-12")
    out = scenarios.bind(svc, WHO, tpl["object_id"], coh["object_id"])
    assert out["scenario"]["object_id"] != tpl["object_id"]
    assert out["cohort_check"]["status"] == "IDENTICAL"
    assert out["scenario"]["body"]["scope"]["type"] == "cohort"
    own = scenarios.create(svc, WHO, _definition())
    again = scenarios.bind(svc, WHO, own["object_id"], coh["object_id"])
    assert again["scenario"]["object_id"] == own["object_id"]
    assert again["scenario"]["version"] == 2
    pv = _preview(again["scenario"])
    assert pv["scope"]["summary"]["entities"] == \
        coh["body"]["counts"]["entities"]


def test_bind_refuses_a_cohort_from_the_other_book(svc):
    coh = cohorts.freeze(_book("retail"), svc, service.principal(WHO),
                         name="Cards", filters=[{"column": "product",
                                                 "op": "in",
                                                 "values": ["Credit Card"]}],
                         source={"kind": "manual"})
    with pytest.raises(HTTPException) as err:
        scenarios.bind(svc, WHO, _tpl(svc, "CORP-01")["object_id"],
                       coh["object_id"])
    assert err.value.detail["error_code"] == "INCOMPATIBLE_COHORT"


def test_injection_in_scope_filter_is_refused(svc):
    with pytest.raises(HTTPException):
        lib.normalise_definition(_definition(scope={
            "type": "filters", "filters": [
                {"column": "sector; DROP TABLE x", "op": "eq",
                 "value": "a"}]}), book=_book("corporate"))
    with pytest.raises(HTTPException):
        lib.normalise_definition(_definition(scope={
            "type": "top_owners", "n": 5, "by": "ead_sar_mn) --"}),
            book=_book("corporate"))


def test_units_are_never_confused(svc):
    with pytest.raises(HTTPException):
        lib.normalise_definition(_definition(components=[
            {"kind": "parameter", "field": "pd_pit_12m", "operation": "percent",
             "value": "20"}]), book=_book("corporate"))
    with pytest.raises(HTTPException):
        lib.normalise_definition(_definition(components=[
            {"kind": "score", "score_type": "behaviour", "operation": "points",
             "value": "-30"}]), book=_book("retail"))


# ---- sharing ---------------------------------------------------------------------

def test_share_carries_reference_not_data_and_respects_tenant(svc):
    obj = scenarios.create(svc, WHO, _definition())
    out = scenarios.share(svc, WHO, obj["object_id"], to=["colleague"],
                          message="have a look")
    card = out["shared"][0]["card"]
    assert card["object_id"] == obj["object_id"] and card["executed"] is False
    assert "rows" not in card and "body" not in card
    colleague = service.principal(COLLEAGUE)
    seen = svc.get(obj["object_id"], colleague)
    copy = scenarios.clone(svc, COLLEAGUE, obj["object_id"], name="Mine now")
    assert copy["owner_id"] == "colleague"
    assert len(_rows(svc, obj["object_id"])) == seen["version"]
    with pytest.raises(HTTPException):
        scenarios.revise(svc, COLLEAGUE, obj["object_id"], {"name": "x"},
                         reason="not mine")
    with pytest.raises(HTTPException) as err:
        svc.get(obj["object_id"], service.principal(STRANGER))
    assert err.value.status_code == 404


# ---- HTTP -----------------------------------------------------------------------

def test_http_round_trip(client):
    listed = client.get(f"{P}/scenarios", params={"domain": "retail"}).json()
    assert listed["total"] == 18
    tpl = next(c for c in listed["scenarios"] if c["template_id"] == "RET-18")
    pv = client.post(f"{P}/scenarios/{tpl['object_id']}/preview").json()
    assert pv["readiness"] == "BLOCKED" and pv["calculated"] is False
    detail = client.get(f"{P}/scenarios/{tpl['object_id']}").json()
    assert detail["equation"] and detail["contract_hash"]
    made = client.post(f"{P}/scenarios", json={"definition": _definition()})
    assert made.status_code == 201
    other = next(c for c in client.get(f"{P}/scenarios", params={
        "domain": "corporate"}).json()["scenarios"]
        if c["template_id"] == "CORP-05")
    pre = client.post(f"{P}/scenarios/combine-preview", json={
        "sources": [{"object_id": made.json()["object_id"]},
                    {"object_id": other["object_id"]}]}).json()
    assert pre["preview"]["readiness"] == "BLOCKED"
    before = client.get(f"{P}/scenarios", params={"owner": "mine"}).json()
    assert before["total"] == 1, "combine-preview saved nothing"
    saved = client.post(f"{P}/scenarios/combine", json={
        "sources": [{"object_id": made.json()["object_id"]},
                    {"object_id": other["object_id"]}], "name": "C"})
    assert saved.status_code == 201
    meta = client.get(f"{P}/scenarios/meta").json()
    assert set(meta["policies"]) == set(lib.POLICIES)

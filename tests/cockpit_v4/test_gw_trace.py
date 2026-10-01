"""P12 — governance Trace, hash-chained ledger, governed export packages.

EVIDENCE LABEL: no model call except the scripted analyst (MODEL MOCK) where a
Cockpit thread is needed for the LLM-exchange link.
"""

# Fixtures are shared with sibling suites by import; pytest injects them by
# parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import base64
import io
import json
import sqlite3
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.cockpit_v4 import routes
from backend.llm import exchange
from backend.workspace import api as workspace_api
from backend.workspace import exchange_api, exports, runs, service
from backend.workspace.store import WorkspaceStore
from tests.cockpit_v4.test_gw_llm_exchange import _finalize_script
from tests.cockpit_v4.test_gw_runs import WHO, P, client, full_run, svc, uat_scenario, who  # noqa: F401 (fixtures)

PNG_1PX = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4d600"
    "00000049454e44ae426082")).decode()
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"></svg>'


def _zip(resp):
    assert resp.status_code == 200, resp.text
    return zipfile.ZipFile(io.BytesIO(resp.content))


def executed(client, svc):
    obj, cohort = uat_scenario(svc)
    run, result = full_run(client, obj["object_id"],
                           cohort_id=cohort["object_id"], session_id="s-t")
    return obj, cohort, run, result


# ---- the ledger ------------------------------------------------------------------

def _store(tmp_path):
    return WorkspaceStore(tmp_path / "ws.sqlite3")


def _seed(store):
    store.insert_version({"object_id": "scn-a", "version": 1,
                          "kind": "scenario", "tenant_id": "t",
                          "owner_id": "u", "body": {"x": 1}})
    store.insert_version({"object_id": "scn-a", "version": 2,
                          "kind": "scenario", "tenant_id": "t",
                          "owner_id": "u", "body": {"x": 2}})
    store.add_comment(tenant_id="t", object_id="scn-a", version=2,
                      author_id="u", body="looks right")
    store.add_share(tenant_id="t", object_id="scn-a", version=2,
                    kind="scenario", from_id="u", to_id="v", message="fyi",
                    card={})
    store.add_observation({"tenant_id": "t", "lens_id": "lens-1",
                           "lens_version": 1, "trigger": "manual",
                           "status": "SUCCEEDED", "started_at": 1.0,
                           "finished_at": 2.0, "body": {"kpis": []}})
    store.add_alert_event(tenant_id="t", alert_id="alr-1", from_state="",
                          to_state="NEW", actor_id="monitoring")


def test_every_governed_write_is_chained_and_verifies(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    report = store.verify_ledger(tenant_id="t")
    assert report["ok"] and report["entries"] == 6, report
    kinds = [e["record_kind"] for e in store.ledger(tenant_id="t")]
    assert kinds == ["object", "object", "comment", "share", "observation",
                     "alert_event"]
    entries = store.ledger(tenant_id="t")
    assert entries[0]["prev_hash"] == "0" * 64
    for a, b in zip(entries, entries[1:], strict=False):
        assert b["prev_hash"] == a["chain_hash"]
    # Tenants have separate chains.
    store.insert_version({"object_id": "scn-z", "version": 1,
                          "kind": "scenario", "tenant_id": "other",
                          "owner_id": "w", "body": {}})
    assert store.ledger(tenant_id="other")[0]["prev_hash"] == "0" * 64
    assert store.verify_ledger(tenant_id="t")["entries"] == 6


@pytest.mark.parametrize("table", ["lens_observations", "alert_events",
                                   "comments", "shares", "ledger", "objects"])
def test_governed_tables_refuse_update_and_delete(tmp_path, table):
    store = _store(tmp_path)
    _seed(store)
    conn = sqlite3.connect(tmp_path / "ws.sqlite3")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute(f"DELETE FROM {table}")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute(f"UPDATE {table} SET tenant_id='x'")


def test_tampering_around_the_triggers_is_detected_not_trusted(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    conn = sqlite3.connect(tmp_path / "ws.sqlite3")
    conn.execute("DROP TRIGGER shares_no_update")
    conn.execute("UPDATE shares SET to_id='attacker'")
    conn.execute("DROP TRIGGER objects_no_update")
    # Permissions are not part of the body hash: only the ledger sees this.
    conn.execute("UPDATE objects SET permissions='{\"visibility\":\"tenant\"}'"
                 " WHERE version=1")
    conn.execute("INSERT INTO alert_events VALUES ('ae-x','t','alr-1','NEW',"
                 "'RESOLVED','x','','',9)")
    conn.execute("DROP TRIGGER comments_no_delete")
    conn.execute("DELETE FROM comments")
    conn.commit()
    report = store.verify_ledger(tenant_id="t")
    problems = {(p["problem"], p["record_id"].split("-")[0])
                for p in report["problems"]}
    assert not report["ok"]
    assert ("ALTERED", "shr") in problems
    assert ("ALTERED", "scn") in problems
    assert ("UNLEDGERED", "ae") in problems
    assert ("MISSING", "cmt") in problems
    # A restart does not legitimise the row slipped in around the module.
    again = WorkspaceStore(tmp_path / "ws.sqlite3").verify_ledger(
        tenant_id="t")
    assert any(p["problem"] == "UNLEDGERED" for p in again["problems"])


def test_a_pre_ledger_store_is_backfilled_once_and_marked(tmp_path):
    path = tmp_path / "old.sqlite3"
    store = WorkspaceStore(path)
    _seed(store)
    # Simulate a store written before the ledger existed.
    conn = sqlite3.connect(path)
    conn.executescript("DROP TRIGGER ledger_no_delete; DELETE FROM ledger; "
                       "DELETE FROM meta WHERE key='ledger_since';")
    conn.commit()
    reopened = WorkspaceStore(path)
    report = reopened.verify_ledger(tenant_id="t")
    assert report["ok"] and report["backfilled"] == 6, report
    assert json.loads(reopened.meta("ledger_since"))["backfilled"] == 6


def test_credentials_are_never_persisted(tmp_path):
    store = _store(tmp_path)
    key = "sk-ant-api03-" + "Z" * 40
    store.insert_version({"object_id": "fnd-1", "version": 1,
                          "kind": "finding", "tenant_id": "t",
                          "owner_id": "u", "title": f"note {key}",
                          "body": {"statement": f"my key is {key}",
                                   "api_key": "plain-value-123",
                                   "evidence": ["Bearer abcdefghijklmnop"],
                                   "membership_hash": "a" * 64}})
    store.add_comment(tenant_id="t", object_id="fnd-1", version=1,
                      author_id="u", body="password=hunter2hunter2")
    store.add_alert_event(tenant_id="t", alert_id="a", from_state="",
                          to_state="NEW", actor_id="u",
                          note=f"token {key}")
    got = store.get("fnd-1", tenant_id="t")
    assert got["body"]["membership_hash"] == "a" * 64  # hashes untouched
    assert got["body"]["api_key"] == exchange.REDACTED
    for db in tmp_path.glob("ws.sqlite3*"):
        raw = db.read_bytes()
        for secret in (b"sk-ant-api03", b"abcdefghijklmnop", b"hunter2",
                       b"plain-value-123"):
            assert secret not in raw, (db.name, secret)


# ---- the Trace -------------------------------------------------------------------------

def test_result_trace_shows_versions_hashes_lineage_and_method_decisions(
        client, svc):
    obj, cohort, run, result = executed(client, svc)
    t = client.get(f"{P}/trace/objects/{result['object_id']}").json()
    assert t["kind"] == "scenario_result" and t["model_calls"] == 0
    assert t["integrity"]["ok"], t["integrity"]
    v1 = t["versions"][0]
    assert v1["content_hash"] == result["content_hash"]
    assert v1["ledger"]["links"] and v1["ledger"]["row_matches"]
    assert {"contract_digest", "execution_digest"} <= set(t["digests"])
    ancestors = {a["object_id"] for a in t["lineage"]["ancestors"]}
    # result <- run <- scenario + cohort, walked to the roots.
    assert {run["object_id"], obj["object_id"],
            cohort["object_id"]} <= ancestors
    rt = client.get(f"{P}/trace/objects/{run['object_id']}").json()
    states = [e["detail"].split(":")[0] for e in rt["events"]
              if e["type"] == "run_state"]
    assert states.index(runs.METHOD_SELECTION) < states.index(
        runs.READY_TO_EXECUTE) < states.index(runs.EXECUTED)
    assert any("method chosen: Method 1 — Delta" in e["detail"]
               for e in rt["events"])
    assert len(rt["versions"]) >= 4
    assert all(v["ledger"]["links"] for v in rt["versions"])


def test_trace_is_only_for_those_who_may_open_the_object(client, svc, who):
    _o, _c, _r, result = executed(client, svc)
    who.update({"id": "stranger", "tenant": "other-tenant"})
    assert client.get(
        f"{P}/trace/objects/{result['object_id']}").status_code == 404
    who.update({"id": "colleague", "tenant": "demo-tenant"})
    assert client.get(
        f"{P}/trace/objects/{result['object_id']}").status_code == 404


def test_ledger_verify_endpoint(client, svc):
    executed(client, svc)
    report = client.get(f"{P}/trace/ledger/verify").json()
    assert report["ok"] and report["entries"] > 5, report


# ---- export packages: reopen/export parity ---------------------------------------------

def test_result_package_carries_exact_tables_definitions_and_manifest(
        client, svc):
    obj, cohort, run, result = executed(client, svc)
    resp = client.post(f"{P}/exports/objects/{result['object_id']}", json={
        "snapshots": [
            {"name": "waterfall-selected", "format": "svg", "data": SVG},
            {"name": "waterfall-total", "format": "png", "data": PNG_1PX},
            {"name": "waterfall-selected", "format": "plotly",
             "data": {"data": [{"type": "bar", "y": [1]}], "layout": {}}}]})
    zf = _zip(resp)
    manifest = json.loads(zf.read("manifest.json"))
    names = set(zf.namelist())
    assert manifest["root"]["content_hash"] == result["content_hash"]
    assert resp.headers["X-Package-Root-Hash"] == result["content_hash"]
    # Every listed file hashes to the manifest; nothing unlisted.
    for path, sha in manifest["files"].items():
        assert exports._sha(zf.read(path)) == sha, path
    assert names - set(manifest["files"]) == {"manifest.json"}
    # Objects exactly as stored: root, run, scenario, cohort.
    paths = {o["object_id"]: o["path"] for o in manifest["objects"]}
    assert {result["object_id"], run["object_id"], obj["object_id"],
            cohort["object_id"]} <= set(paths)
    stored = json.loads(zf.read(paths[result["object_id"]]))
    assert stored["body"] == result["body"]
    # The decomposition tables are the stored strings, component by component.
    d = result["body"]["decomposition"]["delta"]["scopes"]["selected"]
    rows = list(__import__("csv").DictReader(io.StringIO(
        zf.read("tables/decomposition_delta_selected.csv").decode())))
    assert [r["id"] for r in rows] == [c["id"] for c in sorted(
        d["components"], key=lambda c: c["order"])]
    assert [r["value"] for r in rows] == [
        "" if c["value"] is None else c["value"] for c in sorted(
            d["components"], key=lambda c: c["order"])]
    for t in ("stages", "top_contributors", "pareto", "change_distribution",
              "method_results", "decomposition_delta_total",
              "decomposition_delta_reconciliation"):
        assert f"tables/{t}.csv" in names, t
    assert {"snapshots/waterfall-selected.svg",
            "snapshots/waterfall-total.png",
            "snapshots/waterfall-selected.plotly.json"} <= names
    assert manifest["llm_exchange"]["requested"] is False
    assert not any(n.startswith("llm_exchange/") for n in names)
    trace_json = json.loads(zf.read("trace.json"))
    assert trace_json["object_id"] == result["object_id"]
    # And the package verifies against the store.
    report = client.post(f"{P}/exports/verify", content=resp.content).json()
    assert report["ok"], report
    assert report["objects_checked"] == len(manifest["objects"])


def _rewrite(data: bytes, edit) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    files = {n: src.read(n) for n in src.namelist()}
    edit(files)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for n, d in files.items():
            zf.writestr(n, d)
    return out.getvalue()


def test_an_edited_package_is_reported_not_trusted(client, svc):
    _o, _c, _r, result = executed(client, svc)
    data = client.get(f"{P}/exports/objects/{result['object_id']}").content

    def tamper_table(files):
        files["tables/pareto.csv"] += b"Invented,sector,1.0,1.0\n"
    report = client.post(f"{P}/exports/verify",
                         content=_rewrite(data, tamper_table)).json()
    assert {"path": "tables/pareto.csv", "problem": "FILE_ALTERED"} in \
        report["problems"]

    def tamper_and_rehash(files):
        tamper_table(files)
        m = json.loads(files["manifest.json"])
        m["files"]["tables/pareto.csv"] = exports._sha(
            files["tables/pareto.csv"])
        files["manifest.json"] = json.dumps(m).encode()
    report = client.post(f"{P}/exports/verify",
                         content=_rewrite(data, tamper_and_rehash)).json()
    assert {"path": "tables/pareto.csv",
            "problem": "TABLE_DIFFERS_FROM_STORE"} in report["problems"]

    def tamper_body(files):
        path = f"objects/{result['object_id']}@v{result['version']}.json"
        o = json.loads(files[path])
        o["body"]["scenario_name"] = "something else"
        files[path] = json.dumps(o).encode()
        m = json.loads(files["manifest.json"])
        m["files"][path] = exports._sha(files[path])
        files["manifest.json"] = json.dumps(m).encode()
    report = client.post(f"{P}/exports/verify",
                         content=_rewrite(data, tamper_body)).json()
    assert any(p["problem"] == "BODY_DOES_NOT_HASH_TO_MANIFEST"
               for p in report["problems"])

    def smuggle(files):
        files["extra.txt"] = b"not from CreditProbe"
    report = client.post(f"{P}/exports/verify",
                         content=_rewrite(data, smuggle)).json()
    assert {"path": "extra.txt", "problem": "UNLISTED_FILE"} in \
        report["problems"]
    assert client.post(f"{P}/exports/verify",
                       content=b"not a zip").status_code == 422


def test_snapshots_are_validated(client, svc):
    _o, _c, _r, result = executed(client, svc)
    url = f"{P}/exports/objects/{result['object_id']}"
    bad = [{"name": "x", "format": "png", "data": base64.b64encode(
               b"GIF89a").decode()},
           {"name": "x", "format": "svg", "data": "<script>alert(1)</script>"},
           {"name": "../../etc", "format": "svg", "data": SVG},
           {"name": "x", "format": "exe", "data": ""}]
    for snap in bad:
        assert client.post(url, json={"snapshots": [snap]}).status_code \
            == 422, snap
    many = [{"name": f"s{i}", "format": "svg", "data": SVG}
            for i in range(exports.MAX_SNAPSHOTS + 1)]
    assert client.post(url, json={"snapshots": many}).status_code == 422


def test_lens_and_cohort_packages(client, svc):
    from backend.workspace import lenses
    _o, cohort, _r, _res = executed(client, svc)
    zf = _zip(client.get(f"{P}/exports/objects/{cohort['object_id']}"))
    members = zf.read("tables/members.csv").decode().splitlines()[1:]
    assert len(members) == cohort["body"]["counts"]["entities"] == 248
    membership = json.loads(zf.read("manifest.json"))["membership"]
    assert membership["status"] == "IDENTICAL"
    assert membership["membership_hash"] == cohort["body"]["membership_hash"]
    lenses.ensure_seeded(svc, WHO)
    lens_id = lenses.object_id("LENS-01")
    client.post(f"{P}/lenses/{lens_id}/refresh")
    data = client.get(f"{P}/exports/objects/{lens_id}").content
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert "tables/observations.csv" in zf.namelist()
    assert json.loads(zf.read("manifest.json"))["root"]["kind"] == "lens"
    # A later refresh appends an observation: the package still verifies
    # (the log grew; nothing it holds changed).
    client.post(f"{P}/lenses/{lens_id}/refresh")
    report = client.post(f"{P}/exports/verify", content=data).json()
    assert report["ok"], report


# ---- the LLM exchange behind an object -------------------------------------------------

@pytest.fixture
def audited(store_db, runtime, svc, monkeypatch, v4_config):
    """A workspace + V4 app whose principal can be switched; the recorder on."""
    monkeypatch.setenv(exchange.FLAG, "1")
    store = exchange.store_at(exchange.store_path_for(v4_config))
    monkeypatch.setattr(exchange_api, "exchange_store", lambda: store)
    holder = {"who": {"id": "banker", "tenant": "demo-tenant",
                      "roles": ("analyst",)}}
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: holder["who"],
                   startup_sha="t")
    app.include_router(routes.router)
    app.include_router(workspace_api.router)
    return TestClient(app), holder


def _finding_on_thread(svc, thread_id):
    return svc.create("finding", service.principal(WHO), {
        "statement": "Construction PD drift explains the ECL rise",
        "evidence": {"thread_id": thread_id, "metric": "M005"},
        "confidence": "moderate", "limitations": ["synthetic book"]},
        title="Construction PD drift")


def test_trace_links_the_llm_exchange_for_auditors_only(audited, drive, svc):
    client, holder = audited
    _o, provider, record = drive("How many facilities?", _finalize_script())
    finding = _finding_on_thread(svc, record.thread_id)
    t = client.get(f"{P}/trace/objects/{finding['object_id']}").json()
    assert t["llm_exchange"]["threads"] == [record.thread_id]
    assert t["llm_exchange"]["visible"] is False  # analyst
    assert client.post(f"{P}/exports/objects/{finding['object_id']}",
                       json={"include_llm_exchange": True}).status_code == 403
    holder["who"] = {"id": "banker", "tenant": "demo-tenant",
                     "roles": ("analyst", "auditor")}
    sent = len(provider.sent)
    t = client.get(f"{P}/trace/objects/{finding['object_id']}").json()
    calls = t["llm_exchange"]["calls"]
    assert calls and calls[0]["run_id"] == record.run_id
    assert calls[0]["hashes"]["canonical_request"]
    zf = _zip(client.post(f"{P}/exports/objects/{finding['object_id']}",
                          json={"include_llm_exchange": True}))
    names = zf.namelist()
    base = f"llm_exchange/{record.run_id}/llm_exchange/call_1/"
    assert f"{base}canonical_request.json" in names
    exported = json.loads(zf.read(f"{base}canonical_request.json"))
    assert exchange.digest(exported) == calls[0]["hashes"][
        "canonical_request"]
    assert len(provider.sent) == sent  # trace and export made no model call

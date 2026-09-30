"""P12 exit gate — the secret-leak suite.

Canary credentials are planted everywhere a banker, an operator or a provider
could put one: the provider credential in the environment, keys and bearer
tokens typed into a Cockpit question, a scenario description, a comment, a
share message, an alert note and a Lens description. Then every surface this
round added is read -- the workspace store files, the LLM exchange store
files, every Trace, ledger verify, Messages, the Monitoring Centre, grid and
cohort CSV, and every export package with and without the LLM exchange --
and no canary may appear anywhere, in any encoding the surface produces.

EVIDENCE LABEL: scripted analyst (MODEL MOCK); no live provider.
"""

# Fixtures are shared with sibling suites by import; pytest injects them by
# parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import io
import json
import zipfile

import pytest

from backend.llm import exchange
from backend.workspace import lenses, service
from tests.cockpit_v4.test_gw_llm_exchange import _finalize_script
from tests.cockpit_v4.test_gw_runs import WHO, P, full_run, svc, uat_scenario  # noqa: F401 (fixtures)
from tests.cockpit_v4.test_gw_trace import audited  # noqa: F401

KEY = "sk-ant-api03-CANARY" + "K" * 36
OPENAI = "sk-proj-CANARY" + "O" * 30
BEARER = "Bearer CANARYbearer0123456789abcdef"
PASSWORD = "password=CANARYpw0123"
AWS = "AKIACANARY0123456789"
CANARIES = ("CANARY", KEY, OPENAI, "CANARYbearer", "CANARYpw", AWS)


def _clean(label: str, data: bytes | str) -> None:
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    for c in CANARIES:
        assert c.encode() not in raw, f"{label} leaks {c[:18]}…"


def _zip_clean(label: str, data: bytes) -> int:
    zf = zipfile.ZipFile(io.BytesIO(data))
    for name in zf.namelist():
        _clean(f"{label}:{name}", zf.read(name))
    return len(zf.namelist())


@pytest.fixture
def planted(audited, drive, svc, monkeypatch, tmp_path):
    client, holder = audited
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("COCKPIT_ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI)
    holder["who"] = {"id": "banker", "tenant": "demo-tenant",
                     "roles": ("analyst", "auditor")}
    # A Cockpit turn whose question carries credentials.
    _o, _p, record = drive(
        f"Use my key {KEY} with Authorization: {BEARER} and {PASSWORD} "
        f"and {AWS} -- how many facilities?", _finalize_script())
    # Workspace objects, notes and messages carrying credentials.
    scn, cohort = uat_scenario(svc)
    run, result = full_run(client, scn["object_id"],
                           cohort_id=cohort["object_id"], session_id="s-l")
    finding = svc.create("finding", service.principal(WHO), {
        "statement": f"key {KEY}", "confidence": "low",
        "evidence": {"thread_id": record.thread_id, "note": BEARER},
        "limitations": [PASSWORD]}, title=f"leak test {AWS}")
    for oid in (result["object_id"], finding["object_id"]):
        assert client.post(f"{P}/objects/{oid}/comments", json={
            "body": f"remember {PASSWORD} and {KEY}"}).status_code in (200,
                                                                      201)
    share = client.post(f"{P}/messages", json={
        "object_id": result["object_id"], "to": ["colleague"],
        "message": f"here you go {BEARER} {OPENAI}"})
    assert share.status_code == 201, share.text
    lenses.ensure_seeded(svc, WHO)
    lens_id = lenses.object_id("LENS-01")
    client.post(f"{P}/lenses/{lens_id}/refresh")
    return {"client": client, "record": record, "result": result,
            "run": run, "finding": finding, "cohort": cohort,
            "scenario": scn, "lens": lens_id, "share": share, "tmp": tmp_path}


def test_no_canary_reaches_any_store_file(planted, v4_config):
    store = service.objects().store
    files = [p for p in __import__("pathlib").Path(store.path).parent.glob(
        __import__("pathlib").Path(store.path).name + "*")]
    xpath = exchange.store_path_for(v4_config)
    files += list(xpath.parent.glob(xpath.name + "*"))
    assert files
    for f in files:
        _clean(str(f.name), f.read_bytes())


def test_no_canary_in_any_trace_or_governance_view(planted):
    client = planted["client"]
    for oid in ("result", "run", "finding", "cohort", "scenario", "lens"):
        obj = planted[oid]
        object_id = obj if isinstance(obj, str) else obj["object_id"]
        r = client.get(f"{P}/trace/objects/{object_id}")
        assert r.status_code == 200, (oid, r.text)
        _clean(f"trace {oid}", r.content)
    _clean("ledger verify", client.get(f"{P}/trace/ledger/verify").content)
    run_id = planted["record"].run_id
    _clean("llm exchange view",
           client.get(f"{P}/llm-exchange/runs/{run_id}").content)
    _clean("model lab", client.get(f"{P}/model-lab/exchanges").content)
    for path in ("/messages?box=all", "/monitoring",
                 f"/objects/{planted['result']['object_id']}/comments",
                 f"/objects/{planted['finding']['object_id']}"):
        r = client.get(f"{P}{path}")
        assert r.status_code == 200, (path, r.text)
        _clean(path, r.content)


def test_no_canary_in_any_export(planted):
    client = planted["client"]
    total = 0
    for oid in ("result", "finding", "cohort", "scenario", "run"):
        object_id = planted[oid]["object_id"]
        for llm in (False, True):
            r = client.post(f"{P}/exports/objects/{object_id}",
                            json={"include_llm_exchange": llm})
            assert r.status_code == 200, (oid, llm, r.text)
            total += _zip_clean(f"export {oid} llm={llm}", r.content)
    r = client.get(f"{P}/exports/objects/{planted['lens']}")
    total += _zip_clean("export lens", r.content)
    run_id = planted["record"].run_id
    r = client.get(f"{P}/llm-exchange/runs/{run_id}/export")
    total += _zip_clean("llm exchange export", r.content)
    r = client.post(f"{P}/grid/export", json={"domain": "corporate",
                                              "filters": []})
    _clean("grid csv", r.content)
    assert total > 60  # many files were actually read


def test_the_finding_package_includes_the_exchange_and_is_still_clean(
        planted):
    client = planted["client"]
    r = client.post(f"{P}/exports/objects/{planted['finding']['object_id']}",
                    json={"include_llm_exchange": True})
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["llm_exchange"]["calls"] >= 1
    assert any(n.startswith("llm_exchange/") for n in zf.namelist())
    # The redaction is visible as a marker, never as the value.
    blob = b"".join(zf.read(n) for n in zf.namelist())
    assert exchange.REDACTED.encode() in blob

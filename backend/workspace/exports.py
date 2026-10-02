"""
Governed export packages: a workspace object, exactly as stored, with the
tables it was drawn from, its definitions, its chart snapshots, its Trace and
-- on request, for auditors -- the sanitized LLM exchange behind it.

A package is a ZIP whose `manifest.json` names every file with its SHA-256,
every object with its version and content hash (and its entry in the
tenant's hash-chained ledger), the release and fingerprint, and what was
redacted. `verify_package` re-hashes a package and compares it with the store,
so a package that was edited after export -- or an export that no longer
matches the stored record -- is reported, not trusted ("reopen/export
parity").

Nothing here recomputes a number: tables are the stored strings, written as
they are. Every text file is scanned for credential-shaped content before it
is written, whatever its origin.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import time
import zipfile
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from backend.llm import exchange
from backend.workspace import access, service, trace
from backend.workspace.store import content_hash

PACKAGE_VERSION = 1

#: Client-rendered chart snapshots a package accepts.
MAX_SNAPSHOTS = 24
MAX_SNAPSHOT_BYTES = 6_000_000
_NAME = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,60}$")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _csv(columns: list[str], rows: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow(["" if r.get(c) is None else
                    (json.dumps(r.get(c), ensure_ascii=False, default=str)
                     if isinstance(r.get(c), (dict, list)) else r.get(c))
                    for c in columns])
    return out.getvalue()


# ---- the exact tables of each kind ------------------------------------------

def tables_for(obj: dict[str, Any]) -> dict[str, str]:
    """`tables/<name>.csv` -> CSV text, from the stored body only."""
    b, kind = obj["body"], obj["kind"]
    out: dict[str, str] = {}
    if kind == "scenario_result":
        for method, d in (b.get("decomposition") or {}).items():
            for scope in ("selected", "total"):
                s = (d.get("scopes") or {}).get(scope)
                if not s:
                    continue
                out[f"decomposition_{method}_{scope}"] = _csv(
                    ["order", "id", "label", "kind", "value", "status",
                     "reason", "definition"],
                    sorted(s.get("components", []),
                           key=lambda c: c.get("order", 0)))
            out[f"decomposition_{method}_reconciliation"] = _csv(
                ["scope", "opening", "closing", "change", "change_pct",
                 "residual", "reconciles", "identity"],
                [{"scope": k, **{f: v.get(f) for f in (
                    "opening", "closing", "change", "change_pct", "residual",
                    "reconciles", "identity")}}
                 for k, v in (d.get("scopes") or {}).items()]
                + [{"scope": "cross_scope", **(d.get("cross_scope") or {})}])
        out["method_results"] = _csv(
            ["method", "label", "status", "ran", "baseline", "scenario",
             "change", "change_pct", "reason", "limitations"],
            list((b.get("results") or {}).values()))
        for name in ("stages", "top_contributors", "pareto",
                     "change_distribution"):
            rows = b.get(name) or []
            if rows:
                out[name] = _csv(list(rows[0].keys()), rows)
    elif kind == "comparison":
        for name, rows in b.items():
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                out[name] = _csv(list(rows[0].keys()), rows)
    elif kind == "cohort":
        out["counts"] = _csv(["measure", "value"], [
            {"measure": k, "value": v} for k, v in
            {**(b.get("counts") or {}), "ead": b.get("ead"),
             "ecl": b.get("ecl")}.items()])
    elif kind == "run":
        out["state_log"] = _csv(["at", "state", "reason"],
                                b.get("state_log") or [])
    return out


def _lens_tables(store: Any, obj: dict[str, Any], tenant: str
                 ) -> dict[str, str]:
    obs = store.observations(obj["object_id"], tenant_id=tenant, limit=50)
    out = {"observations": _csv(
        ["observation_id", "status", "trigger", "period", "release_id",
         "fingerprint", "started_at", "error"], obs)}
    latest = next((o for o in obs if o["status"] == "SUCCEEDED"), None)
    if latest:
        body = latest["body"] or {}
        kpis = body.get("kpis") or []
        if kpis:
            out["latest_kpis"] = _csv(list(kpis[0].keys()), kpis)
        for name, value in (body.get("tables") or {}).items():
            rows = value.get("rows") if isinstance(value, dict) else value
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                safe = re.sub(r"[^a-z0-9_]+", "_", str(name).lower())[:40]
                out[f"latest_{safe}"] = _csv(list(rows[0].keys()), rows)
    return out


def _cohort_tables(who_raw: dict[str, Any], obj: dict[str, Any]
                   ) -> tuple[dict[str, str], dict[str, Any]]:
    """The cohort's exact members: its saved question re-resolved on the
    same release, and exported only when the membership hash is IDENTICAL
    to the one frozen (otherwise the stored snapshot, if any, and why)."""
    from backend.workspace import cohorts

    b = obj["body"]
    book = access.book(who_raw, b["domain_id"])
    check = cohorts.verify(book, obj)
    if check["identical"]:
        ids = cohorts._member_ids(book, None, cohorts.resolve_stored(book, b))
        source = "re-resolved; membership hash identical to the frozen one"
    else:
        ids = list(b.get("member_ids") or [])
        source = ("stored snapshot" if ids else "not exportable") + \
            f" ({check['status']})"
    return ({"members": _csv(["member_id"], [{"member_id": m} for m in ids])},
            {"status": check["status"], "membership_hash":
             b.get("membership_hash"), "members": len(ids),
             "source": source})


def _alert_tables(store: Any, obj: dict[str, Any], tenant: str
                  ) -> dict[str, str]:
    return {"events": _csv(["event_id", "at", "from_state", "to_state",
                            "actor_id", "note", "observed"],
                           store.alert_events(obj["object_id"],
                                              tenant_id=tenant))}


# ---- packaging -----------------------------------------------------------------

def _snapshots(snapshots: list[dict[str, Any]]) -> list[tuple[str, bytes, str]]:
    if len(snapshots) > MAX_SNAPSHOTS:
        raise HTTPException(422, {"error_code": "TOO_MANY_SNAPSHOTS",
                                  "message": f"At most {MAX_SNAPSHOTS} chart "
                                             f"snapshots per package."})
    out, total = [], 0
    for s in snapshots:
        name, fmt = str(s.get("name", "")), str(s.get("format", ""))
        if not _NAME.match(name) or fmt not in ("svg", "png", "plotly"):
            raise HTTPException(422, {"error_code": "INVALID_SNAPSHOT",
                                      "message": "A snapshot needs a simple "
                                                 "name and svg/png/plotly."})
        raw = s.get("data")
        if fmt == "png":
            try:
                data = base64.b64decode(str(raw).split(",")[-1],
                                        validate=True)
            except ValueError as err:
                raise HTTPException(422, {"error_code": "INVALID_SNAPSHOT",
                                          "message": "PNG must be base64."}
                                    ) from err
            if not data.startswith(b"\x89PNG"):
                raise HTTPException(422, {"error_code": "INVALID_SNAPSHOT",
                                          "message": "Not a PNG."})
        elif fmt == "svg":
            text = str(raw or "")
            if text.startswith("data:image/svg+xml"):
                from urllib.parse import unquote
                text = unquote(text.split(",", 1)[1])
            if "<svg" not in text[:2000]:
                raise HTTPException(422, {"error_code": "INVALID_SNAPSHOT",
                                          "message": "Not an SVG."})
            data = text.encode("utf-8")
        else:
            data = json.dumps(raw, ensure_ascii=False, sort_keys=True,
                              default=str).encode("utf-8")
        total += len(data)
        if total > MAX_SNAPSHOT_BYTES:
            raise HTTPException(413, {"error_code": "SNAPSHOTS_TOO_LARGE",
                                      "message": "Chart snapshots exceed "
                                                 f"{MAX_SNAPSHOT_BYTES} bytes."})
        ext = {"svg": "svg", "png": "png", "plotly": "plotly.json"}[fmt]
        out.append((f"snapshots/{name}.{ext}", data, fmt))
    return out


def package(who_raw: dict[str, Any], object_id: str, *,
            include_llm_exchange: bool = False,
            snapshots: list[dict[str, Any]] | None = None
            ) -> tuple[bytes, dict[str, Any]]:
    svc = service.objects()
    who = service.principal(who_raw)
    obj = svc.get(object_id, who)
    tr = trace.object_trace(who_raw, object_id)
    if include_llm_exchange:
        access.require_exchange_reader(who_raw)

    files: dict[str, bytes] = {}
    redactions: list[dict[str, str]] = []

    def text(path: str, value: str) -> None:
        found: list[dict[str, str]] = []
        clean = exchange.scrub_text(value, path, found)
        redactions.extend(found)
        files[path] = clean.encode("utf-8")

    def js(path: str, value: Any) -> None:
        found: list[dict[str, str]] = []
        clean = exchange.sanitize(value, path=path, found=found)
        redactions.extend(found)
        files[path] = json.dumps(clean, ensure_ascii=False, indent=2,
                                 sort_keys=True, default=str).encode("utf-8")

    # Objects: the root and every readable ancestor, exactly as stored.
    objects = []
    wanted = [(object_id, obj["version"])] + [
        (a["object_id"], a["version"]) for a in tr["lineage"]["ancestors"]
        if a.get("readable")]
    for oid, ver in dict.fromkeys(wanted):
        o = svc.get(oid, who, version=ver)
        path = f"objects/{oid}@v{ver}.json"
        js(path, {k: o[k] for k in (
            "object_id", "version", "kind", "title", "status", "domain_id",
            "release_id", "fingerprint", "period", "owner_id", "created_at",
            "created_by", "lineage", "tags", "content_hash", "body")})
        link = svc.store.ledger_entry(tenant_id=who.tenant, kind="object",
                                      record_id=f"{oid}@v{ver}")
        objects.append({"object_id": oid, "version": ver, "kind": o["kind"],
                        "title": o["title"], "content_hash": o["content_hash"],
                        "path": path, "root": oid == object_id,
                        "ledger": None if link is None else {
                            "seq": link["seq"],
                            "record_hash": link["record_hash"],
                            "chain_hash": link["chain_hash"]}})

    tables = tables_for(obj)
    if obj["kind"] == "lens":
        tables.update(_lens_tables(svc.store, obj, who.tenant))
    if obj["kind"] == "alert":
        tables.update(_alert_tables(svc.store, obj, who.tenant))
    membership = None
    if obj["kind"] == "cohort":
        extra, membership = _cohort_tables(who_raw, obj)
        tables.update(extra)
    for name, csv_text in tables.items():
        text(f"tables/{name}.csv", csv_text)
    js("trace.json", tr)

    snaps = []
    for path, data, fmt in _snapshots(snapshots or []):
        if fmt == "png":
            files[path] = data
        else:
            text(path, data.decode("utf-8"))
        snaps.append({"path": path, "format": fmt,
                      "source": "client-rendered from the same figure data "
                                "the page drew (Plotly)"})

    llm = {"requested": include_llm_exchange, "runs": [], "calls": 0}
    if include_llm_exchange:
        from backend.workspace import exchange_api

        for run_id in dict.fromkeys(c["run_id"] for c in
                                    tr["llm_exchange"]["calls"]):
            view = exchange_api.run_view(run_id, who_raw)
            inner = exchange_api.export_package(view)
            with zipfile.ZipFile(io.BytesIO(inner)) as zf:
                for name in zf.namelist():
                    data = zf.read(name)
                    target = f"llm_exchange/{run_id}/{name}"
                    try:
                        text(target, data.decode("utf-8"))
                    except UnicodeDecodeError:
                        files[target] = data
            llm["runs"].append(run_id)
            llm["calls"] += len(view["calls"])

    caveats = []
    if obj["kind"] == "run" and obj["status"] != "EXECUTED":
        caveats.append(f"This run was NOT executed (it is at {obj['status']})."
                       " The package holds its definition and state log "
                       "only; it carries no results.")
    readme = (
        "CreditProbe governed export package\n"
        "===================================\n\n"
        f"Object: {obj['kind']} {object_id} v{obj['version']} — "
        f"{obj['title']}\n"
        f"Release {obj['release_id']} · fingerprint {obj['fingerprint']} · "
        f"period {obj['period']}\n\n"
        "objects/   every object exactly as stored (root + readable "
        "ancestors), with its content hash\n"
        "tables/    the exact stored values behind every chart (strings as "
        "stored; nothing recomputed)\n"
        "snapshots/ chart images and Plotly figure specs rendered by the "
        "page from the same data\n"
        "trace.json versions, lineage, events, LLM exchange references and "
        "integrity\n"
        + ("llm_exchange/ the sanitized model exchange of each run\n"
           if include_llm_exchange else "")
        + "".join(f"\nCAVEAT: {c}\n" for c in caveats)
        + "\nmanifest.json lists every file's SHA-256. Verify a package "
          "with POST /api/v1/cockpit-v4/workspace/exports/verify.\n"
          "Secrets are redacted before anything is written.\n")
    text("README.txt", readme)

    ledger = svc.store.verify_ledger(tenant_id=who.tenant)
    manifest = {
        "package_version": PACKAGE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_by": who.id, "tenant_id": who.tenant,
        "root": {"object_id": object_id, "version": obj["version"],
                 "kind": obj["kind"], "content_hash": obj["content_hash"]},
        "release_id": obj["release_id"], "fingerprint": obj["fingerprint"],
        "period": obj["period"], "domain_id": obj["domain_id"],
        "objects": objects, "snapshots": snaps, "membership": membership,
        "caveats": caveats,
        "tables": sorted(f"tables/{n}.csv" for n in tables),
        "llm_exchange": llm,
        "integrity": tr["integrity"],
        "tenant_ledger": {k: ledger[k] for k in ("ok", "entries",
                                                 "chain_head",
                                                 "problem_count")},
        "secrets": {"redactions": len(redactions),
                    "paths": sorted({r["path"] for r in redactions})[:50],
                    "note": "Credential-shaped text is replaced by "
                            "[REDACTED] before writing; values are never "
                            "listed."},
        "files": {p: _sha(d) for p, d in sorted(files.items())},
        "model_calls": 0,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for p, d in sorted(files.items()):
            zf.writestr(p, d)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2,
                                                ensure_ascii=False,
                                                default=str))
    return buffer.getvalue(), manifest


# ---- verification ------------------------------------------------------------------

def verify_package(who_raw: dict[str, Any], data: bytes) -> dict[str, Any]:
    """Re-hash a package and hold it against the store.

    * every file listed must be present and hash to its manifest entry, and
      nothing unlisted may ride along;
    * every object file must hash (its body) to its content hash, and that
      content hash must be the one the store holds for the same version;
    * the tables must be byte-identical to what the stored version produces
      now (reopen/export parity).
    """
    problems: list[dict[str, Any]] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as err:
        raise HTTPException(422, {"error_code": "NOT_A_PACKAGE",
                                  "message": "Not a ZIP package."}) from err
    names = set(zf.namelist())
    if "manifest.json" not in names:
        raise HTTPException(422, {"error_code": "NOT_A_PACKAGE",
                                  "message": "No manifest.json."})
    manifest = json.loads(zf.read("manifest.json"))
    listed = manifest.get("files", {})
    for path, sha in listed.items():
        if path not in names:
            problems.append({"path": path, "problem": "MISSING"})
        elif _sha(zf.read(path)) != sha:
            problems.append({"path": path, "problem": "FILE_ALTERED"})
    for extra in sorted(names - set(listed) - {"manifest.json"}):
        problems.append({"path": extra, "problem": "UNLISTED_FILE"})

    svc = service.objects()
    who = service.principal(who_raw)
    checked = 0
    for o in manifest.get("objects", []):
        if o["path"] not in names:
            continue
        stored_copy = json.loads(zf.read(o["path"]))
        if content_hash(stored_copy.get("body")) != o["content_hash"]:
            problems.append({"path": o["path"],
                             "problem": "BODY_DOES_NOT_HASH_TO_MANIFEST"})
        try:
            live = svc.get(o["object_id"], who, version=o["version"])
        except HTTPException:
            problems.append({"path": o["path"],
                             "problem": "NOT_AVAILABLE_TO_YOU"})
            continue
        checked += 1
        if live["content_hash"] != o["content_hash"]:
            problems.append({"path": o["path"],
                             "problem": "DIFFERS_FROM_STORE"})
        if o.get("root"):
            parity = tables_for(live)
            if live["kind"] == "lens":
                parity.update(_lens_tables(svc.store, live, who.tenant))
            if live["kind"] == "alert":
                parity.update(_alert_tables(svc.store, live, who.tenant))
            if live["kind"] == "cohort":
                parity.update(_cohort_tables(who_raw, live)[0])
            for name, csv_text in parity.items():
                path = f"tables/{name}.csv"
                clean = exchange.scrub_text(csv_text, path, [])
                if path not in names:
                    problems.append({"path": path,
                                     "problem": "TABLE_MISSING"})
                    continue
                exported = zf.read(path).decode("utf-8")
                if live["kind"] in ("lens", "alert") and not \
                        name.startswith("latest_"):
                    # Append-only logs grow after export: every exported
                    # row must still be there, unchanged.
                    gone = set(exported.splitlines()) - set(
                        clean.splitlines())
                    if gone:
                        problems.append({"path": path, "problem":
                                         "TABLE_ROWS_NOT_IN_STORE",
                                         "rows": len(gone)})
                elif live["kind"] in ("lens", "alert"):
                    continue  # the latest view moves with each refresh
                elif exported != clean:
                    problems.append({"path": path,
                                     "problem": "TABLE_DIFFERS_FROM_STORE"})
    return {"ok": not problems, "files_checked": len(listed),
            "objects_checked": checked, "problems": problems,
            "root": manifest.get("root"), "verified_at": time.time()}


__all__ = ["MAX_SNAPSHOTS", "MAX_SNAPSHOT_BYTES", "PACKAGE_VERSION",
           "package", "tables_for", "verify_package"]

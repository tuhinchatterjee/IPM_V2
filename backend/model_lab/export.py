"""
The comparison evidence pack. Built from STORED data only; it never calls a
model, and building it twice gives the same content (a new revision number,
the same checksums for unchanged files).

Security: every CSV/XLSX text cell that could be read as a formula is
prefixed with a quote; HTML is escaped and carries no model-authored script
or URL; ZIP member names are fixed, sanitised paths; credentials and hidden
reasoning never enter the pack; record-level rows beyond a bounded preview
are omitted and listed in the omission ledger.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any

from backend.model_lab import FROZEN_COMMIT, LAB_VERSION, RELEASE_CLAIM

MAX_ARTIFACT_ROWS = 200
_FORMULA = ("=", "+", "-", "@", "\t", "\r")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_cell(v: Any) -> Any:
    """CSV/Excel formula-injection guard. Numbers stay numbers."""
    if v is None or isinstance(v, (int, float, bool)):
        return v
    s = str(v)
    if s and s[0] in _FORMULA:
        # A negative number is data, not a formula.
        try:
            float(s)
            return s
        except ValueError:
            return "'" + s
    return s


def safe_name(s: str) -> str:
    s = _SAFE_NAME.sub("_", str(s)).strip("._")[:80]
    return s or "item"


def _metric_cols(prefix: str, m: dict[str, Any] | None) -> dict[str, Any]:
    m = m or {}
    return {f"{prefix}": m.get("value"), f"{prefix}_unit": m.get("unit"),
            f"{prefix}_status": m.get("status"),
            f"{prefix}_source": m.get("source"),
            f"{prefix}_missing_reason": m.get("missing_reason")}


# ---- rows (one calculation source for UI, CSV, XLSX, manifest) ------------

def rows(ev: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    cid = ev["comparison_id"]
    out: dict[str, list[dict[str, Any]]] = {
        k: [] for k in ("summary", "stages", "calls", "checks", "claims",
                        "failures", "resource_samples", "opus_match")}
    for k in ev["children"]:
        m = k.get("metrics") or {}
        base = {"comparison_id": cid, "child_run_id": k["child_run_id"],
                "attempt_id": k["attempt_id"], "profile_id": k["profile_id"],
                "display_name": k["display_name"],
                "evidence_class": "fixture" if k["fixture"] else "natural"}
        row = base | {
            "execution_state": k["execution_state"],
            "frozen_state": k.get("frozen_state"),
            "error_code": k.get("error_code") or "",
            "reason": k.get("reason") or "",
            "requested_model": k.get("requested_model"),
            "request_controls": (json.dumps(k["request_controls"],
                                            sort_keys=True)
                                 if k.get("request_controls") else ""),
            "reasoning_variant": k.get("reasoning_variant") or "",
            "identity_status": (k.get("identity") or {}).get("status"),
            "repetition": k["repetition"], "lineage": k.get("lineage"),
            "first_divergence": (k.get("first_divergence") or {}).get(
                "summary"),
            "checks_passed": sum(1 for c in k["checks"]
                                 if c["outcome"] == "PASS"),
            "checks_failed": sum(1 for c in k["checks"]
                                 if c["outcome"] == "FAIL"),
            "checks_unassessed": sum(1 for c in k["checks"]
                                     if c["outcome"] not in ("PASS",
                                                             "FAIL")),
            "claims_contradicted": k["claim_rates"]["contradicted_rate"][
                "display"],
            "claims_unsupported": k["claim_rates"]["unsupported_rate"][
                "display"],
            "claims_assessed_of_extracted": k["claim_rates"][
                "assessment_coverage"]["display"],
            "required_output_coverage": k["claim_rates"][
                "required_output_coverage"]["display"],
            "repair_status": k["repair"]["status"],
            "repair_opportunities": k["repair"]["opportunities"],
            "valid_repairs": k["repair"]["valid_repairs"],
        }
        for name in ("service_ms", "queue_delay_ms", "provider_call_ms",
                     "creditprobe_ms", "unallocated_ms", "user_wait_ms",
                     "load_ms", "first_protocol_event_ms", "input_tokens",
                     "output_tokens", "peak_context_tokens",
                     "reasoning_tokens", "cost_usd",
                     "infrastructure_cost_usd"):
            row |= _metric_cols(name, m.get(name))
        out["summary"].append(row)
        for s, v in (k.get("stages") or {}).items():
            out["stages"].append(base | {
                "stage": s, "status": v["status"], "note": v.get("note", ""),
                "calls": " ".join(v.get("calls") or []),
                "shared_calls": " ".join(v.get("shared_calls") or []),
                "checks": " ".join(v.get("checks") or []),
                "evidence_confidence": v.get("evidence_confidence"),
                "timing_rule": "shared calls are counted once, by call_id; "
                               "no per-stage split of a shared span"})
        for c in k.get("calls") or []:
            out["calls"].append(base | {
                x: (" ".join(c[x]) if isinstance(c.get(x), list) else
                    json.dumps(c[x]) if isinstance(c.get(x), dict) else
                    c.get(x))
                for x in ("call_id", "run_id", "turn_index", "seq", "purpose",
                          "phase", "stage_tags", "tool_names", "outcome",
                          "usable", "stop_reason", "duration_ms",
                          "input_tokens", "output_tokens",
                          "cache_read_tokens", "cache_write_tokens",
                          "token_status", "token_source", "protocol_flag",
                          "errors_returned", "request_controls",
                          "reasoning_chars")} | {"duration_ms_unit": "ms"})
        for c in k["checks"]:
            out["checks"].append(base | {
                "check_id": c["check_id"], "stage": c["stage"],
                "kind": c["kind"], "outcome": c["outcome"],
                "expected": json.dumps(c.get("expected"), default=str),
                "actual": json.dumps(c.get("actual"), default=str),
                "tolerance": json.dumps(c.get("tolerance")),
                "truth_source": c.get("truth_source"),
                "severity": c.get("severity"), "status": c.get("status"),
                "evidence_ref": json.dumps(c.get("evidence_ref"))})
        for cl in k["claims"]:
            out["claims"].append(base | {
                x: (json.dumps(cl[x], default=str)
                    if isinstance(cl.get(x), (list, dict)) else cl.get(x))
                for x in ("claim_id", "answer_span_ref", "extracted_text",
                          "claim_type", "asserted_value", "units",
                          "verification_status", "extraction_method",
                          "extraction_confidence_class", "materiality",
                          "reviewer_status", "explanation", "result_refs")})
        for f in k.get("failures") or []:
            out["failures"].append(base | {
                x: (json.dumps(f[x], default=str)
                    if isinstance(f.get(x), (list, dict)) else f.get(x))
                for x in ("primary_category", "supporting_categories",
                          "symptom", "failed_requirement", "likely_owner",
                          "origin_confidence", "affected_stages",
                          "inherited_effects", "earliest_event", "severity",
                          "next_diagnostic", "intervention_category",
                          "approval_needed", "model_failure")})
        for s, v in (k.get("opus_match") or {}).items():
            out["opus_match"].append(base | {
                "stage": s, "match_pct": v.get("pct"),
                "display": v.get("display"), "assessed": v.get("assessed"),
                "defined": v.get("defined"), "reason": v.get("reason"),
                "checks": json.dumps(v.get("checks"), default=str),
                "comparator": ev["comparator"]["profile_id"],
                "comparator_is_opus": ev["comparator"]["is_opus"]})
    return out


def resource_rows(events: list[dict]) -> list[dict[str, Any]]:
    out = []
    for e in events:
        if e["event_type"] != "resource.samples":
            continue
        p = e.get("payload_obj") or {}
        out.append({"comparison_id": e["comparison_id"],
                    "child_run_id": e["child_run_id"],
                    "method": p.get("method"),
                    "interval_s": p.get("interval_s"), "n": p.get("n"),
                    "peak_lab_rss_mb": p.get("peak_lab_rss_mb"),
                    "peak_lab_rss_status": p.get("peak_lab_rss_status"),
                    "min_system_available_mb":
                    p.get("min_system_available_mb"),
                    "model_runtime_memory": p.get("model_runtime_memory"),
                    "model_runtime_memory_reason":
                    p.get("model_runtime_memory_reason"),
                    "gpu": p.get("gpu"), "gpu_reason": p.get("gpu_reason"),
                    "memory_semantics": (p.get("host") or {}).get(
                        "memory_semantics")})
    return out


def _csv(rows_: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    cols: list[str] = []
    for r in rows_:
        for k in r:
            if k not in cols:
                cols.append(k)
    w = csv.DictWriter(buf, fieldnames=cols or ["empty"])
    w.writeheader()
    for r in rows_:
        w.writerow({k: safe_cell(r.get(k)) for k in cols})
    return buf.getvalue().encode("utf-8")


def _xlsx(ev: dict[str, Any], tables: dict[str, list[dict]],
          manifest: dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Read Me"
    for line in [
        ["CreditProbe model comparison — " + RELEASE_CLAIM],
        ["comparison_id", ev["comparison_id"]],
        ["frozen source", FROZEN_COMMIT], ["lab build", LAB_VERSION],
        ["evaluator", ev["evaluator_version"]],
        ["oracle", ev["oracle_version"]],
        ["comparator", ev["comparator"]["profile_id"],
         ev["comparator"]["status"], ev["comparator"]["note"]],
        ["Blank cells are UNKNOWN / UNAVAILABLE, never zero. Each metric "
         "has _status and _missing_reason columns."],
        ["Shared-stage calls appear once in Calls; do not add stage rows "
         "together."],
        ["Opus Match is agreement with the comparator, not correctness."],
    ]:
        ws.append([safe_cell(x) for x in line])
    ws["A1"].font = Font(bold=True, size=13)
    sheets = [("Models & Profiles", "profiles"), ("Summary", "summary"),
              ("Four Stages", "stages"), ("Calls", "calls"),
              ("Validation Checks", "checks"), ("Claim Review", "claims"),
              ("Failure Diagnosis", "failures"), ("Opus Match", "opus_match"),
              ("Costs & Resources", "resource_samples")]
    for title, key in sheets:
        data = tables.get(key) or []
        s = wb.create_sheet(title)
        cols: list[str] = []
        for r in data:
            for k in r:
                if k not in cols:
                    cols.append(k)
        cols = cols or ["(no rows)"]
        s.append(cols)
        for c in s[1]:
            c.font = Font(bold=True)
        for r in data:
            s.append([safe_cell(r.get(c)) if not isinstance(r.get(c),
                                                            (dict, list))
                      else safe_cell(json.dumps(r.get(c), default=str))
                      for c in cols])
        s.freeze_panes = "A2"
        s.auto_filter.ref = s.dimensions
        for i, c in enumerate(cols, 1):
            s.column_dimensions[get_column_letter(i)].width = min(
                48, max(10, len(c) + 2))
    rep = wb.create_sheet("Reproducibility")
    for k, v in manifest.items():
        rep.append([safe_cell(k), safe_cell(json.dumps(v, default=str)
                                            if isinstance(v, (dict, list))
                                            else v)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _esc(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _answer_html(k: dict[str, Any]) -> str:
    a = k.get("answer") or {}
    parts = [f"<h1>{_esc(k['display_name'])}</h1>",
             f"<p><b>State:</b> {_esc(k['execution_state'])} "
             f"({_esc(k.get('frozen_state'))}) {_esc(k.get('error_code'))}"
             f"</p>"]
    if k["fixture"]:
        parts.append("<p><b>FIXTURE</b>: deterministic demonstration, not "
                     "a model.</p>")
    parts.append(f"<h2>Answer</h2><pre>{_esc(a.get('narrative'))}</pre>")
    if a.get("clarification_question"):
        parts.append(f"<p><b>Clarification asked:</b> "
                     f"{_esc(a['clarification_question'])}</p>")
    for t in a.get("tables") or []:
        rows_ = t.get("rows") or []
        cols = t.get("columns") or []
        parts.append(f"<h3>{_esc(t.get('title'))}</h3><table border=1>"
                     "<tr>" + "".join(f"<th>{_esc(c)}</th>" for c in cols)
                     + "</tr>")
        for r in rows_[:MAX_ARTIFACT_ROWS]:
            disp = r.get("display") or r
            parts.append("<tr>" + "".join(f"<td>{_esc(disp.get(c))}</td>"
                                          for c in cols) + "</tr>")
        parts.append("</table>")
    if a.get("limitations"):
        parts.append("<h3>Limitations</h3><ul>" + "".join(
            f"<li>{_esc(x)}</li>" for x in a["limitations"]) + "</ul>")
    return ("<!doctype html><meta charset=utf-8><meta http-equiv="
            "\"Content-Security-Policy\" content=\"default-src 'none'; "
            "style-src 'unsafe-inline'\"><title>answer</title>"
            + "".join(parts))


def _readme(ev: dict[str, Any], manifest: dict[str, Any],
            files: list[str]) -> str:
    rows_ = "".join(
        f"<tr><td>{_esc(k['display_name'])}</td>"
        f"<td>{_esc('FIXTURE' if k['fixture'] else 'model')}</td>"
        f"<td>{_esc(k['execution_state'])}</td>"
        + "".join(f"<td>{_esc((k.get('stages') or {}).get(s, {}).get('status'))}"
                  f"</td>" for s in ("S1", "S2", "S3", "S4"))
        + f"<td>{_esc((k.get('first_divergence') or {}).get('summary'))}</td>"
        f"<td>{_esc(k.get('reason'))}</td></tr>"
        for k in ev["children"])
    return f"""<!doctype html><meta charset=utf-8>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Comparison {_esc(ev['comparison_id'])}</title>
<style>body{{font:14px system-ui;margin:24px;max-width:1100px}}td,th{{border:1px solid #999;padding:4px 6px}}table{{border-collapse:collapse}}</style>
<h1>Model comparison {_esc(ev['comparison_id'])} — {_esc(RELEASE_CLAIM)}</h1>
<p>Question: <b>{_esc(manifest['question_text'])}</b></p>
<p>Frozen source {_esc(FROZEN_COMMIT[:12])} · data {_esc(manifest['data_snapshot_id'])} ·
evaluator {_esc(ev['evaluator_version'])} · comparator {_esc(ev['comparator']['profile_id'])}
({_esc(ev['comparator']['status'])})</p>
<p>{_esc(ev['summary']['note'])}. Blank = unknown, never zero.
Opus Match is agreement with the comparator, never correctness.</p>
<table><tr><th>Model</th><th>Class</th><th>Execution</th><th>S1</th><th>S2</th><th>S3</th><th>S4</th><th>First divergence</th><th>Reason</th></tr>{rows_}</table>
<h2>Files</h2><ul>{''.join(f'<li>{_esc(f)}</li>' for f in files)}</ul>
<p>Reproduce: re-open this comparison in the lab (no model call) or verify
checksums.sha256. Reproducibility warning: a rerun is a NEW attempt and may
differ; model outputs are not deterministic.</p>
"""


def build(coord, cid: str, ev: dict[str, Any], out_dir: Path,
          *, partial: bool = False) -> dict[str, Any]:
    tenant = coord.cfg.tenant_id
    status = coord.status(cid)
    events = coord.store.events(cid, tenant, 0, 100000)
    for e in events:
        if e.get("payload_ref") and e["event_type"] in (
                "resource.samples",):
            e["payload_obj"] = json.loads(coord.store.get_blob(
                e["payload_ref"]))
    tables = rows(ev)
    tables["resource_samples"] = resource_rows(events)
    tables["profiles"] = [
        {"profile_id": c["profile_id"], "display_name": c["display_name"],
         "profile_digest": c["profile_digest"], "state": c["state"],
         "reason": c["reason"], "fixture": c["fixture"],
         "requested_model": next((k["requested_model"] for k in
                                  ev["children"] if k["child_run_id"] ==
                                  c["child_run_id"]), None)}
        for c in status["children"]]
    spec = status["spec"]
    omissions = [{"item": "record-level rows beyond "
                  f"{MAX_ARTIFACT_ROWS} per artifact", "reason":
                  "bounded preview; full data stays in the lab store"},
                 {"item": "provider credentials", "reason": "never stored"},
                 {"item": "hidden reasoning", "reason": "not requested or "
                  "available (OG-06)"},
                 {"item": "full system prompts", "reason": "redacted "
                  "default; hashes in manifest"}]
    manifest = {
        "comparison_id": cid, "spec_hash": status["spec_hash"],
        "state": status["state"], "partial_snapshot": partial,
        "frozen_source_id": FROZEN_COMMIT, "lab_build_id": LAB_VERSION,
        "evaluator_version": ev["evaluator_version"],
        "oracle_version": ev["oracle_version"],
        "question_text": spec["question_text"],
        "data_snapshot_id": spec["data_snapshot_id"],
        "catalogue_hash": spec["catalogue_hash"],
        "tools_hash": spec["tools_hash"], "policy_hash": spec["policy_hash"],
        "protected_manifest_hash": spec["protected_manifest_hash"],
        "profile_digests": spec["profile_digests"],
        "comparator": ev["comparator"],
        "comparison_class": ev["comparison_class"],
        "release_claim": RELEASE_CLAIM, "generated_at": time.time(),
        "omissions": omissions, "task": ev.get("task"),
    }
    files: dict[str, bytes] = {}
    files["manifest.json"] = json.dumps(manifest, indent=1, default=str,
                                        sort_keys=True).encode()
    for key, name in (("summary", "summary.csv"), ("stages", "stages.csv"),
                      ("calls", "calls.csv"), ("checks", "checks.csv"),
                      ("claims", "claims.csv"), ("failures", "failures.csv"),
                      ("opus_match", "opus_match.csv"),
                      ("resource_samples", "resource_samples.csv")):
        files[name] = _csv(tables[key])
    files["comparison.xlsx"] = _xlsx(ev, tables, manifest)
    sanitized = []
    for e in events:
        e = {k: v for k, v in e.items() if k != "payload_obj"}
        sanitized.append(json.dumps(e, default=str, sort_keys=True))
    files["events.jsonl"] = ("\n".join(sanitized) + "\n").encode()
    files["reviews.jsonl"] = ("\n".join(json.dumps(r, default=str)
                                        for r in coord.store.reviews(
                                            cid, tenant)) + "\n").encode()
    lim = ["# Limitations", "", f"- Release claim: {RELEASE_CLAIM}.",
           "- One question is a concrete finding, not a ranking.",
           "- Blank values are unknown, never zero."]
    if any(k["fixture"] for k in ev["children"]):
        lim.append("- FIXTURE rows are deterministic demonstrations through "
                   "the real engine; they are not model results.")
    if ev["comparator"]["status"] != "READY":
        lim.append(f"- {ev['comparator']['status']}: no 'versus comparator' "
                   f"delta is valid.")
    for o in omissions:
        lim.append(f"- Omitted: {o['item']} ({o['reason']}).")
    files["limitations.md"] = ("\n".join(lim) + "\n").encode()
    for k in ev["children"]:
        d = f"answers/{safe_name(k['child_run_id'])}"
        files[f"{d}/answer.html"] = _answer_html(k).encode()
        files[f"{d}/answer.txt"] = ((k.get("answer") or {}).get(
            "narrative") or "").encode()
        subs = []
        for t in k.get("turns") or []:
            for s in coord.runs.submissions_for_run(t["run_id"]):
                p = s.get("payload") or {}
                subs.append({"submission_id": s.get("submission_id"),
                             "steps": [{"step_id": st.get("step_id"),
                                        "language": st.get("language"),
                                        "code": st.get("code")}
                                       for st in p.get("steps") or []]})
        files[f"artifacts/{safe_name(k['child_run_id'])}/submissions.json"] \
            = json.dumps(subs, indent=1).encode()
    names = sorted(files)
    files["README.html"] = _readme(ev, manifest, names).encode()
    checks = "".join(f"{hashlib.sha256(files[n]).hexdigest()}  {n}\n"
                     for n in sorted(files))
    files["checksums.sha256"] = checks.encode()

    prev = coord.store.latest_export(cid, tenant)
    revision = (prev["revision"] + 1) if prev else 1
    out_dir.mkdir(parents=True, exist_ok=True)
    zname = f"comparison_{safe_name(cid)}_{revision}.zip"
    zpath = out_dir / zname
    try:
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for n in sorted(files):
                assert not n.startswith("/") and ".." not in n.split("/")
                info = zipfile.ZipInfo(n, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, files[n])
        sha = hashlib.sha256(zpath.read_bytes()).hexdigest()
        rec = coord.store.add_export(cid, tenant, "READY", path=str(zpath),
                                     sha=sha)
        return {"state": "READY", "path": str(zpath), "sha256": sha,
                "revision": rec["revision"], "files": sorted(files),
                "tables": tables, "manifest": manifest}
    except Exception as exc:  # noqa: BLE001
        coord.store.add_export(cid, tenant, "FAILED_RETRYABLE",
                               error=str(exc))
        return {"state": "FAILED_RETRYABLE", "error": str(exc)}

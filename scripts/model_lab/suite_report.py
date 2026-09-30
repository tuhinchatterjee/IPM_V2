"""
RunPod suite report: factual comparative metrics, raw evidence preserved.

    python scripts/model_lab/suite_report.py [--runtime-dir DIR]

Reads the suite config, the runner checkpoint, the pin roster and the saved
evaluations; calls no model. Works for a partial or blocked suite: every
model and every (lane, question) cell appears, with NOT_RUN / SKIPPED and
the reason where it did not run. Writes report.json, cells.csv and
report.html under <runtime>/benchmark/<suite_id>/report/.

No overall winner is declared. Per cell it gives the full answer, S1-S4,
independent correctness (oracle checks), saved-Opus agreement where it
exists (Q01), the comparison id and export pack carrying the Full Model I/O
Trace, tables and charts, and for ASSISTED_V1 the exact packet hash plus the
stage-by-stage change against the same model's baseline.
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFAULT_SUITE = ROOT / "profiles" / "_runpod_suite.json"
DEFAULT_RUNTIME = ROOT / "artifacts" / "model_comparison" / "runtime"
RANK = {"FAIL": 0, "PARTIAL": 1, "PASS": 2}
STAGES = ("S1", "S2", "S3", "S4")


def _model_row(m: dict, profiles: dict, roster: dict, cp: dict) -> dict:
    pid = m["profile_id"]
    p = (profiles.get(pid).raw if pid in profiles else {})
    art, rp = p.get("artifact") or {}, p.get("runpod") or {}
    pin = roster.get(pid) or {}
    run = (cp.get("models") or {}).get(pid) or {}
    return {
        "MODEL": m["model"], "MODEL_VARIANT": pid,
        "PARENT": p.get("parent_profile_id"),
        "PARAMETERS": art.get("parameters") or p.get("parameters_total"),
        "QUANTIZATION": art.get("quantization") or "none (native)",
        "EXACT_REVISION": art.get("revision") or "UNPINNED",
        "REPOSITORY": art.get("repository"),
        "LICENSE_STATUS": art.get("license_status") or "UNDETERMINED",
        "LICENSE": art.get("license"),
        "RUNTIME": rp.get("runtime") or rp.get("server") or p.get("route"),
        "CONTEXT": p.get("context_tokens"),
        "VRAM_PEAK_MIB": run.get("vram_peak_mib") or
        pin.get("vram_after_load_mib"),
        "A40_FIT": (rp.get("fit") or {}).get("summary") or
        rp.get("resource_status"),
        "PIN_STATUS": art.get("pin_status"),
        "PROBE_STATUS": pin.get("probe_status"),
        "RUN_STATUS": run.get("status") or "NOT_RUN",
        "RUN_REASON": run.get("reason") or "",
    }


def _cell(ev: dict | None, child_pid: str) -> dict[str, Any]:
    if not ev:
        return {}
    k = next((c for c in ev.get("children") or []
              if c["profile_id"] == child_pid), None)
    if not k:
        return {}
    checks = {c["check_id"]: c for c in k.get("checks") or []}
    oracle = {cid: c["outcome"] for cid, c in checks.items()
              if cid.startswith(("ORACLE-", "S1S2-POP", "S2-RESULT",
                                 "S4-CHART", "S4-ORACLE-FACTS",
                                 "S4-LARGEST"))}
    correct = checks.get("S2-RESULT", {}).get("outcome") or \
        checks.get("S1S2-POP", {}).get("outcome") or "NEEDS_REVIEW"
    ans = k.get("answer") or {}
    ref = k.get("reference_match") or {}
    return {
        "execution": k.get("execution_state"),
        "answer": ans.get("narrative"),
        "tables": [t.get("title") for t in ans.get("tables") or []],
        "charts": [c.get("title") or c.get("kind")
                   for c in ans.get("charts") or []],
        "stages": {s: (k.get("stages") or {}).get(s, {}).get("status")
                   for s in STAGES},
        "correctness": correct, "oracle_checks": oracle,
        "claims": {c["claim_id"]: [c["verification_status"],
                                   c.get("oracle_consistency")]
                   for c in k.get("claims") or []},
        "opus_agreement": ({s: v.get("display") for s, v in ref.items()}
                           if ref else None),
        "lane": k.get("lane"),
    }


def _delta(base: dict, assist: dict) -> dict[str, str]:
    out = {}
    for s in STAGES + ("correctness",):
        a = (base.get("stages") or {}).get(s) if s != "correctness" \
            else base.get("correctness")
        b = (assist.get("stages") or {}).get(s) if s != "correctness" \
            else assist.get("correctness")
        if a in RANK and b in RANK:
            out[s] = ("IMPROVED" if RANK[b] > RANK[a] else "REGRESSED"
                      if RANK[b] < RANK[a] else "SAME")
        else:
            out[s] = "NOT_COMPARABLE" if (a or b) else "NOT_RUN"
    return out


def build(runtime: Path, suite: dict) -> dict[str, Any]:
    from backend.model_lab import registry
    from backend.model_lab.store import LabStore

    sys.path.insert(0, str(ROOT / "scripts" / "model_lab"))
    import benchmark_suite as bs

    profiles = registry.load_profiles()
    cp = bs.load_checkpoint(runtime, suite)
    roster_path = runtime / "pins" / "ROSTER.json"
    roster = ({r["profile_id"]: r for r in
               json.loads(roster_path.read_text())["roster"]}
              if roster_path.exists() else {})
    store = LabStore(runtime)
    models = [_model_row(m, profiles, roster, cp) for m in suite["models"]]
    cells = []
    for m in suite["models"]:
        pid = m["profile_id"]
        per_q: dict[str, dict] = {}
        for q in suite["questions"]:
            for lane in bs.LANE_ORDER:
                c = cp["cells"].get(bs._key(pid, lane, q["question_id"])) \
                    or {}
                ev = None
                if c.get("comparison_id"):
                    row = store._q("SELECT owner_scope FROM comparisons "
                                   "WHERE comparison_id=?",
                                   (c["comparison_id"],))
                    if row:
                        cur = store.current_evaluation(
                            c["comparison_id"], row[0]["owner_scope"])
                        ev = cur["body"] if cur else None
                body = _cell(ev, pid)
                spec_packet = None
                if c.get("comparison_id") and lane == "ASSISTED_V1":
                    srow = store._q("SELECT spec_json FROM comparisons WHERE "
                                    "comparison_id=?", (c["comparison_id"],))
                    if srow:
                        pk = json.loads(srow[0]["spec_json"]).get(
                            "assistance_packet") or {}
                        spec_packet = {"sha256": pk.get("sha256"),
                                       "bytes": pk.get("bytes"),
                                       "packet": pk.get("packet")}
                cell = {"profile_id": pid, "model": m["model"],
                        "lane": lane, "question_id": q["question_id"],
                        "state": c.get("state") or (
                            "SKIPPED" if (cp.get("models") or {}).get(
                                pid, {}).get("status") in ("SKIPPED",
                                                           "PROBE_FAILED")
                            else "NOT_RUN"),
                        "reason": c.get("error") or (cp.get("models") or {})
                        .get(pid, {}).get("reason") or "",
                        "comparison_id": c.get("comparison_id"),
                        "trace": (f"/api/v1/model-lab/comparisons/"
                                  f"{c['comparison_id']}/model-io"
                                  if c.get("comparison_id") else None),
                        "export_pack": c.get("export"),
                        "assistance_packet": spec_packet, **body}
                per_q.setdefault(q["question_id"], {})[lane] = cell
                cells.append(cell)
        for pair in per_q.values():
            b, a = pair.get("FROZEN_BASELINE"), pair.get("ASSISTED_V1")
            if a is not None and b is not None:
                a["vs_baseline"] = _delta(b, a)
    return {"suite_id": suite["suite_id"], "models": models,
            "cells": cells,
            "policy": "factual comparative metrics only; no overall winner; "
                      "raw evidence (answers, traces, packs) preserved; "
                      "uncertainty and NEEDS_REVIEW items kept visible"}


def _html(rep: dict) -> str:
    e = html.escape
    mh = list(rep["models"][0].keys()) if rep["models"] else []
    rows = "".join("<tr>" + "".join(f"<td>{e(str(m.get(k) or ''))}</td>"
                                    for k in mh) + "</tr>"
                   for m in rep["models"])
    ch = ["model", "lane", "question_id", "state", "correctness", "stages",
          "opus_agreement", "vs_baseline", "comparison_id", "reason"]
    crow = "".join("<tr>" + "".join(
        f"<td>{e(json.dumps(c.get(k)) if isinstance(c.get(k), dict) else str(c.get(k) or ''))}</td>"
        for k in ch) + "</tr>" for c in rep["cells"])
    return (f"<!doctype html><meta charset=utf-8><title>{e(rep['suite_id'])}"
            f"</title><style>body{{font:13px system-ui;margin:20px}}td,th"
            f"{{border:1px solid #aaa;padding:3px 5px;vertical-align:top}}"
            f"table{{border-collapse:collapse}}</style>"
            f"<h1>{e(rep['suite_id'])}</h1><p>{e(rep['policy'])}</p>"
            f"<h2>Models</h2><table><tr>"
            + "".join(f"<th>{e(h)}</th>" for h in mh) + f"</tr>{rows}</table>"
            "<h2>Cells</h2><table><tr>"
            + "".join(f"<th>{e(h)}</th>" for h in ch) + f"</tr>{crow}</table>"
            "<p>Full answers, claims, packets and trace links are in "
            "report.json; each comparison's export pack carries its Model "
            "I/O Trace.</p>")


def write(runtime: Path, suite: dict) -> Path:
    rep = build(runtime, suite)
    out = runtime / "benchmark" / suite["suite_id"] / "report"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=1, default=str))
    buf = io.StringIO()
    cols = ["model", "profile_id", "lane", "question_id", "state",
            "correctness", "comparison_id", "reason"]
    w = csv.DictWriter(buf, fieldnames=cols + [f"stage_{s}" for s in STAGES]
                       + ["vs_baseline"], extrasaction="ignore")
    w.writeheader()
    for c in rep["cells"]:
        w.writerow(c | {f"stage_{s}": (c.get("stages") or {}).get(s)
                        for s in STAGES} | {
            "vs_baseline": json.dumps(c.get("vs_baseline"))
            if c.get("vs_baseline") else ""})
    (out / "cells.csv").write_text(buf.getvalue())
    (out / "report.html").write_text(_html(rep))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--suite", default=str(DEFAULT_SUITE))
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    args = ap.parse_args(argv)
    os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")
    suite = json.loads(Path(args.suite).read_text())
    out = write(Path(args.runtime_dir).expanduser().resolve(), suite)
    print(f"report written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

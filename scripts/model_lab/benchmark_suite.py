"""
RunPod benchmark runner (suite v2): a state machine over model x lane x
question. It plans by default; it runs only when explicitly confirmed.

    python scripts/model_lab/benchmark_suite.py                 # plan
    python scripts/model_lab/benchmark_suite.py --run --confirm-model-calls \\
        --serve                                  # every qualified model
    python scripts/model_lab/benchmark_suite.py --run --confirm-model-calls \\
        --model qwen3.5-4b-runpod                # already served by hand

Gates per model (the planner shows each reason): pinned exact revision,
licence clear or approved, fits the A40, probe READY_E2E. A blocked model is
SKIPPED with its reason and the suite continues; nothing is substituted.

Per qualified model, in order: (re)probe when --serve starts it ->
FROZEN_BASELINE Q01 -> FROZEN_BASELINE Q02..Q15 -> ASSISTED_V1 Q01..Q15.
A checkpoint is written after every question; a re-run resumes and skips
cells already DONE. Every result is exported with its Full Model I/O Trace.
The runner refuses to start with tracing off.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFAULT_SUITE = ROOT / "profiles" / "_runpod_suite.json"
DEFAULT_RUNTIME = ROOT / "artifacts" / "model_comparison" / "runtime"
LANE_ORDER = ("FROZEN_BASELINE", "ASSISTED_V1")


def _key(pid: str, lane: str, qid: str) -> str:
    return f"{pid}|{lane}|{qid}"


def checkpoint_path(runtime: Path, suite: dict) -> Path:
    return runtime / "benchmark" / suite["suite_id"] / "checkpoint.json"


def load_checkpoint(runtime: Path, suite: dict) -> dict[str, Any]:
    p = checkpoint_path(runtime, suite)
    if p.exists():
        return json.loads(p.read_text())
    return {"suite_id": suite["suite_id"], "cells": {}, "models": {}}


def save_checkpoint(runtime: Path, suite: dict, cp: dict) -> None:
    p = checkpoint_path(runtime, suite)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cp, indent=1, default=str))
    tmp.replace(p)


def plan(suite: dict, *, runtime_dir: Path, lanes: list[str],
         models: list[str] | None, questions: list[str] | None,
         profiles: dict | None = None) -> dict[str, Any]:
    from backend.model_lab import registry

    profiles = profiles if profiles is not None else \
        registry.load_profiles()
    probes_path = runtime_dir / "probes.json"
    probes = (json.loads(probes_path.read_text())
              if probes_path.exists() else {})
    approvals = registry.load_approvals(runtime_dir)
    cp = load_checkpoint(runtime_dir, suite)
    qs = [q for q in suite["questions"]
          if not questions or q["question_id"] in questions]
    rows, cells = [], []
    for m in suite["models"]:
        pid = m["profile_id"]
        if models and pid not in models and m["model"] not in models:
            continue
        prof = profiles.get(pid)
        if prof is None:
            ready = {"status": "NOT_REGISTERED",
                     "reasons": [f"{pid} is not in the registry"]}
        else:
            r = registry.readiness(prof, approvals=approvals, probes=probes)
            ready = {"status": r.status, "reasons": r.reasons}
        for lane in lanes:
            lane_def = suite["lanes"][lane]
            if lane_def["status"] == "BLOCKED":
                why, ok = lane_def.get("reason", "lane blocked"), False
            elif ready["status"] not in registry.RUNNABLE:
                why = "; ".join(ready["reasons"]) or ready["status"]
                ok = False
            else:
                why, ok = "", True
            rows.append({"model": m["model"], "profile_id": pid,
                         "lane": lane, "readiness": ready["status"],
                         "runnable": ok, "reason": why})
            for q in qs:
                k = _key(pid, lane, q["question_id"])
                cells.append({"key": k, "profile_id": pid, "lane": lane,
                              "question_id": q["question_id"],
                              "runnable": ok,
                              "state": (cp["cells"].get(k) or {}).get(
                                  "state", "PENDING" if ok else
                                  "SKIPPED")})
    return {"suite_id": suite["suite_id"], "rows": rows, "cells": cells,
            "questions": qs,
            "runnable_cells": sum(1 for c in cells if c["runnable"]),
            "done_cells": sum(1 for c in cells if c["state"] == "DONE"),
            "total_cells": len(cells)}


class VramSampler:
    """Peak GPU memory while a model is being benchmarked (nvidia-smi)."""

    def __init__(self, interval: float = 2.0) -> None:
        self.peak: int | None = None
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, args=(interval,),
                                   daemon=True)

    def _loop(self, interval: float) -> None:
        import subprocess
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used",
                     "--format=csv,noheader,nounits"], capture_output=True,
                    text=True, timeout=10).stdout.split()
                v = int(out[0]) if out else None
                if v is not None:
                    self.peak = max(self.peak or 0, v)
            except Exception:  # noqa: BLE001
                return
            self._stop.wait(interval)

    def __enter__(self) -> VramSampler:
        self._t.start()
        return self

    def __exit__(self, *a: Any) -> None:
        self._stop.set()


def _sequence(qs: list[dict]) -> list[tuple[str, dict]]:
    """Baseline Q01 first, then the rest of the baseline, then assisted."""
    ids = [q["question_id"] for q in qs]
    first = [q for q in qs if q["question_id"] == "Q01"]
    rest = [q for q in qs if q["question_id"] != "Q01"]
    return ([("FROZEN_BASELINE", q) for q in first + rest] +
            [("ASSISTED_V1", q) for q in sorted(
                qs, key=lambda q: ids.index(q["question_id"]))])


def run_model(svc, suite: dict, pid: str, lanes: list[str], qs: list[dict],
              cp: dict, runtime: Path) -> None:
    ref = suite["reference"]["saved_opus_comparison"]
    has_ref = svc.coord.store.get_comparison(ref, svc.cfg.tenant_id)
    for lane, q in _sequence(qs):
        if lane not in lanes:
            continue
        k = _key(pid, lane, q["question_id"])
        if (cp["cells"].get(k) or {}).get("state") == "DONE":
            continue
        req = {"question": q["question"], "profile_ids": [pid],
               "comparator_id": "", "lane": lane,
               "benchmark_question_id": q["question_id"],
               "deployment": suite["deployment"],
               "group_spend_cap_usd": 0.0, "group_wall_clock_s": 1800,
               "label": f"{suite['suite_id']} {pid} {lane} "
                        f"{q['question_id']}"}
        if has_ref and q["question_id"] in suite["reference"]["applies_to"]:
            req["reference_comparison_id"] = ref
        started = time.time()
        try:
            st = svc.coord.create(req, idempotency_key=f"{suite['suite_id']}"
                                  f":{k}:{int(started)}")
            st = svc.coord.wait(st["comparison_id"], timeout=3900)
            exp = svc.export(st["comparison_id"])
            cell = {"state": "DONE", "comparison_id": st["comparison_id"],
                    "group_state": st["state"],
                    "export": exp.get("path"), "export_sha256":
                    exp.get("sha256")}
        except Exception as exc:  # noqa: BLE001 - record, continue
            cell = {"state": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}"[:400]}
        cell |= {"started_at": started, "finished_at": time.time()}
        cp["cells"][k] = cell
        save_checkpoint(runtime, suite, cp)
        print(f"  {k:48} {cell['state']:6} {cell.get('comparison_id', '')}"
              f" {cell.get('group_state', cell.get('error', ''))}")


def _pin_module():
    import importlib.util
    path = ROOT / "scripts" / "model_lab" / "runpod" / \
        "pin_and_probe_models.py"
    spec = importlib.util.spec_from_file_location("pin_and_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--suite", default=str(DEFAULT_SUITE))
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    ap.add_argument("--lane", action="append", choices=list(LANE_ORDER))
    ap.add_argument("--model", action="append")
    ap.add_argument("--question", action="append")
    ap.add_argument("--run", action="store_true",
                    help="actually run (calls the served model)")
    ap.add_argument("--confirm-model-calls", action="store_true")
    ap.add_argument("--serve", action="store_true",
                    help="start/stop vLLM per model and re-probe it first")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")

    suite = json.loads(Path(args.suite).read_text())
    runtime = Path(args.runtime_dir).expanduser().resolve()
    lanes = args.lane or list(LANE_ORDER)
    p = plan(suite, runtime_dir=runtime, lanes=lanes, models=args.model,
             questions=args.question)
    if args.json:
        print(json.dumps(p, indent=1))
    else:
        print(f"suite {p['suite_id']}: {len(p['questions'])} questions, "
              f"{p['runnable_cells']}/{p['total_cells']} cells runnable, "
              f"{p['done_cells']} done")
        for r in p["rows"]:
            mark = "RUN " if r["runnable"] else "SKIP"
            print(f"  {mark} {r['lane']:16} {r['profile_id']:30} "
                  f"{r['readiness']:18} {r['reason'][:100]}")
    if not args.run:
        print("dry run: no model was called")
        return 0

    from backend.model_lab import io_trace, registry
    if not args.confirm_model_calls:
        print("refusing: --run needs --confirm-model-calls (this calls the "
              "served model)")
        return 2
    if not io_trace.enabled():
        print(f"refusing: {io_trace.ENV_FLAG} is off; every benchmark "
              f"result must carry the full Model I/O Trace")
        return 2
    for lane in lanes:
        if suite["lanes"][lane]["status"] == "BLOCKED":
            print(f"refusing: {lane} is BLOCKED: "
                  + suite["lanes"][lane].get("reason", ""))
            return 2
    order = [m["profile_id"] for m in suite["models"]]
    runnable = [pid for pid in order if any(
        r["profile_id"] == pid and r["runnable"] for r in p["rows"])]
    profiles = registry.load_profiles()
    if not args.serve and len([x for x in runnable
                               if profiles[x].route != "fixture"]) > 1:
        print(f"refusing: without --serve, run ONE served model at a time "
              f"(--model); ready now: {runnable}")
        return 2
    if not runnable:
        print("nothing runnable: every model is blocked (see reasons above)")
        return 0

    from backend.model_lab.service import LabService, default_config

    svc = LabService(default_config(runtime))
    cp = load_checkpoint(runtime, suite)
    for m in suite["models"]:
        pid = m["profile_id"]
        if pid not in runnable:
            reason = next((r["reason"] for r in p["rows"]
                           if r["profile_id"] == pid), "")
            cp["models"].setdefault(pid, {}).update(
                {"status": "SKIPPED", "reason": reason})
            save_checkpoint(runtime, suite, cp)
            continue
        print(f"== {pid}")
        server = None
        if args.serve and profiles[pid].route != "fixture":
            pp = _pin_module()
            res = pp.serve_and_probe(pid, runtime, keep=True)
            if res["probe_status"] != "READY_E2E":
                cp["models"][pid] = {"status": "PROBE_FAILED",
                                     "reason": res.get("failure")}
                save_checkpoint(runtime, suite, cp)
                print(f"  PROBE_FAILED: {res.get('failure')}")
                continue
            server = res.pop("_server")
        try:
            with VramSampler() as vram:
                run_model(svc, suite, pid, lanes, p["questions"], cp,
                          runtime)
            cp["models"][pid] = {"status": "COMPLETED",
                                 "vram_peak_mib": vram.peak}
            save_checkpoint(runtime, suite, cp)
        finally:
            if server is not None:
                _pin_module().stop_server(server)
    return 0


if __name__ == "__main__":
    sys.exit(main())

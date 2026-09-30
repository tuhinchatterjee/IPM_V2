"""
RunPod benchmark runner: plan by default, run only when explicitly confirmed.

    python scripts/model_lab/benchmark_suite.py                 # dry run plan
    python scripts/model_lab/benchmark_suite.py --model qwen3.5-4b-runpod \\
        --lane FROZEN_BASELINE --run --confirm-model-calls

The dry run makes no model call and needs no GPU. It resolves every
(model x lane x question) cell against the registry's readiness and says,
cell by cell, whether it would run and why not.

A real run (on the pod, after `serve.sh <profile>` and a passing probe):

* runs ONE model at a time (one resident model on the A40), sequentially,
  one comparison per question, through the ordinary lab coordinator and the
  unchanged frozen engine;
* refuses unless MODEL_LAB_FULL_IO_TRACE is on -- every result carries the
  full Model I/O Trace;
* refuses the ASSISTED_V1 lane while it is not defined (see the suite file);
* never substitutes a model: a profile that is not READY_E2E is skipped with
  its reason, never replaced.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFAULT_SUITE = ROOT / "profiles" / "_runpod_suite.json"
DEFAULT_RUNTIME = ROOT / "artifacts" / "model_comparison" / "runtime"


def plan(suite: dict, *, runtime_dir: Path, lanes: list[str],
         models: list[str] | None, questions: list[str] | None) -> dict:
    from backend.model_lab import registry

    profiles = registry.load_profiles()
    probes_path = runtime_dir / "probes.json"
    probes = (json.loads(probes_path.read_text())
              if probes_path.exists() else {})
    cells, rows = [], []
    qs = [q for q in suite["questions"]
          if not questions or q["question_id"] in questions]
    for m in suite["models"]:
        pid = m["profile_id"]
        if models and pid not in models and m["model"] not in models:
            continue
        prof = profiles.get(pid)
        if prof is None:
            ready = {"status": "NOT_REGISTERED",
                     "reasons": [f"{pid} is not in the registry"]}
        else:
            r = registry.readiness(prof, approvals={}, probes=probes)
            ready = {"status": r.status, "reasons": r.reasons}
        for lane in lanes:
            lane_def = suite["lanes"][lane]
            if lane_def["status"] == "BLOCKED":
                why, runnable = lane_def["reason"], False
            elif ready["status"] not in registry.RUNNABLE:
                why = "; ".join(ready["reasons"]) or ready["status"]
                runnable = False
            else:
                why, runnable = "", True
            rows.append({"model": m["model"], "profile_id": pid,
                         "lane": lane, "readiness": ready["status"],
                         "runnable": runnable, "reason": why})
            for q in qs:
                cells.append({"profile_id": pid, "lane": lane,
                              "question_id": q["question_id"],
                              "runnable": runnable})
    return {"suite_id": suite["suite_id"], "rows": rows, "cells": cells,
            "questions": qs,
            "runnable_cells": sum(1 for c in cells if c["runnable"]),
            "total_cells": len(cells)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--suite", default=str(DEFAULT_SUITE))
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    ap.add_argument("--lane", action="append",
                    choices=["FROZEN_BASELINE", "ASSISTED_V1"])
    ap.add_argument("--model", action="append")
    ap.add_argument("--question", action="append")
    ap.add_argument("--run", action="store_true",
                    help="actually run (calls the served model)")
    ap.add_argument("--confirm-model-calls", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")

    suite = json.loads(Path(args.suite).read_text())
    runtime = Path(args.runtime_dir).expanduser().resolve()
    lanes = args.lane or list(suite["lanes"])
    p = plan(suite, runtime_dir=runtime, lanes=lanes, models=args.model,
             questions=args.question)
    if args.json:
        print(json.dumps(p, indent=1))
    else:
        print(f"suite {p['suite_id']}: {len(p['questions'])} questions, "
              f"{p['runnable_cells']}/{p['total_cells']} cells runnable now")
        for r in p["rows"]:
            mark = "RUN " if r["runnable"] else "SKIP"
            print(f"  {mark} {r['lane']:16} {r['profile_id']:28} "
                  f"{r['readiness']:18} {r['reason'][:110]}")
    if not args.run:
        print("dry run: no model was called")
        return 0

    from backend.model_lab import io_trace
    if not args.confirm_model_calls:
        print("refusing: --run needs --confirm-model-calls (this calls the "
              "served model)")
        return 2
    if not io_trace.enabled():
        print(f"refusing: {io_trace.ENV_FLAG} is off; every benchmark "
              f"result must carry the full Model I/O Trace")
        return 2
    if "ASSISTED_V1" in lanes and suite["lanes"]["ASSISTED_V1"][
            "status"] == "BLOCKED":
        print("refusing: ASSISTED_V1 is BLOCKED: "
              + suite["lanes"]["ASSISTED_V1"]["reason"])
        return 2
    runnable = sorted({r["profile_id"] for r in p["rows"] if r["runnable"]})
    if len(runnable) != 1:
        print(f"refusing: run exactly ONE ready model at a time (one "
              f"resident model on the A40); ready now: {runnable}")
        return 2

    from backend.model_lab.service import LabService, default_config

    svc = LabService(default_config(runtime))
    ref = suite["reference"]["saved_opus_comparison"]
    has_ref = svc.coord.store.get_comparison(ref, svc.cfg.tenant_id)
    out_dir = runtime / "benchmark" / suite["suite_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {"suite_id": suite["suite_id"], "profile_id": runnable[0],
             "lane": "FROZEN_BASELINE", "started_at": time.time(),
             "results": []}
    for q in p["questions"]:
        req = {"question": q["question"], "profile_ids": runnable,
               "comparator_id": "", "task_id": q["oracle_task_id"] or "",
               "deployment": suite["deployment"],
               "group_spend_cap_usd": 0.0, "group_wall_clock_s": 1800,
               "label": f"{suite['suite_id']} {q['question_id']} "
                        f"FROZEN_BASELINE"}
        if has_ref and q["question_id"] in suite["reference"]["applies_to"]:
            req["reference_comparison_id"] = ref
        st = svc.coord.create(req, idempotency_key=(
            f"{suite['suite_id']}:{runnable[0]}:{q['question_id']}:"
            f"{index['started_at']}"))
        st = svc.coord.wait(st["comparison_id"], timeout=3600)
        index["results"].append({"question_id": q["question_id"],
                                 "comparison_id": st["comparison_id"],
                                 "state": st["state"]})
        print(f"  {q['question_id']} -> {st['comparison_id']} {st['state']}")
        (out_dir / f"{runnable[0]}_{int(index['started_at'])}.json"
         ).write_text(json.dumps(index, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

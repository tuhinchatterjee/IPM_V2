"""
Entry point for ONE long-run diagnostic child, in its own interpreter.

    python -m backend.model_lab.diagnostic_child <job.json>

Started only by `Coordinator._run_child_isolated`. It arms the diagnostic
override for this process, applies the profile's `diagnostic_limits` to the
frozen limit values in memory, runs the child through the lab's ordinary
`_run_child` path (the same adapter, observer, Runtime and frozen
`Worker.execute` as every other child), restores the values and exits. No
frozen file is read differently or written, and no other child ever runs in
this process.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    job = json.loads(Path(argv[0]).read_text())
    os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")

    from backend.model_lab import diagnostic_limits as dl
    from backend.model_lab import registry
    from backend.model_lab.coordinator import Coordinator, LabConfig

    dl.arm()
    c = job["cfg"]
    cfg = LabConfig(runtime_dir=Path(c["runtime_dir"]),
                    tenant_id=c["tenant_id"],
                    remote_parallel_workers=int(c["remote_parallel_workers"]),
                    manifest_path=Path(c["manifest_path"]))
    raw = job["profile"]
    prof = registry._validate(raw, Path(f"{raw['profile_id']}.json"))
    # recover=False: this process must never touch another child's state.
    coord = Coordinator(cfg, profiles={prof.profile_id: prof}, recover=False)
    cid, child_id = job["comparison_id"], job["child_run_id"]
    child = coord.store.child(child_id)
    if child is None:
        return 3
    spec = coord._spec(cid)
    rc = 0
    with dl.applied(raw["diagnostic_limits"]) as info:
        coord.emit(cid, "diagnostic.limits.applied", child_run_id=child_id,
                   source_site="diagnostic_child",
                   payload=info | {"label": dl.LABEL,
                                   "parent_pid": os.getppid()})
        try:
            # Cancellation reaches the frozen worker through the run store
            # (the parent forwards it), so a local event is never set here.
            coord._run_child(cid, spec, child, turn=job.get("turn"),
                             cancel=threading.Event())
        except Exception:  # noqa: BLE001 - reported, then the parent settles
            rc = 1
            coord.emit(cid, "diagnostic.child.error", child_run_id=child_id,
                       status="error", source_site="diagnostic_child",
                       payload={"traceback": traceback.format_exc()[-2000:]})
    coord.emit(cid, "diagnostic.limits.restored", child_run_id=child_id,
               source_site="diagnostic_child",
               payload={"pid": os.getpid(),
                        "policy_after_restore": dl.frozen_policy()})
    return rc


if __name__ == "__main__":
    sys.exit(main())

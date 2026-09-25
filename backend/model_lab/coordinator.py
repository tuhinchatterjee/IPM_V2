"""
Experiment coordinator: schedules independent child investigations.

It manages the QUEUE, not the analysis. Each child is one call to the frozen
`Worker.execute` with that child's own `Runtime` (see `child_runtime`). The
coordinator never authors a plan, changes retry policy, or adds an answer
loop. It does:

* freeze an immutable ComparisonSpec (hashed) before any dispatch;
* preflight every selected profile, keep blocked ones visible, run only the
  eligible and authorised;
* order children deterministically (seeded when repeated);
* run them on lanes: `sequential` (16 GB Mac default: one resident local
  model, Opus not overlapped with local children), or `parallel` (approved
  remote workers, labelled as a different deployment class);
* enforce a group wall-clock and spend cap at child boundaries;
* cancel, pause for clarification, resume only the intended children;
* on restart, mark in-flight children INTERRUPTED and never re-dispatch.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.model_lab import EVALUATOR_VERSION, FROZEN_COMMIT, LAB_VERSION, registry
from backend.model_lab.store import LabStore

# Group states
G_DRAFT, G_PREFLIGHT, G_RUNNING = "DRAFT", "PREFLIGHT", "RUNNING"
G_COMPLETE, G_PARTIAL = "COMPLETE", "PARTIAL"
G_CANCELLED, G_BLOCKED = "CANCELLED", "BLOCKED"
G_TERMINAL = (G_COMPLETE, G_PARTIAL, G_CANCELLED, G_BLOCKED)
# Child states
C_QUEUED, C_PREPARING, C_RUNNING = "QUEUED", "PREPARING", "RUNNING"
C_WAITING = "WAITING_USER"
C_COMPLETED, C_FAILED, C_CANCELLED = "COMPLETED", "FAILED", "CANCELLED"
C_BLOCKED, C_INTERRUPTED = "BLOCKED", "INTERRUPTED"
C_TERMINAL = (C_COMPLETED, C_FAILED, C_CANCELLED, C_BLOCKED, C_INTERRUPTED)
C_SETTLED = C_TERMINAL + (C_WAITING,)

#: frozen terminal state -> child execution state. Quality is a SEPARATE
#: dimension (evaluation); a PARTIAL answer is a completed execution.
_FROZEN_TO_CHILD = {
    "COMPLETED": C_COMPLETED, "PARTIAL": C_COMPLETED,
    "REFERRED": C_COMPLETED, "UNSUPPORTED": C_COMPLETED,
    "WAITING_FOR_USER": C_WAITING, "FAILED": C_FAILED,
    "EXPIRED": C_FAILED, "CANCELLED": C_CANCELLED,
    "INTERRUPTED": C_INTERRUPTED,
}

MODES = ("E2E_BASELINE", "OBSERVED_STAGE_EVIDENCE",
         "CONTROLLED_CHECKPOINT_REPLAY", "PARAMETER/CONTEXT_ABLATION",
         "TRAINING_READINESS")
DEPLOYMENTS = ("mac_sequential", "remote_parallel", "fixture",
               "same_model_hardware_diagnostic")
#: The frozen per-run ceiling a child can spend at most (analytical deep).
#: Reserved per paid child before dispatch; reconciled to actual after.
PER_CHILD_RESERVE_USD = 3.00


def _h(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str)
                          .encode()).hexdigest()


class SpecError(ValueError):
    """The request cannot become a comparison. Nothing was dispatched."""


@dataclass
class LabConfig:
    runtime_dir: Path
    tenant_id: str = "demo-tenant"
    remote_parallel_workers: int = 1
    manifest_path: Path = Path(__file__).resolve().parents[2] / "docs" / \
        "model_comparison" / "PROTECTED_MANIFEST.json"


class Coordinator:
    def __init__(self, cfg: LabConfig, *, store: LabStore | None = None,
                 profiles: dict[str, registry.Profile] | None = None,
                 provider_factory=None, env: dict[str, str] | None = None,
                 on_settled=None, recover: bool = True) -> None:
        from backend.cockpit_v4.run_store import RunStore

        self.cfg = cfg
        self.store = store or LabStore(cfg.runtime_dir)
        self.runs = RunStore(self.store.runs_db_path)
        self.profiles = profiles if profiles is not None else \
            registry.load_profiles()
        self.env = os.environ if env is None else env
        self.provider_factory = provider_factory
        self.on_settled = on_settled
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self.worker_id = f"labw-{uuid.uuid4().hex[:8]}"
        # One resident local model at a time, and no Opus child overlapping a
        # local one in a timing comparison: a single process-wide lane lock.
        self._sequential_lane = threading.Lock()
        if recover:
            self.recover_interrupted()

    def data_tenant(self, domain: str) -> str:
        """The tenant the release's rows belong to. Distinct from the owner
        scope (who may SEE a comparison): children read data as the
        release's own tenant, exactly as the frozen demo principal does."""
        from backend.cockpit_v4 import analytical_runtime as arun

        tenants = arun.for_domain(domain).release_summary().get("tenants")
        return str(tenants[0]) if tenants else self.cfg.tenant_id

    # ---- events ----------------------------------------------------------
    def emit(self, comparison_id: str, event_type: str, *,
             child_run_id: str | None = None, status: str = "ok",
             stage_tags: list[str] | None = None,
             attribution_basis: str = "", source_site: str = "coordinator",
             payload: Any = None, metric_values: dict | None = None,
             units: dict | None = None, measurement_method: str = "",
             missing_reason: str = "", call_id: str | None = None,
             run_id: str | None = None, sensitivity: str = "internal",
             mono: float | None = None, wall: float | None = None) -> None:
        payload_ref = payload_hash = None
        if payload is not None:
            blob = json.dumps(payload, default=str, sort_keys=True)
            payload_ref = self.store.put_blob(blob)
            payload_hash = payload_ref
        self.store.append_event({
            "event_id": f"ev-{uuid.uuid4().hex}",
            "event_schema_version": 1,
            "comparison_id": comparison_id, "child_run_id": child_run_id,
            "owner_scope": self.cfg.tenant_id,
            "attempt_id": None, "turn_id": run_id, "call_id": call_id,
            "stage_tags": stage_tags or [],
            "attribution_basis": attribution_basis,
            "source_site": source_site, "event_type": event_type,
            "monotonic_time": time.monotonic() if mono is None else mono,
            "wall_time": time.time() if wall is None else wall,
            "host_id": os.uname().nodename if hasattr(os, "uname") else "",
            "status": status, "payload_ref": payload_ref,
            "payload_hash": payload_hash, "sensitivity_class": sensitivity,
            "metric_values": metric_values, "units": units,
            "measurement_method": measurement_method,
            "missing_reason": missing_reason})

    # ---- readiness / preflight ---------------------------------------------
    def probes(self) -> dict[str, Any]:
        p = self.cfg.runtime_dir / "probes.json"
        try:
            return json.loads(p.read_text()) if p.exists() else {}
        except ValueError:
            return {}

    def readiness(self) -> dict[str, dict[str, Any]]:
        approvals = registry.load_approvals(self.cfg.runtime_dir)
        probes = self.probes()
        return {pid: registry.readiness(p, approvals=approvals,
                                        probes=probes, env=self.env).to_dict()
                for pid, p in self.profiles.items()}

    def preflight(self, request: dict[str, Any]) -> dict[str, Any]:
        """No inference, no spend. What is ready, blocked, estimated, unknown."""
        question = str(request.get("question") or "").strip()
        selected = list(dict.fromkeys(request.get("profile_ids") or []))
        comparator = request.get("comparator_id") or ""
        errors: list[str] = []
        if not question:
            errors.append("a question is required")
        if len(question) > 4000:
            errors.append("the question is longer than 4,000 characters")
        if not selected:
            errors.append("select at least one model profile")
        unknown = [p for p in selected if p not in self.profiles]
        if unknown:
            errors.append(f"unknown profile ids: {unknown}")
        mode = request.get("execution_mode") or "E2E_BASELINE"
        if mode != "E2E_BASELINE":
            errors.append(f"{mode} is not available from Compare; controlled "
                          f"diagnostics need a saved Deep diagnostics preset")
        deployment = request.get("deployment") or "mac_sequential"
        if deployment not in DEPLOYMENTS:
            errors.append(f"unknown deployment {deployment}")
        trials = int(request.get("trial_count") or 1)
        if not 1 <= trials <= 5:
            errors.append("trial_count must be 1..5")
        cap = request.get("group_spend_cap_usd")
        cap = float(cap) if cap is not None else 0.0
        approvals = registry.load_approvals(self.cfg.runtime_dir)
        if deployment == "remote_parallel" and not approvals.get(
                "remote_inference"):
            errors.append("Remote Parallel UAT needs the 'remote_inference' "
                          "approval (scripts/model_lab/approve.py); Compare "
                          "never provisions GPUs")
        ready = self.readiness()
        rows = []
        paid_children = 0
        for pid in selected:
            if pid not in self.profiles:
                continue
            prof = self.profiles[pid]
            r = ready[pid]
            eligible = r["status"] in registry.RUNNABLE
            price = self._price_status(prof)
            paid = price["status"] == "PAID"
            if eligible and paid:
                paid_children += trials
            rows.append({
                "profile_id": pid, "display_name": prof.display_name,
                "role": prof.role, "fixture": prof.is_fixture,
                "status": r["status"], "reasons": r["reasons"],
                "recovery": r["recovery"], "eligible": eligible,
                "price": price, "lane": self._lane(prof, deployment),
                "estimated_reserve_usd": (PER_CHILD_RESERVE_USD * trials
                                          if paid and eligible else 0.0)})
        reserve = paid_children * PER_CHILD_RESERVE_USD
        if paid_children and reserve > cap + 1e-9:
            errors.append(f"the eligible paid children need a reserve of "
                          f"${reserve:.2f} (worst case ${PER_CHILD_RESERVE_USD:.2f}"
                          f" each) but the group spend cap is ${cap:.2f}")
        eligible = [r for r in rows if r["eligible"]]
        if selected and not eligible:
            errors.append("none of the selected profiles is ready to run")
        comp_ok = bool(comparator) and any(
            r["profile_id"] == comparator and r["eligible"] for r in rows)
        return {
            "ok": not errors, "errors": errors, "profiles": rows,
            "comparator": {"profile_id": comparator, "ready": comp_ok,
                           "is_opus": self.profiles.get(comparator) is not None
                           and self.profiles[comparator].route == "anthropic",
                           "status": ("READY" if comp_ok else
                                      "OPUS_BASELINE_UNAVAILABLE"
                                      if comparator == "opus-frozen" else
                                      "COMPARATOR_UNAVAILABLE")},
            "estimates": {"paid_children": paid_children,
                          "reserve_usd": reserve, "group_spend_cap_usd": cap,
                          "wall_clock_s": request.get("group_wall_clock_s")},
            "unknown": ["model load time", "per-call latency",
                        "local memory peak"],
            "no_inference_performed": True}

    def _price_status(self, prof: registry.Profile) -> dict[str, Any]:
        if prof.is_fixture:
            return {"status": "NONE", "basis": "fixture: no inference"}
        if prof.route == "anthropic":
            return {"status": "PAID", "basis": "frozen verified price card "
                    f"{prof.raw.get('price_card')}"}
        price = prof.raw.get("price") or {}
        if not price:
            return {"status": "UNKNOWN", "basis": "no price configuration"}
        if prof.raw.get("endpoint", {}).get("class") == "remote_gpu":
            return {"status": "PAID", "basis": "remote GPU time is billed "
                    "outside token prices; allocated separately"}
        return {"status": "LOCAL", "basis": price.get("basis", "")}

    @staticmethod
    def _lane(prof: registry.Profile, deployment: str) -> str:
        if deployment == "remote_parallel" and \
                prof.raw.get("endpoint", {}).get("class") in (
                    "remote_gpu", "external_api"):
            return "parallel"
        return "sequential"

    # ---- create ------------------------------------------------------------
    def create(self, request: dict[str, Any], *, principal_id: str = "u1",
               idempotency_key: str = "", start: bool = True
               ) -> dict[str, Any]:
        pre = self.preflight(request)
        if not pre["ok"]:
            raise SpecError("; ".join(pre["errors"]))
        from backend.model_lab.child_runtime import snapshot_identity

        domain = request.get("domain") or "corporate"
        snap = snapshot_identity(domain)
        manifest = json.loads(self.cfg.manifest_path.read_text())
        trials = int(request.get("trial_count") or 1)
        question = str(request["question"]).strip()
        initial_context = {"question": question, "domain": domain,
                           "mode": request.get("mode") or "standard",
                           "as_of": snap["release_id"], "timezone": "UTC",
                           "history": [], "tenant": self.cfg.tenant_id}
        spec = {
            "schema_version": 1, "created_at": time.time(),
            "owner_scope": self.cfg.tenant_id,
            "frozen_source_id": FROZEN_COMMIT,
            "protected_manifest_hash": manifest["aggregate_sha256"],
            "lab_build_id": LAB_VERSION,
            "task_id": request.get("task_id") or "",
            "question_text": question,
            "initial_context_hash": _h(initial_context),
            "parent_id": request.get("parent_id"),
            "data_snapshot_id": snap["data_snapshot_id"],
            "catalogue_hash": snap["catalogue_hash"],
            "tools_hash": snap["tools_hash"], "policy_hash": snap["policy_hash"],
            "domain": domain, "cohort_ref": request.get("cohort_ref"),
            "period_refs": request.get("period_refs") or [],
            "as_of_context": snap["release_id"], "timezone": "UTC",
            "selected_profile_ids": [r["profile_id"] for r in
                                     pre["profiles"]],
            "comparator_id": request.get("comparator_id") or "",
            "execution_mode": request.get("execution_mode") or
            "E2E_BASELINE",
            "analysis_mode": request.get("mode") or "standard",
            "trial_count": trials,
            "run_order_seed": request.get("run_order_seed"),
            "cache_policy": "frozen engine default (no prompt caching)",
            "resource_lane": request.get("deployment") or "mac_sequential",
            "approvals_ref": sorted(registry.load_approvals(
                self.cfg.runtime_dir)),
            "per_run_limits_ref": "backend.cockpit_v4.config "
                                  "STANDARD/DEEP/ANALYTICAL limits (frozen)",
            "group_spend_cap_usd": float(request.get("group_spend_cap_usd")
                                         or 0.0),
            "group_wall_clock_s": float(request.get("group_wall_clock_s")
                                        or 1800),
            "evaluator_version": EVALUATOR_VERSION,
            "oracle_ref": request.get("oracle_ref"),
            "evaluation_split": request.get("evaluation_split") or
            "diagnostic",
            "export_policy": "redacted-default",
            "preset_id": request.get("preset_id"),
            "profile_digests": {p: self.profiles[p].digest() for p in
                                [r["profile_id"] for r in pre["profiles"]]},
            "preflight": pre,
        }
        spec_hash = _h({k: v for k, v in spec.items()
                        if k not in ("created_at", "preflight")})
        row, created = self.store.create_comparison(
            owner_scope=self.cfg.tenant_id, principal_id=principal_id,
            idempotency_key=idempotency_key, spec=spec, spec_hash=spec_hash,
            parent_id=request.get("parent_id"),
            label=request.get("label") or "")
        cid = row["comparison_id"]
        if not created:          # a double-click / retry: the same group
            return self.status(cid)
        self.emit(cid, "comparison.created",
                  payload={"spec_hash": spec_hash})
        self._allocate_children(cid, spec, pre)
        if start:
            self.start(cid)
        return self.status(cid)

    def _allocate_children(self, cid: str, spec: dict[str, Any],
                           pre: dict[str, Any]) -> None:
        trials = spec["trial_count"]
        rows = pre["profiles"]
        order: list[tuple[dict, int]] = [(r, t) for t in range(1, trials + 1)
                                         for r in rows]
        seed = spec.get("run_order_seed")
        if trials > 1 and seed is not None:
            # Seeded, balanced: every repetition block is shuffled separately
            # so no profile always runs first (cache/warm effects).
            rng = random.Random(int(seed))
            blocks = []
            for t in range(1, trials + 1):
                blk = [(r, t) for r in rows]
                rng.shuffle(blk)
                blocks.extend(blk)
            order = blocks
        comparator = spec.get("comparator_id")
        if comparator and seed is None:
            order.sort(key=lambda x: (x[1], x[0]["profile_id"] != comparator))
        for i, (r, t) in enumerate(order):
            prof = self.profiles[r["profile_id"]]
            state = C_QUEUED if r["eligible"] else C_BLOCKED
            child_id = f"child-{uuid.uuid4().hex[:12]}"
            self.store.add_child(
                child_run_id=child_id, comparison_id=cid,
                owner_scope=self.cfg.tenant_id, profile_id=prof.profile_id,
                profile_digest=prof.digest(),
                profile_json=json.dumps(prof.public(), sort_keys=True),
                repetition=t, attempt_id=f"att-{uuid.uuid4().hex[:10]}",
                ordinal=i, lane=r["lane"], state=state, version=1,
                reason="; ".join(r["reasons"]) if not r["eligible"] else "",
                lineage="INITIAL", enqueued_monotonic=time.monotonic(),
                enqueued_wall=time.time())
            self.emit(cid, "child.allocated", child_run_id=child_id,
                      status=state, payload={"profile_id": prof.profile_id,
                                             "reasons": r["reasons"]})

    # ---- run -------------------------------------------------------------------
    def start(self, cid: str) -> None:
        with self._lock:
            if cid in self._threads and self._threads[cid].is_alive():
                return
            self.store.set_comparison_state(
                cid, G_RUNNING, expect=(G_PREFLIGHT, G_RUNNING),
                accepted_monotonic=time.monotonic())
            self._cancel.setdefault(cid, threading.Event())
            t = threading.Thread(target=self._run_group, args=(cid,),
                                 name=f"lab-{cid}", daemon=True)
            self._threads[cid] = t
            t.start()

    def wait(self, cid: str, timeout: float = 600) -> dict[str, Any]:
        t = self._threads.get(cid)
        if t:
            t.join(timeout)
        return self.status(cid)

    def _spec(self, cid: str) -> dict[str, Any]:
        row = self.store.get_comparison(cid, self.cfg.tenant_id)
        if row is None:
            raise KeyError(cid)
        return json.loads(row["spec_json"])

    def _run_group(self, cid: str, only: list[str] | None = None,
                   turn: dict[str, Any] | None = None) -> None:
        spec = self._spec(cid)
        cancel = self._cancel.setdefault(cid, threading.Event())
        started = time.monotonic()
        wall_cap = float(spec.get("group_wall_clock_s") or 1800)
        cap_usd = float(spec.get("group_spend_cap_usd") or 0.0)
        children = [c for c in self.store.children(cid)
                    if (only is None and c["state"] == C_QUEUED)
                    or (only is not None and c["child_run_id"] in only)]
        seq = [c for c in children if c["lane"] == "sequential"]
        par = [c for c in children if c["lane"] == "parallel"]

        def gate(child: dict[str, Any]) -> str | None:
            if cancel.is_set():
                return "cancelled by the user before this child started"
            if time.monotonic() - started > wall_cap:
                return (f"group wall-clock cap {wall_cap:.0f}s reached "
                        f"before this child started")
            prof = self.profiles[child["profile_id"]]
            if self._price_status(prof)["status"] == "PAID":
                spent = self._group_spend(cid)
                if spent["committed_usd"] + spent["pending_usd"] + \
                        PER_CHILD_RESERVE_USD > cap_usd + 1e-9:
                    return (f"group spend cap ${cap_usd:.2f} would be "
                            f"exceeded (spent ${spent['committed_usd']:.4f}, "
                            f"pending ${spent['pending_usd']:.4f}, reserve "
                            f"${PER_CHILD_RESERVE_USD:.2f})")
            return None

        def run_one(child: dict[str, Any]) -> None:
            why = gate(child)
            if why:
                target = C_CANCELLED if cancel.is_set() else C_BLOCKED
                if self.store.transition_child(
                        child["child_run_id"], target,
                        expect=(C_QUEUED, C_WAITING), reason=why):
                    self.emit(cid, "child.skipped",
                              child_run_id=child["child_run_id"],
                              status=target, payload={"reason": why})
                return
            self._run_child(cid, spec, child, turn=turn, cancel=cancel)

        try:
            if par:
                with ThreadPoolExecutor(
                        max_workers=max(1, self.cfg.remote_parallel_workers)
                ) as pool:
                    futures = [pool.submit(run_one, c) for c in par]
                    for c in seq:
                        with self._sequential_lane:
                            run_one(c)
                    for f in futures:
                        f.result()
            else:
                for c in seq:
                    with self._sequential_lane:
                        run_one(c)
        except Exception:  # noqa: BLE001 - the group must still settle
            self.emit(cid, "comparison.error", status="error",
                      payload={"traceback": traceback.format_exc()[-2000:]})
        self._settle_group(cid)

    def _group_spend(self, cid: str) -> dict[str, Any]:
        committed = pending = 0.0
        uncertain = False
        for c in self.store.children(cid):
            for r in self.store.child_runs(c["child_run_id"]):
                s = self.runs.spend(r["run_id"])
                committed += float(s.get("committed_usd") or 0)
                pending += float(s.get("pending_usd") or 0)
                uncertain = uncertain or bool(s.get("uncertain"))
        return {"committed_usd": committed, "pending_usd": pending,
                "uncertain": uncertain}

    def _run_child(self, cid: str, spec: dict[str, Any],
                   child: dict[str, Any], *, turn: dict[str, Any] | None,
                   cancel: threading.Event) -> None:
        from backend.cockpit_v4 import domain_resolver as resolver
        from backend.cockpit_v4.worker import Worker
        from backend.model_lab import resources
        from backend.model_lab.adapters import AdapterUnavailable, build_provider
        from backend.model_lab.child_runtime import runtime_for
        from backend.model_lab.observe import observe

        child_id = child["child_run_id"]
        expect = (C_QUEUED,) if turn is None else (C_WAITING, C_COMPLETED)
        if not self.store.transition_child(child_id, C_PREPARING,
                                           expect=expect,
                                           worker=self.worker_id):
            return      # somebody else claimed it, or it moved on
        prof = self.profiles[child["profile_id"]]
        if prof.digest() != child["profile_digest"]:
            self.store.transition_child(
                child_id, C_BLOCKED, expect=(C_PREPARING,),
                reason="profile changed after the comparison was frozen")
            return
        self.emit(cid, "model.load.started", child_run_id=child_id,
                  source_site="coordinator",
                  measurement_method="coordinator monotonic")
        load_start = time.monotonic()
        try:
            inner = (self.provider_factory(prof) if self.provider_factory
                     else build_provider(prof, env=self.env))
        except AdapterUnavailable as exc:
            self.store.transition_child(child_id, C_BLOCKED,
                                        expect=(C_PREPARING,),
                                        reason=str(exc))
            self.emit(cid, "child.blocked", child_run_id=child_id,
                      status=C_BLOCKED, payload={"reason": str(exc)})
            return
        load_end = time.monotonic()
        self.emit(cid, "model.load.finished", child_run_id=child_id,
                  metric_values={"load_ms": (load_end - load_start) * 1000},
                  units={"load_ms": "ms"},
                  measurement_method="adapter construction only; runtime "
                                     "model residency is reported by the "
                                     "adapter when exposed")
        spans: list[dict[str, Any]] = []

        def sink(rec: dict[str, Any]) -> None:
            spans.append(rec)
            self.emit(cid, f"provider.{rec['kind']}.finished",
                      child_run_id=child_id, call_id=rec.get("call_id"),
                      status=rec.get("status", "ok"),
                      source_site="ObservingProvider",
                      mono=rec.get("start_monotonic"),
                      wall=rec.get("wall_time"),
                      metric_values={"duration_ms": rec.get("duration_ms")},
                      units={"duration_ms": "ms"},
                      measurement_method="monotonic, around converse()",
                      payload=rec)

        provider = observe(inner, sink)
        domain = spec.get("domain") or "corporate"
        rt = runtime_for(prof, provider, domain=domain,
                         runtime_dir=self.cfg.runtime_dir,
                         state_db=self.store.runs_db_path,
                         probe=self.probes().get(prof.profile_id))
        scope = resolver.scope_for(domain)
        data_tenant = self.data_tenant(domain)
        thread_id = child.get("thread_id") or self.runs.create_thread(
            tenant_id=data_tenant, principal_id=f"lab:{child_id}")
        question = (turn or {}).get("text") or spec["question_text"]
        kind = (turn or {}).get("kind") or "INITIAL"
        record, _ = self.runs.accept_run(
            thread_id=thread_id, tenant_id=data_tenant,
            principal_id=f"lab:{child_id}", question=question,
            mode=spec.get("analysis_mode") or "standard",
            release_id=scope.release_id, domain_id=domain,
            release_fingerprint=scope.release_fingerprint, ui_filters={},
            idempotency_key=f"{child_id}:{kind}:{_h(question)[:16]}",
            body_digest="", startup_sha=f"model-lab:{FROZEN_COMMIT[:12]}",
            deadline_at="")
        turn_index = self.store.add_child_run(child_id, record.run_id, kind,
                                              question)
        admitted = time.monotonic()
        if not self.store.transition_child(
                child_id, C_RUNNING, expect=(C_PREPARING,),
                thread_id=thread_id, current_run_id=record.run_id,
                admitted_monotonic=(child.get("admitted_monotonic")
                                    or admitted)):
            return
        self.emit(cid, "child.admitted", child_run_id=child_id,
                  run_id=record.run_id,
                  metric_values={"queue_delay_ms": (
                      admitted - float(child["enqueued_monotonic"] or
                                       admitted)) * 1000},
                  units={"queue_delay_ms": "ms"},
                  measurement_method="enqueued -> admitted, monotonic")
        watcher_stop = threading.Event()

        def watch_cancel() -> None:
            while not watcher_stop.wait(0.2):
                if cancel.is_set():
                    self.runs.request_cancel(record.run_id)
                    return

        w = threading.Thread(target=watch_cancel, daemon=True)
        w.start()
        sampler = resources.Sampler(interval_s=0.5)
        sampler.start()
        try:
            outcome = Worker(store=self.runs, runtime=rt).execute(record)
            frozen_state, err = outcome.state, outcome.error_code
        except Exception as exc:  # noqa: BLE001
            frozen_state, err = "FAILED", f"LAB_WORKER_EXCEPTION:{exc}"
        finally:
            watcher_stop.set()
            samples = sampler.stop()
        finished = time.monotonic()
        self.store.finish_child_run(child_id, turn_index, frozen_state, err)
        to = _FROZEN_TO_CHILD.get(frozen_state, C_FAILED)
        self.store.transition_child(
            child_id, to, expect=(C_RUNNING,), finished_monotonic=finished,
            finished_wall=time.time(), reason=err or "")
        self.emit(cid, "resource.samples", child_run_id=child_id,
                  run_id=record.run_id, payload=samples,
                  measurement_method=samples.get("method", ""))
        self.emit(cid, "child.settled", child_run_id=child_id,
                  run_id=record.run_id, status=to,
                  payload={"frozen_state": frozen_state, "error_code": err,
                           "provider_calls": len(spans)},
                  metric_values={"service_ms": (finished - admitted) * 1000},
                  units={"service_ms": "ms"})

    def _settle_group(self, cid: str) -> None:
        kids = self.store.children(cid)
        states = [k["state"] for k in kids]
        if any(s in (C_QUEUED, C_PREPARING, C_RUNNING) for s in states):
            return
        cancelled = self._cancel.get(cid) and self._cancel[cid].is_set()
        if cancelled:
            g = G_CANCELLED
        elif all(s == C_BLOCKED for s in states):
            g = G_BLOCKED
        elif all(s == C_COMPLETED for s in states):
            g = G_COMPLETE
        else:
            g = G_PARTIAL
        self.store.set_comparison_state(cid, g, settled=True)
        self.emit(cid, "comparison.settled", status=g,
                  payload={"child_states": states,
                           "waiting_user": states.count(C_WAITING)})
        if self.on_settled:
            try:
                self.on_settled(cid)
            except Exception:  # noqa: BLE001 - evaluation never gates runs
                self.emit(cid, "evaluation.error", status="error",
                          payload={"traceback":
                                   traceback.format_exc()[-2000:]})

    # ---- cancel / clarification / follow-up --------------------------------
    def cancel(self, cid: str) -> dict[str, Any]:
        self._cancel.setdefault(cid, threading.Event()).set()
        for c in self.store.children(cid):
            if c["state"] == C_QUEUED:
                self.store.transition_child(c["child_run_id"], C_CANCELLED,
                                            expect=(C_QUEUED,),
                                            reason="cancelled by the user")
            elif c["state"] in (C_RUNNING, C_PREPARING) and \
                    c.get("current_run_id"):
                self.runs.request_cancel(c["current_run_id"])
        self.emit(cid, "comparison.cancel_requested")
        t = self._threads.get(cid)
        if not t or not t.is_alive():
            self._settle_group(cid)
        return self.status(cid)

    def answer_clarification(self, cid: str, *, text: str,
                             child_ids: list[str]) -> dict[str, Any]:
        """Resume ONLY the named children, which must be waiting."""
        text = str(text or "").strip()
        if not text:
            raise SpecError("the clarification answer is empty")
        if not child_ids:
            raise SpecError("name the child investigations this answer is "
                            "for; the lab does not guess")
        kids = {c["child_run_id"]: c for c in self.store.children(cid)}
        bad = [k for k in child_ids if k not in kids or
               kids[k]["state"] != C_WAITING]
        if bad:
            raise SpecError(f"not waiting for a clarification: {bad}")
        self.emit(cid, "clarification.answered",
                  payload={"recipients": child_ids, "text": text})
        return self._resume(cid, child_ids, {"kind": "CLARIFICATION",
                                             "text": text})

    def follow_up(self, cid: str, *, text: str,
                  child_ids: list[str] | None = None) -> dict[str, Any]:
        """NATURAL_CONVERSATION: the same text to each child's OWN thread."""
        text = str(text or "").strip()
        if not text:
            raise SpecError("the follow-up is empty")
        kids = [c for c in self.store.children(cid)
                if c["state"] == C_COMPLETED and c.get("thread_id")
                and (not child_ids or c["child_run_id"] in child_ids)]
        if not kids:
            raise SpecError("no completed child investigation to follow up")
        ids = [c["child_run_id"] for c in kids]
        for c in kids:
            self.store.update_child(c["child_run_id"],
                                    lineage="NATURAL_CONVERSATION")
        self.emit(cid, "followup.sent", payload={"recipients": ids,
                                                 "text": text,
                                                 "label":
                                                 "NATURAL_CONVERSATION"})
        return self._resume(cid, ids, {"kind": "FOLLOW_UP", "text": text})

    def _resume(self, cid: str, ids: list[str], turn: dict[str, Any]
                ) -> dict[str, Any]:
        self.store.set_comparison_state(cid, G_RUNNING)
        t = threading.Thread(target=self._run_group, args=(cid,),
                             kwargs={"only": ids, "turn": turn},
                             daemon=True, name=f"lab-{cid}-resume")
        self._threads[cid] = t
        t.start()
        return self.status(cid)

    # ---- restart safety ------------------------------------------------------
    def recover_interrupted(self) -> list[str]:
        """After a crash: in-flight children become INTERRUPTED, with their
        actual partial usage kept. Nothing is re-dispatched automatically."""
        out = []
        for row in self.store.list_comparisons(self.cfg.tenant_id, 500):
            if row["state"] in G_TERMINAL:
                continue
            for c in self.store.children(row["comparison_id"]):
                if c["state"] in (C_PREPARING, C_RUNNING):
                    if self.store.transition_child(
                            c["child_run_id"], C_INTERRUPTED,
                            expect=(C_PREPARING, C_RUNNING),
                            reason="lab process restarted while this child "
                                   "was in flight; not re-dispatched"):
                        out.append(c["child_run_id"])
                        self.emit(row["comparison_id"], "child.interrupted",
                                  child_run_id=c["child_run_id"],
                                  status=C_INTERRUPTED)
            if not any(c["state"] == C_QUEUED
                       for c in self.store.children(row["comparison_id"])):
                self._settle_group(row["comparison_id"])
        return out

    # ---- read ------------------------------------------------------------------
    def status(self, cid: str) -> dict[str, Any]:
        row = self.store.get_comparison(cid, self.cfg.tenant_id)
        if row is None:
            raise KeyError(cid)
        spec = json.loads(row["spec_json"])
        kids = []
        for c in self.store.children(cid):
            k = {key: c[key] for key in (
                "child_run_id", "profile_id", "profile_digest", "repetition",
                "attempt_id", "ordinal", "lane", "state", "reason",
                "thread_id", "current_run_id", "lineage")}
            k["display_name"] = self.profiles[c["profile_id"]].display_name \
                if c["profile_id"] in self.profiles else c["profile_id"]
            k["fixture"] = json.loads(c["profile_json"]).get("role") == \
                registry.ROLE_FIXTURE
            k["turns"] = self.store.child_runs(c["child_run_id"])
            kids.append(k)
        return {"comparison_id": cid, "state": row["state"],
                "spec": spec, "spec_hash": row["spec_hash"],
                "created_at": row["created_at"],
                "settled_at": row["settled_at"], "children": kids}

"""
Drive the REAL AdvancedCockpit, in-process, through its own HTTP routes.

What runs is exactly what `scripts/cockpit_v4/start.py` launches for the API:
`backend.cockpit_v4.app.create_app(...)` with its real Worker and Supervisor
daemon threads. The harness is a client: it POSTs `/runs`, polls
`GET /runs/{id}` until the run is terminal, and then READS the store.

The provider handed to `create_app` is the real `AnthropicProvider` (live) or
a scripted provider (fixtures), wrapped in `ObservingProvider`, which forwards
every call unchanged.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cert import APPROVED_MODEL, APPROVED_PRICE_CARD
from cert.observe import ObservingProvider, Recorder, install_sdk_shims
from cert.paths import ROOT, ensure_import_path

ensure_import_path()

API = "/api/v1/cockpit-v4"
TERMINAL_STATES = {"COMPLETED", "PARTIAL", "WAITING_FOR_USER", "REFERRED",
                   "UNSUPPORTED", "FAILED", "CANCELLED", "EXPIRED",
                   "INTERRUPTED"}


def parse_iso(text: str) -> float | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def environment_for(runtime_dir: Path, *, model: str = APPROVED_MODEL,
                    price_card: str = APPROVED_PRICE_CARD) -> dict[str, str]:
    """The API child's environment, exactly as start.py builds it.

    Only the runtime directory differs: it is isolated per experiment so the
    certification never touches the presentation runtime's state database.
    """
    return {
        "COCKPIT_AGENTIC_V4": "true",
        "COCKPIT_V4_RUNTIME_DIR": str(runtime_dir),
        "COCKPIT_V4_STATE_DATABASE": str(runtime_dir / "state" / "cockpit_v4.sqlite3"),
        "COCKPIT_V4_RELEASE_ID": os.environ.get("COCKPIT_V4_RELEASE_ID", "v4-saudi-20q-v1"),
        "COCKPIT_V4_PRICE_CARD": str(ROOT / price_card),
        "COCKPIT_V4_LOCAL_DEMO_AUTH": "true",
        "COCKPIT_V4_MEMORY_ENABLED": os.environ.get("COCKPIT_V4_MEMORY_ENABLED", "false"),
        "COCKPIT_AGENTIC_V3_NAMESPACE": os.environ.get("COCKPIT_V4_NAMESPACE", "cockpit_v4"),
        "AI_COCKPIT_REASONING_MODEL": model,
        "AI_PROVIDER": "anthropic",
    }


class SwitchableProvider:
    """Fixture mode only: lets each scripted case install its own script."""

    def __init__(self) -> None:
        self.inner: Any = None

    def set(self, inner: Any) -> None:
        self.inner = inner

    def count_tokens(self, **kwargs: Any) -> Any:
        if self.inner is None:  # capability verification at boot
            payload = json.dumps(kwargs, default=str)
            return int(len(payload) / 3.5) + 1
        return self.inner.count_tokens(**kwargs)

    def converse(self, **kwargs: Any) -> Any:
        if self.inner is None:
            raise RuntimeError("no scripted provider installed for this case")
        return self.inner.converse(**kwargs)


@dataclass
class TurnResult:
    """What one POST produced, before evaluation."""

    http_status: int
    http_body: dict[str, Any]
    run_id: str = ""
    thread_id: str = ""
    posted_at: float = 0.0          # wall clock (epoch s)
    post_mono: float = 0.0
    observed_terminal_mono: float = 0.0
    timed_out: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


class CockpitHarness:
    """One in-process AdvancedCockpit, driven over its own routes."""

    def __init__(self, runtime_dir: Path, *, live: bool, recorder: Recorder,
                 real_provider_factory: Callable[[Any], Any] | None = None,
                 poll_seconds: float = 0.2) -> None:
        self.runtime_dir = runtime_dir
        self.live = live
        self.recorder = recorder
        self.poll_seconds = poll_seconds
        runtime_dir.mkdir(parents=True, exist_ok=True)
        os.environ.update(environment_for(runtime_dir))
        self.shims = install_sdk_shims(recorder)

        from fastapi.testclient import TestClient

        from backend.cockpit_v4 import config as config_mod
        from backend.cockpit_v4.app import create_app

        self.cfg = config_mod.load()
        if live:
            from backend.cockpit_v4.service import resolve_provider

            inner = (real_provider_factory(self.cfg) if real_provider_factory
                     else resolve_provider(self.cfg))
            self.switch = None
        else:
            self.switch = SwitchableProvider()
            inner = self.switch
        self.provider = ObservingProvider(inner, recorder)
        self.app = create_app(self.cfg, provider=self.provider,
                              verify_model=True, start_workers=True)
        state = self.app.state.cockpit_v4
        self.store = state["store"]
        self.runtime = state["runtime"]
        self.preflight_error = state.get("preflight_error", "")
        self.startup_sha = state.get("startup_sha", "")
        self.client = TestClient(self.app)

    # -- health ------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return self.client.get("/health").json()

    def capability(self) -> dict[str, Any]:
        cap = getattr(self.runtime, "capability", None)
        if cap is None:
            return {}
        return {k: getattr(cap, k, None) for k in (
            "model_id", "provider", "live_verified", "verified_at", "source",
            "context_tokens", "max_output_tokens", "supports_forced_tool_use",
            "supports_named_tool_forcing", "supports_effort_control",
            "supports_single_tool_per_turn", "supports_token_counting")}

    # -- one turn ----------------------------------------------------------
    def post(self, question: str, *, domain: str = "", thread_id: str = "",
             mode: str = "standard") -> TurnResult:
        body: dict[str, Any] = {"question": question, "mode": mode}
        if domain:
            body["domain"] = domain
        if thread_id:
            body["thread_id"] = thread_id
        posted_at, post_mono = time.time(), time.monotonic()
        response = self.client.post(f"{API}/runs", json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text[:2000]}
        result = TurnResult(http_status=response.status_code,
                            http_body=payload if isinstance(payload, dict) else {"body": payload},
                            posted_at=posted_at, post_mono=post_mono)
        if response.status_code == 202:
            result.run_id = str(payload.get("run_id") or "")
            result.thread_id = str(payload.get("thread_id") or "")
        return result

    def wait(self, result: TurnResult, *, timeout_seconds: float = 420.0) -> TurnResult:
        if not result.run_id:
            result.observed_terminal_mono = time.monotonic()
            return result
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            record = self.store.get_run(result.run_id)
            if record is not None and str(record.state) in TERMINAL_STATES:
                # The worker settles the answer BEFORE publishing answer.ready;
                # give the event stream a moment to receive its terminal event.
                time.sleep(0.05)
                result.observed_terminal_mono = time.monotonic()
                return result
            time.sleep(self.poll_seconds)
        result.timed_out = True
        result.observed_terminal_mono = time.monotonic()
        return result

    # -- evidence (read-only) ------------------------------------------------
    def reservations(self, run_id: str) -> list[dict[str, Any]]:
        db = Path(self.cfg.state_database)
        uri = f"file:{db}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT reservation_id, purpose, reserved_usd, settled_usd, "
                "uncertain, usage, created_at FROM reservations WHERE run_id=? "
                "ORDER BY created_at, rowid", (run_id,)).fetchall()
        finally:
            conn.close()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["usage"] = json.loads(item.get("usage") or "{}")
            except (TypeError, ValueError):
                pass
            out.append(item)
        return out

    def collect(self, run_id: str) -> dict[str, Any]:
        store = self.store
        record = store.get_run(run_id)
        if record is None:
            return {"run_id": run_id, "missing": True}
        tenant = str(record.tenant_id or "")
        events = [e.to_dict() if hasattr(e, "to_dict") else dict(e.__dict__)
                  for e in store.events_since(run_id, 0, limit=100000)]
        artifacts = []
        for aid in store.artifact_ids_for_run(run_id, tenant_id=tenant):
            art = store.get_artifact(aid, tenant_id=tenant)
            if art is not None:
                artifacts.append(art)
        lease = None
        try:
            lease = store.lease(run_id)
        except Exception:  # noqa: BLE001
            lease = None
        try:
            messages = store.load_messages(run_id)
        except Exception as exc:  # noqa: BLE001
            messages = [{"error": str(exc)}]
        return {
            "run_id": run_id,
            "record": record.to_dict() | {
                "tenant_id": tenant, "question": record.question,
                "domain_id": record.domain_id,
                "release_fingerprint": record.release_fingerprint,
                "created_at": record.created_at, "updated_at": record.updated_at,
                "deadline_at": record.deadline_at, "startup_sha": record.startup_sha},
            "events": events,
            "details": store.details_for_run(run_id),
            "submissions": store.submissions_for_run(run_id),
            "artifacts": artifacts,
            "messages": messages,
            "reservations": self.reservations(run_id),
            "spend": store.spend(run_id),
            "lease": lease,
            "thread_turns": store.thread_turns(record.thread_id),
        }

    def close(self) -> None:
        try:
            state = self.app.state.cockpit_v4
            for key in ("worker", "supervisor"):
                obj = state.get(key)
                if obj is not None and hasattr(obj, "stop"):
                    obj.stop()
        except Exception:  # noqa: BLE001
            pass

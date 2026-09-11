"""
The standalone V4 application. Its own process, its own port, its own state.

Why standalone rather than a router bolted onto the product app
---------------------------------------------------------------
Mounting V4 into the existing FastAPI application would put V4 code in the
process that serves V3, EWS, What-if and everything else -- and a V4 defect
would then take those down. The whole isolation requirement is that a V4
build cannot disturb a running instance, so V4 runs as its own ASGI app on
its own port and shares nothing but read-only data files.

`routes.router` is additive and CAN be included in the product app by a
deployment that wants that later. Nothing here requires it.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.cockpit_v4 import config as config_mod
from backend.cockpit_v4 import routes
from backend.cockpit_v4.run_store import RunStore
from backend.cockpit_v4.service import PreflightFailed, build_runtime
from backend.cockpit_v4.supervisor import Supervisor
from backend.cockpit_v4.worker import Worker

logger = logging.getLogger(__name__)

#: The demo principal a loopback synthetic-only profile may issue. It is
#: server-controlled: nothing in a request can name a different tenant, and
#: the tenant it DOES get is the one the pinned synthetic release actually
#: contains -- a demo principal scoped to a tenant the release has no rows
#: for reads as "the portfolio is empty" rather than "you are looking at the
#: wrong release".
#:
#: It carries NO `name`. "Local UAT" is the name of a profile, not of the
#: person at the keyboard, and a landing page that greets a deployment label
#: as if it were a colleague is worse than one that greets nobody. The label
#: travels as `profile_label`, which the operator view shows and the greeting
#: never reads.
DEMO_PRINCIPAL = {"id": "v4-local-demo", "tenant": "demo", "name": "",
                  "profile_label": "Local UAT", "demo": True}


def demo_tenant(runtime: Any, cfg: config_mod.V4Config) -> str:
    """The synthetic release's own tenant, or the documented fallback."""
    tenants = (getattr(runtime, "release_summary", None) or {}).get("tenants")
    if isinstance(tenants, (list, tuple)) and tenants:
        return str(tenants[0])
    return str(DEMO_PRINCIPAL["tenant"])


def startup_sha() -> str:
    """The SHA the PROCESS started from, read once.

    Not re-read later: a checkout that moves while the process runs would
    otherwise make the trace claim code that is not what is executing.
    """
    cached = os.environ.get("COCKPIT_V4_STARTUP_SHA", "").strip()
    if cached:
        return cached
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parents[2]), timeout=5)
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _demo_resolver(cfg: config_mod.V4Config, runtime: Any = None) -> Any:
    tenant = demo_tenant(runtime, cfg)

    def resolve(request: Request) -> dict[str, Any] | None:
        if not cfg.local_demo_auth:
            return None
        client = request.client.host if request.client else ""
        # Loopback only. A demo principal that works off-host is not a demo
        # profile, it is an unauthenticated deployment.
        if client not in ("127.0.0.1", "::1", "localhost", "testclient"):
            return None
        return {**DEMO_PRINCIPAL, "tenant": tenant}
    return resolve


def _session_resolver() -> Any:
    """Reuse the product's authenticated user when it is importable."""
    def resolve(request: Request) -> dict[str, Any] | None:
        user = getattr(request.state, "user", None)
        if user is None:
            return None
        return {"id": str(getattr(user, "id", "") or getattr(user, "email", "")),
                "tenant": str(getattr(user, "tenant_id", "") or "default"),
                "name": str(getattr(user, "name", "") or "")}
    return resolve


def create_app(cfg: config_mod.V4Config | None = None, *,
               provider: Any = None, verify_model: bool = True,
               start_workers: bool = True) -> FastAPI:
    cfg = cfg or config_mod.load()
    sha = startup_sha()

    app = FastAPI(title="CreditProbe Cockpit V4", version="4.1",
                  docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://127.0.0.1:{cfg.ui_port}",
                       f"http://localhost:{cfg.ui_port}"],
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    store = RunStore(cfg.state_database)
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    for directory in (cfg.artifacts_dir, cfg.logs_dir, cfg.pids_dir):
        directory.mkdir(parents=True, exist_ok=True)

    runtime = None
    preflight_error = ""
    try:
        runtime = build_runtime(cfg, provider=provider,
                               verify_model=verify_model)
    except PreflightFailed as exc:
        # The app still starts, so /diagnostics can SAY what is missing.
        # It just cannot accept a run that would need the missing thing.
        preflight_error = f"{exc.code}: {exc}"
        logger.warning("V4 preflight incomplete: %s", preflight_error)

    class _Runtime:
        cfg = None

    holder = runtime or _Runtime()
    holder.cfg = cfg

    resolver = (_demo_resolver(cfg, runtime) if cfg.local_demo_auth
                else _session_resolver())
    routes.install(store=store, runtime=holder,
                   principal_resolver=resolver, startup_sha=sha)
    app.include_router(routes.router)
    # The shell's status indicator polls /api/v1/health. Serving
    # it here is what stops the header reporting the whole
    # backend as offline when it is pointed at V4.
    app.include_router(routes.compat_router)

    app.state.cockpit_v4 = {
        "config": cfg, "store": store, "runtime": runtime,
        "startup_sha": sha, "preflight_error": preflight_error}

    if start_workers and runtime is not None:
        worker = Worker(store=store, runtime=runtime)
        supervisor = Supervisor(store=store,
                                poll_seconds=cfg.supervisor_poll_seconds,
                                lease_stale_seconds=cfg.lease_stale_seconds)
        threading.Thread(target=worker.serve_forever, daemon=True,
                         name="cockpit-v4-worker").start()
        threading.Thread(target=supervisor.serve_forever, daemon=True,
                         name="cockpit-v4-supervisor").start()
        app.state.cockpit_v4["worker"] = worker
        app.state.cockpit_v4["supervisor"] = supervisor

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "service": "cockpit-v4", "startup_sha": sha,
                "preflight_error": preflight_error,
                "api_port": cfg.api_port}

    return app


__all__ = ["DEMO_PRINCIPAL", "create_app", "startup_sha"]

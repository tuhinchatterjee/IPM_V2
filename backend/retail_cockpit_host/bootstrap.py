"""A V4-only runtime: the domain book, and no pre-domain release anywhere.

The problem this solves
-----------------------
`cockpit_v4.service.load_release` -- the engine's PREFLIGHT, which decides
`release_ready` and therefore `sql_analysis_ready` -- resolves its release
through `cockpit_agentic.store`, the PRE-DOMAIN V3 reader, even for a
deployment that publishes only domain books. Two things then fail for this
candidate, and neither is a configuration mistake:

* pointing the V3 store at the V4 lake gets as far as reading the manifest
  and then stops, because `cockpit_agentic.calendar` requires a release to
  have exactly twenty reporting slots and Cockpit Data has twenty-five
  months. Publishing twenty would be publishing a false calendar;
* seeding a pre-domain release so the preflight has something to open is
  exactly the fake release this integration was told not to build.

So the runtime is assembled HERE instead, from the domain release the
Cockpit actually answers from. Nothing in `backend/cockpit_v4/**` changes:
`service.Runtime` is a dataclass, `routes.install` is a public seam the
engine already exposes, and every field is filled from the engine's own
functions.

Why this is not a shortcut
--------------------------
`service.Runtime.catalog` is not what an analytical run reads. `worker._book_for`
calls `analytical_runtime.for_run`, which resolves the DOMAIN book, and falls
back to `_LegacyBook` only for a run accepted against a non-domain release --
which this deployment cannot produce, because it publishes none. The legacy
catalogue's remaining readers are `/attention-legacy` and the legacy feed,
neither of which this candidate serves. What it does decide is readiness, and
readiness about a domain book should be decided by the domain book.

`capability` and `provider` are built by the engine's own `load_capability`
and `resolve_provider`, unchanged, so the model verification, the price card
and the fail-closed behaviour on an unverified model are all the engine's.

The one exception, and its boundary
-----------------------------------
A provider that CANNOT REACH A PAID API gets its capability from
`offline.offline_capability` instead, because a price for a call that cannot
happen is not a thing to fail closed on. The gate is the provider object --
`offline.is_offline` -- and not `verify_model`, which the engine reads only
for the live probe and which a live deployment could carry by accident. A
real provider always goes through `load_capability` and is still refused by a
card that does not carry its model. See `offline` for the full rule.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BootstrapIncomplete(RuntimeError):
    """The runtime could not be assembled. Named, never half-built."""


def domain_release_id(cfg: Any, domain_id: str = "retail") -> str:
    """The release this book is configured to open."""
    from backend.cockpit_v4 import domains as dom

    return str(dom.DEFAULT_RELEASES[domain_id])


def release_summary(release_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """The summary shape `service.load_release` publishes, from OUR manifest.

    Same keys, same source of truth, so anything reading a release summary
    reads the same thing it would have read from the pre-domain path.
    """
    from backend.cockpit_v4 import service

    summary = {"dataset_release_id": release_id,
               "domain_id": str(manifest.get("domain_id") or ""),
               **{k: manifest.get(k) for k in
                  ("origin", "data_version", "not_client_data",
                   "reporting_currency", "amount_scale", "tenants",
                   "geography", "geography_name", "localization",
                   "amounts_converted", "release_fingerprint",
                   "reporting_frequency", "reporting_periods")
                  if k in manifest}}
    currency, scale = service.denomination(release_id, manifest)
    summary["reporting_currency"] = currency
    summary["amount_scale"] = scale
    return summary


def build_runtime(cfg: Any = None, *, domain_id: str = "retail",
                  provider: Any = None, verify_model: bool = True) -> Any:
    """The engine's `Runtime`, assembled from the domain release.

    Raises `PreflightFailed` for the things the engine itself would refuse --
    a missing credential, an unconfigured or unverified model -- so a caller
    handles them exactly as `create_app` does.
    """
    from backend.cockpit_v4 import catalog as cat
    from backend.cockpit_v4 import config as config_mod
    from backend.cockpit_v4 import lake, service
    from backend.retail_cockpit_host import offline

    cfg = cfg or config_mod.load()
    release_id = domain_release_id(cfg, domain_id)
    if not lake.exists(release_id):
        raise BootstrapIncomplete(
            f"release {release_id!r} is not published in this runtime's V4 "
            f"lake ({lake.root()}). Nothing was substituted for it. Publish "
            f"it with scripts/retail_cockpit/publish_release.py.")

    manifest = lake.read_manifest(release_id)
    tenant = str((manifest.get("tenants") or [lake.DEFAULT_TENANT])[0]
                 or lake.DEFAULT_TENANT)
    catalog = cat.build(domain_id=domain_id, release_id=release_id,
                        tenant_id=tenant)

    if provider is None:
        # Built by the engine, then pinned so the SDK cannot retry outside
        # the ledger -- see `offline.pin_transport`.
        provider = offline.pin_transport(service.resolve_provider(cfg))
    # A provider that cannot call out does not need a price for a call it
    # cannot make. `verify_model=False` alone is NOT enough to reach this:
    # `load_capability` reads the price card unconditionally and only skips
    # the LIVE probe, so a real provider with verification off is still
    # refused by a card that does not carry its model. The gate is the
    # provider object itself -- see `offline.is_offline`.
    if offline.is_offline(provider):
        capability = offline.offline_capability(cfg)
    else:
        capability = service.load_capability(cfg, provider,
                                             verify=verify_model)

    return service.Runtime(
        cfg=cfg, capability=capability, provider=provider, catalog=catalog,
        coverage=None, release_summary=release_summary(release_id, manifest))


def install(app: Any, *, domain_id: str = "retail", provider: Any = None,
            verify_model: bool = True, start_workers: bool = True) -> Any:
    """Put a domain runtime behind an app `create_app` left without one.

    Returns the runtime, or `None` when the engine's own preflight rules
    refuse it -- a missing credential or an unverified model. `None` is not a
    failure to start: the process serves, `/diagnostics` says what is
    missing, and every analytical route refuses with a typed 503 rather than
    accepting work nothing will do.
    """
    import threading

    from backend.cockpit_v4 import routes, service
    from backend.cockpit_v4.supervisor import Supervisor
    from backend.cockpit_v4.worker import Worker

    state = getattr(app.state, "cockpit_v4", None) or {}
    cfg = state.get("config")
    store = state.get("store")
    error = str(state.get("preflight_error") or "")

    try:
        runtime = build_runtime(cfg, domain_id=domain_id, provider=provider,
                                verify_model=verify_model)
        error = ""
    except service.PreflightFailed as exc:
        logger.warning("Cockpit preflight incomplete: %s: %s", exc.code, exc)
        return _reinstall(routes, state, None, f"{exc.code}: {exc}")
    except BootstrapIncomplete as exc:
        logger.error("Cockpit book unavailable: %s", exc)
        return _reinstall(routes, state, None, str(exc))

    _reinstall(routes, state, runtime, error)
    app.state.cockpit_v4["runtime"] = runtime
    app.state.cockpit_v4["preflight_error"] = error

    # `create_app` starts these only when ITS preflight produced a runtime.
    # Ours did, so they are started here -- once, and never twice.
    if start_workers and "worker" not in app.state.cockpit_v4:
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
    return runtime


def _reinstall(routes: Any, state: dict[str, Any], runtime: Any,
               error: str) -> Any:
    from backend.retail_cockpit_host import identity

    routes.install(
        store=state.get("store"), runtime=runtime, cfg=state.get("config"),
        preflight_error=error,
        principal_resolver=identity.forwarded_resolver(),
        startup_sha=str(state.get("startup_sha") or ""))
    return runtime


__all__ = ["BootstrapIncomplete", "build_runtime", "domain_release_id",
           "install", "release_summary"]

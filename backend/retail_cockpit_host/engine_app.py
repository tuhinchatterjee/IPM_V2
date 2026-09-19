"""The candidate Cockpit engine, built from the frozen `create_app()`.

    uvicorn backend.retail_cockpit_host.engine_app:app

Everything analytical is the engine's. This module does exactly three things,
all of them after `create_app()` has returned and none of them inside
`backend/cockpit_v4/**`:

1. replaces the principal resolver with the one that reads what the retail
   proxy forwarded, through `routes.install` -- the module-level seam the
   engine already exposes for precisely this;
2. refuses to start without the boundary secret, rather than starting with
   an open door;
3. says which book it opened, so a launcher can fail fast rather than serve
   a Cockpit bound to the wrong release.

The engine's own CORS allowance stays as it is and is never used: the browser
talks to the retail origin, and this process listens on loopback only.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.retail_cockpit_host import identity

logger = logging.getLogger(__name__)


def build_app(**kwargs: Any) -> Any:
    """The engine, with retail identity wired into it."""
    from backend.cockpit_v4.app import create_app
    from backend.retail_cockpit_host import bootstrap

    # Read first: a process that cannot authenticate its own boundary must
    # not come up serving a Cockpit that would accept anything.
    identity.secret()

    app = create_app(**kwargs)

    # `create_app`'s own preflight reads its release through the pre-domain
    # V3 store, which cannot open a twenty-five month domain book. So the
    # runtime is rebuilt here from the domain release and installed through
    # the seam the engine exposes, together with the retail principal
    # resolver. Both go in one call, so the engine is never briefly serving
    # with one of them and not the other.
    runtime = bootstrap.install(app, **{k: v for k, v in kwargs.items()
                                        if k in ("provider", "verify_model",
                                                 "start_workers")})
    catalog = getattr(runtime, "catalog", None)
    logger.info(
        "Retail Cockpit candidate engine ready: release %s, tenant %s, "
        "preflight %s",
        getattr(catalog, "dataset_release_id", "(none)"), identity.tenant(),
        (getattr(app.state, "cockpit_v4", None)
         or {}).get("preflight_error") or "clean")
    return app


app = build_app()

__all__ = ["app", "build_app"]

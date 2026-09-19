"""The candidate's host side: the engine entrypoint and the retail proxy.

Nothing in this package is part of the frozen engine. It exists so that the
AdvancedCockpit can run as its own process behind the Retail Demo's own
authentication, without a single line of `backend/cockpit_v4/**` changing.

Two pieces, and the split matters:

* `engine_app` builds the engine with `create_app()` and then REPLACES its
  principal resolver through the module-level seam the engine already
  exposes (`routes.install`). The engine's own `_session_resolver` reads
  `request.state.user`, which the retail app never sets -- it puts only a
  request id there -- so every call would 401.
* `proxy` is the retail-side router. The browser only ever talks to the
  retail origin, so the engine's port is never exposed, the retail app's
  default-deny middleware authenticates every call before anything reaches
  the engine, and the client's `EventSource` -- which does not set
  `withCredentials` -- is same-origin and therefore carries its cookie.
"""

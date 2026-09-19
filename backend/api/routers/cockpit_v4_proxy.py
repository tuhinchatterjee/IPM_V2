"""The Retail Demo's authenticated door onto the candidate Cockpit engine.

The browser never talks to the engine. It calls this origin, the app's own
default-deny middleware authenticates the session before anything reaches
here, and this router forwards the call to the engine on loopback with the
principal attached and the boundary secret proving where it came from.

Why a proxy rather than exposing the engine's port
--------------------------------------------------
Three things fall out of it, and each was a real defect otherwise:

* the Cockpit client's `EventSource` does not set `withCredentials`, so a
  cross-origin event stream would carry no session cookie at all;
* the retail app's default-deny 401 is emitted OUTSIDE its CORS middleware,
  so a cross-origin 401 reaches the browser as a CORS error rather than as a
  401 anybody can act on;
* the engine's identity would have to be trusted to a browser-set header.

Same-origin removes all three. The Cockpit client opts in by
`NEXT_PUBLIC_COCKPIT_V4_API=same-origin`, which its own `base()` already
understands as "call my own origin".

Streaming
---------
The engine's event stream is the product. It is forwarded byte for byte:
`aiter_raw` rather than `aiter_text` so nothing is re-chunked or re-encoded,
the upstream's `X-Accel-Buffering: no` and `Cache-Control: no-transform`
carried through, no compression negotiated, and no read timeout -- a run that
thinks for ninety seconds between frames is a run working correctly. Client
disconnect propagates upstream, so the engine's own
`await request.is_disconnected()` fires and its generator stops.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from backend.api.auth import account_for
from backend.api.permissions import Principal, current_principal
from backend.retail_cockpit_host import identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cockpit-v4", tags=["cockpit-v4"])

#: Where the engine listens. Loopback only; the launcher picks the port and
#: passes it to both processes.
ENGINE_URL_VAR = "RETAIL_COCKPIT_ENGINE_URL"
DEFAULT_ENGINE_URL = "http://127.0.0.1:8414"

#: The engine's own prefix, which this router mirrors so a path maps one to
#: one and no rewriting is needed in either direction.
ENGINE_PREFIX = "/api/v1/cockpit-v4"

#: Hop-by-hop headers, which belong to one connection and must not be
#: forwarded across another (RFC 9110 §7.6.1). `content-length` goes too:
#: the body is re-framed by httpx and a stale length is a truncated response.
_DROP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length",
    "content-encoding", "host",
})

#: A run may think for a long time between frames, and an idle stream is not
#: a broken one. Connect is bounded because a refused connection should be
#: reported now rather than hang the page.
_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)


def engine_url() -> str:
    return str(os.environ.get(ENGINE_URL_VAR, "")
               or DEFAULT_ENGINE_URL).rstrip("/")


def _client(request: Request) -> httpx.AsyncClient:
    """One shared client, so connections are pooled across a page of calls."""
    client = getattr(request.app.state, "cockpit_v4_client", None)
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
        request.app.state.cockpit_v4_client = client
    return client


def _principal(principal: Principal) -> dict[str, Any]:
    account = account_for(principal.user_id) if principal.user_id else None
    forwarded = identity.principal_for(account, principal.role)
    if not forwarded["id"]:
        # A header-role caller in a `REQUIRE_LOGIN=false` runtime has a role
        # and no account. That is a real local-development identity, so it
        # is given a stable id rather than an empty one the engine would
        # refuse -- and it is never a signed-in user's id.
        forwarded["id"] = f"role:{forwarded['role'] or 'anonymous'}"
    return forwarded


def _outbound(request: Request, principal: dict[str, Any]) -> dict[str, str]:
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in _DROP}
    # The engine derives identity server-side and refuses to read it from a
    # body. Same rule across the boundary: these two are set HERE, from the
    # session this app already authenticated, and any inbound copy is
    # overwritten rather than merged.
    headers[identity.PRINCIPAL_HEADER] = identity.encode(principal)
    headers[identity.AUTH_HEADER] = identity.secret()
    # Never negotiate compression on a stream: a compressed event stream is
    # a buffered event stream.
    headers.pop("accept-encoding", None)
    headers["accept-encoding"] = "identity"
    return headers


def _inbound(response: httpx.Response) -> dict[str, str]:
    return {k: v for k, v in response.headers.items()
            if k.lower() not in _DROP}


async def _forward(request: Request, path: str,
                   caller: Principal) -> Response:
    try:
        headers = _outbound(request, _principal(caller))
    except identity.SecretMissing as exc:
        logger.error("Cockpit proxy refused a call: %s", exc)
        raise HTTPException(503, {
            "error": "cockpit_not_configured",
            "message": "The Cockpit engine boundary is not configured in "
                       "this runtime.", "status": 503}) from exc

    url = f"{engine_url()}{ENGINE_PREFIX}/{path}"
    client = _client(request)
    streaming = "text/event-stream" in request.headers.get("accept", "")
    body = await request.body()

    build = client.build_request(
        request.method, url, headers=headers, content=body or None,
        params=dict(request.query_params))
    try:
        upstream = await client.send(build, stream=True)
    except httpx.ConnectError as exc:
        raise HTTPException(503, {
            "error": "cockpit_unavailable",
            "message": "The Cockpit engine is not running in this runtime.",
            "status": 503}) from exc

    if not streaming:
        try:
            payload = await upstream.aread()
        finally:
            await upstream.aclose()
        return Response(content=payload, status_code=upstream.status_code,
                        headers=_inbound(upstream),
                        media_type=upstream.headers.get("content-type"))

    async def relay():
        try:
            # RAW, so frames cross exactly as the engine wrote them. Decoding
            # to text and re-encoding would re-chunk the stream, which is the
            # one thing an event stream cannot survive.
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        relay(), status_code=upstream.status_code, headers=_inbound(upstream),
        media_type=upstream.headers.get("content-type", "text/event-stream"))


@router.api_route("/{path:path}",
                  methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request,
                principal: Principal = Depends(current_principal)) -> Response:
    """Every Cockpit call, authenticated here and forwarded there."""
    request.state.cockpit_principal = principal
    return await _forward(request, path, principal)


__all__ = ["DEFAULT_ENGINE_URL", "ENGINE_PREFIX", "ENGINE_URL_VAR",
           "engine_url", "router"]

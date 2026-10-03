"""The workspace API's error envelope for malformed requests.

Every governed refusal of the workspace API is `{"detail": {"error_code",
"message"}}`, and the UI reads `detail.message`. FastAPI's own request
validation answers 422 with a bare list of Pydantic field errors instead,
which the UI can only print as JSON (VAL-DEF-024). The workspace routers
use this route class so a malformed body, path or query parameter is the
same envelope: `INVALID_REQUEST`, a readable message naming the fields, and
the field errors themselves under `fields`.

The route class is per router, so nothing outside the workspace API (the
protected V4 application and its own routes) changes.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response

INVALID_REQUEST = "INVALID_REQUEST"


def _field(err: dict[str, Any]) -> dict[str, Any]:
    loc = [str(p) for p in err.get("loc", ()) if p not in ("body",)]
    return {"field": ".".join(loc) or "request",
            "message": str(err.get("msg", "invalid")),
            "type": str(err.get("type", ""))}


def envelope(exc: RequestValidationError) -> dict[str, Any]:
    fields = [_field(e) for e in exc.errors()]
    named = "; ".join(f"{f['field']}: {f['message']}" for f in fields[:5])
    more = f" (and {len(fields) - 5} more)" if len(fields) > 5 else ""
    return {"error_code": INVALID_REQUEST,
            "message": f"The request is not valid. {named}{more}".strip(),
            "fields": fields}


class GovernedRoute(APIRoute):
    """An `APIRoute` whose request-validation failures use the envelope."""

    def get_route_handler(self) -> Callable[[Request],
                                            Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def governed(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                return JSONResponse(status_code=422,
                                    content={"detail": envelope(exc)})

        return governed

"""Is this installation actually able to serve the Early Warning Score?

The failure this exists for
---------------------------
A fresh install reported itself ready while the Early Warning screen read
"The Early Warning Score domain could not be read." Everything the readiness
check looked at was true: twenty monthly partitions on disk, the domain in
`metadata/retail/catalog.json`, Data Builder synced. None of it was about the
application. The running server exposed no `/retail/ews/*` route at all and its
governed catalogue held one dataset, because the process answering requests had
been started before any of that existed and was never replaced.

So readiness is asked of the APPLICATION, not of the filesystem: the production
FastAPI app is built, its routing table is read, its Early Warning endpoints are
called, and — when something is already listening on the API port — that
server is asked the same questions, because the server a person is looking at
is the one that has to be right.

Nothing here seeds. A readiness check that fixed what it found could only ever
answer "ready".
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

#: Every Early Warning Score route the workspace needs, as (method, path).
#: The paths are the production ones, prefix included, exactly as they appear
#: in the OpenAPI document — so a rename on either side fails this list rather
#: than reaching a reader as an empty screen.
REQUIRED_EWS_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/api/v1/retail/ews/portfolio"),
    ("GET", "/api/v1/retail/ews/product/{product_code}"),
    ("GET", "/api/v1/retail/ews/customers"),
    ("GET", "/api/v1/retail/ews/customers/{customer_id}"),
    ("GET", "/api/v1/retail/ews/model"),
    ("GET", "/api/v1/retail/ews/domain"),
    ("GET", "/api/v1/retail/ews/signals"),
    ("GET", "/api/v1/retail/ews/signals/{key}"),
    ("GET", "/api/v1/retail/ews/prompts"),
    ("POST", "/api/v1/retail/ews/ask"),
)

#: The ones the workspace cannot open without. A subset, checked by CALLING
#: them rather than by finding them in a routing table.
ANSWERING_ROUTES: tuple[str, ...] = (
    "/api/v1/retail/ews/portfolio",
    "/api/v1/retail/ews/model",
    "/api/v1/retail/ews/domain",
)

#: Credentials to try, in order, when the endpoints have to be called. The API
#: is default-deny, so a probe has to sign in like anybody else.
def _candidates() -> list[tuple[str, str]]:
    from backend.services.demo_users import DEMO_PASSWORD, DEMO_USERS

    tried: list[tuple[str, str]] = []
    user = os.environ.get("RETAIL_DEMO_USER")
    password = os.environ.get("RETAIL_DEMO_PASSWORD")
    if user and password:
        tried.append((user, password))
    tried.append(("retail.demo", "RetailDemo!2026"))
    tried.extend((one["username"], one.get("password") or DEMO_PASSWORD)
                 for one in DEMO_USERS
                 if str(one.get("role", "")).upper() == "ADMIN")
    return tried


def production_app() -> Any:
    """The application `uvicorn backend.api.main:app` serves.

    Built through the same factory, so a router that is not registered here is
    not registered there either. Nothing about this is a test double.
    """
    from backend.api.main import create_app

    return create_app()


def routes_of(app: Any) -> set[tuple[str, str]]:
    """Every (method, path) the application actually serves.

    Read from the application's own OpenAPI document, which is what a person
    inspects at /openapi.json and therefore the only listing worth asserting
    on. Walking `app.routes` is not the same thing: this FastAPI keeps an
    included router as a single wrapper object in that list, with no `path` of
    its own, so a walk finds four framework routes and reports that an
    application serving six hundred paths has none of them.
    """
    found: set[tuple[str, str]] = set()
    for path, operations in (app.openapi().get("paths") or {}).items():
        for method in operations:
            found.add((str(method).upper(), str(path)))
    return found


def missing_routes(app: Any | None = None) -> list[str]:
    """Which required Early Warning routes the application does not carry."""
    served = routes_of(app if app is not None else production_app())
    return [f"{method} {path}" for method, path in REQUIRED_EWS_ROUTES
            if (method, path) not in served]


def _sign_in(client: Any) -> bool:
    for username, password in _candidates():
        try:
            answered = client.post("/api/v1/auth/login",
                                   json={"username": username,
                                         "password": password})
        except Exception:  # noqa: BLE001 - a probe never raises upward
            continue
        if answered.status_code < 400:
            return True
    return False


def check_endpoints_answer(app: Any | None = None) -> list[str]:
    """Call the Early Warning endpoints on the production app and read them.

    A route in the table that raises on the latest month is not readiness; the
    screen is as blank either way.
    """
    from fastapi.testclient import TestClient

    problems: list[str] = []
    app = app if app is not None else production_app()
    with TestClient(app) as client:
        if not _sign_in(client):
            return ["no demonstration account could sign in, so the Early "
                    "Warning endpoints cannot be proved to answer"]
        for path in ANSWERING_ROUTES:
            try:
                answered = client.get(path)
            except Exception as problem:  # noqa: BLE001
                problems.append(f"{path} raised {problem!r}")
                continue
            if answered.status_code != 200:
                problems.append(
                    f"{path} answered {answered.status_code}, not 200")
                continue
            try:
                body = answered.json()
            except Exception:  # noqa: BLE001
                problems.append(f"{path} did not answer JSON")
                continue
            if body.get("available") is False:
                problems.append(
                    f"{path} answered available=false: "
                    f"{body.get('because') or 'no reason given'}")
            if path.endswith("/portfolio") and not body.get("month"):
                problems.append(f"{path} could not read a month")
    return problems


def check_live_server(base_url: str = "") -> list[str]:
    """Ask the server that is actually listening, if one is.

    This is the check the fresh install needed. A stale process answers
    /health perfectly well while serving code from before the Early Warning
    Score existed, and every other check in this file would pass around it.
    """
    import urllib.error
    import urllib.request

    port = os.environ.get("API_PORT") or "8328"
    base = (base_url or f"http://localhost:{port}").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/openapi.json", timeout=20) as got:
            document = json.loads(got.read())
    except (urllib.error.URLError, OSError, ValueError):
        # Nothing is listening. That is not a failure: readiness is about
        # whether this installation CAN serve, and the checks above answer it.
        return []

    paths = set(document.get("paths") or {})
    absent = sorted({path for _, path in REQUIRED_EWS_ROUTES} - paths)
    if absent:
        return [
            f"the server answering {base} exposes none of "
            f"{len(absent)} required Early Warning route(s) "
            f"(first: {absent[0]}). It is running code older than this "
            "checkout — stop it and run scripts/retail_uat/restart_backend.sh"
        ]
    return []


def check_domain_and_versions() -> list[str]:
    """The domain itself: twenty months, the versions, and the runtime catalogue."""
    from backend.data_access.catalog import get_catalog
    from backend.retail import ews_model, ews_score

    problems: list[str] = []
    problems.extend(ews_score.check())

    months = ews_score.panel_months()
    if len(months) != ews_score.MONTHS_KEPT:
        problems.append(
            f"the Early Warning Score domain holds {len(months)} monthly "
            f"snapshots, not {ews_score.MONTHS_KEPT}")

    if months:
        try:
            frame = ews_score.read(months[-1])
        except Exception as problem:  # noqa: BLE001
            problems.append(f"{months[-1]} could not be read: {problem!r}")
        else:
            for column, expected in (
                    ("model_version", ews_model.EWS_MODEL_VERSION),
                    ("panel_version", ews_score.EWS_PANEL_VERSION)):
                if column not in frame.columns:
                    problems.append(f"{months[-1]} carries no {column}")
                elif str(frame[column].iloc[0]) != str(expected):
                    problems.append(
                        f"{months[-1]} carries {column} "
                        f"{frame[column].iloc[0]!r}, not {expected!r}")
            if "rulebook_version" not in frame.columns:
                problems.append(f"{months[-1]} carries no rulebook_version")
            elif not str(frame["rulebook_version"].iloc[0]).strip():
                problems.append(f"{months[-1]} carries an empty rulebook_version")

    # The catalogue the RUNNING code reads, not the file on disk. They were
    # different, and the difference was invisible.
    if ews_score.DOMAIN not in set(get_catalog().names()):
        problems.append(
            f"the runtime governed catalogue does not hold {ews_score.DOMAIN}; "
            "the backend is reading a catalogue from before it was registered")
    return problems


def check(*, live: bool = True) -> list[str]:
    """Everything above. An empty list means the workspace will open."""
    problems: list[str] = []
    problems.extend(check_domain_and_versions())

    absent = missing_routes()
    if absent:
        problems.append(
            "the production FastAPI application exposes none of these Early "
            f"Warning routes: {', '.join(absent)}")
    else:
        problems.extend(check_endpoints_answer())

    if live:
        problems.extend(check_live_server())
    return problems


def catalogue_file_datasets(metadata_dir: str | Path | None = None) -> list[dict]:
    """What the catalogue FILE holds. Kept beside the runtime check above so
    that the two can be compared rather than confused for each other."""
    from backend.config import settings

    path = Path(metadata_dir or os.environ.get("METADATA_DIR")
                or settings.metadata_dir) / "catalog.json"
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("datasets") or []


__all__ = [
    "ANSWERING_ROUTES", "REQUIRED_EWS_ROUTES", "catalogue_file_datasets",
    "check", "check_domain_and_versions", "check_endpoints_answer",
    "check_live_server", "missing_routes", "production_app", "routes_of",
]

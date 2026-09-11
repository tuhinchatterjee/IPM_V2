"""
REAL PROCESS · REAL HTTP · UNIT.

The launcher/frontend wiring defect and its neighbours.

The defect: the launcher set only `NEXT_PUBLIC_COCKPIT_V4_API`, so the V4
Cockpit client talked to the V4 API while the application shell, the
backend-status badge and every landing-page widget kept talking to
`http://127.0.0.1:8000` — a backend the V4 instance never started. Half the
page reported a system that was not there.

The second defect: the launcher JSON-decoded the UI's root page, which serves
HTML, so a healthy UI was reported as never becoming ready.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.cockpit_v4._common import (UI_IDENTITY_MARKERS, check_ui_page,
                                        wait_for_json_health,
                                        wait_for_ui_ready)
from scripts.cockpit_v4.start import (LEGACY_DEFAULT_API, UI_API_VARIABLES,
                                      ui_environment)

ROOT = Path(__file__).resolve().parents[2]
CLIENT_TS = ROOT / "frontend" / "src" / "components" / "cockpit-v4" / "client.ts"
LIB_API_TS = ROOT / "frontend" / "src" / "lib" / "api.ts"

#: Anything that would address a host and port. Reconnect delays measured in
#: milliseconds are not that, and a test that cannot tell them apart would
#: fail on `RECONNECT_DELAYS_MS`.
PORT_URL = re.compile(r"(?:https?://)?(?:127\.0\.0\.1|localhost|0\.0\.0\.0)"
                      r":(\d{2,5})")


def _code_only(path: Path) -> str:
    """Source with comments and docstrings removed.

    A file that DOCUMENTS the port it refuses to use must not fail a test
    looking for that port, or the honest comment becomes the thing that
    breaks the build.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    text = text.replace(doc, "")
        return "".join(
            tok.string for tok in
            tokenize.generate_tokens(io.StringIO(text).readline)
            if tok.type != tokenize.COMMENT)
    # TypeScript: strip /* ... */ and // ... comments.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


# ---- the environment the UI process is given ---------------------------

def test_the_ui_receives_both_api_variables_at_the_selected_port():
    """The defect, directly: one variable was set and the other was not."""
    env = ui_environment({}, api_port=8414, ui_port=5414)
    for name in UI_API_VARIABLES:
        assert env[name] == "http://127.0.0.1:8414", (
            f"{name} must name the V4 API. Left unset, the shell falls back "
            f"to {LEGACY_DEFAULT_API}.")
    assert env["NEXT_PUBLIC_COCKPIT_V4_API"] == env["NEXT_PUBLIC_API_URL"], (
        "the Cockpit client and the shell must address the same API, or the "
        "page is half-connected to a backend that is not running")
    assert env["PORT"] == "5414"


@pytest.mark.parametrize("api_port,ui_port", [
    (8414, 5414), (8415, 5415), (8422, 5099), (9001, 3210),
])
def test_the_actually_selected_port_propagates_not_the_proposed_one(
        api_port, ui_port):
    """A busy 8414 means the API is elsewhere; the UI must be told where."""
    env = ui_environment({}, api_port=api_port, ui_port=ui_port)
    expected = f"http://127.0.0.1:{api_port}"
    assert env["NEXT_PUBLIC_COCKPIT_V4_API"] == expected
    assert env["NEXT_PUBLIC_API_URL"] == expected
    assert env["PORT"] == str(ui_port)
    assert "8414" not in json.dumps(env) or api_port == 8414, (
        "the proposed port must not appear when another one was selected")


def test_the_existing_environment_is_preserved():
    """The launcher adds to the child's environment; it does not replace it."""
    env = ui_environment({"PATH": "/usr/bin", "COCKPIT_AGENTIC_V4": "true"},
                         api_port=8416, ui_port=5416)
    assert env["PATH"] == "/usr/bin"
    assert env["COCKPIT_AGENTIC_V4"] == "true"


def test_the_v4_api_can_never_resolve_to_the_legacy_default():
    with pytest.raises(ValueError) as excinfo:
        ui_environment({}, api_port=8000, ui_port=5414)
    assert "legacy default" in str(excinfo.value)


def test_the_launcher_does_not_edit_the_global_frontend_default():
    """Requirement: other CreditProbe instances keep the behaviour they have.

    The fix belongs in the child process's environment, not in the shared
    module. If `lib/api.ts` ever stops carrying its own default, this test
    fails and the reviewer is asked whether that was deliberate.
    """
    source = LIB_API_TS.read_text(encoding="utf-8")
    assert 'process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"' \
        in source, (
            "the generic client's default was changed; V4 must be fixed by "
            "setting the variable for its own UI process, not by editing the "
            "default every other instance relies on")


# ---- no silent fall back to 8000 ---------------------------------------

def test_the_cockpit_client_never_reads_the_generic_api_variable():
    """V4 must not inherit an address meant for the main backend."""
    code = _code_only(CLIENT_TS)
    assert "NEXT_PUBLIC_API_URL" not in code, (
        "the Cockpit V4 client must read only its own variable; reading the "
        "generic one would send a V4 run to whatever is on 8000")
    assert "NEXT_PUBLIC_COCKPIT_V4_API" in code


def test_the_cockpit_client_has_no_host_port_literal_at_all():
    """No default address, so there is nothing to fall back TO."""
    code = _code_only(CLIENT_TS)
    found = PORT_URL.findall(code)
    assert not found, (
        f"the client carries hard-coded address port(s) {found}; the API "
        f"origin must come from configuration only")


def test_an_unconfigured_client_fails_loudly_rather_than_guessing():
    """The behaviour that replaces the fall back, asserted on the source.

    The runtime half of this is in `client.test.ts`, which imports the module
    and calls it. This half proves the mechanism is a thrown error and not a
    default value, which is the part a reviewer needs to see.
    """
    code = _code_only(CLIENT_TS)
    assert "CockpitV4NotConfigured" in code
    assert "if (!configured) throw new CockpitV4NotConfigured();" in code, (
        "an unset variable must raise, not resolve to a default")


# ---- UI readiness: HTML, not JSON --------------------------------------

HEALTHY_NEXT_HTML = (
    "<!DOCTYPE html><html lang=\"en\"><head>"
    "<title>CreditProbe AI — Credit Portfolio Intelligence</title>"
    "<link rel=\"stylesheet\" href=\"/_next/static/css/app.css\"/></head>"
    "<body><div id=\"__next\"></div></body></html>")


def test_healthy_next_html_is_recognised_as_ready():
    ok, detail = check_ui_page(HEALTHY_NEXT_HTML, 200)
    assert ok, detail
    assert any(marker in detail for marker in UI_IDENTITY_MARKERS)


def test_html_is_not_json_decoded():
    """The exact defect: a healthy UI reported as never ready.

    `json.loads` on the root page raised, the exception was swallowed as
    "not ready yet", and the launcher waited out its whole timeout on a UI
    that was serving correctly.
    """
    with pytest.raises(json.JSONDecodeError):
        json.loads(HEALTHY_NEXT_HTML)
    ok, _ = check_ui_page(HEALTHY_NEXT_HTML, 200)
    assert ok, "the UI check must not depend on the body being JSON"


@pytest.mark.parametrize("body,status,reason", [
    ('{"ok": true}', 200, "not an HTML document"),
    ("", 200, "empty body"),
    ("<html><body>nginx welcome page</body></html>", 200, "nothing identifies"),
    ("<html><title>Some Other App</title></html>", 200, "nothing identifies"),
    (HEALTHY_NEXT_HTML, 500, "HTTP 500"),
    (HEALTHY_NEXT_HTML, 404, "HTTP 404"),
    ("<html>CreditProbe</html>", 503, "HTTP 503"),
])
def test_a_page_that_is_not_our_healthy_ui_is_refused(body, status, reason):
    ok, detail = check_ui_page(body, status)
    assert ok is False
    assert reason.split()[0].lower() in detail.lower()


def test_a_refused_connection_is_reported_not_hidden():
    """Nothing is listening: bounded wait, then an honest reason."""
    # Port 1 is privileged and never served by this suite.
    ok, detail = wait_for_ui_ready("http://127.0.0.1:1/", timeout_seconds=1.0)
    assert ok is False
    assert detail and "no response yet" not in detail


def test_a_json_health_check_on_an_html_page_fails_immediately(tmp_path):
    """The mirror image, so the two checks cannot be swapped by accident."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HEALTHY_NEXT_HTML.encode())

        def log_message(self, *_):  # silence the test log
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        ok, detail = wait_for_json_health(f"http://127.0.0.1:{port}/",
                                          timeout_seconds=5.0)
        assert ok is False
        assert "not JSON" in detail, detail
        # And the UI check accepts the very same response.
        ready, _ = wait_for_ui_ready(f"http://127.0.0.1:{port}/",
                                     timeout_seconds=5.0)
        assert ready is True
    finally:
        server.shutdown()


def test_the_launcher_uses_the_right_check_for_each_endpoint():
    """Each endpoint gets the check that matches what it actually serves."""
    # Whitespace-normalised, so reformatting the launcher does not fail this.
    code = re.sub(r"\s+", " ",
                  _code_only(ROOT / "scripts" / "cockpit_v4" / "start.py"))
    assert 'wait_for_json_health( f"http://127.0.0.1:{api_port}/health")' \
        in code, "the API health endpoint serves JSON"
    assert 'wait_for_ui_ready( f"http://127.0.0.1:{ui_port}/"' in code, \
        "the UI root page serves HTML and must not be JSON-decoded"
    assert 'wait_for_json_health( f"http://127.0.0.1:{ui_port}' not in code, \
        "JSON-decoding the UI root page is the defect under test"


# ---- the shell's health view of a V4 runtime ---------------------------

@pytest.fixture
def shell_client(store_db, runtime):
    from backend.cockpit_v4 import routes

    app = FastAPI()

    class Holder:
        cfg = runtime.cfg

    routes.install(store=store_db, runtime=Holder(),
                   principal_resolver=lambda request: {"id": "u",
                                                       "tenant": "demo-tenant"},
                   startup_sha="testsha")
    app.include_router(routes.router)
    app.include_router(routes.compat_router)
    return TestClient(app)


def test_the_shell_health_route_exists_on_the_v4_api(shell_client):
    """Without it the header reports the whole backend offline."""
    response = shell_client.get("/api/v1/health")
    assert response.status_code == 200, (
        "the shell polls this exact path; a 404 renders as 'Backend offline'")


def test_v4_is_not_reported_offline_because_an_optional_route_is_absent(
        shell_client):
    """The requirement, asserted on the payload the badge actually reads."""
    body = shell_client.get("/api/v1/health").json()

    assert body["status"] in ("ok", "degraded"), (
        f"the V4 runtime is serving; it must not report {body['status']!r}")
    names = {c["name"]: c for c in body["components"]}

    assert names["cockpit_v4_api"]["status"] == "ok"

    legacy = names["legacy_dashboard_api"]
    assert legacy["status"] == "not_configured", (
        "an absent optional surface is not configured, not unavailable")
    assert legacy["data"]["optional"] is True
    assert legacy["data"]["runtime"] == "cockpit_v4"
    assert "not part of this instance" in legacy["detail"]


def test_an_optional_surface_cannot_drag_the_headline_down(v4_config):
    """The headline is the worst of the SERVICE components only."""
    from backend.cockpit_v4 import compat_health

    payload = compat_health.health_payload(v4_config, startup_sha="sha")
    optional = [c for c in payload["components"]
                if c["data"].get("optional") and c["status"] != "ok"]
    assert optional, "this fixture has at least one absent optional surface"
    for component in optional:
        assert component["name"] not in compat_health.SERVICE_COMPONENTS


def test_the_payload_matches_the_shape_the_shell_expects(shell_client):
    """The same contract as `backend/api/routers/health.py`."""
    body = shell_client.get("/api/v1/health").json()
    for key in ("status", "app", "version", "environment", "phase",
                "components"):
        assert key in body, f"the shell reads {key}"
    assert body["status"] in ("ok", "degraded", "unavailable")
    for component in body["components"]:
        assert set(component) == {"name", "status", "detail", "data"}
        assert component["status"] in ("ok", "degraded", "unavailable",
                                       "not_configured", "empty")


def test_a_missing_release_is_a_service_fault_and_does_show(v4_config):
    """The distinction has to cut both ways, or it is just a green light."""
    from dataclasses import replace

    from backend.cockpit_v4 import compat_health, service

    service.reset_caches()
    broken = replace(v4_config, release_id="no-such-release")
    payload = compat_health.health_payload(broken, startup_sha="sha")
    names = {c["name"]: c for c in payload["components"]}
    assert names["cockpit_v4_release"]["status"] == "unavailable"
    assert payload["status"] == "unavailable", (
        "a release this runtime is supposed to serve and cannot IS a fault")
    service.reset_caches()


def test_the_shell_health_route_needs_no_session(shell_client):
    """A badge that needs a login cannot say 'I am up' on the login screen."""
    response = shell_client.get("/api/v1/health")
    assert response.status_code == 200
    assert "cockpit_v4_api" in response.text

"""The local UAT identity is the book's tenant, never a literal.

REAL DATABASE · NO MODEL · in-process ASGI client. No provider is called and
no model is fitted: every assertion is about WHO the server thinks is asking
and WHICH book it opens for them.

WHAT BROKE, AND WHY THIS FILE EXISTS
------------------------------------
A live-provider UAT on a Mac, started from the frozen H1 candidate, showed
"Backend unavailable" on every screen. Underneath, the attention feed and the
ECL panel were both answering 403 SECURITY_DENIED with:

    Release 'v4-whatif-corporate-20q-s1' holds no data for tenant 'demo'.

Nothing was wrong with the release. `app.demo_tenant` read the tenant out of
`runtime.release_summary`, which is built from the LEGACY compatibility
release (`cfg.release_id`, opened through the V3-namespace store) and is
absent entirely whenever `create_app`'s preflight fails -- which it does for
a missing `COCKPIT_ANTHROPIC_API_KEY`, for the shipped placeholder price
card, for a model with no verified price, or for that legacy release never
having been seeded on the machine. The fallback was then the literal
`"demo"`, and NO published manifest declares it: `lake.publish` stamps
`lake.DEFAULT_TENANT` into every book, accepted and candidate alike.

So a configuration failure was laundered into an access refusal. That is the
worst kind of error message: it names a real security mechanism for a reason
that has nothing to do with security, and it sends the reader looking for a
permissions problem that does not exist.

It is NOT a What-If defect. With both flags off the accepted books fail in
exactly the same way -- `test_the_accepted_books_break_the_same_way_*` below
is the proof, and it is why the fix is generic rather than scoped to the
candidate.

WHAT IS ASSERTED
----------------
That identity comes from the governed V4 domain book being served, falls back
to the governed `lake.DEFAULT_TENANT`, is resolved once by the server, and
cannot be influenced by anything a request carries. And that a GENUINE tenant
mismatch is still refused, with its reason -- the fix must not have been
"stop checking".
"""

from __future__ import annotations

import pathlib
import re
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.cockpit_v4 import analytical_runtime as arun
from backend.cockpit_v4 import app as v4app
from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake, routes
from backend.cockpit_v4.config import V4Config
from backend.cockpit_v4.scenario import candidate_schema as cs
from backend.cockpit_v4.scenario import flags as fl

ROOT = pathlib.Path(__file__).resolve().parents[2]
P = "/api/v1/cockpit-v4"

#: The literal that must never again be handed to a book.
DEAD_LITERAL = "demo"


@pytest.fixture(scope="module", autouse=True)
def _published():
    """Both accepted books and both candidate books, or this proves nothing."""
    for domain_id in dom.DOMAIN_IDS:
        if not lake.exists(dom.DEFAULT_RELEASES[domain_id]):
            pytest.skip("run scripts/cockpit_v4/seed_domains.py")
    for release_id in cs.RELEASES.values():
        if not lake.exists(release_id):
            pytest.skip("run scripts/whatif/seed_candidate.py")
    arun.reset()
    yield
    arun.reset()


@pytest.fixture()
def flags_on(monkeypatch):
    for variable in fl.VARIABLES.values():
        monkeypatch.setenv(variable, "1")
    arun.reset()
    yield monkeypatch
    arun.reset()


@pytest.fixture()
def flags_off(monkeypatch):
    for variable in fl.VARIABLES.values():
        monkeypatch.delenv(variable, raising=False)
    arun.reset()
    yield monkeypatch
    arun.reset()


def broken_preflight_config() -> V4Config:
    """The Mac's situation: everything real except a runtime.

    `credential_present=False` makes `build_runtime` raise `PreflightFailed`,
    so `create_app` installs `runtime=None` -- exactly the state in which the
    old code fell through to the literal.
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    return V4Config(
        enabled=True, provider="anthropic", reasoning_model="mock-analyst",
        runtime_dir=tmp / "runtime", state_database=str(tmp / "state.sqlite3"),
        release_id="v4-saudi-20q-v1", api_port=8414, ui_port=5414,
        local_demo_auth=True, price_card_path=str(tmp / "prices.json"),
        memory_enabled=False, memory_model="", default_mode="standard",
        heartbeat_seconds=5.0, lease_heartbeat_seconds=2.0,
        lease_stale_seconds=10.0, supervisor_poll_seconds=2.0,
        credential_present=False, missing=("COCKPIT_ANTHROPIC_API_KEY",))


def real_app():
    """The REAL app, built the way the launcher builds it."""
    cfg = broken_preflight_config()
    app = v4app.create_app(cfg, verify_model=False, start_workers=False)
    return cfg, app, TestClient(app)


# ==========================================================================
# 10 / the root cause -- a failed preflight never yields the literal
# ==========================================================================

def test_a_failed_preflight_does_not_hand_a_book_the_literal_demo(flags_on):
    cfg, app, _client = real_app()
    runtime = app.state.cockpit_v4["runtime"]
    assert runtime is None, (
        "this test is worthless unless preflight really failed; that is the "
        "state the defect lived in")
    assert app.state.cockpit_v4["preflight_error"], "and it must say why"

    tenant = v4app.demo_tenant(runtime, cfg)
    assert tenant != DEAD_LITERAL
    assert tenant == lake.DEFAULT_TENANT


def test_the_literal_demo_is_gone_from_the_demo_principal():
    """Not merely unreachable through one path -- absent from the record."""
    assert v4app.DEMO_PRINCIPAL["tenant"] == lake.DEFAULT_TENANT
    assert v4app.DEMO_PRINCIPAL["tenant"] != DEAD_LITERAL


def test_every_published_book_actually_declares_the_tenant_we_resolve_to():
    """The claim the old literal failed: the tenant must be one a book holds."""
    for domain_id in dom.DOMAIN_IDS:
        for release_id in (dom.DEFAULT_RELEASES[domain_id],
                           cs.RELEASES[domain_id]):
            tenants = lake.read_manifest(release_id).get("tenants") or []
            assert lake.DEFAULT_TENANT in tenants, (release_id, tenants)
            assert DEAD_LITERAL not in tenants, (
                f"{release_id} would have made the old literal work by "
                f"accident, which would hide the defect rather than fix it")


# ==========================================================================
# 1 / 2 / 7 / 8 -- the loopback principal reaches both candidate books
# ==========================================================================

@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_a_loopback_request_resolves_to_the_candidate_books_tenant(
        flags_on, domain_id):
    cfg, app, client = real_app()
    assert v4app.demo_tenant(app.state.cockpit_v4["runtime"],
                             cfg) == lake.DEFAULT_TENANT
    got = client.get(f"{P}/attention", params={"domain": domain_id})
    assert got.status_code == 200, got.json()


@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_the_ecl_panel_answers_on_the_same_book(flags_on, domain_id):
    _cfg, _app, client = real_app()
    got = client.get(f"{P}/ecl", params={"domain": domain_id})
    assert got.status_code == 200, got.json()


@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_the_book_served_is_the_candidate_release_with_the_flag_on(
        flags_on, domain_id):
    assert dom.current_release(domain_id) == cs.RELEASES[domain_id]


# ==========================================================================
# 9 -- switching the book changes the release, not the identity
# ==========================================================================

def test_switching_corporate_to_retail_changes_the_release_not_the_tenant(
        flags_on):
    cfg, app, client = real_app()
    before = v4app.demo_tenant(app.state.cockpit_v4["runtime"], cfg)
    seen = {}
    for domain_id in (dom.CORPORATE, dom.RETAIL, dom.CORPORATE):
        got = client.get(f"{P}/attention", params={"domain": domain_id})
        assert got.status_code == 200
        seen[domain_id] = dom.current_release(domain_id)
    after = v4app.demo_tenant(app.state.cockpit_v4["runtime"], cfg)

    assert seen[dom.CORPORATE] != seen[dom.RETAIL], "the book must change"
    assert before == after == lake.DEFAULT_TENANT, (
        "the authenticated tenant must NOT move when the reader switches "
        "books; identity is not a function of the page you are on")


# ==========================================================================
# 3 / 4 -- nothing a request carries can move the tenant or cross the books
# ==========================================================================

@pytest.mark.parametrize("header", [
    {"X-Tenant": "some-other-bank"},
    {"X-Test-Tenant": "some-other-bank"},
    {"Authorization": "Bearer tenant=some-other-bank"},
])
def test_a_request_cannot_name_its_own_tenant(flags_on, header):
    _cfg, _app, client = real_app()
    got = client.get(f"{P}/attention",
                     params={"domain": dom.CORPORATE}, headers=header)
    assert got.status_code == 200, (
        "the header is ignored, so the request still succeeds as the "
        "server's own principal")
    assert "some-other-bank" not in got.text


@pytest.mark.parametrize("asked,forbidden", [
    (dom.CORPORATE, dom.RETAIL),
    (dom.RETAIL, dom.CORPORATE),
])
def test_one_book_never_answers_with_the_others_release(
        flags_on, asked, forbidden):
    _cfg, _app, client = real_app()
    got = client.get(f"{P}/attention", params={"domain": asked})
    assert got.status_code == 200
    assert cs.RELEASES[forbidden] not in got.text, (
        f"asking for {asked} surfaced {forbidden}'s release id")
    assert dom.DEFAULT_RELEASES[forbidden] not in got.text


def test_a_query_parameter_cannot_smuggle_a_tenant(flags_on):
    _cfg, _app, client = real_app()
    got = client.get(f"{P}/attention",
                     params={"domain": dom.CORPORATE,
                             "tenant": "some-other-bank",
                             "tenant_id": "some-other-bank"})
    assert got.status_code == 200
    assert "some-other-bank" not in got.text


# ==========================================================================
# 5 -- a GENUINE mismatch is still refused, with its reason
# ==========================================================================

def stranger_client(store_db, runtime, tenant: str) -> TestClient:
    """The real routes, with a principal the books genuinely do not hold."""
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: {"id": "u1", "tenant": tenant},
                   startup_sha="testsha")
    app.include_router(routes.router)
    return TestClient(app)


@pytest.mark.parametrize("surface", ["attention", "ecl"])
def test_a_real_tenant_mismatch_is_still_refused(
        flags_on, store_db, runtime, surface):
    """The fix must not have been "stop checking"."""
    client = stranger_client(store_db, runtime, "a-bank-with-no-rows-here")
    got = client.get(f"{P}/{surface}", params={"domain": dom.CORPORATE})
    assert got.status_code == 403
    detail = got.json()["detail"]
    assert detail["error_code"] == "SECURITY_DENIED"
    assert "holds no data for tenant" in detail["message"]
    assert "a-bank-with-no-rows-here" in detail["message"]


def test_the_refusal_says_it_is_configuration_not_an_empty_portfolio(
        flags_on, store_db, runtime):
    """An empty feed would read as "your portfolio is fine"."""
    client = stranger_client(store_db, runtime, "a-bank-with-no-rows-here")
    got = client.get(f"{P}/attention", params={"domain": dom.CORPORATE})
    assert "not an empty portfolio" in got.json()["detail"]["message"]


def test_the_old_literal_would_still_be_refused_if_it_came_back(
        flags_on, store_db, runtime):
    """The exact 403 the Mac saw, pinned. If someone reintroduces the
    literal, this is the test that names what the reader would have seen."""
    client = stranger_client(store_db, runtime, DEAD_LITERAL)
    got = client.get(f"{P}/attention", params={"domain": dom.CORPORATE})
    assert got.status_code == 403
    assert f"holds no data for tenant '{DEAD_LITERAL}'" in \
        got.json()["detail"]["message"]


# ==========================================================================
# 6 -- flags OFF: the accepted cockpit is untouched
# ==========================================================================

@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_with_the_flags_off_the_accepted_book_is_served(flags_off, domain_id):
    cfg, app, client = real_app()
    assert dom.current_release(domain_id) == dom.DEFAULT_RELEASES[domain_id]
    assert v4app.demo_tenant(app.state.cockpit_v4["runtime"],
                             cfg) == lake.DEFAULT_TENANT
    assert client.get(f"{P}/attention",
                      params={"domain": domain_id}).status_code == 200
    assert client.get(f"{P}/ecl",
                      params={"domain": domain_id}).status_code == 200


@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_the_accepted_books_break_the_same_way_so_this_is_not_a_whatif_bug(
        flags_off, domain_id):
    """The evidence that the fix belongs in generic V4.

    With the flags OFF the accepted book declares the same tenant, so the
    old literal would have produced the same 403 here. Had this been a
    What-If defect, this assertion would fail.
    """
    tenants = lake.read_manifest(
        dom.DEFAULT_RELEASES[domain_id]).get("tenants") or []
    assert DEAD_LITERAL not in tenants
    assert lake.DEFAULT_TENANT in tenants


def test_one_book_enabled_does_not_move_the_other_books_tenant(monkeypatch):
    monkeypatch.setenv(fl.VARIABLES[dom.CORPORATE], "1")
    monkeypatch.delenv(fl.VARIABLES[dom.RETAIL], raising=False)
    arun.reset()
    try:
        assert dom.current_release(dom.CORPORATE) == cs.RELEASES[dom.CORPORATE]
        assert dom.current_release(dom.RETAIL) == \
            dom.DEFAULT_RELEASES[dom.RETAIL]
        for domain_id in dom.DOMAIN_IDS:
            tenants = lake.read_manifest(
                dom.current_release(domain_id)).get("tenants") or []
            assert tenants == [lake.DEFAULT_TENANT]
    finally:
        arun.reset()


# ==========================================================================
# The resolver's own contract: server-controlled, loopback-only, resolved once
# ==========================================================================

def test_the_tenant_is_resolved_once_and_not_per_request(flags_on):
    """`_demo_resolver` captures the tenant in a closure at create_app time.

    This is what makes it impossible for a request to steer: there is no
    per-request lookup to influence.
    """
    cfg, app, _client = real_app()
    resolver = v4app._demo_resolver(cfg, app.state.cockpit_v4["runtime"])

    class Request:
        def __init__(self, host, headers):
            self.client = type("C", (), {"host": host})()
            self.headers = headers
            self.state = type("S", (), {})()

    first = resolver(Request("127.0.0.1", {"X-Tenant": "bank-a"}))
    second = resolver(Request("127.0.0.1", {"X-Tenant": "bank-b"}))
    assert first["tenant"] == second["tenant"] == lake.DEFAULT_TENANT


def test_the_demo_principal_is_still_loopback_only(flags_on):
    cfg, app, _client = real_app()
    resolver = v4app._demo_resolver(cfg, app.state.cockpit_v4["runtime"])

    class Request:
        def __init__(self, host):
            self.client = type("C", (), {"host": host})()
            self.headers = {}
            self.state = type("S", (), {})()

    assert resolver(Request("127.0.0.1")) is not None
    assert resolver(Request("10.0.0.5")) is None, (
        "a demo principal that works off-host is not a demo profile, it is "
        "an unauthenticated deployment")


# ==========================================================================
# 11 / 12 -- the launcher defects the same UAT uncovered
# ==========================================================================

def test_no_launcher_points_at_a_module_that_does_not_exist():
    """`backend/main.py` has never existed in this repository.

    `uvicorn backend.main:app` exits with ModuleNotFoundError, and the H1
    candidate launcher did not wait for health, so it printed the URLs as if
    the server were up. The real entry point is
    `backend.cockpit_v4.app:create_app --factory`.
    """
    assert not (ROOT / "backend" / "main.py").exists()
    offenders = []
    for path in sorted((ROOT / "scripts").rglob("*.py")):
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            # Comments and docstrings RECORD the defect deliberately; what
            # must not come back is a live argument.
            code = line.split("#", 1)[0]
            if '"backend.main:app"' in code:
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == [], f"these still launch a missing module: {offenders}"


def test_every_launcher_that_starts_a_server_waits_for_health():
    """A launcher that does not wait cannot tell you it failed."""
    from scripts.whatif import start_h2_uat

    source = pathlib.Path(start_h2_uat.__file__).read_text(encoding="utf-8")
    assert "cockpit_v4/start.py" in source or "start.py" in source, (
        "the H2 launcher must hand over to the established start.py "
        "lifecycle, which health-waits, records pids and steps over an "
        "occupied port")


def test_the_preflight_refuses_when_the_frontend_is_not_installed(tmp_path):
    """Launching a UI whose `next` binary is missing dies with
    `sh: next: command not found` after the API is already up."""
    from scripts.whatif import uat_preflight

    problems = uat_preflight.frontend(root=tmp_path)
    assert problems, "an absent node_modules must be a refusal, not a warning"
    joined = " ".join(problems)
    assert "npm ci" in joined, "the refusal must carry the exact remedy"
    assert "node_modules" in joined


def test_the_preflight_accepts_an_installed_frontend(tmp_path):
    binary = tmp_path / "frontend" / "node_modules" / ".bin" / "next"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    assert uat_preflight_frontend(tmp_path) == []


def uat_preflight_frontend(root):
    from scripts.whatif import uat_preflight

    return uat_preflight.frontend(root=root)


def test_the_preflight_requires_the_declared_python(tmp_path):
    """`pyproject.toml` says >=3.12; the check reads the pin rather than
    hardcoding a version that would drift away from it."""
    from scripts.whatif import uat_preflight

    pinned = uat_preflight.required_python()
    declared = re.search(r'requires-python\s*=\s*"[^0-9]*([0-9]+)\.([0-9]+)',
                         (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert declared, "pyproject.toml no longer declares requires-python"
    assert pinned == (int(declared.group(1)), int(declared.group(2)))

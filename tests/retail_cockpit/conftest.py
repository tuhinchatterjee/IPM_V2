"""Fixtures for the retail Cockpit integration's own tests.

Deliberately not `tests/cockpit_v4/conftest.py`: that one is part of the
ported suite and binds every fixture to the legacy `v4-saudi-20q-v1` release,
which this deployment does not publish. Nothing here touches that release.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PORTED = ROOT / "tests" / "cockpit_v4"
if str(PORTED) not in sys.path:
    sys.path.insert(0, str(PORTED))


@pytest.fixture()
def runtime_dir(tmp_path, monkeypatch) -> Path:
    """A V4 runtime directory of this test's own."""
    directory = tmp_path / "cockpit_v4"
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("COCKPIT_V4_RUNTIME_DIR", str(directory))
    monkeypatch.delenv("COCKPIT_V4_SQL_MEMORY_LIMIT", raising=False)
    monkeypatch.delenv("COCKPIT_V4_SQL_TEMP_DIR", raising=False)
    return directory


@pytest.fixture()
def published_release() -> str:
    """The projected release, or skip: it is 400 MB and is not committed."""
    from backend.cockpit_v4 import domains as dom
    from backend.cockpit_v4 import lake

    release_id = dom.DEFAULT_RELEASES[dom.RETAIL]
    if not lake.exists(release_id):
        pytest.skip(
            f"{release_id} is not published in this runtime. Publish it with "
            f"scripts/retail_cockpit/publish_release.py")
    return release_id


@pytest.fixture()
def source_commit() -> str:
    """The frozen source, or skip when the ref has not been fetched."""
    import subprocess

    ref = "19dc143c433eff190de7d304e53b7e941c96735b"
    done = subprocess.run(["git", "cat-file", "-e", f"{ref}^{{commit}}"],
                          cwd=str(ROOT), capture_output=True)
    if done.returncode != 0:
        pytest.skip("the frozen source commit is not in this clone")
    return ref


@pytest.fixture(autouse=True)
def _no_inherited_session_settings(monkeypatch, request):
    """A test must not read the developer's own environment by accident."""
    if "runtime_dir" in request.fixturenames:
        return
    for name in ("COCKPIT_V4_SQL_MEMORY_LIMIT", "COCKPIT_V4_SQL_TEMP_DIR"):
        if name in os.environ:
            monkeypatch.delenv(name, raising=False)


# ---- driving REAL runs with a scripted analyst ------------------------
#
# MODEL MOCK, REAL EVERYTHING ELSE: the worker, the store, the event
# stream, the action state machine, the SQL validator, the grain checks,
# the evidence binding and the DuckDB session over the published
# projection are the product's own. Only `converse` is scripted, and
# `ScriptedProvider` is IMPORTED from the frozen suite rather than
# reimplemented. What is replaced is the fixture chain underneath it,
# which binds to a pre-domain release this deployment does not publish.
#
# No provider call is made by any of it.

RELEASE = "cockpitdata-r1.2.0-c1.0.0-s20260910-p7"


def _ported_harness():
    """The frozen suite's scripted-analyst helpers, loaded by PATH.

    Not `from conftest import ...`: this package has a conftest of its own
    and it shadows the ported one on `sys.path`. Loading it by file keeps
    the helpers the frozen suite wrote -- `ScriptedProvider`, `tool_call`,
    `intent`, `final` -- as the single definition of what a scripted turn
    looks like, rather than a second copy here that could drift from the
    contract it is meant to be exercising.
    """
    import importlib.util

    # Its import sets this if it is unset, and it must not repoint THIS
    # deployment's V3 namespace as a side effect of loading a test helper.
    os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE",
                          "cockpit_agentic_v3")
    spec = importlib.util.spec_from_file_location(
        "_ported_v4_harness", PORTED / "conftest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HARNESS = _ported_harness()
ScriptedProvider = _HARNESS.ScriptedProvider
ScriptedResult = _HARNESS.ScriptedResult
tool_call = _HARNESS.tool_call
intent = _HARNESS.intent
final = _HARNESS.final


@pytest.fixture(scope="session")
def chain_release() -> str:
    from backend.cockpit_v4 import lake

    if not lake.exists(RELEASE):
        pytest.skip(f"{RELEASE} is not published in this runtime")
    return RELEASE


@pytest.fixture(scope="session")
def chain_runtime(chain_release, tmp_path_factory) -> Any:
    """The engine's Runtime over the DOMAIN release, with no model."""
    from backend.cockpit_v4 import capability as cap_mod
    from backend.cockpit_v4 import catalog as cat
    from backend.cockpit_v4 import config as config_mod
    from backend.cockpit_v4 import lake
    from backend.cockpit_v4.service import Runtime
    from backend.retail_cockpit_host import bootstrap

    # SESSION-scoped, and deliberately so. Materialising this book is
    # twenty-six seconds and about 1.7 GB; rebuilding it per test would make
    # the suite unusable, and -- worse -- each rebuild calls
    # `reset_sessions()`, which closes the connection the previous test's
    # cached analytical runtime is still holding. That produced "Connection
    # already closed" on every test after the first.
    os.environ["COCKPIT_V4_RUNTIME_DIR"] = str(
        tmp_path_factory.mktemp("chain-runtime"))
    cfg = config_mod.load()
    manifest = lake.read_manifest(chain_release)
    tenant = str((manifest.get("tenants") or [lake.DEFAULT_TENANT])[0])
    cat.reset_sessions()
    catalog = cat.build(domain_id="retail", release_id=chain_release,
                        tenant_id=tenant)
    # A capability object with no provider behind it. The scripted analyst
    # never reaches the network, so nothing here authorises a paid call.
    capability = cap_mod.Capability(
        provider="anthropic", model_id="mock-analyst", sdk_version="test",
        context_tokens=200_000, max_output_tokens=128_000,
        supports_tools=True, supports_token_counting=True,
        price=cap_mod.PriceCard(input_usd_per_mtok=5.0,
                                output_usd_per_mtok=25.0,
                                cache_write_usd_per_mtok=6.25,
                                cache_read_usd_per_mtok=0.5),
        source="test fixture", verified_at="2026-09-10T00:00:00Z",
        live_verified=True)
    return Runtime(
        cfg=cfg, capability=capability, provider=None, catalog=catalog,
        coverage=None,
        release_summary=bootstrap.release_summary(chain_release, manifest))


@pytest.fixture(autouse=True)
def _fresh_analytical_runtime(request) -> Any:
    """Drop the per-book cache between chain tests, not the session itself."""
    if "drive_chain" not in request.fixturenames:
        yield
        return
    from backend.cockpit_v4 import analytical_runtime as arun

    arun.reset()
    yield
    arun.reset()


@pytest.fixture()
def chain_store(tmp_path) -> Any:
    from backend.cockpit_v4.run_store import RunStore

    return RunStore(str(tmp_path / "runs.sqlite3"))


@pytest.fixture()
def drive_chain(chain_store, chain_runtime, chain_release) -> Any:
    """One scripted conversation, end to end through the real worker."""
    from backend.cockpit_v4.worker import Worker

    def _drive(question: str, script: list[Any], *, mode: str = "standard",
               thread_id: str = "", tenant: str = "demo-tenant",
               principal: str = "u1"):
        provider = ScriptedProvider(script)
        chain_runtime.provider = provider
        # PINNED to the retail book. A thread carries the domain it was
        # opened in, and the engine refuses a run whose label and whose
        # bytes disagree -- which is the cross-domain guard doing its job,
        # not a fixture detail to work around.
        thread_id = thread_id or chain_store.create_thread(
            tenant_id=tenant, principal_id=principal, domain_id="retail",
            release_id=chain_release)
        record, _ = chain_store.accept_run(
            thread_id=thread_id, tenant_id=tenant, principal_id=principal,
            question=question, mode=mode, release_id=chain_release,
            domain_id="retail", ui_filters={}, idempotency_key="",
            body_digest="", startup_sha="testsha", deadline_at="")
        outcome = Worker(store=chain_store,
                         runtime=chain_runtime).execute(record)
        return outcome, provider, record

    return _drive


@pytest.fixture(scope="session")
def template_defaults() -> dict[str, str]:
    """The candidate template's values, resolved the way the launcher does.

    The file is SHELL, not a key-value list: every line is
    `VAR=${VAR:-default}` so an operator's export wins, which is the fix for
    the live 503 where the file silently overwrote an exported price card. A
    regex over the raw text would read the `${...}` wrapper rather than the
    value, so a shell expands it -- with the relevant names UNSET, so what
    comes back is the file's own defaults.
    """
    import json
    import os
    import subprocess

    root = Path(__file__).resolve().parents[2]
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith(("COCKPIT_", "AI_COCKPIT_", "RETAIL_COCKPIT_",
                                  "DATA_ANALYTICS", "METADATA_"))}
    script = (f'set -a; . "{root / ".env.retail-candidate.example"}"; set +a; '
              f'python3 -c "import json,os;print(json.dumps(dict(os.environ)))"')
    done = subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, cwd=str(root), env=clean)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)

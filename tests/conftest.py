"""
Shared test fixtures. The suite is deliberately DB-free: importing data_loader
bootstraps the bundled workbook into its module globals, so the ~70 aggregation
functions can be exercised without PostgreSQL. (config.py still needs to import,
but nothing here opens a database connection.)
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Prefer a real DATABASE_URL from .env when the developer has one, so the Data
# Builder and Trace suites exercise a real PostgreSQL rather than skipping. On a
# machine (or CI job) with no database, the dummy value below keeps config
# importable and those suites skip themselves — see `database_available()`.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unused:unused@localhost:5432/unused")
# NO placeholder API key. There used to be one here, so that config imported
# cleanly while everything ran offline. Now that live tests are allowed to run,
# a placeholder is worse than nothing: it makes `configured` true, so the live
# smoke tests attempt a real call with a key that cannot work and report a
# provider outage instead of skipping. With the variable genuinely unset they
# skip, and with a real key they run.

# The suite acts as a particular role by sending X-IPM-Role, which is the
# documented mechanism for a deployment that has switched signing in off. The
# product's own default is REQUIRE_LOGIN=true, and that default is exercised
# directly by tests/api/test_login_required.py, which sets it explicitly and
# asserts that an unauthenticated request is refused and that a header cannot
# be used to get past it. Forcing it off here keeps the other 900-odd tests
# testing what they are about rather than each maintaining a session.
os.environ["REQUIRE_LOGIN"] = "false"

from backend import data_loader as dl  # noqa: E402


def database_available() -> bool:
    """Whether PostgreSQL is actually reachable, not merely configured.

    Configuration alone is not enough: the fallback URL above is syntactically
    valid and points at a role that does not exist, so a suite gated on
    `settings.has_database` would try to connect and fail instead of skipping.
    """
    from backend.config import settings

    if not settings.has_database:
        return False
    try:
        from sqlalchemy import text

        from backend.db.engine import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def q():
    """The current (latest) quarter of the bundled dataset."""
    return dl.DEFAULT_QUARTER


@pytest.fixture(scope="session")
def data_loaded():
    """Sanity fixture: the bundled dataset is present."""
    assert dl.DF is not None and len(dl.DF) > 0
    assert dl.ACTIVE_SOURCE == "bundled"
    return dl


#: Tests that are ALLOWED to call a real model. Everything else runs offline.
LIVE_MARKER = "live"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: exercises a real AI provider; skipped when no key is configured")


@pytest.fixture(autouse=True)
def _offline_ai(request):
    """Offline by default; live where a test asks for it.

    An earlier version forced offline mode for the whole session. That made the
    suite deterministic and it also meant 1,300 passing tests said nothing at all
    about the configuration the product actually ships in — the live path was
    never executed, and the first person to add an API key found nine broken
    behaviours the suite had reported as fine.

    So the rule is narrower now: a test marked `live` runs against whatever
    provider is configured, and everything else is pinned offline so it cannot
    pass or fail on what a model said that afternoon.
    """
    import dataclasses
    import os

    from backend import llm
    from backend.config import settings

    if request.node.get_closest_marker(LIVE_MARKER):
        yield
        return

    previous = os.environ.get("AI_PROVIDER")
    os.environ["AI_PROVIDER"] = "offline"
    original = llm.settings
    llm.settings = dataclasses.replace(settings, ai_provider="offline")
    llm.get_provider(refresh=True)
    yield
    llm.settings = original
    if previous is None:
        os.environ.pop("AI_PROVIDER", None)
    else:
        os.environ["AI_PROVIDER"] = previous
    llm.get_provider(refresh=True)

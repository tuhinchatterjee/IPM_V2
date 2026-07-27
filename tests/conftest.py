"""
Shared test fixtures. The suite is deliberately DB-free: importing data_loader
bootstraps the bundled workbook into its module globals, so the ~70 aggregation
functions can be exercised without PostgreSQL. (config.py still needs to import,
but nothing here opens a database connection.)
"""

import os

import pytest

# config.Settings requires these to import cleanly even though the tests never
# connect to a database or an AI backend.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unused:unused@localhost:5432/unused")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

from backend import data_loader as dl  # noqa: E402


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

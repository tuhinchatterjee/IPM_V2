"""Opus360 harness tests. MODEL MOCK only: no test here makes a paid call."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", os.environ.get("COCKPIT_V4_NAMESPACE", "cockpit_v4"))
for p in (str(ROOT), str(ROOT / "scripts" / "opus360")):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(scope="session")
def harness(tmp_path_factory):
    """One in-process frozen AdvancedCockpit with a scripted (switchable) provider."""
    os.environ.pop("COCKPIT_ANTHROPIC_API_KEY", None)
    from cert.engine import CockpitHarness
    from cert.observe import Recorder

    runtime = tmp_path_factory.mktemp("opus360-runtime")
    recorder = Recorder(runtime / "calls")
    h = CockpitHarness(runtime, live=False, recorder=recorder)
    if h.preflight_error:
        pytest.skip(f"frozen runtime unavailable here: {h.preflight_error}")
    yield h
    h.close()


@pytest.fixture(scope="session")
def bank():
    import yaml
    from cert.paths import BANK_PATH

    return yaml.safe_load(BANK_PATH.read_text(encoding="utf-8"))

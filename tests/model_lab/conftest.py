"""
Fixtures for the model-lab contract tests.

Every "model" here is a labelled FIXTURE driving the REAL frozen engine
(Worker, validators, DuckDB, Finalizer, store). These tests prove the lab's
half of each contract -- observation, scheduling, evaluation, export,
access -- and nothing about any real model's quality.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")

QUESTION = "What is Stage 2 exposure by sector for the latest quarter?"
ALL_FIXTURES = ["fixture-reference", "fixture-alternate-plan",
                "fixture-wrong-scope", "fixture-repair",
                "fixture-invented-cause", "fixture-clarify",
                "fixture-no-tool"]


def _published() -> bool:
    from backend.cockpit_v4 import lake
    return lake.exists("v4-saudi-corporate-20q-v4")


@pytest.fixture(scope="session", autouse=True)
def _needs_release():
    if not _published():
        pytest.skip("corporate release not published; run "
                    "scripts/cockpit_v4/seed_domains.py")


def make_service(tmp: Path, **kw: Any):
    from backend.model_lab.service import LabService, default_config
    return LabService(default_config(tmp), **kw)


def run(svc, profiles: list[str], *, comparator: str = "fixture-reference",
        question: str = QUESTION, key: str = "", **extra: Any
        ) -> tuple[str, dict[str, Any]]:
    req = {"question": question, "profile_ids": profiles,
           "comparator_id": comparator, "group_spend_cap_usd": 0.0} | extra
    st = svc.coord.create(req, idempotency_key=key)
    st = svc.coord.wait(st["comparison_id"], timeout=300)
    cur = svc.coord.store.current_evaluation(st["comparison_id"],
                                             svc.cfg.tenant_id)
    return st["comparison_id"], cur["body"] if cur else {}


@pytest.fixture(scope="session")
def demo(tmp_path_factory):
    """One full fixture comparison, reused by the read-only tests."""
    svc = make_service(tmp_path_factory.mktemp("lab"))
    cid, ev = run(svc, ALL_FIXTURES + ["opus-frozen", "qwen3.5-9b"])
    return svc, cid, ev


def child(ev: dict[str, Any], profile_id: str) -> dict[str, Any]:
    return next(k for k in ev["children"] if k["profile_id"] == profile_id)

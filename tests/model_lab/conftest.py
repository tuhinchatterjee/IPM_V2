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


#: The protected-manifest check this checkout supports: Git blobs in a
#: repository, recorded SHA-256 in a deployment bundle (no .git).
MANIFEST_CHECK = "--check" if (ROOT / ".git").exists() else "--check-bundle"


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


def as_opus_profiles(fixture_id: str = "fixture-reference") -> dict:
    """The registry with a labelled FIXTURE registered as `opus-frozen`, so
    a saved "Opus" reference can be built offline. Never a real Opus."""
    from backend.model_lab import registry
    raw = registry.load_profiles()[fixture_id].raw | {
        "profile_id": "opus-frozen", "display_name": "Saved Opus (fixture)"}
    return registry.load_profiles() | {
        "opus-frozen": registry._validate(raw, Path("opus-frozen.json"))}


def build_fixture_reference_set(runtime: Path, set_dir: Path,
                                qids: list[str], **kw: Any) -> int:
    """Grant a cap that covers exactly these questions, then build their
    saved references with the fixture standing in for Opus."""
    import json

    from backend.model_lab.coordinator import PER_CHILD_RESERVE_USD
    sys.path.insert(0, str(ROOT / "scripts" / "model_lab"))
    import opus_reference_set

    runtime.mkdir(parents=True, exist_ok=True)
    ap = runtime / "approvals.json"
    data = json.loads(ap.read_text()) if ap.exists() else {}
    data["opus_spend"] = {"granted_at": 1.0, "granted_by": "test",
                          "cap_usd": PER_CHILD_RESERVE_USD * len(qids)}
    ap.write_text(json.dumps(data))
    svc = make_service(runtime, profiles=as_opus_profiles())
    argv = ["build", "--runtime-dir", str(runtime), "--set-dir",
            str(set_dir), "--confirm-paid-opus-calls",
            "--allow-fixture-reference"]
    for q in qids:
        argv += ["--question", q]
    return opus_reference_set.main(argv, svc=svc, **kw)

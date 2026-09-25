"""
`create_lab_app()` = the frozen `create_app()` plus the lab router.

Composition, not modification: the frozen app is built exactly as its own
launcher builds it, and one additional router is included. The lab's
comparison children run in a lab-owned RunStore that the frozen app's worker
never reads, so normal single-model chat and lab comparisons cannot claim
each other's runs.

    python -m uvicorn backend.model_lab.app:create_lab_app --factory

Environment (set by scripts/model_lab/start.py):
    MODEL_LAB_RUNTIME_DIR   lab-owned state directory (required)
    MODEL_LAB_FIXTURE_APP   "true": serve the frozen app on the fixture
                            provider (no key, no model) -- demonstration only
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")


def _guard_runtime_dir(path: Path) -> Path:
    """Reject escaped or shared state roots before anything starts (I06)."""
    root = Path(__file__).resolve().parents[2]
    real = path.expanduser().resolve()
    if real.is_symlink():
        raise RuntimeError(f"{path} is a symlink")
    forbidden = [root / "data", root / "metadata", root / "backend",
                 root / "frontend", root / "config"]
    for f in forbidden:
        if real == f.resolve() or f.resolve() in real.parents:
            raise RuntimeError(f"lab runtime {real} is inside protected "
                               f"{f}")
    for var in ("COCKPIT_V4_STATE_DATABASE",):
        v = os.environ.get(var, "")
        if v and "://" in v:
            raise RuntimeError(f"{var} must be a local path, not a URL")
    return real


def _fixture_chat_env(runtime_dir: Path) -> None:
    """A lab-owned price card for the demonstration chat's mock model, so
    the frozen loader accepts it without a key. Zero prices, labelled."""
    import json
    card = runtime_dir / "fixture_price_card.json"
    card.write_text(json.dumps({"provider": "anthropic", "models": {
        "mock-analyst": {"provider": "anthropic", "context_tokens": 200000,
                         "max_output_tokens": 16384, "supports_tools": True,
                         "supports_token_counting": False,
                         "source": "model lab fixture chat (no inference)",
                         "verified_at": "2026-09-25",
                         "price": {"input_usd_per_mtok": 0.0,
                                   "output_usd_per_mtok": 0.0,
                                   "cache_write_usd_per_mtok": 0.0,
                                   "cache_read_usd_per_mtok": 0.0}}}}))
    os.environ["AI_COCKPIT_REASONING_MODEL"] = "mock-analyst"
    os.environ["COCKPIT_V4_PRICE_CARD"] = str(card)
    os.environ.setdefault("COCKPIT_AGENTIC_V4", "true")
    os.environ.setdefault("COCKPIT_V4_LOCAL_DEMO_AUTH", "true")


def create_lab_app(*, service=None, frozen_provider: Any = None) -> Any:
    from backend.cockpit_v4.app import create_app
    from backend.model_lab import api
    from backend.model_lab.service import LabService, default_config

    runtime_dir = _guard_runtime_dir(Path(os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", "artifacts/model_comparison/runtime")))
    runtime_dir.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    if os.environ.get("MODEL_LAB_FIXTURE_APP", "").lower() == "true" or \
            frozen_provider is not None:
        # Demonstration only: the frozen single-model chat runs on the
        # reference fixture so the page works with no key. Labelled in /info.
        from backend.model_lab.adapters.fixture import FixtureProvider
        kwargs = {"provider": frozen_provider or FixtureProvider(
            "reference", "mock-analyst"), "verify_model": False}
    if kwargs:
        _fixture_chat_env(runtime_dir)
    app = create_app(**kwargs)
    if service is None:
        from backend.cockpit_v4.app import demo_tenant
        st = app.state.cockpit_v4
        cfg = default_config(runtime_dir)
        # Owner scope = the tenant the frozen principal resolver will hand
        # this browser, so lab visibility follows the same identity.
        cfg.tenant_id = demo_tenant(st["runtime"], st["config"])
        service = LabService(cfg)
    svc = service
    api.install(svc)
    app.include_router(api.router)
    app.state.model_lab = {"service": svc, "runtime_dir": str(runtime_dir),
                           "fixture_chat": bool(kwargs)}
    return app

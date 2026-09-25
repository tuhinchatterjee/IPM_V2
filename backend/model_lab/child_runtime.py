"""
Build one child's frozen `Runtime`, pinned to one profile.

This is the seam the frozen code already exposes (`live_uat.build_runtime`,
the `drive` test fixture): a `Runtime` carries the provider and capability a
`Worker` reads for each run. Nothing global is mutated; two children in the
same process hold two different runtimes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from backend.model_lab.registry import Profile

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")


def capability_for(profile: Profile, probe: dict[str, Any] | None = None
                   ) -> Any:
    from backend.cockpit_v4.capability import Capability, PriceCard
    from backend.cockpit_v4.model_capabilities import ModelTraits

    raw = profile.raw
    if profile.route == "anthropic":
        # The frozen verified price card, read by the frozen loader, which
        # fails closed on a placeholder or a missing model entry. Traits come
        # from the frozen registry (claude-opus-5 -> forced tools + effort).
        from backend.cockpit_v4.capability import load_price_card
        return load_price_card(ROOT / raw["price_card"],
                               model_id=profile.requested_model,
                               provider="anthropic")
    # Controls come from the PROBE when one ran: a declared control that was
    # never demonstrated is not sent as if it were supported.
    ctl = dict(raw.get("supported_controls") or {})
    if probe and probe.get("controls"):
        ctl.update({k: v for k, v in probe["controls"].items()
                    if v is not None})
    price = raw.get("price") or {}
    traits = ModelTraits(
        forced_tool_use=bool(ctl.get("forced_tool_use")),
        named_tool_forcing=bool(ctl.get("named_tool_forcing")),
        effort_control=bool(ctl.get("effort_control")),
        single_tool_per_turn=True, source=f"lab-profile:{profile.profile_id}")
    return Capability(
        provider="anthropic",   # the frozen engine's wire dialect, see OG-03
        model_id=profile.requested_model,
        sdk_version=profile.route,
        context_tokens=int(raw.get("context_tokens") or 32_768),
        max_output_tokens=int(raw.get("max_output_tokens") or 8192),
        supports_tools=True,
        supports_token_counting=bool(ctl.get("token_counting")),
        price=PriceCard(float(price.get("input_usd_per_mtok", 0.0)),
                        float(price.get("output_usd_per_mtok", 0.0)),
                        float(price.get("cache_write_usd_per_mtok", 0.0)),
                        float(price.get("cache_read_usd_per_mtok", 0.0))),
        source=str(price.get("source") or "lab profile"),
        verified_at=str(price.get("verified_at") or ""),
        live_verified=False, traits=traits)


def runtime_for(profile: Profile, provider: Any, *, domain: str,
                runtime_dir: Path, state_db: Path,
                probe: dict[str, Any] | None = None) -> Any:
    from backend.cockpit_v4 import analytical_runtime as arun
    from backend.cockpit_v4 import config as config_mod
    from backend.cockpit_v4.service import Runtime

    book = arun.for_domain(domain)
    cap = capability_for(profile, probe)
    cfg = config_mod.V4Config(
        enabled=True, provider="anthropic", reasoning_model=cap.model_id,
        runtime_dir=runtime_dir, state_database=str(state_db),
        release_id=book.release_id, api_port=8424, ui_port=5424,
        local_demo_auth=True,
        price_card_path=str(ROOT / (profile.raw.get("price_card") or
                                    "profiles")),
        memory_enabled=False, memory_model="", default_mode="standard",
        heartbeat_seconds=5.0, lease_heartbeat_seconds=2.0,
        lease_stale_seconds=10.0, supervisor_poll_seconds=2.0,
        credential_present=True, missing=())
    return Runtime(cfg=cfg, capability=cap, provider=provider,
                   catalog=book.catalog, coverage=None,
                   release_summary=book.release_summary())


def snapshot_identity(domain: str) -> dict[str, Any]:
    """The data snapshot a comparison is pinned to (read-only)."""
    import hashlib

    from backend.cockpit_v4 import analytical_runtime as arun
    from backend.cockpit_v4 import contracts
    from backend.cockpit_v4 import domain_resolver as resolver

    scope = resolver.scope_for(domain)
    book = arun.for_domain(domain)
    tools = contracts.provider_tools(catalog=book.catalog)

    def h(obj: Any) -> str:
        return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str)
                              .encode()).hexdigest()

    policy_files = [ROOT / "backend/cockpit_v4/prompts/analyst.md",
                    ROOT / "backend/cockpit_v4/credit_policy.json"]
    policy = hashlib.sha256(b"".join(p.read_bytes() for p in policy_files)
                            ).hexdigest()
    summary = book.release_summary()
    return {"domain": domain, "release_id": scope.release_id,
            "release_fingerprint": scope.release_fingerprint,
            "data_snapshot_id": f"{scope.release_id}@"
                                f"{scope.release_fingerprint}",
            "catalogue_hash": h(summary), "tools_hash": h(tools),
            "policy_hash": policy,
            "periods": summary.get("periods") or summary.get("quarters")}

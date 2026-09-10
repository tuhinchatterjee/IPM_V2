"""
Assembly and preflight: what must be true before a run may cost anything.

Order matters here. Credential, model, capability and price are checked
BEFORE the release is opened, and the release is opened before any context is
built, and context is built before the first generation is dispatched. A run
that fails at any of those stages fails with the check's own name -- so an
operator is sent to the setting that is actually wrong, rather than to a
generic provider error three stages later.

Nothing in this module answers a question. If a check fails, the run stops
with that reason; there is no deterministic substitute and no V3 fallback.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any

from backend.cockpit_agentic import calendar as v3_calendar
from backend.cockpit_agentic import catalog as v3_catalog
from backend.cockpit_agentic import scope as v3_scope
from backend.cockpit_agentic import store as v3_store
from backend.cockpit_v4 import DOMAIN
from backend.cockpit_v4 import capability as cap_mod
from backend.cockpit_v4 import config as config_mod
from backend.cockpit_v4 import states as st
from backend.cockpit_v4.config import V4Config, limits_for

logger = logging.getLogger(__name__)

_CATALOG_CACHE: dict[str, Any] = {}
_COVERAGE_CACHE: dict[str, Any] = {}
_LOCK = threading.RLock()


class PreflightFailed(RuntimeError):
    """A named check failed before anything could cost money."""

    def __init__(self, code: str, message: str, *,
                 variables: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.variables = variables


@dataclass
class Runtime:
    """Everything one run needs, assembled once and verified."""

    cfg: V4Config
    capability: cap_mod.Capability
    provider: Any
    catalog: Any
    coverage: Any
    release_summary: dict[str, Any]

    def scope_for(self, principal: dict[str, Any]) -> Any:
        """The effective read scope, derived server-side from the principal.

        Reuses V3's `for_principal`, so the intersection of the Cockpit's
        capability scope with this principal's grants is computed in exactly
        one place for both builds. Nothing in a request or a model response
        can widen it.
        """
        return v3_scope.for_principal(_Principal(principal),
                                      dataset_release_id=self.cfg.release_id)


class _Principal:
    """Adapts V4's principal dict to the attribute shape V3 scope expects."""

    def __init__(self, principal: dict[str, Any]) -> None:
        self.tenant_id = str(principal.get("tenant") or "")
        self.id = str(principal.get("id") or "")
        self.cockpit_relations = tuple(principal.get("relations") or ())


def credential() -> str:
    """The one Cockpit credential. No fallback, ever."""
    value = os.environ.get(config_mod.CREDENTIAL_VAR, "").strip()
    if not value:
        raise PreflightFailed(
            st.PROVIDER_CREDENTIAL_MISSING,
            f"{config_mod.CREDENTIAL_VAR} is not set in this runtime. The "
            f"Cockpit does not fall back to another module's credential.",
            variables=(config_mod.CREDENTIAL_VAR,))
    return value


def credential_status() -> str:
    return ("PRESENT" if os.environ.get(config_mod.CREDENTIAL_VAR, "").strip()
            else "MISSING")


def resolve_provider(cfg: V4Config) -> Any:
    """Build the provider client bound to the Cockpit's own key."""
    key = credential()
    if cfg.provider != "anthropic":
        raise PreflightFailed(
            st.MODEL_CONFIGURATION_MISSING,
            f"AI_PROVIDER={cfg.provider!r} is not supported by this build. "
            f"The installed adapter is 'anthropic'.",
            variables=("AI_PROVIDER",))
    from backend.llm.anthropic_provider import AnthropicProvider

    try:
        return AnthropicProvider(api_key=key)
    except TypeError:
        # Older adapter signature: construct then bind the key explicitly,
        # rather than letting the SDK pick up an ambient ANTHROPIC_API_KEY.
        provider = AnthropicProvider()
        setattr(provider, "api_key", key)
        return provider


def load_capability(cfg: V4Config, provider: Any = None,
                    *, verify: bool = True) -> cap_mod.Capability:
    if not cfg.reasoning_model:
        raise PreflightFailed(
            st.MODEL_CONFIGURATION_MISSING,
            f"{config_mod.REASONING_MODEL_VAR} is not set. V4 does not "
            f"default a model, inherit AI_MODEL or resolve 'latest'.",
            variables=(config_mod.REASONING_MODEL_VAR,))
    if not cfg.price_card_path:
        raise PreflightFailed(
            st.CAPABILITY_UNVERIFIED,
            "COCKPIT_V4_PRICE_CARD is not set, so no paid request can be "
            "reserved against a verified price.",
            variables=("COCKPIT_V4_PRICE_CARD",))
    try:
        capability = cap_mod.load_price_card(
            cfg.price_card_path, model_id=cfg.reasoning_model,
            provider=cfg.provider)
    except cap_mod.CapabilityUnverified as exc:
        raise PreflightFailed(st.CAPABILITY_UNVERIFIED, str(exc)) from exc
    if verify and provider is not None:
        try:
            capability = cap_mod.verify_live(capability, provider)
        except cap_mod.CapabilityUnverified as exc:
            raise PreflightFailed(st.CAPABILITY_UNVERIFIED, str(exc)) from exc
    return capability


def load_release(cfg: V4Config) -> tuple[Any, Any, dict[str, Any]]:
    """Open the pinned release READ-ONLY and validate its manifest.

    A release that has gone away is reported as gone. Substituting the latest
    one would answer a question about one book with another book's numbers,
    and nothing in the answer would say so.
    """
    if not cfg.release_id:
        raise PreflightFailed(
            st.DATA_UNAVAILABLE,
            "COCKPIT_V4_RELEASE_ID is not set, so no authorized release is "
            "pinned.", variables=("COCKPIT_V4_RELEASE_ID",))
    with _LOCK:
        cached = _CATALOG_CACHE.get(cfg.release_id)
        if cached is not None:
            return cached[0], _COVERAGE_CACHE.get(cfg.release_id), cached[1]
    try:
        manifest = v3_store.read_manifest(cfg.release_id)
        calendar = v3_store.load_calendar(cfg.release_id)
    except v3_store.ReleaseNotFound as exc:
        raise PreflightFailed(
            st.DATA_UNAVAILABLE,
            f"{exc} Nothing was substituted for it.") from exc

    summary = {"dataset_release_id": cfg.release_id, "domain_id": DOMAIN,
               **{k: manifest.get(k) for k in
                  ("origin", "data_version", "not_client_data",
                   "reporting_currency", "amount_scale", "tenants")
                  if k in manifest}}
    catalog = v3_catalog.build(
        dataset_release_id=cfg.release_id, calendar=calendar,
        tenant_id=str((manifest.get("tenants") or [""])[0]),
        reporting_currency=str(manifest.get("reporting_currency") or "INR"),
        amount_scale=str(manifest.get("amount_scale") or "crore"))
    with _LOCK:
        _CATALOG_CACHE[cfg.release_id] = (catalog, summary)
    return catalog, _COVERAGE_CACHE.get(cfg.release_id), summary


def coverage_for(cfg: V4Config) -> Any:
    """The measured coverage profile, computed once per release.

    Missingness comes from here, not from ten preview rows.
    """
    with _LOCK:
        cached = _COVERAGE_CACHE.get(cfg.release_id)
    if cached is not None:
        return cached
    try:
        from backend.cockpit_agentic import generate as v3_generate
        from backend.cockpit_agentic import profile as v3_profile

        manifest = v3_store.read_manifest(cfg.release_id)
        calendar = v3_store.load_calendar(cfg.release_id)
        frames = {relation: v3_store.read_relation(cfg.release_id, relation)
                  for relation in manifest["relations"]}
        release = v3_generate.Release(dataset_release_id=cfg.release_id,
                                      calendar=calendar, frames=frames)
        profile = v3_profile.profile_release(release)
    except Exception as exc:  # noqa: BLE001
        logger.info("V4 coverage profile unavailable for %s: %s",
                    cfg.release_id, exc)
        return None
    with _LOCK:
        _COVERAGE_CACHE[cfg.release_id] = profile
    return profile


def build_runtime(cfg: V4Config | None = None, *, provider: Any = None,
                  verify_model: bool = True) -> Runtime:
    """Run every preflight check, in the order an operator should read them."""
    cfg = cfg or config_mod.load()
    if not cfg.enabled:
        raise PreflightFailed(
            st.MODEL_CONFIGURATION_MISSING,
            "COCKPIT_AGENTIC_V4 is not enabled in this runtime.",
            variables=("COCKPIT_AGENTIC_V4",))
    if provider is None:
        provider = resolve_provider(cfg)
    capability = load_capability(cfg, provider, verify=verify_model)
    catalog, _, summary = load_release(cfg)
    coverage = coverage_for(cfg)
    return Runtime(cfg=cfg, capability=capability, provider=provider,
                   catalog=catalog, coverage=coverage,
                   release_summary=summary)


def diagnostics(cfg: V4Config | None = None, *,
                startup_sha: str = "") -> dict[str, Any]:
    """Per-capability readiness. Three separate checks, not one green badge.

    `ready_for_product_help` needs a credential, a model and a verified
    price. `ready_for_sql_analysis` additionally needs the release to open.
    `ready_for_python_analysis` additionally needs an isolated runner. A build
    with no Python jail is honest about it rather than showing all-green and
    failing on the first Python step.
    """
    cfg = cfg or config_mod.load()
    report: dict[str, Any] = {
        "route": "cockpit_v4", "enabled": cfg.enabled,
        "startup_sha": startup_sha,
        "credential": credential_status(),
        "settings": cfg.to_dict(),
        "checks": {},
    }
    checks = report["checks"]

    checks["credential"] = {"ok": credential_status() == "PRESENT",
                            "variable": config_mod.CREDENTIAL_VAR}
    try:
        capability = load_capability(cfg, None, verify=False)
        checks["model_and_price"] = {"ok": True,
                                     "capability": capability.to_dict()}
    except PreflightFailed as exc:
        checks["model_and_price"] = {"ok": False, "reason": str(exc),
                                     "code": exc.code}
    try:
        catalog, _, summary = load_release(cfg)
        checks["release"] = {
            "ok": True, "release": summary,
            "relations": len(catalog.relations()),
            "quarters": len(getattr(catalog.calendar, "slots", ()) or ())}
    except PreflightFailed as exc:
        checks["release"] = {"ok": False, "reason": str(exc), "code": exc.code}

    from backend.cockpit_v4 import pyrunner

    runner = pyrunner.probe()
    checks["python_runner"] = runner

    try:
        from backend.cockpit_v4.run_store import RunStore

        RunStore(cfg.state_database)
        checks["state_database"] = {
            "ok": True, "path": config_mod.redact_database_url(
                cfg.state_database)}
    except Exception as exc:  # noqa: BLE001
        checks["state_database"] = {"ok": False, "reason": str(exc)[:200]}

    base_ok = (checks["credential"]["ok"]
               and checks["model_and_price"].get("ok")
               and checks["state_database"].get("ok") and cfg.enabled)
    report["ready_for_product_help"] = bool(base_ok)
    report["ready_for_sql_analysis"] = bool(
        base_ok and checks["release"].get("ok"))
    report["ready_for_python_analysis"] = bool(
        base_ok and checks["release"].get("ok") and runner.get("available"))
    report["limits"] = {
        "standard": config_mod.STANDARD_LIMITS.__dict__,
        "deep": config_mod.DEEP_LIMITS.__dict__,
    }
    return report


def reset_caches() -> None:
    with _LOCK:
        _CATALOG_CACHE.clear()
        _COVERAGE_CACHE.clear()


__all__ = ["PreflightFailed", "Runtime", "build_runtime", "coverage_for",
           "credential", "credential_status", "diagnostics", "limits_for",
           "load_capability", "load_release", "reset_caches",
           "resolve_provider"]

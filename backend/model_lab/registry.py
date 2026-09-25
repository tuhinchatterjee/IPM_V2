"""
Model registry: pinned operational identities and honest readiness.

A profile is data (`profiles/*.json`), never code, and never something model
or user content can change at run time. Readiness is recomputed from what is
actually present -- credentials by NAME only, approvals, endpoint probes --
and a profile is never promoted because it is installable.

Status is independent of model intelligence: BLOCKED_RESOURCE says the host
could not carry the model, not that the model reasoned badly.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = ROOT / "profiles"

DISCOVERED = "DISCOVERED"
NEEDS_APPROVAL = "NEEDS_APPROVAL"
NOT_INSTALLED = "NOT_INSTALLED"
PROBING = "PROBING"
READY_E2E = "READY_E2E"
READY_DIAGNOSTIC_ONLY = "READY_DIAGNOSTIC_ONLY"
INCOMPATIBLE_PROTOCOL = "INCOMPATIBLE_PROTOCOL"
BLOCKED_RESOURCE = "BLOCKED_RESOURCE"
DISABLED = "DISABLED"
STATUSES = (DISCOVERED, NEEDS_APPROVAL, NOT_INSTALLED, PROBING, READY_E2E,
            READY_DIAGNOSTIC_ONLY, INCOMPATIBLE_PROTOCOL, BLOCKED_RESOURCE,
            DISABLED)
RUNNABLE = (READY_E2E,)

ROLE_COMPARATOR = "comparator"
ROLE_CANDIDATE = "candidate"
ROLE_FIXTURE = "fixture"

#: Controls the frozen engine relies on. A route that cannot prove the
#: mandatory ones is not READY_E2E.
MANDATORY_CONTROLS = ("tools", "forced_tool_use", "tool_result_roundtrip",
                      "stop_reason_mapping")


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    profile_id: str
    display_name: str
    role: str
    family: str
    registry_id: str
    route: str               # anthropic | openai_compat | ollama_native | fixture
    declared_status: str
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def requested_model(self) -> str:
        return str(self.raw.get("endpoint", {}).get("model") or
                   self.registry_id)

    @property
    def is_fixture(self) -> bool:
        return self.role == ROLE_FIXTURE

    def digest(self) -> str:
        """Pins the entire profile at child creation (A01)."""
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True)
                              .encode()).hexdigest()

    def public(self) -> dict[str, Any]:
        """What the browser may see. Endpoint secrets are references only."""
        r = dict(self.raw)
        ep = dict(r.get("endpoint") or {})
        ep.pop("api_key", None)
        r["endpoint"] = ep
        r["profile_digest"] = self.digest()
        return r


def _validate(raw: dict[str, Any], path: Path) -> Profile:
    need = ("profile_id", "display_name", "role", "family", "registry_id",
            "route", "status")
    missing = [k for k in need if not raw.get(k)]
    if missing:
        raise RegistryError(f"{path.name}: missing {missing}")
    if raw["status"] not in STATUSES:
        raise RegistryError(f"{path.name}: unknown status {raw['status']}")
    if raw["role"] not in (ROLE_COMPARATOR, ROLE_CANDIDATE, ROLE_FIXTURE):
        raise RegistryError(f"{path.name}: unknown role {raw['role']}")
    ep = raw.get("endpoint") or {}
    if "api_key" in ep:
        raise RegistryError(f"{path.name}: a profile may name a credential "
                            f"variable (api_key_env), never hold a key")
    return Profile(profile_id=raw["profile_id"],
                   display_name=raw["display_name"], role=raw["role"],
                   family=raw["family"], registry_id=raw["registry_id"],
                   route=raw["route"], declared_status=raw["status"], raw=raw)


def load_profiles(directory: Path | None = None) -> dict[str, Profile]:
    directory = directory or PROFILE_DIR
    out: dict[str, Profile] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_") or path.name == "presets.json":
            continue
        p = _validate(json.loads(path.read_text()), path)
        if p.profile_id in out:
            raise RegistryError(f"duplicate profile id {p.profile_id}")
        out[p.profile_id] = p
    return out


def load_presets(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    path = (directory or PROFILE_DIR) / "presets.json"
    if not path.exists():
        return {}
    return {p["preset_id"]: p for p in json.loads(path.read_text())["presets"]}


# ---- readiness -----------------------------------------------------------

@dataclass
class Readiness:
    profile_id: str
    status: str
    reasons: list[str]
    recovery: str
    checks: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"profile_id": self.profile_id, "status": self.status,
                "reasons": self.reasons, "recovery": self.recovery,
                "checks": self.checks}


def readiness(profile: Profile, *, approvals: dict[str, Any],
              probes: dict[str, Any] | None = None,
              env: dict[str, str] | None = None) -> Readiness:
    """Effective status. Never more optimistic than the declared status."""
    env = os.environ if env is None else env
    raw = profile.raw
    checks: dict[str, Any] = {}
    reasons: list[str] = []
    declared = profile.declared_status

    if declared in (DISABLED, DISCOVERED, INCOMPATIBLE_PROTOCOL,
                    BLOCKED_RESOURCE):
        return Readiness(profile.profile_id, declared,
                         [raw.get("status_reason") or declared],
                         raw.get("recovery") or "", checks)

    if profile.route == "fixture":
        return Readiness(profile.profile_id, declared,
                         ["deterministic demonstration fixture; not a model"],
                         "", {"fixture": True})

    ep = raw.get("endpoint") or {}
    key_env = ep.get("api_key_env")
    if key_env:
        present = bool(env.get(key_env))
        checks["credential"] = {"variable": key_env,
                                "present": present}   # never the value
        if not present:
            reasons.append(f"credential {key_env} is not set in the lab "
                           f"server's environment")
    approval_key = raw.get("approval_required")
    if approval_key:
        grant = (approvals or {}).get(approval_key)
        checks["approval"] = {"key": approval_key, "granted": bool(grant),
                              "cap_usd": (grant or {}).get("cap_usd")}
        if not grant:
            reasons.append(f"approval '{approval_key}' has not been granted "
                           f"(scripts/model_lab/approve.py)")
    probes = probes or {}
    probe = probes.get(profile.profile_id)
    if raw.get("requires_probe"):
        checks["probe"] = probe or {"state": "NOT_RUN"}
        if not probe:
            reasons.append("capability probe has not run on this host")
        elif not probe.get("runtime_reachable"):
            return Readiness(profile.profile_id, NOT_INSTALLED,
                             [f"runtime not reachable: "
                              f"{probe.get('error') or 'no response'}"],
                             raw.get("recovery") or "", checks)
        elif not probe.get("model_present"):
            return Readiness(profile.profile_id, NOT_INSTALLED,
                             [f"model {profile.requested_model} is not "
                              f"present in the runtime"],
                             raw.get("recovery") or "", checks)
        elif probe.get("resolved_model") and \
                probe["resolved_model"] != profile.requested_model:
            return Readiness(profile.profile_id, INCOMPATIBLE_PROTOCOL,
                             [f"requested {profile.requested_model} but the "
                              f"server resolved {probe['resolved_model']}"],
                             "pin the exact artifact tag/digest", checks)
        elif not all(probe.get("controls", {}).get(c) for c in
                     MANDATORY_CONTROLS):
            failed = [c for c in MANDATORY_CONTROLS
                      if not probe.get("controls", {}).get(c)]
            return Readiness(profile.profile_id, INCOMPATIBLE_PROTOCOL,
                             [f"mandatory controls not proven: {failed}"],
                             "try another runtime/parser route", checks)
    if reasons:
        if approval_key and not (approvals or {}).get(approval_key):
            status = NEEDS_APPROVAL
        elif key_env and not env.get(key_env):
            status = NEEDS_APPROVAL
        else:
            status = NOT_INSTALLED
        return Readiness(profile.profile_id, status, reasons,
                         raw.get("recovery") or "", checks)
    # Everything required was proven. A probe-qualified candidate becomes
    # READY_E2E only here, from evidence -- never from its declared status.
    if raw.get("requires_probe"):
        modes = raw.get("allowed_modes") or []
        status = (READY_E2E if "E2E_BASELINE" in modes
                  else READY_DIAGNOSTIC_ONLY)
        return Readiness(profile.profile_id, status, ["probe passed"], "",
                         checks)
    return Readiness(profile.profile_id, declared, ["ready"], "", checks)


# ---- approvals (server-side file, written only by an operator CLI) --------

def approvals_path(runtime_dir: Path) -> Path:
    return runtime_dir / "approvals.json"


def load_approvals(runtime_dir: Path) -> dict[str, Any]:
    p = approvals_path(runtime_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}

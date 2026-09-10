"""
The V4 configuration contract, read from the environment and validated.

Why V4 reads the environment itself rather than extending `backend.config`
--------------------------------------------------------------------------
`backend/config.py` is shared by every module in the product. A V4 setting
added there is a setting every other runtime parses on startup, and the whole
point of this build is that V4 cannot disturb V3, EWS, What-if or anything
else that is running. So V4 owns its own names, all prefixed `COCKPIT_V4_`,
and reads them here.

Nothing in this module invents a value that would cost money or grant access.
Paths and unused ports get documented safe defaults, because a wrong path is
an inconvenience. A model id, a price, a key, a tenant, a release id and a
permission have NO default at all: a runtime that cannot say which model it
pays for does not get to guess, and `validate()` reports it as missing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.cockpit_v4 import DEEP, MODES, STANDARD

#: The only credential V4 will use. There is deliberately no fallback to
#: ANTHROPIC_API_KEY, to an SDK default, or to any other module's key: a
#: Cockpit that can quietly bill someone else's account is not isolated.
CREDENTIAL_VAR = "COCKPIT_ANTHROPIC_API_KEY"

#: The analyst model. Reused from V3's name because it means the same thing.
#: `AI_COCKPIT_PREPROCESS_MODEL` is deliberately NOT read: V4 has no
#: mandatory preprocessing call for it to configure.
REASONING_MODEL_VAR = "AI_COCKPIT_REASONING_MODEL"

DEFAULT_API_PORT = 8414
DEFAULT_UI_PORT = 5414

#: Directory names V4 must never write into, whatever configuration says.
FORBIDDEN_ROOTS = ("data/curated", "data/raw", "metadata", "data/analytics")


class ConfigurationInvalid(RuntimeError):
    """A V4 setting is missing or unusable. Named, never printed."""

    def __init__(self, message: str, *, variables: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.variables = variables
        self.status = "MODEL_CONFIGURATION_MISSING"


def _flag(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {
        "1", "true", "yes", "on"}


def _text(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def _port(name: str, default: int) -> int:
    raw = _text(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationInvalid(
            f"{name} is not a port number.", variables=(name,)) from exc
    if not 1 <= value <= 65535:
        raise ConfigurationInvalid(
            f"{name} is outside the valid port range.", variables=(name,))
    return value


@dataclass(frozen=True)
class Limits:
    """Section 11, as data. Every field is a bound something checks."""

    mode: str
    deadline_seconds: float
    execution_submissions: int
    analysis_rounds: int
    generation_attempts: int
    provider_attempts: int
    catalog_calls: int
    artifact_reads: int
    steps_per_batch: int
    total_steps: int
    step_seconds: float
    python_memory_mib: int
    sql_memory_mib: int
    output_bytes_per_step: int
    preview_rows: int
    preview_columns: int
    format_regenerations: int
    answer_corrections: int
    spend_ceiling_usd: float
    charts: int
    soft_input_tokens: int
    reserved_output_tokens: int


STANDARD_LIMITS = Limits(
    mode=STANDARD, deadline_seconds=60.0, execution_submissions=5,
    analysis_rounds=3, generation_attempts=12, provider_attempts=24,
    catalog_calls=4, artifact_reads=6, steps_per_batch=6, total_steps=12,
    step_seconds=15.0, python_memory_mib=512, sql_memory_mib=512,
    output_bytes_per_step=25 * 1024 * 1024, preview_rows=100,
    preview_columns=32, format_regenerations=1, answer_corrections=1,
    spend_ceiling_usd=1.0, charts=2, soft_input_tokens=6_000,
    reserved_output_tokens=4_096)

DEEP_LIMITS = Limits(
    mode=DEEP, deadline_seconds=120.0, execution_submissions=5,
    analysis_rounds=3, generation_attempts=16, provider_attempts=32,
    catalog_calls=6, artifact_reads=10, steps_per_batch=8, total_steps=24,
    step_seconds=30.0, python_memory_mib=1024, sql_memory_mib=1024,
    output_bytes_per_step=50 * 1024 * 1024, preview_rows=100,
    preview_columns=32, format_regenerations=1, answer_corrections=1,
    spend_ceiling_usd=2.0, charts=3, soft_input_tokens=10_000,
    reserved_output_tokens=6_144)


def limits_for(mode: str) -> Limits:
    return DEEP_LIMITS if str(mode).lower() == DEEP else STANDARD_LIMITS


@dataclass(frozen=True)
class V4Config:
    """The resolved V4 runtime settings. Values, never secrets."""

    enabled: bool
    provider: str
    reasoning_model: str
    runtime_dir: Path
    state_database: str
    release_id: str
    api_port: int
    ui_port: int
    local_demo_auth: bool
    price_card_path: str
    memory_enabled: bool
    memory_model: str
    default_mode: str
    heartbeat_seconds: float
    lease_heartbeat_seconds: float
    lease_stale_seconds: float
    supervisor_poll_seconds: float
    #: Present/absent only. The value never leaves `credential.require()`.
    credential_present: bool
    missing: tuple[str, ...] = field(default_factory=tuple)

    @property
    def artifacts_dir(self) -> Path:
        return self.runtime_dir / "artifacts"

    @property
    def logs_dir(self) -> Path:
        return self.runtime_dir / "logs"

    @property
    def pids_dir(self) -> Path:
        return self.runtime_dir / "pids"

    def to_dict(self) -> dict[str, Any]:
        """Safe for diagnostics: no secret, and no secret-bearing URL."""
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "reasoning_model": self.reasoning_model,
            "runtime_dir": str(self.runtime_dir),
            "state_database": redact_database_url(self.state_database),
            "release_id": self.release_id,
            "api_port": self.api_port,
            "ui_port": self.ui_port,
            "local_demo_auth": self.local_demo_auth,
            "price_card_path": self.price_card_path,
            "memory_enabled": self.memory_enabled,
            "memory_model": self.memory_model,
            "default_mode": self.default_mode,
            "credential": "PRESENT" if self.credential_present else "MISSING",
            "missing_settings": list(self.missing),
        }


def redact_database_url(url: str) -> str:
    """Keep the scheme and host; drop anything that could be a password."""
    text = str(url or "")
    if "://" not in text:
        return text
    scheme, _, rest = text.partition("://")
    if "@" in rest:
        _, _, host = rest.rpartition("@")
        return f"{scheme}://***@{host}"
    return text


def default_runtime_dir() -> Path:
    return Path(_text("COCKPIT_V4_RUNTIME_DIR")
                or Path.home() / ".creditprobe" / "cockpit_v4").expanduser()


def check_write_target(path: Path | str, cfg: "V4Config") -> Path:
    """Refuse a write outside the V4 runtime directory, before the first byte.

    A branch isolates code. It does not isolate a Parquet lake, a SQLite file
    or a log directory, so this is where runtime isolation is actually
    enforced -- and it is enforced by path containment, not by trusting that
    every caller passed the right directory.
    """
    target = Path(path).expanduser().resolve()
    root = cfg.runtime_dir.expanduser().resolve()
    text = str(target).replace("\\", "/")
    for forbidden in FORBIDDEN_ROOTS:
        if f"/{forbidden}/" in f"{text}/":
            raise ConfigurationInvalid(
                f"{target} is inside {forbidden}, which belongs to the rest "
                f"of the product. V4 writes only under its runtime directory.")
    if root not in target.parents and target != root:
        raise ConfigurationInvalid(
            f"{target} is outside the V4 runtime directory {root}. A build "
            f"that can write outside its own runtime is not isolated, "
            f"whatever branch it is on.")
    return target


def load() -> V4Config:
    """Read the environment. Reports what is missing; never invents it."""
    runtime_dir = default_runtime_dir()
    mode = _text("COCKPIT_V4_DEFAULT_MODE", STANDARD).lower()
    if mode not in MODES:
        mode = STANDARD

    reasoning_model = _text(REASONING_MODEL_VAR)
    release_id = _text("COCKPIT_V4_RELEASE_ID")
    price_card = _text("COCKPIT_V4_PRICE_CARD")
    memory_enabled = _flag("COCKPIT_V4_MEMORY_ENABLED", "false")
    memory_model = _text("COCKPIT_V4_MEMORY_MODEL")

    missing: list[str] = []
    if not reasoning_model:
        missing.append(REASONING_MODEL_VAR)
    if not release_id:
        missing.append("COCKPIT_V4_RELEASE_ID")
    if not price_card:
        missing.append("COCKPIT_V4_PRICE_CARD")
    if memory_enabled and not memory_model:
        missing.append("COCKPIT_V4_MEMORY_MODEL")
    if not os.environ.get(CREDENTIAL_VAR, "").strip():
        missing.append(CREDENTIAL_VAR)

    state_db = _text("COCKPIT_V4_STATE_DATABASE") or str(
        runtime_dir / "state" / "cockpit_v4.sqlite3")

    return V4Config(
        enabled=_flag("COCKPIT_AGENTIC_V4", "false"),
        provider=_text("AI_PROVIDER", "anthropic"),
        reasoning_model=reasoning_model,
        runtime_dir=runtime_dir,
        state_database=state_db,
        release_id=release_id,
        api_port=_port("COCKPIT_V4_API_PORT", DEFAULT_API_PORT),
        ui_port=_port("COCKPIT_V4_UI_PORT", DEFAULT_UI_PORT),
        local_demo_auth=_flag("COCKPIT_V4_LOCAL_DEMO_AUTH", "false"),
        price_card_path=price_card,
        memory_enabled=memory_enabled,
        memory_model=memory_model,
        default_mode=mode,
        heartbeat_seconds=float(_text("COCKPIT_V4_HEARTBEAT_SECONDS", "5")),
        lease_heartbeat_seconds=2.0,
        lease_stale_seconds=10.0,
        supervisor_poll_seconds=2.0,
        credential_present=bool(
            os.environ.get(CREDENTIAL_VAR, "").strip()),
        missing=tuple(missing))


def validate(cfg: V4Config | None = None) -> dict[str, Any]:
    """Name every missing setting at once. Never prints a value."""
    cfg = cfg or load()
    return {
        "ok": not cfg.missing and cfg.enabled,
        "enabled": cfg.enabled,
        "missing": list(cfg.missing),
        "settings": cfg.to_dict(),
    }


__all__ = ["CREDENTIAL_VAR", "ConfigurationInvalid", "DEEP_LIMITS",
           "DEFAULT_API_PORT", "DEFAULT_UI_PORT", "Limits",
           "REASONING_MODEL_VAR", "STANDARD_LIMITS", "V4Config",
           "check_write_target", "default_runtime_dir", "limits_for", "load",
           "redact_database_url", "validate"]

"""
Central application configuration.

A single `settings` object, loaded once at import, is the one source of truth for
host/port, environment, filesystem paths, AI-backend endpoints, and (from later
phases) the database URL and Flask secret. Read it everywhere via
`from config import settings` instead of scattering literals or `os.environ`
lookups through the codebase.

Precedence: real process environment variables win; a local `.env` file fills in
the gaps in development. In production the NSSM service injects these as env vars
and no `.env` file is present.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# config.py lives in backend/, so the project root (where .env, logs/, uploads/
# and the data workbooks live) is one level up.
BASE_DIR = Path(__file__).resolve().parent.parent

# Dev convenience only: load .env if present. Real env vars always take precedence
# (override=False), so production service-injected values are never shadowed.
load_dotenv(BASE_DIR / ".env", override=False)


def _get(name: str, default: str) -> str:
    val = os.environ.get(name)
    return val if val is not None and val != "" else default


def _int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


def _resolve_dir(value: str) -> Path:
    """Resolve a configured directory relative to the project root unless it is
    already absolute. The directory is created if missing."""
    p = Path(value)
    if not p.is_absolute():
        p = BASE_DIR / p
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass(frozen=True)
class Settings:
    env: str
    host: str
    port: int
    log_dir: Path
    upload_dir: Path
    max_upload_mb: int
    ollama_base_url: str
    anthropic_api_key: str
    # Populated in later phases; empty until then.
    database_url: str
    secret_key: str
    #: When true every API call needs a signed session, and the header-based
    #: role switcher is refused. Off by default so a local run works out of the
    #: box; on for any deployment where the browser is not the only client.
    require_login: bool

    # ---- API (FastAPI) ----
    api_host: str
    api_port: int
    cors_origins: tuple[str, ...]

    # ---- analytical data layers (see docs/ARCHITECTURE.md §4.2) ----
    # raw:       source files exactly as received — never modified
    # curated:   mapped to governed field names, typed, validated
    # analytics: business-ready Parquet the engine reads through the DAL
    raw_dir: Path
    curated_dir: Path
    analytics_dir: Path
    metadata_dir: Path

    @property
    def is_prod(self) -> bool:
        return self.env.lower() == "prod"

    @property
    def debug(self) -> bool:
        return not self.is_prod

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def has_database(self) -> bool:
        """False in environments where Postgres has not been configured yet. The
        API degrades to a clearly-reported 'not configured' state rather than
        failing to start, so a non-developer can boot the app before setting the
        database up."""
        return bool(self.database_url)


def _load() -> Settings:
    return Settings(
        env=_get("ENV", "dev"),
        host=_get("HOST", "127.0.0.1"),
        port=_int("PORT", 8050),
        log_dir=_resolve_dir(_get("LOG_DIR", "logs")),
        upload_dir=_resolve_dir(_get("UPLOAD_DIR", "uploads")),
        max_upload_mb=_int("MAX_UPLOAD_MB", 25),
        ollama_base_url=_get("OLLAMA_BASE_URL", "http://localhost:11434"),
        anthropic_api_key=_get("ANTHROPIC_API_KEY", ""),
        database_url=_get("DATABASE_URL", ""),
        secret_key=_get("SECRET_KEY", ""),
        require_login=_get("REQUIRE_LOGIN", "false").strip().lower()
        in ("1", "true", "yes", "on"),
        api_host=_get("API_HOST", "127.0.0.1"),
        api_port=_int("API_PORT", 8000),
        # Both spellings of the same machine. Somebody running the backend
        # directly and typing 127.0.0.1 into the browser is doing nothing
        # unusual, and a blocked preflight there looks like a broken product
        # rather than a CORS default. In Docker neither is used: the browser
        # calls the page's own origin and Next forwards it.
        cors_origins=tuple(
            o.strip() for o in _get(
                "CORS_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000",
            ).split(",") if o.strip()
        ),
        raw_dir=_resolve_dir(_get("DATA_RAW_DIR", "data/raw")),
        curated_dir=_resolve_dir(_get("DATA_CURATED_DIR", "data/curated")),
        analytics_dir=_resolve_dir(_get("DATA_ANALYTICS_DIR", "data/analytics")),
        metadata_dir=_resolve_dir(_get("METADATA_DIR", "metadata")),
    )


settings = _load()

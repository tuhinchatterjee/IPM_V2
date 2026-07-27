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

    @property
    def is_prod(self) -> bool:
        return self.env.lower() == "prod"

    @property
    def debug(self) -> bool:
        return not self.is_prod

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


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
    )


settings = _load()

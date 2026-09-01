"""
Where a circular's original lives, and how it stays the same. Part G.

Immutability, concretely
-------------------------
The original is written once under its own SHA-256 and never touched again.
There is no update path and no delete path — `save` on bytes that are already
present returns the existing record rather than writing a second copy, so a
bulk upload that includes the same circular twice ends with one original and
two references to it.

A citation resolves through the hash. That is the point of all of it: a reader
who wants to check a quoted obligation can be handed the bytes the quote was
taken from, and can prove they are the bytes that were uploaded.

Why the filesystem rather than the database
--------------------------------------------
A regulator's rulebook is tens of megabytes and is read whole or not at all.
Postgres would carry it as a large object nothing queries, would bloat every
backup, and would make "give me the original" a database round trip. The
metadata, the sections and the rules are in Postgres, where they are queried;
the bytes are on disk under their hash, where they are not.

Tenancy
--------
The path carries the tenant. A restricted supervisory letter uploaded by one
bank is not reachable by a path another tenant can construct, and nothing in
this module joins across them.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.regulatory import schema as rs

logger = logging.getLogger(__name__)

STORE_VERSION = "1.0.0"

#: Where originals live. Configurable because a bank will mount a volume;
#: defaulted so a developer does not have to.
_ENV = "CREDITPROBE_REGULATORY_STORE"
_DEFAULT = "data/regulatory"

#: The largest original accepted. A regulator's consolidated rulebook is
#: large; a 500 MB upload is a mistake or an attack, and finding out after it
#: is on disk is too late.
MAX_BYTES = 64 * 1024 * 1024

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: A tenant becomes a DIRECTORY name, and a directory name has no business
#: containing a dot. Keeping dots left "../../etc" as "..-..-etc" — which does
#: not traverse, and which anybody auditing the store would still have to stop
#: and reason about. A name with no dots in it needs no reasoning.
_SAFE_TENANT = re.compile(r"[^A-Za-z0-9_-]+")


def root() -> Path:
    return Path(os.environ.get(_ENV) or _DEFAULT)


def _tenant_dir(tenant: str) -> Path:
    """One directory per tenant, named safely.

    A tenant id reaching a path is exactly how a traversal happens, so it is
    sanitised rather than trusted, and an empty tenant becomes `_shared`
    instead of the store root.
    """
    safe = _SAFE_TENANT.sub("-", str(tenant or "").strip()).strip("-")
    return root() / (safe or "_shared")


def _safe_name(filename: str) -> str:
    name = _SAFE.sub("-", Path(str(filename or "")).name).strip("-")
    return name[:120] or "original"


@dataclass(frozen=True)
class Stored:
    """One original on disk."""

    content_hash: str
    path: Path
    byte_size: int
    tenant: str
    filename: str
    #: True when these exact bytes were already present under this tenant.
    already_present: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"content_hash": self.content_hash, "path": str(self.path),
                "byte_size": self.byte_size, "tenant": self.tenant,
                "filename": self.filename,
                "already_present": self.already_present}


def save(payload: bytes, *, filename: str, tenant: str = "") -> Stored:
    """Write an original once, under its hash. Never overwrites."""
    if not payload:
        raise rs.RegulatoryError("an empty file is not a circular")
    if len(payload) > MAX_BYTES:
        raise rs.RegulatoryError(
            f"the file is {len(payload) / 1_048_576:.0f} MB and the limit is "
            f"{MAX_BYTES // 1_048_576} MB")

    digest = rs.sha256_of(payload)
    directory = _tenant_dir(tenant) / digest[:2]
    directory.mkdir(parents=True, exist_ok=True)
    name = _safe_name(filename)
    path = directory / f"{digest}-{name}"

    if path.exists():
        return Stored(content_hash=digest, path=path,
                      byte_size=path.stat().st_size, tenant=tenant,
                      filename=name, already_present=True)

    # Written to a temporary name and moved into place, so a crash mid-write
    # cannot leave a truncated file sitting under a hash that promises its
    # contents.
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return Stored(content_hash=digest, path=path, byte_size=len(payload),
                  tenant=tenant, filename=name)


def read(content_hash: str, *, tenant: str = "") -> bytes:
    """The original behind a citation, or a refusal that says which hash."""
    found = locate(content_hash, tenant=tenant)
    if found is None:
        raise rs.RegulatoryError(
            f"no original is stored under {content_hash[:12]}… for this "
            "tenant")
    return found.read_bytes()


def locate(content_hash: str, *, tenant: str = "") -> Path | None:
    directory = _tenant_dir(tenant) / str(content_hash)[:2]
    if not directory.is_dir():
        return None
    for path in directory.iterdir():
        if path.name.startswith(f"{content_hash}-"):
            return path
    return None


def verify(content_hash: str, *, tenant: str = "") -> bool:
    """Whether the bytes on disk still hash to what the citation claims.

    The check that makes immutability a fact rather than a policy. Run it
    before quoting a circular in an exported answer, and a file somebody
    edited in place stops being quotable rather than being quoted.
    """
    path = locate(content_hash, tenant=tenant)
    if path is None:
        return False
    try:
        return rs.sha256_of(path.read_bytes()) == content_hash
    except OSError as e:  # pragma: no cover - an unreadable file is a False
        logger.warning("Could not verify %s: %s", content_hash[:12], e)
        return False


def usage(tenant: str = "") -> dict[str, Any]:
    """How much is stored, for the administration screen."""
    directory = _tenant_dir(tenant)
    files = [p for p in directory.rglob("*") if p.is_file()
             and not p.name.endswith(".partial")]
    return {"originals": len(files),
            "bytes": sum(p.stat().st_size for p in files),
            "root": str(directory), "version": STORE_VERSION}


__all__ = ["MAX_BYTES", "STORE_VERSION", "Stored", "locate", "read", "root",
           "save", "usage", "verify"]

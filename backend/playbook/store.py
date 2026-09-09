"""
Where Playbook's bytes live. Playbook §11, §15.

Two stores, one rule
--------------------
Sources are what the user gave us; artifacts are what we produced. Both are
written to durable, authorized application storage under the configured upload
directory, and neither is ever the only copy of anything. A document that exists
only inside a provider's execution container, or only in a front-end blob, is a
document that will be gone when somebody comes back to it tomorrow.

This follows `backend/reporting/store.py`, which already made the decision worth
copying: metadata and payload are separate files, so a listing does not read
megabytes off disk, and an issued document is re-served as the EXACT bytes that
were issued. A committee report that changes after it was tabled is not a
version-controlled document, it is a lost argument.

Layout under `<upload_dir>/playbook`:

    sources/<workspace>/<source_id>/<sanitised filename>
    artifacts/<workspace>/<artifact_id>/v<version>/<filename>.<ext>
    previews/<workspace>/<artifact_id>/v<version>/<format>/page-NN.png

Path safety
-----------
Every filename that reaches this module came from an upload, which means it came
from outside. `safe_filename` is applied to all of them: a name is reduced to its
own basename, stripped of separators and control characters, bounded in length,
and refused outright if nothing usable survives. Path traversal is not filtered
here so much as made unrepresentable — the caller never supplies a directory.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

#: Characters Windows, POSIX and the Files API between them refuse. Kept as one
#: list so a filename that survives here survives everywhere it is later used.
_FORBIDDEN = re.compile(r'[<>:"|?*\\/\x00-\x1f]')
_MAX_NAME = 120


class StorageError(RuntimeError):
    """The bytes could not be stored or read back."""


def safe_filename(name: str, *, fallback: str = "document") -> str:
    """Reduce an untrusted filename to something safe to write.

    `../../etc/passwd` becomes `passwd`; a name of only separators becomes the
    fallback. Unicode is normalised first so two visually identical names cannot
    resolve to two different files.
    """
    name = unicodedata.normalize("NFKC", name or "")
    # Take the basename under BOTH separators: a Windows upload arriving on a
    # POSIX host still carries backslashes, and Path() would not split them.
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _FORBIDDEN.sub("_", name).strip(" .")
    if len(name) > _MAX_NAME:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 8:
            name = stem[: _MAX_NAME - len(ext) - 1] + "." + ext
        else:
            name = name[:_MAX_NAME]
    return name or fallback


def root() -> Path:
    base = Path(settings.upload_dir) / "playbook"
    base.mkdir(parents=True, exist_ok=True)
    return base


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class Stored:
    """A file that is now on disk, and what it turned out to be."""

    path: Path
    size_bytes: int
    sha256: str
    filename: str

    @property
    def relative(self) -> str:
        """The path as persisted — relative, so moving the upload directory
        between environments does not invalidate every stored row."""
        return str(self.path.relative_to(root()))


def _write(target: Path, content: bytes, filename: str) -> Stored:
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write to a neighbouring temporary file and move it into place, so a
    # crash mid-write leaves no half-file that later reads as a valid document.
    tmp = target.with_suffix(target.suffix + ".partial")
    tmp.write_bytes(content)
    tmp.replace(target)
    return Stored(
        path=target,
        size_bytes=len(content),
        sha256=sha256(content),
        filename=filename,
    )


def put_source(workspace_id: int, source_id: int, filename: str,
               content: bytes) -> Stored:
    """Store an uploaded source document."""
    name = safe_filename(filename)
    return _write(root() / "sources" / str(workspace_id) / str(source_id) / name,
                  content, name)


def put_artifact(workspace_id: int, artifact_id: int, version: int,
                 filename: str, content: bytes) -> Stored:
    """Store one rendered format of one artifact version.

    Called only after the bytes have been retrieved in full and validated. A
    job that has not reached this point has not produced a file, whatever the
    model said it did.
    """
    name = safe_filename(filename)
    return _write(
        root() / "artifacts" / str(workspace_id) / str(artifact_id)
        / f"v{version}" / name,
        content, name,
    )


def put_preview(workspace_id: int, artifact_id: int, version: int,
                fmt: str, page: int, content: bytes) -> Stored:
    """Store one rendered page or slide image for in-app inspection."""
    name = f"page-{page:03d}.png"
    return _write(
        root() / "previews" / str(workspace_id) / str(artifact_id)
        / f"v{version}" / safe_filename(fmt) / name,
        content, name,
    )


def read(relative: str) -> bytes:
    """Read stored bytes back by their persisted relative path.

    The resolved path is checked to be inside the store. A stored row is not a
    trusted input either: a row written by an older, buggier version of this
    code must not become a way to read `/etc/shadow`.
    """
    base = root().resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise StorageError("refusing to read outside the Playbook store")
    if not target.is_file():
        raise StorageError(f"stored file is missing: {relative}")
    return target.read_bytes()


def exists(relative: str) -> bool:
    try:
        base = root().resolve()
        target = (base / relative).resolve()
        return target.is_relative_to(base) and target.is_file()
    except OSError:
        return False

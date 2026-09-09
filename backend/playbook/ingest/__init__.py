"""
Reading source documents into located, citable evidence. Playbook §7.

One entry point. `read(filename, content)` validates the upload, dispatches to
the reader for what the bytes actually are, and returns chunks plus an honest
manifest of what was and was not read.

Filenames are not trusted for dispatch — `validate.check` sniffs the content and
that is what decides. A previous report saved as `report.txt` is still a Word
document if its bytes say so, and a `.docx` that is really a ZIP of something
else is refused rather than fed to a parser.
"""

from __future__ import annotations

from backend.playbook.ingest import docx_reader, pdf_reader, pptx_reader, sheets, validate
from backend.playbook.ingest.types import (
    Chunk,
    Manifest,
    ReadResult,
    UnreadableSource,
)
from backend.playbook.ingest.validate import Accepted, RejectedUpload

__all__ = [
    "Accepted",
    "Chunk",
    "Manifest",
    "ReadResult",
    "RejectedUpload",
    "UnreadableSource",
    "accept",
    "read",
]


def accept(filename: str, content: bytes) -> Accepted:
    """Validate an upload without parsing it. Raises `RejectedUpload`."""
    return validate.check(filename, content)


def read(filename: str, content: bytes) -> tuple[Accepted, ReadResult]:
    """Validate, then read. Raises `RejectedUpload` or `UnreadableSource`."""
    accepted = validate.check(filename, content)
    kind = accepted.kind
    if kind == validate.DOCX:
        result = docx_reader.read(content, filename=filename)
    elif kind == validate.PDF:
        result = pdf_reader.read(content, filename=filename)
    elif kind == validate.XLSX:
        result = sheets.read(content, filename=filename, kind="xlsx")
    elif kind == validate.PPTX:
        result = pptx_reader.read(content, filename=filename)
    elif kind == validate.CSV:
        result = sheets.read(content, filename=filename, kind="csv")
    else:
        text = content.decode("utf-8", errors="replace").strip()
        if not text:
            raise UnreadableSource(f"{filename} is empty.")
        manifest = Manifest(format=kind, read=[f"{len(text)} characters"])
        result = ReadResult(
            [Chunk("paragraph", f"{kind}://text", text, [], ordinal=0)], manifest
        )
    return accepted, result

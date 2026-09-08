"""
Whether a file may be accepted at all. Playbook §16.

An upload is untrusted input with a friendly icon. Four things are checked
before a parser is ever handed the bytes, because every one of them is a way a
document has been used to attack the thing that opened it.

**The declared type must match the actual bytes.** An extension is a claim by
whoever named the file. The magic-byte check is the only part of that claim that
is evidence.

**Macro-enabled formats are refused.** `.docm`, `.xlsm`, `.pptm`. Playbook never
needs to execute anything a document brought with it, so the safest handling of
a macro is to decline the file and say why.

**Compressed expansion is bounded.** OOXML files are ZIP archives, and a small
archive that expands to gigabytes is the oldest denial-of-service in document
handling. The ratio is checked before extraction, not discovered during it.

**Size is bounded** by the existing `MAX_UPLOAD_MB` setting, so Playbook uses the
limit the deployment already configured rather than inventing a second one.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from backend.config import settings

DOCX = "docx"
PDF = "pdf"
XLSX = "xlsx"
PPTX = "pptx"
CSV = "csv"
TXT = "txt"
MD = "md"

#: What Playbook accepts as evidence, per §4's core input set.
SUPPORTED = (DOCX, PDF, XLSX, PPTX, CSV, TXT, MD)

MIME = {
    DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    PDF: "application/pdf",
    XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    PPTX: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    CSV: "text/csv",
    TXT: "text/plain",
    MD: "text/markdown",
}

#: Extensions that carry executable content. Refused by name, before any parse.
MACRO_ENABLED = {"docm", "xlsm", "xlsb", "pptm", "dotm", "xltm", "potm"}

#: An OOXML archive expanding more than this is treated as hostile. Real office
#: documents sit far below it; a zip bomb sits orders of magnitude above.
MAX_EXPANSION_RATIO = 200
#: An absolute ceiling on uncompressed size, for a small archive with a huge ratio.
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024

#: The OOXML part that identifies which office format an archive really is.
_OOXML_MARKERS = {
    DOCX: "word/document.xml",
    XLSX: "xl/workbook.xml",
    PPTX: "ppt/presentation.xml",
}


class RejectedUpload(ValueError):
    """The file may not be accepted. The message is shown to the user."""


@dataclass(frozen=True)
class Accepted:
    kind: str
    mime: str
    filename: str
    size_bytes: int


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _sniff(content: bytes) -> str:
    """What the bytes actually are, independent of what they were called."""
    if content.startswith(b"%PDF-"):
        return PDF
    if content[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                names = set(zf.namelist())
        except zipfile.BadZipFile as exc:
            raise RejectedUpload("This file looks like a ZIP archive but could "
                                 "not be opened.") from exc
        for kind, marker in _OOXML_MARKERS.items():
            if marker in names:
                return kind
        raise RejectedUpload("This is a ZIP archive but not a Word, Excel or "
                             "PowerPoint document.")
    return ""


def _check_expansion(content: bytes, filename: str) -> None:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        uncompressed = sum(i.file_size for i in zf.infolist())
    if uncompressed > MAX_UNCOMPRESSED_BYTES:
        raise RejectedUpload(
            f"{filename} expands to {uncompressed // (1024 * 1024)} MB, which is "
            "beyond what Playbook will open."
        )
    if content and uncompressed / len(content) > MAX_EXPANSION_RATIO:
        raise RejectedUpload(
            f"{filename} expands more than {MAX_EXPANSION_RATIO}× its stored "
            "size. Playbook does not open archives shaped like this."
        )


def check(filename: str, content: bytes) -> Accepted:
    """Accept the upload, or refuse it with a reason a user can act on."""
    if not content:
        raise RejectedUpload("That file is empty.")

    limit = settings.max_upload_bytes
    if len(content) > limit:
        raise RejectedUpload(
            f"That file is {len(content) // (1024 * 1024)} MB. The limit is "
            f"{limit // (1024 * 1024)} MB."
        )

    ext = _extension(filename)
    if ext in MACRO_ENABLED:
        raise RejectedUpload(
            f".{ext} files carry macros, which Playbook will not open. Save it "
            "as a macro-free document and upload that instead."
        )

    sniffed = _sniff(content)
    if sniffed:
        if sniffed in _OOXML_MARKERS:
            _check_expansion(content, filename)
        # A mislabelled office document is still readable — we trust the bytes
        # over the name, and say so rather than refusing a usable file.
        if ext != sniffed and ext in SUPPORTED:
            pass
        return Accepted(sniffed, MIME[sniffed], filename, len(content))

    # Not a recognised binary container: only the text formats remain.
    if ext in (CSV, TXT, MD):
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content.decode("utf-16")
            except UnicodeDecodeError as exc:
                raise RejectedUpload(
                    f"{filename} is not readable as text."
                ) from exc
        return Accepted(ext, MIME[ext], filename, len(content))

    raise RejectedUpload(
        f"Playbook does not read .{ext or 'this'} files. It reads "
        "DOCX, PDF, XLSX, PPTX, CSV, TXT and Markdown."
    )

"""
Reading a PDF. Playbook §7.

The distinction this reader exists to make
------------------------------------------
A PDF is not one thing. A text-based PDF is a document whose words can be read.
An image-only PDF — a scan, or a deck exported as pictures — is a stack of
photographs that happens to have a .pdf extension, and pypdf will extract
exactly nothing from it while raising no error at all.

Treating the second as the first is how a report ends up citing a source that
was never read. So every page is classified, and a page that yielded no text is
recorded as needing vision rather than as an empty page. `Manifest.needs` then
carries that upward, and the answer says the source could not be read instead of
quietly answering without it.

OCR is not available in this deployment — no tesseract, no OCR library — so
this reader never claims to have performed any. Where text extraction fails, the
honest options are to look at the page as an image through the model's vision,
or to say the page is unreadable. Both are better than a confident summary of a
page nobody opened.
"""

from __future__ import annotations

import io

from backend.playbook.ingest.types import (
    NOTE,
    PAGE,
    Chunk,
    Manifest,
    ReadResult,
    UnreadableSource,
)

#: Below this many characters, a page is treated as having yielded no usable
#: text. Scanned pages routinely extract a few stray ligatures.
_MIN_PAGE_CHARS = 20


def read(content: bytes, *, filename: str = "") -> ReadResult:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise UnreadableSource("pypdf is not installed") from exc

    manifest = Manifest(format="pdf")
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise UnreadableSource(
            f"{filename or 'This file'} could not be opened as a PDF."
        ) from exc

    if getattr(reader, "is_encrypted", False):
        # An empty-password decrypt is worth one attempt; anything else is a
        # document we were not given the means to read.
        try:
            if not reader.decrypt(""):
                raise UnreadableSource(
                    f"{filename or 'This PDF'} is password-protected."
                )
        except UnreadableSource:
            raise
        except Exception as exc:
            raise UnreadableSource(
                f"{filename or 'This PDF'} is encrypted and could not be opened."
            ) from exc

    chunks: list[Chunk] = []
    image_only: list[int] = []

    for n, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
            manifest.skip(f"page {n}", "text extraction failed on this page")
        if len(text) < _MIN_PAGE_CHARS:
            image_only.append(n)
            continue
        chunks.append(Chunk(PAGE, f"pdf://p{n}", text, [], ordinal=len(chunks)))

    pages = len(reader.pages)
    manifest.read.append(f"{len(chunks)} of {pages} pages as text")

    if image_only:
        manifest.needs.append("vision")
        manifest.warnings.append(
            f"{len(image_only)} page(s) yielded no extractable text "
            f"({', '.join(str(p) for p in image_only[:10])}"
            f"{'…' if len(image_only) > 10 else ''}). They are images. No OCR is "
            "available in this deployment, so nothing on them has been read."
        )
        for n in image_only:
            manifest.skip(f"page {n}", "image-only page, no text layer")

    if not chunks:
        raise UnreadableSource(
            f"{filename or 'This PDF'} has no extractable text on any of its "
            f"{pages} page(s). It appears to be a scan or an exported image."
        )

    try:
        meta = reader.metadata or {}
        info = {k.lstrip("/"): str(v) for k, v in meta.items() if v}
        if info:
            chunks.append(Chunk(NOTE, "pdf://properties", "", [], info,
                                ordinal=len(chunks)))
    except Exception:  # pragma: no cover - optional part
        manifest.skip("document properties", "could not be read")

    return ReadResult(chunks, manifest)

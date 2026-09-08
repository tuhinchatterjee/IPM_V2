"""
Reading a PowerPoint deck. Playbook §7.

Slide identity is preserved, because every instruction Playbook receives about a
deck is positional: "revise slide 4", "add a slide after the results". A deck
read as an undifferentiated bag of text cannot honour any of them.

The rule about charts is the same one as for images elsewhere: a chart whose
underlying data python-pptx can reach is read as data; a chart that is a picture
is recorded as a picture nobody opened. Claiming to have read a figure that was
never parsed is exactly the kind of confident wrongness that makes a committee
paper indefensible.
"""

from __future__ import annotations

import io

from backend.playbook.ingest.types import (
    NOTE,
    SLIDE,
    TABLE,
    Chunk,
    Manifest,
    ReadResult,
    UnreadableSource,
)


def _table_data(shape) -> dict:
    grid = [[cell.text.strip() for cell in row.cells] for row in shape.table.rows]
    if not grid:
        return {"columns": [], "rows": []}
    header, *body = grid
    return {"columns": header, "rows": body}


def read(content: bytes, *, filename: str = "") -> ReadResult:
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise UnreadableSource("python-pptx is not installed") from exc

    manifest = Manifest(format="pptx")
    try:
        prs = Presentation(io.BytesIO(content))
    except Exception as exc:
        raise UnreadableSource(
            f"{filename or 'This file'} could not be opened as a presentation."
        ) from exc

    chunks: list[Chunk] = []
    pictures = charts_read = charts_unreadable = 0

    for n, slide in enumerate(prs.slides, start=1):
        title = ""
        try:
            if slide.shapes.title is not None:
                title = (slide.shapes.title.text or "").strip()
        except Exception:
            title = ""

        body: list[str] = []
        for shape in slide.shapes:
            if shape.has_table:
                chunks.append(Chunk(
                    TABLE, f"pptx://slide/{n}/table", "", [title or f"Slide {n}"],
                    _table_data(shape), ordinal=len(chunks),
                ))
                continue
            if getattr(shape, "has_chart", False):
                try:
                    chart = shape.chart
                    series = {
                        s.name or f"series {i}": list(s.values)
                        for i, s in enumerate(chart.plots[0].series)
                    }
                    categories = [str(c) for c in chart.plots[0].categories]
                    chunks.append(Chunk(
                        TABLE, f"pptx://slide/{n}/chart", "",
                        [title or f"Slide {n}"],
                        {"categories": categories,
                         "series": {k: [str(v) for v in v_] for k, v_ in series.items()}},
                        ordinal=len(chunks),
                    ))
                    charts_read += 1
                except Exception:
                    charts_unreadable += 1
                continue
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                pictures += 1
                continue
            if shape.has_text_frame:
                text = (shape.text_frame.text or "").strip()
                if text and text != title:
                    body.append(text)

        chunks.append(Chunk(
            SLIDE, f"pptx://slide/{n}", "\n".join([title, *body]).strip(),
            [title] if title else [], {"title": title, "index": n},
            ordinal=len(chunks),
        ))

        try:
            if slide.has_notes_slide:
                notes = (slide.notes_slide.notes_text_frame.text or "").strip()
                if notes:
                    chunks.append(Chunk(NOTE, f"pptx://slide/{n}/notes", notes,
                                        [title or f"Slide {n}"],
                                        ordinal=len(chunks)))
        except Exception:  # pragma: no cover - optional part
            manifest.skip(f"slide {n} notes", "could not be read")

    total = len(prs.slides._sldIdLst)  # noqa: SLF001 — python-pptx has no public count
    if not chunks:
        raise UnreadableSource(
            f"{filename or 'This deck'} has {total} slide(s) and no readable text."
        )

    manifest.read.append(f"{total} slides")
    if charts_read:
        manifest.read.append(f"{charts_read} chart(s) read as data")
    if charts_unreadable:
        manifest.warnings.append(
            f"{charts_unreadable} chart(s) could not be read as data; their "
            "figures have not been taken from the deck."
        )
    if pictures:
        manifest.warnings.append(
            f"{pictures} picture(s) were not interpreted. Anything shown only "
            "in an image has not been read."
        )
    return ReadResult(chunks, manifest)

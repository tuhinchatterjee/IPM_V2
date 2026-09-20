"""
The shell a report is delivered in: its title, its cover and its contents.

Chapter 09 asks for "real headings, tables, sensible page layout, source notes
and **usable navigation**" in Word, and "correct pagination, no clipped tables
and **no broken characters**" in PDF. A delivered report had none of the
navigation and several of the broken characters, and the reason for both was
the same one line.

The title
---------
`author_document` was called with `title=workspace.title`, and a workspace is
titled from its first message. So the H1, the running header and the file name
of a sixteen-page committee report were all the user's prompt —

    Create a detailed Auto Loan Application Scorecard Model Development Report
    using the attached evidence. Treat AL-AS-v1.

— and because that prompt contained a newline, the newline went into the PDF's
running header, where the font has no glyph for it and it rendered as two
black boxes. One cause, two symptoms.

Fixed at the source: `author_document` now parses with no title, so the
model's own leading `# H1` becomes the document's title rather than its first
section. `title_of` reads that, falls back to the first heading and then to
what the caller had, and cleans whatever it chooses — one line, no marks,
bounded length.

Navigation
----------
Each format is rendered independently from the canonical Document, so the
cover and the contents are built once here as data and laid out by each
writer in its own terms. Word gets a real TOC field so its navigation pane
works and the entries stay right when the document reflows; the PDF gets a
built list, because a PDF has no reader to update a field later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.playbook.render import inline

#: Long enough for a real report title, short enough for a running header.
MAX_TITLE = 120

#: A trailing sentence fragment left by trimming reads worse than an ellipsis.
_TIDY = re.compile(r"\s+")


def title_of(document, fallback: str = "") -> str:
    """The report's own title.

    `service.author_document` now parses with no title, so a draft opening
    `# Auto Loan Application Scorecard — Model Development Report` arrives
    with that as `document.title`. That is the report naming itself, and it
    is always right when it exists.

    The order matters and is deliberate: the document's own title, then its
    first heading for a draft that opens straight into one, then whatever the
    caller had — which is the workspace's name, i.e. the user's first message,
    and the thing that produced a prompt-as-title in the first place. It is
    cleaned either way, because a fallback is not a licence to print anything.
    """
    heading = next((s.heading for s in getattr(document, "sections", None) or []
                    if getattr(s, "heading", "")), "")
    return clean_title(getattr(document, "title", "") or heading or fallback)


def clean_title(text: str) -> str:
    """One line, no marks, bounded length.

    No attempt is made to strip an instruction back into a title. Guessing
    which words of a sentence are the subject produces "Quarterly pack" from
    "Prepare the quarterly pack" and something worse from the next phrasing;
    an over-long fallback is cut at its first sentence, which is a rule rather
    than a guess.
    """
    flat = _TIDY.sub(" ", inline.plain(text or "")).strip(" .;:—-")
    if not flat:
        return "CreditProbe report"
    if len(flat) > MAX_TITLE:
        first = re.split(r"(?<=[.!?])\s", flat, maxsplit=1)[0].strip(" .;:—-")
        if 12 <= len(first) <= MAX_TITLE:
            return first
        cut = flat[:MAX_TITLE].rsplit(" ", 1)[0]
        return f"{cut.rstrip(' .,;:')}…"
    return flat


@dataclass
class Entry:
    """One line of the contents."""

    text: str
    level: int = 1


@dataclass
class Shell:
    """Everything the cover and the contents need, in one shape.

    Built once and laid out by each writer, so the two formats cannot drift
    into describing the same document differently.
    """

    title: str = "CreditProbe report"
    subtitle: str = ""
    #: `doc.meta` as ordered rows — model id, owner, date, status. It used to
    #: be joined into one line with middots, which reads as a caption and not
    #: as the record a committee paper's front matter is.
    facts: list[tuple[str, str]] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)

    @property
    def has_contents(self) -> bool:
        """Below this a contents page is furniture, not navigation."""
        return len(self.entries) >= 3


def shell_of(document, fallback: str = "") -> Shell:
    """Read the cover and contents off the document itself."""
    facts = [(str(k).replace("_", " ").strip().title(), str(v).strip())
             for k, v in (getattr(document, "meta", None) or {}).items()
             if str(v).strip()]
    entries = [Entry(inline.plain(s.heading),
                     max(1, min(int(getattr(s, "level", 1) or 1), 3)))
               for s in (getattr(document, "sections", None) or [])
               if getattr(s, "heading", "")]
    return Shell(
        title=title_of(document, fallback),
        subtitle=_TIDY.sub(" ", inline.plain(
            getattr(document, "subtitle", "") or "")).strip(),
        facts=facts,
        entries=entries,
    )

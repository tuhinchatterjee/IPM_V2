"""
Inline formatting, for writers that can express it.

The canonical `Document` has no inline model: a `Block` carries one flat
`text` string (`document.py:49`), and `parse()` never consumed `**`, `*` or
backticks. So every writer wrote `**Model ID:** AL-AS-v1.0` as a single plain
run and the asterisks reached the reader — in a sixteen-page committee report,
on every line that tried to emphasise anything.

Fixed here rather than in the model. Adding spans to `Block` would change
`as_dict`, every stored `content_hash` and `merge._fingerprint`, which means a
migration and a re-hash of every existing version to solve a rendering
problem. Writers are where presentation belongs, and both of the ones that
matter can express it: python-docx sets `run.bold`, and reportlab's
`Paragraph` accepts `<b>`, `<i>` and `<font face="Courier">` — verified, not
assumed.

What is deliberately NOT supported: links, images, nested emphasis beyond
bold-inside-italic, and anything requiring a parser with state. An unmatched
`**` stays literal, because a half-applied format is worse than none and
silently eating the characters would hide a malformed draft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Code spans first and literally: backticks win over everything inside them,
#: which is the whole point of a code span. Then the two emphasis forms, each
#: requiring a non-space adjacent to the marker so `a * b * c` stays arithmetic
#: and `snake_case_names` stay whole.
_TOKEN = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<strong>\*\*(?=\S)(?:[^*]|\*(?!\*))+?(?<=\S)\*\*)"
    r"|(?P<strongu>__(?=\S).+?(?<=\S)__)"
    r"|(?P<em>\*(?=\S)[^*\n]+?(?<=\S)\*)"
    r"|(?P<emu>(?<![A-Za-z0-9_])_(?=\S)[^_\n]+?(?<=\S)_(?![A-Za-z0-9_]))"
)


@dataclass(frozen=True)
class Run:
    """One stretch of text with one set of marks."""

    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False


def runs(text: str) -> list[Run]:
    """Split a flat string into typed runs. Never loses a character."""
    out: list[Run] = []
    at = 0
    for match in _TOKEN.finditer(text or ""):
        if match.start() > at:
            out.append(Run(text[at:match.start()]))
        kind = match.lastgroup or ""
        body = match.group()
        if kind == "code":
            out.append(Run(body[1:-1], code=True))
        elif kind in ("strong", "strongu"):
            # Bold may wrap italic — "**a *b* c**" — so its body is re-scanned
            # and the bold mark applied on top of whatever comes back.
            for inner in runs(body[2:-2]):
                out.append(Run(inner.text, bold=True, italic=inner.italic,
                               code=inner.code))
        else:
            out.append(Run(body[1:-1], italic=True))
        at = match.end()
    if at < len(text or ""):
        out.append(Run(text[at:]))
    return out or [Run(text or "")]


def plain(text: str) -> str:
    """The same string with the markers removed and nothing else changed.

    For the places that can hold no formatting at all — a table cell, a
    heading, a bookmark, a file name — where leaving `**` in is the defect
    and applying it is impossible.
    """
    return "".join(run.text for run in runs(text))


#: reportlab's Paragraph parses its input as markup, so any of these in the
#: source text would be read as a tag rather than shown.
_MARKUP = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def markup(text: str) -> str:
    """The same string as reportlab inline markup.

    Escaping happens per run and before the tags are added, so a literal
    `<` in the document cannot become a tag and a tag this function added
    cannot be escaped by it.
    """
    parts: list[str] = []
    for run in runs(text):
        body = "".join(_MARKUP.get(ch, ch) for ch in run.text)
        if run.code:
            body = f'<font face="Courier">{body}</font>'
        if run.italic:
            body = f"<i>{body}</i>"
        if run.bold:
            body = f"<b>{body}</b>"
        parts.append(body)
    return "".join(parts)


def escape(text: str) -> str:
    """Markup-safe text with no formatting applied at all."""
    return "".join(_MARKUP.get(ch, ch) for ch in (text or ""))

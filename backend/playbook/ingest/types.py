"""
What reading a document produces. Playbook §7.

One shape for every format, because the rest of Playbook should not care
whether a table came out of a Word file, a spreadsheet or a slide — only where
it came from and whether it was read in full.

The two things every chunk carries
----------------------------------
**A locator.** `xlsx://ECL!B12`, `docx://para/17`, `pdf://p4`, `pptx://slide/6`.
This is what lets a report cite a figure, an editor find the section it was
asked to change, and a reviewer check a claim without rereading the source.

**A path.** The heading trail, e.g. `["4. Results", "4.2 Coverage"]`. Section
level editing needs to know what a paragraph is *inside*, and a flat list of
paragraphs cannot answer "rewrite the executive summary" without guessing.

And every read produces a Manifest, which is the honest half: what was read,
what was not, and why. Claiming to have checked every sheet when four were
skipped is the specific failure this type exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Chunk kinds. Closed, so a reader cannot invent a category downstream code
#: does not handle.
HEADING = "heading"
PARAGRAPH = "paragraph"
TABLE = "table"
SHEET_RANGE = "sheet_range"
SLIDE = "slide"
PAGE = "page"
NOTE = "note"

KINDS = (HEADING, PARAGRAPH, TABLE, SHEET_RANGE, SLIDE, PAGE, NOTE)


@dataclass
class Chunk:
    """One addressable piece of a source document."""

    kind: str
    locator: str
    text: str = ""
    path: list[str] = field(default_factory=list)
    #: Typed content for tables and sheet ranges: {"columns": [...], "rows": [...]}
    data: dict = field(default_factory=dict)
    ordinal: int = 0

    @property
    def token_estimate(self) -> int:
        """Rough size, for retrieval budgeting. Deliberately crude — it decides
        what to fetch, never what to report."""
        return max(1, len(self.text) // 4 + sum(len(str(r)) for r in
                                                self.data.get("rows", [])) // 4)

    def as_row(self) -> dict:
        return {
            "kind": self.kind,
            "locator": self.locator,
            "text": self.text,
            "path": list(self.path),
            "data": dict(self.data),
            "ordinal": self.ordinal,
            "token_estimate": self.token_estimate,
        }


@dataclass
class Manifest:
    """What was read, what was not, and why.

    `complete` is False whenever anything was skipped. Downstream, that is what
    stops an answer saying "across all sheets" when one was password-protected
    and silently dropped.
    """

    format: str
    read: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Set where a format needs a capability this deployment does not have,
    #: e.g. an image-only PDF with no OCR available.
    needs: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.skipped and not self.needs

    def skip(self, what: str, why: str) -> None:
        self.skipped.append({"what": what, "why": why})

    def as_dict(self) -> dict:
        return {
            "format": self.format,
            "read": list(self.read),
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
            "needs": list(self.needs),
            "complete": self.complete,
        }


@dataclass
class ReadResult:
    chunks: list[Chunk]
    manifest: Manifest


class UnreadableSource(RuntimeError):
    """The document could not be read at all.

    Distinct from a partial read, which is a normal outcome recorded in the
    manifest. This is "there is nothing here to work with", and it must reach
    the user as that rather than as an empty report.
    """

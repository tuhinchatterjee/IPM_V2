"""
Checking that a generated file is the document it claims to be. Playbook §11.

The failure this prevents
-------------------------
A model says it wrote a twenty-page report. A file appears. It opens. It is four
pages, the results table is missing, and the executive summary quotes a figure
that is in no source. Every step reported success.

So nothing is labelled ready on the strength of having been produced. Each file
is opened again with the same readers Playbook uses on user uploads, and what
comes back is compared against the `Document` it was rendered from: the sections
that should be there, the tables that should be there, and — the part that
matters most — every figure in the prose.

Numbers are the strict check. A figure that appears in the rendered document but
in none of the evidence is a fabrication, and it fails validation rather than
being footnoted. This is the file-level half of the same rule
`backend/analyst/session.py` enforces on answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.playbook import document as D
from backend.playbook.ingest import docx_reader, pdf_reader, pptx_reader, sheets

#: A number as it appears in prose: 22.77, 1,050, 8.95%, -0.5.
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")

#: Figures that carry no risk of being a fabricated result: years, section
#: numbers, small counts. Checking them would produce noise that hides the
#: findings that matter.
_IGNORABLE = re.compile(r"^(19|20)\d{2}$")

#: A source locator is a reference, not a claim. `fixture://…@1.0.0#weighted`
#: and `xlsx://ECL!B12` contain digits that are addresses, and reading them as
#: reported figures would make every references appendix look like a
#: fabrication. They are removed before any figure is extracted, on both sides
#: of the comparison, so a locator can neither invent a figure nor excuse one.
_LOCATOR = re.compile(r"\S+://\S+")


@dataclass
class Validation:
    """What was checked, and what did not hold."""

    format: str
    ok: bool = True
    issues: list[str] = field(default_factory=list)
    checked: dict = field(default_factory=dict)

    def fail(self, issue: str) -> None:
        self.ok = False
        self.issues.append(issue)

    def as_dict(self) -> dict:
        return {"format": self.format, "ok": self.ok,
                "issues": list(self.issues), "checked": dict(self.checked)}


def figures(text: str) -> set[str]:
    """Every number in a piece of prose, normalised for comparison.

    Thousands separators and trailing zeros are removed so that "1,050",
    "1050" and "1050.00" are recognised as the same figure — otherwise the
    check would fire on formatting rather than on facts.
    """
    out: set[str] = set()
    for raw in _NUMBER.findall(_LOCATOR.sub(" ", text or "")):
        token = raw.rstrip("%").replace(",", "")
        if _IGNORABLE.match(token):
            continue
        if "." in token:
            token = token.rstrip("0").rstrip(".")
        if token and token not in {"-", ""}:
            out.add(token)
    return out


#: A whole line that is nothing but the page furniture a writer draws:
#: "Page 7", "Page 7 of 12". Anchored at both ends on purpose — "Page 10 of
#: the annex was reviewed" is prose making a claim, and is checked.
_PAGE_FURNITURE = re.compile(
    r"^\s*page\s+\d+(?:\s*(?:of|/)\s*\d+)?\s*$", re.IGNORECASE)

#: A list or heading ordinal as a renderer draws it: "10. " or "3) ". The
#: punctuation is required. Without it a prose line opening with a figure
#: ("10 accounts were reviewed") would look like a marker.
_LEADING_ORDINAL = re.compile(r"^\s*\d+(?:\.\d+)*[.)]\s+(?=\S)")


def _structure_of(doc: D.Document) -> tuple[set[str], set[str]]:
    """The canonical positions an ordinal is allowed to occupy.

    Headings and ordered-list items, normalised. Bullets are excluded: they
    have no ordinals, so nothing about them can excuse a numeral.
    """
    headings = {D._normalise(s.heading) for s in doc.sections if s.heading}
    items: set[str] = set()
    for section in doc.sections:
        for block in section.blocks:
            if block.kind == D.NUMBERS:
                for item in block.data.get("items", []):
                    key = D._normalise(item)
                    if key:
                        items.add(key)
    return headings - {""}, items


def _is_structural_position(remainder: str, headings: set[str],
                            items: set[str]) -> bool:
    """Is what follows this ordinal a heading or ordered item of this document?

    Prefix matching, because a PDF wraps a long list item across lines and the
    marker sits on the first of them.
    """
    key = D._normalise(remainder)
    if not key:
        return False
    if key in headings or key in items:
        return True
    return any(candidate.startswith(key)
               for candidate in items | headings)


def structural_numerals(text: str, doc: D.Document) -> tuple[str, int]:
    """Remove the numerals a renderer produced, leaving every claim intact.

    A committee paper numbers its headings, numbers its recommendations and
    puts a page number at the foot of every page. None of those are things the
    evidence has to support — but the ordinals are drawn into a PDF's text
    layer as ordinary characters (`pdf_writer` writes `f"{i}."`; DOCX uses a
    list style and a PAGE field, which is why only PDFs ever failed this), and
    the canonical document stores list items *without* their ordinals. So the
    validator saw them as figures stated in no source.

    The distinction is positional, never by value. A numeral is structural only
    when it is a leading ordinal whose line is a heading or ordered item **of
    this document**, or a line that is nothing but page furniture. Everything
    else on every line is left exactly as it was and still has to be supported:
    in "10. SAR 10 million was drawn" the marker goes and the SAR 10 million
    stays, because one is furniture and the other is a claim.
    """
    headings, items = _structure_of(doc)
    kept: list[str] = []
    removed = 0
    for line in (text or "").splitlines():
        if _PAGE_FURNITURE.match(line):
            removed += 1
            continue
        match = _LEADING_ORDINAL.match(line)
        if match:
            remainder = line[match.end():]
            if _is_structural_position(remainder, headings, items):
                line = remainder
                removed += 1
        kept.append(line)
    return "\n".join(kept), removed


def _document_text(doc: D.Document) -> str:
    """Everything the canonical document states, including its header block.

    `plain_text()` omits `meta`, and every writer renders it — so a reporting
    period or a threshold living there came back from the rendered file as a
    figure with no source. `plain_text()` itself is deliberately left alone:
    it also decides what an approved version makes admissible as evidence, and
    widening that is a different question from reading the whole document.
    """
    parts = [doc.plain_text()]
    parts.extend(str(value) for value in (doc.meta or {}).values() if value)
    return "\n".join(parts)


def _check_content(v: Validation, doc: D.Document, found_text: str,
                   found_headings: list[str]) -> None:
    """The checks every format shares: headings present, no invented figures."""
    expected = [s.heading for s in doc.sections if s.heading]
    normalised = {re.sub(r"\s+", " ", h.strip().lower()) for h in found_headings}
    missing = [
        h for h in expected
        if re.sub(r"\s+", " ", h.strip().lower()) not in normalised
        and h.strip().lower() not in found_text.lower()
    ]
    if missing:
        v.fail(f"{len(missing)} section(s) are missing from the rendered file: "
               + ", ".join(missing[:5]))
    v.checked["sections_expected"] = len(expected)
    v.checked["sections_found"] = len(expected) - len(missing)

    claims, structural = structural_numerals(found_text, doc)
    v.checked["structural_numerals"] = structural
    allowed = figures(_document_text(doc))
    present = figures(claims)
    invented = sorted(present - allowed)
    if invented:
        v.fail("the rendered file states figure(s) that are in no source: "
               + ", ".join(invented[:8]))
    dropped = sorted(allowed - present)
    if dropped:
        v.checked["figures_not_found"] = dropped[:8]
    v.checked["figures_expected"] = len(allowed)
    v.checked["figures_found"] = len(present & allowed)


def validate(content: bytes, fmt: str, doc: D.Document) -> Validation:
    """Open a generated file and check it against the document it came from."""
    fmt = (fmt or "").lower()
    v = Validation(format=fmt)
    try:
        if fmt == "docx":
            result = docx_reader.read(content, filename=f"generated.{fmt}")
            headings = [c.text for c in result.chunks if c.kind == "heading"]
            text = "\n".join(
                [c.text for c in result.chunks]
                + [" ".join(str(x) for row in c.data.get("rows", []) for x in row)
                   for c in result.chunks if c.kind == "table"]
            )
            v.checked["tables"] = sum(1 for c in result.chunks if c.kind == "table")
            expected_tables = sum(1 for s in doc.sections for b in s.blocks
                                  if b.kind == D.TABLE and b.data.get("columns"))
            if v.checked["tables"] < expected_tables:
                v.fail(f"{expected_tables} table(s) were expected and "
                       f"{v.checked['tables']} are present.")
            _check_content(v, doc, text, headings)

        elif fmt == "pdf":
            result = pdf_reader.read(content, filename="generated.pdf")
            pages = [c for c in result.chunks if c.kind == "page"]
            text = "\n".join(c.text for c in pages)
            v.checked["pages"] = len(pages)
            if not pages:
                v.fail("the PDF has no readable page.")
            _check_content(v, doc, text, [])

        elif fmt == "pptx":
            result = pptx_reader.read(content, filename="generated.pptx")
            slides = [c for c in result.chunks if c.kind == "slide"]
            text = "\n".join(
                [c.text for c in result.chunks]
                + [" ".join(str(x) for row in c.data.get("rows", []) for x in row)
                   for c in result.chunks if c.kind == "table"]
            )
            v.checked["slides"] = len(slides)
            if len(slides) < 2:
                v.fail("a deck of fewer than two slides is not a presentation.")
            blank = [c.data.get("index") for c in slides if not c.text.strip()]
            if blank:
                v.fail(f"slide(s) {blank[:5]} carry no text at all.")
            # A deck summarises, so a missing section is not a failure — but an
            # invented figure still is.
            allowed = figures(_document_text(doc))
            invented = sorted(figures(text) - allowed)
            if invented:
                v.fail("the deck states figure(s) that are in no source: "
                       + ", ".join(invented[:8]))
            v.checked["figures_expected"] = len(allowed)

        elif fmt == "xlsx":
            result = sheets.read(content, filename="generated.xlsx", kind="xlsx")
            sheet_names = [c.data.get("sheet") for c in result.chunks]
            v.checked["sheets"] = len(sheet_names)
            if not sheet_names:
                v.fail("the workbook has no readable sheet.")
            text = "\n".join(
                " ".join(str(x) for row in c.data.get("rows", []) for x in row)
                for c in result.chunks
            )
            allowed = figures(_document_text(doc))
            invented = sorted(figures(text) - allowed)
            if invented:
                v.fail("the workbook states figure(s) that are in no source: "
                       + ", ".join(invented[:8]))
        else:
            v.fail(f"there is no validator for .{fmt} files.")
    except Exception as exc:  # noqa: BLE001 — any failure to reopen is a failure
        v.fail(f"the generated file could not be reopened: {exc}")
    return v


def validate_all(files: dict[str, bytes], doc: D.Document) -> dict[str, Validation]:
    return {fmt: validate(content, fmt, doc) for fmt, content in files.items()}


def consistent(results: dict[str, Validation]) -> list[str]:
    """Cross-format contradictions. PB-020's "same material facts" check.

    Formats are allowed to carry different amounts of detail — a deck summarises
    — but none of them may carry a figure the others have never heard of, and
    `validate` has already checked each against the shared document. What is
    left to check here is that they were all validated against the same one.
    """
    issues: list[str] = []
    counts = {fmt: v.checked.get("figures_expected") for fmt, v in results.items()
              if v.checked.get("figures_expected") is not None}
    if len(set(counts.values())) > 1:
        issues.append(
            "the formats were rendered from different content: "
            + ", ".join(f"{f}={c}" for f, c in sorted(counts.items()))
        )
    return issues

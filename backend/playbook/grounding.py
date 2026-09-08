"""
Checking a draft against its evidence. Playbook §7, §10.

`backend/analyst/session.py` states the rule for answers: every figure is
checked against the evidence ledger, one that is in no observation is removed,
and the removal is recorded rather than hidden. This is that rule for documents.

Why removal rather than a warning
---------------------------------
A committee paper with a footnote saying "one figure could not be verified" is
a committee paper somebody will circulate anyway. The unsupported figure has to
leave, and what replaces it has to say plainly that the number was not
available — which is a sentence a reader can act on, and is also true.

What is checked, and what is deliberately not
---------------------------------------------
Figures are checked. Prose is not: an author's recommendation, a judgement about
materiality, a sentence explaining why a movement matters — none of those have a
locator and none of them should. The distinction PB-033 asks for is between a
reported figure, which must reconcile, and an interpretation, which must be
labelled as one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.playbook import document as D
from backend.playbook.evidence import Ledger
from backend.playbook.validate import figures

#: A sentence, roughly. Removal works at sentence granularity because deleting
#: a bare number leaves prose that reads as though it were complete and is not.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Finding:
    locator_free_text: str
    figures: list[str]
    section: str
    action: str  # "removed" | "flagged"


@dataclass
class GroundingResult:
    document: D.Document
    findings: list[Finding] = field(default_factory=list)
    #: Figures the evidence supports that the draft never used. Not a failure —
    #: reported so a gap check can tell "not mentioned" from "not available".
    unused_figures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "removed": [
                {"section": f.section, "figures": f.figures,
                 "text": f.locator_free_text, "action": f.action}
                for f in self.findings
            ],
            "unused_figures": list(self.unused_figures),
        }

    def note(self) -> str:
        """What the thread says about what was removed. Plain, and never buried."""
        if not self.findings:
            return ""
        counted = sum(len(f.figures) for f in self.findings)
        where = ", ".join(sorted({f.section for f in self.findings if f.section}))
        return (
            f"{counted} figure(s) in the draft could not be traced to any "
            f"attached evidence and were removed"
            + (f" (in {where})" if where else "")
            + ". The surrounding statements now say the figure was unavailable "
              "rather than stating a number no source supports."
        )


#: What replaces a removed sentence. Says what happened; invents nothing.
REPLACEMENT = ("[A figure stated here could not be traced to the attached "
               "evidence and has been removed.]")


def check(doc: D.Document, ledger: Ledger, *,
          remove: bool = True) -> GroundingResult:
    """Reconcile every figure in a drafted document against the ledger."""
    supported = ledger.figures()
    result = GroundingResult(document=doc)
    used: set[str] = set()

    for section in doc.sections:
        for block in section.blocks:
            if block.kind == D.TABLE:
                _check_table(block, supported, used, section.heading, result,
                             remove)
            elif block.kind in (D.BULLETS, D.NUMBERS):
                _check_items(block, supported, used, section.heading, result,
                             remove)
            elif block.text:
                _check_text(block, supported, used, section.heading, result,
                            remove)

    result.unused_figures = sorted(supported - used)
    return result


def _record(result: GroundingResult, text: str, unsupported: set[str],
            section: str, removed: bool) -> None:
    result.findings.append(Finding(
        locator_free_text=text.strip()[:240],
        figures=sorted(unsupported),
        section=section,
        action="removed" if removed else "flagged",
    ))


def _check_text(block: D.Block, supported: set[str], used: set[str],
                section: str, result: GroundingResult, remove: bool) -> None:
    kept: list[str] = []
    for sentence in _SENTENCE.split(block.text):
        found = figures(sentence)
        unsupported = found - supported
        used |= found & supported
        if unsupported:
            _record(result, sentence, unsupported, section, remove)
            if remove:
                kept.append(REPLACEMENT)
                continue
        kept.append(sentence)
    if remove:
        block.text = " ".join(s for s in kept if s).strip()


def _check_items(block: D.Block, supported: set[str], used: set[str],
                 section: str, result: GroundingResult, remove: bool) -> None:
    kept: list[str] = []
    for item in block.data.get("items", []):
        found = figures(item)
        unsupported = found - supported
        used |= found & supported
        if unsupported:
            _record(result, item, unsupported, section, remove)
            if remove:
                continue
        kept.append(item)
    if remove:
        block.data["items"] = kept


def _check_table(block: D.Block, supported: set[str], used: set[str],
                 section: str, result: GroundingResult, remove: bool) -> None:
    """A table cell is replaced rather than the row dropped.

    Removing a row would change what the table is a table OF, which is a
    bigger edit than the evidence justifies. Blanking the unsupported cell and
    saying so keeps the shape and loses only the claim.
    """
    rows = block.data.get("rows") or []
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            found = figures(str(value))
            unsupported = found - supported
            used |= found & supported
            if unsupported:
                _record(result, f"{section} table cell: {value}", unsupported,
                        section, remove)
                if remove:
                    rows[r][c] = "not available"
    block.data["rows"] = rows

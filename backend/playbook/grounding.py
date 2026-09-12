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

The boundary this check does NOT cross
--------------------------------------
This proves TRACEABILITY, not truth. A figure survives because it appears in the
evidence, and a user-uploaded document is evidence — so a source asserting
"coverage is 41.5 per cent" makes 41.5 a quotable figure, and a report quoting it
with a citation is behaving correctly even if the source is wrong or hostile.

That is the right boundary and it is worth being explicit about, because the
tempting misreading is that grounding makes a document safe to believe. It does
not. What it removes is the figure that came from nowhere — the one no source
states and no calculation produced, which is the one nobody can check. Whether a
source deserves belief is a question for the reader, which is why every figure
carries where it came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.playbook import document as D
from backend.playbook.evidence import Ledger
from backend.playbook.validate import classify, figures

#: A sentence, roughly. Removal works at sentence granularity because deleting
#: a bare number leaves prose that reads as though it were complete and is not.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Finding:
    locator_free_text: str
    figures: list[str]
    section: str
    action: str  # "removed" | "flagged"
    #: paragraph / callout / bullets / numbers / table — because "a figure in
    #: a table cell" and "a figure in a sentence" are removed differently and
    #: a reader of the failure needs to know which happened.
    block_kind: str = ""
    #: Each unsupported token with what kind of number it was and the text
    #: around it. A finding that says only "10" cannot be acted on.
    classes: list[dict] = field(default_factory=list)

    def line(self) -> str:
        """One readable line: what, where, what kind, and in what sentence."""
        kinds = ", ".join(
            f"{c['token']} ({c['kind']})" for c in self.classes) \
            or ", ".join(self.figures)
        return (f"{self.section or 'untitled'} [{self.block_kind or 'text'}] "
                f"{self.action}: {kinds}"
                f"\n          in: {self.locator_free_text[:160]}")


@dataclass
class GroundingResult:
    document: D.Document
    findings: list[Finding] = field(default_factory=list)
    #: Figures the evidence supports that the draft never used. Not a failure —
    #: reported so a gap check can tell "not mentioned" from "not available".
    unused_figures: list[str] = field(default_factory=list)
    #: Sections carried forward unchanged from an already-grounded version, and
    #: therefore not re-checked here. Named rather than silently skipped.
    attested: list[str] = field(default_factory=list)

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
            "attested": list(self.attested),
            # The classification, kept in the stored record. "grounding
            # FAILED" with no token, no class and no sentence is not a
            # diagnosis, and a live failure that says only that costs a
            # whole paid run to learn nothing.
            "classified": [
                {"section": f.section, "block": f.block_kind,
                 "figures": f.classes, "text": f.locator_free_text}
                for f in self.findings
            ],
        }

    def report(self) -> str:
        """Every finding, one per line, with token, class and context."""
        if not self.findings:
            return "no unsupported figure"
        return "\n        ".join(f.line() for f in self.findings)

    def by_kind(self) -> dict[str, list[str]]:
        """Unsupported tokens grouped by what kind of number they were."""
        out: dict[str, list[str]] = {}
        for finding in self.findings:
            for entry in finding.classes:
                out.setdefault(entry["kind"], []).append(entry["token"])
        return {k: sorted(set(v)) for k, v in sorted(out.items())}

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


def check(doc: D.Document, ledger: Ledger, *, remove: bool = True,
          scope: set[str] | None = None) -> GroundingResult:
    """Reconcile every figure in a drafted document against the ledger.

    `scope`, when given, names the sections the model actually drafted. The
    rest of the document is a scoped edit's carried-forward content: sections
    copied byte-for-byte out of an approved version that was itself grounded
    when it was written. Re-checking those against a different ledger is not a
    stricter test — it removes figures from sections the revision never
    touched, which is a live failure this has already produced. They are
    recorded as `attested` so the chain of custody is stated rather than
    assumed.

    This narrows nothing about the draft. Every section the model wrote is
    checked exactly as before, `ok` still means zero findings, and removal
    still happens before anything is committed.
    """
    supported = ledger.figures()
    result = GroundingResult(document=doc)
    used: set[str] = set()

    for section in doc.sections:
        if scope is not None and section.heading not in scope:
            result.attested.append(section.heading)
            continue
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
            section: str, removed: bool, block_kind: str = "") -> None:
    classes = [f.as_dict() for f in classify(text)
               if f.evidence_bearing and f.token in unsupported]
    seen: set[str] = set()
    unique = []
    for entry in classes:
        if entry["token"] not in seen:
            seen.add(entry["token"])
            unique.append(entry)
    result.findings.append(Finding(
        locator_free_text=text.strip()[:240],
        figures=sorted(unsupported),
        section=section,
        action="removed" if removed else "flagged",
        block_kind=block_kind,
        classes=unique,
    ))


def _check_text(block: D.Block, supported: set[str], used: set[str],
                section: str, result: GroundingResult, remove: bool) -> None:
    kept: list[str] = []
    for sentence in _SENTENCE.split(block.text):
        found = figures(sentence)
        unsupported = found - supported
        used |= found & supported
        if unsupported:
            _record(result, sentence, unsupported, section, remove,
                    block.kind)
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
            _record(result, item, unsupported, section, remove,
                    block.kind)
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
                        section, remove, block.kind)
                if remove:
                    rows[r][c] = "not available"
    block.data["rows"] = rows


def emptied_sections(before: D.Document, after: D.Document,
                     scope: set[str] | None = None) -> list[str]:
    """Sections that removal left with nothing a reader could use.

    The one way safe removal can still produce a bad report: a section that
    said something now says only that a figure was unavailable, or says
    nothing at all. That is worse than a rejected run, because it looks
    finished. Reported so the caller can refuse rather than persist it.
    """
    after_by = {s.heading: s for s in after.sections}
    hollow: list[str] = []
    for section in before.sections:
        if scope is not None and section.heading not in scope:
            continue
        other = after_by.get(section.heading)
        if other is None or not _substance(section):
            continue
        if not _substance(other):
            hollow.append(section.heading)
    return hollow


def _substance(section: D.Section) -> bool:
    """Whether a section still says anything a reader can act on.

    REPLACEMENT counts. "A figure stated here could not be traced to the
    attached evidence and has been removed" is a true sentence that tells the
    reader exactly where they stand, and shipping it is the whole point of
    removing rather than warning. What does not count is a section left with
    no prose at all — a bullet list whose every item went, or a table whose
    every cell reads "not available". Those look like content and are not.
    """
    for block in section.blocks:
        if block.kind == D.TABLE:
            if any(str(cell).strip() not in {"", "not available"}
                   for row in block.data.get("rows") or [] for cell in row):
                return True
        elif block.kind in (D.BULLETS, D.NUMBERS):
            if [i for i in block.data.get("items", []) if i.strip()]:
                return True
        elif (block.text or "").strip():
            return True
    return False

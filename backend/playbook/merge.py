"""
A scoped edit that is scoped by construction. Playbook §9, PB-017.

The failure this exists for
---------------------------
"Revise only the executive summary" was enforced by a sentence in a prompt and
two checks after the fact. The prompt says everything else must come back
byte-for-byte unchanged; the model returns a whole document; and whether the
rest actually survived was left to the model's compliance. A live run showed
what that is worth: version 2 came back carrying a figure that was in no
evidence, and the check could not even say which section it was in.

So the scope is no longer a request. The model may rewrite whatever it likes;
only the section that was asked for is taken from its reply, and every other
section is carried forward as the SAME OBJECT from the approved version. Two
consequences follow that no amount of prompting can give you:

* unrelated sections are identical because they were never replaced — not
  "identical as far as we checked";
* grounding only has to scrutinise the one section that actually changed, so a
  figure elsewhere cannot be removed by a revision that never touched it
  (`grounding.check` takes the scope for exactly this).

Both of those depend on the base being the STORED CANONICAL version. A later
live run showed what happens otherwise: the base was a Markdown re-render of
the approved version, which drops every citation locator and the document's
header block, and the merge then carried that damage forward into canonical
storage under the name "unchanged".

What this does not do
---------------------
It does not make the edit correct. The drafted section still goes through
grounding like any other, and an invented figure inside the scope is removed
exactly as before. This bounds the blast radius; it does not lower the bar.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field

from backend.playbook import document as D


class ScopeNotFound(ValueError):
    """The section a scoped edit named is not in the document.

    Raised rather than resolved. A scoped edit whose scope cannot be found
    would otherwise apply to nothing and report success, which is the worst of
    the available outcomes: the user believes their change was made.
    """


@dataclass
class MergeResult:
    """The merged document, and what was refused to build it."""

    document: D.Document
    #: The heading actually edited, resolved from the requested scope.
    target: str = ""
    #: What that section is called in the merged document. The same as
    #: `target` unless the draft retitled it, which is inside the scope of
    #: editing it — and which grounding then has to look for by its new name.
    applied_heading: str = ""
    #: Sections the model changed that it was not asked to change. Carried
    #: forward from the approved version instead, and named here so the user
    #: is told rather than left to notice.
    rejected: list[str] = field(default_factory=list)
    #: Sections the model invented, which a scoped edit may not add.
    added: list[str] = field(default_factory=list)
    #: Sections the model dropped, which a scoped edit may not remove.
    dropped: list[str] = field(default_factory=list)

    @property
    def drifted(self) -> bool:
        return bool(self.rejected or self.added or self.dropped)

    def note(self) -> str:
        """One sentence for the thread, or nothing when it behaved."""
        if not self.drifted:
            return ""
        parts = []
        if self.rejected:
            parts.append(f"changed {_names(self.rejected)} without being asked")
        if self.added:
            parts.append(f"added {_names(self.added)}")
        if self.dropped:
            parts.append(f"removed {_names(self.dropped)}")
        return (
            f"The revision was applied to {self.target} only. The draft also "
            + ", ".join(parts)
            + "; those were discarded and the approved version was kept."
        )


def _names(headings: list[str]) -> str:
    quoted = [f"“{h}”" for h in headings[:4]]
    if len(headings) > 4:
        quoted.append(f"and {len(headings) - 4} more")
    return ", ".join(quoted)


def _canonical_data(data: dict) -> str:
    """A block's typed content, in the one form storage preserves.

    Sorted keys, because `repr(dict)` is sensitive to insertion order and
    PostgreSQL's JSONB is not: it stores object keys in its own order, so a
    table read back from a version row reprs differently from the identical
    table that was written. That made every section holding a table report as
    changed after a round-trip through storage — a representation difference,
    with nothing about the document altered. Values are still compared
    exactly; only the key order, which the canonical model does not preserve,
    is normalised. `Document.content_hash` has always sorted keys for the same
    reason.
    """
    return json.dumps(data or {}, sort_keys=True, ensure_ascii=False,
                      default=str)


def _fingerprint(section: D.Section) -> tuple:
    """What "this section is unchanged" means, exactly.

    The heading, the level and every block — kind, text, data and the citation
    locators. Comparing rendered text alone would let a citation or a table
    cell change silently.
    """
    return (section.heading, section.level,
            tuple((b.kind, b.text, _canonical_data(b.data), tuple(b.sources))
                  for b in section.blocks))


def _renamed_target(base: D.Document, drafted: D.Document,
                    target: D.Section) -> D.Section | None:
    """The target when the model retitled it — but only when that is certain.

    Renaming the section you were asked to edit is inside the scope of editing
    it. The difficulty is knowing which section the new name belongs to, and
    guessing would be the one mistake this module exists to prevent. So the
    fallback is positional and admits itself only when nothing else moved:
    the same number of sections, and every heading other than the target's
    matching one-for-one. Anything looser and a reordered draft would have its
    sections silently swapped.
    """
    if len(drafted.sections) != len(base.sections):
        return None
    index = base.sections.index(target)
    for position, (before, after) in enumerate(
            zip(base.sections, drafted.sections, strict=True)):
        if position != index and before.heading != after.heading:
            return None
    candidate = drafted.sections[index]
    return candidate if candidate.heading != target.heading else None


def scoped_merge(base: D.Document, drafted: D.Document,
                 scope: str) -> MergeResult:
    """Take one section from `drafted`; keep everything else from `base`.

    `scope` is matched with `Document.section`'s tolerant lookup, so "the
    executive summary" finds "1. Executive summary" — which is how people refer
    to sections and why that method exists.
    """
    target = base.section(scope)
    if target is None:
        raise ScopeNotFound(
            f"This document has no section matching {scope!r}, so there is "
            "nothing to revise. Nothing was changed."
        )

    drafted_target = (drafted.section(target.heading)
                      or drafted.section(scope)
                      or _renamed_target(base, drafted, target))
    if drafted_target is None:
        raise ScopeNotFound(
            f"The revision did not contain {target.heading!r}, the section it "
            "was asked to change. Nothing was changed."
        )

    merged = copy.deepcopy(base)
    result = MergeResult(document=merged, target=target.heading,
                         applied_heading=drafted_target.heading)

    for section in merged.sections:
        if section.heading == target.heading:
            # The one section the request was about. Its heading comes across
            # too: retitling the target is inside the scope of editing it.
            section.heading = drafted_target.heading
            section.level = drafted_target.level
            section.blocks = copy.deepcopy(drafted_target.blocks)
            break

    # Everything below is reporting only — the merge above already decided the
    # document. A user who asked for one section changed is entitled to know
    # the model tried to change others.
    base_by_heading = {s.heading: s for s in base.sections
                       if s.heading != target.heading}
    drafted_by_heading = {s.heading: s for s in drafted.sections
                          if s.heading != drafted_target.heading}

    for heading, original in base_by_heading.items():
        other = drafted_by_heading.get(heading)
        if other is None:
            result.dropped.append(heading)
        elif _fingerprint(other) != _fingerprint(original):
            result.rejected.append(heading)
    for heading in drafted_by_heading:
        if heading not in base_by_heading:
            result.added.append(heading)

    return result


def unchanged_outside(base: D.Document, after: D.Document,
                      target: str) -> list[str]:
    """Which sections other than `target` differ. Empty means the scope held.

    The assertion the live check makes, and the one `scoped_merge` is built to
    satisfy trivially. Kept here beside the merge so both read the same
    definition of "unchanged".
    """
    resolved = base.section(target)
    skip = resolved.heading if resolved else ""
    after_by_heading = {s.heading: s for s in after.sections}
    differing = []
    for section in base.sections:
        if section.heading == skip:
            continue
        other = after_by_heading.get(section.heading)
        if other is None or _fingerprint(other) != _fingerprint(section):
            differing.append(section.heading)
    return differing


#: What a section reports as changed but reads as identical actually was.
#:
#: CANONICAL_DRIFT   the stored content differs — wording, a figure, a table
#:                   cell, a citation. The contract was broken.
#: RENDER_NORMALISED the canonical content is identical and only a rendered or
#:                   re-parsed representation differs — line endings, a
#:                   collapsed newline, a serializer's whitespace. A reporting
#:                   artefact, not an edit.
CANONICAL_DRIFT = "canonical drift"
RENDER_NORMALISED = "render normalisation"


def section_hash(section: D.Section) -> str:
    """The canonical identity of one section.

    Sorted keys, so it cannot disagree with `Document.content_hash` about what
    two sections having the same content means — unlike `_fingerprint`, whose
    `repr(data)` is sensitive to dict insertion order.
    """
    payload = json.dumps(section.as_dict(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    """The identity of a rendered or re-parsed string, for the same comparison."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def first_difference(before: str, after: str) -> dict | None:
    """Where two strings first diverge, with the character on each side.

    A diff that prints two strings which look the same is unactionable, and
    that is exactly what a whitespace or punctuation difference produces. This
    names the offset and shows the codepoint, so "identical" can be
    distinguished from "identical to the eye".
    """
    if before == after:
        return None
    limit = min(len(before), len(after))
    index = next((i for i in range(limit) if before[i] != after[i]), limit)
    return {
        "offset": index,
        "before": before[index:index + 24],
        "after": after[index:index + 24],
        "before_codepoint": (f"U+{ord(before[index]):04X}"
                             if index < len(before) else "end of string"),
        "after_codepoint": (f"U+{ord(after[index]):04X}"
                            if index < len(after) else "end of string"),
        "context": before[max(0, index - 40):index],
    }


def _differing_field(before: D.Section, after: D.Section) -> str:
    """Which field of a section changed first. `_fingerprint`'s own order."""
    if before.heading != after.heading:
        return "heading"
    if before.level != after.level:
        return "level"
    for i, (b, a) in enumerate(zip(before.blocks, after.blocks,
                                   strict=False)):
        for name, left, right in (("kind", b.kind, a.kind),
                                  ("text", b.text, a.text),
                                  ("data", _canonical_data(b.data), _canonical_data(a.data)),
                                  ("sources", tuple(b.sources), tuple(a.sources))):
            if left != right:
                return f"blocks[{i}].{name}"
    if len(before.blocks) != len(after.blocks):
        return "block count"
    return ""


def diff_sections(before: D.Document, after: D.Document) -> list[dict]:
    """Section-by-section, what changed — for a report a person has to read.

    Exists because a live check that says only "v1 intact, v2 written" cannot
    be acted on. Every entry names the section, what happened to it, the text
    on both sides, the canonical hash on both sides, which field diverged
    first, and whether that divergence is canonical drift or a rendering
    artefact — because those two demand opposite fixes and a printed text diff
    alone cannot tell them apart.
    """
    before_by = {s.heading: s for s in before.sections}
    after_by = {s.heading: s for s in after.sections}
    out: list[dict] = []
    for heading, section in before_by.items():
        other = after_by.get(heading)
        if other is None:
            out.append({"section": heading, "change": "dropped",
                        "before": section.text, "after": "",
                        "before_hash": section_hash(section), "after_hash": "",
                        "field": "the whole section",
                        "classification": CANONICAL_DRIFT})
        elif _fingerprint(other) != _fingerprint(section):
            field = _differing_field(section, other)
            out.append({
                "section": heading, "change": "changed",
                "before": section.text, "after": other.text,
                "before_hash": section_hash(section),
                "after_hash": section_hash(other),
                "field": field,
                # Both sides are canonical Sections here, so a fingerprint
                # difference IS canonical drift. The distinction earns its keep
                # one level up, where a caller compares canonical against a
                # rendered or re-parsed representation.
                "classification": CANONICAL_DRIFT,
                "first_difference": first_difference(section.text, other.text),
            })
    for heading, section in after_by.items():
        if heading not in before_by:
            out.append({"section": heading, "change": "added",
                        "before": "", "after": section.text,
                        "before_hash": "", "after_hash": section_hash(section),
                        "field": "the whole section",
                        "classification": CANONICAL_DRIFT})
    return out


def classify(canonical_before: str, canonical_after: str,
             rendered_before: str, rendered_after: str) -> str:
    """Canonical drift, or a rendering artefact — the question a failure asks.

    Canonical hashes decide it. When they agree and the rendered strings do
    not, nothing in the document changed and the difference belongs to the
    renderer or the reader. Deliberately not tolerant: it compares canonical
    identity exactly and never treats differing content as equivalent.
    """
    if canonical_before != canonical_after:
        return CANONICAL_DRIFT
    if rendered_before != rendered_after:
        return RENDER_NORMALISED
    return ""

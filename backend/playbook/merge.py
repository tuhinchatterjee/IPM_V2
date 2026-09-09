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
  figure elsewhere cannot be removed by a revision that never touched it.

What this does not do
---------------------
It does not make the edit correct. The drafted section still goes through
grounding like any other, and an invented figure inside the scope is removed
exactly as before. This bounds the blast radius; it does not lower the bar.
"""

from __future__ import annotations

import copy
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


def _fingerprint(section: D.Section) -> tuple:
    """What "this section is unchanged" means, exactly.

    The heading, the level and every block — kind, text, data and the citation
    locators. Comparing rendered text alone would let a citation or a table
    cell change silently.
    """
    return (section.heading, section.level,
            tuple((b.kind, b.text, repr(b.data), tuple(b.sources))
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
    result = MergeResult(document=merged, target=target.heading)

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


def diff_sections(before: D.Document, after: D.Document) -> list[dict]:
    """Section-by-section, what changed — for a report a person has to read.

    Exists because a live check that says only "v1 intact, v2 written" cannot
    be acted on. Every entry names the section, what happened to it, and the
    text on both sides.
    """
    before_by = {s.heading: s for s in before.sections}
    after_by = {s.heading: s for s in after.sections}
    out: list[dict] = []
    for heading, section in before_by.items():
        other = after_by.get(heading)
        if other is None:
            out.append({"section": heading, "change": "dropped",
                        "before": section.text, "after": ""})
        elif _fingerprint(other) != _fingerprint(section):
            out.append({"section": heading, "change": "changed",
                        "before": section.text, "after": other.text})
    for heading, section in after_by.items():
        if heading not in before_by:
            out.append({"section": heading, "change": "added",
                        "before": "", "after": section.text})
    return out

"""Bring the dashboard into line with a version that was just written. §15.

The gap this closes
-------------------
Gates 4 and 5 built section rows and metric snapshots, and gave them careful
rules about retitles, reopened reviews and readings that are never rewritten.
Nothing called them. `sections.sync` and `compare.freeze` had no caller outside
their own tests, so a document generated through the real authoring path
produced no section rows and froze no readings, and the dashboard beside it
described a workspace nobody had written to.

§15 asks that the dashboard refresh after Claude finishes. It cannot refresh
from state that was never recorded. This module is the one call the authoring
path makes, and it is what makes "the dashboard refreshes" a fact about the
data rather than a promise about a component.

Why it runs in the generation's own transaction
-----------------------------------------------
A version whose section rows were never written is a document the dashboard
misdescribes: sections missing from the Pack, a completed review still
standing against text that no longer exists, a Since Last Time table with no
THEN for the version in front of the reader. That is worse than a failed
generation, which the user can simply run again.

So this is not wrapped in a swallow. If adoption cannot be recorded, the
version is not written either, and the failure is reported. Either the
document and the state that describes it both exist, or neither does.

Nothing here calls a provider, and nothing here decides anything: it records
what the new version says.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.models.playbook import PlaybookMetricBinding
from backend.playbook import document as D
from backend.playbook.intelligence import compare
from backend.playbook.intelligence import sections as sect


@dataclass
class Adoption:
    """What recording the version actually changed. Reported, not inferred."""

    version: int = 0
    sections_written: int = 0
    #: `{key, heading}` per section, not bare keys: the key is what a client
    #: acts on and the heading is what a person reads, and a list carrying
    #: only one of them forces every reader to look up the other.
    sections_changed: list[dict] = field(default_factory=list)
    reviews_reopened: list[dict] = field(default_factory=list)
    metrics_frozen: int = 0

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "sections": self.sections_written,
            "sections_changed": [dict(s) for s in self.sections_changed],
            "reviews_reopened": [dict(s) for s in self.reviews_reopened],
            "metrics_frozen": self.metrics_frozen,
        }


def adopt(session, workspace_id: int, artifact_id: int, *, version_id: int,
          version: int, doc: D.Document) -> Adoption:
    """Record a new version in the dashboard's own terms.

    Sections are synced first: which sections exist, which changed, and whose
    sign-off has to be reopened because the text it covered has moved.

    Metric readings are then frozen against this version — governed bindings
    only, because a suggestion nobody confirmed is not something the document
    relied on. `compare.freeze` never rewrites an existing snapshot, so a
    re-run over the same version returns what was already recorded.
    """
    before = {r.section_key: (r.status, r.last_changed_version)
              for r in sect.rows_for(session, artifact_id)}

    rows = sect.sync(session, artifact_id, doc, version=version)

    changed, reopened = [], []
    for row in rows:
        was = before.get(row.section_key)
        if was is None:
            continue
        named = {"key": row.section_key, "heading": row.heading}
        if row.last_changed_version != was[1]:
            changed.append(named)
        # An approval that no longer stands. Not "left the human-only
        # statuses": `needs_review` is itself one, and it is exactly where a
        # reopened section lands — so testing for departure from that set
        # would report nothing, every time.
        if was[0] == sect.APPROVED and row.status != sect.APPROVED:
            reopened.append(named)

    bindings = (session.query(PlaybookMetricBinding)
                .filter(PlaybookMetricBinding.workspace_id == workspace_id)
                .all())
    snapshots = compare.freeze(session, artifact_id, version_id, version,
                               bindings)

    return Adoption(version=version, sections_written=len(rows),
                    sections_changed=changed, reviews_reopened=reopened,
                    metrics_frozen=len(snapshots))

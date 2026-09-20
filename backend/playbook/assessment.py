"""
What you got, once you had it. Chapters 12 and 16.

A user waited seven minutes, received a Word file and a PDF, and was told
nothing about either. Whether every section they asked for had been written,
which figures the evidence could not account for, which of the seven attached
sources had actually been read, whether anybody had checked any of it, and
where the time had gone — all of it existed in the database and none of it was
ever said.

Two halves, deliberately separate
---------------------------------
**The card is counted.** Sections written, thin and stating a gap; formats
delivered and failed; sources attached, read and cited; figures the grounding
pass could not trace, with the section they are in; the review state; and the
time, split into the provider call and the local render. Every one of those is
read back from a stored row — `progress.of` for the sections and formats, the
version's `source_manifest` for the evidence, its `validation` for the
grounding findings and the timings, `review.of` for who has checked it.
Chapter 12 is explicit that CreditProbe calculates completion from recorded
item states, so nothing here asks a model anything.

**The verdict is written.** One bounded call, given ONLY the card — not the
document, not the evidence, not the conversation — so it has nothing to invent
a number from, and labelled as judgement wherever it is shown. It can be turned
off with `PLAYBOOK_WRITTEN_ASSESSMENT=0` without touching code, and when it
fails the card is delivered anyway: an assessment of the report is not worth
losing the report over.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from backend.playbook import progress as progress_state
from backend.playbook import repository as repo

logger = logging.getLogger(__name__)

#: The written verdict, on unless the deployment says otherwise.
_OFF = {"0", "false", "no", "off"}


def written_enabled() -> bool:
    """Read at call time, not at import, so a test can turn it off."""
    return (os.environ.get("PLAYBOOK_WRITTEN_ASSESSMENT")
            or "1").strip().lower() not in _OFF


#: A paragraph, not a report. The card is the record; this is the reading of
#: it, and an assessment longer than the summary it assesses is noise.
VERDICT_MAX_TOKENS = 700

VERDICT_SYSTEM = """\
You are CreditProbe AI, writing the completion note that appears under a \
document CreditProbe has just delivered.

You are given a record of what was produced. It is the whole of what you know: \
you have not seen the document, the evidence or the conversation. Every number \
below was counted from stored records.

Write at most 150 words, in plain prose, addressed to the person who asked for \
the document. Say what was delivered, what is worth their attention first, and \
what they should do next. Name the specific sections, formats and figures from \
the record.

Do not state any number that is not in the record. Do not estimate, score, or \
give a completion percentage. Do not claim anything was reviewed, approved or \
verified. Do not repeat the record as a list — it is shown beside your note.\
"""


@dataclass
class Card:
    """The counted half. Every field is read back from a row."""

    available: bool = False
    reason: str = ""
    version: int = 0
    title: str = ""
    #: Sections by what they say: written, still thin, or an admission that
    #: the evidence is missing. `gaps` names them, because "3 sections state a
    #: gap" is only useful with the three.
    written: int = 0
    thin: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    #: Formats, and what became of each. Chapter 07's independent outcomes.
    delivered: list[str] = field(default_factory=list)
    failed: dict = field(default_factory=dict)
    #: One row per attached source: was it read in full, and did anything from
    #: it reach this version.
    sources: list[dict] = field(default_factory=list)
    #: What the ledger recorded as not read, carried on the version.
    omissions: list[dict] = field(default_factory=list)
    #: Figures the grounding pass could not trace to evidence, with where they
    #: are. Kept rather than removed — chapter 16 wants them reported.
    untraceable: list[dict] = field(default_factory=list)
    review: dict = field(default_factory=dict)
    #: Milliseconds, named apart so nobody has to guess which is which.
    time: dict = field(default_factory=dict)
    #: The written half. Empty when it is off, and when it failed.
    verdict: str = ""
    verdict_state: str = "off"     # "off" | "written" | "unavailable"

    @property
    def sections(self) -> int:
        return self.written + len(self.thin) + len(self.gaps)

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "version": self.version,
            "title": self.title,
            "sections": {"total": self.sections, "written": self.written,
                         "thin": list(self.thin), "gaps": list(self.gaps)},
            "files": {"delivered": list(self.delivered),
                      "failed": dict(self.failed)},
            "evidence": {"sources": [dict(s) for s in self.sources],
                         "omissions": [dict(o) for o in self.omissions]},
            "untraceable": [dict(f) for f in self.untraceable],
            "review": dict(self.review),
            "time": dict(self.time),
            "verdict": self.verdict,
            "verdict_state": self.verdict_state,
        }

    def brief(self) -> str:
        """The card as the only thing the written verdict is given.

        Plain lines rather than JSON: it is being read, not parsed, and a
        record a person can check is a record that cannot quietly grow a field
        the model treats as a fact about the document.
        """
        out = [f"Document: {self.title or 'untitled'} (version {self.version})"]
        out.append(f"Sections: {self.sections} in total, {self.written} "
                   f"written in full.")
        if self.thin:
            out.append("Sections with very little in them: "
                       + "; ".join(self.thin))
        if self.gaps:
            out.append("Sections that say the evidence for them is missing: "
                       + "; ".join(self.gaps))
        out.append("Files delivered: "
                   + (", ".join(f.upper() for f in self.delivered) or "none"))
        if self.failed:
            out.append("Files that could not be produced: "
                       + "; ".join(f"{f.upper()} ({why})"
                                   for f, why in self.failed.items()))
        for source in self.sources:
            state = "read in full" if source.get("complete") else "read in part"
            cited = ("cited in this version" if source.get("cited")
                     else "nothing from it was cited")
            out.append(f"Source: {source.get('filename', '')} — {state}, "
                       f"{cited}.")
        for gap in self.omissions:
            out.append(f"Evidence not read: {gap.get('what', '')} "
                       f"({gap.get('why', '')})")
        for finding in self.untraceable:
            figures = ", ".join(finding.get("figures") or [])
            out.append(f"Figure with no source, in "
                       f"{finding.get('section') or 'an untitled section'}: "
                       f"{figures}")
        if self.review:
            out.append(f"Review state: {self.review.get('label', 'Draft')}, "
                       f"{self.review.get('open_items', 0)} open item(s). "
                       f"Nobody has approved it.")
        seconds = (self.time.get("total_ms", 0) or 0) / 1000
        out.append(f"Time taken: {seconds:.0f}s in total, of which "
                   f"{(self.time.get('authoring_ms', 0) or 0) / 1000:.0f}s "
                   f"writing and "
                   f"{(self.time.get('render_ms', 0) or 0) / 1000:.0f}s "
                   f"building the files.")
        return "\n".join(out)


def _source_rows(session, workspace_id: int, locators: set[str]) -> list[dict]:
    """Each attached source, how completely it was read, and whether it was
    used.

    "Used" is answered by the version's own `source_manifest`: it records the
    locators that went into the evidence ledger for the run that wrote it, so
    a source that was attached and never reached the document is visible
    rather than implied by its absence.
    """
    rows: list[dict] = []
    for source in repo.sources(session, workspace_id):
        manifest = source.manifest or {}
        mine = {c.locator for c in repo.chunks(session, source.id)}
        rows.append({
            "source_id": source.id,
            "filename": source.filename,
            "role": (source.source_role or "").replace("_", " "),
            "status": source.status,
            "complete": bool(manifest.get("complete")),
            "skipped": [dict(s) for s in (manifest.get("skipped") or [])],
            "chunks": len(mine),
            "cited": len(mine & locators),
        })
    return rows


def of(session, workspace_id: int) -> Card:
    """The counted card for this workspace's current version.

    Never raises for a workspace with no document: that is a real state with a
    real answer, and `progress.of` already says it in words.
    """
    counted = progress_state.of(session, workspace_id)
    if not counted.available:
        return Card(available=False, reason=counted.reason)

    from backend.playbook.intelligence import service as intel

    artifact = intel._current_artifact(session, workspace_id)
    versions = repo.versions(session, artifact.id)
    current = next((v for v in versions
                    if v.id == artifact.current_version_id), None)
    if current is None:                      # pragma: no cover - guarded above
        return Card(available=False, reason="This document has no version.")

    thin, gaps = [], []
    written = 0
    for item in counted.items:
        if item.kind != "content":
            continue
        if item.state == progress_state.NEEDS_INPUT:
            gaps.append(item.label)
        elif item.delivered:
            written += 1
        else:
            thin.append(item.label)

    validation = current.validation or {}
    grounding = validation.get("grounding") or {}
    manifest = current.source_manifest or {}
    timings = validation.get("timings") or {}

    return Card(
        available=True,
        version=current.version,
        title=(current.content or {}).get("title", "") or artifact.title or "",
        written=written,
        thin=thin,
        gaps=gaps,
        delivered=[f for f, state in counted.files.items()
                   if state.get("present")],
        failed={f: (validation.get(f, {}).get("issues") or ["not produced"])[0]
                for f, state in counted.files.items()
                if not state.get("present")},
        sources=_source_rows(session, workspace_id,
                             set(manifest.get("locators") or [])),
        omissions=[dict(o) for o in (manifest.get("omissions") or [])],
        # The first pass's findings: what the draft reached for that the
        # evidence did not support. `removed` is the historical key name.
        untraceable=[{"section": f.get("section", ""),
                      "figures": list(f.get("figures") or [])}
                     for f in (grounding.get("removed") or [])],
        review=dict(counted.review),
        time={
            "authoring_ms": int(timings.get("authoring_ms") or 0),
            "render_ms": int(timings.get("render_ms") or 0),
            "provider_ms": int(timings.get("provider_ms") or 0),
            "total_ms": int(timings.get("authoring_ms") or 0)
            + int(timings.get("render_ms") or 0),
        },
    )


def write_verdict(card: Card) -> Card:
    """Add the written half, in one bounded call.

    The model is given `card.brief()` and nothing else. It cannot describe the
    document because it has not seen the document; it is reading the record,
    which is the only thing that makes this safe to show beside measurements.

    A failure here is not a failure of the run. The card is returned as it
    came in, with `verdict_state` saying what happened, and the caller carries
    on delivering the files.
    """
    if not card.available or not written_enabled():
        return card

    from backend.llm import roles as role_config
    from backend.playbook import provider

    try:
        role = role_config.role(role_config.AUTHOR)
        if not (role.model or ""):
            card.verdict_state = "unavailable"
            return card
        response = provider._call(
            provider._client(), model=role.model, system=VERDICT_SYSTEM,
            messages=[{"role": "user", "content": card.brief()}],
            tools=[], container={}, purpose="playbook_assessment", role=role,
            max_tokens=VERDICT_MAX_TOKENS)
        text = provider._text(response).strip()
    except Exception:  # noqa: BLE001 — never lose a report over its summary
        logger.exception("Playbook could not write a completion assessment")
        card.verdict_state = "unavailable"
        return card

    card.verdict = text
    card.verdict_state = "written" if text else "unavailable"
    return card


def for_delivery(session, workspace_id: int) -> dict:
    """The card, with its verdict, ready to carry on a message.

    One entry point for the delivery path so the two halves cannot be shown
    apart — a written judgement with no measurements beside it is exactly the
    thing chapter 12 forbids.
    """
    card = of(session, workspace_id)
    if card.available:
        card = write_verdict(card)
    return card.as_dict()

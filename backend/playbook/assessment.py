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

from backend.models.playbook import PlaybookArtifactVersion
from backend.playbook import document as D
from backend.playbook import progress as progress_state
from backend.playbook import repository as repo
from backend.playbook import review as review_state

#: The formats a version can carry. Kept here rather than imported from the
#: capability registry: this is reading a stored record, not deciding what
#: may be produced.
FORMATS = frozenset({"docx", "pdf", "pptx", "xlsx"})

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
        out.append(
            f"Time taken: {_spoken(self.time.get('total_ms'))} in total, of "
            f"which {_spoken(self.time.get('authoring_ms'))} writing and "
            f"{_spoken(self.time.get('render_ms'))} building the files.")
        return "\n".join(out)


def _spoken(ms: int | None) -> str:
    """A duration as the note should say it.

    "0s" reads as a measurement that failed rather than one that was small,
    and a cached or scripted run really does take a few milliseconds.
    """
    ms = int(ms or 0)
    if ms and ms < 1000:
        return "under a second"
    seconds = round(ms / 1000)
    return (f"{seconds // 60}m {seconds % 60}s" if seconds >= 60
            else f"{seconds}s")


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


def _version_for(session, workspace_id: int, version_id: int | None):
    """The version this card is about, and the artifact it belongs to.

    A turn names the version it just wrote. Without that the card would be
    read off whatever the workspace's CURRENT artifact happens to be — which,
    for a turn that produced a deck, is the report it was made from, and the
    card would then describe files the message did not deliver.
    """
    from backend.models.playbook import PlaybookArtifact
    from backend.playbook.intelligence import service as intel

    if version_id is not None:
        version = session.get(PlaybookArtifactVersion, version_id)
        if version is None:
            return None, None
        artifact = session.get(PlaybookArtifact, version.artifact_id)
        if artifact is None or artifact.workspace_id != workspace_id:
            return None, None
        return version, artifact

    artifact = intel._current_artifact(session, workspace_id)
    if artifact is None or artifact.current_version_id is None:
        return None, None
    return session.get(PlaybookArtifactVersion,
                       artifact.current_version_id), artifact


def of(session, workspace_id: int, *, version_id: int | None = None) -> Card:
    """The counted card for one version — the one a turn wrote, or the
    workspace's current one.

    Never raises for a workspace with no document: that is a real state with
    a real answer, and saying it is better than filling it with noughts.
    """
    version, artifact = _version_for(session, workspace_id, version_id)
    if version is None:
        return Card(available=False,
                    reason="No document deliverable has been produced yet.")

    doc = D.Document.from_dict(version.content or {})
    thin, gaps = [], []
    written = 0
    # The same rule the dashboard counts by, from the same function: a
    # section that says something is written, and one whose whole body is an
    # admission that the evidence is missing is not.
    for ordinal, section in enumerate(doc.sections, start=1):
        state, _ = progress_state._section_state(section)
        label = section.heading or f"Section {ordinal}"
        if state == progress_state.NEEDS_INPUT:
            gaps.append(label)
        elif state in progress_state.COUNTS:
            written += 1
        else:
            thin.append(label)

    validation = version.validation or {}
    grounding = validation.get("grounding") or {}
    manifest = version.source_manifest or {}
    timings = validation.get("timings") or {}

    # A format that was attempted and failed leaves no file row, so the
    # attempt is read from the stored validation record rather than vanishing.
    files = {f.format: f for f in repo.files(session, version.id)}
    attempted = sorted(set(files) | {f for f in validation if f in FORMATS})
    state = review_state.of(version)

    return Card(
        available=True,
        version=version.version,
        title=(version.content or {}).get("title", "") or artifact.title or "",
        written=written,
        thin=thin,
        gaps=gaps,
        delivered=[f for f in attempted if f in files],
        failed={f: (validation.get(f, {}).get("issues") or ["not produced"])[0]
                for f in attempted if f not in files},
        sources=_source_rows(session, workspace_id,
                             set(manifest.get("locators") or [])),
        omissions=[dict(o) for o in (manifest.get("omissions") or [])],
        # The first pass's findings: what the draft reached for that the
        # evidence did not support. `removed` is the stored key's name.
        untraceable=[{"section": f.get("section", ""),
                      "figures": list(f.get("figures") or [])}
                     for f in (grounding.get("removed") or [])],
        review={"state": state.state, "label": state.label,
                "summary": state.summary(), "open_items": state.open_items,
                "by": state.by},
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


def for_delivery(session, workspace_id: int, *,
                 version_id: int | None = None) -> dict:
    """The card, with its verdict, ready to carry on a message.

    One entry point for the delivery path so the two halves cannot be shown
    apart — a written judgement with no measurements beside it is exactly the
    thing chapter 12 forbids.
    """
    card = of(session, workspace_id, version_id=version_id)
    if card.available:
        card = write_verdict(card)
    return card.as_dict()

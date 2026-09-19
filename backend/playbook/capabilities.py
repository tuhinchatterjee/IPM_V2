"""
What Playbook can actually produce, and by which route. Playbook §11.

An explicit registry, because the alternative is a product that says yes to
every format and produces a renamed text file for the ones it cannot do. A
request for something not listed here gets a truthful refusal naming what IS
available — which is a better answer than a file that will not open.

Two routes, and the difference is recorded on every file
--------------------------------------------------------
`SKILL` — Anthropic's document Skills running in the code-execution container.
This is the route that writes genuinely well-composed documents, because the
model is authoring the file rather than filling a fixed template.

`LOCAL` — this repository's own writers: `backend/reporting/writers.py` for
Word and PDF, `backend/exports/results.py`'s conventions for workbooks, and
python-pptx for decks. Deterministic, offline, and used for three things: demo
seeding (which must make no provider call at all), operation with no provider
configured, and as the fallback when a Skill's output fails validation.

Every stored file records which route produced it, because "written by a
document Skill" and "rendered locally" are different claims and only one of
them is true of any given file.
"""

from __future__ import annotations

from dataclasses import dataclass

DOCX = "docx"
PDF = "pdf"
PPTX = "pptx"
XLSX = "xlsx"

SKILL = "anthropic_skill"
LOCAL = "local"

MIME = {
    DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    PDF: "application/pdf",
    PPTX: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

#: The Anthropic Skill that writes each format. These ids are the provider's,
#: verified against its current documentation rather than remembered.
SKILL_ID = {DOCX: "docx", PDF: "pdf", PPTX: "pptx", XLSX: "xlsx"}


@dataclass(frozen=True)
class Capability:
    format: str
    mime: str
    #: Routes that can produce this format, best first.
    routes: tuple[str, ...]
    description: str


REGISTRY: dict[str, Capability] = {
    DOCX: Capability(
        DOCX, MIME[DOCX], (SKILL, LOCAL),
        "Word reports with heading styles, tables and source references.",
    ),
    PDF: Capability(
        PDF, MIME[PDF], (SKILL, LOCAL),
        "A PDF carrying the same facts and findings as the Word revision.",
    ),
    PPTX: Capability(
        PPTX, MIME[PPTX], (SKILL, LOCAL),
        "Editable PowerPoint with native text and tables — never flattened "
        "to pictures.",
    ),
    XLSX: Capability(
        XLSX, MIME[XLSX], (SKILL, LOCAL),
        "A workbook of the analysis tables behind a report.",
    ),
}

SUPPORTED: tuple[str, ...] = (DOCX, PDF, PPTX, XLSX)


class UnsupportedFormat(ValueError):
    """A format Playbook does not produce. The message is shown to the user."""


def require(fmt: str) -> Capability:
    """The capability for a requested format, or a refusal that says what is
    available instead."""
    key = (fmt or "").strip().lower().lstrip(".")
    if key in REGISTRY:
        return REGISTRY[key]
    raise UnsupportedFormat(
        f"Playbook does not produce .{key or 'that'} files. It produces "
        + ", ".join(f".{f}" for f in SUPPORTED)
        + "."
    )


def describe() -> dict:
    """What the interface shows about output formats. Never a credential."""
    return {
        "formats": [
            {
                "format": c.format,
                "mime": c.mime,
                "routes": list(c.routes),
                "description": c.description,
            }
            for c in REGISTRY.values()
        ],
        "unsupported": unsupported(),
    }


#: Things a reader might reasonably expect a chat assistant to do, which this
#: deployment does not do at all. Chapter 02's third state, and the reason it
#: is written down: an audit that lists only what exists cannot distinguish
#: "we looked and there is no web search" from "nobody asked". DC-13 turns on
#: exactly that distinction — disabled research must not be simulated — and
#: `chat._capability_note()` tells the assistant the same thing, so a question
#: about a search gets a plain no rather than a description of one.
#:
#: A capability moves off this list by being built, not by being promised.
NOT_SUPPORTED: dict[str, str] = {
    "research": "There is no web search or browsing. Nothing in a Playbook "
                "answer comes from outside the workspace's own files, "
                "exported analyses and conversation.",
    "email": "Playbook cannot send mail.",
    "connectors": "There are no third-party connectors.",
    "sharing": "Playbook cannot share anything outside the workspace. Files "
               "are downloaded by a person who is already permitted to see "
               "them.",
}

#: Deliberately NOT on that list: code execution. It is a real capability with
#: two runtime states, and `documents.report()` already publishes which one
#: this deployment is in. Naming it here as well would put the same question
#: in two places that can disagree — the failure this registry exists to
#: prevent.


def unsupported() -> dict:
    """The capabilities this deployment does not have, said out loud."""
    return {name: {"state": "not_supported", "detail": detail}
            for name, detail in sorted(NOT_SUPPORTED.items())}


def supported() -> tuple[str, ...]:
    """The formats this deployment can actually produce.

    A function rather than the constant, because chapter 02 asks the product to
    state what is Implemented as opposed to Available but disabled, and that is
    a runtime fact. Today every registered format has a local renderer, so the
    answer is the whole set; when one stops being true this is the one place
    that has to change.
    """
    return tuple(f for f in SUPPORTED if f in REGISTRY)

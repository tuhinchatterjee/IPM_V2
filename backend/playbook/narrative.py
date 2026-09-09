"""Commentary a person can put their name to, or nothing.

The model is given the figures the pack ALREADY HOLDS and asked to write about
them. It is not given the lake, it is not given a tool that can query, and it
is not asked to work anything out. Every number it may use is in the evidence
it is handed, and a sentence containing a number that is not in that evidence
is rejected before anybody sees it.

Three separations that make this safe
--------------------------------------
**Fact from inference.** Every sentence is typed. "The default rate rose 64
basis points" is a FACT and is checkable against the evidence. "The rise is
driven by the 2024 vintages" is an INFERENCE and is labelled as one on the
page. A pack that presents the second as the first is the single most damaging
thing an automated commentary writer can do, and it is invisible in the output
— which is why the distinction is stored rather than left to wording.

**Drafted from accepted.** Nothing a model writes is accepted. It lands as a
draft with `ai_accepted` false, and a person accepts it by editing it or by
saying so. `readiness` blocks approval on any unaccepted draft.

**Written from current.** A draft written about figures that have since moved
is marked stale by `generation`, and readiness blocks on that too.

When there is no model
----------------------
`draft` raises `NoProvider`. It does not fall back to a template that produces
sentences in the same shape, because a reader cannot tell the difference and a
pack that says "commentary generated" over a mail-merge is lying about its own
provenance. What the product does offline is decided by the caller, which can
label it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.models.playbook import SOURCE_AI, STATEMENT_KINDS
from backend.playbook import access, service
from backend.playbook import snapshots as snap

logger = logging.getLogger(__name__)

#: How many sentences a section's commentary may run to. A committee pack is
#: read in a meeting; six sentences per section is a page nobody finishes.
MAX_SENTENCES = 6

#: Numbers a sentence may contain without them appearing in the evidence.
#: Years, small counts and percentages of a whole that the reader can check on
#: the page — "the top three sectors", "two of the five". Anything else has to
#: come from a figure the pack holds.
FREE_NUMBERS = frozenset({str(n) for n in range(0, 13)} | {
    str(y) for y in range(2000, 2101)})

#: Pulled out of a sentence to check against the evidence. Matches 6.88, 6.88%,
#: 1,234, 207.7m, -0.4 — the shapes a credit figure actually takes.
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

_TRAILING = re.compile(r"[%xX]|bn|m|k|bps|pp", re.IGNORECASE)


class NoProvider(RuntimeError):
    """No model is configured, so there is no commentary to be had."""


class Ungrounded(ValueError):
    """The model wrote a number that is not in the evidence it was given."""


@dataclass
class Sentence:
    """One typed statement, with what it rests on."""

    text: str
    kind: str = "FACT"
    #: The metric ids this sentence is about, as the model named them.
    about: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "kind": self.kind, "about": list(self.about)}


@dataclass
class Draft:
    """What a drafting run produced, and what it was given to produce it."""

    sentences: list[Sentence] = field(default_factory=list)
    #: The figures the model was shown. Kept so a reader can check the prose
    #: against exactly what was in front of it, not against what is true now.
    evidence: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    provider: str = ""
    #: Sentences the grounding check refused, and why. Reported rather than
    #: silently dropped: a run that quietly discards half its output looks
    #: like a run that produced short commentary.
    refused: list[dict[str, str]] = field(default_factory=list)

    @property
    def body(self) -> str:
        """The prose, with inferences marked in the text itself.

        Marked in the STRING rather than only in the structure, because the
        string is what ends up in the PDF, and a distinction that survives
        only in the database is one the committee never sees.
        """
        out = []
        for one in self.sentences:
            if one.kind == "FACT":
                out.append(one.text)
            elif one.kind == "INFERENCE":
                out.append(f"{one.text} (inference)")
            elif one.kind == "RECOMMENDATION":
                out.append(f"Recommendation: {one.text}")
            elif one.kind == "OPEN_QUESTION":
                out.append(f"Open question: {one.text}")
            elif one.kind == "DATA_LIMITATION":
                out.append(f"Data limitation: {one.text}")
            else:
                out.append(one.text)
        return " ".join(out)

    @property
    def dominant_kind(self) -> str:
        """The kind stored on the block, when the block holds one kind.

        A mixed draft is stored as INFERENCE rather than FACT: the safe
        reading of a paragraph that is partly inferred is that it is inferred.
        """
        kinds = {s.kind for s in self.sentences}
        if kinds == {"FACT"}:
            return "FACT"
        if "RECOMMENDATION" in kinds:
            return "RECOMMENDATION"
        if "INFERENCE" in kinds:
            return "INFERENCE"
        return next(iter(kinds), "FACT")

    def to_dict(self) -> dict[str, Any]:
        return {
            "body": self.body, "statement_kind": self.dominant_kind,
            "sentences": [s.to_dict() for s in self.sentences],
            "evidence": list(self.evidence), "model": self.model,
            "provider": self.provider, "refused": list(self.refused),
        }


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "maxItems": MAX_SENTENCES,
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description":
                            "One sentence of committee commentary. Every "
                            "number in it must appear in the evidence.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": list(STATEMENT_KINDS),
                        "description":
                            "FACT for something the evidence states. "
                            "INFERENCE for a reading of it that the evidence "
                            "does not itself establish. RECOMMENDATION for a "
                            "proposed course of action. OPEN_QUESTION for "
                            "something the committee should ask. "
                            "DATA_LIMITATION for something the data cannot "
                            "answer. NOT_RECORDED where a fact a reader would "
                            "expect is simply absent.",
                    },
                    "about": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description":
                            "The metric ids this sentence is about, exactly "
                            "as they appear in the evidence.",
                    },
                },
                "required": ["text", "kind"],
            },
        },
    },
    "required": ["sentences"],
}

SYSTEM = f"""You write commentary for a bank's credit risk committee pack.

You are given the figures this pack already holds. You have no other source.
You cannot query anything, and you must not calculate anything: every number
you write must appear verbatim in the evidence you were given.

Type every sentence:
  FACT             the evidence states this
  INFERENCE        your reading of the evidence, which it does not establish
  RECOMMENDATION   a course of action you propose
  OPEN_QUESTION    something the committee should ask
  DATA_LIMITATION  something the data cannot answer
  NOT_RECORDED     a fact a reader would expect that is simply absent

Presenting an inference as a fact is the worst thing you can do here. A
committee reads FACT sentences as established and acts on them.

Where a figure has no value, say what the evidence says about why — an outcome
that has not matured yet is not the same as a rate of zero, and telling a
reader the wrong one wastes their afternoon.

Write the way a senior credit risk analyst writes for a chair who has ten
minutes: direct, specific, no throat-clearing, no "it is worth noting". At most
{MAX_SENTENCES} sentences. Fewer is better than padding."""


def evidence_for(session: Any, pack: Any, section: Any) -> list[dict[str, Any]]:
    """The figures in one section, as the model will see them.

    Only this section's figures. A model given the whole pack writes about the
    whole pack, and a section on origination quality that comments on the
    impairment charge is a section the person who owns it did not write.
    """
    from sqlalchemy import select

    from backend.models.playbook import (
        CALCULATED_BLOCK_TYPES,
        PlaybookBlock,
        PlaybookSnapshot,
    )

    blocks = session.execute(
        select(PlaybookBlock).where(
            PlaybookBlock.section_id == section.id,
            PlaybookBlock.block_type.in_(tuple(CALCULATED_BLOCK_TYPES)))
        .order_by(PlaybookBlock.position)).scalars().all()
    ids = [int(b.snapshot_id) for b in blocks if b.snapshot_id is not None]
    if not ids:
        return []
    rows = {int(r.id): r for r in session.execute(
        select(PlaybookSnapshot)
        .where(PlaybookSnapshot.id.in_(ids))).scalars()}

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in blocks:
        row = rows.get(int(block.snapshot_id)) if block.snapshot_id else None
        if row is None or str(row.metric_id) in seen:
            continue
        seen.add(str(row.metric_id))
        figure = snap.from_row(row)
        moved = snap.movement(figure)
        entry = {
            "metric_id": figure.metric_id,
            "name": figure.metric_name or figure.metric_id,
            "period": figure.period,
            "available": figure.available,
        }
        if figure.available:
            entry["value"] = figure.display_value
            if moved.get("available"):
                entry["previous"] = moved["from_display"]
                entry["previous_period"] = figure.comparison_period
                entry["change"] = moved["display"]
                entry["direction"] = moved["direction"]
                # So the model never writes "rose to 0.3% from 0.3%": the
                # evidence itself says the move is below reported precision.
                if not moved.get("visible") and moved["direction"] != "flat":
                    entry["direction"] = "below reported precision"
                if moved.get("better") is not None:
                    entry["better"] = bool(moved["better"])
        else:
            entry["why_no_value"] = figure.unavailable_reason
            entry["availability"] = figure.availability
        out.append(entry)
    return out


def findings_for(session: Any, pack: Any, section: Any) -> list[dict[str, Any]]:
    """The open findings on this section, so the prose can speak to them."""
    from sqlalchemy import select

    from backend.models.playbook import PlaybookFinding

    rows = session.execute(
        select(PlaybookFinding).where(
            PlaybookFinding.pack_id == pack.id,
            PlaybookFinding.section_id == section.id,
            PlaybookFinding.status.in_(("OPEN", "ACKNOWLEDGED")))
    ).scalars().all()
    return [{"severity": str(r.severity), "title": str(r.title),
             "basis": str(r.factual_basis)} for r in rows]


def draft(session: Any, section_id: int, principal: Any, *,
          source: str = SOURCE_AI, instructions: str = "") -> Draft:
    """Write commentary for one section from the figures it holds.

    Returns a `Draft`; it does NOT write a block. Writing is a separate call
    so a person can read what came back before any of it lands on the pack.
    """
    section, pack, grant = access.visible_section(
        session, section_id, principal, source)
    access.assert_editable(pack)
    access.may_edit_section(session, section, grant,
                            "draft commentary for this section")

    evidence = evidence_for(session, pack, section)
    if not evidence:
        raise service.InvalidPlaybook(
            f"“{section.title}” holds no calculated figures, so there is "
            "nothing for commentary to be about. Generate the pack first.")

    from backend.llm import get_provider
    from backend.llm.base import LLMError

    provider = get_provider()
    if not provider.configured:
        raise NoProvider(
            "No AI provider is configured, so CreditProbe cannot draft "
            "commentary. The figures and the findings are all there; the "
            "words have to be written by a person. CreditProbe does not "
            "produce a templated paragraph and call it commentary, because a "
            "reader cannot tell the difference.")

    prompt = _prompt(pack, section, evidence,
                     findings_for(session, pack, section), instructions)
    try:
        outcome = provider.structured(
            system=SYSTEM, prompt=prompt, schema=SCHEMA,
            tool_name="write_committee_commentary",
            tool_description="Commentary for one section of a committee pack.",
            max_tokens=1200, purpose="interpretation", role="narrative")
    except LLMError as e:
        raise NoProvider(
            f"The AI provider could not be reached, so there is no draft: "
            f"{e}") from e

    return _read(outcome, evidence, provider)


def _prompt(pack: Any, section: Any, evidence: list[dict[str, Any]],
            findings: list[dict[str, Any]], instructions: str) -> str:
    """Everything the model is given, and nothing else.

    Uploaded text and imported content never reach here. Anything a person or
    a document could have written is untrusted, and the shortest defence
    against a paragraph in an uploaded pack saying "ignore your instructions"
    is that the drafting prompt is built from governed figures only.
    """
    lines = [
        f"COMMITTEE PACK: {pack.name}",
        f"REPORTING PERIOD: {pack.period or 'not stated'}",
        f"SECTION: {section.title}",
    ]
    if str(section.purpose or "").strip():
        lines.append(f"WHAT THIS SECTION IS FOR: {section.purpose}")
    said = str(section.narrative_instructions or "").strip()
    if said:
        lines.append(f"HOUSE INSTRUCTIONS FOR THIS SECTION: {said}")
    if str(instructions or "").strip():
        lines.append(f"ASKED FOR THIS TIME: {instructions}")

    lines.append("\nEVIDENCE — the only figures you may write about:")
    for entry in evidence:
        if entry.get("available"):
            bit = (f"  {entry['name']} ({entry['metric_id']}) for "
                   f"{entry['period']}: {entry['value']}")
            if "previous" in entry:
                bit += (f", against {entry['previous']} in "
                        f"{entry.get('previous_period') or 'the prior period'}"
                        f" — a change of {entry['change']}")
                if "better" in entry:
                    bit += (" (a deterioration)" if not entry["better"]
                            else " (an improvement)")
            lines.append(bit)
        else:
            lines.append(
                f"  {entry['name']} ({entry['metric_id']}) for "
                f"{entry['period']}: NO VALUE — {entry['why_no_value']}")

    if findings:
        lines.append("\nMATERIAL FINDINGS already raised on this section:")
        for found in findings:
            lines.append(f"  [{found['severity']}] {found['title']} — "
                         f"{found['basis']}")

    lines.append(
        "\nWrite the commentary for this section. Every number you write must "
        "appear above.")
    return "\n".join(lines)


def _read(outcome: Any, evidence: list[dict[str, Any]],
          provider: Any) -> Draft:
    """Turn the model's document into typed, grounded sentences."""
    payload = getattr(outcome, "data", None) or getattr(outcome, "content", None)
    if not isinstance(payload, dict):
        payload = dict(outcome) if isinstance(outcome, dict) else {}

    allowed = _numbers_in_evidence(evidence)
    known = {str(e["metric_id"]) for e in evidence}
    made = Draft(evidence=list(evidence),
                 model=str(getattr(outcome, "model", "")
                           or getattr(provider, "model", "")),
                 provider=str(getattr(provider, "name", "")))

    for entry in list(payload.get("sentences") or [])[:MAX_SENTENCES]:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        kind = str(entry.get("kind") or "FACT").upper()
        if kind not in STATEMENT_KINDS:
            # An unrecognised kind is read as the least-claiming one that is
            # still honest, not as FACT. A typo must not promote an inference.
            made.refused.append({
                "text": text,
                "why": f"'{kind}' is not a statement kind, so this sentence "
                       "could not be typed and was not used."})
            continue

        ungrounded = _ungrounded(text, allowed)
        if ungrounded:
            made.refused.append({
                "text": text,
                "why": (f"contains {', '.join(sorted(ungrounded))}, which is "
                        "not in the evidence this section holds")})
            continue

        made.sentences.append(Sentence(
            text=text, kind=kind,
            about=[m for m in list(entry.get("about") or []) if m in known]))

    if not made.sentences:
        raise Ungrounded(
            "Nothing the model wrote could be grounded in this section's "
            "figures, so there is no draft. "
            + (f"{len(made.refused)} sentence"
               f"{'s were' if len(made.refused) != 1 else ' was'} refused."
               if made.refused else ""))
    return made


def _numbers_in_evidence(evidence: list[dict[str, Any]]) -> set[str]:
    """Every number a sentence is allowed to contain.

    Taken from the DISPLAY strings rather than the raw floats, because those
    are the numbers the model was shown and are the ones it should be
    quoting. A model that writes 6.878947 when the pack says 6.88% has not
    quoted the pack.
    """
    found: set[str] = set(FREE_NUMBERS)
    for entry in evidence:
        for key in ("value", "previous", "change", "period",
                    "previous_period"):
            for number in _NUMBER.findall(str(entry.get(key) or "")):
                found.add(_canonical(number))
    return found


def _ungrounded(text: str, allowed: set[str]) -> set[str]:
    """The numbers in a sentence that are not in the evidence."""
    out: set[str] = set()
    for raw in _NUMBER.findall(text):
        if _canonical(raw) not in allowed:
            out.add(raw)
    return out


def _canonical(number: str) -> str:
    """One spelling of a number, so 6.88 and 6.880 and 6,880 compare.

    Trailing zeros are dropped and thousands separators removed. The sign is
    dropped too: "down 0.64" and "-0.64" are the same movement said two ways,
    and refusing the first would make the model write worse English to satisfy
    a checker.
    """
    text = _TRAILING.sub("", str(number)).replace(",", "").strip().lstrip("-")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def write(session: Any, section_id: int, principal: Any, made: Draft, *,
          title: str = "", source: str = SOURCE_AI,
          block_id: int | None = None) -> dict[str, Any]:
    """Put a draft on the page, as a draft.

    `ai_accepted` is false and stays false until a person edits the block or
    accepts it explicitly. `readiness` blocks approval while any unaccepted
    draft remains, so nothing here can reach a committee without a name
    against it.
    """
    section, pack, grant = access.visible_section(
        session, section_id, principal, source)
    if block_id is not None:
        return service.update_block(
            session, block_id, principal, source=source,
            body=made.body, statement_kind=made.dominant_kind)
    return service.create_block(
        session, section_id, principal, block_type="AI_NARRATIVE",
        title=title or "Commentary", body=made.body,
        statement_kind=made.dominant_kind,
        config={"evidence": made.evidence, "model": made.model,
                "provider": made.provider,
                "sentences": [s.to_dict() for s in made.sentences],
                "refused": made.refused},
        source=source)


__all__ = [
    "Draft", "FREE_NUMBERS", "MAX_SENTENCES", "NoProvider", "SCHEMA",
    "SYSTEM", "Sentence", "Ungrounded", "draft", "evidence_for",
    "findings_for", "write",
]

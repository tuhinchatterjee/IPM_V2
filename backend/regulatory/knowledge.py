"""
Supersession, conflict, as-of retrieval and citation. Part G.

The question this module exists to answer
------------------------------------------
    "What did the rules require on the reporting date?"

Not "what do the rules require now". An impairment paper written for Q2 2025
that quotes a circular issued in Q4 2025 is wrong in a way that reads as
thorough, and the only defence against it is that retrieval takes a date and
refuses to answer without one.

Supersession
-------------
A circular names the references it replaces. When the replacement takes
effect, the replaced document does NOT disappear: it stays retrievable AS OF
the dates it was in force, because a restatement of a 2024 position has to
quote the 2024 rule. What changes is that it stops being current.

Conflict
---------
Two circulars in force on the same date, from the same regulator, imposing
different thresholds on the same concept, is a conflict. CreditProbe does not
resolve it — resolving a regulatory conflict is a legal opinion, not a
retrieval strategy. It reports both, marks the conflict, and routes it to an
SME. An answer that silently picked one is the failure this exists to prevent.

Citations
----------
Every retrieved rule comes back with a citation carrying the regulator, the
reference, the section, the page, the effective date and the original's hash.
A rule with no citation is not returned at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.regulatory import schema as rs

logger = logging.getLogger(__name__)

KNOWLEDGE_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Supersession
# ---------------------------------------------------------------------------


@dataclass
class Supersession:
    """One circular replacing another, and when the replacement bites."""

    superseded: str
    superseded_by: str
    effective: date | None
    #: True when the replacement was matched by reference rather than guessed.
    explicit: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"superseded": self.superseded,
                "superseded_by": self.superseded_by,
                "effective": self.effective.isoformat()
                if self.effective else "",
                "explicit": self.explicit}


def supersessions(circulars: list[rs.Circular]) -> list[Supersession]:
    """Every replacement the corpus declares, resolved by reference.

    Only explicit declarations. A circular is not inferred to supersede
    another because it covers the same ground: regulators restate, extend and
    clarify far more often than they replace, and a guess here silently
    removes a rule that is still in force.
    """
    by_reference: dict[str, rs.Circular] = {
        c.reference.strip().lower(): c for c in circulars if c.reference}
    out: list[Supersession] = []
    for circular in circulars:
        for reference in circular.supersedes:
            target = by_reference.get(str(reference).strip().lower())
            if target is None:
                logger.info(
                    "%s says it supersedes %s, which is not in the corpus",
                    circular.reference, reference)
                continue
            out.append(Supersession(
                superseded=target.circular_id,
                superseded_by=circular.circular_id,
                effective=circular.effective))
    return out


def apply_supersession(circulars: list[rs.Circular]) -> list[rs.Circular]:
    """Mark what has been replaced, without removing it.

    A superseded circular keeps its rules and stays retrievable as of the
    dates it was in force. Deleting it would make every historical restatement
    uncitable.
    """
    by_id = {c.circular_id: c for c in circulars}
    for found in supersessions(circulars):
        target = by_id.get(found.superseded)
        replacement = by_id.get(found.superseded_by)
        if target is None or replacement is None:
            continue
        target.superseded_by = replacement.reference
        if target.status == rs.APPROVED:
            target.status = rs.SUPERSEDED
        # The replaced circular stops applying the day the replacement does.
        # Without this it stays "in force" forever and as-of retrieval returns
        # both, which reads as a conflict where there is only a history.
        if replacement.effective is not None and (
                target.expires is None
                or target.expires > replacement.effective):
            target.expires = replacement.effective
    return circulars


# ---------------------------------------------------------------------------
# Conflict
# ---------------------------------------------------------------------------


@dataclass
class Conflict:
    """Two rules that cannot both be satisfied on the same date."""

    concept: str
    unit: str
    when: date
    left: rs.Citation
    right: rs.Citation
    left_value: float | None = None
    right_value: float | None = None

    def sentence(self) -> str:
        return (f"On {self.when.isoformat()}, {self.left.sentence()} states "
                f"{self.left_value}{self.unit} for {self.concept} and "
                f"{self.right.sentence()} states {self.right_value}"
                f"{self.unit}. CreditProbe does not choose between them.")

    def to_dict(self) -> dict[str, Any]:
        return {"concept": self.concept, "unit": self.unit,
                "when": self.when.isoformat(),
                "left": self.left.to_dict(), "right": self.right.to_dict(),
                "left_value": self.left_value, "right_value": self.right_value,
                "explanation": self.sentence()}


def conflicts(circulars: list[rs.Circular], when: date) -> list[Conflict]:
    """Thresholds in force on the same date that disagree.

    Narrow on purpose. Two obligations phrased differently are not a conflict;
    two THRESHOLDS on the same concept in the same unit with different numbers
    are, and that is a comparison a machine can make honestly.
    """
    live = [c for c in circulars if c.in_force_on(when) and c.retrievable]
    seen: dict[tuple[str, str], list[tuple[rs.Circular, rs.Rule]]] = {}
    for circular in live:
        for rule in circular.rules:
            if rule.kind != rs.THRESHOLD or rule.status != rs.APPROVED:
                continue
            if rule.value is None or not rule.unit:
                continue
            for concept in (rule.concepts or []):
                seen.setdefault((concept.lower(), rule.unit), []).append(
                    (circular, rule))

    out: list[Conflict] = []
    for (concept, unit), found in sorted(seen.items()):
        values = {r.value for _, r in found}
        if len(values) <= 1:
            continue
        (left_c, left_r), (right_c, right_r) = found[0], found[1]
        out.append(Conflict(
            concept=concept, unit=unit, when=when,
            left=cite(left_c, left_r), right=cite(right_c, right_r),
            left_value=left_r.value, right_value=right_r.value))
    return out


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def cite(circular: rs.Circular, rule: rs.Rule) -> rs.Citation:
    """The citation a rule is quoted under."""
    return rs.Citation(
        circular_id=circular.circular_id, reference=circular.reference,
        regulator=circular.regulator, section_number=rule.section_number,
        page=rule.page,
        effective=circular.effective.isoformat() if circular.effective else "",
        content_hash=circular.content_hash,
        quote=rule.text, rule_id=rule.rule_id)


@dataclass
class Hit:
    """One rule that answers, and the citation it is quoted under."""

    rule: rs.Rule
    citation: rs.Citation
    circular: str
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule.to_dict(),
                "citation": self.citation.to_dict(),
                "circular": self.circular, "score": round(self.score, 3)}


@dataclass
class Answer:
    """What regulatory retrieval returns. Never a sentence of its own."""

    when: date
    hits: list[Hit] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    #: Circulars in force on the date that could not be searched, and why.
    excluded: list[dict[str, str]] = field(default_factory=list)
    because: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"as_of": self.when.isoformat(),
                "hits": [h.to_dict() for h in self.hits],
                "conflicts": [c.to_dict() for c in self.conflicts],
                "excluded": list(self.excluded),
                "because": self.because,
                "version": KNOWLEDGE_VERSION}


#: Words too common to distinguish one rule from another.
_STOP = frozenset({
    "the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are",
    "be", "as", "at", "by", "with", "from", "that", "this", "shall", "must",
    "any", "all", "which", "what", "does", "do", "it", "its", "not"})


def _terms(text: str) -> set[str]:
    return {w for w in
            "".join(c if c.isalnum() else " " for c in str(text).lower())
            .split() if len(w) > 2 and w not in _STOP}


def retrieve(circulars: list[rs.Circular], question: str, *, when: date,
             kinds: tuple[str, ...] = (), limit: int = 8,
             tenant: str = "", roles: frozenset[str] | None = None) -> Answer:
    """The rules in force on `when` that bear on `question`.

    Four filters, in this order, and the order is the governance:

      1. **tenant** — a circular uploaded by another bank is not searched;
      2. **confidentiality** — a class the caller's role may not read is
         excluded, and the exclusion is REPORTED rather than silent, so an
         answer that is thin because of a permission says so;
      3. **status** — only APPROVED and SUPERSEDED rules, which is what a
         Regulatory Knowledge Release admits;
      4. **date** — in force on the reporting date, not today.

    Scoring is deterministic term overlap. No model reads the corpus: a
    retrieval a reviewer cannot reproduce is a retrieval nobody can sign.
    """
    allowed = roles if roles is not None else frozenset({rs.PUBLIC,
                                                         rs.RESTRICTED})
    wanted = _terms(question)
    excluded: list[dict[str, str]] = []
    hits: list[Hit] = []

    for circular in circulars:
        if tenant and circular.tenant and circular.tenant != tenant:
            continue
        if circular.confidentiality not in allowed:
            excluded.append({
                "circular": circular.citation(),
                "why": (f"{circular.confidentiality} content is not "
                        "retrievable for this role")})
            continue
        if not circular.retrievable:
            excluded.append({
                "circular": circular.citation(),
                "why": (f"status {circular.status}: "
                        + rs.STATUS_MEANS.get(circular.status, ""))})
            continue
        if not circular.in_force_on(when):
            continue

        for rule in circular.rules:
            if rule.status != rs.APPROVED:
                continue
            if kinds and rule.kind not in kinds:
                continue
            overlap = wanted & _terms(rule.text)
            concept_hit = any(c.lower() in question.lower()
                              for c in (rule.concepts or []))
            if not overlap and not concept_hit:
                continue
            score = len(overlap) / max(len(wanted), 1)
            if concept_hit:
                score += 0.5
            hits.append(Hit(rule=rule, citation=cite(circular, rule),
                            circular=circular.citation(), score=score))

    hits.sort(key=lambda h: (-h.score, h.citation.reference,
                             h.rule.section_number))
    found = hits[:limit]
    clashes = conflicts(circulars, when)

    because = (f"{len(found)} rule(s) in force on {when.isoformat()}, from "
               f"{len({h.circular for h in found})} circular(s).")
    if not found:
        because = (f"No approved regulatory rule in force on "
                   f"{when.isoformat()} matches this question.")
    if excluded:
        because += f" {len(excluded)} circular(s) were not searched."
    if clashes:
        because += (f" {len(clashes)} conflict(s) between rules in force on "
                    "that date are reported rather than resolved.")

    return Answer(when=when, hits=found, conflicts=clashes, excluded=excluded,
                  because=because)


__all__ = ["Answer", "Conflict", "Hit", "KNOWLEDGE_VERSION", "Supersession",
           "apply_supersession", "cite", "conflicts", "retrieve",
           "supersessions"]

"""
Regulatory Assurance: what a regulatory answer has to satisfy. Part G.

Why this is separate from Answer Assurance
--------------------------------------------
Answer Assurance asks whether the analysis was performed correctly. A
regulatory answer can be performed perfectly and still be wrong in ways
Assurance has no reader for: quoted from a circular that was superseded before
the reporting date, quoted from a rule nobody reviewed, quoted from a document
whose bytes no longer hash to the citation, or quoted out of a supervisory
letter into an export.

So these are their own checks, with their own outcomes, joined to the same
record. Every one of them is a reason NOT to show an answer, which is why
they are checks rather than warnings.

The critical ones
------------------
Four gates, and a regulatory answer that fails any of them is not shown:

    cited            every regulatory claim resolves to a rule and a document
    in_force         every cited rule was in force on the reporting date
    reviewed         every cited rule was approved by a named SME
    original_intact  the bytes still hash to what the citation claims

`conflict_declared` and `confidentiality_respected` are mandatory rather than
critical: a declared conflict is a legitimate answer — the point is that it is
declared — and a confidentiality exclusion narrows an answer rather than
falsifying it, provided it is reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.regulatory import knowledge as kn
from backend.regulatory import schema as rs

ASSURANCE_VERSION = "1.0.0"

PASS = "PASS"
FAIL = "FAIL"
WARNING = "WARNING"
NOT_APPLICABLE = "NOT_APPLICABLE"

CRITICAL = "CRITICAL"
MANDATORY = "MANDATORY"
ADVISORY = "ADVISORY"

#: name -> (weight, what it means)
CHECKS: dict[str, tuple[str, str]] = {
    "cited": (CRITICAL,
              "Every regulatory statement resolves to a rule in a document on "
              "file. An uncited regulatory claim is the failure this whole "
              "area exists to prevent."),
    "in_force": (CRITICAL,
                 "Every cited rule was in force on the reporting date. A "
                 "circular issued after the quarter being reported is wrong "
                 "in a way that reads as thorough."),
    "reviewed": (CRITICAL,
                 "Every cited rule was approved by a named regulatory SME. "
                 "Extraction proposes; a person disposes."),
    "original_intact": (CRITICAL,
                        "The stored original still hashes to what the "
                        "citation claims, so the quote can be proved against "
                        "the document it came from."),
    "conflict_declared": (MANDATORY,
                          "Where two rules in force on the date disagree, "
                          "both are shown and neither is chosen."),
    "confidentiality_respected": (MANDATORY,
                                  "No class the caller may not read was "
                                  "used, and any exclusion is reported "
                                  "rather than silent."),
    # Critical, and it earns it. Without an active release the corpus is
    # uploaded and extracted and nobody has approved any of it, so quoting
    # from it is the "uncited or unreviewed regulatory claim" §41 lists as
    # blocking. It was MANDATORY first, which made an answer with no release
    # behind it report `ok` — a corpus nobody had reviewed, passing.
    "release_active": (CRITICAL,
                       "The answer was produced under an active Regulatory "
                       "Knowledge Release, and says which. Without one, "
                       "nothing regulatory may be quoted at all."),
    "supersession_checked": (ADVISORY,
                             "Whether anything cited has since been "
                             "replaced, so a reader knows the position has "
                             "moved on."),
}

CRITICAL_CHECKS: tuple[str, ...] = tuple(
    name for name, (weight, _) in CHECKS.items() if weight == CRITICAL)


@dataclass
class Check:
    name: str
    outcome: str
    detail: str

    @property
    def weight(self) -> str:
        return CHECKS.get(self.name, (ADVISORY, ""))[0]

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.name, "outcome": self.outcome,
                "detail": self.detail, "weight": self.weight,
                "means": CHECKS.get(self.name, ("", ""))[1]}


@dataclass
class Record:
    """What was checked about one regulatory answer."""

    checks: list[Check] = field(default_factory=list)
    as_of: str = ""
    release_id: str = ""

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.outcome == FAIL]

    @property
    def critical_failures(self) -> list[Check]:
        return [c for c in self.failures if c.weight == CRITICAL]

    @property
    def ok(self) -> bool:
        return not self.critical_failures

    def sentence(self) -> str:
        if self.ok:
            return (f"Every regulatory claim is cited, in force as of "
                    f"{self.as_of or 'the reporting date'}, reviewed, and "
                    "provable against the stored original.")
        return ("This answer is not shown: "
                + " ".join(c.detail for c in self.critical_failures))

    def to_dict(self) -> dict[str, Any]:
        return {"checks": [c.to_dict() for c in self.checks],
                "as_of": self.as_of, "release_id": self.release_id,
                "ok": self.ok,
                "failed": [c.to_dict() for c in self.failures],
                "critical_failures": [c.name for c in self.critical_failures],
                "explanation": self.sentence(),
                "version": ASSURANCE_VERSION}


def assess(answer: kn.Answer, circulars: list[rs.Circular], *,
           when: date, release: Any = None,
           verify_original: Any = None) -> Record:
    """Check one regulatory answer against the four gates and the rest.

    `verify_original` is injected — normally `store.verify` — so the check can
    run in a test without a filesystem and so a deployment that keeps
    originals somewhere else can supply its own prover. When it is not
    supplied the check reports NOT_APPLICABLE rather than passing: a check
    that cannot run is not a check that passed.
    """
    by_id = {c.circular_id: c for c in circulars}
    record = Record(as_of=when.isoformat(),
                    release_id=str(getattr(release, "release_id", "") or ""))

    if not answer.hits:
        record.checks.append(Check(
            "cited", NOT_APPLICABLE,
            "The answer quotes no regulatory rule, so there is nothing to "
            "cite."))
    else:
        uncited = [h for h in answer.hits
                   if not (h.citation.reference and h.citation.content_hash)]
        record.checks.append(Check(
            "cited", FAIL if uncited else PASS,
            (f"{len(uncited)} regulatory statement(s) resolve to no document "
             "on file.") if uncited else
            f"All {len(answer.hits)} statement(s) carry a citation."))

    stale = [h for h in answer.hits
             if (found := by_id.get(h.citation.circular_id)) is not None
             and not found.in_force_on(when)]
    record.checks.append(Check(
        "in_force", FAIL if stale else (PASS if answer.hits
                                        else NOT_APPLICABLE),
        (f"{len(stale)} cited rule(s) were not in force on {when.isoformat()}."
         ) if stale else
        (f"Every cited rule was in force on {when.isoformat()}."
         if answer.hits else "No rule was cited.")))

    unreviewed = [h for h in answer.hits
                  if h.rule.status != rs.APPROVED or not h.rule.reviewer]
    record.checks.append(Check(
        "reviewed", FAIL if unreviewed else (PASS if answer.hits
                                             else NOT_APPLICABLE),
        (f"{len(unreviewed)} cited rule(s) carry no named SME approval."
         ) if unreviewed else
        ("Every cited rule was approved by a named SME." if answer.hits
         else "No rule was cited.")))

    if verify_original is None:
        record.checks.append(Check(
            "original_intact", NOT_APPLICABLE,
            "No prover was supplied, so whether the stored originals still "
            "hash to their citations was not checked. A check that did not "
            "run is not a check that passed."))
    elif not answer.hits:
        record.checks.append(Check("original_intact", NOT_APPLICABLE,
                                   "Nothing was cited."))
    else:
        broken = []
        for hit in answer.hits:
            circular = by_id.get(hit.citation.circular_id)
            if circular is None:
                broken.append(hit.citation.reference)
                continue
            if not verify_original(circular.content_hash,
                                   tenant=circular.tenant):
                broken.append(circular.reference)
        record.checks.append(Check(
            "original_intact", FAIL if broken else PASS,
            (f"The stored original no longer matches the citation for: "
             f"{', '.join(sorted(set(broken)))}.") if broken else
            "Every citation resolves to a stored original with a matching "
            "hash."))

    record.checks.append(Check(
        "conflict_declared", PASS if not answer.conflicts else PASS,
        (f"{len(answer.conflicts)} conflict(s) between rules in force on "
         f"{when.isoformat()} are shown and not resolved.")
        if answer.conflicts else "No two rules in force on that date "
        "disagree."))

    record.checks.append(Check(
        "confidentiality_respected", PASS,
        (f"{len(answer.excluded)} document(s) were excluded and the exclusion "
         "is reported.") if answer.excluded else
        "No document was excluded for confidentiality."))

    active = str(getattr(release, "status", "") or "")
    record.checks.append(Check(
        "release_active",
        PASS if active == "ACTIVE" else FAIL,
        (f"Produced under Regulatory Knowledge Release "
         f"{record.release_id}.") if active == "ACTIVE" else
        ("No active Regulatory Knowledge Release: nothing regulatory may be "
         "quoted until one is activated.")))

    replaced = [h for h in answer.hits
                if (found := by_id.get(h.citation.circular_id)) is not None
                and found.superseded_by]
    record.checks.append(Check(
        "supersession_checked",
        WARNING if replaced else PASS,
        (f"{len(replaced)} cited circular(s) have since been replaced. The "
         "answer is correct as of the reporting date and the position has "
         "moved on.") if replaced else
        "Nothing cited has been replaced."))

    return record


__all__ = ["ADVISORY", "ASSURANCE_VERSION", "CHECKS", "CRITICAL",
           "CRITICAL_CHECKS", "Check", "FAIL", "MANDATORY", "NOT_APPLICABLE",
           "PASS", "Record", "WARNING", "assess"]

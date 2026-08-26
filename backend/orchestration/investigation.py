"""
"Something seems wrong with Contracting. Investigate it."

What used to happen
-------------------
The request was read as naming a borrower called "Contracting. Investigate",
then — once that was fixed — as an analysis with no measure, and CreditProbe
asked which figure to compute. Both are reasonable readings of a sentence that
names no figure. Neither is what a credit officer means.

What they mean is: *take the population I named and tell me what is moving*.
That is a real analytical request with a real answer, and it is answerable
without inventing anything, because the bank has already declared which
measures matter and which direction is bad.

How it is answered
------------------
A **bounded** set of probes, each one an ordinary governed analysis over the
named population. Bounded matters: an investigation that ran everything would
take a minute, cost a fortune, and bury the two lines that mattered. Each probe
is a question CreditProbe could have been asked directly, so every figure it
reports carries a Trace and reconciles like any other.

The probes are chosen from the semantic ontology rather than written out here.
A concept with a governed direction of deterioration and a governed field is a
probe; one without is not. Publish a new domain into the Data Builder and the
investigation widens on its own.

What it does not do
-------------------
Assert a cause. It reports what moved, in which direction, and by how much,
against the population and window it says it used. "ECL rose 34% while the
portfolio rose 4%" is a finding; "ECL rose because the sector is distressed" is
a story, and CreditProbe has no evidence for it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: How many probes an investigation runs. Five is what fits on a screen and in
#: a credit officer's attention; the sixth is read by nobody and paid for by
#: everybody.
MAX_PROBES = 5

#: The sentence shapes that mean "look into this", as opposed to "compute this".
_INVESTIGATE = (
    r"\binvestigate\b",
    r"\blook into\b",
    r"\bdig into\b",
    r"\bwhat(?:'s| is) (?:going on|happening|wrong|the matter)\b",
    r"\bsomething (?:seems|looks|feels) (?:wrong|off|odd)\b",
    r"\bwhy (?:is|are) .{0,40}(?:deteriorat|worsen|struggl|weak)",
    r"\breview\b.{0,30}\b(?:sector|portfolio|book|segment|region)\b",
    r"\btell me about\b",
    r"\bwhat should I (?:know|worry) about\b",
)


@dataclass(frozen=True)
class Probe:
    """One governed question the investigation asks."""

    concept_id: str
    label: str
    question: str
    #: Why this probe is part of the investigation, for the answer's own notes.
    because: str


@dataclass
class Request:
    """A broad investigation, once read."""

    subject: str = ""
    subject_kind: str = ""
    probes: list[Probe] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return bool(self.subject and self.probes)

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "subject_kind": self.subject_kind,
                "probes": [{"concept": p.concept_id, "label": p.label,
                            "question": p.question, "because": p.because}
                           for p in self.probes]}


def wants_investigation(question: str) -> bool:
    """Whether this asks to be looked into rather than computed."""
    text = " ".join((question or "").lower().split())
    return any(re.search(pattern, text) for pattern in _INVESTIGATE)


def read(question: str, context: Any) -> Request:
    """The population to investigate, and the probes to run over it.

    Returns an empty Request when the sentence asks to investigate but names no
    governed population. That is a clarification, not an investigation of the
    whole book: "investigate it" with no antecedent is a question about what
    "it" is.
    """
    if not wants_investigation(question):
        return Request()

    subject, kind = _population(question, context)
    if not subject:
        return Request()
    return Request(subject=subject, subject_kind=kind,
                   probes=_probes(subject, kind, context))


def _population(question: str, context: Any) -> tuple[str, str]:
    """The governed dimension value the request names."""
    from backend.orchestration import entities

    matches = entities.match_all(question, getattr(context, "dimensions", {}) or {})
    if matches:
        best = max(matches, key=lambda m: (m.exact, m.confidence))
        return best.value, best.kind
    return "", ""


#: The order probes are asked in. Deliberately the order a credit officer would
#: ask them: what the exposure is, then what it is provisioned at, then what the
#: borrowers look like, then whether they are paying.
_PRIORITY = ("ead", "ecl", "stage", "rating", "dpd", "headroom", "utilisation",
             "leverage", "dscr")


def _probes(subject: str, kind: str, context: Any) -> list[Probe]:
    """The governed measures worth asking about, in priority order.

    Read from the ontology and filtered by what the catalogue can actually
    compute for this population, so an investigation never promises a line it
    cannot fill in.
    """
    from backend.semantics import ontology

    del kind
    available = _computable(context)
    out: list[Probe] = []
    for concept_id in _PRIORITY:
        if concept_id not in available:
            continue
        contract = ontology.contract(concept_id)
        if contract is None:
            continue
        direction = ("a rise is deterioration" if contract.higher_is_worse
                     else "a fall is deterioration")
        shape = _SHAPE.get(concept_id, "")
        question = (shape.format(subject=subject) if shape else
                    f"How has {contract.business_name.lower()} moved in "
                    f"{subject} over the latest year?")
        out.append(Probe(
            concept_id=concept_id, label=contract.business_name,
            question=question,
            because=f"{contract.business_name}: {direction}."))
        if len(out) >= MAX_PROBES:
            break

    if out:
        # The one probe that is about names rather than totals. An officer
        # asking what is wrong wants to know who, and a movement total without
        # a name is not actionable.
        out.append(Probe(
            concept_id="worst",
            label="Largest deteriorating borrowers",
            question=(f"Which {subject} customers had a rating downgrade and "
                      "an increase in ECL over the latest year?"),
            because=("A sector total says how much moved; this says who, which "
                     "is what a review acts on.")))
    return out[:MAX_PROBES + 1]


#: How each concept is probed. Written per concept because the right question
#: differs: a stage MIGRATES, a rating is DOWNGRADED, and an exposure MOVES.
#: Asking "how many were downgraded" about an IFRS 9 stage is a sentence a
#: credit officer would notice and not trust the rest of the page after.
_SHAPE: dict[str, str] = {
    "ecl": "How has expected credit loss moved in {subject} over the "
           "latest year?",
    "stage": "What is total exposure at default in {subject} by IFRS 9 stage?",
    "rating": "How many {subject} customers were downgraded over the latest "
              "year?",
    "dpd": "How many {subject} customers had days past due rise over the "
           "latest year?",
    "headroom": "Which {subject} customers have covenant headroom below 15%?",
    "utilisation": "How has limit utilisation moved in {subject} over the "
                   "latest year?",
}


def _computable(context: Any) -> set[str]:
    """Concept ids the governed catalogue can currently compute."""
    from backend.orchestration import concepts as cx

    published: set[str] = set()
    try:
        from backend.data_access import get_data_source

        source = get_data_source()
        for name in source.datasets():
            for field_name in source.fields(name):
                published.add(f"{name}.{field_name}")
    except Exception as e:  # noqa: BLE001
        logger.debug("Catalogue unavailable to the investigation planner: %s", e)
        return set()

    out: set[str] = set()
    for concept in cx.CONCEPTS:
        for candidate in concept.candidates:
            if f"{candidate.dataset}.{candidate.field}" in published:
                out.add(concept.id)
                break
    del context
    return out


def run(request: Request, question: str, *, answer_one: Any) -> Any:
    """Run every probe and assemble one answer out of them.

    `answer_one` is the orchestrator's own `answer`, injected rather than
    imported: the probes are ordinary questions and must go through exactly the
    path a user's question goes through, including the guardrail, the
    validator and the runtime. An investigation that had its own execution
    route would be an investigation nobody could reconcile.
    """
    from backend.orchestration.handlers import HandlerResult

    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    for probe in request.probes:
        try:
            answered = answer_one(probe.question, use_certified=False)
        except Exception as e:  # noqa: BLE001 - one probe must not lose the rest
            logger.warning("Investigation probe %r failed: %s", probe.label, e)
            notes.append(f"{probe.label}: could not be computed ({e}).")
            continue

        finding, figures = _finding(answered)
        if not finding:
            notes.append(f"{probe.label}: {_why_not(answered)}")
            continue
        rows.append({
            "measure": probe.label,
            "finding": finding,
            "rows": figures,
            "question": probe.question,
            "because": probe.because,
        })

    if not rows:
        return None

    return HandlerResult(
        answer=(f"{len(rows)} governed checks over {request.subject}, each one "
                "an analysis you can open: "
                + "; ".join(r["finding"] for r in rows[:3])
                + ("…" if len(rows) > 3 else "")),
        rows=rows,
        columns=[{"name": "measure", "label": "What was checked"},
                 {"name": "finding", "label": "What it found"},
                 {"name": "rows", "label": "Rows"},
                 {"name": "question", "label": "Asked as"}],
        values={"probes": len(rows), "subject": request.subject},
        detail={"investigation": request.to_dict(),
                "rule": ("Each line is a governed analysis over the named "
                         "population. Nothing here asserts a cause.")},
        warnings=notes,
        follow_ups=[r["question"] for r in rows[:4]],
    )


def _finding(answered: Any) -> tuple[str, int]:
    """One probe's headline, and how many rows stood behind it.

    The headline is the sentence the user would have seen had they asked the
    probe directly — assembled the same way, from the same result. An
    investigation whose lines read differently from the answers they open is an
    investigation nobody trusts twice.
    """
    runtime = getattr(answered, "runtime", None)
    if runtime is not None:
        return (_headline(answered) or _plain(answered),
                int(getattr(runtime, "row_count", 0)))
    result = getattr(answered, "result", None)
    if result is not None:
        return str(getattr(result, "answer", "")), len(getattr(result, "rows", []))
    return "", 0


def _headline(answered: Any) -> str:
    """The deterministic sentence assembly would put on this result."""
    written = getattr(answered, "written", None)
    live = str(getattr(written, "headline", "") or "")
    if live:
        return live
    try:
        from backend.orchestration import assembly

        built = assembly.from_analysis(
            answered.question, answered.reading, answered.build,
            answered.runtime, duration_ms=0, mode={})
        return str(built.narrative.direct_answer or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not assemble a probe headline: %s", e)
        return ""


def _plain(answered: Any) -> str:
    build = getattr(answered, "build", None)
    return str(getattr(build, "summary", "") or "").strip()


def _why_not(answered: Any) -> str:
    for attribute in ("clarification", "unsupported", "failure"):
        found = str(getattr(answered, attribute, "") or "")
        if found:
            return found
    return "no figures were returned."


def clarification(question: str) -> str:
    """What to ask when a request to investigate names nothing to investigate."""
    del question
    return (
        "CreditProbe can investigate a population it can identify — a sector, "
        "a region, a segment or a named borrower. Say which one, and it will "
        "check exposure, impairment, staging, ratings and arrears over the "
        "latest year and report what moved.")


__all__ = ["MAX_PROBES", "Probe", "Request", "clarification", "read", "run",
           "wants_investigation"]

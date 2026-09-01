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
    # Lower case deliberately: `wants_investigation` lowers the question before
    # matching, so a capital I here never matched anything at all.
    r"\bwhat should i (?:know|worry) about\b",
    r"\bwhat(?:'s| is) (?:worrying|concerning|the concern)\b",
    r"\bany(?:thing) (?:concerns?|worries|red flags)\b",
    # "What has deteriorated?" names no measure, and it is not a request for
    # one — it is a request to go and look, across the measures that describe
    # deterioration. Answered with the probes rather than a menu of concepts.
    r"\bwhat (?:has|have|is|are) (?:\w+ ){0,2}"
    r"(?:deteriorat|worsen|declin|weaken|slipp|got worse)",
    r"\bwhere (?:is|are) (?:the |we )?(?:risk|trouble|weakness|problems?)\b",
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
    #: §12: what the Analysis Portfolio Planner considered, chose and
    #: rejected, and why. Kept on the request so the Trace can show the
    #: choice rather than only its outcome - an investigation that shows five
    #: probes without saying what it decided not to run is asking to be
    #: trusted about the part nobody can see.
    portfolio: Any = None

    @property
    def valid(self) -> bool:
        return bool(self.subject and self.probes)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "subject": self.subject, "subject_kind": self.subject_kind,
            "probes": [{"concept": p.concept_id, "label": p.label,
                        "question": p.question, "because": p.because}
                       for p in self.probes]}
        if self.portfolio is not None:
            out["portfolio"] = self.portfolio.to_dict()
        return out


def wants_investigation(question: str) -> bool:
    """Whether this asks to be looked into rather than computed."""
    text = " ".join((question or "").lower().split())
    return any(re.search(pattern, text) for pattern in _INVESTIGATE)


#: The whole portfolio, as a population an investigation can run over.
WHOLE_BOOK = "the whole book"

#: A pronoun standing in for a population the sentence never named.
_DANGLING = re.compile(
    r"\b(?:investigate|look into|dig into|review|examine)\s+"
    r"(?:it|this|that|them|those|these)\b", re.I)


def read(question: str, context: Any) -> Request:
    """The population to investigate, and the probes to run over it.

    Two different sentences name no sector, and they do not mean the same
    thing:

        "Investigate it."            — a pronoun with no antecedent. What
                                       "it" is, is the question, and guessing
                                       the whole book answers something nobody
                                       asked. Returns empty, so the caller
                                       asks.

        "What has deteriorated over the latest year?"
                                     — no referent at all, and no gap. The
                                       population IS the book; it is the
                                       question a CRO asks first thing on a
                                       Monday, and replying with a menu of
                                       governed concepts is the product
                                       refusing to do its job.
    """
    if not wants_investigation(question):
        return Request()

    subject, kind = _population(question, context)
    if subject:
        probes, chosen = _plan_probes(question, subject, kind, context)
        return Request(subject=subject, subject_kind=kind, probes=probes,
                       portfolio=chosen)
    if _DANGLING.search(question or ""):
        return Request()
    probes, chosen = _plan_probes(question, "", "portfolio", context)
    return Request(subject=WHOLE_BOOK, subject_kind="portfolio",
                   probes=probes, portfolio=chosen)


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
    """Every governed measure worth PROPOSING, in priority order.

    Read from the ontology and filtered by what the catalogue can actually
    compute for this population, so an investigation never promises a line it
    cannot fill in.

    This is the candidate list, not the selection. It used to be both - it
    stopped at MAX_PROBES and whatever fell off the end was never considered
    or recorded. Now it proposes everything computable and `_plan_probes`
    cuts it through the governed planner, which is what makes the rejections
    real: an investigation that shows five probes and cannot say what it
    decided against is asking to be trusted about the part nobody can see.
    """
    from backend.semantics import ontology

    portfolio = kind == "portfolio"
    shapes = _PORTFOLIO_SHAPE if portfolio else _SHAPE
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
        shape = shapes.get(concept_id, "")
        if shape:
            question = shape if portfolio else shape.format(subject=subject)
        else:
            question = (
                f"How has {contract.business_name.lower()} moved "
                + ("" if portfolio else f"in {subject} ")
                + "over the latest year?")
        out.append(Probe(
            concept_id=concept_id, label=contract.business_name,
            question=question,
            because=f"{contract.business_name}: {direction}."))

    if out:
        # The one probe that is about names rather than totals. An officer
        # asking what is wrong wants to know who, and a movement total without
        # a name is not actionable.
        out.append(Probe(
            concept_id="worst",
            label="Largest deteriorating borrowers",
            question=("Which "
                      + ("" if portfolio else f"{subject} ")
                      + "customers had a rating downgrade and an increase in "
                        "ECL over the latest year?"),
            because=("A sector total says how much moved; this says who, which "
                     "is what a review acts on.")))
    return out


def _plan_probes(question: str, subject: str, kind: str,
                 context: Any) -> tuple[list[Probe], Any]:
    """Choose the probes through the governed Analysis Portfolio Planner.

    §12 asks for one planner, not one per caller. The probe list this module
    used to pick by priority-order-and-cap is now a candidate list scored on
    relevance, availability, independence and cost - which is what stops the
    investigation running two probes that say the same thing, and what lets
    the Trace show what it decided against.

    `_PRIORITY` survives as the caller's prior: an officer asks what the
    exposure is before asking how it is provisioned, and nothing in the
    request says so.
    """
    from backend.orchestration import portfolio as pf

    proposed = _probes(subject, kind, context)
    if not proposed:
        return [], None

    candidates = [
        pf.Candidate(
            analysis_id=probe.concept_id,
            title=probe.label,
            question=probe.question,
            concept_id=probe.concept_id,
            datasets=_datasets_for(probe.concept_id),
            because=probe.because,
            prior=_prior_for(probe.concept_id),
        )
        for probe in proposed
    ]
    chosen = pf.plan(question, candidates,
                     computable=_computable(context) | {"worst"},
                     max_analyses=MAX_PROBES + 1)
    keep = {d.candidate.analysis_id for d in chosen.selected}
    return [p for p in proposed if p.concept_id in keep], chosen


def _prior_for(concept_id: str) -> float:
    """Where this concept sits in the order an officer would ask.

    The one piece of domain knowledge the planner cannot derive from the
    request, so it is supplied rather than inferred.
    """
    if concept_id == "worst":
        # The probe that names borrowers. A sector total says how much moved;
        # this says who, which is what a review acts on - so it is rated
        # highly even though no request ever asks for it by name.
        return 0.95
    if concept_id in _PRIORITY:
        return round(1.0 - _PRIORITY.index(concept_id) / len(_PRIORITY), 4)
    return 0.3


def _datasets_for(concept_id: str) -> tuple[str, ...]:
    """The datasets a probe would read, for the planner's cost and
    independence scores. Read from the concept registry, so a probe over two
    tables is costed as two."""
    from backend.orchestration import concepts as cx

    for concept in cx.CONCEPTS:
        if concept.id == concept_id:
            return tuple(dict.fromkeys(c.dataset for c in concept.candidates))
    return ()


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

#: The same probes over the whole portfolio. Written separately rather than
#: formatted with "the whole book", because "How many the whole book customers
#: were downgraded" is the sort of sentence that costs a demo.
_PORTFOLIO_SHAPE: dict[str, str] = {
    "ead": "How has exposure at default moved over the latest year?",
    "ecl": "How has expected credit loss moved over the latest year?",
    "stage": "What is total exposure at default by IFRS 9 stage?",
    "rating": "How many customers were downgraded over the latest year?",
    "dpd": "How many customers had days past due rise over the latest year?",
    "headroom": "Which customers have covenant headroom below 15%?",
    "utilisation": "How has limit utilisation moved over the latest year?",
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


#: Why the last investigation produced nothing, when it produced nothing.
#:
#: A module-level list rather than a return value because `run()` is called
#: from one place and its `HandlerResult | None` contract is what the executor
#: expects. Read immediately after a None, by `why_empty()`.
_LAST_NOTES: list[str] = []


def why_empty() -> str:
    """What stopped the probes, for a stated failure rather than a question."""
    if not _LAST_NOTES:
        return ""
    return (
        "CreditProbe understood the population and could not complete the "
        "checks over it. "
        + " ".join(_LAST_NOTES[:3])
        + " Nothing is shown rather than a partial picture presented as a "
        "full one.")


@dataclass
class Composition:
    """What a broad investigation's sub-analyses actually did. §3 (D4/D19/D20).

    The defect this closes
    -----------------------
    A broad investigation runs six governed probes through the same path a
    user's question takes, and then threw all six answers away except for
    their headline sentences. The composed answer had no `build`, no
    `runtime`, no invariant report and no evidence facts, so:

    - the flow classifier filed a coordinated portfolio review under
      "conversational, no analysis ran";
    - the Trace could not say which datasets the review touched;
    - the Evidence Fact Graph registered nothing, so nothing in the synthesis
      was grounded against a fact;
    - operational Assurance had no execution to check.

    Every one of those was reported as a separate defect. They are one defect:
    the composition was never recorded. This is the record.

    Nothing here is inferred. Each field is read off a sub-answer that really
    ran, and a probe that produced no runtime contributes nothing — which is
    why `ran` and `attempted` are separate numbers.
    """

    #: Probes that produced a governed result.
    ran: int = 0
    #: Probes that were attempted, including the ones that came back empty.
    attempted: int = 0
    datasets: list[str] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    grains: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    rows: int = 0
    #: Invariants compiled and checked across every sub-analysis.
    invariants_checked: int = 0
    invariants_failed: int = 0
    #: Sub-analyses whose invariants all held. A review is only as sound as
    #: the weakest analysis under it.
    invariants_clean: int = 0
    #: Sub-analyses that validated an Analytical IR, compiled a query
    #: through the safe compiler, and read through the governed path. Counted
    #: separately from `ran` so a review cannot claim work it did not do.
    ir_validated: int = 0
    queries_compiled: int = 0
    governed_reads: int = 0
    #: Sub-analyses whose declared output grain matched their objective.
    grain_contracts_ok: int = 0
    facts_registered: int = 0
    facts_usable: int = 0
    facts_refused: list[dict[str, str]] = field(default_factory=list)
    #: The Trace node ids the sub-analyses left behind, so a reader can enter
    #: the review at the analysis that produced any one line.
    trace_nodes: list[str] = field(default_factory=list)

    @property
    def executed(self) -> bool:
        return self.ran > 0

    @property
    def invariants_passed(self) -> bool | None:
        """None when nothing was checked. A check that did not run is not a
        check that passed — the distinction D7 was raised about."""
        if not self.invariants_checked:
            return None
        return self.invariants_failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran, "attempted": self.attempted,
            "datasets": list(self.datasets), "periods": list(self.periods),
            "grains": list(self.grains), "concepts": list(self.concepts),
            "methods": list(self.methods), "rows": self.rows,
            "ir_validated": self.ir_validated,
            "queries_compiled": self.queries_compiled,
            "governed_reads": self.governed_reads,
            "grain_contracts_ok": self.grain_contracts_ok,
            "invariants": {"checked": self.invariants_checked,
                           "failed": self.invariants_failed,
                           "clean_analyses": self.invariants_clean,
                           "passed": self.invariants_passed},
            "facts": {"registered": self.facts_registered,
                      "usable": self.facts_usable,
                      "refused": list(self.facts_refused[:10])},
            "trace_nodes": list(self.trace_nodes),
        }


def _extend(into: list[str], values: Any) -> None:
    """Append what is new, in first-seen order. Order is not cosmetic here:
    the datasets a review read are shown in the order it read them."""
    for value in (values or []):
        text = str(value or "").strip()
        if text and text not in into:
            into.append(text)


def _observe(into: Composition, answered: Any) -> None:
    """Fold one sub-analysis into the composition. Reads, never infers."""
    build = getattr(answered, "build", None)
    runtime = getattr(answered, "runtime", None)
    if runtime is None:
        return

    into.ran += 1
    _extend(into.datasets, getattr(build, "datasets", None)
            or ([getattr(build, "dataset", "")]
                if getattr(build, "dataset", "") else []))
    _extend(into.periods, [p for p in (getattr(build, "period", ""),
                                       getattr(build, "opening", ""),
                                       getattr(build, "closing", "")) if p])
    _extend(into.grains, [getattr(build, "output_grain", "")
                          or getattr(build, "grain", "")])
    _extend(into.concepts, [getattr(m.concept, "label", "")
                            for m in (getattr(build, "matches", None) or [])])
    _extend(into.methods, [getattr(build, "method", "")])
    into.rows += int(getattr(runtime, "row_count", 0) or 0)

    plan = getattr(runtime, "plan", None)
    if list(getattr(plan, "operations", None) or []):
        into.ir_validated += 1
    if getattr(runtime, "query", None) is not None:
        into.queries_compiled += 1
        # The safe compiler IS the governed read path: a result with a
        # compiled query behind it was scoped before it ran.
        into.governed_reads += 1

    from backend.orchestration import grain as gr

    contract = gr.contract_of(build)
    if contract is not None and contract.ok:
        into.grain_contracts_ok += 1

    report = getattr(answered, "invariants", None)
    if report is not None:
        checked = len(getattr(report, "checks", None) or [])
        failed = len(getattr(report, "failures", None) or [])
        into.invariants_checked += checked
        into.invariants_failed += failed
        if checked and not failed:
            into.invariants_clean += 1

    # The Evidence Fact Graph, built from the sub-analysis the same way it is
    # built for a single answer. Before this, a coordinated review registered
    # zero facts however many analyses ran under it.
    try:
        from backend.orchestration import judgment_bridge as jb

        graph = jb.facts_from(runtime, build,
                              str(getattr(answered, "run_id", "") or "probe"))
        into.facts_registered += len(graph.facts)
        into.facts_usable += len(graph.usable())
        into.facts_refused.extend({"fact_id": f, "why": w}
                                  for f, w in graph.refused[:3])
    except Exception as e:  # noqa: BLE001 - evidence must not lose the answer
        logger.warning("Could not register facts for a probe: %s", e)

    graph = getattr(runtime, "trace", None) or getattr(runtime, "graph", None)
    _extend(into.trace_nodes, list(getattr(graph, "nodes", {}) or {}))


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
    composed = Composition()
    for probe in request.probes:
        composed.attempted += 1
        try:
            answered = answer_one(probe.question, use_certified=False)
        except Exception as e:  # noqa: BLE001 - one probe must not lose the rest
            logger.warning("Investigation probe %r failed: %s", probe.label, e)
            notes.append(f"{probe.label}: could not be computed ({e}).")
            continue

        _observe(composed, answered)
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
        # Every probe failed. The caller needs to know that this is different
        # from "the sentence named no population" — the population was named
        # and understood, and the checks over it did not complete. Falling
        # through to the clarification asks for something the user already
        # gave, which reads as the product not listening.
        _LAST_NOTES[:] = notes
        return None

    _LAST_NOTES.clear()

    return HandlerResult(
        answer=_synthesis(request, rows, notes),
        rows=rows,
        columns=[{"name": "measure", "label": "What was checked"},
                 {"name": "finding", "label": "What it found"},
                 {"name": "rows", "label": "Rows"},
                 {"name": "question", "label": "Asked as"}],
        values={"probes": len(rows), "subject": request.subject,
                "analyses_run": composed.ran,
                "datasets_read": len(composed.datasets)},
        detail={"investigation": request.to_dict(),
                "composed": composed.to_dict(),
                "rule": ("Each line is a governed analysis over the named "
                         "population. Nothing here asserts a cause.")},
        warnings=notes,
        follow_ups=[r["question"] for r in rows[:4]],
        composition=composed,
        # A review that ran governed analyses did not look anything up in a
        # catalogue. Reported as `metadata`, the Trace consistency contract
        # concluded nothing was calculated and the flow classifier filed a
        # coordinated portfolio review under "no analysis ran".
        execution=("composed_analysis" if composed.executed else "metadata"),
        execution_label=(
            f"{composed.ran} governed analyses over "
            f"{len(composed.datasets)} datasets" if composed.executed
            else "Governed metadata"),
    )


#: Words that mark a finding as deterioration rather than movement. Read off
#: the probe headline, which CreditProbe wrote from its own result — never
#: inferred and never a judgement about the sector.
_WORSE = ("rose", "increased", "worsened", "downgraded", "deteriorat",
          "breach", "past due", "higher", "widened")
_BETTER = ("fell", "declined", "improved", "upgraded", "lower", "narrowed")


def _synthesis(request: Any, rows: list[dict[str, Any]],
               notes: list[str]) -> str:
    """An executive summary of what the checks found, then the checks.

    A list of six findings joined by semicolons is a list, and a reader has to
    do the synthesis themselves — which is the work they opened the product to
    avoid. The first sentence says how many checks ran, how many of them point
    the wrong way, and which one is worst; the lines are underneath, each still
    an analysis they can open.

    Nothing here asserts a cause. The direction of each check is read off the
    sentence CreditProbe itself wrote about that check's result.
    """
    worse = [r for r in rows if _points_down(str(r.get("finding") or ""))]
    steady = len(rows) - len(worse)

    lead = (f"{len(rows)} governed checks over {request.subject}. ")
    if not worse:
        lead += ("None of them points to deterioration over the window "
                 "checked.")
    elif len(worse) == len(rows):
        lead += "Every one of them points the wrong way."
    else:
        lead += (f"{len(worse)} point the wrong way and {steady} do not.")

    if worse:
        lead += f" The clearest is: {worse[0]['finding']}"
    if notes:
        lead += (f" {len(notes)} further "
                 f"{'check' if len(notes) == 1 else 'checks'} could not be "
                 "completed and {0} not included."
                 .format("is" if len(notes) == 1 else "are"))
    return lead.strip()


def _points_down(finding: str) -> bool:
    """Whether this check's own sentence describes a worsening."""
    lowered = finding.lower()
    if any(word in lowered for word in _BETTER):
        return False
    return any(word in lowered for word in _WORSE)


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


__all__ = [
    "why_empty",
    "WHOLE_BOOK","MAX_PROBES", "Probe", "Request", "clarification", "read", "run",
           "wants_investigation"]

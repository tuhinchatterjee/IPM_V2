"""How much to analyse, and how much to write. §35, §38.

Two decisions that are really one. A request that warrants six analyses
cannot be answered in sixty words, and one that warrants a single figure is
made worse, not better, by three paragraphs around it. §38 lets the agentic
layer decide how much work to do; §35 bounds how much prose comes back. Both
decisions are made here, together, from the same inputs, and both are
recorded - §38 requires the decision be persisted and traced, which is what
stops "it felt like a long question" being the whole explanation.

Three rules from §35 are not negotiable and are enforced rather than
suggested:

    every completed answer carries at least one user-facing paragraph;
    a table or a chart alone is not an answer;
    the direct answer is not buried.

The last one is why `Decision` carries no "put the summary at the end"
option. There is no request for which burying the answer is correct, so it
is not a choice the policy can make.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LENGTH_POLICY_VERSION = "1.0.0"

SIMPLE = "SIMPLE"
MODERATE = "MODERATE"
COMPLEX = "COMPLEX"

BANDS: tuple[str, ...] = (SIMPLE, MODERATE, COMPLEX)


@dataclass(frozen=True)
class Band:
    """One of §35's three shapes, as numbers something can be checked against.

    The word counts are §35's, and they are ranges rather than targets: an
    answer that pads to reach a floor is worse than a short one, so the floor
    exists to catch the answer that is a table with a caption, not to make
    every answer the same size.
    """

    name: str
    min_paragraphs: int
    max_paragraphs: int
    min_words: int
    max_words: int
    max_visualizations: int

    def fits(self, words: int, paragraphs: int) -> bool:
        return (self.min_paragraphs <= paragraphs <= self.max_paragraphs
                and self.min_words <= words <= self.max_words)

    def to_dict(self) -> dict[str, Any]:
        return {"band": self.name,
                "paragraphs": [self.min_paragraphs, self.max_paragraphs],
                "words": [self.min_words, self.max_words],
                "max_visualizations": self.max_visualizations}


#: §35's bands. One paragraph is the floor everywhere, including SIMPLE:
#: "every completed answer must include at least ONE user-facing paragraph".
POLICY: dict[str, Band] = {
    SIMPLE: Band(SIMPLE, 1, 1, 40, 140, 1),
    MODERATE: Band(MODERATE, 1, 2, 90, 280, 2),
    COMPLEX: Band(COMPLEX, 2, 6, 180, 600, 6),
}

#: Above this many analyses §36 turns the response into an Investigation
#: review rather than a longer answer. A policy that kept extending the page
#: would produce the card wall §36 forbids.
INVESTIGATION_REVIEW_AT = 6


@dataclass
class Inputs:
    """§38's inputs. Everything the decision is allowed to depend on.

    Named exhaustively so the decision cannot quietly depend on something
    else. A length policy that could read anything would be a length policy
    nobody could predict or test.
    """

    objective_count: int = 1
    analysis_count: int = 1
    #: Distinct governed domains touched. A cross-domain answer needs to say
    #: how the domains were joined, which costs words a single-domain answer
    #: does not need.
    domain_count: int = 1
    #: Whether the figures are large enough to change a decision. Passed in
    #: because materiality is a portfolio fact, not a linguistic one.
    material: bool = False
    #: Exceptions found - breaches, outliers, failed covenant tests. Each one
    #: is a thing the reader has to be told about by name.
    exception_count: int = 0
    #: Evidence the answer wanted and does not have. Costs a sentence saying
    #: so, and that sentence is not optional.
    evidence_gaps: int = 0
    #: How uncertain the result is, 0..1. High uncertainty needs saying, and
    #: saying it briefly is how it gets missed.
    uncertainty: float = 0.0
    #: A decision the answer is meant to support, if any. "Should we extend
    #: this limit" earns more than "what is the number".
    decision_expected: bool = False
    #: Set when the user asked for a length. An instruction beats the policy.
    requested_band: str = ""
    #: The reader. An executive summary and an analyst's working note are
    #: different documents.
    role: str = ""
    #: Whether the answer sits inside a Project or Risk Case, where the
    #: context is already established and need not be restated.
    in_case_context: bool = False
    #: Zero means unbounded. A budget can only shrink the work, never grow it.
    cost_budget: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Decision:
    """What was decided, and why. §38's outputs, persisted and traced."""

    band: str = SIMPLE
    analysis_count: int = 1
    task_count: int = 1
    depth: str = "single"
    min_paragraphs: int = 1
    max_paragraphs: int = 1
    min_words: int = 40
    max_words: int = 140
    max_visualizations: int = 1
    needs_clarification: bool = False
    #: §36's layout, chosen from the analysis count rather than by the UI, so
    #: the backend and the frontend cannot disagree about what shape the
    #: answer is.
    layout: str = "single"
    reasons: list[str] = field(default_factory=list)
    inputs: Inputs = field(default_factory=Inputs)
    version: str = LENGTH_POLICY_VERSION

    @property
    def paragraph_band(self) -> str:
        return (f"{self.min_paragraphs}"
                if self.min_paragraphs == self.max_paragraphs
                else f"{self.min_paragraphs}-{self.max_paragraphs}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "band": self.band,
            "analysis_count": self.analysis_count,
            "task_count": self.task_count,
            "depth": self.depth,
            "paragraphs": [self.min_paragraphs, self.max_paragraphs],
            "paragraph_band": self.paragraph_band,
            "words": [self.min_words, self.max_words],
            "max_visualizations": self.max_visualizations,
            "needs_clarification": self.needs_clarification,
            "layout": self.layout,
            "reasons": list(self.reasons),
            "inputs": self.inputs.to_dict(),
        }


#: §36's four layouts, by analysis count.
def _layout(analyses: int) -> str:
    if analyses > INVESTIGATION_REVIEW_AT:
        return "investigation_review"
    if analyses >= 4:
        return "grouped"
    if analyses >= 2:
        return "primary_and_supporting"
    return "single"


def _band_for(inputs: Inputs) -> tuple[str, list[str]]:
    """Which of §35's three shapes this answer is, and why.

    Scored rather than branched: several small reasons for a longer answer
    should add up to one, and a chain of if-statements would let whichever
    was checked first decide alone.
    """
    reasons: list[str] = []
    weight = 0

    if inputs.objective_count > 1:
        weight += inputs.objective_count - 1
        reasons.append(f"{inputs.objective_count} objectives were asked for, "
                       "and each one has to be answered in its own right")
    if inputs.analysis_count > 1:
        weight += inputs.analysis_count - 1
        reasons.append(f"{inputs.analysis_count} analyses were run, and an "
                       "answer that does not say how they relate leaves the "
                       "reader to guess")
    if inputs.domain_count > 1:
        weight += 1
        reasons.append(f"{inputs.domain_count} governed domains were used, so "
                       "the answer has to say how they were brought together")
    if inputs.exception_count:
        weight += min(inputs.exception_count, 3)
        reasons.append(f"{inputs.exception_count} exception(s) were found, and "
                       "an exception nobody names is an exception nobody acts "
                       "on")
    if inputs.evidence_gaps:
        weight += 1
        reasons.append(f"{inputs.evidence_gaps} evidence gap(s) have to be "
                       "stated rather than left for the reader to notice")
    if inputs.uncertainty >= 0.4:
        weight += 1
        reasons.append("the result is uncertain enough that saying so "
                       "briefly would be how it gets missed")
    if inputs.material:
        weight += 1
        reasons.append("the figures are material enough to change a decision")
    if inputs.decision_expected:
        weight += 1
        reasons.append("the answer is meant to support a decision, not only "
                       "to report a number")
    if inputs.in_case_context:
        weight -= 1
        reasons.append("the Project or Risk Case already establishes the "
                       "context, so it is not restated here")

    if weight >= 4:
        return COMPLEX, reasons
    if weight >= 1:
        return MODERATE, reasons
    return SIMPLE, reasons or ["one objective, one analysis, one domain"]


def decide(inputs: Inputs) -> Decision:
    """How much to analyse and how much to write.

    An explicitly requested band wins. §38 lets the agentic layer decide
    within governed limits, and a user who said "in one line" has moved that
    limit - overriding them with a policy that thought the question deserved
    more is the product deciding it knows better than the person reading.
    """
    band_name, reasons = _band_for(inputs)

    if inputs.requested_band in BANDS:
        if inputs.requested_band != band_name:
            reasons.insert(0, (
                f"the reader asked for a {inputs.requested_band.lower()} "
                f"answer; the policy would have written a "
                f"{band_name.lower()} one, and the instruction wins"))
        band_name = inputs.requested_band

    band = POLICY[band_name]
    analyses = max(inputs.analysis_count, 1)
    decision = Decision(
        band=band_name,
        analysis_count=analyses,
        task_count=max(analyses, inputs.objective_count, 1),
        depth=("investigation" if analyses > INVESTIGATION_REVIEW_AT
               else "coordinated" if analyses >= 4
               else "multi" if analyses >= 2 else "single"),
        min_paragraphs=band.min_paragraphs,
        max_paragraphs=band.max_paragraphs,
        min_words=band.min_words,
        max_words=band.max_words,
        max_visualizations=min(band.max_visualizations, max(analyses, 1)),
        layout=_layout(analyses),
        reasons=reasons,
        inputs=inputs,
    )
    return decision


# ------------------------------------------------------------ §35's floor


@dataclass
class Compliance:
    """Whether an assembled answer obeys the contract. Checked, not assumed."""

    ok: bool
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "problems": list(self.problems)}


def _words(text: str) -> int:
    return len((text or "").split())


def _paragraphs(text: str) -> int:
    return len([p for p in (text or "").split("\n\n") if p.strip()])


def check(prose: str, decision: Decision, *, has_result: bool = False,
          answer_first: bool = True) -> Compliance:
    """§35's three rules, against what is about to be shown.

    Over-length is a problem and under-length is a worse one, but only the
    floor is treated as a failure of the CONTRACT: an answer that runs long
    is verbose, while an answer with no paragraph is a table pretending to be
    an answer, which is the thing §35 exists to forbid.
    """
    problems: list[str] = []
    paragraphs = _paragraphs(prose)
    words = _words(prose)

    if paragraphs < 1 or not (prose or "").strip():
        problems.append(
            "no user-facing paragraph: a result with no prose around it is "
            "not an answer, it is a table the reader has to interpret alone")
    elif has_result and words < max(decision.min_words // 2, 20):
        problems.append(
            f"{words} words around a computed result is a caption, not an "
            f"answer; this band asks for at least {decision.min_words}")
    if not answer_first:
        problems.append(
            "the direct answer is not first; §35 forbids burying it, and "
            "there is no request for which burying it is right")
    if paragraphs > decision.max_paragraphs:
        problems.append(
            f"{paragraphs} paragraphs where this band allows "
            f"{decision.max_paragraphs}")
    if words > decision.max_words:
        problems.append(
            f"{words} words where this band allows {decision.max_words}")

    return Compliance(ok=not problems, problems=problems)


def from_portfolio(chosen: Any, reading: Any = None, **overrides: Any
                   ) -> Decision:
    """The length decision a planned portfolio implies.

    The join between §12 and §38: the planner has already decided how many
    analyses to run and over how many domains, and deriving the length from
    that rather than from the question's wording is what keeps the two
    decisions consistent.
    """
    selected = getattr(chosen, "selected", []) or []
    domains: set[str] = set()
    for decision in selected:
        domains.update(getattr(decision.candidate, "datasets", ()) or ())
    inputs = Inputs(
        objective_count=len(getattr(reading, "objectives", []) or []) or 1,
        analysis_count=len(selected) or 1,
        domain_count=len(domains) or 1,
        **overrides,
    )
    return decide(inputs)

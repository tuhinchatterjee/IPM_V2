"""
What analysis to run, expressed as something a validator can refuse.

Why a structured plan and not code
-----------------------------------
The spec's target architecture has a planner write bounded SQL or Python
against the domain. This build expresses the plan as a STRUCTURE instead —
scope, grain, period, filters, measures, groupings — and a governed executor
turns that structure into the query.

That is not a shortcut around the validator; it is the validator's whole
purchase. A plan that names a field is refused by comparing the name against
the dictionary. A plan that names a dataset is refused by comparing it
against the domain. Free-form code has to be parsed before either check can
happen, and every parser is a place where something gets through. Here there
is nothing to parse: a field the dictionary does not contain cannot be
expressed, and a domain outside Early Warning has no way to be named at all.

The seam for a live planner is the same shape: a model returns THIS
structure, and it goes through exactly the same validation as the
deterministic one. The structure is the contract, so the check does not
change when the author does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import dictionary as dic
from backend.early_warning import executable as ex
from backend.early_warning import grain as grain_mod

#: What an analysis step is FOR. Each maps to a governed executor.
POPULATION = "population"
RANKING = "ranking"
GROUPING = "grouping"
MOVEMENT = "movement"
BORROWER = "borrower"
LAYER = "layer"
EVIDENCE = "evidence"
DIAGNOSIS = "diagnosis"
CONCENTRATION = "concentration"
COMPARISON = "comparison"
#: Answered from the governed methodology metadata. No query is run, because
#: there is no query that would mean anything.
METHODOLOGY = "methodology"
#: A workflow action rather than an analysis. Goes through permissions and
#: the deterministic escalation engine, not through the analytical executor.
ACTION = "action"

ANALYSIS_TYPES: tuple[str, ...] = (
    POPULATION, RANKING, GROUPING, MOVEMENT, BORROWER, LAYER, EVIDENCE,
    DIAGNOSIS, CONCENTRATION, COMPARISON, METHODOLOGY, ACTION)

#: Types that read no analytical data at all.
NON_ANALYTICAL: frozenset[str] = frozenset({METHODOLOGY, ACTION})


@dataclass
class Step:
    """One bounded analysis, named in terms the validator can check."""

    analysis: str
    #: The dataset. Always the Early Warning domain — there is no other value
    #: this may take, and the validator proves it.
    domain: str = grain_mod.DOMAIN_ID
    period: str = ""
    comparison_period: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    group_by: str = ""
    measures: list[str] = field(default_factory=list)
    order_by: str = "ews_score"
    descending: bool = True
    limit: int = 25
    customer_id: str = ""
    layer: str = ""
    signal_key: str = ""
    #: Why this step exists, for the audit trail and the plan note.
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.analysis, "domain": self.domain,
            "period": self.period, "comparison_period": self.comparison_period,
            "filters": dict(self.filters), "group_by": self.group_by,
            "measures": list(self.measures), "order_by": self.order_by,
            "descending": self.descending, "limit": self.limit,
            "customer_id": self.customer_id, "layer": self.layer,
            "signal_key": self.signal_key, "rationale": self.rationale,
        }

    @property
    def referenced_fields(self) -> list[str]:
        """Every field this step names. What the validator checks."""
        out = list(self.measures)
        if self.group_by:
            out.append(self.group_by)
        if self.order_by:
            out.append(self.order_by)
        out += list(self.filters)
        return [f for f in out if f]


@dataclass
class Plan:
    """The steps for one turn, and what they are meant to establish."""

    steps: list[Step] = field(default_factory=list)
    output_grain: str = "population_month"
    intent: str = ""
    engine: str = "deterministic"
    notes: list[str] = field(default_factory=list)
    #: What served this plan. Empty when the deterministic planner ran alone.
    model_call: dict[str, Any] = field(default_factory=dict)
    #: The deterministic plan this one replaced, kept so a model plan the
    #: validator refuses outright costs the reader a worse plan rather than
    #: the whole turn. Never used to bypass validation: the fallback is
    #: validated exactly as the model plan was.
    fallback: Plan | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [s.to_dict() for s in self.steps],
                "output_grain": self.output_grain, "intent": self.intent,
                "engine": self.engine, "notes": list(self.notes),
                "model_call": dict(self.model_call)}

    @property
    def is_analytical(self) -> bool:
        return any(s.analysis not in NON_ANALYTICAL for s in self.steps)


#: The measures a population answer always carries, because every Early
#: Warning reading is about a score, a band and the exposure behind them.
BASE_MEASURES: tuple[str, ...] = (
    "ews_score", "ews_band", "exposure", "high_plus")


def _period(request: Any, package: grain_mod.GrainPackage) -> str:
    asked = str(getattr(request, "requested_period", "") or "")
    return asked if asked in package.periods else package.current_period


def _comparison(request: Any, package: grain_mod.GrainPackage,
                 period: str) -> str:
    """The month a movement is measured against, resolved to one that exists."""
    asked = str(getattr(request, "comparison_period", "") or "")
    match = re.match(r"-(\d+)m$", asked)
    if not match:
        return ""
    back = int(match.group(1))
    periods = list(package.periods)
    if period not in periods:
        return ""
    here = periods.index(period)
    return periods[here - back] if here - back >= 0 else periods[0]


def build(request: Any, package: grain_mod.GrainPackage, *,
          ledger: Any = None) -> Plan:
    """The plan for one business request.

    The deterministic planner runs first and always. Where Opus is configured
    it is asked for the same structure from the same grain package, and what
    comes back is validated exactly as the deterministic plan is — the
    contract is the structure, not who wrote it. A model plan the validator
    refuses outright falls back to the deterministic one rather than losing
    the turn.
    """
    floor = _build_deterministic(request, package)
    if ledger is None:
        return floor
    from backend.early_warning.conversation import planner as planner_mod

    return planner_mod.plan(request, package, floor, ledger=ledger)


def _build_deterministic(request: Any,
                         package: grain_mod.GrainPackage) -> Plan:
    """The floor: one step per part the request asked for."""
    analysis = str(getattr(request, "requested_analysis", "") or "")
    # Every part the request asked for, not just the leading one. A question
    # that asks why AND whether it is systemic has two answers owed, and
    # composing one step per part is what lets the sufficiency review say
    # which of them the evidence actually covered.
    analyses = list(getattr(request, "requested_analyses", None)
                    or ([analysis] if analysis else []))
    scope = str(getattr(request, "requested_scope", "") or "portfolio")
    inherited = dict(getattr(request, "inherited_context", {}) or {})
    period = _period(request, package)
    comparison = _comparison(request, package, period)
    customer_id = str(inherited.get("customer_id") or "")
    grouping = str(getattr(request, "requested_grouping", "") or "")

    steps: list[Step] = []
    notes: list[str] = []

    if "methodology" in analyses:
        steps.append(Step(
            analysis=METHODOLOGY, period=period,
            rationale=("The question is about how the model works. It is "
                       "answered from the governed methodology metadata, "
                       "because there is no query over the book that would "
                       "mean anything.")))
        return Plan(steps=steps, output_grain="methodology",
                    intent=analysis, notes=notes)

    wants_action = (getattr(request, "escalation_requested", False)
                    or getattr(request, "report_requested", False)
                    or getattr(request, "remediation_requested", False))
    if wants_action:
        # "What should I do?" and "escalate it" are different questions and
        # get different readings: one is the governed action library, the
        # other is the deterministic escalation route. Both need the
        # obligor's position underneath them, so it is read first.
        intent = ("escalation" if getattr(request, "escalation_requested", False)
                  else "action")
        if customer_id:
            steps.append(Step(
                analysis=BORROWER, period=period, customer_id=customer_id,
                measures=list(BASE_MEASURES),
                rationale="The obligor's position, which the action is about."))
        steps.append(Step(
            analysis=ACTION, period=period, customer_id=customer_id,
            rationale=("The question asks what to do or whom to tell. Both "
                       "come from governed sources — the action library and "
                       "the escalation matrix — rather than from the "
                       "answer layer.")))
        return Plan(steps=steps, output_grain="customer_latest",
                    intent=intent, notes=notes)

    if ("evidence" in analyses or getattr(request, "requested_evidence", False)) \
            and customer_id:
        steps.append(Step(
            analysis=EVIDENCE, period=period, customer_id=customer_id,
            signal_key=str(inherited.get("signal") or ""),
            rationale=("The question asks what sits behind a node, which is "
                       "answered from the signal observation that produced "
                       "the score.")))
        return Plan(steps=steps, output_grain="customer_month",
                    intent="evidence", notes=notes)

    if customer_id and scope == "borrower":
        steps.append(Step(
            analysis=BORROWER, period=period, customer_id=customer_id,
            measures=list(BASE_MEASURES),
            rationale="The obligor the question is about."))
        if "movement" in analyses:
            steps.append(Step(
                analysis=MOVEMENT, period=period,
                comparison_period=comparison or "",
                customer_id=customer_id,
                measures=["ews_score", "anchor_score", "net_notches"],
                rationale=("The question is about movement, so the anchor and "
                           "the notches are read apart: a score that fell "
                           "while its anchor rose has not improved.")))
        # A movement question about an obligor is a MOVEMENT reading, whatever
        # else it also asks. "Why did its score move?" reads as a diagnosis
        # and a movement, and answering it with the obligor's current
        # position answers the question before it.
        return Plan(steps=steps, output_grain="customer_month",
                    intent=("movement" if "movement" in analyses
                            else analysis or "borrower"), notes=notes)

    if "grouping" in analyses or grouping:
        resolved = _resolve_grouping(grouping, package)
        if resolved:
            steps.append(Step(
                analysis=GROUPING, period=period, group_by=resolved,
                measures=list(BASE_MEASURES),
                rationale=f"The question asks for the book cut by {resolved}."))
            return Plan(steps=steps, output_grain="group_month",
                        intent="grouping", notes=notes)
        notes.append(
            f"No grouping field matches {grouping!r}; answered at the "
            f"population level instead.")

    # The population is the ground every remaining reading stands on, so it
    # is always the first step.
    filters = dict(_population_filters(inherited, scope))
    steps.append(Step(
        analysis=POPULATION, period=period, measures=list(BASE_MEASURES),
        filters=dict(filters),
        rationale="The population the question is about."))

    if "ranking" in analyses:
        # "Which names drive it?" points INTO the current scope. Ordered by
        # exposure at high severity rather than by score alone: the reader
        # asking which names drive a population is asking which ones matter,
        # and a very high score on a small exposure does not.
        steps.append(Step(
            analysis=RANKING, period=period,
            filters={**filters, "high_plus": True},
            measures=["ews_score", "ews_band", "exposure",
                      "dominant_subcategory", "dominant_driver"],
            order_by="exposure", limit=10,
            rationale=("The question asks which obligors drive the "
                       "population, so the population is opened rather than "
                       "restated.")))

    # Then one step per part the request asked for. Composed rather than
    # selected: a question with three parts gets three steps, and the
    # sufficiency review can name the one the evidence did not cover.
    if "movement" in analyses or comparison:
        steps.append(Step(
            analysis=MOVEMENT, period=period,
            comparison_period=comparison or package.periods[0],
            measures=list(grain_mod.wide.LAYER_KEYS),
            filters=dict(_population_filters(inherited, scope)),
            rationale=("The question is about a change, so the movement is "
                       "decomposed by layer rather than restated.")))
    if "concentration" in analyses:
        steps.append(Step(
            analysis=CONCENTRATION, period=period,
            measures=["exposure", "high_plus", "ews_score"],
            filters=dict(_population_filters(inherited, scope)),
            rationale=("Whether the weakness is broad or sits in a few names "
                       "decides the response, so concentration is measured "
                       "rather than characterised.")))
    if "diagnosis" in analyses:
        steps.append(Step(
            analysis=DIAGNOSIS, period=period,
            filters={**_population_filters(inherited, scope), "high_plus": True},
            rationale=("The question asks what the population has in common, "
                       "which is a partition rather than a count of the most "
                       "frequent driver.")))
    return Plan(steps=steps, output_grain="population_month",
                intent=analysis or "population", notes=notes)


def _population_filters(inherited: dict[str, Any], scope: str
                         ) -> dict[str, Any]:
    """The slice of the book the question is about, from the screen."""
    out: dict[str, Any] = {}
    for key, column in (("segment", "segment"), ("sector", "sector"),
                        ("region", "region"),
                        ("internal_rating", "internal_rating"),
                        ("band", "ews_band")):
        value = inherited.get(key)
        if value:
            out[column] = value
    del scope
    return out


def _resolve_grouping(asked: str, package: grain_mod.GrainPackage) -> str:
    """Which real field a grouping word names, or nothing.

    Through the one governed alias map, and no further. The substring rule
    that used to sit here — "if the word appears anywhere in a field name,
    take that field" — matched `band` to `classifier_band` as readily as to
    `ews_band` and `sub` to `dominant_subcategory` as readily as to nothing,
    which is a grouping chosen by alphabetical accident. An unrecognised word
    now resolves to nothing, and the reader is asked.
    """
    if not asked:
        return ""
    resolved = ex.normalise(asked, role=ex.GROUP_BY)
    return resolved if resolved in package.groupings else ""


def field_is_known(name: str) -> bool:
    return name in dic.names()


__all__ = ["ACTION", "ANALYSIS_TYPES", "BASE_MEASURES", "BORROWER",
           "COMPARISON", "CONCENTRATION", "DIAGNOSIS", "EVIDENCE",
           "GROUPING", "LAYER", "METHODOLOGY", "MOVEMENT", "NON_ANALYTICAL",
           "POPULATION", "RANKING", "Plan", "Step", "build",
           "field_is_known"]

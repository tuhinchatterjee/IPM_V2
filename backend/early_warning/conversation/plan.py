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
from backend.early_warning import layers as layers_mod

#: What an analysis step is FOR. Each maps to a governed executor.
POPULATION = "population"
RANKING = "ranking"
GROUPING = "grouping"
MOVEMENT = "movement"
#: Who crossed a severity band between two published months. Not the same
#: reading as MOVEMENT, which measures how far a score travelled: a band
#: change is discrete, per obligor, and is what the watchlist keys on.
TRANSITION = "transition"
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
    POPULATION, RANKING, GROUPING, MOVEMENT, TRANSITION, BORROWER, LAYER,
    EVIDENCE, DIAGNOSIS, CONCENTRATION, COMPARISON, METHODOLOGY, ACTION)

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
    #: A band transition's drill-down: which cell of the from-band/to-band
    #: matrix the question asked to see the names in, and which way.
    from_band: str = ""
    to_band: str = ""
    direction: str = ""
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
            "signal_key": self.signal_key, "from_band": self.from_band,
            "to_band": self.to_band, "direction": self.direction,
            "rationale": self.rationale,
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
    fallback: "Plan | None" = None

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


def _about(steps: list["Step"], asked: str) -> str:
    """What a plan is ABOUT: an analysis it actually contains.

    Reporting an intent no step matches is how a borrower question came to
    be answered with a portfolio driver tree. "Why is Gulf Contracting 2
    flagged?" plans one BORROWER step and reports its intent as `diagnosis`,
    because that is the word the sentence used. Nothing matched at first, so
    the headline fell back to the borrower reading and the answer was right.
    Then the sufficiency review noticed `diagnosis` was uncovered, ran one,
    and the packet's headline switched to it — the obligor disappeared from
    its own answer, and a revision meant to ADD something replaced
    everything.

    So the intent is only the asked-for analysis when a step will produce
    it; otherwise it is the leading step that is not scene-setting.
    """
    present = [step.analysis for step in steps]
    if asked and asked in present:
        return asked
    answered = [name for name in present if name != POPULATION]
    return answered[0] if answered else (present[0] if present else POPULATION)


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
    # The detection layer the question named, if it named one. A layer is
    # neither a grouping nor a band: it says WHICH of the model's six
    # layer/dimension outputs the answer is about, and every branch below
    # has to honour it or answer a different question.
    layer = str(getattr(request, "requested_layer", "")
                or inherited.get("layer") or "").upper()
    if not layers_mod.is_code(layer):
        layer = ""

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
        else:
            # "What should I do?" asked of a population is still a question
            # about a population. Without this the plan was one ACTION step
            # with no obligor attached, the action reader had nothing to read
            # from, and the turn came back saying nothing was returned.
            steps.append(Step(
                analysis=POPULATION, period=period,
                measures=list(BASE_MEASURES),
                filters=dict(_population_filters(inherited, scope)),
                rationale=("No obligor is named, so the action is about the "
                           "population the question is about.")))
        steps.append(Step(
            analysis=ACTION, period=period, customer_id=customer_id,
            filters=({} if customer_id
                     else dict(_population_filters(inherited, scope))),
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
        if layer:
            # "What external warning events are driving this borrower?" is a
            # question about one layer of one obligor. Answering it with the
            # obligor's overall position answers the question before it.
            steps.append(Step(
                analysis=LAYER, period=period, customer_id=customer_id,
                layer=layer, measures=[layers_mod.BY_CODE[layer].ta_key],
                rationale=(f"The question names "
                           f"{layers_mod.described(layer)}, so the nodes "
                           f"inside that layer are opened rather than the "
                           f"score they roll into.")))
            return Plan(steps=steps, output_grain="customer_month",
                        intent="layer", notes=notes)
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
                    intent=_about(steps, "movement" if "movement" in analyses
                                  else analysis), notes=notes)

    if "transition" in analyses:
        # The month a transition is measured against is the PREVIOUS
        # published one unless the question named another. "How many changed
        # band this month" means since last month, not since the first
        # snapshot twenty months ago — which is what a generic movement
        # window gave it, and why the answer came back as a score
        # decomposition instead of a count of names.
        against = comparison or _previous_published(package, period)
        move = dict(inherited.get("band_move") or {})
        # "Which sectors had the most adverse band migrations?" is the same
        # transition read one level up, so the grouping rides on the step
        # rather than becoming a second, unrelated analysis.
        cut = _resolve_grouping(grouping, package) if grouping else ""
        steps.append(Step(
            analysis=TRANSITION, period=period, comparison_period=against,
            filters=dict(_population_filters(inherited, scope)),
            measures=["ews_band", "ews_score", "exposure"],
            group_by=cut,
            from_band=str(move.get("from_band") or ""),
            to_band=str(move.get("to_band") or ""),
            direction=str(move.get("direction") or ""),
            rationale=("The question asks who crossed a severity band, "
                       "which is a comparison of two published months "
                       "obligor by obligor rather than a movement in the "
                       "score."
                       + (f" Rolled up by {cut}." if cut else ""))))
        return Plan(steps=steps, output_grain="population_transition",
                    intent="transition", notes=notes)

    # The other parts a grouping question may also be asking for. A request
    # that names a cut AND asks why AND asks whether it is concentrated is
    # three questions; returning the cut and stopping answers one of them and
    # reports it as the whole answer.
    also_asked = [name for name in analyses
                  if name in ("movement", "concentration", "diagnosis",
                              "ranking", "comparison")]

    if "grouping" in analyses or grouping:
        resolved = _resolve_grouping(grouping, package)
        if resolved:
            # A cut of the book still honours the slice the question asked
            # for. Without the filters, "exposure by sector for obligors at
            # High or Very High" was answered for every obligor in every
            # sector — right arithmetic, different question, and nothing on
            # screen to say the filter had been dropped.
            cut = dict(_population_filters(inherited, scope))
            measures = list(BASE_MEASURES)
            if layer:
                # "Which sectors have the highest external-intelligence
                # score?" is the book cut by sector and READ ON L3. The cut
                # is the same; the measure that orders it is not, and until
                # this was carried the answer ranked sectors by total Early
                # Warning score and called it the external one.
                measures.append(layers_mod.BY_CODE[layer].ta_key)
            steps.append(Step(
                analysis=GROUPING, period=period, group_by=resolved,
                filters=cut, measures=measures, layer=layer,
                order_by=(layers_mod.BY_CODE[layer].ta_key if layer
                          else "ews_score"),
                rationale=(f"The question asks for the book cut by {resolved}"
                           + (f", read on {layers_mod.described(layer)}"
                              if layer else "")
                           + (f", within {cut}." if cut else "."))))
            if not also_asked:
                return Plan(steps=steps, output_grain="group_month",
                            intent="grouping", notes=notes)
            # Otherwise the cut is one step among several, and the rest are
            # composed below exactly as they are for any other request.
        notes.append(
            f"No grouping field matches {grouping!r}; answered at the "
            f"population level instead.")

    # The population is the ground every remaining reading stands on, so it
    # is always the first step.
    filters = dict(_population_filters(inherited, scope))
    if layer:
        # The population a layer question is about is the obligors that layer
        # actually fired for — not the whole book with a layer word in the
        # sentence.
        filters[layers_mod.BY_CODE[layer].active_field] = True
    steps.append(Step(
        analysis=POPULATION, period=period, measures=list(BASE_MEASURES),
        filters=dict(filters), layer=layer,
        rationale=("The population the question is about."
                   if not layer else
                   f"The obligors {layers_mod.described(layer)} fired for, "
                   f"which is the population the question is about.")))

    if "ranking" in analyses:
        # "Which names drive it?" points INTO the current scope. Ordered by
        # exposure at high severity rather than by score alone: the reader
        # asking which names drive a population is asking which ones matter,
        # and a very high score on a small exposure does not.
        if layer:
            # A layer ranking is ordered by the LAYER's own score and is not
            # narrowed to high-or-above: an obligor can carry a live external
            # warning and still sit at LOW overall, and that obligor is
            # exactly who the question is asking after. The other layers ride
            # along as measures so the reader can see whether anything
            # internal corroborates the external reading.
            entry = layers_mod.BY_CODE[layer]
            steps.append(Step(
                analysis=RANKING, period=period, filters=dict(filters),
                layer=layer,
                measures=[entry.ta_key, "ews_score", "ews_band", "exposure",
                          *[e.ta_key for e in layers_mod.LAYERS
                            if e.code != layer],
                          "dominant_subcategory", "dominant_driver"],
                order_by=entry.ta_key, limit=10,
                rationale=(f"The question asks which obligors carry "
                           f"{layers_mod.described(layer)}, so they are "
                           f"ordered by that layer's own score rather than "
                           f"by the score it rolls into.")))
        else:
            steps.append(Step(
                analysis=RANKING, period=period,
                filters={**filters, "high_plus": True},
                measures=["ews_score", "ews_band", "exposure",
                          "dominant_subcategory", "dominant_driver"],
                order_by="exposure", limit=10,
                rationale=("The question asks which obligors drive the "
                           "population, so the population is opened rather "
                           "than restated.")))

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
    # What the plan is ABOUT is the analysis that was asked for, not the one
    # that happens to run first.
    #
    # The population step is scene-setting — its own rationale says so, "the
    # ground every remaining reading stands on" — and it is prepended to every
    # plan in this branch. Reporting `population` as the intent whenever it is
    # present made a ranking request, a movement request and a concentration
    # request all describe themselves as population requests, and the packet
    # then wrote its headline from the population pack. The reader asked which
    # obligors are High and was told the portfolio's average score.
    return Plan(steps=steps, output_grain="population_month",
                intent=_about(steps, analysis), notes=notes)


def _previous_published(package: grain_mod.GrainPackage, period: str) -> str:
    """The published month immediately before this one, or this one."""
    periods = list(package.periods)
    if period in periods:
        here = periods.index(period)
        return periods[here - 1] if here > 0 else period
    return periods[-2] if len(periods) >= 2 else (periods[-1] if periods else "")


def _population_filters(inherited: dict[str, Any], scope: str
                         ) -> dict[str, Any]:
    """The slice of the book the question is about, from the screen."""
    out: dict[str, Any] = {}
    # "High or Very High" is ONE filter said as two bands, and the executor
    # already understands it under its own name.
    #
    # It wins over a single band value, because when both are present the
    # single one is an artefact: the group resolver matched "Very High" out
    # of the phrase "High or Very High" and recorded it as though the reader
    # had asked for that band alone. Applying both would narrow the answer to
    # the half of the filter that resolved.
    if str(inherited.get("band") or "").lower() == "high_plus":
        out["high_plus"] = True

    # "…but weak internal corroboration" is half the question, and a
    # population that ignores it is the other half's answer.
    corroboration = str(inherited.get("corroboration") or "").lower()
    if corroboration == "weak":
        out[layers_mod.CORROBORATED_FIELD] = False
    elif corroboration == "strong":
        out[layers_mod.CORROBORATED_FIELD] = True

    for key, column in (("segment", "segment"), ("sector", "sector"),
                        ("region", "region"),
                        ("internal_rating", "internal_rating"),
                        # A single band resolved out of the question arrives
                        # under its canonical column name, because the group
                        # resolver checks it against the domain's own values.
                        ("ews_band", "ews_band"),
                        ("band", "ews_band")):
        value = inherited.get(key)
        if not value:
            continue
        if column == "ews_band":
            if out.get("high_plus") or str(value).lower() == "high_plus":
                continue
            out["ews_band"] = value
        else:
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
           "TRANSITION", "_about",
           "COMPARISON", "CONCENTRATION", "DIAGNOSIS", "EVIDENCE",
           "GROUPING", "LAYER", "METHODOLOGY", "MOVEMENT", "NON_ANALYTICAL",
           "POPULATION", "RANKING", "Plan", "Step", "build",
           "field_is_known"]

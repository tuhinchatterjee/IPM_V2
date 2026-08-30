"""
The AI Intelligence Studio's fifteen tabs. §102, §105-§116.

What this module is
-------------------
The assembly layer. Every tab draws from the modules that own their subject —
the teaching library, the blueprint library, the judgment engines, the
visualization grammar, the routing policy, the release manifest — and wraps
each object in §117's seven answers and §118's fourteen validation fields.

Nothing here computes intelligence. If a number appears in a tab it was
computed by the thing the tab is about, which is the property that stops the
Studio drifting from the product it describes. A Studio with its own
implementation of "is this blueprint healthy" tells you how the Studio feels
about the blueprint.

Why the tabs are data
----------------------
`TABS` is a list, not a set of endpoints. §102 names fifteen; the front end
renders whatever this list contains; a test asserts the list matches the
brief. A tab added in code and not in the list does not appear, and one named
in the list with no builder fails loudly rather than rendering blank.

Deep links rather than duplicated editors
------------------------------------------
§105 is explicit: link to Data Builder, Analysis Studio or Agent Operations
rather than reproducing their editors. Two editors for one object means two
sets of validation, and the one that runs will be whichever screen the user
happened to open. So every object carries `edit_in` and the Studio is
read-only about everything it does not own.
"""

from __future__ import annotations

from typing import Any

from backend.ai_studio import explain as ex
from backend.ai_studio import permissions as pm

TABS_VERSION = "1.0.0"

# ------------------------------------------------------------ §102's fifteen
OVERVIEW = "OVERVIEW"
KNOWLEDGE = "KNOWLEDGE"
TEACHING_CASES = "TEACHING_CASES"
BLUEPRINTS = "INVESTIGATION_BLUEPRINTS"
JUDGMENT = "ANALYTICAL_JUDGMENT"
VISUAL_GRAMMAR = "VISUALIZATION_GRAMMAR"
ROUTING = "MODEL_ROUTING"
PROMPTS = "PROMPTS_AND_TEACHING_PACKS"
EVALUATIONS = "EVALUATIONS"
REVIEWS = "INVESTIGATION_REVIEWS"
FEEDBACK = "FEEDBACK_AND_LEARNING"
AGENTIC = "AGENTIC_HEALTH"
RELEASES = "RELEASES"
LIVE_HEALTH = "LIVE_AI_HEALTH"
SETTINGS = "SETTINGS"

# --------------------------------------------- the final consolidation's new
BRAIN_CENTER = "BRAIN_CENTER"
REGULATORY_LEARNING = "REGULATORY_LEARNING"

TABS: tuple[str, ...] = (
    OVERVIEW, KNOWLEDGE, TEACHING_CASES, BLUEPRINTS, JUDGMENT,
    VISUAL_GRAMMAR, ROUTING, PROMPTS, EVALUATIONS, REVIEWS, FEEDBACK,
    BRAIN_CENTER, REGULATORY_LEARNING, AGENTIC, RELEASES, LIVE_HEALTH,
    SETTINGS,
)

#: On-screen names. The enum is not the label: a reader asked for "the
#: blueprints tab", not INVESTIGATION_BLUEPRINTS.
LABELS: dict[str, str] = {
    OVERVIEW: "Overview", KNOWLEDGE: "Knowledge",
    TEACHING_CASES: "Teaching cases", BLUEPRINTS: "Investigation blueprints",
    JUDGMENT: "Analytical judgment", VISUAL_GRAMMAR: "Visualization grammar",
    ROUTING: "Model routing", PROMPTS: "Prompts & teaching packs",
    EVALUATIONS: "Evaluations", REVIEWS: "Investigation reviews",
    FEEDBACK: "Feedback & learning", AGENTIC: "Agentic health",
    RELEASES: "Releases", LIVE_HEALTH: "Live AI health",
    SETTINGS: "Settings", BRAIN_CENTER: "Brain Center",
    REGULATORY_LEARNING: "Regulatory learning",
}

#: What each tab is FOR, shown at the top of it. §117's principle applied to
#: the tabs themselves: a reader who cannot say what a tab is for will not
#: use it, and the Studio becomes the Overview and fourteen unopened tabs.
PURPOSE: dict[str, str] = {
    OVERVIEW: "What is running, how it is performing, and whether it is safe "
              "to put in front of a client today.",
    KNOWLEDGE: "The foundations everything else is built on: the credit-risk "
               "ontology, the certified methods, the data semantics and the "
               "agent registry.",
    TEACHING_CASES: "Every case CreditProbe learns from, what state it is in, "
                    "and whether a person has actually reviewed it.",
    BLUEPRINTS: "What a competent analyst would look at for each kind of "
                "investigation, and what may not be omitted.",
    JUDGMENT: "The policies that decide how large, how broad, how sustained "
              "and how contradictory a movement is.",
    VISUAL_GRAMMAR: "What each result field MEANS, which picture that "
                    "permits, and what the critic refuses.",
    ROUTING: "Which model role handles what, why, and what it costs.",
    PROMPTS: "The versioned prompts and the pack policy that governs what "
             "reaches a model.",
    EVALUATIONS: "What has been measured, over how many cases, and what the "
                 "evidence actually supports.",
    REVIEWS: "How recent investigations performed, turn by turn.",
    FEEDBACK: "What users told us, and what was done about it.",
    AGENTIC: "Whether the agentic layer is genuinely running.",
    RELEASES: "What is frozen, what is approved, and what has gone stale "
              "underneath it.",
    LIVE_HEALTH: "The provider, the roles, and what a live check would cost.",
    SETTINGS: "Who may do what, and what the Studio will never show.",
    BRAIN_CENTER: "What Brain is running, what this installation has "
                  "learned, what has been imported from elsewhere, and how "
                  "much measured improvement each import actually produced.",
    REGULATORY_LEARNING: "What the bank learned from the regulations it "
                         "read: which teaching cases, ontology changes and "
                         "policies came from a circular, and what measured "
                         "difference that made. The source library and the "
                         "extraction live in Analysis Studio; §27 keeps "
                         "them apart so a circular and a certified method "
                         "never look like the same kind of object.",
}

#: Which permission a tab needs. Checked backend-side; a tab hidden in the
#: front end is a tab reachable with curl.
NEEDS: dict[str, str] = {
    OVERVIEW: pm.VIEW, KNOWLEDGE: pm.VIEW, TEACHING_CASES: pm.VIEW,
    BLUEPRINTS: pm.VIEW, JUDGMENT: pm.VIEW, VISUAL_GRAMMAR: pm.VIEW,
    ROUTING: pm.VIEW, PROMPTS: pm.TEACHING_AUTHOR,
    EVALUATIONS: pm.EVALUATION_RUN, REVIEWS: pm.VIEW, FEEDBACK: pm.TEACHING_REVIEW,
    AGENTIC: pm.VIEW, RELEASES: pm.VIEW, LIVE_HEALTH: pm.LIVE_HEALTH_VIEW,
    SETTINGS: pm.ADMIN, BRAIN_CENTER: pm.BRAIN_VIEW,
    REGULATORY_LEARNING: pm.VIEW,
}


def visible(role: str) -> list[str]:
    """Which tabs a role may open."""
    return [t for t in TABS if pm.holds(role, NEEDS[t])]


def index(role: str) -> dict[str, Any]:
    """The tab bar, with what each one is for and whether it opens."""
    allowed = set(visible(role))
    return {
        "version": TABS_VERSION,
        "tabs": [{"id": t, "label": LABELS[t], "purpose": PURPOSE[t],
                  "needs": NEEDS[t], "visible": t in allowed}
                 for t in TABS],
        "visible": [t for t in TABS if t in allowed],
    }


# ---------------------------------------------------------------------------
# §105 — Knowledge
# ---------------------------------------------------------------------------

def knowledge() -> dict[str, Any]:
    """The four foundations, summarised, with deep links to their editors."""
    from backend.agentic import registry as ag
    from backend.semantics import ontology as on

    sections: list[dict[str, Any]] = []

    concepts = list(getattr(on, "CONCEPTS", ()) or ())
    sections.append(_section(
        "ontology", "Credit-risk ontology",
        count=len(concepts), edit_in="/data-builder",
        explanation=ex.Explanation(
            what="The governed vocabulary: every concept CreditProbe knows, "
                 "with its unit, its direction and the aggregations that are "
                 "valid over it.",
            why="Without it a question about 'coverage' is a string match. "
                "With it, 'coverage' resolves to a concept whose denominator "
                "is defined and whose average is refused.",
            when="On every question, before anything is planned.",
            validated="By the semantic test suite and by every teaching case "
                      "whose concepts resolve through it.",
            performing=f"{len(concepts)} concepts configured.",
            stale_or_failing=ex.NOTHING_STALE,
            release="Its version is recorded on every release and is a "
                    "staleness axis."),
        rows=[{"id": getattr(c, "id", str(c)),
               "name": getattr(c, "name", str(c)),
               "unit": getattr(c, "unit", ""),
               "direction": getattr(c, "direction", ""),
               "aggregations": list(getattr(c, "aggregations", ()) or ()),
               "aliases": list(getattr(c, "aliases", ()) or ())}
              for c in concepts[:400]]))

    methods = _methods()
    sections.append(_section(
        "methods", "Analysis Studio methods",
        count=len(methods), edit_in="/analysis-studio",
        explanation=ex.Explanation(
            what="The certified analytical methods CreditProbe may run.",
            why="A model that could write its own calculation would write a "
                "different one each time and none of them would be "
                "reviewable.",
            when="Whenever a plan names a method rather than composing raw "
                 "operations.",
            validated="Each method carries its own certification record.",
            performing=f"{len(methods)} methods available.",
            stale_or_failing=ex.NOTHING_STALE,
            release="The method version is a release staleness axis."),
        rows=methods))

    sections.append(_section(
        "data_semantics", "Data semantics",
        count=0, edit_in="/data-builder",
        explanation=ex.Explanation(
            what="Domains, datasets, relationships, authority and quality — "
                 "what data exists and which copy of it is the real one.",
            why="Two datasets that both look like exposure produce two "
                "different portfolio totals, and nothing on screen says "
                "which was used.",
            when="At planning, to choose the authoritative source and a "
                 "governed join path.",
            validated="By the Data Builder's own publication checks.",
            performing="Shown in Data Builder, not duplicated here.",
            stale_or_failing="Drift is reported in the Data Inbox.",
            release="The relationship version is a release staleness axis."),
        rows=[]))

    agents = list(getattr(ag, "AGENTS", ()) or ())
    tools = list(getattr(ag, "TOOLS", ()) or ())
    sections.append(_section(
        "agents", "Agent & tool registry",
        count=len(agents) + len(tools), edit_in="/agent-operations",
        explanation=ex.Explanation(
            what="The specialist agents and the tools each may call.",
            why="An agent that could call any tool is an agent whose "
                "permissions nobody can state.",
            when="When an investigation is decomposed across specialists.",
            validated="By the agentic evaluation suite.",
            performing=f"{len(agents)} agents, {len(tools)} tools.",
            stale_or_failing=ex.NOTHING_STALE,
            release="Agent roles are recorded on the release manifest."),
        rows=[{"id": getattr(a, "agent_id", getattr(a, "id", "")),
               "name": getattr(a, "name", ""),
               "tools": list(getattr(a, "tools", ()) or ())}
              for a in agents]))

    return {"version": TABS_VERSION, "tab": KNOWLEDGE,
            "purpose": PURPOSE[KNOWLEDGE], "sections": sections}


def _methods() -> list[dict[str, Any]]:
    try:
        from backend.studio import library as ml

        return [{"id": getattr(m, "method_id", getattr(m, "id", "")),
                 "name": getattr(m, "name", ""),
                 "certification": getattr(m, "certification", "")}
                for m in (getattr(ml, "METHODS", ()) or ())]
    except Exception:  # pragma: no cover - the method library moved
        return []


def _section(section_id: str, name: str, *, count: int, edit_in: str,
             explanation: ex.Explanation,
             rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": section_id, "name": name, "count": count,
            "edit_in": edit_in, "explanation": explanation.to_dict(),
            "rows": rows}


# ---------------------------------------------------------------------------
# §107 — Investigation blueprints
# ---------------------------------------------------------------------------

def blueprints() -> dict[str, Any]:
    """Every blueprint, with what it investigates and what may be omitted."""
    from backend.judgment import blueprints as bp

    objects: list[ex.Object] = []
    for blueprint in bp.LIBRARY:
        required = [o for o in blueprint.required_objectives]
        optional = [o for o in blueprint.optional_objectives]
        objects.append(ex.Object(
            object_id=blueprint.blueprint_id, kind="blueprint",
            name=blueprint.business_name,
            edit_in="",
            explanation=ex.Explanation(
                what=blueprint.description or blueprint.business_name,
                why=(f"Without it, {blueprint.business_name.lower()} is "
                     "whatever the model decides to look at that day, and two "
                     "runs of the same question examine different things."),
                when=blueprint.when_to_use or
                     ("When the request matches: "
                      + ", ".join(blueprint.trigger_patterns[:4])),
                validated=(f"{len(blueprint.mandatory_validations)} mandatory "
                           "validations, run on every investigation that uses "
                           "it."),
                performing=(f"evaluation score {blueprint.evaluation_score}"
                            if blueprint.evaluation_score
                            else ex.NOT_MEASURED),
                stale_or_failing=(f"status {blueprint.status}"
                                  if blueprint.status not in ("", bp.DRAFT)
                                  else ex.NOTHING_STALE),
                release=(f"version {blueprint.version}; the blueprint version "
                         "is a release staleness axis")),
            drilldown=ex.Drilldown(
                validation_status=(ex.PASSED if blueprint.usable
                                   else ex.NOT_EVALUATED),
                test_set="analytical judgment suite — blueprint selection",
                version=str(blueprint.version),
                owner=blueprint.owner,
                last_run=blueprint.last_validated,
                known_limitations=[blueprint.when_not_to_use]
                if blueprint.when_not_to_use else []),
            extra={
                "family": blueprint.family,
                "scope": blueprint.applicable_scope,
                "mandatory_objectives": [
                    {"id": o.id, "statement": o.statement,
                     "engine": o.engine} for o in required],
                "optional_objectives": [
                    {"id": o.id, "statement": o.statement,
                     "engine": o.engine} for o in optional],
                "methods": list(blueprint.required_methods),
                "data_requirements": list(
                    blueprint.required_data_capabilities),
                "hypothesis_templates": list(blueprint.hypothesis_templates),
                "challenge_templates": list(blueprint.challenge_templates),
                "stopping_rules": list(blueprint.stopping_rules),
                "model_route": blueprint.model_route,
                "agent_roles": list(blueprint.agent_roles),
                "review_status": blueprint.review_status,
                "may_be_omitted": [o.id for o in optional],
            }))
    return {"version": TABS_VERSION, "tab": BLUEPRINTS,
            "purpose": PURPOSE[BLUEPRINTS],
            "count": len(objects),
            "objects": [o.to_dict() for o in objects],
            "explanation_audit": ex.audit(objects)}


# ---------------------------------------------------------------------------
# §108 — Analytical judgment
# ---------------------------------------------------------------------------

JUDGMENT_SUBTABS: tuple[str, ...] = (
    "OBSERVATIONS", "MATERIALITY", "BREADTH_AND_CONCENTRATION", "PERSISTENCE",
    "CONTRADICTIONS", "INTERPRETATION")


def judgment() -> dict[str, Any]:
    """The six judgment policies, each with its rules on screen."""
    from backend.judgment import breadth as br
    from backend.judgment import contradictions as cd
    from backend.judgment import interpretation as it
    from backend.judgment import materiality as mt
    from backend.judgment import observations as ob
    from backend.judgment import persistence as pe

    sub: dict[str, Any] = {}

    sub["OBSERVATIONS"] = _policy(
        "observations", "Observation engine", ob.OBSERVATION_VERSION,
        what="Nineteen kinds of structured claim, each with a reviewed "
             "template that says exactly what it may assert.",
        why="A template cannot assert more than its slots. A paragraph can, "
            "and will.",
        when="After the engines run and before anything is written.",
        rules={"types": list(ob.TYPES),
               "templates": dict(ob.TEMPLATES),
               "needs_facts": sorted(ob.NEEDS_FACTS),
               "always_early": sorted(ob.ALWAYS_EARLY)})

    sub["MATERIALITY"] = _policy(
        "materiality", "Materiality policy", mt.MATERIALITY_VERSION,
        what="Nine weighted inputs producing one of five bands.",
        why="'Material' decided by a model is decided differently every time, "
            "and a 48% rise on a small base outranks a real one.",
        when="On every movement the answer reports.",
        rules={"bands": list(mt.BANDS), "weights": dict(mt.WEIGHTS),
               "appetite_floor": mt.APPETITE_FLOOR,
               "evidence_caps": dict(mt.EVIDENCE_CAPS)})

    sub["BREADTH_AND_CONCENTRATION"] = _policy(
        "breadth", "Breadth and concentration", br.BREADTH_VERSION,
        what="Broad, concentrated, mixed or undetermined, from counts and a "
             "Herfindahl index.",
        why="The brief's own line: do not let the model decide broad versus "
            "concentrated from prose alone.",
        when="Whenever a movement is decomposed across entities.",
        rules={"verdicts": [br.BROAD, br.CONCENTRATED, br.MIXED,
                            br.UNDETERMINED],
               "min_entities": br.MIN_ENTITIES,
               "concentrated_at": br.CONCENTRATED_AT,
               "broad_top_at": br.BROAD_TOP_AT,
               "hhi_concentrated_at": br.HHI_CONCENTRATED_AT})

    sub["PERSISTENCE"] = _policy(
        "persistence", "Persistence and noise", pe.PERSISTENCE_VERSION,
        what="Persistent, spike, volatile, reversing or insufficient, from "
             "the shape of the history.",
        why="A movement and a trend are different claims, and only one of "
            "them justifies acting.",
        when="Whenever more than one period is available.",
        rules={"verdicts": [pe.PERSISTENT, pe.SPIKE, pe.VOLATILE,
                            pe.REVERSING, pe.INSUFFICIENT],
               "min_periods": pe.MIN_PERIODS,
               "efficiency_at": pe.EFFICIENCY_AT,
               "spike_dominance": pe.SPIKE_DOMINANCE})

    sub["CONTRADICTIONS"] = _policy(
        "contradictions", "Contradiction taxonomy and diagnostics",
        cd.CONTRADICTION_VERSION,
        what="Thirteen explanations, fifteen recorded diagnostics, and five "
             "outcomes including UNRESOLVED.",
        why="A contradiction has a dozen plausible explanations and a model "
            "asked what is going on will supply one, fluently, with no "
            "evidence.",
        when="Whenever two validated signals point opposite ways in risk "
             "terms.",
        rules={"taxonomy": [{"id": e, "means": cd.MEANS[e]}
                            for e in cd.EXPLANATIONS],
               "checks": [{"id": c, "label": cd.CHECK_LABEL[c],
                           "question": cd.CHECK_QUESTION[c],
                           "supports": cd.SUPPORTS[c]} for c in cd.CHECK_IDS],
               "outcomes": list(cd.OUTCOMES),
               "min_checks": cd.MIN_CHECKS})

    sub["INTERPRETATION"] = _policy(
        "interpretation", "Interpretation contract",
        it.INTERPRETATION_VERSION,
        what="Nine sections, each PRESENT, INSUFFICIENT or NOT_APPLICABLE.",
        why="A contract with nine required sections and no way to decline "
            "produces nine sections every time, three of them invented.",
        when="After the observations and before the narrative model.",
        rules={"sections": [{"id": s, "purpose": it.PURPOSE[s],
                             "feeds": list(it.FEEDS[s])} for s in it.SECTIONS],
               "states": list(it.STATES), "max_words": it.MAX_WORDS,
               "pack_fields": list(it.PACK_FIELDS)})

    return {"version": TABS_VERSION, "tab": JUDGMENT,
            "purpose": PURPOSE[JUDGMENT],
            "subtabs": list(JUDGMENT_SUBTABS),
            "policies": sub}


def _policy(policy_id: str, name: str, version: str, *, what: str, why: str,
            when: str, rules: dict[str, Any]) -> dict[str, Any]:
    """One judgment policy, with §117's answers and its actual rules.

    The rules are included rather than described. A policy tab that says
    "materiality is assessed against a weighted model" tells a Model Risk
    reviewer nothing they can challenge; the weights tell them everything.
    """
    return {
        "id": policy_id, "name": name, "version": version,
        "explanation": ex.Explanation(
            what=what, why=why, when=when,
            validated="By the analytical judgment suite, which evaluates this "
                      "policy separately from the others.",
            performing=ex.NOT_MEASURED,
            stale_or_failing=ex.NOTHING_STALE,
            release=f"version {version}, recorded on the release manifest as "
                    "its own staleness axis").to_dict(),
        "rules": rules,
    }


# ---------------------------------------------------------------------------
# §109 — Visualization grammar, with the result-shape lab
# ---------------------------------------------------------------------------

def visual_grammar() -> dict[str, Any]:
    from backend.judgment import visual_critic as vc
    from backend.judgment import visual_grammar as vg

    return {
        "version": TABS_VERSION, "tab": VISUAL_GRAMMAR,
        "purpose": PURPOSE[VISUAL_GRAMMAR],
        "explanation": ex.Explanation(
            what="Fifteen semantic field roles, a mapping from result shapes "
                 "to charts, a thirteen-factor suitability score and a "
                 "twelve-check critic.",
            why="A rating grade stored as an integer is not a measure. "
                "Anything reading dtypes draws it as a bar.",
            when="After the result and before it is rendered.",
            validated="By the visualization evaluation suite and the chart "
                      "teaching case library, including its invalid "
                      "examples.",
            performing=ex.NOT_MEASURED,
            stale_or_failing=ex.NOTHING_STALE,
            release="The visualization grammar version is a release "
                    "staleness axis.").to_dict(),
        "roles": [{"id": r, "means": vg.ROLE_MEANS[r],
                   "plottable": vg.plottable(r),
                   "labelling": vg.labelling(r),
                   "never_drawn": r in vg.NEVER_DRAWN} for r in vg.ROLES],
        "mapping": [{"shape": s, "means": vg.SHAPE_MEANS[s],
                     "default": vg.default_for(s),
                     "default_label": vg.CHART_LABEL.get(vg.default_for(s),
                                                         ""),
                     "alternatives": list(vg.MAPPING[s][1:])}
                    for s in vg.SHAPES],
        "suitability": {"factors": list(vg.FACTORS),
                        "weights": dict(vg.WEIGHTS),
                        "threshold": vg.THRESHOLD,
                        "fatal": sorted(vg.FATAL),
                        "soft_floor": vg.SOFT_FLOOR,
                        "category_ceilings": dict(vg.CATEGORY_CEILING)},
        "critic": [{"id": c, "asks": vc.ASKS[c], "fatal": c in vc.FATAL,
                    "mandatory": c in vc.MANDATORY} for c in vc.CHECKS],
        "accessibility": ("Every chart carries a table with the same "
                          "figures. A chart with no accessible equivalent is "
                          "refused by the critic."),
        "precision_contract": {"max_decimals": vc.MAX_DECIMALS},
        "interactions": _interactions(),
    }


def _interactions() -> list[dict[str, str]]:
    from backend.judgment import selection as se

    return [{"chart": chart, "means": means}
            for chart, means in sorted(se.MEANS.items())]


def result_shape_lab(shape: str, roles: dict[str, str],
                     **inputs: Any) -> dict[str, Any]:
    """§109's lab: a sanitised result schema in, the whole decision out.

    Scores, rejections, the chosen visual and the fallback — because the
    losing candidates are what make the choice arguable, and a lab that
    showed only its answer would be a slower way of looking at the chart.

    No portfolio data is needed or accepted. The lab takes a SHAPE.
    """
    from backend.judgment import visual_grammar as vg

    if shape not in vg.SHAPES:
        return {"error": "unknown_shape", "shapes": list(vg.SHAPES),
                "message": f"{shape!r} is not one of the fifteen result "
                           "shapes the grammar knows."}
    selection = vg.select(shape, vg.Inputs(roles=dict(roles), **inputs))
    return {
        "version": TABS_VERSION,
        "shape": shape, "shape_means": vg.SHAPE_MEANS[shape],
        "field_roles": {slot: {"role": role,
                               "means": vg.ROLE_MEANS.get(role, "unknown "
                                                                "role")}
                        for slot, role in roles.items()},
        "candidates": [s.to_dict() for s in selection.scores],
        "chosen": selection.chosen,
        "chosen_label": vg.CHART_LABEL.get(selection.chosen, selection.chosen),
        "fell_back": selection.fell_back,
        "reason": selection.reason(),
        "formatting": {"max_decimals": 2,
                       "note": "Two decimals on every user-facing value."},
        "used_live_data": False,
    }


# ---------------------------------------------------------------------------
# §113 — coverage map
# ---------------------------------------------------------------------------

#: §113's columns. Named as strings rather than derived from data, because
#: §113 also says not to use numeric values as categorical headers — and a
#: column list generated from difficulty codes is how that happens.
COVERAGE_COLUMNS: tuple[str, ...] = (
    "foundational", "intermediate", "complex", "expert", "adversarial",
    "corporate", "retail", "english", "arabic", "routine_model",
    "complex_model", "critical",
)


def coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """§113's map, as a table a reader can sort rather than a heat picture.

    Cells carry counts and gaps rather than colour alone: a heatmap whose
    only information is colour cannot be read by somebody who needs the
    number, and cannot be exported.
    """
    gaps = [r["family"] for r in rows if not r.get("approved")]
    return {"version": TABS_VERSION, "columns": list(COVERAGE_COLUMNS),
            "rows": rows, "gaps": gaps,
            "note": ("A zero is a gap, not a blank. A family with no approved "
                     "cases demonstrates nothing.")}


__all__ = ["AGENTIC", "BLUEPRINTS", "COVERAGE_COLUMNS", "EVALUATIONS",
           "EVALUATION_SUBTABS", "evaluations", "failures",
           "investigation_reviews", "live_health",
           "prompts", "releases", "route_simulator", "routing",
           "teaching_cases",
           "FEEDBACK", "JUDGMENT", "JUDGMENT_SUBTABS", "KNOWLEDGE", "LABELS",
           "LIVE_HEALTH", "NEEDS", "OVERVIEW", "PROMPTS", "PURPOSE",
           "RELEASES", "REVIEWS", "ROUTING", "SETTINGS", "TABS",
           "TABS_VERSION", "TEACHING_CASES", "VISUAL_GRAMMAR", "blueprints",
           "coverage", "index", "judgment", "knowledge", "result_shape_lab",
           "visible", "visual_grammar"]


# ---------------------------------------------------------------------------
# §110 — Model routing
# ---------------------------------------------------------------------------

def routing(preflight: dict[str, Any] | None = None) -> dict[str, Any]:
    """Which role handles what, why, and what it costs. §110.

    The four "why" answers §110 asks for are written out rather than derived,
    because they are the whole point of the tab: a reader who can see that a
    question routed to the complex planner and cannot see WHY has been shown a
    log line.
    """
    from backend.judgment import judgment_policy as jp
    from backend.llm import roles as rl
    from backend.orchestration import routing as rt
    from backend.teaching import policy as po

    thresholds = po.default()
    return {
        "version": TABS_VERSION, "tab": ROUTING, "purpose": PURPOSE[ROUTING],
        "explanation": ex.Explanation(
            what="The model roles, the signals that pick between them, and "
                 "the thresholds those signals are compared against.",
            why="A product that silently used a different model than the one "
                "configured would produce different answers with the same "
                "Trace.",
            when="Once per question, before anything is planned.",
            validated="By the routing evaluation suite and by the honest "
                      "preflight, which never reports CONNECTED from the "
                      "presence of a key.",
            performing=ex.NOT_MEASURED,
            stale_or_failing=ex.NOTHING_STALE,
            release="The routing policy fingerprint is a release staleness "
                    "axis.").to_dict(),
        # Roles, never model ids. What serves a role is configuration, and a
        # Studio that hard-coded one would be wrong the week after the next
        # model ships.
        "roles": [{"name": r.name, "purpose": rl.PURPOSE.get(r.name, ""),
                   "configured_model": r.model, "effort": r.effort,
                   "inherited": r.inherited,
                   "active": r.name in rl.ACTIVE_ROLES}
                  for r in rl.all_roles(include_inactive=True)],
        "preflight": preflight or {},
        "why": {
            "routine": "The question's signals fall below the complexity "
                       "threshold: one objective, a governed concept, a "
                       "period the vocabulary knows. The routine planner "
                       "answers it and the harder model would answer it "
                       "identically for more money.",
            "complex": "Several objectives, a broad prompt, a "
                       "high-materiality subject, or a signal the routine "
                       "planner already failed on. What is hard is the "
                       "judgement, not the arithmetic.",
            "critic": "A high-risk or client-facing answer, a rubric repair, "
                      "or a challenge pass — the cases where being wrong "
                      "cannot be corrected afterwards.",
            "none": "The question needs no model at all: a metadata lookup, "
                    "a cached result, or a request CreditProbe declines. "
                    "Spending a call to decline is still spending a call.",
        },
        "thresholds": thresholds.to_dict() if hasattr(thresholds, "to_dict")
        else {"fingerprint": getattr(thresholds, "fingerprint", "")},
        "stages": list(getattr(rt, "STAGES", ())),
        "judgment_escalations": jp.policy(),
        "fallback_policy": {
            "when_complex_unavailable": rt.unavailable_policy(),
            "note": ("CreditProbe never silently substitutes a different "
                     "model. It degrades visibly or declines."),
        },
    }


def route_simulator(question: str) -> dict[str, Any]:
    """§110's safe simulator. Predicts; never calls.

    "No API call in simulation" is the instruction, and it is what makes the
    simulator usable: an administrator who can try twenty phrasings for
    nothing will, and one who spends a call per try will try none.
    """
    from backend.orchestration import routing as rt

    signals = rt.signals(question)
    decision = rt.decide(question)
    return {
        "version": TABS_VERSION,
        "question": question,
        "features": signals.to_dict() if hasattr(signals, "to_dict")
        else {"direct": getattr(signals, "direct", None)},
        "route": decision.to_dict() if hasattr(decision, "to_dict") else {},
        "called_a_provider": False,
        "note": ("Predicted from the same signals the runtime uses. Nothing "
                 "was sent anywhere and nothing was spent."),
    }


# ---------------------------------------------------------------------------
# §111 — Prompts and Teaching Packs
# ---------------------------------------------------------------------------

def prompts() -> dict[str, Any]:
    """Versioned prompts and the pack policy. §111.

    Fingerprints rather than text by default. §111 says do not expose secrets
    or client content, and a prompt is the one artefact most likely to have
    accumulated a hard-coded example from a real portfolio.
    """
    from backend.llm import caching as ca
    from backend.teaching import pack as pk

    return {
        "version": TABS_VERSION, "tab": PROMPTS, "purpose": PURPOSE[PROMPTS],
        "explanation": ex.Explanation(
            what="The versioned prompts each model role receives, and the "
                 "policy governing what a Teaching Pack may contain.",
            why="A prompt is configuration that changes every answer. An "
                "unversioned one changes answers with nothing recording that "
                "it did.",
            when="On every call, assembled in a stable order so the cache "
                 "hits.",
            validated="A prompt candidate is promoted only after an "
                      "evaluation, and a regression blocks it.",
            performing=ex.NOT_MEASURED,
            stale_or_failing=ex.NOTHING_STALE,
            release="Prompt fingerprints are recorded on the release "
                    "manifest.").to_dict(),
        "pack_policy": {
            "included": list(pk.INCLUDED),
            "excluded": list(pk.EXCLUDED),
            "budget_characters": getattr(pk, "DEFAULT_BUDGET", 4000),
            "note": ("A pack is dropped whole rather than truncated. Half a "
                     "teaching case teaches half a lesson, and which half is "
                     "arbitrary."),
        },
        "caching": {
            "stable_order": list(ca.STABLE_ORDER),
            "min_cacheable_chars": ca.MIN_CACHEABLE_CHARS,
            "note": ("One breakpoint, after the stable blocks. A cache "
                     "breakpoint after something that changes per question "
                     "caches nothing and costs the write."),
        },
        "promotion": {
            "requires": ["an evaluation against the development corpus",
                         "no regression on the mandatory threads",
                         "a named approver"],
            "note": "A winning candidate is promoted by a person, not by "
                    "having won.",
        },
    }


# ---------------------------------------------------------------------------
# §112 — Evaluations
# ---------------------------------------------------------------------------

EVALUATION_SUBTABS: tuple[str, ...] = (
    "DEVELOPMENT", "SEALED_CERTIFICATION", "LIVE_SMOKE", "AGENTIC",
    "JUDGMENT", "VISUALIZATION", "MODEL_EXPERIMENTS")


def evaluations() -> dict[str, Any]:
    """§112's seven suites, kept apart.

    Separately, always. The four judgment suites already refuse to combine
    into one score for the reason §96 gives, and the same argument covers
    these seven: a sealed certification and a live smoke test fail for
    unrelated reasons, and an average of them tells you about neither.
    """
    return {
        "version": TABS_VERSION, "tab": EVALUATIONS,
        "purpose": PURPOSE[EVALUATIONS],
        "subtabs": list(EVALUATION_SUBTABS),
        "explanation": ex.Explanation(
            what="Seven evaluation suites, each measuring something "
                 "different, none of them averaged together.",
            why="A number without its sample size and interval is a claim "
                "the evidence may not support, and the first thing anybody "
                "quotes.",
            when="Before a release is cut, and after any change to a prompt, "
                 "a policy or the routing.",
            validated="The suites validate everything else; what validates "
                      "them is the sealed holdout, which the production "
                      "planner cannot reach.",
            performing=ex.NOT_MEASURED,
            stale_or_failing=ex.NOTHING_STALE,
            release="Evaluation metrics and critical failures are recorded "
                    "on the release manifest.").to_dict(),
        "reporting_rules": {
            "intervals": ("Every rate carries a 95% Wilson interval and every "
                          "gate compares the LOWER bound."),
            "min_observations": 30,
            "no_combined_score": True,
            "critical_overrides": ("A single critical failure blocks a "
                                   "release whatever the average says."),
        },
        "cost_control": {
            "confirmation_required": True,
            "note": ("A live evaluation is estimated first and run only on "
                     "explicit confirmation. An evaluation that can start by "
                     "accident is one somebody starts by accident."),
        },
    }


# ---------------------------------------------------------------------------
# §186, §201 — Investigation Reviews and the dimension Overview
# ---------------------------------------------------------------------------

def investigation_reviews(views: dict[str, int], rows: int,
                          dimensions: list[dict[str, Any]]) -> dict[str, Any]:
    """§186's tab. Recent Investigations, and how CreditProbe performed.

    The tab that makes the rest of the Studio answerable. Every other tab
    describes an INPUT — a case, a blueprint, a policy, a prompt — and this
    one is the only place those inputs are visible in the act of being used.
    A Studio without it is a room full of controls with no window.
    """
    return {
        "version": TABS_VERSION, "tab": REVIEWS,
        "purpose": PURPOSE[REVIEWS],
        "explanation": ex.Explanation(
            what="Recent authorized Investigations, each with the six "
                 "Intelligence Dimensions, its coverage, its critical "
                 "failures and the feedback people left on it.",
            why="Every other tab describes something CreditProbe was GIVEN. "
                "This is the only tab that shows what it DID with any of it.",
            when="After any release, when a user reports a bad answer, and "
                 "whenever somebody asks how the product is actually "
                 "performing.",
            validated="Each row is an immutable Assurance Record written at "
                      "the time of the answer, not a re-scoring of it.",
            performing=(f"{rows} record(s) visible to this reviewer."
                        if rows else ex.NOT_MEASURED),
            stale_or_failing="Records pinned to a superseded build or "
                             "release are marked stale rather than "
                             "re-scored.",
            release="Each record names the Intelligence Release and Teaching "
                    "Release that served it.").to_dict(),
        "views": [{"id": v, "count": views.get(v, 0)} for v in views],
        "dimensions": dimensions,
        "presentation": "table",
        "presentation_note": ("A table rather than a card wall: the task is "
                              "comparison across many Investigations, and "
                              "that is a scanning task."),
        "score_rules": {
            "operational_assurance_is_not_accuracy": True,
            "raw_feedback_changes_no_score": True,
            "stale_records_are_not_current": True,
        },
    }


# ---------------------------------------------------------------------------
# §115, §116 — Releases and Live AI health
# ---------------------------------------------------------------------------

def releases(gate: dict[str, Any], manifest: dict[str, Any],
             files: list[str], missing: list[str]) -> dict[str, Any]:
    """§115. What is frozen, approved, and stale underneath."""
    return {
        "version": TABS_VERSION, "tab": RELEASES,
        "purpose": PURPOSE[RELEASES],
        "explanation": ex.Explanation(
            what="The frozen Intelligence Release: the approved cases, the "
                 "policies, the prompts, the thresholds and the metrics that "
                 "were true when it was cut.",
            why="Without one, production runs off whatever is approved right "
                "now, and an answer given last week cannot be reproduced.",
            when="Every answer, when production is configured to require a "
                 "release.",
            validated="By the certification the release records, and by the "
                      "staleness check that runs against the live "
                      "configuration.",
            performing=f"gate reports {gate.get('state', 'unknown')}",
            stale_or_failing=(", ".join(gate.get("moved", []))
                              or ex.NOTHING_STALE),
            release=str(manifest.get("release_id") or ex.NOT_RELEASED)
        ).to_dict(),
        "gate": gate, "manifest": manifest,
        "files": list(files), "missing_files": list(missing),
        "actions": [
            {"id": "compare", "label": "Compare releases", "needs": pm.VIEW},
            {"id": "manifest", "label": "View manifest", "needs": pm.VIEW},
            {"id": "validate", "label": "Validate",
             "needs": pm.EVALUATION_RUN},
            {"id": "estimate", "label": "Estimate live certification",
             "needs": pm.EVALUATION_RUN},
            {"id": "promote", "label": "Promote", "needs": pm.RELEASE_APPROVE,
             "note": "Requires a named approver and a reason."},
            {"id": "rollback", "label": "Roll back",
             "needs": pm.RELEASE_APPROVE,
             "note": "Under governance, with the reason recorded."},
        ],
        "never": ("A release never packages the sealed holdout. Its manifest "
                  "carries counts and a fingerprint; the questions and gold "
                  "answers stay where the production planner cannot reach "
                  "them."),
    }


def live_health(provider: dict[str, Any],
                preflight: dict[str, Any]) -> dict[str, Any]:
    """§116. The provider, the roles, and the exact safe local commands.

    Never a key, never an authorization header, never a request body. The
    commands are given in full because an administrator who cannot copy one
    will invent a variant, and the invented variant is the one that logs a
    key.
    """
    return {
        "version": TABS_VERSION, "tab": LIVE_HEALTH,
        "purpose": PURPOSE[LIVE_HEALTH],
        "provider": provider, "roles": preflight,
        "commands": [
            {"what": "A quick check — one small call per active role",
             "windows": "powershell -File scripts/verify-live-ai.ps1 -Mode quick",
             "unix": "python -m backend.validation.live_verify --mode quick"},
            {"what": "The full sealed certification (costs real money)",
             "windows": "powershell -File scripts/verify-live-ai.ps1 -Mode full -Confirm",
             "unix": "python -m intelligence_factory.certify --certify --confirm"},
            {"what": "Provider state without spending anything",
             "windows": "curl http://localhost:8000/api/v1/health/ai",
             "unix": "curl http://localhost:8000/api/v1/health/ai"},
        ],
        "never_shown": ["API keys", "authorization headers", "request bodies",
                        "prompt text containing client content"],
    }


# ---------------------------------------------------------------------------
# §114 — Failures and active learning
# ---------------------------------------------------------------------------

def failures(items: list[dict[str, Any]]) -> dict[str, Any]:
    """§114. What went wrong, who is looking at it, and what came of it.

    The last line of §114 is the one that matters: no automatic production
    self-learning. Everything here is a queue for a person, and an item that
    has not been through one changes nothing in production.
    """
    from backend.teaching import failures as fl

    return {
        "version": TABS_VERSION, "tab": FEEDBACK, "purpose": PURPOSE[FEEDBACK],
        "explanation": ex.Explanation(
            what="Failures found in production and in evaluation, each with a "
                 "proposed correction and an adjudication.",
            why="A product that learned from its own failures automatically "
                "would change what it believes with nobody having agreed to "
                "it.",
            when="Whenever an answer fails a check, a user reports one, or an "
                 "evaluation regresses.",
            validated="An approved correction becomes a regression case and a "
                      "teaching case, both of which are evaluated before any "
                      "release carries them.",
            performing=f"{len(items)} items in the queue",
            stale_or_failing=ex.NOTHING_STALE,
            release="An item is released only as part of a Teaching Release."
        ).to_dict(),
        "categories": [{"id": c.id, "stage": c.stage, "label": c.label,
                        "looks_like": c.looks_like,
                        "critical": fl.is_critical(c.id)}
                       for c in fl.CATEGORIES],
        "items": items,
        "no_automatic_learning": True,
        "note": ("Unreviewed feedback never changes production. An approved "
                 "correction creates a regression case and a teaching case; "
                 "both are evaluated before a release carries them."),
    }


# ---------------------------------------------------------------------------
# §106 — Teaching cases
# ---------------------------------------------------------------------------

def teaching_cases(summary: dict[str, Any], governance: dict[str, Any],
                   coverage_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """§106. The library, and an honest account of who reviewed it.

    The governance sentence leads, because it is the answer to the question a
    Model Risk reviewer actually has: how many of these has a person read?
    A count of two and a half thousand cases beside a count of zero human
    approvals is the truth, and burying it under a family breakdown would
    make the family breakdown the message.
    """
    return {
        "version": TABS_VERSION, "tab": TEACHING_CASES,
        "purpose": PURPOSE[TEACHING_CASES],
        "explanation": ex.Explanation(
            what="Every case CreditProbe learns from, with its status, its "
                 "family, its difficulty and its provenance.",
            why="Retrieval decides what a model sees before it answers. A "
                "library nobody can audit is a set of instructions nobody "
                "read.",
            when="On every question, through governed retrieval — and only "
                 "APPROVED and explicitly governed SYSTEM_VALIDATED cases "
                 "are ever retrieved.",
            validated="Each case carries its own validation record; the "
                      "governance report counts human review only where a "
                      "named reviewer and a timestamp exist.",
            performing=governance.get("sentence", ex.NOT_MEASURED),
            stale_or_failing=ex.NOTHING_STALE,
            release="Approved cases are frozen into the Teaching Release."
        ).to_dict(),
        "governance": governance,
        "summary": summary,
        "coverage": coverage(coverage_rows),
        "filters": ["family", "difficulty", "scope", "language", "status",
                    "owner", "stale", "critical", "model_route"],
        "never_shown": ("Sealed-holdout content is never shown here, in any "
                        "state, to any role."),
    }

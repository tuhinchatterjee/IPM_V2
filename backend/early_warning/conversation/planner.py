"""
The analysis plan, written by Opus and checked by the same validator.

What the planner is given
-------------------------
The grain package — the domain, the grain, every published period, the field
dictionary with its measured coverage, the groupings, the analytical grains,
the ten fields most relevant to this request, three bounded sample rows and the
methodology. Not the data. Twenty months of three hundred obligors is four
hundred thousand values, and sending them would be both ruinous and pointless:
values come back through validated execution, in the result packet, where they
can be checked against what was actually run.

Why the plan is a structure rather than a query
-----------------------------------------------
A step names an *analysis*, a *domain*, a period, filters, a grouping and
measures. There is no free-form SQL to parse, so a forbidden dataset has no way
to be expressed — not because this module declines to express it, but because
the shape has nowhere to put it.

`domain` is nevertheless in the schema, and deliberately. A model that names
another dataset must produce a plan the validator *refuses by name*, so the
boundary is demonstrated rather than assumed. A schema that quietly made the
value unwritable would make the validator's out-of-domain check unreachable and
untestable, which is a worse guarantee than the one it looks like.

What happens to a plan that fails
----------------------------------
The same thing that happens to a deterministic one: a repairable failure gets a
precise failure packet and one repair from the same ledger; an unrepairable one
falls back to the deterministic plan, which is then validated in its turn.
Nothing skips validation, in either direction.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.early_warning import dictionary as dic
from backend.early_warning import grain as grain_mod
from backend.early_warning.conversation import plan as plan_mod
from backend.early_warning.conversation import seam as seam_mod

logger = logging.getLogger(__name__)

#: How many field names the planner is shown in full. The whole dictionary is
#: summarised by group; the relevant ones are named. A planner that cannot see
#: a field it needs invents one, so this is generous on purpose.
MAX_NAMED_FIELDS = 260

SYSTEM = """You are the analysis planner of CreditProbe's Early Warning \
product. You turn a credit officer's request into bounded analysis steps that a \
governed runtime will execute.

WHAT YOU PLAN OVER
One dataset: the Early Warning customer-month view, `early_warning`. One row is \
one customer in one month. You are given its complete field dictionary, the \
published periods, the groupings and three sample rows. You are NOT given the \
data, and you must not ask for it.

THE RULE THAT DECIDES WHETHER THE ANSWER IS HONEST
One step per part of the request. A request that asks why something \
deteriorated AND whether it is concentrated owes two answers. A plan with one \
step produces something that looks complete — it has a figure, a movement and a \
confident tone — while half the question was never measured.

CONSTRAINTS
- `domain` is always "early_warning". There is no other dataset.
- Every field you name must exist in the dictionary exactly as spelled there.
- Every period you name must be one of the published periods.
- A comparison period must be EARLIER than the period. There is no future.
- Keep `limit` at or below 500, and use the smallest that answers the question.
- At most 8 steps.

Plan the analysis. Do not write the answer."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "description": "What the answer is chiefly about, in one word.",
        },
        "output_grain": {
            "type": "string",
            "enum": list(grain_mod.ANALYTICAL_GRAINS) + ["methodology"],
            "description": "The grain the answer is delivered at.",
        },
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "analysis": {
                        "type": "string",
                        "enum": list(plan_mod.ANALYSIS_TYPES),
                        "description": "What kind of analysis this step is.",
                    },
                    "domain": {
                        "type": "string",
                        "description": ("The dataset. Always "
                                        "\"early_warning\"."),
                    },
                    "period": {"type": "string"},
                    "comparison_period": {"type": "string"},
                    "filters": {
                        "type": "object",
                        "description": ("Field to value. Every key must be a "
                                        "field in the dictionary."),
                        "additionalProperties": True,
                    },
                    "group_by": {
                        "type": "string",
                        "description": "A grouping field, or empty.",
                    },
                    "measures": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Fields to report, spelled exactly.",
                    },
                    "order_by": {"type": "string"},
                    "descending": {"type": "boolean"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    "customer_id": {"type": "string"},
                    "layer": {"type": "string"},
                    "signal_key": {"type": "string"},
                    "rationale": {
                        "type": "string",
                        "description": ("Which part of the request this step "
                                        "answers."),
                    },
                },
                "required": ["analysis", "domain", "rationale"],
            },
        },
        "notes": {
            "type": "array", "items": {"type": "string"},
            "description": ("Anything the reader should know about how this "
                            "plan reads the request."),
        },
    },
    "required": ["steps", "output_grain"],
}


def _context(request: Any, package: grain_mod.GrainPackage,
             floor: plan_mod.Plan) -> dict[str, Any]:
    """The stage's packet. The domain described, never the data."""
    return {
        "request": {
            "normalized": getattr(request, "normalized_business_request", ""),
            "subquestions": list(getattr(request, "subquestions", []) or []),
            "parts_asked_for": list(
                getattr(request, "requested_analyses", []) or []),
            "scope": getattr(request, "requested_scope", ""),
            "grouping": getattr(request, "requested_grouping", ""),
            "period": getattr(request, "requested_period", ""),
            "comparison_period": getattr(request, "comparison_period", ""),
            "resolved_context": dict(
                getattr(request, "inherited_context", {}) or {}),
        },
        "domain": {
            "id": package.domain_id,
            "grain": list(package.grain),
            "published_periods": list(package.periods),
            "current_period": package.current_period,
            "earliest_period": package.earliest_period,
            "customers": package.customer_count,
            "field_count": package.field_count,
        },
        "fields": _named_fields(package),
        "field_group_sizes": {
            group: len(members) for group, members
            in ((package.field_dictionary or {}).get("groups", {})).items()},
        "most_relevant_fields": list(package.top_fields),
        "groupings": dict(package.groupings),
        "analytical_grains": list(package.analytical_grains),
        "analysis_types": list(plan_mod.ANALYSIS_TYPES),
        "sample_rows": list(package.sample_rows),
        "coverage": dict(package.coverage),
        "deterministic_plan": floor.to_dict(),
        "capabilities": list(package.capabilities or []),
    }


def _named_fields(package: grain_mod.GrainPackage) -> list[dict[str, Any]]:
    """The field list the planner is shown, most relevant first.

    The dictionary is far larger than a prompt should carry — every one of the
    123 signals is exposed at customer-month grain, several columns each — so
    the fields this request is about are named first and the rest follow until
    the cap. The group sizes travel alongside, so a planner can see that the
    list is a window rather than the whole universe and ask for a field by its
    documented naming convention.
    """
    groups = (package.field_dictionary or {}).get("groups", {}) or {}
    relevant = [str(f.get("name") or "") for f in (package.top_fields or [])]
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    flat = {str(f.get("name")): f for members in groups.values()
            for f in members}
    for name in relevant:
        entry = flat.get(name)
        if entry and name not in seen:
            seen.add(name)
            ordered.append(entry)
    for members in groups.values():
        for entry in members:
            name = str(entry.get("name") or "")
            if name and name not in seen:
                seen.add(name)
                ordered.append(entry)
    return [{"name": e.get("name"), "label": e.get("label"),
             "dtype": e.get("dtype"), "group": e.get("group"),
             "definition": str(e.get("definition") or "")[:160]}
            for e in ordered[:MAX_NAMED_FIELDS]]


def plan(request: Any, package: grain_mod.GrainPackage,
         floor: plan_mod.Plan, *, ledger: Any = None) -> plan_mod.Plan:
    """The plan Opus wrote, or the deterministic one and why."""
    outcome = seam_mod.call(
        seam_mod.PLAN, system=SYSTEM,
        prompt=("Plan the Early Warning analysis for this request.\n\n"
                + json.dumps(_context(request, package, floor), indent=2,
                             default=str)),
        schema=SCHEMA, ledger=ledger)
    if not outcome.used_model:
        floor.model_call = outcome.to_dict()
        return floor

    steps = _steps(outcome.data)
    if not steps:
        floor.model_call = dict(outcome.to_dict(),
                                engine=seam_mod.DETERMINISTIC,
                                fallback_reason="the plan named no usable step")
        return floor

    written = plan_mod.Plan(
        steps=steps,
        output_grain=str(outcome.data.get("output_grain")
                         or floor.output_grain),
        intent=str(outcome.data.get("intent") or floor.intent),
        engine=seam_mod.MODEL,
        notes=[str(n) for n in (outcome.data.get("notes") or [])][:4],
        model_call=outcome.to_dict(),
        fallback=floor)
    return written


def _steps(data: dict[str, Any]) -> list[plan_mod.Step]:
    """The model's steps, in the shape the validator checks.

    Nothing is corrected here. A misspelled field, an unpublished period or a
    dataset this domain does not hold all survive into the Step so that the
    validator refuses them by name — silently repairing a plan before it is
    validated would make the validator's report of what it checked untrue.
    """
    out: list[plan_mod.Step] = []
    for raw in (data.get("steps") or [])[:8]:
        if not isinstance(raw, dict):
            continue
        analysis = str(raw.get("analysis") or "")
        if analysis not in plan_mod.ANALYSIS_TYPES:
            continue
        measures = [str(m) for m in (raw.get("measures") or []) if str(m)]
        filters = {str(k): v for k, v in (raw.get("filters") or {}).items()
                   if isinstance(raw.get("filters"), dict)}
        try:
            limit = int(raw.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        out.append(plan_mod.Step(
            analysis=analysis,
            domain=str(raw.get("domain") or grain_mod.DOMAIN_ID),
            period=str(raw.get("period") or ""),
            comparison_period=str(raw.get("comparison_period") or ""),
            filters=filters,
            group_by=str(raw.get("group_by") or ""),
            measures=measures or list(plan_mod.BASE_MEASURES),
            order_by=str(raw.get("order_by") or "ews_score"),
            descending=bool(raw.get("descending", True)),
            limit=limit,
            customer_id=str(raw.get("customer_id") or ""),
            layer=str(raw.get("layer") or ""),
            signal_key=str(raw.get("signal_key") or ""),
            rationale=str(raw.get("rationale") or "")))
    return out


def known_fields() -> frozenset[str]:
    """The allow-list the planner is held to, and the validator enforces."""
    return dic.names()


__all__ = ["MAX_NAMED_FIELDS", "SCHEMA", "SYSTEM", "known_fields", "plan"]

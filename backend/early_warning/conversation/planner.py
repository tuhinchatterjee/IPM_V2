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
from backend.early_warning import signal_fields as sigf
from backend.early_warning.conversation import plan as plan_mod
from backend.early_warning.conversation import seam as seam_mod

logger = logging.getLogger(__name__)

#: How many non-signal fields the planner is shown in full. There are about a
#: hundred and fifty of them and the cap is above that, so in practice it sees
#: all of them: a planner that cannot see a field it needs invents one.
MAX_NAMED_FIELDS = 260

#: How many sample rows travel with the prompt. Two is enough to see the
#: shapes; three of two and a half thousand columns is a data export.
SAMPLE_ROWS = 2

SYSTEM = """You are the analysis planner of CreditProbe's Early Warning \
product. You turn a credit officer's request into bounded analysis steps that a \
governed runtime will execute.

WHAT YOU PLAN OVER
One dataset: the Early Warning customer-month view, `early_warning`. One row is \
one customer in one month. You are given its fields, the published periods, the \
groupings and two sample rows. You are NOT given the data, and you must not ask \
for it.

HOW THE SIGNAL COLUMNS ARE NAMED
All 123 signals in the inventory are exposed at this grain, and their columns \
are too many to list. They are named `<prefix>_<measure>`, where the prefix is \
in the signal inventory you are given and the measure is one of the suffixes \
listed beside it — so signal 42's score is \
`sig042_covenant_breach_event_score`. Compose the column you need from those \
two lists rather than guessing at one. A signal with no feed in this \
deployment has columns that exist and are empty; the coverage tells you which, \
and planning over an empty column produces an empty answer rather than an \
error.

THE RULE THAT DECIDES WHETHER THE ANSWER IS HONEST
One step per part of the request. A request that asks why something \
deteriorated AND whether it is concentrated owes two answers. A plan with one \
step produces something that looks complete — it has a figure, a movement and a \
confident tone — while half the question was never measured.

CONSTRAINTS
- `domain` is always "early_warning". There is no other dataset. Write it on \
every step.
- `analysis` must be one of the analysis types you are given, spelled exactly.
- `output_grain` must be one of the analytical grains you are given, spelled \
exactly.
- Every field you name must exist in the dictionary exactly as spelled there.
- Every period you name must be one of the published periods, in the same \
`YYYY-MM` form.
- A comparison period must be EARLIER than the period. There is no future.
- `filters` is an object mapping field name to value, not a list.
- Keep `limit` at or below 500, and use the smallest that answers the question.
- At most 8 steps. Keep each `rationale` to one sentence.

THE SHAPE
{"intent": "diagnosis", "output_grain": "population_month", "steps": [
  {"analysis": "population", "domain": "early_warning", "period": "2026-06",
   "filters": {"sector": "Contracting"}, "measures": ["ews_score", "exposure"],
   "rationale": "The position the question is about."},
  {"analysis": "movement", "domain": "early_warning", "period": "2026-06",
   "comparison_period": "2025-12", "filters": {"sector": "Contracting"},
   "measures": ["ews_score"], "rationale": "Whether it has deteriorated."}]}

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
                # `analysis` is the only field a step cannot do without: it
                # decides what the step IS. `domain` has one legal value and
                # a model that saw no reason to repeat a constant has not
                # written a bad plan; `rationale` is for the audit trail.
                # Requiring either turned a usable plan into a fallback.
                "required": ["analysis"],
            },
        },
        "notes": {
            "type": "array", "items": {"type": "string"},
            "description": ("Anything the reader should know about how this "
                            "plan reads the request."),
        },
    },
    # Same reasoning. Without steps there is no plan; `output_grain` has a
    # sensible default and is not worth losing a plan over.
    "required": ["steps"],
}

#: Names a planner reaches for that mean an analysis this product has under
#: another name. Mapped into the vocabulary the schema already declares —
#: never into a new one, and never invented where there is no match.
_ANALYSIS_ALIASES: dict[str, str] = {
    "trend": plan_mod.MOVEMENT,
    "trend_analysis": plan_mod.MOVEMENT,
    "time_series": plan_mod.MOVEMENT,
    "change": plan_mod.MOVEMENT,
    "deterioration": plan_mod.MOVEMENT,
    "rank": plan_mod.RANKING,
    "top_n": plan_mod.RANKING,
    "obligors": plan_mod.RANKING,
    "borrowers": plan_mod.RANKING,
    "names": plan_mod.RANKING,
    "group": plan_mod.GROUPING,
    "group_by": plan_mod.GROUPING,
    "breakdown": plan_mod.GROUPING,
    "segmentation": plan_mod.GROUPING,
    "distribution": plan_mod.GROUPING,
    "portfolio": plan_mod.POPULATION,
    "summary": plan_mod.POPULATION,
    "overview": plan_mod.POPULATION,
    "aggregate": plan_mod.POPULATION,
    "driver": plan_mod.DIAGNOSIS,
    "drivers": plan_mod.DIAGNOSIS,
    "root_cause": plan_mod.DIAGNOSIS,
    "why": plan_mod.DIAGNOSIS,
    "concentration_analysis": plan_mod.CONCENTRATION,
    "systemic": plan_mod.CONCENTRATION,
    "compare": plan_mod.COMPARISON,
    "comparison_analysis": plan_mod.COMPARISON,
    "borrower_detail": plan_mod.BORROWER,
    "customer": plan_mod.BORROWER,
    "obligor": plan_mod.BORROWER,
    "signal": plan_mod.EVIDENCE,
    "signals": plan_mod.EVIDENCE,
    "lineage": plan_mod.EVIDENCE,
    "layers": plan_mod.LAYER,
    "methodology_explanation": plan_mod.METHODOLOGY,
}

#: The same, for the output grain.
_GRAIN_ALIASES: dict[str, str] = {
    "customer": "customer_month",
    "borrower_month": "customer_month",
    "obligor_month": "customer_month",
    "borrower": "customer_latest",
    "latest": "customer_latest",
    "portfolio_month": "population_month",
    "portfolio": "population_month",
    "population": "population_month",
    "segment_month": "group_month",
    "sector_month": "group_month",
    "group": "group_month",
    "trend": "population_trend",
    "portfolio_trend": "population_trend",
}


def tidy(data: dict[str, Any]) -> dict[str, Any]:
    """A model's plan, mapped into this product's vocabulary.

    Only the vocabulary. An analysis this product does not have under any
    name is left exactly as it arrived so `_steps` drops it and the trace
    says which one; a domain that is not this one is left alone so the
    VALIDATOR refuses it by name. Correcting either here would hide the two
    things worth seeing.
    """
    steps = []
    for raw in data.get("steps") or []:
        if not isinstance(raw, dict):
            continue
        step = dict(raw)
        analysis = str(step.get("analysis") or "").strip().lower()
        analysis = analysis.replace(" ", "_").replace("-", "_")
        if analysis not in plan_mod.ANALYSIS_TYPES:
            analysis = _ANALYSIS_ALIASES.get(analysis, analysis)
        step["analysis"] = analysis
        limit = step.get("limit")
        if isinstance(limit, (int, float)) and not isinstance(limit, bool):
            # Clamped rather than refused: a planner asking for a thousand
            # rows wants "all of them", and the bound is the product's answer
            # to that rather than a reason to lose the plan.
            step["limit"] = max(1, min(int(limit), 500))
        if isinstance(step.get("filters"), list):
            # Some planners write filters as [{"field": x, "value": y}].
            merged: dict[str, Any] = {}
            for entry in step["filters"]:
                if isinstance(entry, dict) and "field" in entry:
                    merged[str(entry["field"])] = entry.get("value")
                elif isinstance(entry, dict):
                    merged.update({str(k): v for k, v in entry.items()})
            step["filters"] = merged
        steps.append(step)
    out = dict(data)
    out["steps"] = steps

    grain = str(out.get("output_grain") or "").strip().lower()
    if grain and grain not in grain_mod.ANALYTICAL_GRAINS \
            and grain != "methodology":
        mapped = _GRAIN_ALIASES.get(grain)
        if mapped:
            out["output_grain"] = mapped
        else:
            # Not a grain this product delivers at, and not one that maps to
            # one. Dropped rather than guessed: the deterministic grain is a
            # better answer than a plausible wrong one, and the schema makes
            # it optional for exactly this case.
            out.pop("output_grain", None)
    return out


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
        "signal_inventory": _signal_inventory(),
        "signal_column_suffixes": _signal_suffixes(),
        "field_group_sizes": {
            group: len(members) for group, members
            in ((package.field_dictionary or {}).get("groups", {})).items()},
        "most_relevant_fields": list(package.top_fields),
        "groupings": dict(package.groupings),
        "analytical_grains": list(package.analytical_grains),
        "analysis_types": list(plan_mod.ANALYSIS_TYPES),
        "sample_rows": list(package.sample_rows)[:SAMPLE_ROWS],
        "coverage": dict(package.coverage),
        "deterministic_plan": floor.to_dict(),
        "capabilities": list(package.capabilities or []),
    }


def _named_fields(package: grain_mod.GrainPackage) -> list[dict[str, Any]]:
    """Every field that is not one signal's own column, described.

    The signal columns are excluded and reached through the inventory and the
    suffix list instead. Listing them here would be two thousand entries of
    which the request needs at most a handful, and a prompt that spends its
    attention on signals the question has nothing to do with is a prompt that
    plans worse, not better.
    """
    groups = (package.field_dictionary or {}).get("groups", {}) or {}
    out: list[dict[str, Any]] = []
    for group, members in groups.items():
        if group == dic.SIGNAL_SCORES:
            continue
        for entry in members:
            out.append({
                "name": entry.get("name"), "label": entry.get("label"),
                "dtype": entry.get("type"), "group": group,
                "unit": entry.get("unit"),
                "definition": str(entry.get("definition") or "")[:150],
                "missing_rate": (entry.get("coverage")
                                 or {}).get("missing_rate"),
            })
    return out[:MAX_NAMED_FIELDS]


def _signal_inventory() -> list[dict[str, Any]]:
    """All 123 signals, with the prefix their columns are built from."""
    return [{"num": entry.num, "prefix": entry.prefix, "name": entry.name,
             "node": entry.code, "layer": entry.layer, "status": entry.status,
             "measures": entry.what_is_measured,
             "source_system": entry.source_system}
            for entry in sigf.fields()]


def _signal_suffixes() -> dict[str, list[dict[str, str]]]:
    """Which measures each kind of inventory row carries."""
    return {
        "scored": [{"suffix": suffix, "label": label}
                   for suffix, _, label, _ in sigf.SCORED_MEASURES],
        "not_scored": [{"suffix": suffix, "label": label}
                       for suffix, _, label, _ in sigf.INVENTORY_MEASURES],
    }


def plan(request: Any, package: grain_mod.GrainPackage,
         floor: plan_mod.Plan, *, ledger: Any = None) -> plan_mod.Plan:
    """The plan Opus wrote, or the deterministic one and why."""
    outcome = seam_mod.call(
        seam_mod.PLAN, system=SYSTEM,
        prompt=("Plan the Early Warning analysis for this request.\n\n"
                + json.dumps(_context(request, package, floor), indent=2,
                             default=str)),
        schema=SCHEMA, ledger=ledger, tidy=tidy)
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


REPAIR_SYSTEM = """You are repairing an Early Warning analysis plan that the \
governed validator refused. You are told exactly what it refused and what the \
domain offers instead.

Return the WHOLE plan, corrected. Keep every step whose purpose still stands \
and change only what the failures name.

WHAT USUALLY NEEDS FIXING
- A grouping the book cannot be partitioned by. The allowed groupings are \
given in full; there are twelve of them and one of them is almost always what \
was meant. A field being readable does not make it a level: grouping by a \
customer name or a score gives one group per obligor.
- A field that does not exist under that name. The nearest real names are \
given.
- A period that was never published, or a comparison period that is not \
earlier than the period.

IF NOTHING FITS
Drop the step rather than substituting a different question. A step that \
answers something nobody asked is worse than a part of the request the answer \
says it could not cover."""


def repair(request: Any, package: grain_mod.GrainPackage,
           refused: plan_mod.Plan, packet: dict[str, Any],
           fallback: plan_mod.Plan, *, ledger: Any = None) -> plan_mod.Plan:
    """The plan Opus corrected, or the deterministic repair and why.

    Spends from the same ledger as everything else — a repair loop that
    started fresh each time is the specific failure the one-ledger design
    exists to prevent — and falls back to the deterministic repair when the
    model is unavailable or its correction is unusable.
    """
    outcome = seam_mod.call(
        seam_mod.REPAIR, system=REPAIR_SYSTEM,
        prompt=("Repair this Early Warning plan.\n\n"
                + json.dumps(packet, indent=2, default=str)),
        schema=SCHEMA, ledger=ledger, tidy=tidy)
    if not outcome.used_model:
        fallback.model_call = outcome.to_dict()
        return fallback

    steps = _steps(outcome.data)
    if not steps:
        fallback.model_call = dict(
            outcome.to_dict(), engine=seam_mod.DETERMINISTIC,
            fallback_reason="the repair named no usable step")
        return fallback

    del request, package
    return plan_mod.Plan(
        steps=steps,
        output_grain=str(outcome.data.get("output_grain")
                         or refused.output_grain),
        intent=str(outcome.data.get("intent") or refused.intent),
        engine="model-repair",
        notes=list(refused.notes) + [
            str(n) for n in (outcome.data.get("notes") or [])][:3],
        model_call=outcome.to_dict(),
        fallback=fallback)


def known_fields() -> frozenset[str]:
    """The allow-list the planner is held to, and the validator enforces."""
    return dic.names()


__all__ = ["MAX_NAMED_FIELDS", "REPAIR_SYSTEM", "SAMPLE_ROWS", "SCHEMA",
           "SYSTEM", "known_fields", "plan", "repair", "tidy"]

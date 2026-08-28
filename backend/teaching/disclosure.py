"""
What the Trace and the Calculation Pack may say about the teaching layer.
§45, §46.

One module, two surfaces, one rule
-----------------------------------
§45 and §46 ask for almost the same seven things — retrieval, routing,
objective coverage, plan validation, critic, result validation, interpretation
rubric — on two different surfaces. Written twice they drift, and the way they
drift is that one of them starts showing something the other one redacts.

So the panel is built once, and the Pack's sheet is a rendering of it.

The three refusals
------------------
Both sections end with the same prohibitions, and each is enforced here rather
than trusted to the caller:

**No benchmark gold.** Nothing in this module can reach the holdout, and a
scan refuses any payload whose keys look like an answer key. The seal is the
basis of every accuracy claim CreditProbe makes; a Trace that leaked one case's
gold answer would not be a small problem.

**No confidential prompts to ordinary users.** Prompt text is admin-only, and
the panel says "withheld" rather than omitting the row — an absent row reads as
"there was no prompt", which is a different and untrue statement.

**No teaching case content.** Retrieval reports ids, scores and matched
features. The worked example itself went to the planner; putting it in a Trace
an ordinary user reads puts a governed teaching case in front of an audience it
was never reviewed for.
"""

from __future__ import annotations

import re
from typing import Any

DISCLOSURE_VERSION = "1.0.0"

#: Who is looking. Prompt text is admin-only (§45); everything else is shown to
#: anyone who can see the Trace at all.
ADMIN_ROLES: frozenset[str] = frozenset({"ADMIN", "SUPERUSER"})

#: The seven sections §45 names, in the order a reader wants them: what the
#: model was shown, what served it, whether the question was covered, and then
#: the three validations in the order they ran.
SECTIONS: tuple[str, ...] = (
    "teaching_retrieval",
    "model_routing",
    "objective_coverage",
    "plan_validation",
    "critic_repair",
    "result_validation",
    "interpretation_rubric",
)

#: Keys that would mean a gold answer or a sealed case had reached a payload.
#: Matched on the key rather than the value, because a value that happens to
#: equal the gold answer is the product being right, and a KEY called "gold" is
#: the seal being broken.
_FORBIDDEN_KEY = re.compile(
    r"gold|holdout|sealed|expected_answer|answer_key|chain_of_thought"
    r"|reasoning_trace|scratchpad", re.I)

WITHHELD = "withheld — visible to administrators"


class Leak(RuntimeError):
    """A payload carried something §45 forbids showing.

    Raised rather than filtered. A silent filter here would mean a caller
    passing gold answers never finds out, and the next surface that forgets to
    filter shows them.
    """


def _scan(payload: Any, path: str = "") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _FORBIDDEN_KEY.search(str(key)):
                raise Leak(f"{path}{key} may not appear in a Trace or a "
                           "Calculation Pack (§45, §46)")
            _scan(value, f"{path}{key}.")
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            _scan(item, path)


def _admin(role: str) -> bool:
    return str(role or "").strip().upper() in ADMIN_ROLES


def _retrieval(gate: Any, result: Any) -> dict[str, Any]:
    """§45's TEACHING RETRIEVAL block. Ids, relevance, features, release."""
    entries = list(getattr(result, "entries", ()) or ())
    return {
        "release": getattr(gate, "release_id", "") or "",
        "release_state": getattr(gate, "state", "") or "",
        "release_note": getattr(gate, "reason", "") or "",
        "case_count": len(entries),
        "cases": [{
            "case_id": e.case_id,
            "case_version": e.case_version,
            "relevance": round(float(e.relevance_score), 4),
            "matched_features": list(e.matched_features),
            "why": e.why_retrieved,
            "cluster": e.diversity_cluster,
            "tokens": e.estimated_tokens,
            "status": e.approved_status,
            "ontology_version": e.ontology_version,
        } for e in entries],
        "refused": dict(getattr(result, "refused", {}) or {}),
    }


def _routing(decision: Any, cascade: Any) -> dict[str, Any]:
    """§45's MODEL ROUTING block, from §25's persisted record."""
    record = decision.record() if hasattr(decision, "record") else {}
    steps = cascade.to_dict() if hasattr(cascade, "to_dict") else {}
    return {**record, "cascade": steps}


def _coverage(coverage: Any) -> dict[str, Any]:
    """§45's OBJECTIVE COVERAGE block."""
    if coverage is None:
        return {}
    return {
        "total": getattr(coverage, "total", 0),
        "complete": getattr(coverage, "complete", 0),
        "by_status": (coverage.by_status()
                      if hasattr(coverage, "by_status") else {}),
        "presentable": getattr(coverage, "presentable", False),
        "sentence": (coverage.sentence()
                     if hasattr(coverage, "sentence") else ""),
        "objectives": [{
            "id": o.objective_id, "description": o.description,
            "action": o.action, "status": o.status, "note": o.note,
        } for o in (getattr(coverage, "objectives", ()) or ())],
    }


def panel(*, gate: Any = None, retrieval: Any = None, decision: Any = None,
          cascade: Any = None, coverage: Any = None,
          plan_validation: dict[str, Any] | None = None,
          critic: dict[str, Any] | None = None,
          result_validation: dict[str, Any] | None = None,
          rubric: dict[str, Any] | None = None,
          prompts: dict[str, str] | None = None,
          viewer_role: str = "") -> dict[str, Any]:
    """The seven sections §45 asks the Trace to show.

    Every argument is optional and an absent one produces an empty section
    rather than a missing key. A Trace that omits "critic_repair" when no
    critic ran reads as a Trace that forgot to record it, and the two are worth
    telling apart.
    """
    built: dict[str, Any] = {
        "version": DISCLOSURE_VERSION,
        "teaching_retrieval": _retrieval(gate, retrieval)
        if retrieval is not None or gate is not None else {},
        "model_routing": _routing(decision, cascade)
        if decision is not None else {},
        "objective_coverage": _coverage(coverage),
        "plan_validation": dict(plan_validation or {}),
        "critic_repair": dict(critic or {}),
        "result_validation": dict(result_validation or {}),
        "interpretation_rubric": dict(rubric or {}),
    }

    # §45: do not expose confidential prompts to ordinary users. Said rather
    # than omitted — an absent row reads as "there was no prompt".
    given = dict(prompts or {})
    if given:
        built["prompts"] = ({name: text for name, text in given.items()}
                            if _admin(viewer_role)
                            else {name: WITHHELD for name in given})

    _scan(built)
    return built


# ---------------------------------------------------------------- §46 rows

def sheet_rows(built: dict[str, Any]) -> list[tuple[str, str]]:
    """The panel as label/value rows for the Calculation Pack.

    §46's list, in its order. A rendering of the same object the Trace shows,
    so the two cannot disagree about what a run did.
    """
    retrieval = built.get("teaching_retrieval") or {}
    routing = built.get("model_routing") or {}
    coverage = built.get("objective_coverage") or {}
    plan = built.get("plan_validation") or {}
    critic = built.get("critic_repair") or {}
    result = built.get("result_validation") or {}
    rubric = built.get("interpretation_rubric") or {}
    cascade = routing.get("cascade") or {}

    def _list(values: Any) -> str:
        return ", ".join(str(v) for v in (values or [])) or "—"

    def _say(value: Any) -> str:
        if value is None or value == "":
            return "—"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value)

    rows: list[tuple[str, str]] = [
        ("Teaching Release", _say(retrieval.get("release"))),
        ("Release state", _say(retrieval.get("release_state"))),
        ("Teaching cases retrieved",
         _list([c.get("case_id") for c in retrieval.get("cases") or []])),
        ("Retrieval refused", _list(
            [f"{k}: {v}" for k, v in (retrieval.get("refused") or {}).items()])),
        ("Prompt versions", _list(sorted(built.get("prompts") or {}))),
        ("Initial route", _say(routing.get("initial_route"))),
        ("Final route", _say(routing.get("final_route"))),
        ("Route score", _say(routing.get("route_score"))),
        ("Route reasons", _list(routing.get("route_reasons"))),
        ("Model role", _say(routing.get("model_role"))),
        ("Configured model", _say(routing.get("configured_model"))),
        ("Served model", _say(routing.get("served_model"))),
        ("Model substituted", _say(routing.get("substituted"))),
        ("Effort", _say(routing.get("effort"))),
        ("Escalated from", _say(routing.get("escalation"))),
        ("Escalation reason", _say(routing.get("escalation_reason"))),
        ("Degraded route", _say(routing.get("degraded"))),
        ("Model calls", _say(cascade.get("model_calls"))),
        ("Objectives", _say(coverage.get("total"))),
        ("Objectives complete", _say(coverage.get("complete"))),
        ("Objective coverage", _list(
            [f"{k}: {v}" for k, v in (coverage.get("by_status") or {}).items()
             if v])),
        ("Coverage statement", _say(coverage.get("sentence"))),
        ("Plan validation", _say(plan.get("status") or plan.get("result"))),
        ("Plan validation detail", _say(plan.get("detail"))),
        ("Critic result", _say(critic.get("status") or critic.get("result"))),
        ("Critic reason", _say(critic.get("reason"))),
        ("Result validation", _say(result.get("status")
                                   or result.get("result"))),
        ("Invariants failed", _list(result.get("failed"))),
        ("Interpretation rubric", _say(rubric.get("status")
                                       or rubric.get("result"))),
        ("Rubric findings", _list(rubric.get("findings"))),
    ]
    return rows


def summary(built: dict[str, Any]) -> str:
    """One sentence for a header chip.

    Says the two things a reader wants before opening anything: which model
    role answered, and whether every objective was settled.
    """
    routing = built.get("model_routing") or {}
    coverage = built.get("objective_coverage") or {}
    role = routing.get("model_role") or "no model"
    total = coverage.get("total") or 0
    complete = coverage.get("complete") or 0
    if not total:
        return f"Planned by {role}."
    return f"Planned by {role}; {complete} of {total} objectives complete."


__all__ = ["ADMIN_ROLES", "DISCLOSURE_VERSION", "Leak", "SECTIONS",
           "WITHHELD", "panel", "sheet_rows", "summary"]

"""What the Scorecard Validation agent may do, and what it may never do. §20.

The agent is a conversational surface over an engine that was already
finished before the agent existed. That ordering is the whole design: every
number it can put in a sentence came from `runner`, every verdict from
`Limit.verdict`, every finding from `findings`. It has no arithmetic of its
own and no way to acquire any.

Three prohibitions, made structural
-----------------------------------
**No arbitrary execution.** There is no tool that takes SQL, a Python
expression, a column list or a filter predicate. The agent names a model and
a test; the engine decides what that means. A tool that accepted a `where`
clause would be a tool through which a model could ask for anything.

**No arithmetic.** No tool returns raw rows for the agent to aggregate. The
smallest thing it can ask for is a completed `Result`, which already carries
its value, its limit, its verdict and its explanation. There is nothing left
for a language model to compute, and so nothing it can compute wrongly.

**No other domain.** Every tool reaches the engine through `models.get` or
`runner.population`, both of which call `domains.require_validation_domain`.
The check is below this module rather than in it, so a tool added tomorrow
inherits it without its author remembering to.

Clarification rather than a guess
---------------------------------
`resolve` turns a request into either a call or a question. Asked to "check
discrimination" with three scorecards in the deployment, it asks which one —
it does not pick the first, and it does not pick the one most recently
discussed. A validation engine that guesses which model a question was about
produces a correct number attached to the wrong scorecard, which is worse
than no answer because it looks like an answer.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agentic.tools import Tool, ToolDenied, ToolUnknown
from backend.scorecard import domains
from backend.scorecard.validation import findings as finding_engine
from backend.scorecard.validation import models as model_registry
from backend.scorecard.validation import registry as test_registry
from backend.scorecard.validation import regulatory as regulatory_map
from backend.scorecard.validation import report as report_studio
from backend.scorecard.validation import runner, states

logger = logging.getLogger(__name__)

AGENT_VERSION = "1.0.0"

AGENT_ID = "scorecard_validation_analyst"
AGENT_NAME = "Scorecard Validation Analyst"

#: What this agent is for, in the words it should use to decline anything
#: else. Held here rather than in a prompt file because the refusal is a
#: product decision, not a wording preference.
SCOPE = (
    "Independent validation of the three scorecards this deployment "
    "validates: Retail Application, Retail Behaviour and Saudi SME. It can "
    "run any of the 48 registered validation tests, explain what each one "
    "measures, assemble the findings, and draft the validation report."
)

OUT_OF_SCOPE = (
    "Anything that is not the validation of one of those three scorecards. "
    "Portfolio analysis, provisioning, early warning, borrower questions and "
    "the rest of the platform are answered by the Cockpit, which is a "
    "different surface with different data access."
)

LIST_MODELS = "scv_list_models"
LIST_TESTS = "scv_list_tests"
EXPLAIN_TEST = "scv_explain_test"
PERIODS = "scv_periods"
RUN_TEST = "scv_run_test"
RUN_CATEGORY = "scv_run_category"
FINDINGS = "scv_findings"
REGULATORY = "scv_regulatory_coverage"
DRAFT_REPORT = "scv_draft_report"

SERVICE = "backend.scorecard.validation"

TOOLS: tuple[Tool, ...] = (
    Tool(LIST_MODELS, "List scorecards",
         "The three scorecards this deployment validates, their governed "
         "record, and which tests each one can support.",
         SERVICE, cost="free"),
    Tool(LIST_TESTS, "List validation tests",
         "The 48 registered tests, optionally filtered to one category.",
         SERVICE, parameters=("category",), cost="free"),
    Tool(EXPLAIN_TEST, "Explain a test",
         "What one test measures, how it is calculated, what it needs, and "
         "what it cannot tell you.",
         SERVICE, parameters=("test_id",), required=("test_id",),
         cost="free"),
    Tool(PERIODS, "Periods and maturity",
         "Which months a scorecard has, and which of them have a realised "
         "outcome. The answer to most wrong numbers in model validation.",
         SERVICE, parameters=("model_id",), required=("model_id",),
         reads_data=True, cost="free"),
    Tool(RUN_TEST, "Run one validation test",
         "Execute one registered test against one scorecard and return its "
         "Result — value, limit, verdict, evidence and explanation.",
         SERVICE,
         parameters=("model_id", "test_id", "period", "segment",
                     "segment_field"),
         required=("model_id", "test_id"), reads_data=True, cost="scan"),
    Tool(RUN_CATEGORY, "Run a validation category",
         "Every test in one category, refusals included.",
         SERVICE, parameters=("model_id", "category", "period"),
         required=("model_id", "category"), reads_data=True, cost="scan"),
    Tool(FINDINGS, "Assess findings",
         "Run every applicable test and return the findings, including the "
         "cross-test patterns and the shortlist to act on first.",
         SERVICE, parameters=("model_id",), required=("model_id",),
         reads_data=True, cost="scan"),
    Tool(REGULATORY, "Supervisory evidence coverage",
         "Which supervisory references this run evidences and where it did "
         "not. Not a compliance assessment.",
         SERVICE, parameters=("model_id",), required=("model_id",),
         reads_data=True, cost="scan"),
    Tool(DRAFT_REPORT, "Draft the validation report",
         "Assemble the validation report from results that already exist. "
         "Produces a draft for review; it does not issue anything.",
         SERVICE, parameters=("model_id",), required=("model_id",),
         reads_data=True, cost="scan"),
)

BY_ID: dict[str, Tool] = {t.tool_id: t for t in TOOLS}

#: What this agent has no tool for, and why. Published so the absence is
#: legible: a reader who wants to know whether the agent can run arbitrary
#: SQL should find the answer here rather than inferring it from silence.
NO_TOOL_FOR: dict[str, str] = {
    "arbitrary SQL or Python": (
        "There is no tool that accepts a query, an expression, a filter or a "
        "column list. The agent names a model and a test; the engine decides "
        "what that means."),
    "raw rows": (
        "The smallest thing any tool returns is a completed Result, which "
        "already carries its value, its limit and its verdict. Nothing is "
        "left for a language model to aggregate."),
    "changing a limit or a model": (
        "Limits are governed and versioned. An agent that could move one "
        "could turn a breach into a pass by asking."),
    "issuing a report or an opinion": (
        "The report tool produces a draft. Issuing it is a person's act."),
    "any dataset outside the three scorecards": (
        "Every tool reaches the engine through models.get or "
        "runner.population, both of which refuse a domain outside the "
        "three."),
}


class Clarify(Exception):
    """The request was not specific enough to run. Carries the question."""

    def __init__(self, question: str, options: list[dict[str, str]],
                 because: str = "") -> None:
        super().__init__(question)
        self.question = question
        self.options = options
        self.because = because

    def to_dict(self) -> dict[str, Any]:
        return {
            "clarification_required": True,
            "question": self.question,
            "options": self.options,
            "because": self.because or (
                "Answering without this would produce a correct number "
                "attached to the wrong thing, which reads as an answer."),
        }


def catalogue() -> dict[str, Any]:
    """What the agent can do, what it cannot, and why the gaps are gaps."""
    return {
        "agent_version": AGENT_VERSION,
        "agent_id": AGENT_ID,
        "name": AGENT_NAME,
        "scope": SCOPE,
        "out_of_scope": OUT_OF_SCOPE,
        "redirect_route": domains.REDIRECT_ROUTE,
        "tools": [t.to_dict() for t in TOOLS],
        "no_tool_for": NO_TOOL_FOR,
        "computes_nothing": (
            "Every number this agent can state came from "
            "backend/scorecard/metrics.py through the validation runner, and "
            "every pass or fail from comparing that number to a governed "
            "limit. The agent selects and explains; it does not calculate."),
    }


def _model(model_id: str) -> model_registry.Model:
    if not model_id:
        raise _which_scorecard()
    try:
        return model_registry.get(model_id)
    except domains.DomainRefused as e:
        raise ToolDenied(str(e)) from e


def _test(test_id: str) -> test_registry.Test:
    found = test_registry.resolve(test_id)
    if found is None:
        raise Clarify(
            f"There is no validation test called {test_id!r}. Which did you "
            "mean?",
            [{"test_id": t.test_id, "name": t.name, "category": t.category}
             for t in test_registry.TESTS
             if test_id.lower() in f"{t.test_id} {t.name}".lower()][:8]
            or [{"test_id": t.test_id, "name": t.name,
                 "category": t.category} for t in test_registry.TESTS[:8]],
            because=("Running an approximately-matching test and labelling "
                     "it with the requested name is how a report comes to "
                     "cite a measurement nobody took."))
    return found


def _check(tool: Tool, parameters: dict[str, Any]) -> dict[str, Any]:
    """Reject an unknown parameter rather than ignoring it.

    An ignored parameter is a caller who believes it did something. If a
    model asks for `RUN_TEST` with a `filter`, silently dropping it returns
    a portfolio number that will be quoted as a filtered one.
    """
    unknown = sorted(set(parameters) - set(tool.parameters))
    if unknown:
        raise ToolDenied(
            f"{tool.tool_id} does not accept {', '.join(unknown)}. It "
            f"accepts {', '.join(tool.parameters) or 'no parameters'}. A "
            "parameter this tool does not understand is a caller who thinks "
            "it does something it does not.")
    missing = [p for p in tool.required if not parameters.get(p)]
    if not missing:
        return parameters

    # A specific question beats a generic one. "Which scorecard? — here are
    # the three, with their portfolios" is answerable; "PERIODS needs
    # model_id" is a parameter name, and asking a person to supply one is
    # asking them to know the API.
    if "model_id" in missing:
        raise _which_scorecard()
    raise Clarify(
        f"{tool.name} needs {', '.join(missing)}.",
        [], because=f"{tool.tool_id} cannot run without it.")


def _which_scorecard() -> Clarify:
    return Clarify(
        "Which scorecard?",
        [{"model_id": m.model_id, "name": m.name, "portfolio": m.portfolio}
         for m in model_registry.all_models()],
        because=("Three scorecards are validated here and they have "
                 "different limits, different data and different weaknesses. "
                 "A number from the wrong one still looks like an answer."))


def _all_results(model: model_registry.Model) -> list[states.Result]:
    out: list[states.Result] = []
    for category in test_registry.CATEGORIES:
        out.extend(runner.run_category(category, model))
    return out


def invoke(tool_id: str, **parameters: Any) -> dict[str, Any]:
    """The only way in. There is no path that does not pass through here.

    An agent is never handed a callable — it is handed a tool id and a
    parameter document, and this function decides whether that pair is
    something the product permits. A tool this module has not defined cannot
    be constructed by asking for it differently.
    """
    tool = BY_ID.get(tool_id)
    if tool is None:
        raise ToolUnknown(
            f"{tool_id!r} is not a Scorecard Validation tool. The tools are: "
            f"{', '.join(sorted(BY_ID))}.")
    given = _check(tool, {k: v for k, v in parameters.items()
                          if v not in (None, "")})

    if tool_id == LIST_MODELS:
        return {"scorecards": [
            {**m.to_dict(),
             "applicable_tests": [t.test_id for t in m.applicable_tests()]}
            for m in model_registry.all_models()]}

    if tool_id == LIST_TESTS:
        category = given.get("category", "")
        wanted = (test_registry.in_category(category) if category
                  else test_registry.all_tests())
        if category and not wanted:
            raise Clarify(
                f"{category!r} is not a validation category.",
                [{"category": c,
                  "title": test_registry.BY_CATEGORY_KEY[c].title}
                 for c in test_registry.CATEGORIES])
        return {"category": category, "tests": [t.to_dict() for t in wanted]}

    if tool_id == EXPLAIN_TEST:
        found = _test(given["test_id"])
        return {"test": found.to_dict(),
                "cannot_tell_you": list(found.limitations)}

    model = _model(given.get("model_id", "")) if "model_id" in tool.required \
        else None

    if tool_id == PERIODS:
        assert model is not None
        matured = set(runner.matured_periods(model))
        available = runner.available_periods(model)
        return {
            "model_id": model.model_id,
            "performance_window_months": model.performance_window_months,
            "periods": [{"period": p, "matured": p in matured}
                        for p in available],
            "immature": [p for p in available if p not in matured],
            "what_immature_means": (
                "No realised outcome yet — which is not the same as no "
                "defaults. Every outcome test refuses these by name."),
        }

    if tool_id == RUN_TEST:
        assert model is not None
        found = _test(given["test_id"])
        result = runner.run(
            found.test_id, model,
            periods=tuple(p.strip() for p in
                          str(given.get("period", "")).split(",") if p.strip()),
            segment=given.get("segment", ""),
            segment_field=given.get("segment_field", ""))
        return {"test": found.to_dict(), "result": result.to_dict()}

    if tool_id == RUN_CATEGORY:
        assert model is not None
        category = given["category"]
        if category not in test_registry.CATEGORIES:
            raise Clarify(
                f"{category!r} is not a validation category.",
                [{"category": c,
                  "title": test_registry.BY_CATEGORY_KEY[c].title}
                 for c in test_registry.CATEGORIES])
        results = runner.run_category(
            category, model,
            periods=tuple(p.strip() for p in
                          str(given.get("period", "")).split(",") if p.strip()))
        return {"category": category,
                "results": [r.to_dict() for r in states.rank(results)],
                "tally": states.tally(results)}

    if tool_id == FINDINGS:
        assert model is not None
        results = _all_results(model)
        assessed = finding_engine.assess(results, model)
        return {
            "model_id": model.model_id,
            "findings": [f.to_dict() for f in assessed],
            "burning_weaknesses": [
                f.to_dict() for f in finding_engine.burning(assessed)],
            "summary": finding_engine.summary(assessed),
        }

    if tool_id == REGULATORY:
        assert model is not None
        return regulatory_map.coverage(_all_results(model))

    if tool_id == DRAFT_REPORT:
        assert model is not None
        made = report_studio.build(model, _all_results(model))
        return {**made.to_dict(),
                "this_is_a_draft": (
                    "This is a draft, assembled from results that already "
                    "exist. Issuing it is a person's act, and this tool "
                    "cannot.")}

    raise ToolUnknown(  # pragma: no cover - unreachable by construction
        f"{tool_id} is registered and has no implementation")


def refuse_out_of_domain(question: str) -> dict[str, Any]:
    """What to say when the question is not about these three scorecards.

    Says where the answer lives rather than only that this is the wrong
    place. A refusal that leaves somebody stuck is a refusal they route
    around.
    """
    return {
        "refused": True,
        "why": OUT_OF_SCOPE,
        "scope": SCOPE,
        "where_instead": domains.REDIRECT_SENTENCE,
        "route": domains.REDIRECT_ROUTE,
        "question": question,
    }


__all__ = [
    "AGENT_ID", "AGENT_NAME", "AGENT_VERSION", "BY_ID", "DRAFT_REPORT",
    "EXPLAIN_TEST", "FINDINGS", "LIST_MODELS", "LIST_TESTS", "NO_TOOL_FOR",
    "OUT_OF_SCOPE", "PERIODS", "REGULATORY", "RUN_CATEGORY", "RUN_TEST",
    "SCOPE", "TOOLS", "Clarify", "catalogue", "invoke",
    "refuse_out_of_domain",
]
